"""Step 28: callers by BTC market regime. The labeller reads no future (a call's label equals the label of the
series cut at the call, later bars and changed future prices change no past label, a bar still open at the call is
never used, data that does not reach a call gives unknown), the build is deterministic (byte-identical output,
the served file equals a rebuild), the main scores are unchanged (no regime input reaches charts.json), and bad
data is refused. Run: python3 -m unittest -v tests.test_regimes"""
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import rate  # noqa: E402
import regimes as R  # noqa: E402

def load(path, mode="r"):
    with open(path, mode) as f:
        return json.load(f) if path.endswith(".json") and mode == "r" else f.read()


DATA = load(R.DATA)
BARS = DATA["bars"]
CHARTS = os.path.join(HERE, "web", "data", "charts.json")
BUNDLE = load(CHARTS)
SERVED = load(os.path.join(HERE, "web", "data", "regimes.json"))
LABELS = R.label_days(BARS)
DAY = R.DAY_MS


def sha(path):
    return hashlib.sha256(load(path, "rb")).hexdigest()


def tmp_root():
    root = tempfile.mkdtemp(prefix="quanty-regimes-")
    shutil.copytree(os.path.join(HERE, "web"), os.path.join(root, "web"))
    os.makedirs(os.path.join(root, "data"))
    shutil.copy(R.DATA, os.path.join(root, "data", "btc_daily.json"))
    return root


class NoLookAhead(unittest.TestCase):
    def test_every_call_gets_the_label_of_the_series_cut_at_the_call(self):
        rows = R.call_rows(BUNDLE, LABELS)
        res = R.check_no_lookahead(BARS, rows)
        self.assertEqual(len(res), len(rows))
        last = BARS[-1][1]
        for r, full, cut in res:
            with self.subTest(call=f'{r["posted_at"]} {r["author"]} {r["asset"]}'):
                self.assertEqual(full, cut)
                if full is None:                     # only when the stored data does not reach the call (a failed fetch): unknown, never stale
                    self.assertGreaterEqual(R.parse(r["posted_at"]) - last, DAY)

    def test_the_label_a_call_gets_is_from_a_bar_closed_before_it(self):
        for c in SERVED["calls"]:
            if c["regime"] is None:
                self.assertIsNone(c["bar_close_time"])
                continue
            with self.subTest(call=c["post_id"] + c["asset"]):
                self.assertLessEqual(R.parse(c["bar_close_time"]), R.parse(c["posted_at"]))
                self.assertLess(R.parse(c["posted_at"]) - R.parse(c["bar_close_time"]), DAY)

    def test_later_bars_never_change_an_earlier_label(self):
        for k in list(range(150, len(BARS), 97)) + [len(BARS) - 1]:
            with self.subTest(cut=R.day(BARS[k - 1][0])):
                self.assertEqual(R.label_days(BARS[:k]), LABELS[:k])

    def test_changing_every_future_price_changes_no_label_up_to_the_call(self):
        for c in SERVED["calls"][::7]:
            t = R.parse(c["posted_at"])
            fake = [b if b[1] <= t else [b[0], b[1]] + [x * (10 if i % 2 else 0.1) for i, x in enumerate(b[2:6])] + [b[6]] for b in BARS]
            k = sum(1 for b in BARS if b[1] <= t)
            with self.subTest(call=c["posted_at"]):
                self.assertEqual(R.label_days(fake)[:k], LABELS[:k])
                self.assertEqual((R.label_at(R.label_days(fake), t) or {}).get("regime"), c["regime"])     # unknown stays unknown

    def test_a_bar_still_open_at_the_call_is_never_used(self):
        i = len(LABELS) - 10
        close = LABELS[i]["close_time"]
        self.assertEqual(R.label_at(LABELS, close)["day"], LABELS[i]["day"])            # closed at the call: used
        self.assertEqual(R.label_at(LABELS, close - 1)["day"], LABELS[i - 1]["day"])    # 1 ms before its close: the bar before
        self.assertEqual(R.label_at(LABELS, close + DAY - 1)["day"], LABELS[i]["day"])

    def test_data_that_does_not_reach_the_call_gives_unknown_not_a_stale_label(self):
        last = LABELS[-1]["close_time"]
        self.assertIsNotNone(R.label_at(LABELS, last + DAY - 1))
        self.assertIsNone(R.label_at(LABELS, last + DAY))                  # the next bar should have closed: missing
        self.assertIsNone(R.label_at(LABELS, BARS[0][1] - 1))              # before the first bar
        self.assertIsNone(LABELS[R.PARAMS["sma_slow"] + R.PARAMS["confirm"] - 3]["regime"])   # warm-up: no regime yet
        self.assertIsNotNone(LABELS[R.PARAMS["sma_slow"] + R.PARAMS["confirm"] - 2]["regime"])

    def test_a_failed_fetch_leaves_new_calls_unknown_and_the_next_fetch_labels_them(self):
        last_call = max(R.parse(c["posted_at"]) for c in SERVED["calls"])
        k = sum(1 for b in BARS if b[1] < last_call - 3 * DAY)                 # the stored data stops 3+ days before the newest call
        stale = dict(DATA, bars=BARS[:k], bars_sha256=R.bars_sha(BARS[:k]))
        doc, _ = R.compute(BUNDLE, sha(CHARTS), stale)
        late = [c for c in doc["calls"] if R.parse(c["posted_at"]) - BARS[k - 1][1] >= DAY]
        self.assertTrue(late)
        self.assertTrue(all(c["regime"] is None and c["bar_day"] is None for c in late))
        self.assertEqual(doc["unknown_calls"], len(late))
        self.assertEqual(sum(x["calls"] for x in doc["per_regime"]["all callers"].values() if x), len(doc["calls"]))
        html = R.page(doc, R.label_days(BARS[:k]))
        self.assertIn('data-regime="unknown"', html)
        stale_labels = R.label_days(BARS[:k])
        for c in late:                                                           # changing prices after the data ends: still unknown
            t = R.parse(c["posted_at"])
            self.assertIsNone(R.label_at(stale_labels, t))
            self.assertIsNone((R.label_at(R.label_days([b[:2] + [x * 10 for x in b[2:6]] + b[6:] for b in BARS[:k]]), t) or {}).get("regime"))
        for r, a, b in R.check_no_lookahead(BARS[:k], R.call_rows(BUNDLE, R.label_days(BARS[:k]))):
            self.assertEqual(a, b)                                               # the check passes on stale data too (unknown = unknown)
        root = tmp_root()
        try:
            R.write(os.path.join(root, "web"), doc, R.label_days(BARS[:k]))       # the pages render with unknown calls
            self.assertIn('data-regime="unknown"', load(os.path.join(root, "web", "regimes.html")))
        finally:
            shutil.rmtree(root)
        full, _ = R.compute(BUNDLE, sha(CHARTS), DATA)                           # the next successful fetch: every call labelled
        self.assertEqual(full["unknown_calls"], 0)
        by = {(c["post_id"], c["asset"]): c for c in full["calls"]}
        for c in doc["calls"]:
            if c["regime"] is not None:                                          # a label given before stays the same
                self.assertEqual(by[(c["post_id"], c["asset"])]["regime"], c["regime"])

    def test_a_switch_needs_confirm_consecutive_days(self):
        for a, b in zip(SERVED["runs"], SERVED["runs"][1:]):
            i = next(j for j, l in enumerate(LABELS) if l["day"] == b["start"])
            with self.subTest(switch=b["start"]):
                self.assertEqual([l["raw"] for l in LABELS[i - R.PARAMS["confirm"] + 1:i + 1]], [b["regime"]] * R.PARAMS["confirm"])


