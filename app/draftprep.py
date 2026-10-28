"""Rookie draft prep: where each pick will land, what it's worth, how each manager drafts,
and (once the rookie class has values) a big board and mock drafts.

- Draft slots come from the season simulation (season.simulate), so a pick's slot is a
  probability spread, not a guess.
- Manager habits come from their past drafts (startup and rookie): position shares vs.
  the league, and how often they took the most valuable player left ("best available").
- Mock drafts: each manager picks the player with the best value x their position habit x
  their positional need, with some randomness, in simulated draft orders.
- The mock is checked by replaying the most recent rookie draft pick by pick: given who was
  already gone, how often was the actual pick the model's first or top-3 choice?
"""
from __future__ import annotations

import datetime as dt
import math
import random
from collections import Counter, defaultdict

from . import drafts as draftmod
from . import sleeper
from .league import POSITIONS

N_MOCKS = 400


def _tier(slot: int, n: int) -> str:
    return "early" if slot <= n / 3 else "mid" if slot <= 2 * n / 3 else "late"


def _pick_label(rnd: int, slot: int) -> str:
    return f"{rnd}.{slot:02d}"


def habits(drafts: list[dict], before: str | None = None) -> dict:
    """roster_id -> {n, pos_share, pos_bias, bpa_rate, avg_rank} from drafts started before
    `before` (ISO date). Uses each pick's draft-day value."""
    picks = [(d, p) for d in drafts if not before or d["start"] < before for p in d["picks"]]
    league_pos = Counter(p["_pos"] for _, p in picks if p.get("_pos") in POSITIONS)
    total = sum(league_pos.values()) or 1
    by = defaultdict(list)
    for d, p in picks:
        by[p["roster_id"]].append((d, p))
    out = {}
    for rid, ps in by.items():
        pos = Counter(p["_pos"] for _, p in ps if p.get("_pos") in POSITIONS)
        n = sum(pos.values()) or 1
        shrink = n / (n + 6)
        bias = {k: max(-1.0, min(1.0, ((pos[k] / n) - league_pos[k] / total) / (league_pos[k] / total or 1))) * shrink
                for k in POSITIONS}
        ranks = []
        for d, p in ps:
            left = [q for q in d["picks"] if q["pick_no"] >= p["pick_no"]]
            ranks.append(1 + sum(q["_dv"] > p["_dv"] for q in left))
        out[rid] = {"n": len(ps), "pos_share": {k: round(pos[k] / n, 3) for k in POSITIONS},
                    "pos_bias": {k: round(v, 3) for k, v in bias.items()},
                    "bpa_rate": round(sum(r == 1 for r in ranks) / len(ranks), 3) if ranks else None,
                    "avg_rank": round(sum(ranks) / len(ranks), 2) if ranks else None}
    return out


def _choice_score(value: float, pos: str, h: dict | None, need: dict) -> float:
    bias = (h or {}).get("pos_bias", {}).get(pos, 0.0)
    return value * (1 + 0.25 * bias) * (1 + 0.08 * max(-1.5, min(2.0, need.get(pos, 0.0))))


def _drafts_with_values(lg) -> list[dict]:
    """Completed drafts with each pick's position and draft-day value attached."""
    drafts_, hist, _ = draftmod.context(lg)
    dates, hv = hist["dates"], hist["values"]
    out = []
    for d in drafts_:
        ps = []
        for p in d["picks"]:
            day = draftmod._ms_to_date(p["_ms"]).isoformat()
            dv = draftmod._value_at(hv.get(p["player_id"]) or [None] * len(dates), dates, day) if dates else 0.0
            ps.append({**p, "_dv": dv, "_pos": (lg.players_db.get(p["player_id"]) or {}).get("position")})
        out.append({**d, "picks": ps})
    return out


def replay(lg, drafts: list[dict]) -> dict | None:
    """Predict each pick of the most recent rookie draft given the picks before it."""
    rookie = [d for d in drafts if d["kind"] == "rookie"]
    if not rookie:
        return None
    d = rookie[-1]
    h = habits(drafts, before=d["start"])
    board = sorted(d["picks"], key=lambda p: -p["_dv"])
    taken, top1, top3, bpa = set(), 0, 0, 0
    for p in sorted(d["picks"], key=lambda p: p["pick_no"]):
        team = lg.teams.get(p["roster_id"]) or {}
        avail = [q for q in board if q["player_id"] not in taken]
        ranked = sorted(avail, key=lambda q: -_choice_score(q["_dv"], q["_pos"], h.get(p["roster_id"]), team.get("need_future", {})))
        ids = [q["player_id"] for q in ranked]
        top1 += ids[:1] == [p["player_id"]]
        top3 += p["player_id"] in ids[:3]
        bpa += avail[0]["player_id"] == p["player_id"]
        taken.add(p["player_id"])
    n = len(d["picks"])
    return {"draft": d["label"], "n": n, "top1": round(top1 / n, 3), "top3": round(top3 / n, 3), "bpa_top1": round(bpa / n, 3)}


