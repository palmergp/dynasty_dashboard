"""Read-only Sleeper API client (https://docs.sleeper.com)."""
from __future__ import annotations

import httpx

from .cache import cached

BASE = "https://api.sleeper.app/v1"
LIVE_TTL = 15 * 60
PLAYERS_TTL = 24 * 3600

_client = httpx.Client(timeout=30, headers={"User-Agent": "dynasty-trade-helper/1.0"})

PLAYER_FIELDS = (
    "full_name", "first_name", "last_name", "position", "team", "age", "birth_date",
    "years_exp", "injury_status", "status", "fantasy_positions", "gsis_id", "depth_chart_order",
)


def _get(path: str):
    r = _client.get(BASE + path)
    r.raise_for_status()
    return r.json()


def league(league_id: str, force=False) -> dict:
    return cached(f"league:{league_id}", LIVE_TTL, lambda: _get(f"/league/{league_id}"), force)


def users(league_id: str, ttl=LIVE_TTL, force=False) -> list:
    return cached(f"users:{league_id}", ttl, lambda: _get(f"/league/{league_id}/users"), force)


def rosters(league_id: str, ttl=LIVE_TTL, force=False) -> list:
    return cached(f"rosters:{league_id}", ttl, lambda: _get(f"/league/{league_id}/rosters"), force)


def traded_picks(league_id: str, force=False) -> list:
    return cached(f"traded_picks:{league_id}", LIVE_TTL, lambda: _get(f"/league/{league_id}/traded_picks"), force)


def transactions(league_id: str, week: int, ttl=LIVE_TTL, force=False) -> list:
    return cached(f"tx:{league_id}:{week}", ttl, lambda: _get(f"/league/{league_id}/transactions/{week}"), force)


def matchups(league_id: str, week: int, done: bool, force=False) -> list:
    return cached(f"matchups:{league_id}:{week}", None if done else LIVE_TTL,
                  lambda: _get(f"/league/{league_id}/matchups/{week}"), force)


def cached_drafts(league_id: str, force=False) -> list:
    return cached(f"drafts:{league_id}", LIVE_TTL, lambda: _get(f"/league/{league_id}/drafts"), force)


def draft(draft_id: str, force=False) -> dict:
    return cached(f"draft:{draft_id}", LIVE_TTL, lambda: _get(f"/draft/{draft_id}"), force)


def draft_picks(draft_id: str, done: bool, force=False) -> list:
    return cached(f"draft_picks:{draft_id}", None if done else LIVE_TTL, lambda: _get(f"/draft/{draft_id}/picks"), force)


LIVE_DRAFT_TTL = 10  # seconds: a draft in progress is re-read this often at most


def live_draft(draft_id: str) -> dict:
    return cached(f"draft_live:{draft_id}", LIVE_DRAFT_TTL, lambda: _get(f"/draft/{draft_id}"))


def live_draft_picks(draft_id: str) -> list:
    return cached(f"draft_picks_live:{draft_id}", LIVE_DRAFT_TTL, lambda: _get(f"/draft/{draft_id}/picks"))


def is_startup(lg: dict, d: dict) -> bool:
    """A startup draft has far more rounds than the league's rookie drafts."""
    return (d.get("settings") or {}).get("rounds", 0) > (lg.get("settings") or {}).get("draft_rounds", 5)


def draft_in_scope(lg: dict, d: dict) -> bool:
    """False for drafts that linked history replaces: the startup-sized draft that restocked
    a restarted league with its old rosters, and linked-league drafts after the restart."""
    if lg.get("_restart") and is_startup(lg, d):
        return False
    start = d.get("start_time") or d.get("created") or 0
    return not (lg.get("_cutoff") and start >= lg["_cutoff"])


def rid(lg: dict, roster_id):
    """A season's roster_id mapped to the current league's franchise (identity unless linked)."""
    f = lg.get("_franchise")
    return f.get(roster_id, roster_id) if f and roster_id is not None else roster_id


