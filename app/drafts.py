"""Draft performance, retention and roster construction.

- Every completed draft in the league's history (startup and rookie) is credited to the
  roster that made each pick.
- Sleeper doesn't timestamp individual picks, so each pick's date is interpolated
  between the draft's start and its last pick by pick number. This matters for slow
  startup drafts that run for weeks.
- Values over time come from history.value_history (DynastyProcess weekly snapshots).
- Roster construction uses each current player's most recent acquisition by his
  current team: startup draft, rookie draft, trade, or waivers/free agency.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from . import history, sleeper

SOURCES = ("startup", "rookie", "trade", "waiver")
SOURCE_LABELS = {"startup": "Startup draft", "rookie": "Rookie draft", "trade": "Trade", "waiver": "Waivers / FA"}


def _ms_to_date(ms) -> dt.date:
    return dt.datetime.fromtimestamp(ms / 1000).date()


def _drafts(lg) -> list[dict]:
    out = []
    for l in sleeper.league_chain(lg.cfg["league_id"]):
        for d in sleeper.cached_drafts(l["league_id"]):
            if d.get("status") != "complete" or not sleeper.draft_in_scope(l, d):
                continue
            full = sleeper.draft(d["draft_id"])
            picks = [{**p, "roster_id": sleeper.rid(l, p["roster_id"])}
                     for p in sleeper.draft_picks(d["draft_id"], True) if p.get("player_id")]
            if not picks:
                continue
            startup = sleeper.is_startup(l, d)
            start = full.get("start_time") or full.get("created")
            end = full.get("last_picked") or start
            n = max(p["pick_no"] for p in picks)
            for p in picks:
                frac = (p["pick_no"] - 1) / (n - 1) if n > 1 else 0
                p["_ms"] = start + frac * (end - start)
            out.append({
                "id": d["draft_id"], "season": int(d["season"]), "kind": "startup" if startup else "rookie",
                "label": f"{d['season']} {'Startup' if startup else 'Rookie'} draft",
                "start": _ms_to_date(start).isoformat(), "end": _ms_to_date(end).isoformat(),
                "rounds": (d.get("settings") or {}).get("rounds"), "picks": picks,
            })
    out.sort(key=lambda d: d["start"])
    return out


def _events(lg, drafts) -> list[tuple]:
    """(ms, player_id, roster_id, source, kind, tx) for every add/drop, oldest first.
    tx is the Sleeper transaction (None for draft picks)."""
    ev = []
    for d in drafts:
        for p in d["picks"]:
            ev.append((p["_ms"], p["player_id"], p["roster_id"], d["kind"], "add", None))
    for tx in sleeper.all_transactions(lg.cfg["league_id"]):
        ms = tx.get("status_updated") or tx.get("created") or 0
        src = "trade" if tx["type"] == "trade" else "waiver"  # waiver, free_agent, commissioner
        for pid, rid in (tx.get("drops") or {}).items():
            ev.append((ms - 1, pid, rid, src, "drop", tx))  # a drop precedes an add in the same move
        for pid, rid in (tx.get("adds") or {}).items():
            ev.append((ms, pid, rid, src, "add", tx))
    ev.sort(key=lambda e: e[0])
    return ev


def _value_at(series: list, dates: list[str], day: str):
    """Value at the last snapshot on/before day; else the first one after (rookies)."""
    best = None
    for d, v in zip(dates, series):
        if d <= day:
            if v is not None:
                best = v
        elif best is not None:
            break
        elif v is not None:
            return v
    return best if best is not None else 0.0


def context(lg) -> tuple[list, dict, list]:
    """(drafts, value history, add/drop events), computed once per League build and
    shared by the draft and waiver reports."""
    ctx = getattr(lg, "_draft_ctx", None)
    if ctx is None:
        drafts = _drafts(lg)
        start = dt.date.fromisoformat(drafts[0]["start"]) if drafts else dt.date(lg.season, 1, 1)
        hist = history.value_history(lg, start - dt.timedelta(days=14))
        ctx = lg._draft_ctx = (drafts, hist, _events(lg, drafts))
    return ctx


def analyze(lg) -> dict:
    drafts, hist, events = context(lg)
    if not drafts:
        return {"drafts": [], "teams": [], "picks": [], "dates": [], "construction": []}
    dates, hv = hist["dates"], hist["values"]

    owner_now = {a["id"]: t["roster_id"] for t in lg.teams.values() for a in t["players"]}
    mgr = {rid: t["manager"] for rid, t in lg.teams.items()}

    # ---- every drafted player
    picks = []
    for d in drafts:
        for p in d["picks"]:
            pid, rid = p["player_id"], p["roster_id"]
            info = lg.players_db.get(pid) or {}
            series = hv.get(pid) or [None] * len(dates)
            day = _ms_to_date(p["_ms"]).isoformat()
            dv = _value_at(series, dates, day)
            now = next((v for v in reversed(series) if v is not None), 0.0)
            # Only plot from the pick date onward.
            plotted = [round(v) if v is not None and dd >= day else None for dd, v in zip(dates, series)]
            left = next(((e[0], e[3]) for e in events if e[1] == pid and e[2] == rid and e[4] == "drop" and e[0] > p["_ms"]), None)
            cur = owner_now.get(pid)
            if cur == rid:
                status = "On roster"
            elif left:
                how = "Traded" if left[1] == "trade" else "Dropped"
                status = f"{how} {_ms_to_date(left[0]).isoformat()}" + (f" · now {mgr.get(cur)}" if cur else "")
            else:
                status = f"Now {mgr.get(cur)}" if cur else "Not rostered"
            picks.append({
                "draft_id": d["id"], "draft": d["label"], "kind": d["kind"], "round": p["round"], "pick_no": p["pick_no"],
                "slot": p["draft_slot"], "roster_id": rid, "manager": mgr.get(rid, f"Team {rid}"),
                "player_id": pid, "name": info.get("full_name") or pid, "pos": info.get("position") or "?",
                "date": day, "draft_value": round(dv), "now_value": round(now), "change": round(now - dv),
                "history": plotted, "on_roster": cur == rid, "in_league": cur is not None, "status": status,
                "current_rid": cur,
            })

    # ---- per-team aggregates & series
    teams = []
    keys = [d["id"] for d in drafts] + ["all"]
    for rid, t in lg.teams.items():
        mine = [p for p in picks if p["roster_id"] == rid]
        per = {}
        for key in keys:
            ps = mine if key == "all" else [p for p in mine if p["draft_id"] == key]
            if not ps:
                continue
            tot, idx = [], []
            for i, day in enumerate(dates):
                live = [p for p in ps if p["date"] <= day]
                if not live:
                    tot.append(None)
                    idx.append(None)
                    continue
                s = sum(p["history"][i] or 0 for p in live)
                base = sum(p["draft_value"] for p in live) or 1
                tot.append(round(s))
                idx.append(round(s / base * 100, 1))
            dvs = sum(p["draft_value"] for p in ps)
            nows = sum(p["now_value"] for p in ps)
            best = max(ps, key=lambda p: p["change"])
            worst = min(ps, key=lambda p: p["change"])
            per[key] = {
                "n": len(ps), "draft_value": round(dvs), "now_value": round(nows),
                "change_pct": round((nows - dvs) / (dvs or 1) * 100, 1),
                "retained": sum(p["on_roster"] for p in ps), "in_league": sum(p["in_league"] for p in ps),
                "retained_pct": round(sum(p["on_roster"] for p in ps) / len(ps) * 100),
                "retained_value": round(sum(p["now_value"] for p in ps if p["on_roster"])),
                "best": {"name": best["name"], "pos": best["pos"], "change": best["change"]},
                "worst": {"name": worst["name"], "pos": worst["pos"], "change": worst["change"]},
                "series": tot, "index": idx,
            }
        teams.append({"roster_id": rid, "manager": t["manager"], "team_name": t["team_name"], "drafts": per})

    return {
        "dates": dates, "drafts": [{k: v for k, v in d.items() if k != "picks"} for d in drafts],
        "teams": teams, "picks": picks, "construction": _construction(lg, events),
        "source": "DynastyProcess weekly snapshots, mapped to the app's value scale",
        # Drafts before the first snapshot are valued as of that snapshot, not draft day.
        "history_start": dates[0] if dates else None,
        "early_drafts": [d["label"] for d in drafts if dates and d["start"] < dates[0]],
    }


def _construction(lg, events) -> list[dict]:
    last_add = {}
    for ms, pid, rid, src, kind, _ in events:
        if kind == "add":
            last_add[(pid, rid)] = (ms, src)
    out = []
    for rid, t in lg.teams.items():
        counts, vals, players = defaultdict(int), defaultdict(float), []
        for a in t["players"]:
            ms, src = last_add.get((a["id"], rid), (None, "waiver"))
            counts[src] += 1
            vals[src] += a["value"]
            players.append({"id": a["id"], "name": a["name"], "pos": a["pos"], "value": a["value"], "source": src,
                            "date": _ms_to_date(ms).isoformat() if ms else None})
        total_v = sum(vals.values()) or 1
        out.append({
            "roster_id": rid, "manager": t["manager"], "n": len(t["players"]),
            "counts": {s: counts[s] for s in SOURCES},
            "values": {s: round(vals[s]) for s in SOURCES},
            "value_pct": {s: round(vals[s] / total_v * 100, 1) for s in SOURCES},
            "players": sorted(players, key=lambda p: -p["value"]),
        })
    return out
