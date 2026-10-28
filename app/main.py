"""FastAPI app: JSON API + static single-page UI. Run with `run.ps1` or
`.venv\\Scripts\\python -m uvicorn app.main:app --reload`."""
from __future__ import annotations

import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, drafts, opportunity, pickups, rankings, records, retro, store, suggest, trade, waivers
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
        return _state["league"]


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
            rows.append({**a, "owner": t["manager"], "owner_rid": t["roster_id"]})
    rows.sort(key=lambda a: -a["value"])
    return _clean(rows)


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
        _, hist, _ = drafts.context(lg)
        return _clean({
            "season": lg.season, "role_season": lg.opportunity["role_season"], "weeks": lg.opportunity["weeks"],
            "players": rows[:400], "shakeups": opportunity.shakeups(lg),
            "backtest": opportunity.backtest_summary(opportunity.backtest(lg, hist)),
        })
    return {**_memo("breakouts", lg, build), "me": lg.me["roster_id"] if lg.me else None, "error": lg.opportunity_error}


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
    store.set_entry(section, body.key, body.text.strip())
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
        store.set_entry("window_overrides", body.user_id, body.window)
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
    store.set_entry("overrides", body.key, body.value, subsection=sub)
    _rebuild()
    return {"ok": True, "overrides": store.load_overrides()}


@app.get("/api/overrides")
def overrides():
    return store.load_overrides()


@app.post("/api/config")
def set_config(body: dict):
    cfg = config.save(body)
    if {"league_id", "username", "linked_league_ids"} & set(body):
        league(force=True)
    else:
        _rebuild()
    return cfg


@app.post("/api/refresh")
def refresh():
    league(force=True)
    return {"ok": True, "built": _state["built"]}


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")
