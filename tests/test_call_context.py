"""Call context (tools/call_context.py), offline: a victory lap is traced back to the author's own
earlier call (reposts of other people's words are not theirs), later posts are labelled close /
trim / review / hold / mention, nothing disclosed keeps the trade open, throttled searches make the
result INCOMPLETE, and --apply writes the follow-ups into the recorded call's lifecycle (the real
Mert ZEC record closes at the first bar after the closing post).
Run: python3 -m unittest -v tests.test_call_context"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import call_context  # noqa: E402

EPOCH = 1288834974657
TODAY = dt.datetime(2026, 10, 31, 18, 0, tzinfo=dt.timezone.utc)


def pid_at(iso):
    ms = int(dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    return str((ms - EPOCH) << 22)


def post(iso, text, author="mert", kind="post", pid=None):
    return {"id": pid or pid_at(iso), "authorHandle": author, "postedAt": iso.replace("Z", ".000Z"), "text": text, "kind": kind,
            "completeness": "complete", "metrics": {}, "capturedAt": "2026-10-31T00:00:00.000Z"}


GLOAT_AT = "2025-09-29T15:33:40Z"
GLOAT_ID = "1972686220850541031"          # the real "did you fade" post id (its time matches)
CALL = post("2025-09-24T06:48:11Z", "@gainzy222 I am irresponsibly long ZEC", pid="1970742039722479782")
BEFORE = [post("2025-09-10T21:16:41Z", "bought some zec (and will buy more if it corrects more)", kind="repost"),   # @sacha's words
          post("2025-09-18T11:15:00Z", "bitcoin = http zcash = https"),
          CALL]


class Harness:
    def __init__(self, after, empty_from=None):
        self.after, self.empty_from, self.calls = after, empty_from, []

    def __call__(self, query):
        self.calls.append(query)
        since, until = query.split("since:")[1].split()[0], query.split("until:")[1].split()[0]
        if self.empty_from and since >= self.empty_from:
            return {"posts": [], "_run": "r", "_sha256": "s"}, "r", None
        pool = self.after if "(sold OR" in query else BEFORE
        got = [p for p in pool if since <= p["postedAt"][:10] < until]
        if not got:      # an active account: something in every window, so an empty page means throttling
            got = [post(since + "T12:00:00Z", "gm zec frens", author="someoneelse")]
        return {"posts": got, "_run": "r", "_sha256": "s"}, "r", None


def embed(pid=GLOAT_ID, at=GLOAT_AT, text="did you fade"):
    return {"__typename": "Tweet", "id_str": pid, "created_at": at.replace("Z", ".000Z"), "text": text, "display_text_range": [0, len(text)],
            "entities": {"symbols": []}, "conversation_id_str": pid, "user": {"screen_name": "mert"}}


class Scratch(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="quanty-ctx-")
        for d in ("records", "sources", "web", "data"):
            shutil.copytree(os.path.join(HERE, d), os.path.join(self.root, d))

    def tearDown(self):
        shutil.rmtree(self.root)

    def run_ctx(self, after, empty_from=None):
        h = Harness(after, empty_from)
        c = call_context.analyse(f"https://x.com/mert/status/{GLOAT_ID}", root=self.root, asset="binance:ZECUSDT", fetch=lambda pid: embed(),
                                 harness=h, today=TODAY, now="2026-10-31T18:00:00Z")
        return c, h


class Before(Scratch):
    def test_victory_lap_points_back_to_the_own_call(self):
        c, _ = self.run_ctx([])
        self.assertEqual(c["victory_lap"], "did you fade")
        self.assertEqual(c["suggested_call"]["id"], CALL["id"])                    # not the earlier repost of @sacha
        labels = {r["text"][:20]: r["label"] for r in c["before"]}
        self.assertEqual(labels["bought some zec (and"], "not theirs")
        self.assertEqual(labels["bitcoin = http zcash"], "own mention")
        self.assertEqual(c["side"], 1)

    def test_words_for_a_pair_asset(self):
        self.assertEqual(call_context.asset_words("binance:ZECUSDT"), ["zec", "zcash"])
        self.assertIn("bitcoin", call_context.asset_words("BTC"))


class After(Scratch):
    def test_nothing_disclosed_stays_open(self):
        c, h = self.run_ctx([post("2025-10-02T10:00:00Z", "zcash mentioned")])
        self.assertEqual(c["state"], "open: nothing disclosed after the call")
        after_q = [q for q in h.calls if "(sold OR sell" in q]                   # the after search asks for exit / hold words
        self.assertTrue(after_q)
        self.assertEqual(after_q[0].split("since:")[1][:10], "2025-09-29")

    def test_trim_then_hold(self):
        c, _ = self.run_ctx([post("2025-11-03T10:00:00Z", "took some profits on zec at 400"), post("2026-02-01T10:00:00Z", "still holding my zcash, not selling")])
        self.assertEqual([r["label"] for r in c["after"]], ["trim", "hold"])
        self.assertEqual(c["state"], "open: still holding as of 2026-02-01 (trimmed 1x)")

    def test_a_close(self):
        c, _ = self.run_ctx([post("2026-03-02T10:00:00Z", "sold all my zec today, rotated into sol")])
        self.assertEqual(c["after"][0]["label"], "close")
        self.assertTrue(c["state"].startswith("closed: close on 2026-03-02"))

    def test_advice_and_hints_do_not_close(self):
        c, _ = self.run_ctx([post("2025-12-01T10:00:00Z", "you should take some profits on zec here"), post("2025-12-05T10:00:00Z", "tighten stops on zcash")])
        self.assertEqual([r["label"] for r in c["after"]], ["not_close", "review"])
        self.assertEqual(c["state"], "open: nothing disclosed after the call")

    def test_throttled_search_is_incomplete(self):
        c, _ = self.run_ctx([], empty_from="2026-01-01")
        self.assertIn("INCOMPLETE", c["state"])
        self.assertTrue(any(w["status"] == "not searched" for w in c["searches"][1]["coverage"]))


class HoldWords(unittest.TestCase):
    """Mert's real phrasing: first-person position statements are holds; a slogan is not."""
    def label(self, text):
        return call_context.label_after({"authorHandle": "mert", "text": text, "kind": "post"}, "mert", ["zec", "zcash"], 1)[0]

    def test_holds(self):
        for t in ("zero, i do not sell zec", "i am going to bid the living shit out of zec and sol", "I sold him to buy zec",
                  "hello scott, nice to meet you, I sold my Bitcoin to buy Zcash", "Ill buy as much ZEC as you have rn", "still holding my zec"):
            self.assertEqual(self.label(t), "hold", t)

    def test_not_holds(self):
        self.assertEqual(self.label("bitcoin liberated money zcash liberates the person holding it"), "mention")
        self.assertEqual(self.label("I sold all my zec today"), "close")
        self.assertEqual(self.label("sold my zec for sol"), "close")       # selling THIS asset is an exit, not a hold

    def test_relabel_uses_the_saved_posts(self):
        c = {"post_id": "1", "posted_at": "2025-09-29T00:00:00Z", "author": "mert", "words": ["zec"], "side": 1, "suggested_call": None,
             "searches": [{"query": "q1", "posts": 0, "searches": 1, "coverage": [], "error": None},
                          {"query": "q2", "posts": 1, "searches": 1, "coverage": [{"since": "2025-09-29", "until": "2026-11-01", "status": "done"}], "error": None}], "url": "u", "asset": "binance:ZECUSDT", "text": "t", "victory_lap": None, "before": [],
             "after_raw": {"9": {"id": "9", "authorHandle": "mert", "postedAt": "2026-01-08T10:00:00.000Z", "text": "zero, i do not sell zec", "kind": "post"}}}
        tmp = tempfile.mkdtemp()
        try:
            out = call_context.relabel(c, root=tmp)
            self.assertEqual(out["state"], "open: still holding as of 2026-01-08")
            self.assertTrue(os.path.exists(os.path.join(tmp, "intake", "context", "1.json")))
        finally:
            shutil.rmtree(tmp)


