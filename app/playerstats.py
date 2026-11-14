"""Season stats for the player page: a game log and season totals with positional ranks.

Points are each week's Sleeper box scores scored with this league's settings, so ranks match
what the league actually rewards (superflex QB scoring, TE premium and so on). Projections are
Sleeper's for that week, also in league scoring. A week without a stat line is a bye when his
team didn't play, otherwise a missed game (Sleeper marks inactive players as active, so injuries
and healthy scratches look the same).
"""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from . import lineup, opportunity, sleeper
from .cache import cached
from .live import stat_line

POS = ("QB", "RB", "WR", "TE")
PAST_TTL = 30 * 86400  # past weeks' projections don't change
URL = "https://api.sleeper.com/stats/nfl/{season}/{week}?season_type=regular" + "".join(f"&position[]={p}" for p in POS)


def week_stats(season: int, week: int, ttl: int | None) -> dict:
    """player_id -> {team, opp, date, stats} for one week's box scores."""
    def fetch():
        rows = lineup._http.get(URL.format(season=season, week=week)).json() or []
        return {r["player_id"]: {"team": r.get("team"), "opp": r.get("opponent"), "date": r.get("date"),
                                 "stats": r.get("stats") or {}} for r in rows if r.get("player_id")}
    return cached(f"wkstats:{season}:{week}", ttl, fetch)


def stats_season(lg) -> int:
    """The league's season, or the one before until its first week is done."""
    return lg.season if opportunity.weeks_done(lg.season) else lg.season - 1


def build(lg, season: int) -> dict:
    """Every completed week of a season: box scores, projections, league points and weekly
    positional ranks, plus each player's season points and games."""
    weeks = opportunity.weeks_done(season)
    past = season < int(sleeper.nfl_state().get("season") or 0)
    ttl = lambda w: None if past else 6 * 3600 if w == weeks[-1] else 7 * 86400  # recent weeks get stat corrections
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = dict(zip(weeks, pool.map(lambda w: week_stats(season, w, ttl(w)), weeks)))
        proj = dict(zip(weeks, pool.map(lambda w: lineup.projections(season, w, None if past else PAST_TTL), weeks)))
    sc = lg.info.get("scoring_settings") or {}
    pos_of = lambda pid: (lg.players_db.get(pid) or {}).get("position")
    pts, rank, played, tot = {}, {}, {}, defaultdict(lambda: [0.0, 0])
    for w, R in rows.items():
        pts[w] = {pid: lineup.score(r["stats"], sc) for pid, r in R.items() if r["stats"].get("gp")}
        played[w] = {t for pid in pts[w] for t in (R[pid]["team"], R[pid]["opp"])}
        by = defaultdict(list)
        for pid, p in pts[w].items():
            by[pos_of(pid)].append((p, pid))
            tot[pid][0] += p
            tot[pid][1] += 1
        rank[w] = {pid: i + 1 for xs in by.values() for i, (_, pid) in enumerate(sorted(xs, reverse=True))}
    return {"season": season, "weeks": weeks, "rows": rows, "proj": proj, "pts": pts, "rank": rank, "played": played, "tot": dict(tot)}


def player(lg, pid: str, S: dict) -> dict | None:
    """One player's game log and season summary from build()."""
    pos_of = lambda q: (lg.players_db.get(q) or {}).get("position")
    pos = pos_of(pid)
    if pos not in POS or not S["weeks"]:
        return None
    sc = lg.info.get("scoring_settings") or {}
    games, totals, team = [], defaultdict(float), None
    for w in S["weeks"]:
        r, pr = S["rows"][w].get(pid), S["proj"][w].get(pid)
        proj = round(lineup.score(pr["stats"], sc), 1) if pr and pr["stats"] else None
        if pid in S["pts"][w]:
            st, team = r["stats"], r["team"]
            for k, v in st.items():
                if isinstance(v, (int, float)):
                    totals[k] += v
            games.append({"week": w, "status": "played", "opp": r["opp"], "team": r["team"],
                          "pts": round(S["pts"][w][pid], 1), "proj": proj, "rank": S["rank"][w][pid], "line": stat_line(pos, st),
                          "snap_pct": round(100 * st.get("off_snp", 0) / st["tm_off_snp"]) if st.get("tm_off_snp") else None})
        else:
            t = (r or {}).get("team") or team or (lg.players_db.get(pid) or {}).get("team")
            status = "no_team" if not t else "bye" if t not in S["played"][w] else "out"
            games.append({"week": w, "status": status, "opp": (r or {}).get("opp")})

    played = [g for g in games if g["status"] == "played"]
    total, gp = S["tot"].get(pid, (0.0, 0))
    peers = [v for q, v in S["tot"].items() if pos_of(q) == pos]
    min_g = max(1, len(S["weeks"]) // 2)  # per-game ranks need half the weeks played
    ppg = total / gp if gp else None
    with_proj = [g for g in played if g["proj"] is not None]
    return {
        "season": S["season"], "weeks": len(S["weeks"]), "pos": pos, "games": games,
        "gp": gp, "pts": round(total, 1), "ppg": round(ppg, 1) if ppg is not None else None,
        "pts_rank": 1 + sum(1 for p, _ in peers if p > total) if gp else None,
        "ppg_rank": 1 + sum(1 for p, n in peers if n >= min_g and p / n > ppg) if gp >= min_g else None, "min_games": min_g,
        "top12": sum(1 for g in played if g["rank"] <= 12), "top24": sum(1 for g in played if g["rank"] <= 24),
        "beat_proj": sum(1 for g in with_proj if g["pts"] > g["proj"]), "n_proj": len(with_proj),
        "snap_pct": round(100 * totals["off_snp"] / totals["tm_off_snp"]) if totals["tm_off_snp"] else None,
        "line": stat_line(pos, totals), "per_game": {k: round(totals[k] / gp, 1) for k in ("pass_att", "pass_yd", "rush_att", "rush_yd", "rec_tgt", "rec", "rec_yd") if gp and totals[k]},
    }
