"""FastAPI app: JSON API + static single-page UI. Run with `run.ps1` or
`.venv\\Scripts\\python -m uvicorn app.main:app --reload`."""
from __future__ import annotations

import socket
import threading
import time

import segno
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (agenda, buylow, calcfit, checks, config, counter, deadline, draftday, draftprep, drafts, feed, future, health, lineup, live, market,
               goalplan, offseason, opportunity, pickhistory, pickups, pitch, plan, playerstats, rankings, recap, records, retro, rookieclass, roster, season, seasonal,
               secondhalf, store, suggest, target, track, trade, waivers, wrapped)
from .config import ROOT
from .league import League
from .values import SOURCE_LABELS

app = FastAPI(title="Front Office")
_lock = threading.Lock()
_state: dict = {"league": None, "built": 0.0}


def league(force: bool = False) -> League:
    with _lock:
        if force or _state["league"] is None:
            _state["league"] = League(config.load(), force=force)
            _state["built"] = time.time()
            _remember_name(_state["league"])
            _snapshot(_state["league"])
        return _state["league"]


def _snapshot(lg):
    """This week's track-record snapshot (once a week; a no-op the rest of the time)."""
    try:
        track.snapshot(lg)
    except Exception as e:  # never block a build over it
        print(f"track snapshot failed: {e}")


def _remember_name(lg):
    """Label the league's saved profile with its name (shown in Settings › Saved leagues)."""
    cfg = config.load()
    lid = str(cfg["league_id"])
    prof = cfg["profiles"].get(lid, {})
    if prof.get("name") != lg.info.get("name") or not all(k in prof for k in config.PROFILE_KEYS):
        config.save({"profiles": {**cfg["profiles"], lid: {**prof, "name": lg.info.get("name")}}})


def _auto_refresh():
    """Rebuild every few minutes. Cached data is only re-downloaded once its normal time-to-live
    has passed (live Sleeper data: 15 minutes), so this is cheap."""
    while True:
        minutes = config.load().get("auto_refresh_minutes") or 0
        time.sleep(max(minutes, 1) * 60)
        if minutes and _state["league"] is not None:
            try:
                _rebuild()
            except Exception as e:  # keep serving the last good build
                print(f"auto-refresh failed: {e}")


@app.on_event("startup")
def _start_refresher():
    threading.Thread(target=_auto_refresh, daemon=True).start()


def _rebuild():
    """Rebuild from cache after a user edit (notes, overrides, settings). Fast: no network."""
    with _lock:
        _state["league"] = League(config.load())
        _state["built"] = time.time()
    _snapshot(_state["league"])


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, set):
        return sorted(obj)
    return obj


def _team_summary(lg, t):
    keys = ("roster_id", "owner_id", "manager", "team_name", "avatar", "wins", "losses", "ties", "fpts",
            "window", "window_source", "contend_score", "starter_redraft", "dynasty_total", "pick_total",
            "avg_age_weighted", "needs", "surplus", "need_now", "need_future", "depth_z",
            "franchise_value", "franchise_score", "franchise_rank")
    out = {k: t.get(k) for k in keys}
    tend = lg.tendencies.get(t["owner_id"]) or {}
    out["tags"] = tend.get("tags", [])
    out["n_trades"] = tend.get("n_trades", 0)
    out["is_me"] = lg.me is not None and t["roster_id"] == lg.me["roster_id"]
    return out


@app.get("/api/overview")
def overview():
    lg = league()
    return _clean({
        "league": {"name": lg.info.get("name"), "season": lg.season, "teams": len(lg.teams),
                   "superflex": lg.superflex, "slots": lg.slots, "weeks_played": lg.weeks_played,
                   "pick_seasons": lg.pick_seasons, "ppr": (lg.info.get("scoring_settings") or {}).get("rec"),
                   "history": lg.history},
        "me": lg.me["roster_id"] if lg.me else None,
        "teams": [_team_summary(lg, t) for t in lg.team_list()],
        "sources": {s: {"label": SOURCE_LABELS[s], "players": len(v), "weight": lg.values.weights.get(s)}
                    for s, v in lg.values.by_source.items()},
        "source_errors": lg.values.errors,
        "built": _state["built"],
        "config": lg.cfg,
    })


