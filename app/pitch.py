"""A short message to send with a trade offer, from Team A to Team B.

Offers with a reason attached get a better hearing. Every point here is something the app
already computes about the deal from B's side, and only points that are true and in B's
favor are used: their positional need, what it does to their lineup and playoff odds, their
window, the calculator they seem to trade by (or any calculator that has them ahead), and
their trade habits. Nothing about A's own gain.
"""
from __future__ import annotations

from . import season
from .league import SLOT_ELIGIBLE
from .values import SOURCE_LABELS

MAX_POINTS = 3


def _who(a: dict) -> str:
    if a["kind"] == "pick":
        return a["name"]
    age = f", {a['age']:.0f}" if a.get("age") else ""
    return f"{a['name']} ({a['pos']}{age})"


def _list(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _would_start(team: dict, a: dict) -> bool:
    """Would he beat one of their current starters for a slot he can fill (win-now value)?"""
    return any(a["pos"] in SLOT_ELIGIBLE[s["slot"]] and a.get("redraft", 0) > s["redraft"] for s in team.get("starters", []))


def _ppg(a: dict) -> float | None:
    role = ((a.get("opp") or {}).get("role") or {})
    return role.get("ppg")


def write(lg, ev: dict, with_odds: bool = True) -> dict:
    a_gives, b_gives = ev["a_gives"], ev["b_gives"]
    A, B = (lg.teams[s["roster_id"]] for s in ev["sides"])
    side_b = ev["sides"][1]
    tend = lg.tendencies.get(B["owner_id"]) or {}
    points = []

    # What they need, and whether it plays for them (not claimed if the deal weakens their lineup overall).
    lineup = side_b["impact"]["lineup_delta_pct"]
    for a in a_gives if lineup >= 0 else []:
        if a["kind"] == "player" and a["pos"] in B.get("needs", []) and _would_start(B, a):
            ppg = _ppg(a)
            points.append(f"You could use {a['pos']} help, and {a['name']} would slot right in"
                          + (f" ({ppg:.1f} points a game this season)." if ppg else "."))
            break
    if lineup >= 2:
        points.append(f"It makes your starting lineup about {lineup:.0f}% stronger for this season.")
    if with_odds:
        try:
            imp = season.trade_impact(lg, A["roster_id"], a_gives, B["roster_id"], b_gives)
        except Exception:
            imp = None
        if imp:
            b = imp["teams"][1]
            lo, hi = b["playoff_pct"]
            if hi - lo >= 2 and lo < 97:
                points.append(f"By my projections it moves your playoff odds from {lo:.0f}% to {hi:.0f}%.")
    young = [a for a in a_gives if a["kind"] == "pick" or (a.get("age") or 99) <= 24.5]
    if B["window"] == "rebuild" and young:
        points.append(f"You get younger: {_list([a['name'] for a in young])}.")
    elif B["window"] == "contend" and any(a["kind"] == "player" and a.get("redraft", 0) > a["value"] for a in a_gives):
        points.append("It's win-now help for your playoff push.")

    # A calculator that has them ahead: theirs if we know it, otherwise any.
    by = {s: -v["pct"] for s, v in ev["by_source"].items()}  # B's side
    lean = (tend.get("calc") or {}).get("source")
    src = lean if lean in by and by[lean] >= 0 else max(by, key=by.get) if by else None
    if src and by[src] >= 0:
        points.append(f"On {SOURCE_LABELS[src]} it comes out {'even' if by[src] < 1 else f'{by[src]:+.0f}%'} for you.")

    n_get, n_give = len(a_gives), len(b_gives)
    if tend.get("consolidation", 0) >= 0.3 and n_get < n_give:
        points.append("You consolidate into the best piece in the deal.")
    elif tend.get("consolidation", 0) <= -0.3 and n_get > n_give:
        points.append(f"You turn {n_give} piece{'s' if n_give > 1 else ''} into {n_get}.")

    points = list(dict.fromkeys(points))[:MAX_POINTS]
    give = _list([_who(a) for a in a_gives])
    get = _list([_who(a) for a in b_gives])
    text = f"Hey {B['manager']}, I'd send you {give} for {get}."
    if points:
        text += "\n\n" + "\n".join(f"- {p}" for p in points)
    text += "\n\nOpen to tweaks if you want to counter."
    return {"text": text, "points": points, "to": B["manager"]}
