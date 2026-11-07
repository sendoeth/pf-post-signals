# Step 28 run: callers by crypto market regime (score-neutral)

Code: a7d35a30fe6d152c997063a3ab55241737f603b9 (regimes, tests, CI) + 81191aa86c5534c5e9250424d446eaa69376fd2a (caller-page table, nav wraps on phones). CI on 81191aa: guard success https://github.com/sendoeth/pf-post-signals/actions/runs/42384327045 · pages success https://github.com/sendoeth/pf-post-signals/actions/runs/42384326670
Compare: https://github.com/sendoeth/pf-post-signals/compare/153c834...81191aa86c5534c5e9250424d446eaa69376fd2a
Live: https://sendoeth.com/pf-post-signals/web/regimes.html · caller page https://sendoeth.com/pf-post-signals/web/caller-bobloukas.html (section "By market regime")
Served = commit 81191aa (curl | sha256sum vs git show): charts.json 6c2d78c96472c58f1f63f972a2e88b04198c09b79bbe33b609eb5f29b0ebe73e, regimes.json 9151655d38bf13956f237da45a171ba8ef77534527d9bace0832d80025bec04b, regimes.html 0761d68f859a7e12dd88d4fbf135f04b74dc72528c13d01b40176aca3416b9d3, caller-bobloukas.html 7099629a2a05feba21ab628775db6c37143490e2099a982e0a445fbd35db1647.
**Scores unchanged**: charts.json at 153c834 (before step 28) = 6c2d78c96472c58f1f63f972a2e88b04198c09b79bbe33b609eb5f29b0ebe73e = served.

Pinned: [data/btc_daily.json](https://raw.githubusercontent.com/sendoeth/pf-post-signals/81191aa86c5534c5e9250424d446eaa69376fd2a/data/btc_daily.json) (sha256 8126461a9ec5fbe626c2ccb161dafcaed0153731c1baf6c0f5d8c1254c5e13a6; bars_sha256 a042bf9748af473ee22c67633141cab73521eceb0134adc5ed6e7c0bb3cfbcde) · [web/data/regimes.json](https://raw.githubusercontent.com/sendoeth/pf-post-signals/81191aa86c5534c5e9250424d446eaa69376fd2a/web/data/regimes.json) · [tools/regimes.py](https://raw.githubusercontent.com/sendoeth/pf-post-signals/81191aa86c5534c5e9250424d446eaa69376fd2a/tools/regimes.py) · [tests/test_regimes.py](https://raw.githubusercontent.com/sendoeth/pf-post-signals/81191aa86c5534c5e9250424d446eaa69376fd2a/tests/test_regimes.py) · [web/data/charts.json](https://raw.githubusercontent.com/sendoeth/pf-post-signals/81191aa86c5534c5e9250424d446eaa69376fd2a/web/data/charts.json)

## Rule, params, matrix, stability, degradation, per-caller table — [outputs/regimes_summary.txt](step28/outputs/regimes_summary.txt)
Generated from the served regimes.json.

## No look-ahead — [outputs/no_lookahead_check.txt](step28/outputs/no_lookahead_check.txt)
`python3 tools/regimes.py check`: each call's label from the full series = the label from the series cut at the call (only bars closed at or before it): 59 of 59 equal.

## Tests (fresh clone of 81191aa) — [outputs/fresh_clone_guard_and_tests.txt](step28/outputs/fresh_clone_guard_and_tests.txt)
guard --history 113 commits 0 hits, --tree 2692 files 0 hits, test_guard 7 OK; regimes check 59/59; tests.test_regimes 19 OK; rating + static + labels + early 67 OK; check_bundle ALL MATCH; full 322 OK (2 skipped).

## Review
Codex: design WITHHOLD (coverage validation, warm-up / first-regime determinism) -> fixed (validate(), series from 2018-02-09 after Binance's truncated outage bar, first regime needs 3 days, unknown on stale tail) -> implementation WITHHOLD x2 (tests would block the refresh when a failed fetch leaves a newer call unknown) -> fixed + stale-data regression -> GO.

## Images
step28/regimes_top.png, regimes_callers.png, regimes_validation.png, regimes_full.png, regimes_phone.png (live), caller_bobloukas_by_regime.png (live caller page).
