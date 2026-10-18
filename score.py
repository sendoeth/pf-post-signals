#!/usr/bin/env python3
"""Resolve and score both systems with identical rules; write data/*.json and the comparison table.

Scoring rule (both systems): a directional decision has side s in {+1 long, -1 short}, entry
price P0 and exit price Ph after h days. signed_return = s * (Ph / P0 - 1); hit = signed_return > 0.
Horizons 1, 7, 30 calendar days. Decisions whose exit lies past the last available price are
reported as pending, never guessed.

Old system (counterfactual): the unmodified dashboard classifier re-run as of each 2026 trading
day (data/counterfactual_regimes.json), mapped to trades by the unmodified policy in
signal_api.js: only NEUTRAL publishes direction; BTC/ETH/LINK bearish, SOL bullish (weak-symbol
inversion). Every other regime withholds. Entry = Binance UTC close of the as-of day.

New system: Corbanu published-trade ledger calls (data/calls.json). Entry = published
reference price at the published timestamp; exit = first Corbanu tracker mark at or after
entry time + h.
"""
import bisect
import datetime as dt
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
HORIZONS = (1, 7, 30)
SYMBOLS = ("BTC", "ETH", "SOL", "LINK")
# Unmodified from signal_api.js (SOVEREIGN_DIR after SOVEREIGN_WEAK_SYMBOL inversion of SOL).
POLICY = {
    "NEUTRAL": {"BTC": -1, "ETH": -1, "SOL": +1, "LINK": -1},
}
# Directions the policy *suppressed* (SOVEREIGN_DIR with the always-on SOL inversion, i.e. what
# would have been published without the regime filter), scored only as a shadow check of whether
# abstaining was right. 0 = no direction defined.
SUPPRESSED = {
    "SYSTEMIC": {"BTC": +1, "ETH": +1, "SOL": -1, "LINK": +1},
    "EARNINGS": {s: 0 for s in SYMBOLS},
    "DIVERGENCE": {s: 0 for s in SYMBOLS},
}
COMMON_START = "2026-09-04"


def d(s):
    return dt.date.fromisoformat(s[:10])


def plus(day, n):
    return (d(day) + dt.timedelta(days=n)).isoformat()


def summarize(rows, horizon):
    done = [r for r in rows if r["returns"].get(str(horizon)) is not None]
    rets = [r["returns"][str(horizon)] for r in done]
    if not rets:
        return {"n": 0, "pending": len(rows), "hit_rate": None, "mean_signed_return": None, "median_signed_return": None}
    return {
        "n": len(rets),
        "pending": len(rows) - len(rets),
        "hit_rate": round(sum(r > 0 for r in rets) / len(rets), 4),
        "mean_signed_return": round(statistics.mean(rets), 5),
        "median_signed_return": round(statistics.median(rets), 5),
    }


def regime_on(regimes, day):
    """Regime as of the last trading day on or before `day` (no look-ahead)."""
    days = [r["asof"] for r in regimes]
    i = bisect.bisect_right(days, day[:10]) - 1
    return regimes[i]["regime"] if i >= 0 else "UNKNOWN"


def old_system(regimes, prices):
    decisions, shadow = [], []
    for r in regimes:
        day = r["asof"]
        if day <= "2026-03-06":  # control day = last embedded day, reproduces the frozen live state
            continue
        trades = POLICY.get(r["regime"])
        for sym in SYMBOLS:
            p0 = prices[sym].get(day)
            if p0 is None:
                continue
            exits = {str(h): prices[sym].get(plus(day, h)) for h in HORIZONS}
            if trades:
                side = trades[sym]
                rets = {h: (side * (p / p0 - 1) if p else None) for h, p in exits.items()}
                decisions.append({"asof": day, "symbol": sym, "regime": r["regime"], "action": "EXECUTE",
                                  "side": side, "entry": p0, "returns": rets})
            else:
                decisions.append({"asof": day, "symbol": sym, "regime": r["regime"], "action": "WITHHOLD",
                                  "side": 0, "entry": p0, "returns": {}})
                side = SUPPRESSED.get(r["regime"], {}).get(sym, 0)
                if side:
                    rets = {h: (side * (p / p0 - 1) if p else None) for h, p in exits.items()}
                    shadow.append({"asof": day, "symbol": sym, "regime": r["regime"], "side": side, "returns": rets})
    return decisions, shadow


def mark_series(observations):
    series = {}
    for o in observations:
        for pid, m in o["marks"].items():
            series.setdefault(pid, []).append((m.get("observedAt") or o["at"], m["price"]))
    for pid in series:
        series[pid].sort()
    return series


def mark_at_or_after(series, when):
    times = [t for t, _ in series]
    i = bisect.bisect_left(times, when)
    return series[i] if i < len(series) else None


