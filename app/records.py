"""All-time record book: games, seasons, players, champions, trades, drafts and pickups.

Games come from Sleeper weekly matchups for every season in the league's history
(including linked leagues up to the restart). Each team is credited to the manager who
owned that roster in that season. Win-loss records use regular-season weeks only;
single-game records also include playoff weeks (labeled). Trade, draft and pickup records
reuse the trade review, draft and waiver reports.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from . import drafts as draftmod
from . import retro, sleeper, tendencies, waivers

TOP = 5


def winners_bracket(league_id: str, done: bool, force=False) -> list:
    return sleeper.cached(f"bracket:{league_id}", None if done else sleeper.LIVE_TTL,
                          lambda: sleeper._get(f"/league/{league_id}/winners_bracket") or [], force)


def _seasons(lg) -> list[dict]:
    """Per season in the history: league, owners by roster and completed weeks."""
    state = sleeper.nfl_state()
    out = []
    for l in sleeper.league_chain(lg.cfg["league_id"]):
        season = int(l["season"])
        if l.get("_cutoff") and season >= dt.datetime.fromtimestamp(l["_cutoff"] / 1000).year:
            continue  # a linked league's games after the restart don't count
        done = l.get("status") == "complete"
        if done:
            weeks = range(1, 19)
        elif str(state.get("season")) == l["season"] and state.get("season_type") == "regular":
            weeks = range(1, int(state.get("week") or 1))
        else:
            weeks = range(0)
        ttl = None if done else sleeper.LIVE_TTL
        owners = {r["roster_id"]: r.get("owner_id") for r in sleeper.rosters(l["league_id"], ttl)}
        out.append({"league": l, "season": season, "done": done, "weeks": list(weeks), "owners": owners,
                    "playoff_start": (l.get("settings") or {}).get("playoff_week_start") or 15})
    return out


def _games(lg, seasons) -> tuple[list[dict], list[dict]]:
    """(games, player performances). A game has both teams' manager and points."""
    games, perfs = [], []
    for s in seasons:
        lid = s["league"]["league_id"]
        for w in s["weeks"]:
            by_mid = defaultdict(list)
            for m in sleeper.matchups(lid, w, s["done"]):
                uid = s["owners"].get(m["roster_id"])
                if m.get("matchup_id") is not None:
                    by_mid[m["matchup_id"]].append((uid, m["roster_id"], m.get("points") or 0.0))
                for pid, pts in zip(m.get("starters") or [], m.get("starters_points") or []):
                    if pid and pid != "0" and pts:
                        perfs.append({"season": s["season"], "week": w, "user_id": uid, "player_id": pid, "points": pts})
            for teams in by_mid.values():
                if len(teams) != 2 or not (teams[0][2] and teams[1][2]):
                    continue  # byes and weeks that weren't played
                (ua, ra, pa), (ub, rb, pb) = teams
                games.append({"season": s["season"], "week": w, "playoffs": w >= s["playoff_start"],
                              "a": ua, "b": ub, "pa": pa, "pb": pb})
    return games, perfs


