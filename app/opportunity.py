"""Opportunity, depth charts, contracts and breakout signals.

Data
- Usage: Sleeper weekly stats per player (snaps, targets, carries, air yards, red-zone
  looks, PPR points), with team totals built by summing teammates.
- Contracts: nflverse's copy of OverTheCap contracts (end year, cap number, guarantees,
  draft round), joined to Sleeper on gsis_id.
- Depth: each NFL team's players at a position ranked by weighted opportunities per game
  (recent games count half), with Sleeper's depth chart as the fallback.

Signals, each 0..1, combine into a breakout score (0-100). The score is about *future*
role growth, so it's discounted for players who already have a full role or are already
priced as stars:
- rising:     snap share or opportunity share up over the last 3 games
- efficient:  fantasy points per opportunity above the position median (role could grow)
- vacancy now:  a player ahead of him is out (IR, Out, PUP, Doubtful, suspended)
- vacancy next: a player ahead of him may leave after this season (contract ends,
                or the team can cut him cheaply), weighted by how close he is in line
- FA move:    his own contract ends while he's stuck behind a starter, so he may sign
              somewhere with a bigger role (the Isaiah Likely path)
- youth:      age and draft capital
"""
from __future__ import annotations

import datetime as dt
import io
import statistics
from collections import defaultdict

import httpx

from . import sleeper
from .cache import cached

POS = ("QB", "RB", "WR", "TE")
SELL_AGE = {"QB": 32, "RB": 26, "WR": 28, "TE": 29}
# Players at the top of the depth chart whose departure opens a big role.
STARTERS = {"QB": 1, "RB": 1, "WR": 2, "TE": 1}
# Same-position share of weighted opportunities that counts as a full role.
FULL_SHARE = {"QB": 0.85, "RB": 0.55, "WR": 0.32, "TE": 0.60}
OUT_STATUSES = {"IR", "Out", "PUP", "Doubtful", "Sus", "NFI"}
LONG_OUT = {"IR", "PUP", "NFI"}  # multi-week absences; Out/Doubtful/Sus are usually shorter
# Weights were checked against backtests of the 2022-2025 seasons (see backtest_report()):
# efficiency and the contract-year-backup signal predicted value gains in every season, youth
# in most, a rising role in some. "The starter ahead may leave" did worse than average in
# every season (teams usually bring in a replacement), so it's shown as context but scores 0.
# "Opening now" can't be backtested (no injury history) and keeps a small weight.
WEIGHTS = {"rising": 0.15, "efficient": 0.30, "vacancy_now": 0.10, "vacancy_next": 0.0, "fa_move": 0.20, "youth": 0.15}
HEADROOM = 0.2  # penalty for an already-full role; larger penalties did worse in backtests
SCALE = 0.55  # weighted sum that maps to a breakout score of 100

CONTRACTS_URL = "https://github.com/nflverse/nflverse-data/releases/download/contracts/historical_contracts.parquet"
STATS_URL = "https://api.sleeper.com/stats/nfl/{season}/{week}"
STAT_FIELDS = ("off_snp", "tm_off_snp", "rec_tgt", "rec_air_yd", "rush_att", "pass_att",
               "rec_rz_tgt", "rush_rz_att", "pts_ppr")

_http = httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": "dynasty-trade-helper/1.0"})


