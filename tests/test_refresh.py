"""Step 9 refresh tests (offline): frozen entry/exit bars survive provider revisions and missing
bars, revisions are logged, newly reached horizons fill. Run: python3 -m unittest -v tests.test_refresh"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import refresh  # noqa: E402
import resolve  # noqa: E402
from tests.test_resolve import hourly, post_url  # noqa: E402


def resolved(series, side=1, when="2026-09-01T10:30:00Z"):
    post = resolve.load_post(url=post_url(when))
    return resolve.resolve(post, resolve.asset_info("BTC"), series, "test", side)


class Refresh(unittest.TestCase):
    def setUp(self):
        self.old = resolved(hourly("2026-09-01T00:00:00Z", "2026-09-20T00:00:00Z"))   # 1d + 7d resolved, 30d not yet
        self.assertEqual(set(self.old["unresolved"]), {"30"})

    def rerun(self, series):
        revisions = []
        bars = refresh.patched(series, refresh.frozen_bars(self.old), revisions, "rec")
        return resolved([list(b) for b in bars]), revisions

    def test_revision_keeps_frozen_entry_and_exits_and_is_logged(self):
        fresh = hourly("2026-09-01T00:00:00Z", "2026-10-10T00:00:00Z")
        fresh = [[t, p + 0.5] for t, p in fresh]                  # provider revised every price
        new, revs = self.rerun(fresh)
        self.assertEqual(new["entry"], self.old["entry"])
        for h in ("1", "7"):
            self.assertEqual(new["exits"][h], self.old["exits"][h])
            self.assertEqual(new["moves"][h], self.old["moves"][h])
        self.assertEqual({r["what"] for r in revs}, {"entry", "1d exit", "7d exit"})
        self.assertTrue(all(r["fetched"] == r["frozen"] + 0.5 for r in revs))

    def test_missing_bar_keeps_frozen_value(self):
        fresh = [b for b in hourly("2026-09-01T00:00:00Z", "2026-10-10T00:00:00Z") if b[0] != self.old["exits"]["7"]["at"]]
        new, revs = self.rerun(fresh)
        self.assertEqual(new["exits"]["7"], self.old["exits"]["7"])
        self.assertEqual([(r["what"], r["fetched"]) for r in revs], [("7d exit", None)])

    def test_new_horizon_fills_and_latest_moves(self):
        new, revs = self.rerun(hourly("2026-09-01T00:00:00Z", "2026-10-10T00:00:00Z"))
        self.assertEqual(revs, [])
        self.assertIsNotNone(new["moves"]["30"])
        self.assertEqual(new["status"], "resolved")
        self.assertGreater(new["latest"]["at"], self.old["latest"]["at"])
        self.assertEqual(new["change_since_post"], new["latest"]["price"] / new["entry"]["price"] - 1)


class CarryOver(unittest.TestCase):
    """A refresh recomputes prices; everything it cannot recompute must survive it (side_choice was dropped by
    every refresh from step 16 until 2026-11-02, asset.renamed_from from step 22)."""
    def test_every_optional_field_is_recomputed_or_carried(self):
        import json
        schema = json.load(open(os.path.join(HERE, "schema", "post_price.v1.json")))
        fresh = resolved(hourly("2026-09-01T00:00:00Z", "2026-09-20T00:00:00Z"))
        top = set(schema["properties"]) - set(fresh) - set(refresh.CARRY_TOP) - set(refresh.RECOMPUTED_BY_LIFECYCLE)
        self.assertEqual(top, set(), "record fields a refresh would drop")
        asset = set(schema["properties"]["asset"]["properties"]) - set(fresh["asset"]) - set(refresh.CARRY_ASSET)
        self.assertEqual(asset, set(), "asset fields a refresh would drop")

    def test_choices_and_rename_survive(self):
        old = resolved(hourly("2026-09-01T00:00:00Z", "2026-09-20T00:00:00Z"))
        old["side_choice"] = {"method": "detector-leg", "terms": ["Bought $INJ"], "reason": "'bought' before the coin"}
        old["asset_choice"] = {"method": "detector", "terms": ["$INJ"], "reason": None}
        old["asset"]["renamed_from"] = "binance:BTCUSDT"
        new = refresh.carry_over(old, resolved(hourly("2026-09-01T00:00:00Z", "2026-10-10T00:00:00Z")))
        self.assertEqual((new["side_choice"], new["asset_choice"], new["asset"]["renamed_from"]),
                         (old["side_choice"], old["asset_choice"], "binance:BTCUSDT"))


if __name__ == "__main__":
    unittest.main()
