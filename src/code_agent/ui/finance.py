"""Orchestra Finance — brand page and interactive dashboard + spreadsheet app."""

from __future__ import annotations

FINANCE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Orchestra Finance — Dashboards & Spreadsheets</title>
<meta name="description" content="Build interactive finance dashboards and intelligent spreadsheets with AI.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#06080e;--bg2:#0c0f18;--bg3:#141828;--surface:#1a1f2e;--border:#2a3045;--text:#e8ecf4;--text2:#8890a8;--accent:#4f8cff;--accent2:#34d399;--accent3:#f472b6;--danger:#ef4444;--warning:#f59e0b;--gradient:linear-gradient(135deg,#4f8cff,#34d399);--gradient2:linear-gradient(135deg,#4f8cff,#f472b6);--radius:16px;--radius-sm:8px;--max-w:1200px;--font:'Inter',system-ui,-apple-system,sans-serif;--mono:'JetBrains Mono',monospace}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:var(--font);background:var(--bg);color:var(--text);line-height:1.6;overflow-x:hidden}
::selection{background:var(--accent);color:#fff}
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
a{color:var(--accent);text-decoration:none}.container{max-width:var(--max-w);margin:0 auto;padding:0 24px}

/* Nav */
nav{position:fixed;top:0;left:0;right:0;z-index:100;background:rgba(6,8,14,.85);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-bottom:1px solid var(--border)}
nav .container{display:flex;align-items:center;justify-content:space-between;height:64px}
.logo{display:flex;align-items:center;gap:10px;font-weight:700;font-size:1.2rem}
.logo-icon{width:32px;height:32px;border-radius:8px;background:var(--gradient);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:1rem;color:#fff}
.logo span{color:var(--accent2)}
.nav-links{display:flex;gap:32px;align-items:center}
.nav-links a{color:var(--text2);font-size:.9rem;font-weight:500;transition:color .2s}
.nav-links a:hover{color:var(--text)}
.nav-cta{padding:8px 20px;border-radius:20px;background:var(--gradient);color:#fff!important;font-weight:600;font-size:.85rem;transition:transform .2s,box-shadow .2s}
.nav-cta:hover{transform:translateY(-1px);box-shadow:0 4px 20px rgba(79,140,255,.3)}
.mobile-toggle{display:none;flex-direction:column;gap:4px;cursor:pointer;background:none;border:none;padding:4px}
.mobile-toggle span{width:24px;height:2px;background:var(--text);border-radius:2px;transition:.3s}

/* Hero */
.hero{min-height:100vh;display:flex;align-items:center;position:relative;overflow:hidden;padding-top:64px}
.hero-bg{position:absolute;inset:0;overflow:hidden;pointer-events:none}
.hero-bg .orb{position:absolute;border-radius:50%;filter:blur(100px);opacity:.1}
.hero-bg .orb:nth-child(1){width:500px;height:500px;background:var(--accent);top:-150px;left:-100px}
.hero-bg .orb:nth-child(2){width:400px;height:400px;background:var(--accent2);bottom:-100px;right:-100px}
.hero-content{position:relative;z-index:1;text-align:center;max-width:800px;margin:0 auto;padding:60px 0}
.hero-badge{display:inline-flex;align-items:center;gap:8px;padding:6px 16px;border-radius:20px;background:var(--surface);border:1px solid var(--border);font-size:.8rem;color:var(--text2);margin-bottom:24px}
.hero-badge .dot{width:6px;height:6px;border-radius:50%;background:var(--accent2);animation:pulse 2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.hero h1{font-size:clamp(2.5rem,6vw,4.2rem);font-weight:800;line-height:1.1;margin-bottom:16px;letter-spacing:-.02em}
.hero h1 .g1{background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.hero h1 .g2{background:var(--gradient2);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.hero p{font-size:clamp(1rem,2vw,1.15rem);color:var(--text2);max-width:600px;margin:0 auto 32px}
.hero-actions{display:flex;gap:16px;justify-content:center;flex-wrap:wrap}
.btn{display:inline-flex;align-items:center;gap:8px;padding:14px 28px;border-radius:12px;font-weight:600;font-size:1rem;border:none;cursor:pointer;transition:transform .2s,box-shadow .2s}
.btn:hover{transform:translateY(-2px)}
.btn-primary{background:var(--gradient);color:#fff;box-shadow:0 4px 20px rgba(79,140,255,.25)}
.btn-primary:hover{box-shadow:0 8px 30px rgba(79,140,255,.35)}
.btn-secondary{background:var(--surface);color:var(--text);border:1px solid var(--border)}
.btn-secondary:hover{background:var(--bg3);border-color:var(--accent)}
.hero-stats{display:flex;gap:48px;justify-content:center;margin-top:48px;flex-wrap:wrap}
.hero-stat{text-align:center}
.hero-stat .num{font-size:2rem;font-weight:800;background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.hero-stat .label{font-size:.85rem;color:var(--text2);margin-top:4px}

/* Sections */
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

/* Dashboard Preview */
.dashboard-preview{margin-top:48px;border-radius:var(--radius);overflow:hidden;border:1px solid var(--border);box-shadow:0 20px 60px rgba(0,0,0,.3)}
.dashboard-preview img{width:100%;display:block}

/* Pricing */
.pricing-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}
.pricing-card{padding:40px 32px;border-radius:var(--radius);background:var(--surface);border:1px solid var(--border);text-align:center;position:relative;transition:transform .3s,border-color .3s}
.pricing-card:hover{transform:translateY(-4px)}
.pricing-card.featured{border-color:var(--accent);box-shadow:0 0 30px rgba(79,140,255,.1)}
.pricing-card .popular{position:absolute;top:-12px;left:50%;transform:translateX(-50%);padding:4px 16px;border-radius:12px;background:var(--gradient);color:#fff;font-size:.75rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em}
.pricing-card h3{font-size:1.2rem;font-weight:700;margin-bottom:8px}
.pricing-card .price{font-size:3rem;font-weight:800;margin:16px 0 8px;background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.pricing-card .price span{font-size:1rem;font-weight:400;color:var(--text2);-webkit-text-fill-color:var(--text2)}
.pricing-card .desc{color:var(--text2);font-size:.85rem;margin-bottom:24px;min-height:40px}
.pricing-card ul{list-style:none;padding:0;margin-bottom:32px;text-align:left}
.pricing-card li{padding:8px 0;font-size:.85rem;color:var(--text2);display:flex;align-items:center;gap:8px}
.pricing-card li::before{content:"✓";color:var(--accent2);font-weight:700}

/* Footer */
footer{padding:48px 0;border-top:1px solid var(--border)}
.footer-grid{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:40px}
@media(max-width:768px){.footer-grid{grid-template-columns:1fr 1fr}}
.footer-brand p{color:var(--text2);font-size:.85rem;max-width:300px;margin-top:12px}
.footer-col h4{font-size:.85rem;font-weight:600;margin-bottom:16px;text-transform:uppercase;letter-spacing:.06em;color:var(--text2)}
.footer-col a{display:block;color:var(--text2);font-size:.85rem;margin-bottom:10px;transition:color .2s}
.footer-col a:hover{color:var(--text)}
.footer-bottom{margin-top:32px;padding-top:24px;border-top:1px solid var(--border);display:flex;justify-content:space-between;flex-wrap:wrap;gap:16px;color:var(--text2);font-size:.8rem}

@media(max-width:768px){
  .nav-links{position:fixed;top:64px;left:0;right:0;background:rgba(6,8,14,.95);flex-direction:column;padding:24px;gap:16px;border-bottom:1px solid var(--border);display:none}
  .nav-links.open{display:flex}.mobile-toggle{display:flex}
  .hero-stats{gap:24px}section{padding:60px 0}
}
@media(max-width:480px){
  .hero h1{font-size:2rem}.hero-actions{flex-direction:column;align-items:stretch}
  .hero-actions .btn{justify-content:center}
}
</style>
</head>
<body>
<!-- Nav -->
<nav>
<div class="container">
<a class="logo" href="/finance"><div class="logo-icon">$</div>Orchestra <span>Finance</span></a>
<div class="nav-links" id="navLinks">
<a href="#features">Features</a><a href="#pricing">Pricing</a><a href="/finance/app" class="nav-cta">Launch App →</a>
</div>
<button class="mobile-toggle" id="mobileToggle" aria-label="Menu"><span></span><span></span><span></span></button>
</div>
</nav>
<!-- Hero -->
<section class="hero">
<div class="hero-bg"><div class="orb"></div><div class="orb"></div></div>
<div class="container hero-content">
<div class="hero-badge"><span class="dot"></span>Now in Early Access</div>
<h1><span class="g1">Finance Dashboards</span><br>+ <span class="g2">Smart Spreadsheets</span></h1>
<p>Build interactive finance dashboards with real-time charts, and manipulate data in an intelligent spreadsheet — all powered by AI.</p>
<div class="hero-actions">
<a href="/finance/app" class="btn btn-primary">Launch Dashboard →</a>
<a href="#features" class="btn btn-secondary">Learn More</a>
</div>
<div class="hero-stats">
<div class="hero-stat"><div class="num">Real-Time</div><div class="label">Charts & Metrics</div></div>
<div class="hero-stat"><div class="num">Smart</div><div class="label">Spreadsheet Engine</div></div>
<div class="hero-stat"><div class="num">AI</div><div class="label">Automatic Insights</div></div>
</div>
</div>
</section>
<!-- Features -->
<section class="features" id="features">
<div class="container">
<div class="section-label">Capabilities</div>
<h2 class="section-title">Dashboards + <span class="g1">Spreadsheets</span></h2>
<p class="section-sub">Everything you need to track, analyze, and present financial data.</p>
<div class="feature-grid">
<div class="feature-card"><div class="icon" style="background:rgba(79,140,255,.15);color:#4f8cff">📊</div><h3>Interactive Dashboards</h3><p>Bar charts, line charts, pie charts, and KPI cards — all rendered live with Canvas API. No external dependencies.</p></div>
<div class="feature-card"><div class="icon" style="background:rgba(52,211,153,.15);color:#34d399">📝</div><h3>Smart Spreadsheet</h3><p>Full-featured spreadsheet with cell editing, formula support (SUM, AVG, MAX, MIN), and keyboard navigation.</p></div>
<div class="feature-card"><div class="icon" style="background:rgba(244,114,182,.15);color:#f472b6">📈</div><h3>Financial KPIs</h3><p>Revenue, expenses, profit margins, cash flow, and burn rate — calculated automatically from your data.</p></div>
<div class="feature-card"><div class="icon" style="background:rgba(79,140,255,.15);color:#4f8cff">📂</div><h3>Export & Share</h3><p>Export spreadsheets as CSV, print dashboards, and share financial reports with your team.</p></div>
<div class="feature-card"><div class="icon" style="background:rgba(52,211,153,.15);color:#34d399">🔄</div><h3>Live Updates</h3><p>Data changes in the spreadsheet automatically update dashboard charts and KPI cards in real-time.</p></div>
<div class="feature-card"><div class="icon" style="background:rgba(244,114,182,.15);color:#f472b6">🔒</div><h3>Local-First</h3><p>All data stays in your browser. No servers, no uploads, no privacy concerns. Works fully offline.</p></div>
</div>
</div>
</section>
<!-- Pricing -->
<section id="pricing">
<div class="container">
<div class="section-label">Pricing</div>
<h2 class="section-title">Plans for <span class="g2">every team</span></h2>
<p class="section-sub">Start free, scale as you grow.</p>
<div class="pricing-grid">
<div class="pricing-card"><h3>Starter</h3><div class="price">$0<span>/mo</span></div><div class="desc">For individuals exploring finance tracking.</div><ul><li>1 dashboard</li><li>Basic spreadsheet</li><li>3 chart types</li><li>CSV export</li></ul><a href="/finance/app" class="btn btn-secondary" style="width:100%;justify-content:center">Get Started</a></div>
<div class="pricing-card featured"><div class="popular">Popular</div><h3>Pro</h3><div class="price">$19<span>/mo</span></div><div class="desc">For professionals and small teams.</div><ul><li>Unlimited dashboards</li><li>Advanced formulas</li><li>All chart types</li><li>AI-powered insights</li><li>Data import (CSV/JSON)</li></ul><a href="/finance/app" class="btn btn-primary" style="width:100%;justify-content:center">Start Free Trial</a></div>
<div class="pricing-card"><h3>Enterprise</h3><div class="price">$99<span>/mo</span></div><div class="desc">For organizations with advanced needs.</div><ul><li>Everything in Pro</li><li>Multi-user collaboration</li><li>Custom integrations</li><li>API access</li><li>Priority support</li></ul><a href="#" class="btn btn-secondary" style="width:100%;justify-content:center">Contact Sales</a></div>
</div>
</div>
</section>
<!-- Footer -->
<footer>
<div class="container">
<div class="footer-grid">
<div class="footer-brand"><a class="logo" href="/finance"><div class="logo-icon">$</div>Orchestra <span>Finance</span></a><p>Build finance dashboards and smart spreadsheets with AI. From tracking to insights — orchestrate your financial data.</p></div>
<div class="footer-col"><h4>Product</h4><a href="#features">Features</a><a href="/finance/app">Dashboard</a><a href="#pricing">Pricing</a></div>
<div class="footer-col"><h4>Resources</h4><a href="#">Docs</a><a href="#">API</a><a href="#">Templates</a></div>
<div class="footer-col"><h4>Company</h4><a href="#">About</a><a href="#">Blog</a><a href="#">Contact</a></div>
</div>
<div class="footer-bottom"><span>&copy; 2026 Orchestra Finance. All rights reserved.</span><span>Built with Orchestra Create.</span></div>
</div>
</footer>
<script>
document.getElementById('mobileToggle')?.addEventListener('click',()=>document.getElementById('navLinks').classList.toggle('open'));
document.querySelectorAll('.nav-links a').forEach(a=>a.addEventListener('click',()=>document.getElementById('navLinks').classList.remove('open')));
</script>
</body>
</html>"""


FINANCE_APP_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Orchestra Finance — Dashboard + Spreadsheet</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#06080e;--bg2:#0c0f18;--surface:#1a1f2e;--border:#2a3045;--text:#e8ecf4;--text2:#8890a8;--accent:#4f8cff;--accent2:#34d399;--accent3:#f472b6;--danger:#ef4444;--warning:#f59e0b;--gradient:linear-gradient(135deg,#4f8cff,#34d399)}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);overflow-x:hidden}
::selection{background:var(--accent);color:#fff}
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}

/* App Header */
.app-header{background:rgba(6,8,14,.9);backdrop-filter:blur(12px);border-bottom:1px solid var(--border);padding:12px 24px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;flex-wrap:wrap;gap:12px}
.app-header .logo{display:flex;align-items:center;gap:10px;font-weight:700;font-size:1.1rem}
.app-header .logo-icon{width:28px;height:28px;border-radius:6px;background:var(--gradient);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:.85rem;color:#fff}
.app-header .logo span{color:var(--accent2)}
.app-header .header-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.header-btn{padding:6px 14px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:.8rem;cursor:pointer;transition:all .2s;font-family:inherit;display:flex;align-items:center;gap:6px}
.header-btn:hover{background:var(--bg2);border-color:var(--accent)}
.header-btn.primary{background:var(--gradient);border:none;color:#fff}
.header-btn.primary:hover{opacity:.9}

/* Tabs */
.tab-bar{display:flex;gap:0;border-bottom:1px solid var(--border);padding:0 24px;background:var(--bg2)}
.tab-btn{padding:12px 24px;font-size:.85rem;font-weight:500;color:var(--text2);cursor:pointer;border:none;background:none;font-family:inherit;border-bottom:2px solid transparent;transition:all .2s}
.tab-btn:hover{color:var(--text)}
.tab-btn.active{color:var(--accent);border-bottom-color:var(--accent)}

/* Dashboard */
.dashboard{display:none;padding:24px}
.dashboard.active{display:block}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-bottom:24px}
.kpi-card{padding:20px;border-radius:12px;background:var(--surface);border:1px solid var(--border)}
.kpi-card .label{font-size:.75rem;text-transform:uppercase;letter-spacing:.06em;color:var(--text2);margin-bottom:4px}
.kpi-card .value{font-size:1.8rem;font-weight:700}
.kpi-card .change{font-size:.8rem;margin-top:4px}
.kpi-card .change.up{color:var(--accent2)}
.kpi-card .change.down{color:var(--danger)}
.chart-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px;margin-bottom:24px}
.chart-card{padding:20px;border-radius:12px;background:var(--surface);border:1px solid var(--border)}
.chart-card h3{font-size:.85rem;font-weight:600;margin-bottom:16px;color:var(--text2)}
.chart-card canvas{width:100%!important;height:auto!important;max-height:250px}

/* Transactions Table */
.transactions{background:var(--surface);border-radius:12px;border:1px solid var(--border);overflow:hidden}
.transactions .header{padding:16px 20px;border-bottom:1px solid var(--border);font-weight:600;font-size:.9rem;display:flex;justify-content:space-between;align-items:center}
.transactions .header .count{color:var(--text2);font-weight:400;font-size:.8rem}
.transactions table{width:100%;border-collapse:collapse;font-size:.85rem}
.transactions th{padding:12px 20px;text-align:left;color:var(--text2);font-weight:500;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border)}
.transactions td{padding:10px 20px;border-bottom:1px solid var(--border)}
.transactions tr:hover{background:var(--bg2)}
.tag{padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:500}
.tag.income{background:rgba(52,211,153,.15);color:var(--accent2)}
.tag.expense{background:rgba(239,68,68,.15);color:var(--danger)}
.tag.investment{background:rgba(245,158,11,.15);color:var(--warning)}

/* Spreadsheet */
.spreadsheet-view{display:none;padding:24px}
.spreadsheet-view.active{display:block}
.sheet-bar{display:flex;gap:8px;margin-bottom:12px;align-items:center;flex-wrap:wrap}
.sheet-bar .info{color:var(--text2);font-size:.8rem;margin-left:auto}
.sheet-container{overflow:auto;border:1px solid var(--border);border-radius:8px;background:var(--surface);max-height:70vh}
.sheet-container table{border-collapse:collapse;width:100%;min-width:800px;font-size:.82rem;font-family:'JetBrains Mono',monospace}
.sheet-container th,.sheet-container td{border:1px solid var(--border);padding:6px 10px;min-width:100px;position:relative}
.sheet-container th{background:var(--bg2);color:var(--text2);font-weight:500;font-size:.75rem;position:sticky;top:0;z-index:2;text-align:center;font-family:'Inter',sans-serif}
.sheet-container td{color:var(--text)}
.sheet-container td:focus{outline:2px solid var(--accent);outline-offset:-2px;background:rgba(79,140,255,.1)}
.sheet-container td.active{outline:2px solid var(--accent);outline-offset:-2px;background:rgba(79,140,255,.1)}
.sheet-container td .formula-bar{display:none}
.sheet-container .row-header{min-width:40px;text-align:center;color:var(--text2);font-size:.75rem;background:var(--bg2);font-family:'Inter',sans-serif;font-weight:500;position:sticky;left:0;z-index:1}
.sheet-toolbar{display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap;align-items:center}
.sheet-toolbar .formula-input{flex:1;padding:8px 12px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-family:'JetBrains Mono',monospace;font-size:.8rem;outline:none;min-width:200px}
.sheet-toolbar .formula-input:focus{border-color:var(--accent)}
.sheet-toolbar .cell-ref{color:var(--accent2);font-family:'JetBrains Mono',monospace;font-size:.8rem;padding:8px 12px;background:var(--surface);border-radius:6px;border:1px solid var(--border);min-width:80px;text-align:center}

/* Empty state */
.empty-state{padding:40px;text-align:center;color:var(--text2)}
.empty-state .icon{font-size:3rem;margin-bottom:12px}

/* Responsive */
@media(max-width:768px){
  .dashboard,.spreadsheet-view{padding:12px}
  .kpi-grid{grid-template-columns:1fr 1fr}
  .chart-grid{grid-template-columns:1fr}
  .sheet-container{font-size:.75rem}
  .sheet-container td,.sheet-container th{padding:4px 6px;min-width:70px}
}
@media(max-width:480px){
  .kpi-grid{grid-template-columns:1fr}
  .app-header .header-actions .header-btn{font-size:.75rem;padding:4px 10px}
}
</style>
</head>
<body>
<div class="app-header">
<div class="logo"><a href="/finance" style="color:inherit;text-decoration:none;display:flex;align-items:center;gap:10px"><div class="logo-icon">$</div>Orchestra <span>Finance</span></a></div>
<div class="header-actions">
<button class="header-btn" onclick="addTransaction()">+ Add Transaction</button>
<button class="header-btn" onclick="exportCSV()">↓ Export CSV</button>
<button class="header-btn primary" onclick="resetData()">⟳ Reset</button>
</div>
</div>
<div class="tab-bar">
<button class="tab-btn active" onclick="switchTab('dashboard',this)">📊 Dashboard</button>
<button class="tab-btn" onclick="switchTab('spreadsheet',this)">📝 Spreadsheet</button>
<button class="tab-btn" onclick="switchTab('insights',this)">🧠 Insights</button>
</div>

<!-- Dashboard Tab -->
<div class="dashboard active" id="tab-dashboard">
<div class="kpi-grid" id="kpiGrid"></div>
<div class="chart-grid">
<div class="chart-card"><h3>📊 Monthly Revenue vs Expenses</h3><canvas id="chartRevenue"></canvas></div>
<div class="chart-card"><h3>🥧 Expense Breakdown</h3><canvas id="chartExpenses"></canvas></div>
<div class="chart-card"><h3>📈 Profit Trend (6 Months)</h3><canvas id="chartProfit"></canvas></div>
</div>
<div class="transactions">
<div class="header">Recent Transactions <span class="count" id="txCount">0 entries</span></div>
<table><thead><tr><th>Date</th><th>Description</th><th>Category</th><th>Type</th><th style="text-align:right">Amount</th></tr></thead><tbody id="txBody"></tbody></table>
</div>
</div>

<!-- Spreadsheet Tab -->
<div class="spreadsheet-view" id="tab-spreadsheet">
<div class="sheet-toolbar">
<span class="cell-ref" id="cellRef">A1</span>
<input class="formula-input" id="formulaInput" placeholder="Enter value or formula (e.g. =SUM(A1:A5))" onkeydown="handleFormulaKey(event)">
<button class="header-btn" onclick="addRow()">+ Row</button>
<button class="header-btn" onclick="addCol()">+ Col</button>
</div>
<div class="sheet-container" id="sheetContainer"></div>
<div class="sheet-bar">
<span style="color:var(--text2);font-size:.8rem">Formulas: =SUM(), =AVG(), =MAX(), =MIN(), =COUNT(), =AI_PROJECT(), =EXPLAIN_VARIANCE(), =FORECAST(), =RISK_ANALYSIS() — click any cell to edit</span>
</div>
</div>

<!-- Insights Tab -->
<div class="spreadsheet-view" id="tab-insights">
<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px">
<div class="chart-card" style="grid-column:1/-1"><h3>🧠 CFO Copilot</h3>
<div style="display:flex;gap:8px;margin-top:12px">
<input id="aiPrompt" style="flex:1;padding:10px 14px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:.85rem;outline:none;font-family:inherit" placeholder="Ask a financial question... e.g. 'What is our profit trend?'">
<button class="header-btn primary" onclick="askCopilot()">Ask AI</button>
</div>
<div id="aiResponse" style="margin-top:12px;padding:16px;border-radius:8px;background:var(--bg2);border:1px solid var(--border);color:var(--text2);font-size:.85rem;display:none;white-space:pre-wrap;line-height:1.6"></div>
</div>
<div class="chart-card"><h3>📊 AI Insights</h3><div id="insightsList"></div></div>
<div class="chart-card"><h3>📈 What-If Scenarios</h3><div id="scenariosList"></div></div>
</div>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px">
<div class="chart-card"><h3>🔮 Forecast</h3><p style="color:var(--text2);font-size:.8rem;margin:8px 0">Next 3 months revenue projection</p><div id="forecastValue" style="font-size:1.8rem;font-weight:700;color:var(--accent2)">—</div></div>
<div class="chart-card"><h3>⚠️ Risk Analysis</h3><p style="color:var(--text2);font-size:.8rem;margin:8px 0">Value at Risk (95% confidence)</p><div id="riskValue" style="font-size:1.8rem;font-weight:700;color:var(--danger)">—</div></div>
<div class="chart-card"><h3>💡 AI Formulas</h3><p style="color:var(--text2);font-size:.8rem;margin:8px 0">Try in any spreadsheet cell:</p>
<code style="display:block;padding:8px;border-radius:4px;background:var(--bg2);font-size:.75rem;margin:4px 0;color:var(--accent)">=AI_PROJECT("revenue","growth",horizon=12)</code>
<code style="display:block;padding:8px;border-radius:4px;background:var(--bg2);font-size:.75rem;margin:4px 0;color:var(--accent2)">=EXPLAIN_VARIANCE(A1,B1)</code>
<code style="display:block;padding:8px;border-radius:4px;background:var(--bg2);font-size:.75rem;margin:4px 0;color:var(--accent3)">=FORECAST("revenue",6)</code>
</div>
</div>
</div>

<script>
// ── Sample Data ──────────────────────────────
const CATEGORIES = ['Product','Engineering','Marketing','Sales','Operations','Design','Support'];
const TYPES = ['income','expense','investment'];
const DESCRIPTIONS = ['Monthly subscription revenue','Cloud hosting','Salary payments','Ad campaign','Consulting fee','Software licenses','Office rent','Contractor payment','SaaS revenue','Freelance project'];

let transactions = [
  {date:'2026-05-01',desc:'Monthly subscription revenue',cat:'Product',type:'income',amount:45000},
  {date:'2026-05-02',desc:'Cloud hosting (AWS)',cat:'Engineering',type:'expense',amount:3200},
  {date:'2026-05-03',desc:'Marketing campaign',cat:'Marketing',type:'expense',amount:5800},
  {date:'2026-05-04',desc':'Consulting project',cat:'Sales',type:'income',amount:12000},
  {date:'2026-05-05',desc':'Office rent',cat:'Operations',type:'expense',amount:4000},
  {date:'2026-05-06',desc':'Software licenses',cat:'Engineering',type:'expense',amount:2100},
  {date:'2026-05-07',desc':'Design contractor',cat:'Design',type:'expense',amount:3500},
  {date:'2026-05-08',desc':'Ad revenue',cat:'Marketing',type:'income',amount:6800},
  {date:'2026-05-09',desc':'Salary payments',cat:'Operations',type:'expense',amount:22000},
  {date:'2026-05-10',desc':'Investment round',cat:'Product',type:'investment',amount:150000},
  {date:'2026-05-11',desc':'Freelance project',cat:'Sales',type:'income',amount:8500},
  {date:'2026-05-12',desc':'Support tooling',cat:'Support',type:'expense',amount:1200},
];

let sheetData = [
  ['Category','Jan','Feb','Mar','Apr','May','Jun','Total'],
  ['Revenue','42000','45000','48000','51000','53800','45000',''],
  ['Expenses','28000','29500','31000','33800','35800','3200',''],
  ['Profit','14000','15500','17000','17200','18000','41800',''],
  ['Burn Rate','12000','12500','13000','13500','14000','14500',''],
  ['Cash Reserve','320000','307500','294500','280700','266700','252200',''],
];

const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun'];

// ── AI-native formula support ──────────────
const AI_FUNCTIONS = {
  AI_PROJECT: (args) => `[AI Projection: ${args[0]||'?'} under '${args[1]||'default'}' horizon=${args.find(a=>a.includes('horizon='))?.split('=')[1]||12}mo]`,
  EXPLAIN_VARIANCE: (args) => `[Variance Analysis: ${args[0]||'actual'} vs ${args[1]||'forecast'} — delta=${((parseFloat(args[0])||0)-(parseFloat(args[1])||0)).toFixed(2)}]`,
  FORECAST: (args) => `[Forecast: ${args[0]||'metric'} over ${args[1]||'3'} periods]`,
  RISK_ANALYSIS: (args) => `[Risk: VaR(95)=${((parseFloat(args[0])||100000)*0.15).toFixed(0)} on portfolio $${(parseFloat(args[0])||0).toLocaleString()}]`,
};

// ── Render KPI ───────────────────────────────
function calcKPIs(){
  const income = transactions.filter(t=>t.type==='income').reduce((s,t)=>s+t.amount,0);
  const expenses = transactions.filter(t=>t.type==='expense').reduce((s,t)=>s+t.amount,0);
  const profit = income - expenses;
  const margin = income>0?(profit/income*100):0;
  return {income,expenses,profit,margin:margin.toFixed(1),count:transactions.length};
}
function renderKPIs(){
  const k = calcKPIs();
  document.getElementById('kpiGrid').innerHTML=`
    <div class="kpi-card"><div class="label">Total Revenue</div><div class="value" style="color:var(--accent2)">$${k.income.toLocaleString()}</div><div class="change up">↑ 12.3% vs last period</div></div>
    <div class="kpi-card"><div class="label">Total Expenses</div><div class="value" style="color:var(--danger)">$${k.expenses.toLocaleString()}</div><div class="change up">↑ 8.1% vs last period</div></div>
    <div class="kpi-card"><div class="label">Net Profit</div><div class="value" style="color:${k.profit>=0?'var(--accent2)':'var(--danger)'}">$${k.profit.toLocaleString()}</div><div class="change ${k.profit>=0?'up':'down'}">Margin ${k.margin}%</div></div>
    <div class="kpi-card"><div class="label">Cash Flow</div><div class="value" style="color:var(--accent)">$${(k.income*0.6).toLocaleString()}</div><div class="change up">Operating cash flow</div></div>
  `;
}

// ── Charts (Canvas) ──────────────────────────
function drawBarChart(id,labels,data,color){
  const c=document.getElementById(id);if(!c)return;
  const ctx=c.getContext('2d');const dpr=window.devicePixelRatio||1;
  const rect=c.parentElement.getBoundingClientRect();
  c.width=rect.width*dpr;c.height=250*dpr;c.style.width=rect.width+'px';c.style.height='250px';
  ctx.scale(dpr,dpr);const w=rect.width,h=250;
  ctx.clearRect(0,0,w,h);
  const pad={t:20,b:30,l:40,r:20};const cw=w-pad.l-pad.r,ch=h-pad.t-pad.b;
  const max=Math.max(...data,1);const bw=cw/data.length*0.6;const gap=cw/data.length*0.4;
  ctx.font='10px Inter,sans-serif';ctx.fillStyle='#8890a8';
  // Grid lines
  for(let i=0;i<=4;i++){const y=pad.t+ch-(ch/4*i);ctx.strokeStyle='rgba(42,48,69,.5)';ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(w-pad.r,y);ctx.stroke();ctx.fillText('$'+(max/4*i).toLocaleString(),2,y+3)}
  data.forEach((v,i)=>{
    const x=pad.l+i*(bw+gap);const bh=(v/max)*ch;
    const g=ctx.createLinearGradient(x,pad.t+ch,x,pad.t+ch-bh);
    g.addColorStop(0,color);g.addColorStop(1,color+'40');
    ctx.fillStyle=g;ctx.beginPath();ctx.roundRect(x,pad.t+ch-bh,bw,bh,4);ctx.fill();
    ctx.fillStyle='#8890a8';ctx.textAlign='center';ctx.fillText(labels[i]||'',x+bw/2,h-5);
  });
}
function drawPieChart(id,data,labels,colors){
  const c=document.getElementById(id);if(!c)return;
  const ctx=c.getContext('2d');const dpr=window.devicePixelRatio||1;
  const rect=c.parentElement.getBoundingClientRect();
  c.width=rect.width*dpr;c.height=250*dpr;c.style.width=rect.width+'px';c.style.height='250px';
  ctx.scale(dpr,dpr);const w=rect.width,h=250;
  ctx.clearRect(0,0,w,h);
  const cx=w/2-60,cy=h/2,r=Math.min(cx,cy)-20;
  const total=data.reduce((a,b)=>a+b,0);let start=-Math.PI/2;
  data.forEach((v,i)=>{
    const angle=(v/total)*Math.PI*2;
    ctx.fillStyle=colors[i];ctx.beginPath();ctx.moveTo(cx,cy);ctx.arc(cx,cy,r,start,start+angle);ctx.closePath();ctx.fill();
    start+=angle;
  });
  // Legend
  let ly=30;const lx=w-120;
  labels.forEach((l,i)=>{
    ctx.fillStyle=colors[i];ctx.fillRect(lx,ly,10,10);
    ctx.fillStyle='#8890a8';ctx.font='11px Inter,sans-serif';ctx.fillText(l+' ('+Math.round(data[i]/total*100)+'%)',lx+16,ly+9);ly+=20;
  });
}
function drawLineChart(id,labels,datasets){
  const c=document.getElementById(id);if(!c)return;
  const ctx=c.getContext('2d');const dpr=window.devicePixelRatio||1;
  const rect=c.parentElement.getBoundingClientRect();
  c.width=rect.width*dpr;c.height=250*dpr;c.style.width=rect.width+'px';c.style.height='250px';
  ctx.scale(dpr,dpr);const w=rect.width,h=250;
  ctx.clearRect(0,0,w,h);
  const pad={t:20,b:30,l:40,r:20};const cw=w-pad.l-pad.r,ch=h-pad.t-pad.b;
  let allVals=[];datasets.forEach(d=>allVals=allVals.concat(d.data));
  const max=Math.max(...allVals,1);const min=0;const range=max-min;
  const stepX=cw/(labels.length-1||1);
  ctx.font='10px Inter,sans-serif';ctx.fillStyle='#8890a8';
  for(let i=0;i<=4;i++){const y=pad.t+ch-(ch/4*i);ctx.strokeStyle='rgba(42,48,69,.3)';ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(w-pad.r,y);ctx.stroke();ctx.fillText('$'+(range/4*i).toLocaleString(),2,y+3)}
  labels.forEach((l,i)=>ctx.fillText(l,pad.l+i*stepX-10,h-5));
  datasets.forEach((ds,di)=>{
    ctx.strokeStyle=ds.color;ctx.lineWidth=2;ctx.beginPath();
    ds.data.forEach((v,i)=>{const x=pad.l+i*stepX;const y=pad.t+ch-((v-min)/range)*ch;i===0?ctx.moveTo(x,y):ctx.lineTo(x,y)});ctx.stroke();
    // Dots
    ds.data.forEach((v,i)=>{const x=pad.l+i*stepX;const y=pad.t+ch-((v-min)/range)*ch;ctx.fillStyle=ds.color;ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fill()});
  });
}

function updateCharts(){
  const rev=[],exp=[],profit=[];
  MONTHS.forEach((_,i)=>{
    const base=i*7000+38000;const baseE=i*3000+26000;
    rev.push(base+Math.round(Math.random()*6000));
    exp.push(baseE+Math.round(Math.random()*3000));
    profit.push(rev[i]-exp[i]);
  });
  drawBarChart('chartRevenue',MONTHS,rev,'#4f8cff');
  drawPieChart('chartExpenses',[35,25,20,12,8],['Engineering','Marketing','Operations','Sales','Design'],['#4f8cff','#34d399','#f472b6','#f59e0b','#a78bfa']);
  drawLineChart('chartProfit',MONTHS,[{data:profit,color:'#34d399'}]);
}

// ── Transactions ─────────────────────────────
function renderTransactions(){
  const body=document.getElementById('txBody');
  document.getElementById('txCount').textContent=transactions.length+' entries';
  body.innerHTML=transactions.slice(0,15).map(t=>`
    <tr><td>${t.date}</td><td>${t.desc}</td><td>${t.cat}</td><td><span class="tag ${t.type}">${t.type}</span></td><td style="text-align:right;font-family:'JetBrains Mono',monospace;font-weight:600;color:${t.type==='expense'?'var(--danger)':t.type==='income'?'var(--accent2)':'var(--warning)'}">${t.type==='expense'?'-':''}$${t.amount.toLocaleString()}</td></tr>
  `).join('');
}

function addTransaction(){
  const d=new Date();const date=d.toISOString().slice(0,10);
  transactions.unshift({date,desc:DESCRIPTIONS[Math.floor(Math.random()*DESCRIPTIONS.length)],cat:CATEGORIES[Math.floor(Math.random()*CATEGORIES.length)],type:TYPES[Math.floor(Math.random()*TYPES.length)],amount:Math.round(Math.random()*30000+500)});
  renderAll();
}

// ── Spreadsheet ──────────────────────────────
let selectedCell=null;

function renderSpreadsheet(){
  const c=document.getElementById('sheetContainer');
  let html='<table><thead><tr><th class="row-header"></th>';
  const cols=['A','B','C','D','E','F','G','H','I','J','K','L'];
  sheetData[0].forEach((_,i)=>{html+=`<th>${cols[i]||'?'}</th>`});
  html+='</tr></thead><tbody>';
  sheetData.forEach((row,ri)=>{
    html+=`<tr><td class="row-header">${ri+1}</td>`;
    row.forEach((cell,ci)=>{
      const ref=cols[ci]+(ri+1);
      const val=ri===0?cell:(evalCell(cell,ri,ci));
      const isFormula=String(cell).startsWith('=');
      html+=`<td contenteditable="${ri>0}" data-ref="${ref}" data-row="${ri}" data-col="${ci}" data-raw="${cell}" onfocus="onCellFocus(this,'${ref}')" onblur="onCellBlur(this,${ri},${ci})" onkeydown="onCellKeydown(event,this,${ri},${ci})">${val}</td>`;
    });
    html+='</tr>';
  });
  html+='</tbody></table>';
  c.innerHTML=html;
}

function evalCell(raw,ri,ci){
  if(ri===0||!raw||!String(raw).startsWith('='))return raw||'';
  const formula=String(raw).substring(1);
  try{
    // AI-native formulas
    const aiMatch=formula.match(/^(AI_PROJECT|EXPLAIN_VARIANCE|FORECAST|RISK_ANALYSIS)\((.+)\)$/i);
    if(aiMatch){
      const fn=aiMatch[1].toUpperCase();
      const args=splitArgs(aiMatch[2]);
      if(AI_FUNCTIONS[fn])return AI_FUNCTIONS[fn](args);
    }
    // Standard range formulas
    const fn=formula.match(/^(SUM|AVG|MAX|MIN|COUNT|STDEV)\(([A-Z]+)(\d+):([A-Z]+)(\d+)\)$/i);
    if(fn){
      const op=fn[1].toUpperCase();const c1=colIdx(fn[2]),r1=parseInt(fn[3])-1,c2=colIdx(fn[4]),r2=parseInt(fn[5])-1;
      const vals=[];
      for(let r=r1;r<=r2;r++){for(let c=c1;c<=c2;c++){const v=parseFloat(sheetData[r]?.[c])||0;vals.push(v)}}
      if(op==='SUM')return fmt(vals.reduce((a,b)=>a+b,0));
      if(op==='AVG')return vals.length?fmt(vals.reduce((a,b)=>a+b,0)/vals.length):'0';
      if(op==='MAX')return vals.length?fmt(Math.max(...vals)):'0';
      if(op==='MIN')return vals.length?fmt(Math.min(...vals)):'0';
      if(op==='COUNT')return vals.length;
      if(op==='STDEV')return vals.length>1?fmt(Math.sqrt(vals.reduce((s,v)=>s+(v-vals.reduce((a,b)=>a+b,0)/vals.length)**2,0)/(vals.length-1))):'0';
    }
    return formula;
  }catch(e){return '#ERR'}
}

function splitArgs(s){
  const args=[];let depth=0,cur='';
  for(const ch of s){if(ch==='(')depth++;if(ch===')')depth--;if(ch===','&&depth===0){args.push(cur.trim());cur=''}else cur+=ch}
  if(cur.trim())args.push(cur.trim());
  return args;
}

function colIdx(c){return c.toUpperCase().charCodeAt(0)-65}
function fmt(n){return Number(n.toFixed(2)).toLocaleString()}

function onCellFocus(el,ref){
  document.getElementById('cellRef').textContent=ref;
  document.getElementById('formulaInput').value=el.getAttribute('data-raw')||'';
  selectedCell=el;
}
function onCellBlur(el,ri,ci){
  const val=el.textContent.trim();
  sheetData[ri][ci]=val;
  el.setAttribute('data-raw',val);
  renderAll();
}
function onCellKeydown(e,el,ri,ci){
  if(e.key==='Enter'){e.preventDefault();el.blur();return}
  if(e.key==='Tab'){e.preventDefault();const next=document.querySelector(`[data-row="${ri}"][data-col="${ci+1}"]`);next?.focus()}
}

function handleFormulaKey(e){
  if(e.key==='Enter'&&selectedCell){
    selectedCell.textContent=e.target.value;
    const ri=parseInt(selectedCell.getAttribute('data-row'));
    const ci=parseInt(selectedCell.getAttribute('data-col'));
    sheetData[ri][ci]=e.target.value;
    selectedCell.setAttribute('data-raw',e.target.value);
    renderAll();
    selectedCell.focus();
  }
}

function addRow(){sheetData.push([...Array(sheetData[0].length)].map(()=>''));renderSpreadsheet();updateChartsFromSheet()}
function addCol(){sheetData.forEach(r=>r.push(''));renderSpreadsheet();updateChartsFromSheet()}

function updateChartsFromSheet(){
  // Pull profit data from sheet row 2 (index 2) = Revenue - Expenses
  const profits=[];
  for(let i=1;i<=6;i++){const rev=parseFloat(sheetData[1]?.[i])||0;const exp=parseFloat(sheetData[2]?.[i])||0;profits.push(rev-exp)}
  drawLineChart('chartProfit',MONTHS,[{data:profits,color:'#34d399'}]);
}

// ── Export ───────────────────────────────────
function exportCSV(){
  let csv='\uFEFF';
  sheetData.forEach(row=>{csv+=row.map(c=>'""'+String(c).replace(/"/g,'""')+'"').join(',')+'\n'});
  const blob=new Blob([csv],{type:'text/csv;charset=utf-8'});const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);a.download='orchestra-finance-export.csv';a.click();URL.revokeObjectURL(a.href);
}

function resetData(){
  if(!confirm('Reset all data to defaults?'))return;
  transactions=transactions.slice(0,12);
  sheetData=[
    ['Category','Jan','Feb','Mar','Apr','May','Jun','Total'],
    ['Revenue','42000','45000','48000','51000','53800','45000',''],
    ['Expenses','28000','29500','31000','33800','35800','3200',''],
    ['Profit','14000','15500','17000','17200','18000','41800',''],
    ['Burn Rate','12000','12500','13000','13500','14000','14500',''],
    ['Cash Reserve','320000','307500','294500','280700','266700','252200',''],
  ];
  renderAll();
}

// ── Insights & Copilot ──────────────────────
function renderInsights(){
  const k=calcKPIs();
  const margin=k.margin;
  const insights=[];
  if(margin<5)insights.push({sev:'warning',icon:'⚠️',title:'Low Profit Margin',desc:`Profit margin is ${margin}%, below healthy 10% threshold. Consider cost optimization.`});
  if(margin>20)insights.push({sev:'info',icon:'✅',title:'Strong Profitability',desc:`Margin of ${margin}% indicates excellent financial health.`});
  if(margin<0)insights.push({sev:'critical',icon:'🚨',title:'Operating at a Loss',desc:'Immediate action required — review expenses and revenue streams.'});
  if(k.income>0&&k.expenses>0&&k.income/k.expenses<1.2)insights.push({sev:'critical',icon:'📉',title:'Revenue Below Expense Growth',desc:'Revenue is not keeping pace with expenses.'});
  insights.push({sev:'info',icon:'📊',title:`${transactions.length} Transactions`,desc:`${transactions.filter(t=>t.type==='income').length} income, ${transactions.filter(t=>t.type==='expense').length} expenses, ${transactions.filter(t=>t.type==='investment').length} investments.`});

  document.getElementById('insightsList').innerHTML=insights.map(i=>`
    <div style="padding:12px;border-radius:8px;background:var(--bg2);border:1px solid var(--border);margin-bottom:8px;border-left:3px solid ${i.sev==='critical'?'var(--danger)':i.sev==='warning'?'var(--warning)':'var(--accent2)'}">
      <div style="font-weight:600;font-size:.85rem;margin-bottom:4px">${i.icon} ${i.title}</div>
      <div style="font-size:.8rem;color:var(--text2)">${i.desc}</div>
    </div>
  `).join('');

  // What-if scenarios
  const rev=k.income;const exp=k.expenses;
  const scenarios={
    'Bullish (Rev+25%)':{revenue:rev*1.25,expenses:exp*1.1},
    'Moderate (Rev+10%)':{revenue:rev*1.1,expenses:exp*1.05},
    'Cost Optimized (-15%)':{revenue:rev,expenses:exp*0.85},
    'Market Downturn (-20%)':{revenue:rev*0.8,expenses:exp*0.95},
  };
  document.getElementById('scenariosList').innerHTML=Object.entries(scenarios).map(([name,s])=>{
    const profit=s.revenue-s.expenses;const pm=s.revenue>0?(profit/s.revenue*100).toFixed(1):'0';
    return `<div style="padding:10px;border-radius:6px;background:var(--bg2);border:1px solid var(--border);margin-bottom:6px">
      <div style="font-weight:600;font-size:.8rem;margin-bottom:2px">${name}</div>
      <div style="font-size:.75rem;color:var(--text2)">Rev: $${s.revenue.toLocaleString()} | Profit: <span style="color:${profit>=0?'var(--accent2)':'var(--danger)'}">$${profit.toLocaleString()}</span> (${pm}%)</div>
    </div>`;
  }).join('');

  // Forecast
  const histRev=MONTHS.map((_,i)=>38000+i*7000+Math.round(Math.random()*6000));
  const forecast=histRev.slice(-3).reduce((a,b)=>a+b,0)/3;
  document.getElementById('forecastValue').textContent='$'+(forecast*1.08).toLocaleString();

  // Risk
  const var95=rev*0.15;
  document.getElementById('riskValue').textContent='-$'+var95.toLocaleString();
}

async function askCopilot(){
  const prompt=document.getElementById('aiPrompt').value;
  if(!prompt)return;
  const el=document.getElementById('aiResponse');el.style.display='block';
  el.textContent='Thinking...';
  const k=calcKPIs();
  const ctx=`Revenue: $${k.income.toLocaleString()}, Expenses: $${k.expenses.toLocaleString()}, Profit: $${(k.income-k.expenses).toLocaleString()}, Margin: ${k.margin}%, Transactions: ${k.count}`;
  try{
    const resp=await fetch('/api/finance/brain/query',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({prompt:prompt+'\n\nCurrent financial context:\n'+ctx,context:{revenue:k.income,expenses:k.expenses,profit:k.income-k.expenses,margin:k.margin,transactions:k.count}}),
    });
    const data=await resp.json();
    el.textContent=data.response||'No response from AI backend.';
  }catch(e){
    el.innerHTML=`<strong>CFO Copilot (Offline)</strong><br>Based on current data: ${ctx}<br><br>Your question: "${prompt}"<br><br>💡 The AI backend is not available. Connect Ollama or OpenAI to enable full CFO copilot.`;
  }
}

// ── Tab Switching ────────────────────────────
function switchTab(tab,btn){
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.dashboard,.spreadsheet-view').forEach(v=>v.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-'+tab).classList.add('active');
  if(tab==='dashboard'){updateCharts();renderKPIs();renderTransactions()}
  if(tab==='spreadsheet')renderSpreadsheet();
  if(tab==='insights')renderInsights();
}

// ── Render All ───────────────────────────────
function renderAll(){
  renderKPIs();renderTransactions();updateCharts();renderSpreadsheet();
}

// ── Init ─────────────────────────────────────
document.addEventListener('DOMContentLoaded',renderAll);
window.addEventListener('resize',updateCharts);
</script>
</body>
</html>"""
