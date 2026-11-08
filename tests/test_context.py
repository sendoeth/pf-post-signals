"""Step 29: replies and quotes read with the post they answer. The parent chain is bounded and fails closed (depth,
cycles, deleted / protected posts, integrity mismatches, byte / count / pixel caps); stored contexts are pinned and
verified; context candidates never carry or create a side (a side comes only from the caller's own words); the
koolkrypto223 reply resolves NEST from the parent's portfolio image and KNTQ from its own words, long from the caller's
"More"; potential callers stay unscored; nothing here changes a record or a score. Offline: embeds are fixtures.
Run: python3 -m unittest -v tests.test_context"""
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import context_page  # noqa: E402
import detect  # noqa: E402
import parents  # noqa: E402
import rate  # noqa: E402
import reader  # noqa: E402
import resolve  # noqa: E402
import watch_callers as wc  # noqa: E402

ACCEPT = "2118181656398090718"          # @koolkrypto223 "More $NEST and $KNTQ", a reply to @0xLcrgs's portfolio
SOXL = "2116304617047007308"            # @goodalexander "solid support here", a reply to @based16z's chart
DELETED = "2115966476817739790"         # its parent was deleted by its author


def load(path, mode="r"):
    with open(path, mode) as f:
        return json.load(f) if path.endswith(".json") and mode == "r" else f.read()


def sha(path):
    return hashlib.sha256(load(path, "rb")).hexdigest()


def post(pid, author, text="", reply=None, quote=None, media=0, truncated=False):
    """An embed payload as cdn.syndication returns it (time = the id's snowflake time)."""
    d = {"id_str": pid, "created_at": resolve.snowflake_time(pid)[:19] + ".000Z", "text": text, "user": {"screen_name": author},
         "display_text_range": [0, len(text)], "entities": {"symbols": []}}
    if reply:
        d["in_reply_to_status_id_str"], d["in_reply_to_screen_name"] = reply
    if quote:
        d["quoted_tweet"] = {"id_str": quote[0], "user": {"screen_name": quote[1]}}
    if media:
        d["mediaDetails"] = [{"type": "photo", "media_url_https": f"https://pbs.twimg.com/media/{pid}x{n}.png"} for n in range(media)]
    if truncated:
        d["note_tweet"] = {"id": "x"}
    return d


def ids(n, start=2118100000000000000):
    return [str(start + i * 4194304 * 1000) for i in range(n)]       # distinct ids, increasing snowflake times


class Chain:
    """A fake embed: {id: payload or an exception}."""
    def __init__(self, posts):
        self.posts = posts
        self.calls = []

    def __call__(self, pid):
        self.calls.append(pid)
        v = self.posts.get(pid)
        if isinstance(v, Exception):
            raise v
        if v is None:
            raise parents.Unavailable(f"post {pid} unavailable (embed HTTP 404: deleted, private or never existed)")
        return copy.deepcopy(v)


def fake_get(url, path):
    from PIL import Image
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (40, 20), (255, 255, 255)).save(path, format="PNG")
    return path


def tmp_root():
    root = tempfile.mkdtemp(prefix="quanty-context-")
    for d in ("sources", "data", "records"):
        os.makedirs(os.path.join(root, d))
    return root


