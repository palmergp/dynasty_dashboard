# Dynasty Trade Helper

A local web app for evaluating and finding trades in a Sleeper dynasty league. It pulls your league from the Sleeper API, blends dynasty values from three sources, works out each team's contention window and needs, profiles each manager's trade tendencies, and suggests trades tailored to every partner.

## Run

```powershell
.\run.ps1
```

This creates `.venv` on first run, starts the server at http://127.0.0.1:8000 and opens your browser. Run the tests with `.\.venv\Scripts\python -m pytest`.

The league ID, username and strategy are set in **Settings**, which is backed by `data/config.json`. Defaults: league `1327705946058686464`, user `gpalmer`, strategy `rebuild`.

## Pages

| Page | What it's for |
|---|---|
| **Dashboard** | Your window, ranks, sell candidates and positional outlook. Also a league table of every team's window, strength, picks, needs and tendency tags. |
| **Rankings** | Franchise score rankings (players + picks vs. league average), and a league map (win-now strength vs. franchise value, in four quadrants). Also franchise composition (top-10 players / depth / picks), roster value over time, a positional strength heatmap (now and long-term), and age structure. |
| **Trade Partners** | Teams ranked by fit, with 3 suggested packages each. Each package shows market fairness, your team-context gain, their acceptance likelihood, and the reasons behind it. |
| **Trade Evaluator** | Build any trade between two teams by clicking assets. Shows the market verdict, a per-source breakdown, and for each side: context value, lineup impact, age change, pick capital, roster cuts and acceptance. "Suggest trades with Team B" generates packages for one partner. |
| **Teams** | Roster with values and notes, needs, and a manager profile with tendency bars and auto notes. Also your own notes on the manager, a window override, and their trade history. |
| **Players** | Every rostered player with values from each source, win-now value and 30-day trend. You can add your own value override and notes here. |
| **Waiver Wire** | Every available QB/RB/WR/TE on an NFL roster, scored for your team. Suggested adds (with why, who to drop, the gain and a FAAB bid), drop candidates, a map of upside vs. value to you, and a filterable, sortable table of everyone available with usage, depth chart and contract. |
| **Breakouts** | Players whose role is likely to grow before the market prices it in: free agents, trade targets on other rosters (with a "Trade for" button) or your own. Includes a breakout-vs-value map, the breakout board, the contract-year-backup watchlist (the Isaiah Likely pattern), depth-chart shake-ups for next season (who moves up if a starter leaves), and a backtest of how last season's flags did. |
| **Trade Review** | Who won every trade. Each one shows the value gap on trade day, the peak gap since and the gap today, the value of each player then and now, the start points each side got, and a chart of each side's haul over time. Also a manager leaderboard (record, summed gaps then and now, points gained and given), a chart of won-at-the-time vs. won-in-hindsight, and filters by season and manager. |
| **Drafts** | Draft performance for the startup and rookie drafts. A line chart of every team's draft-class value over time, with up to 4 teams highlighted, as total value or indexed to draft day = 100. Also a scorecard (draft-day value, value now, change, % still on roster and in the league, best and worst picks), the league's biggest risers and fallers, and roster construction (startup / rookie draft / trade / waivers). |
| **Waivers** | Every waiver claim and free-agent add. Shows pickups per team, a line chart of the value of pickups on each roster over time, and a scorecard (pickups, FAAB spent, still rostered, hits, value at pickup, value captured, start points, best pickups). Also the league's top pickups by value captured and by start points. Season filter. |
| **Waivers › team** | One team's pickup tiles and ranks, its pickup value vs. the league median, and every pickup with value at pickup, peak while held, value now, value captured, start points, a sparkline and the outcome. |
| **Drafts › team** | One team's draft-class value vs. the league median, stat tiles, every pick with its draft-day value, current value, sparkline and status (on roster, traded, dropped), and its roster construction. |
| **Settings** | Source weights, stud premium, pick multipliers per round, and a data refresh. |

## Restarted leagues (linked history)
Some leagues restart in a new Sleeper league, for example to add teams, and Sleeper doesn't connect the old seasons. To include them, put the old league's ID (any season of it) under **Settings › Linked older league IDs**. The app then:
- Adds the old league and all its previous seasons, up to the season the new league started, as history.
- Matches old teams to current teams by **owner**, so history follows each manager. An orphaned old roster keeps its last owner, and managers who left get a franchise of their own.
- Ignores old-league activity after the new league's first draft. The old league often keeps auto-scoring after a restart.
- Treats the new league's startup-sized draft as a roster migration, not a real draft. Each player keeps his original acquisition (startup, rookie draft, trade, waivers).

Trade tendencies, the Drafts, Waivers and Rankings pages, and roster construction all use the combined history. The Settings page shows the season chain that was built. Value history only starts in January 2025, so drafts before then are valued from that date, and the Drafts page says so.

