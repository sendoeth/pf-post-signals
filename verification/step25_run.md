# Step 25 run: caller watcher with owner-only Telegram review

Code: `8cfb12bb2b95ec6a59d49c9da2d9937e7b59f666` (watcher, tests, systemd units), `afd26f23c9586116a81c121509507eddb8607f9b` (report fix + the 24-hour evidence); this file and the images are in the commit after it.
Compare: https://github.com/sendoeth/pf-post-signals/compare/d738a278c6142390fd980d609cbc1adc52595b0a...afd26f23c9586116a81c121509507eddb8607f9b
The watcher changes nothing public: web/data/charts.json is untouched by it (every addition still goes through the owner's /add and /publish).

## Code (pinned)
- [tools/watch_callers.py](https://raw.githubusercontent.com/sendoeth/pf-post-signals/afd26f23c9586116a81c121509507eddb8607f9b/tools/watch_callers.py), [tests/test_watch.py](https://raw.githubusercontent.com/sendoeth/pf-post-signals/afd26f23c9586116a81c121509507eddb8607f9b/tests/test_watch.py), [deploy/systemd/quanty-watch.service](https://raw.githubusercontent.com/sendoeth/pf-post-signals/afd26f23c9586116a81c121509507eddb8607f9b/deploy/systemd/quanty-watch.service), [deploy/systemd/quanty-watch.timer](https://raw.githubusercontent.com/sendoeth/pf-post-signals/afd26f23c9586116a81c121509507eddb8607f9b/deploy/systemd/quanty-watch.timer)
- the private admin bot (cards, buttons) is not in the repository: its test run is [outputs/bot_tests.txt](step25/outputs/bot_tests.txt)

## Live run: 2026-11-05 13:05:08Z .. 2026-11-06 13:06:43Z (145 cycles, every 10 minutes)
| | |
|---|---|
| results | 1 baseline, 128 ok, 15 weak (coverage not advanced), 1 throttled (14:55:58Z, canary 0: nothing marked) |
| searches per hour | 6 normally, 9-12 while X degraded; max 12 = the budget; every search reserved before it ran ([budget.jsonl](step25/outputs/budget.jsonl), 167 reservations) |
| open gaps at the end | 0 (after both degraded spells the next strong answer reached back past the last covered time) |
| candidates / cards | 38 / 38, each sent once |
| post -> card (real time) | 34 cards: min 47 s, median 335 s, max 632 s; all within 11 minutes |
| cards for posts from before the start | 4 (8-11 h old posts a deeper second answer reached; not counted as latency) |
| owner decisions | Add on @koolkrypto223 2118167587637096933 (2026-11-05 13:27:50Z), Skip on @rosa_onchain 2118672055420039460 (2026-11-06 13:53:16Z) |

Degraded spells, fail closed: 14:45Z weak (20 posts vs usual 120, canary 0) and 14:55Z throttled (0 posts, canary 0); 00:46Z-02:26Z X capped every answer at 20 posts (canary 20 of usual 60): the posts were read and carded (@koolkrypto223 01:02Z -> card 01:06Z) but coverage only advanced when answers were strong again.

Files: [cycles.jsonl](step25/outputs/cycles.jsonl) (every cycle with query, harness run id, manifest sha256, counts, strength, canary, coverage), [candidates.jsonl](step25/outputs/candidates.jsonl), [cards_log.json](step25/outputs/cards_log.json), [report.json](step25/outputs/report.json).

## No ownerless publishing; Add = the exact URL's /add preview
[bot_audit_buttons.jsonl](step25/outputs/bot_audit_buttons.jsonl), from the bot's audit log:
```
2026-11-05T13:27:50Z watch_button add post 2118167587637096933
2026-11-05T13:27:53Z tool ["python3", "tools/add_call.py", "https://x.com/koolkrypto223/status/2118167587637096933"] code 2 "REFUSED the coin(s) of this post could not be confirmed (nothing guessed) / REVIEW $KNTQ: no trading venue with hourly bars agrees with Kinetiq's price"
```
The preview only (no --add); its own single-use Add button would add, /publish would push. The watcher never runs git. Tests: test_add_opens_the_normal_preview_for_the_exact_url_and_publishes_nothing, test_strangers_cannot_press_card_buttons, test_unknown_or_forged_card_does_nothing.

## Classifier replay of the 2026-11-05 posts ([classifier_replay_2026-11-05.jsonl](step25/outputs/classifier_replay_2026-11-05.jsonl), public embed)
```
blknoiz06     2026-11-05T10:39:35Z post   parent None                                  GOLD long ('bought gold')       candidate
goodalexander 2026-11-05T11:36:43Z reply  parent reply 2118292132876480727 @blknoiz06 SILVER none (no side stated)    candidate
blknoiz06     2026-11-05T11:56:18Z reply  parent reply 2118306510908596565 @goodalexander SILVER long ('bought silver') candidate
```
Context chain: [context_2118311442441241038.txt](step25/outputs/context_2118311442441241038.txt).

## Cards as text ([cards_as_text.txt](step25/outputs/cards_as_text.txt))
```
👀 New post by @mert (reply · replying to @danheld)
2026-11-06 11:11:56 UTC

unencrypted zcash mentioned

• ZEC: side none

🔗 https://x.com/mert/status/2118662663442178485
↩ original post (@danheld): https://x.com/danheld/status/2118659756323713291
found 4 min after posting · card now
[➕ Add (preview)] [⏭ Skip] [🧵 Context]          sent 11:17:20Z, post-to-card 325 s
```

## Tests (fresh clone of afd26f2, [fresh_clone_guard_and_tests.txt](step25/outputs/fresh_clone_guard_and_tests.txt))
guard history 99 commits 0 hits, tree 2633 files 0 hits, test_guard OK, tests.test_watch 19 OK, full suite 258 OK (2 skipped), check_bundle ALL MATCH; private bot 62 OK (11 watcher tests).
Proven: exactly-once discovery (test_a_new_post_is_found_exactly_once), duplicates (test_reposts_recorded_calls_and_chatter_make_no_card), fail-closed throttling and errors (test_a_throttled_cycle_marks_nothing_and_the_post_is_found_later, test_a_search_error_marks_nothing, test_a_weak_answer_does_not_advance_coverage), gaps (test_a_burst_that_pushes_posts_out_is_caught_up_per_caller, test_a_partial_catch_up_answer_never_closes_a_window), parent retention, reposts ignored, the reserved budget, one cycle at a time, crash ordering, torn lines.

## Review
Codex (bridge): design WITHHOLD (partial answers, catch-up stall, crash races, budget) -> implementation WITHHOLD x3 (partial catch-up, weak forever, stale instance, torn JSONL incl. UTF-8) -> GO; card-link delta GO.

## Images (bot, committed)
- step25/bot_cards_realtime_and_skip.png sha256 7877acedac3134f82083f87e4eb5aab365bafacbdbe5c957290918f51fa80b53: three real-time cards (7, 5, 4 min) incl. the original-post link, and "⏭ Skipped @rosa_onchain 2118672055420039460. It will not be shown again."
- step25/bot_context_add_preview_refusal.png sha256 3339d4db719bfeb92982f79d5e239000c04a86fe993a5aa1a9283aefb36017ab: the Context chain, Add -> "Reading the post…" (the /add preview) -> "Not added … nothing guessed" (KNTQ)
