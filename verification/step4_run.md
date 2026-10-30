# Step 4 run notes: post-to-price resolver

Run 2026-10-30 ~16:11 UTC from the repo root on Linux. Every command below was run in this order; output is raw (stdout + stderr), followed by its exit code. The `DOGEZ` run is the unknown-asset check and is expected to exit 1.

Parity uses the saved step 3 price snapshot `data/hourly_prices.json` (unchanged since commit b96275a, sha256 `3bef0c723eae4bf599a39ba28867061f1b2579a0c69ed7fb2461486eca5c14fb`) and compares with `==`, no tolerance. The two `records/live` runs fetch live prices, so their `latest` values and newly reached horizons are as of this run.

```text
$ python3 --version
Python 3.12.3
[exit 0]
$ python3 -c "import importlib.metadata as m; print('jsonschema', m.version('jsonschema'))"
jsonschema 4.10.3
[exit 0]
$ python3 resolve.py --url https://x.com/BobLoukas/status/2112919830357577753 --asset BTC --side long --out records/live
2112919830357577753 BTC      partial  posted 2026-10-21T14:51:58Z entry 84575.71 @ 2026-10-21T15:00:00Z | since post -8.22% | 1d -3.18% 7d -4.70% 30d unresolved
1 records, schema-valid 1/1, 0 duplicates, 0 errors
[exit 0]
$ python3 resolve.py --receipt sources/bobloukas/receipts/2113613893662588966.json --asset SILVER --side short --out records/live
2113613893662588966 SILVER   partial  posted 2026-10-23T12:49:55Z entry 53.84 @ 2026-10-23T13:00:00Z | since post -8.53% | 1d +0.73% 7d -7.02% 30d unresolved
1 records, schema-valid 1/1, 0 duplicates, 0 errors
[exit 0]
$ python3 resolve.py --url https://x.com/BobLoukas/status/2113613893662588966 --asset DOGEZ
ERROR item 0: unknown asset 'DOGEZ': known BTC, COPPER, COPX, ETH, GOLD, LINK, OIL, QQQ, SILVER, SOL, SPY, STOCKS; or pass binance:<PAIR> / yahoo:<TICKER>
0 records, schema-valid 0/0, 0 duplicates, 1 errors
[exit 1]
$ python3 parity.py
EXACT 2094827036812435935 BTC    call        entry 77596.01 @ 2026-09-01T17:00:00Z | 1d -0.55% 7d +1.47% 30d +8.51%
EXACT 2097324043334451439 COPX   call        entry 95.31 @ 2026-09-08T14:30:00Z | 1d +0.22% 7d -11.56% 30d -12.54%
EXACT 2100953898630443447 BTC    call        entry 80937.83 @ 2026-09-18T15:00:00Z | 1d +0.80% 7d +3.80% 30d +0.20%
EXACT 2102014028855820403 BTC    reiteration entry 85323.0 @ 2026-09-21T13:00:00Z | 1d +0.82% 7d -2.04% 30d -2.13%
EXACT 2102024327075877097 BTC    reiteration entry 85466.35 @ 2026-09-21T14:00:00Z | 1d +1.03% 7d -2.13% 30d -1.92%
EXACT 2104977267109896477 SILVER call        entry 61.105 @ 2026-09-29T17:00:00Z | 1d +0.83% 7d -0.80% 30d unresolved
EXACT 2105699317004583026 BTC    call        entry 84202.0 @ 2026-10-01T17:00:00Z | 1d +1.14% 7d -3.86% 30d unresolved
EXACT 2106744910896312646 SILVER reiteration entry 61.06 @ 2026-10-04T22:00:00Z | 1d -0.57% 7d -0.27% 30d unresolved
EXACT 2106750657877434407 COPX   call        entry 86.0 @ 2026-10-05T13:30:00Z | 1d -0.33% 7d -0.83% 30d unresolved
EXACT 2107063137958564197 STOCKS call        entry 769.69 @ 2026-10-05T13:30:00Z | 1d +1.10% 7d +1.18% 30d unresolved
EXACT 2107475725573906895 STOCKS reiteration entry 778.85 @ 2026-10-06T14:30:00Z | 1d -0.56% 7d -0.17% 30d unresolved
EXACT 2110764348981612915 BTC    call        entry 82108.01 @ 2026-10-15T17:00:00Z | 1d -0.82% 7d -1.00% 30d unresolved
EXACT 2112915214479798344 BTC    reiteration entry 84575.71 @ 2026-10-21T15:00:00Z | 1d -3.18% 7d -4.70% 30d unresolved
EXACT 2112919830357577753 BTC    reiteration entry 84575.71 @ 2026-10-21T15:00:00Z | 1d -3.18% 7d -4.70% 30d unresolved
EXACT 2112919830357577753 GOLD   call        entry 4148.5 @ 2026-10-21T15:00:00Z | 1d +1.78% 7d +2.27% 30d unresolved
EXACT 2113613893662588966 SILVER call        entry 53.84 @ 2026-10-23T13:00:00Z | 1d -0.73% 7d unresolved 30d unresolved
parity: 16/16 exact, 16 records schema-valid, 0 duplicates, 0 errors
[exit 0]
$ python3 -m unittest -v tests.test_resolve
test_bad_url_and_bad_side (tests.test_resolve.Resolver.test_bad_url_and_bad_side) ... ok
test_duplicate_post_kept_once (tests.test_resolve.Resolver.test_duplicate_post_kept_once) ... ok
test_empty_series_is_pending (tests.test_resolve.Resolver.test_empty_series_is_pending) ... ok
test_entry_is_first_bar_at_or_after_post (tests.test_resolve.Resolver.test_entry_is_first_bar_at_or_after_post) ... ok
test_exit_in_long_closure_is_unresolved (tests.test_resolve.Resolver.test_exit_in_long_closure_is_unresolved) ... ok
test_friday_evening_post_has_no_entry_under_the_2_day_rule (tests.test_resolve.Resolver.test_friday_evening_post_has_no_entry_under_the_2_day_rule) ... ok
test_long_closure_gives_no_entry (tests.test_resolve.Resolver.test_long_closure_gives_no_entry) ... ok
test_post_exactly_on_a_bar_uses_that_bar (tests.test_resolve.Resolver.test_post_exactly_on_a_bar_uses_that_bar) ... ok
test_post_newer_than_last_bar_is_pending (tests.test_resolve.Resolver.test_post_newer_than_last_bar_is_pending) ... ok
test_prefixed_asset_missing_from_snapshot (tests.test_resolve.Resolver.test_prefixed_asset_missing_from_snapshot) ... ok
test_receipt_and_url_must_agree (tests.test_resolve.Resolver.test_receipt_and_url_must_agree) ... ok
test_rerun_writes_identical_bytes (tests.test_resolve.Resolver.test_rerun_writes_identical_bytes) ... ok
test_same_post_two_assets_is_not_a_duplicate (tests.test_resolve.Resolver.test_same_post_two_assets_is_not_a_duplicate) ... ok
test_saturday_post_enters_monday_open_within_2_days (tests.test_resolve.Resolver.test_saturday_post_enters_monday_open_within_2_days) ... ok
test_schema_rejects_a_broken_record (tests.test_resolve.Resolver.test_schema_rejects_a_broken_record) ... ok
test_snowflake_matches_every_saved_receipt (tests.test_resolve.Resolver.test_snowflake_matches_every_saved_receipt) ... ok
test_unknown_asset_in_batch_reports_error_and_keeps_others (tests.test_resolve.Resolver.test_unknown_asset_in_batch_reports_error_and_keeps_others) ... ok
test_unknown_asset_is_a_clear_error (tests.test_resolve.Resolver.test_unknown_asset_is_a_clear_error) ... ok
test_unreached_horizons_are_unresolved_not_guessed (tests.test_resolve.Resolver.test_unreached_horizons_are_unresolved_not_guessed) ... ok
test_weekend_post_enters_at_monday_open (tests.test_resolve.Resolver.test_weekend_post_enters_at_monday_open) ... ok

----------------------------------------------------------------------
Ran 20 tests in 0.133s

OK
[exit 0]
$ python3 validate_records.py
records: 18 checked against post_price.v1 -> ALL VALID
[exit 0]
```