class Determinism(unittest.TestCase):
    def test_two_builds_are_byte_identical_and_equal_the_served_files(self):
        root = tmp_root()
        try:
            web = os.path.join(root, "web")
            R.build_web(web)
            one = (sha(os.path.join(web, "data", "regimes.json")), sha(os.path.join(web, "regimes.html")))
            R.build_web(web)
            two = (sha(os.path.join(web, "data", "regimes.json")), sha(os.path.join(web, "regimes.html")))
            self.assertEqual(one, two)
            self.assertEqual(one, (sha(os.path.join(HERE, "web", "data", "regimes.json")), sha(os.path.join(HERE, "web", "regimes.html"))))
        finally:
            shutil.rmtree(root)

    def test_the_served_document_binds_its_inputs(self):
        self.assertEqual(SERVED["bars"]["sha256"], R.bars_sha(BARS))
        self.assertEqual(SERVED["bars"]["sha256"], DATA["bars_sha256"])
        self.assertEqual(SERVED["charts_sha256"], sha(CHARTS))
        self.assertEqual(SERVED["params"], R.PARAMS)
        self.assertEqual(SERVED["rule"], R.rule_text())

    def test_transition_matrix_counts_every_day_and_rows_sum_to_one(self):
        tm = SERVED["transitions"]
        days = sum(1 for l in LABELS if l["regime"])
        self.assertEqual(sum(sum(r.values()) for r in tm["counts"].values()), days - 1)
        for a in R.REGIMES:
            self.assertAlmostEqual(sum(tm["probabilities"][a].values()), 1.0)
        self.assertEqual(tm["counts"]["bull"]["bear"] + tm["counts"]["bear"]["bull"], 0)   # trend flips pass through chop


