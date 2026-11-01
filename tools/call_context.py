#!/usr/bin/env python3
"""Call context: what the author said about the same asset before and after a post. Owner-only, local.

  python3 tools/call_context.py URL [--asset NAME] [--days 90]
  python3 tools/call_context.py URL --asset NAME --apply [--record-post ID]

Two read-only searches through the research harness (the same one the 12-month scan uses):
  before   from:<author> (<asset words>) in the --days before the post
  after    from:<author> (<asset words>) from the post until today
Every post found is labelled:
  own call      the author's own post with a side (detect.detect_side)
  own mention   the author's own post about the asset without a side
  not theirs    a repost (someone else's words) or another account
and the analysed post itself is checked for victory-lap wording ("did you fade", "told you", "called
it"...): then it is a look back, not a new call, and the earliest own call before it is suggested
as the call to add instead (its entry is when the author actually took the position).

After the call, each own post is run through the closing-call rules of classify.py (advice, flip,
close, trim, hint) plus holding words ("still long", "holding", "added more"):
  close / flip  -> the position closes at the first bar after that post (step 13 lifecycle)
  trim          -> recorded, stays open
  review        -> a hint, never closes by itself
  hold          -> still in the position
  nothing       -> the trade stays open (nothing disclosed)
Output: intake/context/<post>.json + .md. Nothing under web/ or records/ changes.

--apply writes the follow-ups (with the labels above as reviewed overrides, each with its matched
words) into data/lifecycle.json for the recorded call, saves their receipts, re-applies the
lifecycle to that record (lifecycle.apply on its own bars) and rebuilds the bundle and pages; the
daily refresh keeps applying it. Nothing is published: that is /publish (or a normal commit).
"""
import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import re
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TOOLS)
sys.path[:0] = [HERE, TOOLS]
import classify  # noqa: E402
import detect  # noqa: E402
import resolve  # noqa: E402
import scan_caller  # noqa: E402

VERSION = "quanty.context.v1"
GLOAT = re.compile(r"\b(?:did (?:you|u) fade|who faded|still fading|told (?:you|ya|u)|called it|you'?re welcome|as i said|i said\b.*\b(?:long|short|buy)|"
                   r"hope you (?:listened|didn'?t fade|bought)|reminder that i)\b", re.I)
HOLD = re.compile(r"\b(?:still (?:long|holding|in|bullish|bearish|short)|(?:i'?m|i am|we'?re|we are) (?:still )?holding|holding (?:my|our)\b|"
                  r"(?:i|we) (?:do not|don'?t|never|will not|won'?t) sell|not selling|haven'?t sold|(?:i'?ll|we'?ll|i will|we will|i am going to|i'?m going to|we are going to) (?:buy|bid)|"
                  r"(?:i|we) (?:added|bought) (?:more|some)|bought more|buying more|adding (?:more|here)|diamond hands|"
                  r"(?:i|we) (?:sold|swapped|rotated|traded) [\w$ ]{1,25}? (?:to buy|for|into)\b)", re.I)
# coin / fund names for assets the asset map does not cover, by base symbol
ALIASES = {"ZEC": ["zec", "zcash"], "XMR": ["xmr", "monero"], "HYPE": ["hype", "hyperliquid"], "SUI": ["sui"], "TAO": ["tao", "bittensor"],
           "DOGE": ["doge", "dogecoin"], "XRP": ["xrp", "ripple"], "AVAX": ["avax", "avalanche"], "LINK": ["link", "chainlink"],
           "SOL": ["sol", "solana"], "ETH": ["eth", "ethereum"], "BTC": ["btc", "bitcoin"]}


def asset_words(name):
    """Search words for an asset: the asset map's terms, or the base symbol + known names."""
    m = detect.load_map()
    words = sorted({t for _, t, a in m["terms"] if a == name.upper()})
    words += [c.lower() for c, a in m["cashtags"].items() if a == name.upper()]
    base = name.split(":")[-1].upper()
    for q in ("USDT", "USDC", "USD", "PERP"):
        if base.endswith(q) and len(base) > len(q):
            base = base[: -len(q)]
            break
    words += ALIASES.get(base, [base.lower()])
    reg = resolve.registered_tickers().get(base)       # step 22: a resolved ticker also searches its coin's name
    if reg:
        words.append(reg["name"].lower())
    return sorted({w for w in words if w}, key=len)


