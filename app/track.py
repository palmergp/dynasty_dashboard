"""Track record: how the app's own calls have turned out in this league.

The models were checked on past seasons (checks.py, secondhalf.py, opportunity.py) but not
on this league. This grades them as results come in:

- Start/sit: each completed week is replayed with that week's Sleeper projections. The
  app's lineup (most projected points from the players each team had that week; taxi
  players left out) is scored with what those players actually scored, next to the lineup
  the team started and the best possible one. Only QB/RB/WR/TE slots count.
- Second-half outlook: a snapshot is saved each week (data/leagues/<id>/track/). Once
  players have played 2+ games since, the outlook, their pace so far and Sleeper's
  projection are each compared with what they actually scored a game.
- Value calls: the snapshots also keep every rostered player's sell-timing verdict, the
  buy-low list and your sell candidates. After 4+ weeks, each player's value change is
  compared with players at the same position and value level in that snapshot (the same
  test as checks.py, but live and in this league).
- Trade suggestions: each one shown in Find trades is logged. Later: how the two sides'
  values moved since, and whether you traded with that manager afterwards.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import statistics
import threading
import time

from . import aging, buylow, checks, lineup, opportunity, recap, sleeper, store
from .league import SLOT_ELIGIBLE
from .secondhalf import MOVE

MIN_VALUE = 300        # players kept in a snapshot's value calls
H2_GAMES = 2           # games since a snapshot before its outlook is graded
VALUE_DAYS = 28        # days before a snapshot's value calls are graded
LOG_MAX = 2000         # suggestion log entries kept
VERDICTS = ("rising", "hold", "soon", "sell")
_lock = threading.Lock()


def _dir(lg):
    return store.path(lg.cfg["league_id"]).with_name("track")


def _key(day: dt.date) -> str:
    """Snapshots are weekly, keyed by the Tuesday that starts the week (after Monday night)."""
    return (day - dt.timedelta(days=(day.weekday() - 1) % 7)).isoformat()


# ------------------------------------------------------------------ snapshots
def snapshot(lg, today: dt.date | None = None) -> bool:
    """Save this week's snapshot if there isn't one yet. Returns True when one was written."""
    today = today or dt.date.today()
    p = _dir(lg) / f"{_key(today)}.json"
    if p.exists():
        return False
    h = lg.h2 or {}
    snap = {"date": today.isoformat(), "season": lg.season, "week": h.get("week"), "weeks_done": h.get("weeks_done"),
            "h2": {pid: {k: o[k] for k in ("pos", "rate", "so_far", "model", "sleeper", "change", "f", "play", "owner_rid")}
                   for pid, o in (h.get("players") or {}).items()},
            "players": {a["id"]: {"pos": a["pos"], "value": a["value"], "owner_rid": t["roster_id"],
                                  "verdict": (a.get("age_outlook") or {}).get("verdict")}
                        for t in lg.teams.values() for a in t["players"] if a["value"] >= MIN_VALUE},
            "buylow": [], "sell": list((lg.me or {}).get("sell_candidates") or [])}
    try:
        snap["buylow"] = [r["id"] for r in buylow.analyze(lg)["players"]]
    except Exception:  # value history missing: no buy-low list this week
        pass
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snap), encoding="utf-8")
    return True


def _snapshots(lg) -> list[dict]:
    d = _dir(lg)
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        if re.fullmatch(r"\d{4}-\d\d-\d\d\.json", p.name):
            out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


# ------------------------------------------------------------------ suggestions
def _slim(a: dict) -> dict:
    return {"kind": a["kind"], "id": a["id"], "name": a["name"], "pos": a.get("pos"), "value": a["value"]}


def log_suggestions(lg, groups: list[tuple[int, list[dict]]]) -> None:
    """Remember suggestions shown in Find trades: (partner roster_id, suggestions) pairs.
    The same trade (partner and pieces) is logged once, the first time it was shown."""
    if not lg.me:
        return
    p = _dir(lg) / "suggestions.json"
    with _lock:
        log = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        seen = {e["key"] for e in log}
        now = time.time()
        for rid, ss in groups:
            for s in ss:
                ids = lambda xs: ",".join(sorted(f"{a['kind']}:{a['id']}" for a in xs))
                key = f"{rid}|{ids(s['give'])}|{ids(s['get'])}"
                if key in seen:
                    continue
                seen.add(key)
                log.append({"key": key, "ts": now, "date": dt.date.today().isoformat(), "partner_rid": rid,
                            "partner": lg.teams[rid]["manager"], "give": [_slim(a) for a in s["give"]],
                            "get": [_slim(a) for a in s["get"]], "acceptance": (s.get("eval") or {}).get("acceptance")})
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(log[-LOG_MAX:]), encoding="utf-8")


def _value_now(lg, a: dict) -> tuple[float, bool]:
    """(today's value, whether it's still the same asset). A pick that has been used is
    valued as the player taken with it."""
    if a["kind"] == "player":
        return lg.values.player(a["id"])["value"], True
    cur = lg.asset("pick", a["id"])
    if cur:
        return cur["value"], True
    season, rnd, orig = (int(x) for x in a["id"].split("-"))
    used = lg.used_picks.get((season, rnd, orig))
    if used:
        return lg.values.player(used[0])["value"], False
    return a["value"], False


def _grade_suggestions(lg, today: dt.date) -> dict:
    p = _dir(lg) / "suggestions.json"
    log = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    me = lg.me["roster_id"] if lg.me else None
    trades = [t for t in lg.trades if me in (t.get("roster_ids") or [])]
    rows = []
    for e in reversed(log):
        then_get, then_give = sum(a["value"] for a in e["get"]), sum(a["value"] for a in e["give"])
        now_get = sum(_value_now(lg, a)[0] for a in e["get"])
        now_give = sum(_value_now(lg, a)[0] for a in e["give"])
        ts = e["ts"] * 1000
        made = None
        for t in trades:
            if (t.get("status_updated") or t.get("created") or 0) > ts and e["partner_rid"] in t["roster_ids"]:
                got = {pid for pid, to in (t.get("adds") or {}).items() if to == me}
                made = "these players" if any(a["id"] in got for a in e["get"] if a["kind"] == "player") else "a trade with them"
                break
        rows.append({**{k: e[k] for k in ("date", "partner_rid", "partner", "give", "get", "acceptance")},
                     "days": (today - dt.date.fromisoformat(e["date"])).days,
                     "then": round(then_get - then_give), "now": round(now_get - now_give),
                     "change": round((now_get - then_get) - (now_give - then_give)), "made": made})
    old = [r for r in rows if r["days"] >= VALUE_DAYS]
    return {"rows": rows[:60], "n": len(rows), "made": sum(1 for r in rows if r["made"]),
            "graded": len(old), "beat_pct": round(sum(r["change"] > 0 for r in old) / len(old) * 100) if old else None,
            "median_change": round(statistics.median(r["change"] for r in old)) if old else None}


# ------------------------------------------------------------------ grading
def _grade_h2(lg, snaps: list[dict]) -> list[dict]:
    stats, out = {}, []
    name = lambda pid: (lg.players_db.get(pid) or {}).get("full_name") or pid
    for s in snaps:
        if not s.get("h2"):
            continue
        if s["season"] not in stats:
            try:
                stats[s["season"]] = opportunity.season_stats(s["season"])
            except Exception:
                stats[s["season"]] = {}
        weekly = stats[s["season"]]
        rows = []
        for pid, o in s["h2"].items():
            pts = [weekly[w][pid].get("pts_ppr", 0.0) for w in o["play"]
                   if pid in weekly.get(w, {}) and weekly[w][pid].get("off_snp")]
            if len(pts) < H2_GAMES or o["so_far"] is None:
                continue
            rows.append({**o, "id": pid, "actual": statistics.mean(pts) * o["f"], "n": len(pts)})
        if not rows:
            continue

        def mae(k):
            xs = [abs(r[k] - r["actual"]) for r in rows if r[k] is not None]
            return round(statistics.mean(xs), 2) if xs else None
        movers = [r for r in rows if r["change"] is not None and abs(r["change"]) >= MOVE]
        hit = sum((r["actual"] - r["so_far"]) * r["change"] > 0 for r in movers)
        graded = sorted(w for w in weekly if s["week"] and w >= s["week"])
        out.append({"date": s["date"], "week": s["week"], "weeks": graded, "n": len(rows),
                    "outlook": mae("rate"), "pace": mae("so_far"), "sleeper": mae("sleeper"), "model": mae("model"),
                    "movers": len(movers), "movers_hit": round(hit / len(movers) * 100) if movers else None,
                    "examples": [{"id": r["id"], "name": name(r["id"]), "pos": r["pos"], "so_far": r["so_far"], "rate": r["rate"],
                                  "actual": round(r["actual"], 1), "n": r["n"], "hit": (r["actual"] - r["so_far"]) * r["change"] > 0}
                                 for r in sorted(movers, key=lambda r: -abs(r["change"]))[:10]]})
    return out


def _grade_values(lg, snaps: list[dict], today: dt.date) -> list[dict]:
    out = []
    for s in snaps:
        days = (today - dt.date.fromisoformat(s["date"])).days
        if days < VALUE_DAYS or not s.get("players"):
            continue
        buy, sell = set(s.get("buylow") or []), set(s.get("sell") or [])
        rows = []
        for pid, o in s["players"].items():
            now = lg.values.player(pid)["value"]
            rows.append({"i": 0, "pos": o["pos"], "band": aging._band(o["value"]), "ratio": now / max(o["value"], 1),
                         "verdict": o["verdict"], "buylow": pid in buy, "sell": pid in sell})
        checks._relative(rows)
        rel = lambda f: checks._summary([r["rel"] for r in rows if f(r) and r["rel"] is not None])
        out.append({"date": s["date"], "days": days, "n": len(rows),
                    "verdicts": {v: rel(lambda r, v=v: r["verdict"] == v) for v in VERDICTS},
                    "buylow": rel(lambda r: r["buylow"]), "sell": rel(lambda r: r["sell"])})
    return out


def lineups(lg) -> dict:
    """Every team's started lineup vs. the app's (most projected points) vs. the best
    possible, for each completed week this season."""
    cur = lineup.current_week(lg)
    weeks = [w for w in recap.weeks(lg) if cur is None or w < cur]
    lid = str(lg.cfg["league_id"])
    scoring = lg.info.get("scoring_settings") or {}
    positions = lg.info.get("roster_positions") or []
    slots = [s for s in positions if s in SLOT_ELIGIBLE]
    taxi = {a["id"] for t in lg.teams.values() for a in t["players"] if a.get("taxi")}
    name = lambda pid: (lg.players_db.get(pid) or {}).get("full_name") or pid
    teams = {rid: {"roster_id": rid, "manager": t["manager"], "you": 0.0, "app": 0.0, "best": 0.0, "weeks": 0, "app_wins": 0}
             for rid, t in lg.teams.items()}
    mine = []
    me = lg.me["roster_id"] if lg.me else None
    for w in weeks:
        P = lineup.projections(lg.season, w)
        proj = {pid: lineup.score(p["stats"], scoring) if p["stats"].get("gp", 1) else 0.0 for pid, p in P.items()}
        for m in sleeper.matchups(lid, w, True):
            rid = m["roster_id"]
            pts = m.get("players_points") or {}
            if rid not in teams or not m.get("points"):
                continue
            started = [(pid, p) for pid, p, slot in zip(m.get("starters") or [], m.get("starters_points") or [], positions)
                       if slot in SLOT_ELIGIBLE and pid and pid != "0"]
            pool = [{"id": pid, "pos": recap._pos(lg, pid), "proj": proj.get(pid, 0.0), "pts": pts.get(pid, 0.0)}
                    for pid in m.get("players") or [] if pid not in taxi]
            pool = [p for p in pool if p["pos"] in SLOT_ELIGIBLE["SUPER_FLEX"]]
            app = lineup._best(slots, pool, {}, key=lambda p: p["proj"]).values()
            best = lineup._best(slots, pool, {}, key=lambda p: p["pts"]).values()
            you, a_pts, b_pts = sum(p for _, p in started), sum(p["pts"] for p in app), sum(p["pts"] for p in best)
            T = teams[rid]
            T["you"] += you
            T["app"] += a_pts
            T["best"] += b_pts
            T["weeks"] += 1
            T["app_wins"] += a_pts > you + 0.05
            if rid == me:
                ids_you = {pid for pid, _ in started}
                ids_app = {p["id"] for p in app}
                by = {p["id"]: p for p in pool}
                swap = lambda ids: sorted(({"name": name(i), "proj": round(by[i]["proj"], 1) if i in by else None,
                                            "pts": round(pts.get(i, 0.0), 1)} for i in ids), key=lambda x: -x["pts"])
                mine.append({"week": w, "you": round(you, 1), "app": round(a_pts, 1), "best": round(b_pts, 1),
                             "app_start": swap(ids_app - ids_you), "you_start": swap(ids_you - ids_app)})
    rows = []
    for T in teams.values():
        if T["weeks"]:
            rows.append({**T, **{k: round(T[k], 1) for k in ("you", "app", "best")},
                         "diff": round(T["app"] - T["you"], 1),
                         "you_pct": round(T["you"] / T["best"] * 100, 1) if T["best"] else None,
                         "app_pct": round(T["app"] / T["best"] * 100, 1) if T["best"] else None,
                         "is_me": T["roster_id"] == me})
    rows.sort(key=lambda r: -(r["you_pct"] or 0))
    return {"weeks": weeks, "mine": mine, "teams": rows}


def analyze(lg) -> dict:
    today = dt.date.today()
    snaps = _snapshots(lg)
    try:
        L = lineups(lg)
    except Exception as e:  # projections or matchups missing
        L = {"weeks": [], "mine": [], "teams": [], "error": f"{type(e).__name__}: {e}"}
    return {"today": today.isoformat(), "snapshots": [s["date"] for s in snaps], "first": snaps[0]["date"] if snaps else None,
            "lineups": L, "h2": _grade_h2(lg, snaps), "values": _grade_values(lg, snaps, today),
            "suggestions": _grade_suggestions(lg, today) if lg.me else {"rows": [], "n": 0},
            "h2_games": H2_GAMES, "value_days": VALUE_DAYS, "move": MOVE}
