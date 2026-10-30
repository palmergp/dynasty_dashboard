"""Age curves from history: how a player's dynasty value changes over a year because of his
age, by position, and what that implies for his sell window.

For every player worth at least MIN_VALUE at a snapshot, we compare his value a year
later (every 4th week, so one player's season isn't counted 52 times). Raw changes are
mostly negative at every age: each rookie class pushes everyone down, and players chosen
for being valuable tend to drift back. So each change is divided by the median change of
players at the same position and value level, which leaves the part that's about age. The
median of that by position and age (rounded down) is the curve; thin ages borrow from
their neighbors. Players who fell off the rankings count at the floor value.

For an expected value, the age effect is multiplied by the average raw change of players
at the same position and value level over 1, 2 and 3 years (every position loses value to
new rookie classes, so even a "hold" usually means a lower number later). That uses the
average, not the median: lower-value players split between fading to nothing and holding
on, and the median of that is whichever group happens to be bigger.
"""
from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

from . import history

MIN_VALUE = 800
MIN_N = 12
STEP = 4  # weeks between sampled starting points
HORIZONS = (1, 2, 3)  # years of raw change kept for the expected value
MAX_GAIN = 3.0         # cap on one player's ratio so a few breakouts don't set the average


def _band(v: float) -> int:
    return 0 if v < 2000 else 1 if v < 4000 else 2


def _age_on(birth: str | None, day: str) -> float | None:
    if not birth:
        return None
    try:
        return (dt.date.fromisoformat(day) - dt.date.fromisoformat(birth)).days / 365.25
    except ValueError:
        return None


def _later(ds: list, days: int) -> list:
    """Index of the snapshot ~`days` after each snapshot (None if there isn't one)."""
    out, k = [], 0
    for d in ds:
        target = d + dt.timedelta(days=days)
        while k < len(ds) and ds[k] < target:
            k += 1
        out.append(k if k < len(ds) and (ds[k] - target).days <= 21 else None)
    return out


def build(lg, years: int = 4) -> dict:
    """{"curve": {pos: {age: {"ratio", "n"}}}, "drift": {pos: {band: [average 1y, 2y, 3y ratio]}},
    "hist": value history used}."""
    hist = history.value_history(lg, dt.date(lg.season - years, 12, 1))
    return {**fit(hist, lg.players_db), "hist": hist}


def fit(hist: dict, players_db: dict, until: str | None = None) -> dict:
    """Curve and drift from a value history, using only outcomes dated on/before `until`
    (for out-of-sample checks)."""
    dates, hv = hist["dates"], hist["values"]
    until = until or (dates[-1] if dates else "")
    ds = [dt.date.fromisoformat(d) for d in dates]
    later = {y: _later(ds, 365 * y) for y in HORIZONS}
    samples = []  # (pos, age, band, ratio)
    raw = defaultdict(list)  # (pos, band, years) -> ratios
    for pid, series in hv.items():
        p = players_db.get(pid) or {}
        pos, birth = p.get("position"), p.get("birth_date")
        if pos not in ("QB", "RB", "WR", "TE") or not birth:
            continue
        for i in range(0, len(dates), STEP):
            v0 = series[i]
            if v0 is None or v0 < MIN_VALUE:
                continue
            for y in HORIZONS:
                j = later[y][i]
                if j is not None and dates[j] <= until:
                    raw[(pos, _band(v0), y)].append(min(MAX_GAIN, (series[j] or 0.0) / v0))
            j = later[1][i]
            if j is None or dates[j] > until:
                continue
            v1 = series[j] if series[j] is not None else 0.0
            age = _age_on(birth, dates[i])
            if age is not None:
                samples.append((pos, int(age), _band(v0), v1 / v0))
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
    by_pos = defaultdict(dict)
    for (pos, b) in drift:
        steps = [statistics.mean(raw[(pos, b, y)]) for y in HORIZONS if len(raw[(pos, b, y)]) >= MIN_N]
        by_pos[pos][b] = [round(r, 3) for r in steps]
    return {"curve": curve, "drift": dict(by_pos)}


def ratio(curve: dict, pos: str, age: float | None) -> float | None:
    rows = curve.get(pos) or {}
    if age is None or not rows:
        return None
    a = int(age)
    a = min(max(a, min(rows)), max(rows))
    return rows.get(a, {}).get("ratio")


def outlook(curve: dict, pos: str, age: float | None, value: float, years: int = 3, drift: dict | None = None) -> dict | None:
    """Value vs. similar players over the next few years from the age curve, and a sell-timing
    verdict. A path of -30% means: worth 30% less, relative to players at his position and
    value level, than he is today. With `drift`, each step also has an expected raw value
    ("typical", "typical_pct"): the age effect plus the average change of players at that
    position and value level."""
    if age is None or pos not in curve:
        return None
    path, v = [], value
    d = ((drift or {}).get(pos) or {}).get(_band(value)) or []
    for y in range(1, years + 1):
        r = ratio(curve, pos, age + y - 1)
        if r is None:
            return None
        v *= r
        step = {"years": y, "age": round(age + y, 1), "value": round(v), "change_pct": round((v / (value or 1) - 1) * 100, 1)}
        if y <= len(d):
            raw = v * d[y - 1]
            step.update(typical=round(raw), typical_pct=round((raw / (value or 1) - 1) * 100, 1))
        path.append(step)
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
        if y2 <= -8:
            why += f" After that he typically falls behind them ({y2:+.0f}% over two years)."
    return {"path": path, "verdict": verdict, "why": why, "y1_pct": y1, "y2_pct": y2}


LABELS = {"sell": "sell now", "soon": "sell within a year", "hold": "hold for now"}


def note(o: dict | None, pos: str, age: float | None) -> str | None:
    """Player-description line for the sell-timing verdict, or None when age isn't a concern."""
    if not o or age is None:
        return None
    if o["verdict"] in ("sell", "soon") or (o["verdict"] == "hold" and o["y2_pct"] <= -8):
        return f"Age {age:g} {pos}, {LABELS[o['verdict']]}: {o['why']}"
    return None
