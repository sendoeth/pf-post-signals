# Step 21 run notes: transcript-to-thesis episodes through the private bot

## Live
- Episode page: https://sendoeth.com/pf-post-signals/web/episode-forward-guidance-2026-10-30.html
- Episodes index: https://sendoeth.com/pf-post-signals/web/episodes.html
- Asset chart with episode bubbles: https://sendoeth.com/pf-post-signals/web/chart.html?asset=GOLD (also `?asset=OIL`, `?asset=SEMIS`, `?asset=BTC`)
- Leaderboard: https://sendoeth.com/pf-post-signals/web/

## Served
- Served commit: `244509c3361e2896072d42f72d5dc2f75f7c776b` ("admin bot: publish 0 record(s), 1 episode(s)", pushed by the private bot's /publish)
- Compare (step 20 notes -> this publish): https://github.com/sendoeth/pf-post-signals/compare/4e24fc3...244509c
- sha256 of the served https://sendoeth.com/pf-post-signals/web/data/episodes.json = `93dc045fa3e375df474fb9b0223e899b487a9e6b3960eaf2e452849b66c9ea30` (same as `git show 244509c:web/data/episodes.json`)
- sha256 of the served https://sendoeth.com/pf-post-signals/web/data/charts.json = `bb89b9686696e24b56bd02bdc6f56e551b60e19159a46d5b7a1a6bf5bd9d5aaf`, byte-identical before and after the publish: the episode changed no caller score
- CI guard on 244509c: success (https://github.com/sendoeth/pf-post-signals/actions/runs/41328274490)

## Commits
| commit | what |
|---|---|
| 360d374 | episodes v1: parser, verifier, consolidation, priced static pages, thought bubbles |
| 5297a1d | episode bubbles on the asset charts, daily episode refresh (bars up to the episode frozen) |
| 6326566 | step 21 intake: LLM provider (fails closed), prompt v2, verify_extras, headline rule, prepare/stage bound by one sha256 |
| 6415111 | parser reads YouTube's stacked copy format too |
| 3967b81 | tests follow the published episode |
| 244509c | the Forward Guidance episode, published by the bot |

## How the episode got there (all through the private bot)
1. `/episode`, then the transcript uploaded as a .txt (YouTube's stacked copy: timestamp line, text line, chapter titles).
2. The bot parsed it (refuses any unreadable line): 566 segments, 13 chapters, 0:00-59:08, transcript sha256 `ad8a9647…c104`.
3. The details line `2026-10-30 | Forward Guidance (Blockworks) | The Fed Is A Sideshow While The AI Trade Implodes | Weekly Roundup | https://www.youtube.com/watch?v=StARUc1Lxrw`.
4. `tools/episode_intake.py prepare`: one request to anthropic/claude-opus-5.5 via OpenRouter with prompt `quanty.transcript.v2` (21,784 tokens in, 11,822 out, $0.32), every stance verified, a PRIVATE preview with the rejected stances and their reasons.
5. The single-use, expiring "Stage" button: `stage --expect-sha 99df797d…8e6b` copies exactly the previewed files (episode, extraction, verified and theses json, all four bound by that sha256) and builds the pages. Not public yet.
6. `/publish`: showed 7 files, "episodes: forward-guidance-2026-10-30", "scores: unchanged", ran the 5 checks (incl. tests.test_transcript), committed and pushed 244509c.

## The episode
- Transcript (private) sha256 `ad8a964714c8e71affdbf2aafe700979bc8da693a496fb07f61aacf0cb1bc104`; 566 segments, 13 chapters, 0:00-59:08
- Extraction sha256 `0341fe21070d862147b6ced0216422a2e1fa5483b77ccf252cb3b325b4818404`, response id `gen-1793550201-wC8GfQwZS7imfzN4ADaT`
- Stances: **31 accepted (7 calls, 24 thoughts), 0 rejected** (re-verified today against the private transcript: the same 31/0). The rejection paths (paraphrase, a quote more than 90s from its stamp, unknown asset, bad kind/direction/horizon, wrong transcript or prompt version) are covered by tests, see below.

| thesis | lean | moments |
|---|---|---|
| Bitcoin | call: wait / stand aside, later bullish | 54:42 55:26 55:32 55:50 55:57 56:34 57:10 57:41 |
| AI trade / semis (SMH) | call: bearish, later bullish | 19:57 27:14 28:40 32:50 37:31 38:11 38:11 39:08 |
| Gold | call: wait / stand aside, later bullish | **11:00** 17:46 18:10 18:16 18:52 19:06 19:13 |
| Oil (WTI) | call: bullish (long early-2027 expiries) | 7:25 41:07 41:44 42:15 42:33 |
| US dollar (DXY) | thought: bearish | 11:16 11:48 |
| US stocks (SPY) | thought: bearish | 7:25 |

**Gold at 10:55.** The example moment ("gold is probably getting hit here as you know the energy short nations are trying to defend currency. The dollar's been been super strong.") is the first gold moment. YouTube copies split lines differently: in the copy run through the bot, "…but uh I think" ends the 10:53 line and "gold is probably getting hit…" starts the 11:00 line, so the verifier stamps it 11:00; the same quote checked against the first copy of the transcript (sha256 `6dd3188e…`) starts at **10:55**. Both checks are in `verification/step21/outputs/episode_numbers.txt`. It is a thought (a reason gold falls, no position); the gold call is "step aside" (18:10, 19:06, 19:13), with "fundamentally good" (18:16) as the later bullish lean.

Calls vs thoughts: solid bubble = call (a position or telling listeners to act now), dashed ring = thought; the arrow is the direction. Episode stances are never rated: they live in web/data/episodes.json, not in the rating input.

## Tests (outputs in verification/step21/outputs/, sha256 below)
- Focused: tests.test_transcript + tests.test_episode_intake, 32 OK. Parser: glued and stacked formats, hour stamps, a duration that does not match its stamp, junk lines, a stamp without text, a glued line taken as another stamp's text, backwards time. Verifier: paraphrase, quote too far from its stamp, unknown asset, bad enums, wrong transcript sha, wrong prompt version. Provider: fails closed (bad JSON, no stances, cut off, HTTP error, network error), the key never in errors or output. Intake: preview private, stage refuses a changed preview (each of the four files tampered in turn), an empty episode never stages, metadata checks incl. a `javascript:` link. Pricing: last bar at or before the episode, bars up to it frozen on refresh, a failed fetch stops the job. Escaping: hostile title and links.
- All python tests: 175 OK. Browser (tests/episodes_test.js): ALL PASS (bubbles inside the plot at 1180 and 390px, cards, toggle, the chart without episodes.json, static pages with JS off).
- Live browser: the episode page at 1100 and 390px (6 theses, 31 moments: 7 calls, 24 thoughts, no overflow, notice present, link to the YouTube episode, 0 console errors); live charts GOLD/OIL/SEMIS/BTC each show the episode bubble and open its card (7 / 5 / 8 / 8 moments).
- Fresh clone of the public repo at 244509c: guard --history 69 commits 0 hits, --tree 2269 files 0 hits, no transcript or private/ file tracked, focused tests OK (the private re-verify skips: no transcript in a clone), an offline rebuild reproduces the published files byte for byte (git status clean).

## Private (fingerprints only; no bot source, transcript or keys are uploaded)
- quanty_admin.py sha256 `7e3993ff7323688684321a9707dc9a8459b1382000be4bca855442516bd821ee`
- tests/test_bot.py sha256 `9c95b04f45b3653912c3326fd2d67e5d921b4a4ad020f7a7ffc6de1a051fcdd1`: 47 OK (13 for /episode: upload and paste intake, preview with rejections, the key passed as a file never on argv, single-use and expiring stage button, the job lock, LLM failure stages nothing, the key redacted from messages and the audit log, /publish lists episode files and blocks anything else, titles containing "|")
- Bot service active since 2026-11-01 15:39:22 UTC (after the last bot change); the LLM key file is mode 600.
- Telegram screenshots (kept private, sha256 only; no ids or addresses visible in them):
  - `quanty episdode (2).png` `399c6d8d2f30adae58091a5f1751b9ad932c943166461484c96ff26efbfd87e7`: /episode, the .txt upload (60.6 KB), the parse reply (transcript sha256 ad8a9647…c104, 566 segments, 13 chapters, 0:00 -> 59:08)
  - `quanty episdode (3).png` `a809cf184e4c8458af3512d5a07d05729707dd016243b0c9743ce947920444c8`: the details line with the YouTube link, the progress message with the expected time, the private preview (31 accepted: 7 calls, 24 thoughts, 0 rejected; every thesis with its timestamps) and the single-use Stage / Drop buttons
  - `quanty episdode (1).png` `93fc060545c849c3ebe4019e6dabd84a7b425d605f4b3bc06d81c7c5b86b2369`: the stage reply (6 theses priced at the episode, web/data/episodes.json sha256 93dc045f…ea30, "nothing is public yet"), /publish (7 files, episodes: forward-guidance-2026-10-30, scores unchanged, charts.json bb89b968…), the 5 checks all passing and "Published 244509c3361e2896072d42f72d5dc2f75f7c776b"

## Output files
| file | sha256 |
|---|---|
| outputs/all_python_tests.txt | e62bbc6b436205d956b391fb199a0d02df6e82bee1d0b63e9e9f612f354a1ae8 |
| outputs/ci_guard.txt | bfc68c0234bc0a16ffe18d0a8f6d4a4456c246e66813b580e9ba5b1211bdda6c |
| outputs/episode_numbers.txt | 63164c111ce6e71974c32bd34d7bdbef76fe74b7b8a737b27e251953080a7c94 |
| outputs/episodes_browser_test.txt | f4291bf9d7ffcb82c3f5f3b66e7bbb0d34edfcf7a19d91ec1e5e68c579160d88 |
| outputs/focused_tests.txt | a2cd923c6872deb0e0ad30c43c0ba965efa3cdfac83a9a3f9728630b1a8aa4fa |
| outputs/fresh_clone.txt | 9305717995d243089d5c0f0b8f2841ee1bb1ee931eed1008fb14713ed89b5df2 |
| outputs/live_browser.txt | 8afc4252a02c20a8438da3c990f577514b5b3d41b61246fa31fb74d73f2f4fa9 |
| outputs/private_bot_fingerprints.txt | e6416548be9aa7eeb8e566f449263a0f9a62e7e68e8602182428ee1678b04ba1 |
| outputs/private_bot_tests.txt | 3779e69d2c38cfb995273bba235f2df15e0c2d00f4a5752e7905dda516fba6e4 |
| live_chart_gold.png | 9d12b053bb667338b372ccb579e52a49a25dfe6b7503e8ac4b18f7086186c7e3 |
| live_episode_desktop.png | 3c6dd8e49395dda5de577d3d69570c70e9f8f81380c5d5a2b2d1a9865c96fcfa |
| live_episode_phone.png | ade0c3d56c3e1c7b296cfef6e7282eded064a08a35abaf1676b8709db2605e89 |
| live_episodes_index.png | b5e902fba56942d805c29169cc3c494f601c159d5feed3b845f64e2f8dab4d55 |