class ScoresUnchanged(unittest.TestCase):
    def test_building_regimes_does_not_touch_charts_json(self):
        root = tmp_root()
        try:
            before = sha(os.path.join(root, "web", "data", "charts.json"))
            R.build_web(os.path.join(root, "web"))
            self.assertEqual(sha(os.path.join(root, "web", "data", "charts.json")), before)
        finally:
            shutil.rmtree(root)

    def test_the_main_scores_are_the_rating_of_all_calls_and_ignore_regimes(self):
        again = rate.rate_bundle(copy.deepcopy(BUNDLE))
        for name, c in BUNDLE["ratings"]["callers"].items():
            with self.subTest(caller=name):
                self.assertEqual(again["callers"][name]["score"], c["score"])
                self.assertEqual(again["callers"][name]["display"], c["display"])

    def test_regime_cells_partition_each_callers_calls_and_use_the_same_rules(self):
        rows = R.call_rows(BUNDLE, LABELS)
        for name, c in BUNDLE["ratings"]["callers"].items():
            cells = SERVED["per_regime"][name]
            with self.subTest(caller=name):
                self.assertEqual(sum(x["calls"] for x in cells.values() if x), c["calls_total"])
                self.assertEqual(sum(x["scored"] for x in cells.values() if x), c["scored"])
                for reg in R.REGIMES:
                    sub = [(r["asset"], r["_p"]) for r in rows if r["author"] == name and r["regime"] == reg]
                    if sub:
                        rc = rate.rate_caller(sub)
                        self.assertEqual(cells[reg]["score"], rc["score"])
                        self.assertEqual(cells[reg]["label"], rate.label(rc["scored"]))

    def test_small_samples_are_marked_on_the_page(self):
        html = load(os.path.join(HERE, "web", "regimes.html"))
        for name, cells in SERVED["per_regime"].items():
            for reg, c in cells.items():
                if c and c["scored"] < rate.SMALL:
                    with self.subTest(caller=name, regime=reg):
                        self.assertEqual(c["label"], "small sample")
        self.assertIn('data-label="small sample"><strong>', html)

    def test_each_caller_page_shows_its_regime_section(self):
        for name in BUNDLE["ratings"]["callers"]:
            page = load(os.path.join(HERE, "web", f"caller-{rate.caller_slug(name)}.html"))
            with self.subTest(caller=name):
                self.assertIn('data-field="by_regime"', page)
                for c in SERVED["calls"]:
                    if c["author"] == name:
                        self.assertIn(f'data-post-id="{c["post_id"]}" data-asset="{c["asset"]}" data-regime="{c["regime"] or "unknown"}"', page)
                self.assertIn(f'data-field="score" data-raw="{BUNDLE["ratings"]["callers"][name]["score"]!r}"', page)


class DataIntegrity(unittest.TestCase):
    def test_bad_series_are_refused(self):
        cases = {"gap": BARS[:10] + BARS[11:20], "duplicate": BARS[:10] + BARS[9:20], "out of order": BARS[:10] + [BARS[11], BARS[10]] + BARS[12:20],
                 "truncated bar": BARS[:10] + [[BARS[10][0], BARS[10][0] + 1694788] + BARS[10][2:]] + BARS[11:20],
                 "bad high": BARS[:10] + [BARS[10][:3] + [BARS[10][4] - 1] + BARS[10][4:]] + BARS[11:20], "empty": []}
        for name, bars in cases.items():
            with self.subTest(case=name):
                self.assertRaises(R.Integrity, R.validate, bars)

    def test_a_stored_bar_that_changes_at_the_source_is_refused_and_nothing_is_written(self):
        root = tempfile.mkdtemp(prefix="quanty-btc-")
        try:
            p = os.path.join(root, "btc.json")
            with open(p, "w") as f:
                json.dump({"bars": BARS[:40]}, f)
            src = [[b[0], str(b[2]), str(b[3]), str(b[4]), str(b[5]), str(b[6]), b[1]] for b in BARS[:45]]
            src[37][4] = str(float(src[37][4]) * 1.01)                       # a past close rewritten
            before = load(p, "rb")
            self.assertRaises(R.Integrity, R.fetch, p, BARS[44][1] + 1, lambda u: src)
            self.assertEqual(load(p, "rb"), before)
            src[37][4] = str(BARS[37][5])
            doc, added = R.fetch(p, BARS[44][1], lambda u: src)               # the bar closing exactly now is not complete yet
            self.assertEqual((doc["count"], added), (44, 4))
            self.assertEqual(doc["bars"], BARS[:44])
            self.assertEqual(doc["bars_sha256"], R.bars_sha(BARS[:44]))
        finally:
            shutil.rmtree(root)

    def test_edited_stored_bars_are_refused_at_build(self):
        bad = dict(DATA, bars=copy.deepcopy(BARS))
        bad["bars"][-3][5] = bad["bars"][-3][5] + 1
        self.assertRaises(R.Integrity, R.compute, BUNDLE, sha(CHARTS), bad)


if __name__ == "__main__":
    unittest.main()
