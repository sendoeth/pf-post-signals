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
LEG_VERBS = {"buy": 1, "buying": 1, "bought": 1, "long": 1, "longing": 1, "deployed": 1, "deploying": 1, "added": 1, "adding": 1, "loaded": 1,
             "loading": 1, "accumulated": 1, "accumulating": 1, "aped": 1,
             "sell": -1, "selling": -1, "sold": -1, "short": -1, "shorting": -1}
OPTION = re.compile(r"\b(calls?|puts?)\b", re.I)


WORDS_PATH = os.path.join(HERE, "data", "coin_words.json")
US_PATH = os.path.join(HERE, "data", "us_tickers.json")
STOCK_COIN_RANK = 500        # an unknown cashtag that is also a US stock counts as the coin only up to this market-cap rank
STOCK_WORDS = re.compile(r"\b(shares?|stocks?|equity|earnings|eps|dividends?|nyse|nasdaq|ipo|guidance|10-?[kq])\b", re.I)
_cache = {}


def _load(path, empty):
    if path not in _cache:
        _cache[path] = json.load(open(path)) if os.path.exists(path) else empty
    return _cache[path]


def coin_words(path=WORDS_PATH):
    return _load(path, {"names": {}, "bare_blocked": [], "wrapped": {}, "index": {}, "index_phrases": [], "stablecoins": []})


def us_tickers(path=US_PATH):
    return _load(path, {"tickers": {}})["tickers"]


