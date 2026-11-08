#!/usr/bin/env python3
"""Step 27: the owner's decisions as labelled examples, the reader's agreement with them, and the gate that
turns corrections into rules. Score-neutral: nothing here reads into or writes a record.

usage: python3 tools/labels.py build      (derive labels from every source; new ones are added, existing ones must match)
       python3 tools/labels.py gate       (evaluate every candidate rule, keep only the ones that pass; writes data/rules.json)
       python3 tools/labels.py report     (web/data/agreement.json + web/agreement.html)

Sources (each label keeps where it came from, with a hash of the decision-relevant content):
  record    a call the owner added (records/**, x.com posts): side as read ("detector" / "detector-leg" = accepted as-is),
            changed ("manual", with the written reason), a coin picked ("(owner pick)"); records from before step 16 are curated.
  scan      a /review decision on a scan (intake/scans/<handle>/report.json): the scanner's stored first read (call / no_call
            + side) and the owner's add / skip with its reason.
  watcher   a watcher card (~/.quanty-watch/candidates.jsonl) and the owner's Add / Skip (~/.quanty-admin/watch_cards.json):
            that state lives outside the repository, so the label keeps a copy of the card and its hash.
Pinning (tamper): a label's post text, first read and owner decision are pinned with a sha256 when it is first made. A rebuild
that derives anything different for an existing label stops with the conflict; two sources disagreeing on one decision stop too.
Gating: an add counts with its side; a skip counts as "no side" only when its written reason says so (SKIP_NO_SIDE phrases);
a skip without such a reason (a repeat, a watcher Skip) and an add that could not be priced are labels but not gate evidence.
Rules (data/rules.json): a kept rule is bound to the sha256 of its code (tools/reader.py) and to the labels it was verified
against; the reader applies it only while both still match (fail closed). A build re-verifies kept rules on the new labels.
"""
import argparse
import collections
import datetime as dt
import glob
import hashlib
import html
import inspect
import json
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TOOLS)
sys.path[:0] = [HERE, TOOLS]
import reader  # noqa: E402

SCHEMA = "quanty.label.v1"
WATCH = os.environ.get("QUANTY_WATCH_DIR", os.path.expanduser("~/.quanty-watch"))
CARDS = os.environ.get("QUANTY_WATCH_CARDS", os.path.expanduser("~/.quanty-admin/watch_cards.json"))
import re  # noqa: E402
# a skip is evidence of "no side" only when its written reason says so in so many words (whole words; "unconditional" is not
# "conditional"), and never when the reason is (also) that the post repeats an earlier call
SKIP_NO_SIDE = (r"\bno (?:clear )?side\b", r"\btakes no position\b", r"\bconditional\b", r"\bpossibilities only\b", r"\bhedged\b")
REPEAT = re.compile(r"\brepeat", re.I)
SIDE = {1: "long", -1: "short", None: "none"}
e = lambda s: html.escape(str(s), quote=True)


class Conflict(Exception):
    pass


def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(path + ".tmp", path)


def rows(path):
    out = []
    try:
        with open(path, "rb") as f:
            for l in f:
                try:
                    out.append(json.loads(l.decode("utf-8")))
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return out


def skip_basis(reason):
    r = reason or ""
    if REPEAT.search(r):
        return None
    m = next((m for m in (re.search(p, r, re.I) for p in SKIP_NO_SIDE) if m), None)
    return m.group(0) if m else None


