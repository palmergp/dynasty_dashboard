"""Season wrapped: one season's story in stats, for the cinematic recap and its dashboard.

Everything is scoped to one season of the league's history (linked leagues included):
- Games: Sleeper weekly matchups. Records, all-play and luck use regular-season weeks;
  single-game highs and lows include the playoffs (labeled).
- All-play record: each week, a team "plays" every other team; luck = actual wins minus
  all-play expected wins.
- Lineups: each week's best possible lineup from that week's roster points (strict slots
  first, then flex). Players on the season-end taxi squad are left out (they can't start).
  Bench points = best possible minus actual; a "lineup loss" is a loss the best lineup
  would have won.
- Pickups and trades: the waiver and trade reports, filtered to the season. A pickup's
  points are what he scored in that manager's starting lineup that season. Trade grades are
  by today's values (retro.py), so a fleece can still change.
- Draft: that season's startup or rookie draft, valued on draft day and today.
- Max points for: Sleeper's "max PF" (best possible lineup every regular-season week), which
  this league uses for draft order; our own best-lineup total when Sleeper has none.
- Butterfly effect: for every game, the smallest one-for-one lineup swap that flips its result;
  the season is then replayed (standings, seeds, the league's real bracket, every team's actual
  weekly scores) with that one change. Swaps that change the champion are kept, smallest first.
  Skipped when our seeding can't reproduce the league's bracket (divisions, custom rules).
"""
from __future__ import annotations

from collections import Counter, defaultdict

from . import drafts as draftmod
from . import records, retro, sleeper, tendencies, waivers
from .league import SLOT_ELIGIBLE

TOP = 5


def seasons(lg) -> list[dict]:
    return [{"season": s["season"], "done": s["done"], "weeks": len(s["weeks"])} for s in records._seasons(lg) if s["weeks"]]


def _best_lineup(slots: list[str], pool: list[tuple[str, str, float]]) -> float:
    """Most points from (id, pos, points) in these slots, strict slots first, then flex."""
    used, total = set(), 0.0
    for slot in sorted(slots, key=lambda s: len(SLOT_ELIGIBLE[s])):
        best = max((p for p in pool if p[0] not in used and p[1] in SLOT_ELIGIBLE[slot]), key=lambda p: p[2], default=None)
        if best:
            used.add(best[0])
            total += best[2]
    return total


