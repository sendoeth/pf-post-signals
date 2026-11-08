#!/usr/bin/env python3
"""Step 29: read a reply or a quote with the post it answers. Owner-side tooling: nothing here writes a record.

usage: python3 tools/parents.py walk <post id>      (fetch + store the context, print it)
       python3 tools/parents.py show <post id>      (the stored context and its candidates, offline)
       python3 tools/parents.py potential          (data/potential_callers.json from every stored context)
       python3 tools/parents.py promote <handle>   (owner: a listed potential caller is watched, still unscored)

1 walk      From the caller's post, follow the reply link (else the quoted post) through X's public embed, the same
            data ingest.py uses. Each post is checked like a receipt (the embed returns the asked id, its time is the
            id's time, the author is named). Bounded: MAX_DEPTH parents, embed bodies and images read with a byte
            cap, MAX_IMAGES per post and in total, a pixel cap before OCR, a deadline for the whole walk.
            Status: complete (a post with no parent was reached: that post is the root), or one that gives NO
            context: truncated (MAX_DEPTH reached; the last post fetched is not called the root), cycle,
            unavailable (deleted, protected, an HTTP error, an integrity mismatch), over_budget (the deadline).
            Each post counts on its own (usable_roles): the direct parent whenever the walk read it in full, the root
            only on a complete walk; a text the embed cuts short and images that could not all be saved give nothing.
2 store     sources/context/<caller id>.json: the caller post and the root (and the direct parent when it is not the
            root) as standard receipts (sources/<author>/receipts/), every post of the chain as id / author / time /
            link / text sha256, every image saved as sources/<author>/media/<post>_<n>.<ext> with its sha256 and
            size. A pin (sha256 over all of it) is checked on every read; a stored context is never rewritten.
3 candidates Assets the parent and the root name, in their text (detect.coin_legs, offline) or their images (the
            step 18 reader: OCR, chart titles, tickers, asset words), each labelled parent_text / parent_image /
            root_text / root_image with its evidence. A candidate has no side: a side comes only from the
            caller's own words (reader.read_in_context).
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

TOOLS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TOOLS)
sys.path[:0] = [HERE, TOOLS]
import detect  # noqa: E402
import ingest  # noqa: E402
import read_images  # noqa: E402
import tickers  # noqa: E402

VERSION = "quanty.context.v1"
MAX_DEPTH = 4                      # parents followed from the caller's post
MAX_IMAGES_PER_POST = 4
MAX_IMAGES = 8                     # images saved for one context
MAX_EMBED_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 40_000_000            # decoded size checked before OCR
WALK_SECONDS = 90                  # the whole walk (fetches and downloads)
OCR_SECONDS = 90                   # one image
CONTEXT_STATUSES_WITH_CANDIDATES = ("complete",)
ROLES = ("parent", "root")


class Unavailable(Exception):
    """A post of the chain cannot be read (deleted, protected, HTTP error, integrity mismatch)."""


class OverBudget(Exception):
    """A byte, pixel, count or time cap was reached."""


class Integrity(Exception):
    """A stored context no longer matches its pin."""


def utcnow():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


# ---- fetching, bounded -----------------------------------------------------------------------------
def read_capped(resp, cap, what):
    blob = resp.read(cap + 1)
    if len(blob) > cap:
        raise OverBudget(f"{what} is over {cap} bytes")
    return blob


def fetch_embed(pid):
    """ingest.fetch_embed with a byte cap on the body."""
    req = urllib.request.Request(ingest.EMBED.format(id=pid, token=ingest.embed_token(pid)), headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = read_capped(resp, MAX_EMBED_BYTES, f"embed of {pid}")
    except urllib.error.HTTPError as e:
        raise Unavailable(f"post {pid} unavailable (embed HTTP {e.code}: deleted, private or never existed)") from e
    except urllib.error.URLError as e:
        raise Unavailable(f"post {pid} unavailable ({e.reason})") from e
    if not body.strip():
        raise Unavailable(f"post {pid} unavailable (empty embed response)")
    return json.loads(body)


def download(url, path):
    """An image, streamed with a byte cap; only jpeg / png / webp."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        if r.headers.get_content_type() not in ("image/jpeg", "image/png", "image/webp"):
            raise Unavailable(f"{url}: not an image ({r.headers.get_content_type()})")
        blob = read_capped(r, MAX_IMAGE_BYTES, url)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "wb") as f:
        f.write(blob)
    os.replace(path + ".tmp", path)
    return path


