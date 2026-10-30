# Dynasty Trade Helper

A local web app for evaluating and finding trades in a Sleeper dynasty league. It pulls your league from the Sleeper API, blends dynasty values from three sources, works out each team's contention window and needs, profiles each manager's trade tendencies, and suggests trades tailored to every partner.

## Getting started

### 1. Install Python
You need **Python 3.10 or newer** (developed on 3.12) and an internet connection.
- **Windows:** install from [python.org](https://www.python.org/downloads/). On the first installer screen, check **"Add python.exe to PATH"**. In a new terminal, `python --version` should print 3.10 or higher. If it opens the Microsoft Store instead, turn off the `python.exe` "App execution alias" in Windows Settings.
- **macOS:** install from python.org or with `brew install python`. Check with `python3 --version`.
- **Linux:** use your package manager. On Debian/Ubuntu you also need `python3-venv`.

### 2. Get the code
Either clone it with git:
```
git clone https://github.com/palmergp/dynasty_dashboard.git
cd dynasty_dashboard
```
or download the ZIP from GitHub (**Code › Download ZIP**), unzip it, and open a terminal in that folder.

### 3. Start the app
**Windows (PowerShell):**
```powershell
.\run.ps1
```
If PowerShell says *running scripts is disabled on this system*, run it once like this instead:
```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
If you downloaded the ZIP, you can also run `Unblock-File .\run.ps1` once.

**macOS / Linux:**
```bash
chmod +x run.sh   # first time only
./run.sh
```

The first run creates a virtual environment in `.venv` and installs the requirements, which takes a minute or two. It then starts the server at http://127.0.0.1:8000 and opens your browser. Leave the terminal open while you use the app, and press Ctrl+C to stop it.

### Using it on your phone
The app also listens on your local network, so a phone on the same Wi-Fi can open it. The terminal prints the address (like `http://192.168.1.20:8000`), and **Settings › Open on your phone** shows it with a QR code to scan. The computer has to stay awake with the app running.
- **Windows:** the first time, Windows Firewall may ask whether to allow Python; allow it on **private** networks. If phones can't connect, check that your home Wi-Fi is set to **Private** (Settings › Network & internet › Wi-Fi › your network). On a Public network the firewall blocks it, which is what you want at a coffee shop.
- Anyone on the same Wi-Fi can open the app (and change its settings), so on networks you don't trust start it with `.\run.ps1 -LocalOnly` (macOS/Linux: `./run.sh --local-only`).

### 4. Point it at your league
The app starts on the author's league. Go to **Settings**, enter your league ID and Sleeper username, choose your strategy (rebuild / contend / auto) and click **Save**.
- **League ID:** open your league at [sleeper.com](https://sleeper.com). The long number in the address bar (`sleeper.com/leagues/<league id>/...`) is the ID. 
- **Restarted leagues:** if your league was restarted (for example, to add teams), also add the old league's ID under **Linked older league IDs**. See [Restarted leagues](#restarted-leagues-linked-history).

The first load of a league takes a minute or more while it downloads rosters, every season's transactions, values, weekly stats, contracts and the value history. After that everything is cached and pages load quickly. **Refresh** in Settings re-downloads the live data.

### Staying up to date
While the app is running, it rebuilds in the background every 15 minutes (`auto_refresh_minutes` in `data/config.json`; 0 turns it off). Live Sleeper data is re-downloaded once it's 15 minutes old, values every 12 hours. The header shows when the data was last updated. When newer data arrives, a **New data · refresh** button appears, so the page you're on never reloads under you.

### Updating
Run `git pull` (or download a fresh ZIP), then start the app again as usual. The run scripts install any new requirements. Your settings, notes and cache in `data/` are kept.

### Troubleshooting
- **Port 8000 is already in use:** stop the other server, or run `.venv\Scripts\python -m uvicorn app.main:app --port 8001` (macOS/Linux: `.venv/bin/python ...`) and open http://127.0.0.1:8001.
- **A page shows an error after changing leagues:** check the league ID and username in Settings, then click Refresh.
- **Starting over:** delete the `data/` folder to clear settings and cache.
- **Tests:** `.venv\Scripts\python -m pytest` (macOS/Linux: `.venv/bin/python -m pytest`) runs the fast unit tests.
- **Smoke test:** this starts the app on a *copy* of your `data/` folder and loads every page in headless Edge or Chrome. Each page has to render its content with no JavaScript errors, and every API endpoint has to respond. It takes about a minute with a warm cache. Run it with `$env:SMOKE=1; .\.venv\Scripts\python -m pytest tests\test_smoke.py` (macOS/Linux: `SMOKE=1 .venv/bin/python -m pytest tests/test_smoke.py`).

## Pages

Pages are grouped into five sections along the top (a tab bar at the bottom on phones). Each section's pages are tabs underneath. Settings is the icon at the top right. Page addresses didn't change, so old bookmarks still work.

**Home**

| Page | What it's for |
|---|---|
| **Dashboard** | "Since your last visit": value moves and injury changes on your roster, trades and notable adds, newly available players and new breakout flags, with a *Mark all as seen* button. Also your window, ranks, sell candidates and positional outlook. Also a league table of every team's window, strength, picks, needs and tendency tags. |

**League**

| Page | What it's for |
|---|---|
| **Rankings** | Franchise score rankings (players + picks vs. league average), and a league map (win-now strength vs. franchise value, in four quadrants). Also franchise composition (top-10 players / depth / picks), roster value over time, a positional strength heatmap (now and long-term), and age structure. |
| **Playoff odds** | Playoff, bye, title and last-place odds for every team, from simulating the rest of the season with weekly projections. Also projected wins, strength of schedule ahead and so far, your remaining games with win chances, and each team's projected rookie-draft slot. |
| **Timeline** | Every team's projected lineup strength now and 1, 2 and 3 years out if nobody trades, with ranks, the playoff line, the year you'd reach it, your core players' projected values and your picks turning into rookies. *Build toward a year* finds the trades that raise your lineup most in a year you pick, at no more than a 10% cost today. |
| **Teams** | Roster with values and notes, needs, and a manager profile with tendency bars and auto notes. Also your own notes on the manager, a window override, and their trade history. |
| **Weekly recap** | A recap of any completed week to paste into the league chat: results, closest game, blowout, top score (ranked in league history), upsets vs. projections, player of the week, points left on the bench, standings, trades, big waiver bids and dynasty value movers. |
| **Record book** | All-time records: champions, all-time standings (titles, finals, record, points), highest and lowest scores, biggest blowouts and closest games, best seasons, best single-game and "franchise player" performances, biggest trade fleeces (today, at the time, and reversals), best and worst draft classes, draft steals and busts, and best pickups. Your entries are highlighted. |

**Trades**

| Page | What it's for |
|---|---|
| **Find trades** | Teams ranked by fit, with 3 suggested packages each. Each package shows market fairness, your team-context gain, their acceptance likelihood, and the reasons behind it. |
| **Evaluate** | Build any trade between two teams by clicking assets. *Make it work for both sides* suggests the smallest changes (ask for more, keep a piece, swap one) that make the deal good for Team A and acceptable to Team B. *Season impact* shows both teams' playoff odds, title odds and projected draft slot with and without the trade. *Message to send* writes a short note for Team B on why the deal helps them. Shows the market verdict, a per-source breakdown, and for each side: context value, lineup impact, age change, pick capital, roster cuts and acceptance. "Suggest trades with Team B" generates packages for one partner. |
| **Deadline** | Your players worth selling before the trade deadline (countdown included): who values them most among likely playoff teams, what they're expected to lose in a year, and a ready-made asking price from each of the two best buyers that works for both sides. Also an out-of-sample check of how the sell verdicts have held up. |
| **League prices** | How this league prices each position, pick round and age group in real trades, compared with the market on each trade day, with the trades behind each number. Also which calculator (KeepTradeCut or DynastyProcess) each manager seems to trade by. |
| **Trade history** | Who won every trade. Each one shows the value gap on trade day, the peak gap since and the gap today, the value of each player then and now, the start points each side got, and a chart of each side's haul over time. Also a manager leaderboard (record, summed gaps then and now, points gained and given), a chart of won-at-the-time vs. won-in-hindsight, and filters by season and manager. |

**Players**

| Page | What it's for |
|---|---|
| **Rostered** | Every rostered player with values from each source, win-now value and 30-day trend. You can add your own value override and notes here. |
| **Breakouts** | Players whose role is likely to grow before the market prices it in: free agents, trade targets on other rosters (with a "Trade for" button) or your own. Includes a breakout-vs-value map, the breakout board, the contract-year-backup watchlist (the Isaiah Likely pattern), depth-chart shake-ups for next season (who moves up if a starter leaves), and a backtest of how last season's flags did. |
| **Buy low** | Players whose value dropped 15%+ from their 4-month high while their role held (price dips, scoring slumps, injury dips), split into trade targets, free agents and your own players not to sell low. Also a check of how past price dips turned out. |
| **Free agents** | Every available QB/RB/WR/TE on an NFL roster, scored for your team. Suggested adds (with why, who to drop, the gain and a FAAB bid), drop candidates, a map of upside vs. value to you, and a filterable, sortable table of everyone available with usage, depth chart and contract. |
| **Pickup history** | Every waiver claim and free-agent add. Shows pickups per team, a line chart of the value of pickups on each roster over time, and a scorecard (pickups, FAAB spent, still rostered, hits, value at pickup, value captured, start points, best pickups). Also the league's top pickups by value captured and by start points. Season filter. |
| **Pickup history › team** | One team's pickup tiles and ranks, its pickup value vs. the league median, and every pickup with value at pickup, peak while held, value now, value captured, start points, a sparkline and the outcome. |
| **Player page** | Click any player's name. Shows his value history, notes and breakout score, a sell-timing verdict (sell now / within a year / hold / rising with age), and his projected value vs. peers and expected value over the next 3 years. It also charts the typical value change by age at his position. The Players table has an *Age outlook* column for scanning. |

**Draft**

| Page | What it's for |
|---|---|
| **Upcoming draft** | The next rookie draft: your picks (valued across the slots they can land in, with how often picks there have hit or busted and whether the market has under- or overpriced them) with projected slots and values, pick capital by team, a heatmap of where every first-round pick will likely land, and how each manager drafts (position leanings, how often they take the best available). Once the rookie class has values after the NFL draft, it adds a big board and mock drafts of who's likely available at each of your picks. *When to sell picks* shows how next year's picks typically gain or lose value month by month. |
| **Hit rates** | How often rookie picks turn into starters or busts, by round, slot (early/mid/late) and position, from the 2019+ rookie classes. *Early or late* charts hit and bust rates slot by slot and how much value the players taken in each range kept after three years (which slots the market under- or overprices), how long each position keeps producing and keeps its dynasty value, and every pick from every class with its outcome. |
| **Roster room** | Next offseason's roster crunch: incoming rookies, who stays on, moves to or ages off the taxi squad, how many players you'll have to cut and in what order (trade the ones with value first), and every other team's crunch, with the best players likely to be cut elsewhere. |
| **Past drafts** | Draft performance for the startup and rookie drafts. A line chart of every team's draft-class value over time, with up to 4 teams highlighted, as total value or indexed to draft day = 100. Also a scorecard (draft-day value, value now, change, % still on roster and in the league, best and worst picks), the league's biggest risers and fallers, and roster construction (startup / rookie draft / trade / waivers). |
| **Past drafts › team** | One team's draft-class value vs. the league median, stat tiles, every pick with its draft-day value, current value, sparkline and status (on roster, traded, dropped), and its roster construction. |

**Settings**

| Page | What it's for |
|---|---|
| **Settings** | Source weights, stud premium, pick multipliers per round, and a data refresh. |

## Restarted leagues (linked history)
Some leagues restart in a new Sleeper league, for example to add teams, and Sleeper doesn't connect the old seasons. To include them, put the old league's ID (any season of it) under **Settings › Linked older league IDs**. The app then:
- Adds the old league and all its previous seasons, up to the season the new league started, as history.
- Matches old teams to current teams by **owner**, so history follows each manager. An orphaned old roster keeps its last owner, and managers who left get a franchise of their own.
- Ignores old-league activity after the new league's first draft. The old league often keeps auto-scoring after a restart.
- Treats the new league's startup-sized draft as a roster migration, not a real draft. Each player keeps his original acquisition (startup, rookie draft, trade, waivers).

Trade tendencies, the Drafts, Waivers and Rankings pages, and roster construction all use the combined history. The Settings page shows the season chain that was built. Value history is fetched back to just before the league's first draft, so old drafts get real draft-day values.

One install can hold several leagues. Each league you've opened is saved under **Settings › Saved leagues**, with its own username, strategy and linked IDs. Notes, value overrides and window overrides are kept per league, so switching never mixes them.

## How the model works

**Values** (`app/values.py`)
- Sources: FantasyCalc (API), KeepTradeCut (parsed from the rankings page) and DynastyProcess (GitHub CSVs). Each is fetched for this league's format: superflex, PPR, 12 teams.
- The sources use differently shaped value curves. So each source is **rank-mapped onto a consensus curve**: its Nth-best player gets the consensus Nth-best value. Each source keeps its own ordering, and only real ranking disagreements remain.
- The available sources are averaged by your weights, then your overrides are applied.
- Win-now values come from FantasyCalc's redraft values.

**Picks**
- Ownership comes from Sleeper's traded picks, covering the next 3 drafts.
- Next year's picks get an early, mid or late tier from each original team's projected finish.

**Teams** (`app/league.py`)
- Each team's best lineup is built from win-now values.
- Positional needs are z-scores against the league, both now (starters) and future (dynasty).
- The contend score blends lineup strength, record and points for (record counts more as the season goes on), plus trade behavior.
- Labels: 60 or above is a contender, 40 or below a rebuilder. You can override any team's window.

**Tendencies** (`app/tendencies.py`)
- Every trade is credited to whoever managed the roster at the time, so Jdell33 doesn't inherit the previous owner's history.
- Per manager, the app measures:
  - consolidation (fewer, better pieces vs. depth)
  - pick appetite
  - youth appetite (value-weighted age change)
  - positional appetite
  - trade edge (how often they come out ahead)
  - activity and partners
- Each tendency is weighted by a confidence of n/(n+3), where n is the number of trades.
- Used picks are valued as the player who was drafted with them. Startup-draft picks are treated as players.

**Drafts** (`app/history.py`, `app/drafts.py`)
- Value history comes from DynastyProcess's GitHub repo. Its values file is committed weekly, so the git history is a free weekly archive going back years. The app fetches snapshots from just before the league's first draft.
- Each snapshot is fetched once and cached. It's mapped onto the app's scale with the same DynastyProcess→consensus curve used for today's values.
- Sleeper doesn't timestamp individual picks. Each pick's date is interpolated between the draft's first and last pick (the startup was a slow draft, June 15 – July 21, 2025), and the player is valued at the snapshot on or before that date.
- Picks are credited to the team that made them.
- Roster construction counts each current player under his most recent move onto his current team, using every draft and every trade, waiver and free-agent transaction.

**Waivers** (`app/waivers.py`)
- Each add from a waiver or free-agent transaction is one pickup. It's held until that team drops or trades the player.
- **Value captured**: the player's value today if still rostered, his value on the trade date if flipped in a trade, and 0 if dropped.
- **Hit**: captured value of 1,000 or more.
- **Start points**: fantasy points scored in that team's starting lineup while it held him, from Sleeper weekly matchups.
- Sleeper files offseason moves under week 1, so pickups made before kickoff are labeled "offseason".

**Franchise score** (`app/league.py`, `app/rankings.py`)
- Franchise value is the total value of every rostered player plus every owned rookie pick for the next 3 drafts, on the same scale.
- Franchise score is that total relative to the league average (100 = average). It rates assets, not this season's strength; the league map shows both.
- Roster value over time is rebuilt by replaying every draft pick, trade and waiver move to get each team's roster at each weekly snapshot. It covers players only, because there's no history of pick values.

**Sorting.** Click any column header, or press Enter/Space on it. Numbers sort high-to-low first and text A–Z, and blanks always go last. The last sort is remembered per page.

**Tooltips.** Labels with a dotted underline, window badges, tendency tags, need cells and values explain themselves on hover or keyboard focus. The text lives in `HELP`, `TAG_HELP` and `WINDOW_HELP` in `static/app.js`.

**Opportunity and breakouts** (`app/opportunity.py`, `app/pickups.py`)
- Usage comes from Sleeper's weekly stats: snaps, targets, carries, air yards, red-zone looks and PPR points. Team totals are summed from teammates. *Weighted opportunities* are carries + 1.5× targets (dropbacks for QBs).
- Contracts come from nflverse's copy of OverTheCap (refreshed daily), joined through DynastyProcess's ID map. Extension years count from the end of the current deal.
- Each NFL depth chart is ranked by opportunities per game (recent games count half), with Sleeper's depth chart as the fallback.
- **Leave risk** for next season is a rule of thumb:
  - expiring deal: about 55%
  - expiring and past the age cliff: 70%
  - productive starter on an expiring deal: 25% (usually extended or tagged)
  - restricted free agent, or a 1st-round rookie with a 5th-year option: 20–25%
  - an aging player the team can cut and save 60%+ of his cap hit: 30–45%
- **Breakout score** (0–100) combines these signals, each from 0 to 1:
  - efficient (30%): points per opportunity vs. the position median
  - contract-year backup (20%): his deal ends while he's behind a starter
  - rising role (15%): last 3 games vs. earlier
  - youth and draft capital (15%)
  - opening now (10%): a player ahead of him is out, and he isn't out longer himself
  - path opening (shown, but 0% of the score): a player ahead of him may leave
- The score is discounted a little for players who already have a full role, more for those already valued at 4,000+, and for players past age 25.
- **Backtest:** the weights were checked by running the model as of the end of each season from 2022 to 2025 (that season's usage, the contracts in force then and the values then) and comparing values a year later. The Breakouts page shows it live.
  - Pooled over the four seasons, the top 20 scores gained 500+ value 22.5% of the time, vs. 4.0% for everyone under 4,000. They beat similar-value players by about 386 on average.
  - Every season beat the base rate by 4× or more: 20%, 35%, 15% and 20% vs. 3–5%.
  - Efficiency and contract-year backups predicted gains in all four seasons, and youth in three.
  - "The starter ahead may leave" did worse than average in all four, because teams usually bring in a replacement, so it no longer counts toward the score.
  - Weights were chosen so they also held up on seasons they weren't tuned on.
  - "Opening now" can't be backtested, because there's no injury history.
  - Isaiah Likely ranked in the top ~11% at the end of 2025.
- **Pickup score** = his value to your team (dynasty value adjusted for your window and needs, as in trades) + a breakout allowance of up to 750.
  - The suggested drop is your active player with the lowest pickup score. Open roster or taxi spots are used first.
  - The suggested bid is the median winning bid on the 8 most similar-value claims in this league over the last two seasons.
- **In trades:** rebuilding teams value breakout upside up to 15% more, and suggestions call out "buy before a breakout" targets. Player notes include contract and breakout signals.

**Sell timing** (`app/aging.py`)
- From about four years of weekly values, each player worth 800+ is compared with his value a year later.
- Raw changes are negative at almost every age, because each rookie class pushes everyone down and valuable players drift back toward the middle. So each change is divided by the typical change for players at the same position and value level. What's left is the age effect.
- The median by position and age, smoothed across neighboring ages, is the curve. On it, RBs start falling behind peers around 25–26, WRs around 27, and TEs around 31.
- Verdicts: **sell now** at 12%+ expected loss vs. peers over a year, **sell within a year** at 6%+ (or 15%+ over two years), **rising** at a 6%+ gain, and **hold** otherwise.
- The same verdict drives the age line in player notes and the dashboard's sell candidates, so they always agree with the player page. A Hold whose decline starts in year two says so.
- **Expected value** on the player page adds back the average raw change for players at his position and value level over 1–3 years. It's usually below today's value even for a Hold. It uses the average, not the median, because lower-value players split between fading out and holding on.

**Playoff odds** (`app/season.py`)
- Each team's weekly mean is its best possible lineup from Sleeper's player projections for that week, so byes and injuries count. Scores vary by the league's own week-to-week spread (the standard deviation of teams' scores around their averages).
- 4,000 simulations of the remaining schedule rank teams by wins, then points for. With 6 playoff teams, seeds 1–2 get byes. The playoffs are played with each team's projected strength in the playoff weeks.
- **Rookie-draft order** uses whichever rule reproduces the league's last rookie draft: non-playoff teams by max points ("potential points", lowest first) or by record (worst first). Playoff teams follow by the round they went out in, champion last.

**Draft prep** (`app/draftprep.py`)
- Pick slots are the simulated draft-order distribution. Values are the blended market value for an early, mid or late pick in that round.
- **Manager habits** come from every startup and rookie draft: position shares vs. the league (shrunk toward average for small samples) and how often they took the most valuable player left.
- **Mock drafts** run each simulated draft order. Each manager takes the best value × position habit × positional need, with some randomness.
- **Mock check:** replaying the 2026 rookie draft pick by pick, the model's first choice was the actual pick 42% of the time and in its top 3 67% of the time. Always taking the best available player scored 39%.

**Trade review** (`app/retro.py`)
- Each side's haul is valued as a package (with the stud premium) at every weekly DynastyProcess snapshot from the trade date on, so then, peak and now are on one consistent scale.
- **Gap** = value received minus value sent. A trade is **even** while the gap is under 250 or under 8% of the bigger side. Otherwise the side ahead today **won**.
- Startup picks count as the player taken.
- Rookie picks count at today's generic value for their round until used, then as the drafted player. (League prices does use pick values from the week of each trade; see below.)
- **Points** are what the acquired players scored in the receiving team's starting lineup while it held them.
- Trades made before the first fetched snapshot are marked "early" and use that snapshot.

**Deadline sell list** (`app/deadline.py`, `app/counter.py`)
- Buyers are teams with a 25%+ chance to make the playoffs in the season simulation.
- **Premium** = the most a buyer values the player (their team context and tendencies) minus what he's worth to your team. **Decline** = his value minus his expected value in a year.
- **Sell score** = premium + half the decline. Listed: players a buyer values above you, plus players expected to lose 10%+ whom a buyer values within 10% of your value.
- **What to ask for** is the best 1–3-asset package from that buyer that gains you 3%+ in team context and that they'd accept about 45%+ of the time.

**Counter-offers** (`app/counter.py`)
- Tries one change at a time (ask for one or two more of their assets, keep one of yours, swap one of yours) and, if the deal is already good for you but unlikely to be accepted, sweeteners (add one of yours, drop one of theirs).
- Keeps the changes that reach +3% for Team A and 45+ acceptance for Team B, closest to the original deal first.

**Buy low** (`app/buylow.py`)
- Drop = today's DynastyProcess value vs. the high of the last 4 months (weekly values), at least 15%.
- Role held = over the last 3 games, at least 85% of his season share of his team's opportunities at his position, and a real role. Injured players qualify on the role they had before the injury and are labeled.
- Left out: players whose age verdict is "sell now" or "sell within a year", and players 33+.

**Rebuild timeline** (`app/future.py`)
- Players follow their expected value (age curve plus the average change at their position and value level). Picks keep their value until their draft, then age like a typical 22-year-old rookie.
- Strength = the best starting lineup from projected values; rookies of unknown position can fill RB/WR and flex slots. The playoff line is the Nth-best team, N = playoff spots.
- Dynasty values price in the future, so this is a guide to who will be good when, not a points projection.

**Pick timing** (`app/pickhistory.py`)
- DynastyProcess's weekly pick rankings (values-picks.csv history, back to February 2021) rank picks among players. Each rank becomes a value with today's rank → value curve, so a pick's value is what it would buy in players at the time.
- For each finished draft class, its value by month (June before the draft through April) is divided by its own average; the average over classes is the typical shape.
- Most Februaries, DP's pick ranks are briefly off-scale (about half their usual numbers), so snapshots that jump 25%+ away from their neighbors are dropped.
- So far: next year's picks are cheapest in summer and early fall, and climb into the draft. From October, a typical 1st gains about 14% by March and an early 1st about 21% by April.

**League prices** (`app/market.py`)
- Each completed trade is valued as of its trade day: players with DynastyProcess's weekly values, rookie picks with DP's pick rankings that week, startup picks as the player taken.
- For each side, log(received ÷ sent) is shared among the assets it sent by value. Averaged across trades, that's a price index per kind of asset, pulled toward 0 with two "at market" pseudo-trades so small samples don't swing.
- A league with few trades will read close to market everywhere, which is an honest "no edge yet".

**Build toward a year** (`app/target.py`)
- Uses the rebuild timeline's projections. For each team, your assets that add least to your lineup in the target year (but that they value) are tried against theirs that add most, 1–2 for 1–3.
- Kept: deals they'd accept about 45%+ of the time that cost you at most 10% in team-context value today. Ranked by your lineup gain in that year × acceptance.

**Calculator leans** (`app/calcfit.py`)
- Every completed trade is valued on its trade date in KeepTradeCut's numbers (each traded player's daily KTC history, from his KTC page) and DynastyProcess's (weekly history). Rookie picks use DP's pick ranking that week, converted into each calculator's numbers at the same rank, so they don't favor either one. FantasyCalc has no history, so it isn't checked.
- A manager who trusts a calculator accepts deals that look fine on it, so their side should look better on that one. Lean = the average of (result on KTC − result on DP) over their trades; it counts with 4+ trades and at least 1.5 standard errors from zero.
- A lean shifts the market half of that manager's acceptance odds 30% (likely) or 50% (clear) toward their calculator, and Find trades lists your assets it rates above the consensus and theirs it rates below.
- DP's values fall off faster from stars to depth than KTC's, so a DP lean also reflects valuing studs more.

**Model checks** (`app/checks.py`)
- Sell verdicts, out of sample: the age curve is refit using only results known a year before the latest full year of data, then every player's verdict over that year (every 4 weeks) is compared with what happened to his value relative to similar players. So far: "sell now" players finished about 10% behind similar players, "sell within a year" about 7% behind, "hold" about even and "rising" about 4% ahead. Expected values averaged 98% of what happened, with a typical miss around 22%.
- Buy low: every 4 weeks since 2021, players down 15%+ from their 4-month high are compared with similar players 6 and 12 months later. Moderate (15–25%) dips beat similar players by about 8% over a year; deeper drops did no better than their peers, so the list stops rewarding drops past 25%. Past usage isn't available, so the role filter isn't tested.

**Season impact** (`app/season.py`)
- The season simulation runs twice with the same random games, once with each team's roster after the trade. The difference is the trade's effect on playoff odds, title odds and the projected slot of each team's own first-round pick.

**Offer message** (`app/pitch.py`)
- Built only from points in the other manager's favor: a need the player fills (only if he'd start and their lineup doesn't get weaker), their lineup and playoff-odds gain, their window, the calculator that has them ahead (theirs if they lean), and their trade habits. Nothing about your own gain.

**Weekly recap** (`app/recap.py`)
- From Sleeper's weekly matchups. Upsets: the winner's starters were projected at least 10 points below the loser's (Sleeper's projections that week). Points left on the bench: the best possible lineup from that week's roster scores minus the actual score.

