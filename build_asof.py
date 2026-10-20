#!/usr/bin/env python3
"""Write one copy of the ORIGINAL dashboard per as-of trading day, data swapped only.

Each copy holds the trailing 251-trading-day window ending on the as-of day (the original
pipeline's window length), so the unmodified classifier sees exactly what it would have
seen that day: no look-ahead. Crypto closes use the previous UTC day, matching the
embedded history (verified 0.13-0.15% median diff vs 3.4% same-day).
"""
import datetime as dt
import json
import os
import re
import sys

import embedded

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "work", "asof")
WINDOW = 251
STOCKS = ["NVDA", "TSM", "AVGO", "ASML", "ASX", "SPY", "SMH", "AMD", "MRVL"]
CRYPTO = ["TAO", "RNDR", "AKT", "FET"]


def prev_day(d):
    return (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()


def extended_history(prices=None):
    """Embedded history + every later trading day with complete data."""
    dates, series = embedded.load()
    if prices is None:
        prices = json.load(open(os.path.join(HERE, "data", "prices.json")))
    last = dates[-1]
    new_days = sorted(d for d in prices["NVDA"] if d > last)
    ext_dates = list(dates)
    ext = {k: list(v) for k, v in series.items()}
    for d in new_days:
        row = {s: prices[s].get(d) for s in STOCKS}
        row.update({c: prices[c].get(prev_day(d)) for c in CRYPTO})
        if any(v is None for v in row.values()):
            print(f"skip {d}: missing {[k for k, v in row.items() if v is None]}", file=sys.stderr)
            continue
        ext_dates.append(d)
        for k, v in row.items():
            ext[k].append(v)
    return ext_dates, ext, len(dates)


def swap_array(block, key, values):
    fmt = ",".join(f"{v:g}" for v in values)
    new, n = re.subn(r"\b" + key + r":\[[^\]]*\]", f"{key}:[{fmt}]", block, count=1)
    if n != 1:
        raise ValueError(f"array {key} not found")
    return new


def swap_object(src, name, data):
    i = src.find(f"const {name}={{")
    j = src.find("};", i)
    block = src[i:j]
    for key, values in data.items():
        block = swap_array(block, key, values)
    return src[:i] + block + src[j:]


def render(template, dates, ext, end):
    lo = end - WINDOW + 1
    win = {k: v[lo:end + 1] for k, v in ext.items()}
    src = re.sub(r"const BT_DATES=\[.*?\]",
                 "const BT_DATES=[" + ",".join(f'"{d}"' for d in dates[lo:end + 1]) + "]",
                 template, count=1, flags=re.S)
    src = swap_object(src, "HIST", {k: win[k] for k in ["NVDA", "TSM", "AVGO", "ASML", "ASX", "SPY", "SMH"]})
    src = swap_object(src, "CORR_EQUITY", {k: win[k] for k in ["AMD", "MRVL"]})
    return swap_object(src, "CORR_CRYPTO", {k: win[k] for k in CRYPTO})


def main():
    template = open(embedded.DASHBOARD, encoding="utf8").read()
    dates, ext, first_new = extended_history()
    os.makedirs(OUT_DIR, exist_ok=True)
    index = []
    # include the last embedded day as a control: it must reproduce the frozen live state
    for end in range(first_new - 1, len(dates)):
        path = os.path.join(OUT_DIR, f"{dates[end]}.html")
        with open(path, "w", encoding="utf8") as f:
            f.write(render(template, dates, ext, end))
        index.append({"asof": dates[end], "file": path})
    json.dump(index, open(os.path.join(OUT_DIR, "index.json"), "w"), indent=0)
    json.dump({"dates": dates, "series": ext}, open(os.path.join(HERE, "data", "extended_history.json"), "w"))
    print(f"{len(index)} as-of dashboards, {dates[first_new - 1]} .. {dates[-1]}", file=sys.stderr)


if __name__ == "__main__":
    main()
