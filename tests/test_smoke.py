"""End-to-end smoke test: start the app on a copy of your data, load every page in a
headless browser (Edge or Chrome), and check each one rendered without errors.

Skipped unless SMOKE=1, because it needs your data/ folder (or network access) and a
browser. Run it with:  SMOKE=1 .venv/Scripts/python -m pytest tests/test_smoke.py -v
(PowerShell: $env:SMOKE=1; .\.venv\Scripts\python -m pytest tests\test_smoke.py -v)
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not os.environ.get("SMOKE"), reason="set SMOKE=1 to run the browser smoke test")

# Route -> text that only appears once that page has rendered.
ROUTES = {
    "#/": "League landscape", "#/rankings": "Franchise rankings", "#/season": "Playoff odds",
    "#/draftprep": "rookie draft prep", "#/partners": "Best trade partners", "#/trade": "Team A gives",
    "#/team": "Manager profile", "#/players": "Rostered players", "#/pickups": "Waiver wire",
    "#/breakouts": "Breakout watch", "#/drafts": "Draft performance", "#/waivers": "free-agent pickups",
    "#/history": "Trade review", "#/records": "Record book", "#/settings": "Valuation",
}
API = ["overview", "players", "picks", "suggestions", "drafts", "rankings", "waivers", "pickups", "breakouts",
       "backtest", "season", "draft-prep", "trade-review", "records", "trades", "feed", "status", "team/1"]


def _browser() -> str | None:
    for name in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name)
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if Path(p).exists():
            return p
    return None


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    if (ROOT / "data").exists():
        shutil.copytree(ROOT / "data", data, dirs_exist_ok=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "DTH_DATA_DIR": str(data), "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(300):  # the first league build can take a while on a cold cache
            try:
                urllib.request.urlopen(base + "/api/overview", timeout=600).read()
                break
            except Exception:
                time.sleep(1)
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.parametrize("path", API)
def test_api(server, path):
    with urllib.request.urlopen(f"{server}/api/{path}", timeout=600) as r:
        assert r.status == 200
        json.loads(r.read())


def _dom(browser, url):
    out = subprocess.run([browser, "--headless=new", "--disable-gpu", "--virtual-time-budget=20000", "--dump-dom", url],
                         capture_output=True, text=True, encoding="utf-8", timeout=180)
    return out.stdout


@pytest.mark.parametrize("route", list(ROUTES) + ["player"])
def test_page(server, route):
    browser = _browser()
    if not browser:
        pytest.skip("no Edge/Chrome found")
    if route == "player":
        with urllib.request.urlopen(f"{server}/api/players", timeout=600) as r:
            route, marker = f"#/player/{json.loads(r.read())[0]['id']}", "Sell timing"
    else:
        marker = ROUTES[route]
    dom = _dom(browser, f"{server}/{route}")
    assert marker in dom, f"{route}: page didn't render (missing '{marker}')"
    assert "data-js-error" not in dom, f"{route}: JavaScript error"
    assert "Not found." not in dom
