# Step 3: per-author comparison

Two authors scored with the identical step 1 rule: `signed_return = side x (P_exit / P_entry - 1)`, hit = signed_return > 0, horizons 1 / 7 / 30 days, exits more than 2 days late or not yet reached are **unresolved**, never guessed.

Sample flags: `insufficient` n < 10, `unreliable` n < 30, `ok` otherwise. **Every cell below is flagged**: neither author has enough resolved calls for a hit rate to mean anything yet.

## Hit rate · mean signed return per call

| Author | Calls | 1d | 7d | 30d |
|---|---|---|---|---|
| goodalexander/Corbanu | 8 | 43% · -0.39% (n=7, 1 unresolved) `insufficient` | 75% · +4.45% (n=8) `insufficient` | 50% · -3.43% (n=4, 4 unresolved) `insufficient` |
| BobLoukas | 10 | 60% · +0.34% (n=10) `unreliable` | 44% · -1.04% (n=9, 1 unresolved) `insufficient` | 67% · -1.27% (n=3, 7 unresolved) `insufficient` |

## Pairs (scored as one unit)

| Author | 1d | 7d | 30d |
|---|---|---|---|
| goodalexander/Corbanu | 50% · -0.52% (n=2) `insufficient` | 100% · +1.87% (n=2) `insufficient` | 50% · -1.71% (n=2) `insufficient` |
| BobLoukas | 0% · -0.70% (n=1) `insufficient` | 0% · -1.22% (n=1) `insufficient` | — · — (n=0, 1 unresolved) `insufficient` |

## By pipeline regime at call time (7d)

| Author | Regime | 7d |
|---|---|---|
| goodalexander/Corbanu | EARNINGS | 100% · +7.85% (n=1) `insufficient` |
| goodalexander/Corbanu | SYSTEMIC | 71% · +3.97% (n=7) `insufficient` |
| BobLoukas | EARNINGS | 33% · -0.51% (n=6, 1 unresolved) `insufficient` |
| BobLoukas | SYSTEMIC | 67% · -2.10% (n=3) `insufficient` |

Regime = the live pipeline's 2-session-gated regime (step 2) on the call date.

## @BobLoukas calls (scored)

| Posted (UTC) | Call | Regime | Entry | 1d | 7d | 30d | Post |
|---|---|---|---|---|---|---|---|
| 2026-09-01T16:37 | long BTC | SYSTEMIC | 77596.01 @ 2026-09-01T17 | -0.55% | +1.47% | +8.51% | [post](https://x.com/BobLoukas/status/2094827036812435935) |
| 2026-09-08T13:59 | long COPX | SYSTEMIC | 95.31 @ 2026-09-08T14 | +0.22% | -11.56% | -12.54% | [post](https://x.com/BobLoukas/status/2097324043334451439) |
| 2026-09-18T14:23 | long BTC (conditional) | SYSTEMIC | 80937.83 @ 2026-09-18T15 | +0.80% | +3.80% | +0.20% | [post](https://x.com/BobLoukas/status/2100953898630443447) |
| 2026-09-29T16:51 | short SILVER | EARNINGS | 61.105 @ 2026-09-29T17 | +0.83% | -0.80% | unresolved | [post](https://x.com/BobLoukas/status/2104977267109896477) |
| 2026-10-01T16:40 | long BTC | EARNINGS | 84202.0 @ 2026-10-01T17 | +1.14% | -3.86% | unresolved | [post](https://x.com/BobLoukas/status/2105699317004583026) |
| 2026-10-04T14:17 | long COPX | EARNINGS | 86.0 @ 2026-10-05T13 | -0.33% | -0.83% | unresolved | [post](https://x.com/BobLoukas/status/2106750657877434407) |
| 2026-10-05T10:59 | long STOCKS | EARNINGS | 769.69 @ 2026-10-05T13 | +1.10% | +1.18% | unresolved | [post](https://x.com/BobLoukas/status/2107063137958564197) |
| 2026-10-15T16:06 | long BTC | EARNINGS | 82108.01 @ 2026-10-15T17 | -0.82% | -1.00% | unresolved | [post](https://x.com/BobLoukas/status/2110764348981612915) |
| 2026-10-21T14:51 | short GOLD | EARNINGS | 4148.5 @ 2026-10-21T15 | +1.78% | +2.27% | unresolved | [post](https://x.com/BobLoukas/status/2112919830357577753) |
| 2026-10-23T12:49 | short SILVER | EARNINGS | 53.84 @ 2026-10-23T13 | -0.73% | unresolved | unresolved | [post](https://x.com/BobLoukas/status/2113613893662588966) |

| Pair | Legs | 1d | 7d | 30d |
|---|---|---|---|---|
| btc-gold-2026-10-21 | BTC long, GOLD short (equal (no weights stated)) | -0.70% | -1.22% | unresolved |

## @BobLoukas coverage

- own posts captured 2026-09-01 → 2026-10-28: **260** (read-only X search in date slices, gaps refilled; see `sources/bobloukas/COVERAGE.md`)
- keyword candidates: 59, all labelled; scored calls **10**, reiterations (same instrument + direction within 7 days) **6**, excluded with a stated reason **21** + 23 non-calls in `data/bobloukas_exclusions.json`
- unresolved horizon cells among scored calls: **8** (30d horizons not yet reached for calls after 2026-09-28; 7d for the 2026-10-23 silver call)

## Limitations

- **Corbanu rows are the step 1 snapshot** (resolved 2026-10-18), reused unchanged so the scoring-parity check holds; some of its unresolved 30d cells have since matured and are not re-resolved here.
- **Tiny samples.** 10 BobLoukas calls and 8 Corbanu legs; every cell is flagged. Nothing here ranks the authors.
- **Different styles and instruments.** Corbanu publishes sized trades with reference prices; BobLoukas posts cycle-based views, mostly BTC, silver, gold, copper miners and US stocks. Entries for BobLoukas are the first hourly bar after the post, not his fills.
- **Labelling is manual** under written rules (`sources/bobloukas/labels.json`). Cycle commentary is often deliberately two-sided; those posts are excluded, which favours his clearer calls. One included call is conditional-leaning (2026-09-18, marked).
- **Instrument mapping.** "Stocks" → SPY, "silver" → SI=F, "gold futures" → GC=F, "COPX" → COPX; pair legs equal-weighted because no weights were stated.
- **Reiteration rule** (7 days) drops repeated calls from scoring, including the 2026-10-21 BTC call with a $79,600 defensive level; a different window changes n.
- **Coverage.** X search returns at most ~60 posts per query; gaps were refilled with narrower date slices, and the 2026-10-01 slice starts at 12:52 UTC. Posts deleted before capture cannot be seen.
