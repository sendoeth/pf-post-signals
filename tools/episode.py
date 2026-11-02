#!/usr/bin/env python3
"""Episodes -> priced theses + static pages.

Reads every sources/episodes/<slug>/ folder (episode.json written by hand, verified.json + theses.json
written by tools/transcript.py verify), prices each thesis asset at the episode, and writes:
  web/data/episodes.json        the bundle (schema quanty.episodes.v1)
  web/episode-<slug>.html       one static page per episode (no JS: inline SVG, works under the CSP)
  web/episodes.html             the list of episodes

Page layout (same order as the article -> theses page):
  1. the episode in our own words + the original link (the transcript itself stays private)
  2. theses: one per asset, a very short line + price at the episode -> now
  3. every timestamped moment behind each thesis: call or thought, direction, speaker, verbatim quote

Prices: the last bar at or before the episode's reference time ("price at the episode") and the
latest bar. Series are cached in sources/episodes/<slug>/prices.json so a rebuild is repeatable;
--refresh fetches them again. Episode stances are never rated: thoughts are not positions, and the
calls are a show's calls, not a tracked X caller's.

usage: python3 tools/episode.py [--refresh] [--offline]
"""
import argparse
import datetime as dt
import glob
import hashlib
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import resolve  # noqa: E402

SITE = "https://sendoeth.com/pf-post-signals/web/"
BUNDLE_SCHEMA = "quanty.episodes.v1"
LOOKBACK_DAYS = 30
AFTER_DAYS = 10                # the chart always shows at least this much time after the episode
ARROW = {"bullish": "↑", "bearish": "↓", "neutral": "→"}
WORD = {"bullish": "bullish", "bearish": "bearish", "neutral": "wait / stand aside"}
SIGN = {"bullish": 1, "bearish": -1, "neutral": 0}

e = lambda s: html.escape(str(s), quote=True)


def sha_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load(path):
    with open(path) as f:
        return json.load(f)


def price_series(asset_key, assets, reference_at, cache_path, refresh=False, offline=False, fetch=None):
    """-> {"source","symbol","series"} for the asset, from the cache unless --refresh."""
    cache = load(cache_path) if os.path.exists(cache_path) else {}
    if asset_key in cache and not refresh:
        return cache[asset_key]
    if offline:
        raise SystemExit(f"no cached prices for {asset_key} in {cache_path} (run without --offline)")
    info = resolve.asset_info(assets[asset_key]["price"])
    since = resolve.iso((resolve.parse(reference_at) - dt.timedelta(days=LOOKBACK_DAYS)).timestamp())
    series = (fetch or resolve.fetch_series)(info, since)
    if not series:
        raise SystemExit(f"no prices for {asset_key} ({info['source']}:{info['symbol']}); keeping the last good data")
    old = cache.get(asset_key)
    if old and (old["source"], old["symbol"]) == (info["source"], info["symbol"]):
        # frozen: the bars up to the episode never change once cached, so "price at the episode" cannot drift
        # with a data vendor revision; a refresh only adds the bars after it
        kept = [b for b in old["series"] if b[0] <= reference_at]
        series = kept + [b for b in series if b[0] > reference_at]
    cache[asset_key] = {"source": info["source"], "symbol": info["symbol"], "fetched_at": resolve.iso(dt.datetime.now(dt.timezone.utc).timestamp()), "series": series}
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=0)
    return cache[asset_key]


def at_or_before(series, when):
    got = [b for b in series if b[0] <= when]
    return got[-1] if got else None


def priced(thesis, px, reference_at):
    ref = at_or_before(px["series"], reference_at)
    last = px["series"][-1] if px["series"] else None
    out = {"source": px["source"], "symbol": px["symbol"], "at_episode": None, "latest": None, "change": None, "with_lean": None}
    if ref:
        out["at_episode"] = {"at": ref[0], "price": ref[1]}
    if last:
        out["latest"] = {"at": last[0], "price": last[1]}
    if ref and last and last[0] > ref[0]:
        out["change"] = last[1] / ref[1] - 1
        s = SIGN[thesis["direction"]]
        out["with_lean"] = None if s == 0 else s * out["change"]
    return out


