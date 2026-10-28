"""Dynasty values from FantasyCalc, KeepTradeCut and DynastyProcess, blended onto one scale.

The sources use differently shaped curves (DynastyProcess decays much faster than KTC),
so each is rank-mapped onto a consensus curve: a source's Nth-best player gets the
consensus value of the Nth-best player. Each source keeps its own ordering, and only
genuine ranking disagreements remain. Picks are mapped with the same per-source curve.
The available sources are then averaged with the configured weights, and user
overrides are applied last.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import statistics
from collections import defaultdict

import httpx

from . import sleeper, store
from .cache import cached

VALUES_TTL = 12 * 3600
SCALE = 10_000
SOURCES = ("fantasycalc", "ktc", "dynastyprocess")
SOURCE_LABELS = {"fantasycalc": "FantasyCalc", "ktc": "KeepTradeCut", "dynastyprocess": "DynastyProcess"}

_http = httpx.Client(timeout=45, headers={"User-Agent": "Mozilla/5.0 (dynasty-trade-helper)"}, follow_redirects=True)

DP_BASE = "https://raw.githubusercontent.com/dynastyprocess/data/master/files"
ROUND_RE = r"(\d)(?:st|nd|rd|th)"


# ---------------------------------------------------------------- name matching
_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def name_key(name: str) -> str:
    n = name.lower().replace(".", "").replace("'", "").replace("-", " ")
    n = _SUFFIX.sub("", n)
    return re.sub(r"[^a-z ]", "", re.sub(r"\s+", " ", n)).strip()


def _name_index(players: dict) -> dict:
    """(name_key, position) -> sleeper_id, preferring players currently on a team."""
    idx = {}
    for pid, p in players.items():
        if not p.get("full_name") or p.get("position") not in ("QB", "RB", "WR", "TE"):
            continue
        key = (name_key(p["full_name"]), p["position"])
        if key not in idx or (p.get("team") and not players[idx[key]].get("team")):
            idx[key] = pid
    return idx


def _match(sid, name, pos, idx):
    if sid and sid not in ("NA", "None"):
        return str(sid)
    return idx.get((name_key(name), pos))


def _parse_pick(name: str):
    """'2027 1st (Early)', '2027 Early 1st', '2028 2nd' -> (season, round, tier|None)."""
    m = re.match(rf"(\d{{4}}) {ROUND_RE}(?: \((Early|Mid|Late)\))?$", name) or None
    if m:
        return int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower() or None
    m = re.match(rf"(\d{{4}}) (Early|Mid|Late) {ROUND_RE}$", name)
    if m:
        return int(m.group(1)), int(m.group(3)), m.group(2).lower()
    return None


# ---------------------------------------------------------------- source fetchers
def _fetch_fantasycalc(num_teams: int, num_qbs: int, ppr: float) -> dict:
    url = (f"https://api.fantasycalc.com/values/current?isDynasty=true"
           f"&numQbs={num_qbs}&numTeams={num_teams}&ppr={ppr}")
    rows = _http.get(url).json()
    out = {"players": [], "picks": []}
    for r in rows:
        p = r["player"]
        if p["position"] == "PICK":
            out["picks"].append({"name": p["name"], "value": r["value"]})
        else:
            out["players"].append({
                "sleeper_id": p.get("sleeperId"), "name": p["name"], "pos": p["position"],
                "value": r["value"], "redraft": r.get("redraftValue"), "trend": r.get("trend30Day"),
            })
    return out


def _fetch_ktc(superflex: bool, tep: bool) -> dict:
    html = _http.get("https://keeptradecut.com/dynasty-rankings").text
    m = re.search(r'<script[^>]*id="ktc-players"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError("KTC page layout changed: ktc-players block not found")
    arr = json.loads(m.group(1))
    ids = _dp_ids()
    ktc_to_sleeper = {r["ktc_id"]: r["sleeper_id"] for r in ids if r.get("ktc_id") not in (None, "", "NA")}
    vkey = "superflexValues" if superflex else "oneQBValues"
    out = {"players": [], "picks": []}
    for p in arr:
        vals = p.get(vkey) or {}
        value = (vals.get("tep") or {}).get("value") if tep else vals.get("value")
        value = value or vals.get("value")
        if not value:
            continue
        if p["position"] == "RDP":
            out["picks"].append({"name": p["playerName"], "value": value})
        else:
            out["players"].append({
                "sleeper_id": ktc_to_sleeper.get(str(p["playerID"])), "name": p["playerName"],
                "pos": p["position"], "value": value,
            })
    return out


def _dp_ids() -> list[dict]:
    return cached("dp:ids", 3 * 24 * 3600, lambda: list(csv.DictReader(io.StringIO(
        _http.get(f"{DP_BASE}/db_playerids.csv").text))))


def _fetch_dynastyprocess(superflex: bool) -> dict:
    ids = _dp_ids()
    fp_to_sleeper = {r["fantasypros_id"]: r["sleeper_id"] for r in ids if r.get("fantasypros_id") not in (None, "", "NA")}
    col_v, col_e = ("value_2qb", "ecr_2qb") if superflex else ("value_1qb", "ecr_1qb")
    players = list(csv.DictReader(io.StringIO(_http.get(f"{DP_BASE}/values-players.csv").text)))
    picks = list(csv.DictReader(io.StringIO(_http.get(f"{DP_BASE}/values-picks.csv").text)))

    # DP publishes pick ECR but not pick values; fit ln(value) ~ ecr on players and apply to picks.
    pts = [(float(r[col_e]), math.log(float(r[col_v]))) for r in players
           if r[col_e] not in ("", "NA") and r[col_v] not in ("", "NA") and float(r[col_v]) > 0 and float(r[col_e]) < 300]
    n = len(pts)
    mx = sum(x for x, _ in pts) / n
    my = sum(y for _, y in pts) / n
    b = sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x, _ in pts)
    a = my - b * mx

    out = {"players": [], "picks": []}
    for r in players:
        if r[col_v] in ("", "NA"):
            continue
        out["players"].append({
            "sleeper_id": fp_to_sleeper.get(r["fp_id"]), "name": r["player"], "pos": r["pos"],
            "value": float(r[col_v]),
        })
    for r in picks:
        if r[col_e] in ("", "NA"):
            continue
        out["picks"].append({"name": r["player"], "value": math.exp(a + b * float(r[col_e]))})
    return out


# ---------------------------------------------------------------- assembly
def _league_format(lg: dict) -> dict:
    slots = lg.get("roster_positions") or []
    sc = lg.get("scoring_settings") or {}
    return {
        "num_teams": lg.get("total_rosters", 12),
        "superflex": "SUPER_FLEX" in slots or slots.count("QB") > 1,
        "ppr": sc.get("rec", 1.0),
        "tep": bool(sc.get("bonus_rec_te")),
    }


def raw_sources(lg: dict, force=False) -> dict:
    fmt = _league_format(lg)
    key = f"{fmt['num_teams']}:{fmt['superflex']}:{fmt['ppr']}:{fmt['tep']}"
    fetchers = {
        "fantasycalc": lambda: _fetch_fantasycalc(fmt["num_teams"], 2 if fmt["superflex"] else 1, fmt["ppr"]),
        "ktc": lambda: _fetch_ktc(fmt["superflex"], fmt["tep"]),
        "dynastyprocess": lambda: _fetch_dynastyprocess(fmt["superflex"]),
    }
    out, errors = {}, {}
    for name, fn in fetchers.items():
        try:
            out[name] = cached(f"values:{name}:{key}", VALUES_TTL, fn, force)
        except Exception as e:  # one broken source shouldn't take the app down
            errors[name] = str(e)
    return {"sources": out, "errors": errors}


class ValueBook:
    """Blended player and pick values for one league format."""

    def __init__(self, lg: dict, cfg: dict, force=False):
        players_db = sleeper.players(force)
        idx = _name_index(players_db)
        raw = raw_sources(lg, force)
        self.errors = raw["errors"]
        weights = {s: float(cfg["source_weights"].get(s, 0)) for s in SOURCES}

        self.by_source: dict[str, dict[str, float]] = {}       # source -> sleeper_id -> normalized value
        self.pick_source: dict[str, dict[tuple, float]] = {}   # source -> (season, round, tier) -> value
        redraft_raw, self.trend = {}, {}
        self.unmatched = defaultdict(list)

        mappers = _consensus_mappers(raw["sources"])
        self.mappers = mappers  # reused to put historical snapshots on the same scale
        for src, data in raw["sources"].items():
            f = mappers[src]
            vals = {}
            for p in data["players"]:
                sid = _match(p.get("sleeper_id"), p["name"], p["pos"], idx)
                if not sid:
                    self.unmatched[src].append(p["name"])
                    continue
                vals[sid] = max(vals.get(sid, 0), f(p["value"]))
                if src == "fantasycalc":
                    if p.get("redraft"):
                        redraft_raw[sid] = p["redraft"]
                    if p.get("trend") is not None:
                        self.trend[sid] = f(p["value"]) - f(max(p["value"] - p["trend"], 0))
            self.by_source[src] = vals
            picks = {}
            for pk in data["picks"]:
                parsed = _parse_pick(pk["name"])
                if parsed:
                    picks[parsed] = f(pk["value"])
            self.pick_source[src] = picks

        # Blend players.
        self.player_value: dict[str, float] = {}
        all_ids = set().union(*[v.keys() for v in self.by_source.values()]) if self.by_source else set()
        for sid in all_ids:
            num = den = 0.0
            for src, vals in self.by_source.items():
                if sid in vals and weights.get(src, 0) > 0:
                    num += vals[sid] * weights[src]
                    den += weights[src]
            if den:
                self.player_value[sid] = num / den

        # Redraft (win-now) values: FantasyCalc redraft, normalized; fill gaps with a
        # position/age-bucket ratio learned from players that have both values.
        rtop = max(redraft_raw.values(), default=1) or 1
        self.redraft = {sid: v * SCALE / rtop for sid, v in redraft_raw.items()}
        ratios = defaultdict(list)
        for sid, rv in self.redraft.items():
            dv = self.player_value.get(sid)
            p = players_db.get(sid)
            if dv and dv > 500 and p:
                ratios[(p.get("position"), _age_bucket(p.get("age")))].append(rv / dv)
        self._ratio = {k: statistics.median(v) for k, v in ratios.items() if len(v) >= 3}
        self._ratio_default = statistics.median([r for v in ratios.values() for r in v]) if ratios else 0.8
        for sid, dv in self.player_value.items():
            if sid not in self.redraft:
                p = players_db.get(sid) or {}
                r = self._ratio.get((p.get("position"), _age_bucket(p.get("age"))), self._ratio_default)
                # Players FantasyCalc omits from redraft are mostly non-contributors right now.
                self.redraft[sid] = dv * min(r, 1.0) * 0.6

        self.weights = weights
        self.overrides = store.load_overrides()

    # -- players
    def player(self, sid: str) -> dict:
        ov = self.overrides["players"].get(sid)
        market = self.player_value.get(sid, 0.0)
        return {
            "value": float(ov) if ov is not None else market,
            "market": market,
            "redraft": self.redraft.get(sid, 0.0) * ((float(ov) / market) if ov is not None and market else 1),
            "sources": {s: round(v[sid]) for s, v in self.by_source.items() if sid in v},
            "trend": self.trend.get(sid),
            "override": ov,
        }

    # -- picks
    def _pick_from_source(self, src: str, season: int, rnd: int, tier: str | None):
        picks = self.pick_source.get(src) or {}
        if (season, rnd, tier) in picks:
            return picks[(season, rnd, tier)]
        if (season, rnd, None) in picks:
            return picks[(season, rnd, None)]
        tiers = [picks[(season, rnd, t)] for t in ("early", "mid", "late") if (season, rnd, t) in picks]
        if tiers:
            return sum(tiers) / len(tiers)
        seasons = sorted({s for s, r, _ in picks if r == rnd})
        if not seasons:
            return None
        nearest = max(s for s in seasons if s <= season) if any(s <= season for s in seasons) else seasons[0]
        base = self._pick_from_source(src, nearest, rnd, tier if nearest == season else None)
        return base * (0.95 ** abs(season - nearest)) if base else None

    def pick(self, season: int, rnd: int, tier: str | None = None) -> dict:
        srcs = {}
        num = den = 0.0
        for src in self.pick_source:
            v = self._pick_from_source(src, season, rnd, tier)
            if v is not None and self.weights.get(src, 0) > 0:
                srcs[src] = round(v)
                num += v * self.weights[src]
                den += self.weights[src]
        market = num / den if den else 0.0
        mult = self.overrides["pick_multipliers"].get(f"{season}-{rnd}") or self.overrides["pick_multipliers"].get(str(rnd))
        value = market * float(mult) if mult else market
        return {"value": value, "market": market, "redraft": 0.0, "sources": srcs, "override": mult}


def _consensus_mappers(sources: dict) -> dict:
    """Per-source monotone functions mapping raw values onto the consensus curve."""
    curves = {}
    for src, data in sources.items():
        vals = sorted((p["value"] for p in data["players"] if p["value"] > 0), reverse=True)
        if vals:
            curves[src] = vals
    if not curves:
        return {}
    depth = max(len(c) for c in curves.values())
    consensus = []
    for i in range(depth):
        at = [c[i] / c[0] * SCALE for c in curves.values() if i < len(c)]
        consensus.append(sum(at) / len(at))
    # Keep the consensus strictly non-increasing.
    for i in range(1, depth):
        consensus[i] = min(consensus[i], consensus[i - 1])

    def make(curve):
        def f(v: float) -> float:
            if v >= curve[0]:
                return consensus[0] * v / curve[0]
            if v <= curve[-1]:
                return consensus[len(curve) - 1] * v / curve[-1]
            lo, hi = 0, len(curve) - 1  # curve is descending; find curve[i] >= v > curve[i+1]
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if curve[mid] >= v:
                    lo = mid
                else:
                    hi = mid
            a, b = curve[lo], curve[hi]
            t = (a - v) / (a - b) if a != b else 0
            return consensus[lo] + t * (consensus[hi] - consensus[lo])
        return f

    return {src: make(c) for src, c in curves.items()}


def _age_bucket(age) -> str:
    if age is None:
        return "?"
    return "<=23" if age <= 23 else "24-26" if age <= 26 else "27-29" if age <= 29 else "30+"