# ------------------------------------------------------------------ data
def contracts(force=False) -> dict:
    """gsis_id -> active contract summary, for QB/RB/WR/TE."""
    def fetch():
        import pyarrow.parquet as pq
        r = _http.get(CONTRACTS_URL)
        r.raise_for_status()
        cols = ["player", "position", "is_active", "gsis_id", "year_signed", "years", "apy", "guaranteed", "team",
                "draft_year", "draft_round", "draft_overall", "season_history", "contract_history"]
        out = {}
        for row in pq.read_table(io.BytesIO(r.content), columns=cols).to_pylist():
            if not row["is_active"] or row["position"] not in POS or not row["gsis_id"]:
                continue
            prev = out.get(row["gsis_id"])
            if prev and (prev["signed"] or 0) >= (row["year_signed"] or 0):
                continue
            seasons = {}
            for y in row["season_history"] or []:
                if str(y.get("year")).isdigit():
                    seasons[str(y["year"])] = {k: round(y.get(f) or 0.0, 3) for k, f in (
                        ("cap", "cap_number"), ("base", "base_salary"), ("pro", "prorated_bonus"), ("gtd", "guaranteed_salary"))}
            out[row["gsis_id"]] = {
                "name": row["player"], "pos": row["position"], "team": row["team"], "signed": row["year_signed"], "years": row["years"],
                "apy": row["apy"], "gtd": row["guaranteed"],
                "draft_year": row["draft_year"], "draft_round": row["draft_round"], "draft_overall": row["draft_overall"],
                "seasons": seasons,
                "history": [{"type": h["contract_type"], "signed": h["year_signed"], "yrs": h["yrs"], "team": h["team"]}
                            for h in row["contract_history"] or []],
            }
        return out
    return cached("contracts:otc:v2", 24 * 3600, fetch, force)


def gsis_ids(db: dict, by_gsis: dict) -> dict:
    """sleeper_id -> gsis_id. Sleeper leaves gsis_id blank for most recent players, so
    DynastyProcess's ID map comes first, then Sleeper's own, then a unique name match."""
    from .values import _dp_ids, name_key
    out = {r["sleeper_id"]: r["gsis_id"] for r in _dp_ids()
           if r.get("sleeper_id") not in (None, "", "NA") and r.get("gsis_id") not in (None, "", "NA")}
    by_name = defaultdict(list)
    for g, c in by_gsis.items():
        by_name[(name_key(c["name"] or ""), c["pos"])].append(g)
    for pid, p in db.items():
        if pid in out:
            continue
        g = (p.get("gsis_id") or "").strip()
        cands = by_name.get((name_key(p.get("full_name") or ""), p.get("position"))) or []
        if g:
            out[pid] = g
        elif len(cands) == 1:
            out[pid] = cands[0]
    return out


def _week(season: int, week: int, ttl, force=False) -> dict:
    """player_id -> slim stat line for one week (players who played offensive snaps)."""
    def fetch():
        params = [("season_type", "regular")] + [("position[]", p) for p in POS + ("FB",)]
        r = _http.get(STATS_URL.format(season=season, week=week), params=params)
        r.raise_for_status()
        out = {}
        for e in r.json():
            s = e.get("stats") or {}
            if not s.get("off_snp") and not s.get("pts_ppr"):
                continue
            pos = (e.get("player") or {}).get("position")
            out[e["player_id"]] = {"team": e.get("team"), "pos": "RB" if pos == "FB" else pos,
                                   **{k: s[k] for k in STAT_FIELDS if s.get(k)}}
        return out
    return cached(f"stats:{season}:{week}", ttl, fetch, force)


def weeks_done(season: int) -> list[int]:
    """Completed regular-season weeks for a season."""
    st = sleeper.nfl_state()
    cur = int(st.get("season") or 0)
    if season < cur or (season == cur and st.get("season_type") == "post"):
        return list(range(1, 19))
    if season == cur and st.get("season_type") == "regular":
        return list(range(1, int(st.get("week") or 1)))
    return []


def season_stats(season: int, force=False) -> dict:
    """week -> stats for every completed week. Past seasons are cached for good; recent
    weeks are refetched now and then to pick up stat corrections."""
    past = season < int(sleeper.nfl_state().get("season") or 0)
    weeks = weeks_done(season)
    out = {}
    for w in weeks:
        ttl = None if past else (6 * 3600 if w == weeks[-1] else 7 * 24 * 3600)
        out[w] = _week(season, w, ttl, force and not past)
    return out