# ---- sources ---------------------------------------------------------------------------------------
def from_records(root):
    out = []
    for f in sorted(glob.glob(os.path.join(root, "records", "**", "*.json"), recursive=True)):
        r = load(f)
        if not r or r.get("schema") != "post_price.v1" or not r["post"]["url"].startswith("https://x.com/"):
            continue
        ac, sc = r.get("asset_choice") or {}, r.get("side_choice") or {}
        aliases = [r["asset"]["name"].split(":")[-1]] + [t.lstrip("$") for t in ac.get("terms") or [] if len(t) < 40]
        multi = bool(ac.get("leg"))
        method = {"detector": "as read", "detector-leg": "as read", "manual": "changed", "none": "as read", "rule": "as read"}.get(sc.get("method"), "curated")
        pick = (ac.get("ticker") or {}).get("asked", "")
        decision = {"decision": "add", "asset": r["asset"]["name"], "side": SIDE[r.get("side")], "method": method,
                    "reason": sc.get("reason") if method == "changed" else (ac.get("reason") if ac.get("method") == "manual" else None),
                    "asset_pick": pick.split("= ", 1)[1].split(" ")[0] if "(owner pick)" in pick else None}
        src = {"type": "record", "file": os.path.relpath(f, root),
               "decision_sha256": sha({k: r.get(k) for k in ("post", "asset", "side", "side_choice", "asset_choice")})}
        out.append({"key": f'{r["post"]["id"]}|{r["asset"]["name"]}', "post": {k: r["post"].get(k) for k in ("id", "url", "author", "posted_at", "text")},
                    "aliases": aliases, "multi": multi, "owner": decision, "first_read": None, "source": src})
    return out


def from_scans(root):
    out = []
    for f in sorted(glob.glob(os.path.join(root, "intake", "scans", "*", "report.json"))):
        rep = load(f)
        for p in rep["posts"]:
            rv = p.get("review")
            if not rv:
                continue
            asset = rv.get("asset") or (p.get("asset") if rv["decision"] == "add" else None)
            side = rv.get("side") if rv["decision"] == "add" else None
            first = {"call": p["label"] == "call", "asset": p.get("asset"), "side": SIDE.get(p.get("side")) if p["label"] == "call" else "none",
                     "from": "the scan's stored read"}
            decision = {"decision": rv["decision"], "asset": asset, "side": side if rv["decision"] == "add" else None,
                        "method": "review", "reason": rv.get("reason"), "asset_pick": None}
            aliases = [asset or p.get("asset") or ""] + [t.lstrip("$") for t in p.get("terms") or [] if len(t) < 40]
            out.append({"key": f'{p["id"]}|{asset or "-"}', "post": {"id": p["id"], "url": p["url"], "author": rep["handle"], "posted_at": p["posted_at"], "text": p["text"]},
                        "aliases": [a for a in aliases if a], "multi": False, "owner": decision, "first_read": first,
                        "source": {"type": "scan", "file": os.path.relpath(f, root), "entry_sha256": sha(p)}})
    return out


def from_watcher(cards_path=CARDS, watch_dir=WATCH):
    cards = (load(cards_path, {}) or {}).get("cards", {})
    cands = {c["id"]: c for c in rows(os.path.join(watch_dir, "candidates.jsonl"))}
    out = []
    for pid, card in sorted(cards.items()):
        c = cands.get(pid)
        if not c or card.get("decision") not in ("add", "skip"):
            continue
        copy = {"card": {k: card.get(k) for k in ("url", "handle", "posted_at", "sent_at", "decision", "decided_at")},
                "candidate": {k: c.get(k) for k in ("id", "url", "handle", "posted_at", "text", "kind", "parent", "legs", "found_at")}}
        legs = c["legs"]
        for l in legs:
            # a coin the watcher could not resolve yet is named by its cashtag ($NEST -> NEST), so the card's label
            # meets the record the owner's Add created for that coin
            asset = l.get("asset") or next((v.lstrip("$").upper() for v in l.get("via") or [] if v.startswith("$")), None)
            first = {"call": l.get("side") in ("long", "short"), "asset": asset, "side": l.get("side") or "none", "from": "the watcher card"}
            decision = {"decision": card["decision"], "asset": asset if card["decision"] == "add" else None, "side": None, "method": "watcher",
                        "reason": None, "asset_pick": None}
            out.append({"key": f'{pid}|{asset or "-"}' if card["decision"] == "add" else f"{pid}|-",
                        "post": {"id": pid, "url": c["url"], "author": c["handle"], "posted_at": c["posted_at"], "text": c["text"]},
                        "aliases": [asset or ""] + [v.lstrip("$") for v in l.get("via") or []], "multi": len(legs) > 1,
                        "owner": decision, "first_read": first, "source": {"type": "watcher", "copy": copy, "copy_sha256": sha(copy)}})
            if card["decision"] == "skip":
                break                                      # one skip label per post
        if card["decision"] == "add" and not any(l.get("asset") or l.get("via") for l in legs):
            continue
    return out