def _remap_tx(lg: dict, tx: dict) -> dict:
    if not lg.get("_franchise"):
        return tx
    tx = dict(tx)
    tx["roster_ids"] = [rid(lg, r) for r in tx.get("roster_ids") or []]
    for k in ("adds", "drops"):
        if tx.get(k):
            tx[k] = {pid: rid(lg, r) for pid, r in tx[k].items()}
    tx["draft_picks"] = [{**dp, **{f: rid(lg, dp.get(f)) for f in ("roster_id", "owner_id", "previous_owner_id")}}
                         for dp in tx.get("draft_picks") or []]
    tx["waiver_budget"] = [{**w, "sender": rid(lg, w.get("sender")), "receiver": rid(lg, w.get("receiver"))}
                           for w in tx.get("waiver_budget") or []]
    return tx


def used_picks(league_id: str, force=False) -> dict:
    """For each completed draft in the league's history:
    (season, round, original roster) -> (player_id, is_startup_draft).

    Sleeper's pick records name the roster that *made* the pick, not the original owner.
    When the draft has no slot_to_roster_id map, we infer it: a team keeps the same
    draft_slot every round, so the original owner of slot s is the roster X whose pick
    (via traded_picks) was used at slot s in every round.
    """
    out = {}
    for lg in league_chain(league_id, force):
        lid = lg["league_id"]
        tps = traded_picks(lid, force)
        for d in cached_drafts(lid, force):
            if d.get("status") != "complete":
                continue
            if not draft_in_scope(lg, d):
                continue
            season = int(d["season"])
            startup = is_startup(lg, d)
            picks = draft_picks(d["draft_id"], True, force)
            raw_map = draft(d["draft_id"], force).get("slot_to_roster_id") or {}
            slot_map = {int(k): v for k, v in raw_map.items() if str(k).isdigit() and v}
            if not slot_map:
                slot_map = _infer_slots(season, picks, tps)
            for p in picks:
                orig = slot_map.get(p.get("draft_slot"))
                if orig and p.get("player_id"):
                    out[(season, p["round"], rid(lg, orig))] = (p["player_id"], startup)
    return out


def _infer_slots(season: int, picks: list, tps: list) -> dict:
    owner = {}  # (round, orig) -> roster that held the pick at draft time
    rosters = {p["roster_id"] for p in picks}
    rounds = {p["round"] for p in picks}
    for r in rounds:
        for x in rosters:
            owner[(r, x)] = x
    for tp in tps:
        if int(tp["season"]) == season and (tp["round"], tp["roster_id"]) in owner:
            owner[(tp["round"], tp["roster_id"])] = tp["owner_id"]
    picker = {(p["round"], p["draft_slot"]): p["roster_id"] for p in picks}
    slots = {p["draft_slot"] for p in picks}
    cand = {x: {s for s in slots if all(picker.get((r, s)) == owner[(r, x)] for r in rounds)} for x in rosters}
    assigned = {}
    changed = True
    while changed:  # propagate forced assignments
        changed = False
        for x, ss in cand.items():
            ss -= set(assigned)
            if x not in assigned.values() and len(ss) == 1:
                assigned[next(iter(ss))] = x
                changed = True
    for x, ss in cand.items():  # leftovers are ambiguous; any consistent slot is fine for valuation
        if x not in assigned.values() and ss - set(assigned):
            assigned[sorted(ss - set(assigned))[0]] = x
    return assigned


def nfl_state(force=False) -> dict:
    return cached("state:nfl", LIVE_TTL, lambda: _get("/state/nfl"), force)


def players(force=False) -> dict:
    """All NFL players, slimmed to the fields we use (the raw payload is ~15MB)."""
    skill = ("QB", "RB", "WR", "TE")

    def fetch():
        raw = _get("/players/nfl")
        out = {}
        for pid, p in raw.items():
            pos = p.get("position")
            if pos not in skill:
                # Two-way players (e.g. Travis Hunter, listed DB) keep their fantasy position.
                pos = next((fp for fp in p.get("fantasy_positions") or [] if fp in skill), pos)
            if pos in skill or pos in ("K", "DEF"):
                out[pid] = {k: p.get(k) for k in PLAYER_FIELDS}
                out[pid]["position"] = pos
        return out
    return cached("players:nfl:v3", PLAYERS_TTL, fetch, force)


