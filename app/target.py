"""Build toward a target year: trades ranked by how much they raise my projected starting
lineup in a chosen season, not by today's value.

Uses the rebuild timeline's projections (future.asset_path): players follow their expected
value, picks turn into rookies after their draft. For each partner:

- Give pool: my assets that add least to my lineup in that year but that the partner values
  (their team context and tendencies), e.g. veterans who'll have faded by then.
- Get pool: their assets that add most to my lineup in that year.
- Every 1-2 for 1-3 combination (at most 4 assets) that they'd accept about 45%+ of the
  time (same acceptance model as the trade suggestions), and that costs me at most 10% in
  team-context value today, is scored by my lineup gain in the target year times the
  acceptance chance.

Today's cost is shown next to each deal, because buying for a later year usually means
paying a little now.
"""
from __future__ import annotations

from itertools import combinations

from . import future
from .counter import GOAL_ACC, _Scorer, _brief

GIVE_POOL = 8
GET_POOL = 10
MAX_ASSETS = 4
MAX_OVERPAY = -0.10  # most I'll lose in team-context value today


def analyze(lg, year: int | None = None, limit: int = 8) -> dict:
    me = lg.me
    tl = future.analyze(lg)
    years = [lg.season + y for y in range(1, future.YEARS + 1)]
    year = year if year in years else (years[1] if len(years) > 1 else years[0])
    y = year - lg.season
    if not me:
        return {"year": year, "years": years, "deals": []}
    paths = {}

    def path(a):
        if a["id"] not in paths:
            paths[a["id"]] = future.asset_path(lg, a)
        return paths[a["id"]]

    def strength(assets):
        return future._lineup(lg, future.lineup_entries(lg, assets, y, path))

    mine = me["players"] + me["picks"]
    base = strength(mine)
    # My assets ordered by how little they add to my lineup in the target year.
    marginal = {a["id"]: base - strength([x for x in mine if x is not a]) for a in mine}
    others = {t["roster_id"]: t["strength"][y] for t in tl["teams"] if not t["is_me"]}
    line = tl["playoff_line"][y]
    mv = min(300, lg.cfg["suggestion_min_value"])

    cands = []
    for rid, them in lg.teams.items():
        if rid == me["roster_id"]:
            continue
        S = _Scorer(lg, me["roster_id"], rid)
        give_pool = sorted((a for a in mine if a["value"] >= mv),
                           key=lambda a: -(S.vals(a)[2] - marginal[a["id"]]) / (a["value"] or 1))[:GIVE_POOL]
        adds = {a["id"]: strength(mine + [a]) - base for a in them["players"] + them["picks"] if a["value"] >= mv}
        get_pool = sorted((a for a in them["players"] + them["picks"] if adds.get(a["id"], 0) > 0),
                          key=lambda a: -(adds[a["id"]] - 0.25 * S.vals(a)[2]))[:GET_POOL]
        for ng in (1, 2):
            for give in combinations(give_pool, ng):
                for nr in range(1, MAX_ASSETS - ng + 1):
                    for get in combinations(get_pool, nr):
                        s = S.score(list(give), list(get))
                        if s["acc"] < GOAL_ACC or s["gain_pct"] < MAX_OVERPAY:
                            continue
                        gids = {a["id"] for a in give}
                        after = strength([a for a in mine if a["id"] not in gids] + list(get))
                        gain = after - base
                        if gain <= 0:
                            continue
                        cands.append((gain * s["acc"] / 100, gain, after, rid, list(give), list(get), s))

    cands.sort(key=lambda c: -c[0])
    deals, seen = [], {}
    for _, gain, after, rid, give, get, s in cands:
        top = max(get, key=lambda a: a["value"])
        # Variety across partners and centerpieces (same-year, same-round picks count as one).
        key = (rid, f"{top['season']}-{top['round']}" if top["kind"] == "pick" else top["id"])
        if key in seen or sum(1 for k in seen if k[0] == rid) >= 2:
            continue
        seen[key] = True
        them = lg.teams[rid]
        their_after = future._lineup(lg, future.lineup_entries(
            lg, [a for a in them["players"] + them["picks"] if a["id"] not in {x["id"] for x in get}] + give, y, path))
        rank_after = 1 + sum(1 for r, v in others.items() if (their_after if r == rid else v) > after)
        deals.append({"roster_id": rid, "manager": them["manager"], "window": them["window"],
                      "give": [_slim(a, path, y) for a in give], "get": [_slim(a, path, y) for a in get],
                      "gain": round(gain), "strength_after": round(after), "rank_after": rank_after,
                      "gap_after": round(after - line), **_brief(s)})
        if len(deals) >= limit:
            break
    me_row = next(t for t in tl["teams"] if t["is_me"])
    return {"year": year, "years": years, "strength": round(base), "rank": me_row["rank"][y], "playoff_line": line,
            "gap": round(base - line), "playoff_teams": tl["playoff_teams"], "deals": deals}


def _slim(a, path, y):
    return {"kind": a["kind"], "id": a["id"], "name": a["name"], "pos": a["pos"], "age": a.get("age"),
            "value": a["value"], "then": round(path(a)[y])}
