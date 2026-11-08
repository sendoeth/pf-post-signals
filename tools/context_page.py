#!/usr/bin/env python3
"""Step 29: the reply-context page (web/context.html, web/data/context.json) and the agreement before / after context.

usage: python3 tools/context_page.py     (offline: reads sources/context/*.json, the stored images' OCR caches, data/labels.json)

Every stored context (tools/parents.py) is shown with the stored copy of the post the caller answered (text, author,
time, link, image sha256), the assets the context names (each with its source and evidence) and what the reader makes
of the reply: a side only ever from the caller's own words. Agreement on the owner's labels (step 27):
  asset found     an added label's asset is among the assets the reader proposes: before = the post's own words,
                  after = own words + context candidates
  side            the side read for the label's asset, before (reader.read, today) and after (reader.read_in_context)
Score-neutral: nothing here reads into or writes a record; charts.json is not touched.
"""
import collections
import hashlib
import html
import json
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TOOLS)
sys.path[:0] = [HERE, TOOLS]
import detect  # noqa: E402
import labels as lb  # noqa: E402
import parents  # noqa: E402
import reader  # noqa: E402
import tickers  # noqa: E402

VERSION = "quanty.context_page.v1"
SIDE = {1: "long", -1: "short", None: "none"}
e = lambda s: html.escape(str(s), quote=True)


def no_ocr(path):
    """Pages are built from the stored OCR caches only: an image without one is listed as unread, never OCR'd here."""
    raise RuntimeError("no stored OCR for this image")


def contexts(root=HERE):
    out = {}
    d = os.path.join(root, "sources", "context")
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.endswith(".json"):
            pid = f[:-5]
            out[pid] = parents.load(pid, root)              # verified against its pin, receipts and image bytes
    return out


def own_legs(text, reg):
    return [{"asset": l["asset"], "aliases": [l["asset"]] + [v.lstrip("$") for v in l["via"]], "multi": True}
            for l in detect.coin_legs(text, net=parents.OfflineNet(), registry=reg) if l["asset"] and l["status"] == "ok"]


def records_by_post(root=HERE):
    import glob
    out = collections.defaultdict(list)
    for f in sorted(glob.glob(os.path.join(root, "records", "**", "*.json"), recursive=True)):
        with open(f) as fh:
            r = json.load(fh)
        out[r["post"]["id"]].append({"asset": r["asset"]["name"], "side": {1: "long", -1: "short"}.get(r.get("side"), "none")})
    return {k: sorted(v, key=lambda x: (x["asset"], x["side"])) for k, v in out.items()}


def agreement(labels, ctx, cands, reg, kept):
    """Before / after context on the owner's gating labels (step 27). Only labels of posts with a stored context can
    change; every other label reads the same by construction."""
    rows, tally = [], collections.Counter()
    for l in labels:
        if not l["gating"]:
            continue
        pid = l["post"]["id"]
        o = l["owner"]
        before = lb.read_label(l, kept)
        own = own_legs(l["post"]["text"], reg)
        names = {x["asset"] for x in own}
        cand = cands.get(pid, [])
        after = before
        if pid in ctx and o.get("asset") and o["asset"] not in names and any(c.get("asset") == o["asset"] for c in cand):
            r = next(x for x in reader.read_in_context(l["post"]["text"], own, cand, rules=kept) if x["asset"] == o["asset"])
            after = {"side": SIDE[r["side"]], "method": r["method"], "rule": None, "words": r["words"], "side_from": r["side_from"]}
        ab, aa = lb.agrees(l, before), lb.agrees(l, after)
        tally["side_before"] += ab
        tally["side_after"] += aa
        tally["n"] += 1
        found_b = found_a = None
        if o["decision"] == "add" and o.get("asset"):
            found_b = o["asset"] in names
            found_a = found_b or any(c.get("asset") == o["asset"] for c in cand)
            tally["adds"] += 1
            tally["found_before"] += found_b
            tally["found_after"] += found_a
        if pid in ctx:
            tally["with_context"] += 1
            rows.append({"id": l["id"], "post": pid, "author": l["post"]["author"], "owner": {"decision": o["decision"], "asset": o.get("asset"), "side": o.get("side")},
                         "own_assets": sorted(names), "context_assets": sorted({c["asset"] for c in cand if c.get("asset")}),
                         "asset_found_before": found_b, "asset_found_after": found_a,
                         "side_before": before["side"], "side_after": after["side"], "side_after_from": after.get("side_from", "own words (unchanged)"),
                         "agree_before": ab, "agree_after": aa})
    return {"labels": tally["n"], "labels_with_context": tally["with_context"],
            "side_agree_before": tally["side_before"], "side_agree_after": tally["side_after"],
            "adds": tally["adds"], "asset_found_before": tally["found_before"], "asset_found_after": tally["found_after"]}, rows


