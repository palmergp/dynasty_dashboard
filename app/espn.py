"""Read-only client for ESPN's public NFL scoreboard and game summaries (unofficial and
undocumented, so it may change). Used for live game clocks and play-by-play."""
from __future__ import annotations

import httpx

from .cache import cached

BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
LIVE_TTL = 20          # seconds: games in progress
_http = httpx.Client(timeout=30, headers={"User-Agent": "front-office/1.0"})
# ESPN's team abbreviations that differ from Sleeper's.
TO_SLEEPER = {"WSH": "WAS"}


def _get(path: str, params: dict | None = None):
    r = _http.get(BASE + path, params=params)
    r.raise_for_status()
    return r.json()


def games(season: int, week: int, live: bool) -> dict:
    """Sleeper team abbreviation -> {event, state, period, clock, seconds_left, date, home, opp,
    score, opp_score, possession, red_zone, name} for one regular-season week."""
    def fetch():
        sb = _get("/scoreboard", {"seasontype": 2, "week": week, "dates": season})
        out = {}
        for e in sb.get("events", []):
            c = e["competitions"][0]
            st = c.get("status") or e.get("status") or {}
            sit = c.get("situation") or {}
            teams = {x["team"]["id"]: x for x in c["competitors"]}
            for tid, x in teams.items():
                o = next(y for i, y in teams.items() if i != tid)
                ab = TO_SLEEPER.get(x["team"]["abbreviation"], x["team"]["abbreviation"])
                out[ab] = {"event": e["id"], "team_id": tid, "state": st.get("type", {}).get("state"),
                           "detail": st.get("type", {}).get("shortDetail"), "period": st.get("period") or 0,
                           "clock": st.get("clock") or 0, "date": e.get("date"), "home": x.get("homeAway") == "home",
                           "opp": TO_SLEEPER.get(o["team"]["abbreviation"], o["team"]["abbreviation"]),
                           "team_name": x["team"].get("displayName"), "opp_name": o["team"].get("displayName"),
                           "score": int(x.get("score") or 0), "opp_score": int(o.get("score") or 0),
                           "possession": sit.get("possession") == tid, "red_zone": bool(sit.get("isRedZone")) and sit.get("possession") == tid}
        return out
    return cached(f"espn_sb:{season}:{week}", LIVE_TTL if live else 3600, fetch)


def plays(event: str, state: str) -> list[dict]:
    """Every play of a game: {id, type, text, yards, score, turnover, period, clock, team_id, wallclock}."""
    return game(event, state)["plays"]


def game(event: str, state: str) -> dict:
    """A game's plays and its injury list. The injury list updates during the game (a player
    ruled out shows up with the time of the ruling); entries from before kickoff are the
    pregame report. Injuries: {name, team (Sleeper abbreviation), status, date, part}."""
    def fetch():
        s = _get("/summary", {"event": event})
        inj = []
        for t in s.get("injuries") or []:
            ab = (t.get("team") or {}).get("abbreviation")
            for i in t.get("injuries") or []:
                d = i.get("details") or {}
                side = d.get("side") if d.get("side") not in (None, "Not Specified") else None
                part = " ".join(x for x in (side, d.get("type")) if x and x != "Not Specified").lower() or None
                inj.append({"name": (i.get("athlete") or {}).get("displayName"), "team": TO_SLEEPER.get(ab, ab),
                            "status": i.get("status"), "date": i.get("date"), "part": part})
        out = []
        for d in (s.get("drives") or {}).get("previous", []) + ([s["drives"]["current"]] if (s.get("drives") or {}).get("current") else []):
            for p in d.get("plays") or []:
                out.append({"id": p["id"], "type": (p.get("type") or {}).get("text"), "text": p.get("text") or "",
                            "yards": p.get("statYardage") or 0, "score": bool(p.get("scoringPlay")), "turnover": bool(p.get("isTurnover")),
                            "period": (p.get("period") or {}).get("number"), "clock": (p.get("clock") or {}).get("displayValue"),
                            "team_id": ((p.get("start") or {}).get("team") or {}).get("id"), "wallclock": p.get("wallclock")})
        return {"plays": list({p["id"]: p for p in out}.values()), "injuries": inj}
    ttl = LIVE_TTL if state == "in" else 6 * 3600 if state == "post" else 60
    return cached(f"espn_game:{event}:{state}", ttl, fetch)