def analyze(lg, sim: dict) -> dict:
    season = lg.pick_seasons[0]
    n = len(lg.teams)
    rounds = lg.draft_rounds
    slot_probs = {t["roster_id"]: t["slot_probs"] for t in sim["teams"]}
    # A rookie draft for this season that hasn't happened yet has its order once it's set.
    last = next((d for d in reversed(sleeper.cached_drafts(lg.cfg["league_id"])) if d.get("type")), {})
    snake = last.get("type") == "snake"

    def slot_in_round(rnd, slot):
        return n + 1 - slot if snake and rnd % 2 == 0 else slot

    # Projected slots come from the simulation only for next year's draft; later drafts are unknown.
    picks = []
    for t in lg.teams.values():
        for pk in t["picks"]:
            if pk["season"] != season:
                continue
            probs = slot_probs.get(pk["orig_roster_id"]) if season == sim["draft_season"] else None
            exp = sum((i + 1) * p for i, p in enumerate(probs)) if probs else None
            lo = hi = None
            if probs:
                cum, lo, hi = 0.0, None, None
                for i, p in enumerate(probs):
                    cum += p
                    if lo is None and cum >= 0.1:
                        lo = i + 1
                    if hi is None and cum >= 0.9:
                        hi = i + 1
            tier = _tier(round(exp), n) if exp else pk.get("tier")
            v = lg.values.pick(season, pk["round"], tier)
            orig = lg.teams.get(pk["orig_roster_id"], {})
            picks.append({
                "id": pk["id"], "round": pk["round"], "owner_rid": t["roster_id"], "owner": t["manager"],
                "orig_rid": pk["orig_roster_id"], "orig": orig.get("manager"),
                "exp_slot": round(exp, 1) if exp else None, "range": [lo, hi] if lo else None,
                "label": _pick_label(pk["round"], slot_in_round(pk["round"], round(exp))) if exp else f"Round {pk['round']}",
                "overall": round((pk["round"] - 1) * n + slot_in_round(pk["round"], round(exp))) if exp else None,
                "slot_probs": probs, "tier": tier, "value": round(v["value"]),
            })
    picks.sort(key=lambda p: (p["round"], p["exp_slot"] or 99))
    capital = defaultdict(lambda: {"n": 0, "value": 0, "firsts": 0})
    for p in picks:
        c = capital[p["owner_rid"]]
        c["n"] += 1
        c["value"] += p["value"]
        c["firsts"] += p["round"] == 1
    cap_rows = sorted(({"roster_id": rid, "manager": lg.teams[rid]["manager"], **c} for rid, c in capital.items()),
                      key=lambda r: -r["value"])

    drafts = _drafts_with_values(lg)
    h = habits(drafts)
    tend = []
    for rid, t in lg.teams.items():
        x = h.get(rid)
        if not x:
            continue
        fav = max(POSITIONS, key=lambda k: x["pos_bias"][k])
        tend.append({"roster_id": rid, "manager": t["manager"], **x,
                     "favorite": fav if x["pos_bias"][fav] > 0.1 else None,
                     "needs": [p for p in POSITIONS if t.get("need_future", {}).get(p, 0) >= 0.5]})
    tend.sort(key=lambda r: r["manager"].lower())

    # Big board: unrostered rookies with values, while this season's rookie draft is still ahead.
    rostered = {a["id"] for t in lg.teams.values() for a in t["players"]}
    board = []
    if season == lg.season:
        for pid, p in lg.players_db.items():
            if p.get("years_exp") == 0 and p.get("position") in POSITIONS and pid not in rostered:
                v = lg.values.player(pid)["value"]
                if v > 0:
                    board.append({"id": pid, "name": p.get("full_name"), "pos": p["position"], "nfl_team": p.get("team"), "value": round(v)})
        board.sort(key=lambda r: -r["value"])
    mock = _mock(lg, board, picks, h, sim.get("_orders") if season == sim["draft_season"] else None) if board else []
    return {"season": season, "teams": n, "rounds": rounds, "snake": snake, "draft_rule": sim["draft_rule"],
            "projected": season == sim["draft_season"], "picks": picks, "capital": cap_rows, "habits": tend,
            "board": board[:60], "mock": mock, "replay": replay(lg, drafts),
            "me": lg.me["roster_id"] if lg.me else None}


def _mock(lg, board: list, picks: list, h: dict, orders: list | None = None, n_mocks: int = N_MOCKS, seed: int = 11) -> list:
    """For each of my picks: how often each board player is still there, and how often I'd take him.
    Each mock uses one simulated draft order (from the season simulation) or a random one."""
    me = lg.me["roster_id"] if lg.me else None
    rng = random.Random(seed)
    mine = [p for p in picks if p["owner_rid"] == me]
    by_orig = {(p["round"], p["orig_rid"]): p for p in picks}
    rids = list(lg.teams)
    avail = defaultdict(Counter)
    taken_by_me = defaultdict(Counter)
    for i in range(n_mocks):
        slots = orders[i % len(orders)] if orders else rng.sample(rids, len(rids))
        rounds = sorted({p["round"] for p in picks})
        seq = [by_orig[(r, rid)] for r in rounds for rid in slots if (r, rid) in by_orig]
        gone = set()
        for p in seq:
            team = lg.teams.get(p["owner_rid"]) or {}
            left = [b for b in board if b["id"] not in gone]
            if not left:
                break
            if p["owner_rid"] == me:
                for b in left:
                    avail[p["id"]][b["id"]] += 1
            pick = max(left, key=lambda b: _choice_score(b["value"], b["pos"], h.get(p["owner_rid"]), team.get("need_future", {}))
                       * math.exp(rng.gauss(0, 0.25)))
            if p["owner_rid"] == me:
                taken_by_me[p["id"]][pick["id"]] += 1
            gone.add(pick["id"])
    by_id = {b["id"]: b for b in board}
    out = []
    for p in mine:
        cands = sorted(avail[p["id"]].items(), key=lambda kv: (-taken_by_me[p["id"]][kv[0]], -kv[1]))[:8]
        out.append({"pick": p["id"], "label": p["label"], "round": p["round"],
                    "candidates": [{**by_id[pid], "available": round(c / n_mocks, 3),
                                    "taken": round(taken_by_me[p["id"]][pid] / n_mocks, 3)} for pid, c in cands]})
    return out
