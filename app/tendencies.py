"""Manager trade tendencies, mined from every completed trade in the league's history.

Trades are credited to the user who managed the roster when the trade happened, so a
new owner doesn't inherit the previous owner's habits.

Note: historical trades are valued with *current* values (no historical value feed is
available), so "who won" has hindsight baked in. Structural tendencies (consolidation,
picks, age, positions) don't depend much on that.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict

from . import sleeper

POSITIONS = ("QB", "RB", "WR", "TE", "PICK")
PICK_PROXY_AGE = 21.0  # a draft pick is a future rookie


def package_value(values: list[float], p: float) -> float:
    """Consolidation-aware package value: (sum v^p)^(1/p). One great asset > two good ones."""
    vals = [max(v, 0.0) for v in values]
    if not vals:
        return 0.0
    return sum(v ** p for v in vals) ** (1 / p)


def _clip(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def _age_at(p: dict, ts_ms) -> float | None:
    if p.get("birth_date"):
        try:
            return (dt.date.fromtimestamp(ts_ms / 1000) - dt.date.fromisoformat(p["birth_date"])).days / 365.25
        except ValueError:
            pass
    return None


def _hist_asset(lg, kind, data, ts_ms):
    if kind == "player":
        pid = data
        p = lg.players_db.get(pid) or {}
        v = lg.values.player(pid)
        return {"kind": "player", "id": pid, "name": p.get("full_name") or pid, "pos": p.get("position") or "?",
                "value": v["market"], "redraft": v["redraft"], "age": _age_at(p, ts_ms)}
    season, rnd = int(data["season"]), data["round"]
    name = f"{season} Round {rnd} pick"
    drafted, startup = lg.used_picks.get((season, rnd, data["roster_id"]), (None, False))
    if drafted and startup:
        # Startup-draft picks are really players, so tendencies treat them as the player taken.
        p = lg.players_db.get(drafted) or {}
        v = lg.values.player(drafted)
        return {"kind": "player", "id": drafted, "name": f"Startup R{rnd} → {p.get('full_name') or drafted}",
                "pos": p.get("position") or "?", "value": v["market"], "redraft": v["redraft"],
                "age": _age_at(p, ts_ms)}
    if drafted:
        # Used picks are valued as the player that was drafted (consistent with valuing
        # traded players at today's values).
        v = lg.values.player(drafted)
        dname = (lg.players_db.get(drafted) or {}).get("full_name") or drafted
        name += f" → {dname}"
    else:
        # Not yet used (or unknown): a generic pick of that round from the next open draft.
        vs = season if season >= lg.pick_seasons[0] else lg.pick_seasons[0]
        v = lg.values.pick(vs, rnd, None)
    return {"kind": "pick", "id": f"{season}-{rnd}-{data['roster_id']}", "name": name,
            "pos": "PICK", "value": v["market"], "redraft": 0.0, "age": PICK_PROXY_AGE, "season": season,
            "round": rnd, "orig_roster_id": data["roster_id"], "drafted": drafted}


def _manager_names(lg) -> dict:
    names = {}
    for l in sleeper.league_chain(lg.cfg["league_id"]):
        for u in sleeper.users(l["league_id"]):
            names.setdefault(u["user_id"], u.get("display_name"))
    return names


def _first_season(lg) -> dict:
    first = {}
    for l in sleeper.league_chain(lg.cfg["league_id"]):
        for r in sleeper.rosters(l["league_id"]):
            if r.get("owner_id"):
                first[r["owner_id"]] = min(first.get(r["owner_id"], 9999), int(l["season"]))
    return first


def parse_trades(lg) -> list[dict]:
    """Normalize raw Sleeper trades into sides with valued assets."""
    p = lg.cfg["consolidation_exponent"]
    names = _manager_names(lg)
    out = []
    for tx in lg.trades:
        ts = tx.get("status_updated") or tx.get("created") or 0
        sides = []
        for rid in tx.get("roster_ids", []):
            uid = tx["roster_owner"].get(str(rid))
            recv, sent = [], []
            for pid, to in (tx.get("adds") or {}).items():
                if to == rid:
                    recv.append(_hist_asset(lg, "player", pid, ts))
            for pid, frm in (tx.get("drops") or {}).items():
                if frm == rid:
                    sent.append(_hist_asset(lg, "player", pid, ts))
            for dp in tx.get("draft_picks") or []:
                if dp["owner_id"] == rid:
                    recv.append(_hist_asset(lg, "pick", dp, ts))
                if dp["previous_owner_id"] == rid:
                    sent.append(_hist_asset(lg, "pick", dp, ts))
            faab = sum(w["amount"] for w in tx.get("waiver_budget") or [] if w.get("receiver") == rid)
            sides.append({
                "roster_id": rid, "user_id": uid, "manager": names.get(uid, f"Team {rid}"),
                "received": recv, "sent": sent, "faab": faab,
                "recv_value": round(package_value([a["value"] for a in recv], p)),
                "sent_value": round(package_value([a["value"] for a in sent], p)),
            })
        if not sides:
            continue
        best = max(sides, key=lambda s: s["recv_value"] - s["sent_value"])
        margin = (best["recv_value"] - best["sent_value"]) / (max(best["recv_value"], best["sent_value"]) or 1)
        out.append({
            "id": tx["transaction_id"], "season": tx["season"], "week": tx.get("leg"),
            "date": dt.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d"), "ts": ts,
            "sides": sides, "winner": best["manager"] if margin >= 0.05 else None,
        })
    return out


def build(lg) -> dict:
    """user_id -> tendency profile."""
    trades = parse_trades(lg)
    lg.parsed_trades = trades
    first = _first_season(lg)
    league_first = min(first.values()) if first else lg.season
    by_user = defaultdict(list)
    for t in trades:
        for s in t["sides"]:
            if s["user_id"]:
                partners = [o["user_id"] for o in t["sides"] if o is not s]
                by_user[s["user_id"]].append((t, s, partners))

    names = _manager_names(lg)
    my_uid = lg.me["owner_id"] if lg.me else None
    profiles = {}
    for team in lg.teams.values():
        uid = team["owner_id"]
        rows = by_user.get(uid, [])
        profiles[uid] = _profile(rows, uid, names, my_uid, first.get(uid, lg.season), league_first, lg.season)
    return profiles


def _profile(rows, uid, names, my_uid, first_season, league_first, season) -> dict:
    n = len(rows)
    conf = n / (n + 3)
    prof = {
        "n_trades": n, "confidence": round(conf, 2), "tags": [], "notes": [],
        "pos_affinity": {p: 0.0 for p in POSITIONS}, "pick_affinity": 0.0, "youth_affinity": 0.0,
        "consolidation": 0.0, "value_edge": 0.0, "window_signal": 0.0, "partners": {},
        "trade_ids": [t["id"] for t, _, _ in rows], "new_manager": first_season > league_first,
        "first_season": first_season,
    }
    if prof["new_manager"]:
        prof["notes"].append(f"Took over this team in {first_season}; only their own trades are counted.")
    if n == 0:
        prof["tags"].append("No trade history")
        prof["notes"].append("Hasn't made a trade yet. Expect a fair-value, low-risk offer to be needed.")
        return prof

    count_diff, edges, fewer = [], [], 0
    pos_net = defaultdict(float)
    pick_net = volume = 0.0
    age_r = age_s = w_r = w_s = 0.0
    redraft_net = 0.0
    partners = Counter()
    for t, s, ps in rows:
        nr, ns = len(s["received"]), len(s["sent"])
        count_diff.append(nr - ns)
        fewer += nr < ns
        size = max(s["recv_value"], s["sent_value"], 1)
        edges.append((s["recv_value"] - s["sent_value"]) / size)
        for a in s["received"]:
            pos_net[a["pos"]] += a["value"]
            volume += a["value"]
            redraft_net += a["redraft"]
            if a["age"] is not None:
                age_r += a["age"] * a["value"]
                w_r += a["value"]
            if a["kind"] == "pick":
                pick_net += a["value"]
        for a in s["sent"]:
            pos_net[a["pos"]] -= a["value"]
            volume += a["value"]
            redraft_net -= a["redraft"]
            if a["age"] is not None:
                age_s += a["age"] * a["value"]
                w_s += a["value"]
            if a["kind"] == "pick":
                pick_net -= a["value"]
        partners.update(p for p in ps if p)

    volume = volume or 1
    prof["consolidation"] = round(_clip(-sum(count_diff) / n / 1.5), 2)  # + = gets fewer, better pieces
    prof["pick_affinity"] = round(_clip(pick_net / volume * 2.5), 2)
    age_delta = (age_r / w_r if w_r else 25) - (age_s / w_s if w_s else 25) if (w_r and w_s) else 0.0
    prof["avg_age_delta"] = round(age_delta, 1)
    prof["youth_affinity"] = round(_clip(-age_delta / 3), 2)
    prof["pos_affinity"] = {p: round(_clip(pos_net.get(p, 0) / volume * 2.5), 2) for p in POSITIONS}
    prof["value_edge"] = round(sum(edges) / n, 3)
    prof["window_signal"] = round(_clip((-prof["youth_affinity"] - prof["pick_affinity"]) / 2 * 1.5) * conf, 2)
    prof["partners"] = {names.get(p, p): c for p, c in partners.most_common()}
    prof["with_me"] = partners.get(my_uid, 0) if my_uid else 0

    # ---- human-readable tags & notes
    seasons = max(season - first_season + 1, 1)
    per = n / seasons
    tags, notes = prof["tags"], prof["notes"]
    if per >= 5:
        tags.append("Very active")
    elif per <= 1.5:
        tags.append("Rarely trades")
    notes.append(f"{n} trade{'s' if n != 1 else ''} since {first_season} ({per:.1f}/season).")
    if prof["consolidation"] >= 0.3:
        tags.append("Consolidator")
        notes.append(f"Got back fewer pieces than they sent in {fewer} of {n} trades. Offer them one stud for several assets.")
    elif prof["consolidation"] <= -0.3:
        tags.append("Depth seeker")
        notes.append("Usually takes back more pieces than they send. Will split a stud into several assets.")
    if prof["pick_affinity"] >= 0.25:
        tags.append("Pick buyer")
        notes.append("Net acquirer of draft picks. Picks are good currency with them, but they won't sell theirs cheap.")
    elif prof["pick_affinity"] <= -0.25:
        tags.append("Pick seller")
        notes.append("Net seller of draft picks. Ask for their picks.")
    if prof["youth_affinity"] >= 0.3:
        tags.append("Buys youth")
        notes.append(f"Players they get back are {abs(age_delta):.1f} yrs younger on average (value-weighted).")
    elif prof["youth_affinity"] <= -0.3:
        tags.append("Buys veterans")
        notes.append(f"Players they get back are {abs(age_delta):.1f} yrs older on average. Win-now mindset.")
    fav = max(("QB", "RB", "WR", "TE"), key=lambda p: prof["pos_affinity"][p])
    if prof["pos_affinity"][fav] >= 0.3:
        tags.append(f"Targets {fav}s")
        notes.append(f"Has been adding {fav} value through trades.")
    dump = min(("QB", "RB", "WR", "TE"), key=lambda p: prof["pos_affinity"][p])
    if prof["pos_affinity"][dump] <= -0.3:
        notes.append(f"Has been moving {dump}s out.")
    if prof["value_edge"] >= 0.08:
        tags.append("Shark")
        notes.append(f"Has come out ahead by about {prof['value_edge'] * 100:.0f}% per trade (by today's values). Expect hard negotiating.")
    elif prof["value_edge"] <= -0.08:
        tags.append("Generous")
        notes.append(f"Has given up about {abs(prof['value_edge']) * 100:.0f}% per trade (by today's values). Room to ask for more.")
    if prof["partners"]:
        top, cnt = next(iter(prof["partners"].items()))
        if cnt >= 2:
            notes.append(f"Most frequent partner: {top} ({cnt} trades).")
    if prof.get("with_me"):
        notes.append(f"Has traded with you {prof['with_me']} time{'s' if prof['with_me'] != 1 else ''}.")
    if n < 3:
        notes.append("Small sample: tendencies are only lightly applied.")
    return prof
