#!/usr/bin/env python3
"""Step 5: build the chart bundle (web/data/charts.json) from step 4 post_price.v1 records.

Every records/**/*.json file is checked with the step 4 rules (schema/post_price.v1.json plus the
record invariants in validate_records.py). A record that fails is refused with its reasons and
never drawn. The same (post, asset) in two files is drawn once: the record with the later last bar
wins, the other is listed as superseded. Per asset, the price line is the union of the records'
hourly series; two records disagreeing on a bar's price refuses the build for that asset.

usage: python3 build_chart.py [--records DIR] [--out FILE]
"""
import argparse
import glob
import hashlib
import json
import os
import sys

import resolve

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLE_SCHEMA = "pf-post-signals.charts.v1"


def record_problems(v, r):
    """Schema errors + the validate_records.py invariants, as readable strings."""
    out = [f"schema: {'/'.join(map(str, e.path)) or '(root)'}: {e.message}"
           for e in sorted(v.iter_errors(r), key=lambda e: list(map(str, e.path)))]
    if out:
        return out
    e = r["entry"]
    for h in map(str, resolve.HORIZONS):
        ex, mv = r["exits"].get(h), r["moves"].get(h)
        if (mv is None) != (h in r["unresolved"]):
            out.append(f"{h}d must be either a move or unresolved")
        elif mv is not None and (ex is None or mv != ex["price"] / e["price"] - 1):
            out.append(f"{h}d move != exit / entry - 1")
        if "side" in r and mv is not None and r["signed_returns"].get(h) != r["side"] * (ex["price"] / e["price"] - 1):
            out.append(f"{h}d signed return != side * move")
    if e and (not r["series"] or r["series"][0] != [e["at"], e["price"]]
              or r["series"][-1] != [r["latest"]["at"], r["latest"]["price"]]):
        out.append("series must run from entry to latest")
    if e and r["change_since_post"] != r["latest"]["price"] / e["price"] - 1:
        out.append("change_since_post != latest / entry - 1")
    return out


def best_since_post(r):
    """Best bar since the post, from the record's own hourly series (opens, entry -> latest).
    With a side: the bar with the largest side * move (best for the call). Without a side: the
    highest price. Ties keep the earliest bar. None when the record has no entry."""
    if not r["entry"]:
        return None
    p0, side = r["entry"]["price"], r.get("side")
    key = (lambda b: side * (b[1] / p0 - 1)) if side else (lambda b: b[1])
    at, price = max(r["series"], key=lambda b: (key(b), -resolve.parse(b[0]).timestamp()))
    best = {"at": at, "price": price, "move": price / p0 - 1, "basis": "call side" if side else "highest price"}
    if side:
        best["for_call"] = side * (price / p0 - 1)
    return best


def build(records_dir):
    v = resolve.validator()
    files = sorted(glob.glob(os.path.join(records_dir, "**", "*.json"), recursive=True))
    refused, valid = [], []
    for f in files:
        rel = os.path.relpath(f, HERE)
        with open(f, "rb") as fh:
            blob = fh.read()
        try:
            r = json.loads(blob)
        except json.JSONDecodeError as exc:
            refused.append({"file": rel, "reasons": [f"not json: {exc}"]})
            continue
        problems = record_problems(v, r) if isinstance(r, dict) else ["not a json object"]
        if problems:
            refused.append({"file": rel, "reasons": problems})
            continue
        valid.append((rel, hashlib.sha256(blob).hexdigest(), r))

    chosen, superseded = {}, []
    for rel, sha, r in valid:
        key = (r["post"]["id"], r["asset"]["name"])
        if key in chosen:
            keep, drop = sorted([chosen[key], (rel, sha, r)],
                                key=lambda x: (x[2]["resolved_with"]["last_bar_at"] or "", x[0]), reverse=True)
            chosen[key] = keep
            superseded.append({"file": drop[0], "by": keep[0], "post_id": key[0], "asset": key[1]})
        else:
            chosen[key] = (rel, sha, r)

    assets = {}
    for (pid, name), (rel, sha, r) in sorted(chosen.items(), key=lambda kv: (kv[0][1], kv[1][2]["post"]["posted_at"], kv[0][0])):
        a = assets.setdefault(name, {"name": name, "source": r["asset"]["source"], "symbol": r["asset"]["symbol"],
                                     "bars": {}, "posts": [], "conflicts": []})
        for t, p in r["series"]:
            if t in a["bars"] and a["bars"][t] != p:
                a["conflicts"].append(f"{t}: {a['bars'][t]} vs {p} in {rel}")
            a["bars"][t] = p
        post = {k: val for k, val in r.items() if k != "series"}
        post["best"] = best_since_post(r)
        post["record_file"], post["record_sha256"] = rel, sha
        a["posts"].append(post)

    out_assets = []
    for name in sorted(assets):
        a = assets[name]
        if a["conflicts"]:
            for p in a["posts"]:
                refused.append({"file": p["record_file"],
                                "reasons": [f"asset {name}: records disagree on bar prices: {a['conflicts'][0]}"]})
            continue
        out_assets.append({"name": name, "source": a["source"], "symbol": a["symbol"],
                           "series": [[t, a["bars"][t]] for t in sorted(a["bars"])], "posts": a["posts"]})
    return {"schema": BUNDLE_SCHEMA, "record_schema": "post_price.v1", "records_scanned": len(files),
            "posts_drawn": sum(len(a["posts"]) for a in out_assets),
            "refused": refused, "superseded": superseded, "assets": out_assets}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--records", default=os.path.join(HERE, "records"))
    ap.add_argument("--out", default=os.path.join(HERE, "web", "data", "charts.json"))
    a = ap.parse_args()
    bundle = build(a.records)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(bundle, f, indent=1)
        f.write("\n")
    for x in bundle["refused"]:
        print(f"REFUSED {x['file']}: " + "; ".join(x["reasons"]))
    for x in bundle["superseded"]:
        print(f"SUPERSEDED {x['file']} by {x['by']} ({x['post_id']} {x['asset']}: later last bar wins)")
    for asset in bundle["assets"]:
        print(f"{asset['name']:<7} {asset['source']}:{asset['symbol']:<8} {len(asset['series'])} bars, "
              f"{len(asset['posts'])} posts")
    print(f"{bundle['records_scanned']} records scanned, {bundle['posts_drawn']} drawn, "
          f"{len(bundle['superseded'])} superseded, {len(bundle['refused'])} refused -> {os.path.relpath(a.out, HERE)}")


if __name__ == "__main__":
    main()
