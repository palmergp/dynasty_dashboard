"""App configuration, persisted to data/config.json so it can be edited from the UI."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULTS = {
    "league_id": "1327705946058686464",
    "username": "gpalmer",
    # Older leagues to include as history when the league was restarted (e.g. to expand)
    # and Sleeper doesn't link the seasons. Any season of the old league works.
    "linked_league_ids": [],
    # "auto" lets the model decide; "rebuild" / "contend" forces a strategy for my team.
    "my_strategy": "rebuild",
    # Relative weights for each value source; sources missing a player are skipped.
    "source_weights": {"fantasycalc": 1.0, "ktc": 1.0, "dynastyprocess": 1.0},
    # Exponent for package valuation: (sum v^p)^(1/p). Higher = stronger stud premium.
    "consolidation_exponent": 1.35,
    # Minimum market value for an asset to be offered/requested in generated trades.
    "suggestion_min_value": 800,
    # Per-league settings, remembered so switching back to a league restores them:
    # league_id -> {"name", "username", "my_strategy", "linked_league_ids"}.
    "profiles": {},
}
PROFILE_KEYS = ("username", "my_strategy", "linked_league_ids")


def load() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG_PATH.exists():
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        for k, v in saved.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def merged(updates: dict) -> dict:
    """The current config with updates applied, without saving."""
    cfg = load()
    for k, v in updates.items():
        if k not in DEFAULTS:
            continue
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def save(updates: dict) -> dict:
    cfg = merged(updates)
    prof = cfg["profiles"].setdefault(str(cfg["league_id"]), {})
    prof.update({k: cfg[k] for k in PROFILE_KEYS})
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg
