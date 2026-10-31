#!/usr/bin/env python3
"""Step 18: read a call from chart screenshots when the ticker is not in the text. Owner-only, local.

  .venv/bin/python tools/read_images.py URL      (needs pillow + numpy: python3 -m venv --system-site-packages .venv;
                                                 .venv/bin/pip install pillow==11.3.0 numpy==2.3.4)

1 collect   the post's images and the images of the post it replies to or quotes (X's public embed
            data; originals from pbs.twimg.com), saved as sources/<author>/media/<post>_<n>.<ext> with
            sha256; the context post's receipt is saved too. Nothing is hotlinked by the site.
2 read      OCR of every image (tesseract.js through the research harness, cached beside the image
            with the image sha256), then:
              titles     detect/image_names.json (fund / chart titles -> asset; every word must be there)
              tickers    words in the OCR text that are known assets (resolve.ASSETS)
              words      the asset detector (detect.py) on the OCR text
              labels     price labels (numbers with 2-4 decimals)
3 crop      is the post's image a crop of a context image? multi-scale normalized cross-correlation
            (score >= 0.70 = crop), plus the price labels both images share
4 price     for each candidate asset, the price at post time (last bar at or before the post) and,
            for each label in the post's own image: within 3% = "near the price at post time",
            else how far away, and whether it matches a daily low / high of the last 2 years
5 decide    never sets a side. A label far from the price, a joke marker, or support / resistance
            words with a far label mark the post as possible sarcasm / a target level. The result is
            always status needs_review with a confidence; tools/add_call.py adds it only with
            --asset, --side and a written --reason, and records this evidence file and its sha256.
Output: intake/images/<post>.json and .md
"""
import datetime as dt
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request

TOOLS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TOOLS)
sys.path[:0] = [HERE, TOOLS]
import detect  # noqa: E402
import ingest  # noqa: E402
import resolve  # noqa: E402

VERSION = "quanty.images.v1"
XR = os.environ.get("XR_DIR", "/home/postfiat/xresearch-kit/tools/xresearch")
NAMES = os.path.join(HERE, "detect", "image_names.json")
CROP_MIN = 0.70
NEAR = 0.03
LABEL = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d{1,6})\.(\d{2,4})(?![\d.])")     # 6.8900, 74.10, 77,405.98
SARCASM_WORDS = re.compile(r"\b(?:solid|strong|great|nice|perfect)\s+(?:support|resistance|entry|bottom|base)\b|\bsupport here\b|\bbottom is in\b", re.I)
JOKE = re.compile(r"\b(?:lol|lmao|jk|kidding)\b|😂|🤣|(?:^|\s)/s\b", re.I)


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# 1 collect ---------------------------------------------------------------------------------------
def media_urls(data):
    out = []
    for m in (data or {}).get("mediaDetails") or []:
        u = m.get("media_url_https") or ""
        if m.get("type", "photo") == "photo" and u.startswith("https://pbs.twimg.com/media/"):
            base, ext = u.rsplit(".", 1)
            out.append((f"{base}?format={ext}&name=orig", ext))
    return out


def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        if r.headers.get_content_type() not in ("image/jpeg", "image/png", "image/webp"):
            raise ingest.IngestError(f"{url}: not an image ({r.headers.get_content_type()})")
        blob = r.read()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(blob)
    return path


def collect(url, root=HERE, fetch=ingest.fetch_embed, get=download):
    m = resolve.URL_RE.match(url or "")
    if not m:
        raise ingest.IngestError(f"not a post url: {url!r}")
    data = fetch(m.group(2))
    rpath, receipt, _ = ingest.ingest(url, fetch=lambda pid: data, root=root)
    posts = [("post", receipt, data)]
    for role, cid in (("reply_to", data.get("in_reply_to_status_id_str")), ("quote", (data.get("quoted_tweet") or {}).get("id_str"))):
        if not cid:
            continue
        cdata = fetch(cid)
        curl = f"https://x.com/{cdata['user']['screen_name']}/status/{cid}"
        _, creceipt, _ = ingest.ingest(curl, fetch=lambda pid, d=cdata: d, root=root)
        posts.append((role, creceipt, cdata))
    out = []
    for role, rec, d in posts:
        imgs = []
        for n, (u, ext) in enumerate(media_urls(d)):
            path = os.path.join(root, "sources", rec["authorHandle"].lower(), "media", f"{rec['id']}_{n}.{ext}")
            if not os.path.exists(path):
                get(u, path)
            imgs.append({"file": os.path.relpath(path, root), "sha256": sha256_file(path), "source": u.split("?")[0]})
        out.append({"role": role, "id": rec["id"], "author": rec["authorHandle"], "url": rec["url"], "posted_at": rec["postedAt"][:19] + "Z",
                    "text": rec.get("text") or "", "receipt": os.path.relpath(glob.glob(os.path.join(root, "sources", "*", "receipts", f"{rec['id']}.json"))[0], root),
                    "images": imgs})
    return out


