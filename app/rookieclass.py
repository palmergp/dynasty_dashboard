"""Future rookie classes: what each upcoming class is heavy or light in, and what your picks in
it are likely to land.

- Prospects: KeepTradeCut's devy rankings (the top 200 college players, each with a projected
  draft year and a superflex and 1QB value), put on the app's scale through KTC's mapper.
- Make-up: a class's top 12 and top 24 by value are its projected rookie-draft 1st and 2nd
  rounds (for this league's team count). Positions are compared with past classes (each July's
  DynastyProcess values after the NFL draft, 2019 on: rookies.py) by count and by share of the
  top-24 value. Shares are compared rather than totals because KTC prices a class that's years
  away lower, which would make every later class look weak.
- Your picks: mock drafts of the class. Draft orders for next year's draft come from the season
  simulation; for the year after, from projected lineup strength the season before (future.py)
  with noise. Every manager (you too) takes the best value x their future positional need x
  their draft habits (draftprep), with some randomness. Result: how often each prospect is still
  there at your pick, and how often at least one first-round talent at a position is.
- Classes two or more drafts out are early guesses: prospects' values move a lot in a college
  season, and none has an NFL team or draft capital yet.
"""
from __future__ import annotations

import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict

from . import draftprep, future
from .cache import cached
from .league import POSITIONS
from .values import _http

DEVY_URL = "https://keeptradecut.com/devy-rankings"
N_MOCKS = 300
CLASSES = 2          # upcoming classes shown (later ones are too thin and too early)
SHARE_GAP = 5        # percentage points of top-24 value vs. a typical class: heavy / light
ORDER_NOISE = 0.15   # spread on projected strength when ordering a later draft


