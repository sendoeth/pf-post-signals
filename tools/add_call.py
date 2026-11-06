#!/usr/bin/env python3
"""Step 16: analyse a caller from one pasted post. Owner-only: a local script, no public endpoint.

  python3 tools/add_call.py URL [--asset NAME --reason "..."] [--side long|short|none --reason "..."]
      preview: saves the post receipt (sources/<author>/receipts/<id>.json, sha256), detects asset and
      side, prices the entry against the asset's shared series, and prints the call, its result so far,
      the author's current score and the score with this call added. Writes the full preview to
      intake/pending/<id>_<asset>.json. Nothing under web/ or records/ changes.
  python3 tools/add_call.py URL --add      (same options as the preview)
      applies exactly the pending preview: writes records/posts/<id>_<asset>.json, saves the author's
      avatar if new (initials otherwise), rebuilds web/data/charts.json, the ratings and the static
      pages, checks that the author's score now equals the previewed one and that no frozen value of
      any other position moved, and logs both to intake/log/. A preview older than the current bundle
      is refused (rerun the preview).

Refused, with the reason: posts that are deleted / private, posts whose asset the detector cannot
read (unless --asset with --reason), a post + asset already recorded, a side stated both ways
(unless --side with --reason), and --asset / --side without a written reason.

The new record shares the asset's bars: every bar the bundle already has is written back into the
fetched series (a provider revision is logged, the bundle's value kept), so the new record agrees
with every existing record on that asset.
"""
import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

TOOLS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TOOLS)
sys.path[:0] = [HERE, TOOLS]
import build_chart  # noqa: E402
import detect  # noqa: E402
import frozen_values  # noqa: E402
import ingest  # noqa: E402
import prerender  # noqa: E402
import rate  # noqa: E402
import resolve  # noqa: E402
import tickers  # noqa: E402

VERSION = "quanty.intake.v1"


class Refused(Exception):
    pass


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def file_name(pid, asset_name):
    return f"{pid.replace(':', '-')}_{asset_name.replace(':', '-').replace('=', '')}.json"


def existing_record(root, pid, asset_name):
    hits = glob.glob(os.path.join(root, "records", "**", file_name(pid, asset_name)), recursive=True)
    return os.path.relpath(hits[0], root) if hits else None


def caller_view(ratings, author):
    c = ratings["callers"].get(author)
    if not c:
        return None
    return {k: c.get(k) for k in ("score", "display", "rank", "label", "scored", "calls_total", "with_entry", "raw", "weight")} | {"of": len(ratings["order"])}


def shared_series(fetched, bundle, asset_name):
    """The fetched series with every bar the bundle already has for this asset written back."""
    have = next((dict(map(tuple, a["series"])) for a in bundle["assets"] if a["name"] == asset_name), {})
    out, revisions = [], []
    for t, p in fetched:
        if t in have and have[t] != p:
            revisions.append({"bar": t, "bundle": have[t], "fetched": p, "note": "provider revision; the bundle's value kept"})
            p = have[t]
        out.append([t, p])
    return out, revisions


def choose_side(text, side, reason):
    if side is not None:
        if not reason:
            raise Refused("--side needs --reason: a side chosen by hand is always explained")
        s = None if side == "none" else resolve.side_of(side)
        return s, {"method": "manual", "terms": [], "reason": reason}
    d = detect.detect_side(text)
    terms = d["terms"][1] + d["terms"][-1]
    if d["status"] == "ambiguous":
        raise Refused(f"the post states both sides (long: {d['terms'][1]}, short: {d['terms'][-1]}): rerun with --side and --reason")
    if d["status"] == "none":
        return None, {"method": "none", "terms": [], "reason": "no side words: counted as a call without a side (clarity only)"}
    return d["side"], {"method": "detector", "terms": terms[:20], "reason": None}


