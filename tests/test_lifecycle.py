"""Step 13: closing calls. The BobLoukas silver chain (real receipts in sources/bobloukas/receipts) and
synthetic cases. Run: python3 -m unittest -v tests.test_lifecycle"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import classify  # noqa: E402
import lifecycle  # noqa: E402
import resolve  # noqa: E402
from tests.test_resolve import hourly  # noqa: E402

OPEN, TRIM, HINT, CLOSE, ADVICE = "1776235528741937435", "1979978358214774957", "2004636831774871803", "2009654117799739530", "2014728061996896651"


def text(i):
    with open(os.path.join(HERE, "sources", "bobloukas", "receipts", f"{i}.json")) as f:
        return json.load(f)["text"]


class SilverChain(unittest.TestCase):
    """Expected: 1 open, 1 trim, 1 review, 1 close, 1 not-a-close."""

    def test_classifier_on_the_real_posts(self):
        got = {i: classify.classify(text(i), "SILVER", 1) for i in (TRIM, HINT, CLOSE, ADVICE)}
        self.assertEqual({i: g["type"] for i, g in got.items()}, {TRIM: "trim", HINT: "review", CLOSE: "close", ADVICE: "not_close"})
        self.assertEqual(got[CLOSE]["terms"], ["rotated out of"])
        self.assertEqual(got[CLOSE]["stated_time"], "last week")
        self.assertEqual(got[TRIM]["stated_time"], "on Friday")
        self.assertIn("afford yourself", got[ADVICE]["terms"])
        self.assertEqual(classify.classify(text(OPEN), "SILVER", 1)["type"], "not_close")   # the open itself is no exit

    def chain(self):
        # synthetic hourly prices covering the real dates: 30 -> rises 0.01 per hour
        series = hourly("2024-04-05T00:00:00Z", "2026-03-01T00:00:00Z", price=30.0, step=0.01)
        post = resolve.load_post(receipt=f"sources/bobloukas/receipts/{OPEN}.json")
        os.chdir(HERE)
        rec = resolve.resolve(post, resolve.asset_info("SILVER"), series, "test", 1)
        return lifecycle.apply(rec, {"followups": [ADVICE, CLOSE, HINT, TRIM]}, series), series

    def test_apply_closes_at_the_first_bar_after_the_closing_post(self):
        rec, series = self.chain()
        self.assertEqual([e["type"] for e in rec["lifecycle"]["events"]], ["trim", "review", "close", "not_close"])
        self.assertEqual(rec["status"], "closed")
        self.assertEqual(rec["lifecycle"]["state"], "closed")
        self.assertEqual(rec["closed"]["exit"]["at"], "2026-01-09T16:00:00Z")          # post 15:50:53 -> 16:00 bar
        self.assertEqual(rec["closed"]["for_call"], rec["closed"]["exit"]["price"] / rec["entry"]["price"] - 1)
        self.assertEqual(rec["closed"]["stated_time"], "last week")                   # recorded, not used
        self.assertTrue(rec["lifecycle"]["events"][3]["after_close"])
        self.assertNotIn("bar", rec["lifecycle"]["events"][1])                        # a hint is never priced

    def test_trim_keeps_the_position_open(self):
        series = hourly("2024-04-05T00:00:00Z", "2026-03-01T00:00:00Z", price=30.0, step=0.01)
        rec = resolve.resolve(resolve.load_post(receipt=f"sources/bobloukas/receipts/{OPEN}.json"), resolve.asset_info("SILVER"), series, "t", 1)
        rec = lifecycle.apply(rec, {"followups": [TRIM, HINT]}, series)
        self.assertEqual(rec["lifecycle"]["state"], "open")
        self.assertNotIn("closed", rec)
        self.assertNotEqual(rec["status"], "closed")
        self.assertEqual(rec["lifecycle"]["events"][0]["bar"]["at"], "2025-10-19T19:00:00Z")

    def test_override_needs_and_keeps_a_reason(self):
        series = hourly("2024-04-05T00:00:00Z", "2026-03-01T00:00:00Z", price=30.0, step=0.01)
        rec = resolve.resolve(resolve.load_post(receipt=f"sources/bobloukas/receipts/{OPEN}.json"), resolve.asset_info("SILVER"), series, "t", 1)
        rec = lifecycle.apply(rec, {"followups": [HINT], "overrides": {HINT: {"type": "close", "reason": "author confirmed the stop hit"}}}, series)
        self.assertEqual(rec["closed"]["post_id"], HINT)
        self.assertEqual(rec["lifecycle"]["events"][0]["decided_by"], "override")
        self.assertIn("author confirmed the stop hit", rec["lifecycle"]["events"][0]["reason"])

    def test_followup_must_be_after_the_open(self):
        series = hourly("2024-03-01T00:00:00Z", "2024-05-01T00:00:00Z")
        rec = resolve.resolve(resolve.load_post(receipt=f"sources/bobloukas/receipts/{OPEN}.json"), resolve.asset_info("SILVER"), series, "t", 1)
        with self.assertRaisesRegex(resolve.ResolveError, "not after the opening post"):
            lifecycle.apply(rec, {"followups": ["1765739278053560772"]}, series)

    def test_schema_accepts_the_closed_record(self):
        rec, _ = self.chain()
        resolve.check_record(resolve.validator(), rec)


class Classifier(unittest.TestCase):
    def c(self, t, side=1, asset="BTC"):
        return classify.classify(t, asset, side)

    def test_flip(self):
        r = self.c("Took the loss and flipped short bitcoin here")
        self.assertEqual(r["type"], "flip")
        self.assertEqual(self.c("still long bitcoin, now long more")["type"], "not_close")   # same side is no flip

    def test_closes(self):
        for t in ("Sold all my bitcoin today", "I'm out of bitcoin", "Stopped out of the BTC long", "Closed my bitcoin position"):
            self.assertEqual(self.c(t)["type"], "close", t)

    def test_other_asset_is_not_about_this_position(self):
        r = self.c("Sold all my gold today")
        self.assertEqual(r["type"], "not_close")
        self.assertIn("does not name BTC", r["reason"])

    def test_advice_wins_over_exit_words(self):
        self.assertEqual(self.c("You should take some profits on bitcoin here")["type"], "not_close")


class Ledger(unittest.TestCase):
    def test_ledger_exit_closes_at_the_first_bar_after(self):
        series = [[t, p] for t, p in hourly("2026-09-04T00:00:00Z", "2026-10-10T00:00:00Z", price=8.0, step=-0.001)]
        post = {"id": "corbanu:cxmt-entry", "url": "https://corbanu.com/posts/chinese-memory-sovereign-ai-long-cxmt/", "author": "Corbanu",
                "posted_at": "2026-09-04T20:09:40Z", "posted_at_source": "ledger", "source": "corbanu", "text": "t", "receipt_sha256": None}
        rec = resolve.resolve(post, resolve.asset_info("XYZ:CXMT"), series, "t", 1)
        rec = lifecycle.ledger_close(rec, {"id": "cxmt-exit", "type": "trade", "at": "2026-10-01T14:00:00Z", "targetWeightPct": 0, "note": "fixture"}, series)
        self.assertEqual(rec["status"], "closed")
        self.assertEqual(rec["closed"]["by"], "ledger")
        self.assertEqual(rec["closed"]["exit"]["at"], "2026-10-01T14:00:00Z")
        self.assertEqual(rec["lifecycle"]["events"][0]["decided_by"], "ledger")
        resolve.check_record(resolve.validator(), rec)

    def test_importer_marks_ledger_exits(self):
        sys.path.insert(0, os.path.join(HERE, "tools"))
        import import_corbanu
        self.assertTrue(import_corbanu.is_exit({"type": "trade", "targetWeightPct": 0}))
        self.assertTrue(import_corbanu.is_exit({"type": "exit"}))
        self.assertFalse(import_corbanu.is_exit({"type": "trade", "targetWeightPct": 3.5}))


if __name__ == "__main__":
    unittest.main()