def _wo(s: dict, pos: str) -> float:
    """Weighted opportunities: targets count 1.5x carries in PPR; QBs count dropbacks."""
    if pos == "QB":
        return s.get("pass_att", 0) + s.get("rush_att", 0)
    return s.get("rush_att", 0) + 1.5 * s.get("rec_tgt", 0)


def usage(weekly: dict) -> dict:
    """pid -> season usage: games, snap share, same-position opportunity share, recent splits."""
    team_wo = defaultdict(float)  # (team, week, pos)
    for w, data in weekly.items():
        for s in data.values():
            team_wo[(s.get("team"), w, s.get("pos"))] += _wo(s, s.get("pos"))
    games = defaultdict(list)
    for w in sorted(weekly):
        for pid, s in weekly[w].items():
            if s.get("off_snp"):
                games[pid].append((w, s))
    out = {}
    for pid, gl in games.items():
        def agg(g):
            snp = sum(s.get("off_snp", 0) for _, s in g)
            tm = sum(s.get("tm_off_snp", 0) for _, s in g)
            wo = sum(_wo(s, s["pos"]) for _, s in g)
            twos = sum(team_wo[(s.get("team"), w, s["pos"])] for w, s in g)
            return {"snap": snp / tm if tm else 0.0, "share": wo / twos if twos else 0.0,
                    "wo": wo, "pts": sum(s.get("pts_ppr", 0) for _, s in g), "n": len(g)}
        pos = gl[-1][1]["pos"]
        tot, l3, prev = agg(gl), agg(gl[-3:]), agg(gl[:-3])
        out[pid] = {
            "pos": pos, "team": gl[-1][1].get("team"), "games": tot["n"], "last_week": gl[-1][0],
            "snap": tot["snap"], "share": tot["share"], "wo": tot["wo"], "pts": tot["pts"],
            "ppg": tot["pts"] / tot["n"], "wo_pg": tot["wo"] / tot["n"],
            "snap_l3": l3["snap"], "share_l3": l3["share"], "wo_l3": l3["wo"] / max(l3["n"], 1),
            "ppg_l3": l3["pts"] / max(l3["n"], 1),
            "snap_prev": prev["snap"] if prev["n"] >= 2 else None,
            "share_prev": prev["share"] if prev["n"] >= 2 else None,
            "tgt": sum(s.get("rec_tgt", 0) for _, s in gl), "carries": sum(s.get("rush_att", 0) for _, s in gl),
            "rz": sum(s.get("rec_rz_tgt", 0) + s.get("rush_rz_att", 0) for _, s in gl),
        }
    return out


# ------------------------------------------------------------------ contracts
def contract_end(c: dict, season: int) -> tuple[int | None, dict | None]:
    """Last season of the contract in force as of `season`, and that contract.

    OverTheCap counts extension years as new years after the current deal; every other
    contract type (Drafted, UFA, Franchise, ...) starts in the year it was signed."""
    best = None
    for h in c.get("history") or []:
        if h.get("signed") is None or h.get("yrs") is None or h["signed"] > season:
            continue
        end = h["signed"] + h["yrs"] - (0 if h["type"] == "Extension" else 1)
        if best is None or h["signed"] >= best[0]:
            best = (h["signed"], end, h)
    if not best:
        return None, None
    return best[1], best[2]


def cut_savings(c: dict, year: int) -> tuple[float, float] | None:
    """(cap number, savings) if released before `year`: savings = cap hit minus dead money
    (remaining prorated bonus plus guaranteed salary)."""
    seasons = c.get("seasons") or {}
    cur = seasons.get(str(year))
    if not cur or not cur["cap"]:
        return None
    dead = sum(v["pro"] + v["gtd"] for y, v in seasons.items() if int(y) >= year)
    return cur["cap"], cur["cap"] - dead