def mentions(text, words):
    return [w for w in words if re.search(r"(?<![\w$])\$?" + re.escape(w) + r"(?![\w])", text or "", re.I)]


def label_before(p, author, words):
    own = p["authorHandle"].lower() == author.lower() and p.get("kind") != "repost"
    hit = mentions(p.get("text"), words)
    if not own:
        return "not theirs", ("a repost of someone else's post" if p.get("kind") == "repost" else f"by @{p['authorHandle']}"), None, hit
    s = detect.detect_side(p.get("text"))
    if s["status"] == "detected":
        return "own call", f"side words {s['terms'][s['side']][:3]}", s["side"], hit
    if s["status"] == "ambiguous":
        return "own mention", "states both sides", None, hit
    return "own mention", "no side words", None, hit


def label_after(p, author, words, side):
    if p["authorHandle"].lower() != author.lower() or p.get("kind") == "repost":
        return "not theirs", "a repost or another account", []
    text = p.get("text") or ""
    find = lambda pats: [m.group(0) for pat in pats for m in re.finditer(pat, text, re.I)]
    if find(classify.ADVICE):
        return "not_close", "advice to others", find(classify.ADVICE)[:3]
    flips = [m for m in re.finditer(classify.FLIP[0], text, re.I)]
    if flips and side in (1, -1) and {m.group(1).lower() for m in flips} == {"short" if side == 1 else "long"}:
        return "flip", "states the opposite side", [m.group(0) for m in flips]
    swap = re.search(r"\b(?:sold|swapped|rotated|traded) [\w$ ]{1,25}? (?:to buy|for|into) \$?(\w+)", text, re.I)
    if swap and swap.group(1).lower() in words:
        return "hold", f"sold something else to buy more of it ('{swap.group(0)}')", [swap.group(0)]
    out_of = re.search(r"\b(?:sold|swapped|rotated out of|dumped|exited) (?:all (?:of )?)?(?:my |our )?\$?(\w+)", text, re.I)
    if out_of and out_of.group(1).lower() in words:
        return "close", f"sold this asset ('{out_of.group(0)}')", [out_of.group(0)]
    if find(classify.CLOSE):
        return "close", "explicit exit of the author's own position", find(classify.CLOSE)[:3]
    if find(classify.TRIM):
        return "trim", "partial sale: stays open", find(classify.TRIM)[:3]
    if find(classify.HINT):
        return "review", "a hint at exiting: never closes by itself", find(classify.HINT)[:3]
    if HOLD.search(text):
        return "hold", "still in the position", [HOLD.search(text).group(0)]
    return "mention", "talks about the asset without exit or hold words", []


# for the search after a call: only posts that name the asset AND hint at an exit or a hold
EXIT_HOLD_WORDS = ["sold", "sell", "selling", "exited", "closed", "\"took profit\"", "\"took profits\"", "\"taking profit\"", "profits", "trimmed",
                   "\"out of\"", "rotated", "\"stopped out\"", "holding", "\"still long\"", "\"still holding\"", "\"bought more\"", "added", "flipped", "short"]
EMPTY_STREAK = 3