class ChainBounds(unittest.TestCase):
    def setUp(self):
        self.root = tmp_root()

    def tearDown(self):
        shutil.rmtree(self.root)

    def build(self, chain, pid, **kw):
        kw.setdefault("ocr_engine", lambda p: "SOL")
        return parents.build(pid, root=self.root, fetch=chain, get=fake_get, **kw)

    def test_a_reply_to_a_post_without_parent_is_complete_and_the_parent_is_the_root(self):
        a, b = ids(2)
        doc = self.build(Chain({b: post(b, "caller", "long here", reply=(a, "og")), a: post(a, "og", "$SOL looks great")}), b)
        self.assertEqual(doc["status"], "complete")
        self.assertTrue(doc["root_is_parent"])
        self.assertEqual([r for r, _ in parents.usable_roles(doc)], ["parent"])
        self.assertEqual(doc["parent"]["text"], "$SOL looks great")

    def test_more_than_max_depth_parents_is_truncated_and_names_no_root(self):
        chain = ids(parents.MAX_DEPTH + 3)
        posts = {pid: post(pid, f"u{i}", f"post {i}", reply=(chain[i - 1], f"u{i - 1}") if i else None) for i, pid in enumerate(chain)}
        doc = self.build(Chain(posts), chain[-1])
        self.assertEqual(doc["status"], "truncated")
        self.assertEqual(len(doc["chain"]), parents.MAX_DEPTH)
        self.assertNotIn("root", doc)
        self.assertEqual([r for r, _ in parents.usable_roles(doc)], ["parent"])           # the direct parent only

    def test_a_cycle_stops_the_walk(self):
        a, b = ids(2)
        doc = self.build(Chain({b: post(b, "caller", "x", reply=(a, "og")), a: post(a, "og", "y", quote=(b, "caller"))}), b)
        self.assertEqual(doc["status"], "cycle")
        self.assertNotIn("root", doc)

    def test_deleted_protected_or_mismatched_parents_give_no_context(self):
        a, b = ids(2)
        caller = post(b, "caller", "long this", reply=(a, "og"))
        cases = {
            "deleted (404)": None,
            "tombstone": {"__typename": "TweetTombstone", "tombstone": {"text": {"text": "This Post was deleted by the Post author."}}},
            "other id": post(ids(3)[2], "og", "x"),
            "time not the id's": dict(post(a, "og", "x"), created_at="2020-01-01T00:00:00.000Z"),
            "author not the link's": post(a, "someone_else", "x"),
            "no author": dict(post(a, "og", "x"), user={}),
        }
        for name, parent in cases.items():
            with self.subTest(case=name):
                shutil.rmtree(os.path.join(self.root, "sources"))
                os.makedirs(os.path.join(self.root, "sources"))
                doc = self.build(Chain({b: caller, a: parent}), b)
                self.assertEqual(doc["status"], "unavailable")
                self.assertNotIn("parent", doc)
                self.assertEqual(parents.candidates(doc, root=self.root, ocr_engine=lambda p: "SOL"), [])

    def test_the_caller_post_itself_must_be_readable(self):
        a, = ids(1)
        self.assertRaises(parents.Unavailable, self.build, Chain({}), a)

    def test_a_text_cut_short_in_the_embed_gives_no_words(self):
        a, b = ids(2)
        doc = self.build(Chain({b: post(b, "caller", "x", reply=(a, "og")), a: post(a, "og", "$SOL $ETH", truncated=True)}), b)
        self.assertTrue(doc["parent"]["text_truncated"])
        c = parents.candidates(doc, root=self.root, ocr_engine=lambda p: "")
        self.assertEqual([x["asset"] for x in c], [None])
        self.assertIn("cuts this post's text short", c[0]["sources"][0]["evidence"]["unread"])

    def test_images_are_capped_per_post_and_per_chain(self):
        a, b = ids(2)
        doc = self.build(Chain({b: post(b, "caller", "x", reply=(a, "og")), a: post(a, "og", "chart", media=parents.MAX_IMAGES_PER_POST + 3)}), b)
        self.assertEqual(len(doc["parent"]["images"]), parents.MAX_IMAGES_PER_POST)
        with mock.patch.object(parents, "MAX_IMAGES", 2):
            c, d = ids(2, start=2118200000000000000)
            doc = self.build(Chain({d: post(d, "caller", "x", reply=(c, "og")), c: post(c, "og", "chart", media=3)}), d)
        self.assertEqual(doc["parent"]["images"], [])
        self.assertIn("OverBudget", doc["parent"]["images_error"])
        self.assertEqual(parents.candidates(doc, root=self.root, ocr_engine=lambda p: "SOL")[0]["asset"], None)

    def test_embed_and_image_bodies_are_read_with_a_byte_cap(self):
        class Resp:
            def __init__(self, n):
                self.n = n

            def read(self, k):
                return b"x" * min(self.n, k)
        self.assertEqual(parents.read_capped(Resp(10), 10, "x"), b"x" * 10)
        self.assertRaises(parents.OverBudget, parents.read_capped, Resp(11), 10, "x")

    def test_images_over_the_pixel_cap_are_not_ocrd(self):
        path = fake_get(None, os.path.join(self.root, "big.png"))
        with mock.patch.object(parents, "MAX_PIXELS", 100):
            self.assertRaises(parents.OverBudget, parents.capped_ocr, path)

    def timed(self, posts, slow_fetch=(), fetch_s=100, download_s=0):
        """A simulated clock: a fetch of an id in `slow_fetch` takes fetch_s, every download download_s."""
        clock = [0]
        chain = Chain(posts)

        def fetch(pid):
            if pid in slow_fetch:
                clock[0] += fetch_s
            return chain(pid)

        def get(url, path):
            clock[0] += download_s
            return fake_get(url, path)
        return dict(fetch=fetch, get=get, ocr_engine=lambda p: "SOL", clock=lambda: clock[0], seconds=5)

    def test_the_walk_has_a_deadline(self):
        a, b = ids(2)
        posts = {b: post(b, "caller", "x", reply=(a, "og")), a: post(a, "og", "$SOL")}
        for name, slow in (("a slow caller fetch", {b}), ("a slow last parent fetch", {a})):
            with self.subTest(when=name):
                shutil.rmtree(os.path.join(self.root, "sources"))
                os.makedirs(os.path.join(self.root, "sources"))
                doc = parents.build(b, root=self.root, **self.timed(posts, slow_fetch=slow))
                self.assertEqual(doc["status"], "over_budget")
                self.assertNotIn("parent", doc)                                   # an over-budget fetch keeps nothing
                self.assertEqual(parents.candidates(doc, root=self.root), [])
        c, = ids(1, start=2118400000000000000)
        doc = parents.build(c, root=self.root, **self.timed({c: post(c, "caller", "x")}, slow_fetch={c}))   # no parent at all
        self.assertEqual(doc["status"], "over_budget")

    def test_image_downloads_are_inside_the_deadline(self):
        a, b = ids(2)
        doc = parents.build(b, root=self.root, **self.timed({b: post(b, "caller", "x", reply=(a, "og")), a: post(a, "og", "y", media=2)}, download_s=100))
        self.assertEqual(doc["parent"]["images"], [])
        self.assertIn("deadline", doc["parent"]["images_error"])
        self.assertNotIn("SOL", [x["asset"] for x in parents.candidates(doc, root=self.root)])     # no image candidate


