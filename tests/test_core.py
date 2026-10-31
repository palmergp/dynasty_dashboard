"""Offline tests for the valuation and modeling helpers."""
from app import sleeper
from app.tendencies import package_value
from app.trade import acceptance, context_value, perceived_gain
from app.values import _consensus_mappers, _parse_pick, name_key


def test_package_value_stud_premium():
    assert package_value([5000], 1.35) == 5000
    two = package_value([3000, 3000], 1.35)
    assert 3000 < two < 6000  # two good players < their raw sum
    assert package_value([3000, 3000], 1.0) == 6000
    assert package_value([], 1.35) == 0


def test_parse_pick_formats():
    assert _parse_pick("2027 1st (Early)") == (2027, 1, "early")
    assert _parse_pick("2027 Early 1st") == (2027, 1, "early")
    assert _parse_pick("2028 2nd") == (2028, 2, None)
    assert _parse_pick("2029 Late 3rd") == (2029, 3, "late")
    assert _parse_pick("2026 Pick 1.01") is None


def test_name_key_normalizes_suffixes_and_punctuation():
    assert name_key("Marvin Harrison Jr.") == name_key("Marvin Harrison")
    assert name_key("Ja'Marr Chase") == "jamarr chase"
    assert name_key("Amon-Ra St. Brown") == "amon ra st brown"


def test_consensus_mapping_preserves_order_and_aligns_shapes():
    steep = {"players": [{"value": v} for v in (10000, 5000, 2500, 1250, 600)], "picks": []}
    flat = {"players": [{"value": v} for v in (9000, 8000, 7000, 6000, 5000)], "picks": []}
    m = _consensus_mappers({"a": steep, "b": flat})
    # Same rank -> same consensus value, regardless of each source's curve shape.
    assert abs(m["a"](2500) - m["b"](7000)) < 1e-6
    # Monotone within a source, including interpolated values.
    xs = [10000, 7000, 5000, 3000, 2500, 1000, 600]
    ys = [m["a"](x) for x in xs]
    assert ys == sorted(ys, reverse=True)


def _team(w, needs=None):
    return {"w": w, "need_now": needs or {}, "need_future": needs or {}}


def test_context_value_contender_vs_rebuilder():
    vet = {"kind": "player", "pos": "RB", "age": 28.5, "value": 4000, "redraft": 7000}
    prospect = {"kind": "player", "pos": "WR", "age": 21.5, "value": 4000, "redraft": 800}
    pick = {"kind": "pick", "pos": "PICK", "value": 3000}
    contender, rebuilder = _team(0.85), _team(0.15)
    assert context_value(vet, contender) > context_value(vet, rebuilder)
    assert context_value(prospect, rebuilder) > context_value(prospect, contender)
    assert context_value(pick, rebuilder) > context_value(pick, contender)


def test_tendencies_tilt_context_value():
    young = {"kind": "player", "pos": "WR", "age": 22, "value": 4000, "redraft": 2000}
    base = {"pos_affinity": {"WR": 0.0}, "youth_affinity": 0.0, "pick_affinity": 0.0, "confidence": 1.0}
    likes_youth = {**base, "youth_affinity": 1.0}
    t = _team(0.5)
    assert context_value(young, t, likes_youth) > context_value(young, t, base)


def test_acceptance_monotone_and_shark_threshold():
    neutral = {"confidence": 1.0, "value_edge": 0.0, "consolidation": 0.0}
    shark = {**neutral, "value_edge": 0.2}
    lo, _ = acceptance(-0.1, neutral, 1, 1)
    hi, _ = acceptance(0.1, neutral, 1, 1)
    assert lo < 50 < hi
    assert acceptance(0.03, shark, 1, 1)[0] < acceptance(0.03, neutral, 1, 1)[0]


def test_perceived_gain_blends_context_and_market():
    assert perceived_gain(110, 100, 100, 100) == 0.5 * (10 / 110)
    assert perceived_gain(100, 100, 100, 100, cut_val=10) < 0


def test_draft_day_value_lookup():
    from app.drafts import _value_at
    dates = ["2025-06-06", "2025-06-13", "2025-06-20"]
    assert _value_at([100, 200, 300], dates, "2025-06-15") == 200  # last snapshot on/before
    assert _value_at([None, None, 300], dates, "2025-06-08") == 300  # rookie: first one after
    assert _value_at([None, None, None], dates, "2025-06-08") == 0.0


