# Step 24 run: early signals for mert x SOL and mert x ZEC

Site commit: `3bc93505957ffb91a161d3688fe42148a6f87840` (compare: https://github.com/sendoeth/pf-post-signals/compare/d738a278c6142390fd980d609cbc1adc52595b0a...3bc93505957ffb91a161d3688fe42148a6f87840).
CI on it: guard success, pages build and deployment success.

## Live
- caller page: https://sendoeth.com/pf-post-signals/web/caller-mert.html (#early-SOL, #early-ZEC, affiliation above them)
- coin sections: https://sendoeth.com/pf-post-signals/web/coins.html#early-SOL and https://sendoeth.com/pf-post-signals/web/coins.html#early-ZEC

Served files, byte-identical to the commit (curl | sha256sum vs git show):

| file | sha256 |
|---|---|
| web/data/charts.json | `41323a9855215cb16e3fc6f7cdff3f4bae7200e032e919b5a0b5e995b70a4e2f` |
| web/data/early.json | `e74ab09bc14c52e2565c5d7c0e07c708253a20e60cf3d073bbbb100d650f2d5d` |
| web/caller-mert.html | `9f1999100a832dc5f8e4a7c6f4665fb18db27593cb214d3ef50547ac776f4dbe` |
| web/coins.html | `25f4453d98046555b15fccb21df74de0ec844914b4d4a39c9dc32ca507d14dd7` |
| web/data/coins.json | `3a6b8b2e644a5ff6ee1d6e2798a8e15582feb50cb4cb8ec656e0c0f8608c4762` |

Scores unchanged: web/data/charts.json is the same file as at d738a27 (step 23); the ratings JSON hash is `9f7d7e07fcdc2a5a676b4d98a9afbea590141ab00dd4f1c91d55b201f8d6913d` before and after; check_bundle.py recomputes all 8 caller ratings independently -> ALL MATCH.

## Results

| | mert x SOL | mert x ZEC |
|---|---|---|
| first post naming it | 2021-07-04T17:05:56Z [1411733026724327429](https://x.com/mert/status/1411733026724327429) | 2024-08-07T14:15:16Z [1821188361559978050](https://x.com/mert/status/1821188361559978050) |
| words | "This tutorial from @Figment_io is absolutely amazing for getting up to speed on @solana development. Would highly recommend: …" | "I'm pretty sure you could actually add zcash to solana and enable full privacy You'd sacrifice some latency but that'd be worth for the set of users that'd be interested in it" |
| matched / read as | solana / mention | zcash / mention |
| receipt sha256 | `5c00f28ba0112f827266185639b46ceccb7af39f30ed2dcc2952326f5c945ade` | `22afafe009a3a9445dcd5f88fbbb1ac31a088b15c22c5647b498c18479c6782c` |
| searches | 59 (2017-11 .. 2021-06 confirmed empty) | 57 (2016 .. 2024-07 confirmed empty) |
| price then | $35.113 binance:SOLUSDT, 1h open 2021-07-04T18:00Z | $31.62 binance:ZECUSDT, 1h open 2024-08-07T15:00Z |
| price now | $93.54 binance:SOLUSDT 2026-11-02T16:00Z | $1,254.65 binance:ZECUSDT 2026-11-02T16:00Z |
| multiple | 2.66x | 39.68x |
| peak since | $295.83 binance:SOLUSDT daily high 2025-01-19 (8.43x) | $1,698.00 binance:ZECUSDT daily high 2026-09-26 (53.70x) |
| sources tried | SOLUSDT from 2020-08-11, SOLBUSD from 2020-04-10, bitfinex tSOLUSD from 2021-02-25 | ZECUSDT from 2019-03-21, bitfinex tZECUSD from 2016-10-29 |
| before listing | no (the venue covers the post) | no |
| first recorded call | none on SOL | "I am irresponsibly long ZEC" 2025-09-24 at $54.49: 413 days later, 1.72x above the first-post price |
| normal call added | none (a mention, not a position) | none (a mention; the call already exists) |

The now price and the peak move with the daily refresh (first_mention.py refresh in refresh.yml); the post, the then-price and the search log stay frozen.

Affiliation (shown above the blocks, context only): Mert Mumtaz, co-founder & CEO of Helius (Solana RPC / data infrastructure), per https://www.helius.dev/about whose JSON-LD lists https://x.com/mert in sameAs. data/affiliations.json sha256 `2ca3315ea2730f84e0131da488906021fbda28e7ccaa308a5f2596298deb5e77`.

## Search method and the complete logs
Per year from the coin's floor (SOL 2017-11-01, ZEC 2016-01-01), then month by month inside the first non-empty year, then halves down to a day while a window answers 15+ posts. Each empty window is searched twice and is confirmed empty only if a canary (from:mert, last 7 days) returns at least half of the best canary count; X answered 90 -> 26 -> 0 while throttling, so 7 runs stopped and resumed (all logged). Query: `from:mert ($sol OR sol OR solana)` / `from:mert ($zec OR zcash OR zec)`.

- full logs (every search, run id, manifest sha256): [intake/early/mert_SOL.json](https://raw.githubusercontent.com/sendoeth/pf-post-signals/3bc93505957ffb91a161d3688fe42148a6f87840/intake/early/mert_SOL.json) sha256 `481521573dbeb22f0c18a5f5b50374d28f193a1293737237e4e2e012e43dde08`, [intake/early/mert_ZEC.json](https://raw.githubusercontent.com/sendoeth/pf-post-signals/3bc93505957ffb91a161d3688fe42148a6f87840/intake/early/mert_ZEC.json) sha256 `5f38524b8f68d12e7a9c522e526b9ae46031090882a6ad7a2d363b8ae1a0750f`
- signals with prices and receipts: [sources/early/mert/SOL.json](https://raw.githubusercontent.com/sendoeth/pf-post-signals/3bc93505957ffb91a161d3688fe42148a6f87840/sources/early/mert/SOL.json) `4ec5c809b3943779bb58b159be0bf56a7871b2246851ef31d30571f51749875c`, [sources/early/mert/ZEC.json](https://raw.githubusercontent.com/sendoeth/pf-post-signals/3bc93505957ffb91a161d3688fe42148a6f87840/sources/early/mert/ZEC.json) `734a1910fde5eaf965b2910a152766ae877c6a566d2af9348610c3ab187cdfad`
- receipts: [1411733026724327429.json](https://raw.githubusercontent.com/sendoeth/pf-post-signals/3bc93505957ffb91a161d3688fe42148a6f87840/sources/mert/receipts/1411733026724327429.json), [1821188361559978050.json](https://raw.githubusercontent.com/sendoeth/pf-post-signals/3bc93505957ffb91a161d3688fe42148a6f87840/sources/mert/receipts/1821188361559978050.json)
- bundle: [web/data/early.json](https://raw.githubusercontent.com/sendoeth/pf-post-signals/3bc93505957ffb91a161d3688fe42148a6f87840/web/data/early.json), [web/data/charts.json](https://raw.githubusercontent.com/sendoeth/pf-post-signals/3bc93505957ffb91a161d3688fe42148a6f87840/web/data/charts.json)
- code: [tools/first_mention.py](https://raw.githubusercontent.com/sendoeth/pf-post-signals/3bc93505957ffb91a161d3688fe42148a6f87840/tools/first_mention.py), [tests/test_early.py](https://raw.githubusercontent.com/sendoeth/pf-post-signals/3bc93505957ffb91a161d3688fe42148a6f87840/tests/test_early.py)
- readable tables of both logs: [outputs/search_log_tables.md](step24/outputs/search_log_tables.md)

## Run output
- [find_mert_SOL.txt](step24/outputs/find_mert_SOL.txt), [find_mert_ZEC.txt](step24/outputs/find_mert_ZEC.txt): the final resumed run of each search, printing the whole log
- [price_mert_SOL.json](step24/outputs/price_mert_SOL.json), [price_mert_ZEC.json](step24/outputs/price_mert_ZEC.json): the price command (SOL now was $94.34 at 14:00; the 16:00 refresh is what is served)
- [fresh_clone_guard_and_tests.txt](step24/outputs/fresh_clone_guard_and_tests.txt): fresh clone of 3bc93505957ffb91a161d3688fe42148a6f87840: guard history 92 commits 0 hits, tree 2604 files 0 hits, test_guard 7 OK, test_early 23 OK, full suite 239 OK (2 skipped), check_bundle ALL MATCH
- [browser_board_test.txt](step24/outputs/browser_board_test.txt): board_test ALL PASS; the other 7 browser suites (browser, callers, episodes, polish, position, ratings, security) ALL PASS

What the tests prove (tests/test_early.py): empty windows searched twice (test_empty_windows_are_searched_twice); a weak or empty canary stops instead of confirming, and is re-searched on resume (test_a_weak_canary_does_not_confirm_an_empty_window, test_throttling_stops_instead_of_reading_empty); a window full of word hits is opened (test_a_full_window_of_word_hits_is_opened_not_skipped); reposts and "el sol" not counted (test_word_hits_and_reposts_do_not_count); mention vs stated position vs repost (test_mention_position_repost); before-listing pricing at the earliest first bar, an older pair covering an earlier post, failures never shown as before listing (test_before_listing, test_an_older_pair_covers_an_earlier_post_and_its_peak_counts, test_a_failed_lookup_is_never_priced_as_before_listing); the post day in the peak and the refresh (test_the_post_day_counts_for_the_peak, test_the_daily_refresh_never_reads_the_post_day_from_midnight); ratings unchanged with the blocks on both pages (test_block_on_the_caller_and_coins_pages_and_scores_unchanged).

## Review
Codex (bridge) pre-consult: WITHHOLD x3 (saturated word-hit windows skipped; source failures aborting / mislabelled before listing; the peak missing the post day; the refresh re-reading the post day from midnight), each fixed with a test, then GO.

## Images (live pages)
step24/caller_mert_top.png, caller_mert_affiliation.png, caller_mert_early_SOL.png, caller_mert_early_ZEC.png, coins_early_signals.png, coins_row_SOL.png, coins_row_ZEC.png
