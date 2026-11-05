#!/usr/bin/env python3
"""Step 23: seed data/tickers.json with the top 100 coins and the confirmed Hyperliquid perps, so a post
naming them resolves instantly and offline (no first-post CoinGecko lookups).

Bulk data, a fixed handful of calls:
  CoinGecko   /coins/markets top 1000 by market cap (4 calls) + one call per excluded category
  Binance     /exchangeInfo (every pair's status) + /ticker/price (every price); OKX + Gate the same (no Bybit: it blocks CI)
  Hyperliquid meta + allMids (every perp and its mid)
  Nasdaq      nasdaqlisted.txt + otherlisted.txt (every US-listed ticker, for stock-vs-coin review)
  english     the 10,000 most common English words (which tickers / names are ordinary words)

Rules (the step 22 checks, applied in bulk by tickers.check_venues):
  - not a coin: stablecoins, wrapped / staked / restaked / bridged copies, tokenized gold, silver,
    treasuries, funds, credit and stocks are excluded with the reason (a known wrapped copy is mapped
    to its underlying cashtag: $WBTC -> BTC); a coin pegged near $1 with USD/EUR in its symbol is a
    stablecoin even without the category
  - "top 100" = the first 100 coins by market cap after those exclusions
  - perps: every live Hyperliquid perp whose symbol is a CoinGecko coin in the top 1000
  - identity: two coins with the same symbol and comparable ranks (within tickers.AMBIGUOUS_RATIO) -> review
  - venue: Binance spot, then the Hyperliquid perp; trading AND within tickers.TOLERANCE of the coin's
    price (a halted pair or another coin with the same symbol is skipped); none -> review
  - a ticker already on the site keeps its venue (records are never re-priced elsewhere)

Writes data/tickers.json (every seeded coin: id, name, rank, venue, receipt), sources/tickers/<T>.json
(per-coin receipt), sources/tickers/seed/<date>.json (the whole run: every coin checked, every exclusion
and review with its reason, the sha256 of each bulk response), data/coin_words.json (names -> ticker,
wrapped -> underlying, ordinary-word tickers, index words) and data/us_tickers.json.

usage: python3 tools/seed_tickers.py [--top 100] [--no-perps] [--dry-run]
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse

TOOLS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TOOLS)
sys.path[:0] = [HERE, TOOLS]
import tickers  # noqa: E402

SEED_SCHEMA = "quanty.ticker_seed.v1"
WORDS_SCHEMA = "quanty.coin_words.v1"
EXCLUDE_CATEGORIES = {
    "stablecoins": "stablecoin", "wrapped-tokens": "wrapped copy", "bridged-tokens": "bridged copy",
    "liquid-staking-tokens": "liquid staking token", "liquid-restaking-tokens": "liquid restaking token", "tokenized-btc": "tokenized BTC",
    "tokenized-gold": "tokenized gold", "tokenized-silver": "tokenized silver", "tokenized-commodities": "tokenized commodity",
    "tokenized-treasuries": "tokenized treasuries", "tokenized-t-bills": "tokenized T-bills", "tokenized-money-market-fund-mmfs": "tokenized money market fund",
    "tokenized-credit": "tokenized credit", "tokenized-private-credit": "tokenized private credit", "tokenized-stock": "tokenized stock",
    "tokenized-exchange-traded-funds-etfs": "tokenized ETF",
}
NOT_A_COIN_NAME = re.compile(r"\b(wrapped|bridged|staked|restaked|tokenized|treasury|t-bill|money market|fund|heloc|gold|silver)\b", re.I)
PEGGED_SYMBOL = re.compile(r"(USD|EUR|GBP|JPY|CHF)", re.I)
# a wrapped / staked copy people may write instead of the coin: the cashtag maps to the underlying
WRAPPED = {"WBTC": "BTC", "CBBTC": "BTC", "LBTC": "BTC", "TBTC": "BTC", "SOLVBTC": "BTC", "BTCB": "BTC", "WETH": "ETH", "STETH": "ETH",
           "WSTETH": "ETH", "WEETH": "ETH", "WBETH": "ETH", "RETH": "ETH", "METH": "ETH", "EZETH": "ETH", "RSETH": "ETH", "CBETH": "ETH",
           "JITOSOL": "SOL", "MSOL": "SOL", "BNSOL": "SOL", "JUPSOL": "SOL", "WBNB": "BNB", "WAVAX": "AVAX", "KHYPE": "HYPE", "STHYPE": "HYPE"}
# market indexes: recognised so they are never read as a coin; no price history source yet -> review
INDEX_WORDS = {"TOTAL": "total crypto market cap", "TOTAL2": "crypto market cap without BTC", "TOTAL3": "crypto market cap without BTC and ETH",
               "OTHERS": "crypto market cap outside the top 10", "BTC.D": "bitcoin dominance", "USDT.D": "USDT dominance", "USDC.D": "USDC dominance",
               "STABLE.C.D": "stablecoin dominance", "OTHERS.D": "others dominance"}
INDEX_PHRASES = ["stablecoin dominance", "stable coin dominance", "usdt dominance", "btc dominance", "bitcoin dominance", "total3", "total2", "others.d"]
# names that are ordinary words or people even if not in the word list
NAME_BLOCK = {"official trump", "trump", "melania", "world liberty financial", "pi network", "sky", "stacks", "story", "pump.fun", "four",
              "hyperliquid"}   # 'hyperliquid' is the exchange as often as the coin: $HYPE / hyperliquid:native only
EXTRA_NAMES = {"HYPE": ["hype token"], "LIT": ["lighter"], "BTC": ["bitcoin"], "ETH": ["ethereum", "ether"], "SOL": ["solana"]}
URL = {"markets": "{cg}/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page={page}",
       "category": "{cg}/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page=1&category={cat}",
       "binance_info": "https://data-api.binance.vision/api/v3/exchangeInfo?permissions=SPOT",
       "binance_prices": "https://data-api.binance.vision/api/v3/ticker/price",
       "nasdaq": "https://www.nasdaqtrader.com/dynamic/SymDir/{f}",
       "words": "https://raw.githubusercontent.com/first20hours/google-10000-english/master/google-10000-english-no-swears.txt"}


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(obj):
    return hashlib.sha256(obj if isinstance(obj, bytes) else json.dumps(obj, sort_keys=True).encode()).hexdigest()


class Bulk:
    """Every bulk response the seed needs, fetched once (each call recorded with the sha256 of its answer).
    Also serves tickers.check_venues (binance / hyperliquid per ticker) from the snapshots, so the seed
    applies exactly the step 22 venue rule without one call per coin."""
    def __init__(self, net=None, pause=6.0, sleep=time.sleep, fetch_text=None):
        self.net, self.pause, self.sleep, self.calls = net or tickers.Net(), pause, sleep, []
        self.hls = []                                     # step 26: Hyperliquid spot pairs, filled by load_venues
        self.fetch_text = fetch_text or self._text

    def _text(self, url):
        import urllib.request
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as r:
            return r.read().decode()

    def _get(self, name, url, cg=False):
        if cg and self.calls:
            self.sleep(self.pause)                        # CoinGecko free tier: space the calls out
        d = self.net.get(url)
        if d is None:
            raise tickers.Unavailable(f"{name}: no answer")
        self.calls.append({"what": name, "url": url, "sha256": sha(d), "at": now_iso()})
        return d

    def load(self, categories=EXCLUDE_CATEGORIES):
        cg = tickers.CG
        self.markets = []
        for page in (1, 2, 3, 4):
            self.markets += self._get(f"coingecko markets page {page}", URL["markets"].format(cg=cg, page=page), cg=True)
        self.category = {}
        for cat in categories:
            try:
                rows = self._get(f"coingecko category {cat}", URL["category"].format(cg=cg, cat=cat), cg=True)
            except tickers.Unavailable as e:
                if "no answer" in str(e):                 # an unknown category id: noted, not fatal
                    self.calls.append({"what": f"coingecko category {cat}", "missing": True})
                    continue
                raise
            for c in rows:
                self.category.setdefault(c["id"], []).append(cat)
        self.load_venues()
        return self.load_lists()

    def load_venues(self, strict=True):
        """Every venue's pairs, status and prices (Binance, Hyperliquid, OKX, Gate): no CoinGecko call. strict (the
        seed): any unreachable venue stops the run. not strict (the weekly re-check): an unreachable venue is listed in
        self.unreachable, its coins are reported as not checked and the other venues are still checked (Codex review)."""
        self.bin_status, self.bin_price, self.hl, self.hl_mid = {}, {}, {}, {}
        self.unreachable = []

        def binance():
            info = self._get("binance exchangeInfo", URL["binance_info"])
            self.bin_status = {s["symbol"]: s["status"] for s in info["symbols"]}
            prices = self._get("binance prices", URL["binance_prices"])
            self.bin_price = {p["symbol"]: float(p["price"]) for p in prices}

        def hyperliquid():
            meta = self.net.post(tickers.HL_INFO, {"type": "meta"})
            mids = self.net.post(tickers.HL_INFO, {"type": "allMids"})
            self.calls.append({"what": "hyperliquid meta + allMids", "sha256": sha([meta, mids]), "at": now_iso()})
            self.hl = {u["name"]: u for u in meta["universe"]}
            self.hl_mid = {k: float(v) for k, v in mids.items() if not k.startswith("@")}
        def hlspot():                                  # step 26: Hyperliquid spot pairs (one call)
            ans = self.net.post(tickers.HL_INFO, {"type": "spotMetaAndAssetCtxs"})
            self.calls.append({"what": "hyperliquid spotMetaAndAssetCtxs", "sha256": sha(ans), "at": now_iso()})
            self.hls = tickers.parse_spot(ans)
        self.hls = []
        for name, load in (("binance", binance), ("hyperliquid", hyperliquid), ("hlspot", hlspot)):
            try:
                load()
            except (tickers.Unavailable, KeyError, TypeError, ValueError) as e:
                if strict:
                    raise tickers.Unavailable(f"{name}: {e}") from None
                self.unreachable.append(name)
                self.calls.append({"what": f"{name} (unreachable)", "error": str(e)[:200]})
        self.load_more_venues(strict)
        return self

    def load_lists(self):
        """US-listed tickers (stock-vs-coin review) and the common English words."""
        self.us = {}
        for f in ("nasdaqlisted.txt", "otherlisted.txt"):
            body = self.fetch_text(URL["nasdaq"].format(f=f))
            self.calls.append({"what": f"nasdaq {f}", "sha256": sha(body.encode()), "at": now_iso()})
            for line in body.splitlines()[1:]:
                parts = line.split("|")
                if len(parts) > 2 and not line.startswith("File Creation") and parts[0]:
                    self.us.setdefault(parts[0].strip().upper(), parts[1].strip())
        words = self.fetch_text(URL["words"])
        self.calls.append({"what": "english words (google-10000-english, the 10k most common)", "sha256": sha(words.encode()), "at": now_iso()})
        self.words = {w.strip().lower() for w in words.splitlines() if w.strip()}
        return self

    def load_more_venues(self, strict=True):
        """OKX and Gate spot: every pair's status and last price (step 23 venues). strict (the seed): an unreachable
        venue stops the run, so no coin is placed elsewhere by accident. not strict (the weekly re-check): the venue
        is listed in self.unreachable and its coins are reported as not checked."""
        self.okx_s, self.okx_p, self.gate_s, self.gate_p = {}, {}, {}, {}
        self.byb_s, self.byb_p = {}, {}                  # Bybit is not a venue (blocks the GitHub runners)
        self.unreachable = getattr(self, "unreachable", [])

        def okx():
            okx_i = self._get("okx instruments", "https://www.okx.com/api/v5/public/instruments?instType=SPOT")["data"]
            okx_t = self._get("okx tickers", "https://www.okx.com/api/v5/market/tickers?instType=SPOT")["data"]
            self.okx_s = {i["instId"]: i["state"] for i in okx_i}
            self.okx_p = {t["instId"]: float(t["last"]) for t in okx_t if t.get("last")}

        def gate():
            gate_i = self._get("gate currency pairs", "https://api.gateio.ws/api/v4/spot/currency_pairs")
            gate_t = self._get("gate tickers", "https://api.gateio.ws/api/v4/spot/tickers")
            self.gate_s = {i["id"]: i.get("trade_status") for i in gate_i}
            self.gate_p = {t["currency_pair"]: float(t["last"]) for t in gate_t if t.get("last")}
        for name, load in (("okx", okx), ("gate", gate)):
            try:
                load()
            except (tickers.Unavailable, KeyError, TypeError, ValueError) as e:
                if strict:
                    raise tickers.Unavailable(f"{name}: {e}") from None
                self.unreachable.append(name)
                self.calls.append({"what": f"{name} (unreachable)", "error": str(e)[:200]})
        return self

    # tickers.check_venues interface
    def binance(self, ticker):
        pair = f"{ticker}USDT"
        if pair not in self.bin_status:
            return None
        st = self.bin_status[pair]
        return {"source": "binance", "symbol": pair, "trading": st == "TRADING", "status": st, "price": self.bin_price.get(pair)}

    def hlspot(self, ticker):
        return [v for v in self.hls if (v["base"] or "").upper() == ticker]

    def venue(self, source, symbol):
        """status + price of exactly this registered pair (the weekly re-check never looks elsewhere)."""
        if source == "hlspot":                        # step 26: the same pair, still traded (24h volume) with a mid price
            v = next((x for x in self.hls if x["symbol"] == symbol), None)
            if not v:
                return None
            live = v["price"] is not None and v["volume"] >= tickers.MIN_SPOT_VOLUME
            return {"source": "hlspot", "symbol": symbol, "trading": live, "status": f"24h volume ${v['volume']:,.0f}", "price": v["price"]}
        if source == "dex":                           # step 26: the same pool, still deep enough
            network, _, pool = symbol.partition(":")
            p = self.net.gt_pool(network, pool)
            self.calls.append({"what": f"geckoterminal pool {symbol}", "sha256": sha(p), "at": now_iso()})
            if not p:
                return None
            return {"source": "dex", "symbol": symbol, "trading": p["liquidity"] >= tickers.MIN_DEX_LIQUIDITY,
                    "status": f"liquidity ${p['liquidity']:,.0f}", "price": p["price"]}
        if source == "binance":
            return self._spot("binance", symbol, self.bin_status, self.bin_price, "TRADING")
        if source == "hyperliquid":
            return self.hyperliquid(symbol)
        return {"okx": lambda: self._spot("okx", symbol, self.okx_s, self.okx_p, "live"),
                "bybit": lambda: self._spot("bybit", symbol, self.byb_s, self.byb_p, "Trading"),
                "gate": lambda: self._spot("gate", symbol, self.gate_s, self.gate_p, "tradable")}.get(source, lambda: None)()

    def _spot(self, source, sym, status, prices, ok):
        if sym not in status:
            return None
        return {"source": source, "symbol": sym, "trading": status[sym] == ok, "status": status[sym], "price": prices.get(sym)}

    def okx(self, ticker):
        return self._spot("okx", f"{ticker}-USDT", self.okx_s, self.okx_p, "live")

    def bybit(self, ticker):
        return self._spot("bybit", f"{ticker}USDT", self.byb_s, self.byb_p, "Trading")

    def gate(self, ticker):
        return self._spot("gate", f"{ticker}_USDT", self.gate_s, self.gate_p, "tradable")

    def hyperliquid(self, ticker):
        u = self.hl.get(ticker)
        if not u:
            return None
        return {"source": "hyperliquid", "symbol": ticker, "trading": not u.get("isDelisted", False),
                "status": "delisted" if u.get("isDelisted") else "trading", "price": self.hl_mid.get(ticker)}


def not_a_coin(c, bulk):
    cats = bulk.category.get(c["id"], [])
    if cats:
        return EXCLUDE_CATEGORIES[cats[0]], cats
    sym, price = c["symbol"].upper(), c.get("current_price") or 0
    if PEGGED_SYMBOL.search(sym) and 0.97 <= price <= 1.03:
        return "stablecoin (pegged near $1, no category)", []
    if NOT_A_COIN_NAME.search(c["name"]):
        return f"not a coin by name ({NOT_A_COIN_NAME.search(c['name']).group(0).lower()})", []
    if sym in WRAPPED:
        return f"wrapped copy of {WRAPPED[sym]}", []
    return None, cats


def receipt_for(c, cands, bulk, asked, at):
    """The same receipt tickers.resolve_ticker writes, built from the bulk snapshots."""
    sym = c["symbol"].upper()
    coin = {"id": c["id"], "symbol": sym, "name": c["name"], "rank": c.get("market_cap_rank"), "price": float(c["current_price"])}
    r = {"schema": tickers.SCHEMA, "ticker": sym, "asked": asked, "checked_at": at, "status": None, "reason": None, "coin": coin,
         "candidates": [{"id": x["id"], "symbol": sym, "name": x["name"], "rank": x.get("market_cap_rank")} for x in cands][:10], "venues": [], "chosen": None,
         "rules": {"tolerance": tickers.TOLERANCE, "ambiguous_ratio": tickers.AMBIGUOUS_RATIO, "venue_order": list(tickers.VENUES), "seed": SEED_SCHEMA}}
    ranked = sorted((x for x in cands if x.get("market_cap_rank")), key=lambda x: x["market_cap_rank"])
    if len(ranked) > 1 and ranked[0]["id"] == c["id"] and ranked[1]["market_cap_rank"] < tickers.AMBIGUOUS_RATIO * ranked[0]["market_cap_rank"]:
        return {**r, "status": "review", "reason": f"two comparable coins named {sym}: {ranked[0]['name']} (#{ranked[0]['market_cap_rank']}) and "
                                                    f"{ranked[1]['name']} (#{ranked[1]['market_cap_rank']})"}
    if ranked and ranked[0]["id"] != c["id"]:
        return {**r, "status": "review", "reason": f"{sym} is {ranked[0]['name']} (#{ranked[0]['market_cap_rank']}) first, not {c['name']}"}
    r["venues"], r["chosen"] = tickers.check_venues(sym, coin["price"], bulk)
    if not r["chosen"]:
        return {**r, "status": "review", "reason": f"no trading venue with hourly bars agrees with {c['name']}'s price"}
    return {**r, "status": "ok"}


def plan(bulk, top=100, perps=True, registry=None, at=None):
    """-> {seed: [receipts ok], review: [...], excluded: [...], top100: [...], perps: [...], kept: [...]} (writes nothing)."""
    at = at or now_iso()
    registry = registry or {"tickers": {}}
    by_sym = {}
    for c in bulk.markets:
        if c.get("market_cap_rank") and c.get("current_price") is not None:
            by_sym.setdefault(c["symbol"].upper(), []).append(c)
    excluded, review, seed, kept, top_ids, perp_ids = [], [], {}, [], [], []
    seen = set()

    def consider(c, asked):
        sym = c["symbol"].upper()
        why, cats = not_a_coin(c, bulk)
        if why:
            excluded.append({"ticker": sym, "id": c["id"], "name": c["name"], "rank": c.get("market_cap_rank"), "why": why, "categories": cats,
                             "maps_to": WRAPPED.get(sym)})
            return False
        if c["id"] in seen:
            return True
        seen.add(c["id"])
        if not tickers.TICKER_RE.match(sym):
            review.append({"ticker": sym, "id": c["id"], "name": c["name"], "rank": c.get("market_cap_rank"), "why": "symbol is not a plain ticker"})
            return True
        r = receipt_for(c, by_sym.get(sym, [c]), bulk, asked, at)
        have = registry["tickers"].get(sym)
        if have and r["status"] == "ok" and have["coingecko_id"] == c["id"]:
            if (have["source"], have["symbol"]) != (r["chosen"]["source"], r["chosen"]["symbol"]):
                kept.append({"ticker": sym, "kept": f"{have['source']}:{have['symbol']}", "seed_would_choose": f"{r['chosen']['source']}:{r['chosen']['symbol']}"})
                r = {**r, "chosen": {"source": have["source"], "symbol": have["symbol"]}, "kept_existing_venue": True}
                if not any(v["ok"] and (v["source"], v.get("symbol")) == (have["source"], have["symbol"]) for v in r["venues"]):
                    r = {**r, "status": "review", "reason": f"the venue already used on the site ({have['source']}:{have['symbol']}) failed this check"}
        if have and have["coingecko_id"] != c["id"]:
            r = {**r, "status": "review", "reason": f"{sym} is already {have['name']} ({have['coingecko_id']}) on the site"}
        if r["status"] == "ok":
            seed[sym] = r
        else:
            review.append({"ticker": sym, "id": c["id"], "name": c["name"], "rank": c.get("market_cap_rank"), "why": r["reason"], "receipt": r})
        return True

    for c in sorted((c for c in bulk.markets if c.get("market_cap_rank")), key=lambda c: c["market_cap_rank"]):
        if len(top_ids) >= top:
            break
        if c["symbol"].upper() in top_ids:
            continue                                   # a lower-ranked coin with a ticker already counted (its collision is in the receipt)
        if consider(c, f"seed: top {top} by market cap"):
            top_ids.append(c["symbol"].upper())
    if perps:
        for name, u in sorted(bulk.hl.items()):
            if u.get("isDelisted"):
                continue
            base = name[1:] if re.fullmatch(r"k[A-Z0-9]+", name) else name       # kPEPE = 1000 PEPE: the coin is PEPE
            cands = by_sym.get(base.upper())
            if not cands:
                if base.upper() not in seed:
                    review.append({"ticker": base.upper(), "id": None, "name": None, "rank": None, "why": f"Hyperliquid perp {name}: no CoinGecko coin with this symbol in the top 1000"})
                continue
            top_c = sorted(cands, key=lambda c: c["market_cap_rank"])[0]
            if consider(top_c, f"seed: Hyperliquid perp {name}") and top_c["symbol"].upper() not in top_ids:
                perp_ids.append(top_c["symbol"].upper())
    for sym in list(seed):
        if sym in bulk.us and seed[sym]["coin"]["rank"] and seed[sym]["coin"]["rank"] > 0:
            seed[sym] = {**seed[sym], "also_us_stock": bulk.us[sym][:80]}
    return {"seed": seed, "review": review, "excluded": excluded, "top": [t for t in top_ids if t in seed],
            "top_listed": top_ids, "perps": [t for t in perp_ids if t in seed], "kept": kept, "at": at}


def coin_words(p, bulk):
    """names -> ticker (only names that are not ordinary words / people), ordinary-word tickers, wrapped -> underlying, index words."""
    names, blocked_names = {}, []
    for sym, r in sorted(p["seed"].items()):
        cands = [r["coin"]["name"].lower()] + EXTRA_NAMES.get(sym, [])
        for n in cands:
            n = re.sub(r"\s+", " ", n.strip())
            if len(n) < 3 or n in NAME_BLOCK or n in bulk.words:   # 3-letter names only when not a common word (xrp yes, one no)
                blocked_names.append(n)
                continue
            names.setdefault(n, sym)
    bare_blocked = sorted(sym for sym in p["seed"] if sym.lower() in bulk.words or len(sym) < 3)
    return {"schema": WORDS_SCHEMA, "built_at": p["at"],
            "note": "built by tools/seed_tickers.py. names: whole-word, case-insensitive -> ticker (never a common English word). bare tickers (no $) "
                    "count only in capitals and not in bare_blocked (common English words or under 3 letters); fixed-map tickers (SOL, LINK, ETH) always. "
                    "wrapped: a cashtag of a wrapped / staked copy -> the underlying coin. index: market indexes, never a coin (review: no price history source yet).",
            "names": dict(sorted(names.items())), "blocked_names": sorted(set(blocked_names)), "bare_blocked": bare_blocked,
            "wrapped": WRAPPED, "index": INDEX_WORDS, "index_phrases": INDEX_PHRASES,
            "stablecoins": sorted({x["ticker"] for x in p["excluded"] if x["why"].startswith("stablecoin")} | {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE"})}


def write(p, bulk, root=HERE):
    """Registry entries + per-coin receipts + the seed receipt + coin words + US tickers."""
    day = p["at"][:10]
    seed_dir = os.path.join(root, "sources", "tickers", "seed")
    os.makedirs(seed_dir, exist_ok=True)
    seed_rel = os.path.join("sources", "tickers", "seed", f"{day}.json")
    doc = {"schema": SEED_SCHEMA, "seeded_at": p["at"], "calls": bulk.calls,
           "rules": {"top": len(p["top_listed"]), "tolerance": tickers.TOLERANCE, "ambiguous_ratio": tickers.AMBIGUOUS_RATIO,
                     "excluded_categories": EXCLUDE_CATEGORIES, "venue_order": list(tickers.VENUES)},
           "counts": {"top_listed": len(p["top_listed"]), "top_seeded": len(p["top"]), "perps_seeded": len(p["perps"]), "seeded": len(p["seed"]),
                      "review": len(p["review"]), "excluded": len(p["excluded"]), "kept_existing_venue": len(p["kept"])},
           "top": p["top"], "top_listed": p["top_listed"], "perps": p["perps"], "kept": p["kept"],
           "excluded": p["excluded"], "review": [{k: v for k, v in x.items() if k != "receipt"} for x in p["review"]],
           "coins": {t: {k: r[k] for k in ("coin", "venues", "chosen")} | ({"also_us_stock": r["also_us_stock"]} if r.get("also_us_stock") else {})
                     for t, r in sorted(p["seed"].items())}}
    with open(os.path.join(root, seed_rel), "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    seed_sha = hashlib.sha256(open(os.path.join(root, seed_rel), "rb").read()).hexdigest()
    reg_path = os.path.join(root, "data", "tickers.json")
    reg = tickers.load_registry(reg_path)
    added = 0
    for sym, r in sorted(p["seed"].items()):
        if sym not in reg["tickers"]:
            tickers.register({k: v for k, v in r.items() if k not in ("also_us_stock", "kept_existing_venue")}, root)   # receipt + entry
            added += 1
    reg = tickers.load_registry(reg_path)              # once, after every registration: then the seed fields
    for sym, r in sorted(p["seed"].items()):
        e = reg["tickers"][sym]
        e.update({"rank": r["coin"]["rank"], "seed": seed_rel, "seed_sha256": seed_sha, "in_top": sym in p["top"], "hl_perp": sym in p["perps"] or sym in bulk.hl})
        if r.get("also_us_stock"):
            e["also_us_stock"] = r["also_us_stock"]
    reg["seeded_at"], reg["seed"] = p["at"], seed_rel
    with open(reg_path, "w") as f:
        json.dump(reg, f, indent=1)
        f.write("\n")
    with open(os.path.join(root, "data", "coin_words.json"), "w") as f:
        json.dump(coin_words(p, bulk), f, indent=1)
        f.write("\n")
    with open(os.path.join(root, "data", "us_tickers.json"), "w") as f:
        json.dump({"schema": "quanty.us_tickers.v1", "source": "nasdaqtrader.com SymDir nasdaqlisted + otherlisted", "built_at": p["at"],
                   "tickers": dict(sorted(bulk.us.items()))}, f, separators=(",", ":"))
        f.write("\n")
    return {"seed_receipt": seed_rel, "seed_sha256": seed_sha, "added": added, "registry": len(reg["tickers"])}


def words_only(root=HERE, fetch_text=None):
    """Rebuild data/coin_words.json from the latest seed receipt + the word list (no CoinGecko call)."""
    import glob
    seed_p = sorted(glob.glob(os.path.join(root, "sources", "tickers", "seed", "*.json")))[-1]
    doc = json.load(open(seed_p))
    b = Bulk(fetch_text=fetch_text)
    b.words = {w.strip().lower() for w in b.fetch_text(URL["words"]).splitlines() if w.strip()}
    p = {"seed": {t: {"coin": c["coin"]} for t, c in doc["coins"].items()}, "excluded": doc["excluded"], "at": doc["seeded_at"]}
    w = coin_words(p, b)
    with open(os.path.join(root, "data", "coin_words.json"), "w") as f:
        json.dump(w, f, indent=1)
        f.write("\n")
    return w


def summary(p):
    lines = [f"top {len(p['top_listed'])} coins (after exclusions): {len(p['top'])} seeded, {len([x for x in p['review'] if x['ticker'] in p['top_listed']])} to review",
             f"Hyperliquid perps confirmed: {len(p['perps'])} more seeded", f"seeded total {len(p['seed'])}, review {len(p['review'])}, excluded {len(p['excluded'])}"]
    for x in p["kept"]:
        lines.append(f"kept {x['ticker']} on {x['kept']} (seed would choose {x['seed_would_choose']})")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--no-perps", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--words-only", action="store_true", help="rebuild data/coin_words.json from the latest seed receipt (no CoinGecko call)")
    a = ap.parse_args(argv)
    if a.words_only:
        w = words_only()
        print(f"coin words: {len(w['names'])} names, {len(w['bare_blocked'])} blocked bare tickers, {len(w['stablecoins'])} stablecoins")
        return 0
    try:
        bulk = Bulk().load()
    except tickers.Unavailable as e:
        print(f"FAILED (nothing written): provider unavailable: {e}", file=sys.stderr)
        return 3
    p = plan(bulk, a.top, not a.no_perps, tickers.load_registry())
    print(summary(p))
    if not a.dry_run:
        print(json.dumps(write(p, bulk)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
