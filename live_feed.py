#!/usr/bin/env python3
"""Daily live feed for the regime pipeline: fresh prices -> unmodified classifier -> duration gate.

Replaces the dashboard's embedded price history (frozen at 2026-03-06) with a daily rebuild:

1. fetch the pipeline's 9 equity + 4 crypto inputs (fetch_prices.fetch_all, validated in step 1);
2. classify every completed session not yet in live/raw_regimes.json by loading a data-swapped copy
   of the ORIGINAL dashboard (trailing 251 sessions, no look-ahead) - cached per session, so
   re-runs never recount a session;
3. apply the minimum-duration gate (gate.apply_gate, a pure function of the raw sequence);
4. write live/ai_semi_dashboard.live.html in which classifyRegime() returns the gated regime for
   every consumer (dashboard queue, signal_api) and returns STALE_DATA - which withholds - once
   the market data is older than MAX_AGE_DAYS;
5. verify the rendered page reports the gated regime, then publish atomically with live/status.json.

Exit 0 = published, 1 = not published (previous live file left in place; it withholds once stale).
"""
import datetime as dt
import json
import os
import subprocess
import sys

import build_asof
import embedded
import fetch_prices
import gate

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(HERE, "live")
WORK = os.path.join(LIVE, "work")
RAW_CACHE = os.path.join(LIVE, "raw_regimes.json")
LIVE_HTML = os.path.join(LIVE, "ai_semi_dashboard.live.html")
STATUS = os.path.join(LIVE, "status.json")
MIN_DAYS = 2
MAX_AGE_DAYS = 4          # covers a weekend plus one holiday
US_CLOSE_DONE_UTC = 21    # a session counts as complete after 21:00 UTC
NODE_ENV = {**os.environ, "LD_LIBRARY_PATH": "/home/postfiat/chromium-libs/lib"}


def log(msg):
    print(f"[{dt.datetime.now(dt.UTC):%Y-%m-%dT%H:%M:%SZ}] {msg}", flush=True)


def classify(files):
    out = subprocess.run(["node", os.path.join(HERE, "run_asof.js"), *files], capture_output=True,
                         text=True, env=NODE_ENV, timeout=60 * len(files) + 120)
    if out.returncode != 0:
        raise RuntimeError(f"classifier failed: {out.stderr[-500:]}")
    return json.loads(out.stdout)


def gate_patch(src, gate_info):
    """Rename the original classifier and add a gated wrapper. Function declarations are hoisted,
    so every caller - including code that runs before this point - gets the gated result."""
    if src.count("function classifyRegime(){") != 1:
        raise RuntimeError("classifyRegime() not found exactly once")
    wrapper = (
        "const PF_GATE=" + json.dumps(gate_info) + ";\n"
        "function classifyRegime(){\n"
        "  const r=classifyRegimeRaw();\n"
        "  const ageDays=(Date.now()-Date.parse(PF_GATE.dataAsOf+'T21:00:00Z'))/86400000;\n"
        "  const base={...r,rawRegime:r.regime.id,dataAsOf:PF_GATE.dataAsOf,gateMinDays:PF_GATE.minDays};\n"
        "  if(!(ageDays<=PF_GATE.maxAgeDays)) return {...base,stale:true,gated:true,"
        "regime:{id:'STALE_DATA',label:'Stale market data - withholding',weights:BT_WEIGHTS.base}};\n"
        "  const eff=PF_GATE.effective==='NEUTRAL'?EXE_NEUTRAL:PB_CATS.find(c=>c.id===PF_GATE.effective);\n"
        "  if(!eff) return {...base,gated:true,regime:{id:'UNKNOWN_GATED',label:'Unknown gated regime - withholding',weights:BT_WEIGHTS.base}};\n"
        "  return {...base,regime:eff,gated:eff.id!==r.regime.id,effectiveSince:PF_GATE.effectiveSince};\n"
        "}\n")
    return src.replace("function classifyRegime(){", wrapper + "function classifyRegimeRaw(){", 1)


def atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        f.write(text)
    os.replace(tmp, path)


def main():
    os.makedirs(WORK, exist_ok=True)
    now = dt.datetime.now(dt.UTC)
    prices = fetch_prices.fetch_all()
    # drop a session that is still trading (Yahoo serves the live price as today's bar)
    today = now.strftime("%Y-%m-%d")
    if now.hour < US_CLOSE_DONE_UTC:
        for s in fetch_prices.STOCKS:
            prices[s].pop(today, None)
    dates, ext, first_new = build_asof.extended_history(prices)
    latest = dates[-1]
    age = (now.date() - dt.date.fromisoformat(latest)).days
    if age > MAX_AGE_DAYS:
        log(f"NOT PUBLISHED: latest complete session {latest} is {age} days old")
        return 1

    cache = json.load(open(RAW_CACHE)) if os.path.exists(RAW_CACHE) else {}
    if not cache:  # seed from the validated counterfactual replay (same method, step 1)
        cache = {r["asof"]: r["regime"] for r in json.load(open(os.path.join(HERE, "data", "counterfactual_regimes.json")))}
    template = open(embedded.DASHBOARD, encoding="utf8").read()
    todo = [i for i in range(first_new, len(dates)) if dates[i] not in cache]
    if todo:
        files = []
        for i in todo:
            path = os.path.join(WORK, f"{dates[i]}.html")
            atomic_write(path, build_asof.render(template, dates, ext, i))
            files.append(path)
        for r in classify(files):
            cache[r["asof"]] = r["regime"]
        atomic_write(RAW_CACHE, json.dumps(cache, indent=0, sort_keys=True))
        log(f"classified {len(todo)} new session(s): " + ", ".join(f"{d}={cache[d]}" for d in (dates[i] for i in todo)))

    raw = [(d, cache[d]) for d in dates[first_new:] if d in cache]
    if not raw or raw[-1][0] != latest:
        log("NOT PUBLISHED: latest session missing from the raw sequence")
        return 1
    session, raw_regime, effective, since = gate.apply_gate(raw, MIN_DAYS)[-1]
    gate_info = {"effective": effective, "effectiveSince": since, "rawAtBuild": raw_regime, "dataAsOf": latest,
                 "minDays": MIN_DAYS, "maxAgeDays": MAX_AGE_DAYS, "gateVersion": gate.GATE_VERSION,
                 "builtAt": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    candidate = os.path.join(WORK, "candidate.html")
    atomic_write(candidate, gate_patch(build_asof.render(template, dates, ext, len(dates) - 1), gate_info))

    check = classify([candidate])[0]
    g = check.get("gate") or {}
    if check["lastDate"] != latest or g.get("effective") != effective or g.get("raw") != raw_regime or g.get("stale"):
        log(f"NOT PUBLISHED: verification mismatch {check}")
        return 1
    os.replace(candidate, LIVE_HTML)
    atomic_write(STATUS, json.dumps({**gate_info, "rawRegime": raw_regime, "sessions_classified": len(raw),
                                     "queue_regime_label": g.get("queueRegime"),
                                     "data_age_days_at_build": age, "stale": age > MAX_AGE_DAYS}, indent=1))
    log(f"PUBLISHED {latest}: raw={raw_regime} effective={effective} (since {since}, gate {MIN_DAYS}d)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
