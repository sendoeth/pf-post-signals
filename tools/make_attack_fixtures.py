#!/usr/bin/env python3
"""Step 8: hostile records for the security test, built from one real record.

Every fixture copies records/posts/2115823513915290059_BTC.json and plants attacker-controlled
content where X-derived data enters: post text, author, url, asset name, oversized text. Text that
the schema allows must render inert; everything else must be refused by build_chart.py. Each
payload tries to set window.__pwned, the canary the browser test watches.
Writes tests/fixtures/attack_records/*.json and tests/fixtures/attack_expected.json.
"""
import copy
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "tests", "fixtures", "attack_records")
BASE = os.path.join(HERE, "records", "posts", "2115823513915290059_BTC.json")

TEXT = ('<script>window.__pwned="script tag"</script> <img src=x onerror="window.__pwned=\'img onerror\'"> '
        '<svg onload="window.__pwned=\'svg onload\'"></svg> <a href="javascript:window.__pwned=\'js link\'">x</a> '
        '"><iframe srcdoc="<script>parent.__pwned=1</script>"></iframe> {{constructor.constructor("window.__pwned=1")()}}')

FIXTURES = {
    # (name, change, expected outcome)
    "text_html_payloads": (lambda r: r["post"].update(text=TEXT), "drawn, inert"),
    "text_unicode_tricks": (lambda r: r["post"].update(text="‮evil‬ \u0000 ﻿ <script>window.__pwned=2</script>"), "drawn, inert"),
    "author_html": (lambda r: r["post"].update(author='"><img src=x onerror=window.__pwned=3>'), "refused"),
    "url_javascript": (lambda r: r["post"].update(url="javascript:window.__pwned=4"), "refused"),
    "url_lookalike_domain": (lambda r: r["post"].update(url="https://x.com.evil.example/a/status/1"), "refused"),
    "asset_name_html": (lambda r: r["asset"].update(name='<b onmouseover="window.__pwned=5">BTC</b>'), "refused"),
    "text_oversized": (lambda r: r["post"].update(text="A" * 30000), "refused"),
}


def main():
    with open(BASE) as f:
        base = json.load(f)
    os.makedirs(OUT, exist_ok=True)
    expected = {}
    for i, (name, (change, outcome)) in enumerate(FIXTURES.items()):
        r = copy.deepcopy(base)
        r["post"]["id"] = str(int(base["post"]["id"]) + i + 1)   # one post per fixture, no supersede
        change(r)
        if r["post"]["url"].startswith("https://x.com/BobLoukas/status/"):
            r["post"]["url"] = f"https://x.com/BobLoukas/status/{r['post']['id']}"
        path = os.path.join(OUT, f"{name}.json")
        with open(path, "w") as f:
            json.dump(r, f, indent=1, ensure_ascii=False)
            f.write("\n")
        expected[f"tests/fixtures/attack_records/{name}.json"] = {"post_id": r["post"]["id"], "expected": outcome}
    with open(os.path.join(HERE, "tests", "fixtures", "attack_expected.json"), "w") as f:
        json.dump(expected, f, indent=1)
        f.write("\n")
    print(f"{len(FIXTURES)} attack fixtures -> {os.path.relpath(OUT, HERE)}")


if __name__ == "__main__":
    main()