# ---- merge + pin -----------------------------------------------------------------------------------
def kind_of(lb):
    o, fr = lb["owner"], lb["first_read"]
    read = fr["side"] if fr else None
    if o["decision"] == "skip":
        if not lb["gating"]:
            return "skipped (no stated reason to read it as no side)" if o["method"] == "watcher" else "skip_repeat_or_other"
        return "false_call" if read in ("long", "short") else "agree_no_side"
    if o.get("side") is None:
        return "add_refused"
    if read is None:
        return "accepted_as_read" if o["method"] == "as read" else "curated"
    if read == o["side"]:
        return "agree"
    if read == "none":
        return "missed_call" if fr and not fr.get("asset") else "side_added"
    if o["side"] == "none":
        return "side_removed"
    return "side_flipped"


def derive(root, cards_path=CARDS, watch_dir=WATCH):
    by = collections.OrderedDict()
    for lb in from_scans(root) + from_records(root) + from_watcher(cards_path, watch_dir):
        k = lb["key"]
        if k not in by:
            by[k] = {**lb, "sources": [lb.pop("source")]}
            continue
        have = by[k]
        # the scan collapses whitespace and X search cuts long posts short: the words must match, one may be a cut-off copy
        a, b = " ".join(have["post"]["text"].split()), " ".join(lb["post"]["text"].split())
        if not (a == b or a.startswith(b) or b.startswith(a)):
            raise Conflict(f"{k}: {have['sources'][0]['type']} and {lb['source']['type']} hold different post texts")
        if lb["source"]["type"] == "record":
            have["post"] = lb["post"]                     # the record's receipt text is the authority (exact whitespace)
        o1, o2 = have["owner"], lb["owner"]
        if o1["decision"] != o2["decision"] or (o1.get("side") and o2.get("side") and o1["side"] != o2["side"]):
            raise Conflict(f"{k}: {have['sources'][0]['type']} says {o1['decision']} {o1.get('side')}, {lb['source']['type']} says {o2['decision']} {o2.get('side')}")
        # the record is the authority for what was added; the scan / card keeps the stored first read
        if lb["source"]["type"] == "record":
            have["owner"] = {**o2, "reason": o2.get("reason") or o1.get("reason"),
                             "method": o1["method"] if o1["method"] in ("review", "watcher") and o2["method"] != "changed" else o2["method"]}
            have["aliases"], have["multi"] = lb["aliases"], lb["multi"]
        if not have.get("first_read") and lb.get("first_read"):
            have["first_read"] = lb["first_read"]
        have["sources"].append(lb["source"])
    out = []
    for k, lb in by.items():
        if not lb.get("first_read"):                       # no stored read: the base reader's read, pinned when the label is made
            r = reader.read(lb["post"]["text"], lb["aliases"], lb["multi"], rules=[])
            lb["first_read"] = {"call": r["side"] is not None, "asset": lb["owner"].get("asset"), "side": SIDE[r["side"]],
                                "from": "the base reader when the label was made"}
        o = lb["owner"]
        lb["gating"] = (o["decision"] == "add" and o.get("side") is not None) or (o["decision"] == "skip" and bool(skip_basis(o.get("reason"))))
        lb["skip_basis"] = skip_basis(o.get("reason")) if o["decision"] == "skip" else None
        lb["kind"] = kind_of(lb)
        out.append(lb)
    return out


