"""Which trade calculator each manager seems to trust, from their past trades.

Managers judge offers with a calculator, and the calculators disagree. A manager who trusts
KeepTradeCut accepts deals that look fine on KTC, so across their trades KTC should make
their side look better than DynastyProcess does (and vice versa). For every completed
trade, each side is valued on the trade date in each calculator's own numbers:

- KeepTradeCut: its daily value history from each player's KTC page.
- DynastyProcess: its weekly value history (values-players.csv commits).
- Rookie picks: DynastyProcess's pick ranking that week, converted into each calculator's
  numbers at the same rank, so picks don't favor either side.
- FantasyCalc publishes no history, so it can't be checked.

Lean = the average of (side's gain on KTC − gain on DP) over a manager's trades. It counts
when there are at least MIN_TRADES trades and it's at least 1.5 standard errors from zero.
Leaning managers' acceptance odds then use their calculator for the "market" half of how
they see a deal (trade.market_view).
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from . import history, pickhistory, tendencies
from .cache import cached
from .tendencies import package_value
from .values import _dp_ids, _http, _name_index, name_key

SOURCES = ("ktc", "dynastyprocess")
MIN_TRADES = 4
MAX_MISSING = 0.15     # skip trades where players without KTC history carry more of the value
LEAN = {2.0: 0.5, 1.5: 0.3}   # |t| threshold -> how much of their market view uses their calculator


# ---------------------------------------------------------------- KTC history
def _ktc_index() -> dict:
    """sleeper_id -> KTC page slug, for players KTC currently ranks."""
    def fetch():
        html = _http.get("https://keeptradecut.com/dynasty-rankings").text
        m = re.search(r'<script[^>]*id="ktc-players"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            raise RuntimeError("KTC page layout changed: ktc-players block not found")
        return [{"slug": p["slug"], "ktc_id": str(p["playerID"]), "name": p["playerName"], "pos": p["position"]}
                for p in json.loads(m.group(1)) if p.get("position") != "RDP"]
    rows = cached("ktc:index", 3 * 24 * 3600, fetch)
    by_ktc = {r["ktc_id"]: r["sleeper_id"] for r in _dp_ids() if r.get("ktc_id") not in (None, "", "NA")}
    return rows, by_ktc


def _ktc_series(slug: str, superflex: bool, need: str) -> list:
    """[[iso date, value], ...] from a KTC player page, fetched again only when the cached
    copy ends before `need` (the latest trade it's needed for)."""
    block = "pd-superflex" if superflex else "pd-oneqb"
    key = f"ktc:hist:{slug}:{block}"

    def fetch():
        t = _http.get(f"https://keeptradecut.com/dynasty-rankings/players/{slug}").text
        m = re.search(rf'<script[^>]*id="{block}"[^>]*>(.*?)</script>', t, re.S)
        rows = (json.loads(m.group(1)).get("overallValue") or []) if m else []
        return [[f"20{r['d'][:2]}-{r['d'][2:4]}-{r['d'][4:6]}", r["v"]] for r in rows if r.get("v") is not None]
    data = cached(key, None, fetch)
    if data and data[-1][0] < need and need < dt.date.today().isoformat():
        data = cached(key, None, fetch, force=True)
    return data


def _at(series: list, day: str) -> float | None:
    """Value on the last date on/before `day`, else the first one after (new rookies)."""
    best = None
    for d, v in series:
        if d <= day:
            best = v
        else:
            return best if best is not None else v
    return best


def _inverse(f, hi: float = 30000.0):
    """Inverse of a monotone raw -> consensus mapper, by bisection."""
    def g(target: float) -> float:
        lo, h = 0.0, hi
        for _ in range(40):
            mid = (lo + h) / 2
            if f(mid) < target:
                lo = mid
            else:
                h = mid
        return (lo + h) / 2
    return g


# ---------------------------------------------------------------- analysis
def _sides(lg) -> list[dict]:
    """Trade sides with sent/received valued in each calculator's numbers on the trade day."""
    if not lg.trades:
        return []
    days = {tx["transaction_id"]: dt.datetime.fromtimestamp((tx.get("status_updated") or tx.get("created") or 0) / 1000).date().isoformat()
            for tx in lg.trades}
    first = min(days.values())
    dp = history.value_history(lg, dt.date.fromisoformat(first) - dt.timedelta(days=14), raw=True)
    dp_dates, dp_vals = dp["dates"], dp["values"]
    try:
        H = pickhistory.pick_history(lg)
    except Exception:
        H = None
    mappers = lg.values.mappers
    inv = {s: _inverse(mappers[s]) for s in SOURCES if s in mappers}

    # Every player traded, with the latest day we need his KTC value for.
    need = {}
    for tx in lg.trades:
        ms = tx.get("status_updated") or tx.get("created") or 0
        for pid in tx.get("adds") or {}:
            a = tendencies._hist_asset(lg, "player", pid, ms)
            need[a["id"]] = max(need.get(a["id"], ""), days[tx["transaction_id"]])
        for d in tx.get("draft_picks") or []:
            a = tendencies._hist_asset(lg, "pick", d, ms)
            if a["kind"] == "player":  # startup pick = the player taken
                need[a["id"]] = max(need.get(a["id"], ""), days[tx["transaction_id"]])
    rows, by_ktc = _ktc_index()
    idx = _name_index(lg.players_db)
    slug = {}
    for r in rows:
        sid = by_ktc.get(r["ktc_id"]) or idx.get((name_key(r["name"]), r["pos"]))
        if sid and sid in need:
            slug[sid] = r["slug"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        series = dict(zip(slug, pool.map(lambda sid: _ktc_series(slug[sid], lg.superflex, need[sid]), slug)))

    from .drafts import _value_at

    def value(a, day) -> dict:
        """{source: value or None} for one asset on one day."""
        if a["kind"] == "player":
            s = series.get(a["id"])
            v_dp = _value_at(dp_vals[a["id"]], dp_dates, day) if a["id"] in dp_vals else None
            return {"ktc": _at(s, day) if s else None, "dynastyprocess": v_dp}
        v = pickhistory.value_at(lg, H, day, a["season"], a["round"]) if H else None
        if v is None:
            v = lg.values.pick(max(a["season"], lg.pick_seasons[0]), a["round"])["market"]
        return {s: inv[s](v) if s in inv else None for s in SOURCES}

    p = lg.cfg["consolidation_exponent"]
    names = tendencies._manager_names(lg)
    out = []
    for tx in lg.trades:
        ms = tx.get("status_updated") or tx.get("created") or 0
        day = days[tx["transaction_id"]]
        by = {rid: {"sent": [], "recv": []} for rid in tx.get("roster_ids") or []}
        for pid, to in (tx.get("adds") or {}).items():
            a = tendencies._hist_asset(lg, "player", pid, ms)
            a["v"] = value(a, day)
            frm = (tx.get("drops") or {}).get(pid)
            if to in by:
                by[to]["recv"].append(a)
            if frm in by:
                by[frm]["sent"].append(a)
        for d in tx.get("draft_picks") or []:
            a = tendencies._hist_asset(lg, "pick", d, ms)
            a["v"] = value(a, day)
            if d["owner_id"] in by:
                by[d["owner_id"]]["recv"].append(a)
            if d["previous_owner_id"] in by:
                by[d["previous_owner_id"]]["sent"].append(a)
        assets = [a for s in by.values() for a in s["sent"]]
        total = sum(a["v"]["dynastyprocess"] or 0 for a in assets) or 1
        missing = sum(a["v"]["dynastyprocess"] or 0 for a in assets if a["v"]["ktc"] is None)
        if missing / total > MAX_MISSING:
            continue
        for rid, s in by.items():
            g = {}
            for src in SOURCES:
                recv = package_value([a["v"][src] or 0 for a in s["recv"]], p)
                sent = package_value([a["v"][src] or 0 for a in s["sent"]], p)
                g[src] = (recv - sent) / (max(recv, sent) or 1)
            if not s["recv"] or not s["sent"]:
                continue
            uid = tx["roster_owner"].get(str(rid))
            out.append({"tx": tx["transaction_id"], "date": day, "user_id": uid, "manager": names.get(uid, f"Team {rid}"),
                        "recv": [_brief(a) for a in s["recv"]], "sent": [_brief(a) for a in s["sent"]],
                        "gain": {k: round(v * 100, 1) for k, v in g.items()}, "diff": g["ktc"] - g["dynastyprocess"]})
    return out


def _brief(a):
    return {"name": a["name"], **{s: round(a["v"][s]) if a["v"][s] is not None else None for s in SOURCES}}


def _verdict(diffs: list[float]) -> dict:
    n = len(diffs)
    mean = statistics.mean(diffs) if diffs else 0.0
    se = statistics.stdev(diffs) / math.sqrt(n) if n >= 2 else None
    t = mean / se if se else 0.0
    lean, strength = None, 0.0
    if n >= MIN_TRADES:
        for cut, lam in sorted(LEAN.items(), reverse=True):
            if abs(t) >= cut:
                lean, strength = ("ktc" if mean > 0 else "dynastyprocess"), lam
                break
    return {"n": n, "diff_pct": round(mean * 100, 1), "t": round(t, 2), "lean": lean, "strength": strength}


def analyze(lg) -> dict:
    sides = _sides(lg)
    by_user = defaultdict(list)
    for s in sides:
        by_user[s["user_id"]].append(s)
    managers = []
    for t in lg.teams.values():
        rows = by_user.get(t["owner_id"], [])
        v = _verdict([r["diff"] for r in rows])
        managers.append({"roster_id": t["roster_id"], "user_id": t["owner_id"], "manager": t["manager"],
                         "is_me": bool(lg.me and t is lg.me), **v,
                         "avg_gain": {s: round(statistics.mean(r["gain"][s] for r in rows), 1) if rows else None for s in SOURCES},
                         "trades": [{k: r[k] for k in ("date", "recv", "sent", "gain")} for r in sorted(rows, key=lambda r: r["date"], reverse=True)]})
    managers.sort(key=lambda m: (m["lean"] is None, -abs(m["t"])))
    # League-wide: which calculator makes completed trades look closer to even.
    trades = defaultdict(list)
    for s in sides:
        trades[s["tx"]].append(s)
    closer = {"ktc": 0, "dynastyprocess": 0}
    gaps = {src: [] for src in SOURCES}
    for ss in trades.values():
        imb = {src: max(abs(s["gain"][src]) for s in ss) for src in SOURCES}
        for src in SOURCES:
            gaps[src].append(imb[src])
        if imb["ktc"] != imb["dynastyprocess"]:
            closer[min(imb, key=imb.get)] += 1
    return {"sources": list(SOURCES), "trades": len(trades), "sides": len(sides),
            "median_gap": {s: round(statistics.median(v), 1) if v else None for s, v in gaps.items()},
            "closer": closer, "managers": managers, "min_trades": MIN_TRADES}


def leans(lg) -> dict:
    """user_id -> {"source", "strength"} for managers with a clear lean (cached per build)."""
    out = getattr(lg, "_calc_leans", None)
    if out is None:
        out = {m["user_id"]: {"source": m["lean"], "strength": m["strength"], "n": m["n"], "diff_pct": m["diff_pct"]}
               for m in lg.calcfit["managers"] if m["lean"]}
        lg._calc_leans = out
    return out


def gaps(lg, them: dict, mine: list, theirs: list, limit: int = 3) -> dict | None:
    """For a manager with a calculator lean: my assets their calculator rates above the
    consensus (offer these) and theirs it rates below (ask for these)."""
    lean = (tendencies_calc(lg, them) or {}).get("source")
    if not lean:
        return None

    def ratio(a):
        v = a["sources"].get(lean)
        return v / a["value"] if v and a["value"] >= 1000 else None
    offer = sorted((a for a in mine if (ratio(a) or 0) >= 1.10), key=lambda a: -ratio(a))[:limit]
    ask = sorted((a for a in theirs if 0 < (ratio(a) or 9) <= 0.90), key=lambda a: ratio(a))[:limit]
    return {"source": lean, "offer": [{"name": a["name"], "pct": round((ratio(a) - 1) * 100)} for a in offer],
            "ask": [{"name": a["name"], "pct": round((ratio(a) - 1) * 100)} for a in ask]}


def tendencies_calc(lg, team: dict) -> dict | None:
    return (lg.tendencies.get(team["owner_id"]) or {}).get("calc")
