"""Step 16: tools/add_call.py, offline. Each test runs in a scratch copy of the repo (records/,
sources/, web/) with saved embed fixtures (tests/fixtures/intake) and prices taken from the bundle's
own series, so preview and --add see exactly the same data.
Run: python3 -m unittest -v tests.test_add_call"""
import glob
import hashlib
import html.parser
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import add_call  # noqa: E402
import rate  # noqa: E402
import resolve  # noqa: E402

FIX = os.path.join(HERE, "tests", "fixtures", "intake")


def fixture(name):
    with open(os.path.join(FIX, f"{name}.json")) as f:
        return json.load(f)


def embed_for(fx):
    """A syndication-shaped response for a fixture post (what fetch_embed would return)."""
    pid = fx["url"].rsplit("/", 1)[1]
    return {"__typename": "Tweet", "id_str": pid, "created_at": fx["at"].replace("Z", ".000Z"), "text": fx["text"],
            "display_text_range": [0, len(fx["text"])], "entities": {"symbols": []}, "conversation_id_str": pid,
            "user": {"screen_name": fx["author"]}, "favorite_count": 1, "conversation_count": 0}


def tree_hash(root, sub):
    h = hashlib.sha256()
    for p in sorted(glob.glob(os.path.join(root, sub, "**", "*"), recursive=True)):
        if os.path.isfile(p):
            h.update(os.path.relpath(p, root).encode())
            with open(p, "rb") as f:
                h.update(hashlib.sha256(f.read()).digest())
    return h.hexdigest()


class Scratch(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="quanty-add-")
        for d in ("records", "sources", "web"):
            shutil.copytree(os.path.join(HERE, d), os.path.join(self.root, d))
        with open(os.path.join(self.root, "web", "data", "charts.json")) as f:
            bundle = json.load(f)
        snap = os.path.join(self.root, "snapshot.json")
        with open(snap, "w") as f:
            json.dump({a["name"]: a["series"] for a in bundle["assets"]}, f)
        self.prices = resolve.Prices(snapshot=snap)
        self.embeds = {}

    def tearDown(self):
        shutil.rmtree(self.root)

    def fetch(self, pid):
        if pid not in self.embeds:
            raise AssertionError(f"unexpected fetch of {pid}")
        return self.embeds[pid]

    def preview(self, name, **kw):
        fx = fixture(name)
        if not fx.get("existing"):
            self.embeds[fx["url"].rsplit("/", 1)[1]] = embed_for(fx)
        args = dict(fx.get("args", {}), **kw)
        return add_call.preview(fx["url"], root=self.root, fetch=self.fetch, prices=self.prices, now="2026-10-31T00:00:00.000Z", **args)

    def add(self, pending):
        return add_call.add(pending["pending_file"], root=self.root, fetch=self.fetch, save_avatar=True, ohlc=None, now="2026-10-31T00:00:00Z")

    def ratings(self):
        with open(os.path.join(self.root, "web", "data", "charts.json")) as f:
            return json.load(f)["ratings"]

    def preview_then_add(self, name):
        web0, rec0 = tree_hash(self.root, "web"), tree_hash(self.root, "records")
        p = self.preview(name)
        # preview alone changes nothing under web/ or records/
        self.assertEqual((tree_hash(self.root, "web"), tree_hash(self.root, "records")), (web0, rec0), name)
        self.assertTrue(os.path.exists(os.path.join(self.root, p["pending_file"])))
        before = self.ratings()["callers"].get(p["author"])
        log = self.add(p)
        after = self.ratings()["callers"][p["author"]]
        # the previewed score is the score after the add, exactly; so is the delta
        self.assertEqual(log["score_after_add"], p["score_after"])
        self.assertEqual(after["score"], p["score_after"]["score"])
        if before:
            self.assertEqual(after["score"] - before["score"], p["score_delta"])
        else:
            self.assertIsNone(p["score_delta"])
        self.assertTrue(log["matches_preview"])
        self.assertNotEqual(tree_hash(self.root, "web"), web0)
        self.assertTrue(os.path.exists(os.path.join(self.root, p["record_file"])))
        self.assertFalse(os.path.exists(os.path.join(self.root, p["pending_file"])))
        return p, log