## SHA-256: generated files

```text
580a7fb57c889d0eccea3b88c12766c2012eeb1ce52e8660d44096326c7d6cd4  data/parity_bobloukas.json
78a4c201683ffb0701d02f495905162ee8843d18d65526535c2449ba82fecf64  records/bobloukas/2094827036812435935_BTC.json
265ca36ae2cb04c24f638cde7e851cf7fb7ae0a84065476779cb85dac2327b4f  records/bobloukas/2097324043334451439_COPX.json
0138c693b7f35f613c9309079e6e039aad89dcbcc6c9f84609512126d945093f  records/bobloukas/2100953898630443447_BTC.json
c90fcf52ba73834225ff3a9a3f3d1ede8dce83ae98cfd41c4b2790431ced61b3  records/bobloukas/2102014028855820403_BTC.json
dd802aaa6c032f07c63decc99356a71e893effe149cd5f899816a463e06b488d  records/bobloukas/2102024327075877097_BTC.json
2f7dcf85795447d841f4e589e79d90ac5f13ef71a58d08dae8ed6adf5429d395  records/bobloukas/2104977267109896477_SILVER.json
4561d6a2eb676a7dc0873eae4937764c9f8798b70b53285e34e0e17e3c365ca4  records/bobloukas/2105699317004583026_BTC.json
bd41593dbccf249dd0a2ececff8c9fae6ed15510d1e5f1c40220cbaa6c7359e7  records/bobloukas/2106744910896312646_SILVER.json
74189bfb17be516b013d21c88b37508de060d7c82ef5dee73c772a4131afbbd6  records/bobloukas/2106750657877434407_COPX.json
74471c0514e0395e3e9a4c0fd870522c437ef8c2625cb7bca7fcccd6ed37f3b5  records/bobloukas/2107063137958564197_STOCKS.json
ea78ec71192245da8d58dff05c8e762c064c743cfa797fc029c1ffdf0b581a53  records/bobloukas/2107475725573906895_STOCKS.json
bc74dc5ae2ef397816aad0a9a0c2ee64166277200464398f8b6e3e47e7331393  records/bobloukas/2110764348981612915_BTC.json
ac92b56a96001b5991e92ae09f41a23f0c3d5448dfd1250754f14c1bedf15e18  records/bobloukas/2112915214479798344_BTC.json
16f3d253bbda38355d4fc1454bbd20726320bca074d4bb0fcdabd4d571cb21bf  records/bobloukas/2112919830357577753_BTC.json
b19b7e1a1d47d118aafa76279eef03321f1be4ab4b3b75ffb5ebdd7addd39f94  records/bobloukas/2112919830357577753_GOLD.json
9062c07fce6cb6c1ae0272c64e21ef1a9e269be7084a18e4af67c5a9a44033d2  records/bobloukas/2113613893662588966_SILVER.json
ceb9a1cd871f9a0e88ed7fcfac779bce19d316b47cfd13c451223c216e5fed45  records/live/2112919830357577753_BTC.json
30ad6ae8c75744fa0a0b68644fa90dc9dd40dfebb795c066f0035b0200e10283  records/live/2113613893662588966_SILVER.json
```

## SHA-256: code, schema and inputs

```text
143250809503faea7dc170978424b3ccb3ef810f14a2d0f95d8e322176265bbd  resolve.py
e00ff422ddc969e8706451dc74ba6faa76817d5d98dcb45944c0f468cd9d2bc0  parity.py
569a44a3e13c19a22f109ad06db285592ed90c5e54517d59820c3ec258e18e7a  validate_records.py
f383e578c2af020a9be45f8df1aa55b2253963fa7fe9ac7f3182408c3f95e8ac  schema/post_price.v1.json
3017fa69db2df563438e92a57890259ceccfc5ed83a70efe6935852c19db0ab1  tests/test_resolve.py
3bef0c723eae4bf599a39ba28867061f1b2579a0c69ed7fb2461486eca5c14fb  data/hourly_prices.json
2d4960a8731e2975106d2110c4ea8a8284fe885c7e320ea860b18104841e7e27  data/bobloukas_calls.json
a9f3422e1620716ff3b2b75ec0bdd0f6f697f1db8c29a98cbe753be753e11fa5  sources/bobloukas/labels.json
```
