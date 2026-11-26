#!/usr/bin/env python3
"""Step 30: owner-set sector tags (data/sectors.json) and the sectors page (web/sectors.html, web/data/sectors.json).

usage:
  python3 tools/sectors.py check                                      validate data/sectors.json
  python3 tools/sectors.py list
  python3 tools/sectors.py add <id> <name...> [--proxy LABEL]          preview only
  python3 tools/sectors.py tag <ticker> <id> [source-url]              preview only
  python3 tools/sectors.py untag <ticker> <id>                         preview only
  ... add/tag/untag --confirm <token>                                  write, if the file is still the one previewed
  python3 tools/sectors.py build                                       web/data/sectors.json + web/sectors.html

A sector is a theme the owner names (semis, solar, metals, L1, memes) and the assets the owner puts in it, each with
the source the owner gives. Nothing is ever detected: every change is a preview first, and it is written only with the
token of that preview (sha256 of the file it was made from + the change), so a stale or edited preview cannot write.
A proxy (an ETF or index) is a label only: it is never priced. Score-neutral: sectors never read into or write a
record, a price or a rating; charts.json stays byte-identical (tests/test_sectors.py).
"""
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TOOLS)
SCHEMA = "quanty.sectors.v1"
WEB_SCHEMA = "quanty.sectors_page.v1"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
URL_RE = re.compile(r"^https://[^\s<>\"']{4,500}$")
MAX_NAME, MAX_PROXY = 40, 24
e = lambda s: html.escape(str(s), quote=True)


class SectorError(ValueError):
    """A refused sector file or change (shown to the owner as is)."""


def path(root=HERE):
    return os.path.join(root, "data", "sectors.json")


def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def known_assets(root=HERE):
    """Assets a sector may hold: every ticker in data/tickers.json and every asset name the records already use
    (metals, index stand-ins and HL xyz stocks are record assets, not coins)."""
    with open(os.path.join(root, "data", "tickers.json")) as f:
        out = set(json.load(f)["tickers"])
    cp = os.path.join(root, "web", "data", "charts.json")
    if os.path.exists(cp):
        with open(cp) as f:
            out |= {a["name"] for a in json.load(f)["assets"]}
    return out


def _no_dupe_keys(pairs):
    keys = [k for k, _ in pairs]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        raise SectorError(f"duplicate key(s) {', '.join(dupes)}")
    return dict(pairs)


def parse(text):
    try:
        return json.loads(text, object_pairs_hook=_no_dupe_keys)
    except json.JSONDecodeError as err:
        raise SectorError(f"not JSON: {err}") from None


def validate(doc, assets):
    """Refuse anything but the schema: ids, names, label-only proxies, known assets, https sources, no duplicates."""
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or set(doc) != {"schema", "sectors"}:
        raise SectorError(f"expected {{schema: {SCHEMA}, sectors: [...]}}")
    if not isinstance(doc["sectors"], list):
        raise SectorError("sectors must be a list")
    seen = set()
    for s in doc["sectors"]:
        if not isinstance(s, dict) or set(s) != {"id", "name", "proxy", "created_at", "members"}:
            raise SectorError(f"sector {s.get('id') if isinstance(s, dict) else s!r}: keys must be id, name, proxy, created_at, members")
        sid = s["id"]
        if not isinstance(sid, str) or not ID_RE.match(sid):
            raise SectorError(f"sector id {sid!r}: lowercase letters, digits and '-', at most 32")
        if sid in seen:
            raise SectorError(f"duplicate sector id {sid!r}")
        seen.add(sid)
        if not isinstance(s["name"], str) or not 0 < len(s["name"].strip()) <= MAX_NAME:
            raise SectorError(f"sector {sid}: name must be 1-{MAX_NAME} characters")
        if s["proxy"] is not None and (not isinstance(s["proxy"], str) or not re.fullmatch(r"[A-Za-z0-9:._-]{1,%d}" % MAX_PROXY, s["proxy"])):
            raise SectorError(f"sector {sid}: proxy must be a short label (an ETF or index name) or null; it is never priced")
        if not isinstance(s["members"], list):
            raise SectorError(f"sector {sid}: members must be a list")
        mine = set()
        for m in s["members"]:
            if not isinstance(m, dict) or set(m) != {"asset", "source", "added_at"}:
                raise SectorError(f"sector {sid}: each member is {{asset, source, added_at}}")
            if m["asset"] not in assets:
                raise SectorError(f"sector {sid}: unknown ticker {m['asset']!r} (not in data/tickers.json or the records)")
            if m["asset"] in mine:
                raise SectorError(f"sector {sid}: {m['asset']} listed twice")
            mine.add(m["asset"])
            if m["source"] is not None and (not isinstance(m["source"], str) or not URL_RE.match(m["source"])):
                raise SectorError(f"sector {sid}: source for {m['asset']} must be an https link or null")
    return doc


