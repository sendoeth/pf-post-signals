#!/usr/bin/env python3
"""Step 12: write the data into the pages as plain HTML, so a fetch without JavaScript (curl,
crawlers, link previews) sees real numbers. The scripts replace these blocks with the interactive
view; the content is the same bundle.

- web/index.html: <!--static:NAME--> ... <!--/static:NAME--> blocks for the "prices as of" line,
  the author table, the stats strip and the ranked rows (default view: sorted by return)
- web/pos-<post>_<asset>.html: one page per position, built from web/position.html, with the post,
  side, entry, latest, return, best, status and 1d / 7d / 30d moves, plus title / description /
  Open Graph tags for link previews. The script reads the post from <main data-post data-asset>.
- web/position.html: a static list of every position, linking to its page
Every value is HTML-escaped; formatting mirrors the scripts (assets/board.js, assets/common.js).
Called by build_chart.py after it writes the real bundle; also runnable on its own.

usage: python3 tools/prerender.py [--web DIR]
"""
import glob
import html
import json
import os
import re
import sys
from decimal import ROUND_HALF_UP, Decimal

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HZ = ("1", "7", "30")
AUTHOR_COLORS = ["#2a78d6", "#eb6834", "#4a3aa7", "#d55181", "#5b6475", "#8a5a2b"]
SITE = "https://sendoeth.com/pf-post-signals/web/"


def e(s):
    return html.escape(str(s), quote=True)