def build(root=HERE, refresh=False, offline=False, fetch=None):
    assets = load(os.path.join(root, "data", "episode_assets.json"))["assets"]
    episodes = []
    for d in sorted(glob.glob(os.path.join(root, "sources", "episodes", "*", ""))):
        meta_p, th_p, ver_p = (os.path.join(d, n) for n in ("episode.json", "theses.json", "verified.json"))
        if not all(os.path.exists(p) for p in (meta_p, th_p, ver_p)):
            continue
        meta, th = load(meta_p), load(th_p)
        for k in ("url", "show_url"):
            if meta.get(k) is not None and not re.fullmatch(r"https://[^\s\"'<>]+", meta[k]):
                raise SystemExit(f"{meta_p}: {k} must be an https:// link")
        if load(ver_p)["transcript_sha256"] != th["transcript_sha256"]:
            raise SystemExit(f"{d}: verified.json and theses.json come from different transcripts")
        theses = []
        for t in th["theses"]:
            px = price_series(t["asset"], assets, meta["reference_at"], os.path.join(d, "prices.json"), refresh, offline, fetch)
            t = dict(t, text=meta["theses_text"].get(t["asset"], ""), proxy=assets[t["asset"]]["proxy"],
                     price=priced(t, px, meta["reference_at"]),
                     series=[b[:2] for b in px["series"]])
            theses.append(t)
        rel = lambda p: os.path.relpath(p, root)
        episodes.append({**{k: meta[k] for k in ("slug", "show", "title", "speakers", "recorded_on", "recorded_source", "reference_at",
                                                 "reference_note", "url", "show_url", "summary", "summary_by")},
                         "transcript_sha256": th["transcript_sha256"], "extraction_sha256": th["extraction_sha256"],
                         "model": th["model"], "prompt_version": th["prompt_version"], "duration": th["duration"],
                         "chapters": th["chapters"], "stances": {"accepted": th["accepted"], "rejected": th["rejected"]},
                         "files": {rel(p): sha_file(p) for p in (meta_p, th_p, ver_p, os.path.join(d, "extraction.json"))},
                         "theses": theses})
    return {"schema": BUNDLE_SCHEMA, "note": "episode stances are not rated; thoughts are not positions", "episodes": episodes}


# ---------- rendering ----------

def pct(x):
    return "n/a" if x is None else f"{x * 100:+.2f}%"


def money(p):
    return f"{p:,.2f}" if p >= 10 else f"{p:,.4f}"


def tone(x):
    return "" if x is None else ("gain" if x > 0 else "loss" if x < 0 else "")


def bubble(cx, cy, kind, direction, r=11):
    """call = solid disc; thought = dashed ring. The arrow inside is the direction."""
    cls = f"bub {kind} {direction}"
    ring = (f'<circle class="ring" cx="{cx:.1f}" cy="{cy:.1f}" r="{r}"/>')
    a = {"bullish": f"M{cx:.1f} {cy + 5:.1f}V{cy - 5:.1f}M{cx - 4:.1f} {cy - 1:.1f}L{cx:.1f} {cy - 5:.1f}L{cx + 4:.1f} {cy - 1:.1f}",
         "bearish": f"M{cx:.1f} {cy - 5:.1f}V{cy + 5:.1f}M{cx - 4:.1f} {cy + 1:.1f}L{cx:.1f} {cy + 5:.1f}L{cx + 4:.1f} {cy + 1:.1f}",
         "neutral": f"M{cx - 5:.1f} {cy:.1f}H{cx + 5:.1f}"}[direction]
    return f'<g class="{cls}">{ring}<path class="arrow" d="{a}"/></g>'


