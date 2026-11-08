# Step 29 run: replies read with the post they answer (reply context, images included)

Code: 7f5a53a794823b9697e46dab113f9ee7994a6c48 (step 29) + 890a106 (position pages keep the context after the page script renders) + e2fa88e / b2d1cca (phone width). CI guard + pages success on each.
Live: https://sendoeth.com/pf-post-signals/web/context.html (reader page) · position page https://sendoeth.com/pf-post-signals/web/pos-2118181656398090718_NEST.html (section "Reply context") · data web/data/context.json.
Scores unchanged: charts.json 8bdf9a369ed31953c85a5209ff83850ca862079dbbe068cb1d11b826829263da before step 29 (195642c) = after (served).

## Context, agreement, acceptance case, fail-closed cases — [outputs/context_summary.txt](step29/outputs/context_summary.txt)
27 stored contexts: 25 complete, 1 truncated (more than 4 parents: no root claimed; the direct parent still counts), 1 unavailable (the parent was deleted by its author: no candidates).
Agreement on the owner's labels (step 27): asset found 48 -> 50 of 51 added calls (BTC from @aBlock0's text, SOXL from @based16z's chart image); side agreement 31 -> 31 of 58 (context never sets a side).
Acceptance @koolkrypto223 "More $NEST and $KNTQ" (2118181656398090718): parent @0xLcrgs portfolio post, its image sha256 a1a1c4d3… OCR "NEST 0.60%" -> NEST from parent_image; KNTQ only from the caller's own words (the portfolio holds none); both long from "More" (kept rule more_cashtag, the caller's words); ETH / HYPE context-only -> side none ("the caller names other assets").
Potential callers: 14, all "potential (unscored, pending owner promotion)"; none is in the ratings.

## Bot (Telegram) — step29/bot_context_and_potential.png
/context on the koolkrypto223 reply: "replying to @0xLcrgs: rate my portfolio… [1 image(s)]", thread start link, "context assets (never a side): ETH (parent image, root image), HYPE (parent image, parent text), NEST (parent image)", NEST long [own words + parent image], KNTQ long, reply + original post links. /potential: the 14 accounts, unscored.

## Tests
- tests/test_context.py: 33 (bounds, failures, pins incl. OCR text and receipt bytes, deadline after every fetch and download, sides only from own words, acceptance, deleted parent, score-neutral, deterministic page, file-order independent, promotion scores nothing, every reply page shows its context).
- tests/context_test.js (Chromium): red on the first deploy (24 pages lost the section when position.js rendered), green after 890a106: [outputs/context_browser_test_live.txt](step29/outputs/context_browser_test_live.txt).
- Private bot: 99 OK (cards with context, failure note, flagged context legs, /context, /potential, /promote, publish allow-list).
- Fresh clone with the guard: [outputs/fresh_clone_guard_and_tests.txt](step29/outputs/fresh_clone_guard_and_tests.txt).

## Review
Codex: design WITHHOLD (per-asset side evidence, partial-context rejection, pins, bounds) -> implementation WITHHOLD (unpinned OCR, receipt fields, deadline, file order) -> WITHHOLD (deadline after the caller fetch and downloads) -> GO.

## Images
step29/context_top.png, context_agreement.png, context_potential_callers.png, context_nest_kntq.png, context_soxl.png, context_deleted_parent.png, context_phone.png, position_nest_reply_context.png (live), bot_context_and_potential.png (Telegram).
