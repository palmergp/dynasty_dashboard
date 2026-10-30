"""Deadline sell list: which of my players to sell before the trade deadline, to whom, and
for what.

Contenders pay most for win-now help in the weeks before the deadline; after it, those
players are worth what the offseason market says, a year older. For each of my players:

- Premium: the most any likely playoff team would value him at (team context: their
  window, needs and trade tendencies) minus what he's worth to my team.
- Decline: how much value he's expected to lose over the next year (age curve, expected
  value), which is what waiting costs.
- Sell score = premium + half the decline, in value points. Listed: players some buyer
  values above my team does, plus players expected to lose 10%+ in a year whom a buyer
  values at no more than 10% below my value (selling near full price now beats watching them lose more).

Buyers are teams with a 25%+ chance to make the playoffs in the season simulation. For the
best two buyers per player, the asking price is the best package of theirs that works for
both sides (counter.best_returns) and doesn't weaken their lineup for the rest of the season
(projected points per week): a contender won't take a deal that makes them worse now.
"""
from __future__ import annotations

import datetime as dt

from . import counter, season, sleeper
from .trade import context_value

BUYER_ODDS = 25.0
MIN_VALUE = 400
TOP = 10


def _deadline(lg) -> dict:
    st = lg.info.get("settings") or {}
    dl = st.get("trade_deadline") or 0
    state = sleeper.nfl_state()
    live = str(state.get("season")) == str(lg.season) and state.get("season_type") == "regular"
    week = int(state.get("week") or 0) if live else None
    out = {"week": dl or None, "current_week": week, "weeks_left": None, "dates": None, "open": True}
    if dl and dl < 99 and state.get("season_start_date") and str(state.get("season")) == str(lg.season):
        start = dt.date.fromisoformat(state["season_start_date"]) + dt.timedelta(days=7 * (dl - 1))
        out["dates"] = [start.isoformat(), (start + dt.timedelta(days=6)).isoformat()]
    if dl and dl < 99 and week is not None:
        out["weeks_left"] = dl - week
        out["open"] = dl - week >= 0
    elif not live:
        out["open"] = lg.info.get("status") not in ("post_season", "complete")
    return out


def analyze(lg, sim: dict) -> dict:
    me = lg.me
    if not me:
        return {"deadline": _deadline(lg), "buyers": [], "players": []}
    odds = {t["roster_id"]: t["playoff_pct"] for t in sim["teams"]}
    buyers = [t for rid, t in lg.teams.items() if rid != me["roster_id"] and odds.get(rid, 0) >= BUYER_ODDS]
    rows = []
    for a in me["players"]:
        if a["kind"] != "player" or max(a["value"], a["redraft"]) < MIN_VALUE:
            continue
        mine = context_value(a, me)
        offers = []
        for b in buyers:
            tend = lg.tendencies.get(b["owner_id"]) or {}
            theirs = context_value(a, b, tend)
            offers.append({"roster_id": b["roster_id"], "manager": b["manager"], "playoff_pct": odds[b["roster_id"]],
                           "need": round(b.get("need_now", {}).get(a["pos"], 0.0), 2), "their_value": round(theirs),
                           "premium": round(theirs - mine)})
        offers.sort(key=lambda o: -o["premium"])
        o = a.get("age_outlook") or {}
        y1 = (o.get("path") or [{}])[0]
        expected = y1.get("typical")
        decline = max(0.0, a["value"] - expected) if expected is not None else 0.0
        if not offers or not (offers[0]["premium"] > 0 or (decline >= 0.10 * a["value"] and offers[0]["premium"] >= -0.10 * mine)):
            continue
        reasons = []
        if o.get("verdict") in ("sell", "soon"):
            reasons.append(o["why"])
        if a["redraft"] > a["value"]:
            reasons.append(f"Worth more to win now ({a['redraft']:,} win-now) than in dynasty ({a['value']:,}), which is what contenders pay for.")
        needy = [x["manager"] for x in offers[:3] if x["need"] >= 0.5]
        if needy:
            reasons.append(f"{', '.join(needy)} {'needs' if len(needy) == 1 else 'need'} {a['pos']} help.")
        rows.append({**{k: a.get(k) for k in ("id", "name", "pos", "nfl_team", "age", "value", "redraft", "injury")},
                     "verdict": o.get("verdict"), "my_value": round(mine), "expected_next_year": round(expected) if expected is not None else None,
                     "decline": round(decline), "premium": offers[0]["premium"],
                     "score": round(offers[0]["premium"] + 0.5 * decline), "buyers": offers[:3], "reasons": reasons})
    rows.sort(key=lambda r: -r["score"])
    rows = rows[:TOP]
    for r in rows:  # asking prices from the two best buyers
        a = next(x for x in me["players"] if x["id"] == r["id"])
        for b in r["buyers"][:2]:
            asks = counter.best_returns(lg, me["roster_id"], [a], b["roster_id"], limit=5)
            for x in asks:
                x["their_weekly"] = season.lineup_change(lg, b["roster_id"], x["get"], [a])
            # Prefer packages that help the buyer this season; then the usual order (best for me).
            asks.sort(key=lambda x: (x["their_weekly"] is not None and x["their_weekly"] < -0.5))
            for x in asks[:1]:
                x["get"] = [{k: g.get(k) for k in ("kind", "id", "name", "pos", "value", "age")} for g in x["get"]]
                if x["their_weekly"] is not None:
                    x["their_weekly"] = round(x["their_weekly"], 1)
            b["asks"] = asks[:1]
        r["buyers"] = r["buyers"][:2]
    return {"deadline": _deadline(lg),
            "buyers": sorted(({"roster_id": b["roster_id"], "manager": b["manager"], "playoff_pct": odds[b["roster_id"]],
                               "window": b["window"], "needs": b.get("needs", [])} for b in buyers), key=lambda x: -x["playoff_pct"]),
            "players": rows, "buyer_odds": BUYER_ODDS}
