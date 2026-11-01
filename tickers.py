#!/usr/bin/env python3
"""Step 22: plain tickers with safe automatic price resolution.

A cashtag / ticker a post names (or an X contract cashtag like 'hyperliquid:native') is resolved in
two separate checks, and both must pass:

  identity  which coin is meant: CoinGecko's coins with exactly that symbol, ranked by market cap.
            One ranked coin, or a top coin ranked far ahead of the next (AMBIGUOUS_RATIO), wins;
            two comparable coins go to review. A contract tag names its coin directly (native gas
            tokens by chain, contracts via CoinGecko's platform lookup).
  venue     where its hourly prices come from: Binance spot <TICKER>USDT, then the Hyperliquid perp
            <TICKER>. A venue counts only if the pair is trading now AND its price agrees with the
            identified coin's price within TOLERANCE. A ticker collision (an old coin with the same
            symbol on an exchange, a halted pair with a stale price) fails this check and is skipped.

Every answer is a receipt (schema quanty.ticker.v1): the candidates, the coin, every venue checked
with both prices and the difference, and the choice or the reason there is none. Any provider
error fails closed ("refused"); nothing is guessed. Resolved tickers are kept in data/tickers.json
(with the receipt under sources/tickers/), which resolve.asset_info reads, so prices refresh offline
and the asset is named by its plain ticker everywhere.

usage: python3 tickers.py LIT [HYPE ...]         # print the receipts, write nothing
       python3 tickers.py --contract hyperliquid:native
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "data", "tickers.json")
RECEIPTS = os.path.join(HERE, "sources", "tickers")
SCHEMA, REGISTRY_SCHEMA = "quanty.ticker.v1", "quanty.tickers.v1"
TOLERANCE = 0.05          # a venue's price must be within 5% of the identified coin's price
AMBIGUOUS_RATIO = 4       # the top coin must rank at least 4x ahead of the next coin with that symbol
TICKER_RE = re.compile(r"^[A-Z0-9]{1,12}$")
CG = "https://api.coingecko.com/api/v3"
BINANCE = "https://data-api.binance.vision/api/v3"
HL_INFO = "https://api.hyperliquid.xyz/info"
UA = {"User-Agent": "Mozilla/5.0 (quanty-quants ticker resolver)", "Accept": "application/json"}

# X contract cashtags: "<chain>:native" for the chain's gas token, "<chain>:<address>" for a token
CONTRACT_TAG = re.compile(r"(?<![\w:])(hyperliquid|ethereum|base|arbitrum|optimism|solana|bsc|polygon|avalanche):"
                          r"(native|0x[0-9a-fA-F]{40}|[1-9A-HJ-NP-Za-km-z]{32,44})(?![\w])")
NATIVE = {"hyperliquid": "hyperliquid", "ethereum": "ethereum", "base": "ethereum", "arbitrum": "ethereum", "optimism": "ethereum",
          "solana": "solana", "bsc": "binancecoin", "polygon": "polygon-ecosystem-token", "avalanche": "avalanche-2"}
PLATFORM = {"ethereum": "ethereum", "base": "base", "arbitrum": "arbitrum-one", "optimism": "optimistic-ethereum", "solana": "solana",
            "bsc": "binance-smart-chain", "polygon": "polygon-pos", "avalanche": "avalanche", "hyperliquid": "hyperevm"}


class Unavailable(RuntimeError):
    """A provider could not be reached or answered nonsense: fail closed."""


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Net:
    """The three providers. Every call can be replaced (tests run offline)."""
    def __init__(self, timeout=25, waits=(15, 30, 60), sleep=None):
        self.timeout, self.waits = timeout, waits
        self.sleep = sleep or __import__("time").sleep
        self._hl = None

    def get(self, url):
        for wait in (*self.waits, None):         # CoinGecko's free tier answers 429 when called quickly: wait, retry, then fail closed
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=self.timeout) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code in (400, 404):
                    return None                  # "no such pair / coin": an answer, not an outage
                if e.code == 429 and wait is not None:
                    self.sleep(wait)
                    continue
                raise Unavailable(f"{urllib.parse.urlsplit(url).netloc}: HTTP {e.code}") from None
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
                raise Unavailable(f"{urllib.parse.urlsplit(url).netloc}: {getattr(e, 'reason', e)}") from None
        raise Unavailable("unreachable")

    def post(self, url, body):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={**UA, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            raise Unavailable(f"hyperliquid: {getattr(e, 'reason', e)}") from None

    # CoinGecko
    def cg_search(self, symbol):
        d = self.get(f"{CG}/search?query={urllib.parse.quote(symbol)}")
        if not d or "coins" not in d:
            raise Unavailable("coingecko: no search answer")
        return [{"id": c["id"], "symbol": c["symbol"].upper(), "name": c["name"], "rank": c.get("market_cap_rank")}
                for c in d["coins"] if c.get("symbol", "").upper() == symbol]

    def cg_coin(self, cg_id):
        d = self.get(f"{CG}/coins/markets?vs_currency=usd&ids={urllib.parse.quote(cg_id)}")
        if not d:
            return None
        c = d[0]
        if c.get("current_price") is None:
            raise Unavailable(f"coingecko: no price for {cg_id}")
        return {"id": c["id"], "symbol": c["symbol"].upper(), "name": c["name"], "rank": c.get("market_cap_rank"), "price": float(c["current_price"])}

    def cg_contract(self, platform, address):
        d = self.get(f"{CG}/coins/{platform}/contract/{address}")
        return d["id"] if d and d.get("id") else None

    # venues
    def binance(self, ticker):
        pair = f"{ticker}USDT"
        info = self.get(f"{BINANCE}/exchangeInfo?symbol={pair}")
        if not info or not info.get("symbols"):
            return None
        status = info["symbols"][0].get("status")
        px = self.get(f"{BINANCE}/ticker/price?symbol={pair}")
        return {"source": "binance", "symbol": pair, "trading": status == "TRADING", "status": status,
                "price": float(px["price"]) if px and px.get("price") else None}

    def hyperliquid(self, ticker):
        if self._hl is None:
            meta = self.post(HL_INFO, {"type": "meta"})
            mids = self.post(HL_INFO, {"type": "allMids"})
            self._hl = ({u["name"]: u for u in meta["universe"]}, mids)
        uni, mids = self._hl
        u = uni.get(ticker)
        if not u:
            return None
        return {"source": "hyperliquid", "symbol": ticker, "trading": not u.get("isDelisted", False),
                "status": "delisted" if u.get("isDelisted") else "trading", "price": float(mids[ticker]) if ticker in mids else None}


def identify(symbol, net):
    """-> (coin or None, candidates, status, reason)."""
    cands = net.cg_search(symbol)
    ranked = sorted((c for c in cands if c["rank"]), key=lambda c: c["rank"])
    if not cands:
        return None, cands, "refused", f"no coin with the symbol {symbol} on CoinGecko"
    if not ranked:
        return None, cands, "review", f"{len(cands)} coins named {symbol}, none ranked by market cap: pick one by hand"
    top = ranked[0]
    if len(ranked) > 1 and ranked[1]["rank"] < AMBIGUOUS_RATIO * top["rank"]:
        return None, cands, "review", (f"two comparable coins named {symbol}: {top['name']} (#{top['rank']}) and "
                                       f"{ranked[1]['name']} (#{ranked[1]['rank']}): pick one by hand")
    return top, cands, "ok", None


def check_venues(ticker, coin_price, net):
    """Every venue checked, in order; the first trading venue whose price agrees wins."""
    checks, chosen = [], None
    for name in ("binance", "hyperliquid"):
        v = getattr(net, name)(ticker)
        if v is None:
            checks.append({"source": name, "listed": False, "ok": False, "why": f"no {ticker} market"})
            continue
        diff = (v["price"] / coin_price - 1) if v["price"] and coin_price else None
        ok = bool(v["trading"] and diff is not None and abs(diff) <= TOLERANCE)
        why = None if ok else (f"not trading (status {v['status']})" if not v["trading"] else
                               "no price" if diff is None else f"price {v['price']} is {diff:+.1%} from the coin's {coin_price}: a different coin or a stale pair")
        checks.append({"source": v["source"], "symbol": v["symbol"], "listed": True, "status": v["status"], "price": v["price"],
                       "coin_price": coin_price, "diff": None if diff is None else round(diff, 6), "ok": ok, "why": why})
        if ok and not chosen:
            chosen = {"source": v["source"], "symbol": v["symbol"]}
    return checks, chosen


def load_registry(path=REGISTRY):
    if not os.path.exists(path):
        return {"schema": REGISTRY_SCHEMA, "tickers": {}}
    with open(path) as f:
        return json.load(f)


def resolve_ticker(symbol, net=None, cg_id=None, registry=None, how=None):
    """-> receipt dict (status ok / review / refused). Writes nothing."""
    net = net or Net()
    sym = (symbol or "").strip().lstrip("$").upper()
    r = {"schema": SCHEMA, "ticker": sym, "asked": how or f"${sym}", "checked_at": now_iso(), "status": None, "reason": None,
         "coin": None, "candidates": [], "venues": [], "chosen": None,
         "rules": {"tolerance": TOLERANCE, "ambiguous_ratio": AMBIGUOUS_RATIO, "venue_order": ["binance", "hyperliquid"]}}
    if not TICKER_RE.match(sym):
        return {**r, "status": "refused", "reason": f"{symbol!r} is not a ticker"}
    try:
        if cg_id:
            coin = net.cg_coin(cg_id)
            if not coin:
                return {**r, "status": "refused", "reason": f"CoinGecko has no coin {cg_id}"}
            if coin["symbol"] != sym:
                return {**r, "status": "refused", "reason": f"{cg_id} is {coin['symbol']}, not {sym}"}
            r["candidates"] = [{k: coin[k] for k in ("id", "symbol", "name", "rank")}]
        else:
            top, cands, status, why = identify(sym, net)
            r["candidates"] = cands[:10]
            if not top:
                return {**r, "status": status, "reason": why}
            coin = net.cg_coin(top["id"])
            if not coin:
                return {**r, "status": "refused", "reason": f"CoinGecko has no market data for {top['id']}"}
        r["coin"] = coin
        reg = (registry or load_registry())["tickers"].get(sym)
        if reg and reg["coingecko_id"] != coin["id"]:
            return {**r, "status": "review", "reason": f"{sym} is already {reg['name']} ({reg['coingecko_id']}) on the site, this is {coin['name']} ({coin['id']})"}
        r["venues"], r["chosen"] = check_venues(sym, coin["price"], net)
    except Unavailable as e:
        return {**r, "status": "refused", "reason": f"provider unavailable, nothing guessed: {e}"}
    if not r["chosen"]:
        return {**r, "status": "review", "reason": f"no trading venue with hourly bars agrees with {coin['name']}'s price"}
    return {**r, "status": "ok"}


def resolve_contract(chain, ref, net=None, registry=None):
    """X contract cashtag ('hyperliquid', 'native') -> receipt for the coin's ticker."""
    net = net or Net()
    tag = f"{chain}:{ref}"
    try:
        if ref == "native":
            cg_id = NATIVE.get(chain)
        else:
            cg_id = net.cg_contract(PLATFORM[chain], ref) if chain in PLATFORM else None
        if not cg_id:
            return {"schema": SCHEMA, "ticker": None, "asked": tag, "status": "review", "reason": f"no coin found for the contract tag {tag}",
                    "checked_at": now_iso(), "coin": None, "candidates": [], "venues": [], "chosen": None}
        coin = net.cg_coin(cg_id)
    except Unavailable as e:
        return {"schema": SCHEMA, "ticker": None, "asked": tag, "status": "refused", "reason": f"provider unavailable, nothing guessed: {e}",
                "checked_at": now_iso(), "coin": None, "candidates": [], "venues": [], "chosen": None}
    if not coin:
        return {"schema": SCHEMA, "ticker": None, "asked": tag, "status": "refused", "reason": f"CoinGecko has no coin {cg_id}",
                "checked_at": now_iso(), "coin": None, "candidates": [], "venues": [], "chosen": None}
    return resolve_ticker(coin["symbol"], net, cg_id=cg_id, registry=registry, how=tag)


