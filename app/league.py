"""Builds the league snapshot: teams, rosters, picks, lineups, needs and contention windows."""
from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

from . import aging, calcfit, opportunity, pickvalue, seasonal, sleeper, store, tendencies
from .values import ValueBook

POSITIONS = ("QB", "RB", "WR", "TE")
SLOT_ELIGIBLE = {
    "QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"},
    "FLEX": {"RB", "WR", "TE"}, "WRRB_FLEX": {"RB", "WR"}, "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}
# Age at which dynasty value at each position typically starts falling off.
SELL_AGE = {"QB": 32, "RB": 26, "WR": 28, "TE": 29}
ROUND_NAMES = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}


def _age(p: dict) -> float | None:
    bd = p.get("birth_date")
    if bd:
        try:
            return round((dt.date.today() - dt.date.fromisoformat(bd)).days / 365.25, 1)
        except ValueError:
            pass
    return p.get("age")


def _z(values: list[float]) -> list[float]:
    if len(values) < 2:
        return [0.0] * len(values)
    m, s = statistics.mean(values), statistics.pstdev(values) or 1.0
    return [(v - m) / s for v in values]


class League:
    def __init__(self, cfg: dict, force: bool = False):
        self.cfg = cfg
        lid = cfg["league_id"]
        sleeper.LINKS[lid] = [str(x).strip() for x in cfg.get("linked_league_ids") or [] if str(x).strip()]
        self.info = sleeper.league(lid, force)
        if not self.info:
            raise ValueError(f"Sleeper has no league with ID {lid}. Check the ID in Settings.")
        self.users = {u["user_id"]: u for u in sleeper.users(lid, force=force)}
        raw_rosters = sleeper.rosters(lid, force=force)
        self.players_db = sleeper.players(force)
        self.values = ValueBook(self.info, cfg, force)
        store.migrate_legacy(lid)
        self.user_data = store.load(lid)
        self.season = int(self.info["season"])
        self.slots = [s for s in self.info.get("roster_positions", []) if s in SLOT_ELIGIBLE]
        self.superflex = "SUPER_FLEX" in self.slots or self.slots.count("QB") > 1
        st = self.info.get("settings", {})
        self.draft_rounds = st.get("draft_rounds", 3)
        self.history = [{"league_id": l["league_id"], "name": l.get("name"), "season": int(l["season"]),
                         "teams": l.get("total_rosters"), "linked": bool(l.get("_franchise"))}
                        for l in sleeper.league_chain(lid, force)]
        drafts = sleeper.cached_drafts(lid, force)
        current_draft_done = any(d.get("season") == str(self.season) and d.get("status") == "complete" for d in drafts)
        first = self.season + 1 if current_draft_done else self.season
        self.pick_seasons = [first, first + 1, first + 2]
        self.weeks_played = max((r["settings"].get("wins", 0) + r["settings"].get("losses", 0)
                                 + r["settings"].get("ties", 0)) for r in raw_rosters) if raw_rosters else 0

        self.teams: dict[int, dict] = {}
        for r in raw_rosters:
            u = self.users.get(r.get("owner_id")) or {}
            s = r.get("settings", {})
            taxi = set(r.get("taxi") or [])
            reserve = set(r.get("reserve") or [])
            team = {
                "roster_id": r["roster_id"],
                "owner_id": r.get("owner_id"),
                "manager": u.get("display_name") or f"Team {r['roster_id']}",
                "team_name": ((u.get("metadata") or {}).get("team_name") or "").strip(),
                "avatar": u.get("avatar"),
                "wins": s.get("wins", 0), "losses": s.get("losses", 0), "ties": s.get("ties", 0),
                "fpts": s.get("fpts", 0) + s.get("fpts_decimal", 0) / 100,
                "fpts_against": s.get("fpts_against", 0) + s.get("fpts_against_decimal", 0) / 100,
                "faab_used": s.get("waiver_budget_used", 0),
                "players": [],
                "picks": [],
            }
            for pid in r.get("players") or []:
                a = self.player_asset(pid)
                if a["pos"] not in POSITIONS:
                    continue
                a["taxi"] = pid in taxi
                a["ir"] = pid in reserve
                a["roster_id"] = r["roster_id"]
                team["players"].append(a)
            team["players"].sort(key=lambda a: -a["value"])
            self.teams[r["roster_id"]] = team

        self.me = next((t for t in self.teams.values()
                        if self.users.get(t["owner_id"], {}).get("display_name", "").lower() == cfg["username"].lower()), None)

        for t in self.teams.values():
            self._lineup(t)
        self._position_strength()
        try:
            self.opportunity = opportunity.analyze(self, force)
            self.opportunity_error = None
        except Exception as e:  # usage and contract feeds are extras; the rest still works
            self.opportunity = {"season": self.season, "role_season": self.season, "weeks": 0, "players": {}}
            self.opportunity_error = f"{type(e).__name__}: {e}"
        try:
            self.aging = aging.build(self)
            self.aging_error = None
        except Exception as e:  # value history is an extra too
            self.aging = {"curve": {}, "drift": {}, "hist": {"dates": [], "values": {}}}
            self.aging_error = f"{type(e).__name__}: {e}"
        try:
            self.seasonal = seasonal.analyze(self)
        except Exception:  # value history missing: no calendar notes
            self.seasonal = {"groups": [], "month": None}
        for t in self.teams.values():
            for a in t["players"]:
                self.annotate(a)
        # Pick tiers for the next draft depend on projected finish, which uses roster strength.
        self._windows(pre_picks=True)
        from . import rookies, season  # these import league
        try:
            self.sim = season.simulate(self)
        except Exception:  # no schedule or projections: picks fall back to tier prices
            self.sim = None
        from . import secondhalf
        try:
            self.h2 = secondhalf.build(self)
        except Exception:  # projections or usage missing: no second-half outlook
            self.h2 = None
        secondhalf.attach(self)
        try:
            self.rookies = rookies.analyze(self)
            self.rookies_error = None
        except Exception as e:  # history download failed: picks just don't get hit odds
            self.rookies, self.rookies_error = None, f"{type(e).__name__}: {e}"
        self._proj = pickvalue.Projector(self, self.sim, self.rookies)
        self._assign_picks(sleeper.traded_picks(lid, force))
        self.trades = sleeper.all_trades(lid, force)
        self.used_picks = sleeper.used_picks(lid, force)
        self.tendencies = tendencies.build(self)
        try:
            self.calcfit = calcfit.analyze(self)
            self.calcfit_error = None
        except Exception as e:  # KTC history is an extra; acceptance falls back to the blend
            self.calcfit = {"managers": [], "trades": 0, "sides": 0, "sources": list(calcfit.SOURCES)}
            self.calcfit_error = f"{type(e).__name__}: {e}"
        for m in self.calcfit["managers"]:
            if m["lean"] and m["user_id"] in self.tendencies:
                self.tendencies[m["user_id"]]["calc"] = {"source": m["lean"], "strength": m["strength"],
                                                         "n": m["n"], "diff_pct": m["diff_pct"]}
        self._windows(pre_picks=False)
        for t in self.teams.values():
            self._team_summary(t)
            for a in t["players"]:
                a["notes"] = player_notes(a, self)
        self._franchise()
        try:
            pickvalue.annotate_future(self, self._proj)
        except Exception:  # projections for later drafts are notes only
            pass

    # ------------------------------------------------------------ assets
    def player_asset(self, pid: str) -> dict:
        p = self.players_db.get(pid) or {}
        v = self.values.player(pid)
        return {
            "kind": "player", "id": pid,
            "name": p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() or pid,
            "pos": p.get("position") or "?", "nfl_team": p.get("team") or "FA",
            "age": _age(p), "years_exp": p.get("years_exp"), "injury": p.get("injury_status"),
            "value": round(v["value"]), "market": round(v["market"]), "redraft": round(v["redraft"]),
            "sources": v["sources"], "trend": round(v["trend"]) if v["trend"] is not None else None,
            "override": v["override"],
            "user_note": self.user_data["player_notes"].get(pid, ""),
        }

    def annotate(self, a: dict) -> dict:
        """Attach breakout/contract/depth info from the opportunity model to a player asset."""
        o = self.opportunity["players"].get(a["id"])
        a["breakout"] = o["breakout"] if o else 0
        a["opp_score"] = o["opp_score"] if o else None
        a["opp"] = o
        a["age_outlook"] = aging.outlook(self.aging["curve"], a["pos"], a["age"], a["value"], drift=self.aging["drift"])
        return a

    def pick_asset(self, season: int, rnd: int, orig: int, owner: int, tier: str | None) -> dict:
        v = self.values.pick(season, rnd, tier)
        orig_team = self.teams.get(orig, {})
        tier_txt = f", {tier.title()}" if tier else ""
        return {
            "kind": "pick", "id": f"{season}-{rnd}-{orig}",
            "name": f"{season} {ROUND_NAMES.get(rnd, f'R{rnd}')} ({orig_team.get('manager', orig)}{tier_txt})",
            "pos": "PICK", "season": season, "round": rnd, "orig_roster_id": orig, "roster_id": owner,
            "tier": tier, "age": None,
            "value": round(v["value"]), "market": round(v["market"]), "redraft": 0,
            "sources": v["sources"], "override": v["override"],
        }

    def _assign_picks(self, traded: list):
        owner = {}
        for season in self.pick_seasons:
            for rnd in range(1, self.draft_rounds + 1):
                for rid in self.teams:
                    owner[(season, rnd, rid)] = rid
        for tp in traded:
            key = (int(tp["season"]), tp["round"], tp["roster_id"])
            if key in owner:
                owner[key] = tp["owner_id"]
        # Next draft's picks get an early/mid/late tier from projected finish (weakest = early).
        order = sorted(self.teams.values(), key=lambda t: t["contend_score"])
        n = len(order)
        tier_of = {t["roster_id"]: ("early" if i < n / 3 else "mid" if i < 2 * n / 3 else "late")
                   for i, t in enumerate(order)}
        for (season, rnd, orig), own in sorted(owner.items()):
            if own not in self.teams:
                continue
            # Next year's picks: priced across the slots the season simulation says they can land in.
            info = self._proj.next_draft(season, rnd, orig)
            tier = info["tier"] if info else tier_of[orig] if season == self.pick_seasons[0] else None
            pk = self.pick_asset(season, rnd, orig, own, tier)
            if info:
                scale = info["value"] / (pk["value"] or 1)
                pk.update(value=round(info["value"]), market=round(info["market"]),
                          sources={k: round(v * scale) for k, v in pk["sources"].items()},
                          **{k: info[k] for k in ("slot_range", "exp_slot", "hit", "bust", "later", "kept") if k in info})
                pk["notes"] = self._proj.notes(info, "from the season simulation")
            self.teams[own]["picks"].append(pk)

    def asset(self, kind: str, aid: str) -> dict | None:
        for t in self.teams.values():
            for a in t["players"] + t["picks"]:
                if a["kind"] == kind and a["id"] == aid:
                    return a
        return None

    # ------------------------------------------------------------ team analysis
    def _lineup(self, t: dict):
        """Greedy best lineup by win-now (redraft) value; strict slots first, then flex."""
        pool = [a for a in t["players"] if not a["taxi"]]
        used, starters = set(), []
        order = sorted(self.slots, key=lambda s: len(SLOT_ELIGIBLE[s]))
        for slot in order:
            best = max((a for a in pool if a["id"] not in used and a["pos"] in SLOT_ELIGIBLE[slot]),
                       key=lambda a: a["redraft"], default=None)
            if best:
                used.add(best["id"])
                starters.append({"slot": slot, "id": best["id"], "name": best["name"], "pos": best["pos"],
                                 "redraft": best["redraft"]})
        t["starters"] = starters
        t["starter_ids"] = used
        t["starter_redraft"] = sum(s["redraft"] for s in starters)
        for a in t["players"]:
            a["starter"] = a["id"] in used

    def _position_strength(self):
        """Per-position strength (top-k by redraft and by dynasty) and z-scored needs."""
        k = {"QB": 2 if self.superflex else 1, "RB": 3, "WR": 4, "TE": 1}
        teams = list(self.teams.values())
        for t in teams:
            t["pos_now"], t["pos_future"], t["pos_depth"] = {}, {}, {}
            for pos in POSITIONS:
                ps = [a for a in t["players"] if a["pos"] == pos]
                now = sorted((a["redraft"] for a in ps), reverse=True)
                fut = sorted((a["value"] for a in ps), reverse=True)
                t["pos_now"][pos] = sum(now[:k[pos]])
                t["pos_future"][pos] = sum(fut[:k[pos]])
                t["pos_depth"][pos] = sum(fut[k[pos]:k[pos] + 3])
        for pos in POSITIONS:
            for field, out in (("pos_now", "need_now"), ("pos_future", "need_future"), ("pos_depth", "depth_z")):
                zs = _z([t[field][pos] for t in teams])
                for t, z in zip(teams, zs):
                    # Needs are positive when the team is below league average.
                    t.setdefault(out, {})[pos] = round(z if out == "depth_z" else -z, 2)

    def _windows(self, pre_picks: bool):
        teams = list(self.teams.values())
        z_str = _z([t["starter_redraft"] for t in teams])
        games = max(self.weeks_played, 1)
        z_win = _z([(t["wins"] + 0.5 * t["ties"]) / games for t in teams])
        z_pf = _z([t["fpts"] for t in teams])
        # Record matters more as the season goes on (up to 45% weight by week 14).
        g = min(self.weeks_played / 14, 1.0) * 0.45
        for t, a, b, c in zip(teams, z_str, z_win, z_pf):
            win_now = (1 - g) * a + g * (0.5 * b + 0.5 * c)
            t["win_now_z"] = round(win_now, 2)
            behavior = 0.0
            if not pre_picks:
                tend = self.tendencies.get(t["owner_id"]) or {}
                behavior = tend.get("window_signal", 0.0)  # +1 buying vets, -1 buying youth/picks
            score = 50 + 22 * win_now + 8 * behavior
            t["contend_score"] = round(max(0, min(100, score)), 1)
        if pre_picks:
            return
        for t in teams:
            override = self.user_data["window_overrides"].get(t["owner_id"] or "")
            if t is self.me and self.cfg.get("my_strategy") in ("rebuild", "contend"):
                override = self.cfg["my_strategy"]
            if override:
                t["window"] = override
                t["window_source"] = "you"
                t["w"] = {"contend": 0.85, "middle": 0.5, "rebuild": 0.15}[override]
            else:
                s = t["contend_score"]
                t["window"] = "contend" if s >= 60 else "rebuild" if s <= 40 else "middle"
                t["window_source"] = "auto"
                t["w"] = s / 100

    def _team_summary(self, t: dict):
        vals = [a for a in t["players"] if a["value"] > 0]
        tv = sum(a["value"] for a in vals) or 1
        t["dynasty_total"] = round(sum(a["value"] for a in t["players"]))
        t["pick_total"] = round(sum(p["value"] for p in t["picks"]))
        t["avg_age_weighted"] = round(sum((a["age"] or 26) * a["value"] for a in vals) / tv, 1)
        t["needs"] = self._needs_text(t)
        t["surplus"] = [pos for pos in POSITIONS if t["depth_z"][pos] >= 0.8]
        t["sell_candidates"] = [a["id"] for a in t["players"] if is_sell_candidate(a)]

    def _franchise(self):
        """Franchise value = every rostered player + every owned pick, on the same value
        scale. Franchise score = that total relative to the league average (100 = average)."""
        for t in self.teams.values():
            t["franchise_value"] = t["dynasty_total"] + t["pick_total"]
        avg = statistics.mean(t["franchise_value"] for t in self.teams.values()) or 1
        ranked = sorted(self.teams.values(), key=lambda t: -t["franchise_value"])
        for i, t in enumerate(ranked):
            t["franchise_score"] = round(t["franchise_value"] / avg * 100)
            t["franchise_rank"] = i + 1

    def _needs_text(self, t):
        field = "need_now" if t.get("w", 0.5) >= 0.5 else "need_future"
        ranked = sorted(POSITIONS, key=lambda p: -t[field][p])
        return [p for p in ranked if t[field][p] >= 0.5]

    def team_list(self):
        return sorted(self.teams.values(), key=lambda t: -t["contend_score"])


