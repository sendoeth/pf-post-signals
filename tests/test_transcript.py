"""Transcript pipeline (tools/transcript.py + tools/episode.py), offline: the glued YouTube timestamps
parse exactly, a stance is only accepted with a verbatim quote near its timestamp, stances on one
asset fold into one thesis with every timestamp kept, episodes are priced at the episode (last bar at
or before it), the pages are static and carry the notice, and the raw transcript stays private.
Run: python3 -m unittest -v tests.test_transcript"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import episode  # noqa: E402
import transcript as tr  # noqa: E402

EP = os.path.join(HERE, "sources", "episodes", "forward-guidance-2026-10-30")
PRIVATE = next((p for p in (os.path.join(HERE, "private", "transcripts", "forward-guidance-2026-10-30.txt"),       # where /episode keeps it
                             os.path.join(HERE, "private", "transcripts", "forward-guidance", "2026-10-30-weekly-roundup.txt"))
                if os.path.exists(p)), "missing")

SAMPLE = """Chapter 1: Intro
0:000 secondsNothing said here is a recommendation.
0:077 seconds[music]
1:021 minute, 2 secondsknow. Like, I was just willfully ignorant
9:009 minutesI'll I'll be here for the good times.
Chapter 2: Gold
10:0310 minutes, 3 secondsprobably just going to make the matters worse
10:5510 minutes, 55 secondsI'm sure we'll talk about metals a little bit, but uh I think gold is probably getting hit here as you know the energy short nations are trying
11:0411 minutes, 4 secondsto defend currency. The dollar's been been super strong. Uh, so it's probably
1:02:031 hour, 2 minutes, 3 secondslong episodes have hours
"""


def stance(**kw):
    s = {"asset": "GOLD", "kind": "thought", "direction": "bearish", "horizon": "now", "speaker": "Quinn Thompson",
         "speaker_confidence": "high", "t": "10:55",
         "quote": "I think gold is probably getting hit here as you know the energy short nations are trying to defend currency.",
         "reason": "energy-short nations sell gold"}
    s.update(kw)
    return s


def extraction(parsed_sha, *stances):
    return {"schema": tr.EXTRACTION_SCHEMA, "prompt_version": tr.PROMPT_VERSION, "transcript_sha256": parsed_sha,
            "model": "test", "stances": list(stances)}


class Parse(unittest.TestCase):
    def test_glued_timestamps(self):
        p = tr.parse(SAMPLE)
        got = [(s["ts"], s["text"][:12]) for s in p["segments"]]
        self.assertEqual(got[:4], [("0:00", "Nothing said"), ("0:07", "[music]"), ("1:02", "know. Like, "), ("9:00", "I'll I'll be")])
        self.assertEqual(got[4], ("10:03", "probably jus"))         # not 10:0 + "310 minutes"
        self.assertEqual(got[-1], ("1:02:03", "long episode"))
        self.assertEqual([(c["n"], c["title"], c["t"]) for c in p["chapters"]], [(1, "Intro", 0), (2, "Gold", 603)])

    def test_refuses_unreadable_and_backwards(self):
        with self.assertRaises(tr.TranscriptError):
            tr.parse("0:000 secondsok\nsome pasted junk line\n")
        with self.assertRaises(tr.TranscriptError):
            tr.parse("1:001 minuteok\n0:3030 secondsearlier\n")
        with self.assertRaises(tr.TranscriptError):
            tr.parse("0:0512 secondsduration does not match the stamp\n")
        with self.assertRaises(tr.TranscriptError):
            tr.parse("")

    def test_stacked_format(self):
        """YouTube's other copy: chapter title, then the timestamp on its own line, then the text."""
        p = tr.parse("Brewers Win the World Series\n0:00\nNothing said on for guidance is a recommendation\n0:07\n[music]\n"
                     "Fed Holds With Two Hawkish Dissents\n2:46\nyeah markets had broadly priced a pause\n1:02:03\nhours work too")
        self.assertEqual([(s["ts"], s["chapter"], s["text"][:12]) for s in p["segments"]],
                         [("0:00", 1, "Nothing said"), ("0:07", 1, "[music]"), ("2:46", 2, "yeah markets"), ("1:02:03", 2, "hours work t")])
        self.assertEqual([(c["n"], c["title"], c["t"]) for c in p["chapters"]], [(1, "Brewers Win the World Series", 0), (2, "Fed Holds With Two Hawkish Dissents", 166)])

    def test_stacked_format_refusals(self):
        for bad, why in [("0:00\n0:07\ntext", "has no text"), ("0:00\ntext\n0:07", "has no text"),
                         ("0:00\ntext\nstray line not before a timestamp\nmore", "stray line"),
                         ("0:00\ntext\n" + "x" * 120 + "\n0:07\nmore", "xxxx"),              # too long for a chapter title
                         ("0:10\ntext\n0:05\nearlier", "backwards"),
                         ("0:05\n0:1010 secondsActual quote", "0:05 has no text")]:          # a glued line is not the text of a bare stamp
            with self.assertRaises(tr.TranscriptError, msg=bad) as c:
                tr.parse(bad)
            self.assertIn(why, str(c.exception), bad)

    def test_both_formats_give_the_same_episode(self):
        p = tr.parse(SAMPLE)
        out, cur = [], None
        for sg in p["segments"]:
            if sg["chapter"] != cur:
                cur = sg["chapter"]
                out.append(next(c["title"] for c in p["chapters"] if c["n"] == cur))
            out += [sg["ts"], sg["text"]]
        q = tr.parse("\n".join(out))
        self.assertEqual(q["segments"], p["segments"])
        self.assertEqual(q["chapters"], p["chapters"])

    def test_quote_matching_spans_lines_and_ignores_punctuation(self):
        p = tr.parse(SAMPLE)
        self.assertEqual(tr.find_quote(p, "gold is probably getting hit here, as you know; the energy-short nations are trying to defend currency", 655), 655)
        self.assertIsNone(tr.find_quote(p, "gold is getting hit because energy short nations defend their currency", 655))   # a paraphrase
        self.assertEqual(tr.find_quote(p, "[laughter] I'll I'll be here for the good times", 540), 540)

    def test_prompt_is_fixed_and_carries_the_whole_transcript(self):
        p = tr.parse(SAMPLE)
        text = tr.render_prompt(p)
        self.assertIn("10:55 I'm sure we'll talk about metals", text)
        self.assertIn('"quote"', text)
        self.assertNotIn("FIELD_DOCS", text)
        self.assertEqual(tr.PROMPT_VERSION, "quanty.transcript.v2")


