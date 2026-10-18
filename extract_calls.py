#!/usr/bin/env python3
"""Extract structured trade calls from goodalexander / Corbanu publications since 2026-09-01.

Canonical source: Corbanu's published-trade ledger (corbanu.com/assets/portfolio/ledger.json),
which timestamps every entry with its reference price and weight. Each ledger event is linked
to its article; the article header supplies the stated horizon and target. Mentions of the same
trades on X / Discord are recorded as confirmations, and mentions that cannot be resolved
against a price are listed as excluded with a reason. Output: data/calls.json.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources", "corbanu")
SINCE = "2026-09-01"

# Two-legged ideas published as one trade: same article, opposite sides, same timestamp.
PAIRS = {"cxmt": "cxmt-cbrs", "cbrs": "cxmt-cbrs", "kioxia": "kioxia-jp225", "jp225": "kioxia-jp225"}

# Non-ledger mentions by goodalexander in the window (X article 2026-10-15, Discord #corbanu).
OTHER_MENTIONS = [
    {"at": "2026-09-30T02:47:00Z", "source": "https://discord.com/channels/1061800464045310053/1546231723682041916",
     "text": "we added to cerebras https://corbanu.com/posts/cerebras-left-on-the-bench/",
     "status": "confirmation", "matches": "cbrs add 2026-09-30"},
    {"at": "2026-09-30T18:52:00Z", "source": "https://discord.com/channels/1061800464045310053/1546231723682041916",
     "text": "burn CBRS", "status": "confirmation", "matches": "cbrs short"},
    {"at": "2026-10-15T17:11:42Z", "source": "https://x.com/goodalexander/status/2110780667218808911",
     "text": "I am still long $ORCL despite the near term pain.", "status": "confirmation", "matches": "orcl long"},
    {"at": "2026-10-15T17:11:42Z", "source": "https://x.com/goodalexander/status/2110780667218808911",
     "text": "I am not long CRWV though I am likely going to buy the bonds.", "status": "excluded",
     "reason": "conditional intent on a bond with no public price series; not a resolvable call"},
]


def article_terms(href):
    """Stated horizon / target from the article header, when present."""
    name = "posts_" + href.strip("/").split("/")[-1] + ".txt"
    path = os.path.join(SRC, name)
    if not os.path.exists(path):
        return {}
    head = open(path, encoding="utf8").read()[:1500]
    terms = {}
    m = re.search(r"Horizon\s+(\d{1,2} \w+ \d{4})", head)
    if m:
        terms["stated_horizon"] = m.group(1)
    m = re.search(r"(?:Weighted|Base) target\s+([^\n]+?)\s+Horizon", head)
    if m:
        terms["stated_target"] = m.group(1).strip()
    m = re.search(r"Review\s+(\d{1,2} \w+)", head)
    if m:
        terms["review_date"] = m.group(1)
    return terms


def main():
    ledger = json.load(open(os.path.join(SRC, "portfolio_ledger.json")))
    positions = {p["id"]: p for p in ledger["positions"]}
    calls = []
    for ev in ledger["events"]:
        if ev["at"] < SINCE or ev.get("type") != "trade":
            continue
        pos = positions[ev["positionId"]]
        side = "long" if ev["quantity"] > 0 else "short"
        prior = [c for c in calls if c["position_id"] == ev["positionId"]]
        call = {
            "call_id": ev["id"],
            "position_id": ev["positionId"],
            "author": "goodalexander / Corbanu",
            "ticker": pos.get("underlyingTicker", pos["symbol"]),
            "instrument": pos["rawSymbol"],
            "venue": pos["venue"],
            "side": side,
            "kind": "add" if prior else "entry",
            "pair_id": None if prior else PAIRS.get(ev["positionId"]),
            "called_at": ev["at"],
            "reference_price": ev["price"],
            "target_weight_pct": ev.get("targetWeightPct"),
            "source_link": "https://corbanu.com" + ev["href"],
            "source_text_sha256": ev.get("sourceSha256"),
            "price_convention": ev.get("priceConvention", ""),
            "note": ev.get("note", ""),
        }
        call.update(article_terms(ev["href"]))
        calls.append(call)
    out = {
        "schema": "pf-post-signals.calls.v1",
        "source": "https://corbanu.com/assets/portfolio/ledger.json",
        "ledger_updated_at": ledger["updatedAt"],
        "since": SINCE,
        "calls": calls,
        "other_mentions": OTHER_MENTIONS,
    }
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    json.dump(out, open(os.path.join(HERE, "data", "calls.json"), "w"), indent=1)
    print(f"{len(calls)} calls, {len(OTHER_MENTIONS)} other mentions")


if __name__ == "__main__":
    main()
