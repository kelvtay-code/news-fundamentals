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
| `research_team_ledger.csv` (Dashboard folder) | Synthesis (write), self-check (read) | Append-only log of every recommendation ever made — see "Performance ledger and self-check" below |

If a source file is missing, say so explicitly in the report instead of inventing rows.

## Pre-flight: freshness check and once-a-day guard

Run this before Stage 1, every time — don't skip it because a run "feels" recent.

1. **Freshness.** For each of the three sources, find the latest file by its own
   `DDMMYY_HHMM` / `YYYYMMDD_HHMM` timestamp (not by Drive's modified-time, which can lag or
   reorder) and compare its date to today's date. If any source's latest file is **not from
   today**, say so explicitly before running anything else (name the source and the stale
   date) and ask whether to proceed on the stale snapshot or wait for a fresh one — don't run
   silently on yesterday's business overview, Dual_X, or bulletin.
2. **Once a day.** Before generating a new report, check the Dashboard folder for an existing
   `research_team_DDMMYY_*.html` whose date is today. If one already exists, don't regenerate —
   tell the user a report already exists for today (name it, with its time), and only produce
   a new one if they explicitly ask to rerun anyway (e.g. because a source refreshed since that
   run). This keeps the pipeline to one run per calendar day even if the skill is invoked
   several times.

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
- **GEX** — sign, First→Last trend, GEX Sign Flip. A flip is a *candidate* regime change, not a
  confirmed one on the day it first appears — a 5 Sep 2026 performance review of 66 graded
  recommendations found same-session sign-flip trades went 0-for-3. Score a fresh (first-seen)
  flip modestly; do not let it alone justify a directional trade in the synthesis step (see
  below) — treat it as confirmed only once it has held for a second consecutive session.
- **GEX Classification** — read "Extreme Positive Gamma" / "Moderate Positive Gamma" literally:
  these describe a *dealer-pinned, low-realized-vol regime*, i.e. price compression, not license
  for a directional continuation bet. The same review found Tier-1 calls built on this
  classification alone went 0-for-8; the failure mode was recommending a directional call
  spread on the strength of the classification's bullish-sounding name while its own plain-English
  meaning ("pinned," "low vol") pointed to a range-bound structure instead. See the synthesis
  rules for the corrected mapping.
- **Implied IV** — level and IV Rank (a rising IV against a low IV Rank is a cheaper entry than
  the same slope against a high one).
- **Put Wall / Call Wall** — levels and Wall Position % (price's position between the two:
  near a wall = pinning risk; through a wall = breakout risk; "inverted" wall note = the walls
  have crossed, treat as noise not signal).
- **Volume expansion, 5-day vs 30-day** — fetch current average volume for both windows
  (finfetch or equivalent) and compute the ratio. Ratio ≥ 1.2 is confirming; below 1.0 is
  fading interest and should pull the score down even if IV/GEX look constructive.
- **Wyckoff phase** — treat as a lagging confirmation, not a leading signal, over a 1–2 session
  hold: the same review found Tier-1 bull calls made while a ticker's own phase read "Mark-up"
  won only 13.3% (2 of 15) — worse than calls with no phase alignment at all. Don't let a
  Mark-up/Accumulation tag alone upgrade a trade's size; require it alongside a wall/volume
  signal that agrees.

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
4. **Proposed trade** — pick a structure the GEX/wall read actually supports. Work this as an
   ordered decision list, top to bottom — stop at the first row that matches, don't cherry-pick
   a later one because it produces a more excited-sounding trade:
   1. **Conflict check first.** If Technicalist's regime read (Wyckoff phase, GEX
      classification, wall position) disagrees with Sentilist's direction, this is a
      **conflict** — flag it explicitly in the card. A 5 Sep 2026 review of 66 graded
      recommendations found conflicted Tier-1 setups won **13.3%** (2 of 15) vs. **55.6%**
      (5 of 9) when nothing was flagged. Sizing down is not enough on its own: a conflicted
      ticker caps at **watch-only, no position** unless the sentiment side is exceptional
      (rated 9–10, multi-source-confirmed, quantified) — in that one case, smallest defined-risk
      size only, and say explicitly that it's a size-down-for-conflict, not a size-down-for-caution.
   2. **"Extreme/Moderate Positive Gamma" without a sign-flip that's held ≥2 sessions** → this
      describes a pinned, low-vol regime — trade it as **iron condor / calendar, small size**,
      *not* a directional debit spread, even if Wyckoff phase and wall room both look bullish.
      (This was the specific, repeated failure mode in the review: CVX was recommended as a
      directional call spread on this exact classification three sessions running and lost each
      time — the note said "dealer-pinned, low realized-vol" and the trade ignored it.)
   3. **Positive gamma + a GEX sign-flip confirmed over ≥2 sessions + bullish Wyckoff phase +
      wall room to the call wall** → call spread targeting the call wall.
   4. **Negative gamma, IV rising in a Mark-down/Distribution phase** (fear repricing, not a
      premium build) → put spread / defined-risk bearish, not a long-vol bet.
   5. **Price already through a wall with volume confirming** → directional debit spread in the
      breakout direction, stop past the wall that failed to hold.
   6. **Sentiment-only catch-all rows** → smallest size, defined-risk only (debit spread, not
      naked), and say so explicitly.

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

## Performance ledger and self-check (mandatory, every run)

Keep the pipeline honest against its own track record instead of re-deriving it from scratch
each time someone asks:

1. **Log every recommendation.** After building the day's final ticker list (Tier 1 + catch-all),
   append one row per ticker to `research_team_ledger.csv` in the Dashboard folder (create it if
   missing) with columns: `date, ticker, tier, direction (bull/bear), rec_price, trade,
   conflict_flag (y/n), gex_classification, gex_sign_flip, wyckoff_phase`. `rec_price` is that
   day's Current Price from the Watchlist snapshot. This makes a future scorecard a straight
   join against later snapshots' prices instead of a manual re-read of old reports.
2. **Grade on a rolling basis.** When asked to review performance (or roughly weekly if running
   unattended), compare each ledger row at least 2 trading sessions old against the latest
   Current Price: bull wins if price is ≥0.5% higher, bear wins if ≥0.5% lower, else flat.
   Break the result out by conflict-flag (y/n), by GEX classification, by tier, and by whether a
   sign-flip was fresh (first-seen) vs. confirmed (≥2 sessions) — these are exactly the splits
   that surfaced real, actionable problems the first time this review ran (5 Sep 2026: conflict-
   flagged Tier 1 at 13.3% vs. 55.6% clean; Extreme/Moderate Positive Gamma at 0-for-8; same-day
   sign-flips at 0-for-3).
3. **Feed findings back into this file.** If a rolling review turns up a new, repeated failure
   mode with a clear mechanism (not just a losing streak on one ticker), add it to this SKILL.md
   as a numbered rule the same way the three above were added — cite the date and the sample
   size so a future reviewer can tell a well-evidenced rule from a thin one, and revisit/relax a
   rule if a larger sample later contradicts it.