def analyze(lg) -> dict:
    names = tendencies._manager_names(lg)
    nm = lambda uid: names.get(uid, "Unowned team") if uid else "Unowned team"
    pname = lambda pid: (lg.players_db.get(pid) or {}).get("full_name") or pid
    ppos = lambda pid: (lg.players_db.get(pid) or {}).get("position") or "?"
    seasons = _seasons(lg)
    games, perfs = _games(lg, seasons)

    # ---- team games
    sides = [{"season": g["season"], "week": g["week"], "playoffs": g["playoffs"], "user_id": u, "manager": nm(u),
              "points": round(p, 2), "opp": nm(o), "opp_points": round(op, 2)}
             for g in games for u, p, o, op in ((g["a"], g["pa"], g["b"], g["pb"]), (g["b"], g["pb"], g["a"], g["pa"]))]
    high = sorted(sides, key=lambda x: -x["points"])[:TOP]
    low = sorted((x for x in sides if not x["playoffs"]), key=lambda x: x["points"])[:TOP]
    blowouts = sorted((x for x in sides if x["points"] > x["opp_points"]), key=lambda x: -(x["points"] - x["opp_points"]))[:TOP]
    close = sorted((x for x in sides if x["points"] > x["opp_points"]), key=lambda x: x["points"] - x["opp_points"])[:TOP]
    for x in blowouts + close:
        x["margin"] = round(x["points"] - x["opp_points"], 2)

    # ---- seasons and all-time standings (regular season)
    rec = defaultdict(lambda: {"w": 0, "l": 0, "t": 0, "pf": 0.0, "pa": 0.0, "g": 0})
    for x in sides:
        if x["playoffs"]:
            continue
        for key in ((x["user_id"], x["season"]), (x["user_id"], "all")):
            r = rec[key]
            r["g"] += 1
            r["pf"] += x["points"]
            r["pa"] += x["opp_points"]
            r["w" if x["points"] > x["opp_points"] else "l" if x["points"] < x["opp_points"] else "t"] += 1
    season_rows = [{"user_id": u, "manager": nm(u), "season": s, **r, "pf": round(r["pf"], 1),
                    "win_pct": round((r["w"] + 0.5 * r["t"]) / r["g"], 3)}
                   for (u, s), r in rec.items() if s != "all" and r["g"]]
    for r in season_rows:
        r["ppg"] = round(r["pf"] / r["g"], 1)
    most_pf = sorted(season_rows, key=lambda r: -r["pf"])[:TOP]
    best_rec = sorted(season_rows, key=lambda r: (-r["win_pct"], -r["pf"]))[:TOP]

    champs, titles, finals = [], defaultdict(int), defaultdict(int)
    for s in seasons:
        if not s["done"]:
            continue
        b = winners_bracket(s["league"]["league_id"], True)
        final = next((m for m in b if m.get("p") == 1 and m.get("w")), None)
        if not final:
            continue
        cu, ru = s["owners"].get(final["w"]), s["owners"].get(final["l"])
        titles[cu] += 1
        finals[cu] += 1
        finals[ru] += 1
        champs.append({"season": s["season"], "league": s["league"].get("name"), "champion": nm(cu), "champion_id": cu,
                       "runner_up": nm(ru)})
    champs.sort(key=lambda c: -c["season"])

    standings = []
    for (u, s), r in rec.items():
        if s != "all" or not r["g"]:
            continue
        mine = [x for x in season_rows if x["user_id"] == u]
        standings.append({"user_id": u, "manager": nm(u), "seasons": len(mine), "w": r["w"], "l": r["l"], "t": r["t"],
                          "win_pct": round((r["w"] + 0.5 * r["t"]) / r["g"], 3), "pf": round(r["pf"], 1),
                          "ppg": round(r["pf"] / r["g"], 1), "titles": titles.get(u, 0), "finals": finals.get(u, 0),
                          "high": max((x["points"] for x in sides if x["user_id"] == u), default=0)})
    standings.sort(key=lambda r: (-r["titles"], -r["win_pct"]))

    # ---- players in starting lineups
    for p in perfs:
        p.update(name=pname(p["player_id"]), pos=ppos(p["player_id"]), manager=nm(p["user_id"]))
    best_games = sorted(perfs, key=lambda p: -p["points"])[:TOP]
    by_pm = defaultdict(lambda: [0.0, 0])
    for p in perfs:
        k = (p["player_id"], p["user_id"])
        by_pm[k][0] += p["points"]
        by_pm[k][1] += 1
    franchise = sorted(({"player_id": pid, "name": pname(pid), "pos": ppos(pid), "manager": nm(u),
                         "points": round(v[0], 1), "starts": v[1]} for (pid, u), v in by_pm.items()),
                       key=lambda r: -r["points"])[:TOP]

    # ---- trades
    R = retro.analyze(lg)

    def trade_row(t, moment):
        m = t[moment]
        loser = next((s["manager"] for s in t["sides"] if s["manager"] != m["leader"]), None)
        win_side = next((s for s in t["sides"] if s["manager"] == m["leader"]), None)
        return {"id": t["id"], "date": t["date"], "season": t["season"], "week": t["week"],
                "winner": m["leader"], "loser": loser, "gap": m["gap"], "pct": m["pct"],
                "then_gap": t["then"], "now_gap": t["now"],
                # Winner's side first, so the expanded view reads "winner got / loser got".
                "sides": [{"manager": s["manager"], "received": s["received"], "faab": s["faab"], "points": s["points"]}
                          for s in sorted(t["sides"], key=lambda s: s is not win_side)]}
    fleece_now = [trade_row(t, "now") for t in sorted((t for t in R["trades"] if t["now"]["leader"]), key=lambda t: -t["now"]["gap"])[:TOP]]
    fleece_then = [trade_row(t, "then") for t in sorted((t for t in R["trades"] if t["then"]["leader"]), key=lambda t: -t["then"]["gap"])[:TOP]]
    flips = []
    for t in R["trades"]:
        if t["then"]["leader"] and t["now"]["leader"] and t["then"]["leader"] != t["now"]["leader"]:
            row = trade_row(t, "now")
            row["swing"] = t["then"]["gap"] + t["now"]["gap"]
            row["then_leader"] = t["then"]["leader"]
            flips.append(row)
    flips = sorted(flips, key=lambda r: -r["swing"])[:TOP]

    # ---- drafts
    D = draftmod.analyze(lg)
    classes = []
    dmeta = {d["id"]: d for d in D["drafts"]}
    for t in D["teams"]:
        for did, s in t["drafts"].items():
            if did == "all" or did not in dmeta:
                continue
            classes.append({"manager": t["manager"], "draft": dmeta[did]["label"], "kind": dmeta[did]["kind"],
                            "n": s["n"], "draft_value": s["draft_value"], "now_value": s["now_value"],
                            "change": s["now_value"] - s["draft_value"], "change_pct": s["change_pct"], "best": s["best"]})
    early = set(D.get("early_drafts") or [])
    for c in classes:
        c["early"] = c["draft"] in early
    # Classes are ranked by % change so a 20-round startup and a 3-round rookie class compare
    # fairly, and startup and rookie drafts are ranked separately.
    ranked = lambda kind, sign: sorted((c for c in classes if c["kind"] == kind and c["n"] >= 2 and c["draft_value"] > 0),
                                       key=lambda c: -sign * c["change_pct"])[:TOP]
    steals = sorted(D["picks"], key=lambda p: -p["change"])[:TOP]
    busts = sorted(D["picks"], key=lambda p: p["change"])[:TOP]
    pick_row = lambda p: {"name": p["name"], "pos": p["pos"], "manager": p["manager"], "draft": p["draft"],
                          "pick": f"Rd {p['round']}, #{p['pick_no']}", "draft_value": p["draft_value"], "now_value": p["now_value"],
                          "change": p["change"]}

    # ---- pickups
    W = waivers.analyze(lg)
    pk = lambda p: {"name": p["name"], "pos": p["pos"], "manager": p["manager"], "date": p["date"], "bid": p["bid"],
                    "type": p["type"], "captured": p["captured"], "start_points": p["start_points"], "starts": p["starts"],
                    "value_at_pickup": p["value_at_pickup"], "outcome": p["outcome"]}
    pickups = W["pickups"]
    pick_value = [pk(p) for p in sorted(pickups, key=lambda p: -p["captured"])[:TOP]]
    pick_points = [pk(p) for p in sorted(pickups, key=lambda p: -p["start_points"])[:TOP]]
    big_bids = [pk(p) for p in sorted(pickups, key=lambda p: -p["bid"])[:TOP] if p["bid"]]
    free = [pk(p) for p in sorted((p for p in pickups if not p["bid"]), key=lambda p: -p["start_points"])[:TOP]]

    return {
        "seasons": [s["season"] for s in seasons], "n_games": len(games),
        "value_history_start": D.get("history_start"),
        "champions": champs, "standings": standings,
        "games": {"high": high, "low": low, "blowouts": blowouts, "close": close},
        "season_records": {"points": most_pf, "record": best_rec},
        "players": {"games": best_games, "franchise": franchise},
        "trades": {"now": fleece_now, "then": fleece_then, "flips": flips},
        "drafts": {"best_rookie": ranked("rookie", 1), "worst_rookie": ranked("rookie", -1),
                   "best_startup": ranked("startup", 1), "worst_startup": ranked("startup", -1), "steals": [pick_row(p) for p in steals],
                   "busts": [pick_row(p) for p in busts]},
        "pickups": {"value": pick_value, "points": pick_points, "bids": big_bids, "free": free},
    }
