"""Trade retrospectives: who won each trade at the time, at its most lopsided, and today.

Values come from the same DynastyProcess weekly history as the draft report, so "then"
and "now" are on one consistent scale (today's blended values mix in other sources, which
would create gaps that are really just source differences). Each side's haul is valued as
a package with the same stud premium as everywhere else.

- Players: their weekly value.
- Startup-draft picks: the player taken (they were really players).
- Rookie picks: today's generic value for that round until the pick is used, then the
  player drafted with it. There's no history of pick values, so this is the one place
  "then" isn't truly then.
- Points: fantasy points the received players scored in the receiving team's starting
  lineup while it held them (picks count once their player is drafted by that team).

The gap for a side is the value it received minus the value it sent. A trade is "even"
when the gap is under 250 or under 8% of the bigger side.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from . import drafts as draftmod
from . import tendencies, waivers
from .tendencies import package_value

EVEN_ABS, EVEN_PCT = 250, 0.08


def _day(ms) -> str:
    return dt.datetime.fromtimestamp(ms / 1000).date().isoformat()


def _gap(net: float, size: float) -> dict:
    return {"gap": round(net), "pct": round(net / (size or 1) * 100, 1)}


def _decided(net: float, size: float) -> bool:
    return abs(net) >= EVEN_ABS and abs(net) >= EVEN_PCT * size


def analyze(lg) -> dict:
    drafts_, hist, events = draftmod.context(lg)
    dates, hv = hist["dates"], hist["values"]
    if not dates:
        return {"dates": [], "trades": [], "managers": []}
    n = len(dates)
    p = lg.cfg["consolidation_exponent"]
    names = tendencies._manager_names(lg)

    drafted = {}  # player -> (ms, drafting roster)
    for d in drafts_:
        for pk in d["picks"]:
            drafted.setdefault(pk["player_id"], (pk["_ms"], pk["roster_id"]))
    pts_by = defaultdict(list)  # (roster, player) -> [(season, week, points)]
    for (season, rid, pid), wk in waivers._start_points(lg).items():
        pts_by[(rid, pid)].extend((season, w, x) for w, x in wk)

    def idx(day: str) -> int:
        j = 0
        for i, d in enumerate(dates):
            if d <= day:
                j = i
        return j

    def player_vals(pid):
        s = hv.get(pid) or [None] * n
        return [v or 0.0 for v in s]

    def held_points(rid, pid, ms, start):
        """Start points for rid from `start` (season, week) until rid next drops him."""
        stop = (9999, 99)
        for e in events:
            if e[0] > ms and e[1] == pid and e[2] == rid and e[4] == "drop":
                stop = (int(e[5]["season"]), e[5].get("leg") or 0) if e[5] else stop
                break
        return sum(x for s, w, x in pts_by.get((rid, pid), []) if start <= (s, w) <= stop)

    trades = []
    for tx in lg.trades:
        ms = tx.get("status_updated") or tx.get("created") or 0
        day = _day(ms)
        j0 = idx(day)
        start = (int(tx["season"]), tx.get("leg") or 0)
        rids = tx.get("roster_ids") or []
        assets = []  # dicts with from/to, series, points
        for pid, to in (tx.get("adds") or {}).items():
            a = tendencies._hist_asset(lg, "player", pid, ms)
            assets.append({**a, "to": to, "from": (tx.get("drops") or {}).get(pid), "vals": player_vals(pid),
                           "points": held_points(to, pid, ms, start)})
        for dp in tx.get("draft_picks") or []:
            a = tendencies._hist_asset(lg, "pick", dp, ms)
            to, frm = dp["owner_id"], dp["previous_owner_id"]
            if a["kind"] == "player":  # startup pick: the player taken
                vals, pid = player_vals(a["id"]), a["id"]
                pts = held_points(to, pid, ms, start)
            else:
                generic = lg.values.pick(lg.pick_seasons[0], dp["round"], None)["market"]
                pid = a.get("drafted")
                vals, pts = [generic] * n, 0.0
                if pid and pid in drafted:
                    dms, drid = drafted[pid]
                    jd = idx(_day(dms))
                    pv = player_vals(pid)
                    vals = [generic if j < jd else pv[j] for j in range(n)]
                    if drid == to:  # this team made the pick, so his points are theirs
                        pts = held_points(to, pid, dms, (int(dp["season"]), 0))
            assets.append({**a, "to": to, "from": frm, "vals": vals, "points": pts})

        sides = []
        for rid in rids:
            recv = [a for a in assets if a["to"] == rid]
            sent = [a for a in assets if a["from"] == rid]
            rs = [package_value([a["vals"][j] for a in recv], p) if j >= j0 else None for j in range(n)]
            ss = [package_value([a["vals"][j] for a in sent], p) if j >= j0 else None for j in range(n)]
            faab = sum(w["amount"] for w in tx.get("waiver_budget") or [] if w.get("receiver") == rid)
            uid = tx["roster_owner"].get(str(rid))
            sides.append({
                "roster_id": rid, "user_id": uid,
                "manager": names.get(uid, f"Team {rid}") if uid else f"Orphaned team {rid}",
                "received": [{k: a[k] for k in ("kind", "id", "name", "pos")} | {
                    "then": round(a["vals"][j0]), "now": round(a["vals"][-1]),
                    "peak": round(max(a["vals"][j0:])), "points": round(a["points"], 1)} for a in recv],
                "faab": faab, "recv_series": [round(v) if v is not None else None for v in rs],
                "_recv": rs, "_sent": ss,
                "points": round(sum(a["points"] for a in recv), 1),
                "points_sent": round(sum(a["points"] for a in sent), 1),
            })
        if len(sides) < 2:
            continue

        def leader(j):
            """(side index, net, size) of the side furthest ahead at snapshot j."""
            best = max(range(len(sides)), key=lambda i: sides[i]["_recv"][j] - sides[i]["_sent"][j])
            s = sides[best]
            return best, s["_recv"][j] - s["_sent"][j], max(s["_recv"][j], s["_sent"][j])

        def moment(j):
            i, net, size = leader(j)
            return {"date": max(dates[j], day), "leader": sides[i]["manager"] if _decided(net, size) else None,
                    "leader_rid": sides[i]["roster_id"] if _decided(net, size) else None, **_gap(net, size)}
        jp = max(range(j0, n), key=lambda j: leader(j)[1])
        then, peak, now = moment(j0), moment(jp), moment(n - 1)
        for s in sides:
            s["net_then"] = round(s["_recv"][j0] - s["_sent"][j0])
            s["net_now"] = round(s["_recv"][-1] - s["_sent"][-1])
            s["result"] = ("won" if now["leader_rid"] == s["roster_id"] else "even" if now["leader_rid"] is None else "lost")
        trades.append({
            "id": tx["transaction_id"], "date": day, "season": tx["season"], "week": tx.get("leg"),
            "before_history": day < dates[0], "start": j0,
            "then": then, "peak": peak, "now": now, "sides": sides,
        })

    # Per-manager record across all trades.
    agg = {}
    for t in trades:
        for s in t["sides"]:
            m = agg.setdefault(s["user_id"], {"user_id": s["user_id"], "manager": s["manager"], "trades": 0,
                                              "won": 0, "lost": 0, "even": 0, "net_then": 0, "net_now": 0,
                                              "points": 0.0, "points_sent": 0.0, "best": None, "worst": None})
            m["trades"] += 1
            m[s["result"]] += 1
            m["net_then"] += s["net_then"]
            m["net_now"] += s["net_now"]
            m["points"] += s["points"]
            m["points_sent"] += s["points_sent"]
            brief = {"id": t["id"], "date": t["date"], "net": s["net_now"]}
            if not m["best"] or s["net_now"] > m["best"]["net"]:
                m["best"] = brief
            if not m["worst"] or s["net_now"] < m["worst"]["net"]:
                m["worst"] = brief
    current = {t["owner_id"]: t["roster_id"] for t in lg.teams.values()}
    managers = []
    for m in agg.values():
        m["points"], m["points_sent"] = round(m["points"], 1), round(m["points_sent"], 1)
        m["roster_id"] = current.get(m["user_id"])
        managers.append(m)
    managers.sort(key=lambda m: -m["net_now"])
    for t in trades:
        for s in t["sides"]:
            del s["_recv"], s["_sent"]
    trades.sort(key=lambda t: t["date"], reverse=True)
    return {"dates": dates, "trades": trades, "managers": managers,
            "even": {"abs": EVEN_ABS, "pct": EVEN_PCT * 100},
            "source": "DynastyProcess weekly snapshots, mapped to the app's value scale"}
