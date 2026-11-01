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
import rate  # noqa: E402

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

    def test_other_calls_on_the_same_asset(self):
        for r in self.rows:
            p = r["p"]
            page = parse(os.path.join(self.web, f"pos-{prerender.slug(p['post']['id'], r['asset'])}.html"))
            want = sorted((o for o in self.rows if o["asset"] == r["asset"] and o["p"]["post"]["id"] != p["post"]["id"]),
                          key=lambda o: (o["p"]["post"]["posted_at"], o["p"]["post"]["id"]))
            got = {f: raw for f, raw, _ in page.fields}
            self.assertEqual(json.loads(got["other_calls"]), [o["p"]["post"]["id"] for o in want])
            links = [a["href"] for t, a in page.tags if t == "a" and a.get("href", "").startswith("pos-")]
            self.assertEqual(links, [f"pos-{prerender.slug(o['p']['post']['id'], o['asset'])}.html" for o in want])
            text = "".join(page.text)
            for o in want:
                self.assertIn(f"@{o['p']['post']['author']} · {'NO SIDE' if o['side'] == 'none' else o['side'].upper()} · "
                              f"{prerender.fmt_time(o['p']['post']['posted_at'])} · {'realized' if o['p'].get('closed') else 'return'} {prerender.fmt_pct(o['ret'])}", text)

    def test_advice_notice_on_every_page(self):
        """Step 20: the same not-financial-advice notice on every page, also without JavaScript."""
        names = ["index.html", "chart.html", "position.html"] + sorted(n for n in os.listdir(self.web) if n.startswith(("pos-", "caller-")))
        texts = set()
        import re
        for name in names:
            with open(os.path.join(self.web, name), encoding="utf-8") as f:
                got = re.findall(r'<p class="nfa" id="nfa" data-field="nfa">(.*?)</p>', f.read(), re.S)
            self.assertEqual(len(got), 1, name)
            texts.add(" ".join(re.sub(r"<[^>]+>", "", got[0]).split()))
        self.assertEqual(len(texts), 1)                                   # identical wording everywhere
        self.assertTrue(texts.pop().startswith("Not financial advice. The calls on this site are public posts by their authors"))
        links = [a.get("href") for t, a in parse(os.path.join(self.web, "index.html")).tags if t == "a"]
        self.assertIn("#nfa", links)

    def test_no_stale_or_missing_pages(self):
        want = {f"pos-{prerender.slug(r['p']['post']['id'], r['asset'])}.html" for r in self.rows}
        have = {n for n in os.listdir(self.web) if n.startswith("pos-")}
        # step 22: a renamed position keeps its old URL as a static redirect to a page that exists
        red_path = os.path.join(os.path.dirname(self.web), "data", "redirects.json")
        redirects = json.load(open(red_path))["pages"] if os.path.exists(red_path) else {}
        for old in have - want:
            self.assertIn(old, redirects, f"{old} is neither a position nor a listed redirect")
            self.assertIn(redirects[old]["to"], want)
            page = open(os.path.join(self.web, old)).read()
            self.assertIn(f'<meta http-equiv="refresh" content="0; url={redirects[old]["to"]}">', page)
        self.assertEqual(have - set(redirects), want)
        callers = {f"caller-{rate.caller_slug(n)}.html" for n in self.bundle["ratings"]["callers"]}
        self.assertEqual({n for n in os.listdir(self.web) if n.startswith("caller-")}, callers)

    def test_caller_scores_without_javascript(self):
        rt = self.bundle["ratings"]
        # leaderboard author table: score order, raw score, display, caller link
        page = parse(os.path.join(self.web, "index.html"))
        trs = [a["data-author"] for t, a in page.tags if t == "tr" and a.get("data-static") == "1"]
        self.assertEqual(trs, rt["order"])
        scores = [(raw, text) for f, raw, text in page.fields if f == "score"]
        self.assertEqual([json.loads(r) for r, _ in scores], [rt["callers"][n]["score"] for n in rt["order"]])
        for (_, text), n in zip(scores, rt["order"]):
            self.assertTrue(text.startswith(rt["callers"][n]["display"]), text)
        links = [a["href"] for t, a in page.tags if t == "a" and a.get("class") == "caller-link"]
        self.assertEqual(links, [f"caller-{rate.caller_slug(n)}.html" for n in rt["order"]])
        # caller pages: every input and every call, equal to the bundle
        for name, c in rt["callers"].items():
            cp = parse(os.path.join(self.web, f"caller-{rate.caller_slug(name)}.html"))
            got = {f: raw for f, raw, _ in cp.fields}
            self.assertEqual(json.loads(got["caller"]), name)
            self.assertEqual(json.loads(got["score"]), c["score"])
            self.assertEqual(json.loads(got["score_exact"]), c["score"])
            for k in ("calls_total", "with_entry", "scored"):
                self.assertEqual(json.loads(got[k]), c[k], name)
            if c["components"]:
                for k in ("hit", "quality", "clarity"):
                    self.assertEqual(json.loads(got[k]), c["components"][k], name)
                self.assertEqual((json.loads(got["raw"]), json.loads(got["weight"])), (c["raw"], c["weight"]))
            rows = [a for t, a in cp.tags if t == "tr" and "data-post-id" in a]
            self.assertEqual([(a["data-post-id"], a["data-asset"], a["data-counted"]) for a in rows],
                             [(x["post_id"], x["asset"], str(x["counted"]).lower()) for x in c["calls"]])
            results = [json.loads(raw) for f, raw, _ in cp.fields if f == "call_result"]
            self.assertEqual(results, [x["result"] for x in c["calls"]])
            metas = {a.get("property") or a.get("name"): a.get("content") for t, a in cp.tags if t == "meta"}
            self.assertIn(c["display"], metas["og:title"])
        # position pages: the caller's score row
        for r in self.rows:
            pp = parse(os.path.join(self.web, f"pos-{prerender.slug(r['p']['post']['id'], r['asset'])}.html"))
            text = {f: t for f, _, t in pp.fields}
            c = rt["callers"][r["p"]["post"]["author"]]
            self.assertTrue(text["caller_score"].startswith(f'{c["display"]} / 100 (rank {c["rank"]}'), text["caller_score"])

    def test_only_known_scripts_and_no_inline_code(self):
        for name in ["index.html", "position.html"] + sorted(n for n in os.listdir(self.web) if n.startswith(("pos-", "caller-"))):
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
            pages = ["index.html"] + sorted(n for n in os.listdir(web) if n.startswith(("pos-", "caller-")))
            self.assertTrue(any(n.startswith("caller-") for n in pages))
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


