"""Weekly league recap: the week's games, awards, standings and what's next, plus a version
to paste into the league chat.

From Sleeper's weekly matchups and projections:
- Games: score, each team's pre-game projection (its starters' Sleeper projections that
  week) and the winner's pre-game chance to win (projected margin over the league's
  week-to-week spread). An upset is a winner who had under a 35% chance.
- Lineups: each team's best possible score from that week's roster ("optimal") and the
  share of it they started; the biggest bench mistake names the swap.
- Luck: all-play record (how a team would have done against every other team that week).
  Over the season, luck = actual wins minus the wins its all-play rate would predict.
- Awards: top and low score (the top one ranked in league history), closest game, blowout,
  biggest upset, unluckiest loss, luckiest win, best and worst lineup calls, player and dud
  of the week, and the team that beat its projection by the most.
- Standings after the week with movement, streaks, and (for the latest week) playoff odds.
- Next week: projected scores and win chances for every game, with a game of the week.
- Trades (judged at today's values), the biggest waiver bids and the biggest dynasty value
  movers among rostered players (DynastyProcess's weekly values).
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

from . import records, season as seasonmod, sleeper
from .league import SLOT_ELIGIBLE

UPSET = 35.0     # winner's pre-game win chance below this = upset
MOVER_MIN = 1500
SKILL = ("QB", "RB", "WR", "TE")
EMOJI = {"top": "🔥", "low": "🧊", "close": "😬", "blowout": "💥", "upset": "🚨", "unlucky": "😩", "lucky": "🍀",
         "coach": "🧠", "blunder": "🪑", "player": "⭐", "dud": "💤", "beat": "📈"}


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


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
        pos = next((x for x in p.get("fantasy_positions") or [] if x in SKILL), pos)
    return pos


def _optimal(lg, m: dict) -> tuple[float, set]:
    """(best possible score from the roster's points that week, the QB/RB/WR/TE in that
    lineup). Slots other than QB/RB/WR/TE and flexes, like K and DEF, count as started."""
    pts = m.get("players_points") or {}
    fixed = sum(p for pid, p, slot in zip(m.get("starters") or [], m.get("starters_points") or [], lg.info.get("roster_positions") or [])
                if slot not in SLOT_ELIGIBLE and pid and pid != "0")
    pool = sorted(((pid, p) for pid, p in pts.items() if _pos(lg, pid) in SKILL), key=lambda x: -x[1])
    used, total = set(), 0.0
    for slot in sorted(lg.slots, key=lambda s: len(SLOT_ELIGIBLE[s])):
        for pid, p in pool:
            if pid not in used and _pos(lg, pid) in SLOT_ELIGIBLE[slot]:
                used.add(pid)
                total += p
                break
    return fixed + total, used


def _week_games(lid: str, w: int, done: bool) -> list[tuple[dict, dict]]:
    """Completed games as (winner, loser) matchup entries."""
    by = defaultdict(list)
    for m in sleeper.matchups(lid, w, done):
        if m.get("matchup_id") is not None:
            by[m["matchup_id"]].append(m)
    return [(a, b) if a["points"] >= b["points"] else (b, a) for a, b in (v for v in by.values() if len(v) == 2)
            if a.get("points") and b.get("points")]


def analyze(lg, week: int | None = None) -> dict:
    ws = weeks(lg)
    if not ws:
        return {"weeks": [], "week": None}
    week = week if week in ws else ws[-1]
    cur = _current(lg)
    lid = str(lg.cfg["league_id"])
    mgr = {rid: t["manager"] for rid, t in lg.teams.items()}
    name = lambda rid: mgr.get(rid, f"Team {rid}")
    pname = lambda pid: (lg.players_db.get(pid) or {}).get("full_name") or pid
    playoff_start = cur["playoff_start"]
    regular = week < playoff_start

    # ---- every week through this one: standings, streaks, all-play
    rec = defaultdict(lambda: {"w": 0, "l": 0, "t": 0, "pf": 0.0, "ap_w": 0, "ap_l": 0, "results": []})
    prev_order = None
    games = []
    for w in range(1, week + 1):
        wg = _week_games(lid, w, cur["done"])
        if w == week:
            games = wg
            if regular:
                prev_order = _order(rec)
        if w >= playoff_start:
            continue
        scores = [m["points"] for g in wg for m in g]
        for a, b in wg:
            for x, y in ((a, b), (b, a)):
                r = rec[x["roster_id"]]
                res = "W" if x["points"] > y["points"] else "L" if x["points"] < y["points"] else "T"
                r[{"W": "w", "L": "l", "T": "t"}[res]] += 1
                r["pf"] += x["points"]
                r["results"].append(res)
                r["ap_w"] += sum(1 for s in scores if s < x["points"])
                r["ap_l"] += sum(1 for s in scores if s > x["points"])
    if not games:
        return {"weeks": ws, "week": week}

    # ---- this week's games
    proj = seasonmod._projections(lg.season, week)
    projected = lambda m: sum(proj.get(pid, 0.0) for pid in m.get("starters") or [] if pid and pid != "0")
    done_weeks = [w for w in ws if w < week] or [week]
    sd = seasonmod._spread(lg, done_weeks) * math.sqrt(2)
    teams = [m for g in games for m in g]
    scores = sorted((m["points"] for m in teams), reverse=True)
    rank = lambda pts: 1 + sum(1 for s in scores if s > pts + 1e-6)
    tw = {}
    for m in teams:
        opt, opt_ids = _optimal(lg, m)
        tw[m["roster_id"]] = {"roster_id": m["roster_id"], "manager": name(m["roster_id"]), "points": round(m["points"], 1),
                              "proj": round(projected(m), 1), "optimal": round(opt, 1), "eff": round(m["points"] / opt * 100) if opt else None,
                              "rank": rank(m["points"]), "all_play": len(teams) - rank(m["points"]), "_m": m, "_opt": opt_ids}
    out_games = []
    for w_, l_ in games:
        W, L = tw[w_["roster_id"]], tw[l_["roster_id"]]
        p_win = round(_phi((W["proj"] - L["proj"]) / sd) * 100) if W["proj"] and L["proj"] else None
        margin = round(W["points"] - L["points"], 1)
        tags = []
        if p_win is not None and p_win < UPSET:
            tags.append("upset")
        if margin < 5:
            tags.append("close")
        if margin >= 40:
            tags.append("blowout")
        out_games.append({"winner": _pub(W), "loser": _pub(L), "margin": margin, "win_prob": p_win, "tags": tags})
    out_games.sort(key=lambda g: -g["winner"]["points"])

    # ---- awards
    awards = []
    all_games, perfs = records._games(lg, records._seasons(lg))
    hist = sorted((p for g in all_games for p in (g["pa"], g["pb"])), reverse=True)
    top = max(tw.values(), key=lambda t: t["points"])
    low = min(tw.values(), key=lambda t: t["points"])
    hr = 1 + sum(1 for s in hist if s > top["points"] + 1e-6)
    awards.append(_award("top", "Top score", top["manager"], f"{top['points']:.1f}",
                         f"{_ordinal(hr)}-highest score in league history" if hr <= 10 and len(hist) > 40 else f"{top['all_play']}-0 against the league"))
    awards.append(_award("low", "Low score", low["manager"], f"{low['points']:.1f}", f"would have lost to all {len(teams) - 1} teams" if low["all_play"] == 0 else ""))
    close = min(out_games, key=lambda g: g["margin"])
    awards.append(_award("close", "Closest game", f"{close['winner']['manager']} over {close['loser']['manager']}", f"by {close['margin']:.1f}", ""))
    blow = max(out_games, key=lambda g: g["margin"])
    if blow is not close:
        awards.append(_award("blowout", "Blowout", f"{blow['winner']['manager']} over {blow['loser']['manager']}", f"by {blow['margin']:.1f}", ""))
    ups = [g for g in out_games if "upset" in g["tags"]]
    if ups:
        u = min(ups, key=lambda g: g["win_prob"])
        awards.append(_award("upset", "Biggest upset", u["winner"]["manager"], f"{u['win_prob']}% to win",
                             f"projected {u['winner']['proj']:.0f} vs. {u['loser']['proj']:.0f}, beat {u['loser']['manager']}"))
    losers = [tw[g["loser"]["roster_id"]] for g in out_games]
    winners = [tw[g["winner"]["roster_id"]] for g in out_games]
    unl = min(losers, key=lambda t: t["rank"])
    if unl["rank"] <= len(teams) // 2:
        awards.append(_award("unlucky", "Unluckiest loss", unl["manager"], f"{_ordinal(unl['rank'])}-highest score",
                             f"{unl['all_play']}-{len(teams) - 1 - unl['all_play']} against the league, still lost"))
    lucky = max(winners, key=lambda t: t["rank"])
    if lucky["rank"] > len(teams) // 2:
        awards.append(_award("lucky", "Luckiest win", lucky["manager"], f"{_ordinal(lucky['rank'])}-highest score", "won anyway"))
    coach = max(tw.values(), key=lambda t: (t["eff"] or 0, t["points"]))
    awards.append(_award("coach", "Best lineup", coach["manager"], f"{coach['eff']}% of optimal", "started almost everyone they should have"))
    blunder = max(tw.values(), key=lambda t: t["optimal"] - t["points"])
    left = blunder["optimal"] - blunder["points"]
    if left >= 8:
        swap = _swap(lg, blunder["_m"], blunder["_opt"], pname)
        flipped = next((g for g in out_games if g["loser"]["roster_id"] == blunder["roster_id"] and blunder["optimal"] > g["winner"]["points"]), None)
        awards.append(_award("blunder", "Points left on the bench", blunder["manager"], f"{left:.1f}",
                             " ".join(x for x in (swap + "." if swap else "", f"Would have beaten {flipped['winner']['manager']}." if flipped else "") if x)))
    starts = [(p, pid, m["roster_id"]) for m in teams for pid, p in zip(m.get("starters") or [], m.get("starters_points") or [])
              if pid and pid != "0" and _pos(lg, pid) in SKILL]
    if starts:
        p, pid, rid = max(starts)
        prank = 1 + sum(1 for x in perfs if x["points"] > p + 1e-6)
        awards.append(_award("player", "Player of the week", pname(pid), f"{p:.1f} pts",
                             f"for {name(rid)}" + (f", {_ordinal(prank)}-best start in league history" if prank <= 10 and len(perfs) > 200 else "")))
        duds = [(proj.get(pid, 0) - p, p, pid, rid) for p, pid, rid in starts if proj.get(pid, 0) >= 12]
        if duds:
            short, p, pid, rid = max(duds)
            if short >= 8:
                awards.append(_award("dud", "Dud of the week", pname(pid), f"{p:.1f} pts", f"projected {proj[pid]:.0f}, started by {name(rid)}"))
    beat = max(tw.values(), key=lambda t: t["points"] - t["proj"])
    if beat["proj"] and beat["points"] - beat["proj"] >= 15:
        awards.append(_award("beat", "Beat the projection", beat["manager"], f"+{beat['points'] - beat['proj']:.0f}",
                             f"{beat['points']:.0f} vs. {beat['proj']:.0f} projected"))

    # ---- standings
    standings = []
    if regular:
        order = _order(rec)
        before = {rid: i for i, rid in enumerate(prev_order or [])}
        odds = {t["roster_id"]: t["playoff_pct"] for t in (lg.sim or {}).get("teams", [])} if week == ws[-1] else {}
        for i, rid in enumerate(order):
            r = rec[rid]
            g = r["w"] + r["l"] + r["t"]
            ap = r["ap_w"] / ((r["ap_w"] + r["ap_l"]) or 1)
            streak = _streak(r["results"])
            standings.append({"rank": i + 1, "roster_id": rid, "manager": name(rid), "w": r["w"], "l": r["l"], "t": r["t"], "pf": round(r["pf"], 1),
                              "move": (before[rid] - i) if rid in before and prev_order else 0, "streak": streak,
                              "all_play": f"{r['ap_w']}-{r['ap_l']}", "luck": round(r["w"] + 0.5 * r["t"] - ap * g, 1),
                              "playoff_pct": odds.get(rid)})

    # ---- next week
    preview = _preview(lg, lid, week, ws, sd, cur, mgr, odds if regular else {})

    # ---- trades, waivers, movers
    trades = []
    for t in getattr(lg, "parsed_trades", []):
        if str(t["season"]) != str(lg.season) or t["week"] != week:
            continue
        best = max(t["sides"], key=lambda s: s["recv_value"] - s["sent_value"])
        size = max(best["recv_value"], best["sent_value"]) or 1
        edge = (best["recv_value"] - best["sent_value"]) / size * 100
        trades.append({"sides": [{"manager": s["manager"], "gets": [a["name"] for a in s["received"]] or ["FAAB"]} for s in t["sides"]],
                       "verdict": f"Edge {best['manager']} (+{edge:.0f}% at today's values)" if edge >= 5 else "Even at today's values"})
    bids = []
    for tx in sleeper.transactions(lid, week):
        if tx.get("type") == "waiver" and tx.get("status") == "complete" and (tx.get("settings") or {}).get("waiver_bid"):
            for pid, rid in (tx.get("adds") or {}).items():
                bids.append({"bid": tx["settings"]["waiver_bid"], "player": pname(pid), "pos": _pos(lg, pid), "manager": name(rid)})
    bids.sort(key=lambda b: -b["bid"])
    movers = _movers(lg, week)

    out = {"weeks": ws, "week": week, "league": lg.info.get("name"), "games": out_games, "awards": awards,
           "standings": standings, "preview": preview, "trades": trades, "waivers": bids[:5], "movers": movers,
           "headline": _headline(out_games, standings, awards), "playoffs": not regular}
    out["text"] = _text(out, emoji=False)
    out["text_emoji"] = _text(out, emoji=True)
    return out


def _pub(t: dict) -> dict:
    return {k: v for k, v in t.items() if not k.startswith("_")}


def _award(key, title, who, stat, detail):
    return {"key": key, "title": title, "who": who, "stat": stat, "detail": detail}


def _order(rec) -> list:
    return sorted(rec, key=lambda r: (-(rec[r]["w"] + 0.5 * rec[r]["t"]), -rec[r]["pf"]))


def _streak(results: list[str]) -> str:
    if not results:
        return ""
    last, n = results[-1], 0
    for r in reversed(results):
        if r != last:
            break
        n += 1
    return f"{last}{n}"


def _swap(lg, m, opt_ids, pname) -> str | None:
    """'Benched X (21.6) for Y (4.2)': the best benched player who belonged in the lineup
    and the worst starter he could have replaced."""
    pts = m.get("players_points") or {}
    starters = [pid for pid in m.get("starters") or [] if pid and pid != "0" and _pos(lg, pid) in SKILL]
    benched = sorted((pid for pid in opt_ids if pid not in starters), key=lambda pid: -pts.get(pid, 0))
    for b in benched:
        bpos = _pos(lg, b)
        cands = [s for s in starters if s not in opt_ids and (bpos == _pos(lg, s) or {bpos, _pos(lg, s)} <= {"RB", "WR", "TE"})]
        if cands:
            s = min(cands, key=lambda pid: pts.get(pid, 0))
            return f"Benched {pname(b)} ({pts.get(b, 0):.1f}) for {pname(s)} ({pts.get(s, 0):.1f})"
    return None


def _preview(lg, lid, week, ws, sd, cur, mgr, odds) -> list:
    nxt = week + 1
    if nxt >= cur["playoff_start"] or nxt in ws:  # playoffs, or a week that's already been played
        return []
    proj = seasonmod._projections(lg.season, nxt)
    by = defaultdict(list)
    for m in sleeper.matchups(lid, nxt, False):
        if m.get("matchup_id") is not None:
            by[m["matchup_id"]].append(m["roster_id"])
    out = []
    for a, b in (v for v in by.values() if len(v) == 2):
        pa = seasonmod._lineup_points(lg, lg.teams[a]["players"], proj) if a in lg.teams else 0
        pb = seasonmod._lineup_points(lg, lg.teams[b]["players"], proj) if b in lg.teams else 0
        p = round(_phi((pa - pb) / sd) * 100)
        if pb > pa:
            a, b, pa, pb, p = b, a, pb, pa, 100 - p
        out.append({"fav": mgr.get(a), "dog": mgr.get(b), "fav_proj": round(pa, 1), "dog_proj": round(pb, 1), "fav_prob": p,
                    "stakes": round(min(odds.get(a, 50), 100 - odds.get(a, 50)) + min(odds.get(b, 50), 100 - odds.get(b, 50)))})
    if out:
        gotw = max(out, key=lambda g: g["stakes"] - abs(g["fav_prob"] - 50))
        gotw["gotw"] = True
    out.sort(key=lambda g: g["fav_prob"])
    return out


def _headline(games, standings, awards) -> list[str]:
    out = []
    if standings:
        lead = standings[0]
        if lead["l"] == 0 and lead["w"] >= 3:
            out.append(f"{lead['manager']} stays perfect at {lead['w']}-0.")
        winless = [s for s in standings if s["w"] == 0 and s["l"] >= 3]
        for s in winless[:1]:
            out.append(f"{s['manager']} is still looking for a first win (0-{s['l']}).")
        hot = max(standings, key=lambda s: int(s["streak"][1:]) if s["streak"].startswith("W") else 0)
        if hot["streak"].startswith("W") and int(hot["streak"][1:]) >= 3 and hot is not lead:
            out.append(f"{hot['manager']} has won {hot['streak'][1:]} straight.")
    a = {x["key"]: x for x in awards}
    if "upset" in a:
        out.append(f"Upset alert: {a['upset']['who']} won with a {a['upset']['stat'].split('%')[0]}% chance.")
    if "top" in a:
        out.append(f"{a['top']['who']} put up the week's best score ({a['top']['stat']}).")
    return out[:3]


def _text(R: dict, emoji: bool) -> str:
    e = (lambda k: EMOJI.get(k, "") + " ") if emoji else (lambda k: "")
    lines = [f"{'🏈 ' if emoji else ''}Week {R['week']} recap · {R['league']}"]
    if R["headline"]:
        lines += ["", " ".join(R["headline"])]
    lines += ["", "Results"]
    for g in R["games"]:
        tag = " (upset!)" if "upset" in g["tags"] else ""
        lines.append(f"- {g['winner']['manager']} {g['winner']['points']:.1f} def. {g['loser']['manager']} {g['loser']['points']:.1f}{tag}")
    lines += ["", "Awards"]
    for a in R["awards"]:
        lines.append(f"- {e(a['key'])}{a['title']}: {a['who']}, {a['stat']}" + (f" ({a['detail']})" if a["detail"] else ""))
    if R["standings"]:
        lines += ["", "Standings"]
        for s in R["standings"]:
            mv = f" {'↑' if s['move'] > 0 else '↓'}{abs(s['move'])}" if s["move"] else ""
            lines.append(f"{s['rank']}. {s['manager']} {s['w']}-{s['l']}{'-' + str(s['t']) if s['t'] else ''}{mv}" + (f" ({s['streak']})" if s["streak"] else ""))
    if R["preview"]:
        lines += ["", "Next week"]
        for g in R["preview"]:
            lines.append(f"- {g['fav']} ({g['fav_prob']}%) vs. {g['dog']}" + (" ← game of the week" if g.get("gotw") else ""))
    if R["trades"]:
        lines += ["", "Trades"]
        for t in R["trades"]:
            lines.append("- " + "; ".join(f"{s['manager']} gets {', '.join(s['gets'])}" for s in t["sides"]) + f". {t['verdict']}.")
    if R["waivers"]:
        lines += ["", "Waivers"] + [f"- {b['manager']} paid ${b['bid']} for {b['player']}" for b in R["waivers"][:3]]
    if R["movers"]:
        lines += ["", "Dynasty value movers"]
        if R["movers"]["up"]:
            lines.append("- Up: " + ", ".join(f"{m['name']} ({m['manager']}) {m['pct']:+.0f}%" for m in R["movers"]["up"]))
        if R["movers"]["down"]:
            lines.append("- Down: " + ", ".join(f"{m['name']} ({m['manager']}) {m['pct']:+.0f}%" for m in R["movers"]["down"]))
    return "\n".join(lines)


def _movers(lg, week: int) -> dict | None:
    """Rostered players whose DynastyProcess value moved most over the week."""
    hist = lg.aging["hist"]
    dates, hv = hist["dates"], hist["values"]
    start = (sleeper.nfl_state().get("season_start_date") or "")
    if not dates or not start or str(sleeper.nfl_state().get("season")) != str(lg.season):
        return None
    end = (dt.date.fromisoformat(start) + dt.timedelta(days=7 * week - 1)).isoformat()  # Tuesday after the week
    j = max((i for i, d in enumerate(dates) if d <= end), default=None)
    i = max((k for k, d in enumerate(dates) if d <= (dt.date.fromisoformat(end) - dt.timedelta(days=7)).isoformat()), default=None)
    if i is None or j is None or i == j:
        return None
    owner = {a["id"]: (t["manager"], a["pos"]) for t in lg.teams.values() for a in t["players"]}
    rows = []
    for pid, (m, pos) in owner.items():
        s = hv.get(pid)
        if s and s[i] and s[j] and max(s[i], s[j]) >= MOVER_MIN:
            rows.append(((s[j] / s[i] - 1) * 100, pid, m, pos))
    rows.sort()
    nm = lambda pid: (lg.players_db.get(pid) or {}).get("full_name") or pid
    row = lambda r: {"name": nm(r[1]), "id": r[1], "manager": r[2], "pos": r[3], "pct": round(r[0], 1)}
    out = {"up": [row(r) for r in reversed(rows[-3:]) if r[0] >= 5], "down": [row(r) for r in rows[:3] if r[0] <= -5]}
    return out if out["up"] or out["down"] else None