def leave_risk(c: dict | None, season: int, pos: str, age: float | None, role_level: float,
               years_exp: int | None = None) -> tuple[float, str | None, int | None]:
    """(probability he's not on this team next season, reason, contract end year)."""
    if not c:
        return 0.10, None, None
    end, h = contract_end(c, season)
    nxt = season + 1
    cliff = SELL_AGE.get(pos, 30)
    if end is not None and end <= season:
        if h and h["type"] == "Drafted" and c.get("draft_round") == 1 and h["yrs"] == 4 and (years_exp or 0) <= 3:
            return 0.20, f"1st-round rookie deal ends after {season}; a 5th-year option is likely", end
        if h and h["type"] in ("UDFA", "ERFA", "SFA", "Practice") and (years_exp or 0) <= 3:
            return 0.25, f"Contract ends after {season}, but as a restricted free agent he usually stays", end
        if age is not None and age >= cliff:
            return 0.70, f"Contract ends after {season}: unrestricted free agent in {nxt}, at age {age:g}", end
        if role_level >= 0.8:
            return 0.25, f"Contract ends after {season}, but productive starters are usually extended or tagged", end
        return 0.55, f"Contract ends after {season}: unrestricted free agent in {nxt}", end
    cs = cut_savings(c, nxt)
    if cs and age is not None and age >= cliff - 1:
        cap, save = cs
        if cap >= 3 and save >= 0.6 * cap:
            p = 0.45 if age >= cliff else 0.30
            return p, f"Age {age:g}: the team can release him before {nxt} and save ${save:.1f}M of a ${cap:.1f}M cap hit", end
    if age is not None and age >= cliff + 2:
        return 0.25, f"Age {age:g}, well past the {pos} age cliff", end
    return 0.06, None, end


# ------------------------------------------------------------------ scoring
def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _youth(age, draft_round, years_exp) -> float:
    a = 0.0 if age is None else _clamp((26.5 - age) / 4)
    d = {1: 1.0, 2: 0.75, 3: 0.5, 4: 0.3, 5: 0.25}.get(draft_round or 0, 0.15 if draft_round else 0.1)
    rookie = 0.15 if (years_exp or 0) <= 1 else 0.0
    return _clamp(0.55 * a + 0.45 * d + rookie)


def score(sig: dict, role_level: float, value: float, age: float | None, pos: str) -> int:
    raw = sum(WEIGHTS[k] * sig.get(k, 0.0) for k in WEIGHTS)
    headroom = 1 - HEADROOM * role_level      # a full-time starter has less room to grow
    priced = 1 - 0.5 * _clamp((value - 4000) / 4000)  # stars are already priced as stars
    # A dynasty breakout needs years left to cash in: fade from age 25 to just past the cliff.
    aging = 1 - 0.6 * _clamp(((age or 25) - 25) / (SELL_AGE[pos] + 1 - 25))
    return round(100 * _clamp(raw / SCALE * headroom * priced * aging))


def _opening_now(own: str | None, ahead: str | None) -> float:
    """How much an injury ahead of him opens up right now, given his own health. If he's
    out longer-term himself, the starter will likely be back first, so it opens nothing."""
    if ahead not in OUT_STATUSES or own in LONG_OUT:
        return 0.0
    if own in OUT_STATUSES:
        return 0.5 if ahead in LONG_OUT else 0.0
    return 1.0 if ahead in LONG_OUT else 0.5


def _line_factor(gap: int) -> float:
    """Credit for a vacancy by how far down the depth chart he is (1 = next in line)."""
    return {1: 1.0, 2: 0.5}.get(gap, 0.25)