def test_kickoff_is_thursday_after_labor_day():
    from app.waivers import _kickoff
    assert _kickoff(2025) == "2025-09-04"
    assert _kickoff(2026) == "2026-09-10"


def test_infer_draft_slots_handles_traded_picks():
    # 3 teams, 2 rounds, linear. Team 1's round-1 pick was traded to team 3.
    picks = [
        {"round": 1, "draft_slot": 1, "roster_id": 2}, {"round": 1, "draft_slot": 2, "roster_id": 3},
        {"round": 1, "draft_slot": 3, "roster_id": 3},
        {"round": 2, "draft_slot": 1, "roster_id": 2}, {"round": 2, "draft_slot": 2, "roster_id": 1},
        {"round": 2, "draft_slot": 3, "roster_id": 3},
    ]
    tps = [{"season": "2026", "round": 1, "roster_id": 1, "owner_id": 3, "previous_owner_id": 1}]
    assert sleeper._infer_slots(2026, picks, tps) == {1: 2, 2: 1, 3: 3}


# ---------------------------------------------------------------- opportunity model
from app import opportunity as op


def test_contract_end_rules():
    # OverTheCap extension years start after the current deal; other deals start when signed.
    likely = {"history": [{"type": "Drafted", "signed": 2022, "yrs": 4}, {"type": "UFA", "signed": 2026, "yrs": 3}]}
    assert op.contract_end(likely, 2025)[0] == 2025
    assert op.contract_end(likely, 2026)[0] == 2028
    andrews = {"history": [{"type": "Drafted", "signed": 2018, "yrs": 4}, {"type": "Extension", "signed": 2021, "yrs": 4},
                           {"type": "Extension", "signed": 2025, "yrs": 3}]}
    assert op.contract_end(andrews, 2024)[0] == 2025
    assert op.contract_end(andrews, 2026)[0] == 2028


def test_leave_risk():
    expiring = {"history": [{"type": "UFA", "signed": 2024, "yrs": 3}], "seasons": {}}
    assert op.leave_risk(expiring, 2026, "WR", 31, 0.9)[0] == 0.70      # old + expiring
    assert op.leave_risk(expiring, 2026, "WR", 25, 0.9)[0] == 0.25      # good young starter: extended/tagged
    assert op.leave_risk(expiring, 2026, "WR", 25, 0.3)[0] == 0.55
    cuttable = {"history": [{"type": "UFA", "signed": 2025, "yrs": 3}],
                "seasons": {"2027": {"cap": 10.0, "base": 8.0, "pro": 2.0, "gtd": 0.0}}}
    p, why, _ = op.leave_risk(cuttable, 2026, "RB", 27.5, 0.9)
    assert p == 0.45 and "save $8.0M" in why


def test_breakout_score_discounts():
    sig = {"efficient": 1.0, "fa_move": 1.0, "youth": 1.0}
    base = op.score(sig, 0.0, 500, 23, "TE")
    assert op.score(sig, 1.0, 500, 23, "TE") < base          # already a full-time starter
    assert op.score(sig, 0.0, 8000, 23, "TE") < base         # already priced as a star
    assert op.score(sig, 0.0, 500, 30, "TE") < base          # past the age cliff
    assert op.score({}, 0.0, 500, 23, "TE") == 0


def test_usage_shares():
    weekly = {w: {"a": {"team": "X", "pos": "TE", "off_snp": 30, "tm_off_snp": 60, "rec_tgt": 2, "pts_ppr": 5},
                  "b": {"team": "X", "pos": "TE", "off_snp": 50, "tm_off_snp": 60, "rec_tgt": 6, "pts_ppr": 10}} for w in range(1, 6)}
    weekly[5]["a"]["rec_tgt"] = 6  # role grows in the last game
    u = op.usage(weekly)
    assert u["a"]["games"] == 5 and abs(u["a"]["snap"] - 0.5) < 1e-9
    assert u["a"]["share_l3"] > u["a"]["share_prev"]


def test_opening_now_respects_own_injury():
    assert op._opening_now(None, "IR") == 1.0      # healthy, starter out long-term
    assert op._opening_now(None, "Out") == 0.5     # healthy, starter out short-term
    assert op._opening_now("IR", "Out") == 0.0     # he's out longer than the starter (Thornton/Rice)
    assert op._opening_now("IR", "IR") == 0.0
    assert op._opening_now("Out", "IR") == 0.5     # both out, but the starter longer
    assert op._opening_now(None, None) == 0.0


