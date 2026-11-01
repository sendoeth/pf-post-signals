#!/usr/bin/env python3
"""Transcripts -> stances -> theses (episode pipeline).

A podcast/video transcript is analysed in three fixed steps, all in this tool so every episode lands
in the same database with the same checks:

  1. parse    the raw transcript (YouTube-style "M:SS<spoken duration><text>" lines + "Chapter N: Title")
              into timestamped segments; the raw file stays private, only its sha256 is published.
  2. extract  an LLM reads the WHOLE transcript with the fixed prompt below (PROMPT_VERSION) and returns
              stances as JSON (schema STANCE_FIELDS). The model id + prompt version + transcript sha256
              are stored with the result, so a later run with another model is comparable.
  3. verify   every stance is checked against the transcript: its quote must appear verbatim
              (case/punctuation-insensitive) starting within WINDOW seconds of its timestamp, its asset
              must be a priceable asset, its kind/direction/speaker must be valid. Anything that fails
              is rejected with the reason; nothing unverified reaches the site.
  4. theses   verified stances are consolidated per asset (all timestamps kept, in order) into one
              thesis per asset: the overall lean, whether any of it was a direct call, and the
              timeline of what was said when.

"call"    = a direct position or recommendation by the speaker (long/short/buy/sell/avoid now).
"thought" = a view on direction or a reason an asset moves, without a stated position. Thoughts are
            drawn as their own bubble and are never part of a caller's rating.

usage:
  python3 tools/transcript.py parse <transcript.txt>
  python3 tools/transcript.py prompt <transcript.txt>            # the exact text sent to the model
  python3 tools/transcript.py verify <transcript.txt> <extraction.json> [--out DIR]
"""
import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

PROMPT_VERSION = "quanty.transcript.v2"
EXTRACTION_SCHEMA = "quanty.extraction.v1"
EPISODE_SCHEMA = "quanty.episode.v1"
WINDOW = 90                        # seconds: a quote must start within this distance of its timestamp
KINDS = ("call", "thought")
DIRECTIONS = ("bullish", "bearish", "neutral")
HORIZONS = ("now", "weeks", "months", "next year", "long term")
STANCE_FIELDS = {
    "asset": "priceable asset name (GOLD, OIL, BTC, USD, SEMIS, ...) - the thing whose price the stance is about",
    "kind": "call | thought",
    "direction": "bullish | bearish | neutral (neutral = wait / stand aside / no position)",
    "horizon": "now | weeks | months | next year | long term",
    "speaker": "who said it (name), or 'both' when they agree in the exchange",
    "speaker_confidence": "high | medium | low (transcripts carry no speaker labels)",
    "t": "timestamp M:SS or H:MM:SS where the quote starts",
    "quote": "verbatim words from the transcript (copy, do not fix grammar), 8-60 words",
    "reason": "one short line: why they lean this way, in plain words",
}

PROMPT = """You are reading the full transcript of a markets podcast. Find every stance the hosts or guests
take on a tradable asset (a commodity, currency, index, sector, stock or coin).

Rules:
- Read the whole transcript before answering; the same asset often comes back later. Report every
  separate moment as its own stance with its own timestamp.
- kind = "call" only when the speaker states their own position or tells listeners to be long/short,
  buy/sell, or to stay out NOW (e.g. "what we've been advocating for longing", "I'm not long anything").
  Everything else - a reason an asset is moving, an expectation, a conditional plan - is "thought".
- direction is the speaker's lean for the asset's price over the stated horizon: bullish, bearish, or neutral
  (wait / step aside). "Not a buy yet, maybe bullish in 2027" is two stances: neutral now and bullish next year.
- An asset discussed at length usually has several moments: a new reason, a new speaker, or a new conclusion is
  a new stance with its own timestamp. Do not merge them; it is normal for one asset to have 5-10 stances.
- Facts and news read out (earnings numbers, what a stock did today) are not stances unless the speaker
  draws a direction from them.
- Ignore ads, disclaimers and sponsor reads.
- quote must be copied verbatim from the transcript text (no timestamps), 8-60 words.
- Transcripts have no speaker labels; infer the speaker from context and say how sure you are.

- asset must be one of these names (use the closest one; skip stances on anything else):
ASSET_LIST

Also return:
- "speakers": {"<full name>": "<how you recognised them, one short line>"} for the hosts and guests.
- "summary": 4 to 10 items {"t": "<timestamp where that part starts>", "text": "<1-2 sentences in your own
  words, no quotes>"} covering the episode in order, markets content only (skip ads and small talk).
- "theses_text": {"<ASSET>": "<one short line, max 25 words: the overall view on that asset across the
  whole episode>"} for every asset you report a stance on.

Return only JSON: {"speakers": {...}, "summary": [...], "stances": [ {FIELDS} ], "theses_text": {...}}

Stance fields:
FIELD_DOCS

Transcript (timestamp then text):
TRANSCRIPT
"""

