"""Waiver-claim and free-agent pickup evaluation.

Each add from a waiver or free-agent transaction is one pickup, held until that team
drops or trades the player (or still held today). For every pickup:
- value at pickup and while held: DynastyProcess weekly history, same as the draft report
- value captured: what the pickup is worth to the team today. That is his current value
  if still rostered, his value on the trade date if he was flipped, and 0 if dropped.
- start points: fantasy points he scored in that team's starting lineup while held
  (from Sleeper weekly matchups). This is the in-season payoff dynasty value misses.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from . import drafts as draftmod
from . import sleeper

HIT_VALUE = 1000  # a pickup that is (or was flipped for) at least this much is a "hit"


def _ms_day(ms) -> str:
    return dt.datetime.fromtimestamp(ms / 1000).date().isoformat()


def _kickoff(season: int) -> str:
    """NFL kickoff: the Thursday after Labor Day (first Monday of September)."""
    d = dt.date(season, 9, 1)
    labor_day = d + dt.timedelta(days=(0 - d.weekday()) % 7)
    return (labor_day + dt.timedelta(days=3)).isoformat()


def _value_on(series, dates, day) -> float:
    """Value at the last snapshot on/before day, or 0 if the player wasn't listed yet."""
    best = 0.0
    for d, v in zip(dates, series):
        if d > day:
            break
        if v is not None:
            best = v
    return best


def _start_points(lg) -> dict:
    """(season, roster_id, player_id) -> [(week, points)] for weeks he was started."""
    state = sleeper.nfl_state()
    out = defaultdict(list)
    for l in sleeper.league_chain(lg.cfg["league_id"]):
        season = int(l["season"])
        if l.get("_cutoff") and season >= dt.datetime.fromtimestamp(l["_cutoff"] / 1000).year:
            continue  # a linked league's games after the restart don't count
        done = l.get("status") == "complete"
        last = 18 if done else min(18, int(state.get("week") or 18))
        for w in range(1, last + 1):
            for m in sleeper.matchups(l["league_id"], w, done):
                for pid, pts in zip(m.get("starters") or [], m.get("starters_points") or []):
                    if pid and pid != "0":
                        out[(season, sleeper.rid(l, m["roster_id"]), pid)].append((w, pts or 0.0))
    return out


def analyze(lg) -> dict:
    _, hist, events = draftmod.context(lg)
    dates, hv = hist["dates"], hist["values"]
    points = _start_points(lg)
    owner_now = {a["id"]: t["roster_id"] for t in lg.teams.values() for a in t["players"]}
    mgr = {rid: t["manager"] for rid, t in lg.teams.items()}
    seasons = sorted({int(l["season"]) for l in sleeper.league_chain(lg.cfg["league_id"])})

    pickups = []
    for i, (ms, pid, rid, src, kind, tx) in enumerate(events):
        if kind != "add" or not tx or tx["type"] not in ("waiver", "free_agent"):
            continue
        end = next((f for f in events[i + 1:] if f[1] == pid and f[2] == rid and f[4] == "drop"), None)
        day = _ms_day(ms)
        end_day = _ms_day(end[0]) if end else None
        series = hv.get(pid) or [None] * len(dates)
        v_add = _value_on(series, dates, day)
        held = [v for d, v in zip(dates, series) if d >= day and (end_day is None or d <= end_day) and v is not None]
        now = next((v for v in reversed(series) if v is not None), 0.0)
        if end is None and owner_now.get(pid) == rid:
            outcome, captured = "On roster", now
        elif end and end[3] == "trade":
            outcome, captured = f"Traded {end_day}", _value_on(series, dates, end_day)
        elif end:
            outcome, captured = f"Dropped {end_day}", 0.0
        else:
            outcome, captured = "No longer rostered", 0.0

        start = (int(tx["season"]), tx.get("leg") or 0)
        stop = (int(end[5]["season"]), end[5].get("leg") or 0) if end and end[5] else (9999, 99)
        pts, starts = 0.0, 0
        for s in seasons:
            for w, p in points.get((s, rid, pid), []):
                if start <= (s, w) <= stop:
                    pts += p
                    starts += 1

        info = lg.players_db.get(pid) or {}
        name = info.get("full_name") or f"{info.get('first_name') or ''} {info.get('last_name') or ''}".strip() or pid
        pickups.append({
            "player_id": pid, "name": name, "pos": info.get("position") or "?",
            "roster_id": rid, "manager": mgr.get(rid, f"Team {rid}"), "season": int(tx["season"]),
            # Sleeper files offseason moves under week 1; label them as offseason instead.
            "week": None if day < _kickoff(int(tx["season"])) else tx.get("leg"),
            "date": day, "end_date": end_day, "type": "claim" if tx["type"] == "waiver" else "fa",
            "bid": (tx.get("settings") or {}).get("waiver_bid") or 0,
            "value_at_pickup": round(v_add), "peak": round(max(held, default=v_add)), "now_value": round(now),
            "captured": round(captured), "outcome": outcome, "on_roster": outcome == "On roster",
            "hit": captured >= HIT_VALUE, "start_points": round(pts, 1), "starts": starts,
            "history": [round(v) if v is not None and d >= day else None for d, v in zip(dates, series)],
        })

    first = min((p["date"] for p in pickups), default=dates[0] if dates else None)
    keys = ["all"] + [str(s) for s in seasons]
    teams = []
    for rid, t in lg.teams.items():
        stats = {}
        for key in keys:
            ps = [p for p in pickups if p["roster_id"] == rid and (key == "all" or str(p["season"]) == key)]
            # Value of this team's pickups that it was holding at each snapshot.
            series = []
            for j, d in enumerate(dates):
                if first and d < first:
                    series.append(None)
                    continue
                series.append(round(sum((p["history"][j] or 0) for p in ps
                                        if p["date"] <= d and (p["end_date"] is None or d < p["end_date"]))))
            best_v = max(ps, key=lambda p: p["captured"], default=None)
            best_p = max(ps, key=lambda p: p["start_points"], default=None)
            stats[key] = {
                "n": len(ps), "claims": sum(p["type"] == "claim" for p in ps), "fa": sum(p["type"] == "fa" for p in ps),
                "faab": sum(p["bid"] for p in ps), "on_roster": sum(p["on_roster"] for p in ps),
                "hits": sum(p["hit"] for p in ps),
                "value_at_pickup": sum(p["value_at_pickup"] for p in ps), "captured": sum(p["captured"] for p in ps),
                "start_points": round(sum(p["start_points"] for p in ps), 1), "starts": sum(p["starts"] for p in ps),
                "best_value": _brief(best_v, "captured"), "best_points": _brief(best_p, "start_points"),
                "series": series,
            }
        teams.append({"roster_id": rid, "manager": t["manager"], "stats": stats})
    return {"dates": dates, "seasons": seasons, "teams": teams, "pickups": pickups, "hit_value": HIT_VALUE,
            "source": "DynastyProcess weekly snapshots (values) and Sleeper matchups (points)"}


def _brief(p, field):
    if not p or not p[field]:
        return None
    return {"name": p["name"], "pos": p["pos"], "value": p[field]}
