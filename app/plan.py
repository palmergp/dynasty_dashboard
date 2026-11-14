"""Trade plan: several trades together, and what they do to your team combined.

A rebuild is usually a series of trades, and moves that each look fine can clash: two that
send out the same player, three that each add a body until the roster overflows, or a set
that leaves you without a starting QB. The plan replays the trades in order on copies of
the rosters (so a later trade can send on something an earlier one brought in), then
compares your team before and after all of them:

- Value: market value in and out, and your team-context gain, trade by trade and in total.
- This season: playoff and title odds and your own 1st's projected slot (same simulated
  games with and without the plan).
- Rebuild timeline: your projected lineup strength and rank each year (partners' rosters
  change too).
- Roster: active players vs. the limit next offseason (roster room), position values, age
  and pick capital.
- Next trades: the usual trade suggestions, run on the league as the plan leaves it.
- Overlapping trades: two trades that both send out (or both bring in) the same player or
  pick are alternatives. Each is run as the plan without the other, and the better one is the
  one with the higher expected gain (your team-context gain x their acceptance odds), with
  the rest of the comparison (timeline, this season, roster) as reasons.
"""
from __future__ import annotations

from . import future, roster, season, suggest, trade
from .league import POSITIONS, League

UNLIKELY = 35
MAX_CONFLICTS = 4
CLOSE = 0.10  # expected gains within 10% of each other: a close call


def _ownership(lg) -> tuple[dict, dict]:
    """(kind, id) -> roster_id and (kind, id) -> asset for every rostered player and pick."""
    own, assets = {}, {}
    for t in lg.teams.values():
        for a in t["players"] + t["picks"]:
            own[(a["kind"], a["id"])] = t["roster_id"]
            assets[(a["kind"], a["id"])] = a
    return own, assets


def _sides(tr) -> tuple[list, list]:
    return [(r["kind"], r["id"]) for r in tr["a_gives"]], [(r["kind"], r["id"]) for r in tr["b_gives"]]


def _blocked(own, rid_me, b, gives, gets) -> list:
    """Assets that are no longer where the trade needs them at this point in the plan."""
    return [k for k in gives if own.get(k) != rid_me] + [k for k in gets if own.get(k) != b]


def run(lg, trades: list[dict]) -> dict:
    R = _run(lg, trades)
    R["conflicts"] = [_compare(lg, trades, i, j, shared) for i, j, shared in _overlaps(lg, trades)[:MAX_CONFLICTS]]
    if R["conflicts"]:
        R["problems"].append("Some trades overlap: they can't all happen. See Overlapping trades for which to keep.")
    return R