@app.get("/api/team/{rid}")
def team(rid: int):
    lg = league()
    t = lg.teams.get(rid)
    if not t:
        raise HTTPException(404, "No such team")
    out = _team_summary(lg, t)
    out.update({k: t[k] for k in ("players", "picks", "starters", "sell_candidates", "pos_now", "pos_future")})
    out["tendencies"] = lg.tendencies.get(t["owner_id"]) or {}
    out["manager_note"] = lg.user_data["manager_notes"].get(t["owner_id"] or "", "")
    out["trades"] = [x for x in lg.parsed_trades if any(s["user_id"] == t["owner_id"] for s in x["sides"])]
    return _clean(out)


@app.get("/api/players")
def players():
    lg = league()
    rows = []
    for t in lg.teams.values():
        for a in t["players"]:
            o = a.get("age_outlook")
            rows.append({**a, "owner": t["manager"], "owner_rid": t["roster_id"],
                         "age_outlook": {"verdict": o["verdict"], "y1_pct": o["y1_pct"]} if o else None})
    rows.sort(key=lambda a: -a["value"])
    return _clean(rows)


@app.get("/api/player/{pid}")
def player(pid: str):
    lg = league()
    if pid not in lg.players_db:
        raise HTTPException(404, "No such player")
    from .league import player_notes
    owner = next((t for t in lg.teams.values() for a in t["players"] if a["id"] == pid), None)
    a = next((x for x in owner["players"] if x["id"] == pid), None) if owner else lg.annotate(lg.player_asset(pid))
    if not owner:
        a["notes"] = player_notes(a, lg)
    A = lg.aging
    hist = A["hist"]
    series = hist["values"].get(pid) or [None] * len(hist["dates"])
    return _clean({
        "player": a, "owner": owner["manager"] if owner else None, "owner_rid": owner["roster_id"] if owner else None,
        "is_mine": bool(owner and lg.me and owner["roster_id"] == lg.me["roster_id"]),
        "dates": hist["dates"], "history": [round(v) if v is not None else None for v in series],
        "outlook": a.get("age_outlook"),
        "curve": [{"age": age, "ratio": r["ratio"], "n": r["n"]} for age, r in sorted((A["curve"].get(a["pos"]) or {}).items())],
    })


@app.get("/api/player/{pid}/stats")
def player_stats(pid: str):
    """His game log and season totals (this season, or last until week 1 is done)."""
    lg = league()
    if pid not in lg.players_db:
        raise HTTPException(404, "No such player")
    S = _memo("season-stats", lg, lambda: playerstats.build(lg, playerstats.stats_season(lg)))
    return _clean(playerstats.player(lg, pid, S) or {"season": S["season"], "games": None})


@app.get("/api/picks")
def picks():
    lg = league()
    rows = [{**p, "owner": t["manager"]} for t in lg.teams.values() for p in t["picks"]]
    rows.sort(key=lambda a: (a["season"], a["round"], -a["value"]))
    return _clean(rows)


class AssetRef(BaseModel):
    kind: str
    id: str


class TradeIn(BaseModel):
    a_rid: int
    a_gives: list[AssetRef]
    b_rid: int
    b_gives: list[AssetRef]


def _trade(body: TradeIn):
    """(league, A's assets, B's assets) for a proposed trade, validated."""
    lg = league()
    if body.a_rid not in lg.teams or body.b_rid not in lg.teams or body.a_rid == body.b_rid:
        raise HTTPException(400, "Pick two different teams")

    def resolve(refs, rid):
        out = []
        for r in refs:
            a = lg.asset(r.kind, r.id)
            if not a or a["roster_id"] != rid:
                raise HTTPException(400, f"Asset {r.id} is not on that roster")
            out.append(a)
        return out
    return lg, resolve(body.a_gives, body.a_rid), resolve(body.b_gives, body.b_rid)