TS = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?")
DURATION = re.compile(r"^(?:(\d+) hours?)?(?:, )?(?:(\d+) minutes?)?(?:, )?(?:(\d+) seconds?)?")
CHAPTER = re.compile(r"^Chapter (\d+): (.+)$")


class TranscriptError(ValueError):
    pass


def sha256(blob):
    return hashlib.sha256(blob).hexdigest()


def fmt(sec):
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def to_seconds(ts):
    m = TS.fullmatch(ts.strip())
    if not m:
        raise TranscriptError(f"bad timestamp {ts!r}")
    a, b, c = m.groups()
    return int(a) * 3600 + int(b) * 60 + int(c) if c is not None else int(a) * 60 + int(b)


def split_line(line):
    """'1:021 minute, 2 secondsknow. Like,' -> (62, 'know. Like,'). The YouTube copy glues the
    timestamp, a spoken duration and the text together; the duration must equal the timestamp, which
    is how the glue point is found (so '10:0310 minutes, 3 seconds...' cannot be misread)."""
    cands = []
    for end in (r"(\d{1,2}):(\d{2}):(\d{2})", r"(\d{1,2}):(\d{2})"):
        m = re.match(end, line)
        if m:
            g = [int(x) for x in m.groups()]
            sec = g[0] * 3600 + g[1] * 60 + g[2] if len(g) == 3 else g[0] * 60 + g[1]
            cands.append((sec, line[m.end():]))
    for sec, rest in cands:
        d = DURATION.match(rest)
        if d and d.group(0):
            h, mi, s = (int(x) if x else 0 for x in d.groups())
            if h * 3600 + mi * 60 + s == sec:
                return sec, rest[d.end():].strip()
    return None


def parse(text):
    """-> {"segments": [{t, ts, chapter, text}], "chapters": [{n, title, t}]}; refuses lines it can't read."""
    segs, chapters, bad = [], [], []
    chapter = None
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        c = CHAPTER.match(line)
        if c:
            chapter = {"n": int(c.group(1)), "title": c.group(2).strip(), "t": None}
            chapters.append(chapter)
            continue
        got = split_line(line)
        if not got:
            bad.append(f"line {i}: {short(line)}")
            continue
        sec, body = got
        if segs and sec < segs[-1]["t"]:
            bad.append(f"line {i}: time goes backwards ({fmt(sec)} after {segs[-1]['ts']})")
            continue
        if chapter and chapter["t"] is None:
            chapter["t"] = sec
        segs.append({"t": sec, "ts": fmt(sec), "chapter": chapter["n"] if chapter else None, "text": body})
    if bad:
        raise TranscriptError("unreadable transcript lines:\n  " + "\n  ".join(bad[:10]))
    if not segs:
        raise TranscriptError("no timestamped lines")
    return {"segments": segs, "chapters": chapters}


def short(s, n=80):
    return s if len(s) <= n else s[:n] + "..."


def norm_words(s):
    """lowercase words without punctuation/brackets, so a verbatim quote matches across line breaks
    and the model's punctuation differences, but not a paraphrase."""
    s = unicodedata.normalize("NFKC", s).lower().replace("’", "'")
    s = re.sub(r"\[[^\]]*\]", " ", s)               # [laughter], [clears throat]
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", s)


def word_index(parsed):
    """flat word list + the segment start time of each word."""
    words, times = [], []
    for s in parsed["segments"]:
        w = norm_words(s["text"])
        words += w
        times += [s["t"]] * len(w)
    return words, times


def find_quote(parsed, quote, near, index=None):
    """-> segment time where the quote starts (closest to `near`), or None."""
    words, times = index or word_index(parsed)
    q = norm_words(quote)
    if len(q) < 4:
        return None
    hits = [times[i] for i in range(len(words) - len(q) + 1) if words[i] == q[0] and words[i:i + len(q)] == q]
    return min(hits, key=lambda t: abs(t - near)) if hits else None


def render_prompt(parsed, assets=None):
    assets = assets or load_assets()["assets"]
    body = "\n".join(f"{s['ts']} {s['text']}" for s in parsed["segments"])
    fields = "\n".join(f"- {k}: {v}" for k, v in STANCE_FIELDS.items())
    alist = "\n".join(f"  {k}: {v['label']}" for k, v in sorted(assets.items()))
    return (PROMPT.replace("ASSET_LIST", alist).replace("FIELD_DOCS", fields)
                  .replace("FIELDS", ", ".join(f'"{k}"' for k in STANCE_FIELDS)).replace("TRANSCRIPT", body))


