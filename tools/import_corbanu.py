#!/usr/bin/env python3
"""Step 11: import every Corbanu published trade as a position record.

Source: Corbanu's machine-readable tracker ledger (sources/corbanu/portfolio_ledger.json, the step 1
snapshot; the live corbanu.com/assets/portfolio/ledger.json had the same 8 events on 2026-10-30).
Each trade event becomes one record in records/corbanu/: side from the sign of the published target
weight, the ledger's reference price / weight / article link / article sha256 kept under "trade",
the article title as the quoted text. Prices come from the venue the trades are published on:
Hyperliquid's HIP-3 "xyz" stock perps. ORCLon (Ondo tokenized Oracle on Felix) has no public hourly
candles, and the Hyperliquid spot token named ORCL is unrelated, so the ORCL trade is priced from
the xyz:ORCL perp on the same stock and labelled as a stand-in.

The entry follows the same rule as every other post: the first hourly bar at or after the published
time. The ledger's reference price is kept next to it (tools/compare_corbanu.py compares both).

usage: python3 tools/import_corbanu.py
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import resolve  # noqa: E402

LEDGER = os.path.join(HERE, "sources", "corbanu", "portfolio_ledger.json")
OUT = os.path.join(HERE, "records", "corbanu")
SITE = "https://corbanu.com"
ORCL_STAND_IN = {
    "for": "ORCLon (Ondo tokenized Oracle, Felix spot), the instrument in Corbanu's ledger",
    "reason": "ORCLon has no public hourly candles; the Hyperliquid spot token named ORCL is unrelated "
              "(mark about $87 against Oracle near $146, 2.9 billion supply). Priced from the xyz:ORCL "
              "perp on the same stock instead.",
}


def title_of(href):
    slug = href.strip("/").split("/")[-1]
    path = os.path.join(HERE, "sources", "corbanu", f"posts_{slug}.txt")
    with open(path, encoding="utf-8") as f:
        first = next(line for line in f if line.strip())
    return first.strip().replace(" — Corbanu", "")


def main():
    with open(LEDGER, "rb") as f:
        blob = f.read()
    ledger = json.loads(blob)
    ledger_sha = hashlib.sha256(blob).hexdigest()
    positions = {p["id"]: p for p in ledger["positions"]}
    with open(os.path.join(HERE, "data", "calls.json")) as f:
        calls = json.load(f)
    pair_of = {c["call_id"]: c.get("pair_id") for c in (calls["calls"] if isinstance(calls, dict) else calls)}
    v, prices, n = resolve.validator(), resolve.Prices(), 0
    os.makedirs(OUT, exist_ok=True)
    for e in sorted(ledger["events"], key=lambda e: (e["at"], e["id"])):
        if e["type"] != "trade":
            continue
        pos = positions[e["positionId"]]
        symbol = pos["symbol"]
        asset = resolve.asset_info("XYZ:ORCL" if symbol == "ORCLon" else "XYZ:" + symbol)
        if symbol == "ORCLon":
            asset["stand_in"] = ORCL_STAND_IN
        acts = resolve.corporate_actions(asset["symbol"])
        if acts:
            asset["adjustments"] = [{"at": a["at"], "ratio": a["ratio"], "kind": a["kind"]} for a in acts]
        side = 1 if e["targetWeightPct"] > 0 else -1
        post = {"id": f"corbanu:{e['id']}", "url": SITE + e["href"], "author": "Corbanu", "posted_at": e["at"][:19] + "Z",
                "posted_at_source": "ledger", "source": "corbanu", "text": title_of(e["href"]), "receipt_sha256": e["sourceSha256"]}
        rec = resolve.resolve(post, asset, prices.series(asset, post["posted_at"]), prices.label, side)
        rec["trade"] = {"ledger_event_id": e["id"], "position_id": e["positionId"], "reference_price": e["price"],
                        "target_weight_pct": e["targetWeightPct"], "article_url": SITE + e["href"],
                        "source_sha256": e["sourceSha256"], "price_convention": e.get("priceConvention", ""),
                        "venue": pos.get("venue", ""), "pair_id": pair_of.get(e["id"]), "ledger_sha256": ledger_sha}
        rec["asset_choice"] = {"method": "ledger", "terms": [symbol],
                               "reason": "instrument named in Corbanu's published ledger" + ("; priced via stand-in (see asset.stand_in)" if symbol == "ORCLon" else "")}
        resolve.check_record(v, rec)
        path = os.path.join(OUT, f"{e['id']}_{asset['name'].replace(':', '-')}.json")
        with open(path, "w") as f:
            json.dump(rec, f, indent=1, ensure_ascii=False)
            f.write("\n")
        n += 1
        en = rec["entry"]
        print(f"{e['id']:<12} {asset['name']:<11} {'long ' if side > 0 else 'short'} ref {e['price']} @ {e['at'][:16]} -> "
              f"entry {en['price'] if en else '-'} @ {en['at'][:16] if en else '-'}; for the call {resolve.pct(side * rec['change_since_post']) if rec['change_since_post'] is not None else 'unresolved'}"
              + ("  [stand-in xyz:ORCL for ORCLon]" if symbol == "ORCLon" else ""))
    print(f"{n} Corbanu trades imported from {os.path.relpath(LEDGER, HERE)} (sha256 {ledger_sha}) -> {os.path.relpath(OUT, HERE)}")


if __name__ == "__main__":
    main()
