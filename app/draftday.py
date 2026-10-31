"""Draft day: the rookie draft room, live.

While the league's rookie draft runs, the page re-reads the draft from Sleeper (public and
read-only) every 15 seconds:
- Who's on the clock, and how many picks until yours.
- Board: rookies not yet taken, by value, with NFL draft-capital odds (rookies.py), the
  chance each is still there at your next pick and the one after, and who's most likely to
  take him first. Chances come from mock drafts of the picks in between: each manager takes
  the best value x their position habits x their needs, with noise (as in draftprep.py). You
  take the best value x your needs.
- Moving up: for each pick before yours, what it costs in pick value (market prices by slot,
  pickvalue.py) and the chance each of your top targets is still there at that pick.
- Moving down: for the picks just after yours, what you'd gain and the chance your targets
  last that long.
Before the draft starts (once Sleeper has the draft and its order) the same view runs from
pick 1. Replay steps through the last completed rookie draft with today's values (so it
knows how that class turned out): a way to try the page out of season.
"""
from __future__ import annotations

import datetime as dt
import math
import random
from collections import Counter, defaultdict

from . import draftprep, pickvalue, sleeper
from .league import POSITIONS

N_SIMS = 300
TOP = 40        # board players followed through the mock drafts
AHEAD = 8       # picks after yours considered for moving down
ACTIVE = ("drafting", "paused")


def _drafts(lg) -> list[dict]:
    ds = [d for d in sleeper.cached_drafts(lg.cfg["league_id"]) if not sleeper.is_startup(lg.info, d)]
    return sorted(ds, key=lambda d: (str(d.get("season")), d.get("start_time") or d.get("created") or 0))


def _order(lg, D: dict) -> dict:
    """Draft slot -> original roster_id."""
    slot_rid = {int(k): v for k, v in (D.get("slot_to_roster_id") or {}).items() if str(k).isdigit() and v}
    if not slot_rid:
        by_user = {t["owner_id"]: rid for rid, t in lg.teams.items() if t.get("owner_id")}
        slot_rid = {s: by_user[u] for u, s in (D.get("draft_order") or {}).items() if u in by_user}
    return slot_rid


def pick_order(D: dict, slot_rid: dict, made: list[dict], traded: dict, owners: dict | None = None) -> list[dict]:
    """Every pick in order: overall number, round, label, original roster, owner and the
    player taken (None while it's still to come). `owners` (pick number -> roster) fixes
    owners known from the picks themselves (a replay)."""
    st = D.get("settings") or {}
    n, rounds = st.get("teams") or len(slot_rid), st.get("rounds") or 3
    snake = D.get("type") == "snake"
    by_no = {p["pick_no"]: p for p in made}
    seq = []
    for k in range(1, n * rounds + 1):
        r, i = (k - 1) // n + 1, (k - 1) % n + 1
        orig = slot_rid.get(n + 1 - i if snake and r % 2 == 0 else i)
        p = by_no.get(k)
        owner = p["roster_id"] if p else (owners or {}).get(k) or traded.get((r, orig), orig)
        seq.append({"no": k, "round": r, "label": pickvalue.label(r, i), "orig": orig, "owner": owner,
                    "player": p["player_id"] if p else None})
    return seq


def _board(lg, season: int, taken: set, replay: bool) -> list[dict]:
    exp = max(0, lg.season - season)
    rostered = set() if replay else {a["id"] for t in lg.teams.values() for a in t["players"]}
    prospects = (lg.rookies or {}).get("prospects") or {}
    out = []
    for pid, p in lg.players_db.items():
        if p.get("years_exp") != exp or p.get("position") not in POSITIONS or pid in taken or pid in rostered:
            continue
        v = lg.values.player(pid)["value"]
        if v > 0:
            pr = prospects.get(pid) or {}
            out.append({"id": pid, "name": p.get("full_name") or pid, "pos": p["position"], "nfl_team": p.get("team"),
                        "age": p.get("age"), "value": round(v), "nfl_pick": pr.get("pick"), "hit": pr.get("hit"), "bust": pr.get("bust")})
    return sorted(out, key=lambda b: -b["value"])


