from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, StreamingResponse

from orchestra.code_agent.dashboard.metrics import get_metrics


def register_dashboard_routes(app: Any, prefix: str = "/dashboard") -> None:

    @app.get(prefix, response_class=HTMLResponse)
    async def dashboard_page():
        """Serve the Orchestra real-time cost dashboard."""
        return HTMLResponse(_DASHBOARD_HTML)

    @app.get(f"{prefix}/stream")
    async def dashboard_stream(request: Request):
        """SSE endpoint — streams a metrics snapshot every 2 seconds."""

        async def event_generator():
            metrics = get_metrics()
            while True:
                if await request.is_disconnected():
                    break
                try:
                    metrics.tick()
                    data = metrics.snapshot()
                    yield f"data: {json.dumps(data)}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
                await asyncio.sleep(2)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get(f"{prefix}/snapshot")
    async def dashboard_snapshot():
        """One-shot JSON snapshot of all dashboard metrics."""
        m = get_metrics()
        m.tick()
        return m.snapshot()


# ---------------------------------------------------------------------------
# Self-contained dashboard HTML — no build step, no npm, no external deps
# except Chart.js from CDN
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Orchestra Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg:       #0d1117;
    --surface:  #161b22;
    --border:   #21262d;
    --text:     #e6edf3;
    --muted:    #8b949e;
    --green:    #3fb950;
    --blue:     #58a6ff;
    --purple:   #bc8cff;
    --orange:   #d29922;
    --red:      #f85149;
    --teal:     #39d353;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, 'Segoe UI', sans-serif; min-height: 100vh; }

  header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 16px 24px; border-bottom: 1px solid var(--border);
    background: var(--surface);
  }
  header h1 { font-size: 18px; font-weight: 600; letter-spacing: 0.5px; }
  header h1 span { color: var(--blue); }

  .live-badge {
    display: flex; align-items: center; gap: 6px;
    font-size: 12px; color: var(--muted);
  }
  .live-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--green);
    animation: pulse 2s ease-in-out infinite;
  }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }

  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: auto auto;
    gap: 1px;
    background: var(--border);
    height: calc(100vh - 57px);
  }

  .panel {
    background: var(--surface);
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    overflow: hidden;
    min-height: 0;
  }

  .panel-header {
    display: flex; align-items: baseline; justify-content: space-between;
    flex-shrink: 0;
  }
  .panel-title {
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 1px; color: var(--muted);
  }
  .panel-value {
    font-size: 28px; font-weight: 700; letter-spacing: -0.5px;
    flex-shrink: 0;
  }
  .panel-sub {
    font-size: 12px; color: var(--muted); flex-shrink: 0;
  }

  .chart-wrap {
    flex: 1;
    position: relative;
    min-height: 0;
  }

  .stat-row {
    display: flex; gap: 16px; flex-wrap: wrap; flex-shrink: 0;
  }
  .stat-pill {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
  }
  .stat-pill .label { color: var(--muted); margin-bottom: 2px; }
  .stat-pill .val { font-weight: 600; font-size: 14px; }

  .bar-grid { display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; }
  .bar-item { display: flex; align-items: center; gap: 10px; font-size: 12px; }
  .bar-label { width: 110px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .bar-track { flex: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 3px; transition: width 0.6s ease; }
  .bar-pct { width: 42px; text-align: right; font-weight: 600; }

  .gauge-row { display: flex; gap: 20px; flex-shrink: 0; }
  .gauge { flex: 1; }
  .gauge-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
  .gauge-val { font-size: 22px; font-weight: 700; }
  .gauge-track { height: 4px; background: var(--border); border-radius: 2px; margin-top: 6px; overflow: hidden; }
  .gauge-fill { height: 100%; border-radius: 2px; transition: width 0.6s ease; }

  .latency-pills { display: flex; gap: 10px; flex-shrink: 0; }
  .lat-pill { flex: 1; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; text-align: center; }
  .lat-pill .lp-label { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
  .lat-pill .lp-val { font-size: 18px; font-weight: 700; margin-top: 2px; }

  .no-data { color: var(--muted); font-size: 13px; text-align: center; padding: 20px; }

  #status-bar {
    position: fixed; bottom: 0; left: 0; right: 0;
    font-size: 11px; color: var(--muted);
    background: var(--surface);
    border-top: 1px solid var(--border);
    padding: 4px 24px;
    display: flex; justify-content: space-between;
  }
</style>
</head>
<body>

<header>
  <h1>&#127926; <span>Orchestra</span> Dashboard</h1>
  <div class="live-badge">
    <div class="live-dot" id="dot"></div>
    <span id="live-label">Connecting…</span>
  </div>
</header>

<div class="grid">

  <!-- ── Panel 1: Token Spend ── -->
  <div class="panel" id="panel-spend">
    <div class="panel-header">
      <div class="panel-title">&#x1F4B0; Token Spend</div>
      <div style="font-size:11px;color:var(--muted)" id="spend-rate">— /hr</div>
    </div>
    <div class="panel-value" id="spend-total">$0.000000</div>
    <div class="panel-sub" id="spend-tokens">0 tokens total</div>
    <div class="chart-wrap">
      <canvas id="chart-spend"></canvas>
    </div>
    <div class="bar-grid" id="model-bars"></div>
  </div>

  <!-- ── Panel 2: Acceptance Rates ── -->
  <div class="panel" id="panel-accept">
    <div class="panel-header">
      <div class="panel-title">&#x2705; Acceptance Rate</div>
      <div style="font-size:11px;color:var(--muted)" id="accept-window">60s rolling</div>
    </div>
    <div class="panel-value" id="accept-pct" style="color:var(--green)">—</div>
    <div class="panel-sub" id="accept-counts">0 evaluated · 0 passed</div>
    <div class="chart-wrap">
      <canvas id="chart-accept"></canvas>
    </div>
    <div class="bar-grid" id="agent-bars"></div>
  </div>

  <!-- ── Panel 3: Council Latency ── -->
  <div class="panel" id="panel-latency">
    <div class="panel-header">
      <div class="panel-title">&#x23F1;&#xFE0F; Council Latency</div>
      <div style="font-size:11px;color:var(--muted)" id="latency-evals">0 evals</div>
    </div>
    <div class="latency-pills">
      <div class="lat-pill">
        <div class="lp-label">P50</div>
        <div class="lp-val" id="lat-p50" style="color:var(--green)">—</div>
      </div>
      <div class="lat-pill">
        <div class="lp-label">P95</div>
        <div class="lp-val" id="lat-p95" style="color:var(--orange)">—</div>
      </div>
      <div class="lat-pill">
        <div class="lp-label">P99</div>
        <div class="lp-val" id="lat-p99" style="color:var(--red)">—</div>
      </div>
      <div class="lat-pill">
        <div class="lp-label">Mean</div>
        <div class="lp-val" id="lat-mean" style="color:var(--blue)">—</div>
      </div>
    </div>
    <div class="chart-wrap">
      <canvas id="chart-latency"></canvas>
    </div>
    <div class="bar-grid" id="judge-bars"></div>
  </div>

  <!-- ── Panel 4: Compute Utilization ── -->
  <div class="panel" id="panel-compute">
    <div class="panel-header">
      <div class="panel-title">&#x1F5A5;&#xFE0F; Compute Utilization</div>
      <div style="font-size:11px;color:var(--muted)">Orchestra process</div>
    </div>
    <div class="gauge-row">
      <div class="gauge">
        <div class="gauge-label">CPU</div>
        <div class="gauge-val" id="cpu-val">0%</div>
        <div class="gauge-track"><div class="gauge-fill" id="cpu-bar" style="background:var(--blue);width:0%"></div></div>
      </div>
      <div class="gauge">
        <div class="gauge-label">Memory</div>
        <div class="gauge-val" id="mem-val">0 MB</div>
        <div class="gauge-track"><div class="gauge-fill" id="mem-bar" style="background:var(--purple);width:0%"></div></div>
      </div>
    </div>
    <div class="chart-wrap">
      <canvas id="chart-compute"></canvas>
    </div>
    <div class="stat-row" id="db-stats"></div>
  </div>

</div>

<div id="status-bar">
  <span id="status-msg">Waiting for data…</span>
  <span id="status-ts"></span>
</div>

<script>
// ── Chart defaults ──────────────────────────────────────────────────────────
Chart.defaults.color = '#8b949e';
Chart.defaults.borderColor = '#21262d';
Chart.defaults.font.family = "-apple-system, 'Segoe UI', sans-serif";
Chart.defaults.font.size = 11;

const MAX_PTS = 60;

function makeLineChart(id, datasets, yLabel='') {
  const ctx = document.getElementById(id).getContext('2d');
  return new Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 400 },
      plugins: { legend: { display: datasets.length > 1, position: 'top' } },
      scales: {
        x: { display: false },
        y: {
          grid: { color: '#21262d' },
          ticks: { color: '#8b949e', maxTicksLimit: 5 },
          title: yLabel ? { display: true, text: yLabel, color: '#8b949e' } : { display: false }
        }
      },
      elements: { point: { radius: 0 }, line: { tension: 0.3, borderWidth: 2 } }
    }
  });
}

