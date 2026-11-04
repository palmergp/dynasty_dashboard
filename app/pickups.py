"""Waiver-wire suggestions: which available players to add, who to drop, and what to bid.

Pickup score (value points) = the player's value to your team (dynasty value adjusted for
your window and positional needs, as in trades) + a breakout allowance of up to 750 at a
breakout score of 100. The allowance lets a cheap player with real role-growth signals
outrank a slightly more valuable player with none.

Projected starters: each NFL team's top-projected QB, RB and TE and top two WRs for the
coming week (Sleeper's projections in league scoring). A starter no value source has priced
yet, like an undrafted QB thrown in after two injuries, would otherwise count as worthless,
so he's valued like the cheaper of the five other starters at his position projected
closest to him (the lower quartile of their dynasty and win-now values).
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict

from . import lineup
from .opportunity import STARTERS
from .trade import _roster_limit, context_value

ALLOWANCE = 750
COMPS = 5              # comparable starters for an unpriced projected starter


def pickup_score(a: dict, team: dict) -> float:
    return context_value(a, team) + ALLOWANCE * a.get("breakout", 0) / 100


def _bid(value: float, claims: list[tuple[float, int]], left: int) -> dict:
    """Suggested FAAB bid from this league's past winning claims on similar-value players."""
    if not claims:
        return {"mid": 1, "lo": 0, "hi": 3, "n": 0}
    lv = math.log(max(value, 50))
    near = sorted(claims, key=lambda c: abs(math.log(max(c[0], 50)) - lv))[:8]
    bids = sorted(b for _, b in near)
    q = lambda f: bids[min(len(bids) - 1, int(f * (len(bids) - 1) + 0.5))]
    return {"mid": min(left, round(statistics.median(bids))), "lo": min(left, q(0.25)), "hi": min(left, q(0.75)), "n": len(near)}


def projected_starters(lg) -> tuple[int | None, dict]:
    """(week, pid -> projected points) for every NFL team's projected starters that week."""
    week = lineup.current_week(lg)
    if week is None:
        return None, {}
    sc = lg.info.get("scoring_settings") or {}
    by = defaultdict(list)
    for pid, r in lineup.projections(lg.season, week).items():
        pos = (lg.players_db.get(pid) or {}).get("position")
        pts = lineup.score(r["stats"], sc)
        if pos in STARTERS and r.get("team") and pts > 0:
            by[(r["team"], pos)].append((pts, pid))
    return week, {pid: round(pts, 1) for (_, pos), rows in by.items() for pts, pid in sorted(rows, reverse=True)[:STARTERS[pos]]}


def starter_price(lg, pid: str, starters: dict) -> dict | None:
    """Value for an unpriced projected starter: the lower quartile of the values of the COMPS
    priced starters at his position projected closest to him."""
    pos, pts = (lg.players_db.get(pid) or {}).get("position"), starters[pid]
    near = sorted((abs(p - pts), q) for q, p in starters.items() if q != pid and (lg.players_db.get(q) or {}).get("position") == pos)
    comps = [c for c in (lg.player_asset(q) for _, q in near) if c["value"] > 0][:COMPS]
    if len(comps) < COMPS:
        return None
    lq = lambda xs: sorted(xs)[len(xs) // 4]
    return {"value": lq([c["value"] for c in comps]), "redraft": lq([c["redraft"] for c in comps]), "n": len(comps)}


def suggest(lg, waiver_report: dict) -> dict:
    me = lg.me
    rostered = {a["id"] for t in lg.teams.values() for a in t["players"]}
    P = lg.opportunity["players"]
    budget = (lg.info.get("settings") or {}).get("waiver_budget", 0)
    left = max(0, budget - me.get("faab_used", 0))
    st = lg.info.get("settings") or {}
    limit = _roster_limit(lg)
    active = [a for a in me["players"] if not a.get("taxi") and not a.get("ir")]
    open_spots = max(0, limit - len(active))
    open_taxi = max(0, st.get("taxi_slots", 0) - sum(1 for a in me["players"] if a.get("taxi")))
    taxi_years = st.get("taxi_years", 0)

    drops = sorted(({"asset": a, "score": round(pickup_score(a, me))} for a in active), key=lambda d: d["score"])
    claims = [(p["value_at_pickup"], p["bid"]) for p in waiver_report.get("pickups", [])
              if p["type"] == "claim" and p["season"] >= lg.season - 1]

    try:
        week, starters = projected_starters(lg)
    except Exception:  # projections are a bonus; never block the page on them
        week, starters = None, {}
    avail = []
    for pid in P:
        if pid in rostered:
            continue
        a = lg.annotate(lg.player_asset(pid))
        if pid in starters:
            a["proj"] = {"week": week, "pts": starters[pid]}
            est = starter_price(lg, pid, starters) if not a["sources"] else None
            if est and est["value"] > a["value"]:
                a.update(value=est["value"], redraft=max(a["redraft"], est["redraft"]), est=est)
        if a["value"] <= 0 and a["breakout"] <= 0 and not a["opp_score"]:
            continue
        avail.append({"asset": a, "score": round(pickup_score(a, me))})
    avail.sort(key=lambda r: -r["score"])

    worst = drops[0] if drops else None
    out = []
    for r in avail[:60]:
        a = r["asset"]
        taxi_ok = open_taxi > 0 and (a.get("years_exp") or 0) < taxi_years
        drop = None if (open_spots or taxi_ok) else worst
        gain = r["score"] - (drop["score"] if drop else 0)
        if drop and gain <= 50:
            continue
        why = []
        if a.get("proj"):
            why.append(f"Projected to start for {a['nfl_team']} in week {week}: {a['proj']['pts']} pts")
        if a.get("est"):
            why.append(f"No value source has priced him yet, so he's valued like the cheaper starting {a['pos']}s "
                       f"projected about the same ({a['est']['n']} of them)")
        why += [n["text"] for n in (a.get("opp") or {}).get("notes", [])]
        need_field = "need_now" if me.get("w", 0.5) >= 0.5 else "need_future"
        if me.get(need_field, {}).get(a["pos"], 0) >= 0.5:
            why.append(f"Fills a {a['pos']} need on your roster")
        if me.get("w", 0.5) >= 0.5 and a["redraft"] >= 1500:
            why.append(f"Startable now: win-now value {a['redraft']:,}")
        out.append({**r, "drop": drop, "gain": round(gain), "taxi_ok": taxi_ok,
                    "bid": _bid(a["value"], claims, left), "why": why})
        if len(out) >= 12:
            break
    return {"budget": budget, "faab_left": left, "roster_limit": limit, "active": len(active),
            "open_spots": open_spots, "open_taxi": open_taxi, "taxi_years": taxi_years,
            "drops": drops[:6], "suggestions": out, "available": avail[:300],
            "n_claims": len(claims), "proj_week": week, "weeks": lg.opportunity.get("weeks"), "role_season": lg.opportunity.get("role_season")}
