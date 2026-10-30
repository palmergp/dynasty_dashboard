r"""End-to-end smoke test: start the app on a copy of your data, load every page in a
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
    "#/draftprep": "<h1>Upcoming draft", "#/partners": "<h1>Find trades", "#/trade": "Team A gives",
    "#/team": "Manager profile", "#/players": "Rostered players", "#/pickups": "<h1>Free agents",
    "#/breakouts": "Breakout watch", "#/drafts": "<h1>Past drafts", "#/waivers": "<h1>Pickup history",
    "#/history": "<h1>Trade history", "#/records": "Record book", "#/settings": "Valuation",
    "#/deadline": "<h1>Deadline sell list", "#/buylow": "<h1>Buy low", "#/future": "<h1>Rebuild timeline", "#/prices": "<h1>League prices",
    "#/recap": "<h1>Weekly recap", "#/roster": "<h1>Roster room", "#/hitrates": "<h1>Rookie pick hit rates",
    "#/calendar": "<h1>Calendar", "#/plan": "<h1>Trade plan",
}
# Cards that load after the page renders: route -> text that appears once they've loaded.
LATE = {"#/deadline": ("By position and age", "Vs. similar players"), "#/settings": (" OK</span>",), "#/future": ("Rank after",),
        "#/prices": ("Avg. result on KTC",), "#/buylow": ("Vs. similar players",)}
API = ["overview", "players", "picks", "suggestions", "drafts", "rankings", "waivers", "pickups", "breakouts",
       "backtest", "season", "draft-prep", "trade-review", "records", "trades", "feed", "status", "team/1",
       "deadline", "buylow", "future", "pick-timing", "league-prices", "phone",
       "target", "calculators", "checks", "recap", "roster-room", "rookie-hits", "seasonal", "calendar", "health"]


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


@pytest.mark.parametrize("path", ["evaluate", "trade-impact", "pitch", "counter"])
def test_trade_posts(server, path):
    with urllib.request.urlopen(f"{server}/api/players", timeout=600) as r:
        players = [p for p in json.loads(r.read()) if p.get("roster_id")]
    a = players[0]
    b = next(p for p in players if p["roster_id"] != a["roster_id"])
    body = {"a_rid": a["roster_id"], "a_gives": [{"kind": "player", "id": a["id"]}],
            "b_rid": b["roster_id"], "b_gives": [{"kind": "player", "id": b["id"]}]}
    req = urllib.request.Request(f"{server}/api/{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        assert r.status == 200
        out = json.loads(r.read())
    if path == "pitch":
        assert out["text"].startswith("Hey ")


def test_plan_post(server):
    with urllib.request.urlopen(f"{server}/api/overview", timeout=600) as r:
        me = json.loads(r.read())["me"]
    with urllib.request.urlopen(f"{server}/api/players", timeout=600) as r:
        players = json.loads(r.read())
    mine = next(p for p in players if p.get("roster_id") == me)
    other = next(p for p in players if p.get("roster_id") not in (None, me))
    t = {"b_rid": other["roster_id"], "a_gives": [{"kind": "player", "id": mine["id"]}], "b_gives": [{"kind": "player", "id": other["id"]}]}
    body = json.dumps({"trades": [t, t]}).encode()  # the second repeats the first, so it must be flagged and skipped
    req = urllib.request.Request(f"{server}/api/plan", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        out = json.loads(r.read())
    assert [t["skipped"] for t in out["trades"]] == [False, True] and out["problems"]


@pytest.mark.parametrize("path", ["static/manifest.json", "static/icon-192.png", "static/apple-touch-icon.png"])
def test_phone_install_files(server, path):
    with urllib.request.urlopen(f"{server}/{path}", timeout=60) as r:
        assert r.status == 200


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
    for late in LATE.get(route, ()):
        assert late in dom, f"{route}: a card that loads after the page didn't render (missing '{late}')"
    assert "data-js-error" not in dom, f"{route}: JavaScript error"
    assert "Not found." not in dom
    assert 'aria-current="true"' in dom or route == "#/settings", f"{route}: no section highlighted in the nav"
