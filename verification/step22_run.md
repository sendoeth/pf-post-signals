# Step 22 run notes: plain tickers with safe automatic price resolution

## Live
- koolkrypto223 LIT (Lighter): https://sendoeth.com/pf-post-signals/web/pos-2116898993435463783_LIT.html
- koolkrypto223 HYPE: https://sendoeth.com/pf-post-signals/web/pos-2116898993435463783_HYPE.html
- ZEC under its plain ticker: https://sendoeth.com/pf-post-signals/web/pos-1970742039722479782_ZEC.html
- the old ZEC URL (redirects): https://sendoeth.com/pf-post-signals/web/pos-1970742039722479782_binance-ZECUSDT.html
- leaderboard: https://sendoeth.com/pf-post-signals/web/

## Served
- Served commit (pushed by the private bot's /publish): `563a16583feb92f4e63a0e5fda6b137b48c6ed1b`, tests fixed in `68af4ef` (guard CI success: see below)
- Compare (end of step 21 -> now): https://github.com/sendoeth/pf-post-signals/compare/3ac0bbf...68af4ef
- sha256 of the served https://sendoeth.com/pf-post-signals/web/data/charts.json = `8591d74a2f3d7e8066a904fc2d07756ae5cacc0649b486d2263087a2be7a2421` (same as `git show 563a165:web/data/charts.json`; 68af4ef changes only a test)
- Guard CI: **failure on 563a165** (tests/test_tickers.py simulated the koolkrypto add on a copy of the site and broke once the real post was published: "duplicate"), **success on 68af4ef** after the tests used a scratch site as it was before the post. The served data and pages did not change between the two.

| commit | what |
|---|---|
| 9ad5099 | tickers.py resolver, contract cashtags, coin legs + option sides, add_call --leg, schema (additive), redirects, ZEC rename |
| 81b64c3 | evidence: ZEC rename report, 8 browser suites |
| 563a165 | the bot's publish: koolkrypto223 HYPE + LIT, tickers HYPE + LIT |
| 68af4ef | test isolation fix (guard green) |

## How the coins were resolved (the post: https://x.com/koolkrypto223/status/2116898993435463783)
"…selling some $100 HYPE calls for Dec25, and buying ~equal premium of $LIT calls." X turned $HYPE into the contract tag `hyperliquid:native`; $LIT is a plain cashtag.

1. `/add <post>` in the private bot, **no --asset**. The tool refused to guess between two coins and listed one leg per coin with its coin, venue and side:
   - `LEG HYPE side none: selling calls caps the upside; it is not a stated short ('selling some $100 HYPE calls') via hyperliquid:native = Hyperliquid [hyperliquid] on binance:HYPEUSDT`
   - `LEG LIT side long: buying calls ('buying ~equal premium of $LIT calls') via $LIT = Lighter [lighter] on hyperliquid:LIT`
2. A button per leg ran `add_call.py <post> --leg HYPE` / `--leg LIT` (the detector's own leg, recorded as `asset_choice.method: detector`, `side_choice.method: detector-leg`), then Add (`--add --leg …`), then /publish. The bot audit shows no `--asset` in any call.

Receipts (identity + venue check, kept with the records):
- LIT: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/sources/tickers/LIT.json sha256 `c726444899d400b7bf616904ab467cd24ff50a15a01eea587f076738be367b08` (the sha256 the bot preview showed). Coin Lighter [lighter] #82 $3.21; candidates incl. Litentry [litentry] #1787; venues: binance:LITUSDT **skipped: not trading (status BREAK)**, stale price 0.743 (-77%); hyperliquid:LIT **ok** (-0.35%). Chosen hyperliquid:LIT.
- HYPE: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/sources/tickers/HYPE.json sha256 `f9eaceb09ea3808263d85c9dff38473caf32f681997ddae071f6c4f07bbe9956`. Asked as `hyperliquid:native` -> Hyperliquid [hyperliquid] #10; binance:HYPEUSDT ok, hyperliquid:HYPE ok; chosen binance:HYPEUSDT.
- ZEC: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/sources/tickers/ZEC.json sha256 `cfc66ac234462a02b7fd0423f7fe1c5d6859c70862a9b0cd8eca79b1384ad3d6` -> Zcash [zcash] #11 on binance:ZECUSDT (the venue the record already used).
- Registry: https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/data/tickers.json sha256 `73fac665a3fa903f692144ad1c4ec41f7992c9c29959a78d72d0469f229598e7`

Live records (outputs/live_served.txt): HYPE binance:HYPEUSDT no side, entry 88.08 @ 2026-11-01T15:00Z; LIT hyperliquid:LIT long, entry 3.2523 @ 2026-11-01T15:00Z; both `leg.of = [HYPE, LIT]`.

## The Litentry collision (outputs/litentry_collision.txt, run live)
1. `$LIT` as a post names it -> OK, Lighter on hyperliquid:LIT; binance:LITUSDT skipped (halted since 2025-02-10, stale 0.743, -77% from Lighter's 3.23).
2. Litentry asked for explicitly (coingecko id `litentry`) -> **REVIEW**: "LIT is already Lighter (lighter) on the site, this is Litentry (litentry)".
3. The same with an empty registry -> **REVIEW**: "no trading venue with hourly bars agrees with Litentry's price" (binance halted at 0.743, +664%; hyperliquid 3.22, +3209% from 0.097).

## ZEC before / after (outputs/zec_rename.txt + zec_rename.json)
`tools/rename_asset.py binance:ZECUSDT ZEC`: the ticker had to resolve to exactly the record's source:symbol (Zcash on binance:ZECUSDT) before anything moved.
- entry `{"at": "2025-09-24T07:00:00Z", "price": 54.49}` EQUAL; exits 1d 58.32 / 7d 79.09 / 30d EQUAL; signed returns 0.07029 / 0.45146 / 3.74638 EQUAL; latest 1251.48 EQUAL; status resolved EQUAL; closed null EQUAL; best 1684.6 EQUAL
- caller scores all EQUAL, mert 54.54545454545455 -> 54.54545454545455 (and still that value after the koolkrypto add)
- lifecycle: no ZEC entry (untouched); the old position URL is a static redirect from data/redirects.json (meta refresh 0 + canonical); a real browser opening the old URL ends at pos-1970742039722479782_ZEC.html (outputs/live_browser.txt)

## Tests (outputs/, raw links below)
- focused tests.test_tickers + tests.test_static + tests.test_call_context: 44 OK (1 skip: the scratch-copy rename test skips once the repo is already renamed). Resolver: collision, halted pair, a trading pair at the wrong price, no agreeing venue = review, two comparable coins = review, unranked-only = review, unknown ticker = refused, provider down = refused, 429 waits then fails closed, contract tags (native + ERC-20 + unknown), registry conflict. Legs: the real post, option sides, mapped assets without lookups. Add without --asset: legs required, LIT = Lighter, HYPE no side, receipt registered at add. Codex repros: a registered venue failing today's check is refused, a contract tag next to a mapped cashtag forces legs, buying puts = short.
- all python: 196 OK; browser suites (browser, board, position, callers, ratings, security, polish, episodes): ALL PASS after the rename
- fresh clone at 68af4ef: guard --history 75 commits 0 hits, --tree 2318 files 0 hits, focused tests OK, check_bundle ALL MATCH, validate_records ALL VALID, candles 51/51, ZEC/HYPE/LIT resolve offline from the registry, a rebuild changes nothing

## Private bot (fingerprints only, source stays private)
- quanty_admin.py sha256 `53d8abad71e378c988c353211190e66dab8af650713f6b6ab158257eed0f4c74`, tests/test_bot.py sha256 `1e370efa41dcdad9a06301b2fd9b0d896cf60812242b0b2cdc598b2ee29092db`: 51 OK (leg buttons, --leg never --asset, single-use buttons, context priced by source:symbol for a new coin, /publish allows data/tickers.json + sources/tickers/<TICKER>.json only)
- Telegram screenshots (stitched from the owner's 9 screenshots, overlaps cut; no ids or addresses visible):
  - https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/telegram/tg_step22_key_moments.png sha256 `2f3a9c87d1dd418dac38b0f16e47eae5b1057dc852ab90b81900300cf28284bd`: compact single image (two coin legs, the LIT leg resolved to Lighter, /publish -> Published 563a165)
  - https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/telegram/tg_step22_all_in_one.png sha256 `23fbea79032189275e3a775bb694dd42e5155ff8c5fa5c8d2f552eab294c18e5`: the three below side by side in one image
  - https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/telegram/tg_1_add_legs_hype.png sha256 `32256ed5d7e738e5bfe95313209c8812e9dfed4706cdc2030aaea3021144cfb8`: /add with no asset -> 'Several coins in this post' with one button per leg (HYPE = Hyperliquid on binance:HYPEUSDT, LIT = Lighter [lighter] on hyperliquid:LIT) -> HYPE leg preview (no side, from 'selling some $100 HYPE calls') -> Add -> context -> 'added ..._HYPE.json', score = preview
  - https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/telegram/tg_2_lit_leg_lighter.png sha256 `021ba42b559e8010df3ca6f3ead24f6c81c86c478483e10d3f3a6758fb16e250`: second /add -> legs -> LIT leg preview: asset LIT (hyperliquid:LIT) by detector, coin Lighter [lighter], receipt sha256 c726444899d400b7..., side LONG by detector-leg ('buying ~equal premium of $LIT calls'), entry 3.2523 -> context
  - https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/telegram/tg_3_lit_add_publish.png sha256 `c13812f6a38322f51e70724c26cd39f4c13e21d92efe7c3fc12fe6cc0b16de8a`: /cancel of a stray manual prompt (nothing typed) -> LIT added (47.8 = preview) -> /publish (41 files, both records, @koolkrypto223 new -> 47.8) -> Published 563a16583feb92f4e63a0e5fda6b137b48c6ed1b with all 5 checks passing

## Raw evidence links
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/all_python_tests.txt sha256 `878d6bc29b9befc3a7580f24de11e9441fe7351ea6ad196ef658af97bd724414`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/browser_board_test.txt sha256 `7b2d5a78b32ab96cb453670b8102dd85ee7d551d7647225142aba4f950ed9e43`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/browser_browser_test.txt sha256 `e1f03253114b3e68a2d590f2febbc35ba14f8bb6b42ffc71e511b18853e2f560`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/browser_callers_test.txt sha256 `d13df4367fd3cfff22969283699c864c43f590b95f218ff58340ace696d57cfb`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/browser_episodes_test.txt sha256 `f4291bf9d7ffcb82c3f5f3b66e7bbb0d34edfcf7a19d91ec1e5e68c579160d88`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/browser_polish_test.txt sha256 `ed035374948216db1ddd0563008194911878d7b901a79fea29221e4f3fa2e05a`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/browser_position_test.txt sha256 `46bd34a4e7ae70037b8183f60afe83a359521ad7e5779aaf7ddb83faf5f6c001`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/browser_ratings_test.txt sha256 `3cf39f18f32c1f7fbd132dfabb0635f7fae87f7b3c02f9b8a3f2d82829a41823`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/browser_security_test.txt sha256 `9a70eff7841011b0c6f561e7da3d0226d8f1294d1cedfeea640c68f6748d674f`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/focused_tests.txt sha256 `828513945dcc3b40c7e40be12d837aeb6870f3dbeb3ce35823d62080963d33a7`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/fresh_clone.txt sha256 `3722db895d6554176dfd2d8b33e3187eef67bebbf6bbcde698cb5d760cf9c6b5`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/litentry_collision.txt sha256 `181644531933bc86d396c8b0d5490a23343305ca35c831e4c8ac12753c17824b`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/live_browser.txt sha256 `588d3ff9b78cab796b8d48ea0184fe063914751bbcb125b67873268624bcd6c3`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/live_served.txt sha256 `5a93b556695a989721ef3c476166696fbe9eaeee11202d8ce87639781b049a98`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/private_bot.txt sha256 `af24b3424878dd86e2be30ae629ea821f313866f93acd8b056dbdb309c83d351`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/zec_rename.json sha256 `e47292d249405aba2e54fd6a1385e7e2c5428ef7f28423518f3c31fa99ec614c`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/outputs/zec_rename.txt sha256 `a7ea2ce79cf35efd6d0098c8af4c80923e462fdd6ecb3f1171da5a2f71b3e177`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/live_pos_HYPE.png sha256 `3882a47ceae504d4648cbfca0553945ec5a75acb53cb5ea1f56b47519a34ebaf`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/live_pos_LIT.png sha256 `eaa4559e29477c7e47b987482f73bf3efaaffed2b9eb0b936cb469ac39cc8147`
- https://raw.githubusercontent.com/sendoeth/pf-post-signals/main/verification/step22/live_pos_ZEC.png sha256 `6bdc53c84f42c1cc732419208169e3d76e6155c9583a3a3dfa6a02151117d40a`

Check any of them yourself: `curl -sL <link> | sha256sum`
