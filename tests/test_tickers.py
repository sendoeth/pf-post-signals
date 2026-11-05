"""Step 22, offline: plain tickers with safe automatic price resolution (tickers.py), coin legs and
their sides (detect.coin_legs / leg_side), the add tool without --asset (tools/add_call.py --leg),
and the rename to a plain ticker without changing a number (tools/rename_asset.py).
Run: python3 -m unittest -v tests.test_tickers"""
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import detect  # noqa: E402
import resolve  # noqa: E402
import tickers  # noqa: E402

POST = ("Probably best trade to capture my view towards hyperliquid:native and $LIT right now is selling some $100 HYPE calls for Dec25, "
        "and buying ~equal premium of $LIT calls.\n\nOn @DeriveXYZ that'd look something like:\n\nDeposit 1000 hyperliquid:native \n"
        "Sell 1000x$100C hyperliquid:native")


class FakeNet:
    """The live answers seen on 2026-11-01 (Binance LITUSDT halted at a stale 0.743; Lighter 3.26 on Hyperliquid)."""
    def __init__(self, down=False, **over):
        self.down, self.calls = down, []
        self.search = {"LIT": [("lighter", "Lighter", 82), ("litentry", "Litentry", 1787)], "HYPE": [("hyperliquid", "Hyperliquid", 10)],
                       "ZEC": [("zcash", "Zcash", 11), ("binance-peg-zcash-token", "Binance-Peg ZEC", None)],
                       "TWIN": [("twin-a", "Twin A", 300), ("twin-b", "Twin B", 500)], "NONAME": [("no-a", "No A", None), ("no-b", "No B", None)]}
        self.coins = {"lighter": ("LIT", "Lighter", 82, 3.26), "litentry": ("LIT", "Litentry", 1787, 0.097), "hyperliquid": ("HYPE", "Hyperliquid", 10, 88.14),
                      "zcash": ("ZEC", "Zcash", 11, 1235.11), "twin-a": ("TWIN", "Twin A", 300, 1.0), "chainlink": ("LINK", "Chainlink", 15, 14.0)}
        self.bin = {"LIT": ("BREAK", 0.743), "HYPE": ("TRADING", 88.14), "ZEC": ("TRADING", 1235.3), "LINK": ("TRADING", 14.02)}
        self.hl = {"LIT": (False, 3.25265), "HYPE": (False, 88.1065), "ZEC": (False, 1236.25)}
        self.contracts = {("ethereum", "0x514910771af9ca656af840dff83e8264ecf986ca"): "chainlink"}
        self.__dict__.update(over)

    def _up(self, what):
        self.calls.append(what)
        if self.down:
            raise tickers.Unavailable("api.coingecko.com: HTTP 429")

    def cg_search(self, symbol):
        self._up(("search", symbol))
        return [{"id": i, "symbol": symbol, "name": n, "rank": r} for i, n, r in self.search.get(symbol, [])]

    def cg_coin(self, cg_id):
        self._up(("coin", cg_id))
        c = self.coins.get(cg_id)
        return {"id": cg_id, "symbol": c[0], "name": c[1], "rank": c[2], "price": c[3]} if c else None

    def cg_contract(self, platform, address):
        self._up(("contract", platform, address))
        return self.contracts.get((platform, address.lower()))

    def binance(self, t):
        b = self.bin.get(t)
        return {"source": "binance", "symbol": f"{t}USDT", "trading": b[0] == "TRADING", "status": b[0], "price": b[1]} if b else None

    def okx(self, t):
        return None                                   # step 23 venues: not listed unless a test says so

    def hlspot(self, t):                        # step 26: no Hyperliquid spot pair in these older scenarios
        self.calls.append(("hlspot", t))
        return []

    def cg_platforms(self, cg_id):              # step 26: no contract on a supported chain -> no DEX pool
        return {}

    def bybit(self, t):
        return None

    def gate(self, t):
        return None

    def hyperliquid(self, t):
        h = self.hl.get(t)
        return {"source": "hyperliquid", "symbol": t, "trading": not h[0], "status": "delisted" if h[0] else "trading", "price": h[1]} if h else None


EMPTY = {"schema": tickers.REGISTRY_SCHEMA, "tickers": {}}


