"""Counter-offers and asking prices.

Both use the same quick scoring as the trade suggestions: my gain is my team-context
value received minus sent (and any roster cuts), as a share of the bigger side; their
acceptance is the calibrated, tendency-adjusted likelihood from trade.acceptance. A deal
"works" when my gain is at least GOAL_GAIN and their acceptance at least GOAL_ACC.

- fix(): the smallest changes to a proposed deal that make it work for both sides. Ask
  for one or two more of their assets, or give one less of mine; if it's already good
  for me but they'd likely refuse, add one of mine or drop one of theirs.
- best_returns(): for assets I want to sell to a team, the packages of theirs (1-3
  assets) that work and give me the most.
"""
from __future__ import annotations

from itertools import combinations

from .tendencies import package_value
from .trade import acceptance, context_value, market_view, perceived_gain, roster_cost_fn

GOAL_GAIN = 0.03
GOAL_ACC = 45
POOL = 12


class _Scorer:
    def __init__(self, lg, me_rid: int, them_rid: int):
        self.lg, self.me, self.them = lg, lg.teams[me_rid], lg.teams[them_rid]
        self.tend = lg.tendencies.get(self.them["owner_id"]) or {}
        self.p = lg.cfg["consolidation_exponent"]
        self.my_cut, self.their_cut = roster_cost_fn(lg, self.me), roster_cost_fn(lg, self.them)
        self._v = {}

    def vals(self, a):
        """(market, value to me, value to them, market as they see it) for an asset."""
        k = a["id"]
        if k not in self._v:
            self._v[k] = (a["value"], context_value(a, self.me), context_value(a, self.them, self.tend), market_view(a, self.tend))
        return self._v[k]

    def score(self, give: list, get: list) -> dict:
        p = self.p
        g, r = [self.vals(a) for a in give], [self.vals(a) for a in get]
        mkt_give, mkt_get = package_value([x[0] for x in g], p), package_value([x[0] for x in r], p)
        give_me, get_me = package_value([x[1] for x in g], p), package_value([x[1] for x in r], p)
        give_them, get_them = package_value([x[2] for x in g], p), package_value([x[2] for x in r], p)
        n_get = sum(1 for a in get if a["kind"] == "player")
        n_give = sum(1 for a in give if a["kind"] == "player")
        cut_me = self.my_cut(n_get, {a["id"] for a in give})
        cut_them = self.their_cut(n_give, {a["id"] for a in get})
        gain = (get_me - give_me - cut_me) / (max(get_me, give_me) or 1)
        view_give, view_get = package_value([x[3] for x in g], p), package_value([x[3] for x in r], p)
        acc, _ = acceptance(perceived_gain(give_them, get_them, view_give, view_get, cut_them), self.tend, len(give), len(get))
        return {"gain_pct": gain, "gain": get_me - give_me - cut_me, "acc": acc, "mkt_give": mkt_give, "mkt_get": mkt_get}

    @staticmethod
    def works(s: dict) -> bool:
        return s["gain_pct"] >= GOAL_GAIN and s["acc"] >= GOAL_ACC


def _brief(s: dict) -> dict:
    return {"gain_pct": round(s["gain_pct"] * 100, 1), "acceptance": round(s["acc"]),
            "mkt_give": round(s["mkt_give"]), "mkt_get": round(s["mkt_get"])}


def _names(xs):
    return ", ".join(a["name"] for a in xs)


