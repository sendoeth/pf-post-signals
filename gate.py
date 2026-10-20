#!/usr/bin/env python3
"""Minimum-duration regime gate: a pure function of the raw per-session regime sequence.

A new raw regime becomes effective only after it has been the raw output for `min_days`
consecutive trading sessions; until then the previous effective regime stays in force.
Because the effective regime is recomputed from the full raw sequence every time, re-running
a session cannot double-count it and there is no mutable state to corrupt.

`python3 gate.py` evaluates min_days 1..5 on data/counterfactual_regimes.json and writes
data/gate_evaluation.json.
"""
import datetime as dt
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
GATE_VERSION = 1


def apply_gate(raw, min_days):
    """raw: [(session, regime)] in order. Returns [(session, raw, effective, effective_since)]."""
    out, effective, since = [], None, None
    candidate, streak = None, 0
    for session, regime in raw:
        if effective is None:  # bootstrap: first observed regime is in force
            effective, since = regime, session
        if regime == effective:
            candidate, streak = None, 0
        else:
            streak = streak + 1 if regime == candidate else 1
            candidate = regime
            if streak >= min_days:
                effective, since, candidate, streak = regime, session, None, 0
        out.append((session, regime, effective, since))
    return out


def changes(seq):
    return [(a[0], b[0], a[2], b[2]) for a, b in zip(seq, seq[1:]) if a[2] != b[2]]


def weekend_driven(change):
    """A change whose previous session is a Friday (Fri->Mon) or whose session is a Monday->Tuesday flip."""
    prev_day = dt.date.fromisoformat(change[0])
    return prev_day.weekday() in (0, 4)


def evaluate(raw, max_days=5):
    rows = []
    for n in range(1, max_days + 1):
        seq = apply_gate(raw, n)
        ch = changes(seq)
        days = {}
        for _, _, eff, _ in seq:
            days[eff] = days.get(eff, 0) + 1
        rows.append({"min_days": n, "regime_changes": len(ch),
                     "weekend_driven": sum(weekend_driven(c) for c in ch),
                     "effective_days": days,
                     "changes": [{"on": c[1], "from": c[2], "to": c[3]} for c in ch]})
    return rows


def main():
    regimes = json.load(open(os.path.join(HERE, "data", "counterfactual_regimes.json")))
    raw = [(r["asof"], r["regime"]) for r in regimes if r["asof"] > "2026-03-06"]
    result = {"gate_version": GATE_VERSION, "sessions": len(raw), "first": raw[0][0], "last": raw[-1][0],
              "evaluation": evaluate(raw)}
    json.dump(result, open(os.path.join(HERE, "data", "gate_evaluation.json"), "w"), indent=1)
    for row in result["evaluation"]:
        print(f'min_days={row["min_days"]}: {row["regime_changes"]:2d} changes, {row["weekend_driven"]:2d} weekend-driven, '
              f'days {row["effective_days"]}')


if __name__ == "__main__":
    main()
