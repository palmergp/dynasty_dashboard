"""Draft pick values and odds from where each pick is likely to land.

The value sources price picks as early/mid/late in each round. Each tier's value is placed
at the middle of its slots (1.02-1.03 for an early 1st in a 12-team league) and
interpolated between, which gives a market price for every slot (1.01 a bit above the
early-1st price, 1.04 a bit below).

- Next year's picks: the season simulation gives the chance that the original team ends up
  in each draft position. A pick's value is the market price at each slot weighted by those
  chances, so a near-certain 1.01 is worth more than a generic early 1st, and a pick that
  could land anywhere from 1.03 to 1.08 is priced across that whole range.
- Later picks keep the market's generic value (that's how other managers price them), but
  get a projected range from the rebuild timeline: the team's projected lineup rank in the
  season before that draft, spread wide (and wider each year out) because it's a guess.

Every pick also gets odds from the rookie hit-rate history (rookies.py): the chance a pick
at those slots becomes a starter or a bust, and how much of their draft-day value the
players taken there still had three years later. That last one compares the market with
itself: above 100% means the market has underpriced picks at those slots (worth buying),
below means overpriced (worth selling before the draft). It's a signal, not part of the
trade value, which stays at the market price other managers will pay.
"""
from __future__ import annotations

import math

from . import sleeper

ROUND_NAMES = {1: "1st", 2: "2nd", 3: "3rd"}
FUTURE_UNIFORM = 0.25   # share of a projected range spread evenly over every slot


def snake(lg) -> bool:
    last = next((d for d in reversed(sleeper.cached_drafts(lg.cfg["league_id"])) if d.get("type")), {})
    return last.get("type") == "snake"


def slot_in_round(rnd: int, position: int, n: int, is_snake: bool) -> int:
    """Pick number within the round for the team at draft-order `position` (1 = first)."""
    return n + 1 - position if is_snake and rnd % 2 == 0 else position


def tier_of(slot: int, n: int) -> str:
    return "early" if slot <= n / 3 else "mid" if slot <= 2 * n / 3 else "late"


def label(rnd: int, slot: int) -> str:
    return f"{rnd}.{slot:02d}"


def market_curve(lg, season: int) -> tuple[list[float], list[float]]:
    """(value, market) for every overall slot 1..teams x rounds, interpolated from the
    early/mid/late tier prices (value includes pick multipliers from Settings)."""
    n, rounds = len(lg.teams), lg.draft_rounds
    third = n / 3
    centers = {"early": (1 + third) / 2, "mid": (third + 1 + 2 * third) / 2, "late": (2 * third + 1 + n) / 2}
    pts_v, pts_m = [], []
    for r in range(1, rounds + 1):
        for t in ("early", "mid", "late"):
            v = lg.values.pick(season, r, t)
            x = (r - 1) * n + centers[t]
            pts_v.append((x, v["value"]))
            pts_m.append((x, v["market"]))

    def interp(pts):
        out = []
        for s in range(1, n * rounds + 1):
            if s <= pts[0][0]:
                (x0, y0), (x1, y1) = pts[0], pts[1]
            elif s >= pts[-1][0]:
                (x0, y0), (x1, y1) = pts[-2], pts[-1]
            else:
                i = next(i for i in range(len(pts) - 1) if pts[i][0] <= s <= pts[i + 1][0])
                (x0, y0), (x1, y1) = pts[i], pts[i + 1]
            y = y0 + (y1 - y0) * (s - x0) / ((x1 - x0) or 1)
            out.append(max(y, 0.6 * pts[-1][1]))
        return out
    return interp(pts_v), interp(pts_m)


def future_dist(rank: int, n: int, years_out: int) -> list[float]:
    """Chance of each draft position (1 = first) for a team projected to finish `rank`
    (1 = best): worst teams pick first, spread wider the further out it is."""
    center = n + 1 - rank
    sd = 2.0 + 1.0 * max(0, years_out - 1)
    w = [math.exp(-((p - center) / sd) ** 2 / 2) for p in range(1, n + 1)]
    tot = sum(w)
    return [(1 - FUTURE_UNIFORM) * x / tot + FUTURE_UNIFORM / n for x in w]


def _range(probs: list[float]) -> tuple[int, int]:
    """10th-90th percentile of a distribution over positions 1..n."""
    cum, lo, hi = 0.0, None, None
    for i, p in enumerate(probs):
        cum += p
        if lo is None and cum >= 0.1:
            lo = i + 1
        if hi is None and cum >= 0.9:
            hi = i + 1
    return lo or 1, hi or len(probs)