class Verify(unittest.TestCase):
    def setUp(self):
        self.p = tr.parse(SAMPLE)
        self.sha = "a" * 64

    def run_one(self, **kw):
        acc, rej = tr.verify(self.p, extraction(self.sha, stance(**kw)), self.sha)
        return acc, rej

    def test_good_stance(self):
        acc, rej = self.run_one()
        self.assertEqual((len(acc), rej), (1, []))
        self.assertEqual((acc[0]["seconds"], acc[0]["matched_t"], acc[0]["chapter"]), (655, "10:55", 2))

    def test_rejections(self):
        cases = {
            "quote not found verbatim": dict(quote="gold is falling because the energy short nations need to defend currency"),
            "more than 90s from": dict(t="0:07"),
            "not a priceable episode asset": dict(asset="NATGAS_EU"),
            "kind 'idea'": dict(kind="idea"),
            "direction 'long'": dict(direction="long"),
            "horizon 'soon'": dict(horizon="soon"),
            "quote has 3 words": dict(quote="gold is probably"),
            "missing reason": dict(reason=""),
            "bad timestamp": dict(t="ten fifty"),
        }
        for why, kw in cases.items():
            acc, rej = self.run_one(**kw)
            self.assertEqual(acc, [], why)
            self.assertIn(why, "; ".join(rej[0]["reasons"]), why)

    def test_refuses_other_transcript_or_prompt(self):
        with self.assertRaises(tr.TranscriptError):
            tr.verify(self.p, extraction("b" * 64, stance()), self.sha)
        ex = extraction(self.sha, stance())
        ex["prompt_version"] = "quanty.transcript.v0"
        with self.assertRaises(tr.TranscriptError):
            tr.verify(self.p, ex, self.sha)


class Consolidate(unittest.TestCase):
    def test_one_thesis_per_asset_with_every_timestamp(self):
        ms = [dict(stance(), t=t, seconds=s, matched_t=t, chapter=1, kind=k, direction=d, horizon=h)
              for t, s, k, d, h in [("18:54", 1134, "call", "neutral", "now"), ("10:55", 655, "thought", "bearish", "now"),
                                    ("17:56", 1076, "thought", "bullish", "long term")]]
        ms.append(dict(stance(asset="USD"), t="11:18", seconds=678, matched_t="11:18", chapter=1))
        th = tr.consolidate(ms)
        self.assertEqual([t["asset"] for t in th], ["GOLD", "USD"])            # calls first
        g = th[0]
        self.assertEqual((g["kind"], g["direction"], g["later"], g["mentions"]), ("call", "neutral", "bullish", 3))
        self.assertEqual([m["t"] for m in g["moments"]], ["10:55", "17:56", "18:54"])   # time order
        self.assertEqual((th[1]["kind"], th[1]["direction"]), ("thought", "bearish"))