def pin_view(lb):
    return {"text": lb["post"]["text"], "first_read": lb["first_read"], "owner": lb["owner"]}


def build(root=HERE, cards_path=CARDS, watch_dir=WATCH):
    path = os.path.join(root, "data", "labels.json")
    have = {l["id"]: l for l in (load(path, {"labels": []}) or {"labels": []})["labels"]}
    new, conflicts = [], []
    for lb in derive(root, cards_path, watch_dir):
        lid = lb.pop("key")
        pinned = sha(pin_view(lb))
        if lid in have:
            old = have[lid]
            # the text and the owner's decision must always match; the first read only when it comes from the same place
            # (the watcher's state is not in a fresh clone: its stored read stays pinned and is not re-derived there)
            same_read = lb["first_read"]["from"] != old["first_read"]["from"] or lb["first_read"] == old["first_read"]
            if lb["post"]["text"] != old["post"]["text"] or lb["owner"] != old["owner"] or not same_read:
                conflicts.append(f"{lid}: derived {pinned[:12]}, pinned {old['pinned_sha256'][:12]}")
                continue
            have[lid]["sources"] = sorted({json.dumps(s, sort_keys=True) for s in have[lid]["sources"] + lb["sources"]})
            have[lid]["sources"] = [json.loads(s) for s in have[lid]["sources"]]
            for k in ("gating", "skip_basis", "kind"):        # derived, not pinned: recomputed with the current rules for reading a label
                have[lid][k] = lb[k]
            continue
        have[lid] = {"schema": SCHEMA, "id": lid, **lb, "pinned_sha256": pinned, "labelled_at": now_iso()}
        new.append(lid)
    if conflicts:
        raise Conflict("a source no longer matches its pinned label (nothing written):\n" + "\n".join(conflicts))
    labels = sorted(have.values(), key=lambda l: (l["post"]["posted_at"], l["id"]))
    for l in labels:                                       # a pinned label must still hash to its pin
        if sha(pin_view(l)) != l["pinned_sha256"]:
            raise Conflict(f"{l['id']}: edited after pinning")
    save(path, {"schema": "quanty.labels.v1", "count": len(labels), "labels": labels})
    verify_kept(root)
    return labels, new


# ---- reading + agreement ---------------------------------------------------------------------------
def read_label(lb, rules):
    r = reader.read(lb["post"]["text"], lb["aliases"], lb["multi"], rules=rules)
    return {"side": SIDE[r["side"]], "method": r["method"], "rule": r["rule"], "words": r["words"]}


def agrees(lb, read):
    o = lb["owner"]
    want = o["side"] if o["decision"] == "add" else "none"
    return read["side"] == want


def agreement(labels, rules):
    g = [l for l in labels if l["gating"]]
    per = {l["id"]: agrees(l, read_label(l, rules)) for l in g}
    return {"n": len(g), "agree": sum(per.values()), "rate": round(sum(per.values()) / len(g), 4) if g else None}, per


def labels_sha(labels):
    return reader.corpus_sha(labels)


def code_sha(rid):
    return reader.code_sha(rid)


