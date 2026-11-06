#!/usr/bin/env python3
"""Step 25: the caller watcher. Finds new posts by every tracked caller shortly after they are posted, reads
them with the existing asset and side rules, and queues candidates for the owner's private Telegram review.
It never adds, publishes or pushes anything: the owner's bot shows each candidate and its Add button opens
the normal /add preview.

usage: python3 tools/watch_callers.py cycle              (one cycle; the systemd user timer runs this)
       python3 tools/watch_callers.py context <post id>  (the post and its parents, from the public embed; no search)
       python3 tools/watch_callers.py replay <url> ...   (classify posts fetched from the public embed)
       python3 tools/watch_callers.py report [--hours N]
       python3 tools/watch_callers.py export <dir>

Discovery
  One read-only search per cycle over all callers: `(from:a OR from:b ...) since:<yesterday>`, newest first.
  A SEEN SET over that overlapping window, not a watermark: a post a weak answer left out is found later.
Coverage (fail closed)
  A cycle advances coverage only on a full-strength answer: not an error, not empty unless a canary (step 24:
  all callers' last 7 days in one search, >= half the best canary) says the callers were simply quiet, and at
  least half the usual size. The span between the last covered time and the oldest post of the next strong
  answer, if any, is a GAP: stored until every caller's posts in it were read by bounded per-caller searches
  (`from:h since:d1 until:d2`, halved while capped); a day too busy to cover stays flagged, never dropped.
Durability
  One cycle at a time (flock). Every search is reserved in budget.jsonl before it runs (canary, catch-up and
  failed searches included) and the rolling hourly budget is checked against the reservations. A candidate is
  appended (fsync) before its post is marked seen; state.json is replaced atomically.
State
  outside the repository (QUANTY_WATCH_DIR, default ~/.quanty-watch): state.json, cycles.jsonl,
  candidates.jsonl, budget.jsonl. The bot keeps its own file (cards sent, decisions).
"""
import argparse
import datetime as dt
import fcntl
import glob
import hashlib
import json
import os
import statistics
import sys
import time

TOOLS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TOOLS)
sys.path[:0] = [HERE, TOOLS]
import detect   # noqa: E402
import tickers  # noqa: E402

SCHEMA = "quanty.watch.v1"
DIR = os.environ.get("QUANTY_WATCH_DIR", os.path.expanduser("~/.quanty-watch"))
CARDS = os.environ.get("QUANTY_WATCH_CARDS", os.path.expanduser("~/.quanty-admin/watch_cards.json"))
BUDGET = int(os.environ.get("QUANTY_WATCH_BUDGET", "12"))     # searches per rolling 60 minutes, every kind counted
CAPPED_AT = 40               # an answer this big may have been cut short by X (newest first)
WEAK_SHARE = 0.5             # an answer under half the usual size (median of recent strong answers) is degraded
CANARY_MIN_SHARE = 0.5       # step 24
SEEN_DAYS = 10
CARD_HOURS = 72              # a gap post older than this is still queued, marked late


class Stop(Exception):
    pass


