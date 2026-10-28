# Starts the Dynasty Trade Helper at http://127.0.0.1:8000.
# Creates the virtualenv on first run and installs any new requirements after an update.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check -r requirements.txt
Start-Process "http://127.0.0.1:8000"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
