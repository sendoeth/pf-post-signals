#!/usr/bin/env python3
"""Step 23: weekly venue re-check of every ticker in data/tickers.json.

For each registered coin, exactly its registered pair (source:symbol) is checked against the coin's
current CoinGecko price, with the step 22 rule: the pair must be trading AND within tickers.TOLERANCE.
  - passes      -> ok (a previous flag is cleared, with the date it recovered)
  - fails       -> flagged {since, why}; tickers.from_registry then answers "review" for new posts
  - the venue is never swapped: existing records keep being priced where they were; a flagged coin is
    listed for the owner (a delisted venue needs a decision, not a silent switch)

Calls: the five venues in bulk (no per-coin call) + one CoinGecko /coins/markets call per 250 coins.
Provider failure -> nothing written, exit 3 (the daily job runs this non-blocking on Mondays).
Writes sources/tickers/recheck/<date>.json and the flags in data/tickers.json.

usage: python3 tools/recheck_tickers.py [--dry-run]
"""
import argparse
import datetime as dt
import json
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TOOLS)
sys.path[:0] = [HERE, TOOLS]
import seed_tickers  # noqa: E402
import tickers  # noqa: E402

SCHEMA = "quanty.ticker_recheck.v1"


def coin_prices(bulk, ids):
    out = {}
    ids = sorted(ids)
    for i in range(0, len(ids), 250):
        rows = bulk._get(f"coingecko prices {i // 250 + 1}", f"{tickers.CG}/coins/markets?vs_currency=usd&per_page=250&ids={','.join(ids[i:i + 250])}", cg=True)
        for c in rows:
            if c.get("current_price") is not None:
                out[c["id"]] = {"price": float(c["current_price"]), "rank": c.get("market_cap_rank")}
    return out


def recheck(reg, bulk, prices, now):
    results, flagged, recovered = {}, [], []
    unchecked = []
    for t, e in sorted(reg["tickers"].items()):
        if e["source"] in getattr(bulk, "unreachable", []):
            # the venue did not answer this runner: not checked, the flag (or its absence) stays as it was
            results[t] = {"venue": f"{e['source']}:{e['symbol']}", "ok": None, "why": f"not checked: {e['source']} unreachable from this runner"}
            unchecked.append(t)
            continue
        try:
            v = bulk.venue(e["source"], e["symbol"])
        except tickers.Unavailable as err:             # step 26: a per-pool lookup that fails is "not checked", never a flag
            results[t] = {"venue": f"{e['source']}:{e['symbol']}", "ok": None, "why": f"not checked: {err}"}
            unchecked.append(t)
            continue
        cp = prices.get(e["coingecko_id"])
        if not cp:
            ok, why, diff = False, f"CoinGecko has no current price for {e['coingecko_id']}", None
        elif not v:
            ok, why, diff = False, f"{e['source']}:{e['symbol']} is no longer listed", None
        elif not v["trading"]:
            ok, why, diff = False, f"{e['source']}:{e['symbol']} is not trading (status {v['status']})", None
        elif not v["price"]:
            ok, why, diff = False, f"{e['source']}:{e['symbol']} has no price", None
        else:
            diff = v["price"] / cp["price"] - 1
            ok = abs(diff) <= tickers.TOLERANCE
            why = None if ok else f"{e['source']}:{e['symbol']} price {v['price']} is {diff:+.1%} from {e['name']}'s {cp['price']}"
        results[t] = {"venue": f"{e['source']}:{e['symbol']}", "ok": ok, "why": why, "diff": None if diff is None else round(diff, 6),
                      "venue_price": v and v.get("price"), "coin_price": cp and cp["price"], "rank_now": cp and cp["rank"]}
        if ok and e.get("flag"):
            recovered.append(t)
            e.pop("flag")
            e["recovered_at"] = now
        elif not ok:
            e["flag"] = {"since": (e.get("flag") or {}).get("since", now), "why": why, "last_checked": now}
            flagged.append(t)
        e["checked_at"] = now
        if cp and cp.get("rank"):
            e["rank"] = cp["rank"]
    return results, flagged, recovered, unchecked


def main(argv=None, root=HERE, bulk=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    now = seed_tickers.now_iso()
    reg_path = os.path.join(root, "data", "tickers.json")
    reg = tickers.load_registry(reg_path)
    try:
        bulk = bulk or seed_tickers.Bulk().load_venues(strict=False)
        prices = coin_prices(bulk, {e["coingecko_id"] for e in reg["tickers"].values()})
    except (tickers.Unavailable, KeyError, TypeError, ValueError) as e:
        print(f"FAILED (nothing written): provider unavailable: {e}", file=sys.stderr)
        return 3
    results, flagged, recovered, unchecked = recheck(reg, bulk, prices, now)
    doc = {"schema": SCHEMA, "checked_at": now, "calls": bulk.calls, "rule": {"tolerance": tickers.TOLERANCE, "venue_swapped": False},
           "counts": {"checked": len(results) - len(unchecked), "ok": sum(bool(r["ok"]) for r in results.values()), "flagged": len(flagged),
                      "recovered": len(recovered), "not_checked": len(unchecked)},
           "unreachable_venues": getattr(bulk, "unreachable", []),
           "flagged": {t: results[t]["why"] for t in flagged}, "recovered": recovered, "results": results}
    print(f"re-checked {doc['counts']['checked']} tickers: {doc['counts']['ok']} ok, {len(flagged)} flagged, {len(recovered)} recovered"
          + (f", {len(unchecked)} not checked ({', '.join(doc['unreachable_venues'])} unreachable)" if unchecked else ""))
    for t in flagged:
        print(f"  FLAG {t}: {results[t]['why']}")
    if a.dry_run:
        return 0
    out_dir = os.path.join(root, "sources", "tickers", "recheck")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"{now[:10]}.json"), "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    reg["rechecked_at"] = now
    with open(reg_path, "w") as f:
        json.dump(reg, f, indent=1)
        f.write("\n")
    print(f"wrote sources/tickers/recheck/{now[:10]}.json and the flags in data/tickers.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
