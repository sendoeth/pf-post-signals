#!/usr/bin/env python3
"""Fetch daily closes for the regime pipeline's inputs and the post-call tickers.

Stocks: Yahoo Finance chart API (adjusted=False close). Crypto: Binance spot klines
(UTC daily close), CoinGecko for tokens Binance does not list. Writes data/prices.json:
{symbol: {YYYY-MM-DD: close}}.
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "prices.json")
START = "2025-03-01"

STOCKS = ["NVDA", "TSM", "AVGO", "ASML", "ASX", "SPY", "SMH", "AMD", "MRVL"]
BINANCE = {"TAO": "TAOUSDT", "RNDR": "RENDERUSDT", "FET": "FETUSDT",
           "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "LINK": "LINKUSDT"}
COINGECKO = {"AKT": "akash-network"}


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def day(ts_seconds):
    return datetime.fromtimestamp(ts_seconds, tz=timezone.utc).strftime("%Y-%m-%d")


def yahoo(symbol):
    start = int(datetime.strptime(START, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    end = int(time.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={start}&period2={end}&interval=1d")
    res = get_json(url)["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    # Yahoo daily bars are stamped at the US open; the exchange-local date is the trading day.
    offset = res["meta"].get("gmtoffset", 0)
    return {day(t + offset): round(c, 4) for t, c in zip(res["timestamp"], closes) if c is not None}


def binance(pair):
    start_ms = int(datetime.strptime(START, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    out = {}
    while True:
        url = (f"https://data-api.binance.vision/api/v3/klines?symbol={pair}"
               f"&interval=1d&startTime={start_ms}&limit=1000")
        rows = get_json(url)
        for r in rows:
            out[day(r[0] / 1000)] = float(r[4])
        if len(rows) < 1000:
            return out
        start_ms = rows[-1][0] + 86_400_000


def coingecko(coin_id):
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days=365&interval=daily"
    # CoinGecko stamps each daily price at 00:00 UTC = previous day's close.
    return {day(ts / 1000 - 1): round(p, 6) for ts, p in get_json(url)["prices"]}


def main():
    prices = {}
    for s in STOCKS:
        prices[s] = yahoo(s)
        print(f"{s}: {len(prices[s])} days", file=sys.stderr)
    for s, pair in BINANCE.items():
        prices[s] = binance(pair)
        print(f"{s}: {len(prices[s])} days", file=sys.stderr)
    for s, cid in COINGECKO.items():
        prices[s] = coingecko(cid)
        print(f"{s}: {len(prices[s])} days", file=sys.stderr)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(prices, f, indent=0, sort_keys=True)
    print(f"wrote {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
