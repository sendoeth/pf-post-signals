#!/usr/bin/env python3
"""Render AUTHORS.md (step 3 per-author comparison) from data/author_comparison.json + data/bobloukas_*.json."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def pct(v):
    return "—" if v is None else f"{v * 100:+.2f}%"


def rate(v):
    return "—" if v is None else f"{v * 100:.0f}%"


def cell(s):
    return f'{rate(s["hit_rate"])} · {pct(s["mean_signed_return"])} (n={s["n"]}{", " + str(s["pending"]) + " unresolved" if s["pending"] else ""}) `{s["sample_flag"]}`'


def main():
    comp = json.load(open(os.path.join(DATA, "author_comparison.json")))
    rows = json.load(open(os.path.join(DATA, "bobloukas_calls.json")))
    pairs = json.load(open(os.path.join(DATA, "bobloukas_pairs.json")))
    c = comp["bobloukas_counts"]
    L = ["# Step 3: per-author comparison", "",
         "Two authors scored with the identical step 1 rule: `signed_return = side x (P_exit / P_entry - 1)`, hit = signed_return > 0, "
         "horizons 1 / 7 / 30 days, exits more than 2 days late or not yet reached are **unresolved**, never guessed.", "",
         f"Sample flags: `insufficient` n < {comp['min_n_reportable']}, `unreliable` n < {comp['min_n_reliable']}, `ok` otherwise. "
         "**Every cell below is flagged**: neither author has enough resolved calls for a hit rate to mean anything yet.", "",
         "## Hit rate · mean signed return per call", "",
         "| Author | Calls | 1d | 7d | 30d |", "|---|---|---|---|---|"]
    for name, a in comp["authors"].items():
        L.append(f"| {name} | {a['calls']} | " + " | ".join(cell(a["by_horizon"][str(h)]) for h in (1, 7, 30)) + " |")
    L += ["", "## Pairs (scored as one unit)", "", "| Author | 1d | 7d | 30d |", "|---|---|---|---|"]
    for name, a in comp["authors"].items():
        L.append(f"| {name} | " + " | ".join(cell(a["pairs_by_horizon"][str(h)]) for h in (1, 7, 30)) + " |")
    L += ["", "## By pipeline regime at call time (7d)", "", "| Author | Regime | 7d |", "|---|---|---|"]
    for name, a in comp["authors"].items():
        for g, v in a["by_regime"].items():
            L.append(f"| {name} | {g} | {cell(v['7'])} |")
    L += ["", "Regime = the live pipeline's 2-session-gated regime (step 2) on the call date.", "",
          "## @BobLoukas calls (scored)", "",
          "| Posted (UTC) | Call | Regime | Entry | 1d | 7d | 30d | Post |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["status"] != "call":
            continue
        side = "long" if r["side"] > 0 else "short"
        e = r["entry"]
        L.append(f"| {r['posted_at'][:16]} | {side} {r['instrument']}{' (conditional)' if r['conditional'] else ''} | {r['regime']} | "
                 f"{e['price'] if e else '—'} @ {e['at'][:13] if e else '—'} | " + " | ".join(
                     pct(r["returns"].get(h)) if r["returns"].get(h) is not None else "unresolved" for h in ("1", "7", "30"))
                 + f" | [post]({r['url']}) |")
    L += ["", "| Pair | Legs | 1d | 7d | 30d |", "|---|---|---|---|---|"]
    for p in pairs:
        L.append(f"| {p['pair_id']} | {', '.join(p['legs'])} ({p['weighting']}) | " + " | ".join(
            pct(p["returns"].get(h)) if p["returns"].get(h) is not None else "unresolved" for h in ("1", "7", "30")) + " |")
    L += ["", "## @BobLoukas coverage", "",
          f"- own posts captured 2026-09-01 → 2026-10-28: **{c['own_posts_captured']}** (read-only X search in date slices, gaps refilled; see `sources/bobloukas/COVERAGE.md`)",
          f"- keyword candidates: 59, all labelled; scored calls **{c['scored_calls']}**, reiterations (same instrument + direction within 7 days) **{c['reiterations']}**, "
          f"excluded with a stated reason **{c['excluded_with_reason']}** + 23 non-calls in `data/bobloukas_exclusions.json`",
          f"- unresolved horizon cells among scored calls: **{c['unresolved_cells']}** (30d horizons not yet reached for calls after 2026-09-28; 7d for the 2026-10-23 silver call)",
          "", "## Limitations", "",
          "- **Corbanu rows are the step 1 snapshot** (resolved 2026-10-18), reused unchanged so the scoring-parity check holds; some of its unresolved 30d cells have since matured and are not re-resolved here.",
          "- **Tiny samples.** 10 BobLoukas calls and 8 Corbanu legs; every cell is flagged. Nothing here ranks the authors.",
          "- **Different styles and instruments.** Corbanu publishes sized trades with reference prices; BobLoukas posts cycle-based views, mostly BTC, "
          "silver, gold, copper miners and US stocks. Entries for BobLoukas are the first hourly bar after the post, not his fills.",
          "- **Labelling is manual** under written rules (`sources/bobloukas/labels.json`). Cycle commentary is often deliberately two-sided; those posts "
          "are excluded, which favours his clearer calls. One included call is conditional-leaning (2026-09-18, marked).",
          "- **Instrument mapping.** \"Stocks\" → SPY, \"silver\" → SI=F, \"gold futures\" → GC=F, \"COPX\" → COPX; pair legs equal-weighted because no weights were stated.",
          "- **Reiteration rule** (7 days) drops repeated calls from scoring, including the 2026-10-21 BTC call with a $79,600 defensive level; "
          "a different window changes n.",
          "- **Coverage.** X search returns at most ~60 posts per query; gaps were refilled with narrower date slices, and the 2026-10-01 slice starts at 12:52 UTC. "
          "Posts deleted before capture cannot be seen.", ""]
    open(os.path.join(HERE, "AUTHORS.md"), "w").write("\n".join(L))
    print("\n".join(L[:20]))


if __name__ == "__main__":
    main()
