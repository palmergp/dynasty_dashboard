"""Trade suggestions and partner ranking.

The generator looks for *value arbitrage*: assets worth more to the partner than to me
(e.g. an aging RB to a contender) in exchange for assets worth more to me than to them
(young players, picks). Packages are scored by my context gain times the partner's
tendency-adjusted acceptance likelihood.
"""
from __future__ import annotations

from itertools import combinations

from .trade import acceptance, context_value, evaluate, perceived_gain, roster_cost_fn
from .tendencies import package_value

MAX_GIVE_POOL = 9
MAX_GET_POOL = 12


def _pool(assets, me, them, tend, min_value, mine: bool, size: int):
    """Assets with their value to me and to the partner, best arbitrage edge first."""
    rows = []
    for a in assets:
        if a["value"] < min_value:
            continue
        v_me, v_them = context_value(a, me), context_value(a, them, tend)
        edge = ((v_them - v_me) if mine else (v_me - v_them)) / (a["value"] or 1)
        rows.append((a, v_me, v_them, edge))
    # Prefer assets with an arbitrage edge, but keep high-value ones in the mix.
    rows.sort(key=lambda r: -(r[3] * 3 + r[0]["value"] / 10000))
    return rows[:size]


def _combos(pool, max_n):
    for n in range(1, max_n + 1):
        yield from combinations(pool, n)


def for_partner(lg, partner_rid: int, limit: int = 4) -> list[dict]:
    me = lg.me
    them = lg.teams[partner_rid]
    p = lg.cfg["consolidation_exponent"]
    tend = lg.tendencies.get(them["owner_id"]) or {}
    mv = lg.cfg["suggestion_min_value"]
    give_pool = _pool(me["players"] + me["picks"], me, them, tend, mv, True, MAX_GIVE_POOL)
    get_pool = _pool(them["players"] + them["picks"], me, them, tend, mv, False, MAX_GET_POOL)

    my_cut, their_cut = roster_cost_fn(lg, me), roster_cost_fn(lg, them)
    cands = []
    for give in _combos(give_pool, 2):
        mkt_give = package_value([r[0]["value"] for r in give], p)
        give_me = package_value([r[1] for r in give], p)
        give_them = package_value([r[2] for r in give], p)
        give_ids = {r[0]["id"] for r in give}
        give_np = sum(1 for r in give if r[0]["kind"] == "player")
        for get in _combos(get_pool, 3):
            if len(give) + len(get) > 4:
                continue
            mkt_get = package_value([r[0]["value"] for r in get], p)
            if not 0.75 <= mkt_get / (mkt_give or 1) <= 1.35:
                continue
            get_me = package_value([r[1] for r in get], p)
            get_np = sum(1 for r in get if r[0]["kind"] == "player")
            cut_me = my_cut(get_np, give_ids)
            my_gain = (get_me - give_me - cut_me) / (max(get_me, give_me) or 1)
            if my_gain < 0.0:
                continue
            get_them = package_value([r[2] for r in get], p)
            cut_them = their_cut(give_np, {r[0]["id"] for r in get})
            acc, _ = acceptance(perceived_gain(give_them, get_them, mkt_give, mkt_get, cut_them),
                                tend, len(give), len(get))
            if acc < 30:
                continue
            # Expected value gained (points of my context value), not % — so trivial
            # depth swaps don't outrank deals that move the needle.
            score = (get_me - give_me - cut_me) * (acc / 100)
            cands.append((score, [r[0] for r in give], [r[0] for r in get]))

    cands.sort(key=lambda c: -c[0])
    out, seen = [], set()
    for score, give, get in cands:
        # Diversify: don't return several variants built around the same centerpieces.
        primary = max(give, key=lambda a: a["value"])["id"]
        primary_get = max(get, key=lambda a: a["value"])["id"]
        if (primary, primary_get) in seen or sum(1 for k in seen if k[0] == primary) >= 2:
            continue
        seen.add((primary, primary_get))
        ev = evaluate(lg, me["roster_id"], give, partner_rid, get)
        out.append({"score": round(score), "give": give, "get": get, "eval": ev,
                    "why": _why(me, them, tend, give, get)})
        if len(out) >= limit:
            break
    return out


def _why(me, them, tend, give, get) -> list[str]:
    why = []
    for a in give:
        if a["kind"] == "player" and a["pos"] in them.get("needs", []):
            why.append(f"{them['manager']} needs {a['pos']} help, and {a['name']} fills it.")
        if them["window"] == "contend" and a.get("redraft", 0) > a["value"]:
            why.append(f"{a['name']} produces now, which a contender pays for.")
    for a in get:
        o = a.get("opp") or {}
        if a["kind"] == "player" and a.get("breakout", 0) >= 35:
            top = o.get("notes") or []
            why.append(f"Buy before a breakout: {a['name']} scores {a['breakout']}"
                       + (f" ({top[0]['text'][0].lower() + top[0]['text'][1:]})." if top else "."))
    young = [a["name"] for a in get if a["kind"] == "player" and (a.get("age") or 99) <= 24.5]
    picks = [a["name"] for a in get if a["kind"] == "pick"]
    if me["window"] == "rebuild" and (young or picks):
        why.append("You get younger: " + ", ".join(young + picks) + ".")
    if picks and tend.get("pick_affinity", 0) < -0.2:
        why.append("They've been willing to sell picks before.")
    return list(dict.fromkeys(why))


def partners(lg, per_partner: int = 3) -> list[dict]:
    me = lg.me
    out = []
    for rid, them in lg.teams.items():
        if rid == me["roster_id"]:
            continue
        tend = lg.tendencies.get(them["owner_id"]) or {}
        sugg = for_partner(lg, rid, per_partner)
        complement = abs(me["w"] - them["w"])
        best = max((s["score"] for s in sugg), default=0)
        seasons = max(lg.season - tend.get("first_season", lg.season) + 1, 1)
        activity = min(1.0, tend.get("n_trades", 0) / seasons / 4) if tend.get("n_trades") else 0.25
        fit = 100 * (0.40 * min(1, complement / 0.7) + 0.40 * min(1, best / 1200) + 0.20 * activity)
        reasons = []
        if complement >= 0.3:
            reasons.append(f"{them['window'].title()} window vs. your {me['window']}: natural trade partner.")
        my_sells = {a["pos"] for a in me["players"] if a["id"] in me["sell_candidates"]}
        overlap = [p for p in them.get("needs", []) if p in my_sells]
        if overlap:
            reasons.append(f"Needs {', '.join(overlap)}, which you have to sell.")
        if tend.get("tags"):
            reasons.append("Tendencies: " + ", ".join(tend["tags"]) + ".")
        out.append({"roster_id": rid, "manager": them["manager"], "team_name": them["team_name"],
                    "window": them["window"], "contend_score": them["contend_score"], "fit": round(fit),
                    "reasons": reasons, "suggestions": sugg})
    out.sort(key=lambda x: -x["fit"])
    return out