# 2 read ------------------------------------------------------------------------------------------
def harness_ocr(path):
    env = dict(os.environ, PATH=os.path.expanduser("~/.local/node24/bin") + ":" + os.environ.get("PATH", ""))
    r = subprocess.run(["timeout", "180", "npm", "run", "-s", "xr", "--", "media", "ocr", os.path.abspath(path)], cwd=XR, env=env, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"ocr failed for {path}: {(r.stdout + r.stderr)[-400:]}")
    return r.stdout.strip()


def ocr(path, root=HERE, engine=harness_ocr):
    """OCR text, cached beside the image (keyed by the image sha256)."""
    full = os.path.join(root, path)
    cache = full + ".ocr.json"
    sha = sha256_file(full)
    if os.path.exists(cache):
        with open(cache) as f:
            c = json.load(f)
        if c.get("image_sha256") == sha:
            return c["text"]
    text = engine(full)
    with open(cache, "w") as f:
        json.dump({"image_sha256": sha, "engine": "tesseract.js (x-research harness: media ocr)", "text": text}, f, indent=1, ensure_ascii=False)
        f.write("\n")
    return text


def names():
    with open(NAMES) as f:
        return json.load(f)["titles"]


def read_text(text):
    low = (text or "").lower()
    titles = []
    for title, asset in sorted(names().items(), key=lambda kv: -len(kv[0])):
        words = re.findall(r"[a-z0-9&]+", title.lower())
        if words and all(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", low) for w in words):
            if not any(t["asset"] == asset for t in titles):
                titles.append({"title": title, "asset": asset})
    tickers = sorted({w for w in re.findall(r"\$?\b([A-Z]{2,6})\b", text or "") if w in resolve.ASSETS})
    words = sorted({m["asset"] for m in detect.detect(text or "")["matched"]})
    labels = sorted({float(w.replace(",", "") + "." + f) for w, f in LABEL.findall(text or "")})
    return {"titles": titles, "tickers": tickers, "words": words, "labels": labels}


# 3 crop ------------------------------------------------------------------------------------------
def crop_match(child, parent, width=360):
    """Best normalized cross-correlation of `child` inside `parent` over scales -> {score, box}."""
    import numpy as np
    from PIL import Image
    P, C = Image.open(parent).convert("L"), Image.open(child).convert("L")
    k = width / P.width
    A = np.asarray(P.resize((width, max(1, round(P.height * k))), Image.BILINEAR), dtype=np.float64)
    H, W = A.shape
    S1 = np.pad(A, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    S2 = np.pad(A * A, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    FA = None
    best = {"score": -1.0}
    for s in np.arange(0.15, 1.61, 0.05):
        cw, ch = round(C.width * s), round(C.height * s)
        if cw < 12 or ch < 8 or cw > W or ch > H:
            continue
        T = np.asarray(C.resize((cw, ch), Image.BILINEAR), dtype=np.float64)
        T = T - T.mean()
        tn = np.sqrt((T * T).sum())
        if tn < 1e-6:
            continue
        # correlation of A with T at every offset (FFT), normalized by the window's own variance
        shape = (H + ch, W + cw)
        FA = np.fft.rfft2(A, shape)
        corr = np.fft.irfft2(FA * np.conj(np.fft.rfft2(T, shape)), shape)[:H - ch + 1, :W - cw + 1]
        win = lambda S: S[ch:, cw:][:H - ch + 1, :W - cw + 1] - S[:-ch, cw:][:H - ch + 1, :W - cw + 1] - S[ch:, :-cw][:H - ch + 1, :W - cw + 1] + S[:-ch, :-cw][:H - ch + 1, :W - cw + 1]
        n = cw * ch
        var = np.maximum(win(S2) - win(S1) ** 2 / n, 1e-6)
        score = corr / (np.sqrt(var) * tn)
        y, x = np.unravel_index(np.argmax(score), score.shape)
        if score[y, x] > best["score"]:
            best = {"score": float(score[y, x]), "box": [round(x / k), round(y / k), round(cw / k), round(ch / k)]}
    best["crop"] = best["score"] >= CROP_MIN
    return best


# 4 price -----------------------------------------------------------------------------------------
def price_at(asset, when, prices):
    series = prices.series(asset, (resolve.parse(when) - dt.timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    before = [b for b in series if b[0] <= when]
    return (before[-1] if before else None), series


def extremes(asset, when, history):
    """Daily lows / highs of the 2 years before the post: [(date, low, high)]."""
    return history(asset, when)


def yahoo_daily(asset, when):
    if asset["source"] != "yahoo":
        return []
    end = resolve.parse(when)
    bars = resolve.yahoo_chart(asset["symbol"], end - dt.timedelta(days=730), end, "1d")
    return [(b[0][:10], b[3], b[2]) for b in bars]


def check_labels(labels, asset, when, prices, history=yahoo_daily):
    bar, _ = price_at(asset, when, prices)
    if not bar:
        return {"asset": asset["name"], "price_at_post": None, "labels": []}
    px = bar[1]
    days = extremes(asset, when, history)
    out = []
    for lab in labels:
        d = (lab - px) / px
        row = {"label": lab, "vs_price": d, "near": abs(d) <= NEAR}
        if days and lab > 0:
            # the nearest daily low / high of the 2 years before the post: "matches" within 1%, else "nearest"
            # (chart sites and Yahoo adjust history differently, so a few % apart is still worth showing)
            lo = min(days, key=lambda x: min(abs(x[1] - lab), abs(x[2] - lab)))
            which = "low" if abs(lo[1] - lab) <= abs(lo[2] - lab) else "high"
            val = lo[1] if which == "low" else lo[2]
            row["nearest_daily"] = {"date": lo[0], "which": which, "value": val, "label_vs_it": (lab - val) / val, "matches": abs(lab - val) / val <= 0.01}
        out.append(row)
    return {"asset": asset["name"], "price_at_post": {"at": bar[0], "price": px}, "labels": out}


# 5 decide ----------------------------------------------------------------------------------------
def analyse(url, root=HERE, fetch=ingest.fetch_embed, get=download, ocr_engine=harness_ocr, prices=None, history=yahoo_daily, now=None):
    posts = collect(url, root, fetch, get)
    post = posts[0]
    for p in posts:
        for im in p["images"]:
            im["ocr"] = ocr(im["file"], root, ocr_engine)
            im["read"] = read_text(im["ocr"])
    own = [im for im in post["images"]]
    ctx = [im for p in posts[1:] for im in p["images"]]
    crops = []
    for a in own:
        for b in ctx:
            cm = crop_match(os.path.join(root, a["file"]), os.path.join(root, b["file"]))
            shared = sorted(set(a["read"]["labels"]) & set(b["read"]["labels"]))
            crops.append({"post_image": a["file"], "context_image": b["file"], **cm, "shared_labels": shared})
    # candidates: post text first, then the post's images, then context images it is a crop of, then any context image
    cands = {}
    def add(asset, why):
        cands.setdefault(asset, []).append(why)
    for a in detect.detect(post["text"])["matched"]:
        add(a["asset"], f"post text: '{a['term']}'")
    for im in own:
        for t in im["read"]["titles"]:
            add(t["asset"], f"title in the post's image: '{t['title']}'")
        for t in im["read"]["tickers"]:
            add(t, f"ticker in the post's image: {t}")
    for p in posts[1:]:
        for im in p["images"]:
            is_crop = any(c["context_image"] == im["file"] and c["crop"] for c in crops)
            src = f"{p['role']} post's image" + (" (the post's image is a crop of it)" if is_crop else "")
            for t in im["read"]["titles"]:
                add(t["asset"], f"title in the {src}: '{t['title']}'")
            for t in im["read"]["tickers"]:
                add(t, f"ticker in the {src}: {t}")
        for a in detect.detect(p["text"])["matched"]:
            add(a["asset"], f"{p['role']} post text: '{a['term']}'")
    prices = prices or resolve.Prices()
    own_labels = sorted({x for im in own for x in im["read"]["labels"]})
    checks = []
    for asset in cands:
        try:
            info = resolve.asset_info(asset)
            checks.append(check_labels(own_labels, info, post["posted_at"], prices, history))
        except resolve.ResolveError as e:
            checks.append({"asset": asset, "error": str(e)})
    flags = []
    if JOKE.search(post["text"]):
        flags.append("joke marker in the post text")
    far = [l for c in checks for l in c.get("labels", []) if not l["near"]]
    if SARCASM_WORDS.search(post["text"]) and far:
        flags.append(f"support / resistance words ('{SARCASM_WORDS.search(post['text']).group(0)}') with a price label "
                     f"{far[0]['label']} that is {far[0]['vs_price'] * 100:+.1f}% from the price at post time: sarcasm or a target level, not an entry")
    elif far and not any(l["near"] for c in checks for l in c.get("labels", [])):
        flags.append("no price label in the post's image is near the price at post time: a historical or target level")
    best = sorted(cands, key=lambda a: -len(cands[a]))
    top = best[0] if best else None
    strong = top and any("title" in w for w in cands[top]) and any(c["crop"] for c in crops)
    confidence = "none" if not top else "high" if strong and len(best) == 1 else "medium" if len(best) == 1 or strong else "low"
    out = {"version": VERSION, "url": post["url"], "post_id": post["id"], "author": post["author"], "posted_at": post["posted_at"],
           "analysed_at": now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "posts": posts, "crop_matches": crops, "candidates": [{"asset": a, "evidence": cands[a]} for a in best], "price_checks": checks,
           "flags": flags, "asset_suggested": top, "confidence": confidence, "side": None,
           "side_note": "never set from an image or a joke: the owner decides with a written reason (tools/add_call.py --asset --side --reason)",
           "status": "needs_review" if top else "no_asset"}
    d = os.path.join(root, "intake", "images")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{post['id']}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write("\n")
    with open(os.path.join(d, f"{post['id']}.md"), "w") as f:
        f.write(to_md(out))
    out["evidence_file"] = os.path.relpath(path, root)
    out["evidence_sha256"] = sha256_file(path)
    return out


def to_md(e):
    L = [f"# Image evidence: {e['url']} (not published)", "", f"@{e['author']} · {e['posted_at']} · status **{e['status']}** · confidence **{e['confidence']}** · side: none (owner decides)", ""]
    for p in e["posts"]:
        L.append(f"## {p['role']}: {p['url']}")
        L.append(f"Text: “{' '.join(p['text'].split())[:280]}”")
        for im in p["images"]:
            r = im["read"]
            L.append(f"- `{im['file']}` sha256 `{im['sha256']}`")
            L.append(f"  - titles {[t['title'] + ' -> ' + t['asset'] for t in r['titles']]}, tickers {r['tickers']}, asset words {r['words']}, labels {r['labels']}")
            L.append(f"  - OCR: “{' '.join(im['ocr'].split())[:300]}”")
        L.append("")
    L.append("## Crop match")
    for c in e["crop_matches"]:
        L.append(f"- `{c['post_image']}` in `{c['context_image']}`: score {c['score']:.3f} ({'a crop' if c['crop'] else 'not a crop'}), box {c.get('box')}, shared labels {c['shared_labels']}")
    L += ["", "## Candidates"] + [f"- {c['asset']}: {'; '.join(c['evidence'])}" for c in e["candidates"]]
    L += ["", "## Price at post time"]
    for c in e["price_checks"]:
        if c.get("error"):
            L.append(f"- {c['asset']}: {c['error']}")
            continue
        pp = c["price_at_post"]
        L.append(f"- {c['asset']}: {pp['price'] if pp else '–'} @ {pp['at'] if pp else '–'}")
        for l in c["labels"]:
            md = l.get("nearest_daily")
            L.append(f"  - label {l['label']}: {l['vs_price'] * 100:+.1f}% from the price at post time ({'near' if l['near'] else 'far'})"
                     + (f"; {'matches' if md['matches'] else 'nearest'} daily {md['which']} of the 2 years before: {md['value']} on {md['date']} ({md['label_vs_it'] * 100:+.1f}%)" if md else ""))
    L += ["", "## Flags"] + [f"- {x}" for x in e["flags"] or ["none"]]
    L += ["", f"Suggested asset: **{e['asset_suggested']}** · {e['side_note']}"]
    return "\n".join(L) + "\n"


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    e = analyse(sys.argv[1])
    print(f"post      {e['url']} @{e['author']} {e['posted_at']}")
    for p in e["posts"]:
        for im in p["images"]:
            r = im["read"]
            print(f"{p['role']:<9} {im['file']} sha256 {im['sha256']}")
            print(f"          titles {[t['title'] for t in r['titles']]} tickers {r['tickers']} labels {r['labels']}")
    for c in e["crop_matches"]:
        print(f"crop      {c['post_image']} in {c['context_image']}: score {c['score']:.3f} -> {'CROP' if c['crop'] else 'no'}; shared labels {c['shared_labels']}")
    for c in e["candidates"]:
        print(f"candidate {c['asset']}: {'; '.join(c['evidence'])}")
    for c in e["price_checks"]:
        for l in c.get("labels", []):
            md = l.get("nearest_daily")
            print(f"price     {c['asset']} at post {c['price_at_post']['price']} @ {c['price_at_post']['at']}: label {l['label']} {l['vs_price'] * 100:+.1f}%"
                  + (f"; {'matches' if md['matches'] else 'nearest'} daily {md['which']} (2 yrs before): {md['value']} on {md['date']} ({md['label_vs_it'] * 100:+.1f}%)" if md else ""))
    for fl in e["flags"]:
        print(f"flag      {fl}")
    print(f"result    {e['status']}: asset {e['asset_suggested']} (confidence {e['confidence']}), side not set")
    print(f"evidence  {e['evidence_file']} sha256 {e['evidence_sha256']}")
    print("NOTHING ADDED: add only after review, with tools/add_call.py --asset --side --reason.")


if __name__ == "__main__":
    main()
