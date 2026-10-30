#!/usr/bin/env python3
"""Step 6: paste a post link -> receipt -> detected asset -> price record -> rebuilt chart bundle.

  python3 add_post.py URL [URL ...] [--asset NAME] [--side long|short]

1. ingest.py saves (or reuses) the post receipt
2. detect.py proposes the asset; --asset overrides it. "needs review" stops that post here:
   nothing is resolved on an ambiguous guess
3. resolve.py resolves it against live hourly prices -> records/posts/<id>_<asset>.json
4. build_chart.py rebuilds web/data/charts.json (the page picks it up on the next deploy)
"""
import argparse
import json
import os
import sys

import build_chart
import detect
import ingest
import resolve

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--asset", help="manual asset, overrides the detector (one url at a time)")
    ap.add_argument("--side", help="long or short, if the post states one")
    ap.add_argument("--reason", help="why the asset was chosen by hand (required with --asset; stored in the record)")
    ap.add_argument("--out", default=os.path.join(HERE, "records", "posts"))
    a = ap.parse_args()
    if a.asset and len(a.urls) > 1:
        ap.error("--asset applies to one url at a time")
    if a.asset and not a.reason:
        ap.error("--asset needs --reason: a manual asset choice is always explained")
    prices, v, failed = resolve.Prices(), resolve.validator(), 0
    for url in a.urls:
        try:
            path, receipt, created = ingest.ingest(url, avatars=ingest.AVATARS)
        except ingest.IngestError as e:
            print(f"STOP {url}: {e}")
            failed += 1
            continue
        d = detect.detect(receipt.get("text"), manual=a.asset)
        print(f"{'saved ' if created else 'reused'} receipt {os.path.relpath(path, HERE)}; detector: {d['status']} "
              f"{d['asset'] or ''} {[m['term'] for m in d['matched']]} {d['reason'] or ''}".rstrip())
        if d["status"] not in ("detected", "manual"):
            print(f"STOP {url}: needs review ({d['reason']}); rerun with --asset to resolve it")
            failed += 1
            continue
        choice = {"method": "manual" if d["status"] == "manual" else "detector",
                  "terms": [m["term"] for m in detect.detect(receipt.get("text"))["matched"]],
                  "reason": a.reason if d["status"] == "manual" else None}
        records, _, errors = resolve.run([{"receipt": path, "asset": d["asset"], "side": a.side, "asset_choice": choice}], prices, a.out, v)
        for err in errors:
            print(f"STOP {url}: {err}")
            failed += 1
        for r in records:
            e = r["entry"]
            print(f"record {r['post']['id']} {r['asset']['name']} {r['status']}: entry "
                  f"{e['price'] if e else '-'} @ {e['at'] if e else '-'}, since post {resolve.pct(r['change_since_post'])}, "
                  f"session_lag_days {r['resolved_with']['session_lag_days']}")
    bundle = build_chart.build(os.path.join(HERE, "records"))
    with open(os.path.join(HERE, "web", "data", "charts.json"), "w") as f:
        json.dump(bundle, f, indent=1)
        f.write("\n")
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import prerender
    prerender.main(os.path.join(HERE, "web"))
    print(f"bundle: {bundle['records_scanned']} records scanned, {bundle['posts_drawn']} drawn, "
          f"{len(bundle['superseded'])} superseded, {len(bundle['refused'])} refused")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