def coin_legs(text, amap=None, net=None, registry=None, words=None, us=None):
    """-> [{"asset", "via", "receipt" (None for a mapped asset), "status", "reason"}] in order of first mention.

    Sources, in this order (a coin named several ways is one leg):
      market indexes  TOTAL3, BTC.D, USDT.D, "stablecoin dominance" ...: a review leg (an index, not a coin), and
                      the words are removed first so "BTC.D" is never read as BTC
      contract tags   hyperliquid:native, <chain>:<address> (tickers.resolve_contract)
      cashtags        the fixed map; stablecoins ignored; wrapped copies -> the underlying ($WBTC -> BTC);
                      a seeded / registered coin offline (a US stock ticker too: review only if the post talks
                      shares / earnings); anything else: tickers.resolve_ticker, and if it is also a US-listed ticker it
                      counts as the coin only when it is a top-500 coin and the post does not talk shares (else review)
      words           the fixed term map, then coin names (data/coin_words.json), then bare tickers written in capitals:
                      fixed-map ones (SOL, LINK) always, registered coins unless the ticker is a common English word
    """
    import tickers
    amap = amap or load_map()
    words = words or coin_words()
    us = us if us is not None else us_tickers()
    reg = registry or tickers.load_registry()
    text = text or ""
    legs, seen = [], {}

    def coin(asset, via, pos, receipt=None, need_receipt=False):
        """Every coin found by the map, a name or a bare ticker passes the same checks as a cashtag (Codex review):
        a flagged ticker, a US-stock ticker in a post about shares, or a missing / untrusted receipt -> review."""
        e = reg.get("tickers", {}).get(asset)
        if e and e.get("flag"):
            return add(None, via, status="review", reason=f"{asset} ({e['name']}) is flagged by the weekly venue re-check: {e['flag'].get('why')}", pos=pos)
        if e and e.get("also_us_stock") and STOCK_WORDS.search(text):
            return add(None, via, status="review", reason=f"{asset} is {e['name']} and the US stock {e['also_us_stock']}; this post talks shares / earnings: pick by hand", pos=pos)
        if need_receipt and not receipt:
            return add(None, via, status="review", reason=f"{asset}: its registry receipt is missing or does not match its sha256 (nothing guessed)", pos=pos)
        return add(asset, via, receipt=receipt, pos=pos)

    def add(asset, via, receipt=None, status="ok", reason=None, pos=0):
        key = asset or via
        if key in seen:
            if via not in seen[key]["via"]:
                seen[key]["via"].append(via)
            return
        seen[key] = {"asset": asset, "via": [via], "receipt": receipt, "status": status, "reason": reason, "pos": pos}
        legs.append(seen[key])

    # 1. market indexes (removed before anything else reads the text)
    rest = text
    idx_words = sorted(words.get("index", {}), key=len, reverse=True)
    for w in idx_words:                                # capitals only ("total" / "others" are ordinary words); "total3" is a phrase below
        pat = r"(?<![\w$.])\$?" + re.escape(w) + r"(?![\w.])"
        for m in re.finditer(pat, rest):
            add(None, w.upper(), status="review", reason=f"market index {w.upper()} ({words['index'][w]}): not a coin, no price history source yet", pos=m.start())
        rest = re.sub(pat, " ", rest)
    for ph in words.get("index_phrases", []):
        for m in re.finditer(re.escape(ph), rest, re.I):
            add(None, ph, status="review", reason=f"market index ({ph}): not a coin, no price history source yet", pos=m.start())
        rest = re.sub(re.escape(ph), " ", rest, flags=re.I)
    # 2. contract tags
    for m in tickers.CONTRACT_TAG.finditer(rest):
        r = tickers.resolve_contract(m.group(1), m.group(2), net, reg)
        add(r["ticker"] if r["status"] == "ok" else None, m.group(0), r, r["status"], r["reason"], m.start())
    # 3. cashtags
    stable = set(words.get("stablecoins", []))
    for m in CASHTAG.finditer(rest):
        tag = m.group(1).upper()
        if tag in stable:
            continue                                   # a stablecoin is never a call
        tag = words.get("wrapped", {}).get(tag, tag)
        mapped = amap["cashtags"].get(tag)
        if mapped:
            coin(mapped, "$" + m.group(1).upper(), m.start())
            continue
        if tag in seen or any(l["asset"] == tag for l in legs):
            add(tag, "$" + m.group(1).upper(), pos=m.start())
            continue
        e = reg.get("tickers", {}).get(tag)
        if e and e.get("also_us_stock") and STOCK_WORDS.search(text):
            add(None, "$" + tag, status="review", reason=f"${tag} is {e['name']} and the US stock {e['also_us_stock']}; this post talks shares / earnings: pick by hand", pos=m.start())
            continue
        r = tickers.resolve_ticker(tag, net, registry=reg)
        if not e and tag in us:
            # an unknown cashtag that is also a US-listed ticker: the coin only if it is a real top-500 coin and the
            # post does not talk shares / earnings; otherwise the stock (review, never a tiny token with that symbol)
            rank = ((r.get("coin") or {}).get("rank") or 10 ** 9) if r["status"] == "ok" else 10 ** 9
            if rank > STOCK_COIN_RANK or STOCK_WORDS.search(text):
                add(None, "$" + tag, status="review", reason=f"${tag} is a US-listed stock ({us[tag]})"
                    + (f" and only a #{rank} coin" if rank < 10 ** 9 else "") + f": add it with --asset yahoo:{tag} if the stock is the call", pos=m.start())
                continue
        add(r["ticker"] if r["status"] == "ok" else None, "$" + tag, r, r["status"], r["reason"], m.start())
    rest = tickers.CONTRACT_TAG.sub(" ", CASHTAG.sub(" ", rest))
    # 4. words: the fixed term map, coin names, bare tickers
    for pat, term, asset in amap["terms"]:
        mm = pat.search(rest)
        if mm:
            coin(asset, term, mm.start())
            rest = pat.sub(" ", rest)
    for name, t in sorted(words.get("names", {}).items(), key=lambda kv: -len(kv[0])):
        mm = re.search(r"(?<![\w&])" + re.escape(name).replace(r"\ ", r"\s+") + r"(?![\w&])", rest, re.I)
        if mm:
            coin(t, name, mm.start(), receipt=tickers.from_registry(t, reg), need_receipt=True)
            rest = rest[:mm.start()] + " " * len(mm.group(0)) + rest[mm.end():]
    blocked = set(words.get("bare_blocked", []))
    for mm in re.finditer(r"(?<![\w$:])([A-Z][A-Z0-9]{2,11})(?![\w])", rest):
        t = mm.group(1)
        if amap["cashtags"].get(t):                    # a fixed-map ticker written bare in capitals (SOL, LINK, ETH): the coin
            coin(amap["cashtags"][t], t, mm.start())
        elif t in reg.get("tickers", {}) and t not in blocked:
            coin(t, t, mm.start(), receipt=tickers.from_registry(t, reg), need_receipt=True)
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
        before = re.split(r"[.;\n]|,\s*and\b|,\s*but\b", before)[-1]        # the clause ("into $ETH and $HYPE" shares its verb)
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
