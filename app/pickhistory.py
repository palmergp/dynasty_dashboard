"""Rookie-pick values over time, and when in the year picks are worth the most.

DynastyProcess commits values-picks.csv to GitHub about weekly (back to February 2021).
It ranks picks among players (ECR: "this pick is worth about the 40th-best player")
rather than giving them values, so each rank is turned into a value with today's
rank -> value curve fit on players. Because the rank is *among players*, a pick's value
here is what it would buy in players at that moment, which is the right yardstick for
"when should I sell it".

Row names: "2027 1st", "2027 Early 1st" (generic, until the class's order is known) and
"2026 Pick 1.01" (exact slots, from around the end of the previous season until the
draft). DP leaves a class's slot rows in the file after its draft, so rows for class Y
are ignored after May of year Y. Some snapshots are off-scale (most Februaries, the
pick ranks briefly jump to roughly half their usual numbers and then return). A snapshot
where any class's 2nd- or 3rd-round rank is more than 25% away from the median of the
surrounding snapshots is dropped entirely; the glitch is obvious there, and it affects
the other rounds by less but in the same snapshots.

Seasonality: for each finished class, its round value by calendar month from June of the
year before its draft through April, divided by that class's own average over those
months. Averaging those across classes gives the typical shape of a pick's value over its
last year.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import math
import re
import statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from . import history
from .cache import cached
from .values import _parse_pick, dp_ecr_curve

PATH = "files/values-picks.csv"
SINCE = "2021-01-01"
SLOT_RE = re.compile(r"(\d{4}) Pick (\d+)\.(\d+)$")
WINDOW = [6, 7, 8, 9, 10, 11, 12, 1, 2, 3, 4]  # June (year before the draft) .. April
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
GLITCH = 1.25  # max ratio between a rank and its neighbors' median
TRACKS = [(1, "early", "Early 1st"), (1, None, "1st"), (2, None, "2nd"), (3, None, "3rd")]


def _tier(slot: int) -> str:
    return "early" if slot <= 4 else "mid" if slot <= 8 else "late"


def _snapshot(sha: str, col: str) -> list:
    """[[season, round, tier|None, ecr], ...] for one commit. Exact-slot rows are averaged
    into their round (tier None) and into early/mid/late tiers."""
    def fetch():
        txt = history._http.get(f"https://raw.githubusercontent.com/{history.REPO}/{sha}/{PATH}").text
        generic, slots = {}, defaultdict(list)
        for r in csv.DictReader(io.StringIO(txt)):
            if r.get(col) in (None, "", "NA"):
                continue
            ecr = float(r[col])
            m = SLOT_RE.match(r["player"])
            if m:
                season, rnd, slot = int(m.group(1)), int(m.group(2)), int(m.group(3))
                slots[(season, rnd, None)].append(ecr)
                slots[(season, rnd, _tier(slot))].append(ecr)
                continue
            parsed = _parse_pick(r["player"])
            if parsed:
                generic[parsed] = ecr
        for k, v in slots.items():
            generic.setdefault(k, statistics.mean(v))
        return [[s, r, t, e] for (s, r, t), e in generic.items()]
    return cached(f"dp:picks:{sha}:{col}", None, fetch)


_memo: dict = {}


def pick_history(lg) -> dict:
    """{"dates": [...], "ecr": {(season, round, tier): [ecr|None per date]}, "curve": (a, b)}."""
    col = "ecr_2qb" if lg.superflex else "ecr_1qb"
    commits = history._commits(SINCE, PATH)
    key = (col, commits[-1]["sha"] if commits else None)
    if key in _memo:
        return _memo[key]
    with ThreadPoolExecutor(max_workers=8) as pool:
        snaps = list(pool.map(lambda c: _snapshot(c["sha"], col), commits))
    dates = [c["date"] for c in commits]
    ecr: dict[tuple, list] = {}
    for i, (day, snap) in enumerate(zip(dates, snaps)):
        for season, rnd, tier, e in snap:
            if day > f"{season}-05-31":  # stale rows left in the file after that class's draft
                continue
            ecr.setdefault((season, rnd, tier), [None] * len(dates))[i] = e
    bad = {i for (s, r, t), row in ecr.items() if r in (2, 3) and t is None for i in _glitches(row)}
    for row in ecr.values():
        for i in bad:
            row[i] = None
    out = {"dates": dates, "ecr": ecr, "curve": dp_ecr_curve(lg.superflex)}
    _memo.clear()
    _memo[key] = out
    return out


def _glitches(row: list, half: int = 6) -> list[int]:
    """Indexes of ranks far from the median of the ~6 snapshots on each side."""
    out = []
    for i, e in enumerate(row):
        if e is None:
            continue
        near = [x for x in row[max(0, i - half):i + half + 1] if x is not None]
        if len(near) >= 5 and not 1 / GLITCH <= e / statistics.median(near) <= GLITCH:
            out.append(i)
    return out


def to_value(lg, H: dict, e: float) -> float:
    """A DP pick rank -> value on the app's scale."""
    a, b = H["curve"]
    raw = math.exp(a + b * e)
    f = lg.values.mappers.get("dynastyprocess")
    return f(raw) if f else raw


