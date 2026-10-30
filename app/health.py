"""Data health: every source the app depends on, when it last loaded, and whether it failed.

Most extras (usage stats, value history, KTC history, rookie history, the season
simulation) fail quietly so the rest of the app keeps working; this lists them in one place.
"""
from __future__ import annotations

from . import pickhistory
from .cache import cache_time
from .values import SOURCE_LABELS, _league_format


def _row(name, powers, ok, detail, key=None):
    return {"name": name, "powers": powers, "ok": ok, "detail": detail, "loaded": cache_time(key) if key else None}


def report(lg) -> dict:
    lid = lg.cfg["league_id"]
    fmt = _league_format(lg.info)
    vkey = f"{fmt['num_teams']}:{fmt['superflex']}:{fmt['ppr']}:{fmt['tep']}"
    rows = [_row("Sleeper league", "Everything: rosters, picks, trades, matchups", bool(lg.teams),
                 f"{len(lg.teams)} teams, {len(lg.trades)} trades, {lg.weeks_played} weeks played", f"rosters:{lid}"),
            _row("Sleeper players", "Names, positions, ages, injuries", bool(lg.players_db), f"{len(lg.players_db):,} players", "players:nfl:v3")]
    for src in ("fantasycalc", "ktc", "dynastyprocess"):
        n = len(lg.values.by_source.get(src) or {})
        err = lg.values.errors.get(src)
        rows.append(_row(f"{SOURCE_LABELS[src]} values", "Player and pick values (blended)", n > 0 and not err,
                         err or f"{n:,} players matched, {len(lg.values.unmatched.get(src) or [])} unmatched", f"values:{src}:{vkey}"))
    op = lg.opportunity
    rows.append(_row("Weekly usage and contracts (Sleeper stats, nflverse)", "Breakouts, buy low, free agents, depth charts",
                     not lg.opportunity_error and bool(op.get("players")),
                     lg.opportunity_error or f"{len(op.get('players') or {}):,} players, {op.get('weeks', 0)} weeks of usage", "contracts:otc:v2"))
    hist = lg.aging.get("hist") or {}
    dates = hist.get("dates") or []
    rows.append(_row("DynastyProcess value history", "Age curves, sell timing, buy low, drafts, value movers",
                     not lg.aging_error and bool(dates), lg.aging_error or (f"{len(dates)} weekly snapshots, {dates[0]} to {dates[-1]}" if dates else "none")))
    try:
        H = pickhistory.pick_history(lg)
        rows.append(_row("DynastyProcess pick history", "When to sell picks, league prices", bool(H["dates"]),
                         f"{len(H['dates'])} weekly snapshots since {H['dates'][0]}" if H["dates"] else "none"))
    except Exception as e:
        rows.append(_row("DynastyProcess pick history", "When to sell picks, league prices", False, f"{type(e).__name__}: {e}"))
    cf = lg.calcfit
    rows.append(_row("KeepTradeCut value history", "Calculator leans (League prices, Find trades)", not lg.calcfit_error,
                     lg.calcfit_error or f"{cf.get('trades', 0)} trades valued, {sum(1 for m in cf.get('managers', []) if m.get('lean'))} managers with a lean"))
    rk = lg.rookies
    rows.append(_row("Rookie history (DynastyProcess, nflverse)", "Hit rates, pick odds", rk is not None,
                     lg.rookies_error or f"classes {rk['classes'][0]}–{rk['classes'][-1]}, stats through {rk['last_season']}" if rk else lg.rookies_error))
    sim = lg.sim
    rows.append(_row("Season simulation (Sleeper projections)", "Playoff odds, draft slots, pick values, season impact", sim is not None,
                     f"{sim['sims']:,} simulated seasons, {len(sim['weeks_left'])} weeks left" if sim else "unavailable: picks use generic tier prices"))
    return {"rows": rows, "ok": sum(r["ok"] for r in rows), "total": len(rows)}