def load(root=HERE):
    p = path(root)
    if not os.path.exists(p):
        return {"schema": SCHEMA, "sectors": []}
    with open(p) as f:
        return validate(parse(f.read()), known_assets(root))


def dump(doc):
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def file_sha(root=HERE):
    p = path(root)
    if not os.path.exists(p):
        return hashlib.sha256(b"").hexdigest()
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _find(doc, sid):
    for s in doc["sectors"]:
        if s["id"] == sid:
            return s
    raise SectorError(f"no sector {sid!r} (add it first: /sector add {sid} <name>)")


def plan(root, op, args, when=None):
    """(new document, preview lines, token) for one change. Nothing is written here."""
    doc = json.loads(dump(load(root)))
    when = when or now()
    if op == "add":
        sid, name, proxy = args["id"], args["name"].strip(), args.get("proxy")
        if any(s["id"] == sid for s in doc["sectors"]):
            raise SectorError(f"sector {sid!r} exists")
        doc["sectors"].append({"id": sid, "name": name, "proxy": proxy, "created_at": when, "members": []})
        lines = [f"add sector {sid} \"{name}\"" + (f" (proxy label {proxy}, not priced)" if proxy else "")]
    elif op == "tag":
        s = _find(doc, args["id"])
        ticker = args["ticker"]
        if any(m["asset"] == ticker for m in s["members"]):
            raise SectorError(f"{ticker} is already in {s['id']}")
        s["members"].append({"asset": ticker, "source": args.get("source"), "added_at": when})
        s["members"].sort(key=lambda m: m["asset"])
        lines = [f"tag {ticker} -> {s['id']} ({s['name']})", f"source: {args.get('source') or 'none given'}"]
    elif op == "untag":
        s = _find(doc, args["id"])
        before = len(s["members"])
        s["members"] = [m for m in s["members"] if m["asset"] != args["ticker"]]
        if len(s["members"]) == before:
            raise SectorError(f"{args['ticker']} is not in {s['id']}")
        lines = [f"untag {args['ticker']} from {s['id']} ({s['name']})"]
    else:
        raise SectorError(f"unknown change {op!r}")
    validate(doc, known_assets(root))
    token = hashlib.sha256((file_sha(root) + "\n" + dump(doc)).encode()).hexdigest()[:16]
    lines.append("nothing changes in any record, price or score")
    return doc, lines, token


def apply(root, op, args, token, when):
    """Write the planned change only if the file is still the one previewed (same token)."""
    doc, _, want = plan(root, op, args, when)
    if token != want:
        raise SectorError("the preview is stale or was edited: preview again, then confirm")
    p = path(root)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        f.write(dump(doc))
    os.replace(tmp, p)
    return doc


def listing(doc):
    if not doc["sectors"]:
        return ["no sectors yet"]
    return [f"{s['id']} \"{s['name']}\"" + (f" proxy {s['proxy']}" if s["proxy"] else "") + ": "
            + (", ".join(m["asset"] for m in s["members"]) or "no assets") for s in doc["sectors"]]


# ---------------------------------------------------------------------------
# site: web/data/sectors.json + web/sectors.html (rebuilt from data/sectors.json and charts.json)

def by_asset(doc):
    out = {}
    for s in doc["sectors"]:
        for m in s["members"]:
            out.setdefault(m["asset"], []).append({"id": s["id"], "name": s["name"]})
    return out


def _result(p):
    """As the leaderboard (tools/prerender.py result_of): closed = the frozen realized return,
    open = since the post, for the call when a side is stated."""
    if p.get("closed"):
        return p["closed"]["for_call"] if p.get("side") else p["closed"]["move"]
    if p.get("change_since_post") is None:
        return None
    return p["side"] * p["change_since_post"] if p.get("side") else p["change_since_post"]


