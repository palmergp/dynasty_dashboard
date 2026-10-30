"""Trade evaluation: market fairness, team-context value and acceptance likelihood.

Market value  = blended dynasty values, consolidation-adjusted.
Context value = what an asset is worth to a specific team given its window
                (contenders weight current production; rebuilders weight youth and picks)
                and its positional needs.
Acceptance    = the other manager's context value, further tilted by their historical
                tendencies (positions they chase, pick/youth appetite, consolidation, how
                hard they negotiate).
"""
from __future__ import annotations

import math

from .league import POSITIONS, SELL_AGE, SLOT_ELIGIBLE
from .tendencies import package_value
from .values import SOURCE_LABELS

YOUNG_AGE, OLD_AGE = 24.5, 27.5
# How quickly acceptance falls as a deal gets worse for them. Calibrated on ~190 completed
# trades in two leagues: the side that gave up more value lost a median ~26% (by the model's
# own blend of market and team context), so even lopsided-looking deals do get accepted.
# With 0.20, a fair deal is about a coin flip and a deal like that median one scores ~20.
ACCEPT_SCALE = 0.20
LIKELY, POSSIBLE = 60, 35


def context_value(a: dict, team: dict, tend: dict | None = None) -> float:
    w = team.get("w", 0.5)
    if a["kind"] == "pick":
        v = a["value"] * (1.15 - 0.30 * w)
        if tend:
            v *= 1 + 0.10 * tend["pick_affinity"] * tend["confidence"]
        return v
    alpha = 0.05 + 0.45 * w  # share of win-now value
    v = (1 - alpha) * a["value"] + alpha * a["redraft"]
    if a.get("age") is not None and a["pos"] in SELL_AGE:
        # Rebuilders discount players who will be past their position's age cliff by the
        # time the team is ready to compete: ramps from 2 yrs before the cliff to 2 yrs after.
        ramp = max(0.0, min(1.0, (a["age"] - (SELL_AGE[a["pos"]] - 2)) / 4))
        v *= 1 - 0.4 * (1 - w) * ramp
    if a.get("breakout"):
        # Upside from a growing role is worth most to teams that can wait for it.
        v *= 1 + 0.15 * (1 - w) * a["breakout"] / 100
    field = "need_now" if w >= 0.5 else "need_future"
    need = team.get(field, {}).get(a["pos"], 0.0)
    v *= 1 + 0.06 * max(-1.5, min(2.0, need))
    if tend:
        c = tend["confidence"]
        v *= 1 + 0.08 * tend["pos_affinity"].get(a["pos"], 0.0) * c
        if a.get("age") is not None:
            if a["age"] <= YOUNG_AGE:
                v *= 1 + 0.08 * tend["youth_affinity"] * c
            elif a["age"] >= OLD_AGE:
                v *= 1 - 0.08 * tend["youth_affinity"] * c
    return v


def market_view(a: dict, tend: dict | None = None) -> float:
    """Market value as a manager sees it: the blend, tilted toward the calculator their past
    trades suggest they use (calcfit), by how clear that lean is."""
    c = (tend or {}).get("calc")
    src = (a.get("sources") or {}).get(c["source"]) if c else None
    return a["value"] + c["strength"] * (src - a["market"]) if src else a["value"]


def _roster_limit(lg) -> int:
    return sum(1 for s in lg.info.get("roster_positions", []) if s not in ("IR", "TAXI"))


def _roster_cost(lg, team: dict, incoming: list, outgoing: list) -> tuple[float, list]:
    """Value of the players a team would have to cut to make roster room."""
    active = [a for a in team["players"] if not a.get("taxi") and not a.get("ir")]
    out_ids = {a["id"] for a in outgoing}
    remaining = [a for a in active if a["id"] not in out_ids]
    n_in = sum(1 for a in incoming if a["kind"] == "player")
    over = len(remaining) + n_in - _roster_limit(lg)
    if over <= 0:
        return 0.0, []
    cuts = sorted(remaining, key=lambda a: a["value"])[:over]
    return float(sum(c["value"] for c in cuts)), [c["name"] for c in cuts]


