#!/usr/bin/env python3
"""Step 6: propose the asset a post is about, from its cashtags and a written keyword map.

Rules (detect/asset_map.json, written before scoring):
- cashtags ($BTC) map through "cashtags"; a cashtag with no entry is reported, never guessed
- terms match whole words, case-insensitive; a longer term wins over terms inside it
- exactly one asset -> "detected"; none, several, or an unmapped cashtag -> "needs_review"
- a manual asset always overrides the detector (resolve.asset_info still checks it)
The detector only proposes an asset. Whether a post is a call at all stays a human decision.

usage: python3 detect.py --receipt FILE | --text "..." [--asset NAME]
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAP_PATH = os.path.join(HERE, "detect", "asset_map.json")
CASHTAG = re.compile(r"(?<![\w$])\$([A-Za-z][A-Za-z0-9]{0,9})\b")


def load_map(path=MAP_PATH):
    with open(path) as f:
        m = json.load(f)
    terms = sorted(((t.lower(), a) for a, ts in m["terms"].items() for t in ts), key=lambda x: -len(x[0]))
    pats = [(re.compile(r"(?<![\w&])" + re.escape(t).replace(r"\ ", r"\s+") + r"(?![\w&])", re.I), t, a) for t, a in terms]
    return {"terms": pats, "cashtags": {k.upper(): v for k, v in m["cashtags"].items()}}


def detect(text, amap=None, manual=None):
    if manual:
        return {"status": "manual", "asset": manual.strip(), "matched": [], "reason": "asset given by hand"}
    amap = amap or load_map()
    text = text or ""
    matched, unmapped = [], []
    for tag in CASHTAG.findall(text):
        asset = amap["cashtags"].get(tag.upper())
        if asset:
            matched.append({"asset": asset, "term": "$" + tag.upper()})
        elif "$" + tag.upper() not in unmapped:
            unmapped.append("$" + tag.upper())
    rest = CASHTAG.sub(" ", text)
    for pat, term, asset in amap["terms"]:
        if pat.search(rest):
            matched.append({"asset": asset, "term": term})
            rest = pat.sub(" ", rest)  # a longer term consumes its words
    assets = sorted({m["asset"] for m in matched})
    if unmapped:
        return {"status": "needs_review", "asset": None, "matched": matched,
                "reason": f"cashtag {', '.join(unmapped)} has no price source in the asset map"}
    if len(assets) == 1:
        return {"status": "detected", "asset": assets[0], "matched": matched, "reason": None}
    if not assets:
        return {"status": "needs_review", "asset": None, "matched": [], "reason": "no asset words or cashtags"}
    return {"status": "needs_review", "asset": None, "matched": matched,
            "reason": f"several assets: {', '.join(assets)}"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--receipt")
    g.add_argument("--text")
    ap.add_argument("--asset", help="manual override")
    a = ap.parse_args()
    if a.receipt:
        with open(a.receipt) as f:
            text = json.load(f).get("text")
    else:
        text = a.text
    r = detect(text, manual=a.asset)
    print(json.dumps(r))
    sys.exit(0 if r["status"] in ("detected", "manual") else 3)


if __name__ == "__main__":
    main()
