#!/usr/bin/env python3
"""LLM provider for the transcript extraction (tools/transcript.py prompt, quanty.transcript.v2).

One request per episode: the whole transcript with the fixed prompt goes to an OpenAI-compatible
chat endpoint (OpenRouter by default); the reply must be one JSON object. Everything fails closed:
an HTTP error, a timeout, an empty or non-JSON reply, or a reply without a stance list raises
ExtractError with a short message that never contains the key. The key is read from a file
(QUANTY_LLM_KEY_FILE) and only ever goes into the Authorization header.

The result is the extraction document (schema quanty.extraction.v1) with its provenance: the model
asked for and the model that answered, the provider's response id, token usage, the prompt version,
the transcript sha256 and the sha256 of the raw reply.
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [HERE, os.path.join(HERE, "tools")]
import transcript as tr  # noqa: E402

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-opus-5.5"
SYSTEM = ("You extract stances on tradable assets from market podcast transcripts. You copy quotes word for word, "
          "never invent a timestamp, and answer with one JSON object only.")
KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{16,}")


class ExtractError(RuntimeError):
    pass


def read_key(path=None):
    path = path or os.environ.get("QUANTY_LLM_KEY_FILE")
    if not path or not os.path.exists(path):
        raise ExtractError("no LLM key file configured (QUANTY_LLM_KEY_FILE)")
    with open(path) as f:
        key = f.read().strip()
    if not key:
        raise ExtractError("the LLM key file is empty")
    return key


def clean(msg, key=None):
    msg = str(msg)
    if key:
        msg = msg.replace(key, "[key]")
    return KEY_RE.sub("[key]", msg)[:400]


def parse_reply(text):
    """The reply's JSON object (a ```json fence around it is tolerated, nothing else)."""
    t = (text or "").strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", t, re.S)
    if m:
        t = m.group(1)
    try:
        obj = json.loads(t)
    except json.JSONDecodeError as e:
        raise ExtractError(f"the model did not return valid JSON ({e.msg} at char {e.pos})") from None
    if not isinstance(obj, dict) or not isinstance(obj.get("stances"), list):
        raise ExtractError("the model's JSON has no stances list")
    return obj


def call(prompt, key, model, post=None, timeout=420):
    body = json.dumps({"model": model, "temperature": 0, "max_tokens": 16000, "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                                              "X-Title": "Quanty Quants episodes"})
    try:
        if post:
            return post(req, timeout)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            detail = json.load(e).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            detail = ""
        raise ExtractError(f"LLM HTTP {e.code}: {clean(detail, key)}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ExtractError(f"LLM request failed: {clean(getattr(e, 'reason', e), key)}") from None
    except json.JSONDecodeError:
        raise ExtractError("LLM endpoint returned a non-JSON response") from None


def extract(parsed, transcript_sha, model=None, key=None, post=None, now=None):
    model = model or os.environ.get("QUANTY_LLM_MODEL") or DEFAULT_MODEL
    key = key or read_key()
    prompt = tr.render_prompt(parsed)
    res = call(prompt, key, model, post=post)
    try:
        choice = res["choices"][0]
        text = choice["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ExtractError(f"LLM reply has no message: {clean(json.dumps(res)[:300], key)}") from None
    if choice.get("finish_reason") not in (None, "stop", "end_turn"):
        raise ExtractError(f"LLM reply was cut off (finish_reason {choice.get('finish_reason')})")
    obj = parse_reply(text)
    return {"schema": tr.EXTRACTION_SCHEMA, "prompt_version": tr.PROMPT_VERSION, "transcript_sha256": transcript_sha,
            "model": f"{res.get('model') or model} (via OpenRouter)", "model_requested": model, "response_id": res.get("id"),
            "usage": res.get("usage"), "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "response_sha256": hashlib.sha256((text or "").encode()).hexdigest(),
            "made_at": now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "speakers": obj.get("speakers") or {}, "summary": obj.get("summary") or [], "stances": obj["stances"],
            "theses_text": obj.get("theses_text") or {}}