class Pins(unittest.TestCase):
    def setUp(self):
        self.root = tmp_root()
        a, b = ids(2)
        self.pid = b
        parents.build(b, root=self.root, fetch=Chain({b: post(b, "caller", "x", reply=(a, "og")), a: post(a, "og", "$SOL", media=1)}),
                      get=fake_get, ocr_engine=lambda p: "SOXL 6.89")

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_the_ocr_text_is_pinned_with_the_context(self):
        doc = parents.load(self.pid, self.root)
        self.assertEqual(doc["parent"]["images"][0]["ocr"]["text"], "SOXL 6.89")
        self.assertEqual([c["asset"] for c in parents.candidates(doc, root=self.root) if c["asset"] == "SOXL"], ["SOXL"])
        cache = os.path.join(self.root, doc["parent"]["images"][0]["file"] + ".ocr.json")
        with open(cache, "w") as f:                       # a cache file is never read by candidates()
            json.dump({"image_sha256": doc["parent"]["images"][0]["sha256"], "text": "BTC"}, f)
        self.assertNotIn("BTC", [c["asset"] for c in parents.candidates(parents.load(self.pid, self.root), root=self.root)])

    def test_a_stored_context_is_verified_on_every_read(self):
        doc = parents.load(self.pid, self.root)
        self.assertEqual(doc["pin_sha256"], parents.pin_of(doc))

    def test_an_edited_context_receipt_or_image_is_refused(self):
        p = parents.context_path(self.pid, self.root)
        doc = load(p)
        img = doc["parent"]["images"][0]
        for name, edit in [("context text", lambda: self._write(p, dict(doc, parent=dict(doc["parent"], text="$ETH")))),
                           ("ocr text", lambda: self._write(p, dict(doc, parent=dict(doc["parent"], images=[dict(img, ocr=dict(img["ocr"], text="BTC"))])))),
                           ("receipt reply link", lambda: self._edit_receipt(doc, "replyTo", "1")),
                           ("receipt truncation flag", lambda: self._edit_receipt(doc, "textTruncated", True)),
                           ("receipt text", lambda: self._edit_receipt(doc, "text", "edited")),
                           ("image bytes", lambda: self._append(os.path.join(self.root, doc["parent"]["images"][0]["file"])))]:
            with self.subTest(edit=name):
                saved = {f: load(os.path.join(self.root, f), "rb") for f in (os.path.relpath(p, self.root), doc["parent"]["receipt"], doc["parent"]["images"][0]["file"])}
                edit()
                self.assertRaises(parents.Integrity, parents.load, self.pid, self.root)
                for f, b in saved.items():
                    with open(os.path.join(self.root, f), "wb") as fh:
                        fh.write(b)

    @staticmethod
    def _write(path, d):
        with open(path, "w") as f:
            json.dump(d, f)

    @staticmethod
    def _append(path):
        with open(path, "ab") as f:
            f.write(b"x")

    def _edit_receipt(self, doc, key, value):
        rp = os.path.join(self.root, doc["parent"]["receipt"])
        r = load(rp)
        r[key] = value
        with open(rp, "w") as f:
            json.dump(r, f)

    def test_a_stored_context_is_never_rewritten(self):
        p = parents.context_path(self.pid, self.root)
        before = load(p, "rb")
        doc = parents.build(self.pid, root=self.root, fetch=Chain({}), get=fake_get)        # no fetch needed, none made
        self.assertEqual(load(p, "rb"), before)
        self.assertEqual(doc["pin_sha256"], json.loads(before)["pin_sha256"])