def build_data(root=HERE, ocr_engine=no_ocr):
    reg = tickers.load_registry()
    ctx = contexts(root)
    cands = {pid: parents.candidates(doc, root=root, ocr_engine=ocr_engine, registry=reg) for pid, doc in ctx.items()}
    kept = reader.kept_rules(os.path.join(root, "data", "rules.json"), os.path.join(root, "data", "labels.json"))
    with open(os.path.join(root, "data", "labels.json")) as f:
        labels = json.load(f)["labels"]
    summary, arows = agreement(labels, ctx, cands, reg, kept)
    recs = records_by_post(root)
    entries = []
    for pid, doc in sorted(ctx.items(), key=lambda kv: kv[1]["caller"]["posted_at"]):
        c = doc["caller"]
        own = own_legs(c["text"], reg)
        reads = reader.read_in_context(c["text"], own, cands[pid], rules=kept)
        usable = dict(parents.usable_roles(doc))
        posts = {}
        for role, v in parents.roles(doc):
            posts[role] = {k: v[k] for k in ("id", "url", "author", "posted_at", "text", "text_sha256", "receipt", "link") if k in v}
            posts[role]["text_truncated"] = bool(v.get("text_truncated"))
            posts[role]["images"] = [{k: i[k] for k in ("file", "sha256", "bytes")} for i in v.get("images") or []]
            posts[role]["used"] = role in usable
        entries.append({"post": pid, "url": c["url"], "author": c["author"], "posted_at": c["posted_at"], "text": c["text"],
                        "receipt": c["receipt"], "status": doc["status"], "reason": doc.get("reason"), "pin_sha256": doc["pin_sha256"],
                        "chain": doc["chain"], "posts": posts, "candidates": cands[pid],
                        "reads": [{"asset": r["asset"], "side": SIDE[r["side"]], "method": r["method"], "rule": r.get("rule"),
                                   "provenance": r["provenance"], "side_from": r["side_from"]} for r in reads],
                        "recorded": recs.get(pid, [])})
    pot = {"accounts": []}
    p = os.path.join(root, "data", "potential_callers.json")
    if os.path.exists(p):
        with open(p) as f:
            pot = json.load(f)
    charts = os.path.join(root, "web", "data", "charts.json")
    charts_sha = None
    if os.path.exists(charts):
        with open(charts, "rb") as f:
            charts_sha = hashlib.sha256(f.read()).hexdigest()
    doc = {"schema": VERSION, "limits": {"max_depth": parents.MAX_DEPTH, "max_images": parents.MAX_IMAGES,
                                         "max_image_bytes": parents.MAX_IMAGE_BYTES, "max_pixels": parents.MAX_PIXELS},
           "contexts": len(entries), "agreement": summary, "agreement_rows": arows, "entries": entries,
           "potential_callers": pot["accounts"], "kept_rules": kept,
           "charts_sha256": charts_sha}
    return doc


def pill(s):
    return s.replace("_", " ")


