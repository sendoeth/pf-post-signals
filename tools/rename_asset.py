#!/usr/bin/env python3
"""Step 22: rename an asset to its plain ticker (e.g. binance:ZECUSDT -> ZEC) without changing a number.

  python3 tools/rename_asset.py binance:ZECUSDT ZEC [--report FILE]

1. snapshot every position on the old asset and every caller score from web/data/charts.json
2. the new name must be a confirmed ticker (tickers.py) priced on exactly the record's source:symbol
   (so the series, entry and exits are the same bars); its receipt is registered in data/tickers.json
3. rename: the records (file name + asset.name, asset.renamed_from), data/lifecycle.json keys,
   intake/context files, the candle file web/data/ohlc/<name>.json + its index entry, and add the
   old position URLs to data/redirects.json (tools/prerender.py writes them as static redirects)
4. rebuild web/data/charts.json + pages, then compare: entry, exits, moves, signed returns, latest,
   status, closed, best and every caller score must be equal; anything else fails (exit 1)
"""
import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TOOLS)
sys.path[:0] = [HERE, TOOLS]
import build_chart  # noqa: E402
import prerender  # noqa: E402
import tickers  # noqa: E402
from add_call import file_name  # noqa: E402

SAME = ("side", "status", "entry", "exits", "moves", "signed_returns", "unresolved", "latest", "change_since_post", "closed", "best")


def load(path):
    with open(path) as f:
        return json.load(f)


def dump(path, obj, **kw):
    with open(path, "w") as f:
        json.dump(obj, f, **(kw or {"indent": 1}))
        f.write("\n")


def snapshot(bundle, asset):
    pos = {p["post"]["id"]: {k: p.get(k) for k in SAME} for a in bundle["assets"] if a["name"] == asset for p in a["posts"]}
    scores = {n: {k: c[k] for k in ("score", "display", "rank", "scored", "calls_total")} for n, c in bundle["ratings"]["callers"].items()}
    return pos, scores


