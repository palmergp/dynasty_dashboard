"""Second-half outlook: who should score more (or less) from here, and win-now trade targets.

What predicts a player's points per game for the rest of the season from the weeks so far?
Backtest on nflverse weekly stats, 2016-2025 (players with 3+ games and 5+ PPR points a game,
seasons split after weeks 5, 8 and 11, each season predicted from the others):

- Volume beats points. Targets and carries per game predict RB, WR and TE scoring better
  than points per game do: players whose points lag their volume tend to catch up, and
  players scoring above their volume tend to cool off. Where this model and a points-only
  forecast disagreed by 1.5+ points a game at midseason, the model was right 64-70% of the
  time (RB 68%, WR 64%, TE 70%) and players moved most of the predicted gap. For WRs the
  edge fades after week 11.
- Recent form (last 3 games) and a rising or falling role added little beyond season averages.
- Matchups barely carry over: the points a defense allowed by position in weeks 1-8 correlate
  only 0.18 with what it allows in weeks 9-17. Schedule helped a little for RBs only; the
  fantasy-playoff schedule (weeks 15-17) predicted nothing at any position.
- QBs: points per game alone, with strong regression toward the middle.

Outlook per game = the average of that model and Sleeper's projections for the remaining
weeks (which know about injuries, trades and depth-chart changes), in the league's scoring.
Games left = remaining weeks Sleeper projects him to play (bye or out = none).

Trade math uses only the backtested part: the usage model vs. a points-only forecast (about
what a market that prices on points expects), times the share of that gap players closed
(about 75%), capped at 15% of win-now value. QBs get none.
"""
from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

from . import lineup, opportunity
from .cache import cached

# Rest-of-season PPR points per game, fit at three split weeks (linear in between).
# QB: [const, ppg]; RB/WR/TE: [const, ppg, ppg last 3, opportunities/g, (opp. last 3 - opp./g)]
# plus, for RBs, ppg x (schedule factor - 1).
COEF = {
    5: {"QB": [7.71, 0.488], "RB": [1.672, 0.169, 0.155, 0.358, -0.025, 0.478],
        "WR": [1.746, 0.33, 0.048, 0.447, -0.255], "TE": [1.112, 0.209, 0.029, 0.697, 0.016]},
    8: {"QB": [7.361, 0.52], "RB": [1.671, 0.286, 0.175, 0.256, -0.091, 1.175],
        "WR": [0.92, 0.295, 0.111, 0.516, -0.093], "TE": [0.892, 0.334, -0.05, 0.695, 0.087]},
    11: {"QB": [7.296, 0.534], "RB": [1.044, 0.408, 0.099, 0.275, 0.104, 0.354],
         "WR": [0.993, 0.409, 0.151, 0.351, 0.034], "TE": [0.652, 0.353, 0.153, 0.471, -0.138]},
}
# Points-only forecast [const, ppg], the baseline the usage model is measured against.
BASE = {5: {"RB": [3.121, 0.678], "WR": [2.855, 0.653], "TE": [2.05, 0.7]},
        8: {"RB": [2.522, 0.726], "WR": [1.911, 0.75], "TE": [1.566, 0.774]},
        11: {"RB": [2.159, 0.781], "WR": [1.581, 0.802], "TE": [1.078, 0.847]}}
REALIZED = 0.75       # share of the model-vs-points-only gap players closed (backtest, midseason)
MIN_GAMES, MIN_PPG = 3, 5.0
SHRINK = 8            # games of league-average defense mixed into each defense's RB points allowed
MOVE = 1.5            # points a game: a change worth calling out
EDGE_CAP = 0.15       # most the outlook can move a player's win-now value in trade math
CONTENDER_ODDS = 60   # owners this likely to make the playoffs rarely sell starters
SELLER_ODDS = 25