def analyze(lg, season: int) -> dict | None:
    S = next((s for s in records._seasons(lg) if s["season"] == season and s["weeks"]), None)
    if not S:
        return None
    names = tendencies._manager_names(lg)
    nm = lambda uid: names.get(uid, "Unowned team") if uid else "Unowned team"
    info = lambda pid: lg.players_db.get(pid) or {}
    pname = lambda pid: info(pid).get("full_name") or pid
    ppos = lambda pid: info(pid).get("position") or "?"
    me = (lg.me or {}).get("owner_id")
    lid, owners = S["league"]["league_id"], S["owners"]
    positions = S["league"].get("roster_positions") or []
    slots = [p for p in positions if p in SLOT_ELIGIBLE]
    rosters = sleeper.rosters(lid, None if S["done"] else sleeper.LIVE_TTL)
    taxi = {r["roster_id"]: set(r.get("taxi") or []) for r in rosters}
    games, perfs = records._games(lg, [S])

    # ---- lineups: best possible vs. actual, every team-week
    lineup = {}  # (user_id, week) -> (actual, best)
    scores, detail = {}, {}  # (user_id, week) -> points; -> (starters [(slot, pid, pts)], bench [(pid, pos, pts)])
    for w in S["weeks"]:
        for m in sleeper.matchups(lid, w, S["done"]):
            uid, pts = owners.get(m["roster_id"]), m.get("players_points") or {}
            if m.get("points"):
                scores[(uid, w)] = m["points"]
            if m.get("matchup_id") is None or not m.get("points"):
                continue
            pool = [(pid, ppos(pid), p) for pid, p in pts.items() if pid not in taxi.get(m["roster_id"], ())]
            started = list(zip(positions, m.get("starters") or [], m.get("starters_points") or []))
            other = sum(p for s, pid, p in started if s not in SLOT_ELIGIBLE)
            lineup[(uid, w)] = (m["points"], max(m["points"], _best_lineup(slots, pool) + other))
            on = {pid for _, pid, _ in started}
            detail[(uid, w)] = ([x for x in started if x[0] in SLOT_ELIGIBLE and x[1] and x[1] != "0"],
                                [x for x in pool if x[0] not in on])

    # ---- games, standings, all-play, luck, streaks
    sides = [{"week": g["week"], "playoffs": g["playoffs"], "user_id": u, "manager": nm(u), "points": round(p, 2),
              "opp_id": o, "opp": nm(o), "opp_points": round(op, 2)}
             for g in games for u, p, o, op in ((g["a"], g["pa"], g["b"], g["pb"]), (g["b"], g["pb"], g["a"], g["pa"]))]
    for x in sides:
        x["margin"] = round(x["points"] - x["opp_points"], 2)
    reg = [x for x in sides if not x["playoffs"]]
    by_week = defaultdict(list)
    for x in reg:
        by_week[x["week"]].append(x["points"])
    teams = {}
    for uid in {x["user_id"] for x in sides}:
        mine = sorted((x for x in reg if x["user_id"] == uid), key=lambda x: x["week"])
        w = sum(x["margin"] > 0 for x in mine)
        l = sum(x["margin"] < 0 for x in mine)
        ap = sum(sum(p < x["points"] for p in by_week[x["week"]]) / max(len(by_week[x["week"]]) - 1, 1) for x in mine)
        streak = run = 0
        for x in mine:
            run = run + 1 if x["margin"] > 0 else 0
            streak = max(streak, run)
        lu = [lineup[(uid, x["week"])] for x in sides if x["user_id"] == uid and (uid, x["week"]) in lineup]
        lineup_losses = [x for x in sides if x["user_id"] == uid and x["margin"] < 0 and (uid, x["week"]) in lineup
                         and lineup[(uid, x["week"])][1] > x["opp_points"]]
        teams[uid] = {"user_id": uid, "manager": nm(uid), "w": w, "l": l, "t": len(mine) - w - l,
                      "pf": round(sum(x["points"] for x in mine), 1), "pa": round(sum(x["opp_points"] for x in mine), 1),
                      "allplay_w": round(ap, 1), "luck": round(w - ap, 1), "streak": streak,
                      "high": max((x["points"] for x in mine), default=0), "low": min((x["points"] for x in mine), default=0),
                      "coach_pct": round(100 * sum(a for a, _ in lu) / (sum(b for _, b in lu) or 1), 1) if lu else None,
                      "bench_pts": round(sum(b - a for a, b in lu), 1),
                      "lineup_losses": [{"week": x["week"], "opp": x["opp"], "lost_by": round(-x["margin"], 2),
                                         "best": round(lineup[(uid, x["week"])][1], 2)} for x in lineup_losses]}
    standings = sorted(teams.values(), key=lambda t: (-(t["w"] + 0.5 * t["t"]), -t["pf"]))
    for i, t in enumerate(standings):
        t["rank"] = i + 1
    for i, t in enumerate(sorted(standings, key=lambda t: -t["pf"])):
        t["pf_rank"] = i + 1
    # Max points for: Sleeper's own number when it has one, else our best lineups over the regular season.
    ppts = {owners.get(r["roster_id"]): (r.get("settings") or {}).get("ppts") for r in rosters}
    ppts_dec = {owners.get(r["roster_id"]): (r.get("settings") or {}).get("ppts_decimal") or 0 for r in rosters}
    reg_weeks = {x["week"] for x in reg}
    for t in standings:
        uid = t["user_id"]
        t["max_pf"] = round(ppts[uid] + ppts_dec[uid] / 100, 1) if ppts.get(uid) else \
            round(sum(b for (u, w), (_, b) in lineup.items() if u == uid and w in reg_weeks), 1)
    for i, t in enumerate(sorted(standings, key=lambda t: -t["max_pf"])):
        t["max_pf_rank"] = i + 1

    # ---- playoffs
    champion = runner_up = third = None
    if S["done"]:
        b = records.winners_bracket(lid, True)
        final = next((m for m in b if m.get("p") == 1 and m.get("w")), None)
        bronze = next((m for m in b if m.get("p") == 3 and m.get("w")), None)
        if final:
            cu, ru = owners.get(final["w"]), owners.get(final["l"])
            g = max((x for x in sides if x["playoffs"] and x["user_id"] == cu and x["opp_id"] == ru), key=lambda x: x["week"], default=None)
            champion = {"user_id": cu, "manager": nm(cu), "record": f"{teams[cu]['w']}-{teams[cu]['l']}" if cu in teams else None,
                        "seed": teams[cu]["rank"] if cu in teams else None,
                        "final": {k: g[k] for k in ("week", "points", "opp", "opp_points", "margin")} if g else None}
            runner_up = {"user_id": ru, "manager": nm(ru)}
        if bronze:
            third = {"user_id": owners.get(bronze["w"]), "manager": nm(owners.get(bronze["w"]))}
    butterfly = _butterfly(S, games, scores, detail, standings, champion["user_id"], nm, pname) if champion else []

    # ---- players in starting lineups
    for p in perfs:
        p.update(name=pname(p["player_id"]), pos=ppos(p["player_id"]), manager=nm(p["user_id"]))
    by_player, by_pm = defaultdict(float), defaultdict(lambda: [0.0, 0])
    for p in perfs:
        by_player[p["player_id"]] += p["points"]
        by_pm[(p["player_id"], p["user_id"])][0] += p["points"]
        by_pm[(p["player_id"], p["user_id"])][1] += 1
    top_players = [{"player_id": pid, "name": pname(pid), "pos": ppos(pid), "points": round(v, 1)}
                   for pid, v in sorted(by_player.items(), key=lambda kv: -kv[1])[:10]]
    mvp = {}
    for (pid, uid), (pts, n) in by_pm.items():
        if uid not in mvp or pts > mvp[uid]["points"]:
            mvp[uid] = {"user_id": uid, "manager": nm(uid), "player_id": pid, "name": pname(pid), "pos": ppos(pid), "points": round(pts, 1), "starts": n}
    best_games = sorted(perfs, key=lambda p: -p["points"])[:TOP]

    # ---- pickups (points: in that manager's starting lineup this season, after the pickup)
    starts = defaultdict(list)
    for p in perfs:
        starts[(p["player_id"], p["user_id"])].append((p["week"], p["points"]))
    pk = []
    for p in waivers.analyze(lg)["pickups"]:
        if p["season"] != season:
            continue
        uid = owners.get(p["roster_id"])
        pts = sum(v for w, v in starts.get((p["player_id"], uid), []) if p["week"] is None or w >= p["week"])
        pk.append({"player_id": p["player_id"], "name": p["name"], "pos": p["pos"], "user_id": uid, "manager": nm(uid),
                   "week": p["week"], "date": p["date"], "type": p["type"], "bid": p["bid"], "points": round(pts, 1),
                   "value_at_pickup": p["value_at_pickup"], "now_value": p["now_value"]})
    best_pickup = {}
    for p in pk:
        if p["points"] > 0 and (p["user_id"] not in best_pickup or p["points"] > best_pickup[p["user_id"]]["points"]):
            best_pickup[p["user_id"]] = p
    adds = Counter(p["user_id"] for p in pk)
    faab = defaultdict(int)
    for p in pk:
        faab[p["user_id"]] += p["bid"] or 0
    for uid, t in teams.items():
        t.update(moves=adds.get(uid, 0), faab=faab.get(uid, 0))

    # ---- trades (graded by today's values)
    tr = [t for t in retro.analyze(lg)["trades"] if str(t["season"]) == str(season)]
    trade_rows = []
    for t in tr:
        lead = t["now"]["leader"]
        trade_rows.append({"id": t["id"], "date": t["date"], "week": t["week"], "winner": lead, "gap": t["now"]["gap"], "pct": t["now"]["pct"],
                           "sides": [{"manager": s["manager"], "user_id": s.get("user_id"), "received": s["received"], "faab": s["faab"],
                                      "points": s["points"], "result": s.get("result")}
                                     for s in sorted(t["sides"], key=lambda s: s["manager"] != lead)]})
    trade_rows.sort(key=lambda t: t["date"])
    n_trades = Counter(s["manager"] for t in trade_rows for s in t["sides"])
    for t in teams.values():
        t["trades"] = n_trades.get(t["manager"], 0)
    fleece = max((t for t in trade_rows if t["winner"]), key=lambda t: t["gap"], default=None)

    # ---- that season's draft
    D = draftmod.analyze(lg)
    draft = None
    d = next((d for d in D["drafts"] if d["season"] == season), None)
    if d:
        ps = [p for p in D["picks"] if p["draft_id"] == d["id"]]
        slim = lambda p: {k: p.get(k) for k in ("round", "pick_no", "slot", "manager", "player_id", "name", "pos", "draft_value", "now_value", "change")}
        draft = {"label": d["label"], "kind": d["kind"], "n": len(ps), "first": slim(min(ps, key=lambda p: p["pick_no"])) if ps else None,
                 "steals": [slim(p) for p in sorted(ps, key=lambda p: -p["change"])[:TOP]],
                 "busts": [slim(p) for p in sorted(ps, key=lambda p: p["change"])[:TOP]]}

    wins = [x for x in sides if x["margin"] > 0]
    coached = [t for t in standings if t["coach_pct"] is not None]
    out = {
        "season": season, "done": S["done"], "league": S["league"].get("name"), "n_teams": len(teams),
        "weeks": len({x["week"] for x in reg}), "playoff_weeks": len({x["week"] for x in sides if x["playoffs"]}),
        "me": me if me in teams else None,
        "champion": champion, "runner_up": runner_up, "third": third, "butterfly": butterfly,
        "standings": standings,
        "totals": {"points": round(sum(x["points"] for x in reg), 1), "games": len(reg) // 2,
                   "pickups": len(pk), "claims": sum(p["type"] == "claim" for p in pk), "faab": sum(p["bid"] or 0 for p in pk),
                   "trades": len(trade_rows), "players_started": len(by_player)},
        "games": {"high": sorted(sides, key=lambda x: -x["points"])[:TOP],
                  "low": sorted(reg, key=lambda x: x["points"])[:TOP],
                  "blowouts": sorted(wins, key=lambda x: -x["margin"])[:TOP],
                  "close": sorted(wins, key=lambda x: x["margin"])[:TOP]},
        "players": {"top": top_players, "best_games": best_games, "mvp": sorted(mvp.values(), key=lambda m: -m["points"])},
        "pickups": {"best": sorted(best_pickup.values(), key=lambda p: -p["points"]), "bids": sorted((p for p in pk if p["bid"]), key=lambda p: -p["bid"])[:TOP],
                    "most_active": _leader(standings, "moves")},
        "trades": {"list": trade_rows, "fleece": fleece,
                   "most_active": _leader(standings, "trades") if trade_rows else None},
        "draft": draft,
        "lineups": {"best_coach": max(coached, key=lambda t: t["coach_pct"]) if coached else None,
                    "worst_coach": min(coached, key=lambda t: t["coach_pct"]) if coached else None,
                    "most_bench": max(coached, key=lambda t: t["bench_pts"]) if coached else None},
        "luck": {"lucky": max(standings, key=lambda t: t["luck"]) if standings else None,
                 "unlucky": min(standings, key=lambda t: t["luck"]) if standings else None},
    }
    return out


