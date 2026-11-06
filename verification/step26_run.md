# Step 26 run: Hyperliquid spot and DEX coins, ambiguous tickers picked by the owner

Built on branch step26 while the step 25 watcher ran its 24 hours, merged after (fefa3e8). Fix after the first live add: 8fc78f8. The owner's add: 11479ce (bot publish). Coins page: 76bca35. Test fix: 21614fea3e0d179d1e6a281e82caa7b6ad370a93 (served, CI guard + pages success).
Compare: https://github.com/sendoeth/pf-post-signals/compare/d1eff5d849740a2fe953a569b1251bc80727b3cc...21614fea3e0d179d1e6a281e82caa7b6ad370a93

## Live
- coins page: https://sendoeth.com/pf-post-signals/web/coins.html (rows KNTQ and NEST)
- https://sendoeth.com/pf-post-signals/web/pos-2118181656398090718_NEST.html
- https://sendoeth.com/pf-post-signals/web/pos-2118181656398090718_KNTQ.html
- https://sendoeth.com/pf-post-signals/web/caller-koolkrypto223.html

Served = the commit (curl | sha256sum vs git show 21614fea3e0d179d1e6a281e82caa7b6ad370a93): web/data/charts.json `ef9205c629c8b40f894c5c53417880fe0d13194254f77b1320f74584feda1ccf`, coins.html `b90b870f7c78b24797a1a71e43b940d3805068fd2c75da2fd9a304cdfe76b335`, pos NEST `b9874a8647f9b943422760b593283a472764ae6bf985b819792badd5382fa6c4`, pos KNTQ `c95ea83a9532b8382937c3327a197eb42293f880571450aa78fbfdac05e396ab`, caller `decab87fa5c660674397bc3149db9101117cec8151190720fb4b134536aac694`.

## The calls
@koolkrypto223 2118181656398090718 (2026-11-05 03:20:35Z), a reply to @0xLcrgs's portfolio post: "More $NEST and $KNTQ". Two legs, both LONG by the owner with the reason "reply to 0xLcrgs portfolio screenshot (BTC 94.9%, NEST 0.6%, no KNTQ): \"More $NEST and $KNTQ\" = add both".
| leg | priced on | entry (first hourly bar after the post) | record sha256 |
|---|---|---|---|
| NEST | dex:hyperevm:0x535f30f50ebda33575242c38b976e681d13db6fa (NEST / WHYPE 2%) | 0.026565305221382396 @ 2026-11-05T04:00Z | `b0f9af671163a6769246fb56c00344829792fc2422203dea9c73ecd8d306dfe5` |
| KNTQ | hlspot:@334 (KNTQ/USDC) | 0.45938 @ 2026-11-05T04:00Z | `c6a394be6230f32fe876d997e5d3d6bffd687a345b16f2d9a4fc85be1b9222ef` |

## KNTQ pair choice ([receipt](https://raw.githubusercontent.com/sendoeth/pf-post-signals/21614fea3e0d179d1e6a281e82caa7b6ad370a93/sources/tickers/KNTQ.json), sha256 `25b05ef462d931e61f9f0db9ad5182e521be05b236c662203d97d6d06b667630`, checked 2026-11-06T14:25:07Z, Kinetiq [kinetiq] $0.447309)
```
binance / hyperliquid perp / okx / gate: no KNTQ market
hlspot @254 KNTQ/USDH  mid null    mark 0.20712  24h volume $0           ok false  "no trades in 24h (volume $0, mark 0.20712): a stale pair"
hlspot @334 KNTQ/USDC  mid 0.447855 mark 0.44778 24h volume $8,864,624   diff +0.12%  ok true  chosen
```
Rules: a USD-stablecoin quote, >= $10,000 traded in 24h, mid within 5% of CoinGecko; USDC first, then volume.