class SidesOnlyFromTheCallersWords(unittest.TestCase):
    CTX = [{"asset": "SOXL", "sources": [{"source": "parent_image", "post_id": "1", "author": "og", "evidence": {"matched": "SOXL"}}]}]

    def test_candidates_never_carry_a_side(self):
        doc = parents.load(ACCEPT)
        for c in parents.candidates(doc, ocr_engine=context_page.no_ocr):
            self.assertEqual(set(c), {"asset", "sources"})

    def test_a_context_only_asset_takes_no_side_from_the_parent(self):
        for text in ("solid support here", "interesting", "nice chart", "wow"):
            with self.subTest(text=text):
                r = reader.read_in_context(text, [], self.CTX)
                self.assertEqual([(x["asset"], x["side"]) for x in r], [("SOXL", None)])

    def test_the_parent_text_never_reaches_a_side_function(self):
        seen = []
        real = detect.detect_side
        with mock.patch.object(detect, "detect_side", side_effect=lambda t: seen.append(t) or real(t)):
            reader.read_in_context("I am long here", [], self.CTX + [])
        self.assertEqual(seen, ["I am long here"])

    def test_the_callers_own_words_give_a_context_only_asset_its_side(self):
        r = reader.read_in_context("I am long here", [], self.CTX)
        self.assertEqual((r[0]["asset"], r[0]["side"]), ("SOXL", 1))
        self.assertTrue(r[0]["side_from"].startswith("own words"))

    def test_no_side_when_the_caller_names_other_assets_or_the_context_names_several(self):
        own = [{"asset": "BTC", "aliases": ["BTC"], "multi": False}]
        r = {x["asset"]: x for x in reader.read_in_context("I am long $BTC", own, self.CTX)}
        self.assertEqual(r["BTC"]["side"], 1)
        self.assertEqual(r["SOXL"]["side"], None)
        two = self.CTX + [{"asset": "TSLA", "sources": [{"source": "parent_text", "post_id": "1", "author": "og", "evidence": {}}]}]
        self.assertEqual({x["side"] for x in reader.read_in_context("I am long here", [], two)}, {None})

    def test_an_own_asset_reads_exactly_as_without_context(self):
        own = [{"asset": "NEST", "aliases": ["NEST"], "multi": True}]
        ctx = [{"asset": "NEST", "sources": [{"source": "parent_image", "post_id": "1", "author": "og", "evidence": {}}]}]
        a = reader.read_in_context("More $NEST", own, ctx)[0]
        b = reader.read("More $NEST", ["NEST"], True)
        self.assertEqual((a["side"], a["method"], a["rule"]), (b["side"], b["method"], b["rule"]))

    def test_the_watcher_lists_context_assets_without_legs_when_the_caller_names_assets(self):
        c = {"kind": "reply", "parent": None, "candidate": True,
             "legs": [{"asset": "NEST", "via": ["$NEST"], "status": "ok", "flag": None, "side": "long", "side_words": "More $NEST", "side_reason": "rule"}]}
        doc = parents.load(ACCEPT)
        out, ctx = wc.with_context("More $NEST", c, doc, parents.candidates(doc, ocr_engine=context_page.no_ocr))
        self.assertEqual([l["asset"] for l in out["legs"]], ["NEST"])
        self.assertEqual(out["legs"][0]["side"], "long")                                  # unchanged
        self.assertIn("parent_image", out["legs"][0]["provenance"])
        self.assertIn("ETH", [x["asset"] for x in ctx["candidates"]])

    def test_a_reply_naming_no_asset_becomes_a_card_with_the_context_asset_and_no_side(self):
        doc = parents.load(SOXL)
        c = wc.classify({"text": "solid support here", "kind": "reply", "replyTo": {"postId": doc["parent"]["id"], "handle": "based16z"}})
        self.assertFalse(c["candidate"])                                                   # before step 29: dropped
        out, ctx = wc.with_context("solid support here", c, doc, parents.candidates(doc, ocr_engine=context_page.no_ocr))
        self.assertTrue(out["candidate"])
        self.assertEqual([(l["asset"], l["side"], l["provenance"]) for l in out["legs"]], [("SOXL", "none", ["parent_image"])])
        self.assertIn("check it", out["legs"][0]["flag"])


