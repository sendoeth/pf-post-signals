"""Step 12: the pages without JavaScript. tools/prerender.py writes the data into the HTML; parsed
here with a plain HTML parser (no script runs), the static leaderboard and every static position
page must carry the bundle's values, and hostile X text must stay inert text.
Run: python3 -m unittest -v tests.test_static"""
import html.parser
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
import build_chart  # noqa: E402
import prerender  # noqa: E402

ALLOWED_SCRIPTS = {"assets/frame-guard.js", "assets/common.js", "assets/board.js", "assets/chart.js", "assets/position.js",
                   "vendor/lightweight-charts-4.2.3/lightweight-charts.standalone.production.js"}


class Page(html.parser.HTMLParser):
    """Collects every element, every data-field (text + data-raw) and the static rows."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.fields, self.rows, self._open, self.text = [], [], [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if tag == "li" and a.get("data-static") == "1":
            self.rows.append({"id": a["data-post-id"], "asset": a["data-asset"], "rank": int(a["data-rank"]), "fields": {}})
        if "data-field" in a:
            self._open.append([a["data-field"], a.get("data-raw"), ""])

    def handle_endtag(self, tag):
        if self._open and tag in ("span", "dd", "td", "strong", "p", "time", "a"):
            f, raw, text = self._open.pop()
            self.fields.append((f, raw, text))
            if self.rows:
                self.rows[-1]["fields"].setdefault(f, (raw, text))

    def handle_data(self, data):
        self.text.append(data)
        for o in self._open:
            o[2] += data


def parse(path):
    p = Page()
    with open(path, encoding="utf-8") as f:
        p.feed(f.read())
    return p


def site_copy(bundle_records=None):
    tmp = tempfile.mkdtemp(prefix="pfps-static-")
    web = os.path.join(tmp, "web")
    shutil.copytree(os.path.join(HERE, "web"), web)
    if bundle_records:
        b = build_chart.build(bundle_records)
        with open(os.path.join(web, "data", "charts.json"), "w") as f:
            json.dump(b, f)
    prerender.main(web)
    return tmp, web


class Static(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.web = site_copy()
        with open(os.path.join(cls.web, "data", "charts.json")) as f:
            cls.bundle = json.load(f)
        cls.rows = prerender.rows_of(cls.bundle)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_leaderboard_rows_without_javascript(self):
        page = parse(os.path.join(self.web, "index.html"))
        self.assertEqual([(r["id"], r["asset"]) for r in page.rows], [(r["p"]["post"]["id"], r["asset"]) for r in self.rows])
        self.assertEqual([r["rank"] for r in page.rows], list(range(1, len(self.rows) + 1)))
        for got, want in zip(page.rows, self.rows):
            f = got["fields"]
            self.assertEqual(json.loads(f["return"][0]), want["ret"])
            self.assertEqual(json.loads(f["best"][0]), want["best"])
            self.assertEqual(json.loads(f["status"][0]), want["p"]["status"])
            self.assertEqual(f["status"][1], prerender.status_label(want["p"]))
            self.assertEqual(f["return"][1], prerender.fmt_pct(want["ret"]))
            self.assertEqual(f["asset"][1], want["asset"])
            self.assertEqual(f["author"][1], "@" + want["p"]["post"]["author"])
        self.assertIn("prices as of", "".join(page.text))

    def test_every_position_page_without_javascript(self):
        for r in self.rows:
            p = r["p"]
            path = os.path.join(self.web, f"pos-{prerender.slug(p['post']['id'], r['asset'])}.html")
            page = parse(path)
            got = {f: (raw, text) for f, raw, text in page.fields}
            self.assertEqual(json.loads(got["entry"][0]), p["entry"], path)
            self.assertEqual(json.loads(got["latest"][0]), p["latest"], path)
            self.assertEqual(json.loads(got["return"][0]), r["ret"], path)
            self.assertEqual(json.loads(got["status"][0]), p["status"], path)
            self.assertEqual(got["status"][1], prerender.status_label(p), path)
            mains = [a for t, a in page.tags if t == "main"]
            self.assertEqual((mains[0]["data-post"], mains[0]["data-asset"]), (p["post"]["id"], r["asset"]))
            metas = {a.get("property") or a.get("name"): a.get("content") for t, a in page.tags if t == "meta"}
            self.assertIn(r["asset"], metas["og:title"])
            self.assertIn(prerender.fmt_pct(r["ret"]), metas["og:description"])

    def test_no_stale_or_missing_pages(self):
        want = {f"pos-{prerender.slug(r['p']['post']['id'], r['asset'])}.html" for r in self.rows}
        have = {n for n in os.listdir(self.web) if n.startswith("pos-")}
        self.assertEqual(have, want)

    def test_only_known_scripts_and_no_inline_code(self):
        for name in ["index.html", "position.html"] + sorted(n for n in os.listdir(self.web) if n.startswith("pos-")):
            page = parse(os.path.join(self.web, name))
            for tag, a in page.tags:
                if tag == "script":
                    self.assertIn(a.get("src"), ALLOWED_SCRIPTS, name)
                self.assertFalse([k for k in a if k.startswith("on")], f"{name}: event handler on <{tag}>")
                self.assertNotIn("style", a, f"{name}: inline style on <{tag}> (blocked by the CSP)")


class HostileText(unittest.TestCase):
    def test_attack_fixtures_render_as_text(self):
        tmp, web = site_copy(os.path.join(HERE, "tests", "fixtures", "attack_records"))
        try:
            pages = ["index.html"] + sorted(n for n in os.listdir(web) if n.startswith("pos-"))
            self.assertGreater(len(pages), 1)
            seen_payload = False
            for name in pages:
                page = parse(os.path.join(web, name))
                for tag, a in page.tags:
                    self.assertNotIn(tag, ("iframe", "object", "embed", "svg"), f"{name}: <{tag}> injected")
                    if tag == "script":
                        self.assertIn(a.get("src"), ALLOWED_SCRIPTS, name)
                    if tag == "img":
                        self.assertTrue(a.get("src", "").startswith("avatars/"), f"{name}: foreign img {a}")
                    if tag == "a":
                        self.assertFalse(a.get("href", "").lower().startswith("javascript:"), name)
                    self.assertFalse([k for k in a if k.startswith("on")], f"{name}: event handler on <{tag}>")
                seen_payload |= '<script>window.__pwned="script tag"</script>' in "".join(page.text)
            self.assertTrue(seen_payload, "the hostile text should be visible as literal text")
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