def _habits(lg, before: str | None) -> dict:
    key = f"_draftday_habits:{before}"
    if key not in lg.__dict__:
        try:
            lg.__dict__[key] = draftprep.habits(draftprep._drafts_with_values(lg), before=before)
        except Exception:  # value history missing: managers pick by value and need only
            lg.__dict__[key] = {}
    return lg.__dict__[key]


def mock(lg, seq: list[dict], k0: int, end: int, board: list[dict], me: int | None, habits: dict,
         stop: int | None, skip: int | None = None, n_sims: int = N_SIMS, seed: int = 7) -> tuple[list[Counter], dict]:
    """Mock the picks seq[k0:end]. Returns (for each of those picks, how often each board
    player was still there when it came up; player -> who took him before pick `stop`).
    Pick `skip` takes nobody: a player's chance of lasting past it then means "if you take
    someone else there" (otherwise your own top choice always shows as gone)."""
    rng = random.Random(seed)
    avail = [Counter() for _ in range(end - k0)]
    taker = defaultdict(Counter)
    mine = lambda b: draftprep._choice_score(b["value"], b["pos"], None, (lg.teams.get(me) or {}).get("need_future", {}))
    for _ in range(n_sims):
        gone = set()
        for j in range(k0, end):
            left = [b for b in board if b["id"] not in gone]
            if not left:
                break
            for b in left:
                avail[j - k0][b["id"]] += 1
            if j == skip:
                continue
            o = seq[j]["owner"]
            if o == me:
                pick = max(left, key=mine)
            else:
                need = (lg.teams.get(o) or {}).get("need_future", {})
                pick = max(left, key=lambda b: draftprep._choice_score(b["value"], b["pos"], habits.get(o), need)
                           * math.exp(rng.gauss(0, 0.25)))
            if stop is not None and j < stop:
                taker[pick["id"]][o] += 1
            gone.add(pick["id"])
    return avail, taker


