"""Offseason checklist: what to do between the championship and next season, in order, with
the players and picks each step is about. Everything comes from the other reports:

- Right after the championship: players whose group is usually worth the most in winter
  (seasonal.py), and players the age curve says to sell before they get a year older.
- Before free agency (the new league year, mid-March): your players whose NFL contracts end
  this season, who can change teams (opportunity.py contracts).
- Before the NFL draft: next year's picks usually peak in the months before it
  (pickhistory.py), and picks in slots the market has overpriced or underpriced (pickvalue.py).
- Before the rookie draft: the roster crunch and taxi moves (roster.py), other teams' cut
  candidates to trade for, and the draft-day page.
- Summer: player values usually bottom out (seasonal.py), so it's a cheap time to buy;
  the buy-low list (buylow.py).
Dates marked approximate are estimates: free agency from the NFL's usual calendar, the
rookie draft from the date of the league's last one.
"""
from __future__ import annotations

import datetime as dt

from . import agenda, buylow, roster, seasonal, sleeper

WINTER = ("Nov", "Dec", "Jan", "Feb")
MIN_ASSET = 500   # players worth listing


def _asset(a: dict, note: str | None = None) -> dict:
    kind = a.get("kind") if a.get("kind") in ("player", "pick", "rookie") else "player"  # buy-low rows use "kind" for the dip type
    return {"kind": kind, "id": a["id"], "name": a["name"], "pos": a.get("pos"),
            "value": round(a["value"]), "note": note}


def _free_agency(year: int) -> dt.date:
    """The NFL's new league year: usually the second Wednesday of March."""
    d = dt.date(year, 3, 1)
    while d.weekday() != 2:
        d += dt.timedelta(days=1)
    return d + dt.timedelta(days=7)


