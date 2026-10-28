#!/usr/bin/env python3
"""Step 3: second author (@BobLoukas) next to goodalexander/Corbanu, identical scoring.

1. fetch hourly prices for the labelled instruments (Binance 1h BTCUSDT, Yahoo 1h for SPY, COPX,
   SI=F, GC=F) -> data/hourly_prices.json
2. resolve every labelled BobLoukas call: entry = open of the first hourly bar at/after the post,
   exit = open of the first bar at/after post + h days; an exit more than 2 days late, or past the
   last bar, is unresolved (same tolerance as step 1). signed_return = side * (Ph/P0 - 1),
   hit = signed_return > 0 (score.summarize, unchanged from step 1)
3. tag each call with the live pipeline regime (2-session gated) as of the call date
4. per-author comparison with minimum-sample flags -> data/author_comparison.json + AUTHORS.md

usage: python3 authors.py [--no-fetch]
"""
import bisect
import datetime as dt
import json
import os
import sys
import urllib.request

import gate
import score

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SRC = os.path.join(HERE, "sources", "bobloukas")
HORIZONS = score.HORIZONS
MAX_EXIT_LAG_DAYS = 2           # step 1 tolerance
MIN_N_RELIABLE = 30             # below: hit rate flagged unreliable
MIN_N_REPORTABLE = 10           # below: flagged insufficient
YAHOO = {"STOCKS": "SPY", "COPX": "COPX", "SILVER": "SI=F", "GOLD": "GC=F"}
START = dt.datetime(2026, 8, 30, tzinfo=dt.timezone.utc)


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def iso(ts):
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_hourly():
    bars = {}
    start_ms = int(START.timestamp() * 1000)
    btc = []
    while True:
        rows = get_json("https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1h"
                        f"&startTime={start_ms}&limit=1000")
        btc += [[iso(r[0] / 1000), float(r[1])] for r in rows]
        if len(rows) < 1000:
            break
        start_ms = rows[-1][0] + 3_600_000
    bars["BTC"] = btc
    p1, p2 = int(START.timestamp()), int(dt.datetime.now(dt.timezone.utc).timestamp())
    for inst, sym in YAHOO.items():
        res = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
                       f"?period1={p1}&period2={p2}&interval=1h")["chart"]["result"][0]
        opens = res["indicators"]["quote"][0]["open"]
        bars[inst] = [[iso(t), round(o, 4)] for t, o in zip(res["timestamp"], opens) if o is not None]
    json.dump(bars, open(os.path.join(DATA, "hourly_prices.json"), "w"), indent=0)
    return bars


def bar_at_or_after(series, when):
    times = [t for t, _ in series]
    i = bisect.bisect_left(times, when)
    return series[i] if i < len(series) else None


def lag_days(a, b):
    fa = dt.datetime.fromisoformat(a.replace("Z", "+00:00"))
    fb = dt.datetime.fromisoformat(b.replace("Z", "+00:00"))
    return (fb - fa).total_seconds() / 86400


def regime_tags():
    raw = json.load(open(os.path.join(HERE, "live", "raw_regimes.json")))
    seq = gate.apply_gate(sorted(raw.items()), 2)
    days = [s for s, *_ in seq]

    def tag(when):
        i = bisect.bisect_right(days, when[:10]) - 1
        return seq[i][2] if i >= 0 else "UNKNOWN"
    return tag


def resolve(bars, tag):
    labels = json.load(open(os.path.join(SRC, "labels.json")))
    rows = []
    for c in labels["calls"]:
        post = json.load(open(os.path.join(SRC, "receipts", f"{c['id']}.json")))
        when = post["postedAt"].replace(".000Z", "Z")
        series = bars[c["instrument"]]
        entry = bar_at_or_after(series, when)
        side = 1 if c["side"] == "long" else -1
        row = {"post_id": c["id"], "url": post["url"], "posted_at": when, "author": "BobLoukas",
               "instrument": c["instrument"], "price_source": labels["rules"]["instruments"][c["instrument"]],
               "side": side, "status": c["status"], "reiteration_of": c.get("of"), "pair_id": c.get("pair_id"),
               "conditional": bool(c.get("conditional")), "stop": c.get("stop"), "target": c.get("target"),
               "regime": tag(when), "note": c["note"], "entry": None, "exits": {}, "returns": {},
               "unresolved": {}}
        if entry is None or lag_days(when, entry[0]) > MAX_EXIT_LAG_DAYS:
            row["unresolved"] = {str(h): "no entry bar within 2 days" for h in HORIZONS}
        else:
            row["entry"] = {"at": entry[0], "price": entry[1]}
            for h in HORIZONS:
                target = (dt.datetime.fromisoformat(when.replace("Z", "+00:00")) + dt.timedelta(days=h)
                          ).strftime("%Y-%m-%dT%H:%M:%SZ")
                ex = bar_at_or_after(series, target)
                if ex is None:
                    row["exits"][str(h)], row["returns"][str(h)] = None, None
                    row["unresolved"][str(h)] = "horizon not yet reached"
                elif lag_days(target, ex[0]) > MAX_EXIT_LAG_DAYS:
                    row["exits"][str(h)], row["returns"][str(h)] = None, None
                    row["unresolved"][str(h)] = f"first bar {ex[0]} is >2 days after {target} (market closed)"
                else:
                    row["exits"][str(h)] = {"at": ex[0], "price": ex[1]}
                    row["returns"][str(h)] = side * (ex[1] / entry[1] - 1)
        rows.append(row)
    return labels, rows


