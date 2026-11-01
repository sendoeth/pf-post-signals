"""Episode intake (tools/llm_extract.py + tools/episode_intake.py), offline: the LLM provider fails
closed and never leaks its key, the model's summary / thesis lines are checked before use, the
headline lean is the near-term view, prepare writes only a private preview, and stage publishes
exactly the previewed extraction.
Run: python3 -m unittest -v tests.test_episode_intake"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import episode_intake as ei  # noqa: E402
import llm_extract as le  # noqa: E402
import transcript as tr  # noqa: E402

KEY = "sk-or-v1-" + "a" * 64
SAMPLE = """Chapter 1: Gold
10:5510 minutes, 55 secondsI'm sure we'll talk about metals a little bit, but uh I think gold is probably getting hit here as you know the energy short nations are trying
11:0411 minutes, 4 secondsto defend currency. The dollar's been been super strong. Uh, so it's probably
Chapter 2: Oil
41:1041 minutes, 10 secondsand to the right and has barely sniffed its daily trend. If you look out at any of the experies in early 27, which is
41:1741 minutes, 17 secondswhat we've been advocating for longing that that price action is during peace.
"""
GOLD = {"asset": "GOLD", "kind": "thought", "direction": "bearish", "horizon": "now", "speaker": "Quinn Thompson", "speaker_confidence": "high",
        "t": "10:55", "quote": "I think gold is probably getting hit here as you know the energy short nations are trying to defend currency.",
        "reason": "energy-short nations sell gold"}
OIL = {"asset": "OIL", "kind": "call", "direction": "bullish", "horizon": "months", "speaker": "Quinn Thompson", "speaker_confidence": "high",
       "t": "41:10", "quote": "If you look out at any of the experies in early 27, which is what we've been advocating for longing",
       "reason": "long early-2027 oil"}
REPLY = {"speakers": {"Quinn Thompson": "oil and gas background"}, "summary": [{"t": "10:55", "text": "Gold sold by energy-short nations."},
                                                                               {"t": "41:10", "text": "Long oil into 2027 expiries."}],
         "stances": [GOLD, OIL], "theses_text": {"GOLD": "bearish now on forced selling", "OIL": "long oil into 2027"}}


def api(reply_obj=None, text=None, finish="stop", model="anthropic/claude-opus-5.5"):
    content = text if text is not None else json.dumps(reply_obj)
    return {"id": "gen-1", "model": model, "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "choices": [{"message": {"content": content}, "finish_reason": finish}]}


class Provider(unittest.TestCase):
    def setUp(self):
        self.p = tr.parse(SAMPLE)
        self.sha = "a" * 64

    def run_with(self, response=None, raise_=None):
        sent = {}

        def post(req, timeout):
            sent["req"], sent["timeout"] = req, timeout
            if raise_:
                raise raise_
            return response
        return le.extract(self.p, self.sha, model="anthropic/claude-opus-5.5", key=KEY, post=post, now="2026-11-01T00:00:00Z"), sent

    def test_good_reply_carries_provenance(self):
        ex, sent = self.run_with(api(REPLY))
        self.assertEqual((ex["schema"], ex["prompt_version"], ex["transcript_sha256"]), (tr.EXTRACTION_SCHEMA, tr.PROMPT_VERSION, self.sha))
        self.assertEqual(ex["model"], "anthropic/claude-opus-5.5 (via OpenRouter)")
        self.assertEqual(ex["response_id"], "gen-1")
        self.assertEqual(len(ex["stances"]), 2)
        body = json.loads(sent["req"].data)
        self.assertEqual((body["temperature"], body["response_format"]), (0, {"type": "json_object"}))
        self.assertIn("10:55 I'm sure we'll talk about metals", body["messages"][1]["content"])     # the whole transcript
        self.assertIn("GOLD: Gold", body["messages"][1]["content"])                                   # the asset list
        self.assertEqual(sent["req"].get_header("Authorization"), f"Bearer {KEY}")
        self.assertNotIn(KEY, json.dumps(ex))

    def test_fenced_json_is_accepted(self):
        ex, _ = self.run_with(api(text="```json\n" + json.dumps(REPLY) + "\n```"))
        self.assertEqual(len(ex["stances"]), 2)

    def test_fails_closed(self):
        cases = [(api(text="here you go: {"), "valid JSON"), (api({"theses": []}), "no stances list"), (api(REPLY, finish="length"), "cut off"),
                 ({"error": "x"}, "no message")]
        for resp, why in cases:
            with self.assertRaises(le.ExtractError) as c:
                self.run_with(resp)
            self.assertIn(why, str(c.exception))
        err = urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(json.dumps({"error": {"message": f"bad key {KEY}"}}).encode()))
        with self.assertRaises(le.ExtractError) as c:
            self.run_with(raise_=err)
        self.assertIn("HTTP 401", str(c.exception))
        self.assertNotIn(KEY, str(c.exception))
        with self.assertRaises(le.ExtractError) as c:
            self.run_with(raise_=urllib.error.URLError("timed out"))
        self.assertIn("request failed", str(c.exception))

    def test_key_file(self):
        with self.assertRaises(le.ExtractError):
            le.read_key("/nonexistent/key")
        d = tempfile.mkdtemp()
        try:
            open(os.path.join(d, "k"), "w").write("\n")
            with self.assertRaises(le.ExtractError):
                le.read_key(os.path.join(d, "k"))
            open(os.path.join(d, "k"), "w").write(KEY + "\n")
            self.assertEqual(le.read_key(os.path.join(d, "k")), KEY)
        finally:
            shutil.rmtree(d)


class Extras(unittest.TestCase):
    def test_summary_and_lines_are_checked(self):
        p = tr.parse(SAMPLE)
        ex = dict(REPLY, summary=[{"t": "41:10", "text": "Long oil into 2027 expiries."}, {"t": "99:00", "text": "after the end of the episode"},
                                  {"t": "10:55", "text": "short"}, {"bad": 1}, {"t": "10:55", "text": "Gold sold by energy-short nations."}],
                  theses_text={"GOLD": "ok line here", "NATGAS": "no stance on it", "OIL": "x" * 300})
        acc = [dict(GOLD), dict(OIL)]
        extras, notes = tr.verify_extras(p, ex, acc)
        self.assertEqual([s["t"] for s in extras["summary"]], ["10:55", "41:10"])           # sorted, bad ones dropped
        self.assertEqual(extras["theses_text"], {"GOLD": "ok line here"})
        joined = "; ".join(notes)
        for why in ("99:00", "'NATGAS' dropped", "OIL dropped: length 300", "summary #3 dropped"):
            self.assertIn(why, joined)


class Headline(unittest.TestCase):
    def m(self, t, s, kind, d, h):
        return dict(GOLD, asset="SEMIS", t=t, seconds=s, matched_t=t, chapter=1, kind=kind, direction=d, horizon=h)

    def test_a_next_year_call_does_not_set_today(self):
        th = tr.consolidate([self.m("19:54", 1194, "thought", "bearish", "months"), self.m("27:14", 1634, "call", "bearish", "long term"),
                             self.m("38:10", 2290, "call", "neutral", "next year"), self.m("39:11", 2351, "thought", "bearish", "months")])[0]
        self.assertEqual((th["kind"], th["direction"], th["later"]), ("call", "bearish", "neutral"))

    def test_a_near_call_wins(self):
        th = tr.consolidate([self.m("10:55", 655, "thought", "bearish", "now"), self.m("18:04", 1084, "thought", "bullish", "long term"),
                             self.m("19:03", 1143, "call", "neutral", "now")])[0]
        self.assertEqual((th["direction"], th["later"]), ("neutral", "bullish"))


class Intake(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="quanty-intake-")
        for d in ("data",):
            os.makedirs(os.path.join(self.root, d))
        shutil.copy(os.path.join(HERE, "data", "episode_assets.json"), os.path.join(self.root, "data"))
        self.txt = os.path.join(self.root, "in.txt")
        open(self.txt, "w").write(SAMPLE)

    def tearDown(self):
        shutil.rmtree(self.root)

    def fake(self, reply=REPLY):
        return lambda parsed, sha: dict(reply, schema=tr.EXTRACTION_SCHEMA, prompt_version=tr.PROMPT_VERSION, transcript_sha256=sha, model="fake")

    @staticmethod
    def fetch(info, since):
        return [["2026-10-29T20:00:00Z", 100.0], ["2026-10-30T19:00:00Z", 101.0], ["2026-11-02T15:00:00Z", 103.0]]

    def test_prepare_is_private_and_stage_publishes_exactly_it(self):
        r = ei.prepare(self.txt, "2026-10-30", "Forward Guidance (Blockworks)", "Weekly Roundup", None, "20:00", root=self.root, extract=self.fake())
        self.assertEqual(r["slug"], "forward-guidance-2026-10-30")
        self.assertEqual((r["accepted"], r["rejected"]), (2, 0))
        self.assertIn("Gold: thought bearish · 1 moments: 10:55", r["text"])
        self.assertIn(f"PREVIEW_SHA {r['preview_sha']}", r["text"])
        self.assertTrue(os.path.exists(os.path.join(self.root, "private", "transcripts", "forward-guidance-2026-10-30.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "sources")))              # nothing public before stage
        with self.assertRaises(ei.IntakeError):
            ei.stage(r["slug"], "0" * 64, root=self.root, fetch=self.fetch)
        out = ei.stage(r["slug"], r["preview_sha"], root=self.root, fetch=self.fetch)
        self.assertIn("staged forward-guidance-2026-10-30: 2 theses", out)
        pub = os.path.join(self.root, "sources", "episodes", "forward-guidance-2026-10-30")
        self.assertEqual(tr.sha256(open(os.path.join(pub, "extraction.json"), "rb").read()), r["extraction_sha"])
        self.assertEqual(ei.preview_sha(pub), r["preview_sha"])                              # all four files as previewed
        meta = json.load(open(os.path.join(pub, "episode.json")))
        self.assertEqual((meta["reference_at"], meta["url"], meta["speakers"]), ("2026-10-30T20:00:00Z", None, ["Quinn Thompson"]))
        self.assertEqual(meta["theses_text"]["OIL"], "long oil into 2027")
        page = open(os.path.join(self.root, "web", "episode-forward-guidance-2026-10-30.html"), encoding="utf-8").read()
        self.assertIn("link not added yet", page)
        self.assertNotIn("energy short nations are trying\nto defend", page)               # no raw transcript lines

    def test_any_edited_preview_file_blocks_staging(self):
        for n in ei.PREVIEW_FILES:
            r = ei.prepare(self.txt, "2026-10-30", "FG", "T", None, "20:00", root=self.root, extract=self.fake())
            path = os.path.join(self.root, "private", "episodes", r["slug"], n)
            d = json.load(open(path))
            d["tampered"] = True                     # e.g. a thesis flipped from bullish to bearish after the preview
            json.dump(d, open(path, "w"))
            with self.assertRaises(ei.IntakeError, msg=n):
                ei.stage(r["slug"], r["preview_sha"], root=self.root, fetch=self.fetch)
            self.assertFalse(os.path.exists(os.path.join(self.root, "sources")), n)

    def test_rejections_are_reported_and_an_empty_episode_never_stages(self):
        bad = dict(REPLY, stances=[dict(GOLD, quote="gold falls because energy short countries defend their money now")])
        r = ei.prepare(self.txt, "2026-10-30", "FG", "T", None, "20:00", root=self.root, extract=self.fake(bad))
        self.assertEqual((r["accepted"], r["rejected"]), (0, 1))
        self.assertIn("quote not found verbatim", r["text"])
        with self.assertRaises(ei.IntakeError):
            ei.stage(r["slug"], r["preview_sha"], root=self.root, fetch=self.fetch)

    def test_metadata_is_checked(self):
        for args, why in [(("2026-13-01", "FG", "T", None, "20:00"), "YYYY-MM-DD"), (("2099-01-01", "FG", "T", None, "20:00"), "future"),
                          (("2026-10-30", "FG", "T", "javascript:alert(1)", "20:00"), "https://"), (("2026-10-30", "FG", "T", None, "25:00"), "HH:MM"),
                          (("2026-10-30", "", "T", None, "20:00"), "show"), (("2026-10-30", "FG", "T\x00", None, "20:00"), "title")]:
            with self.assertRaises(ei.IntakeError) as c:
                ei.prepare(self.txt, *args, root=self.root, extract=self.fake())
            self.assertIn(why, str(c.exception))

    def test_a_different_transcript_for_the_same_slug_needs_replace(self):
        ei.prepare(self.txt, "2026-10-30", "FG", "T", None, "20:00", root=self.root, extract=self.fake())
        open(self.txt, "a").write("41:2041 minutes, 20 secondsmore words here\n")
        with self.assertRaises(ei.IntakeError):
            ei.prepare(self.txt, "2026-10-30", "FG", "T", None, "20:00", root=self.root, extract=self.fake())
        r = ei.prepare(self.txt, "2026-10-30", "FG", "T", None, "20:00", root=self.root, extract=self.fake(), replace=True)
        self.assertEqual(r["accepted"], 2)

    def test_slug(self):
        self.assertEqual(ei.slugify("Forward Guidance (Blockworks)", "2026-10-30"), "forward-guidance-2026-10-30")
        self.assertEqual(ei.slugify("Bankless!! Ep", "2026-01-02"), "bankless-ep-2026-01-02")


if __name__ == "__main__":
    unittest.main()
