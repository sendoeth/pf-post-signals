"""Step 4 resolver tests (offline: synthetic bars via a price snapshot). Run: python3 -m unittest -v tests.test_resolve"""
import datetime as dt
import glob
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import resolve  # noqa: E402

V = resolve.validator()


def hourly(start, end, price=100.0, step=1.0, skip=lambda t: False):
    """[[iso, open]] every hour in [start, end), price rising by `step` per bar, minus skipped hours."""
    out, t, p = [], resolve.parse(start), price
    stop = resolve.parse(end)
    while t < stop:
        if not skip(t):
            out.append([t.strftime("%Y-%m-%dT%H:%M:%SZ"), p])
            p += step
        t += dt.timedelta(hours=1)
    return out


def read(path):
    with open(path, "rb") as f:
        return f.read()


def post_url(when, user="someone"):
    ms = int(resolve.parse(when).timestamp() * 1000) - resolve.TWITTER_EPOCH_MS
    return f"https://x.com/{user}/status/{ms << 22}"


def us_session(t):
    """True outside Mon-Fri 13:00-19:59 UTC (a stand-in for a stock market's hours)."""
    return t.weekday() >= 5 or not 13 <= t.hour < 20


class Resolver(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def snapshot(self, **series):
        path = os.path.join(self.tmp.name, "prices.json")
        with open(path, "w") as f:
            json.dump(series, f)
        return resolve.Prices(path)

    def one(self, item, prices):
        recs, dupes, errs = resolve.run([item], prices, v=V)
        self.assertEqual((dupes, errs), ([], []))
        self.assertEqual(len(recs), 1)
        return recs[0]

    # unknown assets
    def test_unknown_asset_is_a_clear_error(self):
        with self.assertRaisesRegex(resolve.UnknownAssetError, r"unknown asset 'DOGEZ'.*known BTC.*binance:<PAIR>"):
            resolve.asset_info("DOGEZ")
        with self.assertRaisesRegex(resolve.UnknownAssetError, "prefix must be"):
            resolve.asset_info("kraken:XBT")

    def test_unknown_asset_in_batch_reports_error_and_keeps_others(self):
        p = self.snapshot(BTC=hourly("2026-10-01T00:00:00Z", "2026-10-05T00:00:00Z"))
        url = post_url("2026-10-01T10:30:00Z")
        recs, dupes, errs = resolve.run([{"url": url, "asset": "NOPE"}, {"url": url, "asset": "BTC"}], p, v=V)
        self.assertEqual(len(recs), 1)
        self.assertEqual(len(errs), 1)
        self.assertIn("unknown asset 'NOPE'", errs[0])

    def test_prefixed_asset_missing_from_snapshot(self):
        p = self.snapshot(BTC=[])
        recs, _, errs = resolve.run([{"url": post_url("2026-10-01T00:00:00Z"), "asset": "yahoo:nvda"}], p, v=V)
        self.assertEqual(recs, [])
        self.assertIn("asset yahoo:NVDA not in price snapshot", errs[0])

    # entry rule + horizons
    def test_entry_is_first_bar_at_or_after_post(self):
        p = self.snapshot(BTC=hourly("2026-09-01T00:00:00Z", "2026-11-05T00:00:00Z"))
        r = self.one({"url": post_url("2026-09-01T10:30:00Z"), "asset": "btc", "side": "short"}, p)
        self.assertEqual(r["entry"], {"at": "2026-09-01T11:00:00Z", "price": 111.0})
        self.assertEqual(r["exits"]["1"]["at"], "2026-09-02T11:00:00Z")
        self.assertEqual(r["exits"]["30"]["at"], "2026-10-01T11:00:00Z")
        self.assertEqual(r["status"], "resolved")
        for h in ("1", "7", "30"):
            self.assertEqual(r["signed_returns"][h], -1 * (r["exits"][h]["price"] / 111.0 - 1))
            self.assertEqual(r["moves"][h], r["exits"][h]["price"] / 111.0 - 1)
        self.assertEqual(r["series"][0], ["2026-09-01T11:00:00Z", 111.0])
        self.assertEqual(r["latest"], {"at": r["series"][-1][0], "price": r["series"][-1][1]})

    def test_post_exactly_on_a_bar_uses_that_bar(self):
        p = self.snapshot(BTC=hourly("2026-09-01T00:00:00Z", "2026-09-03T00:00:00Z"))
        r = self.one({"url": post_url("2026-09-01T05:00:00Z"), "asset": "BTC"}, p)
        self.assertEqual(r["entry"]["at"], "2026-09-01T05:00:00Z")
        self.assertNotIn("signed_returns", r)

    def test_unreached_horizons_are_unresolved_not_guessed(self):
        p = self.snapshot(BTC=hourly("2026-10-20T00:00:00Z", "2026-10-29T00:00:00Z"))
        r = self.one({"url": post_url("2026-10-25T12:00:00Z"), "asset": "BTC", "side": "long"}, p)
        self.assertEqual(r["status"], "partial")
        self.assertIsNotNone(r["moves"]["1"])
        for h in ("7", "30"):
            self.assertIsNone(r["moves"][h])
            self.assertIsNone(r["exits"][h])
            self.assertIsNone(r["signed_returns"][h])
            self.assertEqual(r["unresolved"][h], "horizon not yet reached")

    # closed markets
    def test_weekend_post_enters_at_monday_open(self):
        p = self.snapshot(STOCKS=hourly("2026-09-01T00:00:00Z", "2026-11-10T00:00:00Z", skip=us_session))
        r = self.one({"url": post_url("2026-10-03T16:00:00Z"), "asset": "STOCKS"}, p)  # Saturday
        self.assertEqual(r["entry"]["at"], "2026-10-05T13:00:00Z")                      # Monday
        self.assertEqual(r["exits"]["1"]["at"], "2026-10-05T13:00:00Z")                 # Sunday target -> Monday
        self.assertEqual(r["status"], "resolved")

    def test_saturday_post_enters_monday_open_within_2_days(self):
        p = self.snapshot(STOCKS=hourly("2026-09-01T00:00:00Z", "2026-11-10T00:00:00Z", skip=us_session))
        r = self.one({"url": post_url("2026-10-03T13:30:00Z"), "asset": "STOCKS"}, p)  # Sat 13:30 -> Mon 13:00 = 1.98d
        self.assertEqual(r["entry"]["at"], "2026-10-05T13:00:00Z")

    def test_friday_evening_post_has_no_entry_under_the_2_day_rule(self):
        # known limitation, kept for step 3 parity: Fri 21:15 -> Mon 13:00 is 2.66 days
        p = self.snapshot(STOCKS=hourly("2026-09-01T00:00:00Z", "2026-11-10T00:00:00Z", skip=us_session))
        r = self.one({"url": post_url("2026-10-02T21:15:00Z"), "asset": "STOCKS"}, p)
        self.assertEqual(r["status"], "no_entry")
        self.assertEqual(r["unresolved"]["1"], "first bar 2026-10-05T13:00:00Z is >2 days after the post (market closed)")

    def test_long_closure_gives_no_entry(self):
        gap = lambda t: dt.datetime(2026, 10, 2, tzinfo=dt.timezone.utc) <= t < dt.datetime(2026, 10, 7, tzinfo=dt.timezone.utc)
        p = self.snapshot(GOLD=hourly("2026-09-01T00:00:00Z", "2026-11-10T00:00:00Z", skip=gap))
        r = self.one({"url": post_url("2026-10-02T09:00:00Z"), "asset": "GOLD", "side": "short"}, p)
        self.assertEqual(r["status"], "no_entry")
        self.assertIsNone(r["entry"])
        self.assertIsNone(r["change_since_post"])
        self.assertEqual(r["series"], [])
        self.assertEqual(set(r["unresolved"]), {"1", "7", "30"})
        self.assertIn("market closed", r["unresolved"]["1"])

    def test_exit_in_long_closure_is_unresolved(self):
        gap = lambda t: dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc) <= t < dt.datetime(2026, 10, 13, tzinfo=dt.timezone.utc)
        p = self.snapshot(GOLD=hourly("2026-09-01T00:00:00Z", "2026-11-10T00:00:00Z", skip=gap))
        r = self.one({"url": post_url("2026-10-01T09:00:00Z"), "asset": "GOLD"}, p)
        self.assertIsNone(r["exits"]["7"])
        self.assertIn("is >2 days after 2026-10-08T09:00:00Z (market closed)", r["unresolved"]["7"])
        self.assertIsNotNone(r["moves"]["30"])
        self.assertEqual(r["status"], "partial")

    # post newer than the last bar
    def test_post_newer_than_last_bar_is_pending(self):
        p = self.snapshot(BTC=hourly("2026-10-01T00:00:00Z", "2026-10-10T00:00:00Z"))
        r = self.one({"url": post_url("2026-10-12T08:00:00Z"), "asset": "BTC", "side": "long"}, p)
        self.assertEqual(r["status"], "pending")
        self.assertIsNone(r["entry"])
        self.assertIsNone(r["latest"])
        self.assertEqual(r["resolved_with"]["last_bar_at"], "2026-10-09T23:00:00Z")
        self.assertEqual(r["unresolved"]["30"], "no bar at or after the post yet")

    def test_empty_series_is_pending(self):
        r = self.one({"url": post_url("2026-10-12T08:00:00Z"), "asset": "BTC"}, self.snapshot(BTC=[]))
        self.assertEqual(r["status"], "pending")
        self.assertIsNone(r["resolved_with"]["last_bar_at"])

    # duplicates
    def test_duplicate_post_kept_once(self):
        p = self.snapshot(BTC=hourly("2026-10-01T00:00:00Z", "2026-10-05T00:00:00Z"))
        url = post_url("2026-10-01T10:30:00Z", "dup")
        out = os.path.join(self.tmp.name, "out")
        recs, dupes, errs = resolve.run([{"url": url, "asset": "BTC"}, {"url": url + "?s=20", "asset": "btc"}], p, out, V)
        self.assertEqual((len(recs), len(dupes), errs), (1, 1, []))
        self.assertIn("duplicate post", dupes[0])
        self.assertEqual(len(glob.glob(os.path.join(out, "*.json"))), 1)

    def test_same_post_two_assets_is_not_a_duplicate(self):
        p = self.snapshot(BTC=hourly("2026-10-01T00:00:00Z", "2026-10-05T00:00:00Z"),
                          GOLD=hourly("2026-10-01T00:00:00Z", "2026-10-05T00:00:00Z", price=4000))
        url = post_url("2026-10-01T10:30:00Z", "pair")
        recs, dupes, errs = resolve.run([{"url": url, "asset": "BTC", "side": "long"},
                                         {"url": url, "asset": "GOLD", "side": "short"}], p, v=V)
        self.assertEqual((len(recs), dupes, errs), (2, [], []))

    def test_rerun_writes_identical_bytes(self):
        p = self.snapshot(BTC=hourly("2026-10-01T00:00:00Z", "2026-10-05T00:00:00Z"))
        out = os.path.join(self.tmp.name, "out")
        item = [{"url": post_url("2026-10-01T10:30:00Z"), "asset": "BTC"}]
        resolve.run(item, p, out, V)
        first = {f: read(f) for f in glob.glob(os.path.join(out, "*.json"))}
        resolve.run(item, p, out, V)
        self.assertEqual(first, {f: read(f) for f in glob.glob(os.path.join(out, "*.json"))})

    # inputs
    def test_snowflake_matches_every_saved_receipt(self):
        files = glob.glob(os.path.join(HERE, "sources", "bobloukas", "receipts", "*.json"))
        self.assertGreater(len(files), 200)
        for f in files:
            p = json.loads(read(f))
            self.assertEqual(resolve.snowflake_time(p["id"]), p["postedAt"][:19] + "Z", f)

    def test_receipt_and_url_must_agree(self):
        f = sorted(glob.glob(os.path.join(HERE, "sources", "bobloukas", "receipts", "*.json")))[0]
        with self.assertRaisesRegex(resolve.ResolveError, "not https://x.com/a/status/1"):
            resolve.load_post("https://x.com/a/status/1", f)
        post = resolve.load_post(None, f)
        self.assertEqual(post["posted_at_source"], "receipt")
        self.assertRegex(post["receipt_sha256"], "^[0-9a-f]{64}$")

    def test_bad_url_and_bad_side(self):
        with self.assertRaisesRegex(resolve.ResolveError, "not a post url"):
            resolve.load_post("https://example.com/x/status/1")
        with self.assertRaisesRegex(resolve.ResolveError, "side must be"):
            resolve.side_of("up")

    def test_schema_rejects_a_broken_record(self):
        p = self.snapshot(BTC=hourly("2026-10-01T00:00:00Z", "2026-10-05T00:00:00Z"))
        r = self.one({"url": post_url("2026-10-01T10:30:00Z"), "asset": "BTC"}, p)
        r["status"] = "maybe"
        with self.assertRaisesRegex(resolve.ResolveError, "schema"):
            resolve.check_record(V, r)


if __name__ == "__main__":
    unittest.main()
