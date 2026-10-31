#!/usr/bin/env python3
"""Step 15: deterministic 0-100 caller ratings from priced calls.

Only the bundle's priced records go in; no model, no manual input. For each caller:

  calls      every position of the caller in the bundle (one post can call several assets)
  with entry calls that have an entry bar (a price at post time)
  scored     calls with entry that state a side (long / short) and have a result
  result r   realized return for the side if the call is closed, else the return for the side
             since the post (PFPS.result in web/assets/common.js)

  H  hit rate        100 * (scored calls with r > 0) / n
  A  return quality  mean over scored calls of 50 + 50 * tanh(r / 0.10)
                     (each call is capped smoothly: +10% -> 88.1, +50% -> 100.0, -10% -> 11.9,
                     so one outsized call cannot carry the score)
  C  clarity         100 * scored / with entry  (share of calls that state a side)
  raw   = 0.45 H + 0.40 A + 0.15 C
  w     = n / (n + 10)                  (shrinkage: 10 calls = half data, half prior)
  score = 50 + w * (raw - 50)           (a caller with no scored calls is 50)

Every input is monotone: a better result on any call never lowers the score. Labels: under 10
scored calls "small sample", under 30 "limited sample". Open calls move with the daily price
refresh, so the score is as of the bundle's prices_as_of. Each rating lists every call it read,
with whether it counted and why not.

usage: python3 rate.py [charts.json]   (prints every caller's inputs, components and score)
"""
import json
import math
from decimal import ROUND_HALF_UP, Decimal
import os
import re
import sys

VERSION = "quanty.rating.v1"
K = 10                       # shrinkage strength (calls)
WEIGHTS = {"hit": 0.45, "quality": 0.40, "clarity": 0.15}
SCALE = 0.10                 # tanh scale for one call's result
PRIOR = 50.0
SMALL, LIMITED = 10, 30


def result(p):
    """Result for the call's side: realized if closed, else since the post; None without a price."""
    side = p.get("side")
    if p.get("closed"):
        c = p["closed"]
        return c.get("for_call") if side else c["move"]
    ch = p.get("change_since_post")
    if ch is None:
        return None
    return side * ch if side else ch


def call_quality(r):
    return 50 + 50 * math.tanh(r / SCALE)


def display(score):
    """One decimal, half up (the pages show this string; the exact score stays in "score")."""
    return str(Decimal(repr(score)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def caller_slug(name):
    return re.sub(r"[^a-z0-9_-]", "-", name.lower())


def label(n):
    return "small sample" if n < SMALL else "limited sample" if n < LIMITED else None


def rate_caller(calls):
    """calls: [(asset name, position)] for one caller -> rating dict."""
    listed, scored, with_entry = [], [], 0
    for asset, p in sorted(calls, key=lambda c: (c[1]["post"]["posted_at"], c[1]["post"]["id"], c[0])):
        row = {"post_id": p["post"]["id"], "asset": asset, "posted_at": p["post"]["posted_at"],
               "side": {1: "long", -1: "short"}.get(p.get("side"), "none"), "state": "closed" if p.get("closed") else "open"}
        r = result(p)
        row["result"] = r
        if not p.get("entry"):
            row.update(counted=False, why="no entry bar (no price at post time)")
        elif not p.get("side"):
            with_entry += 1
            row.update(counted=False, why="no side stated: counts against clarity only")
        elif r is None:
            with_entry += 1
            row.update(counted=False, why="no price after the post yet")
        else:
            with_entry += 1
            row.update(counted=True, why="realized return (closed)" if p.get("closed") else "return for the side since the post (open)",
                       quality=call_quality(r))
            scored.append(row)
        listed.append(row)
    n = len(scored)
    out = {"calls_total": len(listed), "with_entry": with_entry, "scored": n, "calls": listed, "label": label(n)}
    if not n:
        out.update(hit_rate=None, avg_result=None, components=None, raw=None, weight=0.0, score=PRIOR,
                   note="no scored calls: the score is the prior")
        return out
    wins = sum(1 for c in scored if c["result"] > 0)
    comps = {"hit": 100.0 * wins / n,
             "quality": sum(c["quality"] for c in scored) / n,
             "clarity": 100.0 * n / with_entry}
    raw = sum(WEIGHTS[k] * comps[k] for k in WEIGHTS)
    w = n / (n + K)
    out.update(wins=wins, hit_rate=wins / n, avg_result=sum(c["result"] for c in scored) / n, components=comps,
               raw=raw, weight=w, score=PRIOR + w * (raw - PRIOR))
    return out


def rate_bundle(bundle):
    by = {}
    for a in bundle["assets"]:
        for p in a["posts"]:
            by.setdefault(p["post"]["author"], []).append((a["name"], p))
    callers = {name: rate_caller(calls) for name, calls in sorted(by.items(), key=lambda kv: kv[0].lower())}
    order = sorted(callers, key=lambda n: (-callers[n]["score"], n.lower()))
    for i, name in enumerate(order, 1):
        callers[name]["rank"] = i
        callers[name]["display"] = display(callers[name]["score"])
    return {"version": VERSION, "as_of": bundle.get("prices_as_of"),
            "formula": {"k": K, "weights": WEIGHTS, "scale": SCALE, "prior": PRIOR, "small_sample": SMALL, "limited_sample": LIMITED,
                        "text": "score = 50 + n/(n+10) * (0.45 H + 0.40 A + 0.15 C - 50); H = 100 * wins/n; "
                                "A = mean(50 + 50 tanh(r/0.10)); C = 100 * sided calls with entry / calls with entry"},
            "order": order, "callers": callers}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "data", "charts.json")
    with open(path) as f:
        bundle = json.load(f)
    rt = rate_bundle(bundle)
    print(f"{rt['version']} · prices as of {rt['as_of']} · {rt['formula']['text']}")
    for name in rt["order"]:
        c = rt["callers"][name]
        comp = c["components"]
        print(f"#{c['rank']} @{name}: score {c['score']:.4f} ({c['label'] or 'sample ok'}) · calls {c['calls_total']}, with entry {c['with_entry']}, scored {c['scored']}"
              + (f" · wins {c['wins']} · H {comp['hit']:.4f} A {comp['quality']:.4f} C {comp['clarity']:.4f} · raw {c['raw']:.4f} · weight {c['weight']:.4f}"
                 f" · avg result {c['avg_result'] * 100:+.2f}%" if comp else " · " + c["note"]))
        for x in c["calls"]:
            print(f"    {x['posted_at'][:16]} {x['asset']:<10} {x['side']:<5} {x['state']:<6} "
                  + (f"r {x['result'] * 100:+8.2f}% A_i {x['quality']:7.3f}" if x["counted"] else f"not counted: {x['why']}"))


if __name__ == "__main__":
    main()
