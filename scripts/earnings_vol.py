#!/usr/bin/env python3
"""Earnings-volatility option strategy optimizer — cheapest structure that
still captures the earnings vol premium.

Idea
----
Ahead of an earnings release, the options expiring *after* the release carry
an extra lump of "event variance" that the options expiring *before* it do not.
As the release approaches, that lump is spread over fewer days, so the quoted
IV of the post-earnings expiry climbs (the classic IV run-up) while the
pre-earnings expiry decays like a normal option.

The optimizer prices a menu of long-event-vol structures and picks the one with
the LOWEST NET DEBIT that still qualifies (makes money in the run-up scenario
or on a 1x implied move through the release):

  straddle        buy ATM call+put, event expiry
  strangle        buy OTM call+put (+/- k x implied move), event expiry
  rev_condor      buy strangle, sell further-OTM strangle (both debit spreads)
  calendar        sell ATM front (pre-earnings) / buy ATM event expiry
  dbl_calendar    put calendar below + call calendar above spot
  fin_strangle    buy event-expiry strangle, sell front-week strangle at the
                  same strikes (a "financed strangle" = double diagonal
                  without the diagonal). Front leg expires before the
                  release, leaving a long strangle at a reduced basis.

Vol model (used when no real chain is supplied)
------------------------------------------------
    total variance to expiry T = sigma_b^2 * T + sigma_e^2 * 1[T past earnings]
    sigma_e^2 = sigma_b^2 * E / 252      (E = "event days", default 12)

sigma_b is solved so that a 30-calendar-day option (which contains the
release) reprices to the screened IVImplied. Implied move = sigma_e*sqrt(2/pi).

Scenarios
---------
  runup   enter today, exit at the close before the release; spot flat, and
          spot +/- 1 sd of the base move over the holding period.
  post    hold through the release, exit next morning: event variance gone
          (IV crush), spot moved by 0, +/-0.5, 1, 1.5, 2 x implied move.

Fills: buy at ask, sell at bid (half-spread = max(3% of mid, $0.02)), on entry
AND exit. P&L is per 1-lot (x100).

Usage
-----
  python scripts/earnings_vol.py                       # screen docs/the-edge.csv
  python scripts/earnings_vol.py --tickers NVDA,HD     # subset
  python scripts/earnings_vol.py --ticker NVDA --spot 205.25 --iv 44.2 \
        --earnings 2026-11-17                           # single name, manual
  python scripts/earnings_vol.py --ticker NVDA --spot 205.25 \
        --earnings 2026-11-17 --chain nvda_chain.csv    # real quotes
     chain CSV columns: expiry(YYYY-MM-DD),strike,type(C/P),bid,ask

Writes docs/earnings-vol.html and docs/earnings-vol.csv.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDGE_CSV = ROOT / "docs" / "the-edge.csv"
OUT_HTML = ROOT / "docs" / "earnings-vol.html"
OUT_CSV = ROOT / "docs" / "earnings-vol.csv"

RATE = 0.04
YEAR = 365.0          # calendar-day year for time to expiry
SPREAD_PCT = 0.03
SPREAD_MIN = 0.02
MIN_FRONT_DTE = 2     # front leg must have at least this many calendar days


# ----------------------------------------------------------------- pricing --
def ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs(S: float, K: float, T: float, vol: float, cp: str) -> float:
    """Black-Scholes price; T in years. T<=0 -> intrinsic."""
    if T <= 1e-9 or vol <= 1e-9:
        return max(0.0, S - K) if cp == "C" else max(0.0, K - S)
    sq = vol * math.sqrt(T)
    d1 = (math.log(S / K) + (RATE + 0.5 * vol * vol) * T) / sq
    d2 = d1 - sq
    if cp == "C":
        return S * ncdf(d1) - K * math.exp(-RATE * T) * ncdf(d2)
    return K * math.exp(-RATE * T) * ncdf(-d2) - S * ncdf(-d1)


def implied_vol(price: float, S: float, K: float, T: float, cp: str) -> float | None:
    intrinsic = max(0.0, S - K) if cp == "C" else max(0.0, K - S)
    if T <= 0 or price <= intrinsic + 1e-6:
        return None
    lo, hi = 1e-4, 6.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if bs(S, K, T, mid, cp) > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def half_spread(mid: float) -> float:
    return max(SPREAD_PCT * mid, SPREAD_MIN)


# ---------------------------------------------------------------- vol model --
@dataclass
class VolModel:
    sigma_b: float          # annualised base (non-event) vol
    event_var: float        # one-off earnings variance (in log-return^2)
    earnings: dt.date       # release date (assumed after the close)
    smile: dict = field(default_factory=dict)  # (expiry,K,cp) -> iv offset vs ATM

    def total_var(self, today: dt.date, expiry: dt.date, include_event=True) -> float:
        T = max((expiry - today).days, 0) / YEAR
        v = self.sigma_b ** 2 * T
        if include_event and expiry > self.earnings >= today:
            v += self.event_var
        return v

    def iv(self, today, expiry, K=None, cp=None, include_event=True) -> float:
        T = max((expiry - today).days, 0) / YEAR
        if T <= 0:
            return 0.0
        base = math.sqrt(self.total_var(today, expiry, include_event) / T)
        return max(0.01, base + self.smile.get((expiry, K, cp), 0.0))

    @property
    def implied_move(self) -> float:  # expected |move| as fraction of spot
        return math.sqrt(self.event_var) * math.sqrt(2.0 / math.pi)


def model_from_iv(iv30: float, earnings: dt.date, today: dt.date, event_days: float) -> VolModel:
    T = 30.0 / YEAR
    k = event_days / 252.0
    if earnings <= today + dt.timedelta(days=30):
        sigma_b = math.sqrt(iv30 ** 2 * T / (T + k))
    else:
        sigma_b = iv30
    return VolModel(sigma_b, sigma_b ** 2 * k, earnings)


# -------------------------------------------------------------- calendar ----
def fridays_after(d: dt.date, n=12):
    d = d + dt.timedelta(days=1)
    while d.weekday() != 4:
        d += dt.timedelta(days=1)
    for _ in range(n):
        yield d
        d += dt.timedelta(days=7)


def pick_expiries(today, earnings, available=None):
    """front = last expiry before the release, event = first expiry after."""
    exps = sorted(available) if available else list(fridays_after(today - dt.timedelta(days=1), 16))
    exps = [e for e in exps if e > today]
    event = next((e for e in exps if e > earnings), None)
    front = None
    for e in exps:
        if e <= earnings and (e - today).days >= MIN_FRONT_DTE:
            front = e
    return front, event


def strike_step(S: float) -> float:
    for lim, step in ((25, 0.5), (100, 1.0), (250, 2.5), (1000, 5.0)):
        if S < lim:
            return step
    return 10.0


def rnd(x: float, step: float) -> float:
    return round(round(x / step) * step, 4)


# --------------------------------------------------------------- structures --
@dataclass
class Leg:
    qty: int        # +1 long, -1 short
    cp: str
    K: float
    expiry: dt.date


@dataclass
class Result:
    ticker: str
    name: str
    legs: list
    debit: float          # per share, after spreads
    max_loss: float       # per share (approx: debit for all-debit structures)
    runup_flat: float
    runup_lo: float
    runup_hi: float
    post: dict            # move multiple -> pnl per share
    vega: float           # $ per 1 vol pt, per share, at entry
    qualifies: bool = False
    note: str = ""
    at_view: float = 0.0
    move_ok: bool = False
    runup_ok: bool = False

    @property
    def per_lot(self):
        return self.debit * 100


class Pricer:
    """Marks legs either from a real chain (entry) or the vol model."""

    def __init__(self, S, model: VolModel, chain=None):
        self.S, self.m, self.chain = S, model, chain or {}

    def mid(self, leg: Leg, S, today, include_event=True):
        T = max((leg.expiry - today).days, 0) / YEAR
        vol = self.m.iv(today, leg.expiry, leg.K, leg.cp, include_event)
        return bs(S, leg.K, T, vol, leg.cp)

    def entry_fill(self, leg: Leg, today):
        q = self.chain.get((leg.expiry, leg.K, leg.cp))
        if q:
            bid, ask = q
            return ask if leg.qty > 0 else bid
        m = self.mid(leg, self.S, today)
        h = half_spread(m)
        return m + h if leg.qty > 0 else max(0.0, m - h)

    def exit_value(self, legs, S, when, include_event=True):
        """Value received when closing all legs (sell longs at bid, buy back shorts at ask)."""
        tot = 0.0
        for lg in legs:
            m = self.mid(lg, S, when, include_event)
            if lg.expiry <= when:  # already expired -> intrinsic, no spread
                tot += lg.qty * m
                continue
            h = half_spread(m)
            tot += lg.qty * (max(0.0, m - h) if lg.qty > 0 else m + h)
        return tot

    def vega(self, legs, today):
        v = 0.0
        for lg in legs:
            T = max((lg.expiry - today).days, 0) / YEAR
            vol = self.m.iv(today, lg.expiry, lg.K, lg.cp)
            v += lg.qty * (bs(self.S, lg.K, T, vol + 0.01, lg.cp) - bs(self.S, lg.K, T, vol, lg.cp))
        return v


def build_candidates(S, im, step, front, event):
    """Return list of (name, legs). im = implied move fraction."""
    atm = rnd(S, step)
    out = [("straddle", [Leg(1, "C", atm, event), Leg(1, "P", atm, event)])]

    def otm(mult):
        c = max(rnd(S * (1 + mult * im), step), atm + step)
        p = min(rnd(S * (1 - mult * im), step), atm - step)
        return c, p

    for k in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5):
        c, p = otm(k)
        out.append((f"strangle {k:g}xIM", [Leg(1, "C", c, event), Leg(1, "P", p, event)]))
    seen = set()
    for k_in in (0.0, 0.25, 0.5, 0.75, 1.0):
        for k_out in (0.75, 1.0, 1.5, 2.0, 2.5, 3.0):
            if k_out < k_in + 0.5:
                continue
            ci, pi = (atm, atm) if k_in == 0 else otm(k_in)
            co, po = otm(k_out)
            if co <= ci or po >= pi or (ci, co, pi, po) in seen:
                continue
            seen.add((ci, co, pi, po))
            nm = "rev_iron_fly" if k_in == 0 else "rev_condor"
            out.append((f"{nm} {k_in:g}/{k_out:g}xIM", [
                Leg(1, "C", ci, event), Leg(-1, "C", co, event),
                Leg(1, "P", pi, event), Leg(-1, "P", po, event)]))
    if front:
        out.append(("calendar ATM", [Leg(-1, "C", atm, front), Leg(1, "C", atm, event)]))
        for k in (0.5, 1.0):
            c, p = otm(k)
            out.append((f"dbl_calendar {k:g}xIM", [
                Leg(-1, "C", c, front), Leg(1, "C", c, event),
                Leg(-1, "P", p, front), Leg(1, "P", p, event)]))
        for k in (0.5, 1.0):
            c, p = otm(k)
            # financed strangle: front leg sold one strike further out so it
            # stays cheap to carry while still covering part of the debit
            out.append((f"fin_strangle {k:g}xIM", [
                Leg(1, "C", c, event), Leg(1, "P", p, event),
                Leg(-1, "C", c + step, front), Leg(-1, "P", p - step, front)]))
    return out


def evaluate(ticker, S, model, today, front, event, chain=None, move_view=1.5):
    """Price every candidate and flag which thesis it qualifies for.

    move thesis : hold through the release; must profit on BOTH sides at
                  +/- move_view x implied move (and every larger move up to 2x
                  the view) after IV crush, be net long vega and have defined
                  risk (no naked shorts).
    runup thesis: close at the bell before the release; must profit with spot
                  flat and at +/- 0.5 sd of the base move over the hold.
    """
    step = strike_step(S)
    im = model.implied_move
    pricer = Pricer(S, model, chain)
    exit_day = model.earnings            # release assumed after the close
    hold = max((exit_day - today).days, 0) / YEAR
    sd = model.sigma_b * math.sqrt(hold)
    post_day = model.earnings + dt.timedelta(days=1)
    mults = sorted({0, 0.5, 1.0, 1.5, 2.0, 3.0, move_view, 2 * move_view})
    results = []
    for name, legs in build_candidates(S, im, step, front, event):
        if chain and any((lg.expiry, lg.K, lg.cp) not in chain for lg in legs):
            continue
        debit = sum(lg.qty * pricer.entry_fill(lg, today) for lg in legs)
        if debit <= 0.005:
            continue

        def ru(s):
            return pricer.exit_value(legs, s, exit_day) - debit

        post = {}
        for mult in mults:
            vals = [pricer.exit_value(legs, S * (1 + sgn * mult * im), post_day, include_event=False)
                    for sgn in ((1,) if mult == 0 else (1, -1))]
            post[mult] = min(vals) - debit   # worst of up / down
        r = Result(ticker, name, legs, debit, debit, ru(S), ru(S * math.exp(-0.5 * sd)),
                   ru(S * math.exp(0.5 * sd)), post, pricer.vega(legs, today))
        r.at_view = post[move_view]
        uses_front = any(lg.expiry == front for lg in legs)
        r.runup_ok = uses_front and min(r.runup_flat, r.runup_lo, r.runup_hi) > 0
        # must keep paying for every move at or beyond the view (no capped wings
        # that hand the profit back to exit spreads on a bigger gap)
        r.move_ok = (not uses_front) and r.vega > 0 and all(v > 0 for m, v in post.items() if m >= move_view)
        r.qualifies = r.move_ok or r.runup_ok
        r.note = "move" if r.move_ok else ("run-up" if r.runup_ok else "")
        results.append(r)
    return results


def best(results, thesis="move"):
    """Lowest net debit among qualifiers; ties -> higher payoff at the view."""
    q = [r for r in results if (r.move_ok if thesis == "move" else r.runup_ok)]
    if not q:
        return None
    score = (lambda r: r.at_view) if thesis == "move" else (lambda r: r.runup_flat)
    return min(q, key=lambda r: (round(r.debit * 100), -score(r)))


# ---------------------------------------------------------------- IO ---------
def load_chain(path, S, today):
    chain, exps = {}, set()
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            e = dt.date.fromisoformat(row["expiry"].strip())
            K = float(row["strike"])
            cp = row["type"].strip().upper()[0]
            bid, ask = float(row["bid"]), float(row["ask"])
            if ask <= 0:
                continue
            chain[(e, K, cp)] = (bid, ask)
            exps.add(e)
    return chain, exps


def model_from_chain(chain, exps, S, today, earnings, front, event):
    """Fit sigma_b from the front expiry and event_var from the event expiry ATM
    IVs; store each strike's smile offset vs its expiry's ATM IV."""
    def atm_iv(e):
        ks = sorted({k for (ee, k, _) in chain if ee == e}, key=lambda k: abs(k - S))
        for k in ks[:3]:
            ivs = []
            for cp in "CP":
                q = chain.get((e, k, cp))
                if q:
                    v = implied_vol(0.5 * (q[0] + q[1]), S, k, (e - today).days / YEAR, cp)
                    if v:
                        ivs.append(v)
            if ivs:
                return sum(ivs) / len(ivs)
        return None
    iv_ev = atm_iv(event)
    iv_fr = atm_iv(front) if front else None
    T_ev = (event - today).days / YEAR
    if iv_fr:
        sigma_b = iv_fr
    else:  # no pre-earnings expiry: fall back to E=12 split
        sigma_b = model_from_iv(iv_ev, earnings, today, 12).sigma_b
    ev_var = max(iv_ev ** 2 * T_ev - sigma_b ** 2 * T_ev, 1e-6)
    m = VolModel(sigma_b, ev_var, earnings)
    for (e, k, cp), (b, a) in chain.items():
        v = implied_vol(0.5 * (b + a), S, k, (e - today).days / YEAR, cp)
        if v:
            m.smile[(e, k, cp)] = v - m.iv(today, e)
    return m


def fmt_legs(legs):
    parts = []
    for lg in legs:
        parts.append(f"{'+' if lg.qty > 0 else '-'}{lg.K:g}{lg.cp} {lg.expiry:%d%b}")
    return " ".join(parts)


def money(x):
    return f"{'-' if x < 0 else ''}${abs(x) * 100:,.0f}"


# ---------------------------------------------------------------- report -----
def render_html(rows, today, event_days, all_results, view=1.5):
    def cls(x):
        return "pos" if x > 0 else "neg"
    trs = []
    for t in rows:
        b, r0 = t["best"], t.get("runup")
        rup = (f"{html.escape(r0.name)} · {money(r0.debit)} → <span class={cls(r0.runup_flat)}>{money(r0.runup_flat)}</span>"
               f"<div class=legs>{html.escape(fmt_legs(r0.legs))}</div>") if r0 else "<span class=legs>none qualifies</span>"
        trs.append(f"""<tr>
