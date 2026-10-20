# pf-post-signals — step 1: old regime pipeline vs post-extracted trade calls

Benchmark of two signal sources on 2026 data with identical scoring:

1. **Old system** — my regime-switching signal pipeline (`ai_semi_dashboard.html` + `signal_api.js`, built Mar 2026).
2. **New system** — structured trade calls extracted from goodalexander / Corbanu publications since Sept 2026.

This is step 1 toward a feed that turns quant/founder posts into structured long/short signals scored by
reliability. Extraction and measurement only: no commentary on anyone's writing, no trading advice.

Full tables: [RESULTS.md](RESULTS.md). Machine-readable: [`data/comparison.json`](data/comparison.json).

## Headline

| System | 1d hit · mean | 7d hit · mean | 30d hit · mean | Abstention |
|---|---|---|---|---|
| Old pipeline, counterfactual, executed (Mar 9 – Oct 16) | 44% · −0.10% (n=68) | 41% · −0.57% (n=68) | 56% · +2.58% (n=68) | 89% of symbol-days |
| Old pipeline, common window Sep 4 – Oct 16 | no calls | no calls | no calls | 100% |
| Old pipeline, shadow of *suppressed* directions | 49% · −0.17% (n=304) | 40% · −0.65% (n=304) | 58% · −0.34% (n=284) | — |
| Corbanu calls, per leg (Sep 4 – Oct 16) | 43% · −0.39% (n=7) | 75% · +4.45% (n=8) | 50% · −3.43% (n=4, 4 pending) | 0% |
| Corbanu published pairs (weighted) | 50% · −0.52% (n=2) | 100% · +1.87% (n=2) | 50% · −1.71% (n=2) | — |

## Findings

1. **The live old pipeline has been frozen since 19 Mar 2026.** Its ledger logged 20,642 cycles
   (every 15 min, 13 Mar → 18 Oct), all `NO_TRADE`, regime SYSTEMIC at a constant 77% confidence, watchdog `STOP`.
   Root cause: the dashboard classifies regime from a price history embedded in the HTML that ends **2026-03-06**
   and was never refreshed, so every cycle recomputed the same March answer. The live record carries no information
   about 2026, which is why step 1 had to reconstruct what the system would have done.
2. **Counterfactual: the regime did not stay SYSTEMIC.** Re-running the *unmodified* classifier on each 2026 trading
   day (trailing 251-day window, no look-ahead) gives SYSTEMIC 76 days, EARNINGS 50, NEUTRAL 17, DIVERGENCE 12. The control
   day (2026-03-06, last embedded day) reproduces the frozen live state exactly (SYSTEMIC, 77).
3. **The one tradeable window lost at short horizons.** The policy only publishes direction in NEUTRAL
   (13 Apr – 5 May): short BTC/ETH/LINK, long SOL. Those 68 calls hit 44% at 1d and 41% at 7d, recovering to 56% / +2.58%
   at 30d. The 30d edge is a single 17-day window, i.e. effectively one market episode, not a robust edge.
4. **Abstaining was right where it abstained.** Had the suppressed SYSTEMIC directions been published, they would have
   hit 40% at 7d (n=304, −0.65% mean). The regime filter avoided losses, but it also abstained 89% of the time and 100%
   during the window where Corbanu was active.
5. **Corbanu calls were directionally better at 7d but small-n and volatile.** 75% of legs positive at 7d (+4.45% mean),
   both published pairs positive at 7d. At 30d the Kioxia leg swung from +19.7% (7d) to −25.0% (30d), dragging the
   pair to −8.3%. Cerebras short was the strongest call (+8.3% 7d, +12.7% 30d); the 30 Sep add +7.8% at 7d.
6. **The old classifier flaps at a threshold.** 22 regime changes in 7 months; after May, 14 of 18 changes fell around
   weekends (Fri→Mon, Mon→Tue). It sits on the "3 decaying signal types" boundary and weekend crypto moves tip it.
   Any rebuild needs hysteresis or a minimum-duration gate before a regime change is acted on.

## What this means for step 2

- The old pipeline's *abstention logic* is worth keeping (it avoided the SYSTEMIC losses); its *directional calls*
  are not, and its data feed must be live, not embedded.
- Post-extracted calls carry real directional information but need many more authors and months before any
  hit rate is meaningful. The feed should score authors by regime and horizon, and weight pairs as units.

## Method

**Identical scoring for both systems.** Each directional decision has side s (+1 long / −1 short), entry P0 and exit Ph
after h ∈ {1, 7, 30} calendar days: `signed_return = s · (Ph/P0 − 1)`, hit = signed_return > 0. Exits past the last
available price are *pending*, never guessed.

**Old system (counterfactual).** `fetch_prices.py` pulls the pipeline's 9 equity and 4 crypto inputs. The fetched series
match the embedded history exactly on all 251 overlapping days for equities (0.00% median diff) and to 0.13–0.15% for crypto
using the previous UTC day's close (the embedded convention; same-day close differs 3.4%). `build_asof.py` writes one copy of
the *original* dashboard per trading day with only the data arrays swapped, `run_asof.js` loads each in headless Chromium
exactly as `signal_api.js` does and records `exeData.regimeClass`. `score.py` maps regimes to trades with the unmodified
policy constants from `signal_api.js` (only NEUTRAL publishes; SOL weak-symbol inversion). Entry = Binance UTC close of
the as-of day.

