#!/usr/bin/env python3
"""Step 11: compare the imported Corbanu positions with step 1 (data/new_system_resolved.json).

Step 1 scored each Corbanu trade from the ledger's published reference price, with exits at the
first Corbanu tracker mark at or after entry + h. Step 11 scores the same trades like every other
post: entry = first hourly bar at or after the published time, exits = first bar at or after
post + h, on the venue's own hourly opens (Hyperliquid xyz perps, split-adjusted; xyz:ORCL as the
labelled stand-in for ORCLon). Every difference is classified:
  entry: reference quote vs the first hourly open after publication
  exit:  Corbanu tracker mark vs Hyperliquid hourly open (different source and time of day)
  ORCL:  stand-in perp vs the Ondo spot token step 1 marked
  newly resolved: a horizon that was pending in step 1 (2026-10-18 snapshot) and is reached now
Writes data/corbanu_vs_step1.json and prints the table.
"""
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pct(x):
    return "pending" if x is None else f"{x * 100:+.2f}%"


def main():
    with open(os.path.join(HERE, "data", "new_system_resolved.json")) as f:
        step1 = {c["call_id"]: c for c in json.load(f)["calls"]}
    rows = []
    for name in sorted(os.listdir(os.path.join(HERE, "records", "corbanu"))):
        with open(os.path.join(HERE, "records", "corbanu", name)) as f:
            rec = json.load(f)
        eid = rec["trade"]["ledger_event_id"]
        s1 = step1.get(eid)
        if s1 is None:
            rows.append({"event": eid, "note": "not in step 1"})
            continue
        if s1["side"] != rec["side"]:
            raise SystemExit(f"{eid}: side differs from step 1 ({s1['side']} vs {rec['side']})")
        entry_diff = rec["entry"]["price"] / s1["entry"] - 1
        hz = {}
        for h in ("1", "7", "30"):
            a, b = s1["returns"].get(h), rec["signed_returns"].get(h)
            if a is None and b is None:
                why = "pending in both"
            elif a is None:
                why = "newly resolved (pending in the step 1 snapshot)"
            elif b is None:
                why = "resolved in step 1, not yet here: " + rec["unresolved"].get(h, "")
            else:
                parts = []
                if abs(entry_diff) > 1e-12:
                    parts.append(f"entry {entry_diff * 100:+.2f}% (reference quote vs first hourly open)")
                parts.append("exit: Corbanu tracker mark vs Hyperliquid hourly open")
                if "stand_in" in rec["asset"]:
                    parts.append("ORCL priced from the xyz:ORCL stand-in, step 1 marked ORCLon")
                why = "; ".join(parts)
            hz[h] = {"step1": a, "step11": b, "diff": None if a is None or b is None else b - a, "why": why}
        rows.append({"event": eid, "asset": rec["asset"]["name"], "side": rec["side"],
                     "step1_entry": {"price": s1["entry"], "at": s1["called_at"], "basis": "published reference price"},
                     "step11_entry": rec["entry"], "entry_diff": entry_diff, "horizons": hz,
                     "stand_in": "stand_in" in rec["asset"], "adjustments": rec["asset"].get("adjustments", [])})
    out = {"compared": len(rows), "rows": rows}
    with open(os.path.join(HERE, "data", "corbanu_vs_step1.json"), "w") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    print("| trade | side | step 1 entry (ref) | step 11 entry (first open) | entry diff | 1d s1 -> s11 | 7d s1 -> s11 | 30d s1 -> s11 |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        hz = r["horizons"]
        print(f"| {r['event']} {r['asset']}{' (stand-in)' if r['stand_in'] else ''}{' (split-adj.)' if r['adjustments'] else ''} | {'long' if r['side'] > 0 else 'short'} | "
              f"{r['step1_entry']['price']:.6g} @ {r['step1_entry']['at'][:16]} | {r['step11_entry']['price']:.6g} @ {r['step11_entry']['at'][:16]} | "
              f"{r['entry_diff'] * 100:+.3f}% | " + " | ".join(f"{pct(hz[h]['step1'])} -> {pct(hz[h]['step11'])}" for h in ("1", "7", "30")) + " |")
    print()
    for r in rows:
        for h in ("1", "7", "30"):
            print(f"{r['event']} {h}d: {r['horizons'][h]['why']}")
    big = [(r["event"], h, r["horizons"][h]["diff"]) for r in rows for h in ("1", "7", "30") if r["horizons"][h]["diff"] is not None and abs(r["horizons"][h]["diff"]) > 0.02]
    print(f"\n{len(rows)} trades compared; sides identical; differences over 2 points: " + (", ".join(f"{e} {h}d {d * 100:+.2f}pt" for e, h, d in big) or "none"))


if __name__ == "__main__":
    main()
