#!/usr/bin/env python3
"""Step 24: early signals. The first post where an account named a coin, what the coin cost then,
and how that aged (now, peak since). Score-neutral: an early signal is labelled and shown, never rated.
A first mention that is itself a stated position is reported so it can be added as a normal call.

  python3 tools/first_mention.py find  <handle> <ASSET>      # narrowing X searches -> intake/early/<handle>_<ASSET>.json
  python3 tools/first_mention.py price <handle> <ASSET>      # receipt + prices -> sources/early/<handle>/<ASSET>.json
  python3 tools/first_mention.py build                       # web/data/early.json (+ the pages via prerender / coins_page)
  python3 tools/first_mention.py refresh                     # today's price and the peak again (daily job; the "then" price is frozen)

Finding the first post (read-only searches through the x-research harness, every search logged):
  1. yearly windows from the asset's floor (whitepaper / launch) forward, until a year holds a confirmed mention
  2. monthly windows inside that year, until a month holds one
  3. halving that month down to single days (earlier half first), so a busy month cannot hide its first day
  A search that returns no posts is searched again before the window counts as empty (X throttles; an empty
  page is not proof). Posts that only match a search word but do not name the asset by the step 23 rules
  ("sol" in Spanish, "solution") are logged as word hits and do not count. Reposts are not the author's words.
  A harness error stops the run (state kept); `find` resumes from the log.

Pricing (sources tried in order; the first whose history covers the post is used, else the earliest first bar
and the label "before listing"): the asset's own venue (data/tickers.json / resolve), other Binance USD pairs,
Bitfinex tXXXUSD (long history, e.g. ZEC from its launch day). then = the first hourly bar at or after the post.
now = the venue's latest hourly bar. peak = the highest daily high since the post (the then-source until the
venue's history starts, the venue after). Every price is stamped with source, symbol, bar time and value.
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
import detect  # noqa: E402
import resolve  # noqa: E402

SCHEMA = "quanty.early_signal.v1"
BUNDLE_SCHEMA = "quanty.early_signals.v1"
FLOOR = {"SOL": "2017-11-01", "ZEC": "2016-01-01", "BTC": "2009-01-01", "ETH": "2014-01-01", "HYPE": "2024-11-01", "LIT": "2025-01-01"}
ALT_PAIRS = {"SOL": ["SOLBUSD"], "ZEC": [], "ETH": [], "BTC": []}       # older Binance USD pairs (delisted later)
EXCLUDE_KINDS = ("repost",)
CANARY_TTL = 0               # seconds a working canary vouches for empty answers: 0 = every empty window gets its own canary (X throttling starts without warning)
COMPLETE_BELOW = 15
CANARY_MIN_SHARE = 0.5        # a canary vouches for an empty window only if it returns at least half the best canary seen (X degrades before it goes silent)          # a window answering fewer posts than this is complete: its earliest post is exact, no need to narrow



def load_json(path):
    with open(path) as f:
        return json.load(f)


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()

def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


# ---- which words name the asset (the step 23 rules, as a plain matcher) -----------------------
def asset_terms(asset, words=None, amap=None):
    """-> {"query": [search words], "patterns": [(compiled, label)]}."""
    words = words or detect.coin_words()
    amap = amap or detect.load_map()
    names = sorted({n for n, t in words.get("names", {}).items() if t == asset} | {t for _, t, a in amap["terms"] if a == asset})
    blocked = set(words.get("bare_blocked", []))
    pats = [(re.compile(r"(?<![\w$])\$" + re.escape(asset) + r"(?![\w])", re.I), f"${asset}")]
    if asset in amap["cashtags"] or asset not in blocked:                                            # capitals: SOL, ZEC (not NEAR)
        pats.append((re.compile(r"(?<![\w$:])" + re.escape(asset) + r"(?![\w])"), asset))
    if asset not in blocked and len(asset) >= 3 and asset.lower() not in names:
        pats.append((re.compile(r"(?<![\w$:])" + re.escape(asset.lower()) + r"(?![\w])"), asset.lower()))   # zec (not sol: a common word)
    for n in names:
        pats.append((re.compile(r"(?<![\w&])" + re.escape(n).replace(r"\ ", r"\s+") + r"(?![\w&])", re.I), n))
    query = sorted({asset.lower(), "$" + asset.lower()} | {n if " " not in n else f'"{n}"' for n in names})
    return {"query": query, "patterns": pats}


def matches(text, terms):
    return [label for pat, label in terms["patterns"] if pat.search(text or "")]


# ---- searching ----------------------------------------------------------------------------------
SEARCH_PAUSE = float(os.environ.get("QUANTY_SEARCH_PAUSE", "8"))   # seconds between live X searches (X throttles bursts)


def harness_search(query):
    import scan_caller
    time.sleep(SEARCH_PAUSE)
    return scan_caller.run_harness(query)


def day(d):
    return d.strftime("%Y-%m-%d")


def parse_day(s):
    return dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)


class Stop(Exception):
    pass


class Finder:
    def __init__(self, handle, asset, search=None, log=None, today=None, words=None, amap=None):
        self.handle, self.asset = handle, asset.upper()
        self.search = search or harness_search
        self.log = log if log is not None else []
        self.today = today or dt.datetime.now(dt.timezone.utc)
        self.terms = asset_terms(self.asset, words, amap)
        # resumable: confirmed-empty windows and hit windows that kept their posts are not searched again
        self._best = max([e.get("raw") or 0 for e in self.log if e.get("level") == "canary"] or [0])
        self._cache = {(e["since"], e["until"]): e for e in self.log
                       if e.get("result") == "word hits only" or (e.get("result") == "hit" and e.get("posts"))
                       or (e.get("result") == "empty (confirmed)" and self.strong(e.get("canary_raw")))}
        self.notes = []
        self.clock = time.time
        self._canary_ok_at = None

    def canary(self):
        """X answers 'no posts' (not an error) while it throttles. An empty window only counts when a search that must
        return posts (the account's last 7 days) still does; otherwise the run stops and resumes later."""
        if CANARY_TTL and self._canary_ok_at and self.clock() - self._canary_ok_at < CANARY_TTL:
            return True
        since, until = day(self.today - dt.timedelta(days=7)), day(self.today + dt.timedelta(days=1))
        q = f"from:{self.handle} since:{since} until:{until}"
        m, run, err = self.search(q)
        n = len((m or {}).get("posts", [])) if not err else 0
        self._best = max(self._best, n)
        self.last_canary = n
        ok = self.strong(n)
        self.log.append({"level": "canary", "since": since, "until": until, "query": q, "attempt": 1, "at": now_iso(), "run": run,
                         "manifest_sha256": (m or {}).get("_sha256"), "raw": n, "best": self._best,
                         "result": "canary ok" if ok else (f"canary weak ({n} of {self._best}: throttling)" if n else "canary empty (throttled)")})
        if ok:
            self._canary_ok_at = self.clock()
            return True
        return False

    def strong(self, n):
        return bool(n) and n >= CANARY_MIN_SHARE * self._best

    def query(self, since, until):
        return f"from:{self.handle} ({' OR '.join(self.terms['query'])}) since:{since} until:{until}"

    def window(self, level, since, until):
        """One window, searched (and an empty answer searched again). -> list of confirmed posts, oldest first."""
        if (since, until) in self._cache:
            e = self._cache[(since, until)]
            self.last = e
            return e.get("posts", [])
        q = self.query(since, until)
        for attempt in (1, 2):
            m, run, err = self.search(q)
            entry = {"level": level, "since": since, "until": until, "query": q, "attempt": attempt, "at": now_iso(),
                     "run": run, "manifest_sha256": (m or {}).get("_sha256")}
            if err:
                entry.update(result="error", error=str(err)[-300:])
                self.log.append(entry)
                raise Stop(f"search failed on {since}..{until}: {str(err)[-200:]}")
            posts = [p for p in (m or {}).get("posts", []) if (p.get("authorHandle") or "").lower() == self.handle.lower()]
            if not posts and attempt == 1:
                entry.update(result="empty (searching again)", raw=0)
                self.log.append(entry)
                continue
            if not posts and not self.canary():
                entry.update(result="empty, canary weak or empty (throttled)", raw=0, canary_raw=self.last_canary, canary_best=self._best)
                self.log.append(entry)
                raise Stop(f"X returned nothing for {since}..{until} and the canary returned {self.last_canary} of {self._best}: throttled, resume later")
            mine = [p for p in posts if p.get("kind") not in EXCLUDE_KINDS]
            confirmed = sorted(({**p, "_matched": matches(p.get("text"), self.terms)} for p in mine if matches(p.get("text"), self.terms)),
                               key=lambda p: p["postedAt"])
            entry.update(raw=len(posts), reposts=len(posts) - len(mine), confirmed=len(confirmed),
                         result="hit" if confirmed else ("word hits only" if posts else "empty (confirmed)"),
                         canary_raw=None if posts else self.last_canary, canary_best=None if posts else self._best,
                         earliest=({"id": confirmed[0]["id"], "postedAt": confirmed[0]["postedAt"], "matched": confirmed[0]["_matched"]} if confirmed else None))
            entry["posts"] = [{k: p.get(k) for k in ("id", "url", "postedAt", "kind", "text", "_matched")} for p in confirmed]
            self.log.append(entry)
            self._cache[(since, until)] = entry
            self.last = entry
            return entry["posts"]
        return []

    def run(self, floor=None):
        """Years (an empty year is skipped; any other year is always opened month by month, since X ranks a year's results
        by relevance), then each window is taken as complete when it answers fewer than COMPLETE_BELOW posts, and opened
        (halved down to a day) when it answers more, whether or not the posts it showed named the coin."""
        floor = parse_day(floor or FLOOR.get(self.asset, "2010-01-01"))
        end = self.today + dt.timedelta(days=1)
        for year in range(floor.year, end.year + 1):
            s = max(floor, dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc))
            u = min(end, dt.datetime(year + 1, 1, 1, tzinfo=dt.timezone.utc))
            got = self.window("year", day(s), day(u))
            if not self.last.get("raw"):
                continue
            first = self.within(s, u, "month")
            if first:
                return first
            if got:
                raise Stop(f"{year} had a mention but no month did (inconsistent search results): run again")
        return None

    def within(self, s, u, level):
        """The first mention inside [s, u): its months (level 'month') or its two halves (level 'day'), earliest first."""
        if level == "month":
            subs, m = [], s.replace(day=1)
            while m < u:
                nxt = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
                subs.append((max(s, m), min(u, nxt)))
                m = nxt
        else:
            mid = s + dt.timedelta(days=(u - s).days // 2)
            subs = [(s, mid), (mid, u)]
        for a, b in subs:
            got = self.window(level, day(a), day(b))
            raw = self.last.get("raw", 0)
            if raw >= COMPLETE_BELOW and (b - a).days > 1:            # X may have cut the list short: look inside
                inner = self.within(a, b, "day")
                if inner:
                    return inner
                if got:
                    # X search can miss posts in a narrow window that a wider window returned: keep the wider window's answer
                    self.notes.append(f"{day(a)}..{day(b)} held posts but both halves came back empty (twice each): "
                                      "the first post is taken from that window")
                    return got[0]
                self.notes.append(f"{day(a)}..{day(b)} answered {raw} posts, none naming the coin, and no narrower window held a mention")
                continue
            if got:
                if raw >= COMPLETE_BELOW:
                    self.notes.append(f"{day(a)}..{day(b)} still answered {raw} posts on a single day (may be truncated by X)")
                return got[0]
        return None


def label_post(p):
    """mention / stated position (long / short) / not his: the step 16 + 23 first-person rules."""
    if p.get("kind") in EXCLUDE_KINDS:
        return {"label": "not his (repost)", "side": None, "words": []}
    text = p.get("text") or ""
    d = detect.detect_side(text)
    if d["status"] == "detected":
        return {"label": "stated position", "side": "long" if d["side"] == 1 else "short", "words": (d["terms"][1] + d["terms"][-1])[:5]}
    return {"label": "mention", "side": None, "words": []}


# ---- pricing ------------------------------------------------------------------------------------
def binance_klines(symbol, interval, start_ms, limit=1000):
    return resolve.get_json(f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&startTime={start_ms}&limit={limit}")


def bitfinex_candles(symbol, tf, start_ms, limit=10000):
    return resolve.get_json(f"https://api-pub.bitfinex.com/v2/candles/trade:{tf}:{symbol}/hist?sort=1&limit={limit}&start={start_ms}")


class Sources:
    """Price sources for one asset, each answering first_bar_at_or_after (hourly) and daily highs."""
    def __init__(self, asset, get_binance=None, get_bitfinex=None):
        self.asset = asset
        self.bk = get_binance or binance_klines
        self.bf = get_bitfinex or bitfinex_candles
        info = resolve.asset_info(asset)
        self.venue = (info["source"], info["symbol"])
        self.order = [self.venue] + [("binance", s) for s in ALT_PAIRS.get(asset, [])] + [("bitfinex", f"t{asset}USD")]

    def first_bar(self, src, ms):
        source, sym = src
        if source == "binance":
            rows = self.bk(sym, "1h", ms, 1)
            return (int(rows[0][0]), float(rows[0][1])) if isinstance(rows, list) and rows else None
        if source == "bitfinex":
            rows = self.bf(sym, "1h", ms, 1)
            return (int(rows[0][0]), float(rows[0][1])) if isinstance(rows, list) and rows else None
        if source == "hyperliquid":
            c = resolve.hyperliquid_candles(sym, dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc))
            return (int(c[0]["t"]), float(c[0]["o"])) if c else None
        return None

    def start_of(self, src):
        return self.first_bar(src, 0)

    def daily_highs(self, src, start_ms, end_ms=None, hourly=False):
        source, sym = src
        step = 3_600_000 if hourly else 86_400_000
        out, t = [], start_ms
        end_ms = end_ms or int(time.time() * 1000)
        while t < end_ms:
            if source == "binance":
                rows = self.bk(sym, "1h" if hourly else "1d", t, 1000)
                rows = [(int(r[0]), float(r[2])) for r in rows] if isinstance(rows, list) else []
            elif source == "bitfinex":
                rows = self.bf(sym, "1h" if hourly else "1D", t, 10000)
                rows = [(int(r[0]), float(r[3])) for r in rows] if isinstance(rows, list) else []
            else:
                rows = [(int(c["t"]), float(c["h"])) for c in resolve.hyperliquid_candles(sym, dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc), "1h" if hourly else "1d")]
            rows = [r for r in rows if r[0] < end_ms]
            if not rows:
                break
            out += rows
            if len(rows) < 900:
                break
            t = rows[-1][0] + step
        return out

    def latest(self):
        source, sym = self.venue
        if source == "binance":
            rows = resolve.get_json(f"https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval=1h&limit=1")
            return int(rows[-1][0]), float(rows[-1][1])
        series = resolve.fetch_series(resolve.asset_info(self.asset), resolve.iso(time.time() - 7200))
        return int(resolve.parse(series[-1][0]).timestamp() * 1000), series[-1][1]