class Apply(Scratch):
    def test_close_is_written_and_the_record_closes(self):
        rec_path = os.path.join(self.root, "records", "posts", "1970742039722479782_binance-ZECUSDT.json")
        self.assertTrue(os.path.exists(rec_path))
        closing = post("2026-03-02T10:15:00Z", "sold all my zec today")
        c, _ = self.run_ctx([closing])
        r = call_context.apply(c, root=self.root)
        self.assertEqual((r["followups"], r["status"]), (1, "closed"))
        with open(rec_path) as f:
            rec = json.load(f)
        self.assertEqual(rec["closed"]["post_id"], closing["id"])
        self.assertEqual(rec["closed"]["exit"]["at"], "2026-03-02T11:00:00Z")          # first bar after the post
        with open(os.path.join(self.root, "data", "lifecycle.json")) as f:
            life = json.load(f)["positions"]["1970742039722479782|binance:ZECUSDT"]
        self.assertEqual(life["followups"], [closing["id"]])
        self.assertEqual(life["overrides"][closing["id"]]["type"], "close")
        self.assertTrue(os.path.exists(os.path.join(self.root, "sources", "mert", "receipts", f"{closing['id']}.json")))
        with open(os.path.join(self.root, "web", "data", "charts.json")) as f:
            b = json.load(f)
        z = next(p for a in b["assets"] for p in a["posts"] if p["post"]["id"] == "1970742039722479782")
        self.assertEqual(z["status"], "closed")

    def test_nothing_to_apply(self):
        c, _ = self.run_ctx([])
        self.assertFalse(call_context.apply(c, root=self.root)["changed"])


class Reuse(Scratch):
    def test_load_hashes_the_bytes_it_parses(self):
        c, _ = self.run_ctx([])
        # the test pins "now" to 2026-10-31 18:00, so allow any age here (the real clock moves on) ...
        got, sha = call_context.load(GLOAT_ID, root=self.root, max_age_h=10 ** 6)
        import hashlib
        with open(os.path.join(self.root, "intake", "context", f"{GLOAT_ID}.json"), "rb") as f:
            self.assertEqual(sha, hashlib.sha256(f.read()).hexdigest())
        self.assertEqual(got["state"], c["state"])
        # ... and the age limit itself: a context file analysed long ago is not reused
        self.assertEqual(call_context.load(GLOAT_ID, root=self.root, max_age_h=0), (None, None))
        self.assertEqual(call_context.load("123", root=self.root), (None, None))

    def test_cli_fails_closed(self):
        import subprocess
        run = lambda *a: subprocess.run([sys.executable, os.path.join(HERE, "tools", "call_context.py"), f"https://x.com/mert/status/{GLOAT_ID}0", *a],
                                        capture_output=True, text=True, cwd=HERE)
        r = run("--asset", "binance:ZECUSDT", "--expect-sha", "0" * 64)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("only works with --reuse", r.stderr)
        r = run("--asset", "binance:ZECUSDT", "--apply", "--reuse", "--expect-sha", "0" * 64)       # no context file for this id
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no recent context file", r.stderr)


if __name__ == "__main__":
    unittest.main()
