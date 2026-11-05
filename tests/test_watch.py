"""Step 25, offline: the caller watcher (tools/watch_callers.py). One combined search per cycle, exactly-once
discovery over an overlapping window, fail-closed throttling (nothing marked, coverage not advanced), weak
answers, gaps closed by bounded per-caller catch-up, the reserved hourly budget, candidates written before
posts are marked seen, reposts ignored, parents kept, recorded calls skipped, unknown tickers flagged with
no provider call, and the real 2026-11-05 posts classified. Run: python3 -m unittest -v tests.test_watch"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import watch_callers as wc  # noqa: E402

T0 = dt.datetime(2026, 11, 5, 12, 0, tzinfo=dt.timezone.utc).timestamp()
CALLERS = ["goodalexander", "mert", "rosa_onchain"]


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def post(pid, handle, t, text, kind="post", **kw):
    return {"id": str(pid), "authorHandle": handle, "postedAt": iso(t), "text": text, "kind": kind, **kw}


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


class FakeX:
    """X search over a timeline: newest first, at most `cap` posts; `throttled` = every answer empty;
    `drop` = ids a (partial) answer leaves out; `error` = the harness fails."""
    def __init__(self, posts, cap=wc.CAPPED_AT * 3):
        self.posts, self.cap, self.calls = list(posts), cap, []
        self.throttled, self.error, self.drop = False, False, set()

    def __call__(self, q):
        self.calls.append(q)
        if self.error:
            return None, None, "harness exit 1"
        if self.throttled:
            return {"posts": [], "_sha256": "e"}, "run-t", None
        hs = {h.lower() for h in __import__("re").findall(r"from:(\w+)", q)}
        since = q.split("since:")[1].split()[0]
        until = q.split("until:")[1].split()[0] if "until:" in q else "9999-12-31"
        got = [p for p in self.posts if p["authorHandle"].lower() in hs and since <= p["postedAt"][:10] < until and p["id"] not in self.drop]
        got = sorted(got, key=lambda p: p["postedAt"], reverse=True)[:self.cap]
        return {"posts": got, "_sha256": "s" + str(len(self.calls))}, f"run-{len(self.calls)}", None


def chatter(handle, start, n, step=60, base=9_000_000):
    return [post(base + i, handle, start + i * step, f"gm {i}", kind="reply", replyTo={"postId": "1", "handle": "someone"}) for i in range(n)]


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="quanty-watch-")
        self.clock = Clock()
        self.timeline = chatter("rosa_onchain", T0 - 6 * 3600, 30) + chatter("mert", T0 - 5 * 3600, 30, base=8_000_000)
        self.x = FakeX(self.timeline)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def watch(self, budget=8):
        return wc.Watch(root=HERE, wdir=self.dir, search=self.x, clock=self.clock, budget=budget, handles=CALLERS)

    def run_cycle(self, minutes=10, budget=8):
        self.clock.t += minutes * 60
        return self.watch(budget).cycle()

    def candidates(self):
        return self.watch().rows("candidates.jsonl")


class Discovery(Base):
    def test_one_combined_search_and_a_quiet_baseline(self):
        out = self.run_cycle()
        self.assertEqual(out["result"], "baseline (everything marked seen, no cards)")
        self.assertEqual(len(self.x.calls), 1)
        self.assertTrue(self.x.calls[0].startswith("(from:goodalexander OR from:mert OR from:rosa_onchain) since:2026-11-04"))
        self.assertEqual(self.candidates(), [])

    def test_a_new_post_is_found_exactly_once(self):
        self.run_cycle()
        self.timeline.append(post(2118306510908596565, "goodalexander", self.clock.t + 120, "bought more $HYPE"))
        self.x.posts = self.timeline
        out = self.run_cycle()
        self.assertEqual((out["result"], out["counts"]["candidates"]), ("ok", 1))
        for _ in range(3):                                          # the same post in every later answer: no new card
            self.assertEqual(self.run_cycle()["counts"]["candidates"], 0)
        c = self.candidates()
        self.assertEqual([x["id"] for x in c], ["2118306510908596565"])
        self.assertEqual(c[0]["url"], "https://x.com/goodalexander/status/2118306510908596565")
        self.assertEqual((c[0]["legs"][0]["asset"], c[0]["legs"][0]["side"]), ("HYPE", "long"))
        self.assertLess(c[0]["found_after_s"], 15 * 60)

    def test_reposts_recorded_calls_and_chatter_make_no_card(self):
        self.run_cycle()
        t = self.clock.t
        self.x.posts += [post(1, "mert", t + 60, "$ZEC to the moon", kind="repost"),
                         post(1970742039722479782, "mert", t + 70, "I am irresponsibly long ZEC"),       # already a recorded call
                         post(3, "mert", t + 80, "great podcast today")]
        out = self.run_cycle()
        self.assertEqual({k: out["counts"][k] for k in ("reposts", "recorded", "no_asset", "candidates")},
                         {"reposts": 1, "recorded": 1, "no_asset": 1, "candidates": 0})

    def test_reply_and_quote_parents_are_kept(self):
        self.run_cycle()
        t = self.clock.t
        self.x.posts += [post(11, "goodalexander", t + 60, "if solar runs hard enough silver might move up faster", kind="reply",
                              replyTo={"postId": "2118292132876480727", "handle": "blknoiz06"}),
                         post(12, "mert", t + 70, "long $SOL", kind="quote", quoted={"id": "99", "url": "https://x.com/aeyakovenko/status/99"})]
        self.run_cycle()
        c = {x["id"]: x for x in self.candidates()}
        self.assertEqual(c["11"]["parent"], {"type": "reply", "id": "2118292132876480727", "handle": "blknoiz06"})
        self.assertEqual(c["12"]["parent"], {"type": "quote", "id": "99", "handle": "aeyakovenko"})


class FailClosed(Base):
    def test_a_throttled_cycle_marks_nothing_and_the_post_is_found_later(self):
        self.run_cycle()
        covered = self.watch().state["covered_until"]
        self.x.posts.append(post(21, "goodalexander", self.clock.t + 60, "bought gold"))
        self.x.throttled = True
        out = self.run_cycle()
        self.assertTrue(out["result"].startswith("throttled"))
        self.assertFalse(out["canary"]["ok"])
        st = self.watch().state
        self.assertNotIn("21", st["seen"])
        self.assertEqual(st["covered_until"], covered)
        self.assertEqual(self.candidates(), [])
        self.x.throttled = False
        self.run_cycle()
        self.assertEqual([c["id"] for c in self.candidates()], ["21"])

    def test_a_search_error_marks_nothing(self):
        self.run_cycle()
        self.x.posts.append(post(22, "mert", self.clock.t + 60, "long $SOL"))
        self.x.error = True
        out = self.run_cycle()
        self.assertTrue(out["result"].startswith("error"))
        self.assertNotIn("22", self.watch().state["seen"])
        self.x.error = False
        self.run_cycle()
        self.assertEqual([c["id"] for c in self.candidates()], ["22"])

    def test_a_weak_answer_does_not_advance_coverage(self):
        for _ in range(3):
            self.run_cycle()
        covered = self.watch().state["covered_until"]
        self.x.drop = {p["id"] for p in self.timeline[:50]}           # X degrades: most posts missing, not zero
        out = self.run_cycle()
        self.assertEqual(out["strength"], "weak")
        self.assertEqual(self.watch().state["covered_until"], covered)
        self.assertEqual(self.watch().state["degraded"], "weak answer")


class Gaps(Base):
    def test_a_burst_that_pushes_posts_out_is_caught_up_per_caller(self):
        self.x.cap = wc.CAPPED_AT                                      # X shows the newest 40 only
        self.timeline[:] = chatter("rosa_onchain", T0 - 3 * 86400, 10)  # quiet before the watcher starts
        self.x.posts = self.timeline
        self.run_cycle()
        t = self.clock.t
        missed = post(31, "goodalexander", t + 60, "bought silver")
        self.x.posts += [missed] + chatter("rosa_onchain", t + 120, 60, step=20, base=7_000_000)   # 60 replies after it
        out = self.run_cycle()
        self.assertIn("gap_opened", out)                                # the combined answer no longer reaches the post
        self.assertNotIn("31", [p["id"] for p in self.x(out["query"])[0]["posts"]])
        for _ in range(40):                                             # every window is answered twice before it closes
            out = self.run_cycle(minutes=10)
            if not self.watch().state["gaps"]:
                break
        self.assertEqual(self.watch().state["gaps"], [])
        found = {c["id"]: c for c in self.candidates()}
        self.assertIn("31", found)                                      # found by the catch-up search, not the combined one
        self.assertTrue(found["31"]["run"] and any(q.startswith("from:goodalexander since:") for q in self.x.calls))
        searches = [q for q in self.x.calls if q.startswith("from:goodalexander since:")]
        self.assertTrue(searches and "until:" in searches[0])                  # bounded windows, never open-ended

    def test_a_day_too_busy_to_cover_is_flagged_not_dropped(self):
        w = self.watch()
        w.state.update(baseline_done=True, covered_until=iso(self.clock.t - 3600).replace(".000Z", "Z"),
                       gaps=[{"start": "2026-11-05T09:00:00Z", "end": "2026-11-05T11:00:00Z", "opened": "x",
                              "callers": {"rosa_onchain": [["2026-11-05", "2026-11-06"]]}, "unresolvable": []}])
        w.save()
        self.x.cap = wc.CAPPED_AT
        self.x.posts = chatter("rosa_onchain", T0 - 30 * 60, 80, step=10, base=6_000_000)       # 80 posts after the gap start
        out = self.run_cycle(minutes=1)
        self.assertEqual(out["catch_up"]["result"], "one day too busy to cover: flagged")
        closed = self.watch().rows("gaps_closed.jsonl")
        self.assertEqual(closed[0]["unresolvable"][0]["handle"], "rosa_onchain")


class Budget(Base):
    def test_every_search_is_reserved_and_the_hourly_cap_holds(self):
        self.run_cycle(budget=3)
        self.x.throttled = True
        out = self.run_cycle(budget=3)                                  # discovery + canary: 3 reserved in the hour
        self.assertTrue(out["result"].startswith("throttled"))
        out = self.run_cycle(budget=3, minutes=5)
        self.assertTrue(out["result"].startswith("stopped: hourly search budget used"))
        purposes = [b["purpose"] for b in self.watch().rows("budget.jsonl")]
        self.assertEqual(purposes, ["discovery", "discovery", "canary"])
        self.assertEqual(len(self.x.calls), 3)
        self.x.throttled = False
        self.assertEqual(self.run_cycle(budget=3, minutes=61)["result"], "ok")   # the hour rolled over

    def test_one_cycle_at_a_time(self):
        import fcntl
        w = self.watch()
        lf = open(os.path.join(self.dir, "cycle.lock"), "a")
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            self.assertEqual(w.cycle()["result"], "skipped: another cycle is running")
            self.assertEqual(self.x.calls, [])
        finally:
            lf.close()


class Durability(Base):
    def test_a_crash_after_the_candidate_is_written_never_loses_or_repeats_it(self):
        self.run_cycle()
        self.x.posts.append(post(41, "mert", self.clock.t + 60, "long $SOL"))
        w = self.watch()
        w.save = lambda: (_ for _ in ()).throw(OSError("disk full"))      # the state save fails after the append
        self.clock.t += 600
        with self.assertRaises(OSError):
            w.cycle()
        self.assertEqual([c["id"] for c in self.candidates()], ["41"])
        self.assertNotIn("41", self.watch().state["seen"])
        self.run_cycle()
        self.assertEqual([c["id"] for c in self.candidates()], ["41"])     # still one
        self.assertIn("41", self.watch().state["seen"])


class Classify(unittest.TestCase):
    def test_an_unknown_ticker_is_flagged_without_any_provider_call(self):
        real = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network call"))
        try:
            c = wc.classify(post(51, "mert", T0, "aping $ZZQX here"))
        finally:
            urllib.request.urlopen = real
        self.assertTrue(c["candidate"])
        self.assertIsNone(c["legs"][0]["asset"])
        self.assertIn("does not look up new tickers", c["legs"][0]["flag"])

    def test_the_real_2026_11_05_posts(self):
        """The thread that started this step, classified as it was posted (texts from the public embed)."""
        ansem = wc.classify(post(2118292132876480727, "blknoiz06", T0, "bought gold"))
        alex = wc.classify(post(2118306510908596565, "goodalexander", T0, "if solar runs hard enough silver might move up faster",
                                kind="reply", replyTo={"postId": "2118292132876480727", "handle": "blknoiz06"}))
        ansem2 = wc.classify(post(2118311442441241038, "blknoiz06", T0, "ok bought silver too", kind="reply",
                                  replyTo={"postId": "2118306510908596565", "handle": "goodalexander"}))
        self.assertEqual([(l["asset"], l["side"]) for l in ansem["legs"]], [("GOLD", "long")])
        self.assertEqual([(l["asset"], l["side"]) for l in alex["legs"]], [("SILVER", "none")])     # "might move up": no side stated
        self.assertEqual(alex["parent"], {"type": "reply", "id": "2118292132876480727", "handle": "blknoiz06"})
        self.assertEqual([(l["asset"], l["side"]) for l in ansem2["legs"]], [("SILVER", "long")])
        self.assertTrue(alex["candidate"])


if __name__ == "__main__":
    unittest.main()


class CodexReview(Base):
    """The four defects the second review reproduced, each pinned."""
    def gap_for(self, handle):
        w = self.watch()
        w.state.update(baseline_done=True, covered_until=iso(self.clock.t).replace(".000Z", "Z"), ok_raw=[60, 60, 60],
                       gaps=[{"start": iso(self.clock.t - 7200).replace(".000Z", "Z"), "end": iso(self.clock.t - 3600).replace(".000Z", "Z"),
                              "opened": "x", "callers": {handle: [["2026-11-05", "2026-11-06"]]}, "unresolvable": []}])
        for p in self.x.posts:
            w.state["seen"][p["id"]] = p["postedAt"]
        w.save()

    def test_a_partial_catch_up_answer_never_closes_a_window(self):
        self.gap_for("goodalexander")
        self.x.posts += [post(61, "goodalexander", T0 - 5400, "bought gold"), post(62, "goodalexander", T0 - 5000, "gm")]
        self.x.drop = {"61"}                                       # X leaves the call out of every answer at first
        out = self.run_cycle(minutes=1)
        self.assertEqual(out["catch_up"]["result"], "window answered once: searched again before it is closed")
        self.x.drop = set()
        out = self.run_cycle(minutes=10)                           # a different answer: not closed yet, the post is found
        self.assertEqual(out["catch_up"]["result"], "window answered once: searched again before it is closed")
        self.assertIn("61", [c["id"] for c in self.candidates()])
        out = self.run_cycle(minutes=10)
        self.assertEqual(out["catch_up"]["result"], "window covered (two identical answers)")
        self.assertEqual(self.watch().state["gaps"], [])

    def test_a_real_quiet_day_recovers_through_the_canary(self):
        for _ in range(3):
            self.run_cycle()
        self.x.posts = [p for p in self.x.posts if p["authorHandle"] == "mert"][:10] + \
            chatter("rosa_onchain", T0 - 5 * 86400, 80, step=600, base=5_000_000)    # busy last week, quiet today
        out = self.run_cycle()
        self.assertEqual(out["strength"], "strong")
        self.assertTrue(out["canary"]["ok"])
        self.assertEqual(self.watch().state["covered_until"], out["started"])

    def test_a_stale_instance_cannot_overwrite_a_newer_cycle(self):
        self.run_cycle()
        old = self.watch()                                         # built now, used after another cycle ran
        self.x.posts.append(post(71, "mert", self.clock.t + 60, "long $SOL"))
        self.run_cycle()
        self.clock.t += 600
        old.cycle()
        st = self.watch().state
        self.assertIn("71", st["seen"])
        self.assertEqual([c["id"] for c in self.candidates()], ["71"])

    def test_a_torn_line_from_a_crash_is_skipped_and_still_counted(self):
        self.run_cycle(budget=3)
        with open(os.path.join(self.dir, "budget.jsonl"), "a") as f:
            f.write('{"t": 17938')                                  # the reservation write was cut off
        with open(os.path.join(self.dir, "candidates.jsonl"), "ab") as f:
            f.write('{"schema": "quanty.watch.v1", "text": "gm '.encode() + "🚀".encode()[:2])     # cut inside an emoji
        w = self.watch(3)
        self.assertEqual(w.used(), 2)                              # 1 real + 1 torn (the search may have run)
        self.x.posts.append(post(81, "mert", self.clock.t + 60, "long $SOL"))
        out = self.run_cycle(budget=3)
        self.assertEqual(out["result"], "ok")
        self.assertEqual([c["id"] for c in self.candidates()], ["81"])
        with open(os.path.join(self.dir, "candidates.jsonl"), "rb") as f:
            self.assertEqual(json.loads(f.read().splitlines()[-1])["id"], "81")   # appended on its own line