<td class=tk>{html.escape(t['ticker'])}</td><td>{t['spot']:.2f}</td><td>{t['earnings']:%a %d %b}</td>
<td>{t['iv']*100:.1f}%</td><td>±{t['im']*100:.1f}%</td>
<td><b>{html.escape(b.name)}</b><div class=legs>{html.escape(fmt_legs(b.legs))}</div></td>
<td class=cost>{money(b.debit)}</td><td>{b.debit/t['spot']*100:.2f}%</td>
<td class={cls(b.post[1.0])}>{money(b.post[1.0])}</td>
<td class={cls(b.at_view)}>{money(b.at_view)}</td>
<td class={cls(b.post[2.0])}>{money(b.post[2.0])}</td>
<td>{rup}</td></tr>""")
    details = []
    for t in rows:
        rs = sorted(all_results[t["ticker"]], key=lambda r: r.debit)
        lines = "".join(
            f"<tr class='{'pick' if r is t['best'] else ''}{'' if r.qualifies else ' dq'}'><td>{html.escape(r.name)}</td>"
            f"<td class=legs>{html.escape(fmt_legs(r.legs))}</td><td>{money(r.debit)}</td>"
            f"<td class={cls(r.runup_flat)}>{money(r.runup_flat)}</td>"
            f"<td class={cls(min(r.runup_lo, r.runup_hi))}>{money(min(r.runup_lo, r.runup_hi))}</td>"
            + "".join(f"<td class={cls(r.post[k])}>{money(r.post[k])}</td>" for k in (0, 0.5, 1.0, 1.5, 2.0))
            + f"<td>{r.vega*100:,.1f}</td><td>{html.escape(r.note) or '–'}</td></tr>" for r in rs)
        details.append(f"""<details><summary><b>{t['ticker']}</b> — all {len(rs)} structures (cheapest first)</summary>
