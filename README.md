# Optionx Hub

A minimal installable PWA (Progressive Web App) dashboard for the Optionx pipeline.

## What it shows
- **Business Overview** — latest sortable fundamentals table (from `business_overview_*.csv`)
- **News Bulletin** — latest news headlines per ticker (from `News/*_news_*.txt`)

## Regenerating
```
python scripts/generate_hub.py
```
This reads the latest snapshot files from the local Optionx Dashboard/News folders and rewrites `docs/index.html`. Commit and push `docs/` to publish an update.

## Installing on your phone
Once published via GitHub Pages, open the site URL in Safari (iPhone) or Chrome (Android) and choose "Add to Home Screen" — it installs like a native app icon, works offline for previously loaded content.

## Note
Portfolio positions and trade data are intentionally excluded from this repo — it only publishes business overview fundamentals and news headlines.
