"""Franchise rankings: overall team state (roster + draft capital) plus the breakdowns
behind it. Covers value composition, age structure, positional heatmap inputs, and roster
value over time.

Roster value over time is rebuilt by replaying every add/drop (draft picks, trades,
waivers) to get each team's roster at each weekly snapshot, then summing the players'
DynastyProcess values at that date. Picks are excluded from the history because there's
no pick-value history.
"""
from __future__ import annotations

import datetime as dt

from . import drafts as draftmod
from .league import POSITIONS

CORE_N = 10
AGE_BUCKETS = (("u24", "23 & under", 0, 23.99), ("24_26", "24–26", 24, 26.99), ("27_29", "27–29", 27, 29.99), ("30p", "30+", 30, 99))


def _bucket(age) -> str:
    if age is None:
        return "24_26"
    return next(k for k, _, lo, hi in AGE_BUCKETS if lo <= age <= hi)


def roster_history(lg) -> dict:
    """{"dates": [...], "values": {roster_id: [value per date]}} from replayed rosters."""
    _, hist, events = draftmod.context(lg)
    dates, hv = hist["dates"], hist["values"]
    rosters = {rid: set() for rid in lg.teams}
    out = {rid: [] for rid in lg.teams}
    first = next((e[0] for e in events), None)
    k = 0
    for i, d in enumerate(dates):
        end_ms = (dt.datetime.fromisoformat(d) + dt.timedelta(days=1)).timestamp() * 1000
        while k < len(events) and events[k][0] < end_ms:
            _, pid, rid, _, kind, _ = events[k]
            if rid in rosters:
                (rosters[rid].add if kind == "add" else rosters[rid].discard)(pid)
            k += 1
        started = first is not None and first < end_ms
        for rid, ps in rosters.items():
            out[rid].append(round(sum((hv.get(pid) or [0] * len(dates))[i] or 0 for pid in ps)) if started else None)
    return {"dates": dates, "values": out, "final_rosters": rosters}


def analyze(lg) -> dict:
    hist = roster_history(lg)
    teams = []
    for rid, t in lg.teams.items():
        players = sorted(t["players"], key=lambda a: -a["value"])
        core = sum(a["value"] for a in players[:CORE_N])
        depth = sum(a["value"] for a in players[CORE_N:])
        ages = {k: 0 for k, *_ in AGE_BUCKETS}
        for a in players:
            ages[_bucket(a["age"])] += a["value"]
        pick_seasons = {str(s): round(sum(p["value"] for p in t["picks"] if p["season"] == s)) for s in lg.pick_seasons}
        teams.append({
            "roster_id": rid, "manager": t["manager"], "team_name": t["team_name"], "window": t["window"],
            "contend_score": t["contend_score"], "win_now": t["starter_redraft"],
            "franchise_value": t["franchise_value"], "franchise_score": t["franchise_score"], "franchise_rank": t["franchise_rank"],
            "player_value": t["dynasty_total"], "pick_value": t["pick_total"], "core": round(core), "depth": round(depth),
            "n_players": len(players), "n_picks": len(t["picks"]), "age": t["avg_age_weighted"],
            "age_value": {k: round(v) for k, v in ages.items()}, "pick_seasons": pick_seasons,
            "need_now": t["need_now"], "need_future": t["need_future"],
            "top_players": [{"name": a["name"], "pos": a["pos"], "value": a["value"]} for a in players[:3]],
            "history": hist["values"][rid],
        })
    teams.sort(key=lambda x: x["franchise_rank"])
    return {
        "teams": teams, "dates": hist["dates"], "positions": list(POSITIONS),
        "age_buckets": [{"key": k, "label": l} for k, l, *_ in AGE_BUCKETS],
        "pick_seasons": [str(s) for s in lg.pick_seasons], "core_n": CORE_N,
    }