class Acceptance(unittest.TestCase):
    def test_koolkrypto223_more_nest_and_kntq(self):
        doc = parents.load(ACCEPT)                       # verified: pin, receipts, image bytes
        self.assertEqual((doc["caller"]["author"], doc["caller"]["text"]), ("koolkrypto223", "More $NEST and $KNTQ"))   # receipts drop the leading @mention
        self.assertEqual((doc["parent"]["author"], doc["parent"]["link"]), ("0xLcrgs", "reply"))
        img = doc["parent"]["images"][0]
        self.assertEqual(sha(os.path.join(HERE, img["file"])), img["sha256"])
        cands = {c["asset"]: c for c in parents.candidates(doc, ocr_engine=context_page.no_ocr) if c["asset"]}
        nest = [s for s in cands["NEST"]["sources"] if s["source"] == "parent_image"][0]
        self.assertEqual(nest["evidence"]["image_sha256"], img["sha256"])
        self.assertIn("NEST 0.60%", nest["evidence"]["ocr_excerpt"])
        self.assertNotIn("KNTQ", cands)                  # the portfolio holds no KNTQ: KNTQ is the caller's own word
        own = [{"asset": "NEST", "aliases": ["NEST"], "multi": True}, {"asset": "KNTQ", "aliases": ["KNTQ"], "multi": True}]
        reads = {r["asset"]: r for r in reader.read_in_context("More $NEST and $KNTQ", own, list(cands.values()), rules=reader.kept_rules())}
        self.assertEqual((reads["NEST"]["side"], reads["NEST"]["rule"]), (1, "more_cashtag"))
        self.assertEqual((reads["KNTQ"]["side"], reads["KNTQ"]["rule"]), (1, "more_cashtag"))
        self.assertEqual(reads["NEST"]["provenance"], ["own words", "parent_image"])
        self.assertEqual(reads["KNTQ"]["provenance"], ["own words"])
        for other in ("ETH", "HYPE"):
            self.assertEqual(reads[other]["side"], None)
            self.assertEqual(reads[other]["side_from"], "none: the caller names other assets")

    def test_the_deleted_parent_fails_closed(self):
        doc = parents.load(DELETED)
        self.assertEqual(doc["status"], "unavailable")
        self.assertIn("deleted", doc["reason"])
        self.assertEqual(parents.candidates(doc, ocr_engine=context_page.no_ocr), [])


