"""Age curves from history: how a player's dynasty value changes over a year because of his
age, by position, and what that implies for his sell window.

For every player worth at least MIN_VALUE at a snapshot, we compare his value a year
later (every 4th week, so one player's season isn't counted 52 times). Raw changes are
mostly negative at every age: each rookie class pushes everyone down, and players chosen
for being valuable tend to drift back. So each change is divided by the median change of
players at the same position and value level, which leaves the part that's about age. The
median of that by position and age (rounded down) is the curve; thin ages borrow from
their neighbors. Players who fell off the rankings count at the floor value.
"""
from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

from . import history

MIN_VALUE = 800
MIN_N = 12
STEP = 4  # weeks between sampled starting points


def _age_on(birth: str | None, day: str) -> float | None:
    if not birth:
        return None
    try:
        return (dt.date.fromisoformat(day) - dt.date.fromisoformat(birth)).days / 365.25
    except ValueError:
        return None


def build(lg, years: int = 4) -> dict:
    """{"curve": {pos: {age: {"ratio", "n"}}}, "hist": value history used}."""
    hist = history.value_history(lg, dt.date(lg.season - years, 12, 1))
    dates, hv = hist["dates"], hist["values"]
    ds = [dt.date.fromisoformat(d) for d in dates]
    later = []  # index of the snapshot ~1 year after each snapshot
    k = 0
    for i, d in enumerate(ds):
        target = d + dt.timedelta(days=365)
        while k < len(ds) and ds[k] < target:
            k += 1
        later.append(k if k < len(ds) and (ds[k] - target).days <= 21 else None)
    samples = []  # (pos, age, band, ratio)
    band = lambda v: 0 if v < 2000 else 1 if v < 4000 else 2
    for pid, series in hv.items():
        p = lg.players_db.get(pid) or {}
        pos, birth = p.get("position"), p.get("birth_date")
        if pos not in ("QB", "RB", "WR", "TE") or not birth:
            continue
        for i in range(0, len(dates), STEP):
            j = later[i]
            v0 = series[i]
            if j is None or v0 is None or v0 < MIN_VALUE:
                continue
            v1 = series[j] if series[j] is not None else 0.0
            age = _age_on(birth, dates[i])
            if age is not None:
                samples.append((pos, int(age), band(v0), v1 / v0))
    drift = defaultdict(list)
    for pos, _, b, r in samples:
        drift[(pos, b)].append(r)
    drift = {k: statistics.median(v) for k, v in drift.items()}
    ratios = defaultdict(list)
    for pos, age, b, r in samples:
        ratios[(pos, age)].append(r / drift[(pos, b)])
    curve = {}
    for pos in ("QB", "RB", "WR", "TE"):
        ages = sorted(a for (p, a) in ratios if p == pos)
        if not ages:
            continue
        rows = {}
        for a in range(min(ages), max(ages) + 1):
            pool, width = list(ratios.get((pos, a), [])), 0
            while len(pool) < MIN_N and width < 3:  # borrow from neighboring ages
                width += 1
                pool += ratios.get((pos, a - width), []) + ratios.get((pos, a + width), [])
            if pool:
                rows[a] = {"ratio": round(statistics.median(pool), 3), "n": len(ratios.get((pos, a), []))}
        # Smooth across neighboring ages (weighted by sample size) so thin ages don't swing.
        smooth = {}
        for a, r in rows.items():
            near = [(rows[b]["ratio"], max(rows[b]["n"], 1) ** 0.5 * (2 if b == a else 1)) for b in (a - 1, a, a + 1) if b in rows]
            smooth[a] = {"ratio": round(max(0.5, min(1.4, sum(x * w for x, w in near) / sum(w for _, w in near))), 3), "n": r["n"]}
        curve[pos] = smooth
    return {"curve": curve, "hist": hist}


def ratio(curve: dict, pos: str, age: float | None) -> float | None:
    rows = curve.get(pos) or {}
    if age is None or not rows:
        return None
    a = int(age)
    a = min(max(a, min(rows)), max(rows))
    return rows.get(a, {}).get("ratio")


def outlook(curve: dict, pos: str, age: float | None, value: float, years: int = 3) -> dict | None:
    """Value vs. similar players over the next few years from the age curve, and a sell-timing
    verdict. A path of -30% means: worth 30% less, relative to players at his position and
    value level, than he is today."""
    if age is None or pos not in curve:
        return None
    path, v = [], value
    for y in range(1, years + 1):
        r = ratio(curve, pos, age + y - 1)
        if r is None:
            return None
        v *= r
        path.append({"years": y, "age": round(age + y, 1), "value": round(v), "change_pct": round((v / (value or 1) - 1) * 100, 1)})
    y1 = path[0]["change_pct"]
    y2 = path[1]["change_pct"] if len(path) > 1 else y1
    peer = f"other {pos}s at his value"
    if y1 <= -12:
        verdict, why = "sell", f"At his age, a {pos} typically loses about {abs(y1):.0f}% of his value over the next year compared with {peer}."
    elif y1 <= -6 or y2 <= -15:
        verdict, why = "soon", f"A {pos} his age typically loses about {abs(y1):.0f}% over the next year and {abs(y2):.0f}% over two, compared with {peer}."
    elif y1 >= 6:
        verdict, why = "rising", f"At his age, a {pos} typically gains about {y1:.0f}% over the next year compared with {peer}."
    else:
        verdict, why = "hold", f"At his age, a {pos} typically keeps roughly even with {peer} over the next year ({y1:+.0f}%)."
    return {"path": path, "verdict": verdict, "why": why, "y1_pct": y1}
