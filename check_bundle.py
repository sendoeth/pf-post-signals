#!/usr/bin/env python3
"""Step 5 record-to-card check (data level): web/data/charts.json must equal the record files.

- every records/**/*.json is accounted for exactly once: drawn, superseded or refused
- every drawn post equals its record file field for field (the record minus its series), and the
  record file's sha256 matches the one the card shows
- every bar of every drawn record is on its asset's price line with the same price
- every unresolved horizon is null in the bundle, never 0
The browser test (tests/browser_test.js) then checks what each card actually renders.
"""
import glob
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
fails = []
with open(os.path.join(HERE, "web", "data", "charts.json")) as f:
    bundle = json.load(f)
files = sorted(os.path.relpath(p, HERE) for p in glob.glob(os.path.join(HERE, "records", "**", "*.json"), recursive=True))

drawn = [p["record_file"] for a in bundle["assets"] for p in a["posts"]]
seen = drawn + [s["file"] for s in bundle["superseded"]] + [r["file"] for r in bundle["refused"]]
for f in files:
    if seen.count(f) != 1:
        fails.append(f"{f}: accounted for {seen.count(f)} times")
if bundle["records_scanned"] != len(files):
    fails.append(f"records_scanned {bundle['records_scanned']} != {len(files)} files")

cells = 0
for a in bundle["assets"]:
    bars = dict(map(tuple, a["series"]))
    if [t for t, _ in a["series"]] != sorted(bars):
        fails.append(f"{a['name']}: series not sorted or has duplicate bars")
    for p in a["posts"]:
        with open(os.path.join(HERE, p["record_file"]), "rb") as fh:
            blob = fh.read()
        rec = json.loads(blob)
        if hashlib.sha256(blob).hexdigest() != p["record_sha256"]:
            fails.append(f"{p['record_file']}: sha256 differs")
        shown = {k: v for k, v in p.items() if k not in ("record_file", "record_sha256")}
        if shown != {k: v for k, v in rec.items() if k != "series"}:
            fails.append(f"{p['record_file']}: bundle post differs from the record")
        if rec["asset"]["name"] != a["name"]:
            fails.append(f"{p['record_file']}: drawn under {a['name']}")
        for t, price in rec["series"]:
            if bars.get(t) != price:
                fails.append(f"{p['record_file']}: bar {t} {price} not on the {a['name']} line")
                break
        for h in ("1", "7", "30"):
            cells += 1
            if h in p["unresolved"] and p["moves"][h] is not None:
                fails.append(f"{p['record_file']}: {h}d unresolved but has a move")

print(f"bundle: {len(files)} record files -> {len(drawn)} drawn, {len(bundle['superseded'])} superseded, "
      f"{len(bundle['refused'])} refused; {cells} horizon cells checked -> " + ("ALL MATCH" if not fails else f"{len(fails)} FAIL"))
for x in fails:
    print(" -", x)
sys.exit(1 if fails else 0)