def rename(old, new, root=HERE, net=None, receipt=None):
    charts = os.path.join(root, "web", "data", "charts.json")
    before_blob = open(charts, "rb").read()
    before = json.loads(before_blob)
    pos_before, scores_before = snapshot(before, old)
    if not pos_before:
        raise SystemExit(f"no positions on {old}")
    recs = [f for f in glob.glob(os.path.join(root, "records", "**", "*.json"), recursive=True) if load(f)["asset"]["name"] == old]
    src = {(load(f)["asset"]["source"], load(f)["asset"]["symbol"]) for f in recs}
    if len(src) != 1:
        raise SystemExit(f"{old}: records priced on several sources {src}")
    source, symbol = src.pop()
    r = receipt or tickers.resolve_ticker(new, net)
    if r["status"] != "ok":
        raise SystemExit(f"{new} is not a confirmed ticker: {r['reason']}")
    if (r["chosen"]["source"], r["chosen"]["symbol"]) != (source, symbol):
        raise SystemExit(f"{new} resolves to {r['chosen']['source']}:{r['chosen']['symbol']}, the records use {source}:{symbol}: not a pure rename")
    entry = tickers.register(r, root)
    moved = []
    for f in recs:
        rec = load(f)
        rec["asset"]["name"], rec["asset"]["renamed_from"] = new, old
        to = os.path.join(os.path.dirname(f), file_name(rec["post"]["id"], new))
        dump(to, rec)
        if to != f:
            os.remove(f)
        moved.append((os.path.relpath(f, root), os.path.relpath(to, root), rec["post"]["id"]))
    life_p = os.path.join(root, "data", "lifecycle.json")
    if os.path.exists(life_p):
        life = load(life_p)
        keys = {(k.rsplit("|", 1)[0] + "|" + new if k.endswith("|" + old) else k): v for k, v in life["positions"].items()}
        if list(keys) != list(life["positions"]):            # rewrite only when a position of this asset is listed
            life["positions"] = keys
            dump(life_p, life)
    for f in glob.glob(os.path.join(root, "intake", "context", "*.json")):
        c = load(f)
        if c.get("asset") == old:
            c["asset"] = new
            dump(f, c)
    ohlc_dir = os.path.join(root, "web", "data", "ohlc")
    idx_p = os.path.join(ohlc_dir, "index.json")
    if os.path.exists(idx_p):
        idx = load(idx_p)
        meta = idx["files"].pop(old, None)
        if meta:
            doc = load(os.path.join(ohlc_dir, meta["file"]))
            doc["asset"] = new
            path = os.path.join(ohlc_dir, f"{new}.json")
            with open(path, "w") as f:
                json.dump(doc, f, separators=(",", ":"))
                f.write("\n")
            os.remove(os.path.join(ohlc_dir, meta["file"]))
            meta["file"], meta["sha256"] = f"{new}.json", hashlib.sha256(open(path, "rb").read()).hexdigest()
            idx["files"][new] = meta
            idx["files"] = dict(sorted(idx["files"].items()))
            dump(idx_p, idx)
    red_p = os.path.join(root, "data", "redirects.json")
    red = load(red_p) if os.path.exists(red_p) else {"schema": "quanty.redirects.v1", "note": "old page URL -> the page it moved to (tools/prerender.py writes a static redirect)", "pages": {}}
    for _, _, pid in moved:
        red["pages"][f"pos-{prerender.slug(pid, old)}.html"] = {"to": f"pos-{prerender.slug(pid, new)}.html", "reason": f"{old} is now shown as its plain ticker {new}; prices and results are unchanged."}
    dump(red_p, red)
    bundle = build_chart.build(os.path.join(root, "records"))
    dump(charts, bundle)
    prerender.main(os.path.join(root, "web"))
    pos_after, scores_after = snapshot(bundle, new)
    problems = []
    if set(pos_after) != set(pos_before):
        problems.append(f"positions before {sorted(pos_before)} after {sorted(pos_after)}")
    for pid, b in pos_before.items():
        for k, v in b.items():
            if pos_after.get(pid, {}).get(k) != v:
                problems.append(f"{pid} {k}: {v} -> {pos_after.get(pid, {}).get(k)}")
    if scores_after != scores_before:
        problems.append(f"caller scores moved: {scores_before} -> {scores_after}")
    if any(a["name"] == old for a in bundle["assets"]):
        problems.append(f"{old} still in the bundle")
    report = {"old": old, "new": new, "coin": {k: r["coin"][k] for k in ("id", "name", "rank", "price")}, "venue": f"{source}:{symbol}",
              "registry_entry": entry, "records": [{"from": a, "to": b} for a, b, _ in moved],
              "redirects": {f"pos-{prerender.slug(pid, old)}.html": f"pos-{prerender.slug(pid, new)}.html" for _, _, pid in moved},
              "bundle_sha256_before": hashlib.sha256(before_blob).hexdigest(), "bundle_sha256_after": hashlib.sha256(open(charts, "rb").read()).hexdigest(),
              "positions_before": pos_before, "positions_after": pos_after, "caller_scores_before": scores_before, "caller_scores_after": scores_after,
              "equal": not problems, "problems": problems}
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--report")
    a = ap.parse_args()
    rep = rename(a.old, a.new.upper())
    if a.report:
        os.makedirs(os.path.dirname(os.path.abspath(a.report)), exist_ok=True)
        dump(a.report, rep)
    for x in rep["records"]:
        print(f"record    {x['from']} -> {x['to']}")
    print(f"coin      {rep['coin']['name']} [{rep['coin']['id']}] #{rep['coin']['rank']} on {rep['venue']} (registry: {rep['registry_entry']['receipt']})")
    for pid, b in rep["positions_before"].items():
        aft = rep["positions_after"].get(pid, {})
        for k in ("entry", "exits", "signed_returns", "latest", "status", "closed", "best"):
            print(f"{pid} {k:<15} {'EQUAL' if b.get(k) == aft.get(k) else 'DIFF '} {json.dumps(b.get(k))[:110]}")
    for n in rep["caller_scores_before"]:
        b, aft = rep["caller_scores_before"][n], rep["caller_scores_after"].get(n)
        print(f"score     @{n:<15} {'EQUAL' if b == aft else 'DIFF '} {b['score']} -> {aft['score'] if aft else None}")
    print(f"bundle    {rep['bundle_sha256_before']} -> {rep['bundle_sha256_after']}")
    print("ALL EQUAL" if rep["equal"] else "PROBLEMS:\n - " + "\n - ".join(rep["problems"]))
    sys.exit(0 if rep["equal"] else 1)


if __name__ == "__main__":
    main()
