"""Build Orchestrator brand landing page."""

BUILD_BRAND_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Orchestra Build Engine — Chromium Build Orchestration</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#0a0a0f;--bg2:#12121a;--surface:#1e1e2e;--border:#2a2a3e;--text:#e4e4f0;--text2:#9494b0;--accent:#6366f1;--accent2:#22d3ee;--radius:16px;--font:'Inter',system-ui,sans-serif;--mono:'JetBrains Mono',monospace}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:var(--font);line-height:1.6;overflow-x:hidden}
a{color:var(--accent2);text-decoration:none}
nav{position:fixed;top:0;width:100%;z-index:100;backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);background:rgba(10,10,15,.8);border-bottom:1px solid var(--border);padding:16px 32px;display:flex;justify-content:space-between;align-items:center}
nav .logo{font-weight:700;font-size:1.2rem;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
nav a{color:var(--text2);margin-left:24px;font-size:.9rem;transition:color .2s}
nav a:hover{color:var(--text)}
.hero{min-height:90vh;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:120px 24px 80px;position:relative;overflow:hidden}
.hero .orb{position:absolute;width:600px;height:600px;border-radius:50%;filter:blur(120px);opacity:.15;animation:float 20s ease-in-out infinite;pointer-events:none}
.hero .orb:nth-child(1){background:var(--accent);top:-200px;left:-200px;animation-delay:0s}
.hero .orb:nth-child(2){background:var(--accent2);bottom:-300px;right:-200px;animation-delay:-7s}
@keyframes float{0%,100%{transform:translate(0,0)scale(1)}33%{transform:translate(40px,-40px)scale(1.1)}66%{transform:translate(-30px,20px)scale(.95)}}
.hero h1{font-size:clamp(2.5rem,6vw,5rem);font-weight:800;line-height:1.1;margin-bottom:20px}
.hero h1 span{background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero p{font-size:clamp(1rem,2vw,1.25rem);color:var(--text2);max-width:640px;margin-bottom:32px}
.badge{display:inline-flex;align-items:center;gap:8px;background:rgba(99,102,241,.15);border:1px solid rgba(99,102,241,.3);border-radius:100px;padding:8px 16px;font-size:.85rem;color:var(--accent2);margin-bottom:24px}
.hero-btns{display:flex;gap:16px;flex-wrap:wrap;justify-content:center}
.btn{display:inline-flex;align-items:center;gap:8px;padding:14px 32px;border-radius:12px;font-weight:600;font-size:1rem;border:none;cursor:pointer;transition:all .2s}
.btn-primary{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#000}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 8px 32px rgba(99,102,241,.4)}
.btn-secondary{background:var(--surface);color:var(--text);border:1px solid var(--border)}
.btn-secondary:hover{background:var(--border)}
.stats{display:flex;gap:48px;margin-top:48px;flex-wrap:wrap;justify-content:center}
.stat{text-align:center}
.stat-num{font-size:2rem;font-weight:800;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.stat-label{font-size:.85rem;color:var(--text2);margin-top:4px}
.section{padding:80px 24px;max-width:1200px;margin:0 auto}
.section h2{font-size:2rem;font-weight:700;text-align:center;margin-bottom:48px}
.grid-3{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:24px}
.card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:32px;transition:all .3s}
.card:hover{border-color:var(--accent);transform:translateY(-4px)}
.card .icon{font-size:2rem;margin-bottom:16px}
.card h3{font-size:1.1rem;font-weight:600;margin-bottom:8px}
.card p{font-size:.9rem;color:var(--text2)}
.platform-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:16px;margin-top:24px}
.platform-tag{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px;text-align:center;font-size:.85rem;font-weight:500}
footer{text-align:center;padding:48px 24px;border-top:1px solid var(--border);color:var(--text2);font-size:.85rem}
@media(max-width:768px){.hero{padding:100px 16px 60px}.stats{gap:24px}.grid-3{grid-template-columns:1fr}}
</style>
</head>
<body>
<nav>
<div class="logo">Orchestra Build</div>
<div>
<a href="/build">Dashboard</a>
<a href="/">Orchestra</a>
</div>
</nav>
<section class="hero">
<div class="orb"></div><div class="orb"></div>
<div class="badge">&#9889; Chromium Build Orchestration Engine</div>
<h1>Build <span>Horizon Frontier</span><br>at Scale</h1>
<p>Enterprise-grade build orchestration for Chromium-based browsers. Manage GN profiles, automate builds, track patches, and optimize your development pipeline.</p>
<div class="hero-btns">
<a href="/build/app" class="btn btn-primary">Open Dashboard</a>
<a href="/build" class="btn btn-secondary">Learn More</a>
</div>
<div class="stats">
<div class="stat"><div class="stat-num">21</div><div class="stat-label">Build Profiles</div></div>
<div class="stat"><div class="stat-num">7</div><div class="stat-label">Platforms</div></div>
<div class="stat"><div class="stat-num">8</div><div class="stat-label">Build Types</div></div>
</div>
</section>
<section class="section">
<h2>Build Orchestration Features</h2>
<div class="grid-3">
<div class="card"><div class="icon">&#9889;</div><h3>GN Profile Manager</h3><p>Pre-built GN arg profiles for every Chromium target platform. Debug, Release, ASAN, CFI, and custom profiles with one-click configuration.</p></div>
<div class="card"><div class="icon">&#128640;</div><h3>Build Runner</h3><p>Execute and monitor builds with real-time progress tracking. Parse ninja output for errors, warnings, and build metrics.</p></div>
<div class="card"><div class="icon">&#128220;</div><h3>Patch Manager</h3><p>Track and manage patches on your Chromium fork. Apply, unapply, detect conflicts, and version your customizations.</p></div>
<div class="card"><div class="icon">&#128200;</div><h3>Build Analytics</h3><p>Analyze build times, success rates, and binary sizes. Get optimization suggestions for faster, leaner builds.</p></div>
<div class="card"><div class="icon">&#129302;</div><h3>AI Build Assistant</h3><p>Get LLM-powered error diagnosis and fix suggestions. Ask questions about GN args, build errors, and optimization strategies.</p></div>
<div class="card"><div class="icon">&#128279;</div><h3>CI/CD Integration</h3><p>Generate GN commands for CI pipelines. Integrate with existing Jenkins, GitLab CI, or GitHub Actions workflows.</p></div>
</div>
</section>
<section class="section">
<h2>Supported Platforms</h2>
<div class="platform-grid">
<div class="platform-tag">Windows x64</div>
<div class="platform-tag">Windows x86</div>
<div class="platform-tag">Linux x64</div>
<div class="platform-tag">Linux arm64</div>
<div class="platform-tag">macOS x64</div>
<div class="platform-tag">macOS arm64</div>
<div class="platform-tag">Android x64</div>
<div class="platform-tag">Android arm64</div>
<div class="platform-tag">iOS arm64</div>
<div class="platform-tag">ChromeOS</div>
<div class="platform-tag">Fuchsia</div>
</div>
</section>
<section class="section">
<h2>Build Types</h2>
<div class="platform-grid">
<div class="platform-tag">Debug</div>
<div class="platform-tag">Release</div>
<div class="platform-tag">ASAN</div>
<div class="platform-tag">CFI</div>
<div class="platform-tag">TSAN</div>
<div class="platform-tag">MSAN</div>
<div class="platform-tag">Size</div>
<div class="platform-tag">Coverage</div>
</div>
</section>
<footer>
Orchestra Build Engine &mdash; Chromium Build Orchestration for Horizon Frontier
</footer>
</body>
</html>"""