def is_sell_candidate(a: dict) -> bool:
    """Players whose age curve says sell (or, without one, near the age cliff), or whose
    current production outruns their dynasty price."""
    if a["kind"] != "player" or a["value"] < 1000:
        return False
    o = a.get("age_outlook")
    if o:
        old = o["verdict"] in ("sell", "soon")
    else:
        old = a["age"] is not None and a["age"] >= SELL_AGE.get(a["pos"], 30) - 0.5
    win_now_heavy = a["redraft"] > a["value"] * 1.25
    return old or win_now_heavy


def capital_note(pr: dict) -> str:
    """Draft-capital odds for a player in his first three seasons (rookies.prospects)."""
    n = pr["pick"]
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    txt = (f"Drafted {n}{suffix} overall in {pr['year']}: {pr['pos']}s taken around there have had a starter season in their "
           f"first 3 years {pr['hit']:.0f}% of the time (elite {pr['elite']:.0f}%, bust {pr['bust']:.0f}%).")
    if pr.get("so_far") in ("elite", "starter"):
        txt += f" He already has: {pr['pos']}{pr['best']} in {pr['best_season']}."
    elif pr.get("seasons"):
        txt += f" No starter season yet after {pr['seasons']} season{'s' if pr['seasons'] > 1 else ''}."
    return txt


