#!/usr/bin/env python3
"""Step 27: the call reader, one place. The side a post's own words give one asset:

  base      exactly the reading /add has always used: detect.detect_side (the post's first-person position words)
            for a one-asset post, detect.leg_side (the words next to this coin) for a multi-coin post or options
  rules     learned from the owner's corrections, applied only when the base read finds no side, and only
            the rules the gate kept (data/rules.json). A rule is a narrow pattern tied to the asset's own name.

Candidates are written here; tools/labels.py gate decides which are kept: a candidate is kept only if agreement
with the owner's labels rises and no label that agreed before disagrees after. Nothing here changes a record:
records keep the side they were added with; the reader only shapes new previews (and the watcher's cards).
"""
import json
import os
import re
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TOOLS)
sys.path[:0] = [HERE, TOOLS]
import detect  # noqa: E402

RULES_PATH = os.path.join(HERE, "data", "rules.json")
SIDE = {1: "long", -1: "short", None: "none"}


def alias_re(aliases):
    names = sorted({a.lstrip("$") for a in aliases if a and a.strip("$")}, key=len, reverse=True)
    return r"\$?(?:" + "|".join(re.escape(a) for a in names) + r")(?![\w])"


def base_read(text, aliases, multi=False):
    """-> (side, words, method): the reading /add uses without learned rules."""
    text = text or ""
    if multi or detect.OPTION.search(text):
        s, why, words = detect.leg_side(text, aliases)
        return s, words, "detector-leg"
    d = detect.detect_side(text)
    if d["status"] == "detected":
        return d["side"], ", ".join((d["terms"][1] + d["terms"][-1])[:3]), "detector"
    return None, None, "detector" if d["status"] == "none" else "ambiguous"


# ---- candidate rules (each: text, aliases -> (side, matched words) or None) -----------------------------
def more_cashtag(text, aliases):
    """'More $NEST and $KNTQ': 'more' directly before a list of cashtags that contains this asset = add more = long."""
    m = re.search(r"(?<![\w])more\s+((?:\$\w+\s*(?:,|and|&)\s*)*)" + alias_re(aliases), text, re.I)
    return (1, m.group(0)) if m else None


def positioned_side(text, aliases):
    """'Still leaning and positioned on the bull side' (for this asset's post): the author's stated positioning."""
    m = re.search(r"\bpositioned on the (bull|bear) side\b", text, re.I)
    return ((1 if m.group(1).lower() == "bull" else -1), m.group(0)) if m else None


def picking_up_quantity(text, aliases):
    """'Picking up 10BTC at $65,000': picking up a stated quantity of this asset = a buy."""
    m = re.search(r"\bpicking up\s+[\d.,]+\s*(?:k\s*)?" + alias_re(aliases), text, re.I)
    return (1, m.group(0)) if m else None


def bullish_anywhere(text, aliases):
    """Broad: the word 'bullish' anywhere = long (expected to be rejected: shorts say 'before turning bullish')."""
    m = re.search(r"\bbullish\b", text, re.I)
    return (1, m.group(0)) if m else None


def targeting_price(text, aliases):
    """Broad: 'targeting $X' = long (a target can also be a downside one)."""
    m = re.search(r"\btargeting \$?\d[\d,.]*", text, re.I)
    return (1, m.group(0)) if m else None


CANDIDATES = {
    "more_cashtag": more_cashtag,
    "positioned_side": positioned_side,
    "picking_up_quantity": picking_up_quantity,
    "bullish_anywhere": bullish_anywhere,
    "targeting_price": targeting_price,
}
ORDER = list(CANDIDATES)


LABELS_PATH = os.path.join(HERE, "data", "labels.json")


def _sha(obj):
    import hashlib
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def corpus_sha(labels):
    """The gate's inputs, recomputed from the labels themselves (never from stored pins): what was read and what the owner decided."""
    return _sha([[l["id"], l["post"]["text"], l["aliases"], l["multi"], l["gating"], l["owner"]["decision"], l["owner"].get("side")]
                 for l in sorted(labels, key=lambda l: l["id"])])


def code_sha(rid=None):
    """A rule's behaviour depends on its own code, the helpers it calls and the base read it runs after: the whole of
    tools/reader.py and detect.py are bound (any edit switches the kept rules off until the gate runs again)."""
    import hashlib
    h = hashlib.sha256()
    for f in (os.path.abspath(__file__), os.path.join(HERE, "detect.py")):
        with open(f, "rb") as fh:
            h.update(hashlib.sha256(fh.read()).digest())
    h.update((rid or "").encode())
    return h.hexdigest()


def kept_rules(path=None, labels_path=None):
    """The rules the gate kept, each only while it is bound: the sha256 of its code equals the gated one and it was
    verified against exactly the current labels. Anything else (edited code, new labels not re-verified, a missing or
    unreadable file) -> the rule is not applied (fail closed)."""
    path, labels_path = path or RULES_PATH, labels_path or LABELS_PATH
    try:
        with open(path) as f:
            d = json.load(f)
        with open(labels_path) as f:
            labels = json.load(f)["labels"]
    except (OSError, ValueError, KeyError):
        return []
    current = corpus_sha(labels)
    out = []
    for rid in d.get("kept", []):
        b = (d.get("bindings") or {}).get(rid) or {}
        if rid in CANDIDATES and b.get("code_sha256") == code_sha(rid) and b.get("verified_labels_sha256") == current:
            out.append(rid)
    return out


def read(text, aliases, multi=False, rules=None):
    """-> {"side": 1|-1|None, "words", "method", "rule"}: the base read, then the kept rules (in gate order) when it finds no side."""
    rules = kept_rules() if rules is None else rules
    s, words, method = base_read(text, aliases, multi)
    if s is None and method != "ambiguous":
        for rid in rules:
            hit = CANDIDATES[rid](text or "", aliases)
            if hit:
                return {"side": hit[0], "words": hit[1], "method": "rule", "rule": rid}
    return {"side": s, "words": words, "method": method, "rule": None}
