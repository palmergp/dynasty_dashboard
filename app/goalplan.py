"""Proposed trade plans: a few trades chosen to make you good in a target year.

Goals: win now, or compete in 1, 2 or 3 years. The target is your projected starting lineup
in that year (the rebuild timeline's model: players age along the age curves, picks turn into
rookies at their draft), plus a small share of your whole roster's value then, so a plan
doesn't empty the cupboard for a few points. "Win now" uses this season's production
(redraft value) instead of dynasty value, and ignores picks (they don't score this year).

The plan is built one trade at a time. Each round, for every other team: your assets that add
least to the goal per unit of market value, their assets that add most, and every 1-2 for
1-2 package between them that they'd plausibly accept (their own team context and the
calculators they seem to use, as in Find trades). The trade with the best expected gain
(your gain toward the goal x the chance they accept) goes in, the league is re-projected as
if it happened, and the next round runs on that. It stops after MAX_TRADES or when nothing
helps enough. At most two trades per partner; assets a trade brings in aren't re-traded.
"""
from __future__ import annotations

from itertools import combinations

from . import future, plan, suggest
from .plan import Planned, _ownership, _slim
from .tendencies import package_value
from .trade import acceptance, context_value, market_view, perceived_gain, roster_cost_fn

GOALS = {"now": (0, "Win now"), "1": (1, "Compete in one year"), "2": (2, "Compete in two years"), "3": (3, "Compete in three years")}
FRANCHISE_W = 0.12   # weight on total roster value in the target year, next to lineup strength
MAX_TRADES = 4
PER_PARTNER = 2
GIVE_POOL, GET_POOL = 8, 8
MIN_ACCEPT = 50
MIN_GAIN = 0.002     # stop when the best trade adds less than 0.2% to the objective
MARKET_BAND = (0.7, 1.6)  # what you get vs. give at market value: overpay by 30% at most


class _Goal:
    """The objective for one team: lineup strength in year h + FRANCHISE_W x roster value then."""

    def __init__(self, lg, h: int):
        self.lg, self.h, self._paths = lg, h, {}

    def val(self, a) -> float:
        """What an asset is worth to the goal year (0 if it can't play by then)."""
        k = (a["kind"], a["id"])
        if k not in self._paths:
            if self.h == 0:
                v = float(a.get("redraft") or 0) if a["kind"] == "player" else 0.0
            else:
                v = future.asset_path(self.lg, a)[self.h]
            self._paths[k] = v
        return self._paths[k]

    def worth(self, a) -> float:
        """Roster value in the goal year (dynasty value now for 'win now')."""
        return float(a["value"]) if self.h == 0 else self.val(a)

    def plays(self, a) -> bool:
        return a["kind"] == "player" or (self.h > 0 and a["season"] <= self.lg.season + self.h)

    def score(self, assets) -> float:
        entries = [("ROOKIE" if a["kind"] == "pick" else a["pos"], self.val(a)) for a in assets if self.plays(a)]
        return future._lineup(self.lg, entries) + FRANCHISE_W * sum(self.worth(a) for a in assets)

    def strength(self, assets) -> float:
        return future._lineup(self.lg, [("ROOKIE" if a["kind"] == "pick" else a["pos"], self.val(a)) for a in assets if self.plays(a)])


def _mix(a: list, b: list, n: int) -> list:
    """The first n distinct items, alternating between two orderings."""
    out, seen = [], set()
    for x, y in zip(a, b):
        for z in (x, y):
            if id(z) not in seen and len(out) < n:
                seen.add(id(z))
                out.append(z)
    return out


def _rank(G, P, rid_me) -> int:
    s = {rid: G.strength(t["players"] + t["picks"]) for rid, t in P.teams.items()}
    return 1 + sum(1 for rid, v in s.items() if rid != rid_me and v > s[rid_me])


