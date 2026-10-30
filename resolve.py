#!/usr/bin/env python3
"""Step 4: post-to-price resolver. One post + one asset -> one schema-valid post_price.v1 record.

Input is a post URL (timestamp decoded from the X snowflake id) or a saved post receipt
(sources/*/receipts/<id>.json, timestamp from the receipt), plus an asset. Rules are the step 3
rules, unchanged:
  entry  = open of the first hourly bar at/after posted_at; more than 2 days late -> no_entry.
           Exchange-hours assets (Yahoo: stocks, ETFs, futures) allow 4 days for entry and exits,
           so a post or horizon falling while the market is closed (evening, weekend, long
           weekend) takes the next session open
  exit h = open of the first bar at/after posted_at + h days (h = 1, 7, 30); past the last bar
           -> "horizon not yet reached", more than 2 days late -> market closed; both unresolved
  move h = P_h / P_entry - 1; with a side, signed_return h = side * move h
  latest = last bar; change_since_post = P_latest / P_entry - 1
Prices come from Binance (1h klines) or Yahoo (1h chart), or from a saved snapshot (--prices),
which is how the step 3 parity check runs.

usage:
  python3 resolve.py --url https://x.com/<user>/status/<id> --asset BTC [--side long] [--out DIR]
  python3 resolve.py --receipt sources/bobloukas/receipts/<id>.json --asset SILVER --prices data/hourly_prices.json
  python3 resolve.py --batch posts.json [--prices FILE] [--out DIR]   # [{"url"|"receipt", "asset", "side"?}, ...]
"""
import argparse
import bisect
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(HERE, "schema", "post_price.v1.json")
HORIZONS = (1, 7, 30)
MAX_LAG_DAYS = 2
# Fri 20:00 UTC close -> Tue 13:30 UTC open after a Monday holiday is 3.73 days; a longer gap means
# missing data, not a closed market, and stays unresolved.
EXCHANGE_HOURS_LAG_DAYS = 4
TWITTER_EPOCH_MS = 1288834974657
URL_RE = re.compile(r"^https://(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/(\d+)(?:[/?#].*)?$")

# name -> (source, symbol). Names match the step 3 instrument names, so the snapshot keys line up.
ASSETS = {
    "BTC": ("binance", "BTCUSDT"), "ETH": ("binance", "ETHUSDT"), "SOL": ("binance", "SOLUSDT"),
    "LINK": ("binance", "LINKUSDT"),
    "STOCKS": ("yahoo", "SPY"), "SPY": ("yahoo", "SPY"), "QQQ": ("yahoo", "QQQ"),
    "COPX": ("yahoo", "COPX"), "SILVER": ("yahoo", "SI=F"), "GOLD": ("yahoo", "GC=F"),
    "COPPER": ("yahoo", "HG=F"), "OIL": ("yahoo", "CL=F"),
}


class ResolveError(Exception):
    pass


class UnknownAssetError(ResolveError):
    pass


class DuplicatePostError(ResolveError):
    pass


def asset_info(name):
    """'BTC' -> known map; 'binance:XRPUSDT' / 'yahoo:NVDA' -> explicit source; anything else fails."""
    raw = name.strip()
    if ":" in raw:
        src, sym = raw.split(":", 1)
        src = src.lower()
        if src not in ("binance", "yahoo") or not re.fullmatch(r"[A-Za-z0-9=.^\-]{1,20}", sym):
            raise UnknownAssetError(f"unknown asset {name!r}: prefix must be binance:<PAIR> or yahoo:<TICKER>")
        return {"name": f"{src}:{sym.upper()}", "source": src, "symbol": sym.upper(), "price_field": "open"}
    key = raw.upper()
    if key not in ASSETS:
        raise UnknownAssetError(f"unknown asset {name!r}: known {', '.join(sorted(ASSETS))}; "
                                "or pass binance:<PAIR> / yahoo:<TICKER>")
    src, sym = ASSETS[key]
    return {"name": key, "source": src, "symbol": sym, "price_field": "open"}


def iso(ts):
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(ts):
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def lag_days(a, b):
    return (parse(b) - parse(a)).total_seconds() / 86400