def test_linked_league_chain(monkeypatch):
    """A restarted league: old seasons map to current franchises by owner (orphans keep
    their last owner), old activity after the restart is dropped, and the restart's
    startup-sized migration draft is out of scope."""
    from app import sleeper
    leagues = {
        "new": {"league_id": "new", "season": "2025", "status": "in_season", "previous_league_id": None, "settings": {"draft_rounds": 3}},
        "old25": {"league_id": "old25", "season": "2025", "status": "complete", "previous_league_id": "old24"},
        "old24": {"league_id": "old24", "season": "2024", "status": "complete", "previous_league_id": None},
    }
    rosters = {
        "new": [{"roster_id": 1, "owner_id": "carl"}, {"roster_id": 2, "owner_id": "ann"}, {"roster_id": 3, "owner_id": "bob"}],
        "old24": [{"roster_id": 1, "owner_id": "ann"}, {"roster_id": 2, "owner_id": "bob"}, {"roster_id": 3, "owner_id": "gone"}],
        "old25": [{"roster_id": 1, "owner_id": "ann"}, {"roster_id": 2, "owner_id": None}, {"roster_id": 3, "owner_id": "gone"}],
    }
    monkeypatch.setattr(sleeper, "league", lambda lid, force=False: leagues.get(lid))
    monkeypatch.setattr(sleeper, "rosters", lambda lid, ttl=None, force=False: rosters[lid])
    monkeypatch.setattr(sleeper, "cached_drafts", lambda lid, force=False: [{"start_time": 5000}] if lid == "new" else [])
    monkeypatch.setitem(sleeper.LINKS, "new", ["old25"])
    chain = sleeper.league_chain("new")
    assert [l["league_id"] for l in chain] == ["new", "old25", "old24"]
    old25 = chain[1]
    assert old25["_franchise"] == {1: 2, 2: 3, 3: 1003}   # orphan roster 2 keeps bob; "gone" left
    assert sleeper._remap_tx(old25, {"roster_ids": [1, 2], "adds": {"p": 2}})["adds"] == {"p": 3}
    assert not sleeper.draft_in_scope(chain[0], {"settings": {"rounds": 20}, "start_time": 5000})  # migration
    assert sleeper.draft_in_scope(chain[0], {"settings": {"rounds": 3}, "start_time": 6000})
    assert not sleeper.draft_in_scope(old25, {"settings": {"rounds": 3}, "start_time": 7000})     # after restart
    assert sleeper.draft_in_scope(old25, {"settings": {"rounds": 3}, "start_time": 4000})


def test_trade_review_even_threshold():
    from app import retro
    assert not retro._decided(200, 1000)     # under 250
    assert not retro._decided(400, 6000)     # under 8% of the bigger side
    assert retro._decided(600, 6000)
    assert retro._gap(-500, 5000) == {"gap": -500, "pct": -10.0}


def test_user_data_is_per_league(tmp_path, monkeypatch):
    from app import store
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "LEGACY_PATH", tmp_path / "user.json")
    (tmp_path / "user.json").write_text('{"player_notes": {"1": "old shared note"}}', encoding="utf-8")
    store.migrate_legacy("A")                      # the old shared file moves to the first league used
    assert store.load("A")["player_notes"] == {"1": "old shared note"}
    assert not (tmp_path / "user.json").exists()
    store.set_entry("B", "player_notes", "2", "only in B")
    assert "2" not in store.load("A")["player_notes"]
    assert store.load("B")["player_notes"] == {"2": "only in B"}


