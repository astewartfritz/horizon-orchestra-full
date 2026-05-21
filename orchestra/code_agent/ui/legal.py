LEGAL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Orchestra Legal — Law Firm Management</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.hero{background:linear-gradient(135deg,#0d1117 0%,#1a1f2e 50%,#0d1117 100%);padding:80px 40px;text-align:center}
.hero h1{font-size:3rem;font-weight:800;color:#fff;margin-bottom:1rem}
.hero h1 span{color:#a78bfa}
.hero p{font-size:1.1rem;color:#8b949e;max-width:600px;margin:0 auto 2rem}
.badge{display:inline-block;background:rgba(167,139,250,.15);color:#a78bfa;border:1px solid rgba(167,139,250,.3);padding:.3rem .8rem;border-radius:20px;font-size:.8rem;font-weight:600;margin-bottom:1.5rem}
.cta-btn{display:inline-block;background:#a78bfa;color:#fff;padding:.9rem 2.5rem;border-radius:10px;font-size:1rem;font-weight:700;text-decoration:none;transition:opacity .2s}
.cta-btn:hover{opacity:.85}
.features{max-width:1100px;margin:0 auto;padding:60px 40px}
.features h2{text-align:center;font-size:1.8rem;font-weight:700;color:#fff;margin-bottom:2.5rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1.5rem}
.card{background:#161b22;border:1px solid #21262d;border-radius:12px;padding:1.5rem}
.card-icon{font-size:2rem;margin-bottom:.75rem}
.card h3{font-size:1rem;font-weight:700;color:#fff;margin-bottom:.5rem}
.card p{font-size:.875rem;color:#8b949e;line-height:1.6}
.privilege-bar{background:rgba(167,139,250,.08);border:1px solid rgba(167,139,250,.2);border-radius:12px;padding:1.5rem 2rem;max-width:800px;margin:0 auto 3rem;text-align:center}
.privilege-bar strong{color:#a78bfa}
</style>
</head>
<body>
<div class="hero">
  <div class="badge">⚖️ Legal Practice Management</div>
  <h1>Law Firm AI — <span>Built for Privacy</span></h1>
  <p>Manage matters, track time, draft documents, and bill clients — all running locally so client data stays protected by attorney-client privilege.</p>
  <a href="/legal/app" class="cta-btn">Open Legal App →</a>
</div>
<div class="features">
  <div class="privilege-bar">
    <strong>🔒 Attorney-Client Privilege by Design</strong> — All data stored locally on your machine. No cloud uploads, no third-party access. Client confidences stay confidential.
  </div>
  <h2>Everything a Small Firm Needs</h2>
  <div class="grid">
    <div class="card"><div class="card-icon">📁</div><h3>Matter Management</h3><p>Open matters for every practice area — litigation, corporate, estate planning, family law, IP, and more. Track status, deadlines, and opposing parties.</p></div>
    <div class="card"><div class="card-icon">⏱</div><h3>Time Tracking</h3><p>Log billable hours with UTBMS activity codes. Track time by matter, attorney, and date. See unbilled value at a glance.</p></div>
    <div class="card"><div class="card-icon">📄</div><h3>AI Document Drafter</h3><p>Generate NDAs, demand letters, retainer agreements, settlement agreements, motions, and 20+ other document types in seconds.</p></div>
    <div class="card"><div class="card-icon">💵</div><h3>Billing & Invoicing</h3><p>Bundle unbilled time into invoices. Track payment status. Support hourly, flat fee, contingency, and retainer arrangements.</p></div>
    <div class="card"><div class="card-icon">🏦</div><h3>Trust / IOLTA Ledger</h3><p>Track client trust account deposits and disbursements. Maintain running balances with full audit trail per matter.</p></div>
    <div class="card"><div class="card-icon">🧠</div><h3>Matter Analysis</h3><p>Get AI-powered strategic analysis: strengths, weaknesses, recommended next steps, research topics, and estimated timelines.</p></div>
  </div>
</div>
</body>
</html>"""


LEGAL_APP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Orchestra Legal</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0d1117;color:#c9d1d9;height:100vh;display:flex;flex-direction:column}
/* Header */
.hdr{background:#161b22;border-bottom:1px solid #21262d;padding:.75rem 1.5rem;display:flex;align-items:center;gap:1rem;flex-shrink:0}
.hdr-title{font-weight:700;font-size:1rem;color:#a78bfa;display:flex;align-items:center;gap:.4rem}
.hdr-back{background:none;border:1px solid #30363d;color:#8b949e;padding:.3rem .8rem;border-radius:6px;font-size:.8rem;cursor:pointer;text-decoration:none}
.hdr-back:hover{background:#21262d}
/* Tabs */
.tabs{display:flex;gap:0;border-bottom:1px solid #21262d;background:#161b22;flex-shrink:0;overflow-x:auto}
.tab{padding:.75rem 1.25rem;font-size:.85rem;font-weight:500;color:#8b949e;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap;transition:all .15s}
.tab:hover{color:#c9d1d9}
.tab.active{color:#a78bfa;border-bottom-color:#a78bfa}
/* Content */
.content{flex:1;overflow:auto;padding:1.5rem}
/* Cards / tables */
.card{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:1.25rem;margin-bottom:1rem}
.card-title{font-weight:700;font-size:.9rem;color:#fff;margin-bottom:1rem}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem;margin-bottom:1.5rem}
.kpi{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:1rem}
.kpi-val{font-size:1.8rem;font-weight:700;color:#a78bfa}
.kpi-lbl{font-size:.75rem;color:#8b949e;margin-top:.2rem}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th{text-align:left;padding:.6rem .75rem;color:#8b949e;font-weight:500;font-size:.78rem;border-bottom:1px solid #21262d}
td{padding:.6rem .75rem;border-bottom:1px solid #161b22;vertical-align:top}
tr:hover td{background:#1c2128}
.badge{display:inline-block;padding:.15rem .55rem;border-radius:4px;font-size:.72rem;font-weight:600}
.badge-open{background:rgba(56,189,78,.15);color:#3fb950}
.badge-closed{background:rgba(139,148,158,.1);color:#8b949e}
.badge-pending{background:rgba(240,136,62,.15);color:#f0883e}
.badge-inactive{background:rgba(139,148,158,.1);color:#8b949e}
.badge-draft{background:rgba(88,166,255,.15);color:#58a6ff}
.badge-sent{background:rgba(240,136,62,.15);color:#f0883e}
.badge-paid{background:rgba(56,189,78,.15);color:#3fb950}
.badge-overdue{background:rgba(248,81,73,.15);color:#f85149}
/* Forms */
.form-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:1rem}
.field label{display:block;font-size:.78rem;color:#8b949e;margin-bottom:.3rem}
input,select,textarea{width:100%;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;padding:.5rem .75rem;font-size:.875rem;font-family:inherit}
input:focus,select:focus,textarea:focus{outline:none;border-color:#a78bfa}
textarea{resize:vertical;min-height:100px}
.btn{padding:.5rem 1.1rem;border-radius:6px;font-size:.85rem;font-weight:600;cursor:pointer;border:none;transition:opacity .15s}
.btn:hover{opacity:.85}
.btn-primary{background:#a78bfa;color:#fff}
.btn-secondary{background:#21262d;color:#c9d1d9;border:1px solid #30363d}
.btn-danger{background:rgba(248,81,73,.15);color:#f85149;border:1px solid rgba(248,81,73,.3)}
.btn-sm{padding:.3rem .7rem;font-size:.78rem}
.actions{display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:1.25rem;align-items:center}
.search-box{flex:1;max-width:300px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;padding:.45rem .75rem;font-size:.85rem}
.search-box:focus{outline:none;border-color:#a78bfa}
/* Modal */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:100;align-items:center;justify-content:center}
.modal-overlay.open{display:flex}
.modal{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:1.5rem;width:min(680px,95vw);max-height:85vh;overflow-y:auto}
.modal-title{font-weight:700;font-size:1rem;color:#fff;margin-bottom:1.25rem;display:flex;justify-content:space-between;align-items:center}
.close-btn{background:none;border:none;color:#8b949e;cursor:pointer;font-size:1.1rem}
/* Document viewer */
.doc-content{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:1.25rem;white-space:pre-wrap;font-family:'Courier New',monospace;font-size:.82rem;line-height:1.7;color:#c9d1d9;max-height:50vh;overflow-y:auto}
/* Empty state */
.empty{text-align:center;padding:3rem;color:#8b949e}
.empty-icon{font-size:2.5rem;margin-bottom:.75rem}
/* Split layout for doc drafter */
.split{display:grid;grid-template-columns:380px 1fr;gap:1.5rem;height:calc(100vh - 180px)}
@media(max-width:900px){.split{grid-template-columns:1fr;height:auto}}
.panel{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:1.25rem;overflow-y:auto}
.trust-pos{color:#3fb950}
.trust-neg{color:#f85149}
</style>
</head>
<body>

<div class="hdr">
  <a href="/" class="hdr-back">← Orchestra</a>
  <div class="hdr-title">⚖️ Legal</div>
  <div style="margin-left:auto;font-size:.78rem;color:#8b949e" id="hdr-stats">Loading…</div>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('dashboard')">Dashboard</div>
  <div class="tab" onclick="switchTab('matters')">Matters</div>
  <div class="tab" onclick="switchTab('clients')">Clients</div>
  <div class="tab" onclick="switchTab('time')">Time</div>
  <div class="tab" onclick="switchTab('documents')">Documents</div>
  <div class="tab" onclick="switchTab('billing')">Billing</div>
</div>

<div class="content" id="content">
  <div class="empty"><div class="empty-icon">⚖️</div><p>Loading…</p></div>
</div>

<!-- Matter Modal -->
<div class="modal-overlay" id="matter-modal">
  <div class="modal">
    <div class="modal-title">
      <span id="matter-modal-title">New Matter</span>
      <button class="close-btn" onclick="closeMatterModal()">✕</button>
    </div>
    <div class="form-row">
      <div class="field"><label>Client *</label><select id="m-client-id"></select></div>
      <div class="field"><label>Matter Title *</label><input id="m-title" placeholder="e.g. Smith v. Jones — Contract Dispute"></div>
    </div>
    <div class="form-row">
      <div class="field"><label>Type</label>
        <select id="m-type">
          <option value="litigation">Litigation</option>
          <option value="corporate">Corporate</option>
          <option value="real_estate">Real Estate</option>
          <option value="estate_planning">Estate Planning</option>
          <option value="family">Family Law</option>
          <option value="criminal">Criminal</option>
          <option value="immigration">Immigration</option>
          <option value="employment">Employment</option>
          <option value="ip">Intellectual Property</option>
          <option value="bankruptcy">Bankruptcy</option>
          <option value="tax">Tax</option>
          <option value="other">Other</option>
        </select>
      </div>
      <div class="field"><label>Status</label>
        <select id="m-status">
          <option value="open">Open</option>
          <option value="pending">Pending</option>
          <option value="inactive">Inactive</option>
          <option value="closed">Closed</option>
        </select>
      </div>
      <div class="field"><label>Fee Arrangement</label>
        <select id="m-fee" onchange="updateFeeFields()">
          <option value="hourly">Hourly</option>
          <option value="flat_fee">Flat Fee</option>
          <option value="contingency">Contingency</option>
          <option value="retainer">Retainer</option>
          <option value="pro_bono">Pro Bono</option>
        </select>
      </div>
    </div>
    <div class="form-row" id="fee-fields">
      <div class="field"><label>Hourly Rate ($)</label><input id="m-rate" type="number" value="350"></div>
    </div>
    <div class="form-row">
      <div class="field"><label>Responsible Attorney</label><input id="m-attorney" placeholder="Name"></div>
      <div class="field"><label>Opened Date</label><input id="m-opened" type="date"></div>
    </div>
    <div class="form-row">
      <div class="field"><label>Opposing Party</label><input id="m-opposing" placeholder="Name or firm"></div>
      <div class="field"><label>Court / Jurisdiction</label><input id="m-court" placeholder="e.g. SDNY, Cook County"></div>
    </div>
    <div class="form-row">
      <div class="field"><label>Statute of Limitations</label><input id="m-sol" type="date"></div>
    </div>
    <div class="field" style="margin-bottom:1rem"><label>Description / Notes</label><textarea id="m-desc" rows="3"></textarea></div>
    <div style="display:flex;gap:.75rem;justify-content:flex-end">
      <button class="btn btn-secondary" onclick="closeMatterModal()">Cancel</button>
      <button class="btn btn-primary" onclick="saveMatter()">Save Matter</button>
    </div>
  </div>
</div>

<!-- Client Modal -->
<div class="modal-overlay" id="client-modal">
  <div class="modal">
    <div class="modal-title">
      <span id="client-modal-title">New Client</span>
      <button class="close-btn" onclick="closeClientModal()">✕</button>
    </div>
    <div class="form-row">
      <div class="field"><label>Name *</label><input id="c-name" placeholder="Full name or entity name"></div>
      <div class="field"><label>Company / Organization</label><input id="c-company" placeholder="Optional"></div>
    </div>
    <div class="form-row">
      <div class="field"><label>Email</label><input id="c-email" type="email"></div>
      <div class="field"><label>Phone</label><input id="c-phone" type="tel"></div>
    </div>
    <div class="field" style="margin-bottom:1rem"><label>Address</label><input id="c-address"></div>
    <div class="field" style="margin-bottom:1rem"><label>Notes</label><textarea id="c-notes" rows="2"></textarea></div>
    <div style="display:flex;gap:.75rem;justify-content:flex-end">
      <button class="btn btn-secondary" onclick="closeClientModal()">Cancel</button>
      <button class="btn btn-primary" onclick="saveClient()">Save Client</button>
    </div>
  </div>
</div>

<!-- Time Entry Modal -->
<div class="modal-overlay" id="time-modal">
  <div class="modal">
    <div class="modal-title">
      <span>Log Time</span>
      <button class="close-btn" onclick="closeTimeModal()">✕</button>
    </div>
    <div class="form-row">
      <div class="field"><label>Matter *</label><select id="t-matter-id"></select></div>
      <div class="field"><label>Date *</label><input id="t-date" type="date"></div>
    </div>
    <div class="form-row">
      <div class="field"><label>Hours *</label><input id="t-hours" type="number" step="0.1" min="0.1" placeholder="1.5"></div>
      <div class="field"><label>Rate ($/hr)</label><input id="t-rate" type="number" value="350"></div>
      <div class="field"><label>Attorney</label><input id="t-attorney" placeholder="Initials or name"></div>
    </div>
    <div class="field" style="margin-bottom:.75rem">
      <label>Activity Code</label>
      <select id="t-activity"></select>
    </div>
    <div class="field" style="margin-bottom:1rem"><label>Description *</label><textarea id="t-desc" rows="3" placeholder="Detailed description of work performed"></textarea></div>
    <div style="display:flex;gap:.75rem;justify-content:flex-end">
      <button class="btn btn-secondary" onclick="closeTimeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="saveTime()">Save Entry</button>
    </div>
  </div>
</div>

<!-- Trust Entry Modal -->
<div class="modal-overlay" id="trust-modal">
  <div class="modal">
    <div class="modal-title">
      <span id="trust-modal-title">Trust Entry</span>
      <button class="close-btn" onclick="document.getElementById('trust-modal').classList.remove('open')">✕</button>
    </div>
    <div class="form-row">
      <div class="field"><label>Matter *</label><select id="tr-matter-id"></select></div>
      <div class="field"><label>Date</label><input id="tr-date" type="date"></div>
    </div>
    <div class="form-row">
      <div class="field"><label>Amount ($) — positive = deposit, negative = disbursement</label><input id="tr-amount" type="number" step="0.01" placeholder="5000.00"></div>
    </div>
    <div class="field" style="margin-bottom:1rem"><label>Description</label><textarea id="tr-desc" rows="2" placeholder="e.g. Retainer deposit from client"></textarea></div>
    <div style="display:flex;gap:.75rem;justify-content:flex-end">
      <button class="btn btn-secondary" onclick="document.getElementById('trust-modal').classList.remove('open')">Cancel</button>
      <button class="btn btn-primary" onclick="saveTrust()">Save Entry</button>
    </div>
  </div>
</div>

<script>
let _currentTab = 'dashboard';
let _matters = [], _clients = [], _analytics = {};
let _editMatterId = null, _editClientId = null;
let _activityCodes = {}, _docTypes = {};

function _llm() {
  return {
    provider: localStorage.getItem('ca_provider') || 'anthropic',
    model: localStorage.getItem('ca_model') || 'claude-opus-4-7',
    api_key: localStorage.getItem('ca_api_key') || ''
  };
}

async function api(path, opts={}) {
  const r = await fetch(path, {headers:{'Content-Type':'application/json'}, ...opts});
  if (!r.ok) {
    const e = await r.json().catch(()=>({}));
    throw new Error(e.detail || r.statusText);
  }
  return r.json();
}

function fmtMoney(n) { return '$' + (parseFloat(n)||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}); }
function fmtHours(h) { return (parseFloat(h)||0).toFixed(1) + 'h'; }
function fmtDate(d) { return d ? d.slice(0,10) : '—'; }
function badgeStatus(s) {
  const map = {open:'badge-open',closed:'badge-closed',pending:'badge-pending',inactive:'badge-inactive',
               draft:'badge-draft',sent:'badge-sent',paid:'badge-paid',overdue:'badge-overdue',written_off:'badge-inactive'};
  return `<span class="badge ${map[s]||''}">${s}</span>`;
}
function matterTypeLabel(t) {
  const m = {litigation:'Litigation',corporate:'Corporate',real_estate:'Real Estate',estate_planning:'Estate Planning',
             family:'Family',criminal:'Criminal',immigration:'Immigration',employment:'Employment',
             ip:'IP',bankruptcy:'Bankruptcy',tax:'Tax',other:'Other'};
  return m[t]||t;
}

async function init() {
  [_activityCodes, _docTypes] = await Promise.all([
    api('/api/legal/activity-codes'),
    api('/api/legal/document-types'),
  ]);
  await refresh();
  switchTab('dashboard');
}

async function refresh() {
  [_matters, _clients, _analytics] = await Promise.all([
    api('/api/legal/matters'),
    api('/api/legal/clients'),
    api('/api/legal/analytics'),
  ]);
  document.getElementById('hdr-stats').textContent =
    `${_analytics.open_matters} open matters · ${_analytics.total_clients} clients · ${fmtMoney(_analytics.unbilled_value)} unbilled`;
}

function switchTab(tab) {
  _currentTab = tab;
  document.querySelectorAll('.tab').forEach((el,i)=>{
    el.classList.toggle('active', ['dashboard','matters','clients','time','documents','billing'][i]===tab);
  });
  renderTab();
}

function renderTab() {
  const c = document.getElementById('content');
  if (_currentTab==='dashboard') renderDashboard(c);
  else if (_currentTab==='matters') renderMatters(c);
  else if (_currentTab==='clients') renderClients(c);
  else if (_currentTab==='time') renderTime(c);
  else if (_currentTab==='documents') renderDocuments(c);
  else if (_currentTab==='billing') renderBilling(c);
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
function renderDashboard(c) {
  const a = _analytics;
  c.innerHTML = `
    <div class="kpi-grid">
      <div class="kpi"><div class="kpi-val">${a.open_matters||0}</div><div class="kpi-lbl">Open Matters</div></div>
      <div class="kpi"><div class="kpi-val">${a.total_clients||0}</div><div class="kpi-lbl">Clients</div></div>
      <div class="kpi"><div class="kpi-val" style="color:#f0883e">${fmtHours(a.unbilled_hours)}</div><div class="kpi-lbl">Unbilled Hours</div></div>
      <div class="kpi"><div class="kpi-val" style="color:#f0883e">${fmtMoney(a.unbilled_value)}</div><div class="kpi-lbl">Unbilled Value</div></div>
      <div class="kpi"><div class="kpi-val" style="color:#f85149">${fmtMoney(a.ar_total)}</div><div class="kpi-lbl">A/R Outstanding</div></div>
      <div class="kpi"><div class="kpi-val" style="color:#3fb950">${fmtMoney(a.invoiced_mtd)}</div><div class="kpi-lbl">Invoiced MTD</div></div>
      <div class="kpi"><div class="kpi-val" style="color:#58a6ff">${fmtMoney(a.trust_balance)}</div><div class="kpi-lbl">Trust Balance</div></div>
    </div>
    <div class="card">
      <div class="card-title">Recent Matters</div>
      ${(a.recent_matters||[]).length===0 ? '<div class="empty"><div class="empty-icon">📁</div><p>No matters yet. <a href="#" onclick="switchTab(\'matters\');openMatterModal()" style="color:#a78bfa">Open your first matter →</a></p></div>' :
        '<table><thead><tr><th>Matter #</th><th>Title</th><th>Type</th><th>Status</th><th>Opened</th></tr></thead><tbody>' +
        (a.recent_matters||[]).map(m=>`<tr onclick="switchTab('matters')" style="cursor:pointer">
          <td style="font-family:monospace;color:#58a6ff">${m.matter_number}</td>
          <td>${m.title}</td>
          <td>${matterTypeLabel(m.matter_type)}</td>
          <td>${badgeStatus(m.status)}</td>
          <td>${fmtDate(m.opened_date)}</td>
        </tr>`).join('') + '</tbody></table>'
      }
    </div>
  `;
}

// ── Matters ───────────────────────────────────────────────────────────────────
function renderMatters(c) {
  let filter = '', search = '';
  const render = async () => {
    let matters = _matters;
    if (filter) matters = matters.filter(m=>m.status===filter);
    if (search) matters = matters.filter(m=>m.title.toLowerCase().includes(search)||m.matter_number.toLowerCase().includes(search));
    c.innerHTML = `
      <div class="actions">
        <input class="search-box" placeholder="Search matters…" value="${search}" oninput="this._s=this.value;setTimeout(()=>{if(this._s===this.value){search=this.value;render();}},250)">
        <select class="search-box" style="max-width:140px" onchange="filter=this.value;render()">
          <option value="">All Status</option>
          <option value="open">Open</option>
          <option value="pending">Pending</option>
          <option value="inactive">Inactive</option>
          <option value="closed">Closed</option>
        </select>
        <button class="btn btn-primary" onclick="openMatterModal()">+ New Matter</button>
      </div>
      ${matters.length===0 ? '<div class="empty"><div class="empty-icon">📁</div><p>No matters found.</p></div>' :
      '<div class="card"><table><thead><tr><th>Matter #</th><th>Title</th><th>Client</th><th>Type</th><th>Fee</th><th>Status</th><th>Opened</th><th></th></tr></thead><tbody>' +
      matters.map(m=>{
        const client = _clients.find(c=>c.id===m.client_id);
        return `<tr>
          <td style="font-family:monospace;color:#58a6ff">${m.matter_number}</td>
          <td style="max-width:200px">${m.title}</td>
          <td>${client?client.name:'—'}</td>
          <td>${matterTypeLabel(m.matter_type)}</td>
          <td>${m.fee_arrangement==='hourly'?fmtMoney(m.hourly_rate)+'/hr':m.fee_arrangement.replace('_',' ')}</td>
          <td>${badgeStatus(m.status)}</td>
          <td>${fmtDate(m.opened_date)}</td>
          <td><button class="btn btn-secondary btn-sm" onclick="openMatterModal('${m.id}')">Edit</button></td>
        </tr>`;
      }).join('') + '</tbody></table></div>'}
    `;
  };
  render();
}

// ── Clients ───────────────────────────────────────────────────────────────────
function renderClients(c) {
  let search = '';
  const render = () => {
    let clients = _clients;
    if (search) clients = clients.filter(cl=>cl.name.toLowerCase().includes(search)||cl.company.toLowerCase().includes(search));
    c.innerHTML = `
      <div class="actions">
        <input class="search-box" placeholder="Search clients…" value="${search}" oninput="this._s=this.value;setTimeout(()=>{if(this._s===this.value){search=this.value;render();}},250)">
        <button class="btn btn-primary" onclick="openClientModal()">+ New Client</button>
      </div>
      ${clients.length===0 ? '<div class="empty"><div class="empty-icon">👤</div><p>No clients yet.</p></div>' :
      '<div class="card"><table><thead><tr><th>Name</th><th>Company</th><th>Email</th><th>Phone</th><th>Client Since</th><th>Matters</th><th></th></tr></thead><tbody>' +
      clients.map(cl=>{
        const mCount = _matters.filter(m=>m.client_id===cl.id).length;
        return `<tr>
          <td style="font-weight:600">${cl.name}</td>
          <td>${cl.company||'—'}</td>
          <td>${cl.email||'—'}</td>
          <td>${cl.phone||'—'}</td>
          <td>${fmtDate(cl.client_since)}</td>
          <td>${mCount}</td>
          <td><button class="btn btn-secondary btn-sm" onclick="openClientModal('${cl.id}')">Edit</button></td>
        </tr>`;
      }).join('') + '</tbody></table></div>'}
    `;
  };
  render();
}

// ── Time Tracking ─────────────────────────────────────────────────────────────
function renderTime(c) {
  let mFilter = '', billedFilter = 'false';
  const render = async () => {
    const params = new URLSearchParams();
    if (mFilter) params.set('matter_id', mFilter);
    if (billedFilter) params.set('billed', billedFilter);
    const entries = await api('/api/legal/time?' + params.toString());
    const totalH = entries.reduce((s,e)=>s+e.hours, 0);
    const totalV = entries.reduce((s,e)=>s+e.hours*e.rate, 0);
    c.innerHTML = `
      <div class="actions">
        <select class="search-box" style="max-width:220px" onchange="mFilter=this.value;render()">
          <option value="">All Matters</option>
          ${_matters.map(m=>`<option value="${m.id}">${m.matter_number} — ${m.title.slice(0,30)}</option>`).join('')}
        </select>
        <select class="search-box" style="max-width:130px" onchange="billedFilter=this.value;render()">
          <option value="false">Unbilled</option>
          <option value="true">Billed</option>
          <option value="">All</option>
        </select>
        <button class="btn btn-primary" onclick="openTimeModal()">+ Log Time</button>
      </div>
      <div class="kpi-grid" style="grid-template-columns:repeat(auto-fit,minmax(120px,1fr));margin-bottom:1rem">
        <div class="kpi"><div class="kpi-val">${fmtHours(totalH)}</div><div class="kpi-lbl">Total Hours</div></div>
        <div class="kpi"><div class="kpi-val" style="color:#f0883e">${fmtMoney(totalV)}</div><div class="kpi-lbl">Total Value</div></div>
        <div class="kpi"><div class="kpi-val">${entries.length}</div><div class="kpi-lbl">Entries</div></div>
      </div>
      ${entries.length===0 ? '<div class="empty"><div class="empty-icon">⏱</div><p>No time entries found.</p></div>' :
      '<div class="card"><table><thead><tr><th>Date</th><th>Matter</th><th>Attorney</th><th>Activity</th><th>Hours</th><th>Rate</th><th>Value</th><th>Description</th><th></th></tr></thead><tbody>' +
      entries.map(e=>{
        const m = _matters.find(x=>x.id===e.matter_id);
        return `<tr>
          <td>${fmtDate(e.date)}</td>
          <td style="font-family:monospace;font-size:.78rem;color:#58a6ff">${m?m.matter_number:'?'}</td>
          <td>${e.attorney||'—'}</td>
          <td title="${_activityCodes[e.activity_code]||''}">${e.activity_code}</td>
          <td style="font-weight:600">${e.hours.toFixed(1)}</td>
          <td>${fmtMoney(e.rate)}/hr</td>
          <td style="color:#f0883e">${fmtMoney(e.hours*e.rate)}</td>
          <td style="max-width:200px;color:#8b949e;font-size:.8rem">${e.description}</td>
          <td><button class="btn btn-danger btn-sm" onclick="deleteTime('${e.id}',render)">✕</button></td>
        </tr>`;
      }).join('') + '</tbody></table></div>'}
    `;
  };
  render();
}

// ── Documents ─────────────────────────────────────────────────────────────────
function renderDocuments(c) {
  c.innerHTML = `
    <div class="split">
      <div class="panel">
        <div class="card-title" style="margin-bottom:1rem">⚖️ AI Document Drafter</div>
        <div class="field" style="margin-bottom:.75rem">
          <label>Document Type *</label>
          <select id="doc-type">
            ${Object.entries(_docTypes).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}
          </select>
        </div>
        <div class="form-row">
          <div class="field"><label>Party A (Your Client)</label><input id="doc-party-a" placeholder="Name"></div>
          <div class="field"><label>Party B (Counterparty)</label><input id="doc-party-b" placeholder="Name"></div>
        </div>
        <div class="field" style="margin-bottom:.75rem">
          <label>Jurisdiction</label>
          <input id="doc-jurisdiction" placeholder="e.g. State of Illinois, Northern District of Texas">
        </div>
        <div class="field" style="margin-bottom:.75rem">
          <label>Key Facts & Context *</label>
          <textarea id="doc-facts" rows="5" placeholder="Describe the transaction, dispute, or situation. Include key terms, dates, amounts, obligations…"></textarea>
        </div>
        <div class="field" style="margin-bottom:1rem">
          <label>Additional Terms / Special Provisions</label>
          <textarea id="doc-additional" rows="3" placeholder="Any specific clauses, carve-outs, or non-standard terms to include…"></textarea>
        </div>
        <button class="btn btn-primary" style="width:100%" onclick="draftDocument()" id="doc-btn">✍ Draft Document</button>
        <div id="doc-checklist" style="margin-top:1rem;display:none"></div>
      </div>
      <div class="panel" id="doc-output">
        <div class="empty" style="margin-top:4rem"><div class="empty-icon">📄</div><p style="color:#8b949e">Complete the form and click Draft Document.<br>The AI will generate a complete professional draft.</p></div>
      </div>
    </div>
  `;
}

async function draftDocument() {
  const docType = document.getElementById('doc-type').value;
  const facts = document.getElementById('doc-facts').value.trim();
  if (!facts) { alert('Please enter facts and context.'); return; }
  const btn = document.getElementById('doc-btn');
  btn.textContent = '⏳ Drafting…'; btn.disabled = true;
  document.getElementById('doc-output').innerHTML = '<div class="empty" style="margin-top:4rem"><div class="empty-icon">⏳</div><p>The AI is drafting your document…</p></div>';
  try {
    const result = await api('/api/legal/brain/draft', {
      method:'POST',
      body: JSON.stringify({
        doc_type: docType,
        facts,
        party_a: document.getElementById('doc-party-a').value,
        party_b: document.getElementById('doc-party-b').value,
        jurisdiction: document.getElementById('doc-jurisdiction').value,
        additional_terms: document.getElementById('doc-additional').value,
        ..._llm()
      })
    });
    document.getElementById('doc-output').innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem">
        <div style="font-weight:700;font-size:.9rem;color:#fff">${result.title||result.document_type}</div>
        <button class="btn btn-secondary btn-sm" onclick="copyDoc()">📋 Copy</button>
      </div>
      <div class="doc-content" id="doc-text">${(result.content||'').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div>
      ${result.key_terms&&result.key_terms.length?`
        <div style="margin-top:1rem"><strong style="font-size:.8rem;color:#8b949e">KEY TERMS</strong>
        <div style="margin-top:.5rem;display:flex;flex-wrap:wrap;gap:.4rem">
          ${result.key_terms.map(t=>`<span class="badge badge-draft">${t}</span>`).join('')}
        </div></div>`:''
      }
      ${result.review_checklist&&result.review_checklist.length?`
        <div style="margin-top:1rem"><strong style="font-size:.8rem;color:#8b949e">ATTORNEY REVIEW CHECKLIST</strong>
        <ul style="margin-top:.5rem;padding-left:1.2rem;font-size:.82rem;color:#c9d1d9;line-height:1.8">
          ${result.review_checklist.map(i=>`<li>${i}</li>`).join('')}
        </ul></div>`:''
      }
      ${result.warnings&&result.warnings.length?`
        <div style="margin-top:1rem;background:rgba(248,81,73,.08);border:1px solid rgba(248,81,73,.2);border-radius:6px;padding:.75rem">
          <strong style="font-size:.78rem;color:#f85149">⚠ WARNINGS</strong>
          <ul style="margin-top:.4rem;padding-left:1.2rem;font-size:.82rem;color:#f85149;line-height:1.8">
            ${result.warnings.map(w=>`<li>${w}</li>`).join('')}
          </ul>
        </div>`:''
      }
    `;
  } catch(e) {
    document.getElementById('doc-output').innerHTML = `<div style="color:#f85149;padding:1rem">Error: ${e.message}</div>`;
  } finally {
    btn.textContent = '✍ Draft Document'; btn.disabled = false;
  }
}

function copyDoc() {
  const text = document.getElementById('doc-text').textContent;
  navigator.clipboard.writeText(text).then(()=>{alert('Document copied to clipboard.');});
}

// ── Billing ───────────────────────────────────────────────────────────────────
function renderBilling(c) {
  let statusFilter = '';
  const render = async () => {
    const params = statusFilter ? `?status=${statusFilter}` : '';
    const [invoices, trust] = await Promise.all([
      api('/api/legal/invoices'+params),
      api('/api/legal/trust'),
    ]);
    c.innerHTML = `
      <div class="actions">
        <select class="search-box" style="max-width:140px" onchange="statusFilter=this.value;render()">
          <option value="">All Invoices</option>
          <option value="draft">Draft</option>
          <option value="sent">Sent</option>
          <option value="paid">Paid</option>
          <option value="overdue">Overdue</option>
        </select>
        <select class="search-box" style="max-width:220px" id="bill-matter-sel">
          <option value="">Select Matter to Invoice…</option>
          ${_matters.filter(m=>m.status==='open').map(m=>`<option value="${m.id}">${m.matter_number} — ${m.title.slice(0,30)}</option>`).join('')}
        </select>
        <button class="btn btn-primary" onclick="createInvoice()">Generate Invoice</button>
        <button class="btn btn-secondary" onclick="openTrustModal()">+ Trust Entry</button>
      </div>
      <div style="display:grid;grid-template-columns:2fr 1fr;gap:1.5rem">
        <div>
          <div class="card-title" style="margin-bottom:.5rem;font-size:.85rem;color:#8b949e">INVOICES</div>
          ${invoices.length===0 ? '<div class="empty"><div class="empty-icon">📋</div><p>No invoices yet.</p></div>' :
          '<div class="card"><table><thead><tr><th>Invoice #</th><th>Matter</th><th>Issue Date</th><th>Total</th><th>Paid</th><th>Balance</th><th>Status</th><th></th></tr></thead><tbody>' +
          invoices.map(inv=>{
            const m = _matters.find(x=>x.id===inv.matter_id);
            const balance = inv.total - inv.paid_amount;
            return `<tr>
              <td style="font-family:monospace;color:#58a6ff">${inv.invoice_number}</td>
              <td>${m?m.matter_number:'?'}</td>
              <td>${fmtDate(inv.issue_date)}</td>
              <td>${fmtMoney(inv.total)}</td>
              <td style="color:#3fb950">${fmtMoney(inv.paid_amount)}</td>
              <td style="color:${balance>0?'#f85149':'#3fb950'}">${fmtMoney(balance)}</td>
              <td>${badgeStatus(inv.status)}</td>
              <td><button class="btn btn-secondary btn-sm" onclick="markPaid('${inv.id}',${inv.total},render)">Mark Paid</button></td>
            </tr>`;
          }).join('') + '</tbody></table></div>'}
        </div>
        <div>
          <div class="card-title" style="margin-bottom:.5rem;font-size:.85rem;color:#8b949e">TRUST LEDGER</div>
          ${trust.length===0 ? '<div class="empty"><div class="empty-icon">🏦</div><p>No trust entries.</p></div>' :
          '<div class="card" style="padding:.75rem"><table><thead><tr><th>Date</th><th>Amount</th><th>Balance</th><th>Description</th></tr></thead><tbody>' +
          trust.slice(0,20).map(t=>`<tr>
            <td>${fmtDate(t.date)}</td>
            <td class="${t.amount>=0?'trust-pos':'trust-neg'}">${t.amount>=0?'+':''}${fmtMoney(t.amount)}</td>
            <td style="font-weight:600">${fmtMoney(t.balance_after)}</td>
            <td style="font-size:.78rem;color:#8b949e">${t.description}</td>
          </tr>`).join('') + '</tbody></table></div>'}
        </div>
      </div>
    `;
  };
  render();
}

async function createInvoice() {
  const matterId = document.getElementById('bill-matter-sel').value;
  if (!matterId) { alert('Select a matter first.'); return; }
  try {
    await api(`/api/legal/invoices/from-matter/${matterId}`, {method:'POST'});
    await refresh(); renderTab();
  } catch(e) { alert('Error: ' + e.message); }
}

async function markPaid(invId, total, render) {
  try {
    await api(`/api/legal/invoices/${invId}`, {method:'PATCH', body:JSON.stringify({status:'paid',paid_amount:total})});
    await refresh(); render();
  } catch(e) { alert('Error: ' + e.message); }
}

// ── Matter Modal ──────────────────────────────────────────────────────────────
function openMatterModal(matterId) {
  _editMatterId = matterId || null;
  const modal = document.getElementById('matter-modal');
  document.getElementById('matter-modal-title').textContent = matterId ? 'Edit Matter' : 'New Matter';
  // Populate client dropdown
  const sel = document.getElementById('m-client-id');
  sel.innerHTML = _clients.map(c=>`<option value="${c.id}">${c.name}${c.company?' ('+c.company+')':''}</option>`).join('');
  // Default date
  if (!matterId) {
    document.getElementById('m-opened').value = new Date().toISOString().slice(0,10);
    document.getElementById('m-title').value = '';
    document.getElementById('m-desc').value = '';
    document.getElementById('m-attorney').value = '';
    document.getElementById('m-opposing').value = '';
    document.getElementById('m-court').value = '';
    document.getElementById('m-sol').value = '';
  } else {
    const m = _matters.find(x=>x.id===matterId);
    if (m) {
      sel.value = m.client_id;
      document.getElementById('m-title').value = m.title;
      document.getElementById('m-type').value = m.matter_type;
      document.getElementById('m-status').value = m.status;
      document.getElementById('m-fee').value = m.fee_arrangement;
      document.getElementById('m-rate').value = m.hourly_rate;
      document.getElementById('m-attorney').value = m.responsible_attorney;
      document.getElementById('m-opened').value = m.opened_date||'';
      document.getElementById('m-opposing').value = m.opposing_party;
      document.getElementById('m-court').value = m.court_jurisdiction;
      document.getElementById('m-sol').value = m.statute_of_limitations||'';
      document.getElementById('m-desc').value = m.description;
    }
  }
  modal.classList.add('open');
}

function closeMatterModal() { document.getElementById('matter-modal').classList.remove('open'); }

function updateFeeFields() {
  const fee = document.getElementById('m-fee').value;
  const container = document.getElementById('fee-fields');
  if (fee==='hourly') container.innerHTML = '<div class="field"><label>Hourly Rate ($)</label><input id="m-rate" type="number" value="350"></div>';
  else if (fee==='flat_fee') container.innerHTML = '<div class="field"><label>Flat Fee ($)</label><input id="m-rate" type="number" value="5000"></div>';
  else if (fee==='contingency') container.innerHTML = '<div class="field"><label>Contingency % (e.g. 33)</label><input id="m-rate" type="number" value="33"></div>';
  else if (fee==='retainer') container.innerHTML = '<div class="field"><label>Retainer Amount ($)</label><input id="m-rate" type="number" value="5000"></div>';
  else container.innerHTML = '';
}

async function saveMatter() {
  const clientId = document.getElementById('m-client-id').value;
  const title = document.getElementById('m-title').value.trim();
  if (!clientId || !title) { alert('Client and title are required.'); return; }
  const fee = document.getElementById('m-fee').value;
  const rateVal = parseFloat(document.getElementById('m-rate')?.value||0);
  const body = {
    client_id: clientId, title,
    matter_type: document.getElementById('m-type').value,
    status: document.getElementById('m-status').value,
    fee_arrangement: fee,
    hourly_rate: fee==='hourly'?rateVal:350,
    flat_fee: fee==='flat_fee'?rateVal:0,
    contingency_pct: fee==='contingency'?rateVal/100:0.33,
    retainer_amount: fee==='retainer'?rateVal:0,
    responsible_attorney: document.getElementById('m-attorney').value,
    opened_date: document.getElementById('m-opened').value,
    opposing_party: document.getElementById('m-opposing').value,
    court_jurisdiction: document.getElementById('m-court').value,
    statute_of_limitations: document.getElementById('m-sol').value,
    description: document.getElementById('m-desc').value,
  };
  try {
    if (_editMatterId) await api(`/api/legal/matters/${_editMatterId}`, {method:'PATCH', body:JSON.stringify(body)});
    else await api('/api/legal/matters', {method:'POST', body:JSON.stringify(body)});
    closeMatterModal(); await refresh(); renderTab();
  } catch(e) { alert('Error: ' + e.message); }
}

// ── Client Modal ──────────────────────────────────────────────────────────────
function openClientModal(clientId) {
  _editClientId = clientId || null;
  document.getElementById('client-modal-title').textContent = clientId ? 'Edit Client' : 'New Client';
  if (!clientId) {
    ['c-name','c-company','c-email','c-phone','c-address','c-notes'].forEach(id=>document.getElementById(id).value='');
  } else {
    const cl = _clients.find(x=>x.id===clientId);
    if (cl) {
      document.getElementById('c-name').value = cl.name;
      document.getElementById('c-company').value = cl.company||'';
      document.getElementById('c-email').value = cl.email||'';
      document.getElementById('c-phone').value = cl.phone||'';
      document.getElementById('c-address').value = cl.address||'';
      document.getElementById('c-notes').value = cl.notes||'';
    }
  }
  document.getElementById('client-modal').classList.add('open');
}
function closeClientModal() { document.getElementById('client-modal').classList.remove('open'); }

async function saveClient() {
  const name = document.getElementById('c-name').value.trim();
  if (!name) { alert('Name is required.'); return; }
  const body = {
    name,
    company: document.getElementById('c-company').value,
    email: document.getElementById('c-email').value,
    phone: document.getElementById('c-phone').value,
    address: document.getElementById('c-address').value,
    notes: document.getElementById('c-notes').value,
  };
  try {
    if (_editClientId) await api(`/api/legal/clients/${_editClientId}`, {method:'PATCH', body:JSON.stringify(body)});
    else await api('/api/legal/clients', {method:'POST', body:JSON.stringify(body)});
    closeClientModal(); await refresh(); renderTab();
  } catch(e) { alert('Error: ' + e.message); }
}

// ── Time Modal ────────────────────────────────────────────────────────────────
function openTimeModal(matterId) {
  const sel = document.getElementById('t-matter-id');
  sel.innerHTML = _matters.map(m=>`<option value="${m.id}">${m.matter_number} — ${m.title.slice(0,40)}</option>`).join('');
  if (matterId) sel.value = matterId;
  document.getElementById('t-date').value = new Date().toISOString().slice(0,10);
  document.getElementById('t-hours').value = '';
  document.getElementById('t-rate').value = '350';
  document.getElementById('t-attorney').value = '';
  document.getElementById('t-desc').value = '';
  const actSel = document.getElementById('t-activity');
  actSel.innerHTML = Object.entries(_activityCodes).map(([k,v])=>`<option value="${k}">${k} — ${v}</option>`).join('');
  document.getElementById('time-modal').classList.add('open');
}
function closeTimeModal() { document.getElementById('time-modal').classList.remove('open'); }

async function saveTime() {
  const hours = parseFloat(document.getElementById('t-hours').value);
  const desc = document.getElementById('t-desc').value.trim();
  const matterId = document.getElementById('t-matter-id').value;
  if (!matterId || !hours || !desc) { alert('Matter, hours, and description are required.'); return; }
  const body = {
    matter_id: matterId,
    date: document.getElementById('t-date').value,
    hours,
    rate: parseFloat(document.getElementById('t-rate').value)||350,
    attorney: document.getElementById('t-attorney').value,
    activity_code: document.getElementById('t-activity').value,
    description: desc,
  };
  try {
    await api('/api/legal/time', {method:'POST', body:JSON.stringify(body)});
    closeTimeModal(); await refresh(); renderTab();
  } catch(e) { alert('Error: ' + e.message); }
}

async function deleteTime(entryId, render) {
  if (!confirm('Delete this time entry?')) return;
  try { await api(`/api/legal/time/${entryId}`, {method:'DELETE'}); await refresh(); render(); }
  catch(e) { alert('Error: ' + e.message); }
}

// ── Trust Modal ───────────────────────────────────────────────────────────────
function openTrustModal() {
  const sel = document.getElementById('tr-matter-id');
  sel.innerHTML = _matters.map(m=>`<option value="${m.id}">${m.matter_number} — ${m.title.slice(0,40)}</option>`).join('');
  document.getElementById('tr-date').value = new Date().toISOString().slice(0,10);
  document.getElementById('tr-amount').value = '';
  document.getElementById('tr-desc').value = '';
  document.getElementById('trust-modal').classList.add('open');
}

async function saveTrust() {
  const amount = parseFloat(document.getElementById('tr-amount').value);
  const desc = document.getElementById('tr-desc').value.trim();
  const matterId = document.getElementById('tr-matter-id').value;
  if (!matterId || isNaN(amount) || !desc) { alert('Matter, amount, and description required.'); return; }
  try {
    await api('/api/legal/trust', {method:'POST', body:JSON.stringify({
      matter_id: matterId,
      date: document.getElementById('tr-date').value,
      amount, description: desc,
    })});
    document.getElementById('trust-modal').classList.remove('open');
    await refresh(); renderTab();
  } catch(e) { alert('Error: ' + e.message); }
}

init();
</script>
</body>
</html>"""