class _Bracket:
    """The season replayed: regular-season games -> seeds -> the real playoff bracket, from each team's
    actual weekly scores plus any changes. Built from the league's own bracket, with each slot tied to
    a seed (or to an earlier game's winner or loser)."""

    def __init__(self, S, reg_games, scores, standings):
        st = S["league"].get("settings") or {}
        self.n = st.get("playoff_teams") or 0
        self.start = S["playoff_start"]
        self.round_type = st.get("playoff_round_type") or 0
        self.reg_games, self.scores = reg_games, scores
        self.users = [t["user_id"] for t in standings]
        self.ok = False
        b = records.winners_bracket(S["league"]["league_id"], True)
        if not b or not self.n:
            return
        owners = S["owners"]
        seed = {t["user_id"]: t["rank"] for t in standings}
        self.rounds = max(m["r"] for m in b)
        self.matches = []
        for m in sorted(b, key=lambda m: (m["r"], m["m"])):
            srcs = []
            for k in ("t1", "t2"):
                frm = m.get(f"{k}_from")
                if frm:
                    srcs.append(("w", frm["w"]) if "w" in frm else ("l", frm["l"]))
                else:
                    s = seed.get(owners.get(m.get(k)))
                    if not s or s > self.n:
                        return  # our seeding doesn't match the league's (divisions, custom rules): don't guess
                    srcs.append(("seed", s))
            self.matches.append({"m": m["m"], "r": m["r"], "p": m.get("p"), "srcs": srcs, "real_w": owners.get(m.get("w"))})
        real = self.run({})
        self.ok = all(x["real_w"] is None or real["results"][x["m"]]["w"] == x["real_w"] for x in self.matches)

    def weeks(self, r):
        if self.round_type == 2:
            return [self.start + 2 * (r - 1), self.start + 2 * (r - 1) + 1]
        if self.round_type == 1 and r == self.rounds:
            return [self.start + r - 1, self.start + r]
        return [self.start + r - 1]

    def run(self, change):
        pts = lambda u, w: self.scores.get((u, w), 0.0) + change.get((u, w), 0.0)
        rec = {u: [0.0, 0.0] for u in self.users}  # wins (ties half), points for
        for w, a, b in self.reg_games:
            pa, pb = pts(a, w), pts(b, w)
            for u, mine, theirs in ((a, pa, pb), (b, pb, pa)):
                if u in rec:
                    rec[u][0] += 1 if mine > theirs else 0.5 if mine == theirs else 0
                    rec[u][1] += mine
        seeds = sorted(rec, key=lambda u: (-rec[u][0], -rec[u][1]))
        results = {}
        for x in self.matches:
            ts = []
            for kind, v in x["srcs"]:
                ts.append(seeds[v - 1] if kind == "seed" else results.get(v, {}).get(kind))
            if None in ts:
                continue
            wk = self.weeks(x["r"])
            s1, s2 = (round(sum(pts(u, w) for w in wk), 2) for u in ts)
            win = 0 if s1 > s2 or (s1 == s2 and seeds.index(ts[0]) < seeds.index(ts[1])) else 1
            results[x["m"]] = {"w": ts[win], "l": ts[1 - win], "teams": ts, "scores": [s1, s2], "week": wk[-1], "r": x["r"], "p": x["p"]}
        final = next((x for x in self.matches if x["p"] == 1), None)
        return {"seeds": seeds, "results": results, "champion": results.get(final["m"], {}).get("w") if final else None}