def test_config_remembers_league_profiles(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    config.save({"league_id": "A", "username": "me", "my_strategy": "rebuild"})
    config.save({"league_id": "B", "username": "friend", "my_strategy": "auto"})
    profiles = config.load()["profiles"]
    assert profiles["A"]["username"] == "me" and profiles["A"]["my_strategy"] == "rebuild"
    assert profiles["B"]["username"] == "friend"


def test_acceptance_calibration():
    """Calibrated on real trades: a fair deal is about a coin flip, and a deal like the
    median losing side of a real accepted trade (-26%) is unlikely but not impossible."""
    fair = acceptance(0.0, {}, 1, 1)[0]
    assert 40 <= fair <= 55
    assert 12 <= acceptance(-0.26, {}, 1, 1)[0] <= 30
    assert acceptance(0.15, {}, 1, 1)[0] >= 60


def test_age_note_matches_sell_verdict():
    from app import aging
    curve = {"RB": {a: {"ratio": r, "n": 50} for a, r in {22: 1.07, 23: 1.09, 24: 1.07, 25: 0.99, 26: 0.92, 27: 0.91, 28: 0.9, 29: 0.9, 30: 0.9}.items()}}
    drift = {"RB": {0: [0.8, 0.55, 0.36]}}
    o = aging.outlook(curve, "RB", 25.4, 1100, drift=drift)
    assert o["verdict"] == "hold" and o["y2_pct"] <= -8
    assert "hold for now" in aging.note(o, "RB", 25.4)  # never "sell window is now" next to a Hold
    assert o["path"][0]["typical"] < o["path"][0]["value"]  # expected value includes the league-wide drop
    young = aging.outlook(curve, "RB", 22.5, 1100, drift=drift)
    assert young["verdict"] == "rising" and aging.note(young, "RB", 22.5) is None
    old = aging.outlook(curve, "RB", 28.5, 1100, drift=drift)
    assert old["verdict"] in ("sell", "soon") and old["verdict"] != "hold"
    assert ("sell now" if old["verdict"] == "sell" else "sell within a year") in aging.note(old, "RB", 28.5)
    assert "typical" not in aging.outlook(curve, "RB", 25.4, 1100)["path"][0]  # no drift given


def test_pick_history_drops_off_scale_snapshots():
    from app.pickhistory import _glitches
    row = [140, 139, 142, 141, 140, 72, 73, 74, 138, 140, 141, 139, None, 142]
    assert _glitches(row) == [5, 6, 7]  # the February-style jump to half the usual rank
    assert _glitches([50, 51, 49, 48, 47, 46, 45]) == []  # a steady climb is real


def test_league_price_kinds():
    from app.market import _kinds
    assert _kinds({"kind": "pick", "round": 1}) == ["R1"]
    assert _kinds({"kind": "pick", "round": 4}) == ["R3"]
    assert _kinds({"kind": "player", "pos": "RB", "age": 23.0}) == ["RB", "young"]
    assert _kinds({"kind": "player", "pos": "WR", "age": 29.0}) == ["WR", "vet"]


def test_timeline_lineup_fits_rookies_in_flex():
    from types import SimpleNamespace
    from app.future import _lineup
    lg = SimpleNamespace(slots=["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX"])
    # A rookie (unknown position) can't play QB or TE, but can fill RB/WR/flex spots.
    total = _lineup(lg, [("QB", 5000), ("ROOKIE", 4000), ("TE", 1000), ("ROOKIE", 3000), ("WR", 2000), ("QB", 500)])
    assert total == 5000 + 4000 + 1000 + 3000 + 2000 + 500


def test_timeline_picks_play_only_after_their_draft():
    from types import SimpleNamespace
    from app.future import lineup_entries
    lg = SimpleNamespace(season=2026)
    pick = {"kind": "pick", "season": 2028, "value": 3000}
    player = {"kind": "player", "pos": "WR", "value": 2000}
    path = lambda a: [a["value"]] * 4
    assert lineup_entries(lg, [player, pick], 1, path) == [("WR", 2000)]  # 2027: not drafted yet
    assert lineup_entries(lg, [player, pick], 2, path) == [("WR", 2000), ("ROOKIE", 3000)]


def test_calculator_lean_needs_enough_consistent_trades():
    from app.calcfit import MIN_TRADES, _at, _verdict
    assert _verdict([0.2, 0.25, 0.18, 0.22])["lean"] == "ktc"        # consistently better on KTC
    assert _verdict([-0.2, -0.25, -0.18, -0.22])["lean"] == "dynastyprocess"
    assert _verdict([0.3, 0.3])["lean"] is None                      # too few trades
    assert _verdict([0.3, -0.3, 0.25, -0.2])["lean"] is None         # no consistent direction
    assert MIN_TRADES >= 3
    series = [["2025-01-01", 100], ["2025-02-01", 200]]
    assert _at(series, "2025-01-15") == 100
    assert _at(series, "2024-12-01") == 100   # before his history starts: first value
    assert _at(series, "2025-03-01") == 200


def test_market_view_leans_toward_their_calculator():
    from app.trade import market_view
    a = {"value": 1000, "market": 1000, "sources": {"ktc": 1400, "dynastyprocess": 800}}
    assert market_view(a) == 1000
    assert market_view(a, {"calc": {"source": "ktc", "strength": 0.5}}) == 1200
    assert market_view(a, {"calc": {"source": "dynastyprocess", "strength": 0.5}}) == 900
    assert market_view({**a, "sources": {}}, {"calc": {"source": "ktc", "strength": 0.5}}) == 1000


def test_roster_room_taxi_and_cuts():
    from types import SimpleNamespace
    from app.roster import _plan
    p = lambda i, v, exp=3, **kw: {"kind": "player", "id": str(i), "name": f"P{i}", "pos": "WR", "value": v, "redraft": v,
                                   "years_exp": exp, "taxi": False, "ir": False, **kw}
    players = [p(i, 1000 + 100 * i) for i in range(5)] + [p(10, 300, exp=2, taxi=True), p(11, 400, exp=0, taxi=True)]
    picks = [{"id": "2027-1-1", "name": "2027 1st", "season": 2027, "value": 2500}, {"id": "2027-2-1", "name": "2027 2nd", "season": 2027, "value": 900}]
    lg = SimpleNamespace(season=2026, me=None)
    plan = _plan(lg, {"roster_id": 1, "manager": "x", "players": players, "picks": picks},
                 {"limit": 6, "taxi_slots": 2, "taxi_years": 3, "allow_vets": False})
    assert [a["name"] for a in plan["promoted"]] == ["P10"]          # third-year player ages off taxi
    assert [a["name"] for a in plan["to_taxi"]] == ["Rookie from 2027 2nd"]  # lowest rookie takes the open spot
    assert plan["active"] == 5 + 1 + 1 and plan["over"] == 1
    assert [c["name"] for c in plan["cuts"]] == ["P10"]              # lowest value next year goes first


def test_recap_ordinals():
    from app.recap import _ordinal
    assert [_ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101)] == ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "101st"]