def build(players: dict, use: dict, eff_use: dict, contracts_by_gsis: dict, season: int,
          value_of, age_of, injuries: dict | None = None) -> dict:
    """Breakout model over a universe of players.

    players: pid -> {name, pos, team, gsis_id, years_exp, depth_order}
    use:     pid -> usage() row for the role season (depth + recent role)
    eff_use: pid -> (pts, wo) pooled across seasons, for efficiency
    """
    injuries = injuries or {}
    # Efficiency baseline: median points per weighted opportunity among regulars.
    ppwo = {pid: pts / wo for pid, (pts, wo) in eff_use.items() if wo >= 25}
    med = {}
    for pos in POS:
        regs = [ppwo[pid] for pid, (pts, wo) in eff_use.items()
                if pid in ppwo and wo >= 60 and (players.get(pid) or {}).get("pos") == pos]
        med[pos] = statistics.median(regs) if len(regs) >= 5 else None

    # Depth charts.
    groups = defaultdict(list)
    for pid, p in players.items():
        if p.get("team") and p.get("pos") in POS:
            groups[(p["team"], p["pos"])].append(pid)
    depth = {}
    for (team, pos), pids in groups.items():
        def key(pid):
            u = use.get(pid)
            role = (0.5 * u["wo_pg"] + 0.5 * u["wo_l3"]) if u and u["games"] >= 1 and u["team"] == team else -1
            return (-role, players[pid].get("depth_order") or 99)
        ranked = sorted(pids, key=key)
        for i, pid in enumerate(ranked):
            depth[pid] = (i + 1, ranked)

    out = {}
    for pid, p in players.items():
        pos = p.get("pos")
        if pos not in POS or not p.get("team"):
            continue
        u = use.get(pid) if (use.get(pid) or {}).get("team") == p["team"] else None
        age = age_of(pid)
        value = value_of(pid)
        c = contracts_by_gsis.get(p.get("gsis_id") or "")
        share = (u["share_l3"] if u and u["games"] >= 3 else u["share"]) if u else 0.0
        role_level = _clamp(share / FULL_SHARE[pos])
        rank, ranked = depth.get(pid, (99, []))
        sig, notes = {}, []
        own_inj = injuries.get(pid)
        if own_inj in LONG_OUT:
            notes.append(("injured", f"On {own_inj} himself: a stash for later, not an immediate opportunity"))

        # Rising role.
        if u and u["snap_prev"] is not None:
            d_snap = u["snap_l3"] - u["snap_prev"]
            d_share = u["share_l3"] - (u["share_prev"] or 0)
            r_snap, r_share = _clamp(d_snap / 0.25), _clamp(d_share / 0.15)
            sig["rising"] = max(r_snap, r_share)
            if sig["rising"] >= 0.3 and r_snap >= r_share:
                notes.append(("rising", f"Role rising: {u['snap_prev']:.0%} of snaps before, {u['snap_l3']:.0%} over the last 3 games"))
            elif sig["rising"] >= 0.3:
                notes.append(("rising", f"Role rising: {u['share_prev']:.0%} of the team's {pos} opportunities before, "
                                        f"{u['share_l3']:.0%} over the last 3 games"))
        # Efficiency per opportunity.
        if pid in ppwo and med.get(pos):
            ratio = ppwo[pid] / med[pos]
            sig["efficient"] = _clamp((ratio - 1.0) / 0.4)
            if ratio >= 1.15:
                notes.append(("efficient", f"Efficient: {ratio:.2f}x the {pos} median in fantasy points per opportunity"))
        # Vacancies ahead of him.
        ahead = [q for q in ranked[:max(0, min(rank - 1, STARTERS[pos]))]]
        gap = rank - STARTERS[pos]
        ahead_info = []
        for q in ahead:
            qp = players[q]
            qu = use.get(q) if (use.get(q) or {}).get("team") == p["team"] else None
            q_role = _clamp(((qu["share"] if qu else 0.0)) / FULL_SHARE[pos])
            qc = contracts_by_gsis.get(qp.get("gsis_id") or "")
            lp, why, end = leave_risk(qc, season, pos, age_of(q), q_role, qp.get("years_exp"))
            inj = injuries.get(q)
            ahead_info.append({"id": q, "name": qp.get("name"), "injury": inj, "leave_p": round(lp, 2),
                               "leave_why": why, "contract_end": end, "age": age_of(q)})
            lf = _line_factor(max(gap, 1))
            opening = _opening_now(own_inj, inj)
            if opening:
                sig["vacancy_now"] = max(sig.get("vacancy_now", 0.0), lf * opening)
                notes.append(("vacancy_now", f"Opportunity now: {qp.get('name')} ({inj}) is ahead of him"
                                             + ("" if inj in LONG_OUT else ", likely a short absence")))
            if lp >= 0.25:
                sig["vacancy_next"] = max(sig.get("vacancy_next", 0.0), _clamp(lp / 0.6) * lf)
                if lp >= 0.4:
                    notes.append(("vacancy_next", f"Path opening: {qp.get('name')} is ahead of him. {why}"))
        # His own contract.
        lp_own, why_own, end_own = leave_risk(c, season, pos, age, role_level, p.get("years_exp"))
        if end_own is not None and end_own <= season and rank > STARTERS[pos] and lp_own >= 0.5:
            talent = max(sig.get("efficient", 0.0), _youth(age, (c or {}).get("draft_round"), p.get("years_exp")))
            sig["fa_move"] = _clamp(0.4 + 0.6 * talent)
            notes.append(("fa_move", f"Contract year as a backup: free agent after {season}, could sign somewhere as a starter"))
        sig["youth"] = _youth(age, (c or {}).get("draft_round"), p.get("years_exp"))

        out[pid] = {
            "breakout": score(sig, role_level, value, age, pos),
            "role_level": round(role_level, 3), "age": age,
            "opp_score": round(100 * _clamp(0.5 * role_level + 0.5 * (u["snap_l3"] if u else 0.0))),
            "signals": {k: round(v, 2) for k, v in sig.items()},
            "notes": [{"key": k, "text": t} for k, t in notes],
            "role": None if not u else {
                "games": u["games"], "snap": round(u["snap"], 3), "snap_l3": round(u["snap_l3"], 3),
                "share": round(u["share"], 3), "share_l3": round(u["share_l3"], 3), "ppg": round(u["ppg"], 1),
                "ppg_l3": round(u["ppg_l3"], 1), "last_week": u["last_week"],
                "tgt": u["tgt"], "carries": u["carries"], "rz": u["rz"],
                "eff": round(ppwo[pid] / med[pos], 2) if pid in ppwo and med.get(pos) else None,
            },
            "depth": {"rank": rank, "label": f"{pos}{rank}" if rank < 99 else None, "ahead": ahead_info},
            "contract": None if not c else {
                "end": end_own, "apy": round(c["apy"] or 0, 2), "leave_p": round(lp_own, 2), "leave_why": why_own,
                "draft_round": c.get("draft_round"), "draft_overall": c.get("draft_overall"), "draft_year": c.get("draft_year"),
            },
        }
    return out


