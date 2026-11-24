"""Build the static dashboard from exported JSON snapshots."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pipeline.config import (
    EVENTS_JSON,
    EVENTS_PARQUET,
    META_JSON,
    REJECTED_JSON,
    RUNS_JSON,
    SITE_DIR,
)

CHART_JS = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>USGS Earthquake Pipeline Dashboard</title>
  <script src="{chart_js}" crossorigin="anonymous" referrerpolicy="no-referrer"></script>
  <style>
    :root {{
      --bg: #05060f;
      --cyan: #00f0ff;
      --magenta: #ff2bd6;
      --lime: #b6ff00;
      --card: #0c0e1a;
      --text: #e8eefc;
      --muted: #8b93a7;
      --border: #1c2238;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: ui-sans-serif, system-ui, Segoe UI, sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.45;
    }}
    header, main, footer {{ max-width: 1100px; margin: 0 auto; padding: 1.25rem; }}
    h1 {{ font-size: 1.6rem; margin: 0 0 0.35rem; color: var(--cyan); }}
    h2 {{ font-size: 1.05rem; color: var(--lime); margin: 0 0 0.75rem; }}
    .sub {{ color: var(--muted); font-size: 0.95rem; }}
    .banner {{
      display: none; background: #3a1028; border: 1px solid var(--magenta);
      color: #ffd6f2; padding: 0.85rem 1rem; border-radius: 8px; margin: 1rem 0;
    }}
    .banner.show {{ display: block; }}
    .grid {{ display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }}
    .card {{
      background: var(--card); border: 1px solid var(--border); border-radius: 12px;
      padding: 1rem;
    }}
    .stat {{ font-size: 1.5rem; color: var(--cyan); font-variant-numeric: tabular-nums; }}
    .label {{ color: var(--muted); font-size: 0.85rem; }}
    .fresh.ok {{ color: var(--lime); }}
    .fresh.stale {{ color: var(--magenta); }}
    canvas {{ max-height: 280px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
    th, td {{ text-align: left; padding: 0.45rem 0.35rem; border-bottom: 1px solid var(--border); }}
    th {{ color: var(--cyan); font-weight: 600; }}
    tr:hover td {{ background: #101428; }}
    a {{ color: var(--cyan); }}
    footer {{ color: var(--muted); font-size: 0.85rem; padding-bottom: 2rem; }}
    .scatter-wrap {{ position: relative; height: 300px; }}
  </style>
</head>
<body>
  <header>
    <h1>Self-Updating Earthquake Pipeline</h1>
    <p class="sub">Portfolio demo by Rahul Ega. Daily USGS public feed, validated and loaded incrementally.</p>
    <div id="stale-banner" class="banner" role="status">
      Stale data: the last successful pipeline run is older than 36 hours.
      The dashboard is showing the last good snapshot and was not overwritten by a failed run.
    </div>
  </header>
  <main>
    <section class="grid" id="kpis"></section>
    <section class="grid" style="margin-top:1rem">
      <div class="card"><h2>Events per day</h2><canvas id="chart-day"></canvas></div>
      <div class="card"><h2>Magnitude distribution</h2><canvas id="chart-mag"></canvas></div>
    </section>
    <section class="card" style="margin-top:1rem">
      <h2>Lat / Lon scatter (no map tiles)</h2>
      <div class="scatter-wrap"><canvas id="chart-scatter"></canvas></div>
    </section>
    <section class="card" style="margin-top:1rem">
      <h2>Latest events</h2>
      <div style="overflow-x:auto"><table id="tbl-events"><thead></thead><tbody></tbody></table></div>
    </section>
    <section class="card" style="margin-top:1rem">
      <h2>Run history</h2>
      <div style="overflow-x:auto"><table id="tbl-runs"><thead></thead><tbody></tbody></table></div>
    </section>
    <section class="card" style="margin-top:1rem">
      <h2>Data quality</h2>
      <div id="quality" class="grid"></div>
    </section>
  </main>
  <footer>
    <p id="credit"></p>
    <p>This is a portfolio demonstration, not an alerting or safety service.
       Earthquake data courtesy of the U.S. Geological Survey (USGS).
       <a href="https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php">Feed documentation</a>.
    </p>
  </footer>
  <script>
    const COLORS = {{ cyan: '#00f0ff', magenta: '#ff2bd6', lime: '#b6ff00', muted: '#8b93a7' }};
    async function loadJson(path, fallback) {{
      try {{
        const res = await fetch(path, {{ cache: 'no-store' }});
        if (!res.ok) throw new Error(path + ' ' + res.status);
        return await res.json();
      }} catch (e) {{
        console.warn(e);
        return fallback;
      }}
    }}
    function el(id) {{ return document.getElementById(id); }}
    function fmt(v) {{ return v == null ? '—' : v; }}
    async function main() {{
      const meta = await loadJson('meta.json', {{ stale: true, total_events: 0, events_per_day: [], magnitude_distribution: [], quality: {{}}, source: {{}}, disclaimer: '' }});
      const eventsPayload = await loadJson('events.json', {{ events: [] }});
      const runsPayload = await loadJson('runs.json', {{ runs: [] }});
      const events = eventsPayload.events || [];
      const runs = runsPayload.runs || [];

      if (meta.stale) el('stale-banner').classList.add('show');

      const freshClass = meta.stale ? 'stale' : 'ok';
      const freshLabel = meta.stale ? 'Stale' : 'Fresh';
      el('kpis').innerHTML = `
        <div class="card"><div class="label">Last successful update (UTC)</div><div class="stat">${{fmt(meta.last_success_at)}}</div></div>
        <div class="card"><div class="label">Freshness</div><div class="stat fresh ${{freshClass}}">${{freshLabel}}</div><div class="label">Age hours: ${{fmt(meta.data_age_hours)}} (threshold ${{meta.stale_hours_threshold}}h)</div></div>
        <div class="card"><div class="label">Events in store</div><div class="stat">${{fmt(meta.total_events)}}</div></div>
        <div class="card"><div class="label">Rejected last successful export</div><div class="stat">${{fmt(meta.rejected_last_run)}}</div></div>`;

      const dayLabels = (meta.events_per_day || []).map(d => d.date);
      const dayCounts = (meta.events_per_day || []).map(d => d.count);
      new Chart(el('chart-day'), {{
        type: 'bar',
        data: {{ labels: dayLabels, datasets: [{{ label: 'Events', data: dayCounts, backgroundColor: COLORS.cyan }}] }},
        options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ ticks: {{ color: COLORS.muted }} }}, y: {{ ticks: {{ color: COLORS.muted }} }} }} }}
      }});

      const magLabels = (meta.magnitude_distribution || []).map(d => d.bucket);
      const magCounts = (meta.magnitude_distribution || []).map(d => d.count);
      new Chart(el('chart-mag'), {{
        type: 'bar',
        data: {{ labels: magLabels, datasets: [{{ label: 'Count', data: magCounts, backgroundColor: COLORS.magenta }}] }},
        options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ ticks: {{ color: COLORS.muted }} }}, y: {{ ticks: {{ color: COLORS.muted }} }} }} }}
      }});

      const pts = events.filter(e => e.longitude != null && e.latitude != null).slice(0, 800);
      new Chart(el('chart-scatter'), {{
        type: 'scatter',
        data: {{ datasets: [{{
          label: 'Events',
          data: pts.map(e => ({{ x: e.longitude, y: e.latitude, mag: e.magnitude }})),
          backgroundColor: COLORS.lime,
          pointRadius: pts.map(e => Math.max(2, Math.min(8, (e.magnitude || 1)))),
        }}] }},
        options: {{
          plugins: {{ tooltip: {{ callbacks: {{ label: (c) => `lon ${{c.raw.x}}, lat ${{c.raw.y}}, mag ${{c.raw.mag}}` }} }} }},
          scales: {{
            x: {{ title: {{ display: true, text: 'Longitude', color: COLORS.muted }}, min: -180, max: 180, ticks: {{ color: COLORS.muted }} }},
            y: {{ title: {{ display: true, text: 'Latitude', color: COLORS.muted }}, min: -90, max: 90, ticks: {{ color: COLORS.muted }} }}
          }}
        }}
      }});

      const etHead = el('tbl-events').querySelector('thead');
      const etBody = el('tbl-events').querySelector('tbody');
      etHead.innerHTML = '<tr><th>Time (UTC)</th><th>Mag</th><th>Place</th><th>Status</th></tr>';
      etBody.innerHTML = events.slice(0, 25).map(e =>
        `<tr><td>${{fmt(e.event_time)}}</td><td>${{fmt(e.magnitude)}}</td><td>${{e.url ? `<a href="${{e.url}}" target="_blank" rel="noopener">${{fmt(e.place)}}</a>` : fmt(e.place)}}</td><td>${{fmt(e.status)}}</td></tr>`
      ).join('');

      const rh = el('tbl-runs').querySelector('thead');
      const rb = el('tbl-runs').querySelector('tbody');
      rh.innerHTML = '<tr><th>Started</th><th>Status</th><th>Fetched</th><th>New</th><th>Updated</th><th>Unchanged</th><th>Rejected</th><th>Duration ms</th></tr>';
      rb.innerHTML = runs.slice(0, 20).map(r =>
        `<tr><td>${{fmt(r.started_at)}}</td><td>${{fmt(r.status)}}</td><td>${{fmt(r.fetched)}}</td><td>${{fmt(r.new_count)}}</td><td>${{fmt(r.updated_count)}}</td><td>${{fmt(r.unchanged_count)}}</td><td>${{fmt(r.rejected_count)}}</td><td>${{fmt(r.duration_ms)}}</td></tr>`
      ).join('');

      const q = meta.quality || {{}};
      el('quality').innerHTML = `
        <div class="card"><div class="label">With coordinates</div><div class="stat">${{fmt(q.events_with_coords)}}</div></div>
        <div class="card"><div class="label">With magnitude</div><div class="stat">${{fmt(q.events_with_magnitude)}}</div></div>
        <div class="card"><div class="label">Min magnitude</div><div class="stat">${{fmt(q.min_magnitude)}}</div></div>
        <div class="card"><div class="label">Max magnitude</div><div class="stat">${{fmt(q.max_magnitude)}}</div></div>`;

      el('credit').textContent = (meta.source && meta.source.credit) ? meta.source.credit : 'Earthquake data provided by the U.S. Geological Survey (USGS).';
    }}
    main();
  </script>
</body>
</html>
"""