def search(handle, words, since, until, harness, window_days=30, budget=24, extra=None):
    """Windowed searches (a search page stops scrolling after ~100 posts): a window whose oldest
    post is far from its start with many posts is split in two. Returns (queries, {"posts": [...]}, error)
    with per-window coverage; stops on the budget or a harness error and says where."""
    t, end = dt.datetime.strptime(since, "%Y-%m-%d"), dt.datetime.strptime(until, "%Y-%m-%d")
    wins = []
    while t < end:
        u = min(t + dt.timedelta(days=window_days), end)
        wins.append([t, u])
        t = u
    posts, cover, err, n, empties = {}, [], None, 0, []
    while wins:
        a, b = wins.pop(0)
        if n >= budget:
            err = f"search budget ({budget}) reached at {a:%Y-%m-%d}: later windows not searched"
            cover.append({"since": f"{a:%Y-%m-%d}", "until": f"{b:%Y-%m-%d}", "status": "not searched"})
            cover += [{"since": f"{x:%Y-%m-%d}", "until": f"{y:%Y-%m-%d}", "status": "not searched"} for x, y in wins]
            break
        q = f"from:{handle} ({' OR '.join(words)})" + (f" ({' OR '.join(extra)})" if extra else "") + f" since:{a:%Y-%m-%d} until:{b:%Y-%m-%d}"
        man, rid, e = harness(q)
        n += 1
        if man is not None and not man["posts"]:
            empties.append([a, b])
            if len(empties) >= EMPTY_STREAK:            # X answers a throttled account with empty pages
                err = f"throttled: {len(empties)} empty pages in a row from {empties[0][0]:%Y-%m-%d}"
                for x, y in empties:
                    cover.append({"since": f"{x:%Y-%m-%d}", "until": f"{y:%Y-%m-%d}", "status": "not searched"})
                cover += [{"since": f"{x:%Y-%m-%d}", "until": f"{y:%Y-%m-%d}", "status": "not searched"} for x, y in wins]
                break
            continue
        for x, y in empties:                            # empty pages followed by a real one were really empty
            cover.append({"since": f"{x:%Y-%m-%d}", "until": f"{y:%Y-%m-%d}", "status": "done", "posts": 0})
        empties = []
        if man is None:
            err = f"{scan_caller.stop_reason(e)} at {a:%Y-%m-%d}: {e[-200:]}"
            cover.append({"since": f"{a:%Y-%m-%d}", "until": f"{b:%Y-%m-%d}", "status": "error"})
            cover += [{"since": f"{x:%Y-%m-%d}", "until": f"{y:%Y-%m-%d}", "status": "not searched"} for x, y in wins]
            break
        own = [p for p in man["posts"] if p["authorHandle"].lower() == handle.lower()]
        oldest = min((p["postedAt"][:10] for p in own), default=None)
        if oldest and len(man["posts"]) >= 40 and (dt.datetime.strptime(oldest, "%Y-%m-%d") - a).days > 2 and (b - a).days > 2:
            mid = a + (b - a) / 2
            mid = mid.replace(hour=0, minute=0, second=0, microsecond=0)
            wins[:0] = [[a, mid], [mid, b]]
            cover.append({"since": f"{a:%Y-%m-%d}", "until": f"{b:%Y-%m-%d}", "status": "split", "posts": len(man["posts"])})
            continue
        for p in man["posts"]:
            p["_run"], p["_sha"] = man.get("_run"), man.get("_sha256")
            posts[p["id"]] = p
        cover.append({"since": f"{a:%Y-%m-%d}", "until": f"{b:%Y-%m-%d}", "status": "done", "posts": len(man["posts"]), "run": man.get("_run"), "manifest_sha256": man.get("_sha256")})
    if not err:
        for x, y in empties:                            # trailing empty pages: not confirmed by a later real page
            cover.append({"since": f"{x:%Y-%m-%d}", "until": f"{y:%Y-%m-%d}", "status": "done", "posts": 0, "note": "empty (at the end of the range)"})
    q0 = f"from:{handle} ({' OR '.join(words)})" + (f" ({' OR '.join(extra)})" if extra else "") + f" since:{since} until:{until}"
    return q0, {"posts": list(posts.values()), "coverage": cover, "searches": n}, err