def iso_ms(ms):
    return resolve.iso(ms / 1000)


def price_signal(post_at, src_obj):
    """-> the then / now / peak block, every value stamped with its source."""
    post_ms = int(resolve.parse(post_at).timestamp() * 1000)
    tried, then, starts, covered_but_failed = [], None, {}, False
    for src in src_obj.order:
        try:
            start = src_obj.start_of(src)
        except Exception as e:  # noqa: BLE001 - a source that does not answer is listed and skipped
            tried.append({"source": f"{src[0]}:{src[1]}", "error": str(e)[:120]})
            continue
        starts[src] = start
        if not start:
            tried.append({"source": f"{src[0]}:{src[1]}", "history_from": None})
            continue
        tried.append({"source": f"{src[0]}:{src[1]}", "history_from": iso_ms(start[0])})
        if start[0] <= post_ms and not then:
            try:
                bar = src_obj.first_bar(src, post_ms)
            except Exception as e:  # noqa: BLE001
                tried[-1]["error"], bar = str(e)[:120], None
            if not bar:
                covered_but_failed = True
            else:
                then = {"source": src[0], "symbol": src[1], "at": iso_ms(bar[0]), "price": bar[1], "before_listing": False}
    if not then and covered_but_failed:               # a source had history at the post but did not answer: never guess
        raise RuntimeError("a source covering the post did not return its bar; run again: " + json.dumps(tried))
    if not then and any("error" in t for t in tried):  # 'before listing' needs every source's start: an unknown one could cover the post
        raise RuntimeError("a source did not answer, so 'before listing' cannot be shown; run again: " + json.dumps(tried))
    if not then:                                       # no source covers the post: the earliest first bar, labelled
        firsts = [(f, s) for s, f in starts.items() if f]                    # only the sources that answered above
        if not firsts:
            raise RuntimeError("no price source answered: " + json.dumps(tried))
        (ms, price), src = min(firsts, key=lambda x: x[0][0])
        then = {"source": src[0], "symbol": src[1], "at": iso_ms(ms), "price": price, "before_listing": True}
    now_ms, now_px = src_obj.latest()
    now = {"source": src_obj.venue[0], "symbol": src_obj.venue[1], "at": iso_ms(now_ms), "price": now_px}
    # peak: the then-source until the venue's history starts, the venue after (daily highs)
    then_src = (then["source"], then["symbol"])
    then_ms = int(resolve.parse(then["at"]).timestamp() * 1000)
    if not starts.get(src_obj.venue):                 # 'now' and the recent peak are the registered venue's: no silent swap
        raise RuntimeError(f"the registered venue {src_obj.venue[0]}:{src_obj.venue[1]} did not answer; run again: " + json.dumps(tried))
    venue_start = starts[src_obj.venue][0]
    def segment(src, a, b=None):
        """highs from a to b: the hourly bars to the next midnight (the post's own day), then daily bars"""
        midnight = (a // 86_400_000 + 1) * 86_400_000
        hours = [(t, h, src) for t, h in src_obj.daily_highs(src, a, min(midnight, b) if b else midnight, hourly=True)]
        days = [(t, h, src) for t, h in src_obj.daily_highs(src, midnight, b)] if not b or midnight < b else []
        return hours + days
    highs = [(then_ms, then["price"], then_src)]                                     # the peak is never below the then-price
    if then_src != src_obj.venue and then_ms < venue_start:
        highs += segment(then_src, then_ms, venue_start)
    highs += segment(src_obj.venue, max(then_ms, venue_start))
    t, h, s = max(highs, key=lambda x: (x[1], -x[0]))
    peak = {"source": s[0], "symbol": s[1], "day": iso_ms(t)[:10], "high": h}
    return {"then": then, "now": now, "peak": peak, "multiple_now": now["price"] / then["price"], "multiple_peak": peak["high"] / then["price"],
            "sources_tried": tried, "note": "then and peak can come from an older venue than now (all USD / USDT quotes); 'before listing' = the post predates every source's first bar"}


# ---- files --------------------------------------------------------------------------------------
def state_path(root, handle, asset):
    return os.path.join(root, "intake", "early", f"{handle.lower()}_{asset}.json")


def receipt_path(root, handle, asset):
    return os.path.join(root, "sources", "early", handle.lower(), f"{asset}.json")


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.write("\n")


def cmd_find(handle, asset, root=HERE, search=None, today=None):
    sp = state_path(root, handle, asset)
    log = load_json(sp)["log"] if os.path.exists(sp) else []
    f = Finder(handle, asset, search=search, log=log, today=today)
    try:
        first = f.run()
        status = "found" if first else "none"
    except Stop as e:
        first, status = None, f"stopped: {e}"
    clean = list(f.log)
    out = {"schema": SCHEMA + ".search", "handle": handle, "asset": asset.upper(), "status": status, "terms": f.terms["query"], "notes": f.notes,
           "rule": f"years -> months -> the hit month; a window answering fewer than {COMPLETE_BELOW} posts is complete (its earliest post is exact), "
                   "else it is halved (earlier half first); every empty answer is searched twice and only counts while a canary search (the account's last 7 days) returns posts",
           "first": ({k: first.get(k) for k in ("id", "url", "postedAt", "kind", "text", "_matched")} if first else None),
           "searches": len(clean), "log": clean, "updated_at": now_iso()}
    save(sp, out)
    return out


def cmd_price(handle, asset, root=HERE, sources=None, fetch_receipt=None):
    st = load_json(state_path(root, handle, asset))
    if st["status"] != "found":
        raise SystemExit(f"no first post for {handle} x {asset}: {st['status']}")
    first = st["first"]
    import ingest
    rpath, receipt, created = (fetch_receipt or (lambda url: ingest.ingest(url, root=root)))(first["url"])
    rblob = read_bytes(rpath)
    lab = label_post({**first, "text": receipt.get("text") or first["text"]})
    px = price_signal(first["postedAt"].replace(".000Z", "Z"), sources or Sources(asset.upper()))
    narrowing = [{k: e.get(k) for k in ("level", "since", "until", "attempt", "result", "raw", "confirmed", "run", "manifest_sha256", "earliest")}
                 for e in st["log"]]
    doc = {"schema": SCHEMA, "handle": handle, "asset": asset.upper(), "built_at": now_iso(), "score_neutral": True,
           "post": {"id": first["id"], "url": first["url"], "posted_at": first["postedAt"].replace(".000Z", "Z"), "kind": first.get("kind"),
                    "text": receipt.get("text") or first["text"], "matched": first.get("_matched"),
                    "receipt": os.path.relpath(rpath, root), "receipt_sha256": sha_bytes(rblob)},
           "label": lab, "prices": px, "search": {"terms": st["terms"], "searches": len(narrowing), "log": narrowing,
                                                  "search_log_file": os.path.relpath(state_path(root, handle, asset), root)}}
    save(receipt_path(root, handle, asset), doc)
    return doc


def recorded_calls(root, handle, asset):
    """The caller's scored calls on the same coin (records/**), oldest first: the early signal is linked to them, never mixed in."""
    import glob
    out = []
    for f in glob.glob(os.path.join(root, "records", "**", "*.json"), recursive=True):
        try:
            r = load_json(f)
        except (OSError, ValueError):
            continue
        if r.get("schema") != "post_price.v1" or (r.get("post", {}).get("author") or "").lower() != handle.lower():
            continue
        if (r.get("asset", {}).get("name") or "").upper() != asset.upper() or not r.get("entry"):
            continue
        out.append({"record": os.path.relpath(f, root), "url": r["post"]["url"], "posted_at": r["post"]["posted_at"], "side": r.get("side"),
                    "entry": r["entry"], "text": r["post"].get("text")})
    return sorted(out, key=lambda c: c["posted_at"])


def call_gap(sig, calls):
    """First mention -> first recorded call: days between them and how far the price had moved by the call."""
    if not calls:
        return None
    c = calls[0]
    a, b = resolve.parse(sig["post"]["posted_at"]), resolve.parse(c["posted_at"])
    then = sig["prices"]["then"]["price"]
    return {"call": c, "days": round((b - a).total_seconds() / 86400, 1), "calls_on_coin": len(calls),
            "price_move_before_call": c["entry"]["price"] / then if then else None,
            "after_first_mention": b >= a}


def build(root=HERE):
    import glob
    sigs = []
    for f in sorted(glob.glob(os.path.join(root, "sources", "early", "*", "*.json"))):
        d = load_json(f)
        blob = read_bytes(f)
        sigs.append({**{k: d[k] for k in ("handle", "asset", "post", "label", "prices", "score_neutral")}, "file": os.path.relpath(f, root),
                     "file_sha256": sha_bytes(blob), "searches": d["search"]["searches"]})
        sigs[-1]["first_call"] = call_gap(sigs[-1], recorded_calls(root, d["handle"], d["asset"]))
    aff_p = os.path.join(root, "data", "affiliations.json")
    aff = load_json(aff_p)["callers"] if os.path.exists(aff_p) else {}
    bundle = {"schema": BUNDLE_SCHEMA, "note": "the first post where an account named a coin; score-neutral (never part of a caller score)",
              "signals": sigs, "affiliations": aff}
    save(os.path.join(root, "web", "data", "early.json"), bundle)
    return bundle


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["find", "price", "build", "refresh"])
    ap.add_argument("handle", nargs="?")
    ap.add_argument("asset", nargs="?")
    a = ap.parse_args(argv)
    if a.cmd == "find":
        out = cmd_find(a.handle, a.asset.upper())
        print(f"{a.handle} x {a.asset.upper()}: {out['status']} after {out['searches']} searches")
        for e in out["log"]:
            print(f"  {e['level']:<5} {e['since']} .. {e['until']}  try {e['attempt']}  {e['result']:<22} raw {e.get('raw', '-')} confirmed {e.get('confirmed', '-')}"
                  + (f"  earliest {e['earliest']['postedAt']} {e['earliest']['matched']}" if e.get("earliest") else ""))
        if out["first"]:
            print(f"FIRST {out['first']['postedAt']} {out['first']['url']}\n  “{' '.join((out['first']['text'] or '').split())[:240]}”")
        return 0 if out["status"] in ("found", "none") else 3
    if a.cmd == "price":
        d = cmd_price(a.handle, a.asset.upper())
        p = d["prices"]
        print(json.dumps({"post": d["post"]["posted_at"], "label": d["label"], "then": p["then"], "now": p["now"], "peak": p["peak"],
                          "x_now": round(p["multiple_now"], 3), "x_peak": round(p["multiple_peak"], 3)}, indent=1))
        return 0
    if a.cmd == "build":
        b = build()
        print(f"web/data/early.json: {len(b['signals'])} signals")
        return 0
    return refresh()


