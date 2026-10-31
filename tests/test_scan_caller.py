"""Step 17: tools/scan_caller.py, offline with a fake research harness. Windows and the 12-month
cutoff, budget stops and resume, rate limits and empty pages, window splits, the labels, and the
report -> review -> add path in a scratch copy of the repo (projected score = post-add score,
nothing under web/ or records/ changes before add, other callers unchanged).
Run: python3 -m unittest -v tests.test_scan_caller"""
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
import resolve  # noqa: E402
import scan_caller  # noqa: E402
from tests.test_add_call import tree_hash  # noqa: E402

EPOCH = 1288834974657
NOW = dt.datetime(2026, 10, 31, 3, 0, tzinfo=dt.timezone.utc)
URL = "https://x.com/ScanTest/status/2116199680157647216"


def pid_at(iso):
    ms = int(dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    return str((ms - EPOCH) << 22)


def post(iso, text, author="ScanTest", kind="post"):
    return {"id": pid_at(iso), "authorHandle": author, "postedAt": iso.replace("Z", ".000Z"), "text": text, "kind": kind,
            "completeness": "complete", "metrics": {"likes": 1}, "capturedAt": "2026-10-31T03:00:00.000Z"}


class FakeHarness:
    """Answers "from:X since:A until:B" with the posts in [A, B); scripted failures by call number."""
    def __init__(self, posts, fail=None, empty=None, fill=True):
        self.posts, self.fail, self.empty, self.calls, self.fill = posts, fail or {}, empty or set(), [], fill

    def __call__(self, query):
        self.calls.append(query)
        n = len(self.calls)
        if n in self.fail:
            return None, None, self.fail[n]
        since, until = query.split("since:")[1].split()[0], query.split("until:")[1].split()[0]
        got = [] if n in self.empty else [p for p in self.posts if since <= p["postedAt"][:10] < until]
        if self.fill and n not in self.empty and not got:      # an active account: a "gm" post in an otherwise quiet window
            got = [post(since + "T09:00:00Z", "gm")]
        return {"posts": got, "_sha256": f"sha{n}", "_run": f"run{n}"}, f"run{n}", None


class Scratch(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="quanty-scan-")
        for d in ("records", "sources", "web"):
            shutil.copytree(os.path.join(HERE, d), os.path.join(self.root, d))

    def tearDown(self):
        shutil.rmtree(self.root)

    def log(self):
        with open(os.path.join(self.root, "intake", "scans", "scantest", "scan_log.json")) as f:
            return json.load(f)


class Windows(Scratch):
    def test_twelve_months_in_ten_day_windows(self):
        ws = scan_caller.windows(dt.datetime(2025, 10, 31), dt.datetime(2026, 11, 1))
        self.assertEqual((ws[0]["since"], ws[-1]["until"]), ("2025-10-31", "2026-11-01"))
        self.assertTrue(all(a["until"] == b["since"] for a, b in zip(ws, ws[1:])))
        self.assertEqual(len(ws), 37)

    def test_cutoff_other_authors_and_bad_ids_are_left_out(self):
        posts = [post("2026-10-20T10:00:00Z", "I am long bitcoin here"), post("2025-10-01T10:00:00Z", "old: I am long bitcoin"),
                 post("2026-10-21T10:00:00Z", "I am long bitcoin", author="SomeoneElse")]
        bad = post("2026-10-22T10:00:00Z", "id does not match the time")
        bad["id"] = pid_at("2026-10-22T11:00:00Z")
        h = FakeHarness(posts + [bad])
        log = scan_caller.scan(URL, root=self.root, harness=h, budget=100, now=NOW)
        def text(v):
            with open(os.path.join(self.root, v["receipt"])) as f:
                return json.load(f)["text"]
        kept = {k: v for k, v in log["posts"].items() if "receipt" in v and text(v) != "gm"}
        self.assertEqual(list(kept), [posts[0]["id"]])                      # the year-old post and the other author are out
        self.assertEqual(log["posts"][bad["id"]], {"skipped": "post time does not match its id"})
        self.assertEqual(log["runs"][-1]["stop"]["reason"], "complete")
        self.assertTrue(os.path.exists(os.path.join(self.root, kept[posts[0]["id"]]["receipt"])))


class Resume(Scratch):
    def test_budget_stop_and_resume(self):
        posts = [post("2026-10-20T10:00:00Z", "I am long bitcoin here"), post("2026-01-05T10:00:00Z", "I am shorting gold")]
        h = FakeHarness(posts)
        log = scan_caller.scan(URL, root=self.root, harness=h, budget=5, now=NOW)
        self.assertEqual(log["runs"][-1]["stop"]["reason"], "budget")
        self.assertEqual(log["coverage"]["windows_done"], 5)
        first = len(h.calls)
        log = scan_caller.scan(URL, root=self.root, harness=h, budget=100, now=NOW)
        self.assertEqual(log["runs"][-1]["stop"]["reason"], "complete")
        self.assertEqual(len(h.calls) - first, len(log["windows"]) - 5)       # done windows are not searched again
        self.assertTrue(all(p["id"] in log["posts"] for p in posts))
        self.assertEqual(len(log["runs"]), 2)

    def test_rate_limit_stops_and_resumes(self):
        h = FakeHarness([post("2026-10-20T10:00:00Z", "I am long bitcoin")], fail={3: "Error: HTTP 429 Too Many Requests"})
        log = scan_caller.scan(URL, root=self.root, harness=h, budget=100, now=NOW)
        self.assertEqual(log["runs"][-1]["stop"]["reason"], "rate_limit")
        self.assertEqual([w["status"] for w in log["windows"]][:3], ["done", "done", "stopped"])
        log = scan_caller.scan(URL, root=self.root, harness=h, budget=100, now=NOW)
        self.assertEqual(log["runs"][-1]["stop"]["reason"], "complete")
        self.assertEqual(log["windows"][2]["status"], "done")

    def test_empty_pages_in_a_row_stop_the_run(self):
        h = FakeHarness([post("2026-10-20T10:00:00Z", "I am long bitcoin")], empty={4, 5, 6})       # throttled from search 4
        log = scan_caller.scan(URL, root=self.root, harness=h, budget=100, now=NOW)
        self.assertEqual(log["runs"][-1]["stop"]["reason"], "empty_result")
        self.assertEqual([w["status"] for w in log["windows"][:7]], ["done", "done", "done", "pending", "pending", "pending", "pending"])
        h.empty = set()
        log = scan_caller.scan(URL, root=self.root, harness=h, budget=100, now=NOW)
        self.assertEqual(log["runs"][-1]["stop"]["reason"], "complete")
        self.assertTrue(all(w["status"] in ("done", "split") for w in log["windows"]))

    def test_a_single_empty_window_needs_a_second_run(self):
        h = FakeHarness([], empty={2})
        log = scan_caller.scan(URL, root=self.root, harness=h, budget=100, now=NOW)
        self.assertEqual(log["windows"][1]["status"], "empty_once")
        self.assertEqual(log["runs"][-1]["stop"]["reason"], "unconfirmed_empty")
        n = len(h.calls)
        h.empty = {n + 1}                       # the next run sees it empty again -> confirmed
        log = scan_caller.scan(URL, root=self.root, harness=h, budget=100, now=NOW)
        self.assertEqual(len(h.calls), n + 1)   # only that window was searched again
        self.assertEqual((log["windows"][1]["status"], log["windows"][1]["empty_runs"]), ("done", [1, 2]))
        self.assertEqual(log["runs"][-1]["stop"]["reason"], "complete")

    def test_a_full_window_that_stopped_scrolling_is_split(self):
        busy = [post(f"2026-01-{d:02d}T{h:02d}:00:00Z", "gm") for d in (12, 13, 14) for h in range(10, 16)]   # 18 posts in the 01-09..01-19 window, oldest 3 days in
        h = FakeHarness(busy)
        log = scan_caller.scan(URL, root=self.root, harness=h, budget=100, now=NOW)
        split = [w for w in log["windows"] if w["status"] == "split"]
        self.assertEqual(len(split), 1)
        self.assertEqual(split[0]["since"], "2026-01-09")
        halves = [w for w in log["windows"] if (w["since"], w["until"]) in (("2026-01-09", "2026-01-14"), ("2026-01-14", "2026-01-19")) and w["status"] == "done"]
        self.assertEqual(len(halves), 2)
        self.assertTrue(all(p["id"] in log["posts"] for p in busy))


class Labels(unittest.TestCase):
    def test_labels(self):
        cases = {
            "I am long bitcoin here": ("call", "BTC", 1),
            "We're still short gold into the cycle low": ("call", "GOLD", -1),
            "gm everyone": ("no_call", None, None),
            "Bitcoin looks heavy this week": ("no_call", None, None),
            "Are you long bitcoin here?": ("no_call", None, None),
            "You should take some profits on silver": ("no_call", None, None),
            "Dont panic sell the bottoms in silver": ("no_call", None, None),
            "A whale is going long bitcoin with 40x": ("no_call", None, None),
            "I'm long bitcoin lol": ("no_call", None, None),
            "I am long bitcoin and gold here": ("needs_review", None, 1),
            "I'm long bitcoin but I'm short the miners in bitcoin": ("needs_review", "BTC", None),
            "Closed my silver short, I am now long silver": ("needs_review", "SILVER", 1),
        }
        for text, (lab, asset, side) in cases.items():
            got = scan_caller.label_post(text)
            self.assertEqual((got["label"], got["asset"], got["side"]), (lab, asset, side), text)
            self.assertTrue(got["reason"])


class ReportAndAdd(Scratch):
    def prices(self):
        with open(os.path.join(self.root, "web", "data", "charts.json")) as f:
            bundle = json.load(f)
        snap = os.path.join(self.root, "snap.json")
        with open(snap, "w") as f:
            json.dump({a["name"]: a["series"] for a in bundle["assets"]}, f)
        return resolve.Prices(snapshot=snap)

    def write_review(self, data):
        with open(os.path.join(self.root, "intake", "scans", "scantest", "review.json"), "w") as f:
            json.dump(data, f)

    def test_report_review_add(self):
        posts = [post("2026-10-20T14:00:00Z", "I am long bitcoin here"),                       # call
                 post("2026-10-22T14:00:00Z", "I am long bitcoin and gold here"),              # review: two assets
                 post("2026-10-23T14:00:00Z", "Bitcoin looks heavy"),                          # no call
                 post("2026-10-24T14:00:00Z", "I'm shorting gold, cycle top")]                 # call, skipped by review
        scan_caller.scan(URL, root=self.root, harness=FakeHarness(posts), budget=100, now=NOW)
        web0, rec0 = tree_hash(self.root, "web"), tree_hash(self.root, "records")
        self.write_review({posts[1]["id"]: {"decision": "add", "asset": "GOLD"}})
        with self.assertRaisesRegex(add_call.Refused, "needs a written reason"):
            scan_caller.report(URL, root=self.root, prices=self.prices(), now="2026-10-31T03:00:00Z")
        self.write_review({posts[1]["id"]: {"decision": "add", "asset": "GOLD", "reason": "the post's position is gold; bitcoin is the comparison"},
                           posts[3]["id"]: {"decision": "skip", "reason": "a hedge inside a longer thread, not a standalone call"}})
        r = scan_caller.report(URL, root=self.root, prices=self.prices(), now="2026-10-31T03:00:00Z")
        # the report changes nothing under web/ or records/
        self.assertEqual((tree_hash(self.root, "web"), tree_hash(self.root, "records")), (web0, rec0))
        status = {p["id"]: p["status"] for p in r["posts"]}
        self.assertEqual(status[posts[0]["id"]], "to add")
        self.assertEqual(status[posts[1]["id"]], "to add")
        self.assertEqual(status[posts[2]["id"]], "no call")
        self.assertEqual(status[posts[3]["id"]], "skipped by review")
        self.assertEqual(r["to_add"], 2)
        gm = sum(1 for p in r["posts"] if p["text"] == "gm")
        self.assertEqual(r["counts"], {"call": 2, "no_call": 1 + gm, "needs_review": 1})
        with open(os.path.join(self.root, "web", "data", "charts.json")) as f:
            before = json.load(f)["ratings"]["callers"]
        log = add_call.add(r["pending_file"], root=self.root, save_avatar=False, ohlc=None, now="2026-10-31T03:00:00Z")
        with open(os.path.join(self.root, "web", "data", "charts.json")) as f:
            after = json.load(f)["ratings"]["callers"]
        self.assertEqual(log["scores_after_add"]["ScanTest"], r["score_projected"])
        self.assertEqual(after["ScanTest"]["score"], r["score_projected"]["score"])
        for name, c in before.items():                                                     # other callers unchanged
            self.assertEqual(after[name]["score"], c["score"], name)
        self.assertEqual(sorted(log["other_callers_unchanged"]), sorted(before))
        gold = [x for x in log["records"] if x["record_file"].endswith("_GOLD.json")][0]
        with open(os.path.join(self.root, gold["record_file"])) as f:
            rec = json.load(f)
        self.assertEqual(rec["asset_choice"]["reason"], "reviewed: the post's position is gold; bitcoin is the comparison")
        # the same scan again: both calls are now already recorded, nothing left to add
        r2 = scan_caller.report(URL, root=self.root, prices=self.prices(), now="2026-10-31T03:10:00Z")
        self.assertEqual(r2["to_add"], 0)
        self.assertTrue(all(p["status"].startswith("already recorded") for p in r2["posts"] if p["id"] in (posts[0]["id"], posts[1]["id"])))


if __name__ == "__main__":
    unittest.main()