function pushChart(chart, labels, ...valueSets) {
  chart.data.labels = labels;
  valueSets.forEach((vals, i) => { chart.data.datasets[i].data = vals; });
  if (chart.data.labels.length > MAX_PTS) {
    chart.data.labels = chart.data.labels.slice(-MAX_PTS);
    chart.data.datasets.forEach(d => { d.data = d.data.slice(-MAX_PTS); });
  }
  chart.update('none');
}

// ── Init charts ─────────────────────────────────────────────────────────────
const spendChart = makeLineChart('chart-spend', [{
  label: 'Total USD', data: [], borderColor: '#3fb950', backgroundColor: 'rgba(63,185,80,0.1)', fill: true
}]);

const acceptChart = makeLineChart('chart-accept', [{
  label: 'Pass rate', data: [], borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,0.1)', fill: true,
  spanGaps: true
}]);

const latencyChart = makeLineChart('chart-latency', [
  { label: 'P50 ms', data: [], borderColor: '#3fb950', spanGaps: true },
  { label: 'P95 ms', data: [], borderColor: '#d29922', spanGaps: true },
], 'ms');

const computeChart = makeLineChart('chart-compute', [
  { label: 'CPU %', data: [], borderColor: '#58a6ff' },
  { label: 'Mem MB', data: [], borderColor: '#bc8cff', yAxisID: 'y2' },
]);
computeChart.options.scales.y2 = {
  position: 'right', grid: { drawOnChartArea: false },
  ticks: { color: '#8b949e', maxTicksLimit: 4 }
};
computeChart.update('none');