class ScoreNeutral(unittest.TestCase):
    SERVED = load(os.path.join(HERE, "web", "data", "context.json"))
    BUNDLE = load(os.path.join(HERE, "web", "data", "charts.json"))

    def test_context_never_changes_a_side_agreement_and_finds_more_assets(self):
        a = self.SERVED["agreement"]
        self.assertEqual(a["side_agree_after"], a["side_agree_before"])
        self.assertGreater(a["asset_found_after"], a["asset_found_before"])
        for r in self.SERVED["agreement_rows"]:
            with self.subTest(label=r["id"]):
                self.assertEqual(r["agree_after"], r["agree_before"])

    def test_the_page_does_not_depend_on_file_order(self):
        import glob as g
        real = g.glob
        with mock.patch.object(g, "glob", side_effect=lambda *a, **k: list(reversed(real(*a, **k)))):
            rev = context_page.build_data()
        self.assertEqual(rev, context_page.build_data())

    def test_the_page_is_deterministic_and_the_served_one_is_a_rebuild(self):
        self.assertEqual(json.dumps(context_page.build_data(), indent=1, ensure_ascii=False) + "\n",
                         load(os.path.join(HERE, "web", "data", "context.json"), "rb").decode())
        self.assertEqual(self.SERVED["charts_sha256"], sha(os.path.join(HERE, "web", "data", "charts.json")))

    def test_building_context_writes_no_record_and_no_score(self):
        root = tmp_root()
        try:
            shutil.copytree(os.path.join(HERE, "records"), os.path.join(root, "records"), dirs_exist_ok=True)
            before = {f: sha(os.path.join(dp, f)) for dp, _, fs in os.walk(os.path.join(root, "records")) for f in fs}
            a, b = ids(2)
            parents.build(b, root=root, fetch=Chain({b: post(b, "caller", "long", reply=(a, "og")), a: post(a, "og", "$SOL", media=1)}), get=fake_get)
            after = {f: sha(os.path.join(dp, f)) for dp, _, fs in os.walk(os.path.join(root, "records")) for f in fs}
            self.assertEqual(before, after)
        finally:
            shutil.rmtree(root)

    def test_the_main_scores_are_the_rating_of_the_records(self):
        again = rate.rate_bundle(copy.deepcopy(self.BUNDLE))
        self.assertEqual({n: c["score"] for n, c in again["callers"].items()}, {n: c["score"] for n, c in self.BUNDLE["ratings"]["callers"].items()})

    def test_potential_callers_are_never_scored(self):
        pot = {p["handle"].lower() for p in self.SERVED["potential_callers"]}
        self.assertTrue(pot)
        self.assertFalse(pot & {n.lower() for n in self.BUNDLE["ratings"]["callers"]})
        for p in self.SERVED["potential_callers"]:
            self.assertTrue(p["status"].startswith(("potential (unscored", "promoted (watched, unscored")))

    def test_promotion_watches_an_account_but_scores_nothing(self):
        root = tmp_root()
        try:
            shutil.copy(os.path.join(HERE, "data", "potential_callers.json"), os.path.join(root, "data", "potential_callers.json"))
            self.assertRaises(ValueError, parents.promote, "not_listed_anywhere", root)
            self.assertRaises(ValueError, parents.promote, "bad handle!", root)
            self.assertTrue(parents.promote("@based16z", root))
            self.assertFalse(parents.promote("based16z", root))
            self.assertIn("based16z", wc.callers(root))
            self.assertEqual(rate.rate_bundle(copy.deepcopy(self.BUNDLE))["callers"].keys(), self.BUNDLE["ratings"]["callers"].keys())
        finally:
            shutil.rmtree(root)

    def test_each_position_page_of_a_reply_shows_its_stored_context(self):
        for en in self.SERVED["entries"]:
            for rec in en["recorded"]:
                page = load(os.path.join(HERE, "web", f"pos-{en['post']}_{rec['asset'].replace(':', '-')}.html"))
                with self.subTest(post=en["post"], asset=rec["asset"]):
                    self.assertIn(f'data-field="reply_context" data-post="{en["post"]}"', page)
                    if en["posts"].get("parent"):
                        self.assertIn(en["posts"]["parent"]["text_sha256"][:16], page)


if __name__ == "__main__":
    unittest.main()
