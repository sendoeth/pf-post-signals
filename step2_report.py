#!/usr/bin/env python3
"""Step 2 before/after: gate evaluation, gated re-score of the old pipeline, live feed state.
Appends a generated section to RESULTS.md (between markers) and writes data/step2.json."""
import json
import os

import gate
import score

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
START, END = "<!-- step2:start -->", "<!-- step2:end -->"


def pct(v):
    return "—" if v is None else f"{v * 100:+.2f}%"


def rate(v):
    return "—" if v is None else f"{v * 100:.0f}%"


def main():
    regimes = json.load(open(os.path.join(DATA, "counterfactual_regimes.json")))
    prices = json.load(open(os.path.join(DATA, "prices.json")))
    ev = json.load(open(os.path.join(DATA, "gate_evaluation.json")))
    status = json.load(open(os.path.join(HERE, "live", "status.json")))
    raw = [(r["asof"], r["regime"]) for r in regimes if r["asof"] > "2026-03-06"]
    gated = gate.apply_gate(raw, 2)
    gated_regimes = [regimes[0]] + [{"asof": s, "regime": eff} for s, _, eff, _ in gated]

    def executed(regs):
        old, _ = score.old_system(regs, prices)
        ex = [x for x in old if x["action"] == "EXECUTE"]
        return {h: score.summarize(ex, h) for h in score.HORIZONS}

    before, after = executed(regimes), executed(gated_regimes)
    out = {"gate_min_days": 2, "gate_version": gate.GATE_VERSION, "evaluation": ev["evaluation"],
           "old_executed_raw": before, "old_executed_gated": after, "live_status": status}
    json.dump(out, open(os.path.join(DATA, "step2.json"), "w"), indent=1)

    lines = [START, "", "## Step 2: live feed + regime duration gate (before / after)", "",
             "| | Before | After |", "|---|---|---|",
             "| Dashboard price history | embedded, ends **2026-03-06** (live ledger frozen at SYSTEMIC 77 since 2026-03-19) | "
             f"rebuilt daily by `live_feed.py`; latest session **{status['dataAsOf']}**, {status['sessions_classified']} sessions classified since 2026-03-09 |",
             f"| Live API `/regime/current` | SYSTEMIC, confidence 77, duration 228 d, no data date | "
             f"{status['effective']} (raw {status['rawRegime']}), effective since {status['effectiveSince']}, `dataAsOf` {status['dataAsOf']}, stale=false |",
             "| Stale / unknown regime | unknown ids fell back to NEUTRAL (publishes direction) | `STALE_DATA` after 4 days without data; unknown ids withhold |",
             "| Ledger push (`post-fiat-signals`) | rejected since 2026-06-09, 25,464 unpushed auto-commits, log said \"Pushed\" anyway | "
             "merged + pushed, shared lock, rebase before push, real failure reporting, token via askpass |",
             "", "### Regime changes with and without the gate (replay 2026-03-09 → 2026-10-16)", "",
             "| Minimum duration | Regime changes | Weekend-adjacent changes | Effective days |", "|---|---|---|---|"]
    for row in ev["evaluation"]:
        mark = " ← chosen" if row["min_days"] == 2 else (" (raw classifier)" if row["min_days"] == 1 else "")
        lines.append(f'| {row["min_days"]} session(s){mark} | {row["regime_changes"]} | {row["weekend_driven"]} | '
                     f'{", ".join(f"{k} {v}" for k, v in sorted(row["effective_days"].items()))} |')
    two = next(r for r in ev["evaluation"] if r["min_days"] == 2)
    lines += ["", "Changes with the 2-session gate: " + ", ".join(f'{c["on"]} {c["from"]}→{c["to"]}' for c in two["changes"]) + ".",
              "", "Weekend-adjacent = the session before the change was a Friday or a Monday (Fri→Mon / Mon→Tue flips). "
              "Step 1 counted 14 of the 18 post-May changes this way; over the whole replay it is 15 of 22.",
              "", "### Old pipeline executed calls, raw vs gated regimes", "",
              "| | 1d | 7d | 30d |", "|---|---|---|---|"]
    for name, res in (("raw classifier", before), ("2-session gate", after)):
        lines.append(f"| {name} | " + " | ".join(f'{rate(res[h]["hit_rate"])} (n={res[h]["n"]}) {pct(res[h]["mean_signed_return"])}'
                                                for h in score.HORIZONS) + " |")
    lines += ["", "The gate removes the weekend flapping without changing the one tradeable episode: NEUTRAL still runs 17 "
              "sessions, starting and ending one session later.", "", END]
    path = os.path.join(HERE, "RESULTS.md")
    text = open(path).read()
    if START in text:
        text = text[:text.index(START)] + text[text.index(END) + len(END):]
    open(path, "w").write(text.rstrip() + "\n\n" + "\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
