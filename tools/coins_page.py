#!/usr/bin/env python3
"""Step 23: the coin coverage page (web/coins.html) and its data (web/data/coins.json), built from
data/tickers.json, the latest seed receipt (sources/tickers/seed/) and the latest weekly re-check
(sources/tickers/recheck/). Static: no JS, the site's CSP, every value escaped.

usage: python3 tools/coins_page.py
"""
import glob
import hashlib
import html
import json
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TOOLS)
SITE = "https://sendoeth.com/pf-post-signals/web/"
e = lambda s: html.escape(str(s), quote=True)

NFA = ('<p class="nfa" id="nfa" data-field="nfa"><strong>Not financial advice.</strong> This page lists which coins the site can price and how '
       'each price source was checked. Nothing here is a recommendation to buy, sell or hold anything.</p>')


def latest(pattern):
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def load(path):
    with open(path) as f:
        return json.load(f)


def build(root=HERE):
    reg = load(os.path.join(root, "data", "tickers.json"))
    seed_p = latest(os.path.join(root, "sources", "tickers", "seed", "*.json"))
    seed = load(seed_p) if seed_p else {"counts": {}, "top_listed": [], "top": [], "perps": [], "excluded": [], "review": [], "coins": {}}
    re_p = latest(os.path.join(root, "sources", "tickers", "recheck", "*.json"))
    rec = load(re_p) if re_p else None
    words_p = os.path.join(root, "data", "coin_words.json")
    words = load(words_p) if os.path.exists(words_p) else {"index": {}}
    rows = []
    for t, x in reg["tickers"].items():
        sc = seed["coins"].get(t, {})
        chosen = next((v for v in sc.get("venues", []) if v.get("ok") and (v["source"], v.get("symbol")) == (x["source"], x["symbol"])), None)
        if not chosen and os.path.exists(os.path.join(root, x["receipt"])):        # added by a post: the check from its own receipt
            chosen = next((v for v in load(os.path.join(root, x["receipt"])).get("venues", [])
                           if v.get("ok") and (v["source"], v.get("symbol")) == (x["source"], x["symbol"])), None)
        rows.append({"ticker": t, "name": x["name"], "coingecko_id": x["coingecko_id"], "rank": x.get("rank"),
                     "venue": f'{x["source"]}:{x["symbol"]}' + (f' ({x["pair"]})' if x.get("pair") else ""),
                     "seed_diff": chosen and chosen.get("diff"), "in_top": t in seed["top"], "hl_perp": bool(x.get("hl_perp")),
                     "also_us_stock": x.get("also_us_stock"), "flag": x.get("flag"), "checked_at": x.get("checked_at") or x.get("added_at"),
                     "receipt": x["receipt"]})
    rows.sort(key=lambda r: (r["rank"] or 10 ** 6, r["ticker"]))
    top_listed = seed["top_listed"]
    review_top = [r for r in seed["review"] if r["ticker"] in top_listed]
    early_p = os.path.join(root, "web", "data", "early.json")
    early = load(early_p)["signals"] if os.path.exists(early_p) else []
    data = {"schema": "quanty.coins.v1", "early_signals": early, "registry_sha256": hashlib.sha256(open(os.path.join(root, "data", "tickers.json"), "rb").read()).hexdigest(),
            "seed": os.path.relpath(seed_p, root) if seed_p else None, "seeded_at": seed.get("seeded_at"),
            "recheck": os.path.relpath(re_p, root) if re_p else None, "rechecked_at": rec and rec["checked_at"],
            "coverage": {"top_listed": len(top_listed), "top_seeded": len([t for t in top_listed if t in reg["tickers"]]),
                         "perps_added": len(seed["perps"]), "registered": len(reg["tickers"]), "flagged": sum(1 for r in rows if r["flag"]),
                         "review": len(seed["review"]), "excluded": len(seed["excluded"])},
            "coins": rows, "review": seed["review"], "excluded": seed["excluded"], "indexes": words.get("index", {})}
    return data


