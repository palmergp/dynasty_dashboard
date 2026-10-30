"""Historical dynasty values from DynastyProcess's weekly snapshots.

DynastyProcess commits values-players.csv to GitHub roughly weekly, so the file's git
history is a free weekly value archive. Each snapshot is fetched once (by commit sha)
and cached forever. Raw DP values are put on the app's scale with today's
DynastyProcess→consensus mapper; DP derives values from rank with a fixed formula,
so one mapper stays valid across snapshots.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from concurrent.futures import ThreadPoolExecutor

import httpx

from .cache import cached
from .values import SCALE, _dp_ids, _match, _name_index

REPO = "dynastyprocess/data"
PATH = "files/values-players.csv"
_http = httpx.Client(timeout=45, headers={"User-Agent": "dynasty-trade-helper/1.0"}, follow_redirects=True)


def _commits(since: str, path: str = PATH) -> list[dict]:
    """[{sha, date}] for a DP data file since an ISO date, oldest first (one per day)."""
    def fetch():
        out, url = [], f"https://api.github.com/repos/{REPO}/commits"
        params = {"path": path, "since": f"{since}T00:00:00Z", "per_page": 100}
        while url:
            r = _http.get(url, params=params)
            r.raise_for_status()
            out += [{"sha": c["sha"], "date": c["commit"]["committer"]["date"][:10]} for c in r.json()]
            url = r.links.get("next", {}).get("url")
            params = None
        return out
    key = f"dp:commits:{since}" if path == PATH else f"dp:commits:{path}:{since}"
    commits = cached(key, 24 * 3600, fetch)
    by_date = {}
    for c in commits:
        by_date.setdefault(c["date"], c)  # API lists newest first: keep the day's last commit
    return [by_date[d] for d in sorted(by_date)]


def _snapshot(sha: str, superflex: bool) -> list[dict]:
    col = "value_2qb" if superflex else "value_1qb"

    def fetch():
        txt = _http.get(f"https://raw.githubusercontent.com/{REPO}/{sha}/{PATH}").text
        return [{"fp_id": r["fp_id"], "name": r["player"], "pos": r["pos"], "value": float(r[col])}
                for r in csv.DictReader(io.StringIO(txt)) if r.get(col) not in (None, "", "NA")]
    return cached(f"dp:snap:{sha}:{col}", None, fetch)


def value_history(lg, since: dt.date, raw: bool = False) -> dict:
    """{"dates": [iso...], "values": {sleeper_id: [value|None per date]}} on the app's scale
    (or in DynastyProcess's own numbers with raw=True).

    A player is None before his first appearance in DP's list (e.g. rookies before the
    NFL draft). If he later drops off it, he's worth at most that snapshot's floor (its
    lowest listed value), which avoids fake 0 ↔ floor spikes for fringe players.
    """
    commits = _commits(since.isoformat())
    with ThreadPoolExecutor(max_workers=8) as pool:
        snaps = list(pool.map(lambda c: _snapshot(c["sha"], lg.superflex), commits))

    fp_to_sleeper = {r["fantasypros_id"]: r["sleeper_id"] for r in _dp_ids()
                     if r.get("fantasypros_id") not in (None, "", "NA")}
    idx = _name_index(lg.players_db)
    mapper = lg.values.mappers.get("dynastyprocess")
    top = max((r["value"] for s in snaps for r in s), default=1)
    scale = (lambda v: v) if raw else mapper or (lambda v: v / top * SCALE)

    dates = [c["date"] for c in commits]
    values: dict[str, list] = {}
    for i, snap in enumerate(snaps):
        for r in snap:
            sid = _match(fp_to_sleeper.get(r["fp_id"]), r["name"], r["pos"], idx)
            if not sid:
                continue
            row = values.setdefault(sid, [None] * len(dates))
            row[i] = max(row[i] or 0, scale(r["value"]))
    floors = [min((scale(r["value"]) for r in snap), default=0.0) for snap in snaps]
    for row in values.values():
        last = None
        for i, v in enumerate(row):
            if v is not None:
                last = v
            elif last is not None:
                row[i] = min(last, floors[i])
    return {"dates": dates, "values": values}