def analyse(url, root=HERE, asset=None, days=90, fetch=None, harness=scan_caller.run_harness, today=None, now=None):
    import ingest
    rpath, receipt, _ = ingest.ingest(url, fetch=fetch or ingest.fetch_embed, root=root)
    post_at = receipt["postedAt"][:19] + "Z"
    author = receipt["authorHandle"]
    if not asset:
        d = detect.detect(receipt.get("text"))
        if d["status"] != "detected":
            raise SystemExit(f"cannot tell the asset of {url}: pass --asset ({d['reason']})")
        asset = d["asset"]
    info = resolve.asset_info(asset)
    words = asset_words(info["name"])
    t0 = resolve.parse(post_at)
    today = today or dt.datetime.now(dt.timezone.utc)
    q1, before, e1 = search(author, words, (t0 - dt.timedelta(days=days)).strftime("%Y-%m-%d"), (t0 + dt.timedelta(days=1)).strftime("%Y-%m-%d"), harness)
    q2, after, e2 = search(author, words, t0.strftime("%Y-%m-%d"), (today + dt.timedelta(days=1)).strftime("%Y-%m-%d"), harness,
                           window_days=60, extra=EXIT_HOLD_WORDS)
    gloat = GLOAT.search(receipt.get("text") or "")
    side_here = detect.detect_side(receipt.get("text"))
    rows_b = []
    for p in sorted((before or {}).get("posts", []), key=lambda p: p["postedAt"]):
        if p["postedAt"][:19] + "Z" >= post_at or p["id"] == receipt["id"]:
            continue
        lab, why, side, hit = label_before(p, author, words)
        if not hit and lab != "not theirs":
            continue
        rows_b.append({"id": p["id"], "url": f"https://x.com/{p['authorHandle']}/status/{p['id']}", "posted_at": p["postedAt"][:19] + "Z", "kind": p.get("kind"),
                       "label": lab, "why": why, "side": side, "words": hit, "text": " ".join((p.get("text") or "").split())[:280], "_raw": p})
    own_calls = [r for r in rows_b if r["label"] == "own call"]
    call = None
    if gloat or side_here["status"] != "detected":
        call = own_calls[0] if own_calls else None
    side = side_here["side"] if side_here["status"] == "detected" else (call["side"] if call else None)
    start = (call or {"posted_at": post_at})["posted_at"]
    rows_a, others_after = [], 0
    for p in sorted((after or {}).get("posts", []), key=lambda p: p["postedAt"]):
        at = p["postedAt"][:19] + "Z"
        if at <= start or p["id"] in (receipt["id"], (call or {}).get("id")):
            continue
        if not mentions(p.get("text"), words):
            continue
        lab, why, terms = label_after(p, author, words, side)
        if lab == "not theirs":                          # only the author's own later posts can close or hold the call
            others_after += 1
            continue
        rows_a.append({"id": p["id"], "url": f"https://x.com/{p['authorHandle']}/status/{p['id']}", "posted_at": at, "kind": p.get("kind"),
                       "label": lab, "why": why, "words": terms, "text": " ".join((p.get("text") or "").split())[:280], "_raw": p})
    state = state_of(rows_a, after["coverage"])
    out = {"version": VERSION, "url": receipt["url"], "post_id": receipt["id"], "author": author, "posted_at": post_at, "text": receipt.get("text"),
           "asset": info["name"], "words": words, "analysed_at": now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "victory_lap": gloat.group(0) if gloat else None, "side_in_post": side_here["side"],
           "searches": [{"query": q1, "posts": len(before["posts"]), "searches": before["searches"], "coverage": before["coverage"], "error": e1},
                        {"query": q2, "posts": len(after["posts"]), "searches": after["searches"], "coverage": after["coverage"], "error": e2}],
           "before": [{k: v for k, v in r.items() if k != "_raw"} for r in rows_b],
           "suggested_call": {k: v for k, v in call.items() if k != "_raw"} if call else None,
           "after": [{k: v for k, v in r.items() if k != "_raw"} for r in rows_a],
           "others_after": others_after, "state": state, "side": side}
    out["_raw_after"] = {r["id"]: r["_raw"] for r in rows_a}
    out["_raw_call"] = call and call["_raw"]
    d = os.path.join(root, "intake", "context")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{receipt['id']}.json")
    keep = {k: v for k, v in out.items() if not k.startswith("_")}
    keep["after_raw"] = {i: {k: p.get(k) for k in ("id", "authorHandle", "postedAt", "text", "kind", "capturedAt", "conversationId", "metrics", "completeness")}
                         for i, p in out["_raw_after"].items()}            # what --apply --reuse needs to save receipts without searching again
    with open(path, "w") as f:
        json.dump(keep, f, indent=1, ensure_ascii=False)
        f.write("\n")
    with open(os.path.join(d, f"{receipt['id']}.md"), "w") as f:
        f.write(to_md(out))
    out["file"] = os.path.relpath(path, root)
    return out