def propose(lg, goal: str) -> dict:
    h, label = GOALS[goal]
    G = _Goal(lg, h)
    years = ["Now"] + [str(lg.season + y) for y in range(1, future.YEARS + 1)]
    rid_me = lg.me["roster_id"]
    own, assets = _ownership(lg)
    p = lg.cfg["consolidation_exponent"]
    mv = lg.cfg["suggestion_min_value"]
    need_qb = 2 if lg.superflex else 1
    moved, picked, per_partner = set(), [], {}

    P = Planned(lg, own, assets)
    start = {"rank": _rank(G, P, rid_me), "strength": round(G.strength(P.me["players"] + P.me["picks"]))}
    for _ in range(MAX_TRADES):
        me = P.me
        mine = me["players"] + me["picks"]
        base = G.score(mine)
        qbs = sum(1 for a in me["players"] if a["pos"] == "QB")
        # My side: what costs the goal least per unit of market value.
        sellable = [a for a in mine if (a["kind"], a["id"]) not in moved and a["value"] >= mv]
        cost = {a["id"]: base - G.score([x for x in mine if x is not a]) for a in sellable}
        # Cheapest to the goal per unit of value, plus the most valuable (to package for a star).
        give_pool = _mix(sorted(sellable, key=lambda a: cost[a["id"]] / (a["value"] or 1)), sorted(sellable, key=lambda a: -a["value"]), GIVE_POOL)
        my_cut = roster_cost_fn(P, me)
        best = None
        for rid, them in P.teams.items():
            if rid == rid_me or per_partner.get(rid, 0) >= PER_PARTNER:
                continue
            tend = lg.tendencies.get(them["owner_id"]) or {}
            theirs = [a for a in them["players"] + them["picks"] if (a["kind"], a["id"]) not in moved and a["value"] >= mv]
            add = {a["id"]: G.score(mine + [a]) - base for a in theirs}
            helps = [a for a in theirs if add[a["id"]] > 0]
            get_pool = _mix(sorted(helps, key=lambda a: -add[a["id"]] / (a["value"] or 1)), sorted(helps, key=lambda a: -add[a["id"]]), GET_POOL)
            their_cut = roster_cost_fn(P, them)
            for ng in (1, 2, 3):
                for give in combinations(give_pool, ng):
                    give_ids = {a["id"] for a in give}
                    mkt_give = package_value([a["value"] for a in give], p)
                    for nr in ((1,) if ng == 3 else (1, 2)):
                        for get in combinations(get_pool, nr):
                            mkt_get = package_value([a["value"] for a in get], p)
                            if not MARKET_BAND[0] <= mkt_get / (mkt_give or 1) <= MARKET_BAND[1]:
                                continue
                            after = [a for a in mine if a["id"] not in give_ids] + list(get)
                            q = qbs - sum(a["pos"] == "QB" for a in give if a["kind"] == "player") + sum(a["pos"] == "QB" for a in get if a["kind"] == "player")
                            if q < min(need_qb, qbs):
                                continue
                            n_in = sum(a["kind"] == "player" for a in get)
                            gain = G.score(after) - base - FRANCHISE_W * my_cut(n_in, give_ids)
                            if gain <= MIN_GAIN * base:
                                continue
                            # Their side, as they'd see it.
                            g_them = package_value([context_value(a, them, tend) for a in give], p)
                            r_them = package_value([context_value(a, them, tend) for a in get], p)
                            v_give = package_value([market_view(a, tend) for a in give], p)
                            v_get = package_value([market_view(a, tend) for a in get], p)
                            cut_t = their_cut(sum(a["kind"] == "player" for a in give), {a["id"] for a in get})
                            acc, _ = acceptance(perceived_gain(g_them, r_them, v_give, v_get, cut_t), tend, len(give), len(get))
                            if acc < MIN_ACCEPT:
                                continue
                            score = gain * acc / 100
                            if best is None or score > best[0]:
                                best = (score, gain, acc, rid, list(give), list(get), mkt_give, mkt_get)
        if best is None:
            break
        score, gain, acc, rid, give, get, mkt_give, mkt_get = best
        them = P.teams[rid]
        tend = lg.tendencies.get(them["owner_id"]) or {}
        rank_before = _rank(G, P, rid_me)
        str_before = G.strength(mine)
        for a in give:
            own[(a["kind"], a["id"])] = rid
        for a in get:
            own[(a["kind"], a["id"])] = rid_me
        moved |= {(a["kind"], a["id"]) for a in give + get}
        per_partner[rid] = per_partner.get(rid, 0) + 1
        P = Planned(lg, own, assets)
        picked.append({
            "b_rid": rid, "manager": them["manager"], "window": them["window"],
            "give": [_slim(a) for a in give], "get": [_slim(a) for a in get],
            "acceptance": round(acc), "market_pct": round(100 * (mkt_get - mkt_give) / (max(mkt_get, mkt_give) or 1), 1),
            "strength": [round(str_before), round(G.strength(P.me["players"] + P.me["picks"]))],
            "rank": [rank_before, _rank(G, P, rid_me)],
            "why": _why(lg, G, years, give, get) + suggest._why(lg.me, them, tend, give, get)[:2],
        })
    end = {"rank": _rank(G, P, rid_me), "strength": round(G.strength(P.me["players"] + P.me["picks"]))}
    # The whole plan through the trade-plan analysis: every year's rank, this season's odds, warnings.
    refs = [{"b_rid": t["b_rid"], "a_gives": [{"kind": a["kind"], "id": a["id"]} for a in t["give"]],
             "b_gives": [{"kind": a["kind"], "id": a["id"]} for a in t["get"]]} for t in picked]
    R = plan._run(lg, refs) if refs else None
    return {"goal": goal, "label": label, "year": years[h], "year_index": h, "trades": picked, "start": start, "end": end,
            "basis": "this season's production" if h == 0 else f"projected {years[h]} values", "refs": refs,
            "timeline": R and R["timeline"], "now": R and R["now"], "total": R and R["total"],
            "problems": [x for x in (R["problems"] if R else []) if "accept only" not in x]}


def _why(lg, G, years, give, get) -> list[str]:
    """Why each piece moves, in terms of the goal year."""
    y = years[G.h]
    out = []
    for a in get:
        if G.h == 0:
            out.append(f"{a['name']} produces now: worth {a.get('redraft') or 0:,.0f} this season vs. {a['value']:,} in dynasty value.")
        elif a["kind"] == "pick":
            out.append(f"{a['name']} turns into a rookie in {a['season']}, a {years[G.h]} starter candidate ({G.val(a):,.0f} projected).")
        else:
            out.append(f"{a['name']} (age {a.get('age') or '?'}) projects at {G.val(a):,.0f} in {y} (now {a['value']:,}).")
    for a in give:
        if G.h == 0:
            if a["kind"] == "pick":
                out.append(f"{a['name']} won't score for you this season.")
            elif (a.get("redraft") or 0) < 0.8 * a["value"]:
                out.append(f"{a['name']} is worth more in dynasty value ({a['value']:,}) than he produces now ({a.get('redraft') or 0:,.0f}).")
        elif a["kind"] == "player" and G.val(a) < 0.75 * a["value"]:
            out.append(f"{a['name']} (age {a.get('age') or '?'}) projects to fall to {G.val(a):,.0f} by {y}: sell before that.")
        elif a["kind"] == "pick" and a["season"] > lg.season + G.h:
            out.append(f"{a['name']} won't be on the field by {y}.")
    return out
