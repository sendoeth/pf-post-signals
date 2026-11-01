#!/usr/bin/env python3
"""Episode intake: transcript file + metadata -> private preview -> staged episode (not public).

  prepare  parse the transcript (refused if any line is unreadable), keep it private
           (private/transcripts/<slug>.txt, gitignored), run the LLM extraction (tools/llm_extract.py),
           verify every stance against the transcript, fold them into theses and write a PRIVATE
           preview to private/episodes/<slug>/. Prints the preview and "PREVIEW_SHA <sha256>" of the
           extraction it shows.
  stage    copy exactly that previewed extraction (checked with --expect-sha) into
           sources/episodes/<slug>/ (all four preview files are bound by one sha256) and build web/data/episodes.json + the pages (tools/episode.py).
           Still not public: the admin bot's /publish commits and pushes.

usage:
  python3 tools/episode_intake.py prepare <transcript.txt> --date YYYY-MM-DD --show "..." --title "..." [--url https://...] [--time HH:MM]
  python3 tools/episode_intake.py stage <slug> --expect-sha <sha256>
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import episode  # noqa: E402
import transcript as tr  # noqa: E402

SLUG_RE = re.compile(r"^[a-z0-9-]{3,80}$")
URL_OK = re.compile(r"https://[^\s\"'<>]{4,300}")


class IntakeError(ValueError):
    pass


def slugify(show, date):
    base = re.sub(r"\([^)]*\)", " ", show.lower())
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:50].strip("-")
    return f"{base or 'episode'}-{date}"


def check_meta(date, show, title, url, time_utc):
    try:
        day = dt.date.fromisoformat(date)
    except ValueError:
        raise IntakeError(f"date must be YYYY-MM-DD, got {date!r}") from None
    if day > dt.datetime.now(dt.timezone.utc).date() or day.year < 2000:
        raise IntakeError("date is in the future or implausible")
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", time_utc):
        raise IntakeError("time must be HH:MM (UTC)")
    for name, v, n in (("show", show, 80), ("title", title, 200)):
        if not v or len(v) > n or any(ord(c) < 32 for c in v):
            raise IntakeError(f"{name} must be 1-{n} printable characters")
    if url and not URL_OK.fullmatch(url):
        raise IntakeError("link must be an https:// URL (or leave it out)")


PREVIEW_FILES = ("episode.json", "extraction.json", "verified.json", "theses.json")


def preview_sha(priv_dir):
    """One sha256 over all four preview files (name + each file's sha256), so the staged episode is
    exactly what the preview showed: none of the four can change in between."""
    lines = []
    for n in PREVIEW_FILES:
        with open(os.path.join(priv_dir, n), "rb") as f:
            lines.append(f"{n} {tr.sha256(f.read())}")
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def paths(root, slug):
    return (os.path.join(root, "private", "transcripts", f"{slug}.txt"), os.path.join(root, "private", "episodes", slug),
            os.path.join(root, "sources", "episodes", slug))


def dump(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.write("\n")


def prepare(transcript_path, date, show, title, url=None, time_utc="20:00", root=HERE, extract=None, replace=False):
    check_meta(date, show, title, url, time_utc)
    slug = slugify(show, date)
    if not SLUG_RE.match(slug):
        raise IntakeError(f"bad slug {slug!r}")
    with open(transcript_path, "rb") as f:
        blob = f.read()
    if len(blob) > 2_000_000:
        raise IntakeError("transcript over 2 MB")
    parsed = tr.parse(blob.decode("utf-8"))          # TranscriptError on any unreadable line
    sha = tr.sha256(blob)
    priv_txt, priv_dir, _ = paths(root, slug)
    os.makedirs(os.path.dirname(priv_txt), exist_ok=True)
    if os.path.exists(priv_txt) and tr.sha256(open(priv_txt, "rb").read()) != sha and not replace:
        raise IntakeError(f"a different transcript is already stored for {slug} (pass --replace to swap it)")
    if os.path.abspath(transcript_path) != os.path.abspath(priv_txt):
        shutil.copyfile(transcript_path, priv_txt)
    if extract is None:
        import llm_extract
        extract = llm_extract.extract
    ex = extract(parsed, sha)
    accepted, rejected = tr.verify(parsed, ex, sha)
    extras, notes = tr.verify_extras(parsed, ex, accepted)
    theses = tr.consolidate(accepted)
    os.makedirs(priv_dir, exist_ok=True)
    dump(os.path.join(priv_dir, "extraction.json"), ex)
    ex_sha = tr.sha256(open(os.path.join(priv_dir, "extraction.json"), "rb").read())
    model = ex.get("model")
    dump(os.path.join(priv_dir, "verified.json"), {"transcript_sha256": sha, "accepted": accepted, "rejected": rejected, "notes": notes})
    dump(os.path.join(priv_dir, "theses.json"), {
        "schema": "quanty.theses.v1", "transcript_sha256": sha, "extraction_sha256": ex_sha, "model": model,
        "prompt_version": ex.get("prompt_version"), "segments": len(parsed["segments"]), "duration": parsed["segments"][-1]["ts"],
        "chapters": [{"n": c["n"], "title": c["title"], "t": tr.fmt(c["t"] or 0)} for c in parsed["chapters"]],
        "accepted": len(accepted), "rejected": len(rejected), "theses": theses})
    dump(os.path.join(priv_dir, "episode.json"), {
        "schema": tr.EPISODE_SCHEMA, "slug": slug, "show": show, "title": title,
        "speakers": list(extras["speakers"]) or ["not identified"],
        "recorded_on": date, "recorded_source": "entered by the owner in the admin bot",
        "reference_at": f"{date}T{time_utc}:00Z",
        "reference_note": f"prices are the last bar at or before {time_utc} UTC on {date}, the time given for the episode",
        "url": url or None, "show_url": None,
        "transcript": {"private": True, "note": "the full transcript is kept private; its sha256 is below and every quote on the page was checked against it word for word"},
        "summary_by": f"{model}, in its own words (checked: timestamps inside the episode, length capped)",
        "summary": extras["summary"], "theses_text": extras["theses_text"]})
    lines = [f"{show} · {date} · {title}", f"slug {slug} · transcript sha256 {sha[:16]}… · {len(parsed['segments'])} segments, {len(parsed['chapters'])} chapters, 0:00-{parsed['segments'][-1]['ts']}",
             f"model {model} · prompt {ex.get('prompt_version')} · usage {json.dumps(ex.get('usage') or {})[:120]}",
             f"stances: {len(accepted)} accepted ({sum(a['kind'] == 'call' for a in accepted)} calls, {sum(a['kind'] == 'thought' for a in accepted)} thoughts), {len(rejected)} rejected", ""]
    for t in theses:
        later = f", later {t['later']}" if t["later"] else ""
        lines.append(f"{t['label']}: {t['kind']} {t['direction']}{later} · {t['mentions']} moments: {' '.join(m['t'] for m in t['moments'])}")
        if extras["theses_text"].get(t["asset"]):
            lines.append(f"   {extras['theses_text'][t['asset']]}")
    if rejected:
        lines.append("")
        lines.append("rejected:")
        for r in rejected:
            st = r["stance"]
            lines.append(f"  #{r['i']} {st.get('asset')} {st.get('t')} {st.get('kind')}: {'; '.join(r['reasons'])}")
    if notes:
        lines.append("")
        lines.append("notes: " + "; ".join(notes))
    lines.append("")
    psha = preview_sha(priv_dir)
    lines.append(f"PREVIEW_SHA {psha}")
    return {"slug": slug, "accepted": len(accepted), "rejected": len(rejected), "preview_sha": psha, "extraction_sha": ex_sha, "text": "\n".join(lines)}


def stage(slug, expect_sha, root=HERE, fetch=None, web=None):
    if not SLUG_RE.match(slug or ""):
        raise IntakeError("bad slug")
    _, priv_dir, pub_dir = paths(root, slug)
    if not all(os.path.exists(os.path.join(priv_dir, n)) for n in PREVIEW_FILES):
        raise IntakeError(f"no preview for {slug}: run prepare first")
    if preview_sha(priv_dir) != expect_sha:
        raise IntakeError("the preview changed since it was shown (sha256 mismatch): prepare it again")
    th = json.load(open(os.path.join(priv_dir, "theses.json")))
    if th["accepted"] < 1:
        raise IntakeError("nothing accepted: refusing to stage an empty episode")
    os.makedirs(pub_dir, exist_ok=True)
    for n in PREVIEW_FILES:
        shutil.copyfile(os.path.join(priv_dir, n), os.path.join(pub_dir, n))
    b = episode.build(root=root, fetch=fetch)                # prices.json keeps any bars already frozen
    episode.write(b, web or os.path.join(root, "web"))
    ep = next(e for e in b["episodes"] if e["slug"] == slug)
    lines = [f"staged {slug}: {len(ep['theses'])} theses, page web/episode-{slug}.html (not public yet)"]
    for t in ep["theses"]:
        p = t["price"]
        at = p["at_episode"]["price"] if p["at_episode"] else None
        lines.append(f"  {t['label']}: {t['kind']} {t['direction']} · at the episode {at} → now {p['latest']['price'] if p['latest'] else None}")
    sha = hashlib.sha256(open(os.path.join(web or os.path.join(root, "web"), "data", "episodes.json"), "rb").read()).hexdigest()
    lines.append(f"web/data/episodes.json sha256 {sha}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("transcript")
    p.add_argument("--date", required=True)
    p.add_argument("--show", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--url")
    p.add_argument("--time", default="20:00")
    p.add_argument("--replace", action="store_true")
    p = sub.add_parser("stage")
    p.add_argument("slug")
    p.add_argument("--expect-sha", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "prepare":
            r = prepare(a.transcript, a.date, a.show, a.title, a.url, a.time, replace=a.replace)
            print(r["text"])
            return 0 if r["accepted"] else 1
        print(stage(a.slug, a.expect_sha))
        return 0
    except (IntakeError, tr.TranscriptError) as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 - the provider's errors (ExtractError) and fetch failures
        print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