def devy(superflex: bool) -> list[dict]:
    """KTC devy rankings: [{id, name, pos, college, year, value}] on KTC's own scale."""
    def fetch():
        html = _http.get(DEVY_URL).text
        m = re.search(r'<script[^>]*id="ktc-players"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            raise RuntimeError("KTC devy page layout changed: ktc-players block not found")
        return [{"id": str(p["playerID"]), "name": p["playerName"], "pos": p["position"], "college": p.get("team"),
                 "year": p.get("draftYear"), "sf": (p.get("superflexValues") or {}).get("value") or 0,
                 "oneqb": (p.get("oneQBValues") or {}).get("value") or 0} for p in json.loads(m.group(1))]
    rows = cached("ktc:devy", 24 * 3600, fetch)
    return [{**{k: r[k] for k in ("id", "name", "pos", "college", "year")}, "value": r["sf" if superflex else "oneqb"]}
            for r in rows if r["pos"] in POSITIONS and r.get("year")]


def typical(rookies: dict | None, n: int) -> dict | None:
    """Average past class: players per position in the top n and top 2n, and share of top-2n value."""
    if not rookies or not rookies.get("picks"):
        return None
    by = defaultdict(list)
    for p in rookies["picks"]:
        by[p["cls"]].append(p)
    r1, r12, share = defaultdict(list), defaultdict(list), defaultdict(list)
    for ps in by.values():
        ps = sorted(ps, key=lambda p: -p["value"])[:2 * n]
        if len(ps) < 2 * n:
            continue
        tot = sum(p["value"] for p in ps) or 1
        for pos in POSITIONS:
            r1[pos].append(sum(1 for p in ps[:n] if p["pos"] == pos))
            r12[pos].append(sum(1 for p in ps if p["pos"] == pos))
            share[pos].append(100 * sum(p["value"] for p in ps if p["pos"] == pos) / tot)
    if not r1:
        return None
    avg = lambda d: {pos: round(statistics.mean(d[pos]), 1) for pos in POSITIONS}
    return {"r1": avg(r1), "r12": avg(r12), "share": avg(share), "classes": len(next(iter(r1.values())))}


def _orders(lg, year: int, sim: dict | None, rng: random.Random) -> tuple[list[list[int]], str]:
    """Sampled draft orders (roster ids by slot) for a class, and where they come from."""
    if sim and sim.get("_orders") and year == sim["draft_season"]:
        return sim["_orders"][:N_MOCKS], "season simulation"
    tl = future.analyze(lg)
    label = str(year - 1)
    if label in tl["years"]:
        y = tl["years"].index(label)
        strength = {t["roster_id"]: t["strength"][y] for t in tl["teams"]}
        return [sorted(strength, key=lambda rid: strength[rid] * math.exp(rng.gauss(0, ORDER_NOISE))) for _ in range(N_MOCKS)], \
            f"projected {label} lineups"
    rids = list(lg.teams)
    return [rng.sample(rids, len(rids)) for _ in range(N_MOCKS)], "random"


def _mock(lg, year: int, board: list, picks: list, habits: dict, orders: list, rng: random.Random) -> dict:
    """pick id -> {slots: Counter, avail: Counter(prospect id), r1_any: Counter(pos)}."""
    me = lg.me["roster_id"]
    by_orig = {(p["round"], p["orig_roster_id"]): p for p in picks}
    rounds = sorted({p["round"] for p in picks})
    r1_ids = {b["id"] for b in board[:len(lg.teams)]}
    out = defaultdict(lambda: {"slots": Counter(), "avail": Counter(), "r1_any": Counter()})
    for order in orders:
        gone = set()
        for r in rounds:
            for slot, rid in enumerate(order, 1):
                p = by_orig.get((r, rid))
                if not p:
                    continue
                left = [b for b in board if b["id"] not in gone]
                if not left:
                    break
                owner = lg.teams.get(p["roster_id"]) or {}
                if p["roster_id"] == me:
                    o = out[p["id"]]
                    o["slots"][slot] += 1
                    for b in left:
                        o["avail"][b["id"]] += 1
                    for pos in {b["pos"] for b in left if b["id"] in r1_ids}:
                        o["r1_any"][pos] += 1
                choice = max(left, key=lambda b: draftprep._choice_score(b["value"], b["pos"], habits.get(p["roster_id"]),
                                                                        owner.get("need_future", {})) * math.exp(rng.gauss(0, 0.25)))
                gone.add(choice["id"])
    return out


def analyze(lg, sim: dict | None) -> dict:
    n = len(lg.teams)
    to_app = (lg.values.mappers or {}).get("ktc") or (lambda v: v)
    prospects = devy(lg.superflex)
    base = typical(lg.rookies, n)
    habits = draftprep.habits(draftprep._drafts_with_values(lg))
    me = lg.me["roster_id"] if lg.me else None
    years = [y for y in lg.pick_seasons if any(p["year"] == y for p in prospects)][:CLASSES]
    rng = random.Random(7)
    classes = []
    for year in years:
        board = sorted(({**p, "value": round(to_app(p["value"]))} for p in prospects if p["year"] == year), key=lambda b: -b["value"])
        for i, b in enumerate(board):
            b["rank"] = i + 1
        top, top2 = board[:n], board[:2 * n]
        tot = sum(b["value"] for b in top2) or 1
        mix = {pos: {"r1": sum(1 for b in top if b["pos"] == pos), "r12": sum(1 for b in top2 if b["pos"] == pos),
                     "share": round(100 * sum(b["value"] for b in top2 if b["pos"] == pos) / tot, 1)} for pos in POSITIONS}
        heavy = [pos for pos in POSITIONS if base and mix[pos]["share"] - base["share"][pos] >= SHARE_GAP]
        light = [pos for pos in POSITIONS if base and mix[pos]["share"] - base["share"][pos] <= -SHARE_GAP]

        picks = [{**pk, "roster_id": t["roster_id"]} for t in lg.teams.values() for pk in t["picks"] if pk["season"] == year]
        orders, source = _orders(lg, year, sim, rng)
        res = _mock(lg, year, board, picks, habits, orders, rng) if me is not None else {}
        mine = []
        for pk in sorted((p for p in picks if p["roster_id"] == me and p["round"] <= 2), key=lambda p: (p["round"], p["orig_roster_id"])):
            o = res.get(pk["id"])
            if not o:
                continue
            k = sum(o["slots"].values()) or 1
            slots = sorted(o["slots"].elements())
            by_pos = {}
            for pos in POSITIONS:
                pros = [b for b in board if b["pos"] == pos][:6]
                by_pos[pos] = {"r1_any": round(100 * o["r1_any"][pos] / k), "n_r1": mix[pos]["r1"],
                               "players": [{"id": b["id"], "name": b["name"], "rank": b["rank"], "value": b["value"],
                                            "avail": round(100 * o["avail"][b["id"]] / k)} for b in pros]}
            mine.append({"id": pk["id"], "name": pk["name"], "round": pk["round"], "orig": lg.teams[pk["orig_roster_id"]]["manager"],
                         "slot_range": [slots[len(slots) // 10], slots[(len(slots) * 9) // 10]] if slots else None,
                         "pos": by_pos})
        classes.append({"year": year, "n": len(board), "mix": mix, "heavy": heavy, "light": light, "order_source": source,
                        "top": {pos: [{k: b[k] for k in ("id", "name", "college", "value", "rank")} for b in board if b["pos"] == pos][:5] for pos in POSITIONS},
                        "my_picks": mine})
    return {"classes": classes, "typical": base, "teams": n, "superflex": lg.superflex,
            "my_needs": [p for p in POSITIONS if (lg.me or {}).get("need_future", {}).get(p, 0) >= 0.5]}