def _lineup_total(lg, players: list) -> float:
    used, total = set(), 0.0
    for slot in sorted(lg.slots, key=lambda s: len(SLOT_ELIGIBLE[s])):
        best = max((a for a in players if a["id"] not in used and a["pos"] in SLOT_ELIGIBLE[slot]
                    and not a.get("taxi")), key=lambda a: a["redraft"], default=None)
        if best:
            used.add(best["id"])
            total += best["redraft"]
    return total


def _impact(lg, team, gets, gives) -> dict:
    out_ids = {a["id"] for a in gives}
    after = [a for a in team["players"] if a["id"] not in out_ids] + [a for a in gets if a["kind"] == "player"]
    before_lineup = team["starter_redraft"]
    after_lineup = _lineup_total(lg, after)

    def wage(players):
        tv = sum(a["value"] for a in players) or 1
        return sum((a["age"] or 26) * a["value"] for a in players) / tv

    picks_delta = sum(a["value"] for a in gets if a["kind"] == "pick") - sum(a["value"] for a in gives if a["kind"] == "pick")
    pos_delta = {p: round(sum(a["value"] for a in gets if a["pos"] == p) - sum(a["value"] for a in gives if a["pos"] == p))
                 for p in POSITIONS}
    return {
        "lineup_before": round(before_lineup), "lineup_after": round(after_lineup),
        "lineup_delta_pct": round((after_lineup - before_lineup) / (before_lineup or 1) * 100, 1),
        "age_before": round(wage(team["players"]), 1), "age_after": round(wage(after), 1),
        "pick_value_delta": round(picks_delta), "pos_value_delta": pos_delta,
    }


def _verdict(pct: float, who: str = "you") -> str:
    if pct >= 0.12:
        return f"Big win for {who}"
    if pct >= 0.04:
        return f"Win for {who}"
    if pct > -0.04:
        return "Fair"
    if pct > -0.12:
        return f"Slight overpay by {who}"
    return f"Overpay by {who}"


def perceived_gain(ctx_recv, ctx_sent, mkt_recv, mkt_sent, cut_val=0.0) -> float:
    """How a manager sees a deal: half their own team context, half the trade calculators."""
    ctx = (ctx_recv - ctx_sent - cut_val) / (max(ctx_recv, ctx_sent) or 1)
    mkt = (mkt_recv - mkt_sent) / (max(mkt_recv, mkt_sent) or 1)
    return 0.5 * ctx + 0.5 * mkt


def roster_cost_fn(lg, team: dict):
    """Fast version of _roster_cost for the generator: f(n_players_in, out_ids) -> value."""
    active = sorted((a for a in team["players"] if not a.get("taxi") and not a.get("ir")), key=lambda a: a["value"])
    limit = _roster_limit(lg)

    def f(n_in: int, out_ids: set) -> float:
        remaining = [a for a in active if a["id"] not in out_ids]
        over = len(remaining) + n_in - limit
        return float(sum(a["value"] for a in remaining[:over])) if over > 0 else 0.0
    return f


def acceptance(gain_pct: float, tend: dict, n_recv: int, n_sent: int) -> tuple[float, list[str]]:
    reasons = []
    adj = gain_pct
    c = tend.get("confidence", 0)
    if n_recv < n_sent and tend.get("consolidation", 0) > 0.2:
        adj += 0.04 * tend["consolidation"] * c
        reasons.append("They like consolidating (fewer, better pieces).")
    elif n_recv > n_sent and tend.get("consolidation", 0) < -0.2:
        adj += 0.04 * -tend["consolidation"] * c
        reasons.append("They like taking back depth.")
    elif n_recv > n_sent and tend.get("consolidation", 0) > 0.2:
        adj -= 0.03 * tend["consolidation"] * c
        reasons.append("They usually avoid taking on extra pieces.")
    # Everyone wants to feel they won; sharks need more, generous managers less.
    threshold = 0.02 + max(-0.06, min(0.08, tend.get("value_edge", 0) * 0.6)) * c
    if tend.get("value_edge", 0) >= 0.08:
        reasons.append("Historically a tough negotiator.")
    elif tend.get("value_edge", 0) <= -0.08:
        reasons.append("Historically accepts below-market deals.")
    score = 100 / (1 + math.exp(-(adj - threshold) / ACCEPT_SCALE))
    return score, reasons


