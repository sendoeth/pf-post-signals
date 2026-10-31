"""Step 15: the 0-100 caller rating (rate.py). Hand-computed fixtures, shrinkage, monotonicity,
realized returns for closed calls, determinism, hostile names, and the live bundle.
Run: python3 -m unittest -v tests.test_rating"""
import json
import math
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import rate  # noqa: E402


def pos(author="alice", pid="1", side=1, change=0.0, closed_for_call=None, entry=True, posted="2026-10-01T00:00:00Z"):
    p = {"post": {"id": pid, "author": author, "posted_at": posted}, "side": side, "change_since_post": change,
         "entry": {"at": posted, "price": 100.0} if entry else None}
    if closed_for_call is not None:
        p["closed"] = {"move": closed_for_call * (side or 1), "for_call": closed_for_call if side else None}
    return p


def bundle(*positions, asset="BTC"):
    return {"prices_as_of": "2026-10-31T00:00:00Z", "assets": [{"name": asset, "posts": list(positions)}]}


def score_of(positions):
    return rate.rate_bundle(bundle(*positions))["callers"]["alice"]


class HandComputed(unittest.TestCase):
    def test_two_scored_calls_one_without_side(self):
        """long +10% (open), short closed at -5% for the call, one call without a side.
        A1 = 50 + 50 tanh(1)    = 50 + 50 x 0.7615941560 = 88.0797077978
        A2 = 50 + 50 tanh(-0.5) = 50 - 50 x 0.4621171573 = 26.8941421370
        H = 50 (1 of 2) · A = 57.4869249674 · C = 100 x 2/3 = 66.6666666667
        raw = 0.45 x 50 + 0.40 x 57.4869249674 + 0.15 x 66.6666666667 = 22.5 + 22.9947699870 + 10 = 55.4947699870
        w = 2/12 = 0.1666666667 · score = 50 + 5.4947699870 / 6 = 50.9157949978"""
        c = score_of([pos(pid="1", side=1, change=0.10), pos(pid="2", side=-1, change=0.30, closed_for_call=-0.05),
                      pos(pid="3", side=None, change=0.50)])
        self.assertEqual((c["calls_total"], c["with_entry"], c["scored"], c["wins"]), (3, 3, 2, 1))
        self.assertAlmostEqual(c["components"]["hit"], 50.0, places=10)
        self.assertAlmostEqual(c["components"]["quality"], 57.4869249674, places=9)
        self.assertAlmostEqual(c["components"]["clarity"], 66.6666666667, places=9)
        self.assertAlmostEqual(c["raw"], 55.4947699870, places=9)
        self.assertAlmostEqual(c["weight"], 1 / 6, places=12)
        self.assertAlmostEqual(c["score"], 50.9157949978, places=9)
        self.assertEqual(c["display"], "50.9")
        self.assertEqual(c["label"], "small sample")

    def test_no_scored_calls_is_the_prior(self):
        c = score_of([pos(pid="1", side=None, change=0.2), pos(pid="2", side=1, entry=False), pos(pid="3", side=1, change=None)])
        self.assertEqual((c["score"], c["scored"], c["weight"]), (50.0, 0, 0.0))
        self.assertEqual([x["counted"] for x in c["calls"]], [False, False, False])
        self.assertEqual(c["with_entry"], 2)                 # the no-entry call is listed but has no price at all

    def test_display_rounds_half_up(self):
        self.assertEqual(rate.display(50.25), "50.3")
        self.assertEqual(rate.display(49.95), "50.0")
        self.assertEqual(rate.display(50.0), "50.0")


class Shrinkage(unittest.TestCase):
    def test_same_results_more_calls_moves_further_from_50(self):
        one = score_of([pos(pid="0", change=0.10)])
        thirty = score_of([pos(pid=str(i), change=0.10) for i in range(30)])
        self.assertAlmostEqual(one["raw"], thirty["raw"], places=12)          # same per-call results
        self.assertAlmostEqual(one["weight"], 1 / 11, places=12)
        self.assertAlmostEqual(thirty["weight"], 30 / 40, places=12)
        self.assertAlmostEqual(thirty["score"] - 50, (one["score"] - 50) * (30 / 40) / (1 / 11), places=9)
        self.assertGreater(thirty["score"], one["score"])
        self.assertEqual((one["label"], thirty["label"]), ("small sample", None))
        self.assertEqual(score_of([pos(pid=str(i), change=0.1) for i in range(12)])["label"], "limited sample")

    def test_losing_caller_is_pulled_up_toward_50(self):
        one = score_of([pos(pid="0", change=-0.2)])
        many = score_of([pos(pid=str(i), change=-0.2) for i in range(40)])
        self.assertLess(many["score"], one["score"])
        self.assertLess(one["score"], 50)