def fmt_pct(x):
    if x is None:
        return "unresolved"
    sign = "+" if x > 0 else "-" if x < 0 else ""
    return sign + str(Decimal(repr(abs(x) * 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) + "%"


def fmt_price(p):
    q = Decimal(repr(p)).quantize(Decimal("1e-8"), rounding=ROUND_HALF_UP).normalize()
    whole, _, frac = f"{q:f}".partition(".")
    neg = whole.startswith("-")
    whole = f"{int(whole.lstrip('-')):,}"
    return ("-" if neg else "") + whole + ("." + frac if frac else "")


def fmt_time(iso):
    return iso[:10] + " " + iso[11:16] + " UTC"


def slug(post_id, asset):
    clean = lambda s: re.sub(r"[^A-Za-z0-9_-]", "-", s)
    return f"{clean(post_id)}_{clean(asset)}"


def author_class(handle):
    h = 0
    for ch in handle.lower():
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return f"ac-{h % len(AUTHOR_COLORS)}"


def result_of(p):
    """closed: the frozen realized return; open: since post (for the call when a side is stated)"""
    if p.get("closed"):
        return p["closed"]["for_call"] if p.get("side") else p["closed"]["move"]
    if p["change_since_post"] is None:
        return None
    return p["side"] * p["change_since_post"] if p.get("side") else p["change_since_post"]


def if_held(p):
    if p["change_since_post"] is None:
        return None
    return p["side"] * p["change_since_post"] if p.get("side") else p["change_since_post"]


def status_label(p):
    if p["status"] == "closed":
        return "closed"
    if p["status"] == "resolved":
        return "all horizons in"
    if p["status"] == "pending":
        return "no price yet"
    if p["status"] == "no_entry":
        return "no price at post time"
    open_ = [h for h in HZ if p.get("unresolved", {}).get(h)]
    return ", ".join(h + "d" for h in open_) + " pending" if open_ else p["status"]


def rows_of(bundle):
    rows = []
    for a in bundle["assets"]:
        for p in a["posts"]:
            side = {1: "long", -1: "short"}.get(p.get("side"), "none")
            ret = result_of(p)
            best = None if not p.get("best") else (p["best"]["for_call"] if p.get("side") else p["best"]["move"])
            rows.append({"p": p, "asset": a["name"], "side": side, "ret": ret, "best": best})
    # default view: by return, unresolved last, then newest, then id + asset (as board.js)
    rows.sort(key=lambda r: (r["ret"] is None, -(r["ret"] or 0), [-ord(c) for c in r["p"]["post"]["posted_at"]], r["p"]["post"]["id"] + r["asset"]))
    return rows


def avatar_html(handle, avatars, cls="avatar"):
    meta = avatars.get(handle.lower())
    if meta and re.fullmatch(r"[a-z0-9_]{1,15}\.jpg", meta.get("file", "")) and meta["file"] == handle.lower() + ".jpg":
        return f'<span class="{cls}" data-avatar="image" aria-hidden="true"><img src="avatars/{e(meta["file"])}" alt=""></span>'
    letters = re.sub(r"[^A-Za-z0-9]", "", handle)[:2].upper() or "?"
    return f'<span class="{cls} {author_class(handle)}" data-avatar="initials" aria-hidden="true">{e(letters)}</span>'


def raw(v):
    return e(json.dumps(v))


def board_blocks(bundle, avatars):
    rows = rows_of(bundle)
    authors = sorted({r["p"]["post"]["author"] for r in rows})
    asof = bundle.get("prices_as_of")
    blocks = {"asof": e(f"{len(rows)} positions from {len(authors)} author{'' if len(authors) == 1 else 's'} · "
                        + (f"prices as of {fmt_time(asof)} (daily refresh)" if asof else "prices not refreshed yet"))}
    out = []
    for i, r in enumerate(rows, 1):
        p, s = r["p"], slug(r["p"]["post"]["id"], r["asset"])
        quote = f'<span class="quote" data-field="quote">“{e(" ".join(p["post"]["text"].split()))}”</span>' if p["post"].get("text") else ""
        end = (fmt_price(p["closed"]["exit"]["price"]) + " exit") if p.get("closed") else (fmt_price(p["latest"]["price"]) if p.get("latest") else "–")
        prices = f'{fmt_price(p["entry"]["price"])} → {end}' if p.get("entry") else "no entry bar"
        tags = (' <span class="tag closed" data-field="closed_tag">closed</span>' if p.get("closed") else "") + \
               (' <span class="tag" data-field="stand_in">stand-in</span>' if p["asset"].get("stand_in") else "") + \
               (' <span class="tag" data-field="adjusted">split-adj.</span>' if p["asset"].get("adjustments") else "")
        out.append(
            f'<li data-static="1" data-post-id="{e(p["post"]["id"])}" data-asset="{e(r["asset"])}" data-rank="{i}">'
            f'<a class="row" href="pos-{e(s)}.html"><span class="rank" data-field="rank">{i}</span>'
            f'<span class="who">{avatar_html(p["post"]["author"], avatars)}<span class="meta"><span class="line1">'
            f'<span class="ticker" data-field="asset">{e(r["asset"])}</span> <span class="badge {r["side"]}" data-field="side">{"NO SIDE" if r["side"] == "none" else r["side"].upper()}</span>{tags}</span>'
            f'<span class="line2"><span data-field="author">@{e(p["post"]["author"])}</span> · <time datetime="{e(p["post"]["posted_at"])}" data-field="posted">{e(fmt_time(p["post"]["posted_at"]))}</time></span>{quote}</span></span>'
            f'<span class="col-spark"></span><span class="col-px px" data-field="prices">{e(prices)}</span>'
            f'<span class="r ret {cls(r["ret"])}" data-field="return" data-raw="{raw(r["ret"])}">{fmt_pct(r["ret"])}</span>'
            f'<span class="r col-best best {cls(r["best"])}" data-field="best" data-raw="{raw(r["best"])}">{"–" if r["best"] is None else "▲ " + fmt_pct(r["best"])}</span>'
            f'<span class="status" data-field="status" data-raw="{raw(p["status"])}">{e(status_label(p))}</span></a></li>')
    blocks["rows"] = "\n".join(out)
    done = [r for r in rows if r["ret"] is not None]
    avg = sum(r["ret"] for r in done) / len(done) if done else None
    hit = sum(r["ret"] > 0 for r in done) / len(done) if done else None
    top = max(done, key=lambda r: r["ret"]) if done else None
    stat = lambda n, label, text, rv, c="": f'<div class="stat" data-stat="{n}"><span class="label">{label}</span><strong class="{c}" data-raw="{raw(rv)}">{e(text)}</strong></div>'
    blocks["stats"] = "".join([
        stat("count", "Positions", str(len(rows)), len(rows)),
        stat("hit_rate", "In profit", "–" if hit is None else f"{round(hit * 100)}%", hit),
        stat("avg_return", "Average return", "–" if avg is None else fmt_pct(avg), avg, cls(avg)),
        stat("best_call", "Best call", f'{fmt_pct(top["ret"])} · {top["asset"]} @{top["p"]["post"]["author"]}' if top else "–",
             f'{top["p"]["post"]["id"]}|{top["asset"]}' if top else None, cls(top["ret"]) if top else "")])
    trs = []
    for a in authors:
        mine = [r for r in rows if r["p"]["post"]["author"] == a]
        d = [r for r in mine if r["ret"] is not None]
        n = len(d)
        flag = "insufficient sample" if n < 10 else "unreliable sample" if n < 30 else "ok"
        best = max(d, key=lambda r: r["ret"]) if d else None
        worst = min(d, key=lambda r: r["ret"]) if d else None
        call = lambda r: f'{fmt_pct(r["ret"])} {r["asset"]}' if r else "–"
        avg_a = sum(r["ret"] for r in d) / n if n else None
        trs.append(f'<tr data-author="{e(a)}" data-static="1"><td class="a-who">{avatar_html(a, avatars)}<span>@{e(a)}</span></td>'
                   f'<td data-field="calls">{len(mine)}</td><td data-field="hit">{"–" if not n else str(round(sum(r["ret"] > 0 for r in d) / n * 100)) + "%"}</td>'
                   f'<td data-field="avg" class="{cls(avg_a)}">{"–" if avg_a is None else fmt_pct(avg_a)}</td>'
                   f'<td data-field="best" class="{cls(best["ret"]) if best else ""}">{e(call(best))}</td><td data-field="worst" class="{cls(worst["ret"]) if worst else ""}">{e(call(worst))}</td>'
                   f'<td data-field="flag" class="flag {"ok" if flag == "ok" else "warn"}">{flag}</td></tr>')
    blocks["authors"] = "\n".join(trs)
    return blocks, rows


def cls(x):
    return "unresolved" if x is None else "gain" if x > 0 else "loss" if x < 0 else ""


def fill(html_text, blocks):
    for name, body in blocks.items():
        pat = re.compile(rf"(<!--static:{name}-->).*?(<!--/static:{name}-->)", re.S)
        if not pat.search(html_text):
            raise SystemExit(f"missing <!--static:{name}--> block")
        html_text = pat.sub(lambda m: m.group(1) + body + m.group(2), html_text)
    return html_text


def position_static(r, asof, avatars):
    p = r["p"]
    side = r["side"]
    rows = [("Asset", f'{r["asset"]} ({p["asset"]["source"]}:{p["asset"]["symbol"]})', "asset", None),
            ("Side", "no side stated" if side == "none" else side, "side", p.get("side")),
            ("Status", status_label(p), "status", p["status"]),
            ("Entry", f'{fmt_price(p["entry"]["price"])} @ {fmt_time(p["entry"]["at"])}' if p.get("entry") else "no entry bar", "entry", p.get("entry")),
            ("Latest", f'{fmt_price(p["latest"]["price"])} @ {fmt_time(p["latest"]["at"])}' if p.get("latest") else "no bar yet", "latest", p.get("latest")),
            ("Since post", fmt_pct(p["change_since_post"]), "change_since_post", p["change_since_post"]),
            ("Return" + (" for the call" if side != "none" else ""), fmt_pct(r["ret"]), "return", r["ret"]),
            ("Best since post", "–" if r["best"] is None else fmt_pct(r["best"]), "best", r["best"])]
    for h in HZ:
        v = p["moves"].get(h)
        rows.append((f"{h}d move", fmt_pct(v) if v is not None else "unresolved · " + p["unresolved"].get(h, ""), f"move_{h}", v))
    if p.get("closed"):
        c = p["closed"]
        ev = next((x for x in p["lifecycle"]["events"] if x["post"]["id"] == c["post_id"]), None)
        rows.insert(6, ("Closed (realized)", f'{fmt_pct(r["ret"])} · exit {fmt_price(c["exit"]["price"])} @ {fmt_time(c["exit"]["at"])}'
                        + (" (daily bar)" if c["exit"].get("interval") == "1d" else ""), "closed", c))
        rows.insert(7, ("Closing post", ("exit event in the published ledger" if c.get("by") == "ledger" else
                        f'{fmt_time(ev["post"]["posted_at"]) if ev else ""} · {c.get("post_url", "")} · matched: {", ".join(ev["terms"]) if ev else ""}'
                        + (f' · the post says "{c["stated_time"]}"; the exit uses the first bar after the post' if c.get("stated_time") else "")), "closing_post", None))
        rows.insert(8, ("If still held", f'{fmt_pct(if_held(p))} (now {fmt_price(p["latest"]["price"])}), not the result', "if_still_held", if_held(p)))
    if p.get("lifecycle", {}).get("events"):
        names = {"trim": "trim", "close": "close", "flip": "flip", "review": "review", "not_close": "not a close"}
        rows.append(("Lifecycle", " | ".join(f'{names[x["type"]]} {fmt_time(x["post"]["posted_at"])}'
                     + (f' at {fmt_price(x["bar"]["price"])}' if x.get("bar") else "") + (f' ({", ".join(x["terms"])})' if x["terms"] else "")
                     for x in p["lifecycle"]["events"]), "lifecycle", None))
    if p.get("resolved_with", {}).get("daily_until") and (p.get("entry") or {}).get("interval") == "1d":
        rows.append(("Resolution", f'daily bars before {fmt_time(p["resolved_with"]["daily_until"])}, hourly after', "resolution", None))
    if p["asset"].get("stand_in"):
        rows.append(("Priced via", "stand-in for " + p["asset"]["stand_in"]["for"], "stand_in", None))
    if p["asset"].get("adjustments"):
        rows.append(("Adjusted", "; ".join(f'{a["kind"]} on {fmt_time(a["at"])}' for a in p["asset"]["adjustments"]), "adjustments", None))
    numeric = ("change_since_post", "return", "best", "if_still_held")
    dl = "".join(f'<dt>{e(k)}</dt><dd data-field="{f}"' + (f' data-raw="{raw(v)}"' if v is not None or f in numeric else "")
                 + f' class="{cls(v) if f in numeric or f.startswith("move_") else ""}">{e(t)}</dd>'
                 for k, t, f, v in rows)
    link = "read the article" if p["post"].get("source") == "corbanu" else "open on X"
    text = f'<p class="text" data-field="text">{e(p["post"]["text"])}</p>' if p["post"].get("text") else '<p class="text notes" data-field="text">Post text not saved: open it on X.</p>'
    return (f'<div data-static="1"><section class="panel post"><div class="who">{avatar_html(p["post"]["author"], avatars)}<div>'
            f'<strong data-field="author">@{e(p["post"]["author"])}</strong><span class="meta"><span data-field="posted_at">{e(fmt_time(p["post"]["posted_at"]))}</span> · '
            f'<a href="{e(p["post"]["url"])}" rel="noopener noreferrer" data-field="url">{link}</a></span></div></div>{text}</section>'
            f'<section class="panel recap"><h2>{e(r["asset"])} · {"NO SIDE" if side == "none" else side.upper()}</h2><dl>{dl}</dl>'
            f'<p class="notes">Prices as of {e(fmt_time(asof)) if asof else "–"}. Record {e(p["record_file"])} · sha256 {e(p["record_sha256"])}</p></section></div>')


def meta_tags(title, desc, url):
    return (f'<title>{e(title)}</title>\n<meta name="description" content="{e(desc)}">\n'
            f'<meta property="og:title" content="{e(title)}">\n<meta property="og:description" content="{e(desc)}">\n'
            f'<meta property="og:type" content="article">\n<meta property="og:site_name" content="Quanty Quants">\n<meta property="og:url" content="{e(url)}">\n<meta name="twitter:card" content="summary">')


def main(web=None):
    web = web or (sys.argv[sys.argv.index("--web") + 1] if "--web" in sys.argv else os.path.join(HERE, "web"))
    with open(os.path.join(web, "data", "charts.json")) as f:
        bundle = json.load(f)
    avatars = {}
    if os.path.exists(os.path.join(web, "avatars", "index.json")):
        with open(os.path.join(web, "avatars", "index.json")) as f:
            avatars = json.load(f)
    blocks, rows = board_blocks(bundle, avatars)
    index_path = os.path.join(web, "index.html")
    with open(index_path) as f:
        index = f.read()
    with open(index_path, "w") as f:
        f.write(fill(index, blocks))
    with open(os.path.join(web, "position.html")) as f:
        template = f.read()
    listing = "\n".join(f'<li><a href="pos-{e(slug(r["p"]["post"]["id"], r["asset"]))}.html">{e(r["asset"])} '
                        f'{"NO SIDE" if r["side"] == "none" else r["side"].upper()} · @{e(r["p"]["post"]["author"])} · {e(fmt_time(r["p"]["post"]["posted_at"]))} · '
                        f'return {fmt_pct(r["ret"])}</a></li>' for r in rows)
    with open(os.path.join(web, "position.html"), "w") as f:
        f.write(fill(template, {"app": f'<div data-static="1"><p class="notes">All positions (open one for its chart):</p><ul class="static-list">{listing}</ul></div>'}))
    keep = set()
    asof = bundle.get("prices_as_of")
    for r in rows:
        p, s = r["p"], slug(r["p"]["post"]["id"], r["asset"])
        side = "NO SIDE" if r["side"] == "none" else r["side"].upper()
        title = f'{r["asset"]} {side}{" (closed)" if p.get("closed") else ""} · @{p["post"]["author"]} · {fmt_pct(r["ret"])} · Quanty Quants'
        desc = (f'@{p["post"]["author"]} {fmt_time(p["post"]["posted_at"])}: {r["asset"]} {side.lower()}, entry '
                + (fmt_price(p["entry"]["price"]) if p.get("entry") else "–")
                + (f', closed at {fmt_price(p["closed"]["exit"]["price"])} on {p["closed"]["exit"]["at"][:10]}, realized {fmt_pct(r["ret"])}, if still held {fmt_pct(if_held(p))}.' if p.get("closed")
                   else f', return {fmt_pct(r["ret"])}, {status_label(p)}.')
                + (f' “{" ".join(p["post"]["text"].split())[:140]}”' if p["post"].get("text") else ""))
        page = re.sub(r"<title>.*?</title>\n<meta name=\"description\" content=\"[^\"]*\">", lambda m: meta_tags(title, desc, f"{SITE}pos-{s}.html"), template, count=1, flags=re.S)
        page = page.replace("<main>", f'<main data-post="{e(p["post"]["id"])}" data-asset="{e(r["asset"])}">', 1)
        page = fill(page, {"app": position_static(r, asof, avatars)})
        name = f"pos-{s}.html"
        with open(os.path.join(web, name), "w") as f:
            f.write(page)
        keep.add(name)
    for old in glob.glob(os.path.join(web, "pos-*.html")):
        if os.path.basename(old) not in keep:
            os.remove(old)
    print(f"prerender: index.html ({len(rows)} rows, {len(blocks['authors'].splitlines())} authors), position.html list, {len(keep)} position pages")


if __name__ == "__main__":
    main()
