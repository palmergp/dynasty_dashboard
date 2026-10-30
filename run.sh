#!/usr/bin/env bash
# Starts the Dynasty Trade Helper at http://127.0.0.1:8000 (macOS / Linux), reachable from
# phones on the same Wi-Fi. Creates the virtualenv on first run and installs any new
# requirements after an update. --local-only keeps it on this computer.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt
bind=127.0.0.1
if [ "${1:-}" != "--local-only" ]; then
    bind=0.0.0.0
    ip=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || true)
    [ -n "$ip" ] && printf '\n  On your phone (same Wi-Fi): http://%s:8000\n  Settings in the app shows a QR code for it.\n\n' "$ip"
fi
(sleep 2; open http://127.0.0.1:8000 2>/dev/null || xdg-open http://127.0.0.1:8000 2>/dev/null || true) &
exec .venv/bin/python -m uvicorn app.main:app --host "$bind" --port 8000