@app.post("/api/evaluate")
def evaluate(body: TradeIn):
    lg, a_gives, b_gives = _trade(body)
    return _clean(trade.evaluate(lg, body.a_rid, a_gives, body.b_rid, b_gives))


class PlanTrade(BaseModel):
    b_rid: int
    a_gives: list[AssetRef]
    b_gives: list[AssetRef]


class PlanIn(BaseModel):
    trades: list[PlanTrade]


@app.post("/api/plan")
def trade_plan(body: PlanIn):
    """Several of your trades together: conflicts, and the combined effect on your team."""
    lg = league()
    if not lg.me:
        raise HTTPException(400, "Your username wasn't found in the league; check Settings.")
    return _clean(plan.run(lg, [t.model_dump() for t in body.trades]))


@app.post("/api/plan/next")
def plan_next(body: PlanIn):
    """Trade suggestions assuming the plan's trades go through."""
    lg = league()
    if not lg.me:
        raise HTTPException(400, "Your username wasn't found in the league; check Settings.")
    return _clean(plan.next_trades(lg, [t.model_dump() for t in body.trades]))


@app.get("/api/plan/propose")
def plan_propose(goal: str = "1"):
    """A sample plan: a few trades chosen to make you good in a target year."""
    lg = league()
    if not lg.me:
        raise HTTPException(400, "Your username wasn't found in the league; check Settings.")
    if goal not in goalplan.GOALS:
        raise HTTPException(400, f"goal must be one of {', '.join(goalplan.GOALS)}")
    return _memo(f"goalplan:{goal}", lg, lambda: _clean(goalplan.propose(lg, goal)))


@app.post("/api/trade-impact")
def trade_impact(body: TradeIn):
    """Both teams' playoff odds and projected draft slot before and after the trade."""
    lg, a_gives, b_gives = _trade(body)
    return _clean(season.trade_impact(lg, body.a_rid, a_gives, body.b_rid, b_gives) or {"teams": []})


@app.post("/api/pitch")
def trade_pitch(body: TradeIn):
    """A message to send with the offer, from Team A to Team B."""
    lg, a_gives, b_gives = _trade(body)
    if not a_gives or not b_gives:
        raise HTTPException(400, "Add assets to both sides first")
    return pitch.write(lg, trade.evaluate(lg, body.a_rid, a_gives, body.b_rid, b_gives))


@app.post("/api/counter")
def counter_offer(body: TradeIn):
    """Smallest changes that make a proposed trade work for both sides (from team A's side)."""
    lg = league()
    if body.a_rid not in lg.teams or body.b_rid not in lg.teams or body.a_rid == body.b_rid:
        raise HTTPException(400, "Pick two different teams")
    find = lambda refs, rid: [a for r in refs for a in [lg.asset(r.kind, r.id)] if a and a["roster_id"] == rid]
    res = counter.fix(lg, body.a_rid, find(body.a_gives, body.a_rid), body.b_rid, find(body.b_gives, body.b_rid))
    slim = lambda xs: [{"kind": a["kind"], "id": a["id"], "name": a["name"]} for a in xs]
    for o in res["options"]:
        o["a_gives"], o["b_gives"] = slim(o["a_gives"]), slim(o["b_gives"])
    return _clean(res)


@app.get("/api/suggestions")
def suggestions(partner: int | None = None, limit: int = 4):
    lg = league()
    if not lg.me:
        raise HTTPException(400, "Your username wasn't found in the league; check Settings.")
    if partner is not None:
        out = suggest.for_partner(lg, partner, limit)
        groups = [(partner, out)]
    else:
        out = suggest.partners(lg, min(limit, 3))
        groups = [(p["roster_id"], p["suggestions"]) for p in out]
    try:
        track.log_suggestions(lg, groups)
    except Exception as e:  # the log is a record only
        print(f"suggestion log failed: {e}")
    return _clean(out)


