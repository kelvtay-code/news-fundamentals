"""
Generate a static PWA hub page (docs/index.html) from:
  - latest business_overview_*.csv   (Dashboard folder)
  - latest news_bulletin_*.html      (Dashboard folder, copied in full)

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

    generated_at = datetime.now()
    sidebar_html = render_freshness_sidebar([
        ("Business Overview", biz_dt),
        ("News Bulletin", bulletin_dt),
        ("Page generated", generated_at),
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
    --bg:#f9f9f7; --panel:#fcfcfb; --border:#e1e0d9; --text:#0b0b0b; --dim:#6b6a63;
    --accent:#0b3d2e; --accent2:#0ca36c;
    --green:#0ca30c; --orange:#c2570a; --red:#d03b3b;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0b0f14; --panel:#121821; --border:#22303f; --text:#e6edf3; --dim:#8aa0b4; --accent:#3fd08a; --accent2:#2dd4bf;
             --green:#4ade80; --orange:#f97316; --red:#ef4444; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family: -apple-system, system-ui, Segoe UI, Roboto, sans-serif; background:var(--bg); color:var(--text); }}
  header {{ padding:16px; border-bottom:1px solid var(--border); background:var(--panel); position:sticky; top:0; z-index:5;
            display:flex; align-items:flex-start; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
  header h1 {{ margin:0; font-size:1.3rem; }}
  .freshness-panel {{ display:flex; gap:14px; flex-wrap:wrap; }}
  .fresh-item {{ display:flex; align-items:center; gap:8px; font-family: Arial, sans-serif; }}
  .fresh-dot {{ width:10px; height:10px; border-radius:50%; flex:none; }}
  .fresh-dot.fresh-green {{ background:var(--green); box-shadow:0 0 0 3px color-mix(in srgb, var(--green) 25%, transparent); }}
  .fresh-dot.fresh-orange {{ background:var(--orange); box-shadow:0 0 0 3px color-mix(in srgb, var(--orange) 25%, transparent); }}
  .fresh-dot.fresh-red, .fresh-dot.stale-red {{ background:var(--red); box-shadow:0 0 0 3px color-mix(in srgb, var(--red) 25%, transparent); }}
  .fresh-label {{ font-size:0.72rem; text-transform:uppercase; letter-spacing:.03em; color:var(--dim); }}
  .fresh-ts {{ font-size:0.78rem; }}
  nav {{ display:flex; gap:8px; padding:10px 16px; background:var(--panel); border-bottom:1px solid var(--border); overflow-x:auto; }}
  nav button {{ border:1px solid var(--border); background:var(--bg); color:var(--text); padding:8px 14px; border-radius:20px; font-size:0.85rem; cursor:pointer; white-space:nowrap; }}
  nav button.active {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
  main {{ padding:16px; max-width:1200px; margin:0 auto; }}
  section {{ display:none; }}
  section.active {{ display:block; }}
  h2 {{ font-size:1rem; color:var(--dim); text-transform:uppercase; letter-spacing:.04em; margin:0 0 10px; }}
  .table-wrap {{ overflow-x:auto; border:1px solid var(--border); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:0.82rem; }}
  th, td {{ padding:8px 10px; text-align:left; border-bottom:1px solid var(--border); white-space:nowrap; }}
  th {{ position:sticky; top:0; background:var(--panel); cursor:pointer; }}
  tbody tr:hover {{ background:rgba(127,127,127,0.08); }}
  .news-toolbar {{ margin-bottom:8px; }}
  .open-full {{ font-family: Arial, sans-serif; font-size:0.82rem; color:var(--accent2); text-decoration:none; }}
  .open-full:hover {{ text-decoration:underline; }}
  #news iframe {{ width:100%; height:calc(100vh - 220px); min-height:600px; border:1px solid var(--border); border-radius:10px; background:#fff; }}
  .empty {{ color:var(--dim); font-style:italic; }}
  footer {{ text-align:center; color:var(--dim); font-size:0.75rem; padding:20px; }}
</style>
</head>
<body>
<header>
  <h1>Optionx Hub</h1>
  <div class="freshness-panel">
    {sidebar_html}
  </div>
</header>
<nav>
  <button class="active" data-target="overview">Business Overview</button>
  <button data-target="news">News Bulletin</button>
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
  document.querySelectorAll('#bizTable th').forEach((th, idx) => {{
    let asc = true;
    th.addEventListener('click', () => {{
      const table = th.closest('table');
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
    print(f"Wrote {SITE_DIR / 'index.html'}  ({len(biz_rows)} overview rows, bulletin: {bulletin_path.name if bulletin_path else 'none'})")


if __name__ == "__main__":
    build()
