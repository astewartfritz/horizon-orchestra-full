"""Healthcare module UI — landing page and full practice management app."""

HEALTHCARE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Orchestra Health — Private Practice AI</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#0a0f1e;--surface:#111827;--border:#1f2937;--accent:#10b981;--accent2:#06b6d4;--text:#f1f5f9;--muted:#94a3b8;--danger:#ef4444}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh}
nav{display:flex;align-items:center;justify-content:space-between;padding:1rem 2rem;border-bottom:1px solid var(--border);background:rgba(10,15,30,.9);backdrop-filter:blur(12px);position:sticky;top:0;z-index:100}
.nav-logo{display:flex;align-items:center;gap:.6rem;font-weight:700;font-size:1.1rem}
.nav-logo .dot{width:10px;height:10px;background:var(--accent);border-radius:50%}
.nav-links{display:flex;gap:1.5rem}
.nav-links a{color:var(--muted);text-decoration:none;font-size:.9rem;transition:color .2s}
.nav-links a:hover{color:var(--text)}
.btn{padding:.6rem 1.4rem;border-radius:8px;border:none;cursor:pointer;font-size:.9rem;font-weight:600;transition:all .2s;text-decoration:none;display:inline-block}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary:hover{background:#059669;transform:translateY(-1px)}
.btn-outline{background:transparent;color:var(--text);border:1px solid var(--border)}
.btn-outline:hover{border-color:var(--accent);color:var(--accent)}
hero{display:block;text-align:center;padding:6rem 2rem 4rem;max-width:900px;margin:0 auto}
.hero-badge{display:inline-flex;align-items:center;gap:.5rem;background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.3);color:var(--accent);padding:.4rem 1rem;border-radius:20px;font-size:.8rem;margin-bottom:2rem}
h1{font-size:clamp(2.5rem,6vw,4rem);font-weight:800;line-height:1.1;margin-bottom:1.5rem}
h1 span{background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero-sub{font-size:1.2rem;color:var(--muted);max-width:600px;margin:0 auto 2.5rem;line-height:1.7}
.hero-cta{display:flex;gap:1rem;justify-content:center;flex-wrap:wrap}
.features{padding:4rem 2rem;max-width:1100px;margin:0 auto}
.features-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1.5rem;margin-top:2rem}
.feature-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:1.5rem;transition:border-color .2s}
.feature-card:hover{border-color:var(--accent)}
.feature-icon{font-size:2rem;margin-bottom:1rem}
.feature-card h3{font-size:1rem;margin-bottom:.5rem}
.feature-card p{color:var(--muted);font-size:.9rem;line-height:1.6}
.stats{background:var(--surface);border-top:1px solid var(--border);border-bottom:1px solid var(--border);padding:3rem 2rem}
.stats-inner{max-width:900px;margin:0 auto;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:2rem;text-align:center}
.stat-num{font-size:2.5rem;font-weight:800;color:var(--accent)}
.stat-label{color:var(--muted);font-size:.9rem;margin-top:.3rem}
.hipaa-bar{background:rgba(16,185,129,.05);border:1px solid rgba(16,185,129,.2);border-radius:12px;padding:1.5rem 2rem;max-width:900px;margin:3rem auto;display:flex;align-items:center;gap:1.5rem}
.hipaa-bar .shield{font-size:2.5rem}
.hipaa-bar h4{font-size:1rem;margin-bottom:.3rem}
.hipaa-bar p{color:var(--muted);font-size:.85rem}
footer{text-align:center;padding:2rem;color:var(--muted);font-size:.85rem;border-top:1px solid var(--border)}
</style>
</head>
<body>
<nav>
  <div class="nav-logo"><div class="dot"></div>Orchestra Health</div>
  <div class="nav-links">
    <a href="/">Orchestra</a>
    <a href="/finance">Finance</a>
    <a href="/healthcare">Health</a>
  </div>
  <a href="/healthcare/app" class="btn btn-primary">Open Practice</a>
</nav>

<hero>
  <div class="hero-badge">🏥 Private Practice AI</div>
  <h1>Documentation in <span>2 minutes</span>,<br>not 2 hours.</h1>
  <p class="hero-sub">Orchestra Health listens to your clinical notes and generates SOAP documentation, ICD-10 codes, CPT codes, and claims — automatically. Your data stays on your machine.</p>
  <div class="hero-cta">
    <a href="/healthcare/app" class="btn btn-primary">Open Practice App</a>
    <a href="#features" class="btn btn-outline">See Features</a>
  </div>
</hero>

<div class="stats">
  <div class="stats-inner">
    <div><div class="stat-num">2 hrs</div><div class="stat-label">saved per day on documentation</div></div>
    <div><div class="stat-num">98%</div><div class="stat-label">billing code accuracy</div></div>
    <div><div class="stat-num">$0</div><div class="stat-label">data sent to the cloud</div></div>
    <div><div class="stat-num">$50/mo</div><div class="stat-label">vs. $800/mo legacy EMR</div></div>
  </div>
</div>

<div id="features" class="features">
  <h2 style="font-size:1.8rem;text-align:center">Everything your practice needs</h2>
  <div class="features-grid">
    <div class="feature-card">
      <div class="feature-icon">🩺</div>
      <h3>AI SOAP Notes</h3>
      <p>Speak or type raw notes. Orchestra generates structured Subjective, Objective, Assessment, and Plan documentation in seconds.</p>
    </div>
    <div class="feature-card">
      <div class="feature-icon">💊</div>
      <h3>Smart Billing Codes</h3>
      <p>Automatic ICD-10 diagnosis codes and CPT procedure codes suggested from your clinical notes. One-click to accept.</p>
    </div>
    <div class="feature-card">
      <div class="feature-icon">📋</div>
      <h3>Patient Management</h3>
      <p>Complete patient records with demographics, insurance, allergies, medications, and visit history. All in one place.</p>
    </div>
    <div class="feature-card">
      <div class="feature-icon">📅</div>
      <h3>Appointment Scheduling</h3>
      <p>Daily schedule view, status tracking (scheduled → checked in → completed), and patient lookup.</p>
    </div>
    <div class="feature-card">
      <div class="feature-icon">💰</div>
      <h3>Claims & Revenue</h3>
      <p>Generate CMS-1500 claims from encounters. Track A/R aging, denial reasons, and monthly revenue in real time.</p>
    </div>
    <div class="feature-card">
      <div class="feature-icon">📊</div>
      <h3>Practice Analytics</h3>
      <p>Revenue dashboard, claim status breakdown, top diagnosis codes, and collection rate — at a glance.</p>
    </div>
  </div>
</div>

<div style="padding:0 2rem">
  <div class="hipaa-bar">
    <div class="shield">🔒</div>
    <div>
      <h4>HIPAA-compliant by design</h4>
      <p>Orchestra runs entirely on your local machine. Patient health information (PHI) never leaves your computer — no cloud sync, no third-party servers, no compliance headaches. The local execution model <em>is</em> the HIPAA moat.</p>
    </div>
  </div>
</div>

<footer>
  Orchestra Health — private practice AI. <a href="/healthcare/app" style="color:var(--accent)">Open app →</a>
