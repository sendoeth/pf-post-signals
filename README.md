# Quanty Quants

Quanty Quants turns posts into priced positions: each tracked post is priced at the first bar at or after it was posted, then followed (best since post, 1d / 7d / 30d, closing posts with frozen realized returns). Live: https://sendoeth.com/pf-post-signals/web/

The repository keeps its original name (pf-post-signals) so existing commit and page links keep working; record and bundle schema ids (`pf-post-signals.*`, `post_price.v1`) are unchanged.

## Step 1: old regime pipeline vs post-extracted trade calls

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

### Step 14: every caller on the position chart, history before the first call

- **All callers**: each position page draws every other tracked call on the same asset as an avatar bubble (ring = side, badge = price direction, ✕ at the exit of a closed call). One toggle per caller plus All / None; the state is in the url (`?callers=bobloukas`, `?callers=none`, no parameter = all). The opened call is always shown and highlighted. Bubbles start at their own entry candle and move up (or down near the top) on a stem when they would overlap one already placed, so each keeps its own click area; a click opens that call's card with links to its position page and the post. Calls outside the view get an edge pill ("◀ 2 earlier calls") that zooms out to fit every shown call.
- **History before the first call**: `fetch_ohlc.py` starts candles max(90 days, first-to-last call span) before the asset's first call. Hourly where the source has it, daily bars before that (`daily_until` in each ohlc file, "daily bar" in the hover readout). Markets listed after the lookback start begin at their first bar (`lookback.starts_at_listing`). "Full history" shows all of it; the page still opens on the opened call. Candles are display only.
- **Frozen values**: `tools/frozen_values.py` compares every entry, close, lifecycle bar and resolved horizon with the pre-step-14 baseline (`verification/step14/frozen_baseline.json`): 177 values, 0 changed.
- **No JavaScript**: every static position page lists the other calls on its asset (author, side, date, return, link).
- Tests: `tests/test_history.py`, `tests/test_static.py` (other-calls list), `tests/callers_test.js` (every caller combination by url + reload, toggle clicks, anchors, overlaps, cards, exit marks, daily readout).

## Step 15: caller scores (0-100, deterministic)

`rate.py` turns each caller's priced calls into one score, written into `web/data/charts.json` as `ratings` (version `quanty.rating.v1`). Only the records go in: no model, no manual input, and the same records always give the same score.

| | |
|---|---|
| Calls | every position of the caller (one post can call several assets) |
| Scored calls (n) | calls with an entry price that state a side (long / short) and have a result |
| Result r | realized return for the side if the call is closed, else the return for the side since the post |
| H, hit rate | 100 × (scored calls with r > 0) / n |
| A, return quality | mean over scored calls of 50 + 50·tanh(r / 0.10): +10% → 88.1, +50% → 100, −10% → 11.9, so one outsized call cannot carry the score |
| C, clarity | 100 × n / calls with an entry (share of calls that state a side) |
| raw | 0.45 H + 0.40 A + 0.15 C |
| shrinkage | w = n / (n + 10); **score = 50 + w × (raw − 50)**; no scored calls → 50 |
| labels | under 10 scored calls "small sample", under 30 "limited sample" |

Every input is monotone (a better result on any call never lowers the score). Open calls move with the daily price refresh, so a score is as of `prices_as_of`. The page shows the score to one decimal (half up); the exact value is in `data-raw` and the bundle.

- Leaderboard: Score column in the author table (default order; sortable by score, author, calls, in profit, avg return via the headers, kept in `?asort=`), each author links to a static breakdown page `caller-<handle>.html`: every input, H / A / C with their weighted parts, raw, data weight, the arithmetic, and every call it read (result, A<sub>i</sub>, counted or why not).
- Position pages and chart cards show the caller's score and link to the breakdown; static no-JS pages carry the same numbers.
- `python3 rate.py` prints every caller's inputs and calls. `check_bundle.py` recomputes every score a second way from the record files; `tests/ratings_test.js` a third way in JavaScript against the live pages.
- Tests: `tests/test_rating.py` (hand-computed fixture, shrinkage, monotonicity fuzz, realized returns, determinism, hostile names, live bundle), `tests/test_static.py` (static scores + caller pages + hostile name), `tests/ratings_test.js`, `tests/security_test.js` (caller pages), `tests/board_test.js` (score order).

