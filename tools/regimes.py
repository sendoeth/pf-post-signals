#!/usr/bin/env python3
"""Step 28: callers by crypto market regime. Score-neutral: the main caller score (rate.py) is untouched.

usage: python3 tools/regimes.py fetch     (append newly completed BTC daily bars to data/btc_daily.json)
       python3 tools/regimes.py build     (web/data/regimes.json + web/regimes.html from the stored bars and the bundle)

The regime of the BTC market, from Binance BTCUSDT daily closes, with fixed parameters (PARAMS):
  trend   bull  close > SMA200 and SMA50 > SMA200
          bear  close < SMA200 and SMA50 < SMA200
          chop  anything else (the two disagree)
  confirm the regime switches only after the raw trend has held its new value for CONFIRM consecutive days
  vol     high when the 30-day realized volatility of daily log returns is above VOL_MULT x its median over the
          previous 365 days, else normal (a tag beside the regime)
No look-ahead: day D's label is computed from bars up to D only, left to right; a call at time t takes the label
of the last bar whose close time is at or before t, so a bar still open at t is never used.
Data integrity: only complete bars are stored; a fetch appends new ones and fails closed if any stored bar would change.
"""
import argparse
import bisect
import collections
import datetime as dt
import hashlib
import html
import json
import math
import os
import statistics
import sys
import time
import urllib.request

TOOLS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TOOLS)
sys.path[:0] = [HERE, TOOLS]
import rate  # noqa: E402

VERSION = "quanty.regime.v1"
PARAMS = {"sma_fast": 50, "sma_slow": 200, "confirm": 3, "vol_window": 30, "vol_lookback": 365, "vol_mult": 1.5}
GRID = {"sma_slow": [180, 220], "sma_fast": [40, 60], "confirm": [2, 4, 5], "vol_mult": [1.3, 1.7]}
SOURCE = "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1d"
DATA = os.path.join(HERE, "data", "btc_daily.json")
START = "2018-02-09"    # Binance's 2018-02-08 bar is a truncated outage bar (closes 00:28 UTC); the series starts after it
DAY_MS = 86_400_000
REGIMES = ("bull", "chop", "bear")
CRYPTO_SOURCES = ("binance", "hyperliquid", "hlspot", "dex", "okx", "gate", "bybit")
e = lambda s: html.escape(str(s), quote=True)


class Integrity(Exception):
    pass


def iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day(ms):
    return iso(ms)[:10]


def parse(ts):
    return int(dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)


def load(path):
    with open(path) as f:
        return json.load(f)


def bars_sha(bars):
    return hashlib.sha256(json.dumps(bars, separators=(",", ":")).encode()).hexdigest()


# ---- data -----------------------------------------------------------------------------------------
def validate(bars):
    """Unique, ordered, contiguous UTC days, each a complete 24h bar with positive prices; else Integrity (nothing labelled)."""
    if not bars:
        raise Integrity("no bars")
    for i, b in enumerate(bars):
        if len(b) != 7 or b[0] % DAY_MS or b[1] != b[0] + DAY_MS - 1 or min(b[2:6]) <= 0 or not (b[4] <= min(b[2], b[5]) <= max(b[2], b[5]) <= b[3]):
            raise Integrity(f"malformed bar {i} ({b[:2]})")
        if i and b[0] - bars[i - 1][0] != DAY_MS:
            raise Integrity(f"bars not contiguous between {day(bars[i - 1][0])} and {day(b[0])} (gap, duplicate or out of order)")
    return bars


def fetch_klines(start_ms, get=None):
    get = get or (lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30)))
    out, t = [], start_ms
    while True:
        rows = get(f"{SOURCE}&startTime={t}&limit=1000")
        if not rows:
            break
        out += rows
        if len(rows) < 1000:
            break
        t = rows[-1][0] + DAY_MS
    return out


