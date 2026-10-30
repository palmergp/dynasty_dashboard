"""Roster room next offseason: who goes on the taxi squad, who has to come off it, and who
to cut (or trade first) when the incoming rookie class overflows the roster.

For next season, per team:
- Rookies: one per pick the team owns in the next rookie draft, valued at the pick.
- Taxi: players stay on taxi through their first `taxi_years` NFL seasons, so current taxi
  players who'll be past that next season move to the active roster. Open taxi spots go to
  the incoming rookies (lowest-valued first, so the best rookie stays active), and, where
  the league allows veterans on taxi, to other taxi-age players not starting.
- Active roster = everyone else except players on IR now (listed separately: they take a
  roster spot again if they're healthy). Anything over the roster limit has to be cut. The app tracks QB/RB/WR/TE
  only, so each kicker, defense or IDP starting slot takes one spot off the limit.
- Cut order: lowest expected value a year from now (age curve) first, taxi players included
  (cutting one lets an incoming rookie take his taxi spot). Players still worth something
  should be packaged in a 2-for-1 trade before cutting.

The league table shows every team's crunch: players other teams may have to cut are cheap
to trade for now and may reach waivers.
"""
from __future__ import annotations

from .league import SLOT_ELIGIBLE

TRADE_FIRST = 500  # cut candidates worth at least this can usually be traded instead


def _keep(a: dict) -> float:
    """Value a year from now (expected value from the age curve), or the pick value for a rookie."""
    if a["kind"] == "rookie":
        return a["value"]
    path = (a.get("age_outlook") or {}).get("path") or []
    return float(path[0]["typical"]) if path and path[0].get("typical") is not None else a["value"] * 0.85


def _plan(lg, t: dict, st: dict) -> dict:
    nxt = lg.season + 1
    limit = st["limit"]
    years = st["taxi_years"] or 0
    taxi_age = lambda a: (a.get("years_exp") or 0) + 1 < years  # still taxi-eligible next season
    players = [a for a in t["players"] if a["kind"] == "player"]
    rookies = [{"kind": "rookie", "id": pk["id"], "name": f"Rookie from {pk['name']}", "pos": "ROOKIE", "value": pk["value"],
                "age": None, "pick": pk["name"]} for pk in t["picks"] if pk["season"] == nxt]
    stay = [a for a in players if a.get("taxi") and taxi_age(a)]
    promoted = [a for a in players if a.get("taxi") and not taxi_age(a)]
    ir = [a for a in players if a.get("ir") and not a.get("taxi")]
    active = [a for a in players if not a.get("taxi") and not a.get("ir")] + promoted
    open_spots = max(0, st["taxi_slots"] - len(stay))
    to_taxi = sorted(rookies, key=lambda r: r["value"])[:open_spots]
    if st["allow_vets"]:
        extra = sorted((a for a in active if taxi_age(a) and not a.get("starter") and a not in promoted),
                       key=lambda a: a["redraft"])[:open_spots - len(to_taxi)]
        to_taxi += extra
        active = [a for a in active if a not in extra]
    taxi_ids = {a["id"] for a in to_taxi}
    active += [r for r in rookies if r["id"] not in taxi_ids]
    over = len(active) - limit
    # A taxi player can be cut too: an active rookie then takes his taxi spot, which frees an
    # active spot just the same (as many as there are active rookies to swap in).
    swappable = sum(1 for a in active if a["kind"] == "rookie")
    order, n_taxi = [], 0
    for a in sorted(active + stay, key=_keep):
        if a in stay:
            if n_taxi >= swappable:
                continue
            n_taxi += 1
        order.append(a)
    slim = lambda a: {"kind": a["kind"], "id": a["id"], "name": a["name"], "pos": a["pos"], "age": a.get("age"),
                      "value": round(a["value"]), "keep": round(_keep(a)), "years_exp": a.get("years_exp"),
                      "starter": bool(a.get("starter")), "taxi": a in stay}
    cuts = [slim(a) for a in order[:max(over, 0)]]
    return {"roster_id": t["roster_id"], "manager": t["manager"], "is_me": bool(lg.me and t is lg.me),
            "rookies": [slim(r) for r in rookies], "taxi_stay": [slim(a) for a in stay], "promoted": [slim(a) for a in promoted],
            "to_taxi": [slim(a) for a in to_taxi], "ir": [slim(a) for a in ir], "active": len(active), "over": over, "cuts": cuts,
            "trade_first": [c for c in cuts if c["value"] >= TRADE_FIRST],
            "next_cuts": [slim(a) for a in order[max(over, 0):max(over, 0) + 3]],
            "cut_value": sum(c["value"] for c in cuts)}


def analyze(lg) -> dict:
    s = lg.info.get("settings") or {}
    slots = [x for x in lg.info.get("roster_positions") or [] if x not in ("IR", "TAXI")]
    other = sum(1 for x in slots if x not in ("BN",) and x not in SLOT_ELIGIBLE)  # K, DEF, IDP: one rostered each
    st = {"limit": len(slots) - other, "other_slots": other,
          "taxi_slots": s.get("taxi_slots") or 0, "taxi_years": s.get("taxi_years") or 0,
          "allow_vets": bool(s.get("taxi_allow_vets")), "ir_slots": s.get("reserve_slots") or 0}
    teams = [_plan(lg, t, st) for t in lg.teams.values()]
    me = next((t for t in teams if t["is_me"]), None)
    others = sorted((t for t in teams if not t["is_me"]), key=lambda t: (-t["over"], -t["cut_value"]))
    likely = sorted(({**c, "manager": t["manager"], "roster_id": t["roster_id"]} for t in others for c in t["cuts"]),
                    key=lambda c: -c["value"])[:10]
    return {"season": lg.season + 1, "settings": st, "me": me, "teams": others, "likely_cuts": likely}