<div class=scroll><table class=sub><tr><th>Structure</th><th>Legs</th><th>Debit</th><th>Run-up flat</th><th>Run-up ±1sd (worst)</th>
<th>Post 0</th><th>±0.5x</th><th>±1x</th><th>±1.5x</th><th>±2x</th><th>Vega/pt</th><th>Qualifies</th></tr>{lines}</table></div></details>""")
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Earnings Vol Optimizer</title>
<style>
:root{{--bg:#f6f8fa;--surface:#fff;--border:#d0d7de;--text:#1f2328;--muted:#656d76;--pos:#1a7f37;--neg:#cf222e;--accent:#0969da;--pick:rgba(9,105,218,.08)}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#0d1117;--surface:#161b22;--border:#30363d;--text:#e6edf3;--muted:#8b949e;--pos:#3fb950;--neg:#f85149;--accent:#79c0ff;--pick:rgba(121,192,255,.1)}}}}
:root[data-theme="dark"]{{--bg:#0d1117;--surface:#161b22;--border:#30363d;--text:#e6edf3;--muted:#8b949e;--pos:#3fb950;--neg:#f85149;--accent:#79c0ff;--pick:rgba(121,192,255,.1)}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:13px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:16px}}
h1{{font-size:20px;margin:0 0 4px}}.sub{{color:var(--muted);margin:0 0 14px}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:14px}}
.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
th,td{{padding:6px 8px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}}
th{{color:var(--muted);font-weight:600;font-size:12px}}td:first-child,th:first-child,td:nth-child(6),th:nth-child(6),td:nth-child(13){{text-align:left}}
.tk{{font-weight:700;color:var(--accent)}}.legs{{color:var(--muted);font-size:11px;text-align:left}}.cost{{font-weight:700}}
.pos{{color:var(--pos)}}.neg{{color:var(--neg)}}tr.pick{{background:var(--pick)}}tr.dq td{{opacity:.55}}
table.sub td:nth-child(2){{text-align:left}}details{{margin:6px 0}}summary{{cursor:pointer;padding:4px 0}}
ul{{margin:6px 0;padding-left:18px}}
</style></head><body>
<h1>Earnings Vol Optimizer</h1>
<p class=sub>As of {today:%d %b %Y} · cheapest long-volatility structure per ticker that pays on a {view:g}x implied earnings move · source: the-edge.csv (IV30, days to earnings) · {len(rows)} tickers, cheapest as % of spot first</p>
<div class=card><div class=scroll><table>
<tr><th>Ticker</th><th>Spot</th><th>Earnings</th><th>IV30</th><th>Impl. move</th><th>Cheapest qualifying structure</th>
<th>Debit/lot</th><th>% spot</th><th>P&amp;L ±1x IM</th><th>P&amp;L ±{view:g}x IM</th><th>P&amp;L ±2x IM</th><th style="text-align:left">Cheapest run-up play (exit pre-release)</th></tr>
{''.join(trs)}</table></div></div>
<div class=card><b>How to read it</b><ul>
<li><b>Thesis</b>: the earnings move will be bigger than the options imply (view = {view:g}x the implied move). Every structure is net long volatility with risk capped at the debit.</li>
<li><b>Pick</b>: the lowest net debit among structures that make money on <i>both</i> an up and a down move of {view:g}x IM after the IV crush. P&amp;L columns show the worse of up/down.</li>
<li><b>Implied move</b> is the event-only expected move: 30d IV is split into base vol + one earnings jump worth E={event_days:g} normal trading days.</li>
<li><b>Run-up play</b>: enter today, close at the bell before the release (spot flat and ±0.5 sd). Uses calendars/double calendars/financed strangles that sell the pre-earnings week to pay for the post-earnings expiry.</li>
<li>Fills: buy ask / sell bid, half-spread max(3%, $0.02) on entry and exit. Flat smile model unless a real chain is supplied (<code>--chain</code>).</li>
<li>Calendar-type picks (front leg sold before the release) are meant to be <b>closed before the announcement</b> or rolled into a pure long strangle after the front expires.</li>
</ul></div>
<div class=card>{''.join(details)}</div>
</body></html>"""