def analyze(lg, replay: bool = False, at: int | None = None) -> dict:
    me = lg.me["roster_id"] if lg.me else None
    ds = _drafts(lg)
    done = [d for d in ds if d.get("status") == "complete"]
    out = {"replay": replay, "me": me, "can_replay": bool(done), "status": None}
    d = (done[-1] if done else None) if replay else next((x for x in reversed(ds) if x.get("status") != "complete"), None)
    if not d:
        return out
    did = d["draft_id"]
    D = sleeper.draft(did) if replay else sleeper.live_draft(did)
    season = int(D.get("season") or d["season"])
    slot_rid = _order(lg, D)
    out.update(status=D.get("status"), draft_id=did, season=season, type=D.get("type"),
               start_time=D.get("start_time"), pick_timer=(D.get("settings") or {}).get("pick_timer"), order_set=bool(slot_rid))
    if replay:
        picks = sorted(sleeper.draft_picks(did, True), key=lambda p: p["pick_no"])
        mine = [p["pick_no"] for p in picks if p["roster_id"] == me]
        at = max(1, min(at or (mine[0] if mine else 1), len(picks)))
        made = [p for p in picks if p["pick_no"] < at]
        seq = pick_order(D, slot_rid, made, {}, {p["pick_no"]: p["roster_id"] for p in picks})
        out.update(at=at, total=len(picks), my_nos=mine)
        # Habits from drafts before this one only, so the replay doesn't peek at its own picks.
        habits = _habits(lg, dt.datetime.fromtimestamp(d["start_time"] / 1000).date().isoformat() if d.get("start_time") else None)
    else:
        made = sorted(sleeper.live_draft_picks(did), key=lambda p: p["pick_no"]) if D.get("status") in ACTIVE + ("complete",) else []
        traded = {(tp["round"], tp["roster_id"]): tp["owner_id"] for tp in sleeper.traded_picks(lg.cfg["league_id"])
                  if str(tp.get("season")) == str(season)}
        seq = pick_order(D, slot_rid, made, traded)
        habits = _habits(lg, None)
    out["poll"] = not replay and D.get("status") in ACTIVE
    name = lambda pid: (lg.players_db.get(pid) or {}).get("full_name") or pid
    manager = lambda rid: (lg.teams.get(rid) or {}).get("manager") or (f"Team {rid}" if rid else "?")
    taken = {s["player"] for s in seq if s["player"]}
    board = _board(lg, season, taken, replay)
    out["recent"] = [{"label": s["label"], "manager": manager(s["owner"]), "mine": s["owner"] == me, "id": s["player"],
                      "name": name(s["player"]), "pos": (lg.players_db.get(s["player"]) or {}).get("position"),
                      "value": round(lg.values.player(s["player"])["value"])}
                     for s in reversed([s for s in seq if s["player"]][-8:])]
    k0 = next((j for j, s in enumerate(seq) if not s["player"]), None)
    out["my_picks"] = [s["label"] for s in seq[k0 or 0:] if s["owner"] == me and not s["player"]] if k0 is not None else []
    if k0 is None or not board:
        out.update(current=None, board=board[:TOP])
        return out
    cur = seq[k0]
    out["current"] = {"label": cur["label"], "no": cur["no"], "manager": manager(cur["owner"]), "is_me": cur["owner"] == me}
    my = [j for j in range(k0, len(seq)) if seq[j]["owner"] == me]
    nxt, nxt2 = (my + [None, None])[:2]
    end = min(len(seq), max(x for x in (nxt2, (nxt or k0) + AHEAD, k0) if x is not None) + 1)
    top = board[:TOP]
    avail, taker = mock(lg, seq, k0, end, top, me, habits, nxt, skip=nxt)
    N = N_SIMS
    chance = lambda j, pid: round(avail[j - k0][pid] / N * 100) if j is not None and j < end else None
    need = (lg.teams.get(me) or {}).get("need_future", {})
    score = lambda b: draftprep._choice_score(b["value"], b["pos"], None, need)
    ranked = sorted(top, key=lambda b: -score(b))
    rank = {b["id"]: i + 1 for i, b in enumerate(ranked)}
    rows = []
    for b in top:
        t = taker.get(b["id"])
        by = t.most_common(1)[0] if t else None
        rows.append({**b, "rank": rank[b["id"]], "next": chance(nxt, b["id"]), "after": chance(nxt2, b["id"]),
                     "likely_by": manager(by[0]) if by and nxt is not None else None,
                     "likely_pct": round(by[1] / N * 100) if by else None})
    out["board"] = rows
    out["next"] = {"label": seq[nxt]["label"], "away": nxt - k0} if nxt is not None else None
    out["next2"] = {"label": seq[nxt2]["label"]} if nxt2 is not None else None
    if nxt is None:
        return out
    # A finished draft's picks no longer have market prices, so a replay uses next year's.
    curve = pickvalue.market_curve(lg, season + 1 if replay else season)[0]
    pv = lambda j: curve[min(seq[j]["no"], len(curve)) - 1]
    targets = ranked[:3]
    out["targets"] = [{"id": b["id"], "name": b["name"], "pos": b["pos"], "next": chance(nxt, b["id"])} for b in targets]
    out["pick_value"] = round(pv(nxt))
    out["up"] = [{"label": seq[j]["label"], "manager": manager(seq[j]["owner"]), "roster_id": seq[j]["owner"],
                  "cost": round(pv(j) - pv(nxt)), "chances": [chance(j, b["id"]) for b in targets]}
                 for j in range(k0, nxt) if seq[j]["owner"] != me]
    # Moving down: your pick goes to another team, which takes the best value (no habits known).
    swapped = [dict(s, owner=None) if j == nxt else s for j, s in enumerate(seq)]
    avail_d, _ = mock(lg, swapped, k0, end, top, me, habits, None)
    later = lambda j, pid: round(avail_d[j - k0][pid] / N * 100)
    out["down"] = [{"label": seq[j]["label"], "manager": manager(seq[j]["owner"]), "roster_id": seq[j]["owner"],
                    "gain": round(pv(nxt) - pv(j)), "chances": [later(j, b["id"]) for b in targets]}
                   for j in range(nxt + 1, min(end, nxt + 1 + AHEAD)) if seq[j]["owner"] != me]
    out["ref"] = [{"name": f"{season + 1} {pickvalue.ROUND_NAMES.get(r, r)} (mid)", "value": round(lg.values.pick(season + 1, r, "mid")["value"])}
                  for r in (1, 2, 3) if r <= lg.draft_rounds]
    return out