def evaluate(lg, a_rid: int, a_gives: list[dict], b_rid: int, b_gives: list[dict]) -> dict:
    p = lg.cfg["consolidation_exponent"]
    ta, tb = lg.teams[a_rid], lg.teams[b_rid]
    tend_a = lg.tendencies.get(ta["owner_id"]) or {}
    tend_b = lg.tendencies.get(tb["owner_id"]) or {}

    mkt_a_gets = package_value([x["value"] for x in b_gives], p)
    mkt_b_gets = package_value([x["value"] for x in a_gives], p)
    size = max(mkt_a_gets, mkt_b_gets, 1)

    by_source = {}
    for src in lg.values.by_source:
        ga = package_value([x["sources"].get(src, 0) for x in b_gives], p)
        gb = package_value([x["sources"].get(src, 0) for x in a_gives], p)
        by_source[src] = {"a_gets": round(ga), "b_gets": round(gb),
                          "pct": round((ga - gb) / (max(ga, gb) or 1) * 100, 1)}

    sides = []
    for team, tend, gets, gives in ((ta, tend_a, b_gives, a_gives), (tb, tend_b, a_gives, b_gives)):
        cut_val, cut_names = _roster_cost(lg, team, gets, gives)
        recv = package_value([context_value(x, team) for x in gets], p)
        sent = package_value([context_value(x, team) for x in gives], p)
        # Roster cuts cost roughly their (mostly small) value to the team.
        gain = recv - sent - cut_val
        gain_pct = gain / (max(recv, sent) or 1)
        recv_t = package_value([context_value(x, team, tend) for x in gets], p)
        sent_t = package_value([context_value(x, team, tend) for x in gives], p)
        mkt_recv = package_value([market_view(x, tend) for x in gets], p)
        mkt_sent = package_value([market_view(x, tend) for x in gives], p)
        acc, reasons = acceptance(perceived_gain(recv_t, sent_t, mkt_recv, mkt_sent, cut_val),
                                  tend, len(gets), len(gives))
        if tend.get("calc"):
            pct = (mkt_recv - mkt_sent) / (max(mkt_recv, mkt_sent) or 1) * 100
            reasons.append(f"Seems to trade by {SOURCE_LABELS[tend['calc']['source']]}; leaning that way, this is {pct:+.0f}% for them.")
        sides.append({
            "roster_id": team["roster_id"], "manager": team["manager"], "window": team["window"],
            "gets_value": round(recv), "gives_value": round(sent), "gain": round(gain),
            "gain_pct": round(gain_pct * 100, 1), "verdict": _verdict(gain_pct, team["manager"]),
            "acceptance": round(acc), "acceptance_label": "Likely" if acc >= LIKELY else "Possible" if acc >= POSSIBLE else "Unlikely",
            "acceptance_reasons": reasons, "roster_cuts": cut_names,
            "impact": _impact(lg, team, gets, gives),
        })

    mkt_pct = (mkt_a_gets - mkt_b_gets) / size
    notes = []
    if any(abs(s["pct"]) >= 10 for s in by_source.values()) and len(by_source) > 1:
        lo = min(by_source.values(), key=lambda s: s["pct"])["pct"]
        hi = max(by_source.values(), key=lambda s: s["pct"])["pct"]
        if hi - lo >= 10:
            notes.append(f"Value sources disagree on this deal (range {lo:+.0f}% to {hi:+.0f}% for {ta['manager']}).")
    for s in sides:
        if s["roster_cuts"]:
            notes.append(f"{s['manager']} would need to cut: {', '.join(s['roster_cuts'])}.")
    if ta["window"] == tb["window"] and ta["window"] != "middle":
        notes.append(f"Both teams are {ta['window']}ing, so context gains are smaller. Arbitrage works best across windows.")
    return {
        "market": {"a_gets": round(mkt_a_gets), "b_gets": round(mkt_b_gets),
                   "pct": round(mkt_pct * 100, 1), "verdict": _verdict(mkt_pct, ta["manager"])},
        "by_source": by_source, "sides": sides, "notes": notes,
        "a_gives": a_gives, "b_gives": b_gives,
    }
