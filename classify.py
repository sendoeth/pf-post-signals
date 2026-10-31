#!/usr/bin/env python3
"""Step 13: classify an author's follow-up post about an open position.

Given the follow-up text, the position's asset and side, decide one of:
  close       an explicit exit ("rotated out of", "sold all", "closed", "exited", "out of",
              "covered", "stopped out")                         -> the position closes
  flip        "now short" / "flipped long" ...                  -> close + open the opposite side
  trim        a partial sale ("sold a clip", "took some profits", "trimmed")  -> stays open
  review      a hint ("trailing stops", "lightened up", "de-risking") -> never closes by itself
  not_close   advice to others ("afford yourself", "you should") or nothing about exiting
Precedence: advice to others, then flip, close, trim, hint. A follow-up that does not name the
position's asset (detect.py terms) is not about this position. Every result keeps the matched
words; a stated earlier time ("last week", "on Friday") is recorded but never used for pricing.
"""
import re

import detect

ADVICE = [r"afford yourself", r"\byou should\b", r"\byou (?:might|may) want\b", r"\bconsider (?:taking|selling)\b",
          r"\bcongrats if you\b", r"\bif you(?:'re| are) (?:long|in)\b", r"\btake (?:some )?profits?\b(?=.*\byou)"]
FLIP = [r"\b(?:flipped|flip(?:ping)?|now|went|gone|turned) (?:to )?(short|long)\b"]
CLOSE = [r"\brotated out of\b", r"\bsold (?:all|everything|my entire|the rest|out)\b", r"\bclosed (?:my|the|out)\b",
         r"\bexited\b", r"\b(?:i'?m|i am|we'?re|now) (?:fully )?out of\b", r"\bout of (?:my|the) (?:\w+ )?position\b",
         r"\bcovered (?:my|the)? ?shorts?\b", r"\bstopped out\b", r"\bno longer (?:hold|long|short|own)\b"]
TRIM = [r"\bsold (?:a|some|part|half|a portion|a decent|a big|a small)\b(?: \w+){0,2}", r"\btrimmed\b", r"\btook some profits?\b",
        r"\btaking some profits?\b", r"\bscaled (?:out|back)\b", r"\breduced (?:my )?(?:position|exposure)\b"]
HINT = [r"\btrailing stops?\b", r"\blightened (?:up)?\b", r"\bde-?risk(?:ing|ed)?\b", r"\bjump ship\b", r"\bnot loving\b",
        r"\btighten(?:ed|ing)? (?:my )?stops?\b", r"\bcareful here\b"]
STATED = [r"\blast week\b", r"\byesterday\b", r"\bon (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
          r"\bthis morning\b", r"\blast night\b", r"\blast month\b", r"\bearlier today\b"]


def _find(patterns, text):
    hits = []
    for p in patterns:
        for m in re.finditer(p, text, re.I):
            hits.append(m.group(0))
    return hits


def classify(text, asset, side=None):
    """-> {"type", "terms", "reason", "stated_time"}"""
    text = text or ""
    found = {m["asset"] for m in detect.detect(text)["matched"]}
    stated = _find(STATED, text)
    out = lambda t, terms, reason: {"type": t, "terms": terms, "reason": reason, "stated_time": stated[0] if stated else None}
    if asset not in found:
        return out("not_close", [], f"does not name {asset} (asset words found: {sorted(found) or 'none'})")
    advice = _find(ADVICE, text)
    if advice:
        return out("not_close", advice, "advice to others, not the author's own exit")
    flip = [m for m in re.finditer(FLIP[0], text, re.I)]
    new_sides = {m.group(1).lower() for m in flip}
    if flip and side in (1, -1) and new_sides == {"short" if side == 1 else "long"}:
        return out("flip", [m.group(0) for m in flip], f"states the opposite side ({new_sides.pop()})")
    close = _find(CLOSE, text)
    if close:
        return out("close", close, "explicit exit of the author's own position")
    trim = _find(TRIM, text)
    if trim:
        return out("trim", trim, "partial sale: the position stays open")
    hint = _find(HINT, text)
    if hint:
        return out("review", hint, "a hint at exiting, not an exit: goes to review, never closes by itself")
    return out("not_close", [], f"mentions {asset} without exit language")


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(classify(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else None)))