@app.get("/api/drafts")
def draft_report():
    lg = league()
    memo = _state.get("drafts")
    if not memo or memo[0] is not lg:
        memo = (lg, _clean(drafts.analyze(lg)))
        _state["drafts"] = memo
    return {**memo[1], "me": lg.me["roster_id"] if lg.me else None}


@app.get("/api/rankings")
def rankings_report():
    lg = league()
    memo = _state.get("rankings")
    if not memo or memo[0] is not lg:
        memo = (lg, _clean(rankings.analyze(lg)))
        _state["rankings"] = memo
    return {**memo[1], "me": lg.me["roster_id"] if lg.me else None}


@app.get("/api/waivers")
def waiver_report():
    lg = league()
    memo = _state.get("waivers")
    if not memo or memo[0] is not lg:
        memo = (lg, _clean(waivers.analyze(lg)))
        _state["waivers"] = memo
    return {**memo[1], "me": lg.me["roster_id"] if lg.me else None}


def _memo(name, lg, fn):
    memo = _state.get(name)
    if not memo or memo[0] is not lg:
        memo = (lg, fn())
        _state[name] = memo
    return memo[1]


@app.get("/api/pickups")
def pickup_report():
    lg = league()
    if not lg.me:
        raise HTTPException(400, "Your username wasn't found in the league; check Settings.")
    w = _memo("waivers", lg, lambda: _clean(waivers.analyze(lg)))
    out = _memo("pickups", lg, lambda: _clean(pickups.suggest(lg, w)))
    return {**out, "error": lg.opportunity_error}


@app.get("/api/breakouts")
def breakout_report():
    lg = league()

    def build():
        owner = {a["id"]: t for t in lg.teams.values() for a in t["players"]}
        rows = []
        for pid, o in lg.opportunity["players"].items():
            t = owner.get(pid)
            a = next((x for x in t["players"] if x["id"] == pid), None) if t else lg.annotate(lg.player_asset(pid))
            if o["breakout"] < 5 and a["value"] < 300:
                continue
            rows.append({**a, "owner_rid": t["roster_id"] if t else None, "owner": t["manager"] if t else None,
                         "owner_window": t["window"] if t else None})
        rows.sort(key=lambda r: -r["breakout"])
        return _clean({
            "season": lg.season, "role_season": lg.opportunity["role_season"], "weeks": lg.opportunity["weeks"],
            "players": rows[:400], "shakeups": opportunity.shakeups(lg),
        })
    return {**_memo("breakouts", lg, build), "me": lg.me["roster_id"] if lg.me else None, "error": lg.opportunity_error}


@app.get("/api/backtest")
def backtest_report():
    """Separate from /api/breakouts: the first run downloads several seasons of history."""
    lg = league()
    return _memo("backtest", lg, lambda: _clean(opportunity.backtest_report(lg)))


def _season(lg):
    return lg.sim or _memo("season", lg, lambda: season.simulate(lg))


@app.get("/api/season")
def season_report():
    lg = league()
    return {**_clean(_season(lg)), "me": lg.me["roster_id"] if lg.me else None}


@app.get("/api/draft-prep")
def draft_prep():
    lg = league()
    return _memo("draftprep", lg, lambda: _clean(draftprep.analyze(lg, _season(lg))))


@app.get("/api/wrapped")
def wrapped_seasons():
    """Seasons with games to recap, newest first."""
    lg = league()
    return {"seasons": _memo("wrapped-seasons", lg, lambda: wrapped.seasons(lg))}


@app.get("/api/wrapped/{season}")
def wrapped_season(season: int):
    """One season's story in stats: the wrapped slides and the dashboard behind them."""
    lg = league()
    out = _memo(f"wrapped:{season}", lg, lambda: _clean(wrapped.analyze(lg, season)))
    if not out:
        raise HTTPException(404, f"No games found for {season}.")
    return out


