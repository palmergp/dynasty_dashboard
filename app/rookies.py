"""Rookie pick hit rates, by round and position, and how long each position's value lasts.

Rookie classes (2019 on): DynastyProcess's values file (values.csv, weekly since February
2019) ranks each class just before rookie-draft season (the last snapshot between mid-May
and mid-July of the draft year), using superflex or 1QB values to match the league. The top
(teams × rounds) become that year's picks: 1.01 is the most valuable rookie, and so on.
Consensus values are a stand-in for where players actually went in rookie drafts.

Outcomes, from nflverse regular-season stats (PPR points per game, at least 7 games), over
a player's first 3 NFL seasons:
- Elite: a top-12 RB/WR or top-6 TE season (QB: top 12 in superflex, top 6 in 1QB).
- Starter: a top-24 RB/WR, top-12 TE season (QB: top 24 / top 12). "Hit" = elite or starter.
- Flex: a top-36 RB/WR, top-18 TE season (QB: top 32 / top 24), but never a starter.
- Bust: none of those.
Only classes with 3 completed seasons count toward the rates.

Longevity:
- Production: every QB/RB/WR/TE drafted into the NFL 2000 onward who had at least one
  starter season, followed for 12 seasons: the share still having starter seasons each year
  after their draft, and how many starter seasons they had in all.
- Dynasty value: for the rookie classes above, the share of their draft-day value (summed
  across a position's picks) still there 1, 2, ... years later, in DynastyProcess's values.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import statistics
from collections import Counter, defaultdict

import pyarrow.parquet as pq

from . import history, sleeper
from .cache import cached
from .values import _dp_ids, _http, name_key

FIRST_CLASS = 2019
WINDOW = 3            # seasons an outcome is judged over
MIN_GAMES = 7
LONG_FROM, LONG_YEARS = 2000, 12
VALUE_YEARS = 6
SMOOTH = 1.5          # kernel width (in draft slots) for the per-slot curves
OUTCOMES = ("elite", "starter", "flex", "bust")
STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_{}.parquet"
DRAFT_URL = "https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.parquet"
POSITIONS = ("QB", "RB", "WR", "TE")


def thresholds(superflex: bool) -> dict:
    """Finish needed at each position for elite / starter / flex."""
    return {"elite": {"QB": 12 if superflex else 6, "RB": 12, "WR": 12, "TE": 6},
            "starter": {"QB": 24 if superflex else 12, "RB": 24, "WR": 24, "TE": 12},
            "flex": {"QB": 32 if superflex else 24, "RB": 36, "WR": 36, "TE": 18}}


# ---------------------------------------------------------------- data
def _season(y: int) -> list:
    """[[gsis_id, pos, games, ppr points], ...] for one finished regular season."""
    def fetch():
        r = _http.get(STATS_URL.format(y))
        r.raise_for_status()
        t = pq.read_table(io.BytesIO(r.content), columns=["player_id", "position", "games", "fantasy_points_ppr"]).to_pydict()
        return [[pid, pos, g or 0, pts or 0.0] for pid, pos, g, pts in zip(*t.values()) if pos in POSITIONS and pid]
    return cached(f"nflverse:reg:{y}", None, fetch)


def _last_season() -> int:
    """Latest regular season that's over."""
    st = sleeper.nfl_state()
    y = int(st.get("season") or dt.date.today().year)
    return y if st.get("season_type") in ("post", "off") else y - 1


def _finishes(first: int, last: int) -> dict:
    """(gsis_id, season) -> positional rank by points per game."""
    out = {}
    for y in range(first, last + 1):
        try:
            rows = _season(y)
        except Exception:  # a season nflverse hasn't published yet
            continue
        by = defaultdict(list)
        for pid, pos, g, pts in rows:
            if g >= MIN_GAMES:
                by[pos].append((pts / g, pid))
        for pos, xs in by.items():
            for i, (_, pid) in enumerate(sorted(xs, reverse=True)):
                out[(pid, y)] = i + 1
    return out


