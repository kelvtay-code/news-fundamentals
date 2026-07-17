"""
Generate a static PWA hub page (docs/index.html) from:
  - latest business_overview_*.csv   (Dashboard folder)
  - latest news_bulletin_*.html      (Dashboard folder, copied in full)
  - latest oil brief html            (Dashboard folder, copied in full)
  - latest bull_screener_*.html      (Dashboard folder, copied in full)

Run this after each pipeline run, then commit+push the docs/ folder
to publish an updated version.
"""
import csv
import html
import re
import shutil
from datetime import datetime
from pathlib import Path

DASHBOARD_DIR = Path(r"G:\My Drive\Claude\Projects\Optionx\Dashboard")
SITE_DIR = Path(__file__).resolve().parent.parent / "docs"

BIZ_PATTERN = re.compile(r"business_overview_(\d{6})_(\d{4})\.csv$")
BULLETIN_PATTERN = re.compile(r"news_bulletin_(\d{8})_(\d{4})\.html$")
BULL_SCREENER_PATTERN = re.compile(r"bull_screener_(\d{6})_(\d{4})\.html$")
BULL_TABLE_RE = re.compile(r'<table id="mainTable">.*?</table>', re.DOTALL)
BULL_SORT_ATTR_RE = re.compile(r'\s*onclick="sortTable\(\d+\)"')

# Oil brief filenames have never had one consistent convention
# (Oil_brief_*, oilbrief_*, oil_dashboard_*, oil_brief_platts_analysis_*, etc.)
# so "latest" is picked by file mtime instead of a parsed timestamp.
# oil_trades_* is excluded -- it holds actual positions, not market commentary.
OIL_BRIEF_GLOBS = ["[Oo]il_brief*.html", "oilbrief_*.html", "oil_dashboard_*.html"]
OIL_TRADES_PREFIX = "oil_trades"

# Freshness thresholds (hours since data timestamp)
FRESH_HOURS = 12
STALE_HOURS = 48


def latest_business_overview():
    candidates = []
    for f in DASHBOARD_DIR.glob("business_overview_*.csv"):
        m = BIZ_PATTERN.match(f.name)
        if not m:
            continue
        date_str, time_str = m.groups()
        dt = datetime.strptime(date_str + time_str, "%d%m%y%H%M")
        candidates.append((dt, f))
    if not candidates:
        return None, None
    dt, path = max(candidates, key=lambda x: x[0])
    return dt, path