def _run(lg, trades: list[dict]) -> dict:
    me = lg.me
    rid_me = me["roster_id"]
    own, assets = _ownership(lg)  # own changes as the plan moves things
    rows, problems = [], []
    for i, tr in enumerate(trades):
        b = tr["b_rid"]
        gives, gets = _sides(tr)
        label = f"Trade {i + 1} with {lg.teams[b]['manager'] if b in lg.teams else b}"
        bad = _blocked(own, rid_me, b, gives, gets)
        if b not in lg.teams or b == rid_me or bad:
            names = ", ".join(assets[k]["name"] for k in bad if k in assets) or "unknown assets"
            problems.append(f"{label}: {names} {'is' if len(bad) == 1 else 'are'} no longer on that roster by this point in the plan "
                            "(already traded in an earlier trade?). Skipped." if bad else f"{label}: pick another team. Skipped.")
            rows.append({"index": i, "skipped": True, "manager": lg.teams.get(b, {}).get("manager")})
            continue
        ev = trade.evaluate(lg, rid_me, [assets[k] for k in gives], b, [assets[k] for k in gets])
        mine, theirs = ev["sides"]
        rows.append({"index": i, "skipped": False, "roster_id": b, "manager": theirs["manager"],
                     "give": [_slim(assets[k]) for k in gives], "get": [_slim(assets[k]) for k in gets],
                     "market_pct": ev["market"]["pct"], "gain_pct": mine["gain_pct"], "gain": mine["gain"],
                     "acceptance": theirs["acceptance"], "acceptance_label": theirs["acceptance_label"]})
        if theirs["acceptance"] < UNLIKELY:
            problems.append(f"{label}: they'd accept only about {theirs['acceptance']}% of the time.")
        for k in gives:
            own[k] = b
        for k in gets:
            own[k] = rid_me

    # Rosters after the whole plan, for every team it touches.
    touched = {rid_me} | {r["roster_id"] for r in rows if not r["skipped"]}
    after = {rid: {"players": [], "picks": []} for rid in touched}
    for k, rid in own.items():
        if rid in after:
            a = assets[k]
            a2 = dict(a, taxi=False, ir=False, roster_id=rid) if a.get("roster_id") != rid else a  # moved: active for them
            after[rid]["players" if a["kind"] == "player" else "picks"].append(a2)

    # This season.
    base = lg.sim
    sim_after = season.simulate(lg, rosters={rid: v["players"] for rid, v in after.items()}) if base and base["weeks_left"] else None
    now = None
    if sim_after:
        b0 = next(t for t in base["teams"] if t["roster_id"] == rid_me)
        b1 = next(t for t in sim_after["teams"] if t["roster_id"] == rid_me)
        now = {k: [b0[k], b1[k]] for k in ("playoff_pct", "title_pct", "avg_slot", "weekly_proj")}
        if base.get("draft_season"):
            owner = next((rid for (kind, aid), rid in own.items() if kind == "pick" and aid == f"{base['draft_season']}-1-{rid_me}"), rid_me)
            now["own_first_owner"] = lg.teams[owner]["manager"] if owner != rid_me else None

    # Rebuild timeline.
    tl = future.analyze(lg)
    strength = {t["roster_id"]: list(t["strength"]) for t in tl["teams"]}
    before_me = list(strength[rid_me])
    for rid, v in after.items():
        strength[rid] = [round(future._lineup(lg, future.lineup_entries(lg, v["players"] + v["picks"], y))) for y in range(len(tl["years"]))]
    ranks = lambda s: [1 + sum(1 for r, xs in s.items() if r != rid_me and xs[y] > s[rid_me][y]) for y in range(len(tl["years"]))]
    me_row = next(t for t in tl["teams"] if t["is_me"])
    timeline = {"years": tl["years"], "strength": [before_me, strength[rid_me]], "rank": [me_row["rank"], ranks(strength)],
                "playoff_line": tl["playoff_line"], "playoff_teams": tl["playoff_teams"]}

    # Roster next offseason and composition.
    st = roster.analyze(lg)["settings"]
    team_after = {**me, "players": after[rid_me]["players"], "picks": after[rid_me]["picks"]}
    room = [roster._plan(lg, me, st), roster._plan(lg, team_after, st)]
    if room[1]["over"] > max(room[0]["over"], 0):
        problems.append(f"Next offseason you'd need {room[1]['over']} cuts (vs. {max(room[0]['over'], 0)} now). See Roster room.")
    comp = [_composition(me["players"], me["picks"]), _composition(after[rid_me]["players"], after[rid_me]["picks"])]
    need_qb = 2 if lg.superflex else 1
    if sum(1 for a in after[rid_me]["players"] if a["pos"] == "QB") < need_qb:
        problems.append(f"You'd have fewer than {need_qb} QBs.")
    done = [r for r in rows if not r["skipped"]]
    total = {"give": sum(a["value"] for r in done for a in r["give"]), "get": sum(a["value"] for r in done for a in r["get"]),
             "gain": sum(r["gain"] for r in done)}
    return {"trades": rows, "problems": problems, "total": total, "now": now, "timeline": timeline,
            "roster": {"before": _room(room[0]), "after": _room(room[1]), "limit": st["limit"]},
            "composition": {"before": comp[0], "after": comp[1]}}