def pairs(rows):
    out = {}
    for r in rows:
        if r["pair_id"]:
            out.setdefault(r["pair_id"], []).append(r)
    result = []
    for pid, legs in out.items():
        rets = {}
        for h in map(str, HORIZONS):
            vals = [l["returns"].get(h) for l in legs]
            rets[h] = None if any(v is None for v in vals) else sum(vals) / len(vals)  # equal weight: none stated
        result.append({"pair_id": pid, "author": "BobLoukas", "posted_at": legs[0]["posted_at"],
                       "legs": [f'{l["instrument"]} {"long" if l["side"] > 0 else "short"}' for l in legs],
                       "weighting": "equal (no weights stated)", "returns": rets})
    return result


def flagged(summ):
    n = summ["n"]
    flag = "insufficient" if n < MIN_N_REPORTABLE else ("unreliable" if n < MIN_N_RELIABLE else "ok")
    return {**summ, "sample_flag": flag}


def main():
    bars = json.load(open(os.path.join(DATA, "hourly_prices.json"))) if "--no-fetch" in sys.argv else fetch_hourly()
    labels, rows = resolve(bars, regime_tags())
    scored = [r for r in rows if r["status"] == "call"]
    pr = pairs(rows)
    corbanu = json.load(open(os.path.join(DATA, "new_system_resolved.json")))
    authors = {
        "goodalexander/Corbanu": {"calls": corbanu["calls"], "pairs": corbanu["pairs"]},
        "BobLoukas": {"calls": scored, "pairs": pr},
    }
    comparison = {"min_n_reliable": MIN_N_RELIABLE, "min_n_reportable": MIN_N_REPORTABLE,
                  "exit_lag_tolerance_days": MAX_EXIT_LAG_DAYS, "authors": {}}
    for name, a in authors.items():
        regs = sorted({c["regime"] for c in a["calls"]})
        comparison["authors"][name] = {
            "calls": len(a["calls"]),
            "by_horizon": {h: flagged(score.summarize(a["calls"], h)) for h in HORIZONS},
            "pairs_by_horizon": {h: flagged(score.summarize(a["pairs"], h)) for h in HORIZONS},
            "by_regime": {g: {h: flagged(score.summarize([c for c in a["calls"] if c["regime"] == g], h))
                              for h in HORIZONS} for g in regs},
        }
    comparison["bobloukas_counts"] = {
        "own_posts_captured": len(json.load(open(os.path.join(SRC, "posts_index.json")))["posts"]),
        "labelled_rows": len(rows), "scored_calls": len(scored),
        "reiterations": sum(r["status"] == "reiteration" for r in rows),
        "excluded_with_reason": len(labels["excluded"]),
        "unresolved_cells": sum(len(r["unresolved"]) for r in scored),
    }
    json.dump(rows, open(os.path.join(DATA, "bobloukas_calls.json"), "w"), indent=1)
    json.dump(pr, open(os.path.join(DATA, "bobloukas_pairs.json"), "w"), indent=1)
    json.dump(comparison, open(os.path.join(DATA, "author_comparison.json"), "w"), indent=1)
    print(json.dumps(comparison["bobloukas_counts"]))
    for name, a in comparison["authors"].items():
        print(name, {h: (v["n"], v["hit_rate"], v["mean_signed_return"], v["sample_flag"]) for h, v in a["by_horizon"].items()})


if __name__ == "__main__":
    main()