def load_business_overview(path):
    rows = []
    with open(path, encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(row)
    return rows


def latest_news_bulletin():
    candidates = []
    for f in DASHBOARD_DIR.glob("news_bulletin_*.html"):
        m = BULLETIN_PATTERN.match(f.name)
        if not m:
            continue
        date_str, time_str = m.groups()
        dt = datetime.strptime(date_str + time_str, "%Y%m%d%H%M")
        candidates.append((dt, f))
    if not candidates:
        return None, None
    dt, path = max(candidates, key=lambda x: x[0])
    return dt, path


def latest_oil_brief():
    candidates = []
    seen = set()
    for pattern in OIL_BRIEF_GLOBS:
        for f in DASHBOARD_DIR.glob(pattern):
            if f.name.lower().startswith(OIL_TRADES_PREFIX) or f in seen:
                continue
            seen.add(f)
            candidates.append((datetime.fromtimestamp(f.stat().st_mtime), f))
    if not candidates:
        return None, None
    dt, path = max(candidates, key=lambda x: x[0])
    return dt, path


def latest_bull_screener():
    candidates = []
    for f in DASHBOARD_DIR.glob("bull_screener_*.html"):
        m = BULL_SCREENER_PATTERN.match(f.name)
        if not m:
            continue
        date_str, time_str = m.groups()
        dt = datetime.strptime(date_str + time_str, "%d%m%y%H%M")
        candidates.append((dt, f))
    if not candidates:
        return None, None
    dt, path = max(candidates, key=lambda x: x[0])
    return dt, path


def freshness(dt):
    """Return (label, css_class) describing how stale a timestamp is."""
    if dt is None:
        return "no data", "stale-red"
    age_hours = (datetime.now() - dt).total_seconds() / 3600
    if age_hours < 1:
        age_label = "just now"
    elif age_hours < 24:
        age_label = f"{age_hours:.0f}h ago"
    else:
        age_label = f"{age_hours / 24:.1f}d ago"
    if age_hours <= FRESH_HOURS:
        return age_label, "fresh-green"
    elif age_hours <= STALE_HOURS:
        return age_label, "fresh-orange"
    else:
        return age_label, "fresh-red"


def esc(s):
    return html.escape(str(s or ""))


def render_business_table(rows):
    if not rows:
        return "<p class='empty'>No business overview data found.</p>"
    cols = ["Ticker", "Company", "Sector", "Price", "Forward P/E", "PEG Ratio",
            "Revenue Growth", "Profit Margin", "Dividend Yield", "Target Price", "Analyst Rating"]
    head = "".join(f"<th>{esc(c)}</th>" for c in cols)
    body_rows = []
    for r in rows:
        cells = "".join(f"<td>{esc(r.get(c, ''))}</td>" for c in cols)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"""
    <div class="table-wrap">
    <table id="bizTable">
      <thead><tr>{head}</tr></thead>
      <tbody>{''.join(body_rows)}</tbody>
    </table>
    </div>
    """


BULL_ROW_RE = re.compile(r"<tr[^>]*>.*?</tr>", re.DOTALL)
BULL_TICKER_TD_RE = re.compile(r'<td class="ticker">([^<]*)</td>')
BULL_SECTOR_TD_RE = re.compile(r'(<td class="ticker">[^<]*</td>)<td>[^<]*</td>')
BULL_DATA_SECTOR_RE = re.compile(r'data-sector="[^"]*"')


def _top_level_sector(table_html, sector_map):
    """Swap the granular Sector column (e.g. 'Technology (Enterprise Hardware)')
    for the top-level Sector from business_overview (e.g. 'Technology'), keyed
    by the ticker already present in each row."""
    def replace_row(m):
        row = m.group(0)
        tmatch = BULL_TICKER_TD_RE.search(row)
        if not tmatch:
            return row
        top_sector = sector_map.get(tmatch.group(1).strip())
        if not top_sector:
            return row
        row = BULL_DATA_SECTOR_RE.sub(f'data-sector="{esc(top_sector)}"', row, count=1)
        row = BULL_SECTOR_TD_RE.sub(rf"\1<td>{esc(top_sector)}</td>", row, count=1)
        return row
    return BULL_ROW_RE.sub(replace_row, table_html)


def _extract_balanced_div(text, start_marker):
    """Return the full '<div ...>...</div>' block starting at start_marker,
    correctly handling nested <div> tags inside it (simple regexes break on
    the first inner </div>)."""
    start = text.find(start_marker)
    if start == -1:
        return None
    open_re = re.compile(r"<div\b")
    close_re = re.compile(r"</div>")
    pos = start
    depth = 0
    while pos < len(text):
        om = open_re.match(text, pos)
        if om:
            depth += 1
            pos = om.end()
            continue
        cm = close_re.match(text, pos)
        if cm:
            depth -= 1
            pos = cm.end()
            if depth == 0:
                return text[start:pos]
            continue
        pos += 1
    return None


def render_bull_screener_table(path, sector_map=None):
    """Parse the masthead/stats-banner/#mainTable markup out of the
    bull-screener HTML and render them natively (table-wrap treatment
    matching the Business Overview tab, masthead re-namespaced to avoid
    colliding with the hub's own top-of-page masthead) instead of loading
    the standalone page in an iframe."""
    if not path:
        return "<p class='empty'>No bull screener file found.</p>"
    text = path.read_text(encoding="utf-8")

    masthead_html = _extract_balanced_div(text, '<div class="masthead">')
    stats_html = _extract_balanced_div(text, '<div class="stats-banner">')
    masthead_html = (masthead_html or "").replace("masthead", "bull-masthead")
    stats_html = (stats_html or "").replace("stats-banner", "bull-stats-banner").replace("stats-inner", "bull-stats-inner").replace("stat-item", "bull-stat-item").replace("stat-sep", "bull-stat-sep")

    m = BULL_TABLE_RE.search(text)
    if not m:
        return "<p class='empty'>Bull screener file found but table markup could not be parsed.</p>"
    table_html = BULL_SORT_ATTR_RE.sub("", m.group(0))
    if sector_map:
        table_html = _top_level_sector(table_html, sector_map)
    return f'{masthead_html}{stats_html}<div class="table-wrap">{table_html}</div>'


def render_freshness_sidebar(sources):
    """sources: list of (label, dt) tuples."""
    items = []
    for label, dt in sources:
        age_label, css_class = freshness(dt)
        abs_label = dt.strftime("%d %b %Y, %H:%M") if dt else "not found"
        items.append(f"""
        <div class="fresh-item">
          <span class="fresh-dot {css_class}"></span>
          <div>
            <div class="fresh-label">{esc(label)}</div>
            <div class="fresh-ts">{esc(abs_label)} &middot; <strong>{esc(age_label)}</strong></div>
          </div>
        </div>
        """)
    return "\n".join(items)


def build():
    SITE_DIR.mkdir(exist_ok=True)

    biz_dt, biz_path = latest_business_overview()
    biz_rows = load_business_overview(biz_path) if biz_path else []
    biz_html = render_business_table(biz_rows)

    bulletin_dt, bulletin_path = latest_news_bulletin()
    if bulletin_path:
        shutil.copyfile(bulletin_path, SITE_DIR / "news-bulletin.html")
        bulletin_frame = (
            '<div class="news-toolbar">'
            '<a class="open-full" href="news-bulletin.html" target="_blank" rel="noopener">'
            'Open full bulletin in new tab &#8599;</a></div>'
            '<iframe src="news-bulletin.html" title="News Bulletin"></iframe>'
        )
    else:
        bulletin_frame = "<p class='empty'>No news bulletin file found.</p>"

    oil_dt, oil_path = latest_oil_brief()
    if oil_path:
        shutil.copyfile(oil_path, SITE_DIR / "oil-brief.html")
        oil_frame = (
            '<div class="news-toolbar">'
            '<a class="open-full" href="oil-brief.html" target="_blank" rel="noopener">'
            'Open full oil brief in new tab &#8599;</a></div>'
            '<iframe src="oil-brief.html" title="Oil Brief"></iframe>'
        )
    else:
        oil_frame = "<p class='empty'>No oil brief file found.</p>"

    bull_dt, bull_path = latest_bull_screener()
    if bull_path:
        shutil.copyfile(bull_path, SITE_DIR / "bull-screener.html")
    biz_sector_map = {r.get("Ticker", "").strip(): r.get("Sector", "").strip() for r in biz_rows}
    bull_html = render_bull_screener_table(bull_path, biz_sector_map)

    generated_at = datetime.now()
    sidebar_html = render_freshness_sidebar([
        ("Page generated", generated_at),
        ("Oil brief", oil_dt),
        ("Bull screener", bull_dt),
    ])

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b3d2e">
<title>Optionx Hub</title>
<link rel="manifest" href="manifest.json">
<link rel="apple-touch-icon" href="icons/icon-192.png">
<style>
  :root {{
    --ft-salmon:   #FFF1E0;
    --ft-red:      #990F3D;
    --ft-blue:     #0F5499;
    --ft-navy:     #262A33;
    --ft-warm-blk: #33302E;
    --ft-border:   #CCB799;
    --ft-mid:      #8D775F;
    --ft-muted:    #66605A;
    --ft-card-bg:  #FFFAF4;
    --ft-card-bdr: #D4A96A;
    --ft-gold:     #F0A500;
    --green:#0ca30c; --orange:#c2570a; --red:#990F3D;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family: Georgia, 'Times New Roman', serif; background:var(--ft-salmon); color:var(--ft-warm-blk); font-size:14px; line-height:1.5; }}

  .masthead {{ background:var(--ft-navy); color:#fff; padding:0 40px; border-bottom:4px solid var(--ft-red); position:sticky; top:0; z-index:5; }}
  .masthead-inner {{ max-width:1320px; margin:0 auto; padding:8px 0 6px; display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; }}
  .masthead-eyebrow {{ font-family: Arial, sans-serif; font-size:9px; letter-spacing:0.1em; text-transform:uppercase; color:#AAAAAA; margin-bottom:2px; }}
  .masthead-title {{ font-size:1.25rem; font-weight:700; letter-spacing:-0.01em; }}
  .masthead-title span {{ color:var(--ft-gold); }}

  .freshness-panel {{ display:flex; gap:10px; flex-wrap:wrap; padding-top:0; }}
  .fresh-item {{ display:flex; align-items:center; gap:5px; font-family: Arial, sans-serif; }}
  .fresh-dot {{ width:8px; height:8px; border-radius:50%; flex:none; }}
  .fresh-dot.fresh-green {{ background:#3fce6e; box-shadow:0 0 0 3px rgba(63,206,110,0.25); }}
  .fresh-dot.fresh-orange {{ background:var(--ft-gold); box-shadow:0 0 0 3px rgba(240,165,0,0.25); }}
  .fresh-dot.fresh-red, .fresh-dot.stale-red {{ background:#e0546f; box-shadow:0 0 0 3px rgba(224,84,111,0.25); }}
  .fresh-label {{ display:none; }}
  .fresh-ts {{ font-size:0.66rem; color:#fff; }}

  nav.section-nav {{ background:var(--ft-navy); padding:0 40px; border-bottom:1px solid #44495A; }}
  nav.section-nav .nav-inner {{ max-width:1320px; margin:0 auto; display:flex; gap:0; overflow-x:auto; }}
  nav.section-nav button {{ font-family: Arial, sans-serif; font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:0.06em;
    color:#AAAAAA; background:none; border:none; padding:7px 12px; cursor:pointer; white-space:nowrap; border-bottom:3px solid transparent; }}
  nav.section-nav button:hover {{ color:#fff; border-bottom-color:var(--ft-red); }}
  nav.section-nav button.active {{ color:#fff; border-bottom-color:var(--ft-red); }}

  main {{ max-width:1320px; margin:0 auto; padding:24px 40px 40px; }}
  section {{ display:none; }}
  section.active {{ display:block; }}
  h2 {{ font-family: Arial, sans-serif; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.1em; color:var(--ft-mid); margin:0 0 12px; }}
  .table-wrap {{ overflow-x:auto; border:1px solid var(--ft-border); background:var(--ft-card-bg); }}
  table {{ border-collapse:collapse; width:100%; font-size:0.82rem; font-family: Arial, sans-serif; }}
  th, td {{ padding:8px 10px; text-align:left; border-bottom:1px solid var(--ft-border); white-space:nowrap; }}
  th {{ position:sticky; top:0; background:var(--ft-navy); color:#fff; font-size:10px; text-transform:uppercase; letter-spacing:0.06em; cursor:pointer; }}
  tbody tr:hover {{ background:var(--ft-salmon); }}
  .news-toolbar {{ margin-bottom:8px; font-family: Arial, sans-serif; }}
  .open-full {{ font-size:0.82rem; color:var(--ft-blue); text-decoration:none; font-weight:600; }}
  .open-full:hover {{ text-decoration:underline; }}
  #news iframe, #oil iframe {{ width:100%; height:calc(100vh - 220px); min-height:600px; border:1px solid var(--ft-border); background:#fff; }}
  .empty {{ color:var(--ft-mid); font-style:italic; font-family: Arial, sans-serif; }}

  #bullscreener .chip {{ display:inline-block; font-family: Arial, sans-serif; font-size:10.5px; font-weight:700; padding:2px 8px; border-radius:2px; white-space:normal; letter-spacing:0.02em; }}
  #bullscreener .chip-bull, #bullscreener .chip-gex {{ background:#E3EEDF; color:#2F6D3F; }}
  #bullscreener .chip-warn {{ background:#F7E3CE; color:#B15C1E; }}
  #bullscreener .chip-none {{ color:var(--ft-mid); font-family: Arial, sans-serif; font-size:11px; }}
  #bullscreener td.rank {{ color:var(--ft-mid); font-family: Arial, sans-serif; font-size:11px; }}
  #bullscreener td.ticker {{ font-family: Arial, sans-serif; font-weight:700; color:var(--ft-red); letter-spacing:0.01em; }}
  #bullscreener td.num, #bullscreener th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  #bullscreener td.newscell {{ font-size:0.78rem; color:var(--ft-muted); }}

  /* Autosize: fixed layout + wrapping so all 15 columns fit without a horizontal scrollbar */
  #bullscreener table {{ table-layout:fixed; background:#fff; }}
  #bullscreener th, #bullscreener td {{ white-space:normal; overflow-wrap:break-word; vertical-align:top; }}
  #bullscreener th {{ line-height:1.3; padding:10px 8px; }}
  #bullscreener td {{ padding:10px 8px; }}
  #bullscreener td {{ background:#fff; }}
  #bullscreener tbody tr:nth-child(even) td, #bullscreener tbody tr.warn-row td {{ background:#fff; }}
  #bullscreener thead th {{ border-right:1px solid #3d4250; }}
  #bullscreener thead th:last-child {{ border-right:none; }}
  #bullscreener tbody td {{ border-right:1px solid var(--ft-border); }}
  #bullscreener tbody td:last-child {{ border-right:none; }}

  /* Tab-specific masthead + stats banner, re-namespaced from the standalone dashboard page
     (site-level .masthead above is a different, sticky element -- keep these separate) */
  #bullscreener .bull-masthead {{ background:var(--ft-navy); color:#fff; border-bottom:4px solid var(--ft-red); border-radius:4px; padding:18px 20px 14px; margin-bottom:0; }}
  #bullscreener .bull-masthead-eyebrow {{ font-family: Arial, sans-serif; font-size:10px; letter-spacing:0.12em; text-transform:uppercase; color:#AAAAAA; margin-bottom:6px; }}
  #bullscreener .bull-masthead-title {{ font-family: Georgia, 'Times New Roman', serif; font-size:1.6rem; font-weight:700; letter-spacing:-0.01em; }}
  #bullscreener .bull-masthead-title span {{ color:var(--ft-gold); }}
  #bullscreener .bull-masthead-date {{ font-family: Arial, sans-serif; font-size:11px; color:#AAAAAA; margin-top:6px; }}
  #bullscreener .bull-masthead-tagline {{ font-style:italic; font-size:12px; color:#CCCCCC; border-top:1px solid #44495A; padding-top:8px; margin-top:8px; }}
  #bullscreener .bull-stats-banner {{ background:var(--ft-red); padding:8px 20px; }}
  #bullscreener .bull-stats-inner {{ display:flex; align-items:center; gap:20px; flex-wrap:wrap; }}
  #bullscreener .bull-stat-item {{ font-family: Arial, sans-serif; font-size:12px; color:#fff; display:flex; align-items:center; gap:6px; }}
  #bullscreener .bull-stat-item strong {{ font-weight:700; }}
  #bullscreener .bull-stat-sep {{ color:rgba(255,255,255,0.4); }}
  #bullscreener .table-wrap {{ margin-top:14px; }}
  #bullscreener th:nth-child(1),  #bullscreener td:nth-child(1)  {{ width:2%; }}
  #bullscreener th:nth-child(2),  #bullscreener td:nth-child(2)  {{ width:5%; }}
  #bullscreener th:nth-child(3),  #bullscreener td:nth-child(3)  {{ width:7%; }}
  #bullscreener th:nth-child(4),  #bullscreener td:nth-child(4)  {{ width:6%; }}
  #bullscreener th:nth-child(5),  #bullscreener td:nth-child(5)  {{ width:8%; }}
  #bullscreener th:nth-child(6),  #bullscreener td:nth-child(6)  {{ width:7%; }}
  #bullscreener th:nth-child(7),  #bullscreener td:nth-child(7)  {{ width:4%; }}
  #bullscreener th:nth-child(8),  #bullscreener td:nth-child(8)  {{ width:7%; }}
  #bullscreener th:nth-child(9),  #bullscreener td:nth-child(9)  {{ width:11%; }}
  #bullscreener th:nth-child(10), #bullscreener td:nth-child(10) {{ width:8%; }}
  #bullscreener th:nth-child(11), #bullscreener td:nth-child(11) {{ width:5%; }}
  #bullscreener th:nth-child(12), #bullscreener td:nth-child(12) {{ width:5%; }}
  #bullscreener th:nth-child(13), #bullscreener td:nth-child(13) {{ width:5%; }}
  #bullscreener th:nth-child(14), #bullscreener td:nth-child(14) {{ width:7%; }}
  #bullscreener th:nth-child(15), #bullscreener td:nth-child(15) {{ width:13%; }}
  footer {{ background:var(--ft-navy); color:#888; font-family: Arial, sans-serif; font-size:11px; text-align:center; padding:16px 40px; margin-top:20px; border-top:3px solid var(--ft-red); }}
  @media (max-width: 700px) {{
    .masthead, nav.section-nav, main {{ padding-left:16px; padding-right:16px; }}
    .masthead-eyebrow {{ display:none; }}
    .masthead-title {{ font-size:1.05rem; }}
    .fresh-ts {{ font-size:0.6rem; }}
  }}
</style>
</head>
<body>
<div class="masthead">
  <div class="masthead-inner">
    <div>
      <div class="masthead-eyebrow">Optionx Intelligence</div>
      <div class="masthead-title">Optionx <span>Hub</span></div>
    </div>
    <div class="freshness-panel">
      {sidebar_html}
    </div>
  </div>
</div>
<nav class="section-nav">
  <div class="nav-inner">
    <button class="active" data-target="overview">Business Overview</button>
    <button data-target="news">News Bulletin</button>
    <button data-target="oil">Oil Brief</button>
    <button data-target="bullscreener">Bull Screener</button>
  </div>
</nav>
<main>
  <section id="overview" class="active">
    <h2>Business Overview</h2>
    {biz_html}
  </section>
  <section id="news">
    <h2>News Bulletin</h2>
    {bulletin_frame}
  </section>
  <section id="oil">
    <h2>Oil Brief</h2>
    {oil_frame}
  </section>
  <section id="bullscreener">
    {bull_html}
  </section>
</main>
<footer>Optionx Hub &middot; static, offline-capable &middot; regenerate after each pipeline run</footer>
<script>
  document.querySelectorAll('nav button').forEach(btn => {{
    btn.addEventListener('click', () => {{
      document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('main section').forEach(s => s.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(btn.dataset.target).classList.add('active');
    }});
  }});
  document.querySelectorAll('.table-wrap table thead th').forEach((th) => {{
    let asc = true;
    th.addEventListener('click', () => {{
      const table = th.closest('table');
      const idx = Array.from(th.parentNode.children).indexOf(th);
      const rows = Array.from(table.querySelectorAll('tbody tr'));
      rows.sort((a, b) => {{
        const av = a.children[idx].textContent.trim();
        const bv = b.children[idx].textContent.trim();
        const an = parseFloat(av.replace(/[^0-9.\\-]/g, ''));
        const bn = parseFloat(bv.replace(/[^0-9.\\-]/g, ''));
        const bothNum = !isNaN(an) && !isNaN(bn);
        return bothNum ? (asc ? an - bn : bn - an) : (asc ? av.localeCompare(bv) : bv.localeCompare(av));
      }});
      asc = !asc;
      const tbody = table.querySelector('tbody');
      rows.forEach(r => tbody.appendChild(r));
    }});
  }});
  if ('serviceWorker' in navigator) {{
    navigator.serviceWorker.register('sw.js').catch(() => {{}});
  }}
</script>
</body>
</html>
"""
    (SITE_DIR / "index.html").write_text(page, encoding="utf-8")
    print(
        f"Wrote {SITE_DIR / 'index.html'}  "
        f"({len(biz_rows)} overview rows, bulletin: {bulletin_path.name if bulletin_path else 'none'}, "
        f"oil brief: {oil_path.name if oil_path else 'none'}, "
        f"bull screener: {bull_path.name if bull_path else 'none'})"
    )


if __name__ == "__main__":
    build()