def image_evidence(root, pid):
    """intake/images/<post>.json written by tools/read_images.py, if the post was read from its images."""
    path = os.path.join(root, "intake", "images", f"{pid}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        e = json.load(f)
    return {"file": os.path.relpath(path, root), "sha256": sha256_file(path), "confidence": e.get("confidence"), "suggested": e.get("asset_suggested")}


def receipt_sha(receipt):
    """sha256 of the ticker receipt exactly as tickers.register writes it (sources/tickers/<TICKER>.json)."""
    return hashlib.sha256((json.dumps(receipt, indent=1) + "\n").encode()).hexdigest()


def legs_message(legs, text):
    """The refusal for a post naming several coins (or a coin that needs review): one line per leg,
    machine-readable for the admin bot (LEG / REVIEW lines)."""
    lines = []
    for l in legs:
        if l["status"] != "ok":
            lines.append(f"REVIEW {' / '.join(l['via'])}: {l['reason']}")
            # step 26: an ambiguous ticker lists its candidates (machine-readable for the bot's pick buttons)
            for c in sorted((l.get("receipt") or {}).get("candidates") or [], key=lambda c: c.get("rank") or 10 ** 9)[:3]:
                if l["status"] == "review" and "pick one by hand" in (l["reason"] or "") and re.fullmatch(r"[a-z0-9-]{1,80}", c["id"]):
                    where = ", ".join(f"{k}:{v}" for k, v in sorted((c.get("platforms") or {}).items())) or "no contract listed"
                    lines.append(f"CANDIDATE {l['via'][0].lstrip('$')} {c['id']} {c['name']} #{c.get('rank') or '-'} {where}")
            continue
        s, why, words = detect.leg_side(text, [l["asset"]] + [v.lstrip("$") for v in l["via"]])
        side = {1: "long", -1: "short"}.get(s, "none")
        coin = f" = {l['receipt']['coin']['name']} [{l['receipt']['coin']['id']}] on {l['receipt']['chosen']['source']}:{l['receipt']['chosen']['symbol']}" if l.get("receipt") else ""
        lines.append(f"LEG {l['asset']} side {side}: {why}" + (f" ('{words}')" if words else "") + f" via {' / '.join(l['via'])}{coin}")
    return "\n".join(lines)


def pick_coin(text, leg, net, picks=None):
    """No mapped asset: resolve every coin the post names (tickers.py). One ok coin -> it; several ->
    the chosen --leg; anything else -> Refused with the legs listed. `picks` = the owner's {TICKER: coingecko id}."""
    legs = detect.coin_legs(text, net=net, picks=picks)
    ok = [l for l in legs if l["status"] == "ok"]
    if leg:
        hit = next((l for l in ok if l["asset"] == leg.upper()), None)
        if not hit:
            raise Refused(f"--leg {leg}: not a resolved coin of this post\n" + legs_message(legs, text))
        return hit, legs
    if len(legs) == 1 and ok:
        return ok[0], legs
    if not legs:
        raise Refused("unreadable post: the detector cannot tell the asset (no asset words, cashtags or contract tags); rerun with --asset and --reason")
    if len(ok) > 1:
        raise Refused("several coins in this post: each is added on its own, pick one with --leg\n" + legs_message(legs, text))
    raise Refused("the coin(s) of this post could not be confirmed (nothing guessed)\n" + legs_message(legs, text))


def build_item(url, root=HERE, fetch=ingest.fetch_embed, prices=None, bundle=None, asset=None, side=None, reason=None, now=None, allow_pending=False,
               leg=None, net=None, picks=None):
    """One post -> {url, receipt, record_file, record, revisions, detected}. Writes only the receipt."""
    if asset and not reason:
        raise Refused("--asset needs --reason: an asset chosen by hand is always explained")
    try:
        rpath, receipt, created = ingest.ingest(url, fetch=fetch, root=root, now=now)
    except ingest.IngestError as e:
        raise Refused(f"unreadable post: {e}") from e
    text = receipt.get("text") or ""
    # step 18: a post with image evidence (tools/read_images.py) is added only with a written reason;
    # the record keeps the evidence file and its sha256 (asset_choice.evidence, below)
    if image_evidence(root, receipt["id"]) and not (reason or "").strip():
        raise Refused(f"image-inferred call: intake/images/{receipt['id']}.json exists; add it only with --asset, --side and a written --reason")
    d = detect.detect(text, manual=asset)
    coin, legs = None, None
    if d["status"] != "manual":                       # step 23: every coin the post names (seeded names / tickers, indexes, stocks) -> legs
        # step 22: cashtags without a fixed mapping and X contract tags are resolved to plain tickers
        coin, legs = pick_coin(text, leg, net or tickers.Net(), picks)
        d = {"status": "detected", "asset": coin["asset"], "matched": [{"asset": coin["asset"], "term": v} for v in coin["via"]], "reason": None}
    try:
        info = resolve.asset_info(d["asset"])
    except resolve.ResolveError as e:
        if not (coin and coin.get("receipt")):
            raise Refused(f"unknown asset {d['asset']}: {e}") from e
        ch = coin["receipt"]["chosen"]                # a new ticker: priced from the venue its receipt confirmed
        info = {"name": coin["asset"], "source": ch["source"], "symbol": ch["symbol"], "price_field": "open"}
    if coin and coin.get("receipt"):
        passed = {(v["source"], v.get("symbol")) for v in coin["receipt"]["venues"] if v["ok"]}
        if (info["source"], info["symbol"]) not in passed:
            raise Refused(f"{info['name']} is priced on {info['source']}:{info['symbol']} on this site, but that venue failed today's check "
                          f"({', '.join(f'{v[0]}:{v[1]}' for v in sorted(passed)) or 'no venue'} passed): nothing added, review the ticker")
    dup = existing_record(root, receipt["id"], info["name"])
    if dup:
        raise Refused(f"duplicate: post {receipt['id']} on {info['name']} is already recorded in {dup}")
    multi = bool(legs and len(legs) > 1)
    aliases = [info["name"].split(":")[-1]] + [m["term"].lstrip("$") for m in d["matched"]] + ([v.lstrip("$") for v in coin["via"]] if coin else [])
    if side is None and (multi or detect.OPTION.search(text)):
        # options ("buying puts" = short, "selling calls" = no side) and several coins: the coin's own words decide
        s, why, words = detect.leg_side(text, aliases)
        if not words and detect.OPTION.search(text) and not multi:
            why = "option words without a clear buy / sell next to this coin: no side (set it by hand if the post says more)"
        side_choice = {"method": "detector-leg", "terms": [words[:80]] if words else [], "reason": why}
    else:
        s, side_choice = choose_side(text, side, reason)
    post = resolve.load_post(receipt=rpath)
    series, revisions = shared_series(prices.series(info, post["posted_at"]), bundle, info["name"])
    rec = resolve.label_daily(resolve.resolve(post, info, series, prices.label, s), prices.daily_until(info, post["posted_at"]))
    rec["asset_choice"] = {"method": "manual" if d["status"] == "manual" else "detector",
                           "terms": ([m["term"] for m in d["matched"]] if coin else [m["term"] for m in detect.detect(text)["matched"]])[:20],
                           "reason": reason if asset else None}
    if coin and coin.get("receipt"):
        r = coin["receipt"]
        rec["asset_choice"]["ticker"] = {"coingecko_id": r["coin"]["id"], "name": r["coin"]["name"], "source": info["source"], "symbol": info["symbol"],
                                         "receipt_sha256": receipt_sha(r), "checked_at": r["checked_at"], "asked": r["asked"]}
    if multi:
        rec["asset_choice"]["leg"] = {"of": [l["asset"] or "/".join(l["via"]) for l in legs], "words": side_choice["terms"][0] if side_choice["terms"] else None}
    ev = image_evidence(root, receipt["id"])
    if ev and d["status"] == "manual":
        # step 18: an asset read from images is never added without a written review reason and the evidence it rests on
        if not (reason or "").strip() or side is None:
            raise Refused("an image-inferred call needs --asset, --side (long / short / none) and a written --reason")
        rec["asset_choice"].update(method="image_review", evidence=ev)
    rec["side_choice"] = side_choice
    resolve.check_record(resolve.validator(), rec)
    if not rec.get("entry"):
        if not (allow_pending and rec["status"] == "pending"):
            raise Refused(f"no price at or after the post within the lag limit ({rec['status']}): nothing to score yet"
                          + ("; --pending adds it now and the daily refresh fills the entry from the first bar" if rec["status"] == "pending" else ""))
    return {"url": receipt["url"], "ticker_receipt": coin["receipt"] if coin and coin.get("receipt") else None,
            "receipt": {"file": os.path.relpath(rpath, root), "sha256": sha256_file(rpath), "created": created, "text_truncated": receipt.get("textTruncated", False)},
            "detected": {"asset": d["status"], "terms": rec["asset_choice"]["terms"], "side": side_choice},
            "record_file": os.path.join("records", "posts", file_name(receipt["id"], info["name"])), "record": rec, "revisions": revisions}


def project(items, root, bundle_blob, name, now=None, extra=None):
    """The bundle exactly as --add will build it (scratch copy of records/), and the pending file."""
    bundle = json.loads(bundle_blob)
    files = [it["record_file"] for it in items]
    if len(set(files)) != len(files):
        raise Refused("the batch holds the same post + asset twice")
    tmp = tempfile.mkdtemp(prefix="quanty-intake-")
    try:
        shutil.copytree(os.path.join(root, "records"), os.path.join(tmp, "records"))
        for it in items:
            path = os.path.join(tmp, it["record_file"])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(it["record"], f, indent=1)
                f.write("\n")
        projected = build_chart.build(os.path.join(tmp, "records"))
    finally:
        shutil.rmtree(tmp)
    authors = sorted({it["record"]["post"]["author"] for it in items})
    pending = {"version": VERSION, "previewed_at": now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "bundle_sha256": hashlib.sha256(bundle_blob).hexdigest(), "items": items, "authors": authors,
               "scores_before": {a: caller_view(bundle["ratings"], a) for a in authors},
               "scores_after": {a: caller_view(projected["ratings"], a) for a in authors},
               "order_after": projected["ratings"]["order"]}
    if len(items) == 1:      # single post: the step 16 fields, kept for the printout and the log
        it, a = items[0], authors[0]
        pending.update({k: it[k] for k in ("url", "receipt", "detected", "record_file", "record", "revisions")})
        pending.update(author=a, new_caller=a not in bundle["ratings"]["callers"], score_before=pending["scores_before"][a], score_after=pending["scores_after"][a])
        before = pending["score_before"]["score"] if pending["score_before"] else None
        pending["score_delta"] = None if before is None else pending["score_after"]["score"] - before
    pending.update(extra or {})
    out = os.path.join(root, "intake", "pending", name)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(pending, f, indent=1, ensure_ascii=False)
        f.write("\n")
    pending["pending_file"] = os.path.relpath(out, root)
    return pending


def load_bundle(root):
    with open(os.path.join(root, "web", "data", "charts.json"), "rb") as f:
        blob = f.read()
    return blob, json.loads(blob)


def preview(url, root=HERE, fetch=ingest.fetch_embed, prices=None, asset=None, side=None, reason=None, now=None, allow_pending=False, leg=None, net=None,
            picks=None):
    """-> the pending intake (also written to intake/pending/). Writes only the receipt and the pending file."""
    blob, bundle = load_bundle(root)
    it = build_item(url, root, fetch, prices or resolve.Prices(), bundle, asset, side, reason, now, allow_pending, leg=leg, net=net, picks=picks)
    return project([it], root, blob, os.path.basename(it["record_file"]), now)


def default_ohlc(root, asset_name, entry_at):
    """Refetch the candle files when the asset has none or they do not cover the new entry bar."""
    idx = os.path.join(root, "web", "data", "ohlc", "index.json")
    meta = {}
    if os.path.exists(idx):
        with open(idx) as f:
            meta = json.load(f)["files"].get(asset_name) or {}
    if meta and meta["first"] <= entry_at <= meta["last"]:
        return "candles already cover the entry bar"
    # step 26: only this asset's candles are fetched and checked; the other files stay as they are
    r = subprocess.run([sys.executable, os.path.join(root, "fetch_ohlc.py"), "--assets", asset_name], cwd=root, capture_output=True, text=True)
    if r.returncode:
        raise Refused(f"not added: fetching {asset_name}'s candles failed, everything was put back:\n{r.stdout[-2000:]}{r.stderr[-2000:]}")
    return f"candles fetched for {asset_name} (fetch_ohlc.py --assets): " + r.stdout.strip().splitlines()[-1]



def snapshot(root, record_files):
    """web/, data/tickers.json and the ticker receipts as they are before an add; the record files it will create."""
    tmp = tempfile.mkdtemp(prefix="quanty-add-")
    shutil.copytree(os.path.join(root, "web"), os.path.join(tmp, "web"), symlinks=True)
    reg = os.path.join(root, "data", "tickers.json")
    had_reg = os.path.exists(reg)
    if had_reg:
        shutil.copy2(reg, os.path.join(tmp, "tickers.json"))
    tdir = os.path.join(root, "sources", "tickers")
    receipts = set(os.listdir(tdir)) if os.path.isdir(tdir) else set()
    return {"tmp": tmp, "had_reg": had_reg, "receipts": receipts, "records": [f for f in record_files if not os.path.exists(os.path.join(root, f))]}


def restore(root, snap):
    """Put back what snapshot() saw: web/, the registry, no new ticker receipts, no new record files."""
    web = os.path.join(root, "web")
    shutil.rmtree(web)
    shutil.copytree(os.path.join(snap["tmp"], "web"), web, symlinks=True)
    reg = os.path.join(root, "data", "tickers.json")
    if snap["had_reg"]:
        shutil.copy2(os.path.join(snap["tmp"], "tickers.json"), reg)
    elif os.path.exists(reg):
        os.remove(reg)
    tdir = os.path.join(root, "sources", "tickers")
    if os.path.isdir(tdir):
        for f in set(os.listdir(tdir)) - snap["receipts"]:
            p = os.path.join(tdir, f)
            if os.path.isfile(p):
                os.remove(p)
    for f in snap["records"]:
        if os.path.exists(os.path.join(root, f)):
            os.remove(os.path.join(root, f))
    shutil.rmtree(snap["tmp"], ignore_errors=True)


def add(pending_file, root=HERE, fetch=ingest.fetch_embed, save_avatar=True, ohlc=default_ohlc, now=None):
    """Apply a pending preview (one post or a reviewed batch) and nothing else."""
    with open(os.path.join(root, pending_file)) as f:
        pending = json.load(f)
    if pending.get("version") != VERSION:
        raise Refused(f"{pending_file}: not a {VERSION} preview")
    charts = os.path.join(root, "web", "data", "charts.json")
    if sha256_file(charts) != pending["bundle_sha256"]:
        raise Refused("stale preview: web/data/charts.json changed since the preview (a refresh or another add); rerun the preview")
    items = pending["items"]
    for it in items:
        if sha256_file(os.path.join(root, it["receipt"]["file"])) != it["receipt"]["sha256"]:
            raise Refused(f"the receipt {it['receipt']['file']} changed since the preview; rerun the preview")
        rec = it["record"]
        dup = existing_record(root, rec["post"]["id"], rec["asset"]["name"])
        if dup:
            raise Refused(f"duplicate: post {rec['post']['id']} on {rec['asset']['name']} is already recorded in {dup}")
    with open(charts) as f:
        old = json.load(f)
    # step 26: an add that fails after it started writing (a candle fetch, a check) leaves nothing behind:
    # everything it can touch is snapshotted first and put back on any failure
    snap = snapshot(root, [it["record_file"] for it in items])

    def apply():
        registered = []
        for it in items:                                  # step 22: keep the coin identity + checked venue of a new ticker
            tr = it.get("ticker_receipt")
            if tr:
                if receipt_sha(tr) != it["record"]["asset_choice"]["ticker"]["receipt_sha256"]:
                    raise Refused(f"the ticker receipt for {tr['ticker']} does not match its record; rerun the preview")
                have = resolve.registered_tickers(os.path.join(root, "data", "tickers.json")).get(tr["ticker"])
                if have and (have["source"], have["symbol"]) != (it["record"]["asset"]["source"], it["record"]["asset"]["symbol"]):
                    raise Refused(f"{tr['ticker']} is registered on {have['source']}:{have['symbol']}, the preview priced it elsewhere; rerun the preview")
                try:
                    entry = tickers.register(tr, root)
                except ValueError as e:
                    raise Refused(f"ticker {tr['ticker']}: {e}") from e
                registered.append({"ticker": tr["ticker"], "coingecko_id": entry["coingecko_id"], "venue": f"{entry['source']}:{entry['symbol']}", "receipt": entry["receipt"]})
        written = []
        for it in items:
            path = os.path.join(root, it["record_file"])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(it["record"], f, indent=1)
                f.write("\n")
            written.append({"record_file": it["record_file"], "record_sha256": sha256_file(path), "receipt": it["receipt"]})
        avatars, avatar = os.path.join(root, "web", "avatars"), {}
        for a in pending["authors"]:
            avatar[a] = "kept"
            if save_avatar and not os.path.exists(os.path.join(avatars, a.lower() + ".jpg")):
                first = next(it for it in items if it["record"]["post"]["author"] == a)
                try:
                    saved = ingest.save_avatar(fetch(first["record"]["post"]["id"]), avatars)
                    avatar[a] = "saved " + os.path.relpath(saved, root) if saved else "none (no profile picture in the embed): the pages show the initials"
                except (ingest.IngestError, OSError, ValueError) as e:
                    avatar[a] = f"none ({e.__class__.__name__}): the pages show the initials"
        bundle = build_chart.build(os.path.join(root, "records"))
        with open(charts, "w") as f:
            json.dump(bundle, f, indent=1)
            f.write("\n")
        prerender.main(os.path.join(root, "web"))
        candles = {}
        for it in items:
            name = it["record"]["asset"]["name"]
            if ohlc and name not in candles:
                first = min((x["record"]["entry"] or {"at": x["record"]["post"]["posted_at"]})["at"] for x in items if x["record"]["asset"]["name"] == name)
                candles[name] = ohlc(root, name, first)
        after = {a: caller_view(bundle["ratings"], a) for a in pending["authors"]}
        problems = []
        for a in pending["authors"]:
            if after[a] != pending["scores_after"][a]:
                problems.append(f"@{a}: score after the add {after[a]} != previewed {pending['scores_after'][a]}")
        if bundle["ratings"]["order"] != pending["order_after"]:
            problems.append(f"order after the add {bundle['ratings']['order']} != previewed {pending['order_after']}")
        others = {n: c["score"] for n, c in old["ratings"]["callers"].items() if n not in pending["authors"]}
        for n, sc in others.items():
            if bundle["ratings"]["callers"][n]["score"] != sc:
                problems.append(f"@{n} is not in this intake but its score moved: {sc} -> {bundle['ratings']['callers'][n]['score']}")
        moved = frozen_values.compare(frozen_values.frozen(old), frozen_values.frozen(bundle))
        problems += [f"frozen value moved: {m}" for m in moved]
        now_keys = frozen_values.frozen(bundle)
        for it in items:
            key = f"{it['record']['post']['id']}|{it['record']['asset']['name']}"
            if key not in now_keys:
                problems.append(f"{key} is not in the rebuilt bundle")
        log = {"version": VERSION, "added_at": now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "records": written, "bundle_sha256_before": pending["bundle_sha256"], "bundle_sha256_after": sha256_file(charts),
               "avatar": avatar, "candles": candles or "skipped", "tickers_registered": registered, "scores_previewed": pending["scores_after"], "scores_after_add": after,
               "scores_before": pending["scores_before"], "other_callers_unchanged": sorted(others), "frozen_values_checked": len(frozen_values.frozen(old)),
               "matches_preview": not problems, "problems": problems}
        if len(items) == 1:      # the step 16 log fields
            a = pending["authors"][0]
            log.update(url=items[0]["url"], record_file=written[0]["record_file"], record_sha256=written[0]["record_sha256"], receipt=items[0]["receipt"],
                       avatar=avatar[a], candles=next(iter(candles.values()), "skipped"),
                       score_previewed=pending["scores_after"][a], score_after_add=after[a], score_before=pending["scores_before"][a])
        for k in ("scan", "review_file"):
            if k in pending:
                log[k] = pending[k]
        out = os.path.join(root, "intake", "log", os.path.basename(pending_file))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w") as f:
            json.dump(log, f, indent=1, ensure_ascii=False)
            f.write("\n")
        if problems:
            raise Refused("not added: the checks after writing it failed, everything was put back:\n - " + "\n - ".join(problems))
        os.remove(os.path.join(root, pending_file))
        log["log_file"] = os.path.relpath(out, root)
        return log

    try:
        out = apply()
    except BaseException:
        restore(root, snap)
        raise
    shutil.rmtree(snap["tmp"], ignore_errors=True)
    return out


def show_score(v):
    if not v:
        return "not tracked yet"
    return f"{v['display']} (exact {v['score']:.6f}, rank {v['rank']} of {v['of']}, {v['scored']} scored calls{', ' + v['label'] if v['label'] else ''})"


def print_preview(p):
    r = p["record"]
    e, side = r["entry"], {1: "LONG", -1: "SHORT"}.get(r.get("side"), "NO SIDE")
    res = rate.result(r)
    # header first: which post this is (date, author, text), so a preview of the wrong post is obvious
    print(f"📌 POST {r['post']['posted_at'][:16].replace('T', ' ')} UTC · @{p['author']}{' · NEW CALLER' if p['new_caller'] else ''}")
    print(f"   “{' '.join((r['post'].get('text') or '').split())[:160]}”")
    print(f"   {{asset}} {{side}} @ {{entry}}".format(asset=r['asset']['name'], side={1: 'LONG', -1: 'SHORT'}.get(r.get('side'), 'NO SIDE'),
                                                      entry=(f"{r['entry']['price']} ({r['entry']['at'][:16].replace('T', ' ')})" if r.get('entry') else "no price yet")))
    print("─" * 40)
    print(f"post      {p['url']}  @{p['author']}  {r['post']['posted_at']}" + ("  (new caller)" if p["new_caller"] else ""))
    print(f"receipt   {p['receipt']['file']}  sha256 {p['receipt']['sha256']}  {'saved now' if p['receipt']['created'] else 'already saved'}"
          + ("  (text cut by the embed endpoint: textTruncated)" if p["receipt"]["text_truncated"] else ""))
    print(f"text      “{' '.join((r['post'].get('text') or '').split())[:200]}”")
    print(f"asset     {r['asset']['name']} ({r['asset']['source']}:{r['asset']['symbol']}) by {r['asset_choice']['method']} {r['asset_choice']['terms']}"
          + (f" reason: {r['asset_choice']['reason']}" if r['asset_choice'].get('reason') else ""))
    tk = r["asset_choice"].get("ticker")
    if tk:
        print(f"coin      {tk['name']} [{tk['coingecko_id']}] priced on {tk['source']}:{tk['symbol']} (identity + price checked by tickers.py, asked as {tk.get('asked')}, receipt sha256 {tk['receipt_sha256'][:16]}…)")
    lg = r["asset_choice"].get("leg")
    if lg:
        print(f"leg       one of {', '.join(lg['of'])} in this post (each coin is its own record)")
    sc = r["side_choice"]
    print(f"side      {side} by {sc['method']} {sc['terms']}" + (f" reason: {sc['reason']}" if sc.get("reason") else ""))
    if e:
        print(f"entry     {e['price']} @ {e['at']}" + (" (daily bar)" if e.get("interval") == "1d" else "")
              + f"   latest {r['latest']['price']} @ {r['latest']['at']}   status {r['status']}")
    else:
        print(f"entry     none yet: status {r['status']} (no bar after the post: market closed); the daily refresh fills it from the first bar")
    if r["asset_choice"].get("evidence"):
        ev = r["asset_choice"]["evidence"]
        print(f"evidence  {ev['file']} sha256 {ev['sha256']} (image read, confidence {ev.get('confidence')}, suggested {ev.get('suggested')})")
    print(f"result    {resolve.pct(res)} {'for the ' + side.lower() if r.get('side') else 'price move'} since the post"
          + "".join(f"   {h}d {resolve.pct(r['moves'][h]) if r['moves'][h] is not None else 'pending'}" for h in ("1", "7", "30")))
    if p["revisions"]:
        print(f"bars      {len(p['revisions'])} provider revision(s) on shared bars: the bundle's values kept")
    print(f"score now @{p['author']}: {show_score(p['score_before'])}")
    print(f"with this @{p['author']}: {show_score(p['score_after'])}"
          + (f"   delta {p['score_delta']:+.6f}" if p["score_delta"] is not None else ""))
    print(f"order     {' > '.join('@' + n for n in p['order_after'])}")
    print(f"pending   {p['pending_file']}  (bundle sha256 {p['bundle_sha256']})")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url")
    ap.add_argument("--asset", help="asset chosen by hand (needs --reason)")
    ap.add_argument("--side", choices=["long", "short", "none"], help="side chosen by hand (needs --reason)")
    ap.add_argument("--reason", help="why the asset or side was chosen by hand; stored in the record")
    ap.add_argument("--add", action="store_true", help="apply the pending preview for this post")
    ap.add_argument("--pending", action="store_true", help="allow a post with no price after it yet (market closed): the daily refresh fills the entry")
    ap.add_argument("--leg", help="for a post naming several coins: the coin (ticker) to add; each leg is its own record")
    ap.add_argument("--coin", action="append", default=[], metavar="TICKER=COINGECKO_ID",
                    help="step 26: the owner's pick for an ambiguous ticker (two coins share it), e.g. NEST=nest-2; repeatable")
    a = ap.parse_args()
    picks = {}
    for c in a.coin:
        mm = re.fullmatch(r"([A-Za-z0-9]{1,12})=([a-z0-9-]{1,80})", c)
        if not mm:
            print(f"REFUSED   --coin {c!r}: write TICKER=coingecko-id, e.g. NEST=nest-2")
            sys.exit(2)
        picks[mm.group(1).upper()] = mm.group(2)
    try:
        if not a.add:
            p = preview(a.url, asset=a.asset, side=a.side, reason=a.reason, allow_pending=a.pending, leg=a.leg, picks=picks)
            print_preview(p)
            print("PREVIEW ONLY: nothing under web/ or records/ changed. Rerun with --add to publish it.")
            return
        m = resolve.URL_RE.match(a.url or "")
        if not m:
            raise Refused(f"not a post url: {a.url!r}")
        hits = sorted(glob.glob(os.path.join(HERE, "intake", "pending", f"{m.group(2)}_*.json")))
        if a.asset or a.leg:
            want = a.leg.upper() if a.leg else resolve.asset_info(a.asset)["name"]
            hits = [h for h in hits if os.path.basename(h) == file_name(m.group(2), want)]
        if not hits:
            raise Refused("no pending preview for this post: run the preview first")
        if len(hits) > 1:
            raise Refused(f"several pending previews for this post ({[os.path.basename(h) for h in hits]}): pass --leg (or --asset)")
        log = add(os.path.relpath(hits[0], HERE))
        print(f"added     {log['record_file']}  sha256 {log['record_sha256']}")
        print(f"avatar    {log['avatar']}")
        print(f"candles   {log['candles']}")
        print(f"bundle    {log['bundle_sha256_before']} -> {log['bundle_sha256_after']}")
        print(f"score     previewed {show_score(log['score_previewed'])}")
        print(f"          after add {show_score(log['score_after_add'])}")
        print(f"checks    score = preview: yes; frozen values of every other position unchanged: yes; log {log['log_file']}")
    except Refused as e:
        print(f"REFUSED   {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