# Older leagues to treat as earlier history of a league, for leagues that were restarted
# (e.g. to add teams) so Sleeper doesn't link them. league_id -> [linked league ids].
# Set from config by League.
LINKS: dict[str, list[str]] = {}


def _own_chain(league_id: str, force=False) -> list[dict]:
    chain = []
    lid = league_id
    while lid and lid != "0":
        lg = league(lid, force)
        if not lg:
            break
        chain.append(lg)
        lid = lg.get("previous_league_id")
    return chain


def league_chain(league_id: str, force=False) -> list[dict]:
    """The current league followed by each previous season's league, newest first.

    Leagues linked in LINKS (and their own previous seasons, up to the season the current
    league started) are appended as older history. Each linked season gets:
    - "_franchise": its roster_id -> the current league's roster_id, matched by owner. An
      orphaned roster keeps its last owner, so history follows each manager's franchise.
    - "_cutoff": when the current league started (its first draft). Linked activity after
      that is ignored; the old league often keeps auto-scoring after a restart.
    The current league's first season is marked "_restart", so its startup-sized draft is
    treated as a roster migration rather than a real draft.
    """
    chain = _own_chain(league_id, force)
    links = [x for x in LINKS.get(league_id) or [] if x]
    if not links or not chain:
        return chain
    chain = [dict(l) for l in chain]
    first = chain[-1]
    first["_restart"] = True
    done = first.get("status") == "complete"
    owners = {r["owner_id"]: r["roster_id"] for r in rosters(first["league_id"], None if done else LIVE_TTL, force)
              if r.get("owner_id")}
    starts = [d.get("start_time") or d.get("created") for d in cached_drafts(first["league_id"], force)]
    cutoff = min((x for x in starts if x), default=None)
    seen = {l["league_id"] for l in chain}
    for i, lid in enumerate(links):
        old = [dict(l) for l in _own_chain(lid, force)
               if l["league_id"] not in seen and int(l["season"]) <= int(first["season"])]
        last_owner = {}
        for l in reversed(old):  # oldest first, so orphans inherit the previous owner
            fmap = {}
            ttl = None if l.get("status") == "complete" else LIVE_TTL
            for r in rosters(l["league_id"], ttl, force):
                uid = r.get("owner_id") or last_owner.get(r["roster_id"])
                last_owner[r["roster_id"]] = uid
                # Managers who aren't in the current league get a franchise id of their own.
                fmap[r["roster_id"]] = owners.get(uid) or 1000 * (i + 1) + r["roster_id"]
            l["_franchise"], l["_cutoff"] = fmap, cutoff
        chain.extend(old)
        seen.update(l["league_id"] for l in old)
    return chain


def all_trades(league_id: str, force=False) -> list[dict]:
    """Completed trades across every season of the league, oldest first.

    Each trade is annotated with the season and that season's roster->user mapping,
    so trades are credited to whoever managed the team at the time.
    """
    return [tx for tx in all_transactions(league_id, force) if tx.get("type") == "trade"]


def all_transactions(league_id: str, force=False) -> list[dict]:
    """Every completed transaction (trades, waivers, free agents, commissioner moves), oldest first."""
    out = []
    for lg in league_chain(league_id, force):
        lid = lg["league_id"]
        done = lg.get("status") == "complete"
        ttl = None if done else LIVE_TTL
        owners = {rid(lg, r["roster_id"]): r.get("owner_id") for r in rosters(lid, ttl, force and not done)}
        cutoff = lg.get("_cutoff")
        for week in range(0, 19):
            for tx in transactions(lid, week, ttl, force and not done):
                if cutoff and (tx.get("status_updated") or tx.get("created") or 0) >= cutoff:
                    continue
                if tx.get("status") == "complete":
                    tx = _remap_tx(lg, dict(tx))
                    tx["season"] = lg["season"]
                    tx["league_id"] = lid
                    tx["roster_owner"] = {str(rid): owners.get(rid) for rid in tx.get("roster_ids", [])}
                    out.append(tx)
    out.sort(key=lambda t: t.get("status_updated") or t.get("created") or 0)
    return out