def post(pid, fetch):
    """-> (receipt-like dict, raw embed data). Integrity as ingest.to_receipt; any failure -> Unavailable."""
    try:
        data = fetch(pid)
    except (Unavailable, OverBudget):
        raise
    except ingest.IngestError as e:
        raise Unavailable(str(e)) from e
    if not isinstance(data, dict) or data.get("__typename") == "TweetTombstone" or not data.get("id_str"):
        reason = ((data or {}).get("tombstone") or {}).get("text", {}).get("text") if isinstance(data, dict) else None
        raise Unavailable(f"post {pid} unavailable ({reason or 'no post data'})")
    author = ((data.get("user") or {}).get("screen_name") or "")
    if not author:
        raise Unavailable(f"post {pid}: no author in the embed")
    try:
        receipt = ingest.to_receipt(f"https://x.com/{author}/status/{pid}", data, utcnow()[:19] + ".000Z")
    except ingest.IngestError as e:
        raise Unavailable(str(e)) from e
    return receipt, data


def link_of(data):
    """The post this one answers: ("reply", id, handle) first, else ("quote", id, handle), else None."""
    if data.get("in_reply_to_status_id_str"):
        return "reply", str(data["in_reply_to_status_id_str"]), data.get("in_reply_to_screen_name")
    q = data.get("quoted_tweet")
    if isinstance(q, dict) and q.get("id_str"):
        return "quote", str(q["id_str"]), (q.get("user") or {}).get("screen_name")
    return None


def walk(pid, fetch=fetch_embed, max_depth=MAX_DEPTH, clock=time.monotonic, seconds=WALK_SECONDS):
    """-> (caller (receipt, data), [(receipt, data, link the previous post used)], status, reason)."""
    start = clock()
    caller = post(pid, fetch)                                   # the caller's own post must be readable
    if clock() - start > seconds:
        return caller, [], "over_budget", f"walk took over {seconds} s"
    nodes, seen, nxt = [], {str(pid)}, link_of(caller[1])
    while nxt:
        kind, cid, handle = nxt
        if cid in seen:
            return caller, nodes, "cycle", f"post {cid} links back into the chain"
        if len(nodes) >= max_depth:
            return caller, nodes, "truncated", f"more than {max_depth} parents: the root is not known"
        if clock() - start > seconds:
            return caller, nodes, "over_budget", f"walk took over {seconds} s"
        try:
            rec, data = post(cid, fetch)
        except Unavailable as e:
            return caller, nodes, "unavailable", str(e)
        except OverBudget as e:
            return caller, nodes, "over_budget", str(e)
        if clock() - start > seconds:
            return caller, nodes, "over_budget", f"walk took over {seconds} s"
        if handle and rec["authorHandle"].lower() != handle.lower():
            return caller, nodes, "unavailable", f"post {cid} is by @{rec['authorHandle']}, the link said @{handle}"
        seen.add(cid)
        nodes.append((rec, data, kind))
        nxt = link_of(data)
    return caller, nodes, "complete", None


# ---- storing -------------------------------------------------------------------------------------
def context_path(pid, root=HERE):
    return os.path.join(root, "sources", "context", f"{pid}.json")


def stored(rec, root):
    """The receipt as stored (an existing one wins over the fresh fetch), its path and the sha256 of its bytes."""
    rel = save_receipt(rec, root)
    with open(os.path.join(root, rel), "rb") as f:
        blob = f.read()
    return json.loads(blob), rel, sha(blob)


