#!/usr/bin/env python3
"""Checks for step 3. Exit 1 on any failure.

schema    every BobLoukas call row has the required fields with valid types/values
coverage  every keyword candidate post is labelled (call / reiteration / excluded / off-topic);
          every labelled id has a receipt whose author is BobLoukas and lies in the window
dupes     no (post, instrument) labelled twice; no scored call is also excluded
parity    re-scoring step-1 Corbanu rows with the same score.summarize reproduces comparison.json,
          and every BobLoukas return equals side * (exit / entry - 1)
"""
import json
import os
import re
import sys

import score

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources", "bobloukas")
DATA = os.path.join(HERE, "data")
fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


labels = json.load(open(os.path.join(SRC, "labels.json")))
index = json.load(open(os.path.join(SRC, "posts_index.json")))
rows = json.load(open(os.path.join(DATA, "bobloukas_calls.json")))
offtopic = json.load(open(os.path.join(DATA, "bobloukas_exclusions.json")))["off_topic"]

# schema
need = {"post_id": str, "url": str, "posted_at": str, "instrument": str, "side": int, "status": str,
        "regime": str, "returns": dict, "unresolved": dict, "exits": dict}
for r in rows:
    for k, t in need.items():
        check(isinstance(r.get(k), t), f"schema: {r.get('post_id')} field {k} not {t.__name__}")
    check(r["side"] in (1, -1), f"schema: {r['post_id']} side")
    check(r["status"] in ("call", "reiteration"), f"schema: {r['post_id']} status")
    check(re.fullmatch(r"https://x\.com/BobLoukas/status/\d+", r["url"] or "") is not None, f"schema: {r['post_id']} url")
    for h in map(str, score.HORIZONS):
        check((r["returns"].get(h) is None) == (h in r["unresolved"]) or r["status"] != "call",
              f"schema: {r['post_id']} h{h} must be either resolved or explicitly unresolved")

# coverage
labelled = {c["id"] for c in labels["calls"]} | {e["id"] for e in labels["excluded"]} | set(offtopic)
cands = {p["id"] for p in index["posts"] if p["candidate"]}
check(not (cands - labelled), f"coverage: unlabelled candidates {sorted(cands - labelled)}")
for i in labelled:
    path = os.path.join(SRC, "receipts", f"{i}.json")
    check(os.path.exists(path), f"coverage: no receipt for {i}")
    if os.path.exists(path):
        p = json.load(open(path))
        check(p["authorHandle"].lower() == "bobloukas", f"coverage: {i} author")
        check("2026-09-01" <= p["postedAt"][:10] <= "2026-10-28", f"coverage: {i} outside window")

# duplicates
keys = [(c["id"], c["instrument"]) for c in labels["calls"]]
check(len(keys) == len(set(keys)), "dupes: (post, instrument) labelled twice")
scored = {c["id"] for c in labels["calls"]}
check(not (scored & {e["id"] for e in labels["excluded"]}), "dupes: post both labelled and excluded")
check(len(index["posts"]) == len({p["id"] for p in index["posts"]}), "dupes: posts_index")

# parity
comp = json.load(open(os.path.join(DATA, "author_comparison.json")))
cor = json.load(open(os.path.join(DATA, "new_system_resolved.json")))
step1 = json.load(open(os.path.join(DATA, "comparison.json")))
for h in score.HORIZONS:
    again = score.summarize(cor["calls"], h)
    check(again == step1["new_calls"][str(h)], f"parity: corbanu h{h} differs from step 1 comparison.json")
    stored = {k: v for k, v in comp["authors"]["goodalexander/Corbanu"]["by_horizon"][str(h)].items() if k != "sample_flag"}
    check(again == stored, f"parity: corbanu h{h} differs in author_comparison.json")
for r in rows:
    for h, ret in r["returns"].items():
        if ret is not None:
            exp = r["side"] * (r["exits"][h]["price"] / r["entry"]["price"] - 1)
            check(abs(exp - ret) < 1e-12, f"parity: {r['post_id']} {r['instrument']} h{h}")

print(f"checks: {len(rows)} rows, {len(cands)} candidates, {len(labelled)} labelled ids -> "
      + ("ALL PASS" if not fails else f"{len(fails)} FAIL"))
for f in fails:
    print(" -", f)
sys.exit(1 if fails else 0)