class Planned:
    """The league as the plan leaves it: rosters moved, and every team's lineup, position
    strength, needs and surplus redone (needs are relative to the whole league). Everything
    else (values, tendencies, windows, pick prices) reads through to the real league."""

    def __init__(self, lg, own: dict, assets: dict):
        self._lg = lg
        self.teams = {rid: {**t, "players": [], "picks": []} for rid, t in lg.teams.items()}
        for t in self.teams.values():
            for k in ("need_now", "need_future", "depth_z"):  # refilled with setdefault below
                t.pop(k, None)
        for k, rid in own.items():
            a = assets[k]
            a2 = dict(a) if a.get("roster_id") == rid else dict(a, taxi=False, ir=False, roster_id=rid)  # moved: active for them
            self.teams[rid]["players" if a["kind"] == "player" else "picks"].append(a2)
        for t in self.teams.values():
            t["players"].sort(key=lambda a: -a["value"])
            League._lineup(self, t)
        League._position_strength(self)
        for t in self.teams.values():
            League._team_summary(self, t)
        self.me = self.teams[lg.me["roster_id"]]

    def __getattr__(self, name):
        return getattr(self._lg, name)


def next_trades(lg, trades: list[dict], limit: int = 6, per_partner: int = 3) -> dict:
    """Trade suggestions for after the plan, best expected gain first. Assets the plan already
    moves are left out, so these add to the plan instead of redoing or undoing it."""
    rid_me = lg.me["roster_id"]
    own, assets = _ownership(lg)
    moved, n = set(), 0
    for tr in trades:
        b = tr["b_rid"]
        gives, gets = _sides(tr)
        if b not in lg.teams or b == rid_me or _blocked(own, rid_me, b, gives, gets):
            continue
        for k in gives:
            own[k] = b
        for k in gets:
            own[k] = rid_me
        moved |= set(gives) | set(gets)
        n += 1
    P = Planned(lg, own, assets)
    out = [{**s, "roster_id": rid, "manager": t["manager"], "window": t["window"]}
           for rid, t in P.teams.items() if rid != rid_me
           for s in suggest.for_partner(P, rid, per_partner, exclude=moved)]
    out.sort(key=lambda s: -s["score"])
    keep, uses = [], {}
    for s in out:  # for variety: at most two per partner, and two built on the same centerpiece you give
        keys = (s["roster_id"], max(s["give"], key=lambda a: a["value"])["id"])
        if all(uses.get(k, 0) < 2 for k in keys):
            uses.update({k: uses.get(k, 0) + 1 for k in keys})
            keep.append(s)
    return {"applied": n, "needs": P.me["needs"], "suggestions": keep[:limit]}


def _overlaps(lg, trades) -> list[tuple[int, int, list[str]]]:
    """Pairs of trades that both send out, or both bring in, the same asset. (One that brings
    in what a later one sends on is a chain, not an overlap.)"""
    names = {k: a["name"] for k, a in _ownership(lg)[1].items()}
    sides = [_sides(t) for t in trades]
    out = []
    for i in range(len(trades)):
        for j in range(i + 1, len(trades)):
            shared = (set(sides[i][0]) & set(sides[j][0])) | (set(sides[i][1]) & set(sides[j][1]))
            if shared:
                out.append((i, j, sorted(names.get(k, k[1]) for k in shared)))
    return out


def _option(lg, trades, keep: int, drop: int) -> dict:
    """The plan with trade `keep` and without trade `drop`, summed up for the comparison."""
    R = _run(lg, [t for k, t in enumerate(trades) if k != drop])
    row = R["trades"][keep - (keep > drop)]
    if row["skipped"]:  # still blocked by a third trade
        return {"index": keep, "skipped": True, "manager": row["manager"]}
    needs = set(lg.me["needs"])
    return {"index": keep, "skipped": False, "manager": row["manager"], "give": row["give"], "get": row["get"],
            "gain": row["gain"], "gain_pct": row["gain_pct"], "market_pct": row["market_pct"], "acceptance": row["acceptance"],
            "expected": round(row["gain"] * row["acceptance"] / 100),
            "fills": sorted({a["pos"] for a in row["get"] if a["pos"] in needs}),
            "ranks": R["timeline"]["rank"][1], "years": R["timeline"]["years"],
            "playoff_pct": R["now"]["playoff_pct"][1] if R["now"] else None,
            "cuts": R["roster"]["after"]["over"],
            "problems": [x for x in R["problems"] if "accept only" not in x]}