def gate(root=HERE):
    """Every candidate in order: keep it iff agreement rises and no label that agreed before disagrees after."""
    labels = load(os.path.join(root, "data", "labels.json"))["labels"]
    kept, results = [], []
    for rid in reader.ORDER:
        before, pb = agreement(labels, kept)
        after, pa = agreement(labels, kept + [rid])
        worse = sorted(k for k in pb if pb[k] and not pa[k])
        fixed = sorted(k for k in pb if not pb[k] and pa[k])
        fires = [l["id"] for l in labels if read_label(l, kept + [rid])["rule"] == rid]
        ok = after["agree"] > before["agree"] and not worse
        results.append({"rule": rid, "doc": (reader.CANDIDATES[rid].__doc__ or "").strip(), "code_sha256": code_sha(rid),
                        "before": before, "after": after, "fixed": fixed, "worsened": worse, "fires_on": fires,
                        "decision": "kept" if ok else "rejected",
                        "why": ("agreement " + f"{before['agree']}/{before['n']} -> {after['agree']}/{after['n']}, no label worse") if ok else
                               (f"{len(worse)} label(s) that agreed would disagree" if worse else "agreement does not rise")})
        if ok:
            kept.append(rid)
    ls = labels_sha(labels)
    doc = {"schema": "quanty.rules.v1", "gated_at": now_iso(), "labels_sha256": ls, "label_count": len(labels),
           "kept": kept, "bindings": {rid: {"code_sha256": code_sha(rid), "verified_labels_sha256": ls} for rid in kept}, "gate": results}
    save(os.path.join(root, "data", "rules.json"), doc)
    return doc


def verify_kept(root=HERE):
    """After new labels: a kept rule stays bound only if it still makes no agreed label disagree (fail closed)."""
    rp = os.path.join(root, "data", "rules.json")
    doc = load(rp)
    if not doc:
        return None
    labels = load(os.path.join(root, "data", "labels.json"))["labels"]
    ls, still, dropped = labels_sha(labels), [], []
    for rid in doc["kept"]:
        b = doc["bindings"].get(rid) or {}
        if rid not in reader.CANDIDATES or b.get("code_sha256") != code_sha(rid):
            dropped.append({"rule": rid, "why": "its code changed since the gate"})
            continue
        _, pb = agreement(labels, still)
        _, pa = agreement(labels, still + [rid])
        if any(pb[k] and not pa[k] for k in pb):
            dropped.append({"rule": rid, "why": "a new label disagrees with it"})
            continue
        still.append(rid)
        b["verified_labels_sha256"] = ls
    doc["kept"] = still
    doc["bindings"] = {r: doc["bindings"][r] for r in still}
    doc["verified_at"], doc["labels_sha256"], doc["label_count"] = now_iso(), ls, len(labels)
    if dropped:
        doc.setdefault("dropped", []).extend({**d, "at": now_iso()} for d in dropped)
    save(rp, doc)
    return dropped


# ---- report ----------------------------------------------------------------------------------------
def report(root=HERE):
    labels = load(os.path.join(root, "data", "labels.json"))["labels"]
    rules = load(os.path.join(root, "data", "rules.json"), {"kept": [], "gate": []})
    kept = reader.kept_rules(os.path.join(root, "data", "rules.json"), os.path.join(root, "data", "labels.json"))
    base, pb = agreement(labels, [])
    now, pa = agreement(labels, kept)
    rows_ = []
    for l in labels:
        rb, ra = read_label(l, []), read_label(l, kept)
        rows_.append({"id": l["id"], "author": l["post"]["author"], "url": l["post"]["url"], "posted_at": l["post"]["posted_at"],
                      "text": l["post"]["text"], "kind": l["kind"], "gating": l["gating"], "skip_basis": l.get("skip_basis"),
                      "owner": l["owner"], "first_read": l["first_read"], "read_base": rb, "read_now": ra,
                      "agree_base": agrees(l, rb) if l["gating"] else None, "agree_now": agrees(l, ra) if l["gating"] else None,
                      "sources": [s["type"] for s in l["sources"]]})

    def group(key):
        out = collections.OrderedDict()
        for r in sorted(rows_, key=lambda r: key(r)):
            g = out.setdefault(key(r), {"labels": 0, "gating": 0, "agree_base": 0, "agree_now": 0})
            g["labels"] += 1
            if r["gating"]:
                g["gating"] += 1
                g["agree_base"] += r["agree_base"]
                g["agree_now"] += r["agree_now"]
        return out
    src = collections.Counter(s for r in rows_ for s in r["sources"])
    doc = {"schema": "quanty.agreement.v1", "built_at": now_iso(), "labels": len(rows_), "labels_sha256": labels_sha(labels),
           "by_source": dict(sorted(src.items())), "overall": {"base": base, "with_kept_rules": now}, "kept_rules": kept,
           "per_caller": group(lambda r: r["author"]), "per_kind": group(lambda r: r["kind"]),
           "changed_by_rules": [r["id"] for r in rows_ if r["read_base"]["side"] != r["read_now"]["side"]],
           "disagreements": [r for r in rows_ if r["gating"] and not r["agree_now"]],
           "gate": rules.get("gate", []), "rules_file": "data/rules.json", "labels_file": "data/labels.json", "rows": rows_}
    save(os.path.join(root, "web", "data", "agreement.json"), doc)
    with open(os.path.join(root, "web", "agreement.html"), "w") as f:
        f.write(page(doc))
    return doc


