#!/usr/bin/env python3
"""Step 7: hourly OHLC candles per asset for the position pages (display only).

For every asset in web/data/charts.json: fetch 1h candles from the same source and symbol the
records use (Binance klines, Yahoo chart), from one day before the earliest entry to now, and write
web/data/ohlc/<asset>.json plus web/data/ohlc/index.json (sha256, fetch time, bar count per file).
Yahoo opens are rounded to 4 decimals and Binance opens parsed as floats, exactly as resolve.py
does, so every drawn record's entry bar can be checked: candle open == record entry price.
Candles never feed a recap value; the records stay the only source of entry, moves and best %.

usage: python3 fetch_ohlc.py [--check-only]   (exit 1 if any entry bar disagrees)
"""
import datetime as dt
import hashlib
import json
import os
import sys

import resolve

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "web", "data", "ohlc")


def fetch(source, symbol, since):
    start = resolve.parse(since).replace(minute=0, second=0, microsecond=0)
    if source == "binance":
        out, ms = [], int(start.timestamp() * 1000)
        while True:
            rows = resolve.get_json("https://data-api.binance.vision/api/v3/klines?symbol="
                                    f"{symbol}&interval=1h&startTime={ms}&limit=1000")
            out += [[resolve.iso(r[0] / 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in rows]
            if len(rows) < 1000:
                return out
            ms = rows[-1][0] + 3_600_000
    p1 = int(start.timestamp())
    p2 = int(dt.datetime.now(dt.timezone.utc).timestamp())
    res = resolve.get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                           f"?period1={p1}&period2={p2}&interval=1h")["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    return [[resolve.iso(t), round(o, 4), round(h, 4), round(lo, 4), round(c, 4)]
            for t, o, h, lo, c in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"])
            if None not in (o, h, lo, c)]


def check(bundle, candles_by_asset):
    """Entry candle open == record entry price. The only accepted difference is a provider revision
    that refresh.py logged for that bar (the record keeps the frozen value, the candle shows the
    provider's current one)."""
    revised = set()
    log_path = os.path.join(HERE, "data", "refresh_log.json")
    if os.path.exists(log_path):
        with open(log_path) as f:
            revised = {(r["bar"], r["fetched"]) for r in json.load(f)["revisions"] if r["what"] == "entry"}
    rows, fails = [], []
    for a in bundle["assets"]:
        opens = {c[0]: c[1] for c in candles_by_asset.get(a["name"], [])}
        for p in a["posts"]:
            if not p["entry"]:
                continue
            got = opens.get(p["entry"]["at"])
            ok = got == p["entry"]["price"] or (p["entry"]["at"], got) in revised
            rows.append((a["name"], p["post"]["id"], p["entry"]["at"], p["entry"]["price"], got, ok))
            if not ok:
                fails.append(f"{a['name']} {p['post']['id']}: candle open at {p['entry']['at']} is {got}, record entry {p['entry']['price']}")
    return rows, fails


def main():
    with open(os.path.join(HERE, "web", "data", "charts.json")) as f:
        bundle = json.load(f)
    os.makedirs(OUT, exist_ok=True)
    candles, index = {}, {"schema": "pf-post-signals.ohlc_index.v1", "files": {}}
    if "--check-only" in sys.argv:
        with open(os.path.join(OUT, "index.json")) as f:
            index = json.load(f)
        for name, meta in index["files"].items():
            with open(os.path.join(OUT, meta["file"])) as f:
                candles[name] = json.load(f)["candles"]
    else:
        for a in bundle["assets"]:
            since = min(p["entry"]["at"] for p in a["posts"] if p["entry"])
            since = (resolve.parse(since) - dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            fetched_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            c = fetch(a["source"], a["symbol"], since)
            candles[a["name"]] = c
            path = os.path.join(OUT, f"{a['name']}.json")
            doc = {"asset": a["name"], "source": a["source"], "symbol": a["symbol"], "interval": "1h",
                   "fetched_at": fetched_at, "fields": ["t", "open", "high", "low", "close"], "candles": c}
            with open(path, "w") as f:
                json.dump(doc, f, separators=(",", ":"))
                f.write("\n")
            with open(path, "rb") as f:
                sha = hashlib.sha256(f.read()).hexdigest()
            index["files"][a["name"]] = {"file": f"{a['name']}.json", "sha256": sha, "fetched_at": fetched_at,
                                         "bars": len(c), "first": c[0][0], "last": c[-1][0]}
            print(f"{a['name']:<7} {a['source']}:{a['symbol']:<8} {len(c)} candles {c[0][0]} -> {c[-1][0]} sha256 {sha}")
        with open(os.path.join(OUT, "index.json"), "w") as f:
            json.dump(index, f, indent=1)
            f.write("\n")
    rows, fails = check(bundle, candles)
    for name, pid, at, want, got, ok in rows:
        print(f"{'OK  ' if ok else 'DIFF'} {name:<7} {pid} entry {at} record {want} candle open {got}")
    print(f"entry bars: {sum(r[5] for r in rows)}/{len(rows)} candle opens equal the record entry price")
    for x in fails:
        print(" -", x)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
