"""Model checks: how the sell-timing verdicts and the buy-low rule held up on past seasons,
using DynastyProcess's weekly value history.

Sell timing (out of sample): the age curve is refit using only outcomes known before the
test year, then each player's verdict at each test date (every 4 weeks over the last year
with a full year of results) is compared with what actually happened to his value over the
next year, relative to players at the same position and value level on the same date.
"Expected value" is checked the same way: actual value a year later ÷ the model's
expectation.

Buy low: at every 4th weekly snapshot, players down 15%+ from their 4-month high (high
800+, still worth 300+, younger than their position's sell age) are compared with all
players at the same position and value level 6 and 12 months later. Usage data isn't
available for past seasons, so the "role intact" filter can't be checked; this tests the
price dip alone.
"""
from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

from . import aging, buylow, history
from .league import SELL_AGE

YEARS_BACK = 6
STEP = 4
VERDICTS = ("rising", "hold", "soon", "sell")
DEPTHS = [(0.15, 0.25, "15–25% down"), (0.25, 0.40, "25–40% down"), (0.40, 1.01, "40%+ down")]


def _hist(lg) -> dict:
    h = getattr(lg, "_checks_hist", None)
    if h is None:
        h = lg._checks_hist = history.value_history(lg, dt.date(lg.season - YEARS_BACK, 12, 1))
    return h


def _summary(rel: list[float]) -> dict:
    if not rel:
        return {"n": 0}
    return {"n": len(rel), "median_pct": round((statistics.median(rel) - 1) * 100, 1),
            "beat_pct": round(sum(r > 1 for r in rel) / len(rel) * 100)}


def _relative(rows: list[dict]) -> None:
    """Add rel = ratio ÷ median ratio of all players at the same date, position and value band."""
    peers = defaultdict(list)
    for r in rows:
        peers[(r["i"], r["pos"], r["band"])].append(r["ratio"])
    med = {k: statistics.median(v) for k, v in peers.items() if len(v) >= 5}
    for r in rows:
        m = med.get((r["i"], r["pos"], r["band"]))
        r["rel"] = r["ratio"] / m if m else None


def sell_timing(lg) -> dict:
    hist = _hist(lg)
    dates, hv = hist["dates"], hist["values"]
    if len(dates) < 100:
        return {"ok": False}
    ds = [dt.date.fromisoformat(d) for d in dates]
    later = aging._later(ds, 365)
    last = max((i for i, j in enumerate(later) if j is not None), default=None)
    if last is None:
        return {"ok": False}
    test_from = (ds[last] - dt.timedelta(days=365)).isoformat()
    model = aging.fit(hist, lg.players_db, until=test_from)
    rows = []
    for pid, series in hv.items():
        p = lg.players_db.get(pid) or {}
        pos, birth = p.get("position"), p.get("birth_date")
        if pos not in SELL_AGE or not birth:
            continue
        for i in range(last, -1, -STEP):
            if dates[i] < test_from:
                break
            v0 = series[i]
            if v0 is None or v0 < aging.MIN_VALUE or later[i] is None:
                continue
            age = aging._age_on(birth, dates[i])
            o = aging.outlook(model["curve"], pos, age, v0, drift=model["drift"]) if age else None
            if not o:
                continue
            v1 = series[later[i]] or 0.0
            rows.append({"i": i, "pos": pos, "band": aging._band(v0), "ratio": v1 / v0, "verdict": o["verdict"],
                         "expected": o["path"][0].get("typical"), "v0": v0, "v1": v1})
    _relative(rows)
    by = {v: _summary([r["rel"] for r in rows if r["verdict"] == v and r["rel"] is not None]) for v in VERDICTS}
    exp = [r["v1"] / r["expected"] for r in rows if r.get("expected")]
    err = [abs(r["v1"] - r["expected"]) / r["v0"] for r in rows if r.get("expected")]
    return {"ok": True, "test_from": test_from, "test_to": dates[last], "train_until": test_from, "n": len(rows),
            "verdicts": by,
            "expected": {"n": len(exp), "median_ratio_pct": round(statistics.median(exp) * 100) if exp else None,
                         "mean_ratio_pct": round(statistics.mean(min(x, 3) for x in exp) * 100) if exp else None,
                         "median_error_pct": round(statistics.median(err) * 100) if err else None}}


def buy_low(lg) -> dict:
    hist = _hist(lg)
    dates, hv = hist["dates"], hist["values"]
    if len(dates) < 60:
        return {"ok": False}
    ds = [dt.date.fromisoformat(d) for d in dates]
    horizons = {"6 months": aging._later(ds, 182), "1 year": aging._later(ds, 365)}
    look = []  # first index inside each date's lookback window
    k = 0
    for d in ds:
        while ds[k] < d - dt.timedelta(days=buylow.LOOKBACK_DAYS):
            k += 1
        look.append(k)
    start = next((i for i, x in enumerate(look) if x > 0), len(dates))  # first date with a full 4-month window
    out = {}
    for label, later in horizons.items():
        rows = []
        for pid, series in hv.items():
            p = lg.players_db.get(pid) or {}
            pos, birth = p.get("position"), p.get("birth_date")
            if pos not in SELL_AGE or not birth:
                continue
            for i in range(start, len(dates), STEP):
                j = later[i]
                v0 = series[i]
                if j is None or v0 is None or v0 < 300:
                    continue
                window = [v for v in series[look[i]:i + 1] if v is not None]
                high = max(window)
                age = aging._age_on(birth, dates[i])
                drop = 1 - v0 / high if high else 0
                dipped = high >= buylow.MIN_HIGH and drop >= buylow.MIN_DROP and age is not None \
                    and age < min(SELL_AGE[pos], buylow.MAX_AGE)
                rows.append({"i": i, "pos": pos, "band": aging._band(v0), "ratio": (series[j] or 0.0) / v0,
                             "dipped": dipped, "drop": drop})
        _relative(rows)
        dip = [r for r in rows if r["dipped"] and r["rel"] is not None]
        out[label] = {"dipped": _summary([r["rel"] for r in dip]),
                      "depth": [{"label": name, **_summary([r["rel"] for r in dip if lo <= r["drop"] < hi])} for lo, hi, name in DEPTHS]}
    return {"ok": True, "since": dates[0], "until": dates[-1], "horizons": out}


def analyze(lg) -> dict:
    return {"sell_timing": sell_timing(lg), "buy_low": buy_low(lg)}