@app.get("/api/rookie-classes")
def rookie_classes():
    """The next two rookie classes: position make-up vs. past classes, and what your picks
    in each are likely to land (KTC devy rankings + mock drafts)."""
    lg = league()
    if not lg.me:
        raise HTTPException(400, "Your username wasn't found in the league; check Settings.")
    try:
        return _memo("rookieclasses", lg, lambda: _clean(rookieclass.analyze(lg, _season(lg))))
    except Exception as e:  # KTC's devy page is an extra
        return {"classes": [], "error": f"{type(e).__name__}: {e}"}


@app.get("/api/deadline")
def deadline_report():
    lg = league()
    if not lg.me:
        raise HTTPException(400, "Your username wasn't found in the league; check Settings.")
    return _memo("deadline", lg, lambda: _clean(deadline.analyze(lg, _season(lg))))


@app.get("/api/buylow")
def buylow_report():
    lg = league()
    return _memo("buylow", lg, lambda: _clean(buylow.analyze(lg)))


@app.get("/api/future")
def future_report():
    lg = league()
    return _memo("future", lg, lambda: _clean(future.analyze(lg)))


@app.get("/api/pick-timing")
def pick_timing():
    lg = league()
    return _memo("picktiming", lg, lambda: _clean(pickhistory.seasonality(lg)))


@app.get("/api/league-prices")
def league_prices():
    lg = league()
    return _memo("prices", lg, lambda: _clean(market.analyze(lg)))


@app.get("/api/target")
def target_report(year: int | None = None):
    lg = league()
    if not lg.me:
        raise HTTPException(400, "Your username wasn't found in the league; check Settings.")
    return _memo(f"target:{year}", lg, lambda: _clean(target.analyze(lg, year)))


@app.get("/api/calculators")
def calculators():
    lg = league()
    return {**_clean(lg.calcfit), "error": lg.calcfit_error}


@app.get("/api/scout")
def scout(b: int, a: int | None = None):
    """Team B as a trade partner for team A (default: you): playoff odds, the calculator their
    trades lean toward, and A's assets it rates above the consensus and B's it rates below."""
    lg = league()
    them = lg.teams.get(b)
    if not them:
        raise HTTPException(404, "No such team")
    mine = lg.teams.get(a) if a is not None else lg.me
    cf = next((m for m in lg.calcfit["managers"] if m["roster_id"] == b), None)
    try:
        odds = next((t for t in _season(lg)["teams"] if t["roster_id"] == b), None)
    except Exception:  # odds are a bonus on this card
        odds = None
    gaps = calcfit.gaps(lg, them, mine["players"] + mine["picks"], them["players"] + them["picks"], limit=6) if mine and mine is not them else None
    return _clean({
        "calc": {k: cf[k] for k in ("lean", "strength", "n", "avg_gain")} if cf else None,
        "min_trades": lg.calcfit.get("min_trades"), "calc_error": lg.calcfit_error, "gaps": gaps,
        "odds": {k: odds[k] for k in ("playoff_pct", "title_pct", "proj_wins", "avg_slot")} if odds else None,
    })


@app.get("/api/checks")
def model_checks():
    lg = league()
    return _memo("checks", lg, lambda: _clean(checks.analyze(lg)))


@app.get("/api/recap")
def weekly_recap(week: int | None = None):
    lg = league()
    return _memo(f"recap:{week}", lg, lambda: _clean(recap.analyze(lg, week)))


@app.get("/api/rookie-hits")
def rookie_hits():
    """Rookie pick hit rates by round and position, and how long value lasts by position.
    The first run downloads about 26 seasons of nflverse stats and DP's July value files."""
    lg = league()
    if lg.rookies is None:
        raise HTTPException(503, f"Couldn't load rookie history: {lg.rookies_error}")
    return _memo("rookies", lg, lambda: _clean(lg.rookies))


@app.get("/api/secondhalf")
def second_half(roster_id: int | None = None):
    """Second-half outlook and win-now trade targets for a team (default: yours)."""
    lg = league()
    return _memo(f"secondhalf:{roster_id}", lg,
                 lambda: _clean({**secondhalf.targets(lg, roster_id), "deadline": deadline._deadline(lg)}))