def value_at(lg, H: dict, day: str, season: int, rnd: int, tier: str | None = None) -> float | None:
    """A pick's value as of `day` (the last snapshot on or before it). Picks further out
    than DP lists use its furthest class, 5% less per extra year. None once drafted."""
    dates = H["dates"]
    i = max((j for j, d in enumerate(dates) if d <= day), default=None)
    if i is None or day > f"{season}-05-31":
        return None
    listed = sorted({s for (s, r, t), v in H["ecr"].items() if r == rnd and t is None and v[i] is not None})
    if not listed:
        return None
    s = season if season in listed else max(listed) if season > max(listed) else None
    if s is None:
        return None
    row = H["ecr"].get((s, rnd, tier)) or H["ecr"].get((s, rnd, None))
    e = row[i] if row and row[i] is not None else H["ecr"][(s, rnd, None)][i]
    return to_value(lg, H, e) * 0.95 ** (season - s)


def _monthly(lg, H: dict, season: int, rnd: int, tier: str | None) -> dict:
    """(year, month) -> average value of one class/round over that month's snapshots."""
    row = H["ecr"].get((season, rnd, tier))
    if not row:
        return {}
    by = defaultdict(list)
    for d, e in zip(H["dates"], row):
        if e is not None:
            by[(int(d[:4]), int(d[5:7]))].append(to_value(lg, H, e))
    return {k: statistics.mean(v) for k, v in by.items()}


def _window_keys(season: int) -> list[tuple]:
    return [(season - 1 if m >= 6 else season, m) for m in WINDOW]


def seasonality(lg, today: dt.date | None = None) -> dict:
    """Typical value of next year's picks by month, relative to each class's own average,
    plus what that means from today until the draft."""
    today = today or dt.date.today()
    H = pick_history(lg)
    upcoming = today.year + 1 if today.month >= 6 else today.year  # the next rookie draft
    tracks = []
    for rnd, tier, label in TRACKS:
        per_class, current = {}, None
        for season in sorted({s for (s, r, t) in H["ecr"] if r == rnd and t == tier}):
            m = _monthly(lg, H, season, rnd, tier)
            keys = _window_keys(season)
            vals = [m.get(k) for k in keys]
            have = [v for v in vals if v is not None]
            if season == upcoming:
                current = {"season": season, "values": [round(v) if v else None for v in vals]}
                continue
            if season > upcoming or len(have) < 8:
                continue
            avg = statistics.mean(have)
            per_class[season] = [v / avg if v else None for v in vals]
        months = []
        for i, mo in enumerate(WINDOW):
            xs = [c[i] for c in per_class.values() if c[i] is not None]
            months.append({"month": mo, "label": MONTHS[mo - 1], "index": round(statistics.mean(xs), 4) if xs else None, "n": len(xs)})
        if current:  # this class so far, on the same scale (vs. the typical shape)
            seen = [(i, v) for i, v in enumerate(current["values"]) if v]
            if seen:
                base = statistics.mean(v / months[i]["index"] for i, v in seen if months[i]["index"])
                current["index"] = [round(v / base, 4) if v else None for v in current["values"]]
        tracks.append({"round": rnd, "tier": tier, "label": label, "classes": sorted(per_class),
                       "months": months, "current": current})

    # From this month to the draft: where the typical peak and trough are.
    now_m = today.month if today.month in WINDOW else (6 if today.month == 5 else None)
    ahead = WINDOW[WINDOW.index(now_m):] if now_m else WINDOW
    for t in tracks:
        idx = {m["month"]: m["index"] for m in t["months"] if m["index"]}
        if now_m not in idx or not ahead:
            t["outlook"] = None
            continue
        best = max(ahead, key=lambda m: idx.get(m, 0))
        worst = min(ahead, key=lambda m: idx.get(m, 9))
        t["outlook"] = {
            "now": MONTHS[now_m - 1], "best": MONTHS[best - 1], "best_pct": round((idx[best] / idx[now_m] - 1) * 100, 1),
            "worst": MONTHS[worst - 1], "worst_pct": round((idx[worst] / idx[now_m] - 1) * 100, 1),
            "draft_pct": round((idx[4] / idx[now_m] - 1) * 100, 1) if 4 in idx else None,
        }
    return {"upcoming": upcoming, "tracks": tracks, "since": H["dates"][0] if H["dates"] else None,
            "snapshots": len(H["dates"]), "month": MONTHS[today.month - 1]}