def context_block(en, standalone=False):
    """One reply's context as HTML (the context page and the position page share it)."""
    rows = []
    for role, v in en["posts"].items():
        imgs = "".join(f'<li class="muted small">image {e(i["file"].rsplit("/", 1)[-1])} · sha256 <code>{e(i["sha256"][:16])}…</code> · {i["bytes"]:,} bytes</li>' for i in v["images"])
        note = "" if v["used"] else ' <span class="muted small">(not used: the walk did not reach a post without a parent)</span>'
        trunc = ' <span class="muted small">(text cut short in the embed: its words are not used)</span>' if v["text_truncated"] else ""
        rows.append(f'<div class="ctx-post" data-role="{e(role)}"><p class="small"><strong>{"Replying to" if role == "parent" and v.get("link") == "reply" else "Quoting" if role == "parent" else "Thread start"}</strong> '
                    f'<a href="{e(v["url"])}" rel="noopener noreferrer">@{e(v["author"])}</a> · {e(v["posted_at"][:16].replace("T", " "))} UTC{note}{trunc}</p>'
                    f'<blockquote data-field="parent_text">{e(v["text"])}</blockquote>'
                    f'<p class="muted small">stored copy: {e(v["receipt"])} · text sha256 <code>{e(v["text_sha256"][:16])}…</code></p>'
                    + (f'<ul class="plain">{imgs}</ul>' if imgs else "") + "</div>")
    cands = "".join(f'<li data-asset="{e(c["asset"])}"><strong>{e(c["asset"])}</strong> <span class="muted small">'
                    + "; ".join(f'{pill(s["source"])}' + (f' (“{e(s["evidence"].get("matched"))}” in image {e(s["evidence"].get("image_sha256", "")[:12])}…: “{e(s["evidence"].get("ocr_excerpt") or "")}”)'
                                                       if s["evidence"].get("image_sha256") else f' ({e(", ".join(s["evidence"].get("words") or []))})') for s in c["sources"])
                    + "</span></li>" for c in en["candidates"] if c.get("asset"))
    unread = "".join(f'<li class="muted small">{pill(s["source"])}: {e(s["evidence"].get("unread"))}</li>' for c in en["candidates"] if not c.get("asset") for s in c["sources"])
    reads = "".join(f'<tr data-asset="{e(r["asset"])}" data-side="{e(r["side"])}"><td>{e(r["asset"])}</td><td>{e(r["side"])}</td><td class="small">{e(r["side_from"])}</td>'
                    f'<td class="small">{e(", ".join(pill(p) for p in r["provenance"]))}</td></tr>' for r in en["reads"])
    status = "" if en["status"] == "complete" else f'<p class="notes">Context <strong>{e(en["status"])}</strong>: {e(en.get("reason") or "")}. The thread start is not known, so it gives nothing.</p>'
    head = (f'<p><a href="{e(en["url"])}" rel="noopener noreferrer">@{e(en["author"])}</a> · {e(en["posted_at"][:16].replace("T", " "))} UTC: “{e(en["text"])}”</p>' if standalone else "")
    return (f'<section class="panel recap context" data-field="reply_context" data-post="{e(en["post"])}" data-status="{e(en["status"])}">'
            + (f'<h2>Reply context</h2>' if not standalone else "") + head + status + "".join(rows)
            + (f'<p class="small"><strong>Assets the context names</strong> (never a side):</p><ul class="plain">{cands}{unread}</ul>' if cands or unread else '<p class="muted small">The context names no asset.</p>')
            + (f'<div class="table-wrap"><table class="calls"><thead><tr><th>Asset</th><th>Side</th><th>Side from</th><th>Asset from</th></tr></thead><tbody>{reads}</tbody></table></div>' if reads else "")
            + f'<p class="muted small">Pinned context sha256 <code>{e(en["pin_sha256"][:16])}…</code> · sides come only from the caller’s own words; nothing here changes a record or a score.</p></section>')


def page(d):
    a = d["agreement"]
    rows = "".join(f'<tr data-label="{e(r["id"])}"><td><a href="https://x.com/{e(r["author"])}/status/{e(r["post"])}" rel="noopener noreferrer">@{e(r["author"])}</a></td>'
                   f'<td>{e(r["owner"]["decision"])} {e(r["owner"].get("asset") or "–")} {e(r["owner"].get("side") or "")}</td><td>{e(", ".join(r["own_assets"]) or "–")}</td>'
                   f'<td>{e(", ".join(r["context_assets"]) or "–")}</td><td>{"–" if r["asset_found_before"] is None else ("yes" if r["asset_found_before"] else "no")} → '
                   f'{"–" if r["asset_found_after"] is None else ("yes" if r["asset_found_after"] else "no")}</td><td>{e(r["side_before"])} → {e(r["side_after"])}</td>'
                   f'<td>{"✔" if r["agree_before"] else "✘"} → {"✔" if r["agree_after"] else "✘"}</td></tr>' for r in d["agreement_rows"])
    pots = "".join(f'<tr data-handle="{e(p["handle"])}"><td><a href="https://x.com/{e(p["handle"])}" rel="noopener noreferrer">@{e(p["handle"])}</a></td><td>{e(p["status"])}</td>'
                   f'<td class="small">' + "; ".join(f'@{e(i["caller"])} {e(i.get("link") or "")} <a href="{e(i["post_url"])}" rel="noopener noreferrer">{e(i["post"])}</a>' for i in p["interactions"]) + "</td></tr>"
                   for p in d["potential_callers"])
    blocks = "".join(context_block(en, standalone=True) for en in reversed(d["entries"]))
    lim = d["limits"]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; manifest-src 'none'; media-src 'none'; font-src 'none'; upgrade-insecure-requests">
