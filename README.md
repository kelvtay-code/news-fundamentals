# Optionx Hub

A minimal installable PWA (Progressive Web App) dashboard for the Optionx pipeline.

## What it shows
- **Business Overview** — latest sortable fundamentals table (from `business_overview_*.csv`)
- **News Bulletin** — latest news headlines per ticker (from `News/*_news_*.txt`)
- **Oil Brief** — latest daily oil market dashboard/brief from the `oil-analyst` agent (most recently modified `Oil_brief_*.html` / `oilbrief_*.html` / `oil_dashboard_*.html` in Dashboard; `oil_trades_*` is excluded since it holds actual positions)
- **Bull Screener** — latest bullish-ticker funnel dashboard from the `bull_screener` agent (most recent `bull_screener_*.html` in Dashboard, matched by timestamp in the filename)
- **Research** — latest three-agent report (`research_team_*.html` in Dashboard) chaining fundalist (business overview) → technicalist (Dual_X, GEX, IV, 5d/30d volume expansion) → sentilist (news bulletin rating, plus a 7+ catch-all for tickers the first two agents missed), synthesized into one report with proposed trades and GEX/put-wall/call-wall commentary. See `.claude/skills/research-team/SKILL.md` for the pipeline spec.

## Earnings Vol Optimizer
```
python scripts/earnings_vol.py                  # screen docs/the-edge.csv (3-35 days to earnings)
python scripts/earnings_vol.py --move-view 1.25 # less aggressive view of the earnings move
python scripts/earnings_vol.py --ticker NVDA --spot 205.25 --earnings 2026-11-17 --chain chain.csv  # real quotes
```
For each name with upcoming earnings, it prices long-volatility structures: straddle, strangles, reverse iron flies/condors, calendars, double calendars and financed strangles. It picks the **lowest-debit** one that still pays on a bigger-than-implied earnings move, plus the cheapest pre-release IV run-up play when one exists. Writes `docs/earnings-vol.html` / `docs/earnings-vol.csv`. Pure Python (no scipy/yfinance); model assumptions are in the script's docstring.

## Regenerating
```
python scripts/generate_hub.py
```
This reads the latest snapshot files from the local Optionx Dashboard/News folders and rewrites `docs/index.html`.

## Publishing (regenerate + commit + push)
```
python scripts/publish_hub.py
```
The `oil-analyst` agent runs this automatically after saving a new oil brief. It's a no-op if nothing changed since the last publish.

## Installing on your phone
Once published via GitHub Pages, open the site URL in Safari (iPhone) or Chrome (Android) and choose "Add to Home Screen" — it installs like a native app icon, works offline for previously loaded content.

## Note
Portfolio positions and trade data are intentionally excluded from this repo — it only publishes business overview fundamentals, news headlines, oil market commentary, and bullish-screener funnel results (never trade/position files).