def _nfl_draft() -> list:
    """[[season, gsis_id, pos, name], ...] for QB/RB/WR/TE drafted since LONG_FROM."""
    def fetch():
        r = _http.get(DRAFT_URL)
        r.raise_for_status()
        t = pq.read_table(io.BytesIO(r.content), columns=["season", "gsis_id", "position", "pfr_player_name"]).to_pydict()
        return [[s, g, p, n] for s, g, p, n in zip(*t.values()) if s and s >= LONG_FROM and g and p in POSITIONS]
    return cached("nflverse:draftpicks:v2", 7 * 24 * 3600, fetch)


def _july(commits: list, y: int) -> dict | None:
    """The last values.csv commit between mid-May and mid-July of year y."""
    cand = [c for c in commits if f"{y}-05-15" <= c["date"] <= f"{y}-07-15"]
    return cand[-1] if cand else None


def _snapshot(sha: str) -> list:
    """values.csv rows as [name, pos, fp_id, draft_year, value_1qb, value_2qb]. Early files
    use other column names, lack fp_id, or leave the rookies' draft_year blank."""
    def fetch():
        txt = _http.get(f"https://raw.githubusercontent.com/{history.REPO}/{sha}/files/values.csv").content.decode("utf-8-sig")
        out = []
        for r in csv.DictReader(io.StringIO(txt)):
            v1 = r.get("value_1qb", r.get("1QBValue"))
            v2 = r.get("value_2qb", r.get("2QB Value"))
            num = lambda v: float(v) if v not in (None, "", "NA") else None
            out.append([r.get("player") or r.get("mergename"), r.get("pos"), r.get("fp_id"),
                        r.get("draft_year") if r.get("draft_year") not in (None, "", "NA") else None, num(v1), num(v2)])
        return out
    return cached(f"dp:valuescsv:{sha}", None, fetch)


# ---------------------------------------------------------------- analysis
def _classes(lg, commits, ids_by_fp, ids_by_name, draft_by_name, n_teams, rounds, superflex):
    """Each class's top rookies as picks: {class, slot, round, pick (in round), ...}."""
    picks = []
    for y in range(FIRST_CLASS, dt.date.today().year + 1):
        c = _july(commits, y)
        if not c:
            continue
        rows = []
        for name, pos, fp, dy, v1, v2 in _snapshot(c["sha"]):
            ident = ids_by_fp.get(fp) or ids_by_name.get((name_key(name or ""), pos)) or {}
            year = dy or ident.get("draft_year")
            v = (v2 if superflex and v2 is not None else v1)
            if pos in POSITIONS and str(year) == str(y) and v:
                rows.append((v, name, pos, ident))
        rows.sort(key=lambda r: -r[0])
        for i, (v, name, pos, ident) in enumerate(rows[:n_teams * rounds]):
            rnd, k = i // n_teams + 1, i % n_teams + 1
            picks.append({"cls": y, "slot": i + 1, "round": rnd, "pick": k, "label": f"{rnd}.{k:02d}",
                          "tier": "early" if k <= n_teams / 3 else "mid" if k <= 2 * n_teams / 3 else "late",
                          "name": name, "pos": pos, "value": v, "sleeper_id": ident.get("sleeper_id"),
                          "gsis": ident.get("gsis_id") or draft_by_name.get((name_key(name or ""), pos)),
                          "date": c["date"]})
    return picks


def _outcome(p: dict, finish: dict, th: dict, last: int) -> tuple[str, int | None, int | None]:
    """(outcome, best finish, season of it) over his first WINDOW seasons so far."""
    best, when = None, None
    for y in range(p["cls"], min(p["cls"] + WINDOW, last + 1)):
        f = finish.get((p["gsis"], y))
        if f and (best is None or f < best):
            best, when = f, y
    pos = p["pos"]
    for o in ("elite", "starter", "flex"):
        if best and best <= th[o][pos]:
            return o, best, when
    return "bust", best, when


def _rates(xs: list) -> dict:
    n = len(xs)
    c = Counter(p["outcome"] for p in xs)
    out = {"n": n, **{o: round(c[o] / n * 100, 1) if n else None for o in OUTCOMES}, "counts": {o: c[o] for o in OUTCOMES}}
    out["hit"] = round((c["elite"] + c["starter"]) / n * 100, 1) if n else None
    return out


