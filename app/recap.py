"""Weekly league recap, written to paste into the league chat.

From Sleeper's weekly matchups: results, the closest game and the blowout, the top score
(ranked against every game in league history), upsets (the winner's starters were projected
to score less than the loser's, by Sleeper's projections for that week), the player of the
week, the most points left on the bench, standings after the week, the week's trades
(judged at today's values), the biggest waiver bids, and the biggest dynasty value risers
and fallers among rostered players (DynastyProcess's weekly values).
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from . import records, season as seasonmod, sleeper
from .league import SLOT_ELIGIBLE

UPSET_PTS = 10.0
MOVER_MIN = 1500


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _current(lg) -> dict | None:
    return next((s for s in records._seasons(lg) if s["league"]["league_id"] == str(lg.cfg["league_id"])), None)


def weeks(lg) -> list[int]:
    s = _current(lg)
    reg_end = ((lg.info.get("settings") or {}).get("playoff_week_start") or 15) + 2
    return [w for w in (s["weeks"] if s else []) if w <= reg_end]


def _pos(lg, pid: str) -> str:
    p = lg.players_db.get(pid) or {}
    pos = p.get("position") or "?"
    if pos not in ("QB", "RB", "WR", "TE", "K", "DEF"):
        pos = next((x for x in p.get("fantasy_positions") or [] if x in ("QB", "RB", "WR", "TE")), pos)
    return pos


def _optimal(lg, m: dict) -> float:
    """Best possible score from the roster's points that week (slots other than QB/RB/WR/TE
    and flexes, like K and DEF, count as started)."""
    pts = m.get("players_points") or {}
    fixed = sum(p for pid, p, slot in zip(m.get("starters") or [], m.get("starters_points") or [], lg.info.get("roster_positions") or [])
                if slot not in SLOT_ELIGIBLE and pid and pid != "0")
    pool = sorted(((pid, p) for pid, p in pts.items() if _pos(lg, pid) in ("QB", "RB", "WR", "TE")), key=lambda x: -x[1])
    used, total = set(), 0.0
    for slot in sorted(lg.slots, key=lambda s: len(SLOT_ELIGIBLE[s])):
        for pid, p in pool:
            if pid not in used and _pos(lg, pid) in SLOT_ELIGIBLE[slot]:
                used.add(pid)
                total += p
                break
    return fixed + total


def analyze(lg, week: int | None = None) -> dict:
    ws = weeks(lg)
    if not ws:
        return {"weeks": [], "week": None, "sections": [], "text": ""}
    week = week if week in ws else ws[-1]
    cur = _current(lg)
    lid = str(lg.cfg["league_id"])
    mgr = {rid: t["manager"] for rid, t in lg.teams.items()}
    pname = lambda pid: (lg.players_db.get(pid) or {}).get("full_name") or pid
    playoff_start = cur["playoff_start"]

    # Standings through this week (regular season only).
    rec = defaultdict(lambda: [0, 0, 0, 0.0])  # wins, losses, ties, points
    games = []
    for w in range(1, week + 1):
        by = defaultdict(list)
        for m in sleeper.matchups(lid, w, cur["done"]):
            if m.get("matchup_id") is not None:
                by[m["matchup_id"]].append(m)
        for pair in by.values():
            if len(pair) != 2 or not (pair[0].get("points") and pair[1].get("points")):
                continue
            a, b = pair
            if w < playoff_start:
                for x, y in ((a, b), (b, a)):
                    r = rec[x["roster_id"]]
                    r[0 if x["points"] > y["points"] else 1 if x["points"] < y["points"] else 2] += 1
                    r[3] += x["points"]
            if w == week:
                games.append((a, b) if a["points"] >= b["points"] else (b, a))
    if not games:
        return {"weeks": ws, "week": week, "sections": [], "text": ""}

    proj = seasonmod._projections(lg.season, week)
    projected = lambda m: sum(proj.get(pid, 0.0) for pid in m.get("starters") or [] if pid and pid != "0")
    sections = []
    lines = [f"{mgr.get(w['roster_id'])} {w['points']:.1f} def. {mgr.get(l['roster_id'])} {l['points']:.1f}" for w, l in
             sorted(games, key=lambda g: -g[0]["points"])]
    sections.append({"title": "Results", "lines": lines})

    hl = []
    close = min(games, key=lambda g: g[0]["points"] - g[1]["points"])
    blow = max(games, key=lambda g: g[0]["points"] - g[1]["points"])
    hl.append(f"Closest game: {mgr[close[0]['roster_id']]} edged {mgr[close[1]['roster_id']]} by {close[0]['points'] - close[1]['points']:.1f}.")
    if blow is not close:
        hl.append(f"Blowout: {mgr[blow[0]['roster_id']]} beat {mgr[blow[1]['roster_id']]} by {blow[0]['points'] - blow[1]['points']:.1f}.")
    teams = [m for g in games for m in g]
    top = max(teams, key=lambda m: m["points"])
    low = min(teams, key=lambda m: m["points"])
    all_games, perfs = records._games(lg, records._seasons(lg))
    scores = sorted((p for g in all_games for p in (g["pa"], g["pb"])), reverse=True)
    rank = 1 + sum(1 for s in scores if s > top["points"] + 1e-6)
    hist = f" ({_ordinal(rank)}-highest score in league history)" if rank <= 10 and len(scores) > 40 else ""
    hl.append(f"Top score: {mgr[top['roster_id']]} with {top['points']:.1f}{hist}.")
    hl.append(f"Low score: {mgr[low['roster_id']]} with {low['points']:.1f}.")
    for w_, l_ in games:
        pw, pl = projected(w_), projected(l_)
        if pw and pl and pl - pw >= UPSET_PTS:
            hl.append(f"Upset: {mgr[w_['roster_id']]} (projected {pw:.0f}) beat {mgr[l_['roster_id']]} (projected {pl:.0f}).")
    starts = [(p, pid, m["roster_id"]) for m in teams for pid, p in zip(m.get("starters") or [], m.get("starters_points") or [])
              if pid and pid != "0" and _pos(lg, pid) in ("QB", "RB", "WR", "TE")]
    if starts:
        p, pid, rid = max(starts)
        prank = 1 + sum(1 for x in perfs if x["points"] > p + 1e-6)
        ptxt = f", the {_ordinal(prank)}-best start in league history" if prank <= 10 and len(perfs) > 200 else ""
        hl.append(f"Player of the week: {pname(pid)} scored {p:.1f} for {mgr[rid]}{ptxt}.")
    bench = max(teams, key=lambda m: _optimal(lg, m) - m["points"])
    left = _optimal(lg, bench) - bench["points"]
    if left >= 10:
        flipped = next(((w_, l_) for w_, l_ in games if l_ is bench and _optimal(lg, bench) > w_["points"]), None)
        hl.append(f"Most points left on the bench: {mgr[bench['roster_id']]}, {left:.1f}"
                  + (f", enough to have beaten {mgr[flipped[0]['roster_id']]}." if flipped else "."))
    sections.append({"title": "Highlights", "lines": hl})

    order = sorted(rec, key=lambda r: (-(rec[r][0] + 0.5 * rec[r][2]), -rec[r][3]))
    if week < playoff_start:
        st = [f"{i + 1}. {mgr.get(r, r)} {rec[r][0]}-{rec[r][1]}{'-' + str(rec[r][2]) if rec[r][2] else ''} ({rec[r][3]:.0f} pts)"
              for i, r in enumerate(order)]
        sections.append({"title": "Standings", "lines": st, "numbered": True})

    tr = []
    for t in getattr(lg, "parsed_trades", []):
        if str(t["season"]) != str(lg.season) or t["week"] != week:
            continue
        parts = [f"{s['manager']} gets {', '.join(a['name'] for a in s['received']) or 'FAAB'}" for s in t["sides"]]
        best = max(t["sides"], key=lambda s: s["recv_value"] - s["sent_value"])
        size = max(best["recv_value"], best["sent_value"]) or 1
        edge = (best["recv_value"] - best["sent_value"]) / size * 100
        verdict = f"Edge {best['manager']} (+{edge:.0f}% at today's values)." if edge >= 5 else "Even at today's values."
        tr.append("; ".join(parts) + ". " + verdict)
    if tr:
        sections.append({"title": "Trades", "lines": tr})

    bids = []
    for tx in sleeper.transactions(lid, week):
        if tx.get("type") == "waiver" and tx.get("status") == "complete" and (tx.get("settings") or {}).get("waiver_bid"):
            for pid, rid in (tx.get("adds") or {}).items():
                bids.append((tx["settings"]["waiver_bid"], pid, rid))
    if bids:
        bids.sort(key=lambda b: -b[0])
        sections.append({"title": "Waivers", "lines": [f"{mgr.get(r, r)} paid ${b} for {pname(pid)}." for b, pid, r in bids[:3]]})

    mv = _movers(lg, week)
    if mv:
        sections.append({"title": "Dynasty value movers", "lines": mv})

    title = f"Week {week} recap · {lg.info.get('name')}"
    text = title + "\n" + "\n".join(f"\n{s['title']}\n" + "\n".join(x if s.get("numbered") else f"- {x}" for x in s["lines"])
                                     for s in sections)
    return {"weeks": ws, "week": week, "title": title, "sections": sections, "text": text}


def _movers(lg, week: int) -> list[str]:
    """Rostered players whose DynastyProcess value moved most over the week."""
    hist = lg.aging["hist"]
    dates, hv = hist["dates"], hist["values"]
    start = (sleeper.nfl_state().get("season_start_date") or "")
    if not dates or not start or str(sleeper.nfl_state().get("season")) != str(lg.season):
        return []
    end = (dt.date.fromisoformat(start) + dt.timedelta(days=7 * week - 1)).isoformat()  # Tuesday after the week
    j = max((i for i, d in enumerate(dates) if d <= end), default=None)
    i = max((k for k, d in enumerate(dates) if d <= (dt.date.fromisoformat(end) - dt.timedelta(days=7)).isoformat()), default=None)
    if i is None or j is None or i == j:
        return []
    owner = {a["id"]: t["manager"] for t in lg.teams.values() for a in t["players"]}
    rows = []
    for pid, mgr in owner.items():
        s = hv.get(pid)
        if s and s[i] and s[j] and max(s[i], s[j]) >= MOVER_MIN:
            rows.append(((s[j] / s[i] - 1) * 100, pid, mgr))
    rows.sort()
    nm = lambda pid: (lg.players_db.get(pid) or {}).get("full_name") or pid
    up = [f"{nm(p)} ({m}) {pct:+.0f}%" for pct, p, m in reversed(rows[-3:]) if pct >= 5]
    down = [f"{nm(p)} ({m}) {pct:+.0f}%" for pct, p, m in rows[:3] if pct <= -5]
    out = []
    if up:
        out.append("Up: " + ", ".join(up) + ".")
    if down:
        out.append("Down: " + ", ".join(down) + ".")
    return out