def build_data(root, web):
    doc = load(root)
    with open(os.path.join(web, "data", "charts.json"), "rb") as f:
        raw = f.read()
    bundle = json.loads(raw)
    posts = {a["name"]: a["posts"] for a in bundle["assets"]}
    out = []
    for s in doc["sectors"]:
        members = []
        for m in s["members"]:
            calls = []
            for p in posts.get(m["asset"], []):
                calls.append({"post_id": p["post"]["id"], "author": p["post"]["author"], "posted_at": p["post"]["posted_at"],
                              "side": {1: "long", -1: "short"}.get(p.get("side"), "none"),
                              "state": "closed" if p.get("closed") else "open", "result": _result(p)})
            calls.sort(key=lambda c: c["posted_at"], reverse=True)
            members.append({"asset": m["asset"], "source": m["source"], "added_at": m["added_at"], "calls": calls})
        out.append({"id": s["id"], "name": s["name"], "proxy": s["proxy"], "members": members})
    return {"schema": WEB_SCHEMA, "sectors": out, "by_asset": by_asset(doc),
            "charts_sha256": hashlib.sha256(raw).hexdigest(), "source_sha256": file_sha(root)}


def slug(post_id, asset):
    clean = lambda x: re.sub(r"[^A-Za-z0-9_-]", "-", x)
    return f"{clean(post_id)}_{clean(asset)}"


def tags_html(asset, d, link=True):
    """The sector tags for one asset (position, caller and leaderboard pages). link=False inside an existing link."""
    out = []
    for s in (d or {}).get("by_asset", {}).get(asset, []):
        if link:
            out.append(f' <a class="tag sector" data-field="sector" data-sector="{e(s["id"])}" href="sectors.html#{e(s["id"])}">{e(s["name"])}</a>')
        else:
            out.append(f' <span class="tag sector" data-field="sector" data-sector="{e(s["id"])}">{e(s["name"])}</span>')
    return "".join(out)