def register(receipt, root=HERE):
    """Keep an ok receipt: sources/tickers/<TICKER>.json + data/tickers.json. Same coin twice = no-op."""
    if receipt["status"] != "ok":
        raise ValueError("only an ok receipt is registered")
    reg_path = os.path.join(root, "data", "tickers.json")
    reg = load_registry(reg_path)
    t = receipt["ticker"]
    have = reg["tickers"].get(t)
    if have and have["coingecko_id"] != receipt["coin"]["id"]:
        raise ValueError(f"{t} is already {have['coingecko_id']}")
    if have:
        return have
    rdir = os.path.join(root, "sources", "tickers")
    os.makedirs(rdir, exist_ok=True)
    rpath = os.path.join(rdir, f"{t}.json")
    with open(rpath, "w") as f:
        json.dump(receipt, f, indent=1)
        f.write("\n")
    entry = {"coingecko_id": receipt["coin"]["id"], "name": receipt["coin"]["name"], "source": receipt["chosen"]["source"],
             "symbol": receipt["chosen"]["symbol"], "receipt": os.path.relpath(rpath, root),
             "receipt_sha256": hashlib.sha256(open(rpath, "rb").read()).hexdigest(), "added_at": receipt["checked_at"]}
    reg["tickers"][t] = entry
    reg["tickers"] = dict(sorted(reg["tickers"].items()))
    os.makedirs(os.path.dirname(reg_path), exist_ok=True)
    with open(reg_path, "w") as f:
        json.dump(reg, f, indent=1)
        f.write("\n")
    return entry


