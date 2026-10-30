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