def refresh_doc(d, src):
    """Today's price, and daily highs after the stored peak day. The post's own day is never re-read from midnight:
    its hours before the post do not count, and its hours after it were read hour by hour when the signal was priced."""
    then = d["prices"]["then"]
    now_ms, now_px = src.latest()
    d["prices"]["now"] = {"source": src.venue[0], "symbol": src.venue[1], "at": iso_ms(now_ms), "price": now_px}
    d["prices"]["multiple_now"] = now_px / then["price"]
    pk = d["prices"]["peak"]
    since_ms = int(resolve.parse(pk["day"] + "T00:00:00Z").timestamp() * 1000)
    if pk["day"] <= then["at"][:10]:
        since_ms = int(resolve.parse(then["at"][:10] + "T00:00:00Z").timestamp() * 1000) + 86_400_000
    for t, h in src.daily_highs(src.venue, since_ms):
        if t >= since_ms and h > pk["high"]:
            pk.update(source=src.venue[0], symbol=src.venue[1], day=iso_ms(t)[:10], high=h)
    d["prices"]["multiple_peak"] = pk["high"] / then["price"]
    return d


def refresh(root=HERE):
    """Daily: today's price and the peak again; the post, the then-price and the search stay frozen."""
    import glob
    for f in sorted(glob.glob(os.path.join(root, "sources", "early", "*", "*.json"))):
        d = load_json(f)
        save(f, refresh_doc(d, Sources(d["asset"])))
    build(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
