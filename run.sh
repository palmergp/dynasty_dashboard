#!/usr/bin/env bash
# Starts the Dynasty Trade Helper at http://127.0.0.1:8000 (macOS / Linux).
# Creates the virtualenv on first run and installs any new requirements after an update.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt
(sleep 2; open http://127.0.0.1:8000 2>/dev/null || xdg-open http://127.0.0.1:8000 2>/dev/null || true) &
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