# ---------------------------------------------------------------- main -------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asof", default=None, help="as-of date YYYY-MM-DD (default: the-edge.csv commit date / today)")
    ap.add_argument("--tickers", default=None, help="comma list to restrict the screen")
    ap.add_argument("--min-days", type=int, default=3)
    ap.add_argument("--max-days", type=int, default=35)
    ap.add_argument("--event-days", type=float, default=12.0,
                    help="earnings variance expressed in normal trading days (default 12)")
    ap.add_argument("--ticker"); ap.add_argument("--spot", type=float)
    ap.add_argument("--iv", type=float, help="30d IV in percent")
    ap.add_argument("--earnings", help="release date YYYY-MM-DD")
    ap.add_argument("--chain", help="real option chain CSV")
    ap.add_argument("--move-view", type=float, default=1.5,
                    help="your view of the earnings move as a multiple of the implied move (default 1.5)")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)

    today = dt.date.fromisoformat(a.asof) if a.asof else dt.date.today()
    universe = []
    if a.ticker:
        if not (a.spot and a.earnings and (a.iv or a.chain)):
            ap.error("--ticker needs --spot, --earnings and --iv or --chain")
        universe.append((a.ticker.upper(), a.spot, (a.iv or 0) / 100, dt.date.fromisoformat(a.earnings)))
    else:
        want = {t.strip().upper() for t in a.tickers.split(",")} if a.tickers else None
        with open(EDGE_CSV, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try:
                    d2e = float(row["DaysToEarnings"]); S = float(row["Price"]); iv = float(row["IVImplied"]) / 100
                except (ValueError, KeyError):
                    continue
                if want and row["Ticker"] not in want:
                    continue
                if not (a.min_days <= d2e <= a.max_days) or iv < 0.10 or S < 5:
                    continue
                universe.append((row["Ticker"], S, iv, today + dt.timedelta(days=int(d2e))))

    rows, all_results = [], {}
    for tk, S, iv, earn in universe:
        chain = exps = None
        if a.chain:
            chain, exps = load_chain(a.chain, S, today)
        front, event = pick_expiries(today, earn, exps)
        if not event:
            continue
        model = (model_from_chain(chain, exps, S, today, earn, front, event) if chain
                 else model_from_iv(iv, earn, today, a.event_days))
        res = evaluate(tk, S, model, today, front, event, chain, a.move_view)
        pick, runup = best(res, "move"), best(res, "runup")
        all_results[tk] = res
        if pick:
            rows.append(dict(ticker=tk, spot=S, earnings=earn, iv=iv or model.iv(today, event),
                             im=model.implied_move, best=pick, runup=runup, front=front, event=event))
    rows.sort(key=lambda t: t["best"].debit / t["spot"])

    v = f"@{a.move_view:g}x"
    print(f"{'TICKER':7}{'SPOT':>9} {'EARN':>6} {'IM':>6}  {'CHEAPEST MOVE PLAY':24}{'DEBIT':>9}{v:>9}{'POST1x':>9}  "
          f"{'CHEAPEST RUN-UP PLAY':22}{'DEBIT':>8}{'FLAT':>8}")
    for t in rows:
        b, r = t["best"], t["runup"]
        rp = f"{r.name:22}{money(r.debit):>8}{money(r.runup_flat):>8}" if r else "-"
        print(f"{t['ticker']:7}{t['spot']:9.2f} {t['earnings']:%d%b} {t['im']*100:5.1f}%  {b.name:24}"
              f"{money(b.debit):>9}{money(b.at_view):>9}{money(b.post[1.0]):>9}  {rp}")
        print(f"{'':37}{fmt_legs(b.legs)}")
    if not a.no_write:
        OUT_HTML.write_text(render_html(rows, today, a.event_days, all_results, a.move_view), encoding="utf-8")
        with open(OUT_CSV, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Ticker", "Spot", "Earnings", "IV30", "ImpliedMove%", "Structure", "Legs",
                        "DebitPerLot", "DebitPctSpot", "Post1xIM", "PostViewIM", "Post2xIM", "VegaPerPt", "RunupStructure", "RunupLegs", "RunupDebit", "RunupPnL"])
            for t in rows:
                b = t["best"]
                w.writerow([t["ticker"], t["spot"], t["earnings"], round(t["iv"] * 100, 1), round(t["im"] * 100, 2),
                            b.name, fmt_legs(b.legs), round(b.debit * 100, 2), round(b.debit / t["spot"] * 100, 3),
                            round(b.post[1.0] * 100, 2), round(b.at_view * 100, 2), round(b.post[2.0] * 100, 2),
                            round(b.vega * 100, 2)] + ([t["runup"].name, fmt_legs(t["runup"].legs), round(t["runup"].debit * 100, 2),
                            round(t["runup"].runup_flat * 100, 2)] if t["runup"] else ["", "", "", ""]))
        print(f"\nwrote {OUT_HTML.relative_to(ROOT)} and {OUT_CSV.relative_to(ROOT)}  ({len(rows)} tickers)")
    return rows, all_results


if __name__ == "__main__":
    main()
