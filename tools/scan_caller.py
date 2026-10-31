#!/usr/bin/env python3
"""Step 17: scan a caller's last 12 months from one pasted post. Owner-only, local.

  python3 tools/scan_caller.py URL scan       collect the author's own posts of the last 12 months
  python3 tools/scan_caller.py URL report     classify, price and project: report.md / report.json + pending batch
  python3 tools/scan_caller.py URL add        apply the pending batch (tools/add_call.py add: exact score check)

scan: 10-day windows from the cutoff (365 days before the scan started) to the scan date, each one
search "from:<handle> since:<day> until:<day>" through the read-only research harness (it can only
read X: posting, liking, following are blocked by its network guard). One search at a time under
the harness's profile lock, no retries. A run stops itself after BUDGET searches (X allows about 50
per 15 minutes per account), on a rate limit, a login prompt or a harness error, and logs why; the
next run resumes at the first window not done. A window whose oldest post is far from its start
with many posts is split in two (search pages stop scrolling). Every own post in the window is
saved as a receipt (sources/<handle>/receipts/<id>.json, never overwriting one), with the harness
run id and the sha256 of its manifest. Log: intake/scans/<handle>/scan_log.json.

report: every collected post is labelled
  call          one asset (detect.py) and one side (detect.detect_side), and none of the below
  no_call       no asset; an asset without side words (commentary); a question; advice to others;
                someone else's trade (whales, wallets, "he opened"); a joke marker
  needs_review  several assets, both sides, or exit words (a close / trim of an earlier call)
with the matched words. Calls already recorded are listed, not added again. intake/scans/<handle>/
review.json holds the owner's decisions for review items (and skips for calls): {post_id:
{"decision": "add"|"skip", "asset"?, "side"?, "reason": "..."}}; an added review item needs a
reason, which is stored in the record. Calls and reviewed additions are priced with the existing
resolver on shared bars and projected into the bundle exactly as add will build it.
"""
import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TOOLS)
sys.path[:0] = [HERE, TOOLS]
import add_call  # noqa: E402
import classify  # noqa: E402
import detect  # noqa: E402
import rate  # noqa: E402
import resolve  # noqa: E402

VERSION = "quanty.scan.v1"
WINDOW_DAYS = 10
BUDGET = 25                      # searches per run; X allows about 50 per 15 minutes per account
SPLIT_MIN_POSTS = 15
EMPTY_STREAK = 3                 # empty pages in a row = throttling             # a window this full whose oldest post is > 2 days after its start is split
XR = os.environ.get("XR_DIR", "/home/postfiat/xresearch-kit/tools/xresearch")
XR_RUNS = os.path.join(os.path.dirname(os.path.dirname(XR)), "research", "x")

OTHERS = [r"\bwhales?\b", r"\bsmart money\b", r"\b(?:a|this|the|one) (?:trader|gambler|wallet|fund|insider|investor)\b",
          r"\b(?:he|she|they) (?:opened|is|are|went|just)\b", r"\bsomeone\b", r"\bhis (?:long|short)\b"]
ADVICE_MORE = [r"\b(?:don'?t|dont|do not|never)\b (?:panic|sell|buy|chase|short|fomo)", r"^\s*(?:buy|sell|short)\b"]
JOKE = [r"\b(?:lol|lmao|jk|kidding)\b", "😂", "🤣", r"(?:^|\s)/s\b"]


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def scan_dir(root, handle):
    return os.path.join(root, "intake", "scans", handle.lower())


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")


def day(d):
    return d.strftime("%Y-%m-%d")


def windows(start, end, days=WINDOW_DAYS):
    out, t = [], start
    while t < end:
        u = min(t + dt.timedelta(days=days), end)
        out.append({"since": day(t), "until": day(u), "status": "pending"})
        t = u
    return out