def to_md(c):
    L = [f"# Call context: {c['url']} (not published)", "",
         f"@{c['author']} · {c['posted_at']} · {c['asset']} · words {c['words']}", f"“{' '.join((c['text'] or '').split())[:280]}”", ""]
    if c["victory_lap"]:
        L.append(f"**Victory lap** ('{c['victory_lap']}'): a look back, not a new call.")
    if c["suggested_call"]:
        s = c["suggested_call"]
        L.append(f"**Suggested call**: {s['posted_at']} {s['url']} “{s['text'][:200]}” ({s['why']})")
    L += ["", f"**State after the call: {c['state']}**", "", "## Before", ""]
    L += [f"- {r['posted_at'][:16]} [{r['label']}]({r['url']}): {r['why']} · “{r['text'][:160]}”" for r in c["before"]] or ["- nothing"]
    L += ["", "## After", ""]
    L += [f"- {r['posted_at'][:16]} [{r['label']}]({r['url']}): {r['why']} {r['words']} · “{r['text'][:160]}”" for r in c["after"]] or ["- nothing"]
    L += ["", "## Searches", ""]
    for s in c["searches"]:
        L.append(f"- `{s['query']}`: {s['posts']} posts in {s['searches']} search(es)" + (f", ERROR {s['error'][:120]}" if s["error"] else ""))
        L += [f"  - {w['since']} → {w['until']}: {w['status']}" + (f" ({w.get('posts')} posts)" if w.get("posts") is not None else "") for w in s["coverage"]]
    return "\n".join(L) + "\n"


