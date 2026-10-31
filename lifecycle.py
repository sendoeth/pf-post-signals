#!/usr/bin/env python3
"""Step 13: apply an author's follow-up posts to an open position.

data/lifecycle.json lists, per position (post id + asset), the follow-up posts by the same author
that talk about it, and optional reviewed overrides. For each follow-up, in time order:
  - classify.py decides close / flip / trim / review / not_close (an override, with its reason,
    replaces the classifier for that post)
  - close and flip: exit = first bar at or after the follow-up post (same lag rule as entries; a
    stated earlier time like "last week" is recorded, never used). The result is frozen in
    rec["closed"] and the position's status becomes "closed". A flip also needs the opposite
    position to be added as its own record (reported, not created silently).
  - trim: priced the same way and recorded; the position stays open
  - review / not_close: recorded, nothing changes
  - anything after the close is recorded with after_close and changes nothing
change_since_post keeps tracking the current price ("if still held"); the result is rec["closed"].

usage: python3 lifecycle.py   (dry run: prints the decisions for every configured position)
"""
import datetime as dt
import glob
import json
import os

import classify
import resolve

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "data", "lifecycle.json")


def load_config():
    if not os.path.exists(CONFIG):
        return {}
    with open(CONFIG) as f:
        return json.load(f)["positions"]


def receipt(post_id):
    hits = sorted(glob.glob(os.path.join(HERE, "sources", "*", "receipts", f"{post_id}.json")))
    if not hits:
        raise resolve.ResolveError(f"follow-up {post_id}: no saved receipt (ingest it first)")
    return resolve.load_post(receipt=hits[0])      # absolute: works for any root (the path itself is not stored)


def exit_bar(series, when, asset):
    """First bar at or after `when`, within the asset's lag limit; None if not available yet."""
    _, bar = resolve.bar_at_or_after(series, when)
    if bar is None or resolve.lag_days(when, bar[0]) > resolve.lag_limit(asset):
        return None
    return {"at": bar[0], "price": bar[1]}


def apply(rec, cfg, series, until=None):
    """Mutates rec: lifecycle events, closed result, status. cfg = {"followups": [ids], "overrides": {id: {...}}}."""
    if not rec.get("entry"):
        return rec
    p0, side = rec["entry"]["price"], rec.get("side")
    events, closed = [], None
    posts = sorted((receipt(i) for i in cfg.get("followups", [])), key=lambda p: p["posted_at"])
    for fp in posts:
        if fp["author"].lower() != rec["post"]["author"].lower():
            raise resolve.ResolveError(f"follow-up {fp['id']} is by @{fp['author']}, not @{rec['post']['author']}")
        if fp["posted_at"] <= rec["post"]["posted_at"]:
            raise resolve.ResolveError(f"follow-up {fp['id']} is not after the opening post")
        ov = cfg.get("overrides", {}).get(fp["id"])
        c = classify.classify(fp.get("text"), rec["asset"]["name"], side)
        if ov:
            c = {"type": ov["type"], "terms": c["terms"], "reason": "reviewed: " + ov["reason"], "stated_time": c["stated_time"]}
        ev = {"type": c["type"], "post": {k: fp.get(k) for k in ("id", "url", "posted_at", "text", "receipt_sha256")},
              "terms": c["terms"], "reason": c["reason"], "stated_time": c["stated_time"], "decided_by": "override" if ov else "classifier"}
        if closed:
            ev["after_close"] = True
        elif c["type"] in ("close", "flip", "trim"):
            bar = exit_bar(series, fp["posted_at"], rec["asset"])
            if bar is None:
                ev["reason"] += "; no price after the post yet, applied on a later refresh"
            else:
                if until and bar["at"] < until:
                    bar["interval"] = "1d"
                ev["bar"] = bar
                ev["move"] = bar["price"] / p0 - 1
                if side:
                    ev["for_call"] = side * ev["move"]
                if c["type"] in ("close", "flip"):
                    closed = {"post_id": fp["id"], "post_url": fp["url"], "by": c["type"], "exit": dict(bar), "move": ev["move"],
                              "stated_time": c["stated_time"]}
                    if side:
                        closed["for_call"] = ev["for_call"]
        events.append(ev)
    rec["lifecycle"] = {"state": "closed" if closed else "open", "events": events}
    rec.pop("closed", None)
    if closed:
        rec["closed"] = closed
        rec["status"] = "closed"
    return rec


