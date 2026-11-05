"""Step 26, offline: Hyperliquid spot pairs and DEX pools as price sources, and owner-resolved ambiguous tickers.
Pair choice (stablecoin quote, traded, price agrees, USDC first, deterministic), the stale pair never chosen,
pools found through the coin's contract (deepest that passes; thin, foreign, stale or disagreeing pools refused),
an ambiguous ticker resolved only by the owner's pick, the new sources priced and re-checked, and existing
coins keeping their venue. Run: python3 -m unittest -v tests.test_spot_dex"""
import json
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import detect          # noqa: E402
import resolve         # noqa: E402
import tickers         # noqa: E402

NEST2 = "0x07c57e32a3c29d5659bda1d3efc2e7bf004e3035"
WHYPE_POOL = "0x535f30f50ebda33575242c38b976e681d13db6fa"
NOW = time.time()


class FakeNet:
    """The providers, scripted. Every call recorded; `forbid` = methods that must not be called."""
    def __init__(self, coins=None, search=None, spot=None, pools=None, last=None, cex=None, platforms=None, forbid=()):
        self.coins = coins or {"kinetiq": {"id": "kinetiq", "symbol": "KNTQ", "name": "Kinetiq", "rank": 207, "price": 0.4621},
                               "nest-2": {"id": "nest-2", "symbol": "NEST", "name": "NEST", "rank": 1414, "price": 0.02567},
                               "nest-3": {"id": "nest-3", "symbol": "NEST", "name": "Nest", "rank": 3650, "price": 0.00125}}
        self.search = search or {"KNTQ": ["kinetiq"], "NEST": ["nest-2", "nest-3"]}
        self.spot = spot if spot is not None else [
            {"symbol": "@254", "base": "KNTQ", "quote": "USDH", "pair": "KNTQ/USDH", "price": None, "mark": 0.20712, "volume": 0.0},
            {"symbol": "@334", "base": "KNTQ", "quote": "USDC", "pair": "KNTQ/USDC", "price": 0.46301, "mark": 0.4629, "volume": 3_303_908.0}]
        self.pools = pools if pools is not None else {NEST2: [
            {"pool": WHYPE_POOL, "name": "NEST / WHYPE 2%", "dex": "nest", "base": NEST2, "liquidity": 1_187_522.0, "price": 0.025628, "volume_24h": 282_055.0},
            {"pool": "0xdb544d63d32d9f3e52ff3a8bfe2a374df0463f8d", "name": "NEST / USDC 2%", "dex": "nest", "base": NEST2, "liquidity": 505_825.0,
             "price": 0.025628, "volume_24h": 262_521.0}]}
        self.last = last or {}
        self.cex = cex or {}
        self.platforms = platforms or {"nest-2": {"hyperevm": NEST2}, "nest-3": {"solana": "68Nq68CrtLVpyvK5Un7UADiNczaGf39hBbj3diRsYj6D"},
                                       "kinetiq": {"hyperevm": "0x000000000000780555bd0bca3791f89f9542c2d6"}}
        self.forbid, self.calls = set(forbid), []

    def _rec(self, name, *a):
        if name in self.forbid:
            raise AssertionError(f"{name} must not be called")
        self.calls.append((name,) + a)

    def cg_search(self, symbol):
        self._rec("cg_search", symbol)
        return [{k: self.coins[i][k] for k in ("id", "symbol", "name", "rank")} for i in self.search.get(symbol, [])]

    def cg_coin(self, cg_id):
        self._rec("cg_coin", cg_id)
        return self.coins.get(cg_id)

    def cg_platforms(self, cg_id):
        self._rec("cg_platforms", cg_id)
        return self.platforms.get(cg_id, {})

    def hlspot(self, ticker):
        self._rec("hlspot", ticker)
        return [v for v in self.spot if v["base"] == ticker]

    def gt_pools(self, network, address):
        self._rec("gt_pools", network, address)
        return self.pools.get(address, [])

    def gt_last(self, network, pool):
        self._rec("gt_last", network, pool)
        return self.last.get(pool, {"last": int(NOW // 3600 * 3600), "base_cg_id": "nest-2"})

    def __getattr__(self, name):                          # binance / hyperliquid / okx / gate
        if name in ("binance", "hyperliquid", "okx", "gate"):
            def venue(ticker):
                self._rec(name, ticker)
                return self.cex.get((name, ticker))
            return venue
        raise AttributeError(name)


def resolve_t(sym, net, **kw):
    return tickers.resolve_ticker(sym, net, registry={"tickers": {}}, **kw)


class HyperliquidSpot(unittest.TestCase):
    def test_the_traded_usdc_pair_is_chosen_and_the_stale_pair_rejected(self):
        r = resolve_t("KNTQ", FakeNet())
        self.assertEqual((r["status"], r["chosen"]), ("ok", {"source": "hlspot", "symbol": "@334", "pair": "KNTQ/USDC"}))
        by = {v["symbol"]: v for v in r["venues"] if v["source"] == "hlspot"}
        self.assertFalse(by["@254"]["ok"])
        self.assertIn("stale pair", by["@254"]["why"])
        self.assertEqual((by["@254"]["mark"], by["@254"]["volume_24h"]), (0.20712, 0.0))   # the receipt keeps why
        self.assertTrue(by["@334"]["chosen"] and not by["@254"]["chosen"])

    def test_the_choice_is_deterministic_usdc_first_then_volume(self):    # the USDH pair has more volume: USDC still wins
        spot = [{"symbol": "@900", "base": "KNTQ", "quote": "USDH", "pair": "KNTQ/USDH", "price": 0.462, "mark": 0.462, "volume": 9_000_000.0},
                {"symbol": "@334", "base": "KNTQ", "quote": "USDC", "pair": "KNTQ/USDC", "price": 0.463, "mark": 0.463, "volume": 3_000_000.0},
                {"symbol": "@335", "base": "KNTQ", "quote": "USDC", "pair": "KNTQ/USDC", "price": 0.463, "mark": 0.463, "volume": 50_000.0}]
        for order in (spot, list(reversed(spot))):
            self.assertEqual(resolve_t("KNTQ", FakeNet(spot=order))["chosen"]["symbol"], "@334")

    def test_a_non_stable_quote_or_a_disagreeing_price_is_not_a_venue(self):
        spot = [{"symbol": "@500", "base": "KNTQ", "quote": "HYPE", "pair": "KNTQ/HYPE", "price": 0.011, "mark": 0.011, "volume": 500_000.0},
                {"symbol": "@501", "base": "KNTQ", "quote": "USDC", "pair": "KNTQ/USDC", "price": 0.60, "mark": 0.60, "volume": 500_000.0}]
        r = resolve_t("KNTQ", FakeNet(spot=spot, platforms={"kinetiq": {}}))
        self.assertEqual(r["status"], "review")
        why = {v["symbol"]: v["why"] for v in r["venues"] if v.get("symbol", "").startswith("@")}
        self.assertIn("not a USD stablecoin", why["@500"])
        self.assertIn("+29.8% from the coin's", why["@501"])

    def test_a_coin_with_an_exchange_venue_never_looks_at_spot_or_dex(self):
        cex = {("binance", "KNTQ"): {"source": "binance", "symbol": "KNTQUSDT", "trading": True, "status": "TRADING", "price": 0.462}}
        r = resolve_t("KNTQ", FakeNet(cex=cex, forbid=("hlspot", "cg_platforms", "gt_pools")))
        self.assertEqual(r["chosen"], {"source": "binance", "symbol": "KNTQUSDT"})


class Dex(unittest.TestCase):
    def test_the_owners_pick_prices_on_the_deepest_pool_found_by_contract(self):
        net = FakeNet()
        r = resolve_t("NEST", net, cg_id="nest-2", how="$NEST = nest-2 (owner pick)")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["chosen"], {"source": "dex", "symbol": f"hyperevm:{WHYPE_POOL}", "pair": "NEST / WHYPE 2%"})
        self.assertIn(("gt_pools", "hyperevm", NEST2), net.calls)                         # by contract, not by ticker
        self.assertEqual(r["asked"], "$NEST = nest-2 (owner pick)")
        pool = next(v for v in r["venues"] if v.get("pool") == WHYPE_POOL)
        self.assertEqual((pool["contract"], pool["pool_base_coingecko_id"], pool["liquidity"]), (NEST2, "nest-2", 1_187_522.0))

    def test_a_thin_pool_is_refused(self):
        thin = {NEST2: [{"pool": "0xaa" + "0" * 38, "name": "NEST / WHYPE", "dex": "nest", "base": NEST2, "liquidity": 40_000.0, "price": 0.02567, "volume_24h": 900.0}]}
        r = resolve_t("NEST", FakeNet(pools=thin), cg_id="nest-2")
        self.assertEqual(r["status"], "review")
        self.assertIn("thin pool: $40,000 liquidity", next(v["why"] for v in r["venues"] if v["source"] == "dex"))

    def test_a_pool_where_the_coin_is_not_the_base_or_names_another_coin_is_refused(self):
        other = {NEST2: [{"pool": "0xbb" + "0" * 38, "name": "KNTQ / NEST", "dex": "nest", "base": "0x0000000000007805", "liquidity": 900_000.0, "price": 0.46, "volume_24h": 1.0},
                         {"pool": WHYPE_POOL, "name": "NEST / WHYPE", "dex": "nest", "base": NEST2, "liquidity": 800_000.0, "price": 0.02567, "volume_24h": 1.0}]}
        r = resolve_t("NEST", FakeNet(pools=other, last={WHYPE_POOL: {"last": int(NOW), "base_cg_id": "nest-3"}}), cg_id="nest-2")
        whys = [v["why"] for v in r["venues"] if v["source"] == "dex"]
        self.assertEqual(whys, ["the coin is not this pool's base token", "the pool names its base token nest-3, not nest-2"])
        self.assertEqual(r["status"], "review")

    def test_a_pool_without_current_candles_or_with_a_wrong_price_is_refused(self):
        r = resolve_t("NEST", FakeNet(last={WHYPE_POOL: {"last": int(NOW - 6 * 3600), "base_cg_id": "nest-2"},
                                            "0xdb544d63d32d9f3e52ff3a8bfe2a374df0463f8d": {"last": int(NOW - 6 * 3600), "base_cg_id": "nest-2"}}), cg_id="nest-2")
        self.assertTrue(all(v["why"] == "no hourly candle in the last 3 hours" for v in r["venues"] if v["source"] == "dex"))
        far = {NEST2: [{"pool": WHYPE_POOL, "name": "NEST / WHYPE", "dex": "nest", "base": NEST2, "liquidity": 900_000.0, "price": 0.031, "volume_24h": 1.0}]}
        r = resolve_t("NEST", FakeNet(pools=far), cg_id="nest-2")
        self.assertIn("+20.8% from the coin's", next(v["why"] for v in r["venues"] if v["source"] == "dex"))

    def test_no_supported_chain_no_dex(self):
        r = resolve_t("NEST", FakeNet(platforms={"nest-2": {"some-chain": "0x1"}}), cg_id="nest-2")
        self.assertIn("no contract on a supported chain (some-chain)", next(v["why"] for v in r["venues"] if v["source"] == "dex"))


class CodexReview(unittest.TestCase):
    """The three defects the review reproduced, pinned."""
    def test_a_pool_without_a_coingecko_id_is_refused(self):
        r = resolve_t("NEST", FakeNet(last={WHYPE_POOL: {"last": int(NOW), "base_cg_id": None},
                                            "0xdb544d63d32d9f3e52ff3a8bfe2a374df0463f8d": {"last": int(NOW), "base_cg_id": None}}), cg_id="nest-2")
        self.assertEqual(r["status"], "review")
        self.assertIn("names its base token nothing", next(v["why"] for v in r["venues"] if v["source"] == "dex"))

    def test_after_usdc_volume_decides(self):
        spot = [{"symbol": "@10", "base": "KNTQ", "quote": "USDH", "pair": "KNTQ/USDH", "price": 0.462, "mark": 0.462, "volume": 10_500.0},
                {"symbol": "@11", "base": "KNTQ", "quote": "USDT0", "pair": "KNTQ/USDT0", "price": 0.462, "mark": 0.462, "volume": 1_000_000.0}]
        self.assertEqual(resolve_t("KNTQ", FakeNet(spot=spot))["chosen"]["symbol"], "@11")

    def test_pool_base_addresses_keep_their_case_and_lose_only_the_network(self):
        sol = "68Nq68CrtLVpyvK5Un7UADiNczaGf39hBbj3diRsYj6D"

        class N(tickers.Net):
            def get(self, url):
                net = url.split("/networks/")[1].split("/")[0]
                addr = sol if net == "solana" else "0xabc"
                return {"data": [{"attributes": {"address": "P1", "name": "X / USDC", "reserve_in_usd": "500000", "base_token_price_usd": "1"},
                                  "relationships": {"dex": {"data": {"id": "d"}}, "base_token": {"data": {"id": f"{net}_{addr}"}}}}]}
        self.assertEqual(N().gt_pools("solana", sol)[0]["base"], sol)
        self.assertEqual(N().gt_pools("polygon_pos", "0xabc")[0]["base"], "0xabc")
        pools = {sol: [{"pool": "P1", "name": "NEST / SOL", "dex": "d", "base": sol, "liquidity": 500_000.0, "price": 0.00125, "volume_24h": 1.0}]}
        r = resolve_t("NEST", FakeNet(pools=pools, last={"P1": {"last": int(NOW), "base_cg_id": "nest-3"}}), cg_id="nest-3")
        self.assertEqual((r["status"], r["chosen"]["symbol"]), ("ok", "solana:P1"))


class Ambiguity(unittest.TestCase):
    def test_an_ambiguous_ticker_is_never_guessed_and_lists_its_candidates(self):
        net = FakeNet()
        r = resolve_t("NEST", net)
        self.assertEqual(r["status"], "review")
        self.assertIn("pick one by hand", r["reason"])
        self.assertFalse([c for c in net.calls if c[0] in ("hlspot", "gt_pools")])       # nothing priced
        plats = {c["id"]: c.get("platforms") for c in r["candidates"]}
        self.assertEqual(plats["nest-2"], {"hyperevm": NEST2})

    def test_the_pick_flows_through_the_post_reader(self):
        net = FakeNet()
        legs = detect.coin_legs("More $NEST and $KNTQ", net=net, registry={"tickers": {}}, picks={"nest": "nest-2"})
        self.assertEqual([(l["asset"], l["status"]) for l in legs], [("NEST", "ok"), ("KNTQ", "ok")])
        self.assertEqual(legs[0]["receipt"]["asked"], "$NEST = nest-2 (owner pick)")
        legs = detect.coin_legs("More $NEST and $KNTQ", net=FakeNet(), registry={"tickers": {}})
        self.assertEqual([l["status"] for l in legs], ["review", "ok"])

    def test_a_pick_for_another_ticker_is_refused(self):
        r = resolve_t("NEST", FakeNet(), cg_id="kinetiq")
        self.assertEqual(r["status"], "refused")
        self.assertIn("kinetiq is KNTQ, not NEST", r["reason"])

    def test_the_refusal_lists_candidates_for_the_bot(self):
        import add_call
        legs = detect.coin_legs("More $NEST and $KNTQ", net=FakeNet(), registry={"tickers": {}})
        msg = add_call.legs_message(legs, "More $NEST and $KNTQ")
        self.assertIn(f"CANDIDATE NEST nest-2 NEST #1414 hyperevm:{NEST2}", msg)
        self.assertIn("CANDIDATE NEST nest-3 Nest #3650 solana:68Nq68CrtLVpyvK5Un7UADiNczaGf39hBbj3diRsYj6D", msg)
        self.assertIn("LEG KNTQ side none", msg)


class Pricing(unittest.TestCase):
    def test_asset_info_for_the_new_sources(self):
        self.assertEqual(resolve.asset_info("hlspot:@334")["symbol"], "@334")
        d = resolve.asset_info(f"dex:hyperevm:{WHYPE_POOL}")
        self.assertEqual((d["source"], d["symbol"]), ("dex", f"hyperevm:{WHYPE_POOL}"))   # case kept: pool addresses
        for bad in ("hlspot:334", "hlspot:@x", "dex:hyperevm:0x123", "dex:Hyper EVM:0x" + "1" * 40):
            with self.assertRaises(resolve.UnknownAssetError):
                resolve.asset_info(bad)

    def test_geckoterminal_candles_page_back_oldest_first(self):
        import datetime as dt
        start = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
        s = int(start.timestamp())
        pages = [[[s + 3600 * (1999 - i), 1, 2, 0.5, 1.5, 9] for i in range(1000)],
                 [[s + 3600 * (999 - i), 1, 2, 0.5, 1.5, 9] for i in range(1000)]]
        seen, real, slept = [], resolve.get_json, []
        resolve.get_json = lambda url: (seen.append(url), {"data": {"attributes": {"ohlcv_list": pages[len(seen) - 1]}}})[1]
        try:
            bars = resolve.geckoterminal_candles(f"hyperevm:{WHYPE_POOL}", start, now=start + dt.timedelta(hours=2000), sleep=slept.append)
        finally:
            resolve.get_json = real
        self.assertEqual(len(seen), 2)
        self.assertIn(f"before_timestamp={s + 3600 * 1000}", seen[1])
        self.assertEqual(bars[0][0], "2026-11-01T00:00:00Z")
        self.assertEqual([b[0] for b in bars], sorted(b[0] for b in bars))
        self.assertEqual(slept, [2.5])                                                  # the free tier: spaced pages

    def test_a_record_on_a_new_source_validates_and_old_ones_still_do(self):
        v = resolve.validator()
        import glob
        recs = sorted(glob.glob(os.path.join(HERE, "records", "**", "*.json"), recursive=True))
        for f in recs:
            with open(f) as fh:
                r = json.load(fh)
            if r.get("schema") == "post_price.v1":
                resolve.check_record(v, r)                                              # the widened schema accepts every record
        with open(next(f for f in recs if f.endswith("_ZEC.json"))) as fh:
            r = json.load(fh)
        r["asset"].update(source="dex", symbol=f"hyperevm:{WHYPE_POOL}")
        resolve.check_record(v, r)
        r["asset"].update(source="hlspot", symbol="@334")
        resolve.check_record(v, r)


class Recheck(unittest.TestCase):
    def bulk(self, spot, pool=None, fail=False):
        import seed_tickers

        class N:
            def gt_pool(self, network, p):
                if fail:
                    raise tickers.Unavailable("geckoterminal: HTTP 429")
                return pool
        b = seed_tickers.Bulk.__new__(seed_tickers.Bulk)
        b.hls, b.net, b.calls, b.unreachable = spot, N(), [], []
        return b

    def run_recheck(self, entry, bulk, price):
        import recheck_tickers
        reg = {"tickers": {"X": {"coingecko_id": "x", "name": "X", **entry}}}
        return recheck_tickers.recheck(reg, bulk, {"x": {"price": price, "rank": 1}}, "2026-11-09T00:00:00Z"), reg

    def test_a_spot_pair_that_stops_trading_is_flagged_never_swapped(self):
        spot = FakeNet().spot
        (res, flagged, _, _), reg = self.run_recheck({"source": "hlspot", "symbol": "@334"}, self.bulk(spot), 0.462)
        self.assertTrue(res["X"]["ok"])
        dead = [dict(v, volume=0.0) if v["symbol"] == "@334" else v for v in spot]
        (res, flagged, _, _), reg = self.run_recheck({"source": "hlspot", "symbol": "@334"}, self.bulk(dead), 0.462)
        self.assertEqual((flagged, reg["tickers"]["X"]["symbol"]), (["X"], "@334"))
        self.assertIn("not trading", res["X"]["why"])

    def test_a_pool_that_thins_out_is_flagged_and_an_outage_is_not(self):
        sym = f"hyperevm:{WHYPE_POOL}"
        (res, flagged, _, _), _ = self.run_recheck({"source": "dex", "symbol": sym}, self.bulk([], {"liquidity": 30_000.0, "price": 0.0256}), 0.0256)
        self.assertEqual(flagged, ["X"])
        (res, flagged, _, unchecked), reg = self.run_recheck({"source": "dex", "symbol": sym}, self.bulk([], fail=True), 0.0256)
        self.assertEqual((flagged, unchecked), ([], ["X"]))
        self.assertNotIn("flag", reg["tickers"]["X"])


class Unchanged(unittest.TestCase):
    def test_every_registered_coin_keeps_its_venue_and_the_scores_their_values(self):
        import build_chart
        reg = tickers.load_registry()
        for t, e in reg["tickers"].items():
            info = resolve.asset_info(t)
            self.assertEqual((info["source"], info["symbol"]), (e["source"], e["symbol"]), t)
        with open(os.path.join(HERE, "web", "data", "charts.json")) as f:
            served = json.load(f)
        self.assertEqual(build_chart.build(os.path.join(HERE, "records"))["ratings"], served["ratings"])


if __name__ == "__main__":
    unittest.main()
