#!/usr/bin/env python3
"""Step 9: daily refresh. Every record is re-resolved from its receipt with fresh hourly prices,
the candles are refetched and the chart bundle is rebuilt.

Frozen values: a record's entry bar and every horizon it has already resolved never change. Before
re-resolving, those bars are written back into the fetched series; if the provider now reports a
different price (a revision) or has dropped the bar, the frozen value is kept and the difference
is logged. Everything else is recomputed from the fresh bars: latest price, % since post, best
since post, and horizons that have now been reached. A post without a receipt falls back to its
URL (snowflake time), and the side stated in the existing record is kept.

Writes records (in place), web/data/ohlc/*, web/data/charts.json and data/refresh_log.json.
Exit 1 (and the workflow commits nothing) on any fetch, schema or invariant failure.

usage: python3 refresh.py
"""
import datetime as dt
import glob
import json
import os
import sys

import build_chart
import resolve

HERE = os.path.dirname(os.path.abspath(__file__))
HORIZONS = [str(h) for h in resolve.HORIZONS]


def receipt_for(post_id):
    hits = sorted(glob.glob(os.path.join(HERE, "sources", "*", "receipts", f"{post_id}.json")))
    return os.path.relpath(hits[0], HERE) if hits else None


def frozen_bars(old):
    """(time, price, what) for every value that must not change."""
    out = []
    if old.get("entry"):
        out.append((old["entry"]["at"], old["entry"]["price"], "entry"))
        for h in HORIZONS:
            if old["moves"].get(h) is not None and old["exits"].get(h):
                out.append((old["exits"][h]["at"], old["exits"][h]["price"], f"{h}d exit"))
    return out


def patched(series, frozen, revisions, label):
    """The fetched series with every frozen bar written back (and each difference logged)."""
    bars = {t: p for t, p in series}
    for t, p, what in frozen:
        if t not in bars:
            revisions.append({"record": label, "bar": t, "what": what, "frozen": p, "fetched": None,
                              "note": "bar missing from the provider's series; frozen value kept"})
        elif bars[t] != p:
            revisions.append({"record": label, "bar": t, "what": what, "frozen": p, "fetched": bars[t],
                              "note": "provider revision; frozen value kept"})
        bars[t] = p
    return sorted(bars.items())


def main():
    started = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    v = resolve.validator()
    files = sorted(glob.glob(os.path.join(HERE, "records", "**", "*.json"), recursive=True))
    olds = []
    for f in files:
        with open(f) as fh:
            olds.append((os.path.relpath(f, HERE), json.load(fh)))
    olds.sort(key=lambda x: x[1]["post"]["posted_at"])      # earliest first: one fetch per asset
    prices = resolve.Prices()
    revisions, changes, failures = [], [], []
    for rel, old in olds:
        try:
            post = resolve.load_post(url=old["post"]["url"], receipt=receipt_for(old["post"]["id"]))
            asset = resolve.asset_info(old["asset"]["name"])
            series = prices.series(asset, post["posted_at"])
            series = patched(series, frozen_bars(old), revisions, rel)
            new = resolve.resolve(post, asset, [list(b) for b in series], prices.label, old.get("side"))
            resolve.check_record(v, new)
            problems = build_chart.record_problems(v, new)
            for t, p, what in frozen_bars(old):           # frozen values really are unchanged
                key = "entry" if what == "entry" else what.split("d ")[0]
                got = new["entry"] if key == "entry" else new["exits"].get(key)
                if got != {"at": t, "price": p}:
                    problems.append(f"frozen {what} changed: {got} != {t} {p}")
            if problems:
                raise resolve.ResolveError("; ".join(problems))
        except (resolve.ResolveError, OSError, ValueError, KeyError) as e:
            failures.append(f"{rel}: {e}")
            continue
        filled = [h for h in HORIZONS if old["moves"].get(h) is None and new["moves"].get(h) is not None]
        changes.append({"record": rel, "post_id": new["post"]["id"], "asset": new["asset"]["name"],
                        "latest_before": old.get("latest"), "latest_after": new["latest"],
                        "since_post_before": old.get("change_since_post"), "since_post_after": new["change_since_post"],
                        "horizons_filled": filled, "status": f"{old['status']} -> {new['status']}"})
        with open(os.path.join(HERE, rel), "w") as fh:
            json.dump(new, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    finished = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log = {"schema": "pf-post-signals.refresh_log.v1", "refreshed_at": finished, "started_at": started,
           "records": len(olds), "refreshed": len(changes), "failures": failures, "revisions": revisions,
           "horizons_filled": sum(len(c["horizons_filled"]) for c in changes), "changes": changes}
    if failures:
        for x in failures:
            print("FAIL", x)
        print(f"refresh: {len(failures)} failures, nothing written for those records; refresh log not updated")
        sys.exit(1)
    with open(os.path.join(HERE, "data", "refresh_log.json"), "w") as fh:
        json.dump(log, fh, indent=1)
        fh.write("\n")
    for c in changes:
        lb, la = c["latest_before"], c["latest_after"]
        print(f"{c['asset']:<7} {c['post_id']} latest {lb['price'] if lb else '-'} @ {lb['at'][:16] if lb else '-'} -> "
              f"{la['price'] if la else '-'} @ {la['at'][:16] if la else '-'}; since post {resolve.pct(c['since_post_before'])} -> "
              f"{resolve.pct(c['since_post_after'])}; filled {c['horizons_filled'] or '-'}; {c['status']}")
    for r in revisions:
        print(f"REVISION {r['record']} {r['what']} {r['bar']}: frozen {r['frozen']} fetched {r['fetched']} ({r['note']})")
    print(f"refresh {finished}: {len(changes)}/{len(olds)} records refreshed, {log['horizons_filled']} horizons filled, "
          f"{len(revisions)} provider revisions logged (frozen values kept), 0 failures")


if __name__ == "__main__":
    main()