def ledger_close(rec, exit_event, series):
    """Corbanu: a ledger exit event closes the position automatically at the first bar after it."""
    when = exit_event["at"][:19] + "Z"
    bar = exit_bar(series, when, rec["asset"])
    post = {"id": f"corbanu:{exit_event['id']}", "url": rec["post"]["url"], "posted_at": when, "text": exit_event.get("note"), "receipt_sha256": None}
    ev = {"type": "close", "post": post, "terms": [exit_event.get("type", "trade")], "reason": "exit event in Corbanu's published ledger",
          "stated_time": None, "decided_by": "ledger"}
    if bar is None:
        ev["reason"] += "; no price after it yet"
        rec["lifecycle"] = {"state": "open", "events": [ev]}
        return rec
    ev["bar"], ev["move"] = bar, bar["price"] / rec["entry"]["price"] - 1
    ev["for_call"] = rec["side"] * ev["move"]
    rec["lifecycle"] = {"state": "closed", "events": [ev]}
    rec["closed"] = {"post_id": post["id"], "post_url": post["url"], "by": "ledger", "exit": dict(bar), "move": ev["move"],
                     "for_call": ev["for_call"], "stated_time": None}
    rec["status"] = "closed"
    return rec


def frozen_bars(rec):
    """Bars a refresh must never change: lifecycle exits and trims."""
    out = []
    for ev in (rec.get("lifecycle") or {}).get("events", []):
        if ev.get("bar"):
            out.append((ev["bar"]["at"], ev["bar"]["price"], f"{ev['type']} {ev['post']['id']}"))
    return out


def main():
    cfg = load_config()
    prices = resolve.Prices()
    for key, c in cfg.items():
        pid, asset_name = key.split("|")
        path = next(iter(glob.glob(os.path.join(HERE, "records", "**", f"{pid.replace(':', '-')}_{asset_name.replace(':', '-')}.json"), recursive=True)), None)
        if not path:
            print(f"{key}: no record yet")
            continue
        with open(path) as f:
            rec = json.load(f)
        asset = resolve.asset_info(asset_name)
        series = prices.series(asset, rec["post"]["posted_at"])
        apply(rec, c, series, prices.daily_until(asset, rec["post"]["posted_at"]))
        print(f"{key}: opened {rec['post']['posted_at'][:16]} at {rec['entry']['price']} ({rec['entry'].get('interval', '1h')} bar {rec['entry']['at'][:16]})")
        for ev in rec["lifecycle"]["events"]:
            bar = ev.get("bar")
            print(f"  {ev['post']['posted_at'][:16]} {ev['post']['id']} -> {ev['type']:<9} {ev['terms']} "
                  + (f"bar {bar['price']} @ {bar['at'][:16]} {resolve.pct(ev.get('for_call', ev.get('move')))}" if bar else "")
                  + (f" stated '{ev['stated_time']}'" if ev.get("stated_time") else "") + (" (after the close)" if ev.get("after_close") else ""))
        if rec.get("closed"):
            print(f"  CLOSED: realized {resolve.pct(rec['closed'].get('for_call', rec['closed']['move']))} at {rec['closed']['exit']['price']} "
                  f"@ {rec['closed']['exit']['at'][:16]}; if still held {resolve.pct(rec['side'] * rec['change_since_post'] if rec.get('side') else rec['change_since_post'])}")


if __name__ == "__main__":
    main()