def player_notes(a: dict, lg: "League") -> list[str]:
    notes = []
    age, pos, v = a["age"], a["pos"], a["value"]
    age_note = aging.note(a.get("age_outlook"), pos, age)
    if age_note:
        notes.append(age_note)
    elif age is not None and age <= 23.5 and v >= 3000:
        notes.append(f"Young ({age:g}) and already valuable; a cornerstone for a rebuild.")
    if v >= 1500 and len(a["sources"]) >= 2:
        hi = max(a["sources"], key=a["sources"].get)
        lo = min(a["sources"], key=a["sources"].get)
        if a["sources"][lo] and a["sources"][hi] / a["sources"][lo] >= 1.25:
            from .values import SOURCE_LABELS
            pct = round((a["sources"][hi] / a["sources"][lo] - 1) * 100)
            notes.append(f"Sources disagree: {SOURCE_LABELS[hi]} is {pct}% higher than {SOURCE_LABELS[lo]}.")
    if a.get("trend") and v > 1000:
        pct = a["trend"] / v * 100
        if pct >= 8:
            notes.append(f"Rising: +{pct:.0f}% in the last 30 days (FantasyCalc).")
        elif pct <= -8:
            notes.append(f"Falling: {pct:.0f}% in the last 30 days (FantasyCalc).")
    if v >= 1500 and a["redraft"] > v * 1.25:
        notes.append("Win-now value exceeds dynasty price: worth more to contenders than to the market.")
    elif v >= 2000 and a["redraft"] < v * 0.6:
        notes.append("Valued on future upside, not current production; contenders will discount him.")
    o = a.get("opp")
    if o:
        c = o.get("contract") or {}
        if c.get("leave_why") and not c["leave_why"].startswith("Age "):  # age is covered above
            notes.append(c["leave_why"] + ".")
        elif c.get("end") is not None and c["end"] <= lg.season:
            notes.append(f"Contract ends after {lg.season}.")
        for n in o["notes"]:
            notes.append(n["text"] + ".")
        if o["breakout"] >= 40:
            notes.append(f"Breakout score {o['breakout']}: role and contract signals point to a bigger role ahead.")
    if v >= seasonal.MIN_VALUE:
        cal = seasonal.note(seasonal.outlook(lg.seasonal, pos, age))
        if cal:
            notes.append(cal)
    pr = ((getattr(lg, "rookies", None) or {}).get("prospects") or {}).get(a["id"])
    if pr:
        notes.append(capital_note(pr))
    from .secondhalf import note as h2_note
    h2 = h2_note(a)
    if h2:
        notes.append(h2)
    if a.get("injury"):
        notes.append(f"Injury status: {a['injury']}.")
    if a.get("taxi"):
        notes.append("On taxi squad.")
    return notes