def chart(t, reference_at, w=640, h=170):
    s = t["series"]
    if len(s) < 2:
        return '<p class="notes">no price series</p>'
    pad_l, pad_r, pad_t, pad_b = 8, 64, 16, 22
    t0, t_last = resolve.parse(s[0][0]).timestamp(), resolve.parse(s[-1][0]).timestamp()
    t_ref = resolve.parse(reference_at).timestamp()
    t1 = max(t_last, t_ref + AFTER_DAYS * 86400)     # room after the episode so the bubble is never pinned to the edge
    lo, hi = min(b[1] for b in s), max(b[1] for b in s)
    span = (hi - lo) or hi * 0.01
    lo, hi = lo - span * 0.12, hi + span * 0.12
    X = lambda ts: pad_l + (ts - t0) / (t1 - t0) * (w - pad_l - pad_r)
    Y = lambda p: pad_t + (hi - p) / (hi - lo) * (h - pad_t - pad_b)
    pts = " ".join(f"{X(resolve.parse(a).timestamp()):.1f},{Y(p):.1f}" for a, p in s)
    ref = t["price"]["at_episode"]
    rx = X(resolve.parse(reference_at).timestamp())
    out = [f'<svg class="ep-chart" viewBox="0 0 {w} {h}" role="img" aria-label="{e(t["label"])} price, {LOOKBACK_DAYS} days before the episode to now">',
           f'<line class="grid" x1="{pad_l}" x2="{w - pad_r}" y1="{Y(hi - (hi - lo) * 0.12):.1f}" y2="{Y(hi - (hi - lo) * 0.12):.1f}"/>',
           f'<line class="grid" x1="{pad_l}" x2="{w - pad_r}" y1="{Y(lo + (hi - lo) * 0.12):.1f}" y2="{Y(lo + (hi - lo) * 0.12):.1f}"/>',
           f'<text class="axis" x="{w - pad_r + 6}" y="{Y(hi - (hi - lo) * 0.12) + 4:.1f}">{money(hi - (hi - lo) * 0.12)}</text>',
           f'<text class="axis" x="{w - pad_r + 6}" y="{Y(lo + (hi - lo) * 0.12) + 4:.1f}">{money(lo + (hi - lo) * 0.12)}</text>',
           f'<line class="ref" x1="{rx:.1f}" x2="{rx:.1f}" y1="{pad_t - 6}" y2="{h - pad_b}"/>',
           f'<polyline class="line" points="{pts}"/>',
           f'<text class="axis" x="{pad_l}" y="{h - 6}">{e(s[0][0][:10])}</text>',
           f'<text class="axis" text-anchor="middle" x="{rx:.1f}" y="{h - 6}">episode {e(reference_at[5:10])}</text>']
    if X(t1) - rx > 90:
        out.append(f'<text class="axis" text-anchor="end" x="{w - pad_r}" y="{h - 6}">{e(resolve.iso(t1)[:10])}</text>')
    if ref:
        out.append(bubble(rx, Y(ref["price"]), t["kind"], t["direction"]))
    if t["price"]["latest"] and t["price"]["change"] is not None:      # no dot on top of the bubble before any new bar
        lx, ly = X(t_last), Y(t["price"]["latest"]["price"])
        out.append(f'<circle class="last" cx="{lx:.1f}" cy="{ly:.1f}" r="3"/>')
    out.append("</svg>")
    return "".join(out)


def head(title, desc, url):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; manifest-src 'none'; media-src 'none'; font-src 'none'; upgrade-insecure-requests">
<meta name="referrer" content="no-referrer">
<script src="assets/frame-guard.js"></script>
<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Quanty Quants">
<meta property="og:url" content="{e(url)}">
<meta name="twitter:card" content="summary">
<link rel="stylesheet" href="assets/board.css">
<link rel="stylesheet" href="assets/episode.css">
</head>
<body>
<main>
  <header class="top">
    <div>
      <h1>Quanty Quants</h1>
      <p class="sub">Podcast and video episodes, distilled into theses</p>
    </div>
    <nav class="nav" aria-label="Views">
      <a href="./">Leaderboard</a>
      <a href="chart.html">Chart</a>
      <a href="episodes.html"{{CUR}}>Episodes</a>
      <a href="coins.html">Coins</a>
    </nav>
  </header>