Each install has one league at a time. A friend should run their own copy (copy the folder without `data/`), because notes and overrides in `data/user.json` aren't kept per league.

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
- Value history comes from DynastyProcess's GitHub repo. Its values file is committed weekly, so the git history is a free weekly archive back to January 2025.
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
- **Breakout score** (0–100) combines six signals, each from 0 to 1:
  - efficient (30%): points per opportunity vs. the position median
  - contract-year backup (20%): his deal ends while he's behind a starter
  - rising role (15%): last 3 games vs. earlier
  - youth and draft capital (15%)
  - opening now (10%): a player ahead of him is out
  - path opening (10%): a player ahead of him may leave
- The score is discounted for players who already have a full role, who are already valued at 4,000+, or who are past age 25.
- **Backtest:** the weights were checked by running the model as of the end of 2025 and comparing values then with values now.
  - The top 20 scores gained 500+ value 20% of the time, vs. 3.4% for everyone under 4,000.
  - On average they beat similar-value players by about 126.
  - Efficiency and contract-year backups predicted best. "The starter ahead may leave" barely did, because teams often draft or sign a replacement, so it has a low weight.
  - Isaiah Likely ranked #65 of 561 with the contract-year-backup flag.
  - One season is a small sample.
- **Pickup score** = his value to your team (dynasty value adjusted for your window and needs, as in trades) + a breakout allowance of up to 750.
  - The suggested drop is your active player with the lowest pickup score. Open roster or taxi spots are used first.
  - The suggested bid is the median winning bid on the 8 most similar-value claims in this league over the last two seasons.
- **In trades:** rebuilding teams value breakout upside up to 15% more, and suggestions call out "buy before a breakout" targets. Player notes include contract and breakout signals.

**Trade review** (`app/retro.py`)
- Each side's haul is valued as a package (with the stud premium) at every weekly DynastyProcess snapshot from the trade date on, so then, peak and now are on one consistent scale.
- **Gap** = value received minus value sent. A trade is **even** while the gap is under 250 or under 8% of the bigger side. Otherwise the side ahead today **won**.
- Startup picks count as the player taken.
- Rookie picks count at today's generic value for their round until used, then as the drafted player. There's no history of pick values, so "at the time" isn't truly historical for picks.
- **Points** are what the acquired players scored in the receiving team's starting lineup while it held them.
- Trades made before value history starts (January 2025) are marked "early" and use the first snapshot.

**Trades** (`app/trade.py`, `app/suggest.py`)
- **Package value** = (Σ vᵖ)^(1/p), with p = 1.35 by default. This adds a stud premium, so two 3,000-value players don't equal one 6,000.
- **Context value** is what an asset is worth to a particular team:
  - Contenders weight win-now production more.
  - Rebuilders weight picks more and discount players nearing their position's age cliff (QB 32, RB 26, WR 28, TE 29).
  - Positional needs adjust the value up or down.
- **Acceptance** blends the other manager's tendency-adjusted context view 50/50 with the market. Real managers check trade calculators.
  - The threshold rises for managers who usually come out ahead.
  - Their consolidation habits are factored in.
- **Suggestions** search 1–2-for-1–3 packages for arbitrage: assets worth more to them than to you, in exchange for assets worth more to you. They are ranked by your expected gain × acceptance likelihood, and count roster cuts.

## Caveats
- Sleeper's API is read-only, so you send the proposals yourself in the Sleeper app.
- No historical value feed is available, so past trades are judged at **today's** values. "Trade edge" and "who won" include hindsight. The structural tendencies (consolidation, picks, age, positions) are much less affected.
- In a young league, many managers have only a handful of trades. The tendencies are applied lightly, and the UI shows the confidence for each.
- Draft history uses DynastyProcess only, because it's the one free source with history. Its "now" values can differ from the three-source blend used elsewhere, and its weekly values can jump around, especially for fringe players.
- Usage, contracts and depth charts are free feeds. Sleeper's stats endpoint is undocumented, and OverTheCap data can lag on recent signings, so a few contracts show an end year already passed. If either feed fails, the app keeps working without breakout signals and shows a warning on the new pages.
- Leave risk ignores team context (cap space, draft capital, coaching changes). Treat "path opening" as a lead to research, not a forecast.
- The KeepTradeCut scraper depends on their page layout. If a source fails, the app uses the remaining sources and shows a warning on the dashboard.

## Data files
All local data lives in `data/` (git-ignored):
- `config.json`: settings.
- `user.json`: your notes, overrides and window overrides.
- `cache/`: API responses. Delete it to force a full refresh.

## Data sources and terms
This project isn't affiliated with or endorsed by Sleeper, FantasyCalc, KeepTradeCut, DynastyProcess, nflverse or OverTheCap. It reads their public APIs, files and web pages; the data belongs to its providers and is subject to their terms. KeepTradeCut values are read from its public rankings page, so check its terms before relying on that source; you can set its weight to 0 in Settings. No data is redistributed in this repository; everything is fetched and cached locally in `data/`.

## License
[MIT](LICENSE). This covers the code in this repository, not the data it fetches.
