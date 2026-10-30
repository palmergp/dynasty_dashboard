"""Buy-low detector: players whose market value has dropped while their role hasn't.

A drop with an intact role is usually a scare, not a decline: a few quiet games, a minor
injury, a crowded headline. Those are the cheapest times to buy (and the worst times to
sell your own).

- Drop: today's DynastyProcess value vs. his high over the last ~4 months (weekly values).
- Role intact: over his last 3 games he still has at least 85% of his season share of his
  team's opportunities at his position (targets/carries/dropbacks), and a real role.
- Injury dips count too, flagged as such: an injured player's last 3 games are his last
  healthy ones, so "role intact" means the role he'll return to.
- Players whose age curve says "sell now" or "sell within a year" (or who are 33+) are left
  out; a falling value is expected there.
"""
from __future__ import annotations

import datetime as dt

LOOKBACK_DAYS = 120
MIN_DROP = 0.15
MIN_HIGH = 800
MIN_ROLE = 0.35        # opportunity model's role level (1 = a full starter's share)
KEEP_SHARE = 0.85      # recent share vs. season share
MAX_AGE = 33
DEEP = 0.25            # past this, a bigger drop hasn't meant a bigger rebound (checks.buy_low)
HURT = {"IR", "Out", "Doubtful", "PUP", "NFI", "Sus"}


def analyze(lg) -> dict:
    hist = lg.aging["hist"]
    dates, hv = hist["dates"], hist["values"]
    if not dates:
        return {"players": [], "as_of": None}
    cutoff = (dt.date.fromisoformat(dates[-1]) - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    j0 = next((j for j, d in enumerate(dates) if d >= cutoff), 0)
    owner = {a["id"]: t for t in lg.teams.values() for a in t["players"]}
    me = lg.me["roster_id"] if lg.me else None
    rows = []
    for pid, o in lg.opportunity["players"].items():
        series = hv.get(pid)
        role = o.get("role")
        if not series or not role or series[-1] is None:
            continue
        window = [(v, j) for j, v in enumerate(series[j0:], j0) if v is not None]
        high, jh = max(window)
        now = series[-1]
        drop = 1 - now / high if high else 0
        if high < MIN_HIGH or drop < MIN_DROP:
            continue
        t = owner.get(pid)
        a = next((x for x in t["players"] if x["id"] == pid), None) if t else lg.annotate(lg.player_asset(pid))
        verdict = (a.get("age_outlook") or {}).get("verdict")
        if verdict in ("sell", "soon") or (a.get("age") or 0) >= MAX_AGE or a["value"] < 300:
            continue
        injured = a.get("injury") in HURT
        intact = role["games"] >= 3 and role["share_l3"] >= KEEP_SHARE * role["share"] and o["role_level"] >= MIN_ROLE
        if not intact and not (injured and o["role_level"] >= MIN_ROLE):
            continue
        reasons = [f"Down {drop:.0%} from his {dates[jh]} high ({high:,.0f} → {now:,.0f}, DynastyProcess)."]
        if injured:
            reasons.append(f"Injured ({a['injury']}). Before that he had {role['share_l3']:.0%} of his team's {a['pos']} opportunities over his last 3 games.")
        elif a["pos"] == "QB" and role["share_l3"] >= 0.8:
            reasons.append(f"Still the starter: {role['share_l3']:.0%} of his team's QB pass attempts and runs over his last 3 games.")
        else:
            reasons.append(f"Same role: {role['share_l3']:.0%} of his team's {a['pos']} opportunities over his last 3 games ({role['share']:.0%} on the season).")
        slump = role.get("ppg_l3") is not None and role["ppg"] and role["ppg_l3"] < 0.8 * role["ppg"]
        if slump:
            reasons.append(f"Scoring slump: {role['ppg_l3']:.1f} points a game over his last 3 vs. {role['ppg']:.1f} on the season.")
        if verdict == "rising":
            reasons.append("Young enough that his age curve is still rising.")
        if a.get("breakout", 0) >= 35:
            reasons.append(f"Breakout score {a['breakout']}.")
        weight = min(1.5, (a["value"] / 2000) ** 0.5)
        score = min(drop, DEEP) * (0.5 + min(1.0, o["role_level"])) * weight * (1.15 if verdict == "rising" else 1.0) * (0.8 if injured else 1.0)
        rows.append({**{k: a.get(k) for k in ("id", "name", "pos", "nfl_team", "age", "value", "injury", "breakout", "years_exp")},
                     "kind": "injury" if injured else "slump" if slump else "dip",
                     "high": round(high), "high_date": dates[jh], "now_dp": round(now), "drop_pct": round(drop * 100, 1),
                     "share": role["share"], "share_l3": role["share_l3"], "ppg": role["ppg"], "ppg_l3": role.get("ppg_l3"),
                     "verdict": verdict, "reasons": reasons, "score": round(score * 100, 1),
                     "owner": t["manager"] if t else None, "owner_rid": t["roster_id"] if t else None,
                     "mine": bool(t and t["roster_id"] == me),
                     "spark": [round(v) if v is not None else None for v in series[j0:]]})
    rows.sort(key=lambda r: -r["score"])
    return {"players": rows, "as_of": dates[-1], "lookback_days": LOOKBACK_DAYS, "min_drop_pct": MIN_DROP * 100}