# ------------------------------------------------------------------ league entry points
def _pooled(*seasons_use):
    """(pts, wo) per player pooled across seasons, each with a weight."""
    out = defaultdict(lambda: [0.0, 0.0])
    for use, w in seasons_use:
        for pid, u in use.items():
            out[pid][0] += w * u["pts"]
            out[pid][1] += w * u["wo"]
    return {k: tuple(v) for k, v in out.items()}


def analyze(lg, force=False) -> dict:
    """Breakout model for the current season, over every NFL player at QB/RB/WR/TE."""
    season = lg.season
    cur = season_stats(season, force)
    prev = season_stats(season - 1, force)
    u_cur, u_prev = usage(cur), usage(prev)
    role_use = u_cur if len(cur) >= 3 else u_prev
    eff = _pooled((u_cur, 1.0), (u_prev, 0.5))
    db = lg.players_db
    cons = contracts(force)
    gsis = gsis_ids(db, cons)
    players = {}
    for pid, p in db.items():
        if p.get("position") in POS and p.get("team"):
            players[pid] = {"name": p.get("full_name") or pid, "pos": p["position"], "team": p["team"],
                            "gsis_id": gsis.get(pid), "years_exp": p.get("years_exp"),
                            "depth_order": p.get("depth_chart_order")}
    ages = {pid: lg.player_asset(pid)["age"] for pid in players}
    vals = {pid: lg.values.player(pid)["value"] for pid in players}
    res = build(players, role_use, eff, cons, season, vals.get, ages.get,
                {pid: db[pid].get("injury_status") for pid in players})
    return {"season": season, "role_season": season if role_use is u_cur else season - 1,
            "weeks": len(cur) if role_use is u_cur else len(prev), "players": res}