def fix(lg, a_rid: int, a_gives: list, b_rid: int, b_gives: list, limit: int = 4) -> dict:
    S = _Scorer(lg, a_rid, b_rid)
    me, them = S.me, S.them
    cur = S.score(a_gives, b_gives)
    if S.works(cur):
        return {"status": "works", "current": _brief(cur), "options": []}
    give_ids = {a["id"] for a in a_gives}
    get_ids = {a["id"] for a in b_gives}
    mv = min(300, lg.cfg["suggestion_min_value"])
    theirs = sorted((a for a in them["players"] + them["picks"] if a["id"] not in get_ids and a["value"] >= mv),
                    key=lambda a: -(S.vals(a)[1] - S.vals(a)[2]))[:POOL]
    mine = sorted((a for a in me["players"] + me["picks"] if a["id"] not in give_ids and a["value"] >= mv),
                  key=lambda a: -(S.vals(a)[2] - S.vals(a)[1]))[:POOL]

    moves = []  # (label, give, get)
    for a in theirs:
        moves.append((f"Also ask for {a['name']}", a_gives, b_gives + [a]))
    for x, y in combinations(theirs[:8], 2):
        moves.append((f"Also ask for {x['name']} and {y['name']}", a_gives, b_gives + [x, y]))
    if len(a_gives) > 1:
        for a in a_gives:
            moves.append((f"Keep {a['name']}", [x for x in a_gives if x is not a], b_gives))
            for b in theirs:
                moves.append((f"Keep {a['name']}, ask for {b['name']}", [x for x in a_gives if x is not a], b_gives + [b]))
    for a in a_gives:  # swap one of mine for something they value more (or I value less)
        for b in mine:
            moves.append((f"Give {b['name']} instead of {a['name']}", [x for x in a_gives if x is not a] + [b], b_gives))
    if cur["gain_pct"] >= GOAL_GAIN:  # good for me, but they'd likely refuse: sweeten it
        for b in mine:
            moves.append((f"Add {b['name']}", a_gives + [b], b_gives))
        if len(b_gives) > 1:
            for a in b_gives:
                moves.append((f"Don't ask for {a['name']}", a_gives, [x for x in b_gives if x is not a]))

    size = max(cur["mkt_give"], cur["mkt_get"], 1)
    ok = []
    for label, give, get in moves:
        if not give or not get:
            continue
        s = S.score(give, get)
        if S.works(s):
            change = abs(s["mkt_give"] - cur["mkt_give"]) + abs(s["mkt_get"] - cur["mkt_get"])
            ok.append((change / size, -s["gain"] * s["acc"], label, give, get, s))
    ok.sort(key=lambda x: (x[0], x[1]))
    options, seen = [], set()
    for _, _, label, give, get, s in ok:
        key = (frozenset(a["id"] for a in give), frozenset(a["id"] for a in get))
        if key in seen:
            continue
        seen.add(key)
        options.append({"label": label, "a_gives": give, "b_gives": get, **_brief(s)})
        if len(options) >= limit:
            break
    why = []
    if cur["gain_pct"] < GOAL_GAIN:
        why.append(f"For {me['manager']} it's a {cur['gain_pct'] * 100:+.0f}% gain in team-context value (the goal is +{GOAL_GAIN * 100:.0f}% or better).")
    if cur["acc"] < GOAL_ACC:
        why.append(f"{them['manager']} would accept about {cur['acc']:.0f}% of the time (the goal is {GOAL_ACC}+).")
    return {"status": "fixes" if options else "none", "current": _brief(cur), "why": why, "options": options}


def best_returns(lg, me_rid: int, give: list, them_rid: int, limit: int = 2, max_n: int = 3) -> list[dict]:
    """Packages of `them_rid`'s assets for `give` that work for both sides, best for me first."""
    S = _Scorer(lg, me_rid, them_rid)
    mv = min(300, lg.cfg["suggestion_min_value"])
    mkt_give = package_value([a["value"] for a in give], S.p)
    pool = sorted((a for a in S.them["players"] + S.them["picks"] if mv <= a["value"] <= 1.3 * mkt_give),
                  key=lambda a: -(S.vals(a)[1] - S.vals(a)[2]) / (a["value"] or 1))[:POOL]
    cands = []
    for n in range(1, max_n + 1):
        for get in combinations(pool, n):
            s = S.score(give, list(get))
            if S.works(s):
                cands.append((s["gain"] * s["acc"] / 100, list(get), s))
    cands.sort(key=lambda c: -c[0])
    out, used = [], set()
    for _, get, s in cands:
        top = max(get, key=lambda a: a["value"])["id"]
        if top in used:  # different centerpieces, not variants of one
            continue
        used.add(top)
        out.append({"get": get, **_brief(s)})
        if len(out) >= limit:
            break
    return out
