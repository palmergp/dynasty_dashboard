"""User-entered data: notes, value overrides and team-window overrides (data/user.json)."""
from __future__ import annotations

import json
import threading

from .config import DATA_DIR

PATH = DATA_DIR / "user.json"
_lock = threading.Lock()

EMPTY = {
    "manager_notes": {},     # user_id -> text
    "player_notes": {},      # sleeper_id -> text
    "window_overrides": {},  # user_id -> "contend" | "rebuild" | "middle"
    "overrides": {"players": {}, "pick_multipliers": {}},  # sleeper_id -> value; "2027-1" or "1" -> multiplier
}


def load() -> dict:
    data = json.loads(json.dumps(EMPTY))
    if PATH.exists():
        saved = json.loads(PATH.read_text(encoding="utf-8"))
        for k, v in saved.items():
            if isinstance(v, dict) and isinstance(data.get(k), dict):
                data[k].update(v)
    return data


def _save(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_overrides() -> dict:
    return load()["overrides"]


def set_entry(section: str, key: str, value, subsection: str | None = None):
    """Set (or clear, when value is empty/None) one entry in a section."""
    with _lock:
        data = load()
        target = data[section][subsection] if subsection else data[section]
        if value in (None, ""):
            target.pop(key, None)
        else:
            target[key] = value
        _save(data)
        return data