def fmt_pct(x):
    """As the leaderboard: two decimals, half up, "unresolved" when there is no price."""
    from decimal import ROUND_HALF_UP, Decimal
    if x is None:
        return "unresolved"
    sign = "+" if x > 0 else "-" if x < 0 else ""
    return sign + str(Decimal(repr(abs(x) * 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) + "%"


def page(d):
    secs = []
    for s in d["sectors"]:
        rows = []
        for m in s["members"]:
            src = f'<a href="{e(m["source"])}" rel="noopener noreferrer">source</a>' if m["source"] else "no source given"
            calls = "".join(f'<li data-post-id="{e(c["post_id"])}" data-asset="{e(m["asset"])}"><a href="pos-{e(slug(c["post_id"], m["asset"]))}.html">'
                            f'{e(c["side"].upper() if c["side"] != "none" else "NO SIDE")} · @{e(c["author"])} · {e(c["posted_at"][:10])} · {e(c["state"])} · '
                            f'<span class="{"gain" if (c["result"] or 0) > 0 else "loss" if (c["result"] or 0) < 0 else ""}" data-field="result">{e(fmt_pct(c["result"]))}</span></a></li>'
                            for c in m["calls"])
            rows.append(f'<div class="sector-asset" data-asset="{e(m["asset"])}"><h3>{e(m["asset"])} <span class="small muted">· {src} · tagged {e(m["added_at"][:10])}</span></h3>'
                        f'<ul class="static-list">{calls or "<li>no tracked calls yet</li>"}</ul></div>')
        proxy = f' <span class="tag" data-field="proxy" title="label only, not priced">proxy {e(s["proxy"])}</span>' if s["proxy"] else ""
        secs.append(f'<section class="panel" id="{e(s["id"])}" data-sector="{e(s["id"])}"><h2>{e(s["name"])}{proxy}</h2>'
                    f'{"".join(rows) or "<p class=notes>no assets tagged yet</p>"}</section>')
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; manifest-src 'none'; media-src 'none'; font-src 'none'; upgrade-insecure-requests">
<meta name="referrer" content="no-referrer">
<script src="assets/frame-guard.js"></script>
<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sectors · Quanty Quants</title>
<meta name="description" content="Calls grouped by theme: owner-set sectors, each asset with its source and every tracked call on it.">
<link rel="stylesheet" href="assets/board.css">
<link rel="stylesheet" href="assets/episode.css">
<link rel="stylesheet" href="assets/position.css">
</head>
<body>
<main>
  <header class="top">
    <div>
      <h1>Quanty Quants</h1>
      <p class="sub">Calls by sector</p>
    </div>
    <nav class="nav" aria-label="Views">
      <a href="./">Leaderboard</a>
      <a href="chart.html">Chart</a>
      <a href="episodes.html">Episodes</a>
      <a href="coins.html">Coins</a>
      <a href="regimes.html">Regimes</a>
      <a href="context.html">Context</a>
      <a href="sectors.html" aria-current="page">Sectors</a>
    </nav>
  </header>
  <section class="ep-head panel" data-field="sector-rule">
    <p>A sector is a theme the owner names and the assets the owner puts in it, each with the source given for it. Nothing is detected: every change is previewed and only written after the owner confirms it. A proxy is a label only and is never priced. Sectors never change a record, a price or a score.</p>
  </section>
  {"".join(secs) or '<p class="notes">No sectors yet.</p>'}
  <p class="muted small">Data: <a href="data/sectors.json">data/sectors.json</a> · charts.json sha256 {e(d["charts_sha256"][:16])}…</p>
  <p class="nfa" id="nfa" data-field="nfa"><strong>Not financial advice.</strong> The calls are public posts by their authors, tracked and priced for analysis. Nothing here is a recommendation to buy, sell or hold anything.</p>
</main>
</body>
</html>
"""


def build_web(web, root=None):
    """Called by tools/prerender.py: writes web/data/sectors.json and web/sectors.html, returns the data."""
    root = root or os.path.dirname(os.path.abspath(web))
    d = build_data(root, web)
    with open(os.path.join(web, "data", "sectors.json"), "w") as f:
        f.write(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
    with open(os.path.join(web, "sectors.html"), "w") as f:
        f.write(page(d))
    return d


def _args(argv):
    op, rest = argv[0], argv[1:]
    token = None
    if "--confirm" in rest:
        i = rest.index("--confirm")
        token, rest = rest[i + 1], rest[:i] + rest[i + 2:]
    proxy = None
    if "--proxy" in rest:
        i = rest.index("--proxy")
        proxy, rest = rest[i + 1], rest[:i] + rest[i + 2:]
    if op == "add":
        if len(rest) < 2:
            raise SectorError("usage: add <id> <name...> [--proxy LABEL]")
        return op, {"id": rest[0], "name": " ".join(rest[1:]), "proxy": proxy}, token
    if op == "tag":
        if len(rest) not in (2, 3):
            raise SectorError("usage: tag <ticker> <id> [source-url]")
        return op, {"ticker": rest[0], "id": rest[1], "source": rest[2] if len(rest) == 3 else None}, token
    if op == "untag":
        if len(rest) != 2:
            raise SectorError("usage: untag <ticker> <id>")
        return op, {"ticker": rest[0], "id": rest[1]}, token
    raise SectorError(f"unknown command {op!r}")


def main(argv=None, root=HERE):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if not argv or argv[0] in ("-h", "--help"):
            print(__doc__)
            return 0
        if argv[0] == "check":
            print(f"sectors: ok, {len(load(root)['sectors'])} sector(s)")
            return 0
        if argv[0] == "list":
            print("\n".join(listing(load(root))))
            return 0
        if argv[0] == "build":
            d = build_web(os.path.join(root, "web"), root)
            print(f"sectors page: {len(d['sectors'])} sector(s), {len(d['by_asset'])} tagged asset(s)")
            return 0
        op, args, token = _args(argv)
        when = args.pop("when", None) or os.environ.get("QUANTY_SECTOR_WHEN") or None
        if token is None:
            when = when or now()
            _, lines, tok = plan(root, op, args, when)
            print("\n".join(lines))
            print(f"preview token: {tok} (when {when})")
            return 0
        if not when:
            raise SectorError("--confirm needs the preview's time (QUANTY_SECTOR_WHEN), so the same change is written")
        apply(root, op, args, token, when)
        print("written: " + "; ".join(plan_lines_after(root)))
        return 0
    except SectorError as err:
        print(f"refused: {err}", file=sys.stderr)
        return 2


def plan_lines_after(root):
    return listing(load(root))


if __name__ == "__main__":
    sys.exit(main())