def backtest(lg, hist: dict, as_of: int | None = None, horizon_days: int = 365) -> dict:
    """Run the model as it would have looked at the end of `as_of` (default: last season),
    then compare each player's value then (mid-January) and `horizon_days` later (or the
    latest snapshot, for the most recent season).

    Rosters come from that season's final stats; injuries aren't known historically, so
    the vacancy-now signal is off. Contracts are the ones in force as of that season
    (extensions signed later in the year are visible, a small leak)."""
    as_of = as_of or lg.season - 1
    weekly = season_stats(as_of)
    if not weekly:
        return {}
    u = usage(weekly)
    eff = _pooled((u, 1.0), (usage(season_stats(as_of - 1)), 0.5))
    db = lg.players_db
    then_day = (dt.date(as_of + 1, 1, 15)).isoformat()
    dates, hv = hist["dates"], hist["values"]
    j_then = max((i for i, d in enumerate(dates) if d <= then_day), default=None)
    if j_then is None or dates[0] > then_day:
        return {}
    later_day = (dt.date.fromisoformat(then_day) + dt.timedelta(days=horizon_days)).isoformat()
    j_later = max(i for i, d in enumerate(dates) if d <= later_day)

    def at(pid, j):
        s = hv.get(pid)
        return (s[j] or 0.0) if s and s[j] is not None else 0.0
    cons = contracts()
    gsis = gsis_ids(db, cons)
    players = {}
    for pid, x in u.items():
        p = db.get(pid) or {}
        players[pid] = {"name": p.get("full_name") or pid, "pos": x["pos"], "team": x["team"],
                        "gsis_id": gsis.get(pid),
                        "years_exp": (p.get("years_exp") or 0) - (lg.season - as_of), "depth_order": None}
    years_back = (dt.date.today() - dt.date.fromisoformat(then_day)).days / 365.25
    ages = {}
    for pid in players:
        a = lg.player_asset(pid)["age"]
        ages[pid] = round(a - years_back, 1) if a is not None else None
    res = build(players, u, eff, cons, as_of, lambda pid: at(pid, j_then), ages.get)
    rows = []
    for pid, r in res.items():
        then, now = at(pid, j_then), at(pid, j_later)
        rows.append({"id": pid, "name": players[pid]["name"], "pos": players[pid]["pos"], "team": players[pid]["team"],
                     "breakout": r["breakout"], "signals": r["signals"], "notes": r["notes"],
                     "role_level": r["role_level"], "age": r["age"],
                     "depth": r["depth"]["label"], "contract_end": (r["contract"] or {}).get("end"), "then": round(then), "now": round(now),
                     "change": round(now - then), "now_team": (db.get(pid) or {}).get("team")})
    return {"as_of": as_of, "then_date": dates[j_then], "now_date": dates[j_later], "rows": rows}


def backtest_summary(bt: dict, top: int = 20, hit: int = 500, cap: int = 4000) -> dict:
    """How the model's top picks at the end of last season did since, vs. similar-value players.

    Players already worth `cap`+ are left out (breakouts are about players not yet priced
    as starters). A "hit" gained `hit`+ value. The excess is each player's change minus the
    average change of players in the same starting value band."""
    if not bt:
        return {}
    cand = sorted((r for r in bt["rows"] if r["then"] < cap), key=lambda r: -r["breakout"])
    if not cand:
        return {}
    band = lambda v: 0 if v < 300 else 1 if v < 1000 else 2 if v < 2000 else 3
    by = defaultdict(list)
    for r in cand:
        by[band(r["then"])].append(r["change"])
    base = {b: statistics.mean(v) for b, v in by.items()}
    for i, r in enumerate(cand):
        r["rank"] = i + 1
        r["excess"] = round(r["change"] - base[band(r["then"])])
    picks = cand[:top]
    return {
        "as_of": bt["as_of"], "then_date": bt["then_date"], "now_date": bt["now_date"],
        "n": len(cand), "top": top, "hit": hit, "cap": cap,
        "top_hits": sum(r["change"] >= hit for r in picks),
        "top_hit_rate": round(sum(r["change"] >= hit for r in picks) / len(picks), 3),
        "base_hit_rate": round(sum(r["change"] >= hit for r in cand) / len(cand), 3),
        "top_excess": round(statistics.mean(r["excess"] for r in picks)),
        "picks": picks,
        "risers": sorted(cand, key=lambda r: -r["change"])[:12],
        "spotlight": next((r for r in cand if r["name"] == "Isaiah Likely"), None),
    }