def snowflake_time(post_id):
    return iso(((int(post_id) >> 22) + TWITTER_EPOCH_MS) // 1000)


def load_post(url=None, receipt=None):
    if receipt:
        with open(receipt, "rb") as f:
            blob = f.read()
        p = json.loads(blob)
        m = URL_RE.match(p.get("url", ""))
        if not m or m.group(2) != str(p["id"]):
            raise ResolveError(f"receipt {receipt}: url and id disagree")
        if url and URL_RE.match(url).group(2) != str(p["id"]):
            raise ResolveError(f"receipt {receipt} is post {p['id']}, not {url}")
        return {"id": str(p["id"]), "url": f"https://x.com/{p['authorHandle']}/status/{p['id']}",
                "author": p["authorHandle"], "posted_at": p["postedAt"][:19] + "Z", "posted_at_source": "receipt",
                "text": p.get("text"), "receipt_sha256": hashlib.sha256(blob).hexdigest()}
    m = URL_RE.match(url or "")
    if not m:
        raise ResolveError(f"not a post url: {url!r}")
    user, pid = m.groups()
    return {"id": pid, "url": f"https://x.com/{user}/status/{pid}", "author": user,
            "posted_at": snowflake_time(pid), "posted_at_source": "snowflake", "text": None, "receipt_sha256": None}


def get_json(url, tries=3):
    """GET json with retries on rate limits / server errors; Yahoo also falls back to query2."""
    import time
    urls = [url] + ([url.replace("query1.finance.yahoo.com", "query2.finance.yahoo.com")] if "query1.finance" in url else [])
    last = None
    for attempt in range(tries):
        for u in urls:
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                last = e
                if e.code not in (429, 500, 502, 503, 504):
                    raise
            except (urllib.error.URLError, TimeoutError) as e:
                last = e
        time.sleep(5 * (attempt + 1))
    raise last


def fetch_series(asset, since):
    """Hourly [iso, open] bars from the hour containing `since` to now."""
    start = parse(since).replace(minute=0, second=0, microsecond=0)
    if asset["source"] == "binance":
        out, ms = [], int(start.timestamp() * 1000)
        while True:
            try:
                rows = get_json("https://data-api.binance.vision/api/v3/klines?symbol="
                                f"{asset['symbol']}&interval=1h&startTime={ms}&limit=1000")
            except urllib.error.HTTPError as e:
                raise UnknownAssetError(f"no binance data for {asset['symbol']} (HTTP {e.code})") from e
            out += [[iso(r[0] / 1000), float(r[1])] for r in rows]
            if len(rows) < 1000:
                break
            ms = rows[-1][0] + 3_600_000
        return out
    p1 = int((start - dt.timedelta(days=1)).timestamp())
    p2 = int(dt.datetime.now(dt.timezone.utc).timestamp())
    try:
        res = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{asset['symbol']}"
                       f"?period1={p1}&period2={p2}&interval=1h")["chart"]["result"]
    except urllib.error.HTTPError as e:
        raise UnknownAssetError(f"no yahoo data for {asset['symbol']} (HTTP {e.code})") from e
    if not res or not res[0].get("timestamp"):
        raise UnknownAssetError(f"no yahoo data for {asset['symbol']}")
    opens = res[0]["indicators"]["quote"][0]["open"]
    return [[iso(t), round(o, 4)] for t, o in zip(res[0]["timestamp"], opens) if o is not None]


class Prices:
    """Bars per asset name, from a snapshot file or fetched live (cached per asset per run)."""

    def __init__(self, snapshot=None):
        self.label = os.path.relpath(snapshot, HERE) if snapshot else "live:binance+yahoo"
        self.snapshot = None
        if snapshot:
            with open(snapshot) as f:
                self.snapshot = json.load(f)
        self.cache = {}

    def series(self, asset, since):
        if self.snapshot is not None:
            if asset["name"] not in self.snapshot:
                raise UnknownAssetError(f"asset {asset['name']} not in price snapshot {self.label}")
            return self.snapshot[asset["name"]]
        hit = self.cache.get(asset["name"])
        if hit is None or hit[0] > since:
            hit = (since, fetch_series(asset, since))
            self.cache[asset["name"]] = hit
        return hit[1]


def bar_at_or_after(series, when, times=None):
    times = times or [t for t, _ in series]
    i = bisect.bisect_left(times, when)
    return (i, series[i]) if i < len(series) else (None, None)


def lag_limit(asset):
    """Days a bar may lag its target time: 2 for 24/7 crypto, 4 for exchange-hours assets."""
    return EXCHANGE_HOURS_LAG_DAYS if asset["source"] == "yahoo" else MAX_LAG_DAYS