@app.get("/api/track-record")
def track_record():
    """How the app's start/sit, second-half, value and trade calls have turned out."""
    lg = league()
    return _memo("track", lg, lambda: _clean(track.analyze(lg)))


@app.get("/api/draftday")
def draft_day(replay: bool = False, at: int | None = None):
    """The rookie draft room: live while the draft runs (not memoized), or a replay of the last one."""
    lg = league()
    if replay:
        return _memo(f"draftday:{at}", lg, lambda: _clean(draftday.analyze(lg, True, at)))
    return _clean(draftday.analyze(lg))


@app.get("/api/offseason")
def offseason_checklist():
    lg = league()
    return _memo("offseason", lg, lambda: _clean(offseason.build(lg)))


@app.get("/api/matchup")
def live_matchup(roster_id: int | None = None, week: int | None = None):
    """A matchup with live points, game status, win chance and big plays. The current week
    isn't memoized: its data refreshes on short timers while games are on."""
    lg = league()
    if week is None or week == lineup.current_week(lg):
        return _clean(live.analyze(lg, roster_id, week))
    return _memo(f"matchup:{roster_id}:{week}", lg, lambda: _clean(live.analyze(lg, roster_id, week)))


@app.get("/api/lineup")
def weekly_lineup(roster_id: int | None = None, week: int | None = None):
    """Start/sit for a team this week (default: yours)."""
    lg = league()
    return _memo(f"lineup:{roster_id}:{week}", lg, lambda: _clean(lineup.analyze(lg, roster_id, week)))


@app.get("/api/roster-room")
def roster_room():
    lg = league()
    return _memo("roster", lg, lambda: _clean(roster.analyze(lg)))


@app.get("/api/seasonal")
def player_seasons():
    """Dynasty value by calendar month for each position and age group, and when your
    players are usually worth the most."""
    lg = league()

    def build():
        S = lg.seasonal
        mine = []
        for a in (lg.me or {}).get("players", []):
            o = seasonal.outlook(S, a["pos"], a["age"]) if a["value"] >= seasonal.MIN_VALUE else None
            if o:
                mine.append({"id": a["id"], "name": a["name"], "pos": a["pos"], "age": a["age"], "value": a["value"],
                             **{k: o[k] for k in ("group", "best", "best_pct", "worst", "worst_pct")}})
        return _clean({**S, "mine": sorted(mine, key=lambda m: -m["best_pct"])})
    return _memo("seasonal", lg, build)


@app.get("/api/calendar")
def season_calendar():
    lg = league()
    return _memo("calendar", lg, lambda: _clean(agenda.build(lg, _season(lg))))


@app.get("/api/health")
def data_health():
    lg = league()
    return {**_clean(health.report(lg)), "built": _state["built"]}


@app.get("/api/status")
def status():
    return {"built": _state["built"], "auto_refresh_minutes": config.load().get("auto_refresh_minutes"), "version": _ui_version()}


def _ui_version() -> int:
    """Changes whenever the page's code changes, so an open tab can tell it's running an old copy."""
    return int(max((ROOT / "static" / f).stat().st_mtime for f in ("index.html", "app.js", "styles.css")))


