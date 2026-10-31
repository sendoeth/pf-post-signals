#!/usr/bin/env python3
"""Step 7: hourly OHLC candles per asset for the position pages (display only).

For every asset in web/data/charts.json: fetch candles from the same source and symbol the records
use (Binance klines, Yahoo chart, Hyperliquid candleSnapshot), from a lookback before the earliest
entry to now, and write web/data/ohlc/<asset>.json plus web/data/ohlc/index.json (sha256, fetch
time, bar count, lookback per file).
Step 14 lookback: max(90 days, the span between the asset's first and last call) before the first
call, so the chart shows what the price did before anyone called it. Hourly where the source has it,
daily bars before that (Yahoo: ~730 days of hourly; Hyperliquid: ~5000 hours of hourly); the file's
daily_until says where daily bars end. A market listed after the lookback start begins at its first
bar (lookback.starts_at_listing). Pre-call bars are display only: no record value reads them.
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


LOOKBACK_MIN_DAYS = 90


def lookback(posts):
    """(days, start iso) for an asset's posts: max(90 days, first-to-last call span) before the first entry."""
    # a post with no price after it yet (market closed) counts from its post time
    entries = sorted(p["entry"]["at"] if p["entry"] else p["post"]["posted_at"] for p in posts)
    span = (resolve.parse(entries[-1]) - resolve.parse(entries[0])).total_seconds() / 86400
    days = max(LOOKBACK_MIN_DAYS, int(span) + 1)
    return days, (resolve.parse(entries[0]) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def ohlc(c):
    return [resolve.iso(c["t"] / 1000), float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"])]


def fetch(source, symbol, since):
    """-> (candles, daily_until): daily_until is the time before which the candles are daily bars."""
    start = resolve.parse(since).replace(minute=0, second=0, microsecond=0)
    if source == "hyperliquid":
        hourly = [ohlc(c) for c in resolve.hyperliquid_candles(symbol, start)]
        daily_until = None
        if resolve.parse(hourly[0][0]) - start > dt.timedelta(days=1):
            # hourly history ends ~5000 hours back: daily bars before that (none before the listing)
            first = resolve.parse(hourly[0][0])
            try:
                daily = [ohlc(c) for c in resolve.hyperliquid_candles(symbol, start, "1d", first)]
            except resolve.UnknownAssetError:
                daily = []
            daily = [b for b in daily if b[0] < hourly[0][0] and resolve.parse(b[0]) + dt.timedelta(days=1) <= first]
            if daily:
                daily_until = hourly[0][0]
            hourly = daily + hourly
        return resolve.adjust_for_actions(symbol, hourly), daily_until
    if source == "binance":
        out, ms = [], int(start.timestamp() * 1000)
        while True:
            rows = resolve.get_json("https://data-api.binance.vision/api/v3/klines?symbol="
                                    f"{symbol}&interval=1h&startTime={ms}&limit=1000")
            out += [[resolve.iso(r[0] / 1000), float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in rows]
            if len(rows) < 1000:
                return out, None
            ms = rows[-1][0] + 3_600_000
    # Yahoo: hourly for ~730 days back; whole daily bars before the first hourly bar, none overlapping it
    now, cutoff = dt.datetime.now(dt.timezone.utc), resolve.yahoo_hourly_from()
    hourly = resolve.yahoo_chart(symbol, max(start, cutoff) - dt.timedelta(days=1), now, "1h")
    if not hourly:
        raise resolve.UnknownAssetError(f"no yahoo data for {symbol}")
    hourly = sorted(dict((b[0], b) for b in hourly).values())
    daily = []
    if start < cutoff:
        first = resolve.parse(hourly[0][0])
        daily = [b for b in resolve.yahoo_chart(symbol, start - dt.timedelta(days=1), cutoff, "1d")
                 if resolve.parse(b[0]) + dt.timedelta(days=1) <= first]
        daily = sorted(dict((b[0], b) for b in daily).values())
    return daily + hourly, (hourly[0][0] if daily else None)


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
            days, since = lookback(a["posts"])
            fetched_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            c, daily_until = fetch(a["source"], a["symbol"], since)
            candles[a["name"]] = c
            path = os.path.join(OUT, f"{a['name']}.json")
            first_call = min(p["entry"]["at"] if p["entry"] else p["post"]["posted_at"] for p in a["posts"])
            lb = {"days": days, "start": since, "first_call": first_call, "first_bar": c[0][0],
                  "starts_at_listing": c[0][0] > resolve.iso((resolve.parse(since) + dt.timedelta(days=4)).timestamp())}
            doc = {"asset": a["name"], "source": a["source"], "symbol": a["symbol"], "interval": "1h",
                   "daily_until": daily_until, "lookback": lb,
                   "fetched_at": fetched_at, "fields": ["t", "open", "high", "low", "close"], "candles": c}
            with open(path, "w") as f:
                json.dump(doc, f, separators=(",", ":"))
                f.write("\n")
            with open(path, "rb") as f:
                sha = hashlib.sha256(f.read()).hexdigest()
            index["files"][a["name"]] = {"file": f"{a['name']}.json", "sha256": sha, "fetched_at": fetched_at,
                                         "bars": len(c), "first": c[0][0], "last": c[-1][0],
                                         "daily_until": daily_until, "lookback": lb}
            print(f"{a['name']:<10} {a['source']}:{a['symbol']:<11} {len(c)} candles {c[0][0]} -> {c[-1][0]} lookback {days}d from {since}"
                  f"{' (market listed later: starts at its first bar)' if lb['starts_at_listing'] else ''}"
                  f"{' daily before ' + daily_until if daily_until else ''} sha256 {sha}")
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