class Resolver(unittest.TestCase):
    def test_lit_is_lighter_on_hyperliquid_not_the_halted_binance_pair(self):
        r = tickers.resolve_ticker("$lit", FakeNet(), registry=EMPTY)
        self.assertEqual((r["status"], r["coin"]["id"], r["chosen"]), ("ok", "lighter", {"source": "hyperliquid", "symbol": "LIT"}))
        b = r["venues"][0]
        self.assertEqual((b["source"], b["ok"]), ("binance", False))
        self.assertIn("not trading (status BREAK)", b["why"])
        self.assertEqual(r["candidates"][1]["id"], "litentry")                     # the other LIT is in the receipt

    def test_a_trading_pair_with_the_wrong_price_is_skipped(self):
        r = tickers.resolve_ticker("LIT", FakeNet(bin={"LIT": ("TRADING", 0.743)}), registry=EMPTY)
        self.assertEqual(r["chosen"]["source"], "hyperliquid")
        self.assertIn("-77.2%", r["venues"][0]["why"])
        self.assertIn("a different coin or a stale pair", r["venues"][0]["why"])

    def test_no_agreeing_venue_is_review(self):
        r = tickers.resolve_ticker("LIT", FakeNet(hl={"LIT": (False, 9.0)}), registry=EMPTY)
        self.assertEqual((r["status"], r["chosen"]), ("review", None))
        self.assertIn("no trading venue", r["reason"])

    def test_binance_first_when_it_agrees(self):
        net = FakeNet()
        r = tickers.resolve_ticker("HYPE", net, registry=EMPTY)
        self.assertEqual(r["chosen"], {"source": "binance", "symbol": "HYPEUSDT"})
        self.assertTrue(all(v["ok"] for v in r["venues"] if v["listed"]))
        self.assertEqual([v["source"] for v in r["venues"]], ["binance", "hyperliquid", "okx", "gate"])   # every exchange venue is checked and listed
        self.assertNotIn(("hlspot", "HYPE"), net.calls)                                     # step 26: spot / DEX only when no exchange passed

    def test_identity_rules(self):
        self.assertEqual(tickers.resolve_ticker("ZEC", FakeNet(), registry=EMPTY)["coin"]["id"], "zcash")   # unranked bridged copies ignored
        for sym, status, why in [("TWIN", "review", "two comparable coins"), ("NONAME", "review", "none ranked"),
                                 ("NOPE", "refused", "no coin with the symbol"), ("not a ticker!", "refused", "not a ticker")]:
            r = tickers.resolve_ticker(sym, FakeNet(), registry=EMPTY)
            self.assertEqual(r["status"], status, sym)
            self.assertIn(why, r["reason"], sym)

    def test_provider_down_fails_closed(self):
        r = tickers.resolve_ticker("LIT", FakeNet(down=True), registry=EMPTY)
        self.assertEqual((r["status"], r["chosen"], r["coin"]), ("refused", None, None))
        self.assertIn("nothing guessed", r["reason"])

    def test_rate_limit_waits_then_fails_closed(self):
        slept = []
        net = tickers.Net(waits=(1, 2), sleep=slept.append)

        def fake_open(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
        orig = tickers.urllib.request.urlopen
        tickers.urllib.request.urlopen = fake_open
        try:
            with self.assertRaises(tickers.Unavailable):
                net.get("https://api.coingecko.com/api/v3/search?query=LIT")
        finally:
            tickers.urllib.request.urlopen = orig
        self.assertEqual(slept, [1, 2])

    def test_contract_tags(self):
        r = tickers.resolve_contract("hyperliquid", "native", FakeNet(), registry=EMPTY)
        self.assertEqual((r["status"], r["ticker"], r["asked"], r["coin"]["id"]), ("ok", "HYPE", "hyperliquid:native", "hyperliquid"))
        r = tickers.resolve_contract("ethereum", "0x514910771AF9Ca656af840dff83E8264EcF986CA", FakeNet(), registry=EMPTY)
        self.assertEqual((r["status"], r["ticker"]), ("ok", "LINK"))
        r = tickers.resolve_contract("ethereum", "0x" + "1" * 40, FakeNet(), registry=EMPTY)
        self.assertEqual(r["status"], "review")
        self.assertEqual(tickers.resolve_contract("hyperliquid", "native", FakeNet(down=True), registry=EMPTY)["status"], "refused")
        self.assertEqual([m.group(0) for m in tickers.CONTRACT_TAG.finditer(POST)], ["hyperliquid:native"] * 3)

    def test_registry(self):
        d = tempfile.mkdtemp()
        try:
            r = tickers.resolve_ticker("LIT", FakeNet(), registry=EMPTY)
            e = tickers.register(r, d)
            self.assertEqual((e["coingecko_id"], e["source"], e["symbol"]), ("lighter", "hyperliquid", "LIT"))
            self.assertEqual(tickers.register(r, d), e)                                # same coin again: no-op
            reg = tickers.load_registry(os.path.join(d, "data", "tickers.json"))
            other = tickers.resolve_ticker("LIT", FakeNet(search={"LIT": [("litentry", "Litentry", 1787)]}, hl={}, bin={"LIT": ("TRADING", 0.097)}), registry=reg)
            self.assertEqual(other["status"], "review")                                # a different LIT than the one on the site
            self.assertIn("already Lighter", other["reason"])
            with self.assertRaises(ValueError):
                tickers.register(tickers.resolve_ticker("TWIN", FakeNet(), registry=EMPTY), d)
            self.assertEqual(resolve.registered_tickers(os.path.join(d, "data", "tickers.json"))["LIT"]["source"], "hyperliquid")
        finally:
            shutil.rmtree(d)


class Legs(unittest.TestCase):
    def test_the_koolkrypto_post(self):
        legs = detect.coin_legs(POST, net=FakeNet(), registry=EMPTY)
        self.assertEqual([(l["asset"], l["status"], l["via"]) for l in legs], [("HYPE", "ok", ["hyperliquid:native"]), ("LIT", "ok", ["$LIT"])])
        self.assertEqual(legs[1]["receipt"]["coin"]["id"], "lighter")
        self.assertEqual(detect.leg_side(POST, ["HYPE", "hyperliquid:native"])[:2], (None, "selling calls caps the upside; it is not a stated short"))
        self.assertEqual(detect.leg_side(POST, ["LIT"]), (1, "buying calls", "buying ~equal premium of $LIT calls"))

    def test_sides(self):
        for text, aliases, side in [("I'm long $SOL here", ["SOL"], 1), ("bought some ZEC puts", ["ZEC"], -1), ("sold BTC puts into the dip", ["BTC"], 1),
                                    ("shorting $ETH", ["ETH"], -1), ("watching $LIT", ["LIT"], None), ("buying HYPE calls and selling LIT calls", ["LIT"], None)]:
            self.assertEqual(detect.leg_side(text, aliases)[0], side, text)

    def test_mapped_assets_need_no_lookup(self):
        net = FakeNet()
        legs = detect.coin_legs("long $BTC and gold here", net=net, registry=EMPTY)
        self.assertEqual([l["asset"] for l in legs], ["BTC", "GOLD"])
        self.assertEqual(net.calls, [])

    def test_a_refused_coin_is_listed_not_guessed(self):
        legs = detect.coin_legs("$NOPE to the moon", net=FakeNet(), registry=EMPTY)
        self.assertEqual((legs[0]["asset"], legs[0]["status"]), (None, "refused"))


class AddWithoutAsset(unittest.TestCase):
    """tools/add_call.py on the real post text with a fake provider and price feed (scratch copy of the site)."""
    def setUp(self):
        import add_call
        self.ac = add_call
        self.root = tempfile.mkdtemp(prefix="quanty-legs-")
        for d in ("records", "sources", "web", "data", "schema"):
            shutil.copytree(os.path.join(HERE, d), os.path.join(self.root, d))
        # the scratch site is as it was before this post was added: no HYPE / LIT records, tickers or receipts,
        # and the add tool reads the scratch registry (not the live one)
        for f in __import__("glob").glob(os.path.join(self.root, "records", "posts", "2116898993435463783_*.json")):
            os.remove(f)
        reg_path = os.path.join(self.root, "data", "tickers.json")
        if os.path.exists(reg_path):
            reg = json.load(open(reg_path))
            for t in ("HYPE", "LIT"):
                reg["tickers"].pop(t, None)
                if os.path.exists(os.path.join(self.root, "sources", "tickers", f"{t}.json")):
                    os.remove(os.path.join(self.root, "sources", "tickers", f"{t}.json"))
            json.dump(reg, open(reg_path, "w"), indent=1)
        import build_chart
        json.dump(build_chart.build(os.path.join(self.root, "records")), open(os.path.join(self.root, "web", "data", "charts.json"), "w"), indent=1)
        self._reg = resolve.registered_tickers
        resolve.registered_tickers = lambda path=None: self._reg(path or reg_path)
        self._treg, self._there = tickers.REGISTRY, tickers.HERE      # the resolver reads the scratch registry and receipts too
        tickers.REGISTRY, tickers.HERE = reg_path, self.root
        self.embed = {"__typename": "Tweet", "id_str": "2116898993435463783", "created_at": "2026-11-01T14:23:44.000Z", "text": POST,
                      "display_text_range": [0, len(POST)], "entities": {"symbols": [{"text": "LIT"}]}, "conversation_id_str": "2116898993435463783",
                      "user": {"screen_name": "koolkrypto223"}}

        class Prices:
            label = "fake"

            def series(self, info, since):
                return [["2026-11-01T15:00:00Z", 3.2523], ["2026-11-01T16:00:00Z", 3.24], ["2026-11-01T17:00:00Z", 3.2362]]

            def daily_until(self, info, since):
                return None
        self.prices = Prices()
        self.url = "https://x.com/koolkrypto223/status/2116898993435463783"

    def tearDown(self):
        resolve.registered_tickers = self._reg
        tickers.REGISTRY, tickers.HERE = self._treg, self._there
        shutil.rmtree(self.root)

    def test_two_coins_need_a_leg_then_lit_is_lighter(self):
        net = FakeNet()
        with self.assertRaises(self.ac.Refused) as c:
            self.ac.preview(self.url, root=self.root, fetch=lambda pid: self.embed, prices=self.prices, net=net)
        msg = str(c.exception)
        self.assertIn("several coins in this post", msg)
        self.assertIn("LEG HYPE side none", msg)
        self.assertIn("LEG LIT side long: buying calls", msg)
        self.assertIn("Lighter [lighter] on hyperliquid:LIT", msg)
        p = self.ac.preview(self.url, root=self.root, fetch=lambda pid: self.embed, prices=self.prices, net=net, leg="LIT")
        r = p["record"]
        self.assertEqual((r["asset"]["name"], r["asset"]["source"], r["asset"]["symbol"], r["side"]), ("LIT", "hyperliquid", "LIT", 1))
        self.assertEqual(r["asset_choice"]["method"], "detector")                      # not --asset
        self.assertIsNone(r["asset_choice"]["reason"])
        self.assertEqual(r["asset_choice"]["ticker"]["coingecko_id"], "lighter")
        self.assertEqual(r["asset_choice"]["leg"]["of"], ["HYPE", "LIT"])
        self.assertEqual(r["side_choice"]["method"], "detector-leg")
        self.assertFalse(os.path.exists(os.path.join(self.root, "data", "tickers.json")) and "LIT" in json.load(open(os.path.join(self.root, "data", "tickers.json")))["tickers"])
        resolve.check_record(resolve.validator(), r)
        log = self.ac.add(p["pending_file"], root=self.root, fetch=lambda pid: self.embed, save_avatar=False, ohlc=None)
        self.assertEqual(log["tickers_registered"][0]["coingecko_id"], "lighter")
        reg = json.load(open(os.path.join(self.root, "data", "tickers.json")))["tickers"]["LIT"]
        self.assertEqual((reg["source"], reg["symbol"]), ("hyperliquid", "LIT"))
        self.assertTrue(os.path.exists(os.path.join(self.root, reg["receipt"])))
        self.assertTrue(log["matches_preview"])

    def test_hype_leg_has_no_side_and_unknown_coins_are_refused(self):
        p = self.ac.preview(self.url, root=self.root, fetch=lambda pid: self.embed, prices=self.prices, net=FakeNet(), leg="HYPE")
        self.assertEqual((p["record"]["asset"]["name"], p["record"].get("side")), ("HYPE", None))
        self.assertIn("caps the upside", p["record"]["side_choice"]["reason"])
        with self.assertRaises(self.ac.Refused) as c:
            self.ac.preview(self.url, root=self.root, fetch=lambda pid: self.embed, prices=self.prices, net=FakeNet(down=True))
        self.assertIn("could not be confirmed", str(c.exception))
        self.assertIn("REVIEW", str(c.exception))
        with self.assertRaises(self.ac.Refused):
            self.ac.preview(self.url, root=self.root, fetch=lambda pid: self.embed, prices=self.prices, net=FakeNet(), leg="BTC")


class CodexRepros(AddWithoutAsset):
    """The three cases Codex reproduced before sign-off."""
    n = 0

    def run_text(self, text, **kw):
        CodexRepros.n += 1                                   # a fresh post id each time (same timestamp, other low bits)
        pid = str(2116898993435463783 + CodexRepros.n)
        self.embed = dict(self.embed, id_str=pid, conversation_id_str=pid, text=text, display_text_range=[0, len(text)])
        return self.ac.preview(f"https://x.com/koolkrypto223/status/{pid}", root=self.root, fetch=lambda _pid: self.embed, prices=self.prices, **kw)

    def test_a_registered_venue_that_fails_today_is_refused(self):
        reg = {"schema": tickers.REGISTRY_SCHEMA, "tickers": {"LIT": {"coingecko_id": "lighter", "name": "Lighter", "source": "binance", "symbol": "LITUSDT",
                                                                      "receipt": "x", "receipt_sha256": "0" * 64, "added_at": "x"}}}
        json.dump(reg, open(os.path.join(self.root, "data", "tickers.json"), "w"))
        with self.assertRaises(self.ac.Refused) as c:
            self.run_text("I am buying $LIT calls", net=FakeNet())
        self.assertIn("failed today's check", str(c.exception))
        self.assertIn("hyperliquid:LIT passed", str(c.exception))

    def test_a_mapped_cashtag_does_not_hide_a_contract_tag(self):
        with self.assertRaises(self.ac.Refused) as c:
            self.run_text("Buying $BTC and hyperliquid:native here", net=FakeNet())
        self.assertIn("several coins", str(c.exception))
        self.assertIn("LEG BTC", str(c.exception))
        self.assertIn("LEG HYPE", str(c.exception))

    def test_buying_puts_on_one_coin_is_short(self):
        p = self.run_text("I am buying $LIT puts", net=FakeNet())
        self.assertEqual((p["record"]["asset"]["name"], p["record"]["side"]), ("LIT", -1))
        self.assertEqual(p["record"]["side_choice"]["reason"], "buying puts")
        p = self.run_text("buying some bitcoin puts here", net=FakeNet())             # a mapped asset too
        self.assertEqual((p["record"]["asset"]["name"], p["record"]["side"]), ("BTC", -1))
        p = self.run_text("$LIT calls look cheap", net=FakeNet())                        # option words, no verb: no side
        self.assertIsNone(p["record"].get("side"))


class Rename(unittest.TestCase):
    def test_a_rename_changes_no_number_and_keeps_the_old_url(self):
        import rename_asset
        import prerender
        root = tempfile.mkdtemp(prefix="quanty-ren-")
        try:
            for d in ("records", "data", "web", "intake", "sources", "schema"):
                shutil.copytree(os.path.join(HERE, d), os.path.join(root, d))
            names = {json.load(open(f))["asset"]["name"] for f in __import__("glob").glob(os.path.join(root, "records", "**", "*.json"), recursive=True)}
            if "binance:ZECUSDT" not in names:
                self.skipTest("already renamed in this checkout")
            with self.assertRaises(SystemExit):                                         # a ticker on another venue is not a pure rename
                rename_asset.rename("binance:ZECUSDT", "ZEC", root=root, net=FakeNet(bin={}))
            rep = rename_asset.rename("binance:ZECUSDT", "ZEC", root=root, net=FakeNet())
            self.assertTrue(rep["equal"], rep["problems"])
            self.assertEqual(rep["positions_before"], rep["positions_after"])
            self.assertEqual(rep["caller_scores_before"], rep["caller_scores_after"])
            old = os.path.join(root, "web", "pos-1970742039722479782_binance-ZECUSDT.html")
            page = open(old).read()
            self.assertIn('content="0; url=pos-1970742039722479782_ZEC.html"', page)
            self.assertTrue(os.path.exists(os.path.join(root, "web", "pos-1970742039722479782_ZEC.html")))
            prerender.main(os.path.join(root, "web"))                                   # a rebuild keeps the redirect
            self.assertTrue(os.path.exists(old))
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
