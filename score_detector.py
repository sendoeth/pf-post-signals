#!/usr/bin/env python3
"""Step 6: score detect.py against the 59 hand-labelled BobLoukas candidates from step 3.

Ground truth comes from sources/bobloukas/labels.json (calls and reiterations carry the instrument;
the BTC/gold pair post carries two) and data/bobloukas_exclusions.json (off-topic). Posts that
are not calls have no asset label, so for them the table only counts what the detector said; it
is not scored as right or wrong. Text = the saved full-text receipt.

usage: python3 score_detector.py   -> data/detector_scores.json + table on stdout
"""
import collections
import json
import os

import detect

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources", "bobloukas")


def main():
    with open(os.path.join(SRC, "labels.json")) as f:
        labels = json.load(f)
    with open(os.path.join(HERE, "data", "bobloukas_exclusions.json")) as f:
        off_topic = json.load(f)["off_topic"]
    truth = collections.defaultdict(set)
    for c in labels["calls"]:
        truth[c["id"]].add(c["instrument"])
    groups = {"call": sorted(truth), "excluded": [e["id"] for e in labels["excluded"]], "off_topic": list(off_topic)}
    amap = detect.load_map()
    rows, table = [], collections.OrderedDict()
    for group, ids in groups.items():
        for pid in ids:
            with open(os.path.join(SRC, "receipts", f"{pid}.json")) as f:
                text = json.load(f)["text"]
            d = detect.detect(text, amap)
            want = sorted(truth.get(pid, []))
            if group != "call":
                outcome = "detected an asset" if d["status"] == "detected" else "needs review"
                kind = "not a call (not scored)"
            elif len(want) > 1:
                kind = "call, two-asset pair"
                found = sorted({m["asset"] for m in d["matched"]})
                outcome = ("needs review, both assets found" if d["status"] == "needs_review" and found == want
                           else "wrong: " + (d["asset"] or ",".join(found) or "none"))
            else:
                kind = "call, one asset"
                outcome = ("exact match" if d["asset"] == want[0] else
                           "needs review" if d["status"] == "needs_review" else "wrong asset")
            table.setdefault(kind, collections.Counter())[outcome] += 1
            rows.append({"post_id": pid, "group": group, "label": want, "detector": d, "outcome": outcome})
    out = {"labelled_posts": len(rows), "groups": {k: len(v) for k, v in groups.items()},
           "table": {k: dict(v) for k, v in table.items()}, "rows": rows,
           "asset_map_sha256": __import__("hashlib").sha256(open(detect.MAP_PATH, "rb").read()).hexdigest()}
    with open(os.path.join(HERE, "data", "detector_scores.json"), "w") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    print(f"{len(rows)} labelled posts: " + ", ".join(f"{k} {v}" for k, v in out["groups"].items()))
    print("| post kind | outcome | n |\n|---|---|---|")
    for kind, c in table.items():
        for outcome, n in sorted(c.items()):
            print(f"| {kind} | {outcome} | {n} |")
    for r in rows:
        if r["group"] == "call" and r["outcome"] != "exact match":
            print(f"call {r['post_id']} label {r['label']}: {r['outcome']} ({r['detector']['reason'] or r['detector']['asset']}; "
                  f"matched {[m['term'] for m in r['detector']['matched']]})")


if __name__ == "__main__":
    main()