// ── Colour helpers ──────────────────────────────────────────────────────────
const COLOURS = ['#58a6ff','#3fb950','#d29922','#bc8cff','#f85149','#39d353','#e3b341'];
function col(i) { return COLOURS[i % COLOURS.length]; }

function pctColour(p) {
  if (p >= 0.8) return 'var(--green)';
  if (p >= 0.6) return 'var(--orange)';
  return 'var(--red)';
}

function fmtMs(ms) {
  if (ms === null || ms === undefined) return '—';
  return ms >= 1000 ? (ms/1000).toFixed(1)+'s' : Math.round(ms)+'ms';
}

function fmtUsd(v) {
  if (v < 0.000001) return '$0.000000';
  if (v < 0.01) return '$' + v.toFixed(6);
  if (v < 1) return '$' + v.toFixed(4);
  return '$' + v.toFixed(2);
}

// ── Bar builders ────────────────────────────────────────────────────────────
function buildBars(container, entries, colourFn) {
  // entries: [{label, value, max, colour?}]
  container.innerHTML = '';
  entries.forEach(({label, value, max, colour}) => {
    const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
    container.insertAdjacentHTML('beforeend', `
      <div class="bar-item">
        <div class="bar-label" title="${label}">${label}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${pct.toFixed(1)}%;background:${colour||'var(--blue)'}"></div></div>
        <div class="bar-pct">${typeof value === 'number' && value < 2 ? (value*100).toFixed(0)+'%' : value}</div>
      </div>`);
  });
}

// ── SSE handler ─────────────────────────────────────────────────────────────
let tickCount = 0;
const es = new EventSource('/dashboard/stream');

es.onopen = () => {
  document.getElementById('live-label').textContent = 'Live';
  document.getElementById('dot').style.background = 'var(--green)';
};
es.onerror = () => {
  document.getElementById('live-label').textContent = 'Reconnecting…';
  document.getElementById('dot').style.background = 'var(--red)';
};

es.onmessage = (event) => {
  const d = JSON.parse(event.data);
  if (d.error) { console.warn('Dashboard error:', d.error); return; }
  tickCount++;

  const now = new Date(d.timestamp * 1000);
  document.getElementById('status-msg').textContent = `Tick #${tickCount} — ${tickCount * 2}s runtime`;
  document.getElementById('status-ts').textContent = now.toLocaleTimeString();

  updateSpend(d.token_spend);
  updateAccept(d.acceptance);
  updateLatency(d.council_latency);
  updateCompute(d.compute);
};