def build_site(
    *,
    site_dir: Path | None = None,
    events_json: Path | None = None,
    runs_json: Path | None = None,
    meta_json: Path | None = None,
    rejected_json: Path | None = None,
    events_parquet: Path | None = None,
) -> Path:
    """Copy snapshots into site/dist and write index.html."""
    out = Path(site_dir or SITE_DIR)
    out.mkdir(parents=True, exist_ok=True)

    mapping = [
        (Path(events_json or EVENTS_JSON), out / "events.json"),
        (Path(runs_json or RUNS_JSON), out / "runs.json"),
        (Path(meta_json or META_JSON), out / "meta.json"),
        (Path(rejected_json or REJECTED_JSON), out / "rejected_latest.json"),
    ]
    for src, dest in mapping:
        if src.exists():
            shutil.copy2(src, dest)
        else:
            dest.write_text(json.dumps({"missing": True}), encoding="utf-8")

    pq = Path(events_parquet or EVENTS_PARQUET)
    if pq.exists():
        shutil.copy2(pq, out / "events.parquet")

    (out / "index.html").write_text(HTML_TEMPLATE.format(chart_js=CHART_JS), encoding="utf-8")
    return out


def main() -> None:
    path = build_site()
    print(f"Site written to {path}")


if __name__ == "__main__":
    main()