def pct(a, n):
    return "–" if not n else f"{a}/{n} ({a / n:.0%})"


def page(d):
    o = d["overall"]
    def table(groups, title):
        trs = "".join(f"<tr><td>{e(k)}</td><td>{g['labels']}</td><td>{e(pct(g['agree_base'], g['gating']))}</td><td>{e(pct(g['agree_now'], g['gating']))}</td></tr>"
                      for k, g in groups.items())
        return (f'<h2 class="sec">{e(title)}</h2><div class="panel tablewrap"><table class="coins"><thead><tr><th></th><th>Labels</th>'
                f'<th>Base reader</th><th>With learned rules</th></tr></thead><tbody>{trs}</tbody></table></div>')
    gate_rows = "".join(
        f'<tr data-rule="{e(g["rule"])}"><td><strong>{e(g["rule"])}</strong><br><span class="muted small">{e(g["doc"])}</span></td>'
        f'<td>{e(g["decision"].upper())}</td><td>{e(pct(g["before"]["agree"], g["before"]["n"]))} → {e(pct(g["after"]["agree"], g["after"]["n"]))}</td>'
        f'<td>{e(", ".join(g["fixed"]) or "–")}</td><td>{e(", ".join(g["worsened"]) or "–")}</td><td>{e(g["why"])}</td></tr>' for g in d["gate"])
    def who(r):
        o_ = r["owner"]
        return f'{o_["decision"]} {o_.get("asset") or ""} {o_.get("side") or ""}'.strip()
    dis = "".join(
        f'<li data-label="{e(r["id"])}"><strong>@{e(r["author"])}</strong> {e(r["posted_at"][:10])} · {e(r["kind"])}: reader <code>{e(r["read_now"]["side"])}</code>, '
        f'owner <code>{e(who(r))}</code> — “{e(" ".join(r["text"].split())[:180])}” <a href="{e(r["url"])}" rel="noopener noreferrer">post</a>'
        + (f'<br><span class="muted small">reason: {e(r["owner"].get("reason") or r.get("skip_basis") or "")[:300]}</span>' if r["owner"].get("reason") else "") + "</li>"
        for r in d["disagreements"])
    changed = "".join(f"<li>{e(i)}</li>" for i in d["changed_by_rules"]) or "<li>none</li>"
    src = " · ".join(f"{e(k)} {v}" for k, v in d["by_source"].items())
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; manifest-src 'none'; media-src 'none'; font-src 'none'; upgrade-insecure-requests">
<meta name="referrer" content="no-referrer">
<script src="assets/frame-guard.js"></script>
<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reader agreement · Quanty Quants</title>
<meta name="description" content="How often the call reader's first read matches the owner's decision, and the rules learned from the corrections.">
<link rel="stylesheet" href="assets/board.css">
<link rel="stylesheet" href="assets/episode.css">
</head>
<body>
<main>
  <header class="top">
    <div>
      <h1>Quanty Quants</h1>
      <p class="sub">How often the call reader agrees with the owner, and what it learned from the corrections</p>
    </div>
    <nav class="nav" aria-label="Views">
      <a href="./">Leaderboard</a>
      <a href="chart.html">Chart</a>
      <a href="episodes.html">Episodes</a>
      <a href="coins.html">Coins</a>
      <a href="agreement.html" aria-current="page">Agreement</a>
      <a href="regimes.html">Regimes</a>
      <a href="context.html">Context</a>
    </nav>
  </header>
  <section class="ep-head panel" data-field="agreement">
    <h2 data-field="overall">Base reader {e(pct(o['base']['agree'], o['base']['n']))} · with learned rules {e(pct(o['with_kept_rules']['agree'], o['with_kept_rules']['n']))}</h2>
    <p>Every decision the owner made on a post the reader read (adding a call as read, changing its side or coin, skipping it) is a label. A label counts
    here when it says something about the side: an add with its side, or a skip whose written reason says there is no side (a conditional, hedged, quoted or
    no-position post). Repeats and skips without a reason are kept as labels but not counted. Score-neutral: labels and rules never change a record or a score.</p>
    <p class="muted small">{d['labels']} labels ({src}) · labels sha256 {e(d['labels_sha256'][:16])}… · learned rules in use: {e(", ".join(d['kept_rules']) or 'none')}
    · data: <a href="data/agreement.json">data/agreement.json</a></p>
  </section>
  {table(d['per_caller'], 'Per caller')}
  {table(d['per_kind'], 'Per kind of decision')}
  <h2 class="sec">Rule gate</h2>
  <p class="notes">A candidate rule is kept only if agreement rises and no label that agreed before disagrees after. A kept rule is bound to its code and the labels it was checked on; if either changes, it is checked again or switched off.</p>
  <div class="panel tablewrap"><table class="coins"><thead><tr><th>Rule</th><th>Decision</th><th>Agreement</th><th>Fixed</th><th>Would break</th><th>Why</th></tr></thead><tbody>{gate_rows}</tbody></table></div>
  <h2 class="sec">Reads changed by the learned rules</h2>
  <ul class="plain">{changed}</ul>
  <h2 class="sec">Disagreements ({len(d['disagreements'])})</h2>
  <ul class="plain">{dis}</ul>
  <p class="nfa" id="nfa" data-field="nfa"><strong>Not financial advice.</strong> The calls are public posts by their authors, tracked and priced for analysis. Nothing here is a recommendation to buy, sell or hold anything.</p>