**Roster room** (`app/roster.py`)
- Next season: one rookie per pick in the next draft. Taxi players past the league's taxi years come off; open taxi spots go to the lowest-valued rookies (and, if the league allows veterans on taxi, to taxi-age players who don't start).
- Anything over the roster limit (QB/RB/WR/TE spots; each kicker or defense slot takes one off) has to be cut, lowest expected value a year from now first. Taxi players can be in the cut order too, since a rookie can take their spot. IR players are left on IR.

**Rookie hit rates** (`app/rookies.py`)
- Each rookie class since 2019 is ranked by DynastyProcess's values (superflex or 1QB, to match the league) from its last weekly snapshot between mid-May and mid-July of the draft year (values.csv history). The top teams × rounds become picks 1.01, 1.02, … It's a stand-in for where players actually went in rookie drafts.
- Outcomes come from nflverse regular-season stats: positional rank by PPR points per game (7+ games), best season within his first 3. Elite = top-12 RB/WR, top-6 TE; starter = top-24 RB/WR, top-12 TE; flex = top-36 RB/WR, top-18 TE. QBs use 12/24/32 in superflex and 6/12/24 in 1QB. Hit = elite or starter; bust = not even a flex season. Only classes with 3 finished seasons count.
- So far (12-team superflex): 1st-round picks hit 67% of the time and bust 13% (picks 1–4: 85% / 5%); 2nd-rounders 27% / 50%; 3rd-rounders 18% / 73%. About 60 picks per round, so each rate is good to roughly ±12 points.
- Longevity: every QB/RB/WR/TE drafted into the NFL since 2000 who had a starter season, followed for 12 seasons. RBs peak in year 2 and half as many are still starting by year 8; WRs by year 9, TEs by year 6, and QBs keep going past year 12. Dynasty value: a position's rookie picks' total value k years later as a share of draft day; RB picks are down to about a third of it by year 5, while WR picks are worth about twice their draft-day value in years 3–5.

