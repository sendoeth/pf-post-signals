# Step 23 run notes: the top 100 coins and confirmed Hyperliquid perps seeded as plain tickers

## Live
- Coverage page: https://sendoeth.com/pf-post-signals/web/coins.html ("95 of the top 100 coins · 92 Hyperliquid perps · 187 tickers")
- goodalexander XMR: https://sendoeth.com/pf-post-signals/web/pos-2115966476817739790_XMR.html (Coin: Monero [monero] on hyperliquid:XMR)
- goodalexander XRP: https://sendoeth.com/pf-post-signals/web/pos-2115966476817739790_XRP.html
- Okada_DeFi0x ETH: https://sendoeth.com/pf-post-signals/web/pos-2116433840499790164_ETH.html
- Okada_DeFi0x HYPE: https://sendoeth.com/pf-post-signals/web/pos-2116433840499790164_HYPE.html
- rosa_onchain INJ: https://sendoeth.com/pf-post-signals/web/pos-2116091851086393720_INJ.html
- Leaderboard: https://sendoeth.com/pf-post-signals/web/

## Served
- Served commit `c18928400375c15480ecd55f511952d7756bd018` (the CI refresh after the bot's publish `e467b94d6f188b305272d16e659a7d1d1ad1972f`)
- Compare (end of step 22 -> now): https://github.com/sendoeth/pf-post-signals/compare/64931d1...c189284
- sha256 of the served https://sendoeth.com/pf-post-signals/web/data/charts.json = `41323a9855215cb16e3fc6f7cdff3f4bae7200e032e919b5a0b5e995b70a4e2f` (same as `git show c189284:web/data/charts.json`)
- Guard CI success on every commit of the step (69b56e9, d69212d, e467b94, e6a98e2, f56d34c and the CI refreshes)

| commit | what |
|---|---|
| 69b56e9 | seed + venues (OKX / Gate / Bybit) + offline registry + detection rules + weekly re-check + coverage page |
| d69212d | live-run fix: stock talk counts only next to the coin ("single name stocks" sent BTC / XRP to review) |
| e467b94 | the private bot's publish: XMR, XRP, ETH, HYPE, INJ |
| e6a98e2 | live-run fix: no Bybit (HTTP 403 to the GitHub runners), the re-check survives any unreachable venue; re-seed |
| f56d34c | found while packaging: the daily refresh dropped side_choice / renamed_from; carried now, 26 records restored |
| baf5019, c189284 | CI refreshes: the weekly re-check written by the runner, side_choice kept |

## Coverage (outputs/coverage.txt)
- **95 of the top 100 coins**, counted after 40 exclusions, + **92 Hyperliquid perps** = **187 tickers**; 20 to review; 0 flagged.
- Top 100 to review, each with its reason (never guessed): WBT WhiteBIT Coin #15, BGB Bitget Token #68, KCS KuCoin #74 (only on Bybit / their own exchanges: "no trading venue with hourly bars agrees"), 币安人生 #102 ("symbol is not a plain ticker"), HASH Provenance #115.
- Excluded (not coins): 25 stablecoins, 6 tokenized treasuries, 4 tokenized gold, 2 bridged copies, tokenized credit / private credit, 1 by name ("fund").
- Venues: Binance 146, Hyperliquid 25 (e.g. XMR: Binance delisted it), Gate 11, OKX 5 (LEO, OKB, CRO, PI, FLR). Bybit is not used: it answers HTTP 403 to the GitHub runners that refresh prices daily (a Bybit-priced record could never be refreshed).
- Market indexes TOTAL / TOTAL2 / TOTAL3 / OTHERS / BTC.D / USDT.D / stablecoin dominance are recognised in posts and go to review (no free price history source; CoinGecko's market-cap history is paid). Stablecoin cashtags are ignored; wrapped copies map to the coin ($WBTC -> BTC).

## Receipts
- Seed (the whole run: every coin, venue check, exclusion and review with its reason, the sha256 of each bulk response):
  https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/sources/tickers/seed/2026-11-02.json sha256 `9426725046be36e70a940546e5e7c532a240c6833dfbeeebcac6979605abc85a`
  (the first seed, before dropping Bybit: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/sources/tickers/seed/2026-11-01.json `eb1e28b09f32298e60449a0b053de8fe99c30c868301269ba6c3db843761e55b`)
- Weekly re-check, written by the GitHub runner (187 checked, 187 ok, 0 flagged, 0 unreachable):
  https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/sources/tickers/recheck/2026-11-02.json sha256 `26f996104bb3cf1cfab94f0b43ae833cba1e22b9d889b6a3d7496150cc97f800`
- Registry https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/data/tickers.json (`a820f896…`), coin words https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/data/coin_words.json (`f749598e…`), coverage data https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/web/data/coins.json (`96f6e81c…`), one receipt per coin in sources/tickers/<TICKER>.json.
- CI re-check runs (outputs/ci_recheck_runs.txt): run 41376101027 failed closed ("provider unavailable: api.bybit.com: HTTP 403", nothing written, the refresh continued) -> Bybit dropped -> run 41377918015 "re-checked 187 tickers: 187 ok" -> run 41378871838 after the carry-over fix.

## The live run (private bot /add, no manual asset flag; screenshots below)
| post | coins found (legs) | added |
|---|---|---|
| goodalexander 2026-10-30 "Still like long XMR. sized down BTC am short bunch of single name stocks … hedged it with long xrp" | XMR long, BTC none, STOCKS short, XRP long ("long xrp", lowercase name) | XMR (Monero on hyperliquid:XMR, entry 623.54), XRP (binance:XRPUSDT, entry 1.2247) |
| Okada_DeFi0x 2026-10-31 "i deployed 60% of my portfolio into $ETH and $HYPE … scenario where $BTC drops to $70K" | ETH long, HYPE long ("deployed" before the coins), BTC none | ETH (2244.04), HYPE (88.27) |
| rosa_onchain 2026-10-30 "Will buy $NEAR at $3 > Will buy $HYPE at $60 > Will buy $SOL at $70 > Bought $INJ at $4" | NEAR, HYPE, SOL, INJ | INJ only (7.234): the others are unfilled limit orders, an owner decision |
| BobLoukas 2026-10-21 "Currently long bitcoin - short gold futures" | BTC long, GOLD short | refused: "duplicate … already recorded in records/bobloukas/" (from the earlier scan) |

Every coin resolved offline from the seeded registry (no CoinGecko call, no rate-limit wait). Records carry asset_choice.method detector + ticker (coin id, receipt sha256) + leg, side_choice detector-leg with the post's words; live outputs/live_served.txt.

What the live run caught, and what changed:
1. "single name stocks" made BTC and XRP (also ETF tickers: Grayscale BTC, Bitwise XRP) go to review in the first goodalexander run -> stock talk now counts only within 40 characters of the coin (d69212d); the second run shows XMR · BTC · STOCKS · XRP legs (screenshots tg_01 vs tg_04 / tg_16).
2. The first XRP Add was pressed while the background context check held the job lock: "busy … this button was already used" (tg_06): the single-job lock and single-use buttons doing their job; XRP was added later (tg_17, tg_18).
3. /publish was refused once: "The live repo moved since this copy (e.g. the daily refresh)" (tg_15): the bot never publishes on a moved repo; the server copy was rebased (bundle, pages, candles rebuilt from the records) and the second /publish went through.
4. The first CI weekly re-check failed closed on Bybit's HTTP 403 -> Bybit dropped (e6a98e2), CI re-check green.
5. Packaging the evidence showed that the daily refresh dropped side_choice (since step 16) and asset.renamed_from (since step 22) -> carried, 26 records restored from their last version that had them, a test now fails if any optional schema field is neither recomputed nor carried; proof: caller scores equal, no frozen value moved, all 57 positions equal apart from the restored labels (outputs/refresh_carry_restore.txt); CI refresh c189284 keeps them.

Follow-ups noted (not changed mid-run): "will buy … at $X" is a conditional order and should give no side; the context check's "the original call" picks noise for very active accounts; review legs keep their written form in leg.of on the first XMR record ("btc", "xrp").

## Tests (outputs/)
- focused tests.test_seed + tests.test_tickers + tests.test_refresh: 44 OK (1 skip: the scratch rename test once the repo is renamed). Seed rules: stablecoin by category and by peg, wrapped / tokenized exclusions, top 100 counted after exclusions, a halted pair, a wrong-price pair, an OKX-only coin, two comparable coins, kPEPE perps, a kept venue that fails today, US-stock overlap. Detection: names, bare tickers, common words ("near the top, link in bio", "NEAR the highs", "total nonsense"), indexes (BTC.D is never BTC), stablecoins ignored, wrapped -> underlying, stock talk only next to the coin, the three Codex repros (flags, untrusted receipts, stock talk in every branch). Offline: no provider call for registered coins; a tampered receipt is not trusted. Re-check: flag, recover, never swap, unreachable venue not checked, provider down writes nothing. Candles: OKX / Bybit / Gate parsing. Refresh: every optional schema field recomputed or carried.
- all python: 216 OK; fresh clone at c189284: guard --history 90 commits 0 hits, --tree 2563 files 0 hits, focused tests OK, check_bundle ALL MATCH, validate_records ALL VALID, candles 56/56, the goodalexander text resolves offline with no provider call, a rebuild changes nothing.

## Private bot (fingerprints only, source stays private; the bot did not change in this step)
- quanty_admin.py sha256 `53d8abad71e378c988c353211190e66dab8af650713f6b6ab158257eed0f4c74`, tests/test_bot.py `1e370efa41dcdad9a06301b2fd9b0d896cf60812242b0b2cdc598b2ee29092db`
- Telegram screenshots (image upload on the task node fails with inference_response_truncated, a known Task Node defect; the images are linked here):
  - key moments in one image: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_step23_key_moments.png sha256 `d97e9e81e3ea566bc74304bb0262d3b8abdfa59f4a446c596824e74486ed0428`
  - tg_01: goodalexander /add: first legs, BTC / XRP wrongly in review: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_01.png sha256 `a3369fd56590e5f219acb6122e0abed5389f298f0a1562386a4b88057ecf5719`
  - tg_02: XMR leg preview: Monero on hyperliquid:XMR, long: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_02.png sha256 `b6aaf551ef2c24e388499b284a690f923dc442983bb785e5d84ddac62a40f770`
  - tg_03: XMR context, Add: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_03.png sha256 `6afd89817590474cff15a24a302737f940fd4854fac37d8255fff2c04e293e39`
  - tg_04: XMR added; second /add: legs fixed (XMR · BTC · STOCKS · XRP): https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_04.png sha256 `adfc4a8658d6494ab65b46305340b8fff7dfadb5a3499c68439c3195dd43a9f5`
  - tg_05: XRP preview: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_05.png sha256 `6c1bfbfd7587eeaab97d038738d7291e0577c516ae9df88bba48b028616833ce`
  - tg_06: busy with context -> button already used; Okada /add legs (ETH / HYPE long from 'deployed'): https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_06.png sha256 `67156060e36c1d73d27097025df4709e32244b86750cedbff8c052f16db1c9a0`
  - tg_07: ETH preview: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_07.png sha256 `94f3c732b457fc10b2c541115d52963435ec150ecb29367bf859c09a3dbdcbdc`
  - tg_08: ETH context: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_08.png sha256 `e0d58caa16a38e1343ceb1ad3846ce658b41a5b3b80322cd3d1244251a0cd1ad`
  - tg_09: ETH added: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_09.png sha256 `4b6866ed3b125d5f062815469208f8e412f56677d339b3156d4349992ce9d032`
  - tg_10: HYPE preview: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_10.png sha256 `43c4c37e08dede282e6de4f6fe07924e112b6221e4c7c4e005f47d8efeb2a6db`
  - tg_11: HYPE added; BobLoukas /add: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_11.png sha256 `aa2edd09c9b323673fa04caa8213851feeeb613b8233039f6a4b8d01edd8724f`
  - tg_12: BobLoukas legs -> BTC / GOLD refused as duplicates: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_12.png sha256 `e63bf46488117dd9c13087968301d2e58316487a7c1f91456190e21c61e52e78`
  - tg_13: rosa /add: NEAR / HYPE / SOL / INJ legs: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_13.png sha256 `f43fd4a09377d93457d4d6c891dfbafa22877890341a86b8b7f2baa8d2e269eb`
  - tg_14: INJ preview: Injective, 'Bought $INJ': https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_14.png sha256 `2b7e0912f3e0394e3de3760f03762bbcd6cadda6051becab1c59438037aa48a6`
  - tg_15: INJ added; /publish refused: the live repo moved: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_15.png sha256 `aa356eea94df70ef3ed7b55100967057571c959c86fc09855adae80638f03c43`
  - tg_16: goodalexander /add again: XRP leg: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_16.png sha256 `c160a7f2c8ba5aa12e059000c647008a369985c16cb76730e2dda75ce066d2d1`
  - tg_17: XRP preview: coin XRP [ripple], 'long xrp': https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_17.png sha256 `7f7d935e7eadea3d32a63c9d551a64e4f82198f3a5e142375173e5eaa8f23453`
  - tg_18: XRP added; /publish: 76 files, 5 records, scores: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_18.png sha256 `80abf30db48409802ea72dabf6c4c757ab88560283540979dc09ff435cc9164d`
  - tg_19: Published e467b94, 5 checks pass: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/telegram/tg_19.png sha256 `0d042f76820561b0f8bd9b8bfa1802c130cc2b0c7701675f8192a16111433f2e`

## Output files
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/outputs/all_python_tests.txt sha256 `f21e6b66a02152b95195d19f53391d6d8e034db2578abc4b939192a29d0632a5`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/outputs/ci_recheck_runs.txt sha256 `07332d9f91e5221c19e2da3e63ba007919b72a0b30e0d76ee212ba9a4c8c149b`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/outputs/coverage.txt sha256 `47b4ffaf5de509251894db66e4d526c77d71ed8edecc0d1e3a5aa18d74a4095b`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/outputs/focused_tests.txt sha256 `4410b8b18837faa08ad563187dd499f1b521bb6a6fd98a4d6f3df98d9c9c2999`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/outputs/fresh_clone.txt sha256 `1f33f5a79dc1e12d02a21b6b7617688e1e1189615f0d79a401905c2779cf1d65`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/outputs/live_browser.txt sha256 `ea83210af354819e89c6b6457bfba7dbb2a7017f82cfcbbf7d7d9dd975f319b2`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/outputs/live_served.txt sha256 `bd69caf8d5de1dfe3d049d8b27ce5822a8085bd0d18e67aa7809503f4136d7f5`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/outputs/refresh_carry_restore.txt sha256 `4c3ee9c28597b9b37b21762ea1687272d8c1ab9de7e745099d79a10462842432`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/live_coins.png sha256 `5064d730383da25197ff25083e7b90355dcd08b174c1f174eb62ecd484a11081`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step23/live_pos_XMR.png sha256 `47ebe33578a5a32a9d103c1d5574d31792f7c3429d1fbe8e85ba703657fa9869`

Check any of them yourself: `curl -sL <raw link> | sha256sum`