</main>
</body>
</html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["build", "gate", "report"])
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            labels, new = build()
            print(f"labels: {len(labels)} ({len(new)} new)")
            for lid in new:
                l = next(x for x in labels if x["id"] == lid)
                o = l["owner"]
                print(f"NEW {lid} @{l['post']['author']} {l['kind']}: reader {l['first_read']['side']} -> owner {o['decision']} {o.get('asset') or ''} {o.get('side') or ''}".rstrip()
                      + (f" ({o['method']}{', ' + o['reason'][:120] if o.get('reason') else ''})"))
        elif a.cmd == "gate":
            d = gate()
            for g in d["gate"]:
                print(f"{g['decision'].upper():8} {g['rule']:<22} {g['before']['agree']}/{g['before']['n']} -> {g['after']['agree']}/{g['after']['n']}"
                      f"  fixed {g['fixed'] or '-'}  worsened {g['worsened'] or '-'}  ({g['why']})")
            print(f"kept: {d['kept'] or 'none'}")
        else:
            d = report()
            o = d["overall"]
            print(f"agreement: base {o['base']['agree']}/{o['base']['n']}, with kept rules {o['with_kept_rules']['agree']}/{o['with_kept_rules']['n']}; "
                  f"{d['labels']} labels {d['by_source']}; changed by rules: {d['changed_by_rules'] or 'none'}")
    except Conflict as ex:
        print(f"CONFLICT  {ex}")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
