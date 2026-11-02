"""Step 23, offline: seeding the top coins and Hyperliquid perps (tools/seed_tickers.py), finding them in
post text (detect.coin_legs), resolving them with no provider call (tickers.from_registry), the weekly
venue re-check (tools/recheck_tickers.py), the OKX / Bybit / Gate candles (resolve.exchange_candles)
and the coverage page (tools/coins_page.py).
Run: python3 -m unittest -v tests.test_seed"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import detect  # noqa: E402
import recheck_tickers  # noqa: E402
import resolve  # noqa: E402
import seed_tickers as st  # noqa: E402
import tickers  # noqa: E402
import coins_page  # noqa: E402

AT = "2026-11-01T20:00:00Z"


def coin(rank, sym, cid, name, price):
    return {"market_cap_rank": rank, "symbol": sym.lower(), "id": cid, "name": name, "current_price": price}


class FakeBulk(st.Bulk):
    """A tiny market built from values seen on 2026-11-01."""
    def __init__(self, **over):
        super().__init__(net=None, sleep=lambda s: None, fetch_text=lambda u: "")
        self.markets = [coin(1, "BTC", "bitcoin", "Bitcoin", 110000.0), coin(2, "ETH", "ethereum", "Ethereum", 3900.0),
                        coin(3, "USDT", "tether", "Tether", 1.0), coin(4, "SOL", "solana", "Solana", 190.0),
                        coin(5, "XAUT", "tether-gold", "Tether Gold", 3990.0), coin(6, "WBTC", "wrapped-bitcoin", "Wrapped Bitcoin", 110000.0),
                        coin(7, "USDX", "usdx-new", "USDX New", 1.001), coin(8, "LEO", "leo-token", "LEO Token", 9.6),
                        coin(9, "LIT", "lighter", "Lighter", 3.23), coin(10, "SUI", "sui", "Sui", 2.4), coin(11, "LINK", "chainlink", "Chainlink", 17.0),
                        coin(12, "TWIN", "twin-a", "Twin A", 1.0), coin(13, "TWIN", "twin-b", "Twin B", 1.0), coin(14, "BGB", "bitget-token", "Bitget Token", 4.5),
                        coin(15, "DASH", "dash", "Dash", 50.0), coin(16, "PEPE", "pepe", "Pepe", 0.00001), coin(17, "NEAR", "near", "NEAR Protocol", 2.5),
                        coin(1787, "LIT", "litentry", "Litentry", 0.097), coin(400, "MOODENG", "moo-deng", "Moo Deng", 0.2)]
        self.category = {"tether": ["stablecoins"], "tether-gold": ["tokenized-gold"], "wrapped-bitcoin": ["wrapped-tokens"]}
        self.bin_status = {"BTCUSDT": "TRADING", "ETHUSDT": "TRADING", "SOLUSDT": "TRADING", "LITUSDT": "BREAK", "SUIUSDT": "TRADING", "LINKUSDT": "TRADING",
                           "TWINUSDT": "TRADING", "DASHUSDT": "TRADING", "PEPEUSDT": "TRADING", "NEARUSDT": "TRADING"}
        self.bin_price = {"BTCUSDT": 110050.0, "ETHUSDT": 3901.0, "SOLUSDT": 189.5, "LITUSDT": 0.743, "SUIUSDT": 2.41, "LINKUSDT": 17.01, "TWINUSDT": 1.0,
                          "DASHUSDT": 50.2, "PEPEUSDT": 0.0000101, "NEARUSDT": 2.5}
        self.hl = {"LIT": {"name": "LIT"}, "kPEPE": {"name": "kPEPE"}, "MOODENG": {"name": "MOODENG"}, "OLD": {"name": "OLD", "isDelisted": True}, "NOCOIN": {"name": "NOCOIN"}}
        self.hl_mid = {"LIT": 3.22, "kPEPE": 0.0101, "MOODENG": 0.201}
        self.okx_s, self.okx_p = {"LEO-USDT": "live"}, {"LEO-USDT": 9.55}
        self.byb_s, self.byb_p = {}, {}
        self.gate_s, self.gate_p = {"BGB_USDT": "untradable"}, {"BGB_USDT": 4.5}
        self.us = {"BTC": "Grayscale Bitcoin Mini Trust", "DASH": "DoorDash, Inc.", "HOOD": "Robinhood Markets", "COIN": "Coinbase Global"}
        self.words = {"near", "link", "top", "the", "one", "dash", "lighter", "sui"} - {"sui"}
        self.calls = [{"what": "fake"}]
        self.__dict__.update(over)


class Seed(unittest.TestCase):
    def setUp(self):
        self.b = FakeBulk()
        self.p = st.plan(self.b, top=10, perps=True, registry={"tickers": {}}, at=AT)

    def test_not_coins_are_excluded_with_the_reason(self):
        why = {x["ticker"]: x["why"] for x in self.p["excluded"]}
        self.assertEqual(why["USDT"], "stablecoin")
        self.assertEqual(why["XAUT"], "tokenized gold")
        self.assertEqual(why["WBTC"], "wrapped copy")
        self.assertIn("stablecoin (pegged near $1", why["USDX"])               # no category, but pegged with USD in the symbol
        self.assertEqual(next(x for x in self.p["excluded"] if x["ticker"] == "WBTC")["maps_to"], "BTC")

    def test_top_counts_coins_after_exclusions(self):
        self.assertEqual(len(self.p["top_listed"]), 10)
        self.assertNotIn("USDT", self.p["top_listed"])
        self.assertEqual(self.p["top_listed"][:4], ["BTC", "ETH", "SOL", "LEO"])

    def test_venues(self):
        s = self.p["seed"]
        self.assertEqual(s["LIT"]["chosen"], {"source": "hyperliquid", "symbol": "LIT"})       # the halted Binance pair is skipped
        self.assertIn("not trading (status BREAK)", s["LIT"]["venues"][0]["why"])
        self.assertEqual(s["LEO"]["chosen"], {"source": "okx", "symbol": "LEO-USDT"})          # only on OKX
        rev = {x["ticker"]: x["why"] for x in self.p["review"]}
        self.assertIn("no trading venue", rev["BGB"])                                           # gate pair untradable
        self.assertIn("two comparable coins named TWIN", rev["TWIN"])
        self.assertEqual(s["PEPE"]["chosen"]["source"], "binance")                              # kPEPE (1000 PEPE) is not a 1:1 price
        self.assertEqual(s["MOODENG"]["chosen"], {"source": "hyperliquid", "symbol": "MOODENG"})
        self.assertIn("MOODENG", self.p["perps"])
        self.assertIn("NOCOIN", rev)
        self.assertNotIn("OLD", rev)                                                            # a delisted perp is not considered
        self.assertEqual(s["DASH"]["also_us_stock"], "DoorDash, Inc.")

    def test_existing_venue_is_kept(self):
        reg = {"tickers": {"PEPE": {"coingecko_id": "pepe", "name": "Pepe", "source": "hyperliquid", "symbol": "kPEPE", "receipt": "x", "receipt_sha256": "0"}}}
        p = st.plan(self.b, top=10, perps=True, registry=reg, at=AT)
        self.assertNotIn("PEPE", p["seed"])                                                     # its venue fails today's check -> review, never re-priced
        self.assertIn("failed this check", next(x["why"] for x in p["review"] if x["ticker"] == "PEPE"))
        reg["tickers"]["PEPE"].update(source="binance", symbol="PEPEUSDT")
        self.assertIn("PEPE", st.plan(self.b, top=10, perps=True, registry=reg, at=AT)["seed"])

    def test_coin_words(self):
        w = st.coin_words(self.p, self.b)
        self.assertEqual(w["names"]["solana"], "SOL")
        self.assertNotIn("lighter", w["names"])                                                 # an ordinary word
        self.assertIn("LINK", w["bare_blocked"])
        self.assertIn("USDT", w["stablecoins"])
        self.assertEqual(w["wrapped"]["WBTC"], "BTC")
        self.assertIn("TOTAL3", w["index"])

    def test_write_registers_and_receipts(self):
        root = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(root, "data"))
            out = st.write(self.p, self.b, root)
            reg = json.load(open(os.path.join(root, "data", "tickers.json")))
            self.assertEqual(out["added"], len(self.p["seed"]))
            lit = reg["tickers"]["LIT"]
            self.assertEqual((lit["coingecko_id"], lit["source"], lit["seed"]), ("lighter", "hyperliquid", "sources/tickers/seed/2026-11-01.json"))
            r = tickers.from_registry("LIT", reg, root)                                         # offline, no provider call
            self.assertEqual((r["status"], r["coin"]["id"]), ("ok", "lighter"))
            seed = json.load(open(os.path.join(root, "sources", "tickers", "seed", "2026-11-01.json")))
            self.assertEqual(seed["counts"]["seeded"], len(self.p["seed"]))
            self.assertIn("tokenized gold", {x["why"] for x in seed["excluded"]})
            # a tampered receipt is not trusted
            open(os.path.join(root, lit["receipt"]), "a").write(" ")
            self.assertIsNone(tickers.from_registry("LIT", reg, root))
        finally:
            shutil.rmtree(root)


class Words(unittest.TestCase):
    def setUp(self):
        self.b = FakeBulk()
        self.p = st.plan(self.b, top=20, perps=True, registry={"tickers": {}}, at=AT)
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "data"))
        st.write(self.p, self.b, self.root)
        self.reg = json.load(open(os.path.join(self.root, "data", "tickers.json")))
        self.words = json.load(open(os.path.join(self.root, "data", "coin_words.json")))
        self._here, tickers.HERE = tickers.HERE, self.root

    def tearDown(self):
        tickers.HERE = self._here
        shutil.rmtree(self.root)

    def legs(self, text, net=None):
        class NoNet:
            def __getattr__(self, k):
                raise AssertionError(f"provider call {k} for: {text}")
        return [(l["asset"], l["status"]) for l in detect.coin_legs(text, net=net or NoNet(), registry=self.reg, words=self.words, us=self.b.us)]

    def test_names_and_bare_tickers_offline(self):
        self.assertEqual(self.legs("rotating out of SOL into SUI here, also bought some chainlink"), [("SOL", "ok"), ("SUI", "ok"), ("LINK", "ok")])
        self.assertEqual(self.legs("LONG LIT HERE"), [("LIT", "ok")])
        self.assertEqual(self.legs("$lit and $moodeng"), [("LIT", "ok"), ("MOODENG", "ok")])

    def test_ordinary_words_are_not_coins(self):
        self.assertEqual(self.legs("price is near the top, link in bio"), [])
        self.assertEqual(self.legs("NEAR the highs"), [])                                      # a common word even in capitals
        self.assertEqual(self.legs("total nonsense from the others"), [])

    def test_indexes_stables_wrapped_stocks(self):
        legs = self.legs("TOTAL3 breaking out while BTC.D and USDT.D roll over")
        self.assertEqual([s for _, s in legs], ["review"] * 3)
        self.assertNotIn(("BTC", "ok"), legs)                                                   # BTC.D is never BTC
        self.assertEqual(self.legs("stablecoin dominance falling, $SOL"), [(None, "review"), ("SOL", "ok")])
        self.assertEqual(self.legs("$USDT on the sidelines, $SOL"), [("SOL", "ok")])            # a stablecoin is not a call
        self.assertEqual(self.legs("long $WBTC"), [("BTC", "ok")])
        from tests.test_tickers import FakeNet
        # unknown cashtags that are US stocks: looked up, no top-500 coin -> the stock (review)
        self.assertEqual(self.legs("$HOOD and $COIN ripping", net=FakeNet()), [(None, "review"), (None, "review")])
        # a real top coin whose ticker is also an ETF stays the coin (Lighter #82 vs the Global X Lithium ETF) ...
        us_lit = dict(self.b.us, LIT="Global X Lithium & Battery Tech ETF")
        reg = {"tickers": {k: v for k, v in self.reg["tickers"].items() if k != "LIT"}}
        got = detect.coin_legs("buying $LIT calls", net=FakeNet(), registry=reg, words=self.words, us=us_lit)
        self.assertEqual([(l["asset"], l["status"]) for l in got], [("LIT", "ok")])
        # ... unless the post talks shares
        got = detect.coin_legs("$LIT shares look cheap vs lithium peers", net=FakeNet(), registry=reg, words=self.words, us=us_lit)
        self.assertEqual([(l["asset"], l["status"]) for l in got], [(None, "review")])
        self.assertEqual(self.legs("$DASH earnings beat, shares up"), [(None, "review")])
        self.assertEqual(self.legs("$DASH breaking out on privacy"), [("DASH", "ok")])

    def test_codex_repros(self):
        # 1. a flag reaches fixed-map coins too
        self.reg["tickers"]["SOL"]["flag"] = {"since": AT, "why": "binance:SOLUSDT is not trading (status BREAK)"}
        for t in ("$SOL", "long SOL", "bought some solana"):
            self.assertEqual(self.legs(t), [(None, "review")], t)
        del self.reg["tickers"]["SOL"]["flag"]
        # 2. a name / bare ticker with an untrusted receipt is not priced
        self.reg["tickers"]["SUI"]["receipt_sha256"] = "0" * 64
        self.assertEqual(self.legs("long SUI"), [(None, "review")])
        # 3. stock talk reaches every branch: a mapped cashtag, a name, a bare ticker
        self.reg["tickers"]["LINK"]["also_us_stock"] = "Interlink Electronics"
        self.assertEqual(self.legs("bought $LINK shares after earnings"), [(None, "review")])
        self.assertEqual(self.legs("bought chainlink shares after earnings"), [(None, "review")])
        self.reg["tickers"]["PEPE"]["also_us_stock"] = "Pepe Holdings"                      # a bare ticker that is not a common word (Codex: BDX)
        self.assertEqual(self.legs("bought PEPE shares after earnings"), [(None, "review")])
        self.assertEqual(self.legs("bought DASH shares after earnings"), [])                    # 'dash' is a common word: never matched bare
        self.assertEqual(self.legs("long LINK into the upgrade"), [("LINK", "ok")])            # no stock talk: the coin
        # real post (goodalexander 2026-10-30): "stocks" far from the coins is not stock talk about them
        self.reg["tickers"]["SOL"]["also_us_stock"] = "Some ETF"
        got = self.legs("Still like long SOL. sized down LINK am short bunch of single name stocks hedged it with long sui")
        ok = [a for a, st_ in got if st_ == "ok"]
        self.assertEqual(ok[:2], ["SOL", "LINK"])                                             # also US stocks, but not talked about as stocks
        self.assertIn("STOCKS", ok)                                                             # the stocks leg itself

    def test_flagged_ticker_goes_to_review(self):
        self.reg["tickers"]["SUI"]["flag"] = {"since": AT, "why": "binance:SUIUSDT is not trading (status BREAK)"}
        self.assertEqual(self.legs("$SUI"), [(None, "review")])


class Recheck(unittest.TestCase):
    def test_flags_recovers_and_never_swaps(self):
        b = FakeBulk()
        p = st.plan(b, top=10, perps=True, registry={"tickers": {}}, at=AT)
        root = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(root, "data"))
            st.write(p, b, root)
            reg = tickers.load_registry(os.path.join(root, "data", "tickers.json"))
            prices = {e["coingecko_id"]: {"price": c["current_price"], "rank": c["market_cap_rank"]} for e in reg["tickers"].values()
                      for c in b.markets if c["id"] == e["coingecko_id"]}
            b.bin_status["SOLUSDT"] = "BREAK"                                                  # SOL's pair halts
            b.bin_price["SUIUSDT"] = 3.5                                                       # SUI's pair drifts 46% off
            res, flagged, recovered = recheck_tickers.recheck(reg, b, prices, AT)
            self.assertEqual(sorted(flagged), ["SOL", "SUI"])
            self.assertIn("not trading (status BREAK)", reg["tickers"]["SOL"]["flag"]["why"])
            self.assertEqual(reg["tickers"]["SOL"]["source"], "binance")                       # never swapped to another venue
            b.bin_status["SOLUSDT"] = "TRADING"
            res, flagged, recovered = recheck_tickers.recheck(reg, b, prices, "2026-11-08T20:00:00Z")
            self.assertEqual(recovered, ["SOL"])
            self.assertNotIn("flag", reg["tickers"]["SOL"])
            self.assertEqual(reg["tickers"]["SUI"]["flag"]["since"], AT)                       # still flagged since the first time
            d = coins_page.build(root) if os.path.exists(os.path.join(root, "web")) else None
        finally:
            shutil.rmtree(root)

    def test_provider_down_writes_nothing(self):
        root = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(root, "data"))
            json.dump({"schema": tickers.REGISTRY_SCHEMA, "tickers": {"SOL": {"coingecko_id": "solana", "name": "Solana", "source": "binance", "symbol": "SOLUSDT"}}},
                      open(os.path.join(root, "data", "tickers.json"), "w"))

            class Down(FakeBulk):
                def _get(self, *a, **k):
                    raise tickers.Unavailable("api.coingecko.com: HTTP 429")
            self.assertEqual(recheck_tickers.main([], root=root, bulk=Down()), 3)
            self.assertFalse(os.path.exists(os.path.join(root, "sources")))
        finally:
            shutil.rmtree(root)


class Candles(unittest.TestCase):
    def test_okx_bybit_gate_parsing(self):
        import datetime as dt
        start = dt.datetime(2026, 11, 1, 10, tzinfo=dt.timezone.utc)
        now = dt.datetime(2026, 11, 1, 12, 30, tzinfo=dt.timezone.utc)
        ms = lambda h: int(dt.datetime(2026, 11, 1, h, tzinfo=dt.timezone.utc).timestamp() * 1000)
        pages = {"okx": [{"data": [[str(ms(12)), "3", "4", "2", "3.5"], [str(ms(11)), "2", "3", "1", "2.5"], [str(ms(10)), "1", "2", "0.5", "1.5"]]}, {"data": []}],
                 "bybit": [{"result": {"list": [[str(ms(12)), "3", "4", "2", "3.5", "0", "0"], [str(ms(11)), "2", "3", "1", "2.5", "0", "0"], [str(ms(10)), "1", "2", "0.5", "1.5", "0", "0"]]}}],
                 "gate": [[[str(ms(10) // 1000), "9", "1.5", "2", "0.5", "1", "9", "true"], [str(ms(11) // 1000), "9", "2.5", "3", "1", "2", "9", "true"],
                           [str(ms(12) // 1000), "9", "3.5", "4", "2", "3", "9", "false"]]]}
        orig = resolve.get_json
        try:
            for src, sym in (("okx", "LEO-USDT"), ("bybit", "XDCUSDT"), ("gate", "GT_USDT")):
                it = iter(pages[src])
                resolve.get_json = lambda url, tries=3: next(it, [] if src == "gate" else {"data": [], "result": {"list": []}})
                got = resolve.exchange_candles(src, sym, start, now=now)
                self.assertEqual(got, [["2026-11-01T10:00:00Z", 1.0, 2.0, 0.5, 1.5], ["2026-11-01T11:00:00Z", 2.0, 3.0, 1.0, 2.5],
                                       ["2026-11-01T12:00:00Z", 3.0, 4.0, 2.0, 3.5]], src)
            resolve.get_json = lambda url, tries=3: {"data": []}
            with self.assertRaises(resolve.UnknownAssetError):
                resolve.exchange_candles("okx", "NOPE-USDT", start, now=now)
        finally:
            resolve.get_json = orig
        self.assertEqual(resolve.asset_info("gate:GT_USDT")["source"], "gate")
        self.assertEqual(resolve.asset_info("okx:LEO-USDT")["symbol"], "LEO-USDT")


class Page(unittest.TestCase):
    def test_coins_page_is_static_and_escaped(self):
        b = FakeBulk()
        b.markets.append(coin(18, "XSS", "x<script>", "<img src=x onerror=alert(1)>", 1.5))
        b.bin_status["XSSUSDT"], b.bin_price["XSSUSDT"] = "TRADING", 1.5
        p = st.plan(b, top=20, perps=True, registry={"tickers": {}}, at=AT)
        root = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(root, "data"))
            os.makedirs(os.path.join(root, "web", "data"))
            st.write(p, b, root)
            coins_page.main(root)
            page = open(os.path.join(root, "web", "coins.html")).read()
            self.assertNotIn("<img src=x", page)
            self.assertNotIn("<script>", page.replace('<script src="assets/frame-guard.js"></script>', ""))
            self.assertIn("Content-Security-Policy", page)
            self.assertEqual(page.count('<p class="nfa" id="nfa"'), 1)
            d = json.load(open(os.path.join(root, "web", "data", "coins.json")))
            self.assertEqual(d["coverage"]["top_listed"], len(p["top_listed"]))
            self.assertIn("LIT", [c["ticker"] for c in d["coins"]])
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