class HostileCaller(unittest.TestCase):
    """A hostile author name never reaches the pages in practice (the record schema refuses it, see
    tests/fixtures/attack_expected.json); rendered anyway, it must stay text."""
    def test_hostile_name_renders_as_text(self):
        name = '"><img src=x onerror=window.__pwned=3><script>window.__pwned=4</script>'
        bundle = {"prices_as_of": "2026-10-31T00:00:00Z", "assets": [{"name": "BTC", "posts": [
            {"post": {"id": "1", "author": name, "posted_at": "2026-10-01T00:00:00Z", "text": "t", "url": "https://x.com/a/status/1"},
             "side": 1, "change_since_post": 0.1, "entry": {"at": "2026-10-01T00:00:00Z", "price": 1.0}}]}]}
        rt = rate.rate_bundle(bundle)
        html_text = prerender.caller_static(name, rt["callers"][name], rt, {})
        page = Page()
        page.feed(html_text)
        self.assertFalse([t for t, a in page.tags if t in ("img", "script", "iframe", "svg")])
        self.assertFalse([a for t, a in page.tags if any(k.startswith("on") for k in a)])
        self.assertIn(name, "".join(page.text))
        self.assertRegex(rate.caller_slug(name), r"^[a-z0-9_-]+$")


if __name__ == "__main__":
    unittest.main()