def _lan_ip() -> str | None:
    """This computer's address on the local network (the interface that routes outward).
    Connecting a UDP socket sends nothing; it only picks the route."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


@app.get("/api/phone")
def phone(request: Request):
    """The address to open on a phone on the same Wi-Fi, a QR code for it, and whether the
    server is actually listening there (run.ps1 -LocalOnly or a 127.0.0.1 uvicorn isn't)."""
    ip = _lan_ip()
    port = request.url.port or 80
    if not ip:
        return {"url": None, "reachable": False, "svg": None}
    try:
        socket.create_connection((ip, port), timeout=0.5).close()
        reachable = True
    except OSError:
        reachable = False
    url = f"http://{ip}:{port}"
    return {"url": url, "reachable": reachable, "svg": segno.make(url, error="m").svg_inline(scale=5, border=2, light="#fff")}


@app.get("/api/feed")
def feed_report():
    lg = league()
    return _clean(feed.changes(lg))


@app.post("/api/feed/seen")
def feed_seen():
    feed.mark_seen(league())
    return {"ok": True}


@app.get("/api/trade-review")
def trade_review():
    lg = league()
    out = _memo("retro", lg, lambda: _clean(retro.analyze(lg)))
    return {**out, "me": lg.me["owner_id"] if lg.me else None}


@app.get("/api/records")
def record_book():
    lg = league()
    out = _memo("records", lg, lambda: _clean(records.analyze(lg)))
    return {**out, "me": lg.me["owner_id"] if lg.me else None}


@app.get("/api/trades")
def trades():
    return _clean(list(reversed(league().parsed_trades)))


class NoteIn(BaseModel):
    kind: str  # manager | player
    key: str
    text: str


@app.post("/api/notes")
def notes(body: NoteIn):
    section = {"manager": "manager_notes", "player": "player_notes"}.get(body.kind)
    if not section:
        raise HTTPException(400, "kind must be manager or player")
    store.set_entry(league().cfg["league_id"], section, body.key, body.text.strip())
    _rebuild()
    return {"ok": True}


class WindowIn(BaseModel):
    user_id: str
    window: str | None  # contend | middle | rebuild | None (auto)


@app.post("/api/window")
def window(body: WindowIn):
    if body.window not in (None, "", "contend", "middle", "rebuild"):
        raise HTTPException(400, "bad window")
    lg = league()
    if lg.me and body.user_id == lg.me["owner_id"]:
        config.save({"my_strategy": body.window or "auto"})
    else:
        store.set_entry(lg.cfg["league_id"], "window_overrides", body.user_id, body.window)
    _rebuild()
    return {"ok": True}


class OverrideIn(BaseModel):
    kind: str  # player | pick
    key: str   # sleeper id, or "2027-1" / "1" for picks
    value: float | None


@app.post("/api/override")
def override(body: OverrideIn):
    sub = {"player": "players", "pick": "pick_multipliers"}.get(body.kind)
    if not sub:
        raise HTTPException(400, "kind must be player or pick")
    lid = league().cfg["league_id"]
    store.set_entry(lid, "overrides", body.key, body.value, subsection=sub)
    _rebuild()
    return {"ok": True, "overrides": store.load_overrides(lid)}


@app.get("/api/overrides")
def overrides():
    return store.load_overrides(league().cfg["league_id"])


@app.post("/api/config")
def set_config(body: dict):
    keys = ("league_id", "username", "linked_league_ids")
    new, old = config.merged(body), config.load()
    if any(new.get(k) != old.get(k) for k in keys):
        # Load the new league before saving, so a bad ID doesn't leave the app broken.
        # Cached data is reused; Refresh forces a re-download.
        try:
            lg = League(new)
        except Exception as e:
            why = (f"Sleeper has no league with ID {new['league_id']}. Check the ID"
                   if "404" in str(e) or "no league" in str(e) else str(e))
            raise HTTPException(400, f"Couldn't load that league, so nothing was saved. {why}.")
        cfg = config.save(body)
        config.save({"profiles": {**cfg["profiles"], str(cfg["league_id"]): {
            **cfg["profiles"].get(str(cfg["league_id"]), {}), "name": lg.info.get("name")}}})
        with _lock:
            _state["league"], _state["built"] = lg, time.time()
    else:
        cfg = config.save(body)
        _rebuild()
    lg = league()
    user, name = cfg["username"], lg.info.get("name")
    warning = None if lg.me else f"{user} isn't a manager in {name}; check the username."
    return {"config": cfg, "league": lg.info.get("name"), "season": lg.season, "teams": len(lg.teams), "warning": warning}


@app.post("/api/refresh")
def refresh():
    league(force=True)
    return {"ok": True, "built": _state["built"]}


@app.middleware("http")
async def revalidate_pages(request, call_next):
    """The page and its scripts must be rechecked on every load: without this, browsers
    (and home-screen apps) keep running an old app.js against a newer server. Unchanged
    files still come back as a quick 304 through their ETag."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")