def analyze(lg) -> dict:
    superflex, n_teams, rounds = lg.superflex, len(lg.teams), lg.draft_rounds
    th = thresholds(superflex)
    last = _last_season()
    ids = _dp_ids()
    by_fp = {r["fantasypros_id"]: r for r in ids if r.get("fantasypros_id") not in (None, "", "NA")}
    by_name = {(name_key(r["name"]), r["position"]): r for r in ids if r.get("name")}
    commits = history._commits(f"{FIRST_CLASS}-01-01", "files/values.csv")
    draft_by_name = {(name_key(n or ""), p): g for _, g, p, n in _nfl_draft()}
    picks = _classes(lg, commits, by_fp, by_name, draft_by_name, n_teams, rounds, superflex)
    finish = _finishes(min(LONG_FROM, FIRST_CLASS), last)
    to_app = lg.values.mappers.get("dynastyprocess") or (lambda v: v)

    # Dynasty value at each later July (players who fell off DP's list count as 0).
    july_vals = {}
    for y in sorted({p["cls"] for p in picks} | set(range(FIRST_CLASS, dt.date.today().year + 1))):
        c = _july(commits, y)
        if c:
            vals = {}
            for name, pos, fp, dy, v1, v2 in _snapshot(c["sha"]):
                ident = by_fp.get(fp) or by_name.get((name_key(name or ""), pos)) or {}
                v = v2 if superflex and v2 is not None else v1
                if ident.get("gsis_id") and v:
                    vals[ident["gsis_id"]] = v
            july_vals[y] = vals
    for p in picks:
        p["outcome"], p["best"], p["best_season"] = _outcome(p, finish, th, last)
        p["seasons"] = max(0, min(WINDOW, last - p["cls"] + 1))
        p["complete"] = p["seasons"] >= WINDOW
        p["value_path"] = [july_vals[p["cls"] + k].get(p["gsis"], 0.0) if p["cls"] + k in july_vals else None for k in range(VALUE_YEARS + 1)]
        p["day_value"] = round(to_app(p["value"]))  # draft-day value, app scale
        p["value_3y"] = round(to_app(p["value_path"][3])) if p["value_path"][3] else (0 if p["value_path"][3] is not None else None)
        now = lg.values.player(p["sleeper_id"]) if p.get("sleeper_id") else None
        p["value_now"] = round(now["value"]) if now and now["value"] else None

    done = [p for p in picks if p["complete"] and p["gsis"]]
    tiers = ("early", "mid", "late")
    by_round = [{"round": r, **_rates([p for p in done if p["round"] == r]),
                 "tiers": [{"tier": t, "label": _tier_label(r, t, n_teams), **_rates([p for p in done if p["round"] == r and p["tier"] == t])} for t in tiers]}
                for r in range(1, rounds + 1)]
    by_pos = [{"pos": pos, **_rates([p for p in done if p["pos"] == pos]),
               "rounds": [{"round": r, **_rates([p for p in done if p["pos"] == pos and p["round"] == r])} for r in range(1, rounds + 1)]}
              for pos in POSITIONS]

    # What a pick turns into: player value 3 years later (app scale) vs. draft-day value.
    payoff = []
    for r in range(1, rounds + 1):
        xs = [p for p in picks if p["round"] == r and p["value_path"][3] is not None]
        if xs:
            later = [to_app(p["value_path"][3]) if p["value_path"][3] else 0.0 for p in xs]
            payoff.append({"round": r, "n": len(xs), "draft_day": round(statistics.mean(to_app(p["value"]) for p in xs)),
                           "mean_later": round(statistics.mean(later)), "median_later": round(statistics.median(later)),
                           "price_now": round(lg.values.pick(lg.pick_seasons[0], r)["value"])})

    # Value longevity: share of a position's draft-day value left k years later.
    value_curve = []
    for pos in POSITIONS:
        row, ns = [], []
        for k in range(VALUE_YEARS + 1):
            xs = [p for p in picks if p["pos"] == pos and p["value_path"][k] is not None]
            row.append(round(sum(p["value_path"][k] for p in xs) / sum(p["value"] for p in xs) * 100) if len(xs) >= 5 else None)
            ns.append(len(xs))
        value_curve.append({"pos": pos, "held": row, "n": ns})

    longevity = _longevity(finish, th, last)
    curves = _curves(picks, n_teams * rounds)
    slot_tiers = []
    for r in range(1, rounds + 1):
        for t in tiers:
            xs = [p for p in done if p["round"] == r and p["tier"] == t]
            ys = [p for p in picks if p["round"] == r and p["tier"] == t and p["value_3y"] is not None]
            if not xs or not ys:
                continue
            day = statistics.mean(p["day_value"] for p in ys)
            later = statistics.mean(p["value_3y"] for p in ys)
            slot_tiers.append({"round": r, "tier": t, "label": _tier_label(r, t, n_teams), **_rates(xs), "n_value": len(ys),
                               "draft_day": round(day), "mean_later": round(later), "median_later": round(statistics.median(p["value_3y"] for p in ys)),
                               "payoff": round(later / day, 2) if day else None,
                               "price_now": round(lg.values.pick(lg.pick_seasons[0], r, t)["value"])})
    for p in picks:  # trim for the response
        p.pop("value_path", None)
    complete_classes = sorted({p["cls"] for p in done})
    return {"superflex": superflex, "teams": n_teams, "rounds": rounds, "window": WINDOW, "last_season": last,
            "thresholds": th, "classes": sorted({p["cls"] for p in picks}), "complete_classes": complete_classes,
            "by_round": by_round, "by_pos": by_pos, "payoff": payoff, "value_curve": value_curve, "value_years": VALUE_YEARS,
            "longevity": longevity, "picks": picks, "min_games": MIN_GAMES, "curves": curves, "slot_tiers": slot_tiers}


