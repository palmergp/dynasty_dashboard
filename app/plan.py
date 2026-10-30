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
"""
from __future__ import annotations

from . import future, roster, season, trade
from .league import POSITIONS

UNLIKELY = 35


def run(lg, trades: list[dict]) -> dict:
    me = lg.me
    rid_me = me["roster_id"]
    own = {}          # (kind, id) -> roster_id, as the plan moves things
    assets = {}       # (kind, id) -> asset
    for t in lg.teams.values():
        for a in t["players"] + t["picks"]:
            own[(a["kind"], a["id"])] = t["roster_id"]
            assets[(a["kind"], a["id"])] = a
    rows, problems = [], []
    for i, tr in enumerate(trades):
        b = tr["b_rid"]
        gives = [(r["kind"], r["id"]) for r in tr["a_gives"]]
        gets = [(r["kind"], r["id"]) for r in tr["b_gives"]]
        label = f"Trade {i + 1} with {lg.teams[b]['manager'] if b in lg.teams else b}"
        bad = [k for k in gives if own.get(k) != rid_me] + [k for k in gets if own.get(k) != b]
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