class Monotonic(unittest.TestCase):
    def test_a_better_result_never_lowers_the_score(self):
        rng = random.Random(15)
        checked = 0
        for _ in range(400):
            n = rng.randint(1, 25)
            calls = [pos(pid=str(i), side=rng.choice([1, -1, None]), change=rng.uniform(-0.6, 0.6),
                         closed_for_call=rng.uniform(-0.6, 0.6) if rng.random() < 0.2 else None) for i in range(n)]
            for p in calls:   # keep closed blocks consistent with the side
                if p.get("closed") and not p["side"]:
                    del p["closed"]
            base = score_of(calls)["score"]
            for i, p in enumerate(calls):
                if not p["side"]:
                    continue
                better = json.loads(json.dumps(calls))
                bump = rng.uniform(0.001, 0.5)
                if better[i].get("closed"):
                    better[i]["closed"]["for_call"] += bump
                else:
                    better[i]["change_since_post"] += bump * better[i]["side"]
                self.assertGreaterEqual(score_of(better)["score"], base - 1e-12)
                checked += 1
        self.assertGreater(checked, 1000)

    def test_a_loss_turned_into_a_win_raises_it(self):
        calls = [pos(pid="1", change=-0.05), pos(pid="2", change=0.03)]
        better = [pos(pid="1", change=0.05), pos(pid="2", change=0.03)]
        self.assertGreater(score_of(better)["score"], score_of(calls)["score"])

    def test_stating_a_side_never_lowers_clarity(self):
        a = score_of([pos(pid="1", change=0.1), pos(pid="2", side=None, change=0.1)])
        b = score_of([pos(pid="1", change=0.1), pos(pid="2", change=0.1)])
        self.assertGreater(b["components"]["clarity"], a["components"]["clarity"])


class Realized(unittest.TestCase):
    def test_closed_call_counts_at_its_realized_return_not_the_current_price(self):
        c = score_of([pos(pid="1", side=1, change=-0.40, closed_for_call=0.25)])   # closed +25%, price since fell 40%
        call = c["calls"][0]
        self.assertEqual((call["result"], call["state"], call["counted"]), (0.25, "closed", True))
        self.assertEqual(c["wins"], 1)
        self.assertAlmostEqual(call["quality"], 50 + 50 * math.tanh(2.5), places=12)
        self.assertIn("realized", call["why"])

    def test_short_open_call_uses_the_side(self):
        c = score_of([pos(pid="1", side=-1, change=-0.10)])   # price -10% -> +10% for the short
        self.assertAlmostEqual(c["calls"][0]["result"], 0.10, places=12)
        self.assertEqual(c["wins"], 1)


class Deterministic(unittest.TestCase):
    def test_input_order_does_not_matter(self):
        calls = [pos(author=a, pid=f"{a}{i}", side=s, change=ch, posted=f"2026-10-{10 + i:02d}T00:00:00Z")
                 for a in ("bob", "Alice", "carl") for i, (s, ch) in enumerate([(1, 0.1), (-1, 0.05), (None, 0.2), (1, -0.3)])]
        a = rate.rate_bundle(bundle(*calls))
        shuffled = calls[:]
        random.Random(1).shuffle(shuffled)
        b = rate.rate_bundle(bundle(*shuffled))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual([a["callers"][n]["rank"] for n in a["order"]], [1, 2, 3])

    def test_ties_rank_by_name(self):
        rt = rate.rate_bundle(bundle(pos(author="zed", pid="1", change=0.1), pos(author="Amy", pid="2", change=0.1)))
        self.assertEqual(rt["order"], ["Amy", "zed"])


class HostileNames(unittest.TestCase):
    def test_slug_keeps_only_safe_characters(self):
        for name in ('"><img src=x onerror=window.__pwned=3>', "../../etc/passwd", "a b\nc", "UPPER_case-1"):
            s = rate.caller_slug(name)
            self.assertRegex(s, r"^[a-z0-9_-]+$")
        self.assertEqual(rate.caller_slug("BobLoukas"), "bobloukas")

    def test_hostile_author_is_rated_like_any_other(self):
        name = '"><img src=x onerror=window.__pwned=3>'
        rt = rate.rate_bundle(bundle(pos(author=name, pid="1", change=0.1)))
        self.assertIn(name, rt["callers"])


class LiveBundle(unittest.TestCase):
    def test_bundle_ratings_equal_a_fresh_computation(self):
        with open(os.path.join(HERE, "web", "data", "charts.json")) as f:
            b = json.load(f)
        self.assertEqual(json.dumps(b["ratings"], sort_keys=True), json.dumps(rate.rate_bundle(b), sort_keys=True))
        for name, c in b["ratings"]["callers"].items():
            self.assertTrue(0 <= c["score"] <= 100, name)
            self.assertEqual(len(c["calls"]), c["calls_total"])
            self.assertEqual(sum(x["counted"] for x in c["calls"]), c["scored"])


if __name__ == "__main__":
    unittest.main()