def pct_px(p):
    return "–" if p is None else (f"${p:,.2f}" if p >= 1 else f"${p:.6g}")


def page(d):
    c = d["coverage"]
    def pct(x):
        return "–" if x is None else f"{x * 100:+.2f}%"
    trs = "".join(
        f'<tr data-ticker="{e(r["ticker"])}"{" class=flagged" if r["flag"] else ""}><td>{e(r["rank"] or "–")}</td><td><strong>{e(r["ticker"])}</strong>'
        + (f' <a href="#early-{e(r["ticker"])}" class="small">early signal</a>' if r["ticker"] in {x["asset"] for x in d.get("early_signals", [])} else "") + '</td>'
        f'<td>{e(r["name"])} <span class="muted">[{e(r["coingecko_id"])}]</span></td><td>{e(r["venue"])}</td><td>{e(pct(r["seed_diff"]))}</td>'
        f'<td>{"top 100" if r["in_top"] else "perp" if r["hl_perp"] else "added by a post"}</td>'
        f'<td>{"FLAGGED: " + e(r["flag"]["why"]) if r["flag"] else "ok"}{" · also US stock: " + e(r["also_us_stock"]) if r["also_us_stock"] else ""}</td></tr>'
        for r in d["coins"])
    rev = "".join(f'<li><strong>{e(r["ticker"])}</strong> {e(r.get("name") or "")}{" (#" + e(r["rank"]) + ")" if r.get("rank") else ""}: {e(r["why"])}</li>' for r in d["review"])
    exc = "".join(f'<li><strong>{e(r["ticker"])}</strong> {e(r["name"])} (#{e(r["rank"])}): {e(r["why"])}'
                  + (f' → write it as ${e(r["maps_to"])}' if r.get("maps_to") else "") + "</li>" for r in d["excluded"])
    idx = "".join(f"<li><strong>{e(k)}</strong>: {e(v)}</li>" for k, v in d["indexes"].items())
    early = ""
    for asset in sorted({x["asset"] for x in d.get("early_signals", [])}):
        rows = ""
        for x in sorted((x for x in d["early_signals"] if x["asset"] == asset), key=lambda x: x["post"]["posted_at"]):
            pr, th = x["prices"], x["prices"]["then"]
            rows += (f'<li data-handle="{e(x["handle"])}"><strong>@{e(x["handle"])}</strong> first named {e(asset)} on {e(x["post"]["posted_at"][:10])} '
                     f'({e(x["label"]["label"])}): {e(pct_px(th["price"]))} on {e(th["source"])}:{e(th["symbol"])}'
                     + (" (before listing)" if th["before_listing"] else "")
                     + f' → {e(pct_px(pr["now"]["price"]))} now, <strong>{pr["multiple_now"]:,.2f}x</strong>, peak {pr["multiple_peak"]:,.2f}x on {e(pr["peak"]["day"])}. '
                     f'“{e(" ".join(x["post"]["text"].split())[:200])}” · <a href="{e(x["post"]["url"])}" rel="noopener noreferrer">post</a> · '
                     f'<a href="caller-{e(x["handle"].lower())}.html#early-{e(asset)}">caller page</a>'
                     + (f' · first recorded call {e(x["first_call"]["call"]["posted_at"][:10])}, {x["first_call"]["days"]:,.0f} days later, '
                        f'{x["first_call"]["price_move_before_call"]:,.2f}x the first-post price' if (x.get("first_call") or {}).get("after_first_mention") else "")
                     + '</li>')
        early += f'<h3 class="sec" id="early-{e(asset)}">{e(asset)}</h3><ul class="plain">{rows}</ul>'
    if early:
        early = ('<h2 class="sec">Early signals</h2><p class="notes">The first post where a tracked account named a coin, priced then and now. '
                 'Score-neutral: an early signal is not a call and never changes a score.</p>' + early)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; manifest-src 'none'; media-src 'none'; font-src 'none'; upgrade-insecure-requests">