def _coef(pos: str, n: int, table: dict = COEF) -> list[float]:
    keys = sorted(table)
    if n <= keys[0]:
        return table[keys[0]][pos]
    if n >= keys[-1]:
        return table[keys[-1]][pos]
    lo = max(k for k in keys if k <= n)
    hi = min(k for k in keys if k >= n)
    if lo == hi:
        return table[lo][pos]
    t = (n - lo) / (hi - lo)
    return [a + t * (b - a) for a, b in zip(table[lo][pos], table[hi][pos])]


def edge(pos: str, u: dict, n_weeks: int, model: float | None) -> float:
    """Win-now value adjustment: how far the usage model sits from a points-only forecast."""
    if model is None or pos not in BASE[8]:
        return 0.0
    c = _coef(pos, n_weeks, BASE)
    base = c[0] + c[1] * u["ppg"]
    return max(-EDGE_CAP, min(EDGE_CAP, REALIZED * (model - base) / base))


def model_ppg(pos: str, u: dict, n_weeks: int, sched: float = 1.0) -> float | None:
    """Rest-of-season PPR points per game from usage so far (None if too little to go on)."""
    if pos not in COEF[8] or u["games"] < MIN_GAMES or u["ppg"] < MIN_PPG:
        return None
    c = _coef(pos, n_weeks)
    if pos == "QB":
        return c[0] + c[1] * u["ppg"]
    x = [u["ppg"], u["ppg_l3"], u["wo_pg"], u["wo_l3"] - u["wo_pg"]]
    if pos == "RB":
        x.append(u["ppg"] * (sched - 1))
    return c[0] + sum(a * b for a, b in zip(c[1:], x))


def _proj_week(lg, w: int) -> tuple[dict, dict]:
    """(pid -> (league points, PPR points, game date), team -> opponent) for one week."""
    scoring = lg.info.get("scoring_settings") or {}
    out, opp = {}, {}
    for pid, p in lineup.projections(lg.season, w).items():
        if p.get("team") and p.get("opp"):
            opp[p["team"]] = p["opp"]
        st = p.get("stats") or {}
        if st.get("gp", 1):
            out[pid] = (lineup.score(st, scoring), st.get("pts_ppr") or 0.0, p.get("date"))
    return out, opp


def _opponents(lg, w: int) -> dict:
    """team -> opponent for a completed week (kept for good)."""
    return cached(f"opps:{lg.season}:{w}", None, lambda: _proj_week(lg, w)[1])


def _rb_allowed(lg, weekly: dict) -> dict:
    """Defense -> RB points allowed per game relative to the league (1.0 = average), shrunk."""
    by = defaultdict(lambda: defaultdict(float))
    for w, data in weekly.items():
        opp = _opponents(lg, w)
        for s in data.values():
            if s.get("pos") == "RB" and opp.get(s.get("team")):
                by[opp[s["team"]]][w] += s.get("pts_ppr", 0.0)
    per = {d: (statistics.mean(v.values()), len(v)) for d, v in by.items()}
    if not per:
        return {}
    avg = statistics.mean(m for m, _ in per.values())
    return {d: (m * n + avg * SHRINK) / (n + SHRINK) / avg for d, (m, n) in per.items()}


