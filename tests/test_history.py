"""Step 14: price history before the first call, and display changes never moving frozen values.
Run: python3 -m unittest -v tests.test_history"""
import datetime as dt
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
import fetch_ohlc  # noqa: E402
import frozen_values  # noqa: E402
import resolve  # noqa: E402

OHLC = os.path.join(HERE, "web", "data", "ohlc")


def load(path):
    with open(path) as f:
        return json.load(f)


class Lookback(unittest.TestCase):
    def posts(self, *ats):
        # plus a post with no price after it yet (market closed), inside the range: it counts from its post time
        return [{"entry": {"at": a}, "post": {"posted_at": a}} for a in ats] + [{"entry": None, "post": {"posted_at": ats[0]}}]

    def test_a_post_with_no_price_yet_counts_from_its_post_time(self):
        self.assertEqual(fetch_ohlc.lookback([{"entry": None, "post": {"posted_at": "2026-10-30T23:01:54Z"}}]), (90, "2026-08-01T23:01:54Z"))

    def test_ninety_days_minimum(self):
        self.assertEqual(fetch_ohlc.lookback(self.posts("2026-10-01T00:00:00Z", "2026-10-20T00:00:00Z")), (90, "2026-07-03T00:00:00Z"))

    def test_longer_when_the_calls_span_longer(self):
        days, start = fetch_ohlc.lookback(self.posts("2024-04-08T04:00:00Z", "2026-10-23T13:00:00Z"))
        self.assertEqual(days, 929)                                 # first-to-last span 928.4 days, rounded up
        self.assertEqual(start, "2021-09-22T04:00:00Z")


class CandleFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load(os.path.join(HERE, "web", "data", "charts.json"))
        cls.index = load(os.path.join(OHLC, "index.json"))
        cls.files = {n: load(os.path.join(OHLC, m["file"])) for n, m in cls.index["files"].items()}

    def test_every_asset_has_history_before_its_first_call(self):
        self.assertEqual(set(self.files), {a["name"] for a in self.bundle["assets"]})
        for a in self.bundle["assets"]:
            doc = self.files[a["name"]]
            lb, c = doc["lookback"], doc["candles"]
            first_call = min(p["entry"]["at"] if p["entry"] else p["post"]["posted_at"] for p in a["posts"])
            self.assertEqual(lb["first_call"], first_call, a["name"])
            self.assertEqual((lb["days"], lb["start"]), fetch_ohlc.lookback(a["posts"]), a["name"])
            self.assertLess(c[0][0], first_call, f"{a['name']}: no bar before the first call")
            self.assertEqual(lb["first_bar"], c[0][0])
            if lb["starts_at_listing"]:
                self.assertGreater(c[0][0], lb["start"], a["name"])        # the market listed after the lookback start
            else:   # a weekend / holiday may sit between the lookback start and the first bar
                self.assertLessEqual(resolve.parse(c[0][0]) - resolve.parse(lb["start"]), dt.timedelta(days=4), a["name"])
            self.assertEqual(self.index["files"][a["name"]]["lookback"], lb)

    def test_daily_bars_only_before_daily_until(self):
        for name, doc in self.files.items():
            du, c = doc["daily_until"], doc["candles"]
            if not du:
                continue
            before = [b for b in c if b[0] < du]
            self.assertTrue(before, name)
            gaps = [(resolve.parse(y[0]) - resolve.parse(x[0])).total_seconds() / 3600 for x, y in zip(before, before[1:])]
            self.assertGreaterEqual(min(gaps), 20, f"{name}: bars closer than a day before daily_until {du}")
            after = [b for b in c if b[0] >= du][:200]
            hourly = [(resolve.parse(y[0]) - resolve.parse(x[0])).total_seconds() / 3600 for x, y in zip(after, after[1:])]
            self.assertIn(1.0, hourly, f"{name}: no hourly bars after daily_until")

    def test_entry_candles_still_match_the_records(self):
        rows, fails = fetch_ohlc.check(self.bundle, {n: d["candles"] for n, d in self.files.items()})
        self.assertEqual(fails, [])
        self.assertEqual(len(rows), sum(1 for a in self.bundle["assets"] for p in a["posts"] if p["entry"]))


class FrozenValues(unittest.TestCase):
    def test_no_frozen_value_moved(self):
        base = load(os.path.join(HERE, "verification", "step14", "frozen_baseline.json"))
        now = frozen_values.frozen(load(os.path.join(HERE, "web", "data", "charts.json")))
        self.assertEqual(frozen_values.compare(base, now), [])
        self.assertTrue(any(v["closed"] for v in base.values()))      # the silver close is part of the baseline

    def test_compare_catches_a_change(self):
        base = load(os.path.join(HERE, "verification", "step14", "frozen_baseline.json"))
        now = json.loads(json.dumps(base))
        key = next(k for k, v in now.items() if v["closed"])
        now[key]["closed"]["exit"]["price"] += 1
        k2 = next(k for k, v in now.items() if v["moves"])
        h = next(iter(now[k2]["moves"]))
        now[k2]["moves"][h] = None
        self.assertEqual(len(frozen_values.compare(base, now)), 2)


if __name__ == "__main__":
    unittest.main()
