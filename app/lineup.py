"""Start/sit: the best lineup for a team this week.

Projections are Sleeper's weekly stat projections scored with this league's own scoring
settings (so TE premium, PPR level and bonuses count). Each player's week-to-week spread
comes from his projection and position, fit on 2018-2024 regular-season weeks (nflverse):
a typical 15-point WR swings about ±8 points.

- Most points: the lineup with the highest projected total (strict slots first, then flex).
- Best chance to win: starting from that lineup, swaps that raise the chance of outscoring
  this week's opponent (their best projected lineup). A heavy underdog should take on
  variance (higher ceilings on close calls); a heavy favorite should play it safe.
- Players whose game has already started stay where they are (Sleeper locks them).
- Free agents projected to start for you are listed too.
"""
from __future__ import annotations

import datetime as dt
import math

import httpx

from . import sleeper
from .cache import cached
from .league import SLOT_ELIGIBLE

# Weekly standard deviation = A + B x projection, by position (nflverse 2018-2024, players
# averaging 4+ points over 8+ games).
SPREAD = {"QB": (5.34, 0.109), "RB": (3.45, 0.279), "WR": (2.99, 0.331), "TE": (2.05, 0.402)}
CLOSE = 1.5            # points: decisions closer than this are coin flips
OUT = {"Out", "IR", "PUP", "Sus", "NFI", "Doubtful"}
_http = httpx.Client(timeout=45, headers={"User-Agent": "dynasty-trade-helper/1.0"})


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def projections(season: int, week: int) -> dict:
    """player_id -> {stats, date, team, opp} for QB/RB/WR/TE (cached 3 hours)."""
    def fetch():
        url = (f"https://api.sleeper.com/projections/nfl/{season}/{week}?season_type=regular"
               "&position[]=QB&position[]=RB&position[]=WR&position[]=TE")
        rows = _http.get(url).json() or []
        return {r["player_id"]: {"stats": r.get("stats") or {}, "date": r.get("date"), "team": r.get("team"), "opp": r.get("opponent")}
                for r in rows if r.get("player_id")}
    return cached(f"proj2:{season}:{week}", 3 * 3600, fetch)


def score(stats: dict, scoring: dict) -> float:
    return sum(v * scoring[k] for k, v in stats.items() if k in scoring and isinstance(v, (int, float)))


def spread(pos: str, proj: float) -> float:
    a, b = SPREAD.get(pos, (3.0, 0.3))
    return a + b * max(proj, 0.0) if proj > 0 else 0.0


def current_week(lg) -> int | None:
    st = sleeper.nfl_state()
    if str(st.get("season")) != str(lg.season) or st.get("season_type") != "regular":
        return None
    last = ((lg.info.get("settings") or {}).get("playoff_week_start") or 15) + 2
    w = int(st.get("week") or 1)
    return w if w <= last else None


def _player(lg, a: dict, P: dict, scoring: dict, today: str) -> dict:
    p = P.get(a["id"])
    proj = score(p["stats"], scoring) if p and p["stats"].get("gp", 1) else 0.0
    sd = spread(a["pos"], proj)
    role = ((a.get("opp") or {}).get("role") or {}) if isinstance(a.get("opp"), dict) else {}
    return {"id": a["id"], "name": a["name"], "pos": a["pos"], "nfl_team": a.get("nfl_team"), "injury": a.get("injury"),
            "proj": round(proj, 1), "sd": round(sd, 1), "floor": round(max(0.0, proj - 0.84 * sd), 1), "ceiling": round(proj + 0.84 * sd, 1),
            "opp": p.get("opp") if p else None, "date": p.get("date") if p else None, "bye": p is None,
            "locked": bool(p and p.get("date") and p["date"] < today), "l3": role.get("ppg_l3"), "taxi": a.get("taxi"), "ir": a.get("ir")}


