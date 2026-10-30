#!/usr/bin/env python3
"""Validate every records/**/*.json against schema/post_price.v1.json and the record invariants. Exit 1 on any failure."""
import glob
import json
import os
import sys

import resolve

HERE = os.path.dirname(os.path.abspath(__file__))
v = resolve.validator()
files = sorted(glob.glob(os.path.join(HERE, "records", "**", "*.json"), recursive=True))
fails = []
for f in files:
    with open(f) as fh:
        r = json.load(fh)
    name = os.path.relpath(f, HERE)
    fails += [f"{name}: {'/'.join(map(str, e.path))}: {e.message}" for e in v.iter_errors(r)]
    e = r["entry"]
    for h in map(str, resolve.HORIZONS):
        ex, mv = r["exits"].get(h), r["moves"].get(h)
        if (mv is None) != (h in r["unresolved"]):
            fails.append(f"{name}: {h}d must be either a move or unresolved")
        if mv is not None and mv != ex["price"] / e["price"] - 1:
            fails.append(f"{name}: {h}d move != exit / entry - 1")
        if "side" in r and r["signed_returns"].get(h) != (None if mv is None else r["side"] * (ex["price"] / e["price"] - 1)):
            fails.append(f"{name}: {h}d signed return != side * move")
    if e and (r["series"][0] != [e["at"], e["price"]] or r["series"][-1] != [r["latest"]["at"], r["latest"]["price"]]):
        fails.append(f"{name}: series must run from entry to latest")
print(f"records: {len(files)} checked against post_price.v1 -> " + ("ALL VALID" if not fails else f"{len(fails)} FAIL"))
for x in fails:
    print(" -", x)
sys.exit(1 if fails else 0)