**New system.** `extract_calls.py` reads Corbanu's machine-readable published-trade ledger
(`corbanu.com/assets/portfolio/ledger.json`): every event since 2026-09-01 with timestamp, reference price, weight and
article (source text SHA-256 included). Article headers add stated horizon/target. goodalexander mentions on X/Discord are
recorded as confirmations or excluded with a reason (e.g. "likely going to buy the [CRWV] bonds": no resolvable price).
Exit = first Corbanu tracker mark at or after entry + h (≤2 days late, else pending). Tracker marks cross-checked against
Yahoo closes: AAPL 0.05%, ORCL 0.96% median difference (ORCLon is a tokenized spot quote).

**Regime tags.** Every decision is tagged with the counterfactual regime as of the last trading day on or before it.

## Limitations

- **Different instruments.** The old system trades BTC/ETH/SOL/LINK; Corbanu trades AI-memory equities, indices and
  Oracle. Same scoring rule, different opportunity sets: this compares signal sources, not like-for-like assets.
- **No overlap in time.** The old system's only executed window (Apr 13 – May 5) precedes Corbanu's first call (Sep 4); in
  the common window it abstained 100%. Per-regime comparison is the only same-conditions view, and there it is
  SYSTEMIC-only (old: shadow, Corbanu: 7 calls).
- **Small n.** 8 Corbanu legs, 2 pairs, 4 resolved at 30d. 68 old calls come from one 17-day window (4 symbols × 17 days,
  heavily autocorrelated). None of the hit rates is statistically distinguishable from 50%.
- **Counterfactual, not live.** The replay reproduces the classifier exactly but the live system never published these
  calls; entry at the UTC close of the as-of day is ~3–4 h after the equity close the decision used.
- **Corbanu prices are reference quotes, not fills,** and P&L ignores funding, fees and borrow (the tracker states the same).
  Signed returns ignore weights except in the pair rows.
- **Self-published tracker** as the exit source, mitigated by the Yahoo cross-check above.
- One ORCL 1d exit is missing: the call was made on a Saturday and the Felix spot token had no mark within 2 days.

## Step 2: live price feed + regime duration gate

The live pipeline had been reading a price history embedded in its dashboard that ends 2026-03-06. Step 2:

- **Live feed** — `live_feed.py` (daily cron, 22:30 UTC Mon–Fri) fetches the same 9 equity + 4 crypto inputs, classifies
  every completed session not yet classified with the *unmodified* dashboard (trailing 251 sessions, cached per session in
  `live/raw_regimes.json`), applies the gate, verifies the rendered page, and atomically publishes
  `live/ai_semi_dashboard.live.html` + `live/status.json`. `signal_api.js` reads it via `PF_DASHBOARD_PATH`
  (patch: [`patches/signal_api_live_feed.patch`](patches/signal_api_live_feed.patch)).
- **Duration gate** — [`gate.py`](gate.py): a regime change takes effect only after 2 consecutive sessions. It is a pure
  function of the raw session sequence, so re-runs cannot double-count a session. In the generated dashboard
  `classifyRegime()` itself returns the gated regime, so every consumer (rebalancing queue, `signal_api.js` filters)
  sees the same value; the raw regime is kept as `rawRegime`.
- **Withholding** — after 4 days without new market data the page reports `STALE_DATA`, and `signal_api.js` now
  withholds direction for any unknown regime id (previously it fell back to NEUTRAL, which publishes).
- **Ledger push** — the `post-fiat-signals` ledger/status push had been rejected since 2026-06-09 while the cron log still
  said "Pushed". Fixed in that repo: one lock for both jobs, rebase before push, real failure reporting, token via askpass,
  and a guard that refuses to commit any file containing a server address.

Before/after numbers: [RESULTS.md → Step 2](RESULTS.md#step-2-live-feed--regime-duration-gate-before--after).

### Reproduce step 2

```bash
python3 gate.py          # data/gate_evaluation.json
# expected: min_days=1: 22 changes, 15 weekend-driven ... min_days=2:  8 changes,  3 weekend-driven ...
python3 step2_report.py  # data/step2.json + Step 2 section of RESULTS.md
python3 live_feed.py     # needs network + chromium; publishes live/ or exits 1 with the reason
# expected: "[...] PUBLISHED <latest session>: raw=<REGIME> effective=<REGIME> (since <date>, gate 2d)"
```

### Step 2 limitations (not tested)

- The gate length (2) was chosen on the same replay it is evaluated on: in-sample, one 7-month window.
- The gated re-score (43% / 57% at 7d / 30d vs 41% / 56% raw) comes from one 17-session NEUTRAL episode (n=68,
  autocorrelated); the difference is noise, not an improvement claim.
- Market holidays: a missing session simply is not classified; a long market closure would trip the 4-day
  stale guard and withhold until data resumes (intended, but not exercised live).
- The first scheduled 22:30 UTC run had not happened at submission time; the first live publish was run manually
  (2026-10-20, session 2026-10-19).
- Crypto inputs use the previous UTC day's close (the embedded convention); AKT comes from CoinGecko's 365-day window,
  which covers the 251-session lookback but not deeper rebuilds.
- `signal_api.js` is not in this repo; its 3 changes are shipped as a patch file.

## Reproduce

```bash
python3 fetch_prices.py          # data/prices.json
python3 build_asof.py            # work/asof/*.html from sources/ai_semi_dashboard.snapshot.html
node run_asof.js                 # data/counterfactual_regimes.json (puppeteer + chromium)
python3 extract_calls.py         # data/calls.json from sources/corbanu/
python3 score.py                 # data/comparison.json + resolved decisions
python3 make_report.py           # RESULTS.md
```

Python 3 stdlib only; `run_asof.js` needs puppeteer. Source snapshots (Corbanu ledger, marks, article text) are committed
under `sources/corbanu/` so the extraction is reproducible after the live files change.
