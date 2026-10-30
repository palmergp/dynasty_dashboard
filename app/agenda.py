"""Season calendar: this league's key dates through next year's rookie draft, and what the
app suggests doing at each one.

Dates come from the league's settings (trade deadline, playoff weeks) and the NFL calendar
(Sleeper's season start, the NFL draft around the last Thursday of April). The rookie draft
is estimated from the date of the league's last one. Suggestions come from the other
reports: the deadline sell list, when picks and players usually peak in value, which of
your picks sit in slots the market has overpriced, and next offseason's roster crunch.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from . import deadline, pickhistory, roster, seasonal, sleeper

MONTH_NUM = {m: i + 1 for i, m in enumerate(seasonal.MONTHS)}


def _week_start(lg, week: int) -> dt.date | None:
    st = sleeper.nfl_state()
    if not st.get("season_start_date") or str(st.get("season")) != str(lg.season):
        return None
    return dt.date.fromisoformat(st["season_start_date"]) + dt.timedelta(days=7 * (week - 1))


def _next_month(month: int, today: dt.date) -> dt.date:
    """The 15th of the next occurrence of a month (this month counts if it's early)."""
    y = today.year if month > today.month or (month == today.month and today.day <= 15) else today.year + 1
    return dt.date(y, month, 15)


def _nfl_draft(year: int) -> dt.date:
    d = dt.date(year, 4, 30)
    while d.weekday() != 3:  # last Thursday of April
        d -= dt.timedelta(days=1)
    return d


def build(lg, sim: dict | None = None) -> dict:
    today = dt.date.today()
    st = lg.info.get("settings") or {}
    ev = []

    def add(day, title, what, link=None, approx=False, kind="league"):
        if day and day >= today - dt.timedelta(days=3):
            ev.append({"date": day.isoformat(), "title": title, "what": what, "link": link, "approx": approx, "kind": kind})

    # ---- this season
    dl = deadline._deadline(lg)
    if dl.get("dates") and dl.get("open"):
        D = deadline.analyze(lg, sim) if sim and lg.me else {"players": []}
        top = D["players"][:3]
        what = (f"Your sell list has {len(D['players'])} player{'s' if len(D['players']) != 1 else ''}"
                + (f", led by {', '.join(p['name'] for p in top)}" if top else "") + ". Contenders pay the most in the weeks before it.")
        add(dt.date.fromisoformat(dl["dates"][0]), f"Trade deadline (week {dl['week']})", what + " Check the exact cutoff in Sleeper.", "#/deadline")
    pw = st.get("playoff_week_start")
    if pw:
        start = _week_start(lg, pw)
        add(start, f"Playoffs start (week {pw})", "After the deadline, trades wait for the offseason; plan your offseason moves.", "#/season")
        rounds = {4: 2, 6: 3, 8: 3}.get(st.get("playoff_teams") or 6, 3)
        end = _week_start(lg, pw + rounds - 1)
        if end:
            add(end + dt.timedelta(days=6), "Championship week ends",
                "The offseason trade market opens. Rebuilding teams' picks and young players get busier.", "#/partners")

    # ---- when picks and players usually peak
    try:
        T = pickhistory.seasonality(lg)
        by_month, rounds = defaultdict(list), defaultdict(set)
        for t in T["tracks"]:
            o = t.get("outlook")
            if o and o.get("best_pct", 0) >= 3:
                by_month[o["best"]].append(f"{t['label'].lower()}s (+{o['best_pct']:.0f}% vs. now)")
                rounds[o["best"]].add(1 if "1st" in t["label"] else 2 if "2nd" in t["label"] else 3)
        for m, xs in by_month.items():
            sell = [p["name"] for p in (lg.me or {}).get("picks", [])
                    if p["round"] in rounds[m] and p.get("kept") is not None and p["kept"] <= 85][:3]
            add(_next_month(MONTH_NUM[m], today), f"Next year's picks usually peak: {', '.join(xs)}",
                "A good month to sell picks you don't plan to use"
                + (f", like {', '.join(sell)}, which sit in slots the market has overpriced." if sell else "."), "#/draftprep", approx=True, kind="picks")
    except Exception:
        pass
    S = lg.seasonal
    if S.get("groups") and lg.me:
        by_month = defaultdict(list)
        for a in lg.me["players"]:
            if a["value"] < seasonal.MIN_VALUE:
                continue
            o = seasonal.outlook(S, a["pos"], a["age"])
            if o and o["best_pct"] >= seasonal.MIN_MOVE:
                by_month[o["best"]].append(f"{a['name']} (+{o['best_pct']:.0f}%)")
        for m, xs in by_month.items():
            add(_next_month(MONTH_NUM[m], today), "Usually the best month to sell some of your players",
                f"Players like {', '.join(xs[:4])} are typically worth the most around now.", "#/deadline", approx=True, kind="players")
        lows = defaultdict(int)
        for g in S["groups"]:
            lows[g["low"]] += 1
        dip = max(lows, key=lows.get)
        add(_next_month(MONTH_NUM[dip], today), "Player values usually bottom out",
            f"Most positions and ages dip around {dip} (the new rookie class pushes veterans down): a cheap time to buy players.", "#/buylow",
            approx=True, kind="players")

    # ---- offseason
    nxt = lg.pick_seasons[0]
    add(_nfl_draft(nxt), f"{nxt} NFL draft",
        "Rookie values settle once landing spots are known. The draft board gets NFL picks and hit odds.", "#/draftprep", approx=True)
    last = next((d for d in reversed(sleeper.cached_drafts(lg.cfg["league_id"])) if d.get("start_time") and not sleeper.is_startup(lg.info, d)), None)
    if last:
        prev = dt.datetime.fromtimestamp(last["start_time"] / 1000).date()
        rd = dt.date(nxt, prev.month, min(prev.day, 28))
        R = roster.analyze(lg)
        me = R.get("me")
        if me and me["over"] > 0:
            cut = ", ".join(c["name"] for c in me["cuts"][:3])
            add(rd - dt.timedelta(days=14), f"Roster crunch: {me['over']} cut{'s' if me['over'] != 1 else ''} needed",
                f"With {len(me['rookies'])} incoming rookies, you'll be over the roster limit. Trade the ones with value before cutting (first in line: {cut}).",
                "#/roster", approx=True)
        mine = [p for p in (lg.me or {}).get("picks", []) if p["season"] == nxt]
        add(rd, f"{nxt} rookie draft (estimated from last year's date)",
            f"You have {len(mine)} pick{'s' if len(mine) != 1 else ''}" + (f": {', '.join(p['name'] for p in mine[:5])}" if mine else "") + ".",
            "#/draftprep", approx=True)
    ev.sort(key=lambda e: e["date"])
    week = sleeper.nfl_state().get("week")
    return {"today": today.isoformat(), "week": week, "events": ev}