def resolve(post, asset, series, prices_label, side=None):
    times = [t for t, _ in series]
    when = post["posted_at"]
    rec = {"schema": "post_price.v1", "post": post, "asset": asset}
    if side is not None:
        rec["side"] = side
    rec.update({"status": None, "entry": None, "latest": None, "change_since_post": None,
                "exits": {}, "moves": {}, "unresolved": {}, "series": [],
                "resolved_with": {"prices": prices_label, "last_bar_at": times[-1] if times else None,
                                  "max_lag_days": MAX_LAG_DAYS,
                                  "session_lag_days": lag_limit(asset)}})
    if side is not None:
        rec["signed_returns"] = {}
    i, entry = bar_at_or_after(series, when, times)
    limit = lag_limit(asset)
    if entry is None or lag_days(when, entry[0]) > limit:
        reason = ("no bar at or after the post yet" if entry is None
                  else f"first bar {entry[0]} is >{limit} days after the post (market closed)")
        rec["status"] = "pending" if entry is None else "no_entry"
        for h in map(str, HORIZONS):
            rec["exits"][h] = None
            rec["moves"][h] = None
            rec["unresolved"][h] = reason
            if side is not None:
                rec["signed_returns"][h] = None
        return rec
    p0 = entry[1]
    rec["entry"] = {"at": entry[0], "price": p0}
    rec["latest"] = {"at": series[-1][0], "price": series[-1][1]}
    rec["change_since_post"] = series[-1][1] / p0 - 1
    rec["series"] = [list(b) for b in series[i:]]
    for h in HORIZONS:
        k = str(h)
        target = (parse(when) + dt.timedelta(days=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _, ex = bar_at_or_after(series, target, times)
        move = None
        if ex is None:
            rec["unresolved"][k] = "horizon not yet reached"
        elif lag_days(target, ex[0]) > limit:
            rec["unresolved"][k] = f"first bar {ex[0]} is >{limit} days after {target} (market closed)"
            ex = None
        else:
            move = ex[1] / p0 - 1
        rec["exits"][k] = {"at": ex[0], "price": ex[1]} if ex else None
        rec["moves"][k] = move
        if side is not None:
            rec["signed_returns"][k] = None if ex is None else side * (ex[1] / p0 - 1)
    rec["status"] = "partial" if rec["unresolved"] else "resolved"
    return rec


def validator():
    import jsonschema
    with open(SCHEMA_PATH) as f:
        return jsonschema.Draft202012Validator(json.load(f))


def check_record(v, rec):
    errs = sorted(v.iter_errors(rec), key=lambda e: list(e.path))
    if errs:
        raise ResolveError(f"schema: {rec['post']['id']} {rec['asset']['name']}: "
                           + "; ".join(f"{'/'.join(map(str, e.path))}: {e.message}" for e in errs[:5]))


def side_of(s):
    if s in (None, ""):
        return None
    s = str(s).lower()
    if s in ("long", "1", "+1"):
        return 1
    if s in ("short", "-1"):
        return -1
    raise ResolveError(f"side must be long or short, got {s!r}")


def run(items, prices, out_dir=None, v=None):
    """items: [{"url"|"receipt", "asset", "side"?}]. Returns (records, duplicates, errors)."""
    v = v or validator()
    records, seen, dupes, errors = [], set(), [], []
    for n, it in enumerate(items):
        try:
            post = load_post(it.get("url"), it.get("receipt"))
            asset = asset_info(it["asset"])
            key = (post["id"], asset["name"])
            if key in seen:
                raise DuplicatePostError(f"duplicate post {post['id']} for {asset['name']} (item {n}), kept the first")
            seen.add(key)
            rec = resolve(post, asset, prices.series(asset, post["posted_at"]), prices.label, side_of(it.get("side")))
            check_record(v, rec)
        except DuplicatePostError as e:
            dupes.append(str(e))
            continue
        except ResolveError as e:
            errors.append(f"item {n}: {e}")
            continue
        records.append(rec)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, f"{post['id']}_{asset['name'].replace(':', '-').replace('=', '')}.json")
            with open(path, "w") as f:
                json.dump(rec, f, indent=1)
                f.write("\n")
    return records, dupes, errors


def pct(x):
    return "unresolved" if x is None else f"{x * 100:+.2f}%"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url")
    ap.add_argument("--receipt")
    ap.add_argument("--asset")
    ap.add_argument("--side")
    ap.add_argument("--batch")
    ap.add_argument("--prices", help="price snapshot json {asset name: [[iso, open], ...]}; default: fetch live")
    ap.add_argument("--out", help="write one record per post to this directory")
    a = ap.parse_args()
    if a.batch:
        with open(a.batch) as f:
            items = json.load(f)
    elif (a.url or a.receipt) and a.asset:
        items = [{"url": a.url, "receipt": a.receipt, "asset": a.asset, "side": a.side}]
    else:
        ap.error("need --url/--receipt with --asset, or --batch")
    records, dupes, errors = run(items, Prices(a.prices), a.out)
    for r in records:
        e = r["entry"]
        print(f"{r['post']['id']} {r['asset']['name']:<8} {r['status']:<8} posted {r['post']['posted_at']} "
              f"entry {e['price'] if e else '-'} @ {e['at'] if e else '-'} | since post {pct(r['change_since_post'])} | "
              + " ".join(f"{h}d {pct(r['moves'][h])}" for h in ("1", "7", "30")))
    for d in dupes:
        print("DUPLICATE", d)
    for err in errors:
        print("ERROR", err, file=sys.stderr)
    print(f"{len(records)} records, schema-valid {len(records)}/{len(records)}, {len(dupes)} duplicates, {len(errors)} errors")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
