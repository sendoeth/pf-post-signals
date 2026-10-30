#!/usr/bin/env python3
"""Step 8 guard: reject server addresses and secret-looking strings before they reach the repo.

Flags
- any IPv4 address literal except a short allowlist (loopback, unspecified, GitHub Pages
  addresses). Our own server address is never written down here: any unknown address fails.
- token patterns: GitHub (ghp_/gho_/ghu_/ghs_/ghr_, github_pat_), Slack (xox*-), AWS access key
  ids, OpenAI-style sk- keys, Telegram bot tokens, Discord bot tokens, PEM private keys.

usage: python3 tools/guard.py --history      every commit reachable from HEAD (diffs + messages)
       python3 tools/guard.py --tree         every tracked file at HEAD
       python3 tools/guard.py FILE [FILE...]
Exit 1 with file / commit and line for each hit (the matched value is masked).
"""
import ipaddress
import re
import subprocess
import sys

ALLOWED_IPS = {"127.0.0.1", "0.0.0.0", "255.255.255.255",
               "185.199.108.153", "185.199.109.153", "185.199.110.153", "185.199.111.153"}  # GitHub Pages
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
TOKENS = {
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "github fine-grained token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    "slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "aws access key id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "api key (sk-)": re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{32,}\b"),
    "telegram bot token": re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b"),
    "discord token": re.compile(r"\b[MNO][A-Za-z\d_-]{23,25}\.[A-Za-z\d_-]{6}\.[A-Za-z\d_-]{27,38}\b"),
    "private key": re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
}


def mask(s):
    return s[:4] + "…" + s[-2:] if len(s) > 8 else s[:2] + "…"


def scan_text(text):
    """Yields (line_no, kind, masked value)."""
    for n, line in enumerate(text.splitlines(), 1):
        for m in IPV4.finditer(line):
            ip = m.group(0)
            try:
                ipaddress.IPv4Address(ip)
            except ValueError:
                continue
            if ip not in ALLOWED_IPS:
                yield n, "ipv4 address", mask(ip)
        for kind, pat in TOKENS.items():
            for m in pat.finditer(line):
                v = m.group(0)
                # real sk- keys are random: digits and capitals. Lower-case word slugs such as
                # "sk-hynix-recontracting-to-repricing" (an article id) are not keys.
                if kind == "api key (sk-)" and not (re.search(r"\d", v) and re.search(r"[A-Z]", v)):
                    continue
                yield n, kind, mask(v)


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, errors="replace", check=True).stdout


def main():
    hits, scanned = [], 0
    if "--history" in sys.argv:
        commits = git("rev-list", "HEAD").split()
        for c in commits:
            body = git("show", "--format=%B", "--patch", "--no-color", "--no-ext-diff", c)
            added = "\n".join(l[1:] if l.startswith("+") and not l.startswith("+++") else (l if not l.startswith(("-", " ", "@", "diff ", "index ", "+++", "---")) else "")
                              for l in body.splitlines())
            for n, kind, val in scan_text(added):
                hits.append(f"commit {c[:12]}: {kind} {val}")
            scanned += 1
        what = f"{scanned} commits (all added lines + messages)"
    else:
        files = git("ls-files").split("\n") if "--tree" in sys.argv else [a for a in sys.argv[1:] if not a.startswith("--")]
        for f in filter(None, files):
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except (IsADirectoryError, FileNotFoundError):
                continue
            for n, kind, val in scan_text(text):
                hits.append(f"{f}:{n}: {kind} {val}")
            scanned += 1
        what = f"{scanned} files"
    for h in hits:
        print("HIT", h)
    print(f"guard: scanned {what} -> " + ("0 hits" if not hits else f"{len(hits)} hits: REJECTED"))
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    main()