def show(r):
    lines = [f"{r['asked']} -> {r['ticker'] or '?'}: {r['status'].upper()}" + (f" ({r['reason']})" if r["reason"] else "")]
    if r.get("coin"):
        c = r["coin"]
        lines.append(f"  coin   {c['name']} [{c['id']}] rank #{c['rank']} price ${c['price']}")
    for c in r.get("candidates", [])[1:4]:
        lines.append(f"  also   {c['name']} [{c['id']}] rank #{c['rank']}")
    for v in r.get("venues", []):
        lines.append(f"  venue  {v['source']}:{v.get('symbol', '-')} " + ("OK" if v["ok"] else "skip")
                     + (f" price {v['price']} vs {v['coin_price']} ({v['diff']:+.2%})" if v.get("diff") is not None else "")
                     + (f" - {v['why']}" if v.get("why") else ""))
    if r.get("chosen"):
        lines.append(f"  chosen {r['chosen']['source']}:{r['chosen']['symbol']}")
    return "\n".join(lines)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    net, code = Net(), 0
    if argv[0] == "--contract":
        chain, _, ref = argv[1].partition(":")
        rs = [resolve_contract(chain, ref, net)]
    else:
        rs = [resolve_ticker(s, net) for s in argv]
    for r in rs:
        print(show(r))
        code = code or (0 if r["status"] == "ok" else 3)
    return code


if __name__ == "__main__":
    sys.exit(main())