def _curves(picks: list, n_slots: int) -> dict:
    """Per overall slot (1.01 = slot 1), smoothed across neighboring slots with a Gaussian
    kernel: hit and bust rates (complete classes) and draft-day and 3-years-later value."""
    import math
    done = [p for p in picks if p["complete"] and p["gsis"]]
    later = [p for p in picks if p["value_3y"] is not None]

    def smooth(xs, f):
        out = []
        for s in range(1, n_slots + 1):
            w = [(math.exp(-((p["slot"] - s) / SMOOTH) ** 2 / 2), f(p)) for p in xs]
            tot = sum(a for a, _ in w)
            out.append(sum(a * v for a, v in w) / tot if tot else None)
        return out
    hit = smooth(done, lambda p: p["outcome"] in ("elite", "starter"))
    bust = smooth(done, lambda p: p["outcome"] == "bust")
    return {"hit": [round(x * 100, 1) for x in hit], "bust": [round(x * 100, 1) for x in bust],
            "draft_day": [round(x) for x in smooth(later, lambda p: p["day_value"])],
            "later": [round(x) for x in smooth(later, lambda p: p["value_3y"])], "smooth": SMOOTH}


def _tier_label(r: int, t: str, n: int) -> str:
    third = n // 3
    lo, hi = {"early": (1, third), "mid": (third + 1, 2 * third), "late": (2 * third + 1, n)}[t]
    return f"{r}.{lo:02d}–{r}.{hi:02d}"


def _longevity(finish: dict, th: dict, last: int) -> dict:
    """Among NFL draftees who had a starter season, the share starting in each year after
    their draft, and their number of starter seasons (classes with LONG_YEARS seasons seen)."""
    draft = [d for d in _nfl_draft() if d[0] + LONG_YEARS - 1 <= last]
    out = []
    for pos in POSITIONS:
        cut = th["starter"][pos]
        starts = []
        for season, gsis, p, _ in draft:
            if p != pos:
                continue
            row = [bool((f := finish.get((gsis, season + k))) and f <= cut) for k in range(LONG_YEARS)]
            if any(row):
                starts.append(row)
        if not starts:
            continue
        share = [round(sum(r[k] for r in starts) / len(starts) * 100) for k in range(LONG_YEARS)]
        counts = [sum(r) for r in starts]
        peak = max(share)
        out.append({"pos": pos, "n": len(starts), "share": share, "median_seasons": statistics.median(counts),
                    "mean_seasons": round(statistics.mean(counts), 1),
                    "peak_year": share.index(peak) + 1,
                    "half_life": next((k + 1 for k in range(share.index(peak), LONG_YEARS) if share[k] < peak / 2), None)})
    return {"positions": out, "from": LONG_FROM, "to": max((d[0] for d in draft), default=None), "years": LONG_YEARS}