def save_receipt(rec, root):
    """The standard receipt (ingest's layout); an existing one is kept as it is."""
    path = os.path.join(root, "sources", rec["authorHandle"].lower(), "receipts", f"{rec['id']}.json")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w") as f:
            json.dump(rec, f, indent=1, ensure_ascii=False)
            f.write("\n")
        os.replace(path + ".tmp", path)
    return os.path.relpath(path, root)


def save_images(rec, data, root, get, budget, deadline=lambda: False):
    out = []
    for n, (url, ext) in enumerate(read_images.media_urls(data)[:MAX_IMAGES_PER_POST]):
        if deadline():
            raise OverBudget(f"the walk deadline ({WALK_SECONDS} s) passed before image {n} of {rec['id']}")
        if budget[0] <= 0:
            raise OverBudget(f"more than {MAX_IMAGES} images in the chain")
        budget[0] -= 1
        path = os.path.join(root, "sources", rec["authorHandle"].lower(), "media", f"{rec['id']}_{n}.{ext}")
        if not os.path.exists(path):
            get(url, path)
            if deadline():
                raise OverBudget(f"the walk deadline ({WALK_SECONDS} s) passed while image {n} of {rec['id']} was downloaded")
        with open(path, "rb") as f:
            blob = f.read()
        out.append({"file": os.path.relpath(path, root), "sha256": sha(blob), "bytes": len(blob), "source": url.split("?")[0]})
    return out


def view(rec, kind=None):
    return {"id": rec["id"], "url": rec["url"], "author": rec["authorHandle"], "posted_at": rec["postedAt"][:19] + "Z",
            "text": rec.get("text") or "", "text_sha256": sha(rec.get("text") or ""), "link": kind}


def pin_of(doc):
    """sha256 over everything that says what the context is (all but the pin and the fetch time)."""
    body = {k: v for k, v in doc.items() if k not in ("pin_sha256", "walked_at")}
    return sha(json.dumps(body, sort_keys=True, ensure_ascii=False))


def build(pid, root=HERE, fetch=fetch_embed, get=download, now=utcnow, ocr_engine=None, clock=time.monotonic, seconds=WALK_SECONDS, **kw):
    """Walk, save receipts and images, OCR the images, write sources/context/<pid>.json; an existing context is
    returned (verified). The deadline covers the fetches and the downloads; OCR has its own per-image limit."""
    path = context_path(pid, root)
    if os.path.exists(path):
        return load(pid, root)
    start = clock()
    caller, nodes, status, reason = walk(pid, fetch, clock=clock, seconds=seconds, **kw)
    ocr_engine = ocr_engine or (lambda full: read_images.ocr(os.path.relpath(full, root), root=root, engine=capped_ocr))
    budget = [MAX_IMAGES]
    crec, crel, csha = stored(caller[0], root)
    doc = {"schema": VERSION, "caller": dict(view(crec), receipt=crel, receipt_sha256=csha), "status": status, "reason": reason,
           "chain": [{"id": r["id"], "author": r["authorHandle"], "posted_at": r["postedAt"][:19] + "Z", "link": k,
                      "text_sha256": sha(r.get("text") or "")} for r, _, k in nodes],
           "limits": {"max_depth": MAX_DEPTH, "max_images": MAX_IMAGES, "max_image_bytes": MAX_IMAGE_BYTES}}
    keep = []
    if nodes:
        keep.append(("parent", nodes[0]))
        if status == "complete" and len(nodes) > 1:
            keep.append(("root", nodes[-1]))
    for role, (rec, data, kind) in keep:
        srec, rel, rsha = stored(rec, root)
        v = dict(view(srec, kind), receipt=rel, receipt_sha256=rsha, text_truncated=bool(srec.get("textTruncated")))
        try:
            v["images"] = save_images(rec, data, root, get, budget, deadline=lambda: clock() - start > seconds)
        except (OverBudget, Unavailable, urllib.error.URLError, OSError) as e:
            v["images"], v["images_error"] = [], f"{type(e).__name__}: {e}"[:300]
        for img in v["images"]:                    # the OCR text is part of the pinned context: never read from a cache file
            try:
                check_pixels(os.path.join(root, img["file"]))
                text = ocr_engine(os.path.join(root, img["file"]))
                img["ocr"] = {"text": text, "sha256": sha(text)}
            except (OverBudget, RuntimeError, OSError) as e:
                img["ocr"] = {"error": f"{type(e).__name__}: {e}"[:300]}
        doc[role] = v
    if status == "complete" and len(nodes) == 1:
        doc["root_is_parent"] = True
    doc["walked_at"] = now()
    doc["pin_sha256"] = pin_of(doc)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(path + ".tmp", path)
    return doc