def test_rookie_outcomes_use_best_finish_in_first_three_seasons():
    from app.rookies import _outcome, _rates, _tier_label, thresholds
    th = thresholds(superflex=True)
    p = {"cls": 2021, "gsis": "x", "pos": "WR"}
    finish = {("x", 2021): 40, ("x", 2022): 20, ("x", 2024): 3}  # year 4 doesn't count
    assert _outcome(p, finish, th, 2025)[:2] == ("starter", 20)
    assert _outcome({**p, "pos": "TE"}, {("x", 2022): 15}, th, 2025)[0] == "flex"
    assert _outcome({**p, "pos": "QB"}, {("x", 2021): 20}, th, 2025)[0] == "starter"          # QB20 starts in superflex
    assert _outcome({**p, "pos": "QB"}, {("x", 2021): 20}, thresholds(False), 2025)[0] == "flex"  # but not in 1QB
    assert _outcome(p, {}, th, 2025)[0] == "bust"
    r = _rates([{"outcome": o} for o in ("elite", "starter", "bust", "bust")])
    assert r["hit"] == 50.0 and r["bust"] == 50.0 and r["n"] == 4
    assert _tier_label(1, "early", 12) == "1.01–1.04" and _tier_label(2, "late", 12) == "2.09–2.12"


def test_pick_slot_pricing():
    from types import SimpleNamespace
    from app import pickvalue
    price = {(1, "early"): 6000, (1, "mid"): 4000, (1, "late"): 3000, (2, "early"): 2000, (2, "mid"): 1800, (2, "late"): 1600}
    values = SimpleNamespace(pick=lambda s, r, t: {"value": price[(r, t)], "market": price[(r, t)]})
    lg = SimpleNamespace(teams={i: {} for i in range(12)}, draft_rounds=2, values=values)
    val, _ = pickvalue.market_curve(lg, 2027)
    assert len(val) == 24
    assert val[0] > 6000 > val[3]                       # 1.01 above the early-1st price, 1.04 below
    assert abs(sum(val[0:4]) / 4 - 6000) < 1             # the tier still averages to its price
    assert all(a >= b for a, b in zip(val, val[1:]))      # never cheaper to pick earlier
    assert pickvalue.slot_in_round(2, 1, 12, True) == 12 and pickvalue.slot_in_round(2, 1, 12, False) == 1
    d = pickvalue.future_dist(rank=12, n=12, years_out=1)  # worst team: picks first
    assert abs(sum(d) - 1) < 1e-9 and d.index(max(d)) == 0 and min(d) > 0
    assert pickvalue._range([0, 0, 1.0] + [0] * 9) == (3, 3)


