"""Waiver-wire suggestions: which available players to add, who to drop, and what to bid.

Pickup score (value points) = the player's value to your team (dynasty value adjusted for
your window and positional needs, as in trades) + a breakout allowance of up to 750 at a
breakout score of 100. The allowance lets a cheap player with real role-growth signals
outrank a slightly more valuable player with none.
"""
from __future__ import annotations

import math
import statistics

from .trade import _roster_limit, context_value

ALLOWANCE = 750


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

    avail = []
    for pid in P:
        if pid in rostered:
            continue
        a = lg.annotate(lg.player_asset(pid))
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
        why = [n["text"] for n in (a.get("opp") or {}).get("notes", [])]
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
            "n_claims": len(claims), "weeks": lg.opportunity.get("weeks"), "role_season": lg.opportunity.get("role_season")}