"""


NFA = ('<p class="nfa" id="nfa" data-field="nfa"><strong>Not financial advice.</strong> The stances on this page are the speakers\' '
       'expressions of opinion in a public episode, distilled and priced for analysis. They are not recommendations: nothing here is '
       'advice to buy, sell or hold anything, and past results say nothing about future ones.</p>')

LEGEND = ('<p class="legend"><span class="key">' + '<svg viewBox="0 0 26 26" width="22" height="22" aria-hidden="true">' + bubble(13, 13, "call", "bullish", 10)
          + '</svg> call: the speaker states a position or tells listeners to act now</span><span class="key"><svg viewBox="0 0 26 26" width="22" height="22" aria-hidden="true">'
          + bubble(13, 13, "thought", "bearish", 10) + '</svg> thought: a view or a reason for a move, no position stated</span>'
          '<span class="key">arrow: ↑ bullish · ↓ bearish · → wait / stand aside</span></p>')


def thesis_card(t, ep):
    p = t["price"]
    later = f' <span class="later">later {ARROW[t["later"]]} {e(WORD[t["later"]])}</span>' if t["later"] else ""
    move = ""
    if p["at_episode"]:
        move = (f'<p class="ep-px">at the episode <strong>{money(p["at_episode"]["price"])}</strong> '
                f'<span class="muted">({e(p["at_episode"]["at"][:16].replace("T", " "))} UTC)</span> → now <strong>{money(p["latest"]["price"])}</strong> '
                + (f'<span class="{tone(p["change"])}">{pct(p["change"])}</span>' if p["change"] is not None else '<span class="muted">no trading since the episode yet</span>')
                + (f' · <span class="{tone(p["with_lean"])}">{"with" if (p["with_lean"] or 0) >= 0 else "against"} the lean</span>' if p["with_lean"] is not None else "")
                + "</p>")
    proxy = f'<p class="muted small">priced with {e(p["source"])}:{e(p["symbol"])}' + (f' — {e(t["proxy"])}' if t["proxy"] else "") + "</p>"
    return (f'<article class="thesis panel" id="t-{e(t["asset"].lower())}">'
            f'<div class="t-head"><h3>{e(t["label"])}</h3><span class="lean {e(t["direction"])}">{ARROW[t["direction"]]} {e(WORD[t["direction"]])}</span>'
            f'<span class="kind {e(t["kind"])}">{"call" if t["kind"] == "call" else "thought"}</span>{later}</div>'
            f'<p class="t-text">{e(t["text"])}</p>{move}{chart(t, ep["reference_at"])}{proxy}'
            f'<p class="small"><a href="#m-{e(t["asset"].lower())}">{t["mentions"]} timestamped moment{"s" if t["mentions"] != 1 else ""}</a> · '
            f'{", ".join(e(m["t"]) for m in t["moments"])}</p></article>')


def moments_block(t):
    rows = []
    for m in t["moments"]:
        conf = "" if m["speaker_confidence"] == "high" else f' <span class="muted">(speaker {e(m["speaker_confidence"])} confidence)</span>'
        rows.append(f'<li class="moment"><span class="ts">{e(m["t"])}</span>'
                    f'<svg viewBox="0 0 26 26" width="24" height="24" aria-hidden="true">{bubble(13, 13, m["kind"], m["direction"], 10)}</svg>'
                    f'<div class="m-body"><p class="m-line"><strong>{"Call" if m["kind"] == "call" else "Thought"}</strong>, '
                    f'{e(WORD[m["direction"]])}, {e(m["horizon"])} · {e(m["speaker"])}{conf}</p>'
                    f'<blockquote>“{e(m["quote"])}”</blockquote><p class="m-reason">{e(m["reason"])}</p></div></li>')
    return (f'<section class="moments panel" id="m-{e(t["asset"].lower())}"><h3>{e(t["label"])} '
            f'<span class="lean {e(t["direction"])}">{ARROW[t["direction"]]} {e(WORD[t["direction"]])}</span></h3><ol>{"".join(rows)}</ol></section>')


def episode_page(ep):
    title = f'{ep["show"]}: {ep["title"]} · Quanty Quants'
    leans = "; ".join(f'{t["label"]} {WORD[t["direction"]]}' for t in ep["theses"])
    desc = f'{len(ep["theses"])} theses from {ep["show"]} ({ep["recorded_on"]}): {leans}.'
    link = (f'<a href="{e(ep["url"])}" rel="noopener noreferrer">the original episode</a>' if ep["url"]
            else f'<a href="{e(ep["show_url"])}" rel="noopener noreferrer">the show page</a> (episode link not added yet)' if ep.get("show_url")
            else "the original episode (link not added yet)")
    summary = "".join(f'<li><span class="ts">{e(s["t"])}</span> {e(s["text"])}</li>' for s in ep["summary"])
    chapters = " · ".join(f'{e(c["t"])} {e(c["title"])}' for c in ep["chapters"])
    calls = sum(1 for t in ep["theses"] for m in t["moments"] if m["kind"] == "call")
    thoughts = sum(1 for t in ep["theses"] for m in t["moments"] if m["kind"] == "thought")
    body = (head(title, desc, f'{SITE}episode-{ep["slug"]}.html').replace("{CUR}", "")
            + '  <p class="crumbs"><a href="episodes.html">← all episodes</a></p>\n'
            f'  <section class="ep-head panel"><p class="muted small">{e(ep["show"])} · recorded {e(ep["recorded_on"])} · {e(ep["duration"])} · '
            f'{" & ".join(e(s) for s in ep["speakers"])}</p><h2>{e(ep["title"])}</h2>'
            f'<p>Listen to {link}. Below: what was said, in our words, then every stance on a tradable asset with its timestamp.</p>'
            f'<h3 class="sec">1 · The episode in short</h3><ol class="summary">{summary}</ol>'
            f'<p class="muted small">Chapters: {chapters}</p></section>\n'
            f'  <h2 class="sec">2 · Theses</h2>\n  <p class="notes">{len(ep["theses"])} assets, {calls} calls and {thoughts} thoughts. '
            f'One thesis per asset, from every moment it came up. Price at the episode = last bar at or before {e(ep["reference_at"][:16].replace("T", " "))} UTC '
            f'({e(ep["reference_note"])}).</p>\n  {LEGEND}\n'
            f'  <div class="theses">{"".join(thesis_card(t, ep) for t in ep["theses"])}</div>\n'
            f'  <h2 class="sec">3 · Every moment, with the words said</h2>\n'
            f'  <p class="notes">Quotes are verbatim from the transcript; each was checked word for word against it, within 90 seconds of its timestamp. '
            f'Speakers are inferred (transcripts carry no names) and marked when unsure.</p>\n'
            f'  {"".join(moments_block(t) for t in ep["theses"])}\n'
            f'  <p class="notes">Method: the whole transcript was read by {e(ep["model"])} with the fixed prompt <code>{e(ep["prompt_version"])}</code>; '
            f'{ep["stances"]["accepted"]} stances passed the verifier, {ep["stances"]["rejected"]} were rejected. Episode stances are not rated and never count toward a caller score. '
            f'Transcript sha256 <code>{e(ep["transcript_sha256"])}</code>; extraction sha256 <code>{e(ep["extraction_sha256"])}</code>. '
            f'Data: <a href="data/episodes.json">data/episodes.json</a>.</p>\n'
            f'  {NFA}\n</main>\n</body>\n</html>\n')
    return body


def list_page(bundle):
    items = []
    for ep in bundle["episodes"]:
        chips = "".join(f'<span class="chip {e(t["direction"])}">{e(t["label"])} {ARROW[t["direction"]]}</span>' for t in ep["theses"])
        items.append(f'<li><a class="ep-row panel" href="episode-{e(ep["slug"])}.html"><span class="muted small">{e(ep["show"])} · {e(ep["recorded_on"])}</span>'
                     f'<strong>{e(ep["title"])}</strong><span class="chips">{chips}</span></a></li>')
    return (head("Episodes · Quanty Quants", "Podcast and video episodes distilled into timestamped theses on assets.", f"{SITE}episodes.html").replace("{CUR}", ' aria-current="page"')
            + '  <p class="notes">Each episode is read in full; every stance on a tradable asset is kept with its timestamp and verbatim words, '
              'then folded into one thesis per asset. Calls are solid bubbles, thoughts are dashed.</p>\n'
            + f'  <ol class="ep-list">{"".join(items)}</ol>\n  {NFA}\n</main>\n</body>\n</html>\n')


def write(bundle, web):
    os.makedirs(os.path.join(web, "data"), exist_ok=True)
    with open(os.path.join(web, "data", "episodes.json"), "w") as f:
        json.dump(bundle, f, indent=1)
        f.write("\n")
    keep = {"episodes.html"}
    for ep in bundle["episodes"]:
        name = f'episode-{ep["slug"]}.html'
        keep.add(name)
        with open(os.path.join(web, name), "w") as f:
            f.write(episode_page(ep))
    with open(os.path.join(web, "episodes.html"), "w") as f:
        f.write(list_page(bundle))
    for old in glob.glob(os.path.join(web, "episode-*.html")):
        if os.path.basename(old) not in keep:
            os.remove(old)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true", help="fetch price series again instead of using the cache")
    ap.add_argument("--offline", action="store_true", help="never fetch; fail if a series is not cached")
    ap.add_argument("--web", default=os.path.join(HERE, "web"))
    a = ap.parse_args(argv)
    bundle = build(refresh=a.refresh, offline=a.offline)
    write(bundle, a.web)
    for ep in bundle["episodes"]:
        print(f'{ep["slug"]}: {len(ep["theses"])} theses')
        for t in ep["theses"]:
            p = t["price"]
            ref = p["at_episode"]["price"] if p["at_episode"] else None
            print(f'  {t["label"]:<24} {t["kind"]:<7} {t["direction"]:<8} at episode {ref}  now {p["latest"]["price"] if p["latest"] else None}  {pct(p["change"])}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
