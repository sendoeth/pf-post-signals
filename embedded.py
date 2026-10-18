"""Read the price history embedded in ai_semi_dashboard.html (the old pipeline's only data source)."""
import os
import re

DASHBOARD = os.environ.get("PF_DASHBOARD", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources", "ai_semi_dashboard.snapshot.html"))


def _array(block, key):
    m = re.search(r"\b" + key + r":\[([^\]]*)\]", block)
    return [float(x) for x in m.group(1).split(",")] if m else None


def _object_block(src, name):
    i = src.find(f"const {name}={{")
    return src[i:src.find("};", i)]


def load(path=DASHBOARD):
    """Return (dates, {symbol: [closes]}) exactly as embedded in the dashboard."""
    src = open(path, encoding="utf8", errors="replace").read()
    dates = re.findall(r'"(\d{4}-\d{2}-\d{2})"', re.search(r"const BT_DATES=\[(.*?)\]", src, re.S).group(1))
    series = {}
    hist = _object_block(src, "HIST")
    for k in re.findall(r"\b(\w+):\[", hist):
        series[k] = _array(hist, k)
    equity = _object_block(src, "CORR_EQUITY")
    for k in ("AMD", "MRVL"):
        series[k] = _array(equity, k)
    crypto = _object_block(src, "CORR_CRYPTO")
    for k in re.findall(r"\b(\w+):\[", crypto):
        series[k] = _array(crypto, k)
    return dates, series
