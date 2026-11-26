# Step 30 run: owner-confirmed sector tags

Code: bd0becd (step 30: data/sectors.json, tools/sectors.py, tags on leaderboard / position / caller pages, static sectors.html, bot /sector + /sectors). CI guard + pages success.
Owner data: 05de224 (the admin bot's /publish after the owner confirmed 10 sector changes in Telegram; the bot labels it "0 record(s)" because no call record changed, only the 3 sector files and the pages that show them).
Live: https://sendoeth.com/pf-post-signals/web/sectors.html · leaderboard https://sendoeth.com/pf-post-signals/web/index.html · position https://sendoeth.com/pf-post-signals/web/pos-2116199680157647216_GOLD.html and https://sendoeth.com/pf-post-signals/web/pos-corbanu-skhx-entry_XYZ-SKHX.html · caller https://sendoeth.com/pf-post-signals/web/caller-bobloukas.html · data https://sendoeth.com/pf-post-signals/web/data/sectors.json
Scores unchanged: web/data/charts.json 88dc1f5a5b6eeadf8e4825421a8093bbdddb269fda68916995c4d46f0e25c0c2 before step 30 (b82260d) = step 30 (bd0becd) = after the owner's sectors (05de224) = served. No file under records/ changed.

## Owner-confirmed sectors (data/sectors.json, sha256 d4cca828…)
| sector | proxy (label, never priced) | asset | source |
|---|---|---|---|
| metals "Metals" | COPX | GOLD | https://en.wikipedia.org/wiki/Gold_as_an_investment |
| | | SILVER | https://en.wikipedia.org/wiki/Silver_as_an_investment |
| | | COPPER | https://en.wikipedia.org/wiki/Copper |
| | | COPX | https://www.globalxetfs.com/funds/copx/ |
| semis "Semiconductors" | SOXX | SOXL | https://www.direxion.com/product/daily-semiconductor-bull-bear-3x-etfs |
| | | XYZ:SKHX | https://en.wikipedia.org/wiki/SK_Hynix |
| | | XYZ:KIOXIA | https://en.wikipedia.org/wiki/Kioxia |
| | | XYZ:CXMT | https://en.wikipedia.org/wiki/ChangXin_Memory_Technologies |

8 assets, 19 calls (metals 15, semis 4) from @BobLoukas, @goodalexander and @Corbanu.

## Confirm before write — [outputs/bot_audit_sector_actions.jsonl](step30/outputs/bot_audit_sector_actions.jsonl)
Each change: owner command -> `tools/sectors.py <op>` preview (what changes, "nothing changes in any record, price or score", preview token = sha256(current file sha + new document)[:16]) -> owner taps Confirm -> the same argv with `--confirm <that token>` writes -> prerender. 10 previews, 10 confirms, every confirm token equals its preview token; then /sectors, /publish -> commit 05de224 (26 files). Telegram user / chat ids removed from the excerpt.
Refusals (tests below): unknown ticker, missing sector, untag of a non-member, duplicate sector id, non-https source, duplicate JSON keys, extra keys, a priced proxy, a stale preview (file changed after it) and an edited preview (different change, same token) all write nothing.

## Tests
- Fresh clone of main at 05de224, CI-pinned venv: guard history 139 commits / tree 2,807 files -> 0 hits; tests.test_guard 7 OK; tests.test_sectors 17 OK; full offline suite 360 OK; check_bundle OK; `sectors.py check` ok, 2 sectors; clone left clean: [outputs/fresh_clone_guard_and_tests.txt](step30/outputs/fresh_clone_guard_and_tests.txt).
- tests/sectors_test.js (Chromium, live site, after board.js / position.js render): 29 checks, 0 failures — every tagged leaderboard row (19), every tagged position page (19) keeps its sector section, sectors.html lists every call: [outputs/sectors_browser_test_live.txt](step30/outputs/sectors_browser_test_live.txt).
- Private bot: 105 OK (Sector: preview then confirm writes with the preview's token, cancel writes nothing, a confirm button works once, bad input runs nothing). The publish allow-list adds only data/sectors.json, web/sectors.html and web/data/sectors.json; 05de224 shows it in use..
- Caller pages (static): caller-bobloukas.html 14 metals tags, caller-corbanu.html 3 semis, caller-goodalexander.html 1 metals + 1 semis.

## Images
step30/leaderboard_tags.png, position_gold_sector.png, position_skhx_sector.png, caller_bobloukas_tags.png (score 46.3 unchanged), sectors_page.png, sectors_phone.png (390 px, no horizontal overflow). All taken from the live site.
