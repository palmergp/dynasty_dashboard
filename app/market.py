"""How this league prices assets in real trades, compared with the market.

Every completed trade is valued as of its trade day: players with DynastyProcess's weekly
values, rookie picks with DP's pick rankings from that week (see pickhistory), startup
picks as the player taken. Each side's haul is a package with the usual stud premium.

For each side, log(received / sent) says how well it did against the market. Each asset
it sent shares in that result by its share of the value sent. Averaged over the league's
trades, that gives a price index per kind of asset: +15% for 1sts means managers who
traded a 1st away got, on average, 15% more market value back than they gave. In other
words this league pays above market for 1sts, so they're worth selling here (and pricey
to buy). Indexes are shrunk toward 0 for small samples.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

from . import drafts as draftmod
from . import pickhistory, tendencies
from .tendencies import package_value

SHRINK = 2.0           # pseudo-trades of "priced at market" added to each kind
MAX_LOG = math.log(3)  # cap one side's result at 3x either way
YOUNG, VET = 24.5, 27.5
KINDS = {
    "QB": "Quarterbacks", "RB": "Running backs", "WR": "Wide receivers", "TE": "Tight ends",
    "R1": "1st-round picks", "R2": "2nd-round picks", "R3": "3rd-round or later picks",
    "young": "Young players (24 and under)", "prime": "Prime-age players (25–27)", "vet": "Veterans (28+)",
}
GROUPS = [("Position", ["QB", "RB", "WR", "TE", "R1", "R2", "R3"]), ("Age", ["young", "prime", "vet"])]


def _kinds(a: dict) -> list[str]:
    if a["kind"] == "pick":
        return [f"R{min(a['round'], 3)}"]
    out = [a["pos"]] if a["pos"] in ("QB", "RB", "WR", "TE") else []
    if a.get("age") is not None:
        out.append("young" if a["age"] <= YOUNG else "vet" if a["age"] >= VET else "prime")
    return out


def analyze(lg) -> dict:
    _, hist, _ = draftmod.context(lg)
    dates, hv = hist["dates"], hist["values"]
    try:
        H = pickhistory.pick_history(lg)
    except Exception:  # no pick history: fall back to today's pick values
        H = None
    p = lg.cfg["consolidation_exponent"]
    names = tendencies._manager_names(lg)

    def player_then(pid, day):
        series = hv.get(pid)
        return draftmod._value_at(series, dates, day) if series and dates else lg.values.player(pid)["market"]

    def asset(kind, data, ms, day):
        a = tendencies._hist_asset(lg, kind, data, ms)
        if a["kind"] == "player":
            a["then"] = player_then(a["id"], day)
        else:
            v = pickhistory.value_at(lg, H, day, a["season"], a["round"]) if H else None
            a["then"] = v if v is not None else lg.values.pick(max(a["season"], lg.pick_seasons[0]), a["round"])["market"]
            a["name"] = f"{a['season']} {('1st', '2nd', '3rd')[a['round'] - 1] if a['round'] <= 3 else str(a['round']) + 'th'}"
        return a

    sides = []
    for tx in lg.trades:
        ms = tx.get("status_updated") or tx.get("created") or 0
        day = dt.datetime.fromtimestamp(ms / 1000).date().isoformat()
        rids = tx.get("roster_ids") or []
        by = {rid: {"sent": [], "recv": []} for rid in rids}
        for pid, to in (tx.get("adds") or {}).items():
            frm = (tx.get("drops") or {}).get(pid)
            a = asset("player", pid, ms, day)
            if to in by:
                by[to]["recv"].append(a)
            if frm in by:
                by[frm]["sent"].append(a)
        for dp in tx.get("draft_picks") or []:
            a = asset("pick", dp, ms, day)
            if dp["owner_id"] in by:
                by[dp["owner_id"]]["recv"].append(a)
            if dp["previous_owner_id"] in by:
                by[dp["previous_owner_id"]]["sent"].append(a)
        for rid, s in by.items():
            sent_v = package_value([a["then"] for a in s["sent"]], p)
            recv_v = package_value([a["then"] for a in s["recv"]], p)
            if sent_v < 100 or recv_v < 100:  # FAAB-only or throw-in sides say nothing about prices
                continue
            uid = tx["roster_owner"].get(str(rid))
            sides.append({"tx": tx["transaction_id"], "date": day, "manager": names.get(uid, f"Team {rid}"), "sent": s["sent"], "recv": s["recv"],
                          "sent_v": sent_v, "recv_v": recv_v,
                          "lr": max(-MAX_LOG, min(MAX_LOG, math.log(recv_v / sent_v)))})

    acc = defaultdict(lambda: {"w": 0.0, "wlr": 0.0, "n": 0, "ex": []})
    for s in sides:
        total = sum(a["then"] for a in s["sent"]) or 1
        share = defaultdict(float)
        for a in s["sent"]:
            for k in _kinds(a):
                share[k] += a["then"] / total
        for k, w in share.items():
            c = acc[k]
            c["w"] += w
            c["wlr"] += w * s["lr"]
            c["n"] += w >= 0.25
            c["ex"].append((w * s["lr"], s))

    def brief(s):
        fmt = lambda xs: ", ".join(f"{a['name']} ({a['then']:,.0f})" for a in sorted(xs, key=lambda a: -a["then"]))
        return {"date": s["date"], "manager": s["manager"], "sent": fmt(s["sent"]), "recv": fmt(s["recv"]),
                "pct": round((math.exp(s["lr"]) - 1) * 100, 1)}

    groups = []
    for title, keys in GROUPS:
        rows = []
        for k in keys:
            c = acc.get(k)
            if not c or c["w"] == 0:
                continue
            est = c["wlr"] / (c["w"] + SHRINK)
            pct = (math.exp(est) - 1) * 100
            sign = 1 if est >= 0 else -1
            ex = [brief(s) for x, s in sorted(c["ex"], key=lambda e: -sign * e[0]) if sign * x > 0][:3]
            verdict = "market" if abs(pct) < 8 or c["n"] < 4 else "over" if pct > 0 else "under"
            rows.append({"key": k, "label": KINDS[k], "pct": round(pct, 1), "n": c["n"], "weight": round(c["w"], 1),
                         "verdict": verdict, "examples": ex})
        groups.append({"title": title, "rows": rows})
    return {"trades": len({s["tx"] for s in sides}), "sides": len(sides),
            "groups": groups, "since": sides and min(s["date"] for s in sides), "shrink": SHRINK,
            "pick_history": H is not None}