def fetch(path=DATA, now_ms=None, get=None):
    """Append the newly COMPLETED bars; refuse if any stored bar would change (nothing written then)."""
    now_ms = now_ms or int(time.time() * 1000)
    have = load(path) if os.path.exists(path) else {"bars": []}
    old = have["bars"]
    start = old[-1][0] - 5 * DAY_MS if old else parse(START + "T00:00:00Z")      # re-read the last days: they must match
    rows = fetch_klines(start, get)
    fresh = [[int(r[0]), int(r[6]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in rows if int(r[6]) < now_ms]
    by = {b[0]: b for b in old}
    for b in fresh:
        if b[0] in by and by[b[0]][:6] != b[:6]:                                      # volume may be restated; prices may not
            raise Integrity(f"stored bar {day(b[0])} differs from the source now: {by[b[0]][:6]} vs {b[:6]}")
    bars = old + [b for b in fresh if b[0] not in by]
    bars.sort(key=lambda b: b[0])
    validate(bars)
    doc = {"schema": "quanty.btc_daily.v1", "source": SOURCE, "fields": ["open_time", "close_time", "open", "high", "low", "close", "volume"],
           "fetched_at": iso(now_ms), "count": len(bars), "first": day(bars[0][0]), "last": day(bars[-1][0]),
           "bars_sha256": bars_sha(bars), "bars": bars}
    with open(path + ".tmp", "w") as f:
        json.dump(doc, f, separators=(",", ":"))
        f.write("\n")
    os.replace(path + ".tmp", path)
    return doc, len(bars) - len(old)


# ---- labeller -------------------------------------------------------------------------------------
def label_days(bars, params=PARAMS):
    """-> list (one per bar) of {day, close_time, close, sma_fast, sma_slow, raw, regime, vol, vol_tag}: causal, left to right."""
    p = params
    closes = [b[5] for b in bars]
    logret = [None] + [math.log(closes[j] / closes[j - 1]) for j in range(1, len(closes))]
    out, vols = [], []
    regime, pending, pending_n = None, None, 0
    s_fast = s_slow = 0.0
    for i, b in enumerate(bars):
        s_fast += closes[i] - (closes[i - p["sma_fast"]] if i >= p["sma_fast"] else 0)
        s_slow += closes[i] - (closes[i - p["sma_slow"]] if i >= p["sma_slow"] else 0)
        fast = s_fast / p["sma_fast"] if i + 1 >= p["sma_fast"] else None
        slow = s_slow / p["sma_slow"] if i + 1 >= p["sma_slow"] else None
        raw = None
        if slow is not None:
            c = closes[i]
            raw = "bull" if c > slow and fast > slow else "bear" if c < slow and fast < slow else "chop"
        if raw is not None:
            if raw != regime:                               # the first regime also needs CONFIRM consecutive days
                pending_n = pending_n + 1 if raw == pending else 1
                pending = raw
                if pending_n >= p["confirm"]:
                    regime, pending, pending_n = raw, None, 0
            else:
                pending, pending_n = None, 0
        vol = None
        if i >= p["vol_window"]:
            rets = logret[i - p["vol_window"] + 1:i + 1]
            mu = math.fsum(rets) / len(rets)
            vol = math.sqrt(math.fsum((x - mu) ** 2 for x in rets) / len(rets)) * math.sqrt(365)     # population sd, annualized
        vols.append(vol)
        prior = [v for v in vols[max(0, i - p["vol_lookback"]):i] if v is not None]
        vol_tag = None
        if vol is not None and len(prior) >= p["vol_lookback"] // 2:
            vol_tag = "high" if vol > p["vol_mult"] * statistics.median(prior) else "normal"
        out.append({"day": day(b[0]), "close_time": b[1], "close": closes[i], "sma_fast": fast, "sma_slow": slow,
                    "raw": raw, "regime": regime, "vol": vol, "vol_tag": vol_tag})
    return out


def label_at(labels, t_ms, closes=None):
    """The label of the last bar whose close time is at or before t (never a bar still open at t). None when t is
    before the first bar or the data does not reach t (the bar that closed before t is missing: no stale label)."""
    closes = closes or [l["close_time"] for l in labels]
    i = bisect.bisect_right(closes, t_ms) - 1
    if i < 0 or t_ms - closes[i] >= DAY_MS:
        return None
    return labels[i]


# ---- validation -----------------------------------------------------------------------------------
def runs(labels):
    out, cur = [], None
    for l in labels:
        if l["regime"] is None:
            continue
        if cur and cur["regime"] == l["regime"]:
            cur["end"], cur["days"] = l["day"], cur["days"] + 1
        else:
            cur = {"regime": l["regime"], "start": l["day"], "end": l["day"], "days": 1}
            out.append(cur)
    return out


def transitions(labels):
    m = {a: {b: 0 for b in REGIMES} for a in REGIMES}
    seq = [l["regime"] for l in labels if l["regime"]]
    for a, b in zip(seq, seq[1:]):
        m[a][b] += 1
    probs = {a: {b: (m[a][b] / sum(m[a].values()) if sum(m[a].values()) else None) for b in REGIMES} for a in REGIMES}
    return {"counts": m, "probabilities": probs}


def stability(bars, base, call_times):
    out = []
    base_map = {l["day"]: l["regime"] for l in base if l["regime"]}
    base_calls = [label_at(base, t) for t in call_times]
    for k, values in GRID.items():
        for v in values:
            p = dict(PARAMS, **{k: v})
            alt = label_days(bars, p)
            alt_map = {l["day"]: l["regime"] for l in alt if l["regime"]}
            common = [d for d in base_map if d in alt_map and d >= "2019-01-01"]
            same = sum(base_map[d] == alt_map[d] for d in common)
            alt_calls = [label_at(alt, t) for t in call_times]
            same_calls = sum((a or {}).get("regime") == (b or {}).get("regime") for a, b in zip(base_calls, alt_calls))
            out.append({"param": k, "value": v, "base": PARAMS[k], "days_compared": len(common), "days_same": same,
                        "days_same_share": round(same / len(common), 4), "calls_same": same_calls, "calls": len(call_times)})
    return out


def degradation(labels):
    """Lag at each confirmed flip between bull and bear (through chop or directly): how far price had already moved
    from the extreme of the regime it left, and whipsaws (a switch undone within 30 days)."""
    rs = runs(labels)
    by_day = {l["day"]: l for l in labels}
    flips = []
    for a, b in zip(rs, rs[1:]):
        seg = [by_day[d]["close"] for d in by_day if a["start"] <= d <= a["end"]]
        if not seg:
            continue
        flip_close = by_day[b["start"]]["close"]
        if a["regime"] == "bull":
            ext = max(seg)
            moved = flip_close / ext - 1
            kind = "left bull"
        elif a["regime"] == "bear":
            ext = min(seg)
            moved = flip_close / ext - 1
            kind = "left bear"
        else:
            continue
        ext_day = next(d for d in sorted(by_day) if a["start"] <= d <= a["end"] and by_day[d]["close"] == ext)
        lag = (dt.date.fromisoformat(b["start"]) - dt.date.fromisoformat(ext_day)).days
        flips.append({"kind": kind, "to": b["regime"], "extreme_day": ext_day, "extreme_close": ext, "flip_day": b["start"],
                      "flip_close": flip_close, "days_after_extreme": lag, "move_since_extreme": round(moved, 4)})
    whips = [{"regime": b["regime"], "start": b["start"], "days": b["days"], "between": a["regime"]}
             for a, b, c in zip(rs, rs[1:], rs[2:]) if b["days"] <= 30 and a["regime"] == c["regime"]]
    return {"flips": flips, "whipsaws": whips, "switches": len(rs) - 1,
            "switches_per_year": round((len(rs) - 1) / max(1, len([l for l in labels if l["regime"]]) / 365.25), 2)}


# ---- per-regime results -------------------------------------------------------------------------
def call_rows(bundle, labels):
    rows, closes = [], [l["close_time"] for l in labels]
    for a in bundle["assets"]:
        for p in a["posts"]:
            t = parse(p["post"]["posted_at"])
            lab = label_at(labels, t, closes)
            rows.append({"author": p["post"]["author"], "asset": a["name"], "post_id": p["post"]["id"], "posted_at": p["post"]["posted_at"],
                         "regime": lab["regime"] if lab else None, "vol_tag": lab["vol_tag"] if lab else None, "bar_day": lab["day"] if lab else None,
                         "bar_close_time": iso(lab["close_time"]) if lab else None, "crypto": a["source"] in CRYPTO_SOURCES, "_p": p})
    return rows


def _cell(sub):
    if not sub:
        return None
    rc = rate.rate_caller(sub)                              # the same rules as the main score, shrinkage toward 50 included
    return {"calls": rc["calls_total"], "scored": rc["scored"], "hit_rate": rc["hit_rate"], "avg_result": rc["avg_result"],
            "score": rc["score"], "display": rate.display(rc["score"]), "label": rc["label"], "weight": rc["weight"]}


def per_vol(rows):
    """All callers and each caller split by the volatility tag at the call (normal / high)."""
    out = collections.OrderedDict()
    for who in sorted({r["author"] for r in rows}, key=str.lower) + ["all callers"]:
        mine = [r for r in rows if who == "all callers" or r["author"] == who]
        out[who] = {v: _cell([(r["asset"], r["_p"]) for r in mine if r["regime"] and r["vol_tag"] == v]) for v in ("normal", "high")}
    return out


def per_regime(rows):
    out = collections.OrderedDict()
    authors = sorted({r["author"] for r in rows}, key=str.lower)
    for who in authors + ["all callers"]:
        mine = [r for r in rows if who == "all callers" or r["author"] == who]
        out[who] = {}
        for reg in REGIMES:
            out[who][reg] = _cell([(r["asset"], r["_p"]) for r in mine if r["regime"] == reg])
        out[who]["unknown"] = _cell([(r["asset"], r["_p"]) for r in mine if r["regime"] is None])
    return out


def rule_text(p=PARAMS):
    return (f"bull: close > SMA{p['sma_slow']} and SMA{p['sma_fast']} > SMA{p['sma_slow']}; bear: close < SMA{p['sma_slow']} and SMA{p['sma_fast']} < SMA{p['sma_slow']}; "
            f"chop: otherwise; a regime (the first one included) needs the same raw state on {p['confirm']} consecutive days; "
            f"vol high when {p['vol_window']}d realized vol (pstdev of log returns x sqrt 365) > {p['vol_mult']}x the median of the previous "
            f"{p['vol_lookback']} days' vols (no tag until {p['vol_lookback'] // 2} of them exist); "
            f"a call takes the label of the last bar closed at or before its time, none when the data does not reach it")


def forward(labels, horizon=30, start="2019-01-01"):
    """Does the label mean anything? BTC's own next-30-day return by the label on the day (evaluation only: it reads
    the future on purpose and never feeds a label)."""
    out = {}
    for reg in REGIMES:
        r = [labels[i + horizon]["close"] / l["close"] - 1 for i, l in enumerate(labels[:-horizon]) if l["regime"] == reg and l["day"] >= start]
        out[reg] = {"days": len(r), "mean": round(statistics.mean(r), 4) if r else None, "median": round(statistics.median(r), 4) if r else None,
                    "share_up": round(sum(x > 0 for x in r) / len(r), 4) if r else None}
    return {"horizon_days": horizon, "since": start, "by_regime": out}


def sides(rows):
    """All callers: longs and shorts per regime (count, scored, wins) — is a caller long into a bear market?"""
    out = {}
    for reg in REGIMES + (None,):
        d = {}
        for side, name in ((1, "long"), (-1, "short")):
            sub = [r for r in rows if r["regime"] == reg and r["_p"].get("side") == side]
            res = [rate.result(r["_p"]) for r in sub if r["_p"].get("entry")]
            res = [x for x in res if x is not None]
            d[name] = {"calls": len(sub), "scored": len(res), "wins": sum(x > 0 for x in res)}
        out[reg or "unknown"] = d
    return out


def compute(bundle, charts_sha, data):
    """The whole regimes document from the stored bars and the bundle (pure: same inputs, same bytes)."""
    bars = validate(data["bars"])
    if bars_sha(bars) != data["bars_sha256"]:
        raise Integrity("data/btc_daily.json: bars do not match their sha256")
    labels = label_days(bars)
    rows = call_rows(bundle, labels)
    times = [parse(r["posted_at"]) for r in rows]
    doc = {"schema": VERSION, "params": PARAMS, "grid": GRID, "rule": rule_text(), "source": data["source"],
           "bars": {"count": len(bars), "first": day(bars[0][0]), "last": day(bars[-1][0]), "sha256": data["bars_sha256"]},
           "charts_sha256": charts_sha, "prices_as_of": bundle.get("prices_as_of"),
           "current": {k: labels[-1][k] for k in ("day", "regime", "vol_tag", "close", "sma_fast", "sma_slow", "vol")},
           "runs": runs(labels), "transitions": transitions(labels), "forward": forward(labels),
           "stability": stability(bars, labels, times), "degradation": degradation(labels),
           "per_regime": per_regime(rows), "per_vol": per_vol(rows), "sides": sides(rows),
           "calls": [{k: v for k, v in r.items() if k != "_p"} for r in sorted(rows, key=lambda r: (r["posted_at"], r["post_id"], r["asset"]))],
           "unknown_calls": sum(1 for r in rows if r["regime"] is None),
           "non_crypto_calls": sum(1 for r in rows if not r["crypto"])}
    return doc, labels


def write(web, doc, labels):
    with open(os.path.join(web, "data", "regimes.json"), "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    with open(os.path.join(web, "regimes.html"), "w") as f:
        f.write(page(doc, labels))


def check_no_lookahead(bars, rows):
    """For every call: label the series cut at the call (only bars closed at or before it) and compare with the label
    the full series gives. -> [(row, full label, cut label)]; equal for every call when nothing reads the future."""
    out = []
    labels = label_days(bars)
    closes = [l["close_time"] for l in labels]
    for r in rows:
        t = parse(r["posted_at"])
        cut = [b for b in bars if b[1] <= t]
        full, alone = label_at(labels, t, closes), (label_days(cut)[-1] if cut else None)
        pick = lambda l: l and (l["day"], l["regime"], l["vol_tag"])
        out.append((r, pick(full), pick(alone) if alone and t - alone["close_time"] < DAY_MS else None))
    return out


def build_web(web):
    """Called by tools/prerender.py on every bundle build (data/btc_daily.json next to web/): None when there is no BTC data."""
    path = os.path.join(os.path.dirname(os.path.abspath(web)), "data", "btc_daily.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    with open(os.path.join(web, "data", "charts.json"), "rb") as f:
        raw_bundle = f.read()
    doc, labels = compute(json.loads(raw_bundle), hashlib.sha256(raw_bundle).hexdigest(), data)
    write(web, doc, labels)
    return doc


def build(root=HERE):
    return build_web(os.path.join(root, "web"))


# ---- page -----------------------------------------------------------------------------------------
COLORS = {"bull": "#2e9d5b", "chop": "#c9a227", "bear": "#c0392b"}


def timeline_svg(labels, start="2019-01-01", w=1000, h=260):
    pts = [l for l in labels if l["day"] >= start and l["regime"]]
    if not pts:
        return ""
    lo, hi = math.log(min(l["close"] for l in pts)), math.log(max(l["close"] for l in pts))
    n = len(pts)
    x = lambda i: 40 + (w - 50) * i / max(1, n - 1)
    y = lambda c: 10 + (h - 40) * (1 - (math.log(c) - lo) / (hi - lo))
    bands, i = [], 0
    while i < n:
        j = i
        while j + 1 < n and pts[j + 1]["regime"] == pts[i]["regime"]:
            j += 1
        bands.append(f'<rect x="{x(i):.1f}" y="10" width="{max(1.0, x(j) - x(i)):.1f}" height="{h - 40}" fill="{COLORS[pts[i]["regime"]]}" fill-opacity="0.18"/>')
        i = j + 1
    line = " ".join(f"{x(i):.1f},{y(l['close']):.1f}" for i, l in enumerate(pts))
    years = "".join(f'<text x="{x(i):.1f}" y="{h - 12}" font-size="11" fill="currentColor">{l["day"][:4]}</text>'
                    for i, l in enumerate(pts) if l["day"].endswith("-01-01"))
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="BTC daily close (log scale) with the regime as background bands">'
            + "".join(bands) + f'<polyline points="{line}" fill="none" stroke="currentColor" stroke-width="1.2"/>' + years + "</svg>")


def pct(x):
    return "–" if x is None else f"{x * 100:+.1f}%"


def hit(x):
    return "–" if x is None else f"{x * 100:.0f}%"


def cell(c, key):
    """One per-regime result: the shrunk score, then hit rate, average result and the sample (small samples marked)."""
    if not c:
        return f'<td data-regime="{e(key)}" data-scored="0">–</td>'
    mark = "*" if c["label"] == "small sample" else "†" if c["label"] == "limited sample" else ""
    return (f'<td data-regime="{e(key)}" data-scored="{c["scored"]}" data-label="{e(c["label"] or "")}"><strong>{e(c["display"])}</strong>{mark} '
            f'<span class="muted small">hit {hit(c["hit_rate"])} · avg {pct(c["avg_result"])} · n={c["scored"]} of {c["calls"]}</span></td>')


def caller_section(name, d):
    """Step 28 caller-page block: this caller's results by the BTC regime at each call (score-neutral)."""
    r = (d or {}).get("per_regime", {}).get(name)
    if not r:
        return ""
    mine = [c for c in d["calls"] if c["author"] == name]
    trs = "".join(f'<tr data-regime-row="{k}"><td>{k}</td>{cell(r.get(k), k)}</tr>' for k in REGIMES + ("unknown",) if r.get(k) or k != "unknown")
    lst = "".join(f'<tr data-post-id="{e(c["post_id"])}" data-asset="{e(c["asset"])}" data-regime="{e(c["regime"] or "unknown")}"><td>{e(c["posted_at"][:16].replace("T", " "))} UTC</td>'
                  f'<td>{e(c["asset"])}</td><td><strong>{e(c["regime"] or "unknown")}</strong>{" · high vol" if c["vol_tag"] == "high" else ""}</td>'
                  f'<td class="why">BTC bar {e(c["bar_day"] or "–")}, closed {e((c["bar_close_time"] or "–").replace("T", " "))}</td></tr>' for c in mine)
    return (f'<section class="panel recap regimes" data-field="by_regime"><h2>By market regime</h2>'
            f'<p class="notes">Score-neutral: the score above does not change. The same rules (hit rate, return quality, clarity, shrinkage toward 50) on only the calls made '
            f'in each BTC regime. * under 10 scored calls (small sample), † under 30 (limited sample). Regime at each call from the last BTC daily bar closed before it: '
            f'<a href="regimes.html">how regimes are labelled</a> · <a href="data/regimes.json">data/regimes.json</a></p>'
            f'<div class="table-wrap"><table class="calls"><thead><tr><th>Regime</th><th>Score in regime</th></tr></thead><tbody>{trs}</tbody></table></div>'
            f'<h3>Each call\'s regime</h3><div class="table-wrap"><table class="calls" data-field="call_regimes"><thead><tr><th>Posted</th><th>Asset</th><th>Regime</th><th>Label from</th></tr></thead><tbody>{lst}</tbody></table></div></section>')


def page(d, labels):
    reg_cells = lambda r, keys=REGIMES: "".join(cell(c, k) for k, c in ((k, r[k]) for k in keys))
    who_td = lambda who: (f'<td><a href="caller-{e(rate.caller_slug(who))}.html">@{e(who)}</a></td>' if who != "all callers" else "<td><strong>all callers</strong></td>")
    rows = "".join(f'<tr data-caller="{e(who)}">{who_td(who)}{reg_cells(r)}</tr>' for who, r in d["per_regime"].items())
    vrows = "".join(f'<tr data-caller="{e(who)}">{who_td(who)}{reg_cells(r, ("normal", "high"))}</tr>' for who, r in d["per_vol"].items())
    srows = "".join(f'<tr><td>{e(reg)}</td>' + "".join(f'<td>{v["calls"]} <span class="muted small">({v["wins"]} of {v["scored"]} won)</span></td>' for v in (x["long"], x["short"]))
                    + "</tr>" for reg, x in d["sides"].items() if x["long"]["calls"] or x["short"]["calls"])
    fw = d["forward"]
    frows = "".join(f'<tr><td>{e(reg)}</td><td>{x["days"]}</td><td>{pct(x["mean"])}</td><td>{pct(x["median"])}</td><td>{hit(x["share_up"])}</td></tr>' for reg, x in fw["by_regime"].items())
    by_reg = collections.Counter(c["regime"] for c in d["calls"])
    fb = fw["by_regime"]
    fw_note = (": bear days were followed by a higher median return than bull days" if (fb["bear"]["median"] or 0) > (fb["bull"]["median"] or 0) else "")
    bear_authors = sorted({c["author"] for c in d["calls"] if c["regime"] == "bear"})
    tm = d["transitions"]
    tm_rows = "".join(f"<tr><td>{a}</td>" + "".join(f'<td>{tm["counts"][a][b]} <span class="muted small">({(tm["probabilities"][a][b] or 0) * 100:.1f}%)</span></td>' for b in REGIMES) + "</tr>"
                      for a in REGIMES)
    dur = collections.defaultdict(list)
    for r in d["runs"]:
        dur[r["regime"]].append(r["days"])
    dur_txt = " · ".join(f"{reg}: {len(v)} runs, mean {statistics.mean(v):.0f} days, median {statistics.median(v):.0f}" for reg, v in dur.items())
    stab = "".join(f'<tr><td>{e(s["param"])} {e(s["base"])} → {e(s["value"])}</td><td>{s["days_same_share"] * 100:.1f}% of {s["days_compared"]} days</td>'
                   f'<td>{s["calls_same"]} of {s["calls"]} calls</td></tr>' for s in d["stability"])
    flips = "".join(f'<li>{e(f["kind"])} → {e(f["to"])} on {e(f["flip_day"])}: {f["days_after_extreme"]} days after the {"high" if f["kind"] == "left bull" else "low"} '
                    f'of {f["extreme_close"]:,.0f} ({e(f["extreme_day"])}); price had already moved {pct(f["move_since_extreme"])}</li>' for f in d["degradation"]["flips"][-8:])
    whips = "".join(f'<li>{e(w["regime"])} for {w["days"]} days from {e(w["start"])}, between {e(w["between"])} runs</li>' for w in d["degradation"]["whipsaws"][-8:]) or "<li>none</li>"
    calls = "".join(f'<tr><td>{e(c["posted_at"][:16].replace("T", " "))}</td><td>@{e(c["author"])}</td><td>{e(c["asset"])}{"" if c["crypto"] else " <span class=muted>(not crypto)</span>"}</td>'
                    f'<td data-regime="{e(c["regime"] or "unknown")}">{e(c["regime"] or "unknown")}{" · high vol" if c["vol_tag"] == "high" else ""}</td><td class="muted small">bar {e(c["bar_day"])} closed {e(c["bar_close_time"])}</td></tr>'
                    for c in d["calls"])
    cur = d["current"]
    p = d["params"]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; manifest-src 'none'; media-src 'none'; font-src 'none'; upgrade-insecure-requests">
<meta name="referrer" content="no-referrer">
<script src="assets/frame-guard.js"></script>
<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Regimes · Quanty Quants</title>
<meta name="description" content="Every call labelled with the BTC market regime at its own time, and each caller's results per regime.">
<link rel="stylesheet" href="assets/board.css">
<link rel="stylesheet" href="assets/episode.css">
</head>
<body>
<main>
  <header class="top">
    <div>
      <h1>Quanty Quants</h1>
      <p class="sub">Who is right in which market: every call labelled with the BTC regime at its own time</p>
    </div>
    <nav class="nav" aria-label="Views">
      <a href="./">Leaderboard</a>
      <a href="chart.html">Chart</a>
      <a href="episodes.html">Episodes</a>
      <a href="coins.html">Coins</a>
      <a href="agreement.html">Agreement</a>
      <a href="regimes.html" aria-current="page">Regimes</a>
    </nav>
  </header>
  <section class="ep-head panel" data-field="regime-now">
    <h2>BTC now: {e(cur['regime'] or 'unknown')}{' · high vol' if cur['vol_tag'] == 'high' else ''} <span class="muted small">(daily close {cur['close']:,.0f} on {e(cur['day'])}, SMA{p['sma_fast']} {cur['sma_fast']:,.0f}, SMA{p['sma_slow']} {cur['sma_slow']:,.0f})</span></h2>
    <p><strong>Rule</strong> ({e(d['schema'])}, fixed parameters): <strong>bull</strong> when the daily close is above its {p['sma_slow']}-day average and the {p['sma_fast']}-day average is above the {p['sma_slow']}-day; <strong>bear</strong> when both are below; <strong>chop</strong> when they disagree. A switch needs the new state on {p['confirm']} consecutive days. <strong>High vol</strong> when the {p['vol_window']}-day realized volatility is above {p['vol_mult']}× its median over the previous {p['vol_lookback']} days.
    <strong>No look-ahead:</strong> each day's label uses bars up to that day only, and a call takes the label of the last daily bar that had <em>closed</em> before it was posted.</p>
    <p class="notes">Score-neutral: the main caller score does not change. The per-regime numbers use the same rules (hit rate, return quality, clarity, shrinkage n/(n+10) toward 50) on the calls made in each regime, so most cells are small samples. The regime is the crypto market's (BTC) for every call, including stocks and commodities ({d['non_crypto_calls']} calls are not crypto: read their cells with that in mind).</p>
    <p class="muted small">Prices as of {e(d['prices_as_of'] or '–')} · charts.json sha256 {e(d['charts_sha256'][:16])}… · Binance BTCUSDT daily, {d['bars']['count']} bars {e(d['bars']['first'])} → {e(d['bars']['last'])}, sha256 {e(d['bars']['sha256'][:16])}… · data: <a href="data/regimes.json">data/regimes.json</a></p>
  </section>
  <div class="panel">{timeline_svg(labels)}<p class="muted small">BTC daily close, log scale, from 2019. Background: green bull, yellow chop, red bear.</p></div>
  <h2 class="sec">Callers by regime</h2>
  <p class="notes">Each cell: the score on only that regime's calls (same formula as the main score, shrunk toward 50), hit rate, average result, n scored of the calls made then. <strong>*</strong> under 10 scored calls (small sample), <strong>†</strong> under 30 (limited sample): most cells are small, read them as descriptive, not as skill. Calls by regime: {", ".join(f"{k} {by_reg[k]}" for k in REGIMES)}{f", unknown {by_reg[None]}" if by_reg[None] else ""}.</p>
  <div class="panel tablewrap"><table class="coins" data-field="per_regime"><thead><tr><th>Caller</th><th>Bull</th><th>Chop</th><th>Bear</th></tr></thead><tbody>{rows}</tbody></table></div>
  <h3 class="sec">Long and short calls by regime (all callers)</h3>
  <div class="panel tablewrap"><table class="coins" data-field="sides"><thead><tr><th>Regime</th><th>Long calls</th><th>Short calls</th></tr></thead><tbody>{srows}</tbody></table></div>
  <h3 class="sec">By volatility at the call</h3>
  <div class="panel tablewrap"><table class="coins" data-field="per_vol"><thead><tr><th>Caller</th><th>Normal vol</th><th>High vol</th></tr></thead><tbody>{vrows}</tbody></table></div>
  <h2 class="sec">How the labeller behaves</h2>
  <p class="notes">Daily transitions (row = from, column = to). {e(dur_txt)}. {d['degradation']['switches']} switches since the first label, {d['degradation']['switches_per_year']} a year.</p>
  <div class="panel tablewrap"><table class="coins"><thead><tr><th>from \\ to</th><th>bull</th><th>chop</th><th>bear</th></tr></thead><tbody>{tm_rows}</tbody></table></div>
  <h3 class="sec">Stability under small parameter changes</h3>
  <div class="panel tablewrap"><table class="coins"><thead><tr><th>Change</th><th>Daily labels unchanged (since 2019)</th><th>Call labels unchanged</th></tr></thead><tbody>{stab}</tbody></table></div>
  <h3 class="sec">Does the label mean anything for BTC itself?</h3>
  <p class="notes">BTC's return over the next {fw['horizon_days']} days by the label on the day, since {e(fw['since'])} (evaluation only: this reads the future on purpose and never feeds a label).
  The label describes the trend so far; it does <strong>not</strong> forecast the next month{fw_note}. Use it to say which market a call was made in, not to time BTC.</p>
  <div class="panel tablewrap"><table class="coins" data-field="forward"><thead><tr><th>Label</th><th>Days</th><th>Mean next {fw['horizon_days']}d</th><th>Median</th><th>Share up</th></tr></thead><tbody>{frows}</tbody></table></div>
  <h3 class="sec">Where it degrades</h3>
  <ul class="plain">
   <li><strong>Lag at turns.</strong> Moving averages lag: the regime leaves bull or bear only after price has moved away from the top or bottom (recent flips below). A call made in the first weeks after a top is still labelled bull.</li>
   <li><strong>Whipsaws in sideways markets.</strong> {len(d['degradation']['whipsaws'])} runs of 30 days or less between two runs of the same regime (2020 and Aug-Oct 2024 most of all); calls made then sit near the boundary, and the stability table shows they are the ones that move when a parameter moves.</li>
   <li><strong>Calls are not spread over regimes.</strong> {by_reg['bull']} of {len(d['calls'])} calls were made in bull; every bear-regime call is by {e(", ".join("@" + a for a in bear_authors)) or "nobody"}, so the bear column is one caller's record, not a comparison.</li>
   <li><strong>One market for every asset.</strong> The regime is BTC's for every call, including the {d['non_crypto_calls']} stock and commodity calls, whose own market can differ.</li>
   <li><strong>Data.</strong> Binance's 2018-02-08 daily bar is a truncated outage bar, so the series starts on {e(d['bars']['first'])}; the first label needs {p['sma_slow']} + {p['confirm'] - 1} days of warm-up ({e(d['runs'][0]['start'])}). A stored bar that changes, a gap, a duplicate or a stale tail is refused, and a call the data does not reach is labelled unknown, never with an old label.</li>
  </ul>
  <p class="notes">Recent flips (days after the extreme, move already made):</p>
  <ul class="plain">{flips}</ul>
  <p class="notes">Whipsaws (a regime lasting 30 days or less between two runs of the same regime):</p>
  <ul class="plain">{whips}</ul>
  <h2 class="sec">Every call and its regime</h2>
  <div class="panel tablewrap"><table class="coins"><thead><tr><th>Posted (UTC)</th><th>Caller</th><th>Asset</th><th>Regime</th><th>Label from</th></tr></thead><tbody>{calls}</tbody></table></div>
  <p class="nfa" id="nfa" data-field="nfa"><strong>Not financial advice.</strong> The calls are public posts by their authors, tracked and priced for analysis. Nothing here is a recommendation to buy, sell or hold anything.</p>
</main>
</body>
</html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["fetch", "build", "check"])
    a = ap.parse_args(argv)
    try:
        if a.cmd == "fetch":
            doc, added = fetch()
            print(f"btc daily: {doc['count']} bars {doc['first']} -> {doc['last']} ({added} new), sha256 {doc['bars_sha256']}")
        elif a.cmd == "check":
            data = load(DATA)
            bars = validate(data["bars"])
            bundle = load(os.path.join(HERE, "web", "data", "charts.json"))
            res = check_no_lookahead(bars, sorted(call_rows(bundle, label_days(bars)), key=lambda r: (r["posted_at"], r["post_id"], r["asset"])))
            bad = 0
            for r, full, cut in res:
                ok = full == cut
                bad += not ok
                print(f"{'ok  ' if ok else 'DIFF'} {r['posted_at']} @{r['author']} {r['asset']}: full series {full[1] if full else None}"
                      f"{'/' + full[2] if full and full[2] else ''} = cut at the call {cut[1] if cut else None}"
                      f"{'/' + cut[2] if cut and cut[2] else ''} (last bar closed {cut[0] if cut else None})")
            print(f"no look-ahead: {len(res) - bad} of {len(res)} calls get the same label from the series cut at the call")
            return 1 if bad else 0
        else:
            d = build()
            print(f"regimes: BTC now {d['current']['regime']} ({d['current']['day']}); {len(d['calls'])} calls labelled; "
                  f"{d['degradation']['switches']} switches; data sha {d['bars']['sha256'][:12]}")
    except Integrity as ex:
        print(f"REFUSED  {ex}")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