def _reasons(pos, u, so_far, model, sleeper, rate, f, sched, missed, left, po_missed, eff) -> list[str]:
    out = []
    if model is not None:
        m = model * f
        if pos == "QB":
            if m <= so_far - MOVE:
                out.append(f"Hot start: QBs scoring {so_far:.1f} a game usually come back toward the pack.")
            elif m >= so_far + MOVE:
                out.append(f"Slow start: QBs at {so_far:.1f} a game usually bounce back.")
        elif m >= so_far + MOVE and eff is not None and eff <= 0.9:
            out.append(f"Volume says more: {u['wo_pg']:.1f} opportunities a game (targets count 1.5) but {so_far:.1f} points; that volume usually scores more.")
        elif m <= so_far - MOVE and eff is not None and eff >= 1.1:
            out.append(f"Scoring above his volume ({u['wo_pg']:.1f} opportunities a game for {so_far:.1f} points); that usually cools off.")
        elif m >= so_far + MOVE:
            out.append(f"Slow start for his role: the model expects {m:.1f} a game from here.")
        elif m <= so_far - MOVE:
            out.append(f"Hot start: the model expects {m:.1f} a game from here.")
    if sched is not None and abs(sched - 1) >= 0.04:
        out.append(f"{'Soft' if sched > 1 else 'Tough'} schedule for RBs from here: opponents have allowed "
                   f"{abs(sched - 1) * 100:.0f}% {'more' if sched > 1 else 'fewer'} RB points than average.")
    if sleeper is not None and model is not None and abs(sleeper - model * f) >= max(MOVE, 0.2 * model * f):
        out.append(f"Sleeper projects {sleeper:.1f} a game from here, {'above' if sleeper > model * f else 'below'} the usage model's "
                   f"{model * f:.1f} (projections know about injuries, trades and depth charts).")
    elif model is None and sleeper is not None:
        out.append(f"Small role so far ({u['ppg']:.1f} a game); the outlook is Sleeper's projection." if u and u["games"] >= MIN_GAMES
                   else f"Only {u['games']} game{'' if u['games'] == 1 else 's'} so far; the outlook is Sleeper's projection." if u
                   else "No games yet this season; the outlook is Sleeper's projection.")
    if missed:
        out.append(f"Projected to miss {missed} of the next {left + missed} games.")
    if po_missed:
        out.append(f"Projected to miss {po_missed} fantasy playoff game{'s' if po_missed > 1 else ''}.")
    return out


def build(lg) -> dict | None:
    """Outlook for every rostered QB/RB/WR/TE. None outside the regular season."""
    cur = lineup.current_week(lg)
    st = lg.info.get("settings") or {}
    po_start = st.get("playoff_week_start") or 15
    if not cur or cur >= po_start + 3:
        return None
    weekly = opportunity.season_stats(lg.season)
    done = sorted(weekly)
    use = opportunity.usage(weekly)
    allowed = _rb_allowed(lg, weekly) if done else {}
    reg = [w for w in range(cur, po_start)]
    po = [w for w in range(max(cur, po_start), po_start + 3)]
    weeks = reg + po
    proj, opps = {}, {}
    for w in weeks:
        proj[w], opps[w] = _proj_week(lg, w)
    today = dt.date.today().isoformat()

    # Points per opportunity by position, for the "volume says more" check.
    ppo = defaultdict(list)
    for u in use.values():
        if u["games"] >= MIN_GAMES and u["wo_pg"] >= 3 and u["pos"] in COEF[8]:
            ppo[u["pos"]].append(u["ppg"] / u["wo_pg"])
    med = {p: statistics.median(v) for p, v in ppo.items() if v}

    out = {}
    for t in lg.teams.values():
        for a in t["players"]:
            if a["kind"] != "player" or a["pos"] not in COEF[8]:
                continue
            pid, u = a["id"], use.get(a["id"])
            team = a.get("nfl_team")
            play, missed, po_missed, lg_pts, ppr_pts, opp_left = {}, 0, 0, 0.0, 0.0, []
            for w in weeks:
                p = proj[w].get(pid)
                if w == cur and p and p[2] and p[2] < today:
                    continue  # this week's game is already played
                has_game = bool(opps[w].get(team))
                if has_game:
                    opp_left.append(opps[w][team])
                if p and p[0] > 0.3:
                    play[w] = True
                    lg_pts += p[0]
                    ppr_pts += p[1]
                elif has_game:
                    missed += w in reg
                    po_missed += w in po
            n_play = len(play)
            sleeper = lg_pts / n_play if n_play else None
            f = lg_pts / ppr_pts if ppr_pts > 0 else 1.0
            sched = None
            if a["pos"] == "RB" and allowed and opp_left:
                sched = statistics.mean(allowed.get(o, 1.0) for o in opp_left)
            model = model_ppg(a["pos"], u, len(done), sched or 1.0) if u else None
            so_far = u["ppg"] * f if u else None
            parts = [x for x in (model * f if model is not None else None, sleeper) if x is not None]
            rate = statistics.mean(parts) if parts else None
            if rate is None:
                continue
            eff = (u["ppg"] / u["wo_pg"]) / med[a["pos"]] if u and u["wo_pg"] and med.get(a["pos"]) else None
            left_reg = sum(1 for w in play if w in reg)
            left_po = sum(1 for w in play if w in po)
            out[pid] = {
                "id": pid, "name": a["name"], "pos": a["pos"], "nfl_team": team, "age": a.get("age"),
                "injury": a.get("injury"), "value": a["value"], "redraft": a["redraft"],
                "owner_rid": t["roster_id"], "owner": t["manager"],
                "games": u["games"] if u else 0, "so_far": round(so_far, 1) if so_far is not None else None,
                "model": round(model * f, 1) if model is not None else None,
                "sleeper": round(sleeper, 1) if sleeper is not None else None,
                "rate": round(rate, 1), "change": round(rate - so_far, 1) if so_far is not None else None,
                "left": left_reg, "left_po": left_po, "weeks_reg": len(reg), "weeks_po": len(po),
                "ros": round(rate * left_reg, 1), "po": round(rate * left_po, 1),
                "sched": round(sched, 3) if sched is not None else None, "edge": round(edge(a["pos"], u, len(done), model), 3),
                "opp_pg": round(u["wo_pg"], 1) if u else None,
                "play": sorted(play), "reasons": _reasons(a["pos"], u, so_far or 0.0, model, sleeper, rate, f, sched,
                                                          missed, left_reg, po_missed, eff),
            }
    return {"week": cur, "weeks_done": len(done), "reg_weeks": reg, "po_weeks": po, "players": out}