// ── Panel updaters ───────────────────────────────────────────────────────────

function updateSpend(s) {
  document.getElementById('spend-total').textContent = fmtUsd(s.total_usd);
  document.getElementById('spend-rate').textContent = fmtUsd(s.per_hour_usd) + '/hr';
  document.getElementById('spend-tokens').textContent =
    s.total_tokens.toLocaleString() + ' tokens total · ' +
    s.per_hour_tokens.toLocaleString() + '/hr';

  // chart
  const hist = s.history || [];
  const labels = hist.map(h => new Date(h.t*1000).toLocaleTimeString());
  const vals   = hist.map(h => h.usd);
  pushChart(spendChart, labels, vals);

  // model bars
  const entries = Object.entries(s.by_model || {});
  const maxCost = Math.max(...entries.map(([,v]) => v), 0.000001);
  buildBars(document.getElementById('model-bars'), entries.map(([k,v], i) => ({
    label: k, value: fmtUsd(v), max: maxCost, colour: col(i)
  })));
}

function updateAccept(a) {
  const rate = a.recent_rate !== null ? a.recent_rate : a.overall_rate;
  const el = document.getElementById('accept-pct');
  if (rate !== null && rate !== undefined) {
    el.textContent = (rate * 100).toFixed(1) + '%';
    el.style.color = pctColour(rate);
  } else {
    el.textContent = '—';
  }
  document.getElementById('accept-counts').textContent =
    `${a.total_evaluated} evaluated · ${a.passed} passed`;

  // chart
  const hist = a.history || [];
  const labels = hist.map(h => new Date(h.t*1000).toLocaleTimeString());
  const vals   = hist.map(h => h.rate);
  pushChart(acceptChart, labels, vals);

  // agent bars
  const agents = Object.entries(a.by_agent || {});
  buildBars(document.getElementById('agent-bars'), agents.map(([k,v], i) => ({
    label: k, value: v, max: 1, colour: pctColour(v)
  })));
}

function updateLatency(l) {
  document.getElementById('lat-p50').textContent  = fmtMs(l.p50_ms);
  document.getElementById('lat-p95').textContent  = fmtMs(l.p95_ms);
  document.getElementById('lat-p99').textContent  = fmtMs(l.p99_ms);
  document.getElementById('lat-mean').textContent = fmtMs(l.mean_ms);
  document.getElementById('latency-evals').textContent = l.total_evals + ' evals';

  // chart
  const hist = l.history || [];
  const labels = hist.map(h => new Date(h.t*1000).toLocaleTimeString());
  const p50s   = hist.map(h => h.p50);
  const p95s   = hist.map(h => h.p95);
  pushChart(latencyChart, labels, p50s, p95s);

  // judge bars
  const judges = Object.entries(l.by_judge || {});
  const maxLat = Math.max(...judges.map(([,v]) => v), 1);
  buildBars(document.getElementById('judge-bars'), judges.map(([k,v], i) => ({
    label: k, value: Math.round(v) + 'ms', max: maxLat, colour: col(i)
  })));
}

function updateCompute(c) {
  document.getElementById('cpu-val').textContent = c.cpu_pct.toFixed(1) + '%';
  document.getElementById('mem-val').textContent = c.mem_mb.toFixed(0) + ' MB';
  document.getElementById('cpu-bar').style.width = Math.min(c.cpu_pct, 100) + '%';
  document.getElementById('mem-bar').style.width = Math.min(c.mem_pct, 100) + '%';

  // chart
  const hist = c.history || [];
  const labels = hist.map(h => new Date(h.t*1000).toLocaleTimeString());
  const cpus   = hist.map(h => h.cpu);
  const mems   = hist.map(h => h.mem);
  pushChart(computeChart, labels, cpus, mems);

  // db size pills
  const dbEl = document.getElementById('db-stats');
  const sizes = c.db_sizes_kb || {};
  dbEl.innerHTML = Object.entries(sizes).map(([k,v]) => `
    <div class="stat-pill">
      <div class="label">${k}.db</div>
      <div class="val">${v} KB</div>
    </div>`).join('');
}
</script>
</body>
</html>"""
