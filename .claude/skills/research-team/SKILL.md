---
name: research-team
description: "Run the three-agent research team (fundalist -> technicalist -> sentilist) over the Optionx watchlist and produce one synthesized trade report. Triggers on 'research team', 'run the research team', 'fundalist technicalist sentilist', '/research-team', or a request to chain fundamentals -> technicals -> sentiment into one report. Reads business_overview_*.csv, the latest Dual_X_*.html/_grid.csv, and the latest news_bulletin_*.html/News/*_news_*.txt from the Dashboard folder. Do NOT use for a single-lens request (just Wyckoff, just GEX, just news) -- use wyck, analyser-confluence, or the senti workflow for those."
---

# Research Team — Fundalist → Technicalist → Sentilist

Three sequential agent passes over the same watchlist, each narrowing and annotating the
list it receives, plus one catch-all rule that lets late-breaking news override the funnel.
Finish with one synthesis report that proposes trades and speaks to GEX / put-wall / call-wall
positioning. This mirrors the "Researcher Team" stage in `docs/trade-desk.html` but runs as its
own three-stage chain rather than a single bull/skeptic debate.

## Data sources (Dashboard folder — same convention as `scripts/generate_hub.py`)

| Source | Used by | Fields needed |
|---|---|---|
| Latest `business_overview_*.csv` | Fundalist | Ticker, Company, Sector, Price, Forward P/E, PEG Ratio, Revenue Growth, Profit Margin, Dividend Yield, Target Price, Analyst Rating |
| Latest `Dual_X_*.html` (or its `_grid.csv` sidecar) | Technicalist | Ticker, IV Implied, IV Slope, IV Rank, GEX First→Last, GEX Slope, GEX Sign Flip, Put Wall, Call Wall, Wall Position %, Wall Note, Wyckoff, GEX Classification |
| 5-day vs 30-day average volume | Technicalist | Not in any snapshot file — pull live per ticker with the `finfetch` skill (or equivalent quote source) |
| Latest `news_bulletin_*.html` (fallback: `News/*_news_*.txt`) | Sentilist | Ticker, headline/brief text, date |

If a source file is missing, say so explicitly in the report instead of inventing rows.

## Stage 1 — Agent: Fundalist

Read the latest `business_overview_*.csv` in full (every ticker, not a pre-filtered subset).

Score each ticker 1–10 on fundamental health: weigh valuation (Forward P/E, PEG) against
growth (Revenue Growth), quality (Profit Margin), and upside (Price vs Target Price, Analyst
Rating). One line of rationale per ticker.

Hand forward every ticker scoring **5 or higher** (don't over-filter here — Technicalist and
Sentilist each apply their own cut). Output: `{ticker, fundalist_score, fundalist_note}` list.

## Stage 2 — Agent: Technicalist

Input: the Fundalist list (ticker only — re-derive everything else fresh).

For each ticker, pull from the latest Dual_X snapshot:
- **Dual expansion** — does it clear the Dual_X co-expansion screen (IV Slope and GEX Slope
  both positive over the snapshot's lookback)? This *is* the "dual expand" the user means.
- **GEX** — sign, First→Last trend, GEX Sign Flip (a negative→positive flip is a real dealer
  regime change, weight it above drift inside one sign).
- **Implied IV** — level and IV Rank (a rising IV against a low IV Rank is a cheaper entry than
  the same slope against a high one).
- **Put Wall / Call Wall** — levels and Wall Position % (price's position between the two:
  near a wall = pinning risk; through a wall = breakout risk; "inverted" wall note = the walls
  have crossed, treat as noise not signal).
- **Volume expansion, 5-day vs 30-day** — fetch current average volume for both windows
  (finfetch or equivalent) and compute the ratio. Ratio ≥ 1.2 is confirming; below 1.0 is
  fading interest and should pull the score down even if IV/GEX look constructive.

Score each ticker 1–10 on technical strength (dual expansion + GEX regime + wall proximity +
volume ratio + Wyckoff phase). Drop tickers Dual_X doesn't cover at all (no options-chain
liquidity to speak of) — note them as "no technical read" rather than silently dropping them
from the final tally if Fundalist scored them highly.

Hand forward tickers scoring **5 or higher**. Output: `{ticker, fundalist_score, fundalist_note,
technicalist_score, technicalist_note, gex_summary, put_wall, call_wall, wall_position,
iv_rank, volume_ratio_5v30}` list.

## Stage 3 — Agent: Sentilist

Input: the Technicalist list (ticker only — re-derive everything else fresh).

Read the latest news bulletin. For each ticker carried forward, rate news/sentiment 1–10
(trade conviction, not just tone — a confirmed catalyst with a clear read scores higher than
vague chatter). Keep only tickers scoring **6 or higher** for the funneled path.

**Catch-all rule (mandatory, run this regardless of the funnel above):** scan *every* ticker
in the news bulletin, including ones Fundalist or Technicalist never carried forward. Any
ticker rated **7 or higher** on this independent pass gets added to the final list even though
it has no fundamental or technical score. Tag these rows clearly (e.g. "sentiment-only — no
fundamental/technical confirmation") so the synthesis step treats them as smaller, defined-risk,
news-driven ideas rather than full-conviction setups.

## Synthesis report

One combined report, one row/card per surviving ticker, each showing whichever of the three
scores it actually has (blank/"—" for sentiment-only rows, not zero). For every ticker:

1. **Fundamental note** (if present).
2. **Technical note** — explicit sentence on GEX (dealer positioning, sign flip) and on the
   put wall / call wall (which side of price they sit, how close, pinned vs breakout framing),
   plus the volume 5d/30d ratio and Wyckoff phase.
3. **Sentiment note** — the news brief that drove the rating, plus the rating itself and
   whether it came through the funnel or the 7+ catch-all.
4. **Proposed trade** — pick a structure the GEX/wall read actually supports:
   - Positive gamma, price pinned between walls, fading conviction → iron condor / calendar,
     small size.
   - Positive gamma + GEX sign-flip + bullish Wyckoff phase + wall room to the call wall →
     call spread targeting the call wall.
   - Negative gamma, IV rising in a Mark-down/Distribution phase (fear repricing, not a premium
     build) → put spread / defined-risk bearish, not a long-vol bet.
   - Price already through a wall with volume confirming → directional debit spread in the
     breakout direction, stop past the wall that failed to hold.
   - Sentiment-only rows → smallest size, defined-risk only (debit spread, not naked), and say
     so explicitly.

Order the report: fully-confirmed tickers (all three scores) first, ranked by combined
conviction; then partial (two of three); then sentiment-only catch-alls last, clearly marked.
Include a short stats banner (counts of full/partial/sentiment-only, sector breakdown) and a
"how to read this" note explaining the catch-all rule, matching the tone of the notes in
`docs/dual-x.html` and `docs/senti-grid.html`.

Render the report using this repo's site design system (FT-style masthead, table/tile CSS —
copy the tokens and structure from `docs/dual-x.html` or `docs/senti-grid.html` rather than
inventing new styling) and save it to the Dashboard folder as
`research_team_DDMMYY_HHMM.html` (same `DDMMYY_HHMM` convention as `Dual_X_*.html` and
`bull_screener_*.html`). `scripts/generate_hub.py` already knows how to find the latest one of
these and publish it as the hub's "Research Team" tab — just run
`python scripts/generate_hub.py` (or `publish_hub.py` to also commit+push) afterward.