class Fixtures(Scratch):
    def test_new_caller(self):
        p, log = self.preview_then_add("new_caller")
        self.assertTrue(p["new_caller"])
        self.assertIsNone(p["score_before"])
        r = p["record"]
        self.assertEqual((r["asset"]["name"], r["side"], r["side_choice"]["method"]), ("BTC", 1, "detector"))
        c = self.ratings()["callers"]["NewCaller"]
        self.assertEqual((c["scored"], c["label"]), (1, "small sample"))
        self.assertTrue(os.path.exists(os.path.join(self.root, "web", "caller-newcaller.html")))
        self.assertIn("none", log["avatar"])                     # no picture in the embed: initials on the pages
        with open(os.path.join(self.root, "web", "caller-newcaller.html")) as f:
            self.assertIn('data-avatar="initials"', f.read())

    def test_existing_caller(self):
        p, _ = self.preview_then_add("existing_caller")
        self.assertFalse(p["new_caller"])
        self.assertEqual((p["record"]["asset"]["name"], p["record"]["side"]), ("GOLD", -1))
        self.assertEqual(p["score_after"]["scored"], p["score_before"]["scored"] + 1)
        self.assertNotEqual(p["score_delta"], 0)

    def test_duplicate_is_refused(self):
        web0, rec0 = tree_hash(self.root, "web"), tree_hash(self.root, "records")
        with self.assertRaisesRegex(add_call.Refused, "duplicate: post 2116199680157647216 on GOLD is already recorded"):
            self.preview("duplicate")
        self.assertEqual((tree_hash(self.root, "web"), tree_hash(self.root, "records")), (web0, rec0))
        self.assertFalse(glob.glob(os.path.join(self.root, "intake", "pending", "*")))

    def test_no_detectable_asset_is_refused(self):
        web0, rec0 = tree_hash(self.root, "web"), tree_hash(self.root, "records")
        with self.assertRaisesRegex(add_call.Refused, "unreadable post: the detector cannot tell the asset"):
            self.preview("no_asset")
        self.assertEqual((tree_hash(self.root, "web"), tree_hash(self.root, "records")), (web0, rec0))
        self.assertFalse(glob.glob(os.path.join(self.root, "intake", "pending", "*")))

    def test_override_keeps_its_reason(self):
        p, _ = self.preview_then_add("override")
        with open(os.path.join(self.root, p["record_file"])) as f:
            rec = json.load(f)
        reason = fixture("override")["args"]["reason"]
        self.assertEqual((rec["asset"]["name"], rec["side"]), ("SILVER", -1))
        self.assertEqual((rec["asset_choice"]["method"], rec["asset_choice"]["reason"]), ("manual", reason))
        self.assertEqual((rec["side_choice"]["method"], rec["side_choice"]["reason"]), ("manual", reason))

    def test_hostile_text_stays_text(self):
        p, _ = self.preview_then_add("hostile")
        for name in (f"pos-{p['record']['post']['id']}_BTC.html", "caller-hostiletest.html", "index.html"):
            parser = Tags()
            with open(os.path.join(self.root, "web", name)) as f:
                parser.feed(f.read())
            self.assertFalse([t for t, a in parser.tags if t in ("svg", "iframe", "img") and not (t == "img" and a.get("src", "").startswith("avatars/"))], name)
            self.assertFalse([t for t, a in parser.tags if t == "script" and not a.get("src")], name)
            self.assertFalse([a for t, a in parser.tags if any(k.startswith("on") for k in a)], name)
        with open(os.path.join(self.root, "web", f"pos-{p['record']['post']['id']}_BTC.html")) as f:
            self.assertIn("&lt;script&gt;window.__pwned=1&lt;/script&gt;", f.read())


class Tags(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class Guards(Scratch):
    def test_stale_preview_is_refused(self):
        a = self.preview("new_caller")
        b = self.preview("existing_caller")
        self.add(b)                                               # the bundle changed after preview a
        with self.assertRaisesRegex(add_call.Refused, "stale preview"):
            self.add(a)

    def test_manual_choices_need_a_reason(self):
        with self.assertRaisesRegex(add_call.Refused, "--asset needs --reason"):
            self.preview("new_caller", asset="BTC", reason=None)
        with self.assertRaisesRegex(add_call.Refused, "--side needs --reason"):
            self.preview("new_caller", side="short")

    def test_both_sides_is_refused_without_a_choice(self):
        fx = fixture("new_caller")
        fx["text"] = "Closed my shorts and I am long bitcoin, but still holding the short position on the hedge"
        self.embeds[fx["url"].rsplit("/", 1)[1]] = embed_for(fx)
        with self.assertRaisesRegex(add_call.Refused, "states both sides"):
            add_call.preview(fx["url"], root=self.root, fetch=self.fetch, prices=self.prices)

    def test_the_new_record_shares_the_assets_bars(self):
        p = self.preview("new_caller")
        with open(os.path.join(self.root, "web", "data", "charts.json")) as f:
            have = dict(map(tuple, next(a for a in json.load(f)["assets"] if a["name"] == "BTC")["series"]))
        self.assertTrue(all(have[t] == px for t, px in p["record"]["series"] if t in have))
        self.assertEqual(p["revisions"], [])


class Side(unittest.TestCase):
    def test_side_words(self):
        import detect
        cases = {"Going long bitcoin here": 1, "I am shorting gold": -1, "closed my short, now long BTC": 1, "bullish on silver": 1,
                 "gm": None, "sold everything": None, "I'm long BTC and I'm short ETH": None}
        for t, want in cases.items():
            self.assertEqual(detect.detect_side(t)["side"], want, t)
        self.assertEqual(detect.detect_side("I'm long BTC and I'm short ETH")["status"], "ambiguous")


if __name__ == "__main__":
    unittest.main()
