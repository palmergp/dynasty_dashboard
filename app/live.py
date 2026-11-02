"""Live matchup: both lineups with points as games are played, each player's game status, a
live win chance, and every big play by anyone on either roster.

- Points: Sleeper's matchups (re-read at most every 30 seconds), in the league's scoring.
- Game status and play-by-play: ESPN's public scoreboard and game summaries (every 20 seconds
  while games are on).
- Win chance: each team's points so far plus each starter's projection for the part of his
  game still to play, with the week-to-week spread (lineup.py) shrunk the same way. Kickers
  and defenses use Sleeper's projected points.
- Big plays: ESPN plays that name a rostered player of either team (matched by the play's
  "F.Last" abbreviation and the offense's team). Each play's fantasy points come from the
  league's scoring: passer, receiver or rusher yards and touchdowns, receptions (with the TE
  bonus), interceptions and lost fumbles. Big = a touchdown, a turnover, a 20+ yard play or
  5+ fantasy points either way. Interceptions count only for the passer, and a receiver's
  play only when he caught the ball. Return touchdowns and two-point plays aren't covered.
- Injuries: a highlight when ESPN's play text says a rostered player "was injured during the
  play" or the game's injury list rules him out, doubtful or questionable to return after
  kickoff. Its clip link searches X for any video post about the injury.
- Stat lines and point breakdowns: Sleeper's weekly stats (they update during games) times
  the league's scoring settings.
- Clips: there's no free source that hands out a clip per play, so each big play links to
  an X search for video posts about that play: posted within 30 minutes of it, naming the
  player, from the NFL's and his team's official accounts (they post big plays within
  minutes); see _x_url for turnovers and injuries. After the game, a link to YouTube's
  highlights for that game.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from urllib.parse import quote

from . import espn, lineup, sleeper
from .cache import cached
from .league import SLOT_ELIGIBLE
from .values import name_key

BIG_YARDS = 20
BIG_POINTS = 5.0
X_HANDLES = {
    "ARI": "AZCardinals", "ATL": "AtlantaFalcons", "BAL": "Ravens", "BUF": "BuffaloBills", "CAR": "Panthers",
    "CHI": "ChicagoBears", "CIN": "Bengals", "CLE": "Browns", "DAL": "dallascowboys", "DEN": "Broncos",
    "DET": "Lions", "GB": "packers", "HOU": "HoustonTexans", "IND": "Colts", "JAX": "Jaguars", "KC": "Chiefs",
    "LV": "Raiders", "LAC": "chargers", "LAR": "RamsNFL", "MIA": "MiamiDolphins", "MIN": "Vikings",
    "NE": "Patriots", "NO": "Saints", "NYG": "Giants", "NYJ": "nyjets", "PHI": "Eagles", "PIT": "steelers",
    "SF": "49ers", "SEA": "Seahawks", "TB": "Buccaneers", "TEN": "Titans", "WAS": "Commanders",
}
SUFFIX = r"(?:\s(?:Jr\.?|Sr\.?|II|III|IV|V))?"
COMPLETE = ("Pass Reception", "Passing Touchdown")
# Where the play itself ends in ESPN's text: what follows is the kick, a conversion or a penalty.
AFTER_PLAY = re.compile(r"\s(?:TWO-POINT CONVERSION|[A-Z][a-z]*\.\S+ extra point|PENALTY|Penalty on)")


def main_text(text: str) -> str:
    m = AFTER_PLAY.search(text)
    return text[:m.start()] if m else text


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _last(p: dict) -> str:
    return re.sub(r"\s+(Jr\.?|Sr\.?|II|III|IV|V)$", "", (p.get("last_name") or "").strip())


def name_pattern(p: dict) -> re.Pattern | None:
    """ESPN writes players as first initial (sometimes more letters) + '.' + last name."""
    first, last = (p.get("first_name") or "").strip(), _last(p)
    if not first or not last:
        return None
    return re.compile(rf"(?<![\w.]){re.escape(first[0])}[a-z]*\.\s?{re.escape(last)}{SUFFIX}(?![\w'-])")


def role(play: dict, start: int) -> str | None:
    """What the player matched at `start` did on the play."""
    t, text = play["type"] or "", play["text"]
    i = text.find(" pass ")
    if " sacked" in text and i < 0:
        return "passer"
    if i >= 0:
        return "passer" if start < i else "receiver"
    if t in ("Rush", "Rushing Touchdown") or "FUMBLES" in text:
        # The ball carrier leads the text, after notes like "(Shotgun)" or "S.Anderson reported in as eligible.",
        # or takes a lateral.
        lead = len(text) - len(re.sub(r"^\s*(?:\([^)]*\)\s*|\S+ reported in as eligible\.\s*)*", "", text))
        return "rusher" if start == lead or text[:start].endswith("Lateral to ") else None
    return None


def play_points(play: dict, r: str, pos: str, sc: dict, lost: bool) -> float:
    """Fantasy points for one player's part in a play, in the league's scoring."""
    t, y = play["type"] or "", play["yards"]
    g = lambda k: sc.get(k, 0) or 0
    pts = 0.0
    if r == "passer":
        if t in COMPLETE:
            pts += g("pass_yd") * y + (g("pass_td") if t == "Passing Touchdown" else 0)
        if "INTERCEPTED" in play["text"]:
            pts += g("pass_int")
    elif r == "receiver" and t in COMPLETE:
        pts += g("rec") + g("rec_yd") * y + (g("rec_td") if t == "Passing Touchdown" else 0) + (g("bonus_rec_te") if pos == "TE" else 0)
    elif r == "rusher":
        pts += g("rush_yd") * y + (g("rush_td") if t == "Rushing Touchdown" else 0)
    if lost:
        pts += g("fum_lost")
    return pts


NAME = re.compile(r"(?<![\w.])[A-Z][a-z]*\.\s?[A-Z][\w'\-]+")


def fumble(play: dict, pat: re.Pattern) -> tuple[bool, bool]:
    """(he fumbled, he lost it). Each "FUMBLES" belongs to the last player named before it,
    leaving out tacklers in parentheses (so a receiver's fumble after the catch isn't the
    passer's). Lost = the play's last fumble on a turnover, or one that ends in a touchback
    before any later fumble (ESPN doesn't flag a fumble out of the end zone as a turnover)."""
    text = play["text"]
    plain = re.sub(r"\([^)]*\)", lambda m: " " * len(m.group()), text)
    mine = {x.start() for x in pat.finditer(text)}
    fums = [f.start() for f in re.finditer(r"FUMBLES", plain)]
    fumbled = lost = False
    for k, at in enumerate(fums):
        names = [x.start() for x in NAME.finditer(plain[:at])]
        if names and names[-1] in mine:
            fumbled = True
            last = k == len(fums) - 1
            lost = lost or (last and play["turnover"]) or "Touchback" in text[at:fums[k + 1] if not last else None]
    return fumbled, lost


def headline(play: dict, r: str, lost: bool) -> str:
    t, y, text = play["type"] or "", play["yards"], play["text"]
    if "INTERCEPTED" in text and r == "passer":
        return "Interception"
    if lost:
        return "Fumble lost"
    what = {"passer": "pass", "receiver": "catch", "rusher": "run"}.get(r, "play")
    if t in ("Passing Touchdown", "Rushing Touchdown"):
        return f"Touchdown: {y}-yd {what}"
    return f"{y}-yd {what}"


def _kd_points(season: int, week: int) -> dict:
    """Projected points for kickers and defenses (Sleeper's own figure)."""
    def fetch():
        url = f"https://api.sleeper.com/projections/nfl/{season}/{week}?season_type=regular&position[]=K&position[]=DEF"
        return {r["player_id"]: (r.get("stats") or {}).get("pts_ppr") or 0.0 for r in lineup._http.get(url).json() or [] if r.get("player_id")}
    return cached(f"projkd:{season}:{week}", 3 * 3600, fetch)


def _stats(season: int, week: int, live: bool) -> dict:
    """player_id -> this week's stats so far (Sleeper updates them during games)."""
    def fetch():
        url = (f"https://api.sleeper.com/stats/nfl/{season}/{week}?season_type=regular"
               + "".join(f"&position[]={p}" for p in ("QB", "RB", "WR", "TE", "K", "DEF")))
        return {e["player_id"]: e.get("stats") or {} for e in lineup._http.get(url).json() or [] if e.get("player_id")}
    return cached(f"stats_live:{season}:{week}", 30 if live else 6 * 3600, fetch)


def stat_line(pos: str, st: dict) -> str | None:
    """A box-score line, e.g. '18/27, 245 yds, 2 TD, 1 INT · 4 car, 22 yds'."""
    n = lambda k: int(st.get(k) or 0)
    tds = lambda k: f", {n(k)} TD" if n(k) else ""
    parts = []
    if pos == "K":
        if n("fga") or n("xpa"):
            parts.append(f"FG {n('fgm')}/{n('fga')}, XP {n('xpm')}/{n('xpa')}" + (f", long {n('fgm_lng')}" if n("fgm_lng") else ""))
    elif pos == "DEF":
        if st.get("gp") or "pts_allow" in st:
            bits = [f"{n('pts_allow')} pts allowed"] + [f"{n(k)} {label}" for k, label in
                                                          (("sack", "sacks"), ("int", "INT"), ("fum_rec", "fum rec"), ("def_td", "TD"), ("safe", "safety")) if n(k)]
            parts.append(", ".join(bits))
    else:
        if n("pass_att"):
            parts.append(f"{n('pass_cmp')}/{n('pass_att')}, {n('pass_yd')} yds{tds('pass_td')}" + (f", {n('pass_int')} INT" if n("pass_int") else ""))
        if n("rush_att"):
            parts.append(f"{n('rush_att')} car, {n('rush_yd')} yds{tds('rush_td')}")
        if n("rec_tgt") or n("rec"):
            parts.append(f"{n('rec')}/{n('rec_tgt')} rec, {n('rec_yd')} yds{tds('rec_td')}")
        if n("fum_lost"):
            parts.append(f"{n('fum_lost')} fum lost")
    return " · ".join(parts) or None


LABELS = {
    "pass_yd": "Passing yards", "pass_td": "Passing TDs", "pass_int": "Interceptions", "pass_2pt": "Passing 2-pt",
    "pass_cmp": "Completions", "pass_inc": "Incompletions", "pass_att": "Pass attempts", "pass_sack": "Sacked",
    "pass_fd": "Passing first downs", "rush_yd": "Rushing yards", "rush_td": "Rushing TDs", "rush_2pt": "Rushing 2-pt",
    "rush_att": "Carries", "rush_fd": "Rushing first downs", "rec": "Receptions", "rec_yd": "Receiving yards",
    "rec_td": "Receiving TDs", "rec_2pt": "Receiving 2-pt", "rec_fd": "Receiving first downs", "rec_tgt": "Targets",
    "bonus_rec_te": "TE catch bonus", "bonus_rec_rb": "RB catch bonus", "bonus_rec_wr": "WR catch bonus",
    "fum_lost": "Fumbles lost", "fum": "Fumbles", "xpm": "Extra points", "xpmiss": "Missed extra points",
    "fgmiss": "Missed field goals", "sack": "Sacks", "int": "Interceptions", "fum_rec": "Fumble recoveries",
    "def_td": "Defensive TDs", "safe": "Safeties", "blk_kick": "Blocked kicks", "ff": "Forced fumbles",
    "def_st_td": "Return TDs", "st_td": "Return TDs",
}


def _label(k: str) -> str:
    if k in LABELS:
        return LABELS[k]
    m = re.fullmatch(r"fgm_(\d+)_(\d+)", k) or re.fullmatch(r"fgm_(\d+)p", k)
    if m:
        return f"Field goals {m.group(1)}–{m.group(2)} yds" if m.lastindex == 2 else f"Field goals {m.group(1)}+ yds"
    m = re.fullmatch(r"pts_allow_(\d+)_(\d+)", k) or re.fullmatch(r"pts_allow_(\d+)p?", k)
    if m:
        return f"Points allowed {m.group(1)}–{m.group(2)}" if m.lastindex == 2 else f"Points allowed {m.group(1)}"
    return k.replace("_", " ").capitalize()


def breakdown(st: dict, scoring: dict) -> list[list]:
    """How a player's points add up: [label, stat, points per unit, points] for each scored stat."""
    out = []
    for k, v in st.items():
        mult = scoring.get(k)
        if mult and isinstance(v, (int, float)) and v:
            out.append([_label(k), round(v, 2), mult, round(v * mult, 2)])
    return sorted(out, key=lambda x: -abs(x[3]))


def _remaining(g: dict | None) -> float:
    """Share of a player's game still to play."""
    if not g or g["state"] == "post":
        return 0.0
    if g["state"] == "pre":
        return 1.0
    if g["period"] > 4:
        return 0.05
    return max(0.0, min(1.0, ((4 - g["period"]) * 900 + g["clock"]) / 3600))


def _approx_time(start: str | None, period: int | None, clock: str | None) -> str | None:
    """A play's rough time of day when ESPN has none: kickoff plus about 3 minutes of real
    time per minute of game clock (quarters run about 45 minutes)."""
    if not start or not period:
        return None
    try:
        mm, ss = (int(x) for x in (clock or "15:00").split(":"))
        played = (min(period, 5) - 1) * 15 + (15 - mm - ss / 60)
        t = dt.datetime.fromisoformat(start.replace("Z", "+00:00")) + dt.timedelta(minutes=3 * played)
        return t.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def _receiver(text: str) -> list[str]:
    """The receiver's last name on a pass ("pass short middle to Bri.Thomas for 12 yards")."""
    m = re.search(r" pass .*?\bto [A-Z][a-z]*\.\s?([A-Z][\w'-]+)", text)
    return [m.group(1)] if m else []


TURNOVERS = ("fumble", "interception")


def _x_url(names: list[str], team: str | None, opp: str | None, kind: str, when: str | None, approx: bool) -> str:
    """X's latest video posts about this one play: posted from the snap to 30 minutes after
    (wider when the play's time is estimated), naming the player (or, for a pass, its
    receiver: captions usually name the catch).
    - Turnovers: the defense's account usually posts these, often without his name or the
      word "fumble" ("BATES FORCES IT!"), and the NFL's account posts every game's
      turnovers. So it's every video from the two teams' own accounts in that window: they
      only post about their own game, and only a few times in half an hour.
    - Injuries: any account (reporters post these; official accounts rarely do)."""
    handles = lambda *ts, nfl=True: " OR ".join((["from:NFL"] if nfl else []) + [f"from:{X_HANDLES[t]}" for t in ts if t in X_HANDLES])
    who = " OR ".join(f'"{n}"' for n in names)
    who = f"({who})" if len(names) > 1 else who
    if kind in TURNOVERS:
        q = f"({handles(team, opp, nfl=False)})"
    elif kind == "injury":
        q = f"{who} (injury OR injured OR hurt OR carted OR down)"
    else:
        q = f"{who} ({handles(team)})"
    q += " filter:videos"
    if when:
        try:
            t = dt.datetime.fromisoformat(when.replace("Z", "+00:00"))
            before, after = (15, 45) if approx else (1, 30)
            q += f" since_time:{int((t - dt.timedelta(minutes=before)).timestamp())} until_time:{int((t + dt.timedelta(minutes=after)).timestamp())}"
        except ValueError:
            pass
    return "https://x.com/search?q=" + quote(q) + "&f=live"


def analyze(lg, rid: int | None = None, week: int | None = None) -> dict:
    lid = str(lg.cfg["league_id"])
    cur = lineup.current_week(lg)
    week = week or cur
    rid = rid or (lg.me or {}).get("roster_id")
    if not week:
        return {"week": None}
    live = week == cur
    ms = sleeper.live_matchups(lid, week) if live else sleeper.matchups(lid, week, True)
    mine = next((m for m in ms if m["roster_id"] == rid), None)
    if not mine:
        return {"week": week, "weeks": list(range(1, (cur or week) + 1)), "teams": [], "me": None}
    opp = next((m for m in ms if m.get("matchup_id") is not None and m.get("matchup_id") == mine.get("matchup_id")
                and m["roster_id"] != rid), None)
    G = espn.games(lg.season, week, live)
    scoring = lg.info.get("scoring_settings") or {}
    P = lineup.projections(lg.season, week)
    KD = _kd_points(lg.season, week)
    ST = _stats(lg.season, week, live)
    positions = lg.info.get("roster_positions") or []
    db = lg.players_db

    def player(pid, pts, slot=None):
        p = db.get(pid) or {}
        pos, team = p.get("position") or "?", p.get("team")
        if pos in ("K", "DEF"):
            proj = KD.get(pid, 0.0)
            team = team or (pid if pos == "DEF" else None)
        else:
            pr = P.get(pid)
            proj = lineup.score(pr["stats"], scoring) if pr and pr["stats"].get("gp", 1) else 0.0
        g = G.get(team)
        r = _remaining(g)
        return {"id": pid, "name": p.get("full_name") or (f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()) or pid,
                "pos": pos, "nfl_team": team, "slot": slot, "points": round(pts or 0.0, 2), "proj": round(proj, 1),
                "line": stat_line(pos, ST.get(pid) or {}), "breakdown": breakdown(ST.get(pid) or {}, scoring),
                "left": round(proj * r, 1), "sd_left": lineup.spread(pos if pos in lineup.SPREAD else "WR", proj) * math.sqrt(r),
                "game": {k: g[k] for k in ("state", "detail", "opp", "home", "possession", "red_zone", "score", "opp_score")} if g else None}

    def side(m):
        if not m:
            return None
        pts = m.get("players_points") or {}
        starters = [player(pid, p, slot) for pid, p, slot in zip(m.get("starters") or [], m.get("starters_points") or [], positions)
                    if pid and pid != "0"]
        ids = {s["id"] for s in starters}
        bench = sorted((player(pid, pts.get(pid)) for pid in m.get("players") or [] if pid not in ids), key=lambda b: -b["points"])
        total = m.get("points") or sum(s["points"] for s in starters)
        t = lg.teams.get(m["roster_id"]) or {}
        return {"roster_id": m["roster_id"], "manager": t.get("manager", f"Team {m['roster_id']}"), "points": round(total, 2),
                "final": round(total + sum(s["left"] for s in starters), 1), "sd": math.sqrt(sum(s["sd_left"] ** 2 for s in starters)),
                "to_play": sum(1 for s in starters if s["game"] and s["game"]["state"] != "post"),
                "starters": starters, "bench": bench}

    A, B = side(mine), side(opp)
    win = None
    if B:
        sd = math.sqrt(A["sd"] ** 2 + B["sd"] ** 2)
        win = 100.0 if sd < 1e-6 and A["final"] > B["final"] else 0.0 if sd < 1e-6 and A["final"] < B["final"] else \
            50.0 if sd < 1e-6 else _phi((A["final"] - B["final"]) / sd) * 100
    plays = big_plays(lg, [x for x in (A, B) if x], G, week, scoring)  # also tags injured players ("hurt")
    states = {g["state"] for g in G.values()}
    return {"week": week, "weeks": list(range(1, (cur or week) + 1)), "live": live, "season": lg.season,
            "poll": live and ("in" in states or "pre" in states), "roster_id": rid,
            "teams": [{"roster_id": m["roster_id"], "manager": (lg.teams.get(m["roster_id"]) or {}).get("manager")} for m in ms],
            "me": A, "opp": B, "win_pct": round(win, 1) if win is not None else None, "plays": plays,
            "games_on": sum(1 for g in G.values() if g["state"] == "in") // 2}


def big_plays(lg, sides: list[dict], G: dict, week: int, scoring: dict) -> list[dict]:
    """Big plays by any rostered QB/RB/WR/TE on either side, newest first."""
    db = lg.players_db
    by_event = {}
    for s in sides:
        for p, starter in [(x, True) for x in s["starters"]] + [(x, False) for x in s["bench"]]:
            g = G.get(p["nfl_team"])
            if p["pos"] not in SLOT_ELIGIBLE["SUPER_FLEX"] or not g or g["state"] == "pre":
                continue
            pat = name_pattern(db.get(p["id"]) or {})
            if pat:
                by_event.setdefault((g["event"], g["state"]), []).append((p, starter, s, pat, g))
    out = []
    for (event, state), cands in by_event.items():
        try:
            gm = espn.game(event, state)
        except Exception:  # one game's feed failing shouldn't hide the rest
            continue
        out += injuries(gm, cands, sides, week, lg.season)
        for pl in gm["plays"]:
            if pl["type"] == "Penalty" or "No Play" in pl["text"]:
                continue
            body = dict(pl, text=main_text(pl["text"]))
            for p, starter, s, pat, g in cands:
                if pl["team_id"] != g["team_id"]:
                    continue
                m = pat.search(body["text"])
                if not m:
                    continue
                r = role(body, m.start())
                if not r:
                    continue
                fumbled, lost = fumble(body, pat)
                # A receiver's play only when he caught it: an interception or incompletion thrown his way is the passer's.
                if r == "receiver" and pl["type"] not in COMPLETE and not fumbled:
                    continue
                pts = play_points(body, r, p["pos"], scoring, lost)
                # A long completion is the receiver's highlight; for the passer only TDs, turnovers and points count.
                big = (pl["score"] and pl["type"] in ("Passing Touchdown", "Rushing Touchdown")) or lost or \
                    (pl["turnover"] and "INTERCEPTED" in body["text"] and r == "passer") or \
                    (r != "passer" and abs(pl["yards"]) >= BIG_YARDS) or abs(pts) >= BIG_POINTS
                if not big:
                    continue
                info = db.get(p["id"]) or {}
                yt = _yt_url(g, p["nfl_team"], week, lg.season)
                when = pl["wallclock"] or _approx_time(g["date"], pl["period"], pl["clock"])
                head = headline(body, r, lost)
                kind = "fumble" if lost else "interception" if head == "Interception" else "play"
                out.append({"key": f"{pl['id']}:{p['id']}", "kind": "play", "pid": p["id"], "name": p["name"], "pos": p["pos"], "nfl_team": p["nfl_team"],
                            "opp": g["opp"], "side": "me" if s is sides[0] else "opp", "manager": s["manager"], "starter": starter,
                            "role": r, "headline": head, "text": pl["text"].strip(), "points": round(pts, 2),
                            "yards": pl["yards"], "td": pl["type"] in ("Passing Touchdown", "Rushing Touchdown"),
                            "turnover": pl["turnover"], "period": pl["period"], "clock": pl["clock"], "wallclock": when,
                            "x_url": _x_url([_last(info)] + (_receiver(body["text"]) if r == "passer" else []),
                                            p["nfl_team"], g["opp"], kind, when, not pl["wallclock"]),
                            "yt_url": yt, "game_over": g["state"] == "post"})
    out.sort(key=lambda x: (x["wallclock"] or "", x["period"] or 0), reverse=True)
    return out


RULING = {"Out": "ruled out", "Doubtful": "doubtful to return", "Questionable": "questionable to return"}


def _yt_url(g: dict, team: str, week: int, season: int) -> str:
    return "https://www.youtube.com/results?search_query=" + quote(
        f"{g.get('team_name') or team} vs {g.get('opp_name') or g['opp']} highlights week {week} {season}")


def injuries(gm: dict, cands: list, sides: list[dict], week: int, season: int) -> list[dict]:
    """In-game injuries to rostered players, as highlights: ESPN's play text notes who "was
    injured during the play", and the game's injury list gets rulings made after kickoff
    (out, doubtful or questionable to return). Also tags the player's lineup row ("hurt")."""
    out = []
    for p, starter, s, pat, g in cands:
        hurt = next((pl for pl in gm["plays"]
                     if any(pl["text"][x.end():].startswith(" was injured") for x in pat.finditer(pl["text"]))), None)
        kick = g.get("date") or ""
        st = next((i for i in gm["injuries"] if i["team"] == p["nfl_team"] and (i["date"] or "") >= kick
                   and name_key(i["name"] or "") == name_key(p["name"])), None)
        if not hurt and not st:
            continue
        ruling = RULING.get(st["status"], (st["status"] or "").lower()) if st else None
        part = st and st["part"]
        p["hurt"] = {"status": st["status"] if st else "Injured", "part": part}
        head = f"Injured: {ruling}" if ruling else "Injured on the play"
        when = (hurt["wallclock"] or _approx_time(kick, hurt["period"], hurt["clock"])) if hurt else st["date"]
        text = hurt["text"].strip() if hurt else ""
        if st:
            text += f"{' ' if text else ''}ESPN: {ruling}{f' ({part})' if part else ''}."
        out.append({"key": f"inj:{p['id']}", "kind": "injury", "pid": p["id"], "name": p["name"], "pos": p["pos"],
                    "nfl_team": p["nfl_team"], "opp": g["opp"], "side": "me" if s is sides[0] else "opp", "manager": s["manager"],
                    "starter": starter, "role": None, "headline": head + (f" ({part})" if part else ""), "text": text,
                    "points": None, "yards": 0, "td": False, "turnover": False,
                    "period": hurt["period"] if hurt else None, "clock": hurt["clock"] if hurt else None, "wallclock": when,
                    "x_url": _x_url([re.sub(r"\s+(Jr\.?|Sr\.?|II|III|IV|V)$", "", p["name"])], p["nfl_team"], g["opp"], "injury", when, not (hurt and hurt["wallclock"])),
                    "yt_url": _yt_url(g, p["nfl_team"], week, season), "game_over": g["state"] == "post"})
    return out
