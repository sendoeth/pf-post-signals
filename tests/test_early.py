"""Step 24, offline: early signals (tools/first_mention.py). Narrowing searches (yearly -> monthly -> daily,
empty windows searched twice, word-only hits and reposts not counted, resumable), mention vs position labels,
then / now / peak pricing across sources incl. 'before listing', the pages, and scores left unchanged.
Run: python3 -m unittest -v tests.test_early"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import first_mention as fm  # noqa: E402

TODAY = dt.datetime(2026, 11, 2, tzinfo=dt.timezone.utc)


def post(at, text, kind="post", author="mert", pid=None):
    return {"id": pid or str(abs(hash((at, text))) % 10 ** 18), "url": f"https://x.com/{author}/status/1", "authorHandle": author,
            "postedAt": at, "text": text, "kind": kind}


class FakeX:
    """X search over a fixed timeline. `flaky` windows answer empty on the first try; `throttle_after` = every answer
    (canary included) is empty after that many searches; `min_days` = narrower windows miss their posts (an X quirk)."""
    def __init__(self, posts, flaky=(), fail_on=None, throttle_after=None, min_days=0, cap=None, canary_counts=None):
        self.posts, self.flaky, self.fail_on, self.calls, self.cap = posts, set(flaky), fail_on, [], cap
        self.canary_counts = list(canary_counts or [])
        self.throttle_after, self.min_days = throttle_after, min_days

    def __call__(self, query):
        since, until = query.split("since:")[1].split()[0], query.split("until:")[1].split()[0]
        self.calls.append((since, until))
        if self.fail_on and since == self.fail_on:
            return None, None, "harness exit 1: rate limit"
        if self.throttle_after is not None and len(self.calls) > self.throttle_after:
            return {"posts": [], "_sha256": "s"}, "run", None
        if "(" not in query:                                                                   # the canary: the account's last days
            n = self.canary_counts.pop(0) if self.canary_counts else 1
            return {"posts": [post("2026-11-01T10:00:00.000Z", f"gm {i}") for i in range(n)], "_sha256": "s"}, "run", None
        if (since, until) in self.flaky and self.calls.count((since, until)) == 1:
            return {"posts": [], "_sha256": "s"}, "run", None
        if self.min_days and (fm.parse_day(until) - fm.parse_day(since)).days < self.min_days:
            return {"posts": [], "_sha256": "s"}, "run", None
        got = [p for p in self.posts if since <= p["postedAt"][:10] < until]
        if self.cap:                                                                           # X shows the newest few only
            got = sorted(got, key=lambda p: p["postedAt"])[-self.cap:]
        return {"posts": got, "_sha256": "s"}, "run", None


TIMELINE = [post("2019-05-02T10:00:00.000Z", "el sol brilla hoy"),                          # Spanish 'sol': a word hit, not the coin
            post("2021-03-09T08:00:00.000Z", "Solana devs are cooking", kind="repost"),       # not his words
            post("2021-03-17T15:30:00.000Z", "solana is the only chain that can scale like this"),
            post("2021-03-21T12:00:00.000Z", "SOL looks great"),
            post("2022-01-10T12:00:00.000Z", "bought more SOL today")]


class Narrowing(unittest.TestCase):
    def test_finds_the_first_real_mention(self):
        x = FakeX(TIMELINE, flaky=[("2018-01-01", "2019-01-01")])
        f = fm.Finder("mert", "SOL", search=x, today=TODAY)
        first = f.run()
        self.assertEqual(first["postedAt"], "2021-03-17T15:30:00.000Z")
        self.assertEqual(first["_matched"], ["solana"])
        levels = [e["level"] for e in f.log if e["level"] != "canary"]
        self.assertEqual(levels[0], "year")
        self.assertEqual(levels[-1], "month")                                              # a quiet month (2 posts) is complete: exact
        self.assertNotIn("day", levels)

    def test_a_busy_month_is_halved_to_the_day(self):
        busy = [post(f"2021-03-{d:02d}T09:00:00.000Z", f"SOL update {d}") for d in range(17, 31)] + \
               [post(f"2021-03-{d:02d}T21:00:00.000Z", f"solana thoughts {d}") for d in range(17, 31)]
        f = fm.Finder("mert", "SOL", search=FakeX(busy), today=TODAY)
        first = f.run()
        self.assertEqual(first["postedAt"], "2021-03-17T09:00:00.000Z")
        days = [e for e in f.log if e["level"] == "day"]
        self.assertTrue(days)
        self.assertLess(days[-1]["raw"], fm.COMPLETE_BELOW)

    def test_narrow_windows_missing_posts_keep_the_wider_answer(self):
        busy = [post(f"2021-03-{d:02d}T09:00:00.000Z", f"SOL update {d}") for d in range(10, 31)]
        f = fm.Finder("mert", "SOL", search=FakeX(busy, min_days=20), today=TODAY)
        first = f.run()
        self.assertEqual(first["postedAt"], "2021-03-10T09:00:00.000Z")
        self.assertIn("both halves came back empty", " ".join(f.notes))

    def test_throttling_stops_instead_of_reading_empty(self):
        root = tempfile.mkdtemp()
        try:
            out = fm.cmd_find("mert", "SOL", root=root, search=FakeX(TIMELINE, throttle_after=3), today=TODAY)
            self.assertTrue(out["status"].startswith("stopped"))
            self.assertIn("throttled", out["status"])
            self.assertNotIn("empty (confirmed)", [e["result"] for e in out["log"] if e["since"] >= "2018-01-01" and e["level"] == "year"])
            out = fm.cmd_find("mert", "SOL", root=root, search=FakeX(TIMELINE), today=TODAY)                 # resumed after the throttle
            self.assertEqual((out["status"], out["first"]["postedAt"]), ("found", "2021-03-17T15:30:00.000Z"))
        finally:
            shutil.rmtree(root)

    def test_a_weak_canary_does_not_confirm_an_empty_window(self):
        root = tempfile.mkdtemp()
        try:
            out = fm.cmd_find("mert", "SOL", root=root, search=FakeX(TIMELINE, canary_counts=[90, 71, 26]), today=TODAY)
            self.assertTrue(out["status"].startswith("stopped"))
            self.assertIn("26 of 90", out["status"])
            canaries = [e["result"] for e in out["log"] if e["level"] == "canary"]
            self.assertEqual(canaries[-1], "canary weak (26 of 90: throttling)")
            confirmed = [e for e in out["log"] if e["result"] == "empty (confirmed)"]
            self.assertEqual([e["canary_raw"] for e in confirmed], [90, 71])
            log = out["log"] + [{**confirmed[0], "since": "2016-01-01", "until": "2017-01-01", "canary_raw": 30}]   # vouched for by a weak canary
            f = fm.Finder("mert", "SOL", search=FakeX(TIMELINE), log=log, today=TODAY)
            self.assertIn(("2017-11-01", "2018-01-01"), f._cache)
            self.assertNotIn(("2016-01-01", "2017-01-01"), f._cache)                         # searched again on resume
        finally:
            shutil.rmtree(root)

    def test_empty_windows_are_searched_twice(self):
        x = FakeX(TIMELINE, flaky=[("2018-01-01", "2019-01-01")])
        f = fm.Finder("mert", "SOL", search=x, today=TODAY)
        f.run()
        y2018 = [e for e in f.log if e["since"] == "2018-01-01" and e["level"] == "year"]
        self.assertEqual([e["attempt"] for e in y2018], [1, 2])
        self.assertEqual(y2018[0]["result"], "empty (searching again)")
        y2017 = [e for e in f.log if e["since"] == "2017-11-01" and e["level"] == "year"]
        self.assertEqual([e["result"] for e in y2017], ["empty (searching again)", "empty (confirmed)"])

    def test_word_hits_and_reposts_do_not_count(self):
        x = FakeX(TIMELINE)
        f = fm.Finder("mert", "SOL", search=x, today=TODAY)
        f.run()
        y2019 = next(e for e in f.log if e["since"] == "2019-01-01")
        self.assertEqual((y2019["result"], y2019["raw"], y2019["confirmed"]), ("word hits only", 1, 0))
        m = next(e for e in f.log if e["level"] == "month" and e["since"] <= "2021-03-09" < e["until"] and e.get("reposts"))
        self.assertEqual(m["reposts"], 1)

    def test_a_full_window_of_word_hits_is_opened_not_skipped(self):
        noise = [post(f"2021-03-{d:02d}T09:00:00.000Z", f"el sol brilla {d}") for d in range(10, 31)]
        real = post("2021-03-02T09:00:00.000Z", "SOL is interesting")
        f = fm.Finder("mert", "SOL", search=FakeX(noise + [real], cap=15), today=TODAY)       # X shows 15 word hits, hides the mention
        first = f.run()
        self.assertEqual(first["postedAt"], "2021-03-02T09:00:00.000Z")
        mar = next(e for e in f.log if e["level"] == "month" and e["since"] == "2021-03-01")
        self.assertEqual((mar["result"], mar["raw"]), ("word hits only", 15))

    def test_a_search_error_stops_and_resumes(self):
        root = tempfile.mkdtemp()
        try:
            out = fm.cmd_find("mert", "SOL", root=root, search=FakeX(TIMELINE, fail_on="2021-01-01"), today=TODAY)
            self.assertTrue(out["status"].startswith("stopped"))
            self.assertEqual(out["log"][-1]["result"], "error")
            done = len([e for e in out["log"] if e["result"] != "error"])
            x = FakeX(TIMELINE)
            out = fm.cmd_find("mert", "SOL", root=root, search=x, today=TODAY)                   # resume
            self.assertEqual(out["status"], "found")
            self.assertNotIn(("2017-11-01", "2018-01-01"), x.calls)                             # confirmed windows are not searched again
            self.assertGreater(len(out["log"]), done)
        finally:
            shutil.rmtree(root)

    def test_nothing_found(self):
        f = fm.Finder("mert", "SOL", search=FakeX([]), today=TODAY)
        self.assertIsNone(f.run())

    def test_terms(self):
        t = fm.asset_terms("ZEC")
        self.assertEqual(fm.matches("long zec here", t), ["zec"])
        self.assertEqual(fm.matches("Zcash is back", t), ["zcash"])
        self.assertEqual(fm.matches("el sol brilla", fm.asset_terms("SOL")), [])           # 'sol' is a common word: only SOL / $SOL / solana


class Labels(unittest.TestCase):
    def test_mention_position_repost(self):
        self.assertEqual(fm.label_post({"text": "solana is fast"})["label"], "mention")
        lab = fm.label_post({"text": "I'm long SOL here"})
        self.assertEqual((lab["label"], lab["side"]), ("stated position", "long"))
        self.assertEqual(fm.label_post({"text": "bought SOL", "kind": "repost"})["label"], "not his (repost)")


class FakeSources(fm.Sources):
    """venue binance:SOLUSDT from 2020-08-11, binance:SOLBUSD from 2020-04-10, bitfinex:tSOLUSD from 2021-02-25."""
    START = {("binance", "SOLUSDT"): "2020-08-11T00:00:00Z", ("binance", "SOLBUSD"): "2020-04-10T00:00:00Z", ("bitfinex", "tSOLUSD"): "2021-02-25T00:00:00Z"}

    def __init__(self, venue_start=None):
        self.asset, self.venue = "SOL", ("binance", "SOLUSDT")
        self.order = [self.venue, ("binance", "SOLBUSD"), ("bitfinex", "tSOLUSD")]
        if venue_start:
            self.START = dict(self.START, **{self.venue: venue_start})

    def ms(self, iso):
        return int(dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)

    def first_bar(self, src, ms):
        start = self.ms(self.START[src])
        t = max(ms, start)
        t = t - t % 3_600_000 + (3_600_000 if t % 3_600_000 else 0)
        return t, 1.0 + (t - self.ms("2020-01-01T00:00:00Z")) / 86_400_000 / 10       # price grows 0.1 a day

    def start_of(self, src):
        return self.first_bar(src, 0)

    broken = ()                                                                                # sources that raise
    spike = None                                                                               # (src, hour iso, high): an hourly high
    day_spike = None                                                                           # (src, day iso, high): a daily high

    def start_of(self, src):
        if src in self.broken:
            raise OSError(f"{src[1]}: HTTP 451")
        return super().start_of(src)

    def daily_highs(self, src, start_ms, end_ms=None, hourly=False):
        step = 3_600_000 if hourly else 86_400_000
        end_ms = end_ms or self.ms("2026-11-02T00:00:00Z")
        out, t = [], start_ms - start_ms % step
        while t < end_ms:
            h = 500.0 if (not hourly and src == ("binance", "SOLBUSD") and t == self.ms("2020-07-01T00:00:00Z")) else 2.0
            if hourly and self.spike and (src, t) == (self.spike[0], self.ms(self.spike[1])):
                h = self.spike[2]
            if not hourly and self.day_spike and (src, t) == (self.day_spike[0], self.ms(self.day_spike[1] + "T00:00:00Z")):
                h = self.day_spike[2]
            out.append((t, h))
            t += step
        return out

    def latest(self):
        return self.ms("2026-11-02T02:00:00Z"), 190.0


class FirstCall(unittest.TestCase):
    def test_the_recorded_call_is_linked_not_mixed_in(self):
        calls = fm.recorded_calls(HERE, "mert", "ZEC")                                         # the scored 2025-09-24 'irresponsibly long ZEC'
        self.assertTrue(calls)
        self.assertEqual(calls[0]["posted_at"], "2025-09-24T06:48:11Z")
        self.assertEqual(fm.recorded_calls(HERE, "mert", "DOGE"), [])
        sig = {"post": {"posted_at": "2025-09-04T06:48:11Z"}, "prices": {"then": {"price": calls[0]["entry"]["price"] / 2}}}
        g = fm.call_gap(sig, calls)
        self.assertEqual((g["days"], g["after_first_mention"]), (20.0, True))
        self.assertAlmostEqual(g["price_move_before_call"], 2.0)
        self.assertIsNone(fm.call_gap(sig, []))


class Pricing(unittest.TestCase):
    def test_venue_covers_the_post(self):
        p = fm.price_signal("2021-03-17T15:30:00Z", FakeSources())
        self.assertEqual((p["then"]["source"], p["then"]["symbol"], p["then"]["at"], p["then"]["before_listing"]),
                         ("binance", "SOLUSDT", "2021-03-17T16:00:00Z", False))                    # first hourly bar at or after the post
        self.assertAlmostEqual(p["multiple_now"], 190.0 / p["then"]["price"])

    def test_an_older_pair_covers_an_earlier_post_and_its_peak_counts(self):
        p = fm.price_signal("2020-05-01T09:10:00Z", FakeSources())
        self.assertEqual((p["then"]["symbol"], p["then"]["before_listing"]), ("SOLBUSD", False))
        self.assertEqual((p["peak"]["symbol"], p["peak"]["day"], p["peak"]["high"]), ("SOLBUSD", "2020-07-01", 500.0))   # before the venue's history
        self.assertEqual([s["source"] for s in p["sources_tried"]], ["binance:SOLUSDT", "binance:SOLBUSD", "bitfinex:tSOLUSD"])

    def test_the_post_day_counts_for_the_peak(self):
        src = FakeSources()
        src.spike = (("binance", "SOLUSDT"), "2021-03-17T20:00:00Z", 900.0)                    # later on the post's own day
        p = fm.price_signal("2021-03-17T15:30:00Z", src)
        self.assertEqual((p["peak"]["day"], p["peak"]["high"]), ("2021-03-17", 900.0))
        src.spike = (("binance", "SOLUSDT"), "2021-03-17T12:00:00Z", 900.0)                    # before the post: not counted
        self.assertNotEqual(fm.price_signal("2021-03-17T15:30:00Z", src)["peak"]["high"], 900.0)

    def test_the_peak_is_never_below_the_then_price(self):
        p = fm.price_signal("2021-03-17T15:30:00Z", FakeSources())
        self.assertGreaterEqual(p["peak"]["high"], p["then"]["price"])

    def test_a_source_that_fails_is_listed_and_skipped(self):
        src = FakeSources()
        src.broken = (("binance", "SOLBUSD"),)
        p = fm.price_signal("2021-03-17T15:30:00Z", src)                                       # the venue covers the post: priced
        self.assertEqual((p["then"]["symbol"], p["then"]["before_listing"]), ("SOLUSDT", False))
        self.assertIn("451", next(t["error"] for t in p["sources_tried"] if t["source"] == "binance:SOLBUSD"))
        with self.assertRaisesRegex(RuntimeError, "cannot be shown"):                           # before listing needs every start
            fm.price_signal("2019-05-02T10:00:00Z", src)

    def test_a_failed_lookup_is_never_priced_as_before_listing(self):
        class NoBar(FakeSources):
            def first_bar(self, src, ms):
                if ms > 0:
                    raise OSError("timeout")
                return super().first_bar(src, ms)
        with self.assertRaisesRegex(RuntimeError, "did not return its bar"):
            fm.price_signal("2021-03-17T15:30:00Z", NoBar())                                   # covered by every source, all fail

    def test_a_venue_that_does_not_answer_stops_pricing(self):
        src = FakeSources()
        src.broken = (("binance", "SOLUSDT"),)
        with self.assertRaisesRegex(RuntimeError, "registered venue binance:SOLUSDT did not answer"):
            fm.price_signal("2021-03-17T15:30:00Z", src)

    def test_the_daily_refresh_never_reads_the_post_day_from_midnight(self):
        src = FakeSources()
        d = {"prices": fm.price_signal("2021-03-17T15:30:00Z", src)}
        first_peak = d["prices"]["peak"]["high"]
        src.day_spike = (("binance", "SOLUSDT"), "2021-03-17", 900.0)                          # the post day's daily bar (incl. hours before the post)
        fm.refresh_doc(d, src)
        self.assertEqual(d["prices"]["peak"]["high"], first_peak)
        src.day_spike = (("binance", "SOLUSDT"), "2024-03-18", 700.0)                          # a later day counts
        fm.refresh_doc(d, src)
        self.assertEqual((d["prices"]["peak"]["day"], d["prices"]["peak"]["high"]), ("2024-03-18", 700.0))
        self.assertEqual(d["prices"]["now"]["price"], 190.0)
        self.assertAlmostEqual(d["prices"]["multiple_peak"], 700.0 / d["prices"]["then"]["price"])

    def test_before_listing(self):
        p = fm.price_signal("2019-05-02T10:00:00Z", FakeSources())
        self.assertTrue(p["then"]["before_listing"])
        self.assertEqual((p["then"]["symbol"], p["then"]["at"]), ("SOLBUSD", "2020-04-10T00:00:00Z"))   # the earliest first bar of any source


class Pages(unittest.TestCase):
    def test_block_on_the_caller_and_coins_pages_and_scores_unchanged(self):
        import build_chart
        import coins_page
        import prerender
        root = tempfile.mkdtemp(prefix="quanty-early-")
        try:
            for d in ("records", "data", "web", "sources", "intake", "schema"):
                if os.path.exists(os.path.join(HERE, d)):
                    shutil.copytree(os.path.join(HERE, d), os.path.join(root, d), dirs_exist_ok=True)
            for d in (("sources", "early"), ("intake", "early")):                               # a clean run, not the real logs
                shutil.rmtree(os.path.join(root, *d), ignore_errors=True)
            for f in ("early.json",):
                if os.path.exists(os.path.join(root, "web", "data", f)):
                    os.remove(os.path.join(root, "web", "data", f))
            before = build_chart.build(os.path.join(root, "records"))
            x = FakeX(TIMELINE)
            fm.cmd_find("mert", "SOL", root=root, search=x, today=TODAY)
            receipt = os.path.join(root, "sources", "mert", "receipts", "test.json")
            os.makedirs(os.path.dirname(receipt), exist_ok=True)
            json.dump({"text": "solana is the only chain that can scale like this <script>x</script>"}, open(receipt, "w"))
            doc = fm.cmd_price("mert", "SOL", root=root, sources=FakeSources(), fetch_receipt=lambda url: (receipt, json.load(open(receipt)), True))
            self.assertTrue(doc["score_neutral"])
            json.dump({"schema": "quanty.affiliations.v1", "callers": {"mert": {"name": "Mert Mumtaz", "role": "Co-founder & CEO of Helius", "assets": ["SOL"],
                       "source": "https://www.helius.dev/about", "evidence": {"name": "Mert Mumtaz", "jobTitle": "Co-founder & CEO"}}}},
                      open(os.path.join(root, "data", "affiliations.json"), "w"))
            fm.build(root)
            web = os.path.join(root, "web")
            json.dump(before, open(os.path.join(web, "data", "charts.json"), "w"))
            prerender.main(web)
            coins_page.main(root)
            page = open(os.path.join(web, "caller-mert.html")).read()
            self.assertIn('data-field="early_signal" data-asset="SOL"', page)
            self.assertIn('data-field="affiliation"', page)
            self.assertIn("Co-founder &amp; CEO of Helius", page)
            self.assertIn("Score-neutral", page)
            self.assertNotIn("<script>x</script>", page)
            coins = open(os.path.join(web, "coins.html")).read()
            self.assertIn('id="early-SOL"', coins)
            after = build_chart.build(os.path.join(root, "records"))
            self.assertEqual(before["ratings"], after["ratings"])                               # early signals never touch a score
            self.assertNotIn("early", json.dumps(after["ratings"]))
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
