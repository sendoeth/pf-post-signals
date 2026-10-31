#!/usr/bin/env python3
"""Step 14: the values a display change must never move.

For every position in a charts.json bundle: post id + asset -> entry bar, closed block (exit, move,
for_call), lifecycle event bars, and every horizon move / signed return that is already resolved.
Pre-call candle history is display only, so the bundle after step 14 must give the same values as
the bundle before it.

usage:
  python3 tools/frozen_values.py dump [charts.json] > baseline.json
  python3 tools/frozen_values.py compare baseline.json [charts.json]   (exit 1 on any change)
A horizon that was unresolved in the baseline may resolve later (a daily refresh); one that was
resolved may never change or disappear.
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(HERE, "web", "data", "charts.json")


def frozen(bundle):
    out = {}
    for a in bundle["assets"]:
        for p in a["posts"]:
            out[f'{p["post"]["id"]}|{a["name"]}'] = {
                "entry": p.get("entry"),
                "closed": p.get("closed"),
                "lifecycle_bars": [[ev["post"]["id"], ev["type"], ev.get("bar")] for ev in (p.get("lifecycle") or {}).get("events", [])],
                "moves": {h: v for h, v in (p.get("moves") or {}).items() if v is not None},
                "signed_returns": {h: v for h, v in (p.get("signed_returns") or {}).items() if v is not None},
            }
    return out


def load(path):
    with open(path) as f:
        return json.load(f)


def compare(base, now):
    diffs = []
    for key, b in base.items():
        n = now.get(key)
        if n is None:
            diffs.append(f"{key}: missing now")
            continue
        for k in ("entry", "closed", "lifecycle_bars"):
            if b[k] != n[k]:
                diffs.append(f"{key}: {k} {b[k]} -> {n[k]}")
        for k in ("moves", "signed_returns"):
            for h, v in b[k].items():
                if n[k].get(h) != v:
                    diffs.append(f"{key}: {k}[{h}] {v} -> {n[k].get(h)}")
    return diffs


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dump"
    if cmd == "dump":
        print(json.dumps(frozen(load(sys.argv[2] if len(sys.argv) > 2 else BUNDLE)), indent=1, sort_keys=True))
        return
    base = load(sys.argv[2])
    now = frozen(load(sys.argv[3] if len(sys.argv) > 3 else BUNDLE))
    diffs = compare(base, now)
    vals = sum(1 + bool(v["closed"]) + len(v["lifecycle_bars"]) + len(v["moves"]) + len(v["signed_returns"]) for v in base.values())
    print(f"positions {len(base)} (now {len(now)}), frozen values compared {vals}, changed {len(diffs)}")
    print("sha256 of the frozen values now:", hashlib.sha256(json.dumps(now, sort_keys=True).encode()).hexdigest())
    for d in diffs:
        print(" -", d)
    sys.exit(1 if diffs else 0)


if __name__ == "__main__":
    main()