def _compare(lg, trades, i, j, shared) -> dict:
    a, b = _option(lg, trades, i, j), _option(lg, trades, j, i)
    if a["skipped"] or b["skipped"]:
        return {"trades": [i, j], "shared": shared, "options": [a, b], "pick": None, "close": False,
                "reasons": {"pick": [], "other": []}, "note": "Another trade in the plan also overlaps with these; sort that one out first."}
    best, other = (a, b) if a["expected"] >= b["expected"] else (b, a)
    n = lambda o: f"Trade {o['index'] + 1}"
    close = best["expected"] <= 0 or best["expected"] - other["expected"] <= CLOSE * abs(best["expected"])
    reasons = {"pick": [f"Expected gain {best['expected']:+,} vs. {other['expected']:+,} (your team-context gain x the chance they accept)."], "other": []}
    for side, o, x in (("pick", best, other), ("other", other, best)):
        say = reasons[side].append
        if o["gain"] - x["gain"] >= 100:
            say(f"{n(o)} adds more to your team: {o['gain']:+,} vs. {x['gain']:+,} in team-context value.")
        if o["acceptance"] - x["acceptance"] >= 10:
            say(f"{n(o)} is more likely to be accepted: about {o['acceptance']}% vs. {x['acceptance']}%.")
        if o["market_pct"] - x["market_pct"] >= 5:
            say(f"{n(o)} wins by more on the market: {o['market_pct']:+.0f}% vs. {x['market_pct']:+.0f}%.")
        better = [k for k in range(1, len(o["years"])) if o["ranks"][k] < x["ranks"][k]]  # future years
        if better:
            say(f"{n(o)} leaves you ranked higher in " + ", ".join(f"{o['years'][k]} (#{o['ranks'][k]} vs. #{x['ranks'][k]})" for k in better) + ".")
        if o["playoff_pct"] is not None and x["playoff_pct"] is not None and o["playoff_pct"] - x["playoff_pct"] >= 3:
            say(f"{n(o)} gives better playoff odds this season: {o['playoff_pct']:.0f}% vs. {x['playoff_pct']:.0f}%.")
        if x["cuts"] > o["cuts"]:
            say(f"{n(o)} needs fewer cuts next offseason ({o['cuts']} vs. {x['cuts']}).")
        if set(o["fills"]) - set(x["fills"]):
            say(f"{n(o)} fills your {'/'.join(sorted(set(o['fills']) - set(x['fills'])))} need.")
        for msg in set(x["problems"]) - set(o["problems"]):
            say(f"With {n(x)}: {msg.split(': ', 1)[-1]}")
    return {"trades": [i, j], "shared": shared, "options": [a, b], "pick": best["index"], "close": close, "reasons": reasons}


def _slim(a):
    return {"kind": a["kind"], "id": a["id"], "name": a["name"], "pos": a["pos"], "value": a["value"], "age": a.get("age")}


def _room(p):
    return {"active": p["active"], "over": max(p["over"], 0), "cuts": [c["name"] for c in p["cuts"]]}


def _composition(players, picks):
    vals = [a for a in players if a["value"] > 0]
    tv = sum(a["value"] for a in vals) or 1
    return {"pos": {p: round(sum(a["value"] for a in players if a["pos"] == p)) for p in POSITIONS},
            "picks": round(sum(p["value"] for p in picks)), "players": len(players),
            "age": round(sum((a["age"] or 26) * a["value"] for a in vals) / tv, 1),
            "total": round(sum(a["value"] for a in players) + sum(p["value"] for p in picks))}
