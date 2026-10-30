"""Playoff odds, strength of schedule and projected rookie-draft order, by simulating the
rest of the regular season and the playoffs.

- Each team's weekly mean is its best possible lineup from Sleeper's weekly player
  projections (byes and injured players project near 0). Scores vary around that mean with
  the league's own week-to-week spread (the standard deviation of teams' scores around
  their season average).
- Standings: wins (ties half), then points for. The top `playoff_teams` make it; with 6,
  seeds 1-2 get byes.
- Draft order follows the rule that best matches this league's last rookie draft: either
  non-playoff teams by max points ("potential points", lowest first) or by record (worst
  first), then playoff teams by the round they went out in, champion last.
"""
from __future__ import annotations

import random
import statistics
from collections import defaultdict

from . import sleeper
from .cache import cached
from .league import SLOT_ELIGIBLE

N_SIMS = 4000
MIN_SD = 18.0


def _projections(season: int, week: int) -> dict:
    def fetch():
        raw = sleeper._get(f"/projections/nfl/regular/{season}/{week}") or {}
        return {pid: p["pts_ppr"] for pid, p in raw.items() if p.get("pts_ppr")}
    return cached(f"proj:{season}:{week}", 6 * 3600, fetch)


def _lineup_points(lg, players: list, proj: dict) -> float:
    """Best lineup's projected points (strict slots first, then flex)."""
    pool = [a for a in players if not a.get("taxi") and not a.get("ir")]
    used, total = set(), 0.0
    for slot in sorted(lg.slots, key=lambda s: len(SLOT_ELIGIBLE[s])):
        best = max((a for a in pool if a["id"] not in used and a["pos"] in SLOT_ELIGIBLE[slot]),
                   key=lambda a: proj.get(a["id"], 0.0), default=None)
        if best:
            used.add(best["id"])
            total += proj.get(best["id"], 0.0)
    return total


def _schedule(lg) -> tuple[list[int], list[int], dict]:
    """(completed weeks, remaining regular-season weeks, week -> [(rid, rid)])."""
    st = lg.info.get("settings") or {}
    reg_end = (st.get("playoff_week_start") or 15) - 1
    state = sleeper.nfl_state()
    live = str(state.get("season")) == str(lg.season) and state.get("season_type") == "regular"
    cur = int(state.get("week") or 1) if live else (reg_end + 1 if lg.info.get("status") in ("post_season", "complete") else 1)
    done = [w for w in range(1, reg_end + 1) if w < cur]
    left = [w for w in range(1, reg_end + 1) if w >= cur]
    pairs = {}
    for w in left:
        by = defaultdict(list)
        for m in sleeper.matchups(lg.cfg["league_id"], w, False):
            if m.get("matchup_id") is not None:
                by[m["matchup_id"]].append(m["roster_id"])
        pairs[w] = [tuple(v) for v in by.values() if len(v) == 2]
    return done, left, pairs


def _spread(lg, done: list[int]) -> float:
    """Week-to-week spread of team scores around each team's own average."""
    by = defaultdict(list)
    for w in done:
        for m in sleeper.matchups(lg.cfg["league_id"], w, True):
            if m.get("points"):
                by[m["roster_id"]].append(m["points"])
    resid = [p - statistics.mean(v) for v in by.values() if len(v) >= 2 for p in v]
    return max(MIN_SD, statistics.pstdev(resid)) if len(resid) > 10 else 25.0


def _rank(teams: dict, wins: dict, pf: dict) -> list[int]:
    return sorted(teams, key=lambda r: (-wins[r], -pf[r]))


