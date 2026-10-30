"""Rebuild timeline: every team's projected strength 1-3 years out, if nobody trades.

- Players: expected value from the age curves (aging.outlook "typical": the age effect
  plus the average change for players at that position and value level, which includes
  falling out of the league).
- Draft picks: worth their pick value until their draft, then a rookie who starts at that
  value and ages like a typical 22-year-old (blend of positions in a typical rookie class).
- Strength in a year = the best starting lineup from projected values (rookies of unknown
  position can fill RB/WR and flex slots). Franchise value = everything, picks included.

Dynasty values price in the future, so a young player's value isn't the same as his
points this season. As a guide to who will be good when, it's the best common yardstick
for every team, but treat the ranks as rough.
"""
from __future__ import annotations

from . import aging
from .league import SLOT_ELIGIBLE

YEARS = 3
ROOKIE_AGE = 21.8
ROOKIE_MIX = {"WR": 0.4, "RB": 0.3, "QB": 0.15, "TE": 0.15}


def _player_path(a: dict) -> list[float]:
    """Projected value now and 1..YEARS years out."""
    path = (a.get("age_outlook") or {}).get("path") or []
    out = [float(a["value"])]
    for y in range(1, YEARS + 1):
        step = path[y - 1] if len(path) >= y else None
        out.append(float(step["typical"]) if step and step.get("typical") is not None else a["value"] * 0.85 ** y)
    return out


def _rookie_factors(lg, value: float) -> list[float]:
    """Value multiple of a newly drafted rookie 0..YEARS years after his draft."""
    curve, drift = lg.aging["curve"], lg.aging["drift"]
    out = [1.0]
    for k in range(1, YEARS + 1):
        num = den = 0.0
        for pos, w in ROOKIE_MIX.items():
            o = aging.outlook(curve, pos, ROOKIE_AGE, value, years=YEARS, drift=drift)
            step = o["path"][k - 1] if o else None
            if step and step.get("typical") is not None:
                num += w * step["typical"] / (value or 1)
                den += w
        out.append(num / den if den else 0.85 ** k)
    return out


def asset_path(lg, a: dict) -> list[float]:
    """Projected value now and 1..YEARS years out, for a player or a draft pick."""
    if a["kind"] == "player":
        return _player_path(a)
    f = _rookie_factors(lg, a["value"])
    return [a["value"] if a["season"] > lg.season + y else a["value"] * f[lg.season + y - a["season"]] for y in range(YEARS + 1)]


def lineup_entries(lg, assets: list[dict], y: int, path=None) -> list[tuple[str, float]]:
    """(pos, value in year y) for the assets that can play in year y: players, plus picks
    already drafted by then (as rookies of unknown position)."""
    path = path or (lambda a: asset_path(lg, a))
    out = []
    for a in assets:
        if a["kind"] == "player":
            out.append((a["pos"], path(a)[y]))
        elif a["season"] <= lg.season + y:
            out.append(("ROOKIE", path(a)[y]))
    return out


def _lineup(lg, players: list[tuple[str, float]]) -> float:
    """Best lineup value from (pos, value) pairs; pos 'ROOKIE' fits slots that take RB or WR."""
    pool = sorted(players, key=lambda x: -x[1])
    used, total = set(), 0.0
    for slot in sorted(lg.slots, key=lambda s: len(SLOT_ELIGIBLE[s])):
        ok = SLOT_ELIGIBLE[slot]
        for i, (pos, v) in enumerate(pool):
            if i not in used and (pos in ok or (pos == "ROOKIE" and ok & {"RB", "WR"})):
                used.add(i)
                total += v
                break
    return total


def analyze(lg) -> dict:
    n_playoff = (lg.info.get("settings") or {}).get("playoff_teams") or 6
    labels = ["Now"] + [str(lg.season + y) for y in range(1, YEARS + 1)]
    teams = []
    for t in lg.teams.values():
        players = [(a, _player_path(a)) for a in t["players"] if a["kind"] == "player"]
        picks = [(pk, asset_path(lg, pk)) for pk in t["picks"]]
        strength, franchise = [], []
        for y in range(YEARS + 1):
            drafted = [("ROOKIE", path[y]) for pk, path in picks if pk["season"] <= lg.season + y]
            strength.append(_lineup(lg, [(a["pos"], path[y]) for a, path in players] + drafted))
            franchise.append(sum(path[y] for _, path in players) + sum(path[y] for _, path in picks))
        y2 = min(2, YEARS)
        core = sorted(players, key=lambda x: -x[1][y2])[:8]
        teams.append({"roster_id": t["roster_id"], "manager": t["manager"], "is_me": bool(lg.me and t["roster_id"] == lg.me["roster_id"]),
                      "window": t["window"], "strength": [round(v) for v in strength], "franchise": [round(v) for v in franchise],
                      "core": [{"id": a["id"], "name": a["name"], "pos": a["pos"], "age": a["age"], "path": [round(v) for v in path]} for a, path in core],
                      "picks": [{"name": pk["name"], "season": pk["season"], "path": [round(v) for v in path]} for pk, path in picks]})
    for y in range(YEARS + 1):
        order = sorted(teams, key=lambda t: -t["strength"][y])
        for i, t in enumerate(order):
            t.setdefault("rank", [None] * (YEARS + 1))[y] = i + 1
    line = [sorted((t["strength"][y] for t in teams), reverse=True)[min(n_playoff, len(teams)) - 1] for y in range(YEARS + 1)]
    me = next((t for t in teams if t["is_me"]), None)
    summary = None
    if me:
        first = next((labels[y] for y in range(YEARS + 1) if me["rank"][y] <= n_playoff), None)
        summary = {"first_playoff_year": first, "rank": me["rank"], "gap": [round(me["strength"][y] - line[y]) for y in range(YEARS + 1)],
                   "ahead_in": {labels[y]: [t["manager"] for t in sorted(teams, key=lambda t: t["rank"][y]) if t["rank"][y] < me["rank"][y]][:5]
                                for y in range(1, YEARS + 1)}}
    teams.sort(key=lambda t: t["rank"][min(2, YEARS)])
    return {"years": labels, "teams": teams, "playoff_line": [round(v) for v in line], "playoff_teams": n_playoff, "me": summary}