def load_assets():
    with open(os.path.join(HERE, "data", "episode_assets.json")) as f:
        return json.load(f)


def verify(parsed, extraction, transcript_sha, assets=None):
    """-> (accepted, rejected). Each accepted stance gains t (seconds), matched_t and chapter."""
    assets = assets or load_assets()["assets"]
    if extraction.get("schema") != EXTRACTION_SCHEMA:
        raise TranscriptError(f"extraction schema must be {EXTRACTION_SCHEMA}")
    if extraction.get("transcript_sha256") != transcript_sha:
        raise TranscriptError("extraction was made from a different transcript (sha256 mismatch)")
    if extraction.get("prompt_version") != PROMPT_VERSION:
        raise TranscriptError(f"extraction used prompt {extraction.get('prompt_version')!r}, this tool is {PROMPT_VERSION}")
    index = word_index(parsed)
    chapter_of = {s["t"]: s["chapter"] for s in parsed["segments"]}
    accepted, rejected = [], []
    for i, s in enumerate(extraction.get("stances", [])):
        why = []
        missing = [k for k in STANCE_FIELDS if not isinstance(s.get(k), str) or not s[k].strip()]
        if missing:
            rejected.append({"i": i, "stance": s, "reasons": [f"missing {', '.join(missing)}"]})
            continue
        if s["kind"] not in KINDS:
            why.append(f"kind {s['kind']!r} not in {KINDS}")
        if s["direction"] not in DIRECTIONS:
            why.append(f"direction {s['direction']!r} not in {DIRECTIONS}")
        if s["horizon"] not in HORIZONS:
            why.append(f"horizon {s['horizon']!r} not in {HORIZONS}")
        if s["speaker_confidence"] not in ("high", "medium", "low"):
            why.append("speaker_confidence must be high/medium/low")
        if s["asset"] not in assets:
            why.append(f"asset {s['asset']!r} is not a priceable episode asset ({', '.join(sorted(assets))})")
        n = len(norm_words(s["quote"]))
        if not 8 <= n <= 60:
            why.append(f"quote has {n} words (8-60)")
        try:
            near = to_seconds(s["t"])
        except TranscriptError as e:
            why.append(str(e))
            near = None
        if near is not None and not why:
            at = find_quote(parsed, s["quote"], near, index)
            if at is None:
                why.append("quote not found verbatim in the transcript")
            elif abs(at - near) > WINDOW:
                why.append(f"quote found at {fmt(at)}, more than {WINDOW}s from the given {s['t']}")
        if why:
            rejected.append({"i": i, "stance": s, "reasons": why})
            continue
        accepted.append(dict(s, t=fmt(near), seconds=near, matched_t=fmt(at), chapter=chapter_of.get(at)))
    return accepted, rejected


def verify_extras(parsed, extraction, accepted):
    """summary / theses_text / speakers from the model: kept only when well formed, else dropped with
    a note (they are our-words text, not quotes, so they are length capped and never contain markup
    beyond what the page escapes)."""
    notes, end = [], parsed["segments"][-1]["t"]
    summary = []
    for i, it in enumerate(extraction.get("summary") or []):
        try:
            sec = to_seconds(it["t"])
            text = " ".join(str(it["text"]).split())
        except (KeyError, TypeError, TranscriptError) as e:
            notes.append(f"summary #{i} dropped: {e}")
            continue
        if not 0 <= sec <= end or not 10 <= len(text) <= 500:
            notes.append(f"summary #{i} dropped: time {it.get('t')} or length {len(text)} out of range")
            continue
        summary.append({"t": fmt(sec), "seconds": sec, "text": text})
    summary.sort(key=lambda x: x["seconds"])
    if len(summary) < 2:
        notes.append(f"summary has {len(summary)} usable items (need 2+)")
    have = {a["asset"] for a in accepted}
    texts = {}
    for k, v in (extraction.get("theses_text") or {}).items():
        v = " ".join(str(v).split())
        if k not in have:
            notes.append(f"theses_text {k!r} dropped: no accepted stance on it")
        elif not 5 <= len(v) <= 240:
            notes.append(f"theses_text {k} dropped: length {len(v)}")
        else:
            texts[k] = v
    for k in sorted(have - set(texts)):
        notes.append(f"theses_text missing for {k}")
    speakers = {" ".join(str(k).split())[:60]: " ".join(str(v).split())[:160] for k, v in (extraction.get("speakers") or {}).items()}
    return {"summary": [{"t": x["t"], "text": x["text"]} for x in summary], "theses_text": texts, "speakers": speakers}, notes