def build(lg) -> dict:
    me = lg.me
    if not me:
        return {"phases": [], "season": lg.season}
    today = dt.date.today()
    nxt = lg.pick_seasons[0]
    st = lg.info.get("settings") or {}
    pw = st.get("playoff_week_start") or 15
    rounds = {4: 2, 6: 3, 8: 3}.get(st.get("playoff_teams") or 6, 3)
    end = agenda._week_start(lg, pw + rounds - 1)
    champ = end + dt.timedelta(days=6) if end else dt.date(lg.season + 1, 1, 10)
    off_year = champ.year
    phases = []

    def phase(key, title, day, approx, items):
        items = [i for i in items if i]
        if items:
            phases.append({"key": key, "title": title, "date": day.isoformat() if day else None, "approx": approx, "items": items})

    # ---- right after the championship
    S = lg.seasonal
    winter = []
    if S.get("groups"):
        m0 = S["month"]
        for a in me["players"]:
            if a["value"] < seasonal.MIN_VALUE:
                continue
            g = next((x for x in S["groups"] if x["pos"] == a["pos"] and x["band"] == seasonal.band(a["pos"], a["age"])), None)
            if not g or not g["index"][m0]:
                continue
            peak = max((m for m in range(12) if seasonal.MONTHS[m] in WINTER and g["index"][m]), key=lambda m: g["index"][m], default=None)
            if peak is not None and (g["index"][peak] / g["index"][m0] - 1) * 100 >= seasonal.MIN_MOVE:
                winter.append(_asset(a, f"{g['label']}s peak around {seasonal.MONTHS[peak]} "
                                        f"({(g['index'][peak] / g['index'][m0] - 1) * 100:+.0f}% vs. now)"))
    old = [_asset(a, {"sell": "Sell now", "soon": "Sell within a year"}[a["age_outlook"]["verdict"]])
           for a in me["players"] if a["value"] >= 1000 and (a.get("age_outlook") or {}).get("verdict") in ("sell", "soon")]
    phase("winter", "Right after the championship", champ, end is None, [
        {"id": "winter-sell", "title": "Sell players at their seasonal high",
         "text": "These players' position and age groups are usually worth the most this winter. Contenders reload as soon as trades reopen.",
         "assets": winter, "link": "#/players"} if winter else None,
        {"id": "age-sell", "title": "Sell before the age curve bites",
         "text": "Each gets a year older before next season, and the age curve says their value falls from here. Sell before the rookie class pushes veterans down in the spring.",
         "assets": old, "link": "#/deadline"} if old else None,
    ])

    # ---- before free agency
    expiring = []
    for a in me["players"]:
        c = ((a.get("opp") or {}).get("contract") or {})
        if a["value"] >= MIN_ASSET and c.get("end") is not None and c["end"] <= lg.season:
            expiring.append(_asset(a, c.get("leave_why") or f"Contract ends after {lg.season}"))
    phase("fa", "Before free agency", _free_agency(off_year), True, [
        {"id": "fa-contracts", "title": "Decide on players with expiring contracts",
         "text": "Their NFL contracts end this season, so free agency can move them to a new team and swing their value either way. Sell the ones whose role depends on staying put; hold the ones a move could help.",
         "assets": expiring, "link": "#/breakouts"} if expiring else None,
    ])

    # ---- before the NFL draft: picks
    picks = [p for p in me["picks"] if p["season"] == nxt]
    over = [_asset(p, f"Players taken there kept {p['kept']}% of their draft-day value") for p in picks if p.get("kept") is not None and p["kept"] <= 85]
    under = [_asset(p, f"Players taken there kept {p['kept']}% of their draft-day value") for p in picks if p.get("kept") is not None and p["kept"] >= 115]
    peak_txt = None
    try:
        from . import pickhistory
        T = pickhistory.seasonality(lg)
        best = [(t["label"], t["outlook"]["best"]) for t in T["tracks"] if t.get("outlook")]
        if best:
            peak_txt = "Next year's picks usually peak before the draft: " + ", ".join(f"{l.lower()}s in {m}" for l, m in best) + "."
    except Exception:  # pick history unavailable
        pass
    phase("nfl", f"Before the {nxt} NFL draft", agenda._nfl_draft(nxt), True, [
        {"id": "picks-sell", "title": "Sell picks in overpriced slots",
         "text": "The market has overpriced picks in these slots: players taken there kept well under their draft-day value three years later. "
                 + (peak_txt or "Sell them while pick prices are high, before the draft."),
         "assets": over, "link": "#/draftprep"} if over else None,
        {"id": "picks-keep", "title": "Keep (or buy more of) picks in underpriced slots",
         "text": "Players taken in these slots have been worth more three years later than on draft day.",
         "assets": under, "link": "#/hitrates"} if under else None,
        {"id": "picks-timing", "title": "Time pick trades", "text": peak_txt + " Rookie values settle once NFL landing spots are known.",
         "assets": [_asset(p) for p in picks], "link": "#/draftprep"} if peak_txt and not over else None,
    ])

    # ---- before the rookie draft
    R = roster.analyze(lg)
    mine = R.get("me") or {}
    last = next((d for d in reversed(sleeper.cached_drafts(lg.cfg["league_id"]))
                 if d.get("start_time") and not sleeper.is_startup(lg.info, d)), None)
    rd = None
    if last:
        prev = dt.datetime.fromtimestamp(last["start_time"] / 1000).date()
        rd = dt.date(nxt, prev.month, min(prev.day, 28))
    cuts = [dict(c, note="trade first" if c["value"] >= roster.TRADE_FIRST else "cut") for c in mine.get("cuts", [])]
    likely = [{**c, "note": f"{c['manager']} may have to cut him"} for c in R.get("likely_cuts", []) if c["kind"] == "player" and c["value"] >= MIN_ASSET]
    phase("rookie", f"Before the {nxt} rookie draft", rd, True, [
        {"id": "crunch", "title": f"Clear {mine['over']} roster spot{'s' if mine['over'] != 1 else ''}",
         "text": "With your incoming rookies you'll be over the roster limit. Package the ones with value two-for-one before cutting anyone.",
         "assets": [_asset(c, c["note"]) for c in cuts], "link": "#/roster"} if mine.get("over", 0) > 0 else None,
        {"id": "taxi", "title": "Move players off and onto taxi",
         "text": "Aging off taxi (they need active spots): " + (", ".join(a["name"] for a in mine["promoted"]) or "nobody")
                 + ". Moving to taxi: " + (", ".join(a["name"] for a in mine["to_taxi"]) or "nobody") + ".",
         "assets": [], "link": "#/roster"} if mine.get("promoted") or mine.get("to_taxi") else None,
        {"id": "cut-targets", "title": "Trade for other teams' cut candidates",
         "text": "These teams will be over the roster limit too. Their cut candidates are cheap now and some will reach waivers.",
         "assets": [_asset(c, c["note"]) for c in likely[:6]], "link": "#/roster"} if likely else None,
        {"id": "draftday", "title": "Get ready for draft day",
         "text": f"You have {len(picks)} pick{'s' if len(picks) != 1 else ''}. Once Sleeper has the draft, Draft day follows it live: the board, your next pick and what moving up or down costs.",
         "assets": [], "link": "#/draftday"},
    ])

    # ---- summer
    low = None
    if S.get("groups"):
        counts = {}
        for g in S["groups"]:
            counts[g["low"]] = counts.get(g["low"], 0) + 1
        low = max(counts, key=counts.get)
    buys = []
    try:
        buys = [_asset(r, f"{r['owner'] or 'free agent'}") for r in buylow.analyze(lg)["players"] if r.get("owner_rid") != me["roster_id"]][:6]
    except Exception:  # value history missing
        pass
    month = seasonal.MONTHS.index(low) + 1 if low else 6
    phase("summer", "Summer", dt.date(nxt, month, 15), True, [
        {"id": "summer-buy", "title": f"Buy while values are low{f' (usually {low})' if low else ''}",
         "text": "Most positions and ages dip in late spring, when the new rookie class takes the spotlight, then climb into the season. "
                 "A good time to buy the players you want for next year." + (" Today's buy-low list is a starting point." if buys else ""),
         "assets": buys, "link": "#/buylow"},
    ])
    phases.sort(key=lambda p: p["date"] or "9999")
    return {"season": lg.season, "next_draft": nxt, "today": today.isoformat(), "phases": phases}