def load(post_id, root=HERE, max_age_h=12):
    """A recent context file for this post -> (context, sha256 of the exact bytes parsed), else (None, None)."""
    path = os.path.join(root, "intake", "context", f"{post_id}.json")
    if not os.path.exists(path):
        return None, None
    with open(path, "rb") as f:
        blob = f.read()                                     # hash and parse the same bytes
    sha = hashlib.sha256(blob).hexdigest()
    c = json.loads(blob)
    age = dt.datetime.now(dt.timezone.utc) - dt.datetime.strptime(c["analysed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    if age > dt.timedelta(hours=max_age_h):
        return None, None
    c["_raw_after"] = c.get("after_raw", {})
    c["file"] = os.path.relpath(path, root)
    return c, sha


def relabel(c, root=HERE):
    """Recompute the after-labels and the state from the saved posts (no search): for improved rules."""
    side, start = c.get("side"), (c.get("suggested_call") or {"posted_at": c["posted_at"]})["posted_at"]
    rows, others = [], 0
    for p in sorted(c.get("after_raw", {}).values(), key=lambda p: p["postedAt"]):
        at = p["postedAt"][:19] + "Z"
        if at <= start or not mentions(p.get("text"), c["words"]):
            continue
        lab, why, terms = label_after(p, c["author"], c["words"], side)
        if lab == "not theirs":
            others += 1
            continue
        rows.append({"id": p["id"], "url": f"https://x.com/{p['authorHandle']}/status/{p['id']}", "posted_at": at, "kind": p.get("kind"),
                     "label": lab, "why": why, "words": terms, "text": " ".join((p.get("text") or "").split())[:280]})
    c["after"], c["others_after"] = rows, others
    c["state"] = state_of(rows, c["searches"][1]["coverage"])
    c["relabelled_at"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = os.path.join(root, "intake", "context", f"{c['post_id']}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({k: v for k, v in c.items() if not k.startswith("_") and k != "file"}, f, indent=1, ensure_ascii=False)
        f.write("\n")
    with open(path[:-5] + ".md", "w") as f:
        f.write(to_md(c))
    return c


def state_of(rows, coverage):
    closes = [r for r in rows if r["label"] in ("close", "flip")]
    trims = [r for r in rows if r["label"] == "trim"]
    holds = [r for r in rows if r["label"] == "hold"]
    if closes:
        state = f"closed: {closes[0]['label']} on {closes[0]['posted_at'][:10]} ({', '.join(closes[0]['words'])})"
    elif holds:
        state = f"open: still holding as of {holds[-1]['posted_at'][:10]}" + (f" (trimmed {len(trims)}x)" if trims else "")
    elif trims:
        state = f"open: trimmed {len(trims)}x, no close"
    else:
        state = "open: nothing disclosed after the call"
    gaps = [w for w in coverage if w["status"] in ("not searched", "error")]
    if gaps and not closes:
        state += f" (INCOMPLETE: {len(gaps)} window(s) from {gaps[0]['since']} not searched, rerun later)"
    return state


def summary(c):
    """Short text for the terminal and the bot."""
    L = [f"context   @{c['author']} {c['asset']} ({c['posted_at'][:10]}), words {c['words']}"]
    if c["victory_lap"]:
        L.append(f"⚠️ victory lap ('{c['victory_lap']}'): a look back, not a new call")
    if c["suggested_call"]:
        s = c["suggested_call"]
        L.append(f"📌 the original call: {s['posted_at'][:16]} “{s['text'][:120]}” {s['url']}")
    own = [r for r in c["before"] if r["label"] != "not theirs"]
    L.append(f"before    {len(own)} own post(s) about it" + (f", {len(c['before']) - len(own)} not theirs (reposts / others)" if len(c["before"]) > len(own) else ""))
    for r in own[-5:]:
        L.append(f"  {r['posted_at'][:10]} {r['label']}: “{r['text'][:90]}”")
    L.append(f"after     {len(c['after'])} own post(s) with exit / hold words" + (f" ({c['others_after']} by others or reposts left out)" if c.get("others_after") else ""))
    for r in c["after"][:8]:
        L.append(f"  {r['posted_at'][:10]} {r['label']}{' ' + str(r['words']) if r['words'] else ''}: “{r['text'][:90]}”")
    L.append(f"state     {c['state']}")
    for s in c["searches"]:
        done = sum(1 for w in s["coverage"] if w["status"] == "done")
        L.append(f"searched  {s['query'].split(' since:')[1]} in {s['searches']} search(es), {done} window(s) done" + (f"; {s['error'][:160]}" if s["error"] else ""))
    return "\n".join(L)


def apply(c, root=HERE, record_post=None):
    """Write the follow-ups for the recorded call into data/lifecycle.json and re-apply its lifecycle."""
    import build_chart
    import lifecycle
    import prerender
    pid = record_post or (c["suggested_call"] or {}).get("id") or c["post_id"]
    hits = glob.glob(os.path.join(root, "records", "**", f"{pid}_*.json"), recursive=True)
    hits = [h for h in hits if json.load(open(h))["asset"]["name"] == c["asset"]]
    if not hits:
        raise SystemExit(f"no record of post {pid} on {c['asset']}: add the call first")
    rec_path = hits[0]
    rec = json.load(open(rec_path))
    follow = [r for r in c["after"] if r["label"] in ("close", "flip", "trim", "review", "hold") and r["posted_at"] > rec["post"]["posted_at"]]
    if not follow:
        return {"record": os.path.relpath(rec_path, root), "followups": 0, "state": c["state"], "changed": False}
    for r in follow:                                    # receipts for the follow-ups (lifecycle reads them)
        raw = c["_raw_after"][r["id"]]
        path = os.path.join(root, "sources", raw["authorHandle"].lower(), "receipts", f"{r['id']}.json")
        if not glob.glob(os.path.join(root, "sources", "*", "receipts", f"{r['id']}.json")):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(scan_caller.to_receipt(raw, {"_run": "context", "_sha256": None}, "call_context"), f, indent=1, ensure_ascii=False)
                f.write("\n")
    cfg_path = os.path.join(root, "data", "lifecycle.json")
    cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {"schema": "pf-post-signals.lifecycle.v1", "positions": {}}
    key = f"{rec['post']['id']}|{rec['asset']['name']}"
    life = cfg["positions"].setdefault(key, {"context": "", "followups": [], "overrides": {}})
    life["context"] = f"call context {c['file'] if 'file' in c else ''}: {c['state']}"
    for r in follow:
        if r["id"] not in life["followups"]:
            life["followups"].append(r["id"])
        t = {"hold": "not_close", "mention": "not_close"}.get(r["label"], r["label"])
        life["overrides"][r["id"]] = {"type": t, "reason": f"call context: {r['why']} ({', '.join(r['words']) or 'no words'})"}
    with open(cfg_path, "w") as f:
        json.dump(cfg, f, indent=1, ensure_ascii=False)
        f.write("\n")
    saved = (lifecycle.CONFIG, lifecycle.HERE)
    lifecycle.CONFIG, lifecycle.HERE = cfg_path, root          # read this root's receipts; restored below
    try:
        lifecycle.apply(rec, life, rec["series"])
    finally:
        lifecycle.CONFIG, lifecycle.HERE = saved
    resolve.check_record(resolve.validator(), rec)
    with open(rec_path, "w") as f:
        json.dump(rec, f, indent=1)
        f.write("\n")
    bundle = build_chart.build(os.path.join(root, "records"))
    with open(os.path.join(root, "web", "data", "charts.json"), "w") as f:
        json.dump(bundle, f, indent=1)
        f.write("\n")
    prerender.main(os.path.join(root, "web"))
    return {"record": os.path.relpath(rec_path, root), "followups": len(follow), "status": rec["status"],
            "closed": rec.get("closed"), "changed": True}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url")
    ap.add_argument("--asset")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--apply", action="store_true", help="write the follow-ups into data/lifecycle.json for the recorded call")
    ap.add_argument("--record-post", help="the recorded call's post id (default: the suggested original, else this post)")
    ap.add_argument("--reuse", action="store_true", help="use this post's context file from the last 12 hours (never searches again: fails if there is none)")
    ap.add_argument("--relabel", action="store_true", help="recompute the after-labels from this post's saved context (no search) and save them")
    ap.add_argument("--expect-sha", help="with --reuse: the context file must still have this sha256 (the version that was reviewed)")
    a = ap.parse_args()
    m = resolve.URL_RE.match(a.url or "")
    if a.relabel:
        c, _ = load(m.group(2), max_age_h=24 * 365) if m else (None, None)
        if not c:
            raise SystemExit("no context file for this post to relabel")
        c = relabel(c)
        print(summary(c))
        print(f"relabelled intake/context/{c['post_id']}.json (no search)")
        return
    if a.expect_sha and not a.reuse:
        raise SystemExit("--expect-sha only works with --reuse (nothing applied)")
    if a.reuse:
        c, sha = load(m.group(2)) if m else (None, None)
        if not c:
            raise SystemExit("no recent context file for this post: run the context again (nothing applied)")
        if a.asset and resolve.asset_info(a.asset)["name"] != c["asset"]:
            raise SystemExit(f"the context file is for {c['asset']}, not {a.asset} (nothing applied)")
        if a.expect_sha and sha != a.expect_sha:
            raise SystemExit("the context changed since it was shown (a newer preview rewrote it): run /add again (nothing applied)")
    else:
        c = analyse(a.url, asset=a.asset, days=a.days)
    print(summary(c))
    print(f"file      {c['file']}")
    if a.apply:
        r = apply(c, record_post=a.record_post)
        print(f"applied   {r['followups']} follow-up(s) to {r['record']}" + (f": status {r.get('status')}" if r["changed"] else ": nothing to apply"))
    else:
        print("NOTHING CHANGED: rerun with --apply to write the follow-ups into the recorded call's lifecycle.")


if __name__ == "__main__":
    main()