## Step 16: add a caller from one pasted post (owner-only)

`tools/add_call.py` is a local script: there is no public intake, form or login on the site.

```
python3 tools/add_call.py https://x.com/<handle>/status/<id>          # preview
python3 tools/add_call.py https://x.com/<handle>/status/<id> --add    # publish exactly that preview
```

- **Preview** saves the post receipt (`sources/<author>/receipts/<id>.json`, sha256), detects the asset (`detect.py`) and the side (`detect.detect_side`: first-person or explicit position words; both sides in one post is refused), prices the entry on the asset's shared series (every bar the bundle already has is written back, so the new record agrees with every existing one), and builds the bundle exactly as `--add` will, in a scratch copy of `records/`. It prints the call, its result so far, the author's current score and the score with this call added, and writes `intake/pending/<id>_<asset>.json`. Nothing under `web/` or `records/` changes.
- **--add** applies that pending file and nothing else: it refuses if `charts.json` changed since the preview (stale) or the receipt changed, writes `records/posts/<id>_<asset>.json`, saves a new caller's avatar (initials when the post has no picture), rebuilds the bundle, ratings and static pages, refetches candles only if they do not cover the entry bar, then checks that the author's score and the ranking equal the preview exactly and that no frozen value of any other position moved. The result is logged in `intake/log/`.
- Refused with the reason: deleted or private posts, posts whose asset the detector cannot read, a post + asset already recorded, a side stated both ways, and `--asset` / `--side` without `--reason`. A hand-picked asset or side keeps its reason in the record (`asset_choice`, `side_choice`).
- Tests: `tests/test_add_call.py` (fixtures in `tests/fixtures/intake`: new caller, existing caller, duplicate, no detectable asset, override with reason, hostile text; preview leaves `web/` and `records/` byte-identical; preview score = post-add score and delta; stale previews, missing reasons and two-sided posts refused; the new record shares the asset's bars).

## Step 17: scan a caller's last 12 months from one post (owner-only)

```
python3 tools/scan_caller.py https://x.com/<handle>/status/<id> scan     # collect (resumable)
python3 tools/scan_caller.py https://x.com/<handle>/status/<id> report   # classify, price, project; nothing published
python3 tools/scan_caller.py https://x.com/<handle>/status/<id> add      # publish the reviewed batch
```

- **scan**: 10-day windows over the 365 days before the scan, each one search `from:<handle> since:… until:…` through the read-only research harness (its network guard blocks posting, liking, following). One search at a time, no retries. A run stops itself after 25 searches (X allows about 50 per 15 minutes per account), on a rate limit, a login prompt or a harness error, and on 3 empty pages in a row (X answers a throttled account with empty pages); the next run resumes at the first window not done. A single empty window counts only when a later run sees it empty again. A full window whose oldest post is far from its start is split in two. Every own post is saved as a receipt with the harness run id and manifest sha256; `intake/scans/<handle>/scan_log.json` logs every window, run and stop reason.
- **report**: every post is labelled `call` (one asset, one side), `no_call` (no asset, commentary without side words, a question, advice to others, someone else's trade, a joke) or `needs_review` (several assets, both sides, exit words), with the matched words. `review.json` holds the owner's decisions (`add` with an asset / side and a written reason, or `skip` with a reason). Calls already recorded are listed, not added again. Calls and reviewed additions are priced with the resolver on shared bars and projected into the bundle exactly as `add` builds it: `intake/scans/<handle>/report.md` + `report.json` (entries, results, 1 / 7 / 30-day moves, the score now and projected) and a pending batch. Nothing under `web/` or `records/` changes.
- **add**: `tools/add_call.py add` on the batch: refuses if the bundle changed since the report, writes every record, rebuilds, and fails unless the projected score and ranking equal the result, every other caller's score is unchanged and no frozen value moved.
- Tests: `tests/test_scan_caller.py` (windows and cutoff, other authors and bad ids, budget stop + resume, rate limit, empty pages, single empty windows, window split, labels, report -> review -> add with exact scores and unchanged other callers).

## Step 18: calls read from chart screenshots (owner review only)

```
python3 -m venv --system-site-packages .venv && .venv/bin/pip install pillow==11.3.0 numpy==2.3.4   # once
.venv/bin/python tools/read_images.py https://x.com/<handle>/status/<id>                           # evidence, nothing added
python3 tools/add_call.py <url> --asset <A> --side long|short|none --reason "..." [--pending]       # after review
python3 tools/add_call.py <url> --asset <A> --add
```

- **Collect**: the post's images and those of the post it replies to or quotes (public embed data, originals from pbs.twimg.com), saved as `sources/<author>/media/<post>_<n>.<ext>` with sha256; the context post's receipt is saved too. The site never hotlinks them.
- **Read**: OCR (tesseract.js through the read-only research harness, cached beside each image with its sha256); chart titles and fund names map to assets through the written `detect/image_names.json` (every word of a title must be present); tickers on the chart are matched against the known assets; price labels (numbers with 2-4 decimals, thousands separators read whole) are collected.
- **Crop**: multi-scale normalized cross-correlation (FFT, integral-image normalization) finds whether the post's image is a crop of a context image (score >= 0.70), with the labels both share.
- **Price**: each label against the candidate asset's price at post time (within 3% = near) and the nearest daily low / high of the 2 years before.
- **Decide**: never sets a side. Support / resistance words with a far label, or a joke marker, are flagged as sarcasm or a target level. The result is `needs_review` (or `no_asset`) with a confidence, in `intake/images/<post>.json` + `.md`. `tools/add_call.py` refuses a post with image evidence unless `--asset`, `--side` and a written `--reason` are given, and records `asset_choice.method = image_review` with the evidence file and its sha256.
- **Market closed**: a post with no bar after it yet (e.g. after Friday's close) is refused unless `--pending`: then it is added with status "no price yet", is not scored, and the daily refresh fills the entry from the first bar after the post.
- Tests: `tests/test_read_images.py` (fixture images made by `tests/fixtures/images/make.py`: a chart, a crop of it, an unrelated chart; the real SOXL pair; OCR text -> titles / tickers / labels; near and far labels; the SOXL pattern end-to-end with no side and nothing added; joke markers; no readable text; reasons required; pending refused unless allowed).

## Reproduce step 2

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

## Step 3: second author (@BobLoukas)

`authors.py` adds @BobLoukas next to goodalexander/Corbanu with the unchanged step 1 scoring, regime tags from the live
pipeline, and minimum-sample flags; `validate_authors.py` checks schema, source coverage, duplicates and scoring parity.
Report: [AUTHORS.md](AUTHORS.md). Labels and rules: [`sources/bobloukas/labels.json`](sources/bobloukas/labels.json);
capture coverage: [`sources/bobloukas/COVERAGE.md`](sources/bobloukas/COVERAGE.md).

```bash
python3 authors.py            # fetches hourly prices, resolves calls, writes data/bobloukas_calls.json + author_comparison.json
python3 validate_authors.py   # expected: "checks: 16 rows, 59 candidates, 59 labelled ids -> ALL PASS"
python3 make_authors_report.py
```

## Step 4: post-to-price resolver

`resolve.py` turns one post + one asset into a `post_price.v1` record ([schema](schema/post_price.v1.json)): entry
(first hourly bar at or after the post), latest bar, % change since the post, 1d / 7d / 30d moves (unresolved when not
reached or when the first bar is more than 2 days late, never guessed), signed returns when a side is given, and the
hourly series from entry to latest. This is the data layer for a chart of posts against price; the chart, asset
auto-detection and hosting are later steps.

- **Input**: a post URL (the timestamp is decoded from the X snowflake id, checked equal to `postedAt` on all 260 saved
  receipts) or a saved receipt (timestamp + text + receipt sha256). Assets: `BTC ETH SOL LINK` (Binance 1h),
  `SPY QQQ STOCKS COPX SILVER GOLD COPPER OIL` (Yahoo 1h), or explicit `binance:<PAIR>` / `yahoo:<TICKER>`; anything
  else is a clear `unknown asset` error.
- **Duplicates**: the same (post, asset) twice in one run is kept once and reported; the same post with two assets
  (a pair) is two records. Re-runs write identical bytes.
- **Parity**: `parity.py` reruns all 16 step 3 BobLoukas rows from their receipts against the saved step 3 price
  snapshot and compares entry, exits, signed returns and unresolved reasons with `==`: 16/16 exact
  ([`data/parity_bobloukas.json`](data/parity_bobloukas.json)).

```bash
python3 resolve.py --url https://x.com/BobLoukas/status/2112919830357577753 --asset BTC --side long --out records/live
python3 parity.py                         # expected last line: "parity: 16/16 exact, 16 records schema-valid, 0 duplicates, 0 errors"
python3 -m unittest -v tests.test_resolve # 20 tests
python3 validate_records.py               # expected: "records: 18 checked against post_price.v1 -> ALL VALID"
```

Run notes with raw output and file hashes: [`verification/step4_run.md`](verification/step4_run.md). Needs
`jsonschema` (schema validation); everything else is stdlib.

### Step 4 limitations

- **Friday-evening stock posts get no entry.** The unchanged step 3 rule rejects an entry more than 2 days after the
  post, and Friday 20:00 UTC to Monday 13:30 UTC is about 2.7 days. Kept for parity, pinned by a test; the chart step
  should use "next session open" for exchange-hours assets.
- Prices are the bar **open**, not a fill. Yahoo 1h history only reaches back about 730 days.
- Live runs refetch prices, so `latest` and newly reached horizons change; parity uses the saved snapshot so it is
  unaffected by later Yahoo revisions.
- Asset choice is manual (`--asset`): detection from post text is step 5.

## Step 5: posts over price (chart page)

Live page: **https://sendoeth.com/pf-post-signals/web/**: pick an asset, click a bubble (or a table row) to open
the post's card. Each bubble sits at the post's entry bar; blue ▲ = up since the post, red ▼ = down.

- `build_chart.py` checks every `records/**/*.json` with the step 4 schema + record invariants and writes
  `web/data/charts.json`. Invalid records are refused with their reasons and never drawn; the same post + asset in two
  files is drawn once (the record with the later last bar wins, the other is listed as superseded); the price line per
  asset is the union of the records' hourly bars (records disagreeing on a bar refuse that asset).
- `web/index.html`: one static file, no build step, no external scripts. Bubbles closer than two hit radii
  (same entry bar, or hours apart on a two-month axis) are stacked on stems so each one stays separately clickable.
  Cards show only record values; unreached horizons read `unresolved · <reason>`, never 0. Light and dark mode.
- `check_bundle.py`: every record file is drawn, superseded or refused exactly once, and every drawn post equals its
  record field for field (sha256 shown on the card).
- `tests/browser_test.js`: headless Chromium clicks every bubble of every asset and compares each card field (text and
  raw value) with the record file on disk, checks no two hit areas overlap, no console errors, no horizontal scroll at
  phone width, and takes the screenshots in `verification/step5/`.

```bash
python3 build_chart.py                       # 18 records scanned, 16 drawn, 2 superseded, 0 refused
python3 build_chart.py --records tests/fixtures/records_with_invalid --out /tmp/x.json   # 4 refused with reasons
python3 check_bundle.py                      # ALL MATCH
node tests/browser_test.js --screenshots verification/step5          # ALL PASS (local server; chart view = web/chart.html since step 10)
node tests/browser_test.js --url https://sendoeth.com/pf-post-signals/web/   # same checks on the live page
```

Run notes with raw output, hashes and screenshots: [`verification/step5_run.md`](verification/step5_run.md).

## Step 6: paste a post link

```bash
python3 add_post.py https://x.com/BobLoukas/status/2115823513915290059   # receipt -> asset -> record -> chart bundle
```

- `ingest.py` fetches the post from X's public embed endpoint (no login), checks it exists, that its timestamp equals
  the one in its id and that the author matches, and saves `sources/<author>/receipts/<id>.json`. Long posts come back cut
  to ~270 characters; the receipt says `textTruncated: true`. Existing receipts are reused, never overwritten.
- `detect.py` proposes the asset from cashtags and the written map in [`detect/asset_map.json`](detect/asset_map.json)
  (whole words, longer terms first). One asset = detected; none, several or an unmapped cashtag = needs review, and
  `add_post.py` stops there unless `--asset` is given. Scored once on the 59 hand-labelled step 3 posts
  (`score_detector.py`, [`data/detector_scores.json`](data/detector_scores.json)): of 14 single-asset calls 12 exact,
  0 wrong, 2 needs review; the BTC/gold pair is flagged with both assets. It only proposes an asset; whether a post is a
  call stays a human decision.
- **Exchange-hours fix**: stocks, ETFs and futures (Yahoo) take the next session open for entry and exits (tolerance 4
  days, enough for a long weekend; longer gaps stay unresolved). Crypto keeps 2 days. Records carry
  `resolved_with.session_lag_days`. Step 4 parity stays 16/16 exact.
- The page draws a stretch with no bars across a whole weekday dashed ("no price data") instead of as prices.

Run notes: [`verification/step6_run.md`](verification/step6_run.md).

## Step 7: position pages

Every post has its own page: `web/position.html?post=<id>&asset=<asset>`, for example
**https://sendoeth.com/pf-post-signals/web/position.html?post=2104977267109896477&asset=SILVER**. The main chart's cards and
table dates link to it.

- Candlesticks (TradingView Lightweight Charts 4.2.3, pinned with a subresource-integrity hash, attribution kept) with
  1h / 4h / 1D intervals, picked from the post's age; 4h and 1D are built from the 1h candles.
- The author's avatar sits on the candle that holds the entry bar; a dashed line runs to the best price since the post
  with its % label; a dotted line marks the record's latest price.
- Recap: asset, side, entry, latest, % since post, best % since post (for the call when a side is stated, else the
  highest price), age of the call, 1d/7d/30d moves. Every value comes from the record; best % is computed by
  `build_chart.py` from the record's own series and recomputed independently by `check_bundle.py`.
- `fetch_ohlc.py` writes `web/data/ohlc/<asset>.json` + `index.json` (sha256, fetch time) from the records' own
  source/symbol and checks every entry bar: candle open == record entry price. Candles are display only.
- Avatars are saved once at ingest into `web/avatars/` (source and sha256 in `index.json`), never hotlinked; initials
  are the fallback.
- `tests/position_test.js` opens every position page at the default interval and at 1h: recap = record, best % =
  recomputed, avatar centre within 1.5 px of the chart's own coordinate for the entry candle, entry candle open =
  record entry, no console errors; it also checks every card and table link on the main page.

Run notes: [`verification/step7_run.md`](verification/step7_run.md).

## Step 8: security hardening

The site is static (GitHub Pages, no backend, no PHP, no connection to our server). Hardening, with the proof in
[`verification/step8_run.md`](verification/step8_run.md):

- **HTTPS enforced** on the Pages sites: `http://` redirects to `https://`.
- **Content Security Policy** (meta tag; Pages cannot send headers): only same-origin scripts, styles, images and data;
  no inline script, no eval, no plugins, no forms, no base-uri. The one allowed inline style is the chart library's
  attribution logo, pinned by its sha256. `no-referrer`. Frame busting (`assets/frame-guard.js`) because a meta CSP
  cannot set `frame-ancestors`: a framed page breaks out or hides.
- **No third parties at runtime**: the chart library is self-hosted in `web/vendor/` with its Apache-2.0 LICENSE;
  `tools/check_vendor.py` checks it byte for byte against the npm tarball (verified against the registry's sha512).
- **X-derived content is untrusted**: rendered with `textContent` only; the schema refuses HTML in author / asset
  names, non-`https://x.com/<user>/status/<id>` links and oversized text; avatars must be JPEGs from X's image host
  and are served as `<handle>.jpg` only. `tests/fixtures/attack_records` holds hostile records;
  `tests/security_test.js` proves none of them executes (canary `window.__pwned` stays unset), every request stays on
  the site's own origin, and there are 0 CSP violations and 0 console errors on every page.
- **Repo**: secret scanning + push protection on, `main` protected (no force push, no deletion), and
  `tools/guard.py` in CI (`.github/workflows/guard.yml`, actions pinned to commits, read-only token) rejects any
  commit whose history or tree has an unknown IPv4 address or a token pattern.

## Step 9: daily price refresh

`.github/workflows/refresh.yml` runs daily at 21:20 UTC (and on demand): `refresh.py` re-resolves every record from its
receipt with fresh hourly prices, `build_chart.py` rebuilds the bundle, `fetch_ohlc.py` refetches the candles, then
every check and test runs; only if all pass does the job commit (`refresh: prices as of <time>`). The pages show
"prices as of" from `data/refresh_log.json`.

- **Frozen values**: an entry bar and every horizon already resolved never change. Before re-resolving, they are written
  back into the fetched series; a provider revision or a dropped bar is logged in `data/refresh_log.json` with the
  frozen and fetched values, and the frozen value stays. Latest, % since post, best since post and newly reached
  horizons come from the fresh bars.
- **Fails closed**: any fetch, schema, invariant, parity, test or guard failure stops the job before anything reaches
  `main`, so the last good data stays live.
- **Protection unchanged**: `main` still requires the `guard` check and forbids force pushes and deletion. The job runs
  `tools/guard.py --history` and `--tree` on its own commit, records that as the `guard` status on exactly that
  commit, and fast-forwards `main`. Token scopes are per job: contents/statuses/pages write for the refresh job only.
- `parity.py` now compares in memory (records/ holds the refreshed records); step 4 parity stays 16/16.

## Step 10: leaderboard front page

**https://sendoeth.com/pf-post-signals/web/** is now a ranked list of every position; the chart view moved to
[`web/chart.html`](web/chart.html). Each row: rank, asset with LONG / SHORT badge, author avatar and handle, posted date
and age, a quote of the post, a sparkline of the price from the entry bar to the latest bar, entry -> current price,
return (for the call when a side is stated, else the price move), best since post and status; every row links to its
position page. A stats strip (positions, share in profit, average return, best call) follows the filters.

- Filters: time (all / last 7 days / today, relative to the "prices as of" time), side, author, asset; sort by
  return, best since post or newest. The state lives in the URL (`?side=short&sort=best`), so any view can be shared;
  unknown URL values fall back to the defaults.
- Same bundle, same CSP, no new data source or third-party request; unresolved values never show as 0.
- `tests/board_test.js` re-implements the ranking independently and loads all 432 filter x sort combinations from
  their URLs, changes every select in the page, checks every row field against its record file, sparkline point
  counts, links, 0 console errors / CSP violations and the phone layout.

## Step 11: Corbanu and goodalexander

- **Corbanu**: every trade in Corbanu's published tracker ledger (8 events; the live ledger at
  corbanu.com/assets/portfolio/ledger.json matched the step 1 snapshot) is a position (`tools/import_corbanu.py`,
  `records/corbanu/`), with the ledger's side, reference price, weight, venue and article kept under `trade`.
- **Venue pricing**: Hyperliquid's public candle API for the HIP-3 `xyz` stock perps the trades are published on.
  `data/corporate_actions.json` back-adjusts the 3:1 Kioxia split of 2026-09-28 (Corbanu's ledger uses the same
  post-split basis: its reference price equals our entry exactly); any other hour-to-hour jump over 40% stops
  resolution. ORCLon has no public hourly candles and the Hyperliquid spot token named ORCL is unrelated, so the ORCL
  trade is priced from the `xyz:ORCL` perp and labelled **stand-in** on every page.
- **goodalexander**: 4 posts that state a position, through the step 6 pipeline (receipts in
  `sources/goodalexander/receipts`); 2 assets by the detector, 2 manual with the reason stored in the record
  (`asset_choice`). Ingest now decodes HTML entities (`S&amp;P`) and drops reply @mentions.
- **Per-author summary** on the leaderboard (calls, share in profit, average return, best, worst) with the step 3
  sample-size flags (under 10 calls: insufficient sample; under 30: unreliable sample).
- `tools/compare_corbanu.py` compares every Corbanu trade with step 1 and explains each difference
  (`data/corbanu_vs_step1.json`).

## Step 12: readable without JavaScript, plain statuses, avatar bubbles

- `tools/prerender.py` (run by `build_chart.py` and the daily refresh) writes the data into the HTML: the leaderboard's
  rows, author table and stats in `index.html`, a list of all positions in `position.html`, and one static page per
  position, `pos-<post>_<asset>.html`, with its key numbers and link-preview tags. `curl` sees real data; the scripts
  then replace it with the interactive view. Leaderboard rows and chart cards link to the static pages.
- Status wording: "all horizons in", "30d pending" (any horizons not reached yet), "no price yet", "no price at post
  time", with a tooltip saying when each pending result comes in (`assets/common.js`).
- Chart view bubbles: the author's local profile picture (or an initial on a fixed per-author colour, no greens or reds),
  a ring for the side (green long, red short, grey no side) and a ▲/▼ badge for the move since the post.
- `tests/test_static.py` (also in CI) parses the pages without running scripts and compares them with the bundle,
  including the hostile fixtures; `tests/board_test.js` fetches the raw HTML and checks it against its own ranking.

## Step 13: closing calls

A position now has a lifecycle. `data/lifecycle.json` lists the author's follow-up posts about it (receipts in
`sources/<author>/receipts`); `classify.py` decides each one and `lifecycle.py` applies it inside the daily refresh:

- **close** (explicit exit: "rotated out of", "sold all", "closed", "exited", "out of", "covered", "stopped out") and
  **flip** ("now short"): exit = first bar at or after the follow-up post; the realized return is frozen in
  `closed` and the status becomes **closed**. A stated earlier time ("last week") is recorded, never used.
- **trim** ("sold a clip", "took some profits"): priced and recorded, the position stays open.
- **review** (hints: "trailing stops", "lightened up", "de-risking") and **not a close** (advice to others such as
  "afford yourself some profit taking", or no exit words): recorded, nothing changes. A reviewed override needs a reason.
- Corbanu: a ledger exit event (or a trade to 0% weight) closes the position automatically (`tools/import_corbanu.py`,
  tested with `tests/fixtures/corbanu_ledger_with_exit.json`; the live ledger has no exits yet).
- Pages: closed positions rank and aggregate by their realized return; the current price appears only as
  "if still held"; best since post stops at the exit; a status filter (open / closed) on the leaderboard; the
  position page shows the closing post, an exit marker and the lifecycle timeline.
- History older than Yahoo's hourly window (about 730 days) uses daily bars, labelled `interval: "1d"`.

Worked example (BobLoukas, silver): opened 2024-04-05 ("loaded to the gills"), trim 2025-10-19, review 2025-12-26
("trailing stops"), close 2026-01-09 ("rotated out of silver last week"): **+188.17%** realized at 80.125; the
2026-01-23 "$100 silver ... afford yourself some profit taking" is advice, not a close. Silver later peaked at $121.30
(2026-01-29); if still held today: +76.71%.

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