def backtest_report(lg, seasons: int = 4) -> dict:
    """Backtests for each of the last `seasons` seasons, pooled. Each season is judged over
    the year after it (the latest one up to now)."""
    from . import history
    first = lg.season - seasons
    hist = history.value_history(lg, dt.date(first, 12, 1))
    by_season = []
    for s in range(first, lg.season):
        summ = backtest_summary(backtest(lg, hist, s))
        if summ:
            by_season.append(summ)
    if not by_season:
        return {}
    latest = by_season[-1]
    mean = lambda k: round(statistics.mean(x[k] for x in by_season), 3)
    pooled = {"seasons": [x["as_of"] for x in by_season], "n": sum(x["n"] for x in by_season),
              "top": latest["top"], "hit": latest["hit"], "cap": latest["cap"],
              "top_hit_rate": mean("top_hit_rate"), "base_hit_rate": mean("base_hit_rate"),
              "top_excess": round(statistics.mean(x["top_excess"] for x in by_season))}
    spot = next((x["spotlight"] | {"as_of": x["as_of"], "n": x["n"]} for x in reversed(by_season) if x.get("spotlight")), None)
    slim = [{k: x[k] for k in ("as_of", "then_date", "now_date", "n", "top_hits", "top_hit_rate", "base_hit_rate", "top_excess")}
            for x in by_season]
    return {"pooled": pooled, "by_season": slim, "latest": latest, "spotlight": spot}


def shakeups(lg) -> list[dict]:
    """Starters who may not be on their team next season (or are out now), and who's next."""
    P = lg.opportunity["players"]
    db = lg.players_db
    owner = {a["id"]: (t["roster_id"], t["manager"]) for t in lg.teams.values() for a in t["players"]}
    groups = defaultdict(list)
    for pid, r in P.items():
        if r["depth"]["rank"] < 99:
            p = db.get(pid) or {}
            groups[(p.get("team"), p.get("position"))].append((r["depth"]["rank"], pid))

    def brief(pid):
        a = lg.annotate(lg.player_asset(pid))
        o = owner.get(pid)
        return {"id": pid, "name": a["name"], "age": a["age"], "value": a["value"], "breakout": a["breakout"],
                "injury": a["injury"], "owner_rid": o[0] if o else None, "owner": o[1] if o else None,
                "depth": P[pid]["depth"]["label"]}
    out = []
    for (team, pos), ranked in groups.items():
        ranked.sort()
        n = STARTERS.get(pos, 1)
        for rank, pid in ranked[:n]:
            c = P[pid].get("contract") or {}
            inj = (db.get(pid) or {}).get("injury_status")
            if (c.get("leave_p") or 0) < 0.4 and inj not in OUT_STATUSES:
                continue
            nxt = [brief(q) for _, q in ranked[n:n + 2]]
            if not nxt:
                continue
            out.append({"team": team, "pos": pos, "starter": {**brief(pid), "leave_p": c.get("leave_p"),
                        "leave_why": c.get("leave_why"), "contract_end": c.get("end")},
                        "out_now": inj in OUT_STATUSES, "next": nxt})
    out.sort(key=lambda s: -max(x["breakout"] for x in s["next"]))
    return out