**Pick values** (`app/pickvalue.py`)
- The value sources price picks as early/mid/late in each round. Each tier's price is placed at the middle of its slots and interpolated, giving a price for every slot (1.01 above the early-1st price, 1.04 below).
- Next year's picks are worth the price at each slot weighted by the season simulation's chance of landing there, so a near-certain 1.01 is worth more than a generic early 1st and a pick that could land anywhere from 1.04 to 1.08 is priced across that range. This value is used everywhere (trades, timeline, draft capital).
- Picks two or more years out keep the market's generic value (that's how other managers price them) but get a rough projected range from the rebuild timeline: the original team's projected lineup rank the season before, spread wider each year out.
- Every pick shows hit and bust odds for its likely slots and how much value players taken there kept after three years (from the rookie history). That last number compares the market with itself: above about 115% the market has underpriced picks there (buy), below about 85% overpriced (sell before the draft). It's a signal, not part of the trade value.
- So far: 1.01–1.03 have hit about 87% of the time and the rest of the 1st about 58%. Late 1sts (124% of value kept) and late 2nds (126%) have been underpriced; early and mid 2nds (76–84%) and mid and late 3rds (about 62%) overpriced. Early 3rds held up better than late ones.

**Trades** (`app/trade.py`, `app/suggest.py`)
- **Package value** = (Σ vᵖ)^(1/p), with p = 1.35 by default. This adds a stud premium, so two 3,000-value players don't equal one 6,000.
- **Context value** is what an asset is worth to a particular team:
  - Contenders weight win-now production more.
  - Rebuilders weight picks more and discount players nearing their position's age cliff (QB 32, RB 26, WR 28, TE 29).
  - Positional needs adjust the value up or down.
