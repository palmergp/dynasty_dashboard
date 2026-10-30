"""When in the year players are worth the most: dynasty value by calendar month, by
position and age group.

From DynastyProcess's weekly value history: each player's monthly average value is divided
by his centered 13-month average (half weight on the two end months), which removes his
long-run trend (aging, a breakout) and leaves the seasonal part. Averaged over players
worth 1,500+ in each position and age group, that gives a typical value by month (100 =
his normal level that year). A player's best month to sell is the high point of his group's
curve over the next 8 months.
"""
from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MIN_VALUE = 1500
AHEAD = 8
MIN_MOVE = 5.0   # % change worth mentioning (smaller swings are within the noise)
BANDS = {  # (young up to, prime up to) by position; older = veteran
    "QB": (25, 30), "RB": (23, 25), "WR": (24, 27), "TE": (25, 28),
}


def band(pos: str, age: float | None) -> str | None:
    if pos not in BANDS or age is None:
        return None
    y, p = BANDS[pos]
    return "young" if age < y + 1 else "prime" if age < p + 1 else "vet"


def band_label(pos: str, b: str) -> str:
    y, p = BANDS[pos]
    return {"young": f"{y} and under", "prime": f"{y + 1}–{p}", "vet": f"{p + 1}+"}[b]


def group_name(pos: str, b: str) -> str:
    return f"{pos}s aged {band_label(pos, b)}"


def analyze(lg) -> dict:
    hist = lg.aging["hist"]
    dates, hv = hist["dates"], hist["values"]
    if not dates:
        return {"groups": [], "month": None}
    months = sorted({d[:7] for d in dates})
    idx = {m: i for i, m in enumerate(months)}
    ratios = defaultdict(lambda: defaultdict(list))  # (pos, band) -> calendar month -> ratios
    for pid, series in hv.items():
        p = lg.players_db.get(pid) or {}
        pos, birth = p.get("position"), p.get("birth_date")
        if pos not in BANDS or not birth:
            continue
        sums = defaultdict(list)
        for d, v in zip(dates, series):
            if v is not None:
                sums[d[:7]].append(v)
        mv = [statistics.mean(sums[m]) if sums.get(m) else None for m in months]
        for i in range(6, len(months) - 6):
            win = mv[i - 6:i + 7]
            if any(v is None for v in win):
                continue
            ma = (0.5 * win[0] + sum(win[1:12]) + 0.5 * win[12]) / 12
            if ma < MIN_VALUE:
                continue
            day = dt.date.fromisoformat(months[i] + "-15")
            age = (day - dt.date.fromisoformat(birth)).days / 365.25
            b = band(pos, age)
            ratios[(pos, b)][int(months[i][5:]) - 1].append(min(1.6, max(0.6, mv[i] / ma)))
    groups = []
    for pos in BANDS:
        for b in ("young", "prime", "vet"):
            r = ratios.get((pos, b))
            if not r:
                continue
            vals = [statistics.mean(r[m]) * 100 if len(r[m]) >= 15 else None for m in range(12)]
            if sum(v is not None for v in vals) < 10:
                continue
            groups.append({"pos": pos, "band": b, "label": f"{pos} {band_label(pos, b)}", "index": [round(v, 1) if v else None for v in vals],
                           "n": sum(len(x) for x in r.values()),
                           "high": MONTHS[max((m for m in range(12) if vals[m]), key=lambda m: vals[m])],
                           "low": MONTHS[min((m for m in range(12) if vals[m]), key=lambda m: vals[m])]})
    return {"groups": groups, "month": dt.date.today().month - 1, "months": MONTHS,
            "since": dates[0], "until": dates[-1], "min_value": MIN_VALUE}


def outlook(S: dict, pos: str, age: float | None, month: int | None = None) -> dict | None:
    """Best and worst month over the next AHEAD months for a player's group, vs. now."""
    b = band(pos, age)
    g = next((x for x in S.get("groups", []) if x["pos"] == pos and x["band"] == b), None)
    if not g:
        return None
    m0 = S["month"] if month is None else month
    now = g["index"][m0]
    ahead = [((m0 + k) % 12, g["index"][(m0 + k) % 12]) for k in range(1, AHEAD + 1) if g["index"][(m0 + k) % 12]]
    if not now or not ahead:
        return None
    best = max(ahead, key=lambda x: x[1])
    worst = min(ahead, key=lambda x: x[1])
    return {"group": group_name(pos, b), "now": now, "best": MONTHS[best[0]], "best_pct": round((best[1] / now - 1) * 100, 1),
            "worst": MONTHS[worst[0]], "worst_pct": round((worst[1] / now - 1) * 100, 1), "index": g["index"]}


def note(o: dict | None) -> str | None:
    """Player-note line when the calendar matters for him (a move of MIN_MOVE% or more)."""
    if not o:
        return None
    if o["best_pct"] >= MIN_MOVE:
        return f"Calendar: {o['group']}s are usually worth most around {o['best']}, about {o['best_pct']:+.0f}% vs. now."
    if o["worst_pct"] <= -MIN_MOVE:
        return f"Calendar: {o['group']}s usually lose value from here (about {o['worst_pct']:+.0f}% by {o['worst']}), so now is a good time to sell."
    return None
