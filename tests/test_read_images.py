"""Step 18: reading calls from chart screenshots (tools/read_images.py), offline: crop matching on
fixture images and on the real SOXL pair, OCR text -> titles / tickers / labels, price-label checks,
the end-to-end analysis with a faked post + reply (status needs_review, no side, nothing added), and
add_call refusing image-inferred calls without a written reason.
Needs pillow + numpy (.venv: python3 -m venv --system-site-packages .venv; .venv/bin/pip install pillow==11.3.0 numpy==2.3.4).
Run: .venv/bin/python -m unittest -v tests.test_read_images"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import add_call  # noqa: E402
import read_images  # noqa: E402
import resolve  # noqa: E402
from tests.test_add_call import tree_hash  # noqa: E402

IMG = os.path.join(HERE, "tests", "fixtures", "images")
EPOCH = 1288834974657
SOXL_TITLE_OCR = "X Direxion Daily Semiconductor Bull 3X Shares - 1w - AMEX 400.0000\n302.0000 320.0000\n169.8500\n86.2100 74.1000\n6.8900\nApr Jul Oct 2026"


def pid_at(iso):
    ms = int(dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    return str((ms - EPOCH) << 22)


class Crop(unittest.TestCase):
    def test_a_crop_is_found_where_it_was_cut(self):
        m = read_images.crop_match(os.path.join(IMG, "crop.png"), os.path.join(IMG, "chart.png"))
        self.assertTrue(m["crop"])
        self.assertGreater(m["score"], 0.95)
        for got, want in zip(m["box"], [100, 60, 230, 285]):           # cut at (100, 60), 230 x 285, scaled 0.75
            self.assertLessEqual(abs(got - want), 6)

    def test_an_unrelated_chart_is_not_a_crop(self):
        m = read_images.crop_match(os.path.join(IMG, "crop.png"), os.path.join(IMG, "other.png"))
        self.assertFalse(m["crop"])
        self.assertLess(m["score"], read_images.CROP_MIN)

    def test_the_real_soxl_crop(self):
        m = read_images.crop_match(os.path.join(HERE, "sources", "goodalexander", "media", "2116304617047007308_0.png"),
                                   os.path.join(HERE, "sources", "based16z", "media", "2116217175962776030_0.jpg"))
        self.assertTrue(m["crop"])
        x, y, w, h = m["box"]
        self.assertTrue(x < 171 < x + w and y < 854 < y + h, m)       # the 6.89 label sits at about (171, 854) in the full chart


class Read(unittest.TestCase):
    def test_title_maps_to_the_asset(self):
        r = read_images.read_text(SOXL_TITLE_OCR)
        self.assertEqual([t["asset"] for t in r["titles"]], ["SOXL"])
        self.assertIn(6.89, r["labels"])
        self.assertIn(302.0, r["labels"])

    def test_a_ticker_on_the_chart(self):
        r = read_images.read_text("BTCUSDT · 1D · Binance\nBTC 77,405.98 81000.00")
        self.assertEqual(r["tickers"], ["BTC"])
        self.assertEqual(r["labels"], [77405.98, 81000.0])               # thousands separators are read whole

    def test_no_readable_text(self):
        self.assertEqual(read_images.read_text("a | rt\nho\n1+"), {"titles": [], "tickers": [], "words": [], "labels": []})

    def test_a_title_needs_every_word(self):
        self.assertEqual(read_images.read_text("Direxion Daily Bull 3X Shares")["titles"], [])     # "Semiconductor" missing


class FakePrices:
    """A price snapshot: SOXL at 77 around the post, BTC at 80000."""
    label = "test"

    def __init__(self, series):
        self.data = series

    def series(self, asset, since):
        return self.data[asset["name"]]

    def daily_until(self, asset, since):
        return None


def hourly(start, n, price):
    t = dt.datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ")
    return [[(t + dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ"), price] for i in range(n)]


class Prices(unittest.TestCase):
    def test_near_and_far_labels(self):
        p = FakePrices({"SOXL": hourly("2026-10-29T00:00:00Z", 60, 77.05)})
        hist = lambda a, w: [("2025-04-07", 7.23, 10.98), ("2026-06-01", 280.0, 302.0)]
        c = read_images.check_labels([6.89, 76.5, 302.0], resolve.asset_info("SOXL"), "2026-10-30T23:01:54Z", p, hist)
        by = {l["label"]: l for l in c["labels"]}
        self.assertEqual(c["price_at_post"]["price"], 77.05)
        self.assertFalse(by[6.89]["near"])
        self.assertAlmostEqual(by[6.89]["vs_price"], 6.89 / 77.05 - 1)
        self.assertEqual((by[6.89]["nearest_daily"]["date"], by[6.89]["nearest_daily"]["which"], by[6.89]["nearest_daily"]["matches"]), ("2025-04-07", "low", False))
        self.assertTrue(by[76.5]["near"])
        self.assertTrue(by[302.0]["nearest_daily"]["matches"])                 # = the 2026-06-01 daily high


class Scratch(unittest.TestCase):
    """A post with a cropped chart replying to a post with the full titled chart, all faked."""
    POST_AT, PARENT_AT = "2026-10-30T23:01:54Z", "2026-10-30T17:14:26Z"

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="quanty-img-")
        for d in ("records", "sources", "web"):
            shutil.copytree(os.path.join(HERE, d), os.path.join(self.root, d))
        self.post, self.parent = pid_at(self.POST_AT), pid_at(self.PARENT_AT)
        self.texts = {"post": "solid support here", "parent": ""}
        self.ocr_text = {"crop.png": "a | rt\n6.8900", "chart.png": SOXL_TITLE_OCR}
        self.prices = FakePrices({"SOXL": hourly("2026-10-29T00:00:00Z", 47, 77.05) + hourly("2026-11-02T13:00:00Z", 30, 74.0)})   # Friday close, then Monday

    def tearDown(self):
        shutil.rmtree(self.root)

    def embed(self, pid, author, at, text, media, reply_to=None):
        return {"__typename": "Tweet", "id_str": pid, "created_at": at.replace("Z", ".000Z"), "text": text, "display_text_range": [0, len(text)],
                "entities": {"symbols": []}, "conversation_id_str": pid, "user": {"screen_name": author}, "in_reply_to_status_id_str": reply_to,
                "mediaDetails": [{"type": "photo", "media_url_https": f"https://pbs.twimg.com/media/{media}"}] if media else []}

    def fetch(self, pid):
        if pid == self.post:
            return self.embed(pid, "TestCaller", self.POST_AT, self.texts["post"], "crop.png", reply_to=self.parent)
        if pid == self.parent:
            return self.embed(pid, "ChartPoster", self.PARENT_AT, self.texts["parent"], "chart.png")
        raise AssertionError(pid)

    def get(self, url, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        name, q = url.split("/media/")[1].split("?")
        shutil.copy(os.path.join(IMG, name + "." + dict(x.split("=") for x in q.split("&"))["format"]), path)
        return path

    def name_of(self, path):
        return "crop.png" if self.post in os.path.basename(path) else "chart.png"

    def analyse(self):
        return read_images.analyse(f"https://x.com/TestCaller/status/{self.post}", root=self.root, fetch=self.fetch, get=self.get,
                                   ocr_engine=lambda p: self.ocr_text[self.name_of(p)], prices=self.prices,
                                   history=lambda a, w: [("2025-04-07", 7.23, 10.98)], now="2026-10-31T00:00:00Z")


class Analyse(Scratch):
    def test_the_soxl_pattern_goes_to_review_without_a_side(self):
        web0, rec0 = tree_hash(self.root, "web"), tree_hash(self.root, "records")
        e = self.analyse()
        self.assertEqual((e["status"], e["asset_suggested"], e["side"], e["confidence"]), ("needs_review", "SOXL", None, "high"))
        self.assertEqual([p["role"] for p in e["posts"]], ["post", "reply_to"])
        self.assertTrue(e["crop_matches"][0]["crop"])
        self.assertEqual(e["crop_matches"][0]["shared_labels"], [6.89])
        self.assertTrue(any("solid support" in f for f in e["flags"]))
        lab = e["price_checks"][0]["labels"][0]
        self.assertEqual((lab["label"], lab["near"]), (6.89, False))
        for p in e["posts"]:
            for im in p["images"]:
                self.assertTrue(os.path.exists(os.path.join(self.root, im["file"])))
                self.assertEqual(len(im["sha256"]), 64)
                self.assertTrue(os.path.exists(os.path.join(self.root, im["file"] + ".ocr.json")))
        # nothing added: web/ and records/ unchanged, no pending intake
        self.assertEqual((tree_hash(self.root, "web"), tree_hash(self.root, "records")), (web0, rec0))
        self.assertFalse(os.path.exists(os.path.join(self.root, "intake", "pending")))
        self.assertTrue(os.path.exists(os.path.join(self.root, "intake", "images", f"{self.post}.json")))

    def test_pending_post_is_refused_unless_allowed(self):
        self.prices = FakePrices({"SOXL": hourly("2026-10-29T00:00:00Z", 47, 77.05)})          # nothing after the post yet
        self.analyse()
        url, why = f"https://x.com/TestCaller/status/{self.post}", "reviewed: the crop is the 2025 low of the SOXL chart"
        with self.assertRaisesRegex(add_call.Refused, "no price at or after the post"):
            add_call.preview(url, root=self.root, fetch=self.fetch, prices=self.prices, asset="SOXL", side="short", reason=why)
        p = add_call.preview(url, root=self.root, fetch=self.fetch, prices=self.prices, asset="SOXL", side="short", reason=why, allow_pending=True)
        self.assertEqual((p["record"]["status"], p["record"]["entry"]), ("pending", None))
        log = add_call.add(p["pending_file"], root=self.root, save_avatar=False, ohlc=None, now="2026-10-31T00:00:00Z")
        self.assertEqual(log["score_after_add"], p["score_after"])                        # a pending call is not scored yet
        self.assertTrue(os.path.exists(os.path.join(self.root, p["record_file"])))

    def test_a_joke_marker_never_sets_a_side(self):
        self.texts["post"] = "going long semis here lol"
        e = self.analyse()
        self.assertIsNone(e["side"])
        self.assertTrue(any("joke" in f for f in e["flags"]))
        self.assertEqual(e["status"], "needs_review")

    def test_no_readable_text_and_no_title(self):
        self.ocr_text = {"crop.png": "a | rt", "chart.png": "4 0 | ="}
        e = self.analyse()
        self.assertEqual((e["status"], e["asset_suggested"], e["confidence"]), ("no_asset", None, "none"))

    def test_add_call_needs_a_reason_and_records_the_evidence(self):
        self.analyse()
        url = f"https://x.com/TestCaller/status/{self.post}"
        with self.assertRaisesRegex(add_call.Refused, "needs --reason|written --reason"):
            add_call.preview(url, root=self.root, fetch=self.fetch, prices=self.prices, asset="SOXL", side="short")
        p = add_call.preview(url, root=self.root, fetch=self.fetch, prices=self.prices, asset="SOXL", side="short",
                             reason="the crop is the 2025 low of the SOXL chart it replies to; 'solid support' 91% lower is a short joke")
        ev = os.path.join(self.root, "intake", "images", f"{self.post}.json")
        ac = p["record"]["asset_choice"]
        self.assertEqual((ac["method"], ac["evidence"]["file"], ac["evidence"]["sha256"]), ("image_review", f"intake/images/{self.post}.json", read_images.sha256_file(ev)))
        self.assertIn("2025 low", ac["reason"])
        self.assertEqual((p["record"]["asset"]["name"], p["record"]["side"]), ("SOXL", -1))
        self.assertEqual(p["record"]["entry"]["at"], "2026-11-02T13:00:00Z")         # the first bar after a Friday-evening post


if __name__ == "__main__":
    unittest.main()