- **Acceptance** blends the other manager's tendency-adjusted context view 50/50 with the market (tilted toward their calculator if they have a clear lean). Real managers check trade calculators.
  - **Calibration:** in about 190 completed trades across two leagues, the side that gave up more value lost a median 26%. That holds even after team context, because managers' and calculators' valuations differ a lot. So the acceptance curve is gentle: a fair deal scores about 48 (a coin flip), +10% for them about 60, and a deal like that median real one about 20.
  - Labels: Likely 60+, Possible 35–59, Unlikely under 35.
  - Rejected offers aren't visible in Sleeper, so this checks plausibility, not the exact odds.
  - The threshold rises for managers who usually come out ahead.
  - Their consolidation habits are factored in.
- **Suggestions** search 1–2-for-1–3 packages for arbitrage: assets worth more to them than to you, in exchange for assets worth more to you. They are ranked by your expected gain × acceptance likelihood, and count roster cuts. Only deals they'd score 45+ are suggested, which keeps them near fair on the market. The gain comes from team context.

## Caveats
- Sleeper's API is read-only, so you send the proposals yourself in the Sleeper app.
- Manager tendencies judge past trades at **today's** values, so "trade edge" includes hindsight. The structural tendencies (consolidation, picks, age, positions) are much less affected. Trade history and league prices use trade-day values instead.
- In a young league, many managers have only a handful of trades. The tendencies are applied lightly, and the UI shows the confidence for each.
- Draft history uses DynastyProcess only, because it's the one free source with history. Its "now" values can differ from the three-source blend used elsewhere, and its weekly values can jump around, especially for fringe players.
- Usage, contracts and depth charts are free feeds. Sleeper's stats endpoint is undocumented, and OverTheCap data can lag on recent signings, so a few contracts show an end year already passed. If either feed fails, the app keeps working without breakout signals and shows a warning on the new pages.
- Leave risk ignores team context (cap space, draft capital, coaching changes). Treat "path opening" as a lead to research, not a forecast.
- The KeepTradeCut scraper depends on their page layout. If a source fails, the app uses the remaining sources and shows a warning on the dashboard.

## Data files
All local data lives in `data/` (git-ignored):
- `config.json`: settings, including a saved profile for each league you've opened.
- `leagues/<league id>/user.json`: that league's notes, value overrides and window overrides.
- `cache/`: API responses. Delete it to force a full refresh.

## Data sources and terms
This project isn't affiliated with or endorsed by Sleeper, FantasyCalc, KeepTradeCut, DynastyProcess, nflverse or OverTheCap. It reads their public APIs, files and web pages; the data belongs to its providers and is subject to their terms. KeepTradeCut values are read from its public rankings page (and, for calculator leans, the public pages of traded players), so check its terms before relying on that source; you can set its weight to 0 in Settings. No data is redistributed in this repository; everything is fetched and cached locally in `data/`.

## License
[MIT](LICENSE). This covers the code in this repository, not the data it fetches.
