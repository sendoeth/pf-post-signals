#!/usr/bin/env python3
"""Step 6: post URL -> saved receipt, from X's public embed endpoint (no login).

For each URL: fetch cdn.syndication.twimg.com/tweet-result, check that the post exists, that its
timestamp equals the one decoded from the post id (snowflake) and that its author matches, then
save sources/<author>/receipts/<id>.json in the step 3 receipt format plus the cashtags X
attached. Long posts come back cut to ~270 characters with no full text: the receipt says
textTruncated: true. An existing receipt is never overwritten (a step 3 receipt has the full
text). Unavailable or deleted posts fail with the reason; nothing is written for them.
The author's profile picture is saved once as web/avatars/<handle>.jpg (step 7), so the
position pages never hotlink X.

usage: python3 ingest.py URL [URL ...]
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import math
import os
import sys
import urllib.error
import urllib.request

import resolve

HERE = os.path.dirname(os.path.abspath(__file__))
EMBED = "https://cdn.syndication.twimg.com/tweet-result?id={id}&token={token}"
AVATARS = os.path.join(HERE, "web", "avatars")


class IngestError(Exception):
    pass


def embed_token(post_id):
    """The token X's embed widget sends: (id / 1e15 * pi) in base 36 without zeros or the dot."""
    x = int(post_id) / 1e15 * math.pi
    digits, whole, frac = "0123456789abcdefghijklmnopqrstuvwxyz", int(x), x - int(x)
    s = ""
    while whole:
        s, whole = digits[whole % 36] + s, whole // 36
    for _ in range(10):
        frac *= 36
        s += digits[int(frac)]
        frac -= int(frac)
    return s.replace("0", "") or "a"


def fetch_embed(post_id):
    req = urllib.request.Request(EMBED.format(id=post_id, token=embed_token(post_id)),
                                 headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise IngestError(f"post {post_id} unavailable (embed HTTP {e.code}: deleted, private or never existed)") from e
    if not body.strip():
        raise IngestError(f"post {post_id} unavailable (empty embed response)")
    return json.loads(body)


def to_receipt(url, data, captured_at):
    m = resolve.URL_RE.match(url or "")
    if not m:
        raise IngestError(f"not a post url: {url!r}")
    pid = m.group(2)
    if not data or data.get("__typename") == "TweetTombstone" or not data.get("id_str"):
        reason = (data or {}).get("tombstone", {}).get("text", {}).get("text") or "no post data"
        raise IngestError(f"post {pid} unavailable ({reason})")
    if data["id_str"] != pid:
        raise IngestError(f"embed returned post {data['id_str']} for {pid}")
    created = dt.datetime.strptime(data["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y-%m-%dT%H:%M:%SZ")
    if created != resolve.snowflake_time(pid):
        raise IngestError(f"post {pid}: embed time {created} != id time {resolve.snowflake_time(pid)}")
    author = data["user"]["screen_name"]
    if m.group(1).lower() != author.lower():
        raise IngestError(f"post {pid} is by @{author}, not @{m.group(1)}")
    raw_text = data.get("text", "")
    start, end = (data.get("display_text_range") or [0, len(raw_text)])[:2]
    return {
        "authorHandle": author,
        "capturedAt": captured_at,
        "cashtags": [s["text"].upper() for s in data.get("entities", {}).get("symbols", [])],
        "conversationId": data.get("conversation_id_str", pid),
        "dataSource": "syndication",
        "id": pid,
        "metrics": {"likes": data.get("favorite_count"), "replies": data.get("conversation_count")},
        "postedAt": created[:19] + ".000Z",
        "replyTo": data.get("in_reply_to_status_id_str"),
        # the embed text is HTML-escaped ("S&amp;P") and starts with the reply's @mentions, which
        # display_text_range excludes; X counts the range in code points, like Python slicing
        "text": html.unescape(raw_text[start:end] if end else raw_text),
        "textTruncated": "note_tweet" in data,
        "url": f"https://x.com/{author}/status/{pid}",
    }


def save_avatar(data, avatars=AVATARS):
    """Store the author's profile picture from the embed data as web/avatars/<handle>.jpg (served
    from our own page, never hotlinked) and record its source and sha256 in index.json.
    Returns the path, or None when the post carries no picture (the page then shows initials)."""
    user = (data or {}).get("user") or {}
    src, handle = user.get("profile_image_url_https"), (user.get("screen_name") or "").lower()
    if not src or not handle or not src.startswith("https://pbs.twimg.com/"):
        return None
    src = src.replace("_normal.", "_200x200.")
    with urllib.request.urlopen(urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as resp:
        if resp.headers.get_content_type() != "image/jpeg":
            return None
        blob = resp.read()
    os.makedirs(avatars, exist_ok=True)
    path = os.path.join(avatars, f"{handle}.jpg")
    with open(path, "wb") as f:
        f.write(blob)
    index_path = os.path.join(avatars, "index.json")
    index = {}
    if os.path.exists(index_path):
        with open(index_path) as f:
            index = json.load(f)
    index[handle] = {"file": f"{handle}.jpg", "source": src, "sha256": hashlib.sha256(blob).hexdigest(),
                     "saved_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    with open(index_path, "w") as f:
        json.dump(dict(sorted(index.items())), f, indent=1)
        f.write("\n")
    return path


def ingest(url, fetch=fetch_embed, root=HERE, now=None, avatars=None):
    """Returns (path, receipt, created: bool)."""
    m = resolve.URL_RE.match(url or "")
    if not m:
        raise IngestError(f"not a post url: {url!r}")
    pid = m.group(2)
    for path in [os.path.join(root, "sources", d, "receipts", f"{pid}.json")
                 for d in sorted(os.listdir(os.path.join(root, "sources")))
                 if os.path.isdir(os.path.join(root, "sources", d, "receipts"))]:
        if os.path.exists(path):
            with open(path) as f:
                receipt = json.load(f)
            if avatars and not os.path.exists(os.path.join(avatars, f"{receipt['authorHandle'].lower()}.jpg")):
                save_avatar(fetch(pid), avatars)   # existing receipt, first time we need its avatar
            return path, receipt, False
    now = now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    data = fetch(pid)
    receipt = to_receipt(url, data, now)
    if avatars:
        save_avatar(data, avatars)
    path = os.path.join(root, "sources", receipt["authorHandle"].lower(), "receipts", f"{pid}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(receipt, f, indent=1, ensure_ascii=False)
        f.write("\n")
    return path, receipt, True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("urls", nargs="+")
    a = ap.parse_args()
    errors = 0
    for url in a.urls:
        try:
            path, r, created = ingest(url, avatars=AVATARS)
        except IngestError as e:
            print("ERROR", e, file=sys.stderr)
            errors += 1
            continue
        with open(path, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        print(f"{'SAVED ' if created else 'EXISTS'} {os.path.relpath(path, HERE)} @{r['authorHandle']} {r['postedAt'][:19]}Z "
              f"source={r['dataSource']} truncated={r.get('textTruncated', False)} cashtags={r.get('cashtags', [])} sha256={sha}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