def test_seasonal_bands_and_outlook():
    from app import seasonal
    assert seasonal.band("RB", 23.9) == "young" and seasonal.band("RB", 24.5) == "prime" and seasonal.band("RB", 26.2) == "vet"
    assert seasonal.band("K", 25) is None
    idx = [100] * 12
    idx[0] = 112  # January high
    S = {"month": 9, "groups": [{"pos": "RB", "band": "prime", "label": "RB 24–25", "index": idx}]}
    o = seasonal.outlook(S, "RB", 24.5)
    assert o["best"] == "Jan" and o["best_pct"] == 12.0
    assert "Jan" in seasonal.note(o)
    assert seasonal.outlook(S, "WR", 24.5) is None


def test_calendar_nfl_draft_is_last_thursday_of_april():
    import datetime as dt
    from app.agenda import _nfl_draft
    for y in (2026, 2027, 2028):
        d = _nfl_draft(y)
        assert d.weekday() == 3 and d.month == 4 and (d + dt.timedelta(days=7)).month == 5


def test_capital_odds_lookup():
    from app.rookies import CAPITAL_GRID, capital_odds
    cap = {"grid": CAPITAL_GRID, "positions": {"WR": {"hit": [100 - i * 0.5 for i in range(len(CAPITAL_GRID))],
                                                       "elite": [0] * len(CAPITAL_GRID), "bust": [0] * len(CAPITAL_GRID)}}}
    assert capital_odds(cap, "WR", 1)["hit"] == 100
    assert capital_odds(cap, "WR", 33)["hit"] < capital_odds(cap, "WR", 10)["hit"]   # later picks: lower odds
    assert capital_odds(cap, "TE", 10) is None and capital_odds(cap, "WR", None) is None


def test_recap_streaks():
    from app.recap import _streak
    assert _streak(["W", "L", "W", "W"]) == "W2" and _streak(["L"]) == "L1" and _streak([]) == ""


