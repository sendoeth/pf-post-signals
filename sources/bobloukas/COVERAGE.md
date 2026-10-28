# @BobLoukas capture coverage (2026-10-28)

Read-only X search through a logged-in browser profile (no posting, liking or following). X returns
at most ~60 posts per search, newest first, so the window was captured in date slices and every
slice whose oldest post was later than its start was re-queried with a narrower slice.

| Query | Own posts | Oldest | Newest |
|---|---|---|---|
| from:BobLoukas since:2026-09-01 | 59 | 2026-10-15 | 2026-10-28 |
| from:BobLoukas since:2026-09-01 until:2026-09-16 | 38 | 2026-09-01 | 2026-09-15 |
| from:BobLoukas since:2026-09-16 until:2026-10-01 | 59 | 2026-09-18 | 2026-10-01 |
| from:BobLoukas since:2026-10-01 until:2026-10-16 | 60 | 2026-10-05 | 2026-10-16 |
| from:BobLoukas since:2026-09-16 until:2026-09-18 (refill) | 8 | 2026-09-15 | 2026-09-18 |
| from:BobLoukas since:2026-10-01 until:2026-10-05 (refill) | 57 | 2026-10-01 12:52 | 2026-10-05 |

260 unique own posts (originals and replies). Each is stored verbatim in `receipts/<post id>.json`
(id, url, postedAt, capturedAt, text, replyTo, metrics) with its X URL as the canonical source.
`posts_index.json` lists all 260 and marks the 59 keyword candidates that were labelled.
Known gap: 2026-10-01 00:00-12:52 UTC was not covered by a slice below the cap.