<meta name="referrer" content="no-referrer">
<script src="assets/frame-guard.js"></script>
<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reply context · Quanty Quants</title>
<meta name="description" content="Replies and quotes read with the post they answer: stored copies, image evidence, and sides only from the caller's own words.">
<link rel="stylesheet" href="assets/board.css">
<link rel="stylesheet" href="assets/episode.css">
<link rel="stylesheet" href="assets/position.css">
</head>
<body>
<main>
  <header class="top">
    <div>
      <h1>Quanty Quants</h1>
      <p class="sub">Replies and quotes, read with the post they answer</p>
    </div>
    <nav class="nav" aria-label="Views">
      <a href="./">Leaderboard</a>
      <a href="chart.html">Chart</a>
      <a href="episodes.html">Episodes</a>
      <a href="coins.html">Coins</a>
      <a href="agreement.html">Agreement</a>
      <a href="regimes.html">Regimes</a>
      <a href="context.html" aria-current="page">Context</a>
    </nav>
  </header>
  <section class="ep-head panel" data-field="context-rule">
    <p>A short reply (“More $NEST and $KNTQ”) means something next to the post it answers. For every reply or quote, the post it answers and the post that started the thread are fetched from X’s public embed, checked like any receipt (the id, its time, the author) and stored with their images (sha256). The <strong>assets</strong> they name, in text or in images (the step 18 image reader), become context candidates, each labelled with where it came from. A <strong>side never comes from context</strong>: only from the caller’s own words. An asset only the context names gets a side only when the caller names no asset of their own and the context names exactly one; otherwise none.</p>
    <p class="notes">Fail closed: a deleted or protected post, an integrity mismatch, a cycle or more than {lim['max_depth']} parents gives no thread-start context; a text the embed cuts short and images that cannot all be saved give nothing from that post. Bounds: {lim['max_images']} images, {lim['max_image_bytes'] // 1024 // 1024} MB each, {lim['max_pixels'] // 1_000_000} megapixels before OCR, a deadline per walk. Every stored context is pinned (sha256 over its posts, links, texts and image bytes) and verified when read. Score-neutral: no record or score changes unless the owner adds a call through the bot.</p>
  </section>
  <h2 class="sec">Agreement with the owner’s labels, before and after context</h2>
  <p class="notes">{a['labels']} gating labels (step 27), {a['labels_with_context']} of them on replies or quotes with a stored context. <strong>Asset found</strong> (added calls): the owner’s asset is among the assets the reader proposes: {a['asset_found_before']} of {a['adds']} from the post’s own words → <strong>{a['asset_found_after']} of {a['adds']}</strong> with context. <strong>Side agreement</strong>: {a['side_agree_before']} of {a['labels']} → <strong>{a['side_agree_after']} of {a['labels']}</strong> (context never sets a side; a side can only come from the caller’s words).</p>
  <div class="panel tablewrap"><table class="coins" data-field="agreement"><thead><tr><th>Caller</th><th>Owner</th><th>Own words name</th><th>Context names</th><th>Asset found</th><th>Side read</th><th>Agrees</th></tr></thead><tbody>{rows}</tbody></table></div>
  <h2 class="sec">Potential callers</h2>
  <p class="notes">Accounts our callers replied to or quoted directly. Never scored: the score reads recorded calls only. The owner can promote one (bot /promote): the watcher then follows it, and it stays unscored until a call of theirs is added.</p>
  <div class="panel tablewrap"><table class="coins" data-field="potential"><thead><tr><th>Account</th><th>Status</th><th>Interactions</th></tr></thead><tbody>{pots or '<tr><td colspan="3">none yet</td></tr>'}</tbody></table></div>
  <h2 class="sec">Every reply and quote ({d['contexts']})</h2>
  {blocks}
  <p class="muted small">Data: <a href="data/context.json">data/context.json</a> · charts.json sha256 {e((d.get('charts_sha256') or '')[:16])}…</p>
  <p class="nfa" id="nfa" data-field="nfa"><strong>Not financial advice.</strong> The calls are public posts by their authors, tracked and priced for analysis. Nothing here is a recommendation to buy, sell or hold anything.</p>
</main>
</body>
</html>
"""


def build(root=HERE, ocr_engine=no_ocr):
    d = build_data(root, ocr_engine)
    with open(os.path.join(root, "web", "data", "context.json"), "w") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
        f.write("\n")
    with open(os.path.join(root, "web", "context.html"), "w") as f:
        f.write(page(d))
    return d


def main():
    d = build()
    a = d["agreement"]
    print(f"context: {d['contexts']} stored contexts; asset found {a['asset_found_before']}/{a['adds']} -> {a['asset_found_after']}/{a['adds']}; "
          f"side agreement {a['side_agree_before']}/{a['labels']} -> {a['side_agree_after']}/{a['labels']}; potential callers {len(d['potential_callers'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
