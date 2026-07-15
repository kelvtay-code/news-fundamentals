"""
Generate a static PWA hub page (site/index.html) from:
  - latest business_overview_*.csv  (Dashboard folder)
  - latest *_news_*.txt per ticker  (News folder)

Run this after each pipeline run, then commit+push the site/ folder
to publish an updated version.
"""
import csv
import html
import os
import re
from datetime import datetime
from pathlib import Path

DASHBOARD_DIR = Path(r"G:\My Drive\Claude\Projects\Optionx\Dashboard")
NEWS_DIR = Path(r"G:\My Drive\Claude\Projects\Optionx\News")
SITE_DIR = Path(__file__).resolve().parent.parent / "site"

BIZ_PATTERN = re.compile(r"business_overview_(\d{6})_(\d{4})\.csv$")
NEWS_PATTERN = re.compile(r"^([A-Z]+)_news_(\d{6})\.(\d{4})\.txt$")


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


def latest_news_per_ticker():
    latest = {}
    for f in NEWS_DIR.glob("*_news_*.txt"):
        m = NEWS_PATTERN.match(f.name)
        if not m:
            continue
        ticker, date_str, time_str = m.groups()
        dt = datetime.strptime(date_str + time_str, "%d%m%y%H%M")
        if ticker not in latest or dt > latest[ticker][0]:
            latest[ticker] = (dt, f)
    return dict(sorted(latest.items()))


def parse_news_file(path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    articles = []
    blocks = re.split(r"\n\[#\d+\]\s*", text)[1:]
    for block in blocks:
        lines = block.strip().splitlines()
        source = lines[0].strip() if lines else ""
        title = next((l.split("Title:", 1)[1].strip() for l in lines if l.startswith("Title:")), "")
        published = next((l.split("Published:", 1)[1].strip() for l in lines if l.startswith("Published:")), "")
        link = next((l.split("Link:", 1)[1].strip() for l in lines if l.startswith("Link:")), "")
        summary = next((l.split("Summary:", 1)[1].strip() for l in lines if l.startswith("Summary:")), "")
        if title:
            articles.append({"source": source, "title": title, "published": published, "link": link, "summary": summary})
    return articles[:5]


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


def render_news_cards(news_map):
    if not news_map:
        return "<p class='empty'>No news files found.</p>"
    cards = []
    for ticker, (dt, path) in news_map.items():
        articles = parse_news_file(path)
        if not articles:
            continue
        items = "".join(
            f"""<li>
                  <a href="{esc(a['link'])}" target="_blank" rel="noopener">{esc(a['title'])}</a>
                  <div class="meta">{esc(a['source'])} &middot; {esc(a['published'])}</div>
                </li>"""
            for a in articles
        )
        cards.append(f"""
        <details class="news-card">
          <summary>{esc(ticker)} <span class="ts">updated {dt.strftime('%d %b %Y')}</span></summary>
          <ul>{items}</ul>
        </details>
        """)
    return "\n".join(cards)


def build():
    SITE_DIR.mkdir(exist_ok=True)

    biz_dt, biz_path = latest_business_overview()
    biz_rows = load_business_overview(biz_path) if biz_path else []
    biz_html = render_business_table(biz_rows)
    biz_ts = biz_dt.strftime("%d %b %Y %H:%M") if biz_dt else "N/A"

    news_map = latest_news_per_ticker()
    news_html = render_news_cards(news_map)

    generated_at = datetime.now().strftime("%d %b %Y %H:%M")

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
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0b0f14; --panel:#121821; --border:#22303f; --text:#e6edf3; --dim:#8aa0b4; --accent:#3fd08a; --accent2:#2dd4bf; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family: -apple-system, system-ui, Segoe UI, Roboto, sans-serif; background:var(--bg); color:var(--text); }}
  header {{ padding:20px 16px 12px; border-bottom:1px solid var(--border); background:var(--panel); position:sticky; top:0; z-index:5; }}
  header h1 {{ margin:0; font-size:1.3rem; }}
  header .sub {{ color:var(--dim); font-size:0.85rem; margin-top:4px; }}
  nav {{ display:flex; gap:8px; padding:10px 16px; background:var(--panel); border-bottom:1px solid var(--border); overflow-x:auto; }}
  nav button {{ border:1px solid var(--border); background:var(--bg); color:var(--text); padding:8px 14px; border-radius:20px; font-size:0.85rem; cursor:pointer; white-space:nowrap; }}
  nav button.active {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
  main {{ padding:16px; max-width:900px; margin:0 auto; }}
  section {{ display:none; }}
  section.active {{ display:block; }}
  h2 {{ font-size:1rem; color:var(--dim); text-transform:uppercase; letter-spacing:.04em; margin:0 0 10px; }}
  .table-wrap {{ overflow-x:auto; border:1px solid var(--border); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; font-size:0.82rem; }}
  th, td {{ padding:8px 10px; text-align:left; border-bottom:1px solid var(--border); white-space:nowrap; }}
  th {{ position:sticky; top:0; background:var(--panel); cursor:pointer; }}
  tbody tr:hover {{ background:rgba(127,127,127,0.08); }}
  .news-card {{ border:1px solid var(--border); border-radius:10px; background:var(--panel); margin-bottom:10px; padding:10px 14px; }}
  .news-card summary {{ cursor:pointer; font-weight:600; display:flex; justify-content:space-between; align-items:center; }}
  .news-card .ts {{ font-weight:400; color:var(--dim); font-size:0.75rem; }}
  .news-card ul {{ list-style:none; margin:10px 0 0; padding:0; }}
  .news-card li {{ padding:8px 0; border-top:1px solid var(--border); }}
  .news-card li:first-child {{ border-top:none; }}
  .news-card a {{ color:var(--accent2); text-decoration:none; font-size:0.9rem; }}
  .news-card a:hover {{ text-decoration:underline; }}
  .meta {{ color:var(--dim); font-size:0.75rem; margin-top:2px; }}
  .empty {{ color:var(--dim); font-style:italic; }}
  footer {{ text-align:center; color:var(--dim); font-size:0.75rem; padding:20px; }}
</style>
</head>
<body>
<header>
  <h1>Optionx Hub</h1>
  <div class="sub">Business overview: {esc(biz_ts)} &middot; Page generated {esc(generated_at)}</div>
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
    <h2>News Bulletin (latest per ticker)</h2>
    {news_html}
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
    print(f"Wrote {SITE_DIR / 'index.html'}  ({len(biz_rows)} overview rows, {len(news_map)} tickers with news)")


if __name__ == "__main__":
    build()