LEAN = {"bullish": 1, "bearish": -1, "neutral": 0}
NEAR = ("now", "weeks", "months")


def consolidate(accepted, assets=None):
    """one thesis per asset: every moment in time order, the overall lean and its split by horizon."""
    assets = assets or load_assets()["assets"]
    by = {}
    for s in sorted(accepted, key=lambda s: s["seconds"]):
        by.setdefault(s["asset"], []).append(s)
    theses = []
    for name, moments in by.items():
        calls = [m for m in moments if m["kind"] == "call"]
        near_calls = [m for m in calls if m["horizon"] in NEAR]
        # the headline is the view for now: the latest near-term call; without one, the weighted lean
        # (calls count double) of everything except the turns they expect next year
        score = sum(LEAN[m["direction"]] * (2 if m["kind"] == "call" else 1) for m in moments if m["horizon"] != "next year")
        head = near_calls[-1]["direction"] if near_calls else ("bullish" if score > 0 else "bearish" if score < 0 else "neutral")
        later = [m for m in moments if m["horizon"] in ("next year", "long term") and m["direction"] != head]
        theses.append({
            "asset": name, "label": assets[name]["label"], "kind": "call" if calls else "thought",
            "direction": head, "mentions": len(moments),
            "later": later[-1]["direction"] if later else None,
            "first_t": moments[0]["t"], "speakers": sorted({m["speaker"] for m in moments}),
            "moments": [{k: m[k] for k in ("t", "seconds", "kind", "direction", "horizon", "speaker",
                                          "speaker_confidence", "quote", "reason", "chapter")} for m in moments],
        })
    theses.sort(key=lambda t: (t["kind"] != "call", -t["mentions"], t["asset"]))
    return theses


def read(path):
    with open(path, "rb") as f:
        blob = f.read()
    return blob, parse(blob.decode("utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parse"); p.add_argument("transcript")
    p = sub.add_parser("prompt"); p.add_argument("transcript")
    p = sub.add_parser("verify"); p.add_argument("transcript"); p.add_argument("extraction")
    p.add_argument("--out", help="write verified.json + theses.json here")
    a = ap.parse_args(argv)
    try:
        blob, parsed = read(a.transcript)
    except TranscriptError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    sha = sha256(blob)
    if a.cmd == "parse":
        segs = parsed["segments"]
        print(f"transcript sha256 {sha}")
        print(f"{len(segs)} segments, {len(parsed['chapters'])} chapters, 0:00 -> {segs[-1]['ts']}")
        for c in parsed["chapters"]:
            print(f"  {fmt(c['t'] or 0):>7}  ch{c['n']:<2} {c['title']}")
        return 0
    if a.cmd == "prompt":
        print(render_prompt(parsed))
        return 0
    with open(a.extraction) as f:
        ex = json.load(f)
    try:
        acc, rej = verify(parsed, ex, sha)
    except TranscriptError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    theses = consolidate(acc)
    for r in rej:
        print(f"REJECTED #{r['i']} {r['stance'].get('asset')} {r['stance'].get('t')}: {'; '.join(r['reasons'])}")
    for t in theses:
        later = f", later {t['later']}" if t["later"] else ""
        print(f"{t['label']:<22} {t['kind']:<7} {t['direction']:<8}{later:<16} {t['mentions']} moments: "
              + " ".join(m["t"] for m in t["moments"]))
    print(f"{len(acc)} accepted, {len(rej)} rejected; transcript {sha[:16]}..; model {ex.get('model')}; prompt {ex.get('prompt_version')}")
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "verified.json"), "w") as f:
            json.dump({"transcript_sha256": sha, "accepted": acc, "rejected": rej}, f, indent=1)
        ex_sha = sha256(open(a.extraction, "rb").read())
        with open(os.path.join(a.out, "theses.json"), "w") as f:
            json.dump({"schema": "quanty.theses.v1", "transcript_sha256": sha, "extraction_sha256": ex_sha,
                       "model": ex.get("model"), "prompt_version": ex.get("prompt_version"),
                       "segments": len(parsed["segments"]), "duration": parsed["segments"][-1]["ts"],
                       "chapters": [{"n": c["n"], "title": c["title"], "t": fmt(c["t"] or 0)} for c in parsed["chapters"]],
                       "accepted": len(acc), "rejected": len(rej), "theses": theses}, f, indent=1)
    return 1 if rej else 0


if __name__ == "__main__":
    sys.exit(main())
