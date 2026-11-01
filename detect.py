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


# Step 16: the side a post states for the author's own position. Only first-person or explicit
# position words count; both sides in one post (e.g. "closed my short, now long") is ambiguous and
# goes back to the owner (--side with a reason). No side words -> no side (a call without a side
# counts against the caller's clarity, never as a win or a loss).
SIDE_WORDS = {
    1: [r"\b(?:i'?m|i am|we'?re|we are|going|went|gone|opened|opening|entered|entering|added|adding|building|built)\b[^.\n]{0,30}?\blongs?\b", r"\b(?:took|taking) (?:a|the|my|some) longs?\b",
        r"\blong (?:positions?|entry|entries|here|now|from|at|on)\b", r"\bthe longs\b", r"\bnow long\b", r"\bcurrently long\b", r"\bstill long\b", r"\b(?:i|we)(?:'ve| have|'m| am|'re| are)? (?:just |also |been )?(?:bought|buying|added|adding|accumulat(?:ed|ing))\b",
        r"\b(?:i'?m|i am|we'?re|we are|i remain|still|very|getting|turning|turned) bullish\b", r"\bbullish (?:on|here)\b"],
    -1: [r"\b(?:i'?m|i am|we'?re|we are|going|went|gone|opened|opening|entered|entering|added|adding|building|built)\b[^.\n]{0,30}?\bshorts?\b", r"\b(?:took|taking) (?:a|the|my|some) shorts?\b",
         r"\bshort (?:positions?|entry|entries|here|now|from|at|on)\b", r"\bthe shorts\b", r"\bnow short\b", r"\bcurrently short\b", r"\blong \w+ - short\b", r"\bstill short\b", r"\b(?:i|we)(?:'m| am|'re| are|'ve| have)? (?:just |also )?(?:shorting|shorted)\b",
         r"\b(?:i'?m|i am|we'?re|we are|i remain|still|very|getting|turning|turned) bearish\b", r"\bbearish (?:on|here)\b"],
}


def detect_side(text):
    """-> {"side": 1 | -1 | None, "status": "detected" | "none" | "ambiguous", "terms": {1: [...], -1: [...]}}"""
    text = text or ""
    found = {s: [m.group(0) for p in pats for m in re.finditer(p, text, re.I)] for s, pats in SIDE_WORDS.items()}
    if found[1] and found[-1]:
        return {"side": None, "status": "ambiguous", "terms": found}
    if found[1] or found[-1]:
        return {"side": 1 if found[1] else -1, "status": "detected", "terms": found}
    return {"side": None, "status": "none", "terms": found}


# Step 22: every coin a post names (mapped words, any cashtag, X contract tags) resolved to a plain
# ticker by tickers.py, one leg per coin, and the side each leg's own words give it.
LEG_VERBS = {"buy": 1, "buying": 1, "bought": 1, "long": 1, "longing": 1, "sell": -1, "selling": -1, "sold": -1, "short": -1, "shorting": -1}
OPTION = re.compile(r"\b(calls?|puts?)\b", re.I)


def coin_legs(text, amap=None, net=None, registry=None):
    """-> [{"asset", "via", "receipt" (None for a mapped asset), "status", "reason"}] in order of first mention."""
    import tickers
    amap = amap or load_map()
    text = text or ""
    legs, seen = [], {}

    def add(asset, via, receipt=None, status="ok", reason=None, pos=0):
        key = asset or via
        if key in seen:
            if via not in seen[key]["via"]:
                seen[key]["via"].append(via)
            return
        seen[key] = {"asset": asset, "via": [via], "receipt": receipt, "status": status, "reason": reason, "pos": pos}
        legs.append(seen[key])

    for m in tickers.CONTRACT_TAG.finditer(text):
        r = tickers.resolve_contract(m.group(1), m.group(2), net, registry)
        add(r["ticker"] if r["status"] == "ok" else None, m.group(0), r, r["status"], r["reason"], m.start())
    for m in CASHTAG.finditer(text):
        tag = m.group(1).upper()
        mapped = amap["cashtags"].get(tag)
        if mapped:
            add(mapped, "$" + tag, pos=m.start())
            continue
        if tag in seen or any(l["asset"] == tag for l in legs):
            add(tag, "$" + tag, pos=m.start())
            continue
        r = tickers.resolve_ticker(tag, net, registry=registry)
        add(r["ticker"] if r["status"] == "ok" else None, "$" + tag, r, r["status"], r["reason"], m.start())
    rest = tickers.CONTRACT_TAG.sub(" ", CASHTAG.sub(" ", text))
    for pat, term, asset in amap["terms"]:
        mm = pat.search(rest)
        if mm:
            add(asset, term, pos=mm.start())
            rest = pat.sub(" ", rest)
    legs.sort(key=lambda l: l["pos"])
    return [{k: v for k, v in l.items() if k != "pos"} for l in legs]


def leg_side(text, aliases):
    """The side one coin's own words give it. Options: buying calls = long, buying puts = short,
    selling calls = no side (capped upside is not a stated short), selling puts = long. Without option
    words, the nearest buy / sell / long / short word before the coin. -> (side, reason, words)."""
    text = text or ""
    names = sorted({a for a in aliases if a}, key=len, reverse=True)
    alias_re = re.compile(r"(?<![\w$:])\$?(?:" + "|".join(re.escape(a.lstrip("$")) for a in names) + r")(?![\w])", re.I)
    for m in alias_re.finditer(text):
        after = text[m.end():m.end() + 12]
        opt = OPTION.match(after.strip()) if after.strip() else None
        before = text[max(0, m.start() - 60):m.start()]
        before = re.split(r"[.;\n]|,\s*and\b|\band\b", before)[-1]            # the clause this mention sits in
        verbs = [(v.group(0).lower(), v.start()) for v in re.finditer(r"\b(" + "|".join(LEG_VERBS) + r")\b", before, re.I)]
        if not verbs:
            continue
        verb = verbs[-1][0]
        words = (before[verbs[-1][1]:] + m.group(0) + (" " + opt.group(1) if opt else "")).strip()
        buy = LEG_VERBS[verb] == 1
        if opt:
            call = opt.group(1).lower().startswith("call")
            if buy:
                return (1 if call else -1), f"buying {'calls' if call else 'puts'}", words
            return (None, "selling calls caps the upside; it is not a stated short", words) if call else (1, "selling puts", words)
        return (1 if buy else -1), f"'{verb}' before the coin", words
    return None, "no side words next to this coin", None


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