def load(pid, root=HERE):
    """A stored context, verified: its pin, every receipt's text, every image's bytes."""
    with open(context_path(pid, root)) as f:
        doc = json.load(f)
    if pin_of(doc) != doc.get("pin_sha256"):
        raise Integrity(f"context {pid}: the stored context does not match its pin")
    for role in ("caller",) + ROLES:
        v = doc.get(role)
        if not v:
            continue
        with open(os.path.join(root, v["receipt"]), "rb") as f:
            blob = f.read()
        rec = json.loads(blob)
        if (sha(blob) != v.get("receipt_sha256") or rec["id"] != v["id"] or rec["authorHandle"] != v["author"]
                or sha(rec.get("text") or "") != v["text_sha256"]):
            raise Integrity(f"context {pid}: receipt {v['receipt']} does not match the context")
        for img in v.get("images") or []:
            with open(os.path.join(root, img["file"]), "rb") as f:
                if sha(f.read()) != img["sha256"]:
                    raise Integrity(f"context {pid}: image {img['file']} changed")
            o = img.get("ocr") or {}
            if "text" in o and sha(o["text"]) != o.get("sha256"):
                raise Integrity(f"context {pid}: OCR text of {img['file']} changed")
    return doc


def usable_roles(doc):
    """The posts candidates may come from, each failing closed on its own:
      parent  the direct parent, read in full by the walk (whatever happened further up the chain)
      root    only when the walk reached a post with no parent (status complete): a truncated, cyclic or
              unavailable chain has no known root, and the last post fetched is never called one
    A post whose images could not all be saved gives no image candidates (its text still counts)."""
    out = []
    for role, v in roles(doc):
        if role == "root" and doc.get("status") not in CONTEXT_STATUSES_WITH_CANDIDATES:
            continue
        out.append((role, v))
    return out


def roles(doc):
    """The posts whose words count as context: the parent, and the root when it is another post."""
    out = [("parent", doc["parent"])] if doc.get("parent") else []
    if doc.get("root") and doc["root"]["id"] != (doc.get("parent") or {}).get("id"):
        out.append(("root", doc["root"]))
    return out


# ---- candidates ------------------------------------------------------------------------------------
class OfflineNet(tickers.Net):
    def get(self, url):
        raise tickers.Unavailable("context candidates never look up new tickers")


def check_pixels(path):
    from PIL import Image
    with Image.open(path) as im:
        w, h = im.size
    if w * h > MAX_PIXELS:
        raise OverBudget(f"{path}: {w}x{h} is over {MAX_PIXELS} pixels")


def capped_ocr(path):
    """The step 18 OCR, after a pixel cap; the harness call is limited to OCR_SECONDS."""
    check_pixels(path)
    import subprocess
    env = dict(os.environ, PATH=os.path.expanduser("~/.local/node24/bin") + ":" + os.environ.get("PATH", ""))
    r = subprocess.run(["timeout", str(OCR_SECONDS), "npm", "run", "-s", "xr", "--", "media", "ocr", os.path.abspath(path)],
                       cwd=read_images.XR, env=env, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"ocr failed for {path}: {(r.stdout + r.stderr)[-300:]}")
    return r.stdout.strip()