def run_harness(query):
    """One read-only search through the research harness -> (manifest dict | None, run id, error text)."""
    env = dict(os.environ, PATH=os.path.expanduser("~/.local/node24/bin") + ":" + os.environ.get("PATH", ""))
    cmd = ["flock", "-w", "240", "/tmp/xresearch-profile.lock", "timeout", "600", "npm", "run", "-s", "xr", "--",
           "search", query, "--depth", "deep", "--slug", "quanty-scan"]
    r = subprocess.run(cmd, cwd=XR, env=env, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    run = next((ln.strip() for ln in reversed(out.splitlines()) if "/research/x/quanty-scan/" in ln), None)
    if r.returncode or not run:
        return None, None, out[-1500:] or f"harness exit {r.returncode}"
    with open(os.path.join(run, "manifest.json"), "rb") as f:
        blob = f.read()
    m = json.loads(blob)
    m["_sha256"] = sha256_bytes(blob)
    m["_run"] = os.path.basename(run)
    return m, m["_run"], None


def stop_reason(err):
    e = (err or "").lower()
    if "429" in e or "rate limit" in e or "too many requests" in e:
        return "rate_limit"
    if "login" in e or "log in" in e or "unusual activity" in e or "verify" in e:
        return "login_required"
    return "harness_error"


def to_receipt(p, m, query):
    """A harness post -> the step 3 receipt format (plus where it came from)."""
    return {"authorHandle": p["authorHandle"], "capturedAt": p.get("capturedAt"), "cashtags": [(h if isinstance(h, str) else h.get("symbol") or h.get("text") or h.get("ticker") or "").upper().lstrip("$") for h in p.get("cashtags") or []],
            "conversationId": p.get("conversationId", p["id"]), "dataSource": "graphql (x-research harness, read-only)", "id": p["id"],
            "kind": p.get("kind"), "metrics": {k: (p.get("metrics") or {}).get(k) for k in ("likes", "replies", "reposts", "views")},
            "postedAt": p["postedAt"], "replyTo": p.get("inReplyToId") or p.get("replyTo"), "text": p.get("text") or "",
            "textTruncated": p.get("completeness") not in (None, "complete"), "url": f"https://x.com/{p['authorHandle']}/status/{p['id']}",
            "harness": {"run": m["_run"], "manifest_sha256": m["_sha256"], "query": query}}


def scan(url, root=HERE, harness=run_harness, budget=BUDGET, now=None):
    m = resolve.URL_RE.match(url or "")
    if not m:
        raise add_call.Refused(f"not a post url: {url!r}")
    handle = m.group(1)
    d = scan_dir(root, handle)
    log_path = os.path.join(d, "scan_log.json")
    log = load_json(log_path)
    now = now or dt.datetime.now(dt.timezone.utc)
    if not log:
        end = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = now - dt.timedelta(days=365)
        log = {"version": VERSION, "handle": handle, "seed_url": url, "started_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "cutoff": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"), "window_days": WINDOW_DAYS, "budget_per_run": budget,
               "windows": windows(cutoff.replace(hour=0, minute=0, second=0, microsecond=0), end), "runs": [], "posts": {}}
    run = {"started_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "searches": 0, "stop": None}
    streak = []
    log["runs"].append(run)
    i = 0
    while i < len(log["windows"]):
        w = log["windows"][i]
        if w["status"] in ("done", "split") or (w["status"] == "empty_once" and len(log["runs"]) in w.get("empty_runs", [])):
            i += 1
            continue
        if run["searches"] >= budget:
            run["stop"] = {"reason": "budget", "note": f"{budget} searches this run (X allows about 50 per 15 minutes); rerun to resume", "at_window": w["since"]}
            break
        query = f"from:{handle} since:{w['since']} until:{w['until']}"
        man, rid, err = harness(query)
        run["searches"] += 1
        if man is None:
            w["status"] = "stopped"
            run["stop"] = {"reason": stop_reason(err), "note": err[-400:], "at_window": w["since"]}
            break
        if not man["posts"]:
            # X answers a throttled account with empty pages, so an empty page is never taken as
            # "no posts" on its own: 3 empty windows in a row stop the run (they are searched again
            # next run); a single empty window is confirmed only when a later run sees it empty too.
            w["empty_runs"] = sorted(set(w.get("empty_runs", [])) | {len(log["runs"])})
            w.update(run=rid, manifest_sha256=man["_sha256"], query=query, posts_seen=0, own_posts=0)
            if len(w["empty_runs"]) >= 2:
                w["status"], w["note"] = "done", "empty in two separate runs: no posts in this window"
                streak = []
                save_json(log_path, log)
                i += 1
                continue
            w["status"] = "empty_once"
            streak.append(w)
            if len(streak) >= EMPTY_STREAK:
                for x in streak:
                    x["status"] = "pending"
                run["stop"] = {"reason": "empty_result", "note": f"{len(streak)} empty pages in a row from {streak[0]['since']}: X throttling; they are searched again next run",
                               "at_window": streak[0]["since"]}
                save_json(log_path, log)
                break
            save_json(log_path, log)
            i += 1
            continue
        streak = []
        own = [p for p in man["posts"] if p["authorHandle"].lower() == handle.lower() and w["since"] <= p["postedAt"][:10] < w["until"]
               and p["postedAt"] >= log["cutoff"]]
        w.update(run=rid, manifest_sha256=man["_sha256"], query=query, posts_seen=len(man["posts"]), own_posts=len(own),
                 oldest=min((p["postedAt"] for p in own), default=None), newest=max((p["postedAt"] for p in own), default=None))
        gap = own and (dt.datetime.strptime(w["oldest"][:10], "%Y-%m-%d") - dt.datetime.strptime(w["since"], "%Y-%m-%d")).days > 2
        span = (dt.datetime.strptime(w["until"], "%Y-%m-%d") - dt.datetime.strptime(w["since"], "%Y-%m-%d")).days
        if gap and len(own) >= SPLIT_MIN_POSTS and span > 2:
            mid = dt.datetime.strptime(w["since"], "%Y-%m-%d") + dt.timedelta(days=span // 2)
            w["status"], w["note"] = "split", f"{len(own)} posts but the oldest is {w['oldest'][:10]}: the page stopped scrolling; searched again in two halves"
            log["windows"][i + 1:i + 1] = [{"since": w["since"], "until": day(mid), "status": "pending"}, {"since": day(mid), "until": w["until"], "status": "pending"}]
            i += 1
            continue
        for p in own:
            rpath = os.path.join(root, "sources", handle.lower(), "receipts", f"{p['id']}.json")
            existing = None
            for cand in glob.glob(os.path.join(root, "sources", "*", "receipts", f"{p['id']}.json")):
                existing = cand
            if resolve.snowflake_time(p["id"]) != p["postedAt"][:19] + "Z":
                log["posts"][p["id"]] = {"skipped": "post time does not match its id"}
                continue
            if not existing:
                save_json(rpath, to_receipt(p, man, query))
                existing = rpath
            with open(existing, "rb") as f:
                blob = f.read()
            log["posts"][p["id"]] = {"postedAt": p["postedAt"], "kind": p.get("kind"), "receipt": os.path.relpath(existing, root),
                                     "receipt_sha256": sha256_bytes(blob), "window": w["since"], "run": rid}
        w["status"] = "done"
        save_json(log_path, log)          # after every window: a crash or stop resumes here
        i += 1
    if not run["stop"]:
        unconfirmed = [w["since"] for w in log["windows"] if w["status"] == "empty_once"]
        run["stop"] = ({"reason": "complete", "note": "every window searched"} if not unconfirmed else
                       {"reason": "unconfirmed_empty", "note": f"{len(unconfirmed)} single empty window(s) {unconfirmed[:5]}: rerun to confirm them"})
    run["finished_at"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    done = [w for w in log["windows"] if w["status"] == "done"]
    log["coverage"] = {"windows_done": len(done), "windows_left": len([w for w in log["windows"] if w["status"] in ("pending", "stopped", "empty_once")]),
                       "windows_split": len([w for w in log["windows"] if w["status"] == "split"]), "posts": len(log["posts"]),
                       "first_post": min((p["postedAt"] for p in log["posts"].values() if "postedAt" in p), default=None),
                       "last_post": max((p["postedAt"] for p in log["posts"].values() if "postedAt" in p), default=None),
                       "empty_windows": [w["since"] for w in done if not w.get("own_posts")]}
    save_json(log_path, log)
    return log


def label_post(text, kind=None):
    """-> {"label": call | no_call | needs_review, "reason", "asset", "side", "terms"}"""
    text = text or ""
    d = detect.detect(text)
    s = detect.detect_side(text)
    terms = {"assets": [m["term"] for m in d["matched"]], "long": s["terms"][1], "short": s["terms"][-1]}
    out = lambda lab, why, asset=None, side=None: {"label": lab, "reason": why, "asset": asset, "side": side, "terms": terms}
    assets = sorted({m["asset"] for m in d["matched"]})
    if not assets:
        return out("no_call", "no asset named")
    hit = lambda pats: [x for p in pats for x in re.findall(p, text, re.I)]
    if hit(JOKE):
        return out("no_call", f"joke marker {hit(JOKE)[:3]}")
    if hit(classify.ADVICE) or hit(ADVICE_MORE):
        return out("no_call", f"advice to others {(hit(classify.ADVICE) + hit(ADVICE_MORE))[:3]}")
    if hit(OTHERS):
        return out("no_call", f"someone else's trade {hit(OTHERS)[:3]}")
    stripped = text.strip()
    if stripped.endswith("?") and s["status"] != "detected":
        return out("no_call", "a question")
    if s["status"] == "none":
        return out("no_call", f"names {', '.join(assets)} without side words (commentary)")
    if len(assets) > 1 or d["status"] != "detected":
        return out("needs_review", f"several assets {assets}" + (f" / {d['reason']}" if d.get("reason") else ""), None, s["side"])
    if s["status"] == "ambiguous":
        return out("needs_review", "states both sides", assets[0])
    exits = hit(classify.CLOSE) + hit(classify.TRIM)
    if exits:
        return out("needs_review", f"exit words {exits[:3]}: may close or trim an earlier call", assets[0], s["side"])
    if stripped.endswith("?"):
        return out("needs_review", "a question with side words", assets[0], s["side"])
    return out("call", "one asset and one side", assets[0], s["side"])


def report(url, root=HERE, prices=None, now=None):
    handle = resolve.URL_RE.match(url).group(1)
    d = scan_dir(root, handle)
    log = load_json(os.path.join(d, "scan_log.json"))
    if not log:
        raise add_call.Refused("no scan yet: run the scan first")
    review = load_json(os.path.join(d, "review.json"), {})
    prices = prices or resolve.Prices()
    blob, bundle = add_call.load_bundle(root)
    rows, items = [], []
    for pid, meta in sorted(log["posts"].items(), key=lambda kv: kv[1].get("postedAt", "")):
        if "receipt" not in meta:
            continue
        rec = load_json(os.path.join(root, meta["receipt"]))
        lab = label_post(rec.get("text"), meta.get("kind"))
        row = {"id": pid, "posted_at": meta["postedAt"], "kind": meta.get("kind"), "url": rec["url"], "receipt": meta["receipt"],
               "receipt_sha256": meta["receipt_sha256"], "text": " ".join((rec.get("text") or "").split())[:280], **lab}
        rv = review.get(pid)
        if rv:
            row["review"] = rv
        tracked = sorted(os.path.relpath(x, root) for x in glob.glob(os.path.join(root, "records", "**", f"{pid.replace(':', '-')}_*.json"), recursive=True))
        if tracked:
            row["already_recorded"] = tracked
        wants = (lab["label"] == "call" and not (rv and rv.get("decision") == "skip")) or (rv and rv.get("decision") == "add")
        if rv and rv.get("decision") in ("add", "skip") and not (rv.get("reason") or "").strip():
            raise add_call.Refused(f"review.json {pid}: a {rv['decision']} decision needs a written reason")
        if lab["label"] == "call" or (rv and rv.get("decision") == "add"):
            asset = (rv or {}).get("asset") or lab["asset"]
            if asset:
                dup = add_call.existing_record(root, pid, resolve.asset_info(asset)["name"])
                if dup:
                    row["status"], wants = f"already recorded ({dup})", False
        if wants:
            try:
                kw = {}
                if rv and rv.get("decision") == "add":
                    kw = {"asset": rv.get("asset"), "side": rv.get("side"), "reason": "reviewed: " + rv["reason"]}
                    if not kw["asset"]:
                        kw.pop("asset")
                    if not kw["side"]:
                        kw.pop("side")
                it = add_call.build_item(rec["url"], root, None, prices, bundle, now=now, **kw)
                r = it["record"]
                row.update(status="to add", asset=r["asset"]["name"], side=r["side"], entry=r["entry"], latest=r["latest"],
                           result=rate.result(r), moves=r["moves"], record_file=it["record_file"])
                items.append(it)
            except add_call.Refused as e:
                row["status"] = f"not added: {e}"
        elif tracked and "status" not in row:
            row["status"] = f"already recorded ({', '.join(tracked)})"
        else:
            row.setdefault("status", "skipped by review" if rv and rv.get("decision") == "skip" else lab["label"].replace("_", " "))
        rows.append(row)
    counts = {k: sum(1 for r in rows if r["label"] == k) for k in ("call", "no_call", "needs_review")}
    already = sum(1 for r in rows if r.get("already_recorded"))
    pend = None
    if items:
        pend = add_call.project(items, root, blob, f"scan-{handle.lower()}.json", now, extra={"scan": os.path.relpath(os.path.join(d, "scan_log.json"), root),
                                                                                            "review_file": os.path.relpath(os.path.join(d, "review.json"), root)})
    out = {"version": VERSION, "handle": handle, "generated_at": (now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
           "bundle_sha256": add_call.sha256_file(os.path.join(root, "web", "data", "charts.json")), "coverage": log.get("coverage"),
           "counts": counts, "to_add": len(items), "already_recorded": already, "score_before": pend and pend["scores_before"].get(handle) or (bundle["ratings"]["callers"].get(handle) and add_call.caller_view(bundle["ratings"], handle)),
           "score_projected": pend and pend["scores_after"].get(handle), "order_projected": pend and pend["order_after"],
           "pending_file": pend and pend["pending_file"], "posts": rows}
    save_json(os.path.join(d, "report.json"), out)
    with open(os.path.join(d, "report.md"), "w") as f:
        f.write(report_md(out))
    return out


def pct(x):
    return "–" if x is None else f"{x * 100:+.2f}%"


def report_md(r):
    c, sb, sp = r["coverage"] or {}, r["score_before"], r["score_projected"]
    lines = [f"# Draft caller report: @{r['handle']} (not published)", "",
             f"Generated {r['generated_at']} from the scan log; bundle sha256 `{r['bundle_sha256']}`.", "",
             f"- Posts collected: {c.get('posts')} ({c.get('first_post')} → {c.get('last_post')}); windows done {c.get('windows_done')}, left {c.get('windows_left')}, split {c.get('windows_split')}",
             f"- Labels: {r['counts']['call']} call, {r['counts']['needs_review']} needs review, {r['counts']['no_call']} no call; {r['to_add']} to add; {r['already_recorded']} already recorded",
             f"- Score now: {add_call.show_score(sb)}", f"- Score with these calls: {add_call.show_score(sp)}", "",
             "## Calls to add", "", "| Posted | Asset | Side | Entry | Result | 1d | 7d | 30d | Post |", "|---|---|---|---|---|---|---|---|---|"]
    for p in r["posts"]:
        if p.get("status") == "to add":
            side = {1: "LONG", -1: "SHORT"}.get(p["side"], "NO SIDE")
            lines.append(f"| {p['posted_at'][:16]} | {p['asset']} | {side} | {p['entry']['price']} @ {p['entry']['at'][:16]} | {pct(p['result'])} | "
                         + " | ".join(pct(p["moves"][h]) for h in ("1", "7", "30")) + f" | [{p['id']}]({p['url']}) |")
    lines += ["", "## Every post", "", "| Posted | Label | Status | Why | Words | Text |", "|---|---|---|---|---|---|"]
    for p in r["posts"]:
        words = ", ".join(p["terms"]["assets"][:3] + p["terms"]["long"][:2] + p["terms"]["short"][:2])
        txt = p["text"][:120].replace("|", "/")
        lines.append(f"| [{p['posted_at'][:16]}]({p['url']}) | {p['label']} | {p.get('status', '')} | {p['reason']}"
                     + (f"; review: {p['review'].get('decision')} ({p['review'].get('reason')})" if p.get("review") else "") + f" | {words} | {txt} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url")
    ap.add_argument("action", choices=["scan", "report", "add"])
    ap.add_argument("--budget", type=int, default=BUDGET)
    a = ap.parse_args()
    try:
        if a.action == "scan":
            log = scan(a.url, budget=a.budget)
            run, c = log["runs"][-1], log["coverage"]
            print(f"scan @{log['handle']} since {log['cutoff'][:10]}: {run['searches']} searches this run, stop: {run['stop']['reason']} ({run['stop']['note'][:160]})")
            print(f"coverage: {c['windows_done']} windows done, {c['windows_left']} left, {c['windows_split']} split; {c['posts']} own posts {c['first_post']} -> {c['last_post']}")
            print(f"log: {os.path.relpath(os.path.join(scan_dir(HERE, log['handle']), 'scan_log.json'), HERE)}")
        elif a.action == "report":
            r = report(a.url)
            print(f"report @{r['handle']}: {r['counts']} · to add {r['to_add']}")
            print(f"score now      {add_call.show_score(r['score_before'])}")
            print(f"with the calls {add_call.show_score(r['score_projected'])}")
            print(f"order          {' > '.join('@' + n for n in (r['order_projected'] or []))}")
            print(f"files          intake/scans/{r['handle'].lower()}/report.md, report.json; pending {r['pending_file']}")
            print("NOT PUBLISHED: nothing under web/ or records/ changed. Run 'add' to publish the batch.")
        else:
            handle = resolve.URL_RE.match(a.url).group(1)
            pf = os.path.join("intake", "pending", f"scan-{handle.lower()}.json")
            if not os.path.exists(os.path.join(HERE, pf)):
                raise add_call.Refused("no pending batch: run the report first")
            log = add_call.add(pf)
            for name, v in log["scores_after_add"].items():
                print(f"@{name}: previewed {add_call.show_score(log['scores_previewed'][name])}")
                print(f"{' ' * len(name)}  after add {add_call.show_score(v)}")
            print(f"records added {len(log['records'])}; bundle {log['bundle_sha256_before']} -> {log['bundle_sha256_after']}")
            print(f"other callers unchanged: {', '.join('@' + n for n in log['other_callers_unchanged'])}; frozen values checked {log['frozen_values_checked']}, moved 0")
            print(f"candles: {log['candles']}")
            print(f"log {log['log_file']}")
    except add_call.Refused as e:
        print(f"REFUSED   {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
