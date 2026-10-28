"""'What changed' feed: differences since the last time you marked the feed as seen.

The last-seen state is a small snapshot per league (data/leagues/<id>/seen.json): your
players' values and injury statuses, every player's breakout score, who was rostered, and
when. Changes are computed against today's league build:
- value moves on your roster (at least 150 and 8%)
- injury status changes on your roster
- players newly flagged as breakout candidates (score 40+)
- trades and notable adds/drops elsewhere in the league since then
- notable players who were dropped and are now free agents
"""
from __future__ import annotations

import datetime as dt
import json
import time

from . import sleeper, store

FLAG = 40          # breakout score that counts as a flag
NOTABLE = 500      # value that makes an add/drop or a free agent worth mentioning


def _path(league_id: str):
    return store.path(league_id).with_name("seen.json")


def _state(lg) -> dict:
    me = lg.me or {"players": []}
    return {
        "ts": int(time.time() * 1000),
        "mine": {a["id"]: a["value"] for a in me["players"]},
        "injuries": {a["id"]: a.get("injury") for a in me["players"]},
        "breakout": {pid: o["breakout"] for pid, o in lg.opportunity["players"].items() if o["breakout"] >= FLAG},
        "rostered": sorted({a["id"] for t in lg.teams.values() for a in t["players"]}),
    }


def mark_seen(lg):
    p = _path(lg.cfg["league_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_state(lg)), encoding="utf-8")


def _name(lg, pid):
    return (lg.players_db.get(pid) or {}).get("full_name") or pid


def _pos(lg, pid):
    return (lg.players_db.get(pid) or {}).get("position") or "?"


def changes(lg) -> dict:
    p = _path(lg.cfg["league_id"])
    if not p.exists():
        mark_seen(lg)
        return {"baseline": True, "since": None, "items": []}
    seen = json.loads(p.read_text(encoding="utf-8"))
    since = dt.datetime.fromtimestamp(seen["ts"] / 1000).isoformat(timespec="minutes")
    items = []
    me = lg.me or {"players": [], "roster_id": None}
    mgr = {rid: t["manager"] for rid, t in lg.teams.items()}

    for a in me["players"]:
        old = seen["mine"].get(a["id"])
        if old is None:
            continue
        d = a["value"] - old
        if abs(d) >= 150 and abs(d) >= 0.08 * max(old, 1):
            items.append({"kind": "value", "pid": a["id"], "name": a["name"], "pos": a["pos"], "delta": round(d),
                          "text": f"{'Up' if d > 0 else 'Down'} {abs(d):,.0f} ({d / max(old, 1) * 100:+.0f}%) to {a['value']:,}"})
        was, now = seen["injuries"].get(a["id"]), a.get("injury")
        if a["id"] in seen["injuries"] and was != now:
            items.append({"kind": "injury", "pid": a["id"], "name": a["name"], "pos": a["pos"],
                          "text": f"Now {now}" + (f" (was {was})" if was else "") if now else f"Healthy again (was {was})"})

    owner = {a["id"]: t for t in lg.teams.values() for a in t["players"]}
    for pid, o in lg.opportunity["players"].items():
        if o["breakout"] >= FLAG and pid not in seen["breakout"]:
            t = owner.get(pid)
            whose = "free agent" if not t else "yours" if t["roster_id"] == me.get("roster_id") else t["manager"]
            top = o["notes"][0]["text"] if o["notes"] else ""
            items.append({"kind": "breakout", "pid": pid, "name": _name(lg, pid), "pos": _pos(lg, pid), "score": o["breakout"],
                          "owner": whose, "text": f"Breakout score {o['breakout']} · {whose}" + (f" · {top}" if top else "")})

    was_rostered = set(seen["rostered"])
    now_rostered = set(owner)
    for pid in was_rostered - now_rostered:
        v = lg.values.player(pid)["value"]
        if v >= NOTABLE:
            items.append({"kind": "available", "pid": pid, "name": _name(lg, pid), "pos": _pos(lg, pid), "value": round(v),
                          "text": f"Dropped and available · value {v:,.0f}"})

    for tx in sleeper.all_transactions(lg.cfg["league_id"]):
        ts = tx.get("status_updated") or tx.get("created") or 0
        if ts <= seen["ts"] or tx.get("league_id") != lg.cfg["league_id"]:
            continue
        day = dt.datetime.fromtimestamp(ts / 1000).date().isoformat()
        if tx["type"] == "trade":
            sides = []
            for rid in tx.get("roster_ids") or []:
                got = [_name(lg, pid) for pid, to in (tx.get("adds") or {}).items() if to == rid]
                got += [f"{dp['season']} R{dp['round']} pick" for dp in tx.get("draft_picks") or [] if dp.get("owner_id") == rid]
                sides.append(f"{mgr.get(rid, rid)} gets {', '.join(got) or 'nothing'}")
            items.append({"kind": "trade", "date": day, "text": "; ".join(sides), "mine": me.get("roster_id") in (tx.get("roster_ids") or [])})
        else:
            for pid, rid in (tx.get("adds") or {}).items():
                v = lg.values.player(pid)["value"]
                if v >= NOTABLE and rid != me.get("roster_id"):
                    items.append({"kind": "move", "date": day, "pid": pid, "name": _name(lg, pid), "pos": _pos(lg, pid),
                                  "text": f"Added by {mgr.get(rid, rid)} · value {v:,.0f}"})
    order = {"injury": 0, "value": 1, "trade": 2, "available": 3, "breakout": 4, "move": 5}
    items.sort(key=lambda x: (order[x["kind"]], -abs(x.get("delta", 0)), -x.get("score", 0)))
    return {"baseline": False, "since": since, "items": items}