def _best(slots: list[str], pool: list[dict], fixed: dict, key) -> dict:
    """slot index -> player: fixed assignments kept, the rest filled greedily (strict slots first)."""
    out = dict(fixed)
    used = {p["id"] for p in fixed.values()}
    for i in sorted((i for i in range(len(slots)) if i not in fixed), key=lambda i: len(SLOT_ELIGIBLE[slots[i]])):
        best = max((p for p in pool if p["id"] not in used and p["pos"] in SLOT_ELIGIBLE[slots[i]]), key=key, default=None)
        if best:
            out[i] = best
            used.add(best["id"])
    return out


def _total(lineup: dict) -> tuple[float, float]:
    return sum(p["proj"] for p in lineup.values()), math.sqrt(sum(p["sd"] ** 2 for p in lineup.values()))


def _win(lineup: dict, opp_mu: float, opp_sd: float) -> float:
    mu, sd = _total(lineup)
    return _phi((mu - opp_mu) / (math.sqrt(sd ** 2 + opp_sd ** 2) or 1))


def analyze(lg, rid: int | None = None, week: int | None = None) -> dict:
    week = week or current_week(lg)
    rid = rid or (lg.me or {}).get("roster_id")
    if not week or rid not in lg.teams:
        return {"week": None}
    lid = lg.cfg["league_id"]
    scoring = lg.info.get("scoring_settings") or {}
    P = projections(lg.season, week)
    today = dt.date.today().isoformat()
    positions = lg.info.get("roster_positions") or []
    slot_idx = [i for i, s in enumerate(positions) if s in SLOT_ELIGIBLE]
    slots = [positions[i] for i in slot_idx]

    def team_players(r):
        return [_player(lg, a, P, scoring, today) for a in lg.teams[r]["players"] if not a.get("taxi") and not a.get("ir")]

    raw = {r["roster_id"]: r for r in sleeper.rosters(lid)}
    mine = team_players(rid)
    by_id = {p["id"]: p for p in mine}
    starters = (raw.get(rid) or {}).get("starters") or []
    current = {k: by_id[starters[i]] for k, i in enumerate(slot_idx) if i < len(starters) and starters[i] in by_id}
    fixed = {k: p for k, p in current.items() if p["locked"]}
    locked_bench = {p["id"] for p in mine if p["locked"] and p not in current.values()}
    pool = [p for p in mine if p["id"] not in locked_bench]
    best_pts = _best(slots, pool, fixed, key=lambda p: p["proj"])

    # Opponent: their best projected lineup this week.
    opp_rid = None
    for m in sleeper.matchups(lid, week, False):
        if m["roster_id"] == rid:
            mid = m.get("matchup_id")
            opp_rid = next((x["roster_id"] for x in sleeper.matchups(lid, week, False) if x.get("matchup_id") == mid and x["roster_id"] != rid), None) if mid else None
    opp = None
    if opp_rid:
        ol = _best(slots, team_players(opp_rid), {}, key=lambda p: p["proj"])
        mu, sd = _total(ol)
        opp = {"roster_id": opp_rid, "manager": lg.teams[opp_rid]["manager"], "proj": round(mu, 1), "sd": round(sd, 1),
               "lineup": [{"slot": slots[i], **ol[i]} for i in sorted(ol)]}

    # Best chance to win: single swaps from the most-points lineup while they help.
    best_win = dict(best_pts)
    if opp:
        for _ in range(6):
            cur = _win(best_win, opp["proj"], opp["sd"])
            used = {p["id"] for p in best_win.values()}
            cand = None
            for i, p in best_win.items():
                if i in fixed:
                    continue
                for q in pool:
                    if q["id"] in used or q["pos"] not in SLOT_ELIGIBLE[slots[i]]:
                        continue
                    trial = {**best_win, i: q}
                    w = _win(trial, opp["proj"], opp["sd"])
                    if w > cur + 0.005 and (cand is None or w > cand[0]):
                        cand = (w, trial)
            if not cand:
                break
            best_win = cand[1]
    rec = best_win

    def lineup_out(lu):
        return [{"slot": slots[i], **lu[i]} for i in sorted(lu)]

    # Changes from the lineup currently set in Sleeper to the recommended one.
    cur_ids = {p["id"] for p in current.values()}
    rec_ids = {p["id"] for p in rec.values()}
    start = sorted((p for p in rec.values() if p["id"] not in cur_ids), key=lambda p: -p["proj"])
    sit = sorted((p for p in current.values() if p["id"] not in rec_ids), key=lambda p: p["proj"])
    why = lambda p: "on bye" if p["bye"] else p["injury"] if p["injury"] in OUT else None
    changes = {"start": [{"name": p["name"], "pos": p["pos"], "proj": p["proj"]} for p in start],
               "sit": [{"name": p["name"], "pos": p["pos"], "proj": p["proj"], "why": why(p)} for p in sit]} if start or sit else None
    flags = [f"{p['name']} is {p['injury']}" for p in rec.values() if p["injury"] in OUT] +             [f"{p['name']} is on bye" for p in rec.values() if p["bye"]]

    # Close calls among the recommended starters and bench.
    bench = sorted((p for p in mine if p["id"] not in rec_ids), key=lambda p: -p["proj"])
    close = []
    for i, p in rec.items():
        for q in bench:
            if q["pos"] in SLOT_ELIGIBLE[slots[i]] and not q["locked"] and abs(p["proj"] - q["proj"]) < CLOSE and q["proj"] > 3:
                close.append({"slot": slots[i], "a": p["name"], "b": q["name"], "a_proj": p["proj"], "b_proj": q["proj"]})
                break

    # Free agents who would start.
    rostered = {a["id"] for t in lg.teams.values() for a in t["players"]}
    worst = {s: min((p["proj"] for i, p in rec.items() if slots[i] == s), default=0) for s in set(slots)}
    fas = []
    for pid, pr in P.items():
        if pid in rostered:
            continue
        info = lg.players_db.get(pid) or {}
        pos = info.get("position")
        if pos not in SPREAD or not info.get("team"):
            continue
        proj = score(pr["stats"], scoring)
        beat = [(s, proj - worst[s]) for s in worst if pos in SLOT_ELIGIBLE[s] and proj - worst[s] >= 1]
        if beat:
            s, gain = max(beat, key=lambda x: x[1])
            fas.append({"id": pid, "name": info.get("full_name") or pid, "pos": pos, "nfl_team": info.get("team"), "proj": round(proj, 1),
                        "slot": s, "gain": round(gain, 1), "injury": info.get("injury_status")})
    fas.sort(key=lambda x: -x["gain"])

    mu_cur, _ = _total(current)
    mu_rec, sd_rec = _total(rec)
    return {"week": week, "roster_id": rid, "manager": lg.teams[rid]["manager"], "is_me": bool(lg.me and rid == lg.me["roster_id"]),
            "teams": [{"roster_id": t["roster_id"], "manager": t["manager"]} for t in lg.teams.values()],
            "current": lineup_out(current), "recommended": lineup_out(rec), "bench": bench,
            "proj_current": round(mu_cur, 1), "proj_recommended": round(mu_rec, 1), "sd": round(sd_rec, 1),
            "proj_most": round(_total(best_pts)[0], 1),
            "win_current": round(_win(current, opp["proj"], opp["sd"]) * 100) if opp and current else None,
            "win_recommended": round(_win(rec, opp["proj"], opp["sd"]) * 100) if opp else None,
            "win_most": round(_win(best_pts, opp["proj"], opp["sd"]) * 100) if opp else None,
            "opponent": opp, "changes": changes, "flags": flags, "close": close[:4], "free_agents": fas[:5],
            "other_slots": [s for s in positions if s not in SLOT_ELIGIBLE and s not in ("BN", "IR", "TAXI")]}