<meta name="referrer" content="no-referrer">
<script src="assets/frame-guard.js"></script>
<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Coins · Quanty Quants</title>
<meta name="description" content="{e(c['top_seeded'])} of the top {e(c['top_listed'])} coins and {e(c['perps_added'])} Hyperliquid perps priced from checked venues.">
<link rel="stylesheet" href="assets/board.css">
<link rel="stylesheet" href="assets/episode.css">
</head>
<body>
<main>
  <header class="top">
    <div>
      <h1>Quanty Quants</h1>
      <p class="sub">Coins the site can price, and how each price source was checked</p>
    </div>
    <nav class="nav" aria-label="Views">
      <a href="./">Leaderboard</a>
      <a href="chart.html">Chart</a>
      <a href="episodes.html">Episodes</a>
      <a href="coins.html" aria-current="page">Coins</a>
      <a href="agreement.html">Agreement</a>
    </nav>
  </header>
  <section class="ep-head panel" data-field="coverage">
    <h2>{e(c['top_seeded'])} of the top {e(c['top_listed'])} coins · {e(c['perps_added'])} Hyperliquid perps · {e(c['registered'])} tickers</h2>
    <p>A post naming any of these coins (cashtag, name, or ticker in capitals) is priced at once, without a lookup. Each coin is identified on CoinGecko,
    and priced on the first venue with hourly bars whose pair is trading and within 5% of the coin's price (Binance, then Hyperliquid, OKX, Gate,
    then Hyperliquid spot: a pair quoted in a USD stablecoin with trades in the last 24 hours; last, a DEX pool found through the coin's own
    contract, with at least $100,000 of liquidity and current hourly candles). A ticker two coins share is never guessed: the owner picks the coin.
    Stablecoins, wrapped / staked copies and tokenized funds, gold and stocks are not coins here and are skipped; the top 100 is counted after them.
    A weekly re-check flags any venue that stops trading or drifts away from the coin's price; a venue is never swapped silently.</p>
    <p class="muted small">Seeded {e(d['seeded_at'] or '–')} ({e(d['seed'] or '–')}) · re-checked {e(d['rechecked_at'] or 'not yet')}
    · {e(c['flagged'])} flagged · {e(c['review'])} to review · {e(c['excluded'])} excluded · data: <a href="data/coins.json">data/coins.json</a></p>
  </section>
  <h2 class="sec">Coins</h2>
  <div class="panel tablewrap"><table class="coins">
    <thead><tr><th>Rank</th><th>Ticker</th><th>Coin</th><th>Venue</th><th>Seed check</th><th>Why listed</th><th>Weekly status</th></tr></thead>
    <tbody>{trs}</tbody></table></div>
  {early}
  <h2 class="sec">To review ({e(len(d['review']))})</h2>
  <p class="notes">Not guessed: each needs a decision (or a venue the site does not use yet).</p>
  <ul class="plain">{rev}</ul>
  <h2 class="sec">Not coins ({e(len(d['excluded']))})</h2>
  <ul class="plain">{exc}</ul>
  <h2 class="sec">Market indexes</h2>
  <p class="notes">Recognised in posts so they are never read as a coin; they go to review until the site has a price history source for them.</p>
  <ul class="plain">{idx}</ul>
  {NFA}
</main>
</body>
</html>
"""


def main(root=HERE):
    d = build(root)
    with open(os.path.join(root, "web", "data", "coins.json"), "w") as f:
        json.dump(d, f, indent=1)
        f.write("\n")
    with open(os.path.join(root, "web", "coins.html"), "w") as f:
        f.write(page(d))
    c = d["coverage"]
    print(f"coins page: {c['top_seeded']}/{c['top_listed']} top, {c['perps_added']} perps, {c['registered']} tickers, {c['flagged']} flagged, {c['review']} review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