class RealEpisode(unittest.TestCase):
    """The published Forward Guidance files agree with each other (and with the private transcript, when present)."""
    def test_published_files_are_consistent(self):
        th, ver = (json.load(open(os.path.join(EP, n))) for n in ("theses.json", "verified.json"))
        ex = json.load(open(os.path.join(EP, "extraction.json")))
        self.assertEqual(th["transcript_sha256"], ver["transcript_sha256"])
        self.assertEqual(th["transcript_sha256"], ex["transcript_sha256"])
        self.assertEqual(th["extraction_sha256"], tr.sha256(open(os.path.join(EP, "extraction.json"), "rb").read()))
        self.assertEqual(th["accepted"] + th["rejected"], len(ex["stances"]))
        self.assertEqual(th["accepted"], len(ver["accepted"]))
        self.assertEqual(th["accepted"], sum(t["mentions"] for t in th["theses"]))
        gold = next(t for t in th["theses"] if t["asset"] == "GOLD")
        self.assertIn("10:55", [m["t"] for m in gold["moments"]])                # the user's example moment
        self.assertEqual(gold["moments"][0]["kind"], "thought")
        oil = next(t for t in th["theses"] if t["asset"] == "OIL")
        self.assertEqual((oil["kind"], oil["direction"]), ("call", "bullish"))

    @unittest.skipUnless(os.path.exists(PRIVATE), "private transcript not in this checkout")
    def test_reverify_against_the_private_transcript(self):
        ex = json.load(open(os.path.join(EP, "extraction.json")))
        if ex["prompt_version"] != tr.PROMPT_VERSION:
            self.skipTest(f"published extraction uses {ex['prompt_version']}")
        blob, p = tr.read(PRIVATE)
        acc, rej = tr.verify(p, ex, tr.sha256(blob))
        th = json.load(open(os.path.join(EP, "theses.json")))
        self.assertEqual((len(acc), len(rej)), (th["accepted"], th["rejected"]))
        self.assertEqual(len(p["segments"]), 471)
        self.assertEqual(len(p["chapters"]), 13)

    def test_every_published_quote_is_short(self):
        for s in json.load(open(os.path.join(EP, "extraction.json")))["stances"]:
            self.assertLessEqual(len(tr.norm_words(s["quote"])), 60)

    def test_raw_transcript_is_private(self):
        r = subprocess.run(["git", "check-ignore", "-q", "private/transcripts/x.txt"], cwd=HERE)
        self.assertEqual(r.returncode, 0, "private/ must be gitignored")