def attach(lg) -> None:
    """Short outlook on each player asset (used by trade math and notes)."""
    h = lg.h2 or {"players": {}}
    for t in lg.teams.values():
        for a in t["players"]:
            o = h["players"].get(a["id"])
            if o:
                a["h2"] = {k: o[k] for k in ("rate", "so_far", "change", "left", "left_po", "edge")}


def note(a: dict) -> str | None:
    o = a.get("h2")
    if not o or o["change"] is None or abs(o["change"]) < MOVE:
        return None
    return (f"Second half: projects {o['rate']:.1f} a game from here, "
            f"{'up from' if o['change'] > 0 else 'down from'} {o['so_far']:.1f} so far.")




def targets(lg, rid: int | None = None, top: int = 12) -> dict:
    """Win-now trade targets for a team: players on other rosters who'd add the most to its
    best lineup over the rest of the season (regular season and fantasy playoffs)."""
    h = lg.h2
    rid = rid or (lg.me or {}).get("roster_id")
    teams = [{"roster_id": r, "manager": t["manager"], "window": t["window"]} for r, t in lg.teams.items()]
    if not h or rid not in lg.teams:
        return {"week": None, "teams": teams}
    T = lg.teams[rid]
    odds = {x["roster_id"]: x["playoff_pct"] for x in (lg.sim or {}).get("teams", [])}
    from .season import _lineup_points  # season imports league
    P = h["players"]
    weeks = h["reg_weeks"] + h["po_weeks"]
    proj = {w: {pid: o["rate"] for pid, o in P.items() if w in o["play"]} for w in weeks}
    base = {w: _lineup_points(lg, T["players"], proj[w]) for w in weeks}
    rows = []
    for pid, o in P.items():
        if o["owner_rid"] == rid or o["rate"] < 4:
            continue
        a = next((x for x in lg.teams[o["owner_rid"]]["players"] if x["id"] == pid), None)
        if a is None:
            continue
        cand = T["players"] + [dict(a, taxi=False, ir=False)]
        g = {w: _lineup_points(lg, cand, proj[w]) - base[w] for w in weeks}
        reg = [g[w] for w in h["reg_weeks"]]
        pos = [g[w] for w in h["po_weeks"]]
        total = sum(g.values())
        if total < 1:
            continue
        own = lg.teams[o["owner_rid"]]
        oo = odds.get(o["owner_rid"])
        rows.append({**{k: o[k] for k in ("id", "name", "pos", "nfl_team", "age", "injury", "value", "redraft", "owner_rid", "owner",
                                          "games", "so_far", "model", "sleeper", "rate", "change", "left", "left_po", "reasons")},
                     "owner_odds": oo, "owner_window": own["window"],
                     "seller": own["window"] == "rebuild" or (oo is not None and oo < SELLER_ODDS),
                     "contender": oo is not None and oo >= CONTENDER_ODDS,
                     "gain_week": round(statistics.mean(reg), 1) if reg else 0.0,
                     "gain_po": round(statistics.mean(pos), 1) if pos else 0.0,
                     "gain_total": round(total, 1),
                     "per_k": round(total / max(a["value"], 300) * 1000, 1)})
    biggest = sorted(rows, key=lambda r: (r["contender"], -r["gain_total"]))[:top]
    cheap = sorted((r for r in rows if r["gain_total"] >= len(weeks) * 1.0), key=lambda r: (r["contender"], -r["per_k"]))[:top]
    mine = sorted((o for o in P.values() if o["owner_rid"] == rid), key=lambda o: -o["rate"])
    # The other side: contenders who'd gain the most from this team's players.
    buyers = [r for r, p in odds.items() if r != rid and p >= 50]
    bases = {b: {w: _lineup_points(lg, lg.teams[b]["players"], proj[w]) for w in weeks} for b in buyers}
    sell = []
    for a in T["players"]:
        o = P.get(a["id"])
        if not o or o["rate"] < 4:
            continue
        gains = []
        for b in buyers:
            cand = lg.teams[b]["players"] + [dict(a, taxi=False, ir=False)]
            g = [_lineup_points(lg, cand, proj[w]) - bases[b][w] for w in weeks]
            gains.append({"roster_id": b, "manager": lg.teams[b]["manager"], "playoff_pct": odds[b],
                          "gain_week": round(statistics.mean(g), 1)})
        gains = sorted((g for g in gains if g["gain_week"] >= 1), key=lambda g: -g["gain_week"])
        if gains:
            sell.append({**{k: o[k] for k in ("id", "name", "pos", "nfl_team", "age", "injury", "value", "redraft",
                                               "so_far", "rate", "change", "left", "left_po", "reasons")},
                         "buyers": gains[:3]})
    sell.sort(key=lambda r: -r["buyers"][0]["gain_week"])
    rostered = [o for o in P.values() if o["change"] is not None and o["model"] is not None and o["left"] + o["left_po"] >= 2]
    risers = sorted((o for o in rostered if o["change"] >= MOVE), key=lambda o: -o["change"])[:top]
    fallers = sorted((o for o in rostered if o["change"] <= -MOVE), key=lambda o: o["change"])[:top]
    return {"week": h["week"], "weeks_done": h["weeks_done"], "reg_weeks": h["reg_weeks"], "po_weeks": h["po_weeks"],
            "roster_id": rid, "manager": T["manager"], "window": T["window"], "is_me": bool(lg.me and rid == lg.me["roster_id"]),
            "playoff_pct": odds.get(rid), "base_week": round(statistics.mean(base[w] for w in h["reg_weeks"]), 1) if h["reg_weeks"] else None,
            "teams": teams, "biggest": biggest, "cheap": cheap, "mine": mine, "sell": sell[:top], "risers": risers, "fallers": fallers,
            "contender_odds": CONTENDER_ODDS, "seller_odds": SELLER_ODDS, "move": MOVE}
