"""Step 30: owner-set sector tags. Run: python3 -m unittest tests.test_sectors -v

- schema: unknown tickers, duplicate ids, duplicate keys, bad ids, priced proxies, non-https sources are refused
- confirm before write: a preview never writes; only the preview's own token writes; a stale or edited one is refused
- site: the tags show on leaderboard rows, position pages, caller pages and the static sectors page
- score-neutral: charts.json and the ratings stay byte-identical when sectors change
"""
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import prerender  # noqa: E402
import sectors as sx  # noqa: E402

WHEN = "2026-11-26T12:00:00Z"


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read(p):
    with open(p) as f:
        return f.read()


def load_json(p):
    with open(p) as f:
        return json.load(f)


class Repo(unittest.TestCase):
    """A throwaway copy of data/ and web/, so nothing here touches the real site."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="qq-sectors-")
        for d in ("data", "web"):
            shutil.copytree(os.path.join(HERE, d), os.path.join(self.root, d))
        p = sx.path(self.root)
        if os.path.exists(p):
            os.remove(p)
        self.assets = sx.known_assets(self.root)

    def tearDown(self):
        shutil.rmtree(self.root)

    def run_cli(self, *argv):
        return sx.main(list(argv), root=self.root)

    def change(self, op, args):
        """Preview, then confirm with the preview's token (what the bot does on the owner's tap)."""
        _, lines, tok = sx.plan(self.root, op, dict(args), WHEN)
        sx.apply(self.root, op, dict(args), tok, WHEN)
        return lines


class Schema(Repo):
    def doc(self, **over):
        s = {"id": "metals", "name": "Metals", "proxy": None, "created_at": WHEN,
             "members": [{"asset": "GOLD", "source": "https://example.org/gold", "added_at": WHEN}]}
        s.update(over)
        return {"schema": sx.SCHEMA, "sectors": [s]}

    def refused(self, doc, words):
        with self.assertRaises(sx.SectorError) as cm:
            sx.validate(doc, self.assets)
        self.assertIn(words, str(cm.exception))

    def test_a_valid_document_passes(self):
        sx.validate(self.doc(), self.assets)

    def test_unknown_ticker_is_refused(self):
        self.refused(self.doc(members=[{"asset": "NOTACOIN", "source": None, "added_at": WHEN}]), "unknown ticker 'NOTACOIN'")

    def test_duplicate_sector_id_is_refused(self):
        d = self.doc()
        d["sectors"].append(dict(d["sectors"][0]))
        self.refused(d, "duplicate sector id 'metals'")

    def test_duplicate_json_keys_are_refused(self):
        with self.assertRaises(sx.SectorError) as cm:
            sx.parse('{"schema": "quanty.sectors.v1", "sectors": [], "sectors": []}')
        self.assertIn("duplicate key", str(cm.exception))

    def test_member_listed_twice_is_refused(self):
        m = {"asset": "GOLD", "source": None, "added_at": WHEN}
        self.refused(self.doc(members=[m, dict(m)]), "GOLD listed twice")

    def test_bad_id_name_proxy_source_and_extra_keys_are_refused(self):
        self.refused(self.doc(id="Semi Conductors"), "lowercase letters")
        self.refused(self.doc(name=""), "name must be")
        self.refused(self.doc(proxy={"symbol": "SOXX", "priced": True}), "never priced")
        self.refused(self.doc(members=[{"asset": "GOLD", "source": "http://example.org", "added_at": WHEN}]), "https link")
        d = self.doc()
        d["sectors"][0]["detected"] = True
        self.refused(d, "keys must be")
        self.refused({"schema": sx.SCHEMA, "sectors": [], "auto": True}, "expected")

    def test_a_record_asset_that_is_not_a_coin_is_known(self):
        # metals, index stand-ins and HL xyz stocks are record assets, not entries in data/tickers.json
        self.assertIn("SILVER", self.assets)
        self.assertIn("XYZ:SKHX", self.assets)


class ConfirmBeforeWrite(Repo):
    def test_a_preview_never_writes(self):
        self.assertEqual(self.run_cli("add", "metals", "Metals"), 0)
        self.assertFalse(os.path.exists(sx.path(self.root)))

    def test_only_the_previews_token_writes(self):
        _, lines, tok = sx.plan(self.root, "add", {"id": "metals", "name": "Metals", "proxy": "COPX"}, WHEN)
        self.assertIn("proxy label COPX, not priced", lines[0])
        with self.assertRaises(sx.SectorError):
            sx.apply(self.root, "add", {"id": "metals", "name": "Metals", "proxy": "COPX"}, "0" * 16, WHEN)
        self.assertFalse(os.path.exists(sx.path(self.root)))
        sx.apply(self.root, "add", {"id": "metals", "name": "Metals", "proxy": "COPX"}, tok, WHEN)
        self.assertEqual(sx.load(self.root)["sectors"][0]["proxy"], "COPX")

    def test_a_stale_preview_is_refused_after_another_change(self):
        self.change("add", {"id": "metals", "name": "Metals"})
        _, _, tok = sx.plan(self.root, "tag", {"ticker": "GOLD", "id": "metals", "source": None}, WHEN)
        self.change("tag", {"ticker": "SILVER", "id": "metals", "source": None})     # the file changed since the preview
        with self.assertRaises(sx.SectorError) as cm:
            sx.apply(self.root, "tag", {"ticker": "GOLD", "id": "metals", "source": None}, tok, WHEN)
        self.assertIn("stale", str(cm.exception))

    def test_an_edited_preview_is_refused(self):
        self.change("add", {"id": "metals", "name": "Metals"})
        _, _, tok = sx.plan(self.root, "tag", {"ticker": "GOLD", "id": "metals", "source": None}, WHEN)
        with self.assertRaises(sx.SectorError):
            sx.apply(self.root, "tag", {"ticker": "SILVER", "id": "metals", "source": None}, tok, WHEN)

    def test_refused_changes_write_nothing(self):
        self.change("add", {"id": "metals", "name": "Metals"})
        before = sha(sx.path(self.root))
        for argv in (("tag", "NOTACOIN", "metals"), ("tag", "GOLD", "nosuch"), ("untag", "GOLD", "metals"),
                     ("add", "metals", "Again"), ("tag", "GOLD", "metals", "http://insecure.example")):
            self.assertEqual(self.run_cli(*argv), 2, argv)
        self.assertEqual(sha(sx.path(self.root)), before)

    def test_cli_confirm_needs_the_preview_time(self):
        self.assertEqual(self.run_cli("add", "metals", "Metals", "--confirm", "abc"), 2)


class Site(Repo):
    def build(self):
        prerender.main(os.path.join(self.root, "web"))
        return load_json(os.path.join(self.root, "web", "data", "sectors.json"))

    def setUp(self):
        super().setUp()
        self.change("add", {"id": "metals", "name": "Metals", "proxy": "COPX"})
        self.change("tag", {"ticker": "GOLD", "id": "metals", "source": "https://en.wikipedia.org/wiki/Gold"})
        self.change("tag", {"ticker": "SILVER", "id": "metals", "source": "https://en.wikipedia.org/wiki/Silver"})

    def test_tags_show_on_rows_positions_callers_and_the_sectors_page(self):
        d = self.build()
        web = os.path.join(self.root, "web")
        self.assertEqual(d["by_asset"]["GOLD"], [{"id": "metals", "name": "Metals"}])
        index = read(os.path.join(web, "index.html"))
        gold_rows = re.findall(r'<li data-static="1"[^>]*data-asset="GOLD".*?</li>', index, re.S)
        self.assertTrue(gold_rows)
        self.assertTrue(all('data-field="sector" data-sector="metals"' in r for r in gold_rows))
        self.assertNotIn("<a ", "".join(re.findall(r'<span class="tag sector"[^>]*>[^<]*</span>', index)))   # no link inside the row link
        btc = re.findall(r'<li data-static="1"[^>]*data-asset="BTC".*?</li>', index, re.S)
        self.assertTrue(btc and not any('data-field="sector"' in r for r in btc))     # untagged assets get no tag
        pos = [f for f in glob.glob(os.path.join(web, "pos-*_GOLD.html"))]
        self.assertTrue(pos)
        for f in pos:
            self.assertIn('data-field="sector_tags"', read(f))
            self.assertIn('href="sectors.html#metals"', read(f))
        caller_hits = [f for f in glob.glob(os.path.join(web, "caller-*.html")) if 'data-sector="metals"' in read(f)]
        self.assertTrue(caller_hits)
        page = read(os.path.join(web, "sectors.html"))
        self.assertIn('id="metals"', page)
        self.assertIn('proxy COPX', page)
        self.assertIn("https://en.wikipedia.org/wiki/Gold", page)
        self.assertNotIn("<script src=\"assets/board.js\"", page)                      # static, no JS needed
        n_gold = sum(len(a["posts"]) for a in load_json(os.path.join(web, "data", "charts.json"))["assets"] if a["name"] == "GOLD")
        self.assertEqual(page.count('data-asset="GOLD"') - 1, n_gold)                 # every GOLD call listed

    def test_results_on_the_sectors_page_match_the_leaderboard(self):
        d = self.build()
        bundle = load_json(os.path.join(self.root, "web", "data", "charts.json"))
        got = {(c["post_id"], m["asset"]): c["result"] for s in d["sectors"] for m in s["members"] for c in m["calls"]}
        for a in bundle["assets"]:
            for p in a["posts"]:
                if (p["post"]["id"], a["name"]) in got:
                    self.assertEqual(got[(p["post"]["id"], a["name"])], prerender.result_of(p))

    def test_sectors_never_change_scores(self):
        web = os.path.join(self.root, "web")
        charts = os.path.join(web, "data", "charts.json")
        before_charts = sha(charts)
        before_ratings = json.dumps(load_json(charts)["ratings"], sort_keys=True)
        records = {f: sha(f) for f in glob.glob(os.path.join(HERE, "records", "**", "*.json"), recursive=True)}
        self.assertGreater(len(records), 50)
        self.build()
        self.change("untag", {"ticker": "SILVER", "id": "metals"})
        self.change("add", {"id": "privacy", "name": "Privacy coins"})
        self.change("tag", {"ticker": "ZEC", "id": "privacy", "source": None})
        self.build()
        self.assertEqual(sha(charts), before_charts)
        self.assertEqual(json.dumps(load_json(charts)["ratings"], sort_keys=True), before_ratings)
        self.assertEqual(load_json(os.path.join(web, "data", "sectors.json"))["charts_sha256"], before_charts)
        for f, h in records.items():
            self.assertEqual(sha(f), h)


class RepoFile(unittest.TestCase):
    def test_the_committed_sectors_file_is_valid(self):
        if os.path.exists(sx.path(HERE)):
            sx.load(HERE)


if __name__ == "__main__":
    unittest.main()
