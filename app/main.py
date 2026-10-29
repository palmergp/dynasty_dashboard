"""FastAPI app: JSON API + static single-page UI. Run with `run.ps1` or
`.venv\\Scripts\\python -m uvicorn app.main:app --reload`."""
from __future__ import annotations

import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, draftprep, drafts, feed, opportunity, pickups, rankings, records, retro, season, store, suggest, trade, waivers
from .config import ROOT
from .league import League
from .values import SOURCE_LABELS

app = FastAPI(title="Dynasty Trade Helper")
_lock = threading.Lock()
_state: dict = {"league": None, "built": 0.0}


def league(force: bool = False) -> League:
    with _lock:
        if force or _state["league"] is None:
            _state["league"] = League(config.load(), force=force)
            _state["built"] = time.time()
            _remember_name(_state["league"])
        return _state["league"]


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


@app.post("/api/evaluate")
def evaluate(body: TradeIn):
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
    res = trade.evaluate(lg, body.a_rid, resolve(body.a_gives, body.a_rid), body.b_rid, resolve(body.b_gives, body.b_rid))
    return _clean(res)


@app.get("/api/suggestions")
def suggestions(partner: int | None = None, limit: int = 4):
    lg = league()
    if not lg.me:
        raise HTTPException(400, "Your username wasn't found in the league; check Settings.")
    if partner is not None:
        return _clean(suggest.for_partner(lg, partner, limit))
    return _clean(suggest.partners(lg, min(limit, 3)))


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
    return _memo("season", lg, lambda: season.simulate(lg))


@app.get("/api/season")
def season_report():
    lg = league()
    return {**_clean(_season(lg)), "me": lg.me["roster_id"] if lg.me else None}


@app.get("/api/draft-prep")
def draft_prep():
    lg = league()
    return _memo("draftprep", lg, lambda: _clean(draftprep.analyze(lg, _season(lg))))


@app.get("/api/status")
def status():
    return {"built": _state["built"], "auto_refresh_minutes": config.load().get("auto_refresh_minutes")}


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


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")