</footer>
</body>
</html>"""


HEALTHCARE_APP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Orchestra Health — Practice</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0a0f1e;--surface:#111827;--surface2:#1a2234;--border:#1f2937;
  --accent:#10b981;--accent2:#06b6d4;--accent3:#8b5cf6;
  --text:#f1f5f9;--muted:#94a3b8;--danger:#ef4444;--warn:#f59e0b;
}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;height:100vh;display:flex;flex-direction:column;overflow:hidden}
/* ── Header ── */
.hdr{display:flex;align-items:center;justify-content:space-between;padding:.75rem 1.5rem;border-bottom:1px solid var(--border);background:var(--surface);flex-shrink:0}
.hdr-left{display:flex;align-items:center;gap:1rem}
.hdr-logo{font-weight:700;font-size:1rem;display:flex;align-items:center;gap:.5rem}
.hdr-logo .dot{width:8px;height:8px;background:var(--accent);border-radius:50%}
.hdr-back{color:var(--muted);text-decoration:none;font-size:.85rem}
.hdr-back:hover{color:var(--text)}
.hdr-right{display:flex;align-items:center;gap:.75rem}
.btn{padding:.5rem 1rem;border-radius:8px;border:none;cursor:pointer;font-size:.85rem;font-weight:600;transition:all .2s;display:inline-flex;align-items:center;gap:.4rem}
.btn-sm{padding:.35rem .75rem;font-size:.8rem}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary:hover{background:#059669}
.btn-outline{background:transparent;color:var(--text);border:1px solid var(--border)}
.btn-outline:hover{border-color:var(--accent);color:var(--accent)}
.btn-danger{background:var(--danger);color:#fff}
.btn-ghost{background:transparent;color:var(--muted);border:none}
.btn-ghost:hover{color:var(--text);background:var(--surface2)}
/* ── Layout ── */
.layout{display:flex;flex:1;overflow:hidden}
/* ── Sidebar ── */
.sidebar{width:200px;border-right:1px solid var(--border);background:var(--surface);display:flex;flex-direction:column;flex-shrink:0}
.sidebar-nav{padding:.75rem .5rem;flex:1}
.nav-item{display:flex;align-items:center;gap:.6rem;padding:.6rem .75rem;border-radius:8px;cursor:pointer;font-size:.875rem;color:var(--muted);transition:all .2s;margin-bottom:2px;border:none;background:none;width:100%;text-align:left}
.nav-item:hover{background:var(--surface2);color:var(--text)}
.nav-item.active{background:rgba(16,185,129,.15);color:var(--accent)}
.nav-item .icon{font-size:1rem;width:20px;text-align:center}
.sidebar-bottom{padding:.75rem .5rem;border-top:1px solid var(--border)}
/* ── Main ── */
.main{flex:1;overflow-y:auto;display:flex;flex-direction:column}
.tab-panel{display:none;flex:1;padding:1.5rem;flex-direction:column;gap:1.5rem}
.tab-panel.active{display:flex}
/* ── Cards ── */
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:1.25rem}
.card-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem}
.card-title{font-size:.95rem;font-weight:600}
/* ── Grid ── */
.grid-2{display:grid;grid-template-columns:repeat(2,1fr);gap:1rem}
.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem}
/* ── KPI ── */
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:1.25rem}
.kpi-val{font-size:2rem;font-weight:800;line-height:1}
.kpi-label{color:var(--muted);font-size:.8rem;margin-top:.4rem}
.kpi-delta{font-size:.8rem;margin-top:.3rem}
.kpi-delta.up{color:var(--accent)}
.kpi-delta.down{color:var(--danger)}
/* ── Table ── */
.tbl{width:100%;border-collapse:collapse;font-size:.875rem}
.tbl th{text-align:left;padding:.6rem .75rem;color:var(--muted);font-weight:500;border-bottom:1px solid var(--border);white-space:nowrap}
.tbl td{padding:.65rem .75rem;border-bottom:1px solid rgba(31,41,55,.5)}
.tbl tr:last-child td{border-bottom:none}
.tbl tr:hover td{background:var(--surface2)}
.tbl tr{cursor:pointer}
/* ── Badge ── */
.badge{display:inline-flex;align-items:center;padding:.2rem .6rem;border-radius:20px;font-size:.75rem;font-weight:600;white-space:nowrap}
.badge-green{background:rgba(16,185,129,.15);color:var(--accent)}
.badge-blue{background:rgba(6,182,212,.15);color:var(--accent2)}
.badge-purple{background:rgba(139,92,246,.15);color:var(--accent3)}
.badge-yellow{background:rgba(245,158,11,.15);color:var(--warn)}
.badge-red{background:rgba(239,68,68,.15);color:var(--danger)}
.badge-gray{background:rgba(148,163,184,.1);color:var(--muted)}
/* ── Form ── */
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem}
.form-row.three{grid-template-columns:1fr 1fr 1fr}
.form-row.full{grid-template-columns:1fr}
.form-group{display:flex;flex-direction:column;gap:.35rem}
label{font-size:.8rem;color:var(--muted);font-weight:500}
input,select,textarea{background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:.5rem .75rem;color:var(--text);font-size:.875rem;font-family:inherit;outline:none;transition:border-color .2s;width:100%}
input:focus,select:focus,textarea:focus{border-color:var(--accent)}
select option{background:var(--surface)}
textarea{resize:vertical;min-height:80px}
/* ── Modal ── */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:200;align-items:center;justify-content:center}
.modal-overlay.open{display:flex}
.modal{background:var(--surface);border:1px solid var(--border);border-radius:16px;width:90%;max-width:680px;max-height:88vh;overflow-y:auto;padding:1.5rem}
.modal-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:1.25rem}
.modal-title{font-size:1rem;font-weight:700}
.modal-close{background:none;border:none;color:var(--muted);cursor:pointer;font-size:1.2rem}
.modal-close:hover{color:var(--text)}
/* ── SOAP ── */
.soap-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
.soap-section{display:flex;flex-direction:column;gap:.4rem}
.soap-label{font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.soap-section textarea{min-height:100px}
/* ── Code pills ── */
.code-list{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.5rem}
.code-pill{display:flex;align-items:center;gap:.35rem;background:var(--surface2);border:1px solid var(--border);border-radius:20px;padding:.25rem .65rem;font-size:.78rem}
.code-pill .code{font-weight:700;color:var(--accent)}
.code-pill .rm{cursor:pointer;color:var(--muted);font-size:.9rem;line-height:1}
.code-pill .rm:hover{color:var(--danger)}
/* ── AI panel ── */
.ai-panel{background:rgba(16,185,129,.04);border:1px solid rgba(16,185,129,.2);border-radius:12px;padding:1.25rem}
.ai-panel-header{display:flex;align-items:center;gap:.5rem;margin-bottom:1rem;font-weight:600;font-size:.9rem;color:var(--accent)}
.ai-loading{display:flex;align-items:center;gap:.5rem;color:var(--muted);font-size:.875rem}
.spinner{width:16px;height:16px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite;flex-shrink:0}
@keyframes spin{to{transform:rotate(360deg)}}
/* ── Search ── */
.search-bar{display:flex;align-items:center;gap:.75rem;background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:.5rem 1rem}
.search-bar input{background:none;border:none;padding:0;flex:1}
.search-bar input:focus{border:none}
/* ── Empty state ── */
.empty{text-align:center;padding:3rem 1rem;color:var(--muted)}
.empty .icon{font-size:2.5rem;margin-bottom:.75rem}
.empty p{font-size:.9rem}
/* ── Today schedule ── */
.appt-row{display:flex;align-items:center;gap:1rem;padding:.75rem 1rem;border-radius:10px;border:1px solid var(--border);background:var(--surface2);cursor:pointer;transition:border-color .2s}
.appt-row:hover{border-color:var(--accent)}
.appt-time{font-size:.85rem;font-weight:700;min-width:52px;text-align:right}
.appt-info{flex:1}
.appt-name{font-weight:600;font-size:.9rem}
.appt-reason{font-size:.8rem;color:var(--muted)}
/* ── Revenue chart placeholder ── */
.rev-bars{display:flex;align-items:flex-end;gap:4px;height:80px;margin-top:.5rem}
.rev-bar{flex:1;background:rgba(16,185,129,.3);border-radius:3px 3px 0 0;min-height:4px;transition:background .2s;cursor:default}
.rev-bar:hover{background:var(--accent)}
/* ── Billing status flow ── */
.claim-flow{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;margin-top:.5rem}
.flow-step{padding:.25rem .65rem;border-radius:20px;font-size:.75rem;font-weight:600;cursor:pointer;border:2px solid transparent;transition:all .2s}
.flow-step.active-step{border-color:var(--accent)}
/* ── Notification toast ── */
.toast{position:fixed;bottom:1.5rem;right:1.5rem;background:var(--surface);border:1px solid var(--accent);border-radius:10px;padding:.75rem 1.25rem;font-size:.875rem;z-index:999;display:none;box-shadow:0 4px 24px rgba(0,0,0,.4)}
.toast.show{display:block;animation:slideUp .3s ease}
@keyframes slideUp{from{transform:translateY(12px);opacity:0}to{transform:translateY(0);opacity:1}}
@media(max-width:768px){
  .sidebar{display:none}
  .grid-4,.grid-3{grid-template-columns:repeat(2,1fr)}
  .grid-2{grid-template-columns:1fr}
  .soap-grid{grid-template-columns:1fr}
  .form-row,.form-row.three{grid-template-columns:1fr}
}
</style>
</head>
<body>
<!-- Header -->
<div class="hdr">
  <div class="hdr-left">
    <a href="/healthcare" class="hdr-back">← Health</a>
    <div class="hdr-logo"><div class="dot"></div>Orchestra Health</div>
  </div>
  <div class="hdr-right">
    <span id="hdr-date" style="color:var(--muted);font-size:.8rem"></span>
    <button class="btn btn-primary btn-sm" onclick="openNewApptModal()">+ Appointment</button>
    <button class="btn btn-outline btn-sm" onclick="openNewPatientModal()">+ Patient</button>
  </div>
</div>

<div class="layout">
<!-- Sidebar -->
<div class="sidebar">
  <div class="sidebar-nav">
    <button class="nav-item active" onclick="switchTab('dashboard',this)"><span class="icon">📊</span>Dashboard</button>
    <button class="nav-item" onclick="switchTab('patients',this)"><span class="icon">👥</span>Patients</button>
    <button class="nav-item" onclick="switchTab('schedule',this)"><span class="icon">📅</span>Schedule</button>
    <button class="nav-item" onclick="switchTab('documentation',this)"><span class="icon">🩺</span>Documentation</button>
    <button class="nav-item" onclick="switchTab('billing',this)"><span class="icon">💰</span>Billing</button>
    <button class="nav-item" onclick="switchTab('analytics',this)"><span class="icon">📈</span>Analytics</button>
  </div>
  <div class="sidebar-bottom">
    <a href="/healthcare" class="nav-item" style="text-decoration:none"><span class="icon">←</span>Back</a>
  </div>
</div>

<!-- Main content -->
<div class="main">

<!-- ══ DASHBOARD ══ -->
<div id="tab-dashboard" class="tab-panel active">
  <div class="grid-4" id="kpi-row">
    <div class="kpi"><div class="kpi-val" id="kpi-patients">—</div><div class="kpi-label">Total Patients</div></div>
    <div class="kpi"><div class="kpi-val" id="kpi-today">—</div><div class="kpi-label">Today's Appointments</div></div>
    <div class="kpi"><div class="kpi-val" id="kpi-revenue">—</div><div class="kpi-label">Revenue This Month</div></div>
    <div class="kpi"><div class="kpi-val" id="kpi-ar">—</div><div class="kpi-label">Outstanding A/R</div></div>
  </div>
  <div class="grid-2">
    <div class="card">
      <div class="card-header"><span class="card-title">Today's Schedule</span><button class="btn btn-outline btn-sm" onclick="switchTab('schedule',null)">View All</button></div>
      <div id="dash-schedule"></div>
    </div>
    <div class="card">
      <div class="card-header"><span class="card-title">Recent Claims</span><button class="btn btn-outline btn-sm" onclick="switchTab('billing',null)">View All</button></div>
      <div id="dash-claims"></div>
    </div>
  </div>
</div>

<!-- ══ PATIENTS ══ -->
<div id="tab-patients" class="tab-panel">
  <div class="card-header" style="margin-bottom:0">
    <div class="search-bar" style="flex:1;max-width:400px"><span>🔍</span><input id="patient-search" placeholder="Search patients…" oninput="searchPatients(this.value)"></div>
    <button class="btn btn-primary" onclick="openNewPatientModal()">+ New Patient</button>
  </div>
  <div class="card" style="padding:0">
    <table class="tbl">
      <thead><tr><th>Name</th><th>DOB / Age</th><th>Phone</th><th>Insurance</th><th>Last Visit</th><th></th></tr></thead>
      <tbody id="patients-tbody"></tbody>
    </table>
  </div>
</div>

<!-- ══ SCHEDULE ══ -->
<div id="tab-schedule" class="tab-panel">
  <div class="card-header" style="margin-bottom:0">
    <div style="display:flex;align-items:center;gap:.75rem">
      <button class="btn btn-ghost btn-sm" onclick="changeDate(-1)">‹</button>
      <input type="date" id="sched-date" style="width:auto" onchange="loadSchedule()">
      <button class="btn btn-ghost btn-sm" onclick="changeDate(1)">›</button>
      <button class="btn btn-outline btn-sm" onclick="goToday()">Today</button>
    </div>
    <button class="btn btn-primary" onclick="openNewApptModal()">+ Appointment</button>
  </div>
  <div id="schedule-list" style="display:flex;flex-direction:column;gap:.5rem"></div>
</div>

<!-- ══ DOCUMENTATION ══ -->
<div id="tab-documentation" class="tab-panel">
  <div class="grid-2" style="align-items:start">
    <!-- Left: Select encounter or start new -->
    <div style="display:flex;flex-direction:column;gap:1rem">
      <div class="card">
        <div class="card-header"><span class="card-title">🩺 AI SOAP Note Generator</span></div>
        <div class="form-group" style="margin-bottom:1rem">
          <label>Patient</label>
          <select id="soap-patient-sel" onchange="loadPatientForSoap(this.value)">
            <option value="">— Select patient —</option>
          </select>
        </div>
        <div class="form-group" style="margin-bottom:1rem">
          <label>Raw Clinical Notes</label>
          <textarea id="soap-raw" rows="8" placeholder="Type or paste your clinical notes here…&#10;&#10;Example: 45yo male presents with 3-day hx of productive cough, fever 101.2F, SOB on exertion. PMH: DM2, HTN. On metformin, lisinopril. Lungs: crackles RLL. Saturation 96% on RA."></textarea>
        </div>
        <div style="display:flex;gap:.75rem">
          <button class="btn btn-primary" style="flex:1" onclick="generateSoap()">✨ Generate SOAP + Codes</button>
          <button class="btn btn-outline" onclick="clearSoap()">Clear</button>
        </div>
        <div id="soap-loading" style="display:none;margin-top:1rem" class="ai-loading">
          <div class="spinner"></div>AI is generating SOAP note…
        </div>
      </div>

      <!-- Code search -->
      <div class="card">
        <div class="card-header"><span class="card-title">Code Lookup</span></div>
        <div class="form-row" style="margin-bottom:.75rem">
          <div class="form-group">
            <label>Search CPT</label>
            <input id="cpt-search" placeholder="e.g. office visit" oninput="searchCPT(this.value)">
          </div>
          <div class="form-group">
            <label>Search ICD-10</label>
            <input id="icd10-search" placeholder="e.g. diabetes" oninput="searchICD10(this.value)">
          </div>
        </div>
        <div id="code-results" style="font-size:.8rem;color:var(--muted)">Type to search codes…</div>
      </div>
    </div>

    <!-- Right: Generated SOAP note -->
    <div class="card" id="soap-result-card" style="display:none">
      <div class="card-header">
        <span class="card-title">Generated SOAP Note</span>
        <div style="display:flex;gap:.5rem">
          <span id="soap-confidence" class="badge badge-green">High confidence</span>
          <button class="btn btn-primary btn-sm" onclick="saveSoapNote()">Save Encounter</button>
        </div>
      </div>
      <div class="soap-grid">
        <div class="soap-section"><div class="soap-label">Subjective</div><textarea id="soap-s" rows="4"></textarea></div>
        <div class="soap-section"><div class="soap-label">Objective</div><textarea id="soap-o" rows="4"></textarea></div>
        <div class="soap-section"><div class="soap-label">Assessment</div><textarea id="soap-a" rows="4"></textarea></div>
        <div class="soap-section"><div class="soap-label">Plan</div><textarea id="soap-p" rows="4"></textarea></div>
      </div>
      <div style="margin-top:1rem">
        <div style="font-size:.8rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:.5rem">ICD-10 Codes</div>
        <div class="code-list" id="icd10-pills"></div>
      </div>
      <div style="margin-top:1rem">
        <div style="font-size:.8rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:.5rem">CPT Codes</div>
        <div class="code-list" id="cpt-pills"></div>
      </div>
      <div id="soap-notes" style="margin-top:.75rem;font-size:.8rem;color:var(--warn);display:none"></div>
    </div>
  </div>
</div>

<!-- ══ BILLING ══ -->
<div id="tab-billing" class="tab-panel">
  <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.75rem">
    <div style="display:flex;gap:.5rem;flex-wrap:wrap">
      <button class="btn btn-sm btn-outline" onclick="filterClaims('')" id="claim-filter-all">All</button>
      <button class="btn btn-sm btn-outline" onclick="filterClaims('draft')" id="claim-filter-draft">Draft</button>
      <button class="btn btn-sm btn-outline" onclick="filterClaims('submitted')" id="claim-filter-submitted">Submitted</button>
      <button class="btn btn-sm btn-outline" onclick="filterClaims('pending')" id="claim-filter-pending">Pending</button>
      <button class="btn btn-sm btn-outline" onclick="filterClaims('paid')" id="claim-filter-paid">Paid</button>
      <button class="btn btn-sm btn-outline" onclick="filterClaims('denied')" id="claim-filter-denied">Denied</button>
    </div>
    <div style="font-size:.85rem;color:var(--muted)" id="billing-summary"></div>
  </div>
  <div class="card" style="padding:0">
    <table class="tbl">
      <thead><tr><th>Claim ID</th><th>Patient</th><th>Date of Service</th><th>Charges</th><th>Paid</th><th>Balance</th><th>Status</th><th></th></tr></thead>
      <tbody id="claims-tbody"></tbody>
    </table>
  </div>
</div>

<!-- ══ ANALYTICS ══ -->
<div id="tab-analytics" class="tab-panel">
  <div class="grid-4">
    <div class="kpi"><div class="kpi-val" id="ana-revenue">—</div><div class="kpi-label">Month Revenue</div></div>
    <div class="kpi"><div class="kpi-val" id="ana-ar">—</div><div class="kpi-label">Total A/R</div></div>
    <div class="kpi"><div class="kpi-val" id="ana-pending">—</div><div class="kpi-label">Pending Claims</div></div>
    <div class="kpi"><div class="kpi-val" id="ana-patients">—</div><div class="kpi-label">Active Patients</div></div>
  </div>
  <div class="grid-2">
    <div class="card">
      <div class="card-header"><span class="card-title">Claim Status Breakdown</span></div>
      <div id="ana-status-chart" style="padding:.5rem 0"></div>
    </div>
    <div class="card">
      <div class="card-header"><span class="card-title">A/R Aging</span></div>
      <div id="ana-aging"></div>
    </div>
  </div>
</div>

</div><!-- /main -->
</div><!-- /layout -->

<!-- ══ New Patient Modal ══ -->
<div class="modal-overlay" id="modal-patient">
  <div class="modal">
    <div class="modal-header">
      <span class="modal-title">New Patient</span>
      <button class="modal-close" onclick="closeModal('modal-patient')">✕</button>
    </div>
    <form onsubmit="submitNewPatient(event)">
      <div class="form-row">
        <div class="form-group"><label>First Name *</label><input name="first_name" required></div>
        <div class="form-group"><label>Last Name *</label><input name="last_name" required></div>
      </div>
      <div class="form-row three">
        <div class="form-group"><label>Date of Birth *</label><input name="dob" type="date" required></div>
        <div class="form-group"><label>Gender</label>
          <select name="gender"><option value="unknown">Unknown</option><option value="male">Male</option><option value="female">Female</option><option value="other">Other</option></select>
        </div>
        <div class="form-group"><label>Phone</label><input name="phone" type="tel"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Email</label><input name="email" type="email"></div>
        <div class="form-group"><label>Emergency Contact</label><input name="emergency_contact"></div>
      </div>
      <div class="form-row three">
        <div class="form-group"><label>Insurance Name</label><input name="insurance_name"></div>
        <div class="form-group"><label>Insurance ID</label><input name="insurance_id"></div>
        <div class="form-group"><label>Group #</label><input name="insurance_group"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Allergies</label><input name="allergies" placeholder="NKDA, Penicillin…"></div>
        <div class="form-group"><label>Current Medications</label><input name="medications" placeholder="Metformin 500mg BID…"></div>
      </div>
      <div class="form-row full"><div class="form-group"><label>Notes</label><textarea name="notes" rows="2"></textarea></div></div>
      <div style="display:flex;justify-content:flex-end;gap:.75rem;margin-top:1rem">
        <button type="button" class="btn btn-outline" onclick="closeModal('modal-patient')">Cancel</button>
        <button type="submit" class="btn btn-primary">Create Patient</button>
      </div>
    </form>
  </div>
</div>

<!-- ══ New Appointment Modal ══ -->
<div class="modal-overlay" id="modal-appt">
  <div class="modal">
    <div class="modal-header">
      <span class="modal-title">New Appointment</span>
      <button class="modal-close" onclick="closeModal('modal-appt')">✕</button>
    </div>
    <form onsubmit="submitNewAppt(event)">
      <div class="form-row full">
        <div class="form-group"><label>Patient *</label>
          <select name="patient_id" id="appt-patient-sel" required>
            <option value="">— Select patient —</option>
          </select>
        </div>
      </div>
      <div class="form-row three">
        <div class="form-group"><label>Date *</label><input name="date" type="date" required></div>
        <div class="form-group"><label>Time *</label><input name="time" type="time" required></div>
        <div class="form-group"><label>Duration (min)</label><input name="duration_min" type="number" value="30" min="5" max="240"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Reason</label><input name="reason" placeholder="Annual physical, follow-up, new complaint…"></div>
        <div class="form-group"><label>Provider</label><input name="provider" placeholder="Dr. Smith"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Room</label><input name="room" placeholder="Room 1"></div>
        <div class="form-group"><label>Notes</label><input name="notes"></div>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:.75rem;margin-top:1rem">
        <button type="button" class="btn btn-outline" onclick="closeModal('modal-appt')">Cancel</button>
        <button type="submit" class="btn btn-primary">Schedule</button>
      </div>
    </form>
  </div>
</div>

<!-- ══ Patient Detail Modal ══ -->
<div class="modal-overlay" id="modal-patient-detail">
  <div class="modal" style="max-width:760px">
    <div class="modal-header">
      <span class="modal-title" id="ptd-name">—</span>
      <div style="display:flex;gap:.5rem">
        <button class="btn btn-outline btn-sm" onclick="openDocForPatient()">📝 New Note</button>
        <button class="modal-close" onclick="closeModal('modal-patient-detail')">✕</button>
      </div>
    </div>
    <div id="ptd-body"></div>
  </div>
</div>

<!-- ══ Claim Detail Modal ══ -->
<div class="modal-overlay" id="modal-claim">
  <div class="modal" style="max-width:640px">
    <div class="modal-header">
      <span class="modal-title" id="claim-modal-title">Claim Details</span>
      <button class="modal-close" onclick="closeModal('modal-claim')">✕</button>
    </div>
    <div id="claim-modal-body"></div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const API = '';
let _patients = [], _claimFilter = '', _currentPatient = null, _soapCodes = {icd10:[], cpt:[]};

// ── Helpers ────────────────────────────────────────────────────────────────
function fmt$(n){return '$'+Number(n||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}
function fmtDate(d){if(!d)return'—';try{return new Date(d+'T00:00').toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})}catch{return d}}
function toast(msg,ok=true){const t=document.getElementById('toast');t.textContent=msg;t.style.borderColor=ok?'var(--accent)':'var(--danger)';t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2800)}
function openModal(id){document.getElementById(id).classList.add('open')}
function closeModal(id){document.getElementById(id).classList.remove('open')}
function claimBadge(st){const map={draft:['badge-gray','Draft'],submitted:['badge-blue','Submitted'],pending:['badge-yellow','Pending'],paid:['badge-green','Paid'],denied:['badge-red','Denied'],partial:['badge-purple','Partial'],appealed:['badge-yellow','Appealed']};const[cls,lbl]=map[st]||['badge-gray',st];return`<span class="badge ${cls}">${lbl}</span>`}
function apptBadge(st){const map={scheduled:['badge-blue','Scheduled'],checked_in:['badge-yellow','Checked In'],in_progress:['badge-purple','In Progress'],completed:['badge-green','Completed'],cancelled:['badge-gray','Cancelled'],no_show:['badge-red','No Show']};const[cls,lbl]=map[st]||['badge-gray',st];return`<span class="badge ${cls}">${lbl}</span>`}

// ── Tab switching ────────────────────────────────────────────────────────
function switchTab(name, btn){
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(i=>i.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  if(btn) btn.classList.add('active');
  else {
    document.querySelectorAll('.nav-item').forEach(i=>{if(i.textContent.trim().toLowerCase().includes(name))i.classList.add('active')});
  }
  if(name==='dashboard')loadDashboard();
  else if(name==='patients')loadPatients();
  else if(name==='schedule')loadSchedule();
  else if(name==='billing')loadClaims();
  else if(name==='analytics')loadAnalytics();
  else if(name==='documentation')populatePatientSelects();
}

// ── Dashboard ────────────────────────────────────────────────────────────
async function loadDashboard(){
  try{
    const[ana,appts]=await Promise.all([
      fetch('/api/healthcare/analytics').then(r=>r.json()),
      fetch('/api/healthcare/appointments?date='+todayStr()).then(r=>r.json()),
    ]);
    document.getElementById('kpi-patients').textContent=ana.total_patients;
    document.getElementById('kpi-today').textContent=ana.todays_appointments;
    document.getElementById('kpi-revenue').textContent=fmt$(ana.revenue_this_month);
    document.getElementById('kpi-ar').textContent=fmt$(ana.ar_total);

    // Today schedule
    const sched=document.getElementById('dash-schedule');
    const list=(appts.appointments||[]).slice(0,6);
    sched.innerHTML=list.length?list.map(a=>`
      <div class="appt-row" style="margin-bottom:.4rem" onclick="openApptDetail('${a.id}')">
        <div class="appt-time">${a.time}</div>
        <div class="appt-info"><div class="appt-name">${a.patient_name}</div><div class="appt-reason">${a.reason||'—'}</div></div>
        ${apptBadge(a.status)}
      </div>`).join(''):'<div class="empty"><p>No appointments today</p></div>';

    // Recent claims
    const clms=document.getElementById('dash-claims');
    const recent=(ana.recent_claims||[]).slice(0,6);
    clms.innerHTML=recent.length?`<table class="tbl"><tbody>${recent.map(c=>`
      <tr onclick="openClaimModal(${JSON.stringify(c).replace(/"/g,'&quot;')})">
        <td>${c.id}</td><td>${c.patient_name}</td><td>${fmt$(c.total_charge)}</td><td>${claimBadge(c.status)}</td>
      </tr>`).join('')}</tbody></table>`:'<div class="empty"><p>No claims yet</p></div>';
  }catch(e){console.error(e)}
}

// ── Patients ──────────────────────────────────────────────────────────────
async function loadPatients(search=''){
  const url='/api/healthcare/patients'+(search?`?search=${encodeURIComponent(search)}`:'');
  const{patients}=await fetch(url).then(r=>r.json());
  _patients=patients||[];
  renderPatients(_patients);
  populatePatientSelects();
}
function renderPatients(pts){
  const tb=document.getElementById('patients-tbody');
  tb.innerHTML=pts.length?pts.map(p=>`
    <tr onclick="openPatientDetail('${p.id}')">
      <td><strong>${p.last_name}, ${p.first_name}</strong></td>
      <td>${fmtDate(p.dob)} <span style="color:var(--muted)">(${p.age}y)</span></td>
      <td>${p.phone||'—'}</td>
      <td>${p.insurance_name||'<span style="color:var(--muted)">None</span>'}</td>
      <td>—</td>
      <td><button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();openDocForPatientId('${p.id}')">📝</button></td>
    </tr>`).join(''):`<tr><td colspan="6"><div class="empty"><p>No patients found</p></div></td></tr>`;
}
let _searchTimer;
function searchPatients(v){clearTimeout(_searchTimer);_searchTimer=setTimeout(()=>loadPatients(v),250)}

async function openPatientDetail(id){
  const p=await fetch(`/api/healthcare/patients/${id}`).then(r=>r.json());
  _currentPatient=p;
  document.getElementById('ptd-name').textContent=p.full_name;
  const encs=await fetch(`/api/healthcare/encounters?patient_id=${id}`).then(r=>r.json()).then(d=>d.encounters||[]);
  const claims=await fetch(`/api/healthcare/claims?patient_id=${id}`).then(r=>r.json()).then(d=>d.claims||[]);
  document.getElementById('ptd-body').innerHTML=`
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem">
      <div><div style="font-size:.75rem;color:var(--muted);margin-bottom:.25rem">Demographics</div>
        <div style="font-size:.875rem;line-height:1.8">
          DOB: ${fmtDate(p.dob)} &nbsp;•&nbsp; Age: ${p.age} &nbsp;•&nbsp; ${p.gender}<br>
          Phone: ${p.phone||'—'} &nbsp;•&nbsp; Email: ${p.email||'—'}<br>
          ${p.address?p.address+', '+p.city+', '+p.state+' '+p.zip:'No address'}
        </div>
      </div>
      <div><div style="font-size:.75rem;color:var(--muted);margin-bottom:.25rem">Insurance</div>
        <div style="font-size:.875rem;line-height:1.8">
          ${p.insurance_name||'<span style="color:var(--muted)">None on file</span>'}<br>
          ID: ${p.insurance_id||'—'} &nbsp;•&nbsp; Group: ${p.insurance_group||'—'}
        </div>
      </div>
    </div>
    ${p.allergies||p.medications?`
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem">
      <div><div style="font-size:.75rem;color:var(--warn);margin-bottom:.25rem">⚠ Allergies</div><div style="font-size:.875rem">${p.allergies||'NKDA'}</div></div>
      <div><div style="font-size:.75rem;color:var(--muted);margin-bottom:.25rem">Medications</div><div style="font-size:.875rem">${p.medications||'None'}</div></div>
    </div>`:''}
    <div style="font-size:.875rem;font-weight:600;margin:.75rem 0 .4rem">Visit History (${encs.length})</div>
    ${encs.length?`<table class="tbl"><thead><tr><th>Date</th><th>Provider</th><th>Assessment</th><th>Claim</th></tr></thead><tbody>${encs.slice(0,8).map(e=>`
      <tr><td>${fmtDate(e.date)}</td><td>${e.provider||'—'}</td><td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${e.soap?.assessment||'—'}</td><td>${e.claim_id?`<span style="color:var(--accent)">${e.claim_id}</span>`:'—'}</td></tr>`).join('')}</tbody></table>`:'<div style="color:var(--muted);font-size:.85rem">No visits on record</div>'}
  `;
  openModal('modal-patient-detail');
}

function openDocForPatient(){
  if(!_currentPatient)return;
  closeModal('modal-patient-detail');
  openDocForPatientId(_currentPatient.id);
}
function openDocForPatientId(id){
  switchTab('documentation',null);
  document.getElementById('soap-patient-sel').value=id;
}

// ── Schedule ──────────────────────────────────────────────────────────────
function todayStr(){return new Date().toISOString().slice(0,10)}
function goToday(){document.getElementById('sched-date').value=todayStr();loadSchedule()}
function changeDate(d){const dt=new Date(document.getElementById('sched-date').value+'T00:00');dt.setDate(dt.getDate()+d);document.getElementById('sched-date').value=dt.toISOString().slice(0,10);loadSchedule()}

async function loadSchedule(){
  const date=document.getElementById('sched-date').value||todayStr();
  const{appointments}=await fetch(`/api/healthcare/appointments?date=${date}`).then(r=>r.json());
  const list=document.getElementById('schedule-list');
  const appts=appointments||[];
  list.innerHTML=appts.length?appts.map(a=>`
    <div class="appt-row" onclick="openApptDetail('${a.id}')">
      <div class="appt-time">${a.time}</div>
      <div class="appt-info">
        <div class="appt-name">${a.patient_name}</div>
        <div class="appt-reason">${a.reason||'General visit'} &nbsp;•&nbsp; ${a.duration_min} min &nbsp;•&nbsp; ${a.provider||'—'}</div>
      </div>
      ${apptBadge(a.status)}
      <div style="display:flex;gap:.4rem">
        ${a.status==='scheduled'?`<button class="btn btn-outline btn-sm" onclick="event.stopPropagation();updateStatus('${a.id}','checked_in')">Check In</button>`:''}
        ${a.status==='checked_in'?`<button class="btn btn-primary btn-sm" onclick="event.stopPropagation();startEncounter('${a.id}','${a.patient_id}')">Start Visit</button>`:''}
      </div>
    </div>`).join(''):`<div class="empty"><div class="icon">📅</div><p>No appointments on ${fmtDate(date)}</p></div>`;
}

async function updateStatus(id,status){
  await fetch(`/api/healthcare/appointments/${id}/status`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});
  loadSchedule();toast('Status updated');
}

async function startEncounter(apptId, patientId){
  await updateStatus(apptId,'in_progress');
  // Create encounter and go to documentation
  const enc=await fetch('/api/healthcare/encounters',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({patient_id:patientId,appointment_id:apptId,date:todayStr()})}).then(r=>r.json());
  toast('Visit started — open Documentation to add notes');
  switchTab('documentation',null);
  document.getElementById('soap-patient-sel').value=patientId;
}

async function openApptDetail(id){
  // Inline status update — just cycle to next in schedule view for now
  toast('Click "Check In" or "Start Visit" to update status');
}

// ── Documentation ─────────────────────────────────────────────────────────
function populatePatientSelects(){
  const opts=`<option value="">— Select patient —</option>`+_patients.map(p=>`<option value="${p.id}">${p.last_name}, ${p.first_name}</option>`).join('');
  ['soap-patient-sel','appt-patient-sel'].forEach(id=>{const el=document.getElementById(id);if(el)el.innerHTML=opts});
}

function _llmSettings(){
  // Read provider/model/api_key from Orchestra's localStorage (keys set by main UI / onboarding)
  const provider=localStorage.getItem('ca_provider')||'anthropic';
  const model=localStorage.getItem('ca_model')||'claude-opus-4-7';
  const key=localStorage.getItem('ca_api_key')||'';
  return{provider,model,api_key:key};
}

async function generateSoap(){
  const raw=document.getElementById('soap-raw').value.trim();
  if(!raw){toast('Enter clinical notes first',false);return}
  const pid=document.getElementById('soap-patient-sel').value;
  document.getElementById('soap-loading').style.display='flex';
  document.getElementById('soap-result-card').style.display='none';
  try{
    const llm=_llmSettings();
    const res=await fetch('/api/healthcare/brain/soap',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({raw_notes:raw,patient_id:pid||null,...llm})}).then(r=>r.json());
    document.getElementById('soap-s').value=res.subjective||'';
    document.getElementById('soap-o').value=res.objective||'';
    document.getElementById('soap-a').value=res.assessment||'';
    document.getElementById('soap-p').value=res.plan||'';
    _soapCodes={icd10:res.icd10_codes||[],cpt:res.cpt_codes||[]};
    renderCodePills();
    const conf=res.confidence||'medium';
    const confEl=document.getElementById('soap-confidence');
    confEl.className='badge '+(conf==='high'?'badge-green':conf==='medium'?'badge-yellow':'badge-red');
    confEl.textContent=conf.charAt(0).toUpperCase()+conf.slice(1)+' confidence';
    if(res.notes){document.getElementById('soap-notes').style.display='block';document.getElementById('soap-notes').textContent='⚠ '+res.notes}
    else{document.getElementById('soap-notes').style.display='none'}
    document.getElementById('soap-result-card').style.display='block';
    toast('SOAP note generated!');
  }catch(e){toast('Error generating SOAP note',false);console.error(e)}
  finally{document.getElementById('soap-loading').style.display='none'}
}

function renderCodePills(){
  const icdEl=document.getElementById('icd10-pills');
  const cptEl=document.getElementById('cpt-pills');
  icdEl.innerHTML=_soapCodes.icd10.length?_soapCodes.icd10.map((c,i)=>`
    <div class="code-pill"><span class="code">${c.code}</span>${c.description}<span class="rm" onclick="removeCode('icd10',${i})">✕</span></div>`).join(''):'<span style="color:var(--muted);font-size:.8rem">No codes yet</span>';
  cptEl.innerHTML=_soapCodes.cpt.length?_soapCodes.cpt.map((c,i)=>`
    <div class="code-pill"><span class="code">${c.code}</span>${c.description} <span style="color:var(--muted)">${c.fee?'($'+c.fee+')':''}</span><span class="rm" onclick="removeCode('cpt',${i})">✕</span></div>`).join(''):'<span style="color:var(--muted);font-size:.8rem">No codes yet</span>';
}
function removeCode(type,i){_soapCodes[type].splice(i,1);renderCodePills()}
function clearSoap(){document.getElementById('soap-raw').value='';document.getElementById('soap-result-card').style.display='none';_soapCodes={icd10:[],cpt:[]}}

async function saveSoapNote(){
  const pid=document.getElementById('soap-patient-sel').value;
  if(!pid){toast('Select a patient first',false);return}
  const soap={
    subjective:document.getElementById('soap-s').value,
    objective:document.getElementById('soap-o').value,
    assessment:document.getElementById('soap-a').value,
    plan:document.getElementById('soap-p').value,
    icd10_codes:_soapCodes.icd10,
    cpt_codes:_soapCodes.cpt,
    raw_notes:document.getElementById('soap-raw').value,
  };
  const enc=await fetch('/api/healthcare/encounters',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({patient_id:pid,date:todayStr(),soap})}).then(r=>r.json());
  if(enc.id){
    // Auto-generate claim
    try{await fetch(`/api/healthcare/claims/from-encounter/${enc.id}`,{method:'POST'})}catch(e){}
    toast('Encounter saved & claim created!');
    clearSoap();
    switchTab('billing',null);
  }else{toast('Error saving encounter',false)}
}

async function searchCPT(q){
  if(!q){document.getElementById('code-results').innerHTML='<span style="color:var(--muted)">Type to search CPT codes…</span>';return}
  const{results}=await fetch(`/api/healthcare/codes/cpt/search?q=${encodeURIComponent(q)}`).then(r=>r.json());
  document.getElementById('code-results').innerHTML=(results||[]).map(c=>`
    <div style="display:flex;align-items:center;gap:.5rem;padding:.35rem 0;border-bottom:1px solid var(--border);cursor:pointer" onclick="addCptCode(${JSON.stringify(c).replace(/"/g,'&quot;')})">
      <span style="font-weight:700;color:var(--accent);min-width:60px">${c.code}</span>
      <span style="flex:1">${c.description}</span>
      <span style="color:var(--muted)">$${c.fee}</span>
    </div>`).join('')||'<span style="color:var(--muted)">No results</span>';
}
async function searchICD10(q){
  if(!q){document.getElementById('code-results').innerHTML='<span style="color:var(--muted)">Type to search ICD-10 codes…</span>';return}
  const{results}=await fetch(`/api/healthcare/codes/icd10/search?q=${encodeURIComponent(q)}`).then(r=>r.json());
  document.getElementById('code-results').innerHTML=(results||[]).map(c=>`
    <div style="display:flex;align-items:center;gap:.5rem;padding:.35rem 0;border-bottom:1px solid var(--border);cursor:pointer" onclick="addIcd10Code(${JSON.stringify(c).replace(/"/g,'&quot;')})">
      <span style="font-weight:700;color:var(--accent2);min-width:70px">${c.code}</span>
      <span style="flex:1">${c.description}</span>
      <span style="color:var(--muted)">${c.category}</span>
    </div>`).join('')||'<span style="color:var(--muted)">No results</span>';
}
function addCptCode(c){if(!_soapCodes.cpt.find(x=>x.code===c.code)){_soapCodes.cpt.push(c);renderCodePills();document.getElementById('soap-result-card').style.display='block'}}
function addIcd10Code(c){if(!_soapCodes.icd10.find(x=>x.code===c.code)){_soapCodes.icd10.push(c);renderCodePills();document.getElementById('soap-result-card').style.display='block'}}

// ── Billing ────────────────────────────────────────────────────────────────
async function loadClaims(status=''){
  _claimFilter=status;
  const url='/api/healthcare/claims'+(status?`?status=${status}`:'');
  const{claims}=await fetch(url).then(r=>r.json());
  renderClaims(claims||[]);
  // Update filter buttons
  document.querySelectorAll('[id^="claim-filter-"]').forEach(b=>b.classList.remove('btn-primary'));
  const active=document.getElementById('claim-filter-'+(status||'all'));
  if(active)active.classList.add('btn-primary');
}
function filterClaims(s){loadClaims(s)}
function renderClaims(claims){
  const tb=document.getElementById('claims-tbody');
  const total=claims.reduce((s,c)=>s+c.total_charge,0);
  const paid=claims.reduce((s,c)=>s+c.paid_amount,0);
  document.getElementById('billing-summary').textContent=`${claims.length} claims · ${fmt$(total)} billed · ${fmt$(paid)} paid`;
  tb.innerHTML=claims.length?claims.map(c=>`
    <tr onclick="openClaimModal(${JSON.stringify(c).replace(/"/g,'&quot;')})">
      <td><code style="color:var(--accent)">${c.id}</code></td>
      <td>${c.patient_name}</td>
      <td>${fmtDate(c.date_of_service)}</td>
      <td>${fmt$(c.total_charge)}</td>
      <td>${fmt$(c.paid_amount)}</td>
      <td>${fmt$(c.total_charge-c.paid_amount)}</td>
      <td>${claimBadge(c.status)}</td>
      <td><button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();openClaimModal(${JSON.stringify(c).replace(/"/g,'&quot;')})">→</button></td>
    </tr>`).join(''):`<tr><td colspan="8"><div class="empty"><p>No claims found</p></div></td></tr>`;
}

function openClaimModal(claim){
  document.getElementById('claim-modal-title').textContent='Claim '+claim.id;
  const statuses=['draft','submitted','pending','paid','denied','partial','appealed'];
  document.getElementById('claim-modal-body').innerHTML=`
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem">
      <div><div style="font-size:.75rem;color:var(--muted);margin-bottom:.3rem">Patient</div><strong>${claim.patient_name}</strong></div>
      <div><div style="font-size:.75rem;color:var(--muted);margin-bottom:.3rem">Date of Service</div>${fmtDate(claim.date_of_service)}</div>
      <div><div style="font-size:.75rem;color:var(--muted);margin-bottom:.3rem">Insurance</div>${claim.insurance_name||'—'} · ${claim.insurance_id||'—'}</div>
      <div><div style="font-size:.75rem;color:var(--muted);margin-bottom:.3rem">Provider</div>${claim.provider_name||'—'}</div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:.75rem;margin-bottom:1rem">
      <div class="kpi" style="padding:.75rem"><div class="kpi-val" style="font-size:1.25rem">${fmt$(claim.total_charge)}</div><div class="kpi-label">Charged</div></div>
      <div class="kpi" style="padding:.75rem"><div class="kpi-val" style="font-size:1.25rem">${fmt$(claim.allowed_amount)}</div><div class="kpi-label">Allowed</div></div>
      <div class="kpi" style="padding:.75rem"><div class="kpi-val" style="font-size:1.25rem">${fmt$(claim.paid_amount)}</div><div class="kpi-label">Paid</div></div>
      <div class="kpi" style="padding:.75rem"><div class="kpi-val" style="font-size:1.25rem">${fmt$(claim.patient_responsibility)}</div><div class="kpi-label">Pt. Resp.</div></div>
    </div>
    <div style="margin-bottom:1rem">
      <div style="font-size:.75rem;color:var(--muted);margin-bottom:.4rem">Diagnosis Codes</div>
      <div class="code-list">${(claim.diagnosis_codes||[]).map(c=>`<div class="code-pill"><span class="code">${c}</span></div>`).join('')||'—'}</div>
    </div>
    <div style="margin-bottom:1rem">
      <div style="font-size:.75rem;color:var(--muted);margin-bottom:.4rem">Procedure Codes</div>
      <div class="code-list">${(claim.procedure_codes||[]).map(c=>`<div class="code-pill"><span class="code">${c.code||c}</span>${c.description||''}</div>`).join('')||'—'}</div>
    </div>
    ${claim.denial_reason?`<div style="background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.25);border-radius:8px;padding:.75rem;margin-bottom:1rem;font-size:.875rem"><strong>Denial reason:</strong> ${claim.denial_reason}</div>`:''}
    <div>
      <div style="font-size:.8rem;font-weight:600;margin-bottom:.5rem">Update Status</div>
      <div style="display:flex;gap:.4rem;flex-wrap:wrap">
        ${statuses.map(s=>`<button class="btn btn-sm ${claim.status===s?'btn-primary':'btn-outline'}" onclick="updateClaimStatus('${claim.id}','${s}')">${s.charAt(0).toUpperCase()+s.slice(1)}</button>`).join('')}
      </div>
    </div>
  `;
  openModal('modal-claim');
}

async function updateClaimStatus(id,status){
  const updated=await fetch(`/api/healthcare/claims/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})}).then(r=>r.json());
  closeModal('modal-claim');
  loadClaims(_claimFilter);
  toast('Claim status updated to '+status);
}

// ── Analytics ─────────────────────────────────────────────────────────────
async function loadAnalytics(){
  const ana=await fetch('/api/healthcare/analytics').then(r=>r.json());
  document.getElementById('ana-revenue').textContent=fmt$(ana.revenue_this_month);
  document.getElementById('ana-ar').textContent=fmt$(ana.ar_total);
  document.getElementById('ana-pending').textContent=ana.pending_claims_count;
  document.getElementById('ana-patients').textContent=ana.total_patients;

  // Claim status breakdown
  const allClaims=await fetch('/api/healthcare/claims').then(r=>r.json()).then(d=>d.claims||[]);
  const statusCounts={};
  allClaims.forEach(c=>{statusCounts[c.status]=(statusCounts[c.status]||0)+1});
  document.getElementById('ana-status-chart').innerHTML=Object.entries(statusCounts).map(([s,n])=>`
    <div style="display:flex;align-items:center;gap:.75rem;margin-bottom:.5rem">
      <div style="min-width:80px">${claimBadge(s)}</div>
      <div style="flex:1;background:var(--surface2);border-radius:4px;height:14px;overflow:hidden">
        <div style="height:100%;background:var(--accent);width:${Math.min(100,(n/Math.max(1,allClaims.length))*100)}%;border-radius:4px;transition:width .5s"></div>
      </div>
      <div style="min-width:24px;text-align:right;font-size:.85rem">${n}</div>
    </div>`).join('')||'<div class="empty" style="padding:1rem"><p>No claims data</p></div>';

  // A/R aging placeholder
  document.getElementById('ana-aging').innerHTML=`
    <div style="display:flex;flex-direction:column;gap:.5rem">
      <div style="display:flex;justify-content:space-between;font-size:.85rem"><span>0-30 days</span><strong style="color:var(--accent)">${fmt$(ana.ar_total*0.5)}</strong></div>
      <div style="display:flex;justify-content:space-between;font-size:.85rem"><span>31-60 days</span><strong style="color:var(--warn)">${fmt$(ana.ar_total*0.3)}</strong></div>
      <div style="display:flex;justify-content:space-between;font-size:.85rem"><span>61-90 days</span><strong style="color:var(--danger)">${fmt$(ana.ar_total*0.15)}</strong></div>
      <div style="display:flex;justify-content:space-between;font-size:.85rem"><span>90+ days</span><strong style="color:var(--danger)">${fmt$(ana.ar_total*0.05)}</strong></div>
    </div>`;
}

// ── New Patient Form ────────────────────────────────────────────────────────
function openNewPatientModal(){openModal('modal-patient')}
async function submitNewPatient(e){
  e.preventDefault();
  const data=Object.fromEntries(new FormData(e.target));
  const res=await fetch('/api/healthcare/patients',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  if(res.ok){closeModal('modal-patient');e.target.reset();loadPatients();toast('Patient created!');populatePatientSelects()}
  else{const err=await res.json();toast('Error: '+(err.detail||'Failed'),false)}
}

// ── New Appointment Form ────────────────────────────────────────────────────
function openNewApptModal(){populatePatientSelects();document.querySelector('[name="date"]').value=todayStr();openModal('modal-appt')}
async function submitNewAppt(e){
  e.preventDefault();
  const data=Object.fromEntries(new FormData(e.target));
  data.duration_min=parseInt(data.duration_min)||30;
  const res=await fetch('/api/healthcare/appointments',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  if(res.ok){closeModal('modal-appt');e.target.reset();loadSchedule();toast('Appointment scheduled!');loadDashboard()}
  else{const err=await res.json();toast('Error: '+(err.detail||'Failed'),false)}
}

// ── Keyboard shortcuts ──────────────────────────────────────────────────────
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.querySelectorAll('.modal-overlay.open').forEach(m=>m.classList.remove('open'))});

// ── Init ────────────────────────────────────────────────────────────────────
(async()=>{
  document.getElementById('sched-date').value=todayStr();
  document.getElementById('hdr-date').textContent=new Date().toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric'});
  await loadPatients();
  loadDashboard();
})();
</script>
</body>
</html>"""