class Build(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="quanty-ep-")
        os.makedirs(os.path.join(self.root, "data"))
        shutil.copy(os.path.join(HERE, "data", "episode_assets.json"), os.path.join(self.root, "data"))
        dst = os.path.join(self.root, "sources", "episodes", "forward-guidance-2026-10-30")
        os.makedirs(dst)
        for n in ("episode.json", "theses.json", "verified.json", "extraction.json"):
            shutil.copy(os.path.join(EP, n), dst)
        self.web = os.path.join(self.root, "web")
        os.makedirs(self.web)

    def tearDown(self):
        shutil.rmtree(self.root)

    @staticmethod
    def fake_fetch(info, since):
        base = {"GC=F": 4000.0, "SMH": 500.0}.get(info["symbol"], 100.0)
        return [["2026-10-29T20:00:00Z", base], ["2026-10-30T19:00:00Z", base * 0.98], ["2026-10-30T21:00:00Z", base * 0.97],
                ["2026-11-03T14:00:00Z", base * 1.01]]

    def test_priced_at_the_episode_and_rendered(self):
        b = episode.build(root=self.root, fetch=self.fake_fetch)
        ep = b["episodes"][0]
        gold = next(t for t in ep["theses"] if t["asset"] == "GOLD")
        self.assertEqual(gold["price"]["at_episode"], {"at": "2026-10-30T19:00:00Z", "price": 3920.0})    # last bar at or before 20:00
        self.assertAlmostEqual(gold["price"]["change"], 4040 / 3920 - 1)
        self.assertIsNone(gold["price"]["with_lean"])                       # neutral: no with/against
        semis = next(t for t in ep["theses"] if t["asset"] == "SEMIS")
        self.assertAlmostEqual(semis["price"]["with_lean"], -(505 / 490 - 1))     # bearish thesis, price up -> against
        oil = next(t for t in ep["theses"] if t["asset"] == "OIL")
        self.assertGreater(oil["price"]["with_lean"], 0)
        self.assertEqual(set(ep["files"]), {f"sources/episodes/forward-guidance-2026-10-30/{n}" for n in
                                           ("episode.json", "theses.json", "verified.json", "extraction.json")})
        self.assertNotIn("rating", json.dumps(b).lower().replace("are not rated", ""))
        # the cache makes the second build identical without fetching
        b2 = episode.build(root=self.root, offline=True)
        self.assertEqual(json.dumps(b, sort_keys=True), json.dumps(b2, sort_keys=True))

        episode.write(b, self.web)
        page = open(os.path.join(self.web, "episode-forward-guidance-2026-10-30.html"), encoding="utf-8").read()
        self.assertIn("Content-Security-Policy", page)
        self.assertEqual(re.findall(r"<script[^>]*src=\"([^\"]+)\"", page), ["assets/frame-guard.js"])   # static page, no app JS
        self.assertNotIn("<script>", page)
        self.assertEqual(page.count('<p class="nfa" id="nfa"'), 1)
        for h in ("1 · The episode in short", "2 · Theses", "3 · Every moment"):
            self.assertIn(h, page)
        moments = [m for t in ep["theses"] for m in t["moments"]]
        self.assertEqual(page.count('class="moment"'), len(moments))
        thought_theses = sum(t["kind"] == "thought" for t in ep["theses"])
        self.assertEqual(page.count('class="bub thought'), sum(m["kind"] == "thought" for m in moments) + thought_theses + 1)   # + the legend
        self.assertIn("I think gold is probably getting hit here", page)
        self.assertIn("the show page", page)                                 # no episode link yet -> says so
        lst = open(os.path.join(self.web, "episodes.html"), encoding="utf-8").read()
        self.assertIn('href="episode-forward-guidance-2026-10-30.html"', lst)
        self.assertEqual(lst.count('<p class="nfa" id="nfa"'), 1)

    def test_refresh_keeps_the_bars_up_to_the_episode(self):
        episode.build(root=self.root, fetch=self.fake_fetch)
        revised = lambda info, since: [["2026-10-29T20:00:00Z", 1.0], ["2026-10-30T19:00:00Z", 2.0],      # a vendor revision
                                       ["2026-11-03T14:00:00Z", 7.0], ["2026-11-04T14:00:00Z", 8.0]]
        b = episode.build(root=self.root, refresh=True, fetch=revised)
        gold = next(t for t in b["episodes"][0]["theses"] if t["asset"] == "GOLD")
        self.assertEqual(gold["price"]["at_episode"]["price"], 3920.0)                 # frozen
        self.assertEqual(gold["price"]["latest"], {"at": "2026-11-04T14:00:00Z", "price": 8.0})
        self.assertEqual([x[0] for x in gold["series"]][-2:], ["2026-11-03T14:00:00Z", "2026-11-04T14:00:00Z"])
        with self.assertRaises(SystemExit):                                            # a failed fetch stops the job
            episode.build(root=self.root, refresh=True, fetch=lambda info, since: [])

    def test_offline_without_cache_fails(self):
        with self.assertRaises(SystemExit):
            episode.build(root=self.root, offline=True)

    def test_text_is_escaped(self):
        p = os.path.join(self.root, "sources", "episodes", "forward-guidance-2026-10-30", "episode.json")
        m = json.load(open(p))
        m["title"] = '<img src=x onerror=alert(1)>'
        json.dump(m, open(p, "w"))
        b = episode.build(root=self.root, fetch=self.fake_fetch)
        episode.write(b, self.web)
        page = open(os.path.join(self.web, "episode-forward-guidance-2026-10-30.html"), encoding="utf-8").read()
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;img src=x", page)
        for bad in ('javascript:alert(1)', 'https://x.com/a" onclick="b', "http://plain.example"):
            m["url"] = bad
            json.dump(m, open(p, "w"))
            with self.assertRaises(SystemExit, msg=bad):
                episode.build(root=self.root, fetch=self.fake_fetch)


if __name__ == "__main__":
    unittest.main()