def _butterfly(S, games, scores, detail, standings, champion, nm, pname, limit=3) -> list[dict]:
    """One lineup call that, flipped, hands the title to someone else. For each game, the smallest
    one-for-one swap (a bench player for an eligible starter) that changes its result, then the whole
    season replayed with that one score changed. Kept when the champion changes; the smallest swings first."""
    reg_games = [(g["week"], g["a"], g["b"]) for g in games if not g["playoffs"]]
    br = _Bracket(S, reg_games, scores, standings)
    if not br.ok:
        return []
    real = br.run({})
    if real["champion"] != champion:
        return []
    n = br.n
    playoff_games = {(r["week"], u): r for r in real["results"].values() for u in r["teams"]}
    cands = []
    for g in games:
        if g["playoffs"] and (g["week"], g["a"]) not in playoff_games:
            continue  # consolation games can't change the title
        for u, o, mine, theirs in ((g["a"], g["b"], g["pa"], g["pb"]), (g["b"], g["a"], g["pb"], g["pa"])):
            if (u, g["week"]) not in detail:
                continue
            margin = mine - theirs
            starters, bench = detail[(u, g["week"])]
            best = None
            for slot, pid, p in starters:
                for qid, qpos, q in bench:
                    if qpos not in SLOT_ELIGIBLE[slot] or q <= 0:
                        continue
                    d = q - p
                    if (margin <= 0 and d > -margin) or (margin > 0 and d < -margin):
                        if best is None or abs(d) < abs(best[3]):
                            best = (slot, pid, qid, d, p, q)
            if best:
                cands.append((g, u, o, margin, best))
    out = []
    for g, u, o, margin, (slot, pid, qid, d, p, q) in cands:
        alt = br.run({(u, g["week"]): d})
        if alt["champion"] == champion or alt["champion"] is None:
            continue
        seat = lambda seeds, x: seeds.index(x) + 1 if seeds.index(x) < n else None
        moved = [{"user_id": x, "manager": nm(x), "from": seat(real["seeds"], x), "to": seat(alt["seeds"], x)}
                 for x in real["seeds"] if seat(real["seeds"], x) != seat(alt["seeds"], x)]
        label = lambda r: "final" if r == br.rounds else "semifinal" if r == br.rounds - 1 else "quarterfinal" if r == br.rounds - 2 else f"round {r}"
        game = lambda r: {"week": r["week"], "round": label(r["r"]), "won": True,
                          "points": r["scores"][r["teams"].index(r["w"])], "opp_points": r["scores"][r["teams"].index(r["l"])]}
        champ_loss = next((r for r in sorted(alt["results"].values(), key=lambda r: r["r"]) if r["l"] == champion and r["p"] in (None, 1)), None)
        fate = {"kind": "missed", "seed": None} if seat(alt["seeds"], champion) is None else None
        if champ_loss:
            fate = {"kind": "lost", "opp": nm(champ_loss["w"]), "opp_id": champ_loss["w"], **game(champ_loss),
                    "points": champ_loss["scores"][champ_loss["teams"].index(champion)],
                    "opp_points": champ_loss["scores"][champ_loss["teams"].index(champ_loss["w"])]}
        new = alt["champion"]
        path = [{**game(r), "opp": nm(r["l"])} for r in sorted(alt["results"].values(), key=lambda r: r["r"]) if r["w"] == new and r["p"] in (None, 1)]
        out.append({
            "week": g["week"], "playoffs": g["playoffs"], "user_id": u, "manager": nm(u), "opp_id": o, "opp": nm(o),
            "slot": slot, "started": {"player_id": pid, "name": pname(pid), "points": round(p, 2)},
            "benched": {"player_id": qid, "name": pname(qid), "points": round(q, 2)},
            "points": round(g["pa"] if u == g["a"] else g["pb"], 2), "opp_points": round(g["pb"] if u == g["a"] else g["pa"], 2),
            "won": margin > 0, "swing": round(d, 2), "alt_points": round((g["pa"] if u == g["a"] else g["pb"]) + d, 2),
            "moved": moved, "fate": fate, "champion": nm(champion), "champion_id": champion,
            "new_champion": nm(new), "new_champion_id": new, "new_path": path,
        })
    # Mistakes first (a loss the bench would have won), regular season before playoffs, smallest swing;
    # one story per game.
    out.sort(key=lambda x: (x["playoffs"], x["won"], abs(x["swing"])))
    seen, keep = set(), []
    for x in out:
        game = (x["week"], frozenset((x["user_id"], x["opp_id"])))
        if game not in seen:
            seen.add(game)
            keep.append(x)
    return keep[:limit]


def _leader(standings: list[dict], key: str) -> dict | None:
    """The manager with the most of something (ties go to the better finish), and how many tied."""
    if not standings:
        return None
    top = max(t[key] for t in standings)
    tied = [t for t in standings if t[key] == top]
    return {"manager": tied[0]["manager"], "user_id": tied[0]["user_id"], "n": top, "tied": len(tied)}
