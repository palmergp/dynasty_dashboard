"""User-entered data: notes, value overrides and team-window overrides, kept per league
in data/leagues/<league_id>/user.json so switching leagues never mixes them."""
from __future__ import annotations

import json
import shutil
import threading

from .config import DATA_DIR

LEGACY_PATH = DATA_DIR / "user.json"  # before profiles, one file was shared by every league
_lock = threading.Lock()

EMPTY = {
    "manager_notes": {},     # user_id -> text
    "player_notes": {},      # sleeper_id -> text
    "window_overrides": {},  # user_id -> "contend" | "rebuild" | "middle"
    "overrides": {"players": {}, "pick_multipliers": {}},  # sleeper_id -> value; "2027-1" or "1" -> multiplier
}


def path(league_id: str):
    return DATA_DIR / "leagues" / str(league_id) / "user.json"


def migrate_legacy(league_id: str):
    """Move the old shared user.json into this league's profile (once)."""
    p = path(league_id)
    if LEGACY_PATH.exists() and not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LEGACY_PATH, p)
        LEGACY_PATH.rename(LEGACY_PATH.with_name("user.json.migrated"))


def load(league_id: str) -> dict:
    data = json.loads(json.dumps(EMPTY))
    p = path(league_id)
    if p.exists():
        saved = json.loads(p.read_text(encoding="utf-8"))
        for k, v in saved.items():
            if isinstance(v, dict) and isinstance(data.get(k), dict):
                data[k].update(v)
    return data


def _save(league_id: str, data: dict):
    p = path(league_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_overrides(league_id: str) -> dict:
    return load(league_id)["overrides"]


def set_entry(league_id: str, section: str, key: str, value, subsection: str | None = None):
    """Set (or clear, when value is empty/None) one entry in a section."""
    with _lock:
        data = load(league_id)
        target = data[section][subsection] if subsection else data[section]
        if value in (None, ""):
            target.pop(key, None)
        else:
            target[key] = value
        _save(league_id, data)
        return data