def _playoffs(seeds: list[int], strength: dict, sd: float, rng) -> list[list[int]]:
    """Single elimination with byes for the top seeds. Returns teams by round eliminated
    (first-round losers first), and the champion last."""
    def game(a, b):
        return (a, b) if rng.gauss(strength[a], sd) >= rng.gauss(strength[b], sd) else (b, a)
    out = []
    alive = list(seeds)
    n = len(alive)
    byes = 2 if n == 6 else 0
    if byes:
        bye, rest = alive[:2], alive[2:]
        r1 = [game(rest[0], rest[3]), game(rest[1], rest[2])]  # 3v6, 4v5
        out.append([l for _, l in r1])
        alive = bye + [w for w, _ in r1]
    while len(alive) > 1:
        rnd = [game(alive[i], alive[-1 - i]) for i in range(len(alive) // 2)]
        out.append([l for _, l in rnd])
        alive = [w for w, _ in rnd]
    out.append(alive)
    return out


def _draft_rule(lg) -> str:
    """'max_pf' or 'record': whichever reproduces the league's most recent rookie draft order."""
    chain = sleeper.league_chain(lg.cfg["league_id"])
    if len(chain) < 2:
        return "max_pf"
    prev, cur = chain[1], chain[0]
    order = next((d.get("draft_order") for d in sleeper.cached_drafts(cur["league_id"]) if d.get("draft_order")), None)
    if not order:
        return "max_pf"
    ro = sleeper.rosters(prev["league_id"], None)
    bracket = sleeper.cached(f"bracket:{prev['league_id']}", None, lambda: sleeper._get(f"/league/{prev['league_id']}/winners_bracket") or [])
    in_playoffs = {t for m in bracket for t in (m.get("t1"), m.get("t2")) if isinstance(t, int)}
    out = [r for r in ro if r["roster_id"] not in in_playoffs and r.get("owner_id") in order]
    s = lambda r: r.get("settings") or {}
    pts = lambda r, k: s(r).get(k, 0) + s(r).get(f"{k}_decimal", 0) / 100
    by_max = sorted(out, key=lambda r: pts(r, "ppts"))
    by_rec = sorted(out, key=lambda r: (s(r).get("wins", 0), pts(r, "fpts")))
    actual = sorted(out, key=lambda r: order[r["owner_id"]])
    agree = lambda a: sum(x["roster_id"] == y["roster_id"] for x, y in zip(a, actual))
    return "record" if agree(by_rec) > agree(by_max) else "max_pf"


def simulate(lg, n_sims: int = N_SIMS, seed: int = 7, rosters: dict | None = None) -> dict:
    """`rosters` (roster_id -> players) replaces those teams' players, e.g. after a trade."""
    rosters = rosters or {}
    st = lg.info.get("settings") or {}
    n_playoff = st.get("playoff_teams") or 6
    done, left, pairs = _schedule(lg)
    sd = _spread(lg, done)
    teams = {rid: t for rid, t in lg.teams.items()}

    # Projected mean per team per remaining week, and for the playoff weeks.
    reg_end = (st.get("playoff_week_start") or 15) - 1
    proj_week = {}
    for w in left + [reg_end + 1, reg_end + 2, reg_end + 3]:
        proj = _projections(lg.season, w)
        proj_week[w] = {rid: _lineup_points(lg, rosters.get(rid, t["players"]), proj) for rid, t in teams.items()}
    strength = {rid: statistics.mean(proj_week[w][rid] for w in (reg_end + 1, reg_end + 2, reg_end + 3)) for rid in teams}

    base_w = {rid: t["wins"] + 0.5 * t["ties"] for rid, t in teams.items()}
    base_pf = {rid: t["fpts"] for rid, t in teams.items()}
    ro = {r["roster_id"]: r for r in sleeper.rosters(lg.cfg["league_id"])}
    base_max = {rid: (ro.get(rid, {}).get("settings") or {}).get("ppts", 0) + (ro.get(rid, {}).get("settings") or {}).get("ppts_decimal", 0) / 100
                for rid in teams}
    rule = _draft_rule(lg)

    rng = random.Random(seed)
    n = len(teams)
    orders = []  # a sample of full simulated draft orders (roster ids by slot), for mock drafts
    acc = {rid: {"wins": 0.0, "playoffs": 0, "bye": 0, "title": 0, "last": 0, "rank": 0.0,
                 "slot": [0] * n} for rid in teams}
    for _ in range(n_sims):
        wins, pf, mx = dict(base_w), dict(base_pf), dict(base_max)
        for w in left:
            mu = proj_week[w]
            for a, b in pairs.get(w, []):
                sa, sb = rng.gauss(mu[a], sd), rng.gauss(mu[b], sd)
                pf[a] += sa
                pf[b] += sb
                mx[a] += max(sa, mu[a])
                mx[b] += max(sb, mu[b])
                if sa > sb:
                    wins[a] += 1
                elif sb > sa:
                    wins[b] += 1
        order = _rank(teams, wins, pf)
        seeds = order[:n_playoff]
        rounds = _playoffs(seeds, strength, sd, rng)
        for i, rid in enumerate(order):
            a = acc[rid]
            a["wins"] += wins[rid]
            a["rank"] += i + 1
            a["playoffs"] += i < n_playoff
            a["bye"] += i < 2 and n_playoff == 6
            a["last"] += i == n - 1
        acc[rounds[-1][0]]["title"] += 1
        # Draft order: non-playoff teams first, then by playoff round eliminated.
        out = [r for r in order if r not in seeds]
        out.sort(key=(lambda r: mx[r]) if rule == "max_pf" else (lambda r: (wins[r], pf[r])))
        playoff_order = []
        for rnd in rounds:
            playoff_order += sorted(rnd, key=lambda r: mx[r]) if rule == "max_pf" else sorted(rnd, key=lambda r: (wins[r], pf[r]))
        draft_order = out + playoff_order
        for slot, rid in enumerate(draft_order):
            acc[rid]["slot"][slot] += 1
        if len(orders) < 400:
            orders.append(draft_order)

    league_avg = statistics.mean(v for w in left for v in proj_week[w].values()) if left else 0
    opp_strength = defaultdict(list)
    for w in left:
        for a, b in pairs.get(w, []):
            opp_strength[a].append(proj_week[w][b])
            opp_strength[b].append(proj_week[w][a])
    games = max(1, len(done))
    pa_avg = statistics.mean(t["fpts_against"] / games for t in teams.values())
    rows = []
    for rid, t in teams.items():
        a = acc[rid]
        slots = [round(c / n_sims, 3) for c in a["slot"]]
        rows.append({
            "roster_id": rid, "manager": t["manager"], "wins": t["wins"], "losses": t["losses"], "ties": t["ties"],
            "fpts": round(t["fpts"], 1),
            "proj_wins": round(a["wins"] / n_sims, 1), "playoff_pct": round(a["playoffs"] / n_sims * 100, 1),
            "bye_pct": round(a["bye"] / n_sims * 100, 1), "title_pct": round(a["title"] / n_sims * 100, 1),
            "last_pct": round(a["last"] / n_sims * 100, 1), "avg_rank": round(a["rank"] / n_sims, 2),
            "weekly_proj": round(statistics.mean(proj_week[w][rid] for w in left), 1) if left else None,
            "playoff_strength": round(strength[rid], 1),
            "sos_left": round(statistics.mean(opp_strength[rid]) - league_avg, 1) if opp_strength[rid] else None,
            "sos_past": round(t["fpts_against"] / games - pa_avg, 1) if done else None,
            "slot_probs": slots, "avg_slot": round(sum((i + 1) * p for i, p in enumerate(slots)), 2),
            "remaining": [{"week": w, "opp": next((b if a2 == rid else a2 for a2, b in pairs.get(w, []) if rid in (a2, b)), None),
                           "proj": round(proj_week[w][rid], 1)} for w in left],
        })
    rows.sort(key=lambda r: -r["playoff_pct"])
    for r in rows:
        for g in r["remaining"]:
            opp = g["opp"]
            g["opp_manager"] = teams[opp]["manager"] if opp in teams else None
            g["opp_proj"] = round(proj_week[g["week"]][opp], 1) if opp in teams else None
    return {"teams": rows, "sims": n_sims, "sd": round(sd, 1), "weeks_done": len(done), "weeks_left": left,
            "playoff_teams": n_playoff, "draft_rule": rule, "draft_season": lg.season + 1, "_orders": orders}


def trade_impact(lg, a_rid: int, a_gives: list, b_rid: int, b_gives: list) -> dict | None:
    """Both teams' playoff odds, title odds and projected draft slot before and after a trade
    (same simulated seasons both times, so the difference is the trade). None when the
    regular season is over."""
    rosters = {}
    for rid, gives, gets in ((a_rid, a_gives, b_gives), (b_rid, b_gives, a_gives)):
        out = {x["id"] for x in gives}
        rosters[rid] = [x for x in lg.teams[rid]["players"] if x["id"] not in out] +                        [dict(x, taxi=False, ir=False) for x in gets if x["kind"] == "player"]
    before = simulate(lg)
    if not before["weeks_left"]:
        return None
    after = simulate(lg, rosters=rosters)
    nxt = before["draft_season"]
    owner = {pk["orig_roster_id"]: t["manager"] for t in lg.teams.values() for pk in t["picks"]
             if pk["season"] == nxt and pk["round"] == 1}
    moved = {x["orig_roster_id"]: (b_rid if x in a_gives else a_rid) for x in a_gives + b_gives
             if x["kind"] == "pick" and x["season"] == nxt and x["round"] == 1}
    out = []
    for rid in (a_rid, b_rid):
        b = next(r for r in before["teams"] if r["roster_id"] == rid)
        a = next(r for r in after["teams"] if r["roster_id"] == rid)
        out.append({"roster_id": rid, "manager": lg.teams[rid]["manager"],
                    **{k: [b[k], a[k]] for k in ("playoff_pct", "title_pct", "avg_slot", "weekly_proj")},
                    "pick_owner": owner.get(rid), "pick_owner_after": lg.teams[moved[rid]]["manager"] if rid in moved else owner.get(rid)})
    return {"teams": out, "draft_season": nxt, "draft_rule": before["draft_rule"], "weeks_left": len(before["weeks_left"]),
            "teams_n": len(lg.teams)}


def lineup_change(lg, rid: int, gives: list, gets: list) -> float | None:
    """Change in a team's projected points per week over the rest of the regular season
    if it sends `gives` and receives `gets` (best lineup each week from Sleeper's
    projections). None when the regular season is over."""
    cache = getattr(lg, "_rest_proj", None)
    if cache is None:
        _, left, _ = _schedule(lg)
        cache = lg._rest_proj = [_projections(lg.season, w) for w in left]
    if not cache:
        return None
    out = {x["id"] for x in gives}
    before = lg.teams[rid]["players"]
    after = [x for x in before if x["id"] not in out] + [dict(x, taxi=False, ir=False) for x in gets if x["kind"] == "player"]
    return statistics.mean(_lineup_points(lg, after, p) - _lineup_points(lg, before, p) for p in cache)