class Projector:
    """Values and odds for one league's picks (built once per League build)."""

    def __init__(self, lg, sim: dict | None, rookies: dict | None):
        self.lg, self.n, self.snake = lg, len(lg.teams), snake(lg)
        self.sim_season = sim["draft_season"] if sim else None
        self.probs = {t["roster_id"]: t["slot_probs"] for t in sim["teams"]} if sim else {}
        self.curves = (rookies or {}).get("curves")
        self.classes = (rookies or {}).get("complete_classes") or []
        self._mc = {}

    def curve(self, season):
        if season not in self._mc:
            self._mc[season] = market_curve(self.lg, season)
        return self._mc[season]

    def project(self, season: int, rnd: int, positions: list[float]) -> dict:
        """Value, market, likely slots and history odds for a pick of round `rnd` whose team
        lands at each draft position with the given chances."""
        n = self.n
        val, mkt = self.curve(season)
        overall = [(rnd - 1) * n + slot_in_round(rnd, p + 1, n, self.snake) for p in range(n)]
        out = {"value": sum(w * val[o - 1] for w, o in zip(positions, overall)),
               "market": sum(w * mkt[o - 1] for w, o in zip(positions, overall))}
        lo, hi = _range(positions)
        slots = sorted({slot_in_round(rnd, lo, n, self.snake), slot_in_round(rnd, hi, n, self.snake)})
        exp_pos = sum((i + 1) * w for i, w in enumerate(positions))
        out["slot_range"] = [label(rnd, slots[0]), label(rnd, slots[-1])]
        out["exp_slot"] = slot_in_round(rnd, round(exp_pos), n, self.snake)
        out["tier"] = tier_of(out["exp_slot"], n)
        c = self.curves
        if c and overall[-1] <= len(c["hit"]):
            out["hit"] = round(sum(w * c["hit"][o - 1] for w, o in zip(positions, overall)))
            out["bust"] = round(sum(w * c["bust"][o - 1] for w, o in zip(positions, overall)))
            out["later"] = round(sum(w * c["later"][o - 1] for w, o in zip(positions, overall)))
            day = sum(w * c["draft_day"][o - 1] for w, o in zip(positions, overall))
            out["kept"] = round(out["later"] / day * 100) if day else None
        return out

    def next_draft(self, season: int, rnd: int, orig: int) -> dict | None:
        p = self.probs.get(orig)
        if season != self.sim_season or not p:
            return None
        return self.project(season, rnd, p)

    def notes(self, info: dict, how: str) -> list[str]:
        a, b = info["slot_range"]
        where = f"Likely {a}" if a == b else f"Likely {a}–{b}"
        out = [f"{where} ({how})."]
        if info.get("hit") is not None:
            cls = f"{self.classes[0]}–{self.classes[-1]} rookie classes" if self.classes else "past rookie classes"
            out.append(f"Picks there have become starters {info['hit']}% of the time and busted {info['bust']}% ({cls}).")
            if info.get("kept") is not None:
                k = info["kept"]
                verdict = ("the market has underpriced picks there: worth buying" if k >= 115 else
                           "the market has overpriced picks there: worth selling before the draft" if k <= 85 else
                           "priced about right")
                out.append(f"Players taken there kept {k}% of their draft-day value three years later, so {verdict}.")
        return out


def annotate_future(lg, proj: Projector) -> None:
    """Projected range, odds and notes for picks beyond next year's draft (values unchanged)."""
    from . import future
    tl = future.analyze(lg)
    rank = {t["roster_id"]: t["rank"] for t in tl["teams"]}
    for t in lg.teams.values():
        for pk in t["picks"]:
            if pk.get("slot_range") or pk["season"] <= (proj.sim_season or lg.pick_seasons[0]):
                continue
            y = min(pk["season"] - 1 - lg.season, len(tl["years"]) - 1)
            r = rank.get(pk["orig_roster_id"])
            if not r or y < 1:
                continue
            info = proj.project(pk["season"], pk["round"], future_dist(r[y], proj.n, y))
            pk.update({k: info[k] for k in ("slot_range", "hit", "bust", "later", "kept") if k in info}, projected=True)
            pk["notes"] = proj.notes(info, f"a rough projection: {lg.teams[pk['orig_roster_id']]['manager']} is projected #{r[y]} of {proj.n} in {tl['years'][y]}")