## NEST resolution ([receipt](https://raw.githubusercontent.com/sendoeth/pf-post-signals/21614fea3e0d179d1e6a281e82caa7b6ad370a93/sources/tickers/NEST.json), sha256 `200bfa645e6907331a0caf72b2da7b5d5e71ea0cba882da162ceec99cd246e4c`, checked 2026-11-06T14:23:01Z)
1. Ambiguous: three CoinGecko coins named NEST; the post alone resolves nothing. The bot listed each with its chain + contract and a button: nest-2 #1458 hyperevm:0x07c57e32a3c29d5659bda1d3efc2e7bf004e3035, nest-3 #3680 solana:68Nq68CrtLVpyvK5Un7UADiNczaGf39hBbj3diRsYj6D, nest-4 #12325 robinhood:0x8e859dbdfbfd2df6a99870e2871eaa58e8784e05.
2. Owner pick: nest-2 (receipt "asked": "$NEST = nest-2 (owner pick)").
3. Pool found through the coin's contract (CoinGecko platforms -> hyperevm 0x07c5...3035 -> GeckoTerminal pools, deepest first):
```
hlspot: no NEST spot pair on Hyperliquid
dex hyperevm:0x535f30f50ebda33575242c38b976e681d13db6fa "NEST / WHYPE 2%"  liquidity $1,101,105  24h volume $203,895
    price 0.02292475 vs coin 0.02350826 (-2.48%)  pool base coingecko id nest-2  last hourly candle 1793970000  ok true  chosen
```
Rules: the coin is the pool's base token, >= $100,000 liquidity, price within 5%, the pool's metadata names the same CoinGecko id (missing = refused), a candle in the last 3 hours.

## Existing prices and scores unchanged ([unchanged_check.txt](step26/outputs/unchanged_check.txt), charts.json 8fc78f8 vs 21614fea3e0d179d1e6a281e82caa7b6ad370a93)
57/57 pre-existing positions: same entry price/time, side and status. Scores of the 7 other callers identical to the last digit; @koolkrypto223 53.290027 -> 48.787341 (the two new calls). 187 earlier tickers identical (KNTQ, NEST added). The bot's own check on each add: "frozen values of every other position unchanged: yes".

## Reachable from CI ([ci_probe.txt](step26/outputs/ci_probe.txt))
GitHub runner: Hyperliquid spot meta 200, @334 candles, GeckoTerminal pools / pool / OHLCV 200, CoinGecko platforms 200.

## Tests (fresh clone of 21614fea3e0d179d1e6a281e82caa7b6ad370a93, [fresh_clone_guard_and_tests.txt](step26/outputs/fresh_clone_guard_and_tests.txt))
guard history 106 commits 0 hits, tree 2650 files 0 hits, test_guard OK; tests.test_spot_dex 22 OK (pair choice + determinism, the stale pair, non-stable quote / disagreeing price, exchange venues never touch spot / DEX, the deepest passing pool found by contract, thin / foreign / mismatched / stale pools, a pool without a CoinGecko id, Solana case + polygon_pos prefix, ambiguity never guessed, the pick through the reader and the bot's candidate lines, the new sources' candles + schema, re-check flags without swapping, every registered coin and the ratings unchanged); test_add_call + test_history + test_tickers + test_seed 61 OK (incl. the add rollback and single-asset candles); full suite 283 OK (2 skipped); check_bundle ALL MATCH; validate_records 59 ALL VALID; fetch_ohlc --check-only 59/59. Private bot 66 OK (pick buttons, the pick carried through legs and the side prompt, strangers, malformed candidate lines).

## Review
Codex: design/implementation WITHHOLD (pool without a CoinGecko id passed, quote ranking over volume, Solana address case / polygon_pos prefix) -> GO; the add rollback + single-asset candles (after the live SOXL incident) GO.

## Bot (text: [bot_messages_as_text.txt](step26/outputs/bot_messages_as_text.txt); images committed)
step26/bot_1_watcher_card.png, bot_2_nest_pick_and_legs.png, bot_3_nest_no_side_then_change.png, bot_4_nest_long_preview.png, bot_5_nest_added.png, bot_6_kntq_no_side_then_change.png, bot_7_kntq_long_preview.png, bot_8_kntq_added_and_published.png; live pages: coins_row_KNTQ.png, coins_row_NEST.png, position_NEST.png, position_KNTQ.png, caller_koolkrypto223.png.