def test_lineup_scoring_and_slots():
    from app import lineup
    scoring = {"rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0, "bonus_rec_te": 0.5}
    assert lineup.score({"rec": 5, "rec_yd": 60, "rec_td": 1, "bonus_rec_te": 5, "pts_ppr": 99}, scoring) == 5 + 6 + 6 + 2.5
    assert lineup.spread("WR", 0) == 0 and lineup.spread("WR", 15) > lineup.spread("QB", 15)  # receivers swing more than QBs
    P = lambda i, pos, proj: {"id": str(i), "pos": pos, "proj": proj, "sd": lineup.spread(pos, proj)}
    pool = [P(1, "QB", 20), P(2, "RB", 15), P(3, "WR", 14), P(4, "RB", 12), P(5, "TE", 9), P(6, "WR", 3)]
    best = lineup._best(["QB", "RB", "WR", "TE", "FLEX"], pool, {}, key=lambda p: p["proj"])
    assert {p["id"] for p in best.values()} == {"1", "2", "3", "4", "5"}  # the 12-point RB takes FLEX over the 3-point WR
    kept = lineup._best(["QB", "RB", "WR", "TE", "FLEX"], pool, {4: pool[5]}, key=lambda p: p["proj"])
    assert kept[4]["id"] == "6"                                            # a locked starter stays put


def test_second_half_model():
    from app import secondhalf as h
    assert h._coef("WR", 8) == h.COEF[8]["WR"]
    mid = h._coef("QB", 6)                                                 # linear between the fitted weeks
    assert h.COEF[5]["QB"][1] < mid[1] < h.COEF[8]["QB"][1]
    u = lambda ppg, wo: {"games": 7, "ppg": ppg, "ppg_l3": ppg, "wo_pg": wo, "wo_l3": wo}
    busy, lucky = h.model_ppg("WR", u(10, 14), 7), h.model_ppg("WR", u(10, 5), 7)
    assert busy > 10 > lucky                                               # volume beats points
    assert h.edge("WR", u(10, 14), 7, busy) > 0 > h.edge("WR", u(10, 5), 7, lucky)
    assert abs(h.edge("WR", u(10, 40), 7, h.model_ppg("WR", u(10, 40), 7))) == h.EDGE_CAP
    assert h.edge("QB", u(25, 35), 7, h.model_ppg("QB", u(25, 35), 7)) == 0  # QBs: no volume signal
    assert h.model_ppg("QB", u(25, 35), 7) < 25                            # hot QB starts regress
    assert h.model_ppg("WR", {**u(10, 14), "games": 2}, 7) is None         # too few games
    soft = h.model_ppg("RB", u(15, 18), 7, sched=1.08)
    assert soft > h.model_ppg("RB", u(15, 18), 7, sched=1.0)               # schedule counts for RBs only
    assert h.model_ppg("WR", u(10, 14), 7, sched=1.08) == busy


def test_second_half_edge_only_in_real_gain():
    from app.trade import context_value
    a = {"kind": "player", "pos": "WR", "age": 25, "value": 3000, "redraft": 4000, "h2": {"edge": 0.15}}
    team = {"w": 0.9}
    plain = context_value({**a, "h2": None}, team)
    assert context_value(a, team) > plain                                  # counts in the team's real gain
    assert context_value(a, team, {}) == plain                             # not in what a manager perceives


def test_track_snapshot_key_and_h2_grading(monkeypatch):
    import datetime as dt
    from app import track
    assert track._key(dt.date(2026, 10, 27)) == "2026-10-27"               # a Tuesday starts its own week
    assert track._key(dt.date(2026, 11, 2)) == "2026-10-27"                # through the next Monday
    weekly = {5: {"a": {"pts_ppr": 20, "off_snp": 50}, "b": {"pts_ppr": 6, "off_snp": 40}},
              6: {"a": {"pts_ppr": 18, "off_snp": 50}, "b": {"pts_ppr": 8, "off_snp": 40}},
              7: {"a": {"pts_ppr": 22, "off_snp": 50}}}                     # b missed week 7
    monkeypatch.setattr(track.opportunity, "season_stats", lambda season: weekly)
    snap = {"date": "2026-10-01", "season": 2026, "week": 5, "h2": {
        "a": {"pos": "WR", "rate": 18.0, "so_far": 14.0, "model": 17.0, "sleeper": 19.0, "change": 4.0, "f": 1.0, "play": [5, 6, 7], "owner_rid": 1},
        "b": {"pos": "RB", "rate": 9.0, "so_far": 12.0, "model": None, "sleeper": 9.0, "change": -3.0, "f": 1.0, "play": [5, 6, 7], "owner_rid": 2}}}
    lg = type("L", (), {"players_db": {}})()
    (g,) = track._grade_h2(lg, [snap])
    assert g["n"] == 2 and g["weeks"] == [5, 6, 7]
    assert g["outlook"] == 2.0                                              # actual 20 and 7 a game: missed by 2 and 2
    assert g["pace"] == 5.5 and g["movers_hit"] == 100                     # pace missed by 6 and 5; both calls went the right way


def test_draftday_order_and_mock():
    from app import draftday
    D = {"type": "snake", "settings": {"teams": 3, "rounds": 2}, "slot_to_roster_id": {"1": 30, "2": 10, "3": 20}}
    made = [{"pick_no": 1, "roster_id": 30, "player_id": "x"}]
    seq = draftday.pick_order(D, draftday._order(None, D), made, {(2, 10): 30})
    assert [s["orig"] for s in seq] == [30, 10, 20, 20, 10, 30]             # snake: round 2 runs backwards
    assert [s["owner"] for s in seq] == [30, 10, 20, 20, 30, 30]            # 10's 2nd was traded to 30
    assert seq[0]["player"] == "x" and seq[3]["label"] == "2.01"
    lg = type("L", (), {"teams": {}})()
    board = [{"id": str(i), "value": 1000 - 100 * i, "pos": "WR"} for i in range(5)]
    avail, _ = draftday.mock(lg, seq, 1, 6, board, 30, {}, None, skip=4, n_sims=20)
    assert avail[0]["0"] == 20                                              # the best player is there at the first pick
    assert avail[4]["4"] == 20 or avail[4]["3"] < 20                        # 3 picks taken, then 30 passes at pick 5


def test_offseason_free_agency_date():
    import datetime as dt
    from app.offseason import _free_agency
    d = _free_agency(2027)
    assert d.weekday() == 2 and 8 <= d.day <= 14 and d.month == 3          # second Wednesday of March