def registry_tickers(text, reg):
    """Capitalised words in an image's text that are registered coins (step 22 registry): a wrapped copy is its
    underlying coin (UBTC -> BTC), stablecoins never count, and a ticker that is a common English word
    (detect's bare_blocked list) is not read from an image either."""
    import re
    w = detect.coin_words()
    wrapped = {k.upper(): v for k, v in (w.get("wrapped") or {}).items()}
    stable = {x.upper() for x in w.get("stablecoins") or []}
    blocked = {x.upper() for x in w.get("bare_blocked") or []}
    out = []
    for word in sorted(set(re.findall(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]{1,9}(?![A-Za-z0-9])", text or ""))):
        asset = wrapped.get(word, word)
        if word in stable or asset in stable or word in blocked or asset not in reg.get("tickers", {}):
            continue
        out.append((asset, word))
    return out


def excerpt(text, word, width=60):
    low, i = (text or "").lower(), (text or "").lower().find(word.lower())
    if i < 0:
        return None
    return " ".join(text[max(0, i - width // 2): i + len(word) + width // 2].split())


def candidates(doc, root=HERE, ocr_engine=None, registry=None):
    """-> [{"asset", "sources": [{"source", "post_id", "author", "evidence"}]}]: assets the context names, no sides.
    Offline and from the pinned context only (its texts and the OCR text stored with each image): nothing is read
    from a cache file. Each post fails closed on its own (usable_roles); an image without OCR is listed, not guessed.
    (`ocr_engine` is accepted for older callers and ignored.)"""
    reg = registry or tickers.load_registry()
    found = {}

    def add(asset, source, v, evidence):
        found.setdefault(asset, []).append({"source": source, "post_id": v["id"], "author": v["author"], "evidence": evidence})

    for role, v in usable_roles(doc):
        if v.get("text_truncated"):
            add(None, f"{role}_text", v, {"unread": "the embed cuts this post's text short: its words are not used"})
            continue_text = False
        else:
            continue_text = True
        for leg in (detect.coin_legs(v["text"], net=OfflineNet(), registry=reg) if continue_text else []):
            if leg["asset"] and leg["status"] == "ok":
                add(leg["asset"], f"{role}_text", v, {"words": leg["via"]})
        if v.get("images_error"):
            add(None, f"{role}_image", v, {"unread": v["images_error"]})
            continue
        for img in v.get("images") or []:
            o = img.get("ocr") or {}
            if "text" not in o:
                add(None, f"{role}_image", v, {"image_sha256": img["sha256"], "unread": o.get("error") or "no OCR stored"})
                continue
            text = o["text"]                         # pinned with the context (load() verifies it)
            r = read_images.read_text(text)
            hits = [(t["asset"], t["title"]) for t in r["titles"]] + [(t, t) for t in r["tickers"]] + [(w, w) for w in r["words"]]
            hits += registry_tickers(text, reg)
            done = set()
            for asset, word in hits:
                if (asset, word) in done:
                    continue
                done.add((asset, word))
                add(asset, f"{role}_image", v, {"image_sha256": img["sha256"], "file": img["file"], "matched": word,
                                                "ocr_excerpt": excerpt(text, word)})
    unread = found.pop(None, [])
    out = [{"asset": a, "sources": s} for a, s in sorted(found.items())]
    if unread:
        out.append({"asset": None, "sources": unread})
    return out


# ---- potential callers -------------------------------------------------------------------------------
def potential(root=HERE, tracked=None):
    """Accounts the tracked callers replied to or quoted directly (the parent of a stored context; a thread root
    further up is context, not an interaction) that are not callers themselves: listed with each interaction,
    never scored, until the owner promotes one."""
    import glob
    tracked = {h.lower() for h in (tracked or [])}
    promoted = promoted_handles(root)
    out = {}
    for f in sorted(glob.glob(os.path.join(root, "sources", "context", "*.json"))):
        pid = os.path.basename(f)[:-5]
        try:
            doc = load(pid, root)
        except (Integrity, OSError, ValueError, KeyError):
            continue
        c = doc["caller"]
        for role, v in roles(doc)[:1]:                 # the direct parent: the account the caller answered or quoted
            h = v["author"]
            if h.lower() in tracked or h.lower() == c["author"].lower():
                continue
            e = out.setdefault(h.lower(), {"handle": h, "status": "promoted (watched, unscored until a call is added)"
                                           if h.lower() in promoted else "potential (unscored, pending owner promotion)",
                                           "interactions": []})
            e["interactions"].append({"caller": c["author"], "caller_post": c["id"], "caller_url": c["url"], "role": role,
                                      "link": (doc["chain"][0] or {}).get("link") if doc["chain"] else None,
                                      "post": v["id"], "post_url": v["url"], "posted_at": v["posted_at"],
                                      "receipt": v["receipt"]})
    return [out[k] for k in sorted(out)]


PROMOTED = os.path.join("data", "promoted_callers.json")


def promoted_list(root=HERE):
    """Handles the owner promoted (bot /promote): watched by the watcher, unscored until a call of theirs is added."""
    try:
        with open(os.path.join(root, PROMOTED)) as f:
            return [h for h in json.load(f).get("handles", []) if isinstance(h, str)]
    except (OSError, ValueError):
        return []


def promoted_handles(root=HERE):
    return {h.lower() for h in promoted_list(root)}


def write_potential(root=HERE, tracked=None):
    rows = potential(root, tracked)
    doc = {"schema": "quanty.potential_callers.v1", "note": "accounts tracked callers replied to or quoted; never scored "
           "(rate.py reads records only) until the owner promotes one and adds a call of theirs",
           "count": len(rows), "accounts": rows}
    path = os.path.join(root, "data", "potential_callers.json")
    with open(path + ".tmp", "w") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(path + ".tmp", path)
    return doc


def promote(handle, root=HERE):
    """The owner promotes a potential caller (bot /promote): only an account listed in data/potential_callers.json.
    The watcher then follows it; it stays unscored until the owner adds a call of theirs (rate.py reads records)."""
    import re
    if not re.fullmatch(r"@?[A-Za-z0-9_]{1,15}", handle or ""):
        raise ValueError(f"not an X handle: {handle!r}")
    handle = handle.lstrip("@")
    with open(os.path.join(root, "data", "potential_callers.json")) as f:
        listed = {a["handle"].lower(): a["handle"] for a in json.load(f)["accounts"]}
    if handle.lower() not in listed:
        raise ValueError(f"@{handle} is not a potential caller (run: python3 tools/parents.py potential)")
    have = promoted_list(root)
    if handle.lower() in {h.lower() for h in have}:
        return False
    path = os.path.join(root, PROMOTED)
    with open(path + ".tmp", "w") as f:
        json.dump({"schema": "quanty.promoted_callers.v1", "note": "watched by the caller watcher; unscored until a call is added",
                   "handles": sorted(have + [listed[handle.lower()]], key=str.lower)}, f, indent=1)
        f.write("\n")
    os.replace(path + ".tmp", path)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["walk", "show", "potential", "promote"])
    ap.add_argument("post", nargs="?")
    a = ap.parse_args(argv)
    if a.cmd == "promote":
        try:
            changed = promote(a.post)
        except (ValueError, OSError) as e:
            print(f"REFUSED {e}")
            return 2
        print(f"@{a.post.lstrip('@')} " + ("promoted: the watcher follows it; unscored until a call of theirs is added" if changed else "was already promoted"))
        return 0
    if a.cmd == "potential":
        import watch_callers
        d = write_potential(HERE, watch_callers.callers(HERE))
        print(f"potential callers: {d['count']}")
        for r in d["accounts"]:
            print(f"  @{r['handle']}: {len(r['interactions'])} interaction(s), {r['status']}")
        return 0
    doc = build(a.post) if a.cmd == "walk" else load(a.post)
    print(f"context {a.post}: {doc['status']}" + (f" ({doc['reason']})" if doc.get("reason") else ""))
    for role, v in roles(doc):
        print(f"  {role}: @{v['author']} {v['posted_at']} {v['url']}\n    {' '.join(v['text'].split())[:200]}\n    images: "
              + ", ".join(f"{i['file']} sha256 {i['sha256'][:12]}" for i in v.get("images") or []))
    for c in candidates(doc):
        print(f"  candidate {c['asset']}: " + "; ".join(f"{s['source']} {s['evidence']}" for s in c["sources"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
