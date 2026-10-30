"""Step 6 ingestion + detection tests (offline: the embed fetch is replaced by fixtures).
Run: python3 -m unittest -v tests.test_ingest_detect"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import detect  # noqa: E402
import ingest  # noqa: E402
import resolve  # noqa: E402

PID = "2115823513915290059"          # 2026-10-29T15:10:xxZ by the snowflake
URL = f"https://x.com/BobLoukas/status/{PID}"


def payload(**over):
    p = {"__typename": "Tweet", "id_str": PID, "created_at": resolve.snowflake_time(PID)[:19] + ".000Z",
         "user": {"screen_name": "BobLoukas"}, "text": "Bitcoin has to get moving here. https://t.co/x",
         "display_text_range": [0, 31], "entities": {"symbols": []}, "favorite_count": 10, "conversation_count": 2}
    p.update(over)
    return p


class Ingest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "sources"))

    def run_ingest(self, data, url=URL):
        return ingest.ingest(url, fetch=lambda pid: data, root=self.tmp.name, now="2026-10-30T00:00:00.000Z")

    def files(self):
        return [os.path.join(d, f) for d, _, fs in os.walk(os.path.join(self.tmp.name, "sources")) for f in fs]

    def test_saves_a_receipt_in_the_step3_format(self):
        path, r, created = self.run_ingest(payload())
        self.assertTrue(created)
        self.assertEqual(path, os.path.join(self.tmp.name, "sources", "bobloukas", "receipts", f"{PID}.json"))
        self.assertEqual(r["postedAt"], resolve.snowflake_time(PID)[:19] + ".000Z")
        self.assertEqual(r["text"], "Bitcoin has to get moving here.")  # display range drops the trailing link
        self.assertFalse(r["textTruncated"])
        self.assertEqual(r["dataSource"], "syndication")
        post = resolve.load_post(receipt=path)            # resolve.py accepts it as a receipt
        self.assertEqual(post["posted_at"], resolve.snowflake_time(PID))
        self.assertEqual(post["posted_at_source"], "receipt")

    def test_text_is_unescaped_and_reply_mentions_dropped(self):
        text = "@someone @grok Short S&amp;P 500 futures &gt; cash"
        _, r, _ = self.run_ingest(payload(text=text, display_text_range=[15, len(text)]))
        self.assertEqual(r["text"], "Short S&P 500 futures > cash")
        self.assertEqual(detect.detect(r["text"])["asset"], "STOCKS")

    def test_long_post_is_marked_truncated(self):
        _, r, _ = self.run_ingest(payload(note_tweet={"id": "x"}))
        self.assertTrue(r["textTruncated"])

    def test_cashtags_are_kept(self):
        _, r, _ = self.run_ingest(payload(entities={"symbols": [{"text": "xmr"}]}))
        self.assertEqual(r["cashtags"], ["XMR"])

    def test_timestamp_must_match_the_post_id(self):
        with self.assertRaisesRegex(ingest.IngestError, "embed time .* != id time"):
            self.run_ingest(payload(created_at="2026-10-29T15:11:59.000Z"))
        self.assertEqual(self.files(), [])

    def test_author_must_match_the_url(self):
        with self.assertRaisesRegex(ingest.IngestError, "is by @BobLoukas, not @someone"):
            self.run_ingest(payload(), url=f"https://x.com/someone/status/{PID}")
        self.assertEqual(self.files(), [])

    def test_unavailable_posts_fail_clearly_and_write_nothing(self):
        for data, why in [({}, "no post data"),
                          ({"__typename": "TweetTombstone", "tombstone": {"text": {"text": "This Post was deleted by the Post author."}}},
                           "deleted by the Post author")]:
            with self.assertRaisesRegex(ingest.IngestError, f"post {PID} unavailable .*{why}"):
                self.run_ingest(data)

        def gone(pid):
            raise ingest.IngestError(f"post {pid} unavailable (embed HTTP 404: deleted, private or never existed)")
        with self.assertRaisesRegex(ingest.IngestError, "HTTP 404"):
            ingest.ingest(URL, fetch=gone, root=self.tmp.name)
        self.assertEqual(self.files(), [])

    def test_existing_receipt_is_reused_not_overwritten(self):
        d = os.path.join(self.tmp.name, "sources", "bobloukas", "receipts")
        os.makedirs(d)
        full = {"id": PID, "text": "full graphql text", "url": URL, "authorHandle": "BobLoukas",
                "postedAt": resolve.snowflake_time(PID)[:19] + ".000Z"}
        with open(os.path.join(d, f"{PID}.json"), "w") as f:
            json.dump(full, f)
        _, r, created = ingest.ingest(URL, fetch=lambda pid: self.fail("must not fetch"), root=self.tmp.name)
        self.assertFalse(created)
        self.assertEqual(r["text"], "full graphql text")

    def test_bad_url(self):
        with self.assertRaisesRegex(ingest.IngestError, "not a post url"):
            ingest.ingest("https://example.com/x", fetch=lambda pid: {}, root=self.tmp.name)

    def test_embed_token_is_stable(self):
        self.assertEqual(ingest.embed_token(PID), ingest.embed_token(PID))
        self.assertRegex(ingest.embed_token(PID), r"^[1-9a-z]+$")


class Avatar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def fake(self, ctype, body=b"x"):
        class Resp:
            headers = type("H", (), {"get_content_type": staticmethod(lambda: ctype)})()
            def read(self): return body
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return lambda req, timeout=None: Resp()

    def data(self, src="https://pbs.twimg.com/profile_images/1/a_normal.jpg", handle="BobLoukas"):
        return {"user": {"screen_name": handle, "profile_image_url_https": src}}

    def test_non_image_avatar_is_refused(self):
        orig = ingest.urllib.request.urlopen
        ingest.urllib.request.urlopen = self.fake("text/html", b"<script>window.__pwned=1</script>")
        try:
            self.assertIsNone(ingest.save_avatar(self.data(), self.tmp.name))
        finally:
            ingest.urllib.request.urlopen = orig
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_avatar_from_another_host_is_refused(self):
        self.assertIsNone(ingest.save_avatar(self.data(src="https://evil.example/a.jpg"), self.tmp.name))
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_jpeg_avatar_is_saved_as_handle_jpg(self):
        orig = ingest.urllib.request.urlopen
        ingest.urllib.request.urlopen = self.fake("image/jpeg", b"\xff\xd8jpeg")
        try:
            path = ingest.save_avatar(self.data(), self.tmp.name)
        finally:
            ingest.urllib.request.urlopen = orig
        self.assertEqual(os.path.basename(path), "bobloukas.jpg")
        with open(os.path.join(self.tmp.name, "index.json")) as f:
            self.assertEqual(json.load(f)["bobloukas"]["file"], "bobloukas.jpg")


class Detect(unittest.TestCase):
    def d(self, text, **kw):
        return detect.detect(text, **kw)

    def test_single_asset_words(self):
        for text, asset in [("Bitcoin has to get moving here", "BTC"), ("End of December Gold will be a screaming buy", "GOLD"),
                            ("Stocks deep in their timing band", "STOCKS"), ("the S&P 500 at highs", "STOCKS"),
                            ("I hold a decent COPX position", "COPX"), ("crude rolling over", "OIL")]:
            self.assertEqual((self.d(text)["status"], self.d(text)["asset"]), ("detected", asset), text)

    def test_cashtags(self):
        self.assertEqual(self.d("$BTC looks ready")["asset"], "BTC")
        self.assertEqual(self.d("watching $spy")["asset"], "STOCKS")
        r = self.d("$XMR trading uncorrelated and strong.")
        self.assertEqual(r["status"], "needs_review")
        self.assertIn("$XMR has no price source", r["reason"])

    def test_longer_term_wins(self):
        r = self.d("copper miners breaking out after an 8-month pause")
        self.assertEqual((r["status"], r["asset"]), ("detected", "COPX"))
        self.assertEqual([m["term"] for m in r["matched"]], ["copper miners"])

    def test_whole_words_only(self):
        self.assertEqual(self.d("a golden opportunity in the oilfield of ideas")["status"], "needs_review")
        self.assertEqual(self.d("methane and stockholders")["status"], "needs_review")

    def test_several_assets_need_review(self):
        r = self.d("long bitcoin - short gold futures into Dec")
        self.assertEqual(r["status"], "needs_review")
        self.assertEqual(r["reason"], "several assets: BTC, GOLD")

    def test_nothing_found_needs_review(self):
        self.assertEqual(self.d("It is on thin ice for sure. It has to move now")["reason"], "no asset words or cashtags")
        self.assertEqual(self.d(None)["status"], "needs_review")

    def test_manual_override_wins(self):
        r = self.d("long bitcoin - short gold futures", manual="GOLD")
        self.assertEqual((r["status"], r["asset"]), ("manual", "GOLD"))


if __name__ == "__main__":
    unittest.main()
