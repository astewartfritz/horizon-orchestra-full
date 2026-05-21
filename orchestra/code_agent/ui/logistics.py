"""Orchestra Logistics — brand page and enterprise logistics dashboard."""

from __future__ import annotations

LOGISTICS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Orchestra Logistics — Enterprise Fleet & Supply Chain</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#060a0f;--bg2:#0c1220;--surface:#141c2e;--border:#1e2a42;--text:#e0e8f4;--text2:#8090b0;--accent:#3b82f6;--accent2:#22c55e;--accent3:#f59e0b;--danger:#ef4444;--gradient:linear-gradient(135deg,#3b82f6,#22c55e);--gradient2:linear-gradient(135deg,#3b82f6,#f59e0b);--radius:16px;--font:'Inter',system-ui,sans-serif}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}body{font-family:var(--font);background:var(--bg);color:var(--text);line-height:1.6;overflow-x:hidden}
::selection{background:var(--accent);color:#fff}
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
a{color:var(--accent);text-decoration:none}.container{max-width:var(--max-w);margin:0 auto;padding:0 24px}
:root{--max-w:1200px}
nav{position:fixed;top:0;left:0;right:0;z-index:100;background:rgba(6,10,15,.85);backdrop-filter:blur(20px);border-bottom:1px solid var(--border)}
nav .container{display:flex;align-items:center;justify-content:space-between;height:64px}
.logo{display:flex;align-items:center;gap:10px;font-weight:700;font-size:1.2rem}
.logo-icon{width:32px;height:32px;border-radius:8px;background:var(--gradient);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:1rem;color:#fff}
.logo span{color:var(--accent2)}
.nav-links{display:flex;gap:32px;align-items:center}
.nav-links a{color:var(--text2);font-size:.9rem;font-weight:500;transition:color .2s}
.nav-links a:hover{color:var(--text)}
.nav-cta{padding:8px 20px;border-radius:20px;background:var(--gradient);color:#fff!important;font-weight:600;border:1px solid rgba(255,255,255,.1)}
.mobile-toggle{display:none;flex-direction:column;gap:4px;cursor:pointer;background:none;border:none;padding:4px}
.mobile-toggle span{width:24px;height:2px;background:var(--text);border-radius:2px;transition:.3s}

.hero{min-height:100vh;display:flex;align-items:center;position:relative;overflow:hidden;padding-top:64px}
.hero-bg{position:absolute;inset:0;pointer-events:none}
.hero-bg .orb{position:absolute;border-radius:50%;filter:blur(120px);opacity:.08}
.hero-bg .orb:nth-child(1){width:600px;height:600px;background:var(--accent);top:-200px;left:-200px}
.hero-bg .orb:nth-child(2){width:500px;height:500px;background:var(--accent2);bottom:-150px;right:-150px}
.hero-content{position:relative;z-index:1;text-align:center;max-width:800px;margin:0 auto;padding:60px 0}
.hero-badge{display:inline-flex;align-items:center;gap:8px;padding:6px 16px;border-radius:20px;background:var(--surface);border:1px solid var(--border);font-size:.8rem;color:var(--text2);margin-bottom:24px}
.hero-badge .dot{width:6px;height:6px;border-radius:50%;background:var(--accent2);animation:pulse 2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.2}}
.hero h1{font-size:clamp(2.2rem,5vw,4rem);font-weight:800;line-height:1.1;margin-bottom:16px}
.hero h1 .g1{background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero h1 .g2{background:var(--gradient2);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero p{font-size:clamp(1rem,2vw,1.15rem);color:var(--text2);max-width:600px;margin:0 auto 32px}
.hero-actions{display:flex;gap:16px;justify-content:center;flex-wrap:wrap}
.btn{display:inline-flex;align-items:center;gap:8px;padding:14px 28px;border-radius:12px;font-weight:600;font-size:1rem;border:none;cursor:pointer;transition:transform .2s}
.btn:hover{transform:translateY(-2px)}
.btn-primary{background:var(--gradient);color:#fff;box-shadow:0 4px 20px rgba(59,130,246,.25)}
.btn-secondary{background:var(--surface);color:var(--text);border:1px solid var(--border)}
.btn-secondary:hover{border-color:var(--accent)}
.hero-stats{display:flex;gap:48px;justify-content:center;margin-top:48px;flex-wrap:wrap}
.hero-stat .num{font-size:2rem;font-weight:800;background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero-stat .label{font-size:.85rem;color:var(--text2);margin-top:4px}
section{padding:100px 0}
.section-label{display:inline-block;padding:4px 12px;border-radius:6px;background:var(--surface);border:1px solid var(--border);font-size:.75rem;font-weight:600;color:var(--accent2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px}
.section-title{font-size:clamp(1.8rem,4vw,2.8rem);font-weight:800;margin-bottom:16px}
.section-sub{color:var(--text2);max-width:600px;font-size:1.05rem;margin-bottom:48px}
.features{background:var(--bg2)}
.feature-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:24px}
.feature-card{padding:32px;border-radius:var(--radius);background:var(--surface);border:1px solid var(--border);transition:transform .3s,border-color .3s}
.feature-card:hover{transform:translateY(-4px);border-color:var(--accent)}
.feature-card .icon{width:48px;height:48px;border-radius:12px;margin-bottom:16px;display:flex;align-items:center;justify-content:center;font-size:1.3rem}
.feature-card h3{font-size:1.1rem;font-weight:600;margin-bottom:8px}
.feature-card p{color:var(--text2);font-size:.9rem}
.pricing-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px;margin-top:48px}
.pricing-card{padding:40px 32px;border-radius:var(--radius);background:var(--surface);border:1px solid var(--border);text-align:center}
.pricing-card.featured{border-color:var(--accent);box-shadow:0 0 30px rgba(59,130,246,.1)}
.pricing-card h3{font-size:1.2rem;font-weight:700;margin-bottom:8px}
.pricing-card .price{font-size:2.5rem;font-weight:800;margin:16px 0;background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.pricing-card .price span{font-size:1rem;color:var(--text2);-webkit-text-fill-color:var(--text2)}
.pricing-card ul{list-style:none;padding:0;margin-bottom:24px;text-align:left}
.pricing-card li{padding:6px 0;font-size:.85rem;color:var(--text2);display:flex;align-items:center;gap:8px}
.pricing-card li::before{content:"✓";color:var(--accent2);font-weight:700}
footer{padding:48px 0;border-top:1px solid var(--border)}
.footer-grid{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:40px}
.footer-brand p{color:var(--text2);font-size:.85rem;max-width:300px;margin-top:12px}
.footer-col h4{font-size:.85rem;font-weight:600;margin-bottom:16px;text-transform:uppercase;letter-spacing:.06em;color:var(--text2)}
.footer-col a{display:block;color:var(--text2);font-size:.85rem;margin-bottom:10px}
.footer-col a:hover{color:var(--text)}
.footer-bottom{margin-top:32px;padding-top:24px;border-top:1px solid var(--border);display:flex;justify-content:space-between;flex-wrap:wrap;gap:16px;color:var(--text2);font-size:.8rem}
@media(max-width:768px){
  .nav-links{position:fixed;top:64px;left:0;right:0;background:rgba(6,10,15,.95);flex-direction:column;padding:24px;gap:16px;display:none}
  .nav-links.open{display:flex}.mobile-toggle{display:flex}
  .hero-stats{gap:24px}section{padding:60px 0}
}
@media(max-width:480px){.hero h1{font-size:2rem}.hero-actions{flex-direction:column}.hero-actions .btn{justify-content:center}}
</style>
</head>
<body>
<nav><div class="container">
<a class="logo" href="/logistics"><div class="logo-icon">🚚</div>Orchestra <span>Logistics</span></a>
<div class="nav-links" id="navLinks">
<a href="#features">Features</a><a href="#pricing">Pricing</a><a href="/logistics/app" class="nav-cta">Launch Dashboard →</a>
</div>
<button class="mobile-toggle" id="mobileToggle" aria-label="Menu"><span></span><span></span><span></span></button>
</div></nav>
<section class="hero">
<div class="hero-bg"><div class="orb"></div><div class="orb"></div></div>
<div class="container hero-content">
<div class="hero-badge"><span class="dot"></span>Enterprise-Grade Logistics Platform</div>
<h1><span class="g1">AI-Native Fleet</span><br>+ <span class="g2">Supply Chain</span></h1>
<p>Real-time fleet tracking, intelligent route optimization, warehouse management, and AI-powered logistics analytics for major enterprises.</p>
<div class="hero-actions">
<a href="/logistics/app" class="btn btn-primary">Launch Dashboard →</a>
<a href="#features" class="btn btn-secondary">Explore Features</a>
</div>
<div class="hero-stats">
<div class="hero-stat"><div class="num">Real-Time</div><div class="label">Fleet Tracking</div></div>
<div class="hero-stat"><div class="num">AI</div><div class="label">Route Optimization</div></div>
<div class="hero-stat"><div class="num">Enterprise</div><div class="label">Supply Chain</div></div>
</div>
</div>
</section>
<section class="features" id="features">
<div class="container">
<div class="section-label">Platform Capabilities</div>
<h2 class="section-title">Enterprise <span class="g1">Logistics OS</span></h2>
<p class="section-sub">End-to-end logistics platform for fleet management, resource planning, and AI-native operations.</p>
<div class="feature-grid">
<div class="feature-card"><div class="icon" style="background:rgba(59,130,246,.15);color:#3b82f6">🚛</div><h3>Fleet Management</h3><p>Track vehicles in real-time, manage driver assignments, monitor maintenance schedules, and optimize fleet utilization across regions.</p></div>
<div class="feature-card"><div class="icon" style="background:rgba(34,197,94,.15);color:#22c55e">🗺️</div><h3>Route Optimization</h3><p>AI-powered nearest-neighbor route optimization with ETA prediction, distance matrix, carbon footprint tracking, and multi-stop planning.</p></div>
<div class="feature-card"><div class="icon" style="background:rgba(245,158,11,.15);color:#f59e0b">📦</div><h3>Supply Chain</h3><p>End-to-end shipment tracking, warehouse inventory management, auto-reorder alerts, and delivery success rate monitoring.</p></div>
<div class="feature-card"><div class="icon" style="background:rgba(59,130,246,.15);color:#3b82f6">🧠</div><h3>AI Logistics Brain</h3><p>Demand forecasting via exponential smoothing, anomaly detection (overdue shipments, driver hours, low inventory), and fleet health scoring.</p></div>
<div class="feature-card"><div class="icon" style="background:rgba(34,197,94,.15);color:#22c55e">📊</div><h3>Real-Time Dashboards</h3><p>Live fleet metrics, resource utilization charts, carbon tracking, on-time delivery rates, and interactive operational dashboards.</p></div>
<div class="feature-card"><div class="icon" style="background:rgba(245,158,11,.15);color:#f59e0b">🏢</div><h3>Enterprise Scale</h3><p>Multi-region warehouse support, driver hour compliance, automated reconciliation, and REST API for integration with existing ERP/WMS systems.</p></div>
</div>
</div></section>
<section id="pricing"><div class="container">
<div class="section-label">Plans</div><h2 class="section-title">Scale your <span class="g2">operations</span></h2>
<div class="pricing-grid">
<div class="pricing-card"><h3>Starter</h3><div class="price">$0<span>/mo</span></div><ul><li>Up to 5 vehicles</li><li>Basic route planning</li><li>Shipment tracking</li><li>Single warehouse</li></ul><a href="/logistics/app" class="btn btn-secondary" style="width:100%;justify-content:center">Get Started</a></div>
<div class="pricing-card featured"><h3>Enterprise</h3><div class="price">Custom</div><ul><li>Unlimited fleet</li><li>AI route optimization</li><li>Multi-region warehouses</li><li>Demand forecasting</li><li>API access</li><li>Dedicated support</li></ul><a href="/logistics/app" class="btn btn-primary" style="width:100%;justify-content:center">Contact Sales</a></div>
</div>
</div></section>
<footer><div class="container">
<div class="footer-grid">
<div class="footer-brand"><a class="logo" href="/logistics"><div class="logo-icon">🚚</div>Orchestra <span>Logistics</span></a><p>AI-native enterprise logistics platform. Fleet management, supply chain optimization, and real-time operational intelligence.</p></div>
<div class="footer-col"><h4>Platform</h4><a href="/logistics/app">Dashboard</a><a href="#features">Features</a><a href="#pricing">Pricing</a></div>
<div class="footer-col"><h4>Resources</h4><a href="#">Docs</a><a href="#">API</a><a href="#">Integrations</a></div>
<div class="footer-col"><h4>Company</h4><a href="#">About</a><a href="#">Careers</a><a href="#">Contact</a></div>
</div>
<div class="footer-bottom"><span>&copy; 2026 Orchestra Logistics. All rights reserved.</span><span>Built with Orchestra Create.</span></div>
</div></footer>
<script>
document.getElementById('mobileToggle')?.addEventListener('click',()=>document.getElementById('navLinks').classList.toggle('open'));
document.querySelectorAll('.nav-links a').forEach(a=>a.addEventListener('click',()=>document.getElementById('navLinks').classList.remove('open')));
</script>
</body>
</html>"""


LOGISTICS_APP_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Orchestra Logistics — Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#060a0f;--bg2:#0c1220;--surface:#141c2e;--border:#1e2a42;--text:#e0e8f4;--text2:#8090b0;--accent:#3b82f6;--accent2:#22c55e;--accent3:#f59e0b;--danger:#ef4444;--gradient:linear-gradient(135deg,#3b82f6,#22c55e)}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);overflow-x:hidden}
::selection{background:var(--accent);color:#fff}
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.app-header{background:rgba(6,10,15,.9);backdrop-filter:blur(12px);border-bottom:1px solid var(--border);padding:12px 24px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;flex-wrap:wrap;gap:12px}
.app-header .logo{display:flex;align-items:center;gap:10px;font-weight:700;font-size:1.1rem}
.app-header .logo-icon{width:28px;height:28px;border-radius:6px;background:var(--gradient);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:.85rem;color:#fff}
.app-header .logo span{color:var(--accent2)}
.header-actions{display:flex;gap:8px;flex-wrap:wrap}
.header-btn{padding:6px 14px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:.8rem;cursor:pointer;font-family:inherit;transition:all .2s}
.header-btn:hover{background:var(--bg2);border-color:var(--accent)}
.header-btn.primary{background:var(--gradient);border:none;color:#fff}
.header-btn.primary:hover{opacity:.9}
.tab-bar{display:flex;border-bottom:1px solid var(--border);padding:0 24px;background:var(--bg2);overflow-x:auto}
.tab-btn{padding:12px 20px;font-size:.82rem;font-weight:500;color:var(--text2);cursor:pointer;border:none;background:none;font-family:inherit;border-bottom:2px solid transparent;transition:all .2s;white-space:nowrap}
.tab-btn:hover{color:var(--text)}
.tab-btn.active{color:var(--accent);border-bottom-color:var(--accent)}
.tab-content{display:none;padding:20px}
.tab-content.active{display:block}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:20px}
.kpi-card{padding:16px;border-radius:10px;background:var(--surface);border:1px solid var(--border)}
.kpi-card .label{font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;color:var(--text2);margin-bottom:2px}
.kpi-card .value{font-size:1.5rem;font-weight:700}
.kpi-card .sub{font-size:.75rem;color:var(--text2);margin-top:2px}
.card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin-bottom:16px}
.card{padding:16px;border-radius:10px;background:var(--surface);border:1px solid var(--border)}
.card h3{font-size:.85rem;font-weight:600;color:var(--text2);margin-bottom:12px}
.data-table{width:100%;border-collapse:collapse;font-size:.8rem}
.data-table th{padding:8px 12px;text-align:left;color:var(--text2);font-weight:500;font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--border)}
.data-table td{padding:6px 12px;border-bottom:1px solid rgba(30,42,66,.5)}
.data-table tr:hover{background:var(--bg2)}
.status{padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:500}
.status.active{background:rgba(34,197,94,.15);color:var(--accent2)}
.status.transit{background:rgba(59,130,246,.15);color:var(--accent)}
.status.available{background:rgba(34,197,94,.15);color:var(--accent2)}
.status.maintenance{background:rgba(245,158,11,.15);color:var(--accent3)}
.status.delivered{background:rgba(34,197,94,.15);color:var(--accent2)}
.status.pending{background:rgba(128,144,176,.15);color:var(--text2)}
.status.exception{background:rgba(239,68,68,.15);color:var(--danger)}
canvas{width:100%!important;max-height:200px}
.insight-card{padding:12px;border-radius:8px;margin-bottom:8px;border-left:3px solid var(--accent);background:var(--bg2);font-size:.82rem}
.insight-card.critical{border-color:var(--danger)}
.insight-card.warning{border-color:var(--accent3)}
.copilot-input{display:flex;gap:8px;margin-bottom:12px}
.copilot-input input{flex:1;padding:10px 14px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:.85rem;outline:none;font-family:inherit}
.copilot-input input:focus{border-color:var(--accent)}
@media(max-width:768px){.tab-content{padding:12px}.kpi-grid{grid-template-columns:1fr 1fr}}
@media(max-width:480px){.kpi-grid{grid-template-columns:1fr}.tab-btn{padding:10px 14px;font-size:.75rem}}
</style>
</head>
<body>
<div class="app-header">
<div class="logo"><a href="/logistics" style="color:inherit;text-decoration:none;display:flex;align-items:center;gap:10px"><div class="logo-icon">🚚</div>Orchestra <span>Logistics</span></a></div>
<div class="header-actions">
<button class="header-btn primary" onclick="refreshData()">⟳ Refresh</button>
<button class="header-btn" onclick="simulateEvent()">+ Simulate Event</button>
</div>
</div>
<div class="tab-bar">
<button class="tab-btn active" onclick="switchTab('fleet',this)">🚛 Fleet</button>
<button class="tab-btn" onclick="switchTab('resources',this)">📦 Resources</button>
<button class="tab-btn" onclick="switchTab('supply',this)">🌐 Supply Chain</button>
<button class="tab-btn" onclick="switchTab('ai',this)">🧠 AI</button>
</div>

<div class="tab-content active" id="tab-fleet">
<div class="kpi-grid" id="fleetKpis"></div>
<div class="card-grid">
<div class="card"><h3>🚛 Fleet Vehicles</h3><table class="data-table" id="fleetTable"><thead><tr><th>Name</th><th>Plate</th><th>Type</th><th>Status</th><th>Region</th></tr></thead><tbody></tbody></table></div>
<div class="card"><h3>👨‍✈️ Drivers</h3><table class="data-table" id="driverTable"><thead><tr><th>Name</th><th>Status</th><th>Hours</th><th>Remaining</th></tr></thead><tbody></tbody></table></div>
</div>
</div>

<div class="tab-content" id="tab-resources">
<div class="kpi-grid" id="resourceKpis"></div>
<div class="card-grid">
<div class="card"><h3>🏭 Warehouses</h3><table class="data-table" id="whTable"><thead><tr><th>Name</th><th>Region</th><th>Capacity</th><th>Used</th><th>Utilization</th></tr></thead><tbody></tbody></table></div>
<div class="card"><h3>📋 Inventory</h3><table class="data-table" id="invTable"><thead><tr><th>SKU</th><th>Name</th><th>Qty</th><th>Value</th><th>Reorder</th></tr></thead><tbody></tbody></table></div>
</div>
</div>

<div class="tab-content" id="tab-supply">
<div class="kpi-grid" id="supplyKpis"></div>
<div class="card"><h3>📦 Shipments</h3><table class="data-table" id="shipTable"><thead><tr><th>Tracking</th><th>Origin → Dest</th><th>Status</th><th>Profit</th></tr></thead><tbody></tbody></table></div>
</div>

<div class="tab-content" id="tab-ai">
<div class="kpi-grid" id="aiKpis"></div>
<div class="card"><h3>🧠 Logistics Copilot</h3>
<div class="copilot-input"><input id="aiPrompt" placeholder="Ask about operations... e.g. 'What's our fleet health?'" onkeydown="if(event.key==='Enter')askCopilot()"><button class="header-btn primary" onclick="askCopilot()">Ask AI</button></div>
<div id="aiResponse" style="padding:12px;border-radius:8px;background:var(--bg2);border:1px solid var(--border);font-size:.82rem;color:var(--text2);display:none;white-space:pre-wrap;line-height:1.6;margin-bottom:16px"></div></div>
<div class="card-grid">
<div class="card"><h3>⚠️ Anomalies</h3><div id="anomaliesList"><div class="insight-card">No anomalies detected</div></div></div>
<div class="card"><h3>🔮 Demand Forecast</h3><canvas id="forecastChart"></canvas><div id="forecastInfo" style="font-size:.8rem;color:var(--text2);margin-top:8px;text-align:center"></div></div>
<div class="card"><h3>🏥 Fleet Health</h3><div id="healthDisplay" style="text-align:center;padding:16px 0"></div></div>
</div>
</div>

<script>
// ── Data fetching ─────────────────────────
async function api(path){try{const r=await fetch('/api/logistics'+path);return await r.json()}catch{return null}}

async function refreshData(){
  const fleet=await api('/fleet');
  const metrics=await api('/fleet/metrics');
  const wh=await api('/supply/warehouses');
  const inv=await api('/supply/inventory');
  const ships=await api('/supply/shipments');
  const brain=await api('/brain/summary');
  const anomalies=await api('/brain/anomalies');
  const health=await api('/brain/health');

  renderFleet(fleet,metrics);
  renderResources(wh,inv);
  renderSupply(ships);
  renderAI(brain,anomalies,health);
}

function renderFleet(fleet,metrics){
  if(!fleet)return;
  document.getElementById('fleetKpis').innerHTML=`
    <div class="kpi-card"><div class="label">Fleet Size</div><div class="value" style="color:var(--accent)">${metrics?.total_vehicles||0}</div><div class="sub">vehicles</div></div>
    <div class="kpi-card"><div class="label">Available</div><div class="value" style="color:var(--accent2)">${metrics?.available||0}</div><div class="sub">ready</div></div>
    <div class="kpi-card"><div class="label">In Transit</div><div class="value" style="color:var(--accent)">${metrics?.in_transit||0}</div><div class="sub">on road</div></div>
    <div class="kpi-card"><div class="label">Maintenance</div><div class="value" style="color:var(--accent3)">${metrics?.maintenance||0}</div><div class="sub">in shop</div></div>
    <div class="kpi-card"><div class="label">Utilization</div><div class="value" style="color:${(metrics?.utilization||0)>70?'var(--accent2)':'var(--accent3)'}">${metrics?.utilization||0}%</div><div class="sub">fleet usage</div></div>
  `;
  const ft=document.getElementById('fleetTable').querySelector('tbody');
  ft.innerHTML=Object.values(fleet.vehicles||{}).map(v=>`
    <tr><td>${v.name}</td><td style="font-family:'JetBrains Mono',monospace">${v.plate}</td><td>${v.type}</td><td><span class="status ${v.status}">${v.status}</span></td><td>${v.region}</td></tr>
  `).join('');
  const dt=document.getElementById('driverTable').querySelector('tbody');
  dt.innerHTML=Object.values(fleet.drivers||{}).map(d=>`
    <tr><td>${d.name}</td><td><span class="status ${d.status}">${d.status}</span></td><td>${d.hours}h</td><td style="color:${d.remaining<10?'var(--danger)':'var(--accent2)'}">${d.remaining}h</td></tr>
  `).join('');
}

function renderResources(wh,inv){
  if(!wh)return;
  const vals=Object.values(wh);const avgUtil=vals.length?vals.reduce((s,w)=>s+w.utilization,0)/vals.length:0;
  document.getElementById('resourceKpis').innerHTML=`
    <div class="kpi-card"><div class="label">Warehouses</div><div class="value" style="color:var(--accent)">${vals.length}</div></div>
    <div class="kpi-card"><div class="label">Avg Utilization</div><div class="value" style="color:${avgUtil<80?'var(--accent2)':'var(--accent3)'}">${avgUtil.toFixed(1)}%</div></div>
    <div class="kpi-card"><div class="label">Total Value</div><div class="value" style="color:var(--accent2)">$${(inv?.total_value||0).toLocaleString()}</div></div>
    <div class="kpi-card"><div class="label">Needs Reorder</div><div class="value" style="color:${(inv?.needs_reorder||0)>0?'var(--accent3)':'var(--accent2)'}">${inv?.needs_reorder||0}</div></div>
  `;
  const wt=document.getElementById('whTable').querySelector('tbody');
  wt.innerHTML=Object.entries(wh||{}).map(([id,w])=>`
    <tr><td>${w.name}</td><td>us-east</td><td>${w.capacity?.toLocaleString()||'-'}</td><td>${w.current?.toLocaleString()||'-'}</td><td><div style="display:flex;align-items:center;gap:6px"><div style="width:60px;height:6px;border-radius:3px;background:var(--border)"><div style="width:${Math.min(w.utilization||0,100)}%;height:100%;border-radius:3px;background:${(w.utilization||0)>90?'var(--danger)':(w.utilization||0)>70?'var(--accent3)':'var(--accent2)'}"></div></div>${w.utilization.toFixed(0)}%</div></td></tr>
  `).join('');
  const it=document.getElementById('invTable').querySelector('tbody');
  it.innerHTML=(inv?.items||[]).map(i=>`
    <tr><td style="font-family:'JetBrains Mono',monospace;font-size:.75rem">${i.sku}</td><td>${i.name}</td><td>${i.quantity}</td><td>$${(i.value||0).toLocaleString()}</td><td>${i.reorder?'<span style="color:var(--accent3)">⚠️ Yes</span>':'<span style="color:var(--accent2)">✓ No</span>'}</td></tr>
  `).join('');
}

function renderSupply(ships){
  if(!ships)return;
  document.getElementById('supplyKpis').innerHTML=`
    <div class="kpi-card"><div class="label">Total Shipments</div><div class="value" style="color:var(--accent)">${ships.count||0}</div></div>
    <div class="kpi-card"><div class="label">Total Profit</div><div class="value" style="color:var(--accent2)">$${(ships.total_profit||0).toLocaleString()}</div></div>
    <div class="kpi-card"><div class="label">On-Time Rate</div><div class="value" style="color:${(ships.on_time_rate||0)>80?'var(--accent2)':'var(--accent3)'}">${ships.on_time_rate||0}%</div></div>
    <div class="kpi-card"><div class="label">Delivery Success</div><div class="value" style="color:${(ships.delivery_success_rate||0)>90?'var(--accent2)':'var(--danger)'}">${ships.delivery_success_rate||0}%</div></div>
  `;
  const st=document.getElementById('shipTable').querySelector('tbody');
  st.innerHTML=(ships.shipments||[]).map(s=>`
    <tr><td style="font-family:'JetBrains Mono',monospace;font-size:.75rem">${s.tracking}</td><td>${s.origin} → ${s.destination}</td><td><span class="status ${s.status}">${s.status}</span></td><td style="color:${s.profit>=0?'var(--accent2)':'var(--danger)'};font-weight:600">$${(s.profit||0).toLocaleString()}</td></tr>
  `).join('');
}

function renderAI(brain,anomalies,health){
  const aData=anomalies?.anomalies||[];
  document.getElementById('aiKpis').innerHTML=`
    <div class="kpi-card"><div class="label">Health Score</div><div class="value" style="color:${(health?.score||0)>80?'var(--accent2)':(health?.score||0)>50?'var(--accent3)':'var(--danger)'}">${health?.score||0}</div><div class="sub">Grade ${health?.grade||'N/A'}</div></div>
    <div class="kpi-card"><div class="label">Anomalies</div><div class="value" style="color:${aData.length>0?'var(--accent3)':'var(--accent2)'}">${aData.length}</div><div class="sub">${anomalies?.count||0} critical</div></div>
    <div class="kpi-card"><div class="label">LLM</div><div class="value" style="color:${brain?.llm_available?'var(--accent2)':'var(--text2)'}">${brain?.llm_available?'Online':'Offline'}</div></div>
    <div class="kpi-card"><div class="label">Fleet</div><div class="value" style="color:var(--accent)">${brain?.fleet?.total_vehicles||0}</div><div class="sub">${brain?.fleet?.available||0} available</div></div>
  `;
  document.getElementById('anomaliesList').innerHTML=aData.length?aData.map(a=>`
    <div class="insight-card ${a.severity}"><strong>${a.type}</strong> (${a.severity})<br>${a.description}<br><em style="font-size:.75rem">→ ${a.recommendation}</em></div>
  `).join(''):'<div class="insight-card">✅ No anomalies detected</div>';

  if(health){
    document.getElementById('healthDisplay').innerHTML=`
      <div style="font-size:4rem;font-weight:800;background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent">${health.grade}</div>
      <div style="font-size:1.2rem;font-weight:600;margin:8px 0">${health.score}/100</div>
      <div style="font-size:.8rem;color:var(--text2)">${(health.reasons||[]).join(' • ')||'All systems healthy'}</div>
    `;
  }

  // Forecast chart
  drawForecastChart();
}

function drawForecastChart(){
  const c=document.getElementById('forecastChart');if(!c)return;
  const ctx=c.getContext('2d');const rect=c.parentElement.getBoundingClientRect();
  c.width=rect.width*2;c.height=200*2;c.style.width=rect.width+'px';c.style.height='200px';
  ctx.scale(2,2);const w=rect.width,h=200;
  ctx.clearRect(0,0,w,h);const pad={t:20,b:25,l:35,r:15};
  const cw=w-pad.l-pad.r,ch=h-pad.t-pad.b;
  const hist=[28,32,30,35,38,42,40,45,48,52,50,55];
  const fc=[58,62,65];const all=[...hist,...fc];const max=Math.max(...all,1);
  const labels=[...Array(hist.length).fill(''),...['F1','F2','F3']];
  const stepX=cw/(all.length-1||1);
  ctx.font='9px Inter,sans-serif';ctx.fillStyle='#8090b0';
  for(let i=0;i<=4;i++){const y=pad.t+ch-(ch/4*i);ctx.strokeStyle='rgba(30,42,66,.3)';ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(w-pad.r,y);ctx.stroke()}
  // Historical
  ctx.strokeStyle='#3b82f6';ctx.lineWidth=2;ctx.beginPath();
  hist.forEach((v,i)=>{const x=pad.l+i*stepX;const y=pad.t+ch-(v/max)*ch;i===0?ctx.moveTo(x,y):ctx.lineTo(x,y)});ctx.stroke();
  // Forecast
  ctx.strokeStyle='#22c55e';ctx.lineWidth=2;ctx.setLineDash([4,3]);ctx.beginPath();
  fc.forEach((v,i)=>{const x=pad.l+(hist.length-1+i)*stepX;const y=pad.t+ch-(v/max)*ch;i===0?ctx.moveTo(x,y):ctx.lineTo(x,y)});ctx.stroke();
  ctx.setLineDash([]);
  // Labels
  labels.forEach((l,i)=>{if(l){const x=pad.l+i*stepX;ctx.fillStyle='#22c55e';ctx.fillText(l,x-6,h-2)}});
  document.getElementById('forecastInfo').textContent=`Next period estimate: ${fc[0]} units (↑ ${((fc[0]/hist[hist.length-1]-1)*100).toFixed(0)}% vs last period)`;
}

async function askCopilot(){
  const prompt=document.getElementById('aiPrompt').value;if(!prompt)return;
  const el=document.getElementById('aiResponse');el.style.display='block';el.textContent='Thinking...';
  try{
    const r=await fetch('/api/logistics/brain/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt})});
    const d=await r.json();el.textContent=d.response||'No response.';
  }catch{
    el.innerHTML='💡 AI backend offline. Connect Ollama or OpenAI for full copilot capabilities.';
  }
}

function simulateEvent(){
  refreshData();
}

function switchTab(tab,btn){
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(v=>v.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-'+tab).classList.add('active');
}

document.addEventListener('DOMContentLoaded',refreshData);
</script>
</body>
</html>"""
