"""Orchestra Finance — brand page and full finance app."""

from __future__ import annotations

FINANCE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Orchestra Finance</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.hero{padding:80px 40px;text-align:center;background:linear-gradient(135deg,#0d1117 0%,#1a2035 50%,#0d1117 100%)}
.hero h1{font-size:3rem;font-weight:800;color:#fff;margin-bottom:1rem}
.hero h1 span{color:#34d399}
.hero p{font-size:1.1rem;color:#8b949e;max-width:600px;margin:0 auto 2rem}
.badge{display:inline-block;background:rgba(52,211,153,.12);color:#34d399;border:1px solid rgba(52,211,153,.3);padding:.3rem .8rem;border-radius:20px;font-size:.8rem;font-weight:600;margin-bottom:1.5rem}
.cta{display:inline-block;background:linear-gradient(135deg,#34d399,#4f8cff);color:#fff;padding:.9rem 2.5rem;border-radius:10px;font-size:1rem;font-weight:700;text-decoration:none}
.features{max-width:1100px;margin:0 auto;padding:60px 40px}
.features h2{text-align:center;font-size:1.8rem;font-weight:700;color:#fff;margin-bottom:2.5rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1.5rem}
.card{background:#161b22;border:1px solid #21262d;border-radius:12px;padding:1.5rem}
.card-icon{font-size:2rem;margin-bottom:.75rem}
.card h3{font-size:1rem;font-weight:700;color:#fff;margin-bottom:.5rem}
.card p{font-size:.875rem;color:#8b949e;line-height:1.6}
</style>
</head>
<body>
<div class="hero">
  <div class="badge">📈 Hedge Fund & PE Grade</div>
  <h1>Finance — <span>Built for Serious Investors</span></h1>
  <p>Portfolio tracking, deal flow management, market data, Monte Carlo simulation, and an AI CFO — all running locally with no data leaving your machine.</p>
  <a href="/finance/app" class="cta">Open Finance App →</a>
</div>
<div class="features">
  <h2>Everything a Fund Needs</h2>
  <div class="grid">
    <div class="card"><div class="card-icon">📊</div><h3>Portfolio Tracker</h3><p>Track positions with live prices, unrealized P&L, cost basis, sector allocation, and total portfolio value in real time.</p></div>
    <div class="card"><div class="card-icon">📡</div><h3>Live Market Data</h3><p>Real-time quotes, historical charts, market indices, sector movers, and financial news — all from public data sources.</p></div>
    <div class="card"><div class="card-icon">🎯</div><h3>Deal Flow (PE)</h3><p>Manage your deal pipeline from sourcing through close. Track stage, size, sector, EV multiples, and next steps.</p></div>
    <div class="card"><div class="card-icon">🎲</div><h3>Monte Carlo & Risk</h3><p>Run Monte Carlo simulations, calculate VaR, Sharpe ratio, and scenario analysis on any financial statement.</p></div>
    <div class="card"><div class="card-icon">🤖</div><h3>AI CFO Chat</h3><p>Ask questions about your portfolio, get instant financial analysis, risk assessment, and investment insights. Works without an API key.</p></div>
    <div class="card"><div class="card-icon">🔒</div><h3>Local-First Security</h3><p>All data stored locally. No cloud uploads. Your LP data, deal terms, and portfolio positions never leave your machine.</p></div>
  </div>
</div>
</body>
</html>"""


FINANCE_APP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Orchestra Finance</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0d1117;color:#c9d1d9;height:100vh;display:flex;flex-direction:column}
.hdr{background:#161b22;border-bottom:1px solid #21262d;padding:.75rem 1.5rem;display:flex;align-items:center;gap:1rem;flex-shrink:0}
.hdr-title{font-weight:700;font-size:1rem;color:#34d399}
.hdr-back{background:none;border:1px solid #30363d;color:#8b949e;padding:.3rem .8rem;border-radius:6px;font-size:.8rem;cursor:pointer;text-decoration:none}
.hdr-back:hover{background:#21262d}
.tabs{display:flex;border-bottom:1px solid #21262d;background:#161b22;flex-shrink:0;overflow-x:auto}
.tab{padding:.75rem 1.25rem;font-size:.85rem;font-weight:500;color:#8b949e;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap;transition:all .15s}
.tab:hover{color:#c9d1d9}
.tab.active{color:#34d399;border-bottom-color:#34d399}
.content{flex:1;overflow:auto;padding:1.5rem}
.card{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:1.25rem;margin-bottom:1rem}
.card-title{font-weight:700;font-size:.9rem;color:#fff;margin-bottom:1rem}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem;margin-bottom:1.5rem}
.kpi{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:1rem}
.kpi-val{font-size:1.6rem;font-weight:700;color:#34d399}
.kpi-lbl{font-size:.75rem;color:#8b949e;margin-top:.2rem}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th{text-align:left;padding:.6rem .75rem;color:#8b949e;font-weight:500;font-size:.78rem;border-bottom:1px solid #21262d}
td{padding:.6rem .75rem;border-bottom:1px solid #161b22;vertical-align:middle}
tr:hover td{background:#1c2128}
.pos{color:#3fb950}
.neg{color:#f85149}
.badge{display:inline-block;padding:.15rem .55rem;border-radius:4px;font-size:.72rem;font-weight:600}
.badge-sourcing{background:rgba(139,148,158,.1);color:#8b949e}
.badge-review{background:rgba(88,166,255,.15);color:#58a6ff}
.badge-diligence{background:rgba(240,136,62,.15);color:#f0883e}
.badge-loi{background:rgba(167,139,250,.15);color:#a78bfa}
.badge-closed{background:rgba(56,189,78,.15);color:#3fb950}
.badge-passed{background:rgba(248,81,73,.12);color:#f85149}
.actions{display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:1.25rem;align-items:center}
.search-box{background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;padding:.45rem .75rem;font-size:.85rem}
.search-box:focus{outline:none;border-color:#34d399}
.btn{padding:.5rem 1.1rem;border-radius:6px;font-size:.85rem;font-weight:600;cursor:pointer;border:none;transition:opacity .15s}
.btn:hover{opacity:.85}
.btn-primary{background:#34d399;color:#0d1117}
.btn-secondary{background:#21262d;color:#c9d1d9;border:1px solid #30363d}
.btn-danger{background:rgba(248,81,73,.15);color:#f85149;border:1px solid rgba(248,81,73,.3)}
.btn-sm{padding:.3rem .7rem;font-size:.78rem}
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:100;align-items:center;justify-content:center}
.modal-overlay.open{display:flex}
.modal{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:1.5rem;width:min(580px,95vw);max-height:85vh;overflow-y:auto}
.modal-title{font-weight:700;font-size:1rem;color:#fff;margin-bottom:1.25rem;display:flex;justify-content:space-between;align-items:center}
.close-btn{background:none;border:none;color:#8b949e;cursor:pointer;font-size:1.1rem}
.form-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem;margin-bottom:1rem}
.field label{display:block;font-size:.78rem;color:#8b949e;margin-bottom:.3rem}
input,select,textarea{width:100%;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;padding:.5rem .75rem;font-size:.875rem;font-family:inherit}
input:focus,select:focus,textarea:focus{outline:none;border-color:#34d399}
textarea{resize:vertical;min-height:80px}
.empty{text-align:center;padding:3rem;color:#8b949e}
.empty-icon{font-size:2.5rem;margin-bottom:.75rem}
/* Chat */
.chat-wrap{display:flex;flex-direction:column;height:calc(100vh - 200px)}
.chat-msgs{flex:1;overflow-y:auto;padding:.5rem 0;display:flex;flex-direction:column;gap:1rem}
.msg{max-width:80%;padding:.75rem 1rem;border-radius:10px;font-size:.875rem;line-height:1.6;white-space:pre-wrap}
.msg.user{background:#1f2d3d;color:#c9d1d9;align-self:flex-end;border-bottom-right-radius:3px}
.msg.ai{background:#161b22;border:1px solid #21262d;color:#c9d1d9;align-self:flex-start;border-bottom-left-radius:3px}
.chat-input-row{display:flex;gap:.5rem;margin-top:1rem}
.chat-input{flex:1;background:#0d1117;border:1px solid #30363d;border-radius:8px;color:#c9d1d9;padding:.65rem 1rem;font-size:.875rem;font-family:inherit;resize:none}
.chat-input:focus{outline:none;border-color:#34d399}
/* Ticker badge */
.ticker{font-family:monospace;font-weight:700;color:#58a6ff;font-size:.9rem}
.change-pos{color:#3fb950}
.change-neg{color:#f85149}
</style>
</head>
<body>

<div class="hdr">
  <a href="/" class="hdr-back">← Orchestra</a>
  <div class="hdr-title">📈 Finance</div>
  <div style="margin-left:auto;font-size:.78rem;color:#8b949e" id="hdr-stats">Loading…</div>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('portfolio')">Portfolio</div>
  <div class="tab" onclick="switchTab('markets')">Markets</div>
  <div class="tab" onclick="switchTab('deals')">Deal Flow</div>
  <div class="tab" onclick="switchTab('analytics')">Analytics</div>
  <div class="tab" onclick="switchTab('chat')">CFO Chat</div>
</div>

<div class="content" id="content">
  <div class="empty"><div class="empty-icon">📈</div><p>Loading…</p></div>
</div>

<!-- Position Modal -->
<div class="modal-overlay" id="pos-modal">
  <div class="modal">
    <div class="modal-title">Add Position <button class="close-btn" onclick="closePosModal()">✕</button></div>
    <div class="form-row">
      <div class="field"><label>Ticker *</label><input id="p-ticker" placeholder="AAPL" style="text-transform:uppercase"></div>
      <div class="field"><label>Name</label><input id="p-name" placeholder="Apple Inc."></div>
    </div>
    <div class="form-row">
      <div class="field"><label>Shares *</label><input id="p-shares" type="number" min="0" step="0.01" placeholder="100"></div>
      <div class="field"><label>Avg Cost ($/share) *</label><input id="p-cost" type="number" min="0" step="0.01" placeholder="150.00"></div>
    </div>
    <div class="form-row">
      <div class="field"><label>Asset Class</label>
        <select id="p-class">
          <option value="equity">Equity</option><option value="etf">ETF</option>
          <option value="bond">Bond</option><option value="crypto">Crypto</option>
          <option value="commodity">Commodity</option><option value="cash">Cash</option>
          <option value="other">Other</option>
        </select>
      </div>
      <div class="field"><label>Sector</label><input id="p-sector" placeholder="Technology"></div>
    </div>
    <div style="display:flex;gap:.75rem;justify-content:flex-end;margin-top:.5rem">
      <button class="btn btn-secondary" onclick="closePosModal()">Cancel</button>
      <button class="btn btn-primary" onclick="savePosition()">Add Position</button>
    </div>
  </div>
</div>

<!-- Deal Modal -->
<div class="modal-overlay" id="deal-modal">
  <div class="modal">
    <div class="modal-title"><span id="deal-modal-title">New Deal</span> <button class="close-btn" onclick="closeDealModal()">✕</button></div>
    <div class="form-row">
      <div class="field"><label>Company *</label><input id="d-company" placeholder="Acme Corp"></div>
      <div class="field"><label>Sector</label><input id="d-sector" placeholder="SaaS / B2B"></div>
    </div>
    <div class="form-row">
      <div class="field"><label>Stage</label>
        <select id="d-stage">
          <option value="sourcing">Sourcing</option>
          <option value="review">Initial Review</option>
          <option value="diligence">Due Diligence</option>
          <option value="loi">LOI / Term Sheet</option>
          <option value="closed">Closed</option>
          <option value="passed">Passed</option>
        </select>
      </div>
      <div class="field"><label>Deal Size ($M)</label><input id="d-size" type="number" min="0" step="0.1" placeholder="25.0"></div>
      <div class="field"><label>EV/EBITDA Multiple</label><input id="d-ev" type="number" min="0" step="0.1" placeholder="8.5"></div>
    </div>
    <div class="form-row">
      <div class="field"><label>Source</label><input id="d-source" placeholder="Banker / Proprietary / Network"></div>
      <div class="field"><label>Deal Lead</label><input id="d-lead" placeholder="Name"></div>
    </div>
    <div class="field" style="margin-bottom:.75rem"><label>Description</label><textarea id="d-desc" rows="2"></textarea></div>
    <div class="form-row">
      <div class="field"><label>Next Step</label><input id="d-nextstep" placeholder="Management call"></div>
      <div class="field"><label>Next Step Date</label><input id="d-nextdate" type="date"></div>
    </div>
    <div style="display:flex;gap:.75rem;justify-content:flex-end;margin-top:.5rem">
      <button class="btn btn-secondary" onclick="closeDealModal()">Cancel</button>
      <button class="btn btn-primary" onclick="saveDeal()">Save Deal</button>
    </div>
  </div>
</div>

<!-- Portfolio Create Modal -->
<div class="modal-overlay" id="port-modal">
  <div class="modal">
    <div class="modal-title">New Portfolio <button class="close-btn" onclick="document.getElementById('port-modal').classList.remove('open')">✕</button></div>
    <div class="field" style="margin-bottom:.75rem"><label>Portfolio Name *</label><input id="port-name" placeholder="Main Fund / Growth Portfolio"></div>
    <div class="field" style="margin-bottom:1rem"><label>Benchmark Ticker</label><input id="port-bench" placeholder="SPY" value="SPY"></div>
    <div style="display:flex;gap:.75rem;justify-content:flex-end">
      <button class="btn btn-secondary" onclick="document.getElementById('port-modal').classList.remove('open')">Cancel</button>
      <button class="btn btn-primary" onclick="savePortfolio()">Create</button>
    </div>
  </div>
</div>

<script>
let _tab = 'portfolio';
let _portfolios = [], _activePort = null, _positions = [], _deals = [];
let _prices = {}, _priceLoading = new Set();
let _editDealId = null;
let _dealStageFilter = '', _dealStatusFilter = 'active';

function _llm() {
  return {
    provider: localStorage.getItem('ca_provider') || 'anthropic',
    model: localStorage.getItem('ca_model') || 'claude-opus-4-7',
    api_key: localStorage.getItem('ca_api_key') || ''
  };
}

async function api(path, opts={}) {
  const r = await fetch(path, {headers:{'Content-Type':'application/json'}, ...opts});
  if (!r.ok) { const e = await r.json().catch(()=>({})); throw new Error(e.detail||r.statusText); }
  return r.json();
}

function fmt$(n,dec=2) { return '$'+(parseFloat(n)||0).toLocaleString('en-US',{minimumFractionDigits:dec,maximumFractionDigits:dec}); }
function fmtPct(n) { return (parseFloat(n)||0).toFixed(2)+'%'; }
function clr(n) { return parseFloat(n)>=0?'pos':'neg'; }
function fmtDate(d) { return d?d.slice(0,10):'—'; }

async function init() {
  _portfolios = await api('/api/finance/portfolios').catch(()=>[]);
  _deals = await api('/api/finance/deals').catch(()=>[]);
  if (_portfolios.length) {
    _activePort = _portfolios[0];
    _positions = await api(`/api/finance/portfolios/${_activePort.id}/positions`).catch(()=>[]);
  }
  updateHeader();
  switchTab('portfolio');
}

function updateHeader() {
  const total = _positions.reduce((s,p)=>s + p.shares*((_prices[p.ticker]?.price)||p.avg_cost), 0);
  const cost = _positions.reduce((s,p)=>s + p.shares*p.avg_cost, 0);
  const pnl = total - cost;
  document.getElementById('hdr-stats').textContent =
    _activePort ? `${_activePort.name} · ${fmt$(total)} · P&L ${pnl>=0?'+':''}${fmt$(pnl)}` : 'No portfolio';
}

function switchTab(tab) {
  _tab = tab;
  document.querySelectorAll('.tab').forEach((el,i)=>{
    el.classList.toggle('active', ['portfolio','markets','deals','analytics','chat'][i]===tab);
  });
  renderTab();
}

function renderTab() {
  const c = document.getElementById('content');
  if (_tab==='portfolio') renderPortfolio(c);
  else if (_tab==='markets') renderMarkets(c);
  else if (_tab==='deals') renderDeals(c);
  else if (_tab==='analytics') renderAnalytics(c);
  else if (_tab==='chat') renderChat(c);
}

// ── Portfolio ──────────────────────────────────────────────────────────────────
function renderPortfolio(c) {
  const positions = _positions;
  const totalCost = positions.reduce((s,p)=>s+p.shares*p.avg_cost,0);
  let totalVal = 0, totalPnl = 0;
  positions.forEach(p=>{
    const price = (_prices[p.ticker]?.price) || p.avg_cost;
    totalVal += p.shares * price;
  });
  totalPnl = totalVal - totalCost;
  const pnlPct = totalCost ? (totalPnl/totalCost*100) : 0;

  const portSel = _portfolios.length > 1
    ? `<select class="search-box" onchange="switchPortfolio(this.value)" style="max-width:200px">
        ${_portfolios.map(p=>`<option value="${p.id}" ${p.id===(_activePort?.id||'')?'selected':''}>${p.name}</option>`).join('')}
       </select>` : (_activePort?`<span style="color:#fff;font-weight:600">${_activePort.name}</span>`:'');

  c.innerHTML = `
    <div class="kpi-grid">
      <div class="kpi"><div class="kpi-val">${fmt$(totalVal)}</div><div class="kpi-lbl">Total Value</div></div>
      <div class="kpi"><div class="kpi-val">${fmt$(totalCost)}</div><div class="kpi-lbl">Cost Basis</div></div>
      <div class="kpi"><div class="kpi-val ${clr(totalPnl)}">${totalPnl>=0?'+':''}${fmt$(totalPnl)}</div><div class="kpi-lbl">Unrealized P&L</div></div>
      <div class="kpi"><div class="kpi-val ${clr(pnlPct)}">${pnlPct>=0?'+':''}${fmtPct(pnlPct)}</div><div class="kpi-lbl">Total Return</div></div>
      <div class="kpi"><div class="kpi-val">${positions.length}</div><div class="kpi-lbl">Positions</div></div>
    </div>
    <div class="actions">
      ${portSel}
      <button class="btn btn-secondary btn-sm" onclick="document.getElementById('port-modal').classList.add('open')">+ Portfolio</button>
      <button class="btn btn-primary" onclick="openPosModal()" ${!_activePort?'disabled':''}>+ Position</button>
      <button class="btn btn-secondary btn-sm" onclick="refreshPrices()" title="Refresh live prices">↺ Prices</button>
    </div>
    ${positions.length===0
      ? `<div class="empty"><div class="empty-icon">📊</div><p>No positions yet.<br>${_activePort?'Click <strong>+ Position</strong> to add your first holding.':`<a href="#" onclick="document.getElementById('port-modal').classList.add('open')" style="color:#34d399">Create a portfolio first →</a>`}</p></div>`
      : `<div class="card"><table>
          <thead><tr><th>Ticker</th><th>Name</th><th>Class</th><th>Shares</th><th>Avg Cost</th><th>Price</th><th>Value</th><th>P&L</th><th>Return</th><th>Weight</th><th></th></tr></thead>
          <tbody>${positions.map(p=>{
            const price = (_prices[p.ticker]?.price) || null;
            const val = price ? p.shares * price : p.shares * p.avg_cost;
            const pnl = price ? p.shares*(price-p.avg_cost) : 0;
            const ret = p.avg_cost ? ((price||p.avg_cost)-p.avg_cost)/p.avg_cost*100 : 0;
            const wt = totalVal ? val/totalVal*100 : 0;
            return `<tr>
              <td class="ticker">${p.ticker}</td>
              <td style="color:#8b949e;font-size:.8rem">${p.name||'—'}</td>
              <td><span style="font-size:.75rem;color:#8b949e">${p.asset_class}</span></td>
              <td>${parseFloat(p.shares).toLocaleString()}</td>
              <td>${fmt$(p.avg_cost)}</td>
              <td>${price?fmt$(price):'<span style="color:#8b949e">—</span>'}</td>
              <td style="font-weight:600">${fmt$(val)}</td>
              <td class="${clr(pnl)}">${price?(pnl>=0?'+':'')+fmt$(pnl):'—'}</td>
              <td class="${clr(ret)}">${price?(ret>=0?'+':'')+fmtPct(ret):'—'}</td>
              <td style="color:#8b949e">${fmtPct(wt)}</td>
              <td><button class="btn btn-danger btn-sm" onclick="removePosition('${p.id}')">✕</button></td>
            </tr>`;
          }).join('')}</tbody>
        </table></div>`}
  `;
  refreshPrices();
}

async function switchPortfolio(id) {
  _activePort = _portfolios.find(p=>p.id===id);
  _positions = await api(`/api/finance/portfolios/${id}/positions`).catch(()=>[]);
  _prices = {};
  renderTab(); updateHeader();
}

async function refreshPrices() {
  const tickers = [...new Set(_positions.map(p=>p.ticker))].filter(t=>!_priceLoading.has(t));
  if (!tickers.length) return;
  tickers.forEach(t=>_priceLoading.add(t));
  try {
    const data = await api(`/api/finance/market/batch?symbols=${tickers.join(',')}`).catch(()=>({quotes:[]}));
    (data.quotes||[]).forEach(q=>{ if(q.symbol) _prices[q.symbol]=q; });
    tickers.forEach(t=>_priceLoading.delete(t));
    if (_tab==='portfolio') renderTab();
    updateHeader();
  } catch(e) { tickers.forEach(t=>_priceLoading.delete(t)); }
}

function openPosModal() { document.getElementById('pos-modal').classList.add('open'); }
function closePosModal() { document.getElementById('pos-modal').classList.remove('open'); }

async function savePosition() {
  const ticker = document.getElementById('p-ticker').value.trim().toUpperCase();
  const shares = parseFloat(document.getElementById('p-shares').value);
  const cost = parseFloat(document.getElementById('p-cost').value);
  if (!ticker||!shares||!cost) { alert('Ticker, shares, and cost are required.'); return; }
  try {
    await api(`/api/finance/portfolios/${_activePort.id}/positions`, {method:'POST', body:JSON.stringify({
      ticker, shares, avg_cost:cost,
      name: document.getElementById('p-name').value,
      asset_class: document.getElementById('p-class').value,
      sector: document.getElementById('p-sector').value,
    })});
    _positions = await api(`/api/finance/portfolios/${_activePort.id}/positions`);
    closePosModal(); renderTab(); updateHeader();
  } catch(e) { alert('Error: '+e.message); }
}

async function removePosition(posId) {
  if (!confirm('Remove this position?')) return;
  await api(`/api/finance/portfolios/${_activePort.id}/positions/${posId}`, {method:'DELETE'});
  _positions = _positions.filter(p=>p.id!==posId);
  renderTab(); updateHeader();
}

async function savePortfolio() {
  const name = document.getElementById('port-name').value.trim();
  if (!name) { alert('Name required.'); return; }
  const p = await api('/api/finance/portfolios', {method:'POST', body:JSON.stringify({name, benchmark:document.getElementById('port-bench').value||'SPY'})});
  _portfolios.push(p); _activePort = p; _positions = [];
  document.getElementById('port-modal').classList.remove('open');
  renderTab();
}

// ── Markets ────────────────────────────────────────────────────────────────────
function renderMarkets(c) {
  c.innerHTML = `
    <div class="actions">
      <input class="search-box" id="mkt-search" placeholder="Search ticker (AAPL, TSLA…)" style="max-width:250px" onkeydown="if(event.key==='Enter')lookupTicker()">
      <button class="btn btn-primary" onclick="lookupTicker()">Look Up</button>
    </div>
    <div id="mkt-quote"></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;margin-top:1rem">
      <div class="card">
        <div class="card-title">📊 Indices</div>
        <div id="mkt-indices"><div style="color:#8b949e;font-size:.85rem">Loading…</div></div>
      </div>
      <div class="card">
        <div class="card-title">🔥 Movers</div>
        <div style="display:flex;gap:.5rem;margin-bottom:.75rem">
          <button class="btn btn-sm btn-secondary" onclick="loadMovers('gainers')">Gainers</button>
          <button class="btn btn-sm btn-secondary" onclick="loadMovers('losers')">Losers</button>
          <button class="btn btn-sm btn-secondary" onclick="loadMovers('active')">Most Active</button>
        </div>
        <div id="mkt-movers"><div style="color:#8b949e;font-size:.85rem">Click a button above.</div></div>
      </div>
    </div>
    <div class="card" style="margin-top:1rem">
      <div class="card-title">📰 Market News</div>
      <div id="mkt-news"><div style="color:#8b949e;font-size:.85rem">Loading…</div></div>
    </div>
    <div class="card" style="margin-top:1rem">
      <div class="card-title">📌 Trader Resources</div>
      <div style="display:flex;flex-direction:column;gap:.75rem">
        <div style="display:flex;align-items:flex-start;gap:.75rem;padding:.6rem;background:#0d1117;border-radius:6px;border:1px solid #21262d">
          <div style="font-size:1.5rem;flex-shrink:0">📈</div>
          <div>
            <div style="font-weight:700;color:#fff;font-size:.9rem">Adam Mancini</div>
            <div style="font-size:.8rem;color:#8b949e;margin:.2rem 0">Technical analyst — S&amp;P 500 futures, key support/resistance levels, and swing trade setups. Dad's pick.</div>
            <a href="https://twitter.com/AdamMancini4" target="_blank" rel="noopener" style="font-size:.78rem;color:#34d399;text-decoration:none">@AdamMancini4 on X →</a>
          </div>
        </div>
        <div style="display:flex;align-items:flex-start;gap:.75rem;padding:.6rem;background:#0d1117;border-radius:6px;border:1px solid #21262d">
          <div style="font-size:1.5rem;flex-shrink:0">🧠</div>
          <div>
            <div style="font-weight:700;color:#fff;font-size:.9rem">Tom Hougaard</div>
            <div style="font-size:.8rem;color:#8b949e;margin:.2rem 0">Professional trader (FTSE, DAX, S&amp;P) known for live trading transparency and trading psychology. Author of <em style="color:#c9d1d9">Best Loser Wins</em> — mindset over strategy.</div>
            <a href="https://twitter.com/TomHougaard" target="_blank" rel="noopener" style="font-size:.78rem;color:#34d399;text-decoration:none">@TomHougaard on X →</a>
          </div>
        </div>
      </div>
    </div>
  `;
  loadIndices(); loadNews();
}

async function lookupTicker() {
  const sym = document.getElementById('mkt-search').value.trim().toUpperCase();
  if (!sym) return;
  const el = document.getElementById('mkt-quote');
  el.innerHTML = `<div style="color:#8b949e;padding:1rem">Loading ${sym}…</div>`;
  try {
    const q = await api(`/api/finance/market/quote/${sym}`);
    const chg = q.change || 0; const chgPct = q.change_pct || 0;
    el.innerHTML = `<div class="card">
      <div style="display:flex;align-items:baseline;gap:1rem;flex-wrap:wrap">
        <span class="ticker" style="font-size:1.4rem">${sym}</span>
        <span style="font-size:1rem;color:#8b949e">${q.name||''}</span>
        <span style="font-size:1.8rem;font-weight:700">${fmt$(q.price)}</span>
        <span class="${clr(chg)}" style="font-size:1rem">${chg>=0?'+':''}${fmt$(chg)} (${chg>=0?'+':''}${fmtPct(chgPct)})</span>
      </div>
      <div style="display:flex;gap:2rem;margin-top:.75rem;flex-wrap:wrap;font-size:.82rem;color:#8b949e">
        <span>Open: ${fmt$(q.open)}</span><span>High: ${fmt$(q.high)}</span>
        <span>Low: ${fmt$(q.low)}</span><span>Volume: ${(q.volume||0).toLocaleString()}</span>
        ${q.market_cap?`<span>Mkt Cap: ${fmt$(q.market_cap/1e9,1)}B</span>`:''}
        ${q.pe_ratio?`<span>P/E: ${q.pe_ratio}</span>`:''}
      </div>
    </div>`;
  } catch(e) { el.innerHTML = `<div style="color:#f85149;padding:.75rem">Not found: ${sym}</div>`; }
}

async function loadIndices() {
  try {
    const data = await api('/api/finance/market/indices');
    const el = document.getElementById('mkt-indices');
    if (!el) return;
    const indices = data.indices || [];
    if (!indices.length) { el.innerHTML='<div style="color:#8b949e;font-size:.85rem">Unavailable.</div>'; return; }
    el.innerHTML = '<table><tbody>' + indices.map(i=>`<tr>
      <td class="ticker">${i.symbol}</td>
      <td style="color:#8b949e;font-size:.8rem">${i.name||''}</td>
      <td style="font-weight:600">${fmt$(i.price)}</td>
      <td class="${clr(i.change_pct)}">${(i.change_pct>=0?'+':'')+fmtPct(i.change_pct)}</td>
    </tr>`).join('') + '</tbody></table>';
  } catch(e) {}
}

async function loadMovers(dir) {
  const el = document.getElementById('mkt-movers');
  el.innerHTML = '<div style="color:#8b949e;font-size:.85rem">Loading…</div>';
  try {
    const data = await api(`/api/finance/market/movers?direction=${dir}`);
    const movers = data.movers || [];
    el.innerHTML = movers.length ? '<table><tbody>' + movers.slice(0,8).map(m=>`<tr>
      <td class="ticker">${m.symbol}</td>
      <td style="font-size:.78rem;color:#8b949e;max-width:120px;overflow:hidden;text-overflow:ellipsis">${m.name||''}</td>
      <td>${fmt$(m.price)}</td>
      <td class="${clr(m.change_pct)}">${(m.change_pct>=0?'+':'')+fmtPct(m.change_pct)}</td>
    </tr>`).join('') + '</tbody></table>' : '<div style="color:#8b949e;font-size:.85rem">No data.</div>';
  } catch(e) { el.innerHTML='<div style="color:#8b949e;font-size:.85rem">Unavailable.</div>'; }
}

async function loadNews() {
  try {
    const data = await api('/api/finance/market/news?limit=8');
    const el = document.getElementById('mkt-news');
    if (!el) return;
    const articles = data.articles || [];
    el.innerHTML = articles.map(a=>`
      <div style="padding:.6rem 0;border-bottom:1px solid #21262d">
        <a href="${a.url||'#'}" target="_blank" rel="noopener" style="color:#c9d1d9;text-decoration:none;font-size:.875rem;font-weight:500;display:block;margin-bottom:.2rem">${a.title||'Untitled'}</a>
        <span style="color:#8b949e;font-size:.75rem">${a.source||''}${a.published_at?' · '+new Date(a.published_at*1000).toLocaleDateString():''}</span>
      </div>
    `).join('') || '<div style="color:#8b949e;font-size:.85rem">No news available.</div>';
  } catch(e) {}
}

// ── Deals ──────────────────────────────────────────────────────────────────────
const STAGES = ['sourcing','review','diligence','loi','closed','passed'];
const STAGE_LABELS = {sourcing:'Sourcing',review:'Initial Review',diligence:'Due Diligence',loi:'LOI / Term Sheet',closed:'Closed',passed:'Passed'};

function stageBadge(s) {
  return `<span class="badge badge-${s}">${STAGE_LABELS[s]||s}</span>`;
}

function renderDeals(c) {
  refreshDeals();
}

async function refreshDeals() {
  const c = document.getElementById('content');
  if (!c || _tab !== 'deals') return;
  const params = new URLSearchParams();
  if (_dealStageFilter) params.set('stage', _dealStageFilter);
  if (_dealStatusFilter) params.set('status', _dealStatusFilter);
  const [deals, analytics] = await Promise.all([
    api('/api/finance/deals?'+params.toString()).catch(()=>[]),
    api('/api/finance/deals/analytics').catch(()=>({})),
  ]);

  c.innerHTML = `
    <div class="kpi-grid" style="grid-template-columns:repeat(auto-fit,minmax(120px,1fr));margin-bottom:1rem">
      <div class="kpi"><div class="kpi-val">${analytics.total_active||0}</div><div class="kpi-lbl">Active Deals</div></div>
      <div class="kpi"><div class="kpi-val">${fmt$(analytics.total_pipeline_m||0,1)}M</div><div class="kpi-lbl">Pipeline Size</div></div>
      <div class="kpi"><div class="kpi-val" style="color:#3fb950">${fmt$(analytics.closed_size_m||0,1)}M</div><div class="kpi-lbl">Closed</div></div>
      ${STAGES.slice(0,4).map(s=>`<div class="kpi"><div class="kpi-val">${analytics.by_stage?.[s]||0}</div><div class="kpi-lbl">${STAGE_LABELS[s]}</div></div>`).join('')}
    </div>
    <div class="actions">
      <select class="search-box" style="max-width:160px" onchange="_dealStageFilter=this.value;refreshDeals()">
        <option value="">All Stages</option>
        ${STAGES.map(s=>`<option value="${s}" ${_dealStageFilter===s?'selected':''}>${STAGE_LABELS[s]}</option>`).join('')}
      </select>
      <select class="search-box" style="max-width:130px" onchange="_dealStatusFilter=this.value;refreshDeals()">
        <option value="active" ${_dealStatusFilter==='active'?'selected':''}>Active</option>
        <option value="" ${_dealStatusFilter===''?'selected':''}>All</option>
      </select>
      <button class="btn btn-primary" onclick="openDealModal()">+ New Deal</button>
    </div>
    ${deals.length===0
      ? '<div class="empty"><div class="empty-icon">🎯</div><p>No deals in pipeline.</p></div>'
      : `<div class="card"><table>
          <thead><tr><th>Company</th><th>Sector</th><th>Stage</th><th>Size ($M)</th><th>EV Mult</th><th>Source</th><th>Lead</th><th>Next Step</th><th>Date</th><th></th></tr></thead>
          <tbody>${deals.map(d=>`<tr>
            <td style="font-weight:600">${d.company}</td>
            <td style="color:#8b949e;font-size:.8rem">${d.sector||'—'}</td>
            <td>${stageBadge(d.stage)}</td>
            <td>${d.size_m?fmt$(d.size_m,1)+'M':'—'}</td>
            <td>${d.ev_multiple?d.ev_multiple.toFixed(1)+'x':'—'}</td>
            <td style="font-size:.8rem;color:#8b949e">${d.source||'—'}</td>
            <td style="font-size:.8rem">${d.lead||'—'}</td>
            <td style="font-size:.8rem;max-width:150px">${d.next_step||'—'}</td>
            <td style="font-size:.8rem;color:#8b949e">${fmtDate(d.next_step_date)}</td>
            <td style="display:flex;gap:.3rem">
              <button class="btn btn-secondary btn-sm" onclick="openDealModal('${d.id}')">Edit</button>
              <button class="btn btn-danger btn-sm" onclick="deleteDeal('${d.id}')">✕</button>
            </td>
          </tr>`).join('')}</tbody>
        </table></div>`}
  `;
}

function openDealModal(dealId) {
  _editDealId = dealId || null;
  document.getElementById('deal-modal-title').textContent = dealId ? 'Edit Deal' : 'New Deal';
  if (!dealId) {
    ['d-company','d-sector','d-size','d-ev','d-source','d-lead','d-desc','d-nextstep','d-nextdate'].forEach(id=>{ const el=document.getElementById(id); if(el) el.value=''; });
    document.getElementById('d-stage').value='sourcing';
  } else {
    api('/api/finance/deals').then(deals=>{
      const d = deals.find(x=>x.id===dealId);
      if (!d) return;
      document.getElementById('d-company').value = d.company;
      document.getElementById('d-sector').value = d.sector||'';
      document.getElementById('d-stage').value = d.stage;
      document.getElementById('d-size').value = d.size_m||'';
      document.getElementById('d-ev').value = d.ev_multiple||'';
      document.getElementById('d-source').value = d.source||'';
      document.getElementById('d-lead').value = d.lead||'';
      document.getElementById('d-desc').value = d.description||'';
      document.getElementById('d-nextstep').value = d.next_step||'';
      document.getElementById('d-nextdate').value = d.next_step_date||'';
    });
  }
  document.getElementById('deal-modal').classList.add('open');
}

function closeDealModal() { document.getElementById('deal-modal').classList.remove('open'); }

async function saveDeal() {
  const company = document.getElementById('d-company').value.trim();
  if (!company) { alert('Company name required.'); return; }
  const body = {
    company, sector: document.getElementById('d-sector').value,
    stage: document.getElementById('d-stage').value,
    size_m: parseFloat(document.getElementById('d-size').value)||0,
    ev_multiple: parseFloat(document.getElementById('d-ev').value)||0,
    source: document.getElementById('d-source').value,
    lead: document.getElementById('d-lead').value,
    description: document.getElementById('d-desc').value,
    next_step: document.getElementById('d-nextstep').value,
    next_step_date: document.getElementById('d-nextdate').value,
  };
  try {
    if (_editDealId) await api(`/api/finance/deals/${_editDealId}`, {method:'PATCH', body:JSON.stringify(body)});
    else await api('/api/finance/deals', {method:'POST', body:JSON.stringify(body)});
    closeDealModal();
    _deals = await api('/api/finance/deals').catch(()=>[]);
    if (_tab === 'deals') refreshDeals(); else renderTab();
  } catch(e) { alert('Error: '+e.message); }
}

async function deleteDeal(dealId) {
  if (!confirm('Remove this deal?')) return;
  await api(`/api/finance/deals/${dealId}`, {method:'DELETE'});
  refreshDeals();
}

// ── Analytics ──────────────────────────────────────────────────────────────────
function renderAnalytics(c) {
  c.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem">
      <div class="card">
        <div class="card-title">🎲 Monte Carlo Simulation</div>
        <div class="form-row">
          <div class="field"><label>Base Revenue ($)</label><input id="mc-rev" type="number" placeholder="1000000" value="1000000"></div>
          <div class="field"><label>Volatility (%)</label><input id="mc-vol" type="number" placeholder="15" value="15"></div>
        </div>
        <div class="form-row">
          <div class="field"><label>Months</label><input id="mc-steps" type="number" placeholder="12" value="12"></div>
          <div class="field"><label>Simulations</label><input id="mc-sims" type="number" placeholder="1000" value="1000"></div>
        </div>
        <button class="btn btn-primary" onclick="runMonteCarlo()">Run Simulation</button>
        <div id="mc-result" style="margin-top:1rem"></div>
      </div>
      <div class="card">
        <div class="card-title">📉 Portfolio Risk</div>
        <div class="form-row">
          <div class="field"><label>Portfolio Value ($)</label><input id="risk-val" type="number" placeholder="1000000" value="1000000"></div>
          <div class="field"><label>Annual Volatility (%)</label><input id="risk-vol" type="number" placeholder="20" value="20"></div>
        </div>
        <button class="btn btn-primary" onclick="runRisk()">Calculate Risk</button>
        <div id="risk-result" style="margin-top:1rem"></div>
      </div>
    </div>
    <div class="card" style="margin-top:1.5rem">
      <div class="card-title">📊 Revenue Forecast</div>
      <div class="form-row">
        <div class="field"><label>Historical Revenues (comma-separated)</label><input id="fc-hist" placeholder="500000,620000,710000,800000" value="500000,620000,710000,800000"></div>
        <div class="field"><label>Method</label><select id="fc-method"><option value="exponential">Exponential</option><option value="linear">Linear</option><option value="average">Average</option></select></div>
        <div class="field"><label>Periods to Forecast</label><input id="fc-horizon" type="number" value="3"></div>
      </div>
      <button class="btn btn-primary" onclick="runForecast()">Forecast</button>
      <div id="fc-result" style="margin-top:1rem"></div>
    </div>
  `;
}

async function runMonteCarlo() {
  const el = document.getElementById('mc-result');
  el.innerHTML = '<span style="color:#8b949e">Running…</span>';
  try {
    const data = await api('/api/finance/analytics/monte-carlo', {method:'POST', body:JSON.stringify({
      base_revenue: parseFloat(document.getElementById('mc-rev').value)||1e6,
      volatility: (parseFloat(document.getElementById('mc-vol').value)||15)/100,
      steps: parseInt(document.getElementById('mc-steps').value)||12,
      simulations: parseInt(document.getElementById('mc-sims').value)||1000,
    })});
    el.innerHTML = `<table><tbody>
      <tr><td style="color:#8b949e">P10 (Bear)</td><td class="neg">${fmt$(data.p10)}</td></tr>
      <tr><td style="color:#8b949e">P50 (Base)</td><td>${fmt$(data.p50)}</td></tr>
      <tr><td style="color:#8b949e">P90 (Bull)</td><td class="pos">${fmt$(data.p90)}</td></tr>
      <tr><td style="color:#8b949e">Mean</td><td>${fmt$(data.mean)}</td></tr>
      <tr><td style="color:#8b949e">Std Dev</td><td>${fmt$(data.std_dev)}</td></tr>
    </tbody></table>`;
  } catch(e) { el.innerHTML = `<span style="color:#f85149">Error: ${e.message}</span>`; }
}

async function runRisk() {
  const el = document.getElementById('risk-result');
  el.innerHTML = '<span style="color:#8b949e">Calculating…</span>';
  try {
    const data = await api('/api/finance/analytics/risk', {method:'POST', body:JSON.stringify({
      portfolio_value: parseFloat(document.getElementById('risk-val').value)||1e6,
      volatility: (parseFloat(document.getElementById('risk-vol').value)||20)/100,
    })});
    el.innerHTML = `<table><tbody>
      ${Object.entries(data).map(([k,v])=>`<tr><td style="color:#8b949e">${k.replace(/_/g,' ')}</td><td>${typeof v==='number'?fmt$(v):v}</td></tr>`).join('')}
    </tbody></table>`;
  } catch(e) { el.innerHTML = `<span style="color:#f85149">Error: ${e.message}</span>`; }
}

async function runForecast() {
  const el = document.getElementById('fc-result');
  el.innerHTML = '<span style="color:#8b949e">Forecasting…</span>';
  try {
    const hist = document.getElementById('fc-hist').value.split(',').map(Number).filter(Boolean);
    const data = await api('/api/finance/analytics/forecast', {method:'POST', body:JSON.stringify({
      historical: hist,
      method: document.getElementById('fc-method').value,
      horizon: parseInt(document.getElementById('fc-horizon').value)||3,
    })});
    const forecasts = data.forecast || data.forecasts || [];
    el.innerHTML = forecasts.length
      ? '<table><tbody>'+forecasts.map((v,i)=>`<tr><td style="color:#8b949e">Period +${i+1}</td><td class="pos">${fmt$(v)}</td></tr>`).join('')+'</tbody></table>'
      : `<pre style="font-size:.8rem;color:#c9d1d9">${JSON.stringify(data,null,2)}</pre>`;
  } catch(e) { el.innerHTML = `<span style="color:#f85149">Error: ${e.message}</span>`; }
}

// ── CFO Chat ───────────────────────────────────────────────────────────────────
let _chatHistory = [];

function renderChat(c) {
  c.innerHTML = `
    <div class="chat-wrap">
      <div class="chat-msgs" id="chat-msgs">
        <div class="msg ai">Hi! I'm your AI CFO. Ask me anything about your portfolio, deal flow, risk, valuation, or financial strategy. I'll give you direct, data-driven analysis.</div>
      </div>
      <div class="chat-input-row">
        <textarea class="chat-input" id="chat-input" rows="2" placeholder="Ask about your portfolio, analyze a deal, explain a risk metric…" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendChat()}"></textarea>
        <button class="btn btn-primary" onclick="sendChat()" id="chat-send">Send</button>
      </div>
    </div>
  `;
  _chatHistory.forEach(m=>appendMsg(m.role==='user'?'user':'ai', m.content));
}

function appendMsg(role, text) {
  const el = document.getElementById('chat-msgs');
  if (!el) return;
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.textContent = text;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const text = input?.value.trim();
  if (!text) return;
  input.value = '';
  document.getElementById('chat-send').disabled = true;
  appendMsg('user', text);

  // Build context from portfolio + deals
  const totalVal = _positions.reduce((s,p)=>s+p.shares*((_prices[p.ticker]?.price)||p.avg_cost),0);
  const context = {
    portfolio_value: totalVal,
    positions: _positions.slice(0,20).map(p=>({ticker:p.ticker,shares:p.shares,avg_cost:p.avg_cost,price:(_prices[p.ticker]?.price)||null})),
    active_deals: _deals.slice(0,10).map(d=>({company:d.company,stage:d.stage,size_m:d.size_m,sector:d.sector})),
  };

  _chatHistory.push({role:'user',content:text});

  try {
    const data = await api('/api/finance/brain/query', {method:'POST', body:JSON.stringify({
      prompt: text, context, ..._llm()
    })});
    const response = data.response || 'No response.';
    appendMsg('ai', response);
    _chatHistory.push({role:'assistant',content:response});
  } catch(e) {
    appendMsg('ai', 'Error: '+e.message);
  } finally {
    document.getElementById('chat-send').disabled = false;
  }
}

init();
</script>
</body>
</html>"""
