#!/usr/bin/env python3
"""Step 4 parity: rerun all 16 step 3 BobLoukas rows through resolve.py and compare exactly.

Inputs are the step 3 labels (receipt + instrument + side) and the saved step 3 price snapshot
(data/hourly_prices.json, the bars data/bobloukas_calls.json was computed from), so the check is
not affected by later Yahoo revisions. Compared with == (no tolerance): entry bar, every exit bar,
every signed return (side * move) and every unresolved reason. Writes records/bobloukas/*.json and
data/parity_bobloukas.json; exit 1 on any mismatch.
"""
import json
import os
import sys

import resolve

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources", "bobloukas")
DATA = os.path.join(HERE, "data")


def main():
    labels = json.load(open(os.path.join(SRC, "labels.json")))
    step3 = json.load(open(os.path.join(DATA, "bobloukas_calls.json")))
    items = [{"receipt": os.path.join("sources", "bobloukas", "receipts", f"{c['id']}.json"),
              "asset": c["instrument"], "side": c["side"]} for c in labels["calls"]]
    os.chdir(HERE)
    records, dupes, errors = resolve.run(items, resolve.Prices(os.path.join(DATA, "hourly_prices.json")),
                                         os.path.join(HERE, "records", "bobloukas"))
    by_key = {(r["post"]["id"], r["asset"]["name"]): r for r in records}
    rows, fails = [], []
    for old in step3:
        key = (old["post_id"], old["instrument"])
        new = by_key.get(key)
        diffs = []
        if new is None:
            diffs.append("missing record")
        else:
            if new["post"]["posted_at"] != old["posted_at"]:
                diffs.append(f"posted_at {new['post']['posted_at']} != {old['posted_at']}")
            if new["entry"] != old["entry"]:
                diffs.append(f"entry {new['entry']} != {old['entry']}")
            for h in map(str, resolve.HORIZONS):
                if new["exits"].get(h) != old["exits"].get(h):
                    diffs.append(f"exit {h}d {new['exits'].get(h)} != {old['exits'].get(h)}")
                if new["signed_returns"].get(h) != old["returns"].get(h):
                    diffs.append(f"return {h}d {new['signed_returns'].get(h)!r} != {old['returns'].get(h)!r}")
            if new["unresolved"] != old["unresolved"]:
                diffs.append(f"unresolved {new['unresolved']} != {old['unresolved']}")
        rows.append({"post_id": key[0], "asset": key[1], "status": old["status"], "exact": not diffs,
                     "entry": old["entry"], "returns": old["returns"], "diffs": diffs})
        if diffs:
            fails.append(f"{key[0]} {key[1]}: " + "; ".join(diffs))
    extra = sorted(set(by_key) - {(o["post_id"], o["instrument"]) for o in step3})
    exact = sum(r["exact"] for r in rows)
    out = {"compared": len(rows), "exact": exact, "records_written": len(records), "extra_records": extra,
           "duplicates": dupes, "errors": errors, "price_snapshot": "data/hourly_prices.json",
           "comparison": "== on entry, exits, signed returns, unresolved reasons (no tolerance)", "rows": rows}
    with open(os.path.join(DATA, "parity_bobloukas.json"), "w") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    for r in rows:
        ret = " ".join(f"{h}d {resolve.pct(r['returns'].get(h))}" for h in ("1", "7", "30"))
        print(f"{'EXACT' if r['exact'] else 'DIFF '} {r['post_id']} {r['asset']:<6} {r['status']:<11} "
              f"entry {r['entry']['price']} @ {r['entry']['at']} | {ret}")
    for f_ in fails + errors + [f"extra record {e}" for e in extra]:
        print(" -", f_)
    print(f"parity: {exact}/{len(rows)} exact, {len(records)} records schema-valid, "
          f"{len(dupes)} duplicates, {len(errors)} errors")
    sys.exit(0 if exact == len(rows) == len(records) and not errors and not extra else 1)


if __name__ == "__main__":
    main()
