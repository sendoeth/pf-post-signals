# Step 27 run: owner corrections become labels, agreement, gated rules

Code + first labels: 048a4785085fd97752ff790c8ae3be97e87b8631. Served: aadafaeeefc7cc3621cf2f10096beaa96d725cc8 (the bot's publish of the live-captured skip label; CI guard success, pages success after a transient GitHub deploy cancel was re-requested).
Compare: https://github.com/sendoeth/pf-post-signals/compare/541567abd67234b0865c42b2ccf81af9e247292a...aadafaeeefc7cc3621cf2f10096beaa96d725cc8
Live: https://sendoeth.com/pf-post-signals/web/agreement.html (+ web/data/agreement.json)
Served = commit: agreement.html 6695855bafec4772c6e1b5928dbb4261f0360d2a0b74f4e6dba6b16514220452, agreement.json 74310c68a038c3527fa0e24e56694b23d0f13ab96eb042b1718fa611f13c86f6, data/labels.json f3de0c57aebba3f83f8c68a59156ccce32a0103a13825164db28cdb7b8379799, data/rules.json c7f52f56a3ab225d027ed3ee9f36a328b78799dd83cc76e3cd9b1ce37b9ad994, web/data/charts.json ef9205c629c8b40f894c5c53417880fe0d13194254f77b1320f74584feda1ccf (= before step 27: scores unchanged).

Pinned: [data/labels.json](https://raw.githubusercontent.com/sendoeth/pf-post-signals/aadafaeeefc7cc3621cf2f10096beaa96d725cc8/data/labels.json) · [data/rules.json](https://raw.githubusercontent.com/sendoeth/pf-post-signals/aadafaeeefc7cc3621cf2f10096beaa96d725cc8/data/rules.json) · [web/data/agreement.json](https://raw.githubusercontent.com/sendoeth/pf-post-signals/aadafaeeefc7cc3621cf2f10096beaa96d725cc8/web/data/agreement.json) · [tools/labels.py](https://raw.githubusercontent.com/sendoeth/pf-post-signals/aadafaeeefc7cc3621cf2f10096beaa96d725cc8/tools/labels.py) · [tools/reader.py](https://raw.githubusercontent.com/sendoeth/pf-post-signals/aadafaeeefc7cc3621cf2f10096beaa96d725cc8/tools/reader.py) · [tests/test_labels.py](https://raw.githubusercontent.com/sendoeth/pf-post-signals/aadafaeeefc7cc3621cf2f10096beaa96d725cc8/tests/test_labels.py)

## Labels by source
69 labels; source mentions record 51, scan 26, watcher 5 (a label can have several); 58 count for agreement.
Kinds: side_added 30, agree 20, skip_repeat_or_other 8, agree_no_side 6, skipped without a stated reason 2, false_call 1, side_flipped 1, add_refused 1.

## Agreement before / after
base reader 26/58 (44.8%) -> with the kept rules 31/58 (53.4%). Per caller: BobLoukas 15/42 -> 18/42, koolkrypto223 2/4 -> 4/4, goodalexander 4/7, others unchanged. Per kind: side_added 0/30 -> 5/30; every other kind unchanged.

## Gate output (every candidate) — [outputs/gate_output.txt](step27/outputs/gate_output.txt)
```
KEPT     more_cashtag         26/58 -> 28/58  fixed ['2118181656398090718|KNTQ', '2118181656398090718|NEST']  worsened -  fires on ['2118181656398090718|KNTQ', '2118181656398090718|NEST']  (agreement 26/58 -> 28/58, no label worse)  code 18ef061dbd15
KEPT     positioned_side      28/58 -> 29/58  fixed ['2022006665764082140|STOCKS']  worsened -  fires on ['2022006665764082140|STOCKS']  (agreement 28/58 -> 29/58, no label worse)  code 82ba7a33e520
KEPT     picking_up_quantity  29/58 -> 30/58  fixed ['2062277523288068152|BTC']  worsened -  fires on ['2062277523288068152|BTC']  (agreement 29/58 -> 30/58, no label worse)  code d39ad460d155
REJECTED bullish_anywhere     30/58 -> 31/58  fixed ['2106750657877434407|COPX', '2107475725573906895|STOCKS']  worsened ['2091161059801391206|-']  fires on ['2091161059801391206|-', '2106750657877434407|COPX', '2107475725573906895|STOCKS']  (1 label(s) that agreed would disagree)  code 559f1caf1b25
KEPT     targeting_price      30/58 -> 31/58  fixed ['2011105173104705981|GOLD']  worsened -  fires on ['1995532011818106902|-', '2011105173104705981|GOLD']  (agreement 30/58 -> 31/58, no label worse)  code 2560bf13ffcf
kept: ['more_cashtag', 'positioned_side', 'picking_up_quantity', 'targeting_price']; labels_sha256 c285e83a578bd54d5c2db451146ad0c02e36bc3c003eabfabfe20a8514285640; label_count 69
```

## Labels whose reads changed — [outputs/labels_changed_by_rules.txt](step27/outputs/labels_changed_by_rules.txt)
```
1995532011818106902|- @BobLoukas skip_repeat_or_other gating=False: base none -> now long (rule targeting_price: 'targeting $80.') owner skip  :: “Silver back in a runaway, lockout move. The recent 6 week pause the midpoint of the total move, targeting $80.”
2011105173104705981|GOLD @BobLoukas side_added gating=True: base none -> now long (rule targeting_price: 'targeting $5,800') owner add long :: “Formidable, but controlled appetite for gold remains. Now targeting $5,800 for this (maybe) new cycle. Just go”
2022006665764082140|STOCKS @BobLoukas side_added gating=True: base none -> now long (rule positioned_side: 'positioned on the bull side') owner add long :: “Week 12 for Stocks, in the middle of the Cycle. Still leaning and positioned on the bull side as it holds the ”
2062277523288068152|BTC @BobLoukas side_added gating=True: base none -> now long (rule picking_up_quantity: 'Picking up 10BTC') owner add long :: “The Bitcoin 4 Year Cycle Journey ‘Model Portfolio’ has made its first buy in 3.5yrs. Picking up 10BTC at $65,0”
2118181656398090718|KNTQ @koolkrypto223 side_added gating=True: base none -> now long (rule more_cashtag: 'More $NEST and $KNTQ') owner add long :: “More $NEST and $KNTQ”
2118181656398090718|NEST @koolkrypto223 side_added gating=True: base none -> now long (rule more_cashtag: 'More $NEST') owner add long :: “More $NEST and $KNTQ”
```
(the first is a repeat skip: not counted; the rule's read is right but the owner skipped it as a repeat)

## The koolkrypto223 NEST and KNTQ labels — [outputs/labels_koolkrypto223_NEST_KNTQ.json](step27/outputs/labels_koolkrypto223_NEST_KNTQ.json)
first read from the watcher card (side none) -> owner add LONG (changed, reason "reply to 0xLcrgs portfolio screenshot (BTC 94.9%, NEST 0.6%, no KNTQ): \"More $NEST and $KNTQ\" = add both"), NEST asset_pick nest-2; sources: the record + the watcher card copy; pins NEST 73aaf78571fffa9517c5e562199c574415408c068c401293d6ef202b0f79ea80, KNTQ 2b01dd68f2f53c737028f89bdecfc22ee2aefdb9eea77f0090c718b979d5c1ea. Base reader: none; with more_cashtag: long.

## Live capture (bot)
2026-11-06 16:18:23Z watch_button skip 2118727055173091775 -> tools/labels.py build: "labels: 69 (1 new) / NEW 2118727055173091775|- @Okada_DeFi0x skipped (no stated reason to read it as no side): reader none -> owner skip (watcher)" -> report "agreement: base 26/58, with kept rules 31/58; 69 labels" -> /publish 4 files (scores unchanged) -> aadafaeeefc7cc3621cf2f10096beaa96d725cc8. Image: step27/bot_skip_captured_and_published.png.

## Tests (fresh clone of aadafaeeefc7cc3621cf2f10096beaa96d725cc8, [outputs/fresh_clone_guard_and_tests.txt](step27/outputs/fresh_clone_guard_and_tests.txt))
guard history 109 commits 0 hits, tree 2677 files 0 hits, test_guard OK; tests.test_labels 20 OK (every label a regression subTest; pins; stable rebuild; accepted-as-read = base reader; NEST/KNTQ; gate keep/reject; skip basis; binding off on edited code / edited labels / unverified labels / breaking label; tamper + conflicting sources + different texts stop the build; scores unchanged); add_call + watch + spot_dex 54 OK; full 303 OK (2 skipped); check_bundle ALL MATCH; the gate re-run in the clone gives the same decisions. Private bot 82 OK (capture after add / batch add / skip, conflicts reported, publish allows only the 4 label files).

## Review
Codex: design WITHHOLD (skip != no side, provenance, rule binding) -> implementation WITHHOLD (pins trusted, function-only code hash, silent text merge, substring skip basis) -> fixed with tests -> GO.

## Images
step27/agreement_top.png, agreement_gate.png, agreement_full.png (live), bot_skip_captured_and_published.png (bot).