def now_iso(t=None):
    return dt.datetime.fromtimestamp(t if t is not None else time.time(), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(ts):
    return dt.datetime.fromisoformat(ts.replace(".000Z", "Z").replace("Z", "+00:00")).timestamp()


def day(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")


def harness_search(query):
    import scan_caller
    return scan_caller.run_harness(query)


class OfflineNet(tickers.Net):
    """The watcher never asks a price or coin provider: an unregistered ticker is flagged, looked up when added."""
    def get(self, url):
        raise tickers.Unavailable("the watcher does not look up new tickers: it is checked when the post is added")


def callers(root=HERE):
    """The tracked X callers: authors of x.com records."""
    out = set()
    for f in glob.glob(os.path.join(root, "records", "**", "*.json"), recursive=True):
        try:
            with open(f) as fh:
                r = json.load(fh)
        except (OSError, ValueError):
            continue
        u = (r.get("post") or {}).get("url") or ""
        if r.get("schema") == "post_price.v1" and u.startswith(("https://x.com/", "https://twitter.com/")):
            out.add(r["post"]["author"])
    return sorted(out, key=str.lower)


def recorded_ids(root=HERE):
    ids = set()
    for f in glob.glob(os.path.join(root, "records", "**", "*.json"), recursive=True):
        ids.add(os.path.basename(f).split("_")[0])
    return ids


def classify(p, reg=None, amap=None, words=None):
    """One post -> kind, parent, asset legs (each with the side its own words give), flags. Offline."""
    text = p.get("text") or ""
    kind = p.get("kind") or ("reply" if p.get("replyTo") else "quote" if p.get("quoted") else "post")
    parent = None
    if isinstance(p.get("replyTo"), dict):
        parent = {"type": "reply", "id": p["replyTo"].get("postId"), "handle": p["replyTo"].get("handle")}
    elif isinstance(p.get("quoted"), dict):
        q = p["quoted"]
        parent = {"type": "quote", "id": q.get("id"), "handle": q.get("handle") or q.get("authorHandle") or ((q.get("url") or "").split("/")[3:4] or [None])[0]}
    legs = []
    if kind != "repost":
        for l in detect.coin_legs(text, amap=amap, net=OfflineNet(), registry=reg, words=words):
            side, why, sw = detect.leg_side(text, l["via"]) if l["asset"] else (None, None, None)
            legs.append({"asset": l["asset"], "via": l["via"], "status": l["status"],
                         "flag": None if l["status"] == "ok" else (l["reason"] or "needs review"),
                         "side": {1: "long", -1: "short"}.get(side, "none"), "side_words": sw, "side_reason": why})
    return {"kind": kind, "parent": parent, "legs": legs, "candidate": kind != "repost" and bool(legs)}


class Watch:
    def __init__(self, root=HERE, wdir=DIR, search=None, clock=time.time, budget=BUDGET, handles=None):
        self.root, self.dir, self.clock, self.budget = root, wdir, clock, budget
        self.search_fn = search or harness_search
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        self.p = lambda name: os.path.join(self.dir, name)
        self.handles = handles or callers(root)
        self.state = self.load()

    # ---- files -----------------------------------------------------------------------------
    def load(self):
        try:
            with open(self.p("state.json")) as f:
                return json.load(f)
        except FileNotFoundError:
            return {"schema": SCHEMA, "seen": {}, "last_seen": {}, "covered_until": None, "gaps": [], "ok_raw": [],
                    "best_canary": 0, "baseline_done": False, "degraded": None}

    def save(self):
        tmp = self.p("state.json.tmp")
        with open(tmp, "w") as f:
            json.dump(self.state, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.p("state.json"))

    def append(self, name, row):
        path = self.p(name)
        torn = False
        if os.path.exists(path) and os.path.getsize(path):
            with open(path, "rb") as f:
                f.seek(-1, os.SEEK_END)
                torn = f.read(1) != b"\n"                  # a crash mid-write left a partial line: end it first
        with open(path, "a") as f:
            f.write(("\n" if torn else "") + json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def rows(self, name, torn=None):
        """Every complete line; a partial line left by a crash is skipped (and counted in `torn`)."""
        out = []
        try:
            with open(self.p(name), "rb") as f:                # bytes: a torn multi-byte character must not escape
                for l in f:
                    if not l.strip():
                        continue
                    try:
                        out.append(json.loads(l.decode("utf-8")))
                    except ValueError:                         # UnicodeDecodeError is a ValueError too
                        if torn is not None:
                            torn.append(l)
        except FileNotFoundError:
            pass
        return out

    # ---- searches (reserved before they run) -------------------------------------------------
    def used(self):
        """Reservations in the last 60 minutes. A torn reservation (crash while reserving) still counts, at the
        file's modification time: the search may have run."""
        t, torn = self.clock(), []
        n = sum(1 for r in self.rows("budget.jsonl", torn) if t - r["t"] < 3600)
        if torn and t - os.path.getmtime(self.p("budget.jsonl")) < 3600:
            n += len(torn)
        return n

    def search(self, query, purpose, cycle):
        if self.used() >= self.budget:
            raise Stop(f"hourly search budget used ({self.budget}): {purpose} not run")
        self.append("budget.jsonl", {"t": self.clock(), "at": now_iso(self.clock()), "purpose": purpose, "cycle": cycle, "query": query})
        m, run, err = self.search_fn(query)
        return m, run, err

    def canary(self, cycle):
        """step 24: every caller's last 7 days together must still answer (X answers 'no posts' while it throttles)."""
        t = self.clock()
        q = "(" + " OR ".join(f"from:{h}" for h in self.handles) + f") since:{day(t - 7 * 86400)} until:{day(t + 86400)}"
        m, run, err = self.search(q, "canary", cycle)
        n = 0 if err else len((m or {}).get("posts", []))
        self.state["best_canary"] = max(self.state.get("best_canary") or 0, n)
        # 7 days of every caller can never honestly be fewer posts than one usual day: the bar is the larger of both
        usual = statistics.median(self.state["ok_raw"][-12:]) if len(self.state["ok_raw"]) >= 3 else 0
        bar = max(self.state["best_canary"], usual)
        ok = bool(n) and n >= CANARY_MIN_SHARE * bar
        return ok, {"query": q, "run": run, "manifest_sha256": (m or {}).get("_sha256"), "raw": n, "best": self.state["best_canary"],
                    "usual": usual, "ok": ok}

    # ---- posts ---------------------------------------------------------------------------------
    def take(self, posts, cycle, recorded, baseline=False):
        """New posts -> candidates (appended first) -> seen. Returns counts."""
        known = {c["id"] for c in self.rows("candidates.jsonl")}
        reg = tickers.load_registry()
        n = {"new": 0, "candidates": 0, "reposts": 0, "recorded": 0, "no_asset": 0}
        fresh = []
        for p in sorted(posts, key=lambda p: (p.get("postedAt") or "", p["id"])):
            if p["id"] in self.state["seen"]:
                continue
            n["new"] += 1
            fresh.append(p)
            if baseline:
                continue
            c = classify(p, reg=reg)
            if c["kind"] == "repost":
                n["reposts"] += 1
            elif p["id"] in recorded:
                n["recorded"] += 1
            elif not c["candidate"]:
                n["no_asset"] += 1
            elif p["id"] not in known:
                found = self.clock()
                self.append("candidates.jsonl", {
                    "schema": SCHEMA, "id": p["id"], "url": f"https://x.com/{p['authorHandle']}/status/{p['id']}", "handle": p["authorHandle"],
                    "posted_at": p["postedAt"].replace(".000Z", "Z"), "text": p.get("text") or "", **{k: c[k] for k in ("kind", "parent", "legs")},
                    "found_at": now_iso(found), "found_after_s": round(found - parse(p["postedAt"])), "cycle": cycle,
                    "late": found - parse(p["postedAt"]) > CARD_HOURS * 3600, "run": p.get("_run"), "manifest_sha256": p.get("_sha")})
                known.add(p["id"])
                n["candidates"] += 1
        for p in fresh:                                   # after every candidate is on disk
            self.state["seen"][p["id"]] = p.get("postedAt")
            h = p["authorHandle"]
            if int(p["id"]) > int(self.state["last_seen"].get(h) or 0):
                self.state["last_seen"][h] = p["id"]
        return n

    def mine(self, m, run):
        hs = {h.lower() for h in self.handles}
        out = []
        for p in (m or {}).get("posts", []):
            if (p.get("authorHandle") or "").lower() in hs:
                out.append({**p, "_run": run, "_sha": (m or {}).get("_sha256")})
        return out

    # ---- one cycle -----------------------------------------------------------------------------
    def cycle(self):
        lockf = open(self.p("cycle.lock"), "a")
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return {"result": "skipped: another cycle is running"}
        try:
            self.state = self.load()                      # read only while holding the lock: never a stale copy
            return self._cycle()
        finally:
            fcntl.flock(lockf, fcntl.LOCK_UN)
            lockf.close()

    def _cycle(self):
        t0 = self.clock()
        cid = hashlib.sha256(f"{t0}".encode()).hexdigest()[:10]
        log = {"schema": SCHEMA, "cycle": cid, "started": now_iso(t0), "callers": self.handles, "budget": self.budget}
        recorded = recorded_ids(self.root)
        try:
            q = "(" + " OR ".join(f"from:{h}" for h in self.handles) + f") since:{day(t0 - 86400)}"
            log["query"] = q
            m, run, err = self.search(q, "discovery", cid)
            log.update(run=run, manifest_sha256=(m or {}).get("_sha256"))
            if err:
                log.update(result="error (nothing marked, next cycle searches again)", error=str(err)[-300:])
                self.state["degraded"] = "search error"
                return self.finish(log)
            posts = self.mine(m, run)
            log["raw"] = len(posts)
            log["by_caller"] = {h: sum(1 for p in posts if p["authorHandle"].lower() == h.lower()) for h in self.handles}
            if not posts:
                ok, can = self.canary(cid)
                log["canary"] = can
                if not ok:
                    log["result"] = "throttled (canary weak or empty): nothing marked, coverage not advanced"
                    self.state["degraded"] = "throttled"
                    return self.finish(log)
            usual = statistics.median(self.state["ok_raw"][-12:]) if len(self.state["ok_raw"]) >= 3 else None
            strong = not posts or usual is None or len(posts) >= WEAK_SHARE * usual
            if not strong:                                # fewer posts than usual: X degrading, or the callers are quiet
                ok, can = self.canary(cid)
                log["canary"] = can
                strong = ok                               # a strong canary says the low count is real
            log["usual_raw"], log["strength"] = usual, "strong" if strong else "weak"
            baseline = not self.state["baseline_done"]
            log["counts"] = self.take(posts, cid, recorded, baseline=baseline)
            oldest = min((parse(p["postedAt"]) for p in posts), default=None)
            covered_from = (t0 - 86400 if not posts or len(posts) < CAPPED_AT else oldest)   # a small answer covers the whole window
            log["oldest"] = now_iso(oldest) if oldest else None
            if strong:
                prev = self.state["covered_until"]
                if prev and covered_from > parse(prev):
                    gap = {"start": prev, "end": now_iso(covered_from), "opened": now_iso(t0),
                           "callers": {h: [[day(parse(prev)), day(covered_from + 86400)]] for h in self.handles}, "unresolvable": []}
                    self.state["gaps"].append(gap)
                    log["gap_opened"] = {"start": gap["start"], "end": gap["end"]}
                self.state["covered_until"] = now_iso(t0)
                self.state["ok_raw"] = (self.state["ok_raw"] + [len(posts)])[-24:]
                self.state["baseline_done"] = True
                self.state["degraded"] = "open gap" if self.state["gaps"] else None
                log["result"] = "baseline (everything marked seen, no cards)" if baseline else "ok"
            else:
                log["result"] = "weak answer: its posts were read, coverage not advanced"
                self.state["degraded"] = "weak answer"
            self.catch_up(cid, log, recorded, live=strong and bool(posts))
        except Stop as e:
            log.setdefault("result", f"stopped: {e}")
            log["stopped"] = str(e)
        return self.finish(log)

    def catch_up(self, cid, log, recorded, live=False):
        """One bounded per-caller search for the oldest open gap (if the budget allows). An empty answer is vouched
        for by this cycle's strong discovery answer (`live`, seconds earlier), else by its own canary."""
        gaps = self.state["gaps"]
        if not gaps or self.used() >= self.budget:
            return
        g = gaps[0]
        h = next(iter(g["callers"]))
        since, until = g["callers"][h][0][:2]
        q = f"from:{h} since:{since} until:{until}"
        m, run, err = self.search(q, "catch-up", cid)
        step = {"query": q, "run": run, "manifest_sha256": (m or {}).get("_sha256")}
        log["catch_up"] = step
        if err:
            step["result"] = "error (window kept)"
            return
        posts = self.mine(m, run)
        step["raw"] = len(posts)
        if not posts:
            if live:
                step["vouched_by"] = "this cycle's strong discovery answer"
            else:
                ok, can = self.canary(cid)
                step["canary"] = can
                if not ok:
                    step["result"] = "throttled (window kept)"
                    return
        step["counts"] = self.take(posts, cid, recorded)
        start = parse(g["start"])
        oldest = min((parse(p["postedAt"]) for p in posts), default=None)
        wins = g["callers"][h]
        ids = hashlib.sha256(",".join(sorted(p["id"] for p in posts)).encode()).hexdigest()
        if len(posts) < CAPPED_AT or (oldest is not None and oldest <= max(start, parse(since + "T00:00:00Z"))):
            # complete for the window, if X answered fully: closed only when a second search gives the same posts
            if len(wins[0]) > 2 and wins[0][2] == ids:
                wins.pop(0)
                step["result"] = "window covered (two identical answers)"
            else:
                wins[0] = [since, until, ids]
                step["result"] = "window answered once: searched again before it is closed"
        else:
            a, b = parse(since + "T00:00:00Z"), parse(until + "T00:00:00Z")
            days = int((b - a) // 86400)
            if days <= 1:
                wins.pop(0)
                g["unresolvable"].append({"handle": h, "day": since, "why": f"{len(posts)} posts in one day: X caps the answer"})
                step["result"] = "one day too busy to cover: flagged"
            else:
                mid = day(a + (days // 2) * 86400)
                wins[0:1] = [[since, mid], [mid, until]]
                step["result"] = f"capped: split into {since}..{mid} and {mid}..{until}"
        if not wins:
            del g["callers"][h]
        if not g["callers"]:
            gaps.pop(0)
            step["gap_closed"] = {"start": g["start"], "end": g["end"], "unresolvable": g["unresolvable"]}
            self.append("gaps_closed.jsonl", g)
        self.state["degraded"] = "open gap" if gaps else (self.state["degraded"] if self.state["degraded"] != "open gap" else None)

    def finish(self, log):
        t = self.clock()
        cutoff = t - SEEN_DAYS * 86400
        self.state["seen"] = {k: v for k, v in self.state["seen"].items() if not v or parse(v) > cutoff}
        self.save()
        log.update(finished=now_iso(t), searches_last_hour=self.used(), open_gaps=len(self.state["gaps"]), degraded=self.state["degraded"])
        self.append("cycles.jsonl", log)
        return log


# ---- context / replay / report / export ----------------------------------------------------------
def embed_post(pid, fetch=None):
    import ingest
    d = (fetch or ingest.fetch_embed)(pid)
    user = (d.get("user") or {}).get("screen_name") or ""
    p = {"id": str(d.get("id_str") or pid), "authorHandle": user, "postedAt": dt.datetime.strptime(d["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y-%m-%dT%H:%M:%SZ")
         if "T" in (d.get("created_at") or "") else d.get("created_at"), "text": d.get("text") or ""}
    if d.get("in_reply_to_status_id_str"):
        p["kind"], p["replyTo"] = "reply", {"postId": d["in_reply_to_status_id_str"], "handle": d.get("in_reply_to_screen_name")}
    elif d.get("quoted_tweet"):
        q = d["quoted_tweet"]
        p["kind"], p["quoted"] = "quote", {"id": q.get("id_str"), "handle": (q.get("user") or {}).get("screen_name")}
    else:
        p["kind"] = "post"
    return p


def context(pid, fetch=None, depth=3):
    chain, cur = [], pid
    while cur and len(chain) <= depth:
        p = embed_post(cur, fetch)
        chain.append(p)
        cur = (p.get("replyTo") or {}).get("postId") or (p.get("quoted") or {}).get("id")
    return chain


def report(wdir=DIR, cards=CARDS, hours=None):
    w = Watch.__new__(Watch)
    w.dir = wdir
    w.p = lambda name: os.path.join(wdir, name)
    cyc, bud = w.rows("cycles.jsonl"), w.rows("budget.jsonl")
    try:
        with open(cards) as f:
            cd = json.load(f).get("cards", {})
    except (OSError, ValueError):
        cd = {}
    per_hour = {}
    for b in bud:
        per_hour[b["at"][:13]] = per_hour.get(b["at"][:13], 0) + 1
    start = cyc[0]["started"] if cyc else None              # posts from before the watcher started are not a latency
    early = [c for c in cd.values() if start and c.get("posted_at") and c["posted_at"] < start]
    lat = sorted(c["latency_s"] for c in cd.values() if c.get("latency_s") is not None and not c.get("late") and c not in early)
    return {"cycles": len(cyc), "first": cyc[0]["started"] if cyc else None, "last": cyc[-1]["started"] if cyc else None,
            "results": {r: sum(1 for c in cyc if c.get("result", "").split(" ")[0] == r) for r in sorted({c.get("result", "").split(" ")[0] for c in cyc})},
            "throttled_cycles": [c["started"] for c in cyc if c.get("result", "").startswith("throttled")],
            "searches_per_hour": per_hour, "max_searches_in_an_hour": max(per_hour.values(), default=0),
            "candidates": len(w.rows("candidates.jsonl")), "cards_sent": len(cd),
            "decisions": {d: sum(1 for c in cd.values() if c.get("decision") == d) for d in ("add", "skip")},
            "cards_for_posts_before_the_start": len(early),
            "latency_s": {"n": len(lat), "min": lat[0] if lat else None, "median": statistics.median(lat) if lat else None, "max": lat[-1] if lat else None,
                          "within_11_min": sum(1 for x in lat if x <= 660)}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["cycle", "context", "replay", "report", "export"])
    ap.add_argument("args", nargs="*")
    a = ap.parse_args(argv)
    if a.cmd == "cycle":
        out = Watch().cycle()
        print(json.dumps({k: out.get(k) for k in ("cycle", "started", "result", "raw", "strength", "counts", "searches_last_hour", "open_gaps", "degraded")}))
        return 0 if not str(out.get("result", "")).startswith(("error", "throttled")) else 3
    if a.cmd == "context":
        for i, p in enumerate(context(a.args[0])):
            print(("  " * i) + f"{'↳ ' if i else ''}@{p['authorHandle']} {p['postedAt']} ({p['kind']}): {' '.join(p['text'].split())[:400]}\n"
                  + ("  " * i) + f"  https://x.com/{p['authorHandle']}/status/{p['id']}")
        return 0
    if a.cmd == "replay":
        import resolve
        for u in a.args:
            mm = resolve.URL_RE.match(u)
            p = embed_post(mm.group(2))
            c = classify(p)
            print(json.dumps({"url": u, "handle": p["authorHandle"], "posted_at": p["postedAt"], "text": p["text"], **c}, ensure_ascii=False))
        return 0
    if a.cmd == "report":
        print(json.dumps(report(), indent=1))
        return 0
    d = a.args[0]
    os.makedirs(d, exist_ok=True)
    for name in ("cycles.jsonl", "candidates.jsonl", "budget.jsonl", "gaps_closed.jsonl"):
        if os.path.exists(os.path.join(DIR, name)):
            with open(os.path.join(DIR, name)) as f, open(os.path.join(d, name), "w") as g:
                g.write(f.read())
    with open(os.path.join(d, "report.json"), "w") as f:
        json.dump(report(), f, indent=1)
    print(f"exported to {d}")
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    sys.exit(main())