def new_system(calls, marks, regimes):
    rows = []
    for c in calls:
        side = 1 if c["side"] == "long" else -1
        p0 = c["reference_price"]
        start = dt.datetime.fromisoformat(c["called_at"].replace("Z", "+00:00"))
        rets, exits = {}, {}
        for h in HORIZONS:
            target = (start + dt.timedelta(days=h)).strftime("%Y-%m-%dT%H:%M:%S")
            hit = mark_at_or_after(marks[c["position_id"]], target)
            # a mark more than 2 days after the target is not a valid h-day exit
            ok = hit and (d(hit[0]) - d(target)).days <= 2
            exits[str(h)] = {"at": hit[0], "price": hit[1]} if ok else None
            rets[str(h)] = side * (hit[1] / p0 - 1) if ok else None
        rows.append({"call_id": c["call_id"], "ticker": c["ticker"], "side": side, "kind": c["kind"],
                     "pair_id": c.get("pair_id"), "called_at": c["called_at"], "entry": p0,
                     "weight_pct": c.get("target_weight_pct"), "regime": regime_on(regimes, c["called_at"]),
                     "exits": exits, "returns": rets, "source_link": c["source_link"]})
    return rows


def pair_rows(rows):
    """Score each published pair as one weighted decision: sum(w_i * r_i) / sum(|w_i|)."""
    pairs = {}
    for r in rows:
        if r["pair_id"]:
            pairs.setdefault(r["pair_id"], []).append(r)
    out = []
    for pid, legs in pairs.items():
        rets = {}
        for h in map(str, HORIZONS):
            if all(l["returns"][h] is not None for l in legs):
                gross = sum(abs(l["weight_pct"]) for l in legs)
                rets[h] = sum(abs(l["weight_pct"]) * l["returns"][h] for l in legs) / gross
            else:
                rets[h] = None
        out.append({"pair_id": pid, "called_at": legs[0]["called_at"], "regime": legs[0]["regime"],
                    "legs": [f'{l["ticker"]} {"long" if l["side"] > 0 else "short"} {abs(l["weight_pct"])}%' for l in legs],
                    "returns": rets})
    return out


def abstention(decisions, start=None):
    pool = [x for x in decisions if not start or x["asof"] >= start]
    return round(sum(x["action"] == "WITHHOLD" for x in pool) / len(pool), 4) if pool else None


def main():
    regimes = json.load(open(os.path.join(DATA, "counterfactual_regimes.json")))
    prices = json.load(open(os.path.join(DATA, "prices.json")))
    calls = json.load(open(os.path.join(DATA, "calls.json")))["calls"]
    marks = mark_series(json.load(open(os.path.join(HERE, "sources", "corbanu", "portfolio_marks.json")))["observations"])

    old, shadow = old_system(regimes, prices)
    new = new_system(calls, marks, regimes)
    pairs = pair_rows(new)
    executed = [x for x in old if x["action"] == "EXECUTE"]
    common_old = [x for x in executed if x["asof"] >= COMMON_START]

    result = {"horizons": HORIZONS, "common_window_start": COMMON_START,
              "regime_days": {}, "old": {}, "old_common_window": {}, "old_shadow_suppressed": {},
              "new_calls": {}, "new_pairs": {}, "per_regime": {}}
    for r in regimes[1:]:
        result["regime_days"][r["regime"]] = result["regime_days"].get(r["regime"], 0) + 1
    result["old_abstention_full"] = abstention(old)
    result["old_abstention_common"] = abstention(old, COMMON_START)
    days_new = sorted({r["asof"] for r in regimes if r["asof"] >= COMMON_START})
    first_call = min(c["called_at"][:10] for c in calls)
    result["new_abstention_common"] = round(sum(day < first_call for day in days_new) / len(days_new), 4)
    for h in HORIZONS:
        result["old"][h] = summarize(executed, h)
        result["old_common_window"][h] = summarize(common_old, h)
        result["old_shadow_suppressed"][h] = summarize(shadow, h)
        result["new_calls"][h] = summarize(new, h)
        result["new_pairs"][h] = summarize(pairs, h)
    for reg in sorted({x["regime"] for x in old} | {x["regime"] for x in new}):
        result["per_regime"][reg] = {
            "days": result["regime_days"].get(reg, 0),
            "old_executed": {h: summarize([x for x in executed if x["regime"] == reg], h) for h in HORIZONS},
            "old_shadow_if_not_abstained": {h: summarize([x for x in shadow if x["regime"] == reg], h) for h in HORIZONS},
            "new_calls": {h: summarize([x for x in new if x["regime"] == reg], h) for h in HORIZONS},
        }
    json.dump(old, open(os.path.join(DATA, "old_system_decisions.json"), "w"), indent=0)
    json.dump(shadow, open(os.path.join(DATA, "old_system_shadow.json"), "w"), indent=0)
    json.dump({"calls": new, "pairs": pairs}, open(os.path.join(DATA, "new_system_resolved.json"), "w"), indent=1)
    json.dump(result, open(os.path.join(DATA, "comparison.json"), "w"), indent=1)
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
