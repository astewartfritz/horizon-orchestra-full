"""Orchestra Create — brand design website HTML."""

from __future__ import annotations

CREATE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Orchestra Create — Full-Scale Digital Design</title>
<meta name="description" content="Build full-scale digital design projects with AI. Orchestrate your creative workflow from concept to deployment.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#0a0a0f;--bg2:#12121a;--bg3:#1a1a28;--surface:#1e1e2e;--border:#2a2a3e;--text:#e4e4f0;--text2:#9494b0;--accent:#7c6ff0;--accent2:#5ee0c0;--accent3:#f06fbf;--gradient:linear-gradient(135deg,#7c6ff0,#5ee0c0);--gradient2:linear-gradient(135deg,#7c6ff0,#f06fbf);--radius:16px;--radius-sm:8px;--max-w:1200px;--font:'Inter',system-ui,-apple-system,sans-serif;--mono:'JetBrains Mono',monospace}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:var(--font);background:var(--bg);color:var(--text);line-height:1.6;overflow-x:hidden}
::selection{background:var(--accent);color:#fff}
::-webkit-scrollbar{width:8px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}
a{color:var(--accent);text-decoration:none}
.container{max-width:var(--max-w);margin:0 auto;padding:0 24px}

/* ── Nav ── */
nav{position:fixed;top:0;left:0;right:0;z-index:100;background:rgba(10,10,15,.8);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-bottom:1px solid var(--border)}
nav .container{display:flex;align-items:center;justify-content:space-between;height:64px}
.logo{display:flex;align-items:center;gap:10px;font-weight:700;font-size:1.2rem}
.logo-icon{width:32px;height:32px;border-radius:8px;background:var(--gradient);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:1rem;color:#fff}
.logo span{color:var(--accent2)}
.nav-links{display:flex;gap:32px;align-items:center}
.nav-links a{color:var(--text2);font-size:.9rem;font-weight:500;transition:color .2s}
.nav-links a:hover{color:var(--text)}
.nav-cta{padding:8px 20px;border-radius:20px;background:var(--gradient);color:#fff!important;font-weight:600;font-size:.85rem;transition:transform .2s,box-shadow .2s}
.nav-cta:hover{transform:translateY(-1px);box-shadow:0 4px 20px rgba(124,111,240,.3)}
.mobile-toggle{display:none;flex-direction:column;gap:4px;cursor:pointer;background:none;border:none;padding:4px}
.mobile-toggle span{width:24px;height:2px;background:var(--text);border-radius:2px;transition:.3s}

/* ── Hero ── */
.hero{min-height:100vh;display:flex;align-items:center;position:relative;overflow:hidden;padding-top:64px}
.hero-bg{position:absolute;inset:0;overflow:hidden;pointer-events:none}
.hero-bg .orb{position:absolute;border-radius:50%;filter:blur(80px);opacity:.15}
.hero-bg .orb:nth-child(1){width:600px;height:600px;background:var(--accent);top:-200px;right:-200px;animation:float1 20s ease-in-out infinite}
.hero-bg .orb:nth-child(2){width:400px;height:400px;background:var(--accent2);bottom:-100px;left:-100px;animation:float2 25s ease-in-out infinite}
.hero-bg .orb:nth-child(3){width:300px;height:300px;background:var(--accent3);top:50%;left:50%;animation:float3 18s ease-in-out infinite}
@keyframes float1{0%,100%{transform:translate(0,0)}50%{transform:translate(-80px,60px)}}
@keyframes float2{0%,100%{transform:translate(0,0)}50%{transform:translate(60px,-80px)}}
@keyframes float3{0%,100%{transform:translate(-50%,-50%)scale(1)}50%{transform:translate(-40%,-60%)scale(1.2)}}
.hero-content{position:relative;z-index:1;text-align:center;max-width:800px;margin:0 auto;padding:60px 0}
.hero-badge{display:inline-flex;align-items:center;gap:8px;padding:6px 16px;border-radius:20px;background:var(--surface);border:1px solid var(--border);font-size:.8rem;color:var(--text2);margin-bottom:24px}
.hero-badge .dot{width:6px;height:6px;border-radius:50%;background:var(--accent2);animation:pulse 2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.hero h1{font-size:clamp(2.5rem,6vw,4.5rem);font-weight:800;line-height:1.1;margin-bottom:16px;letter-spacing:-.02em}
.hero h1 .gradient-text{background:var(--gradient2);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.hero h1 .gradient-text2{background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.hero p{font-size:clamp(1rem,2vw,1.2rem);color:var(--text2);max-width:600px;margin:0 auto 32px;line-height:1.7}
.hero-actions{display:flex;gap:16px;justify-content:center;flex-wrap:wrap}
.btn{display:inline-flex;align-items:center;gap:8px;padding:14px 28px;border-radius:12px;font-weight:600;font-size:1rem;border:none;cursor:pointer;transition:transform .2s,box-shadow .2s}
.btn:hover{transform:translateY(-2px)}
.btn-primary{background:var(--gradient);color:#fff;box-shadow:0 4px 20px rgba(124,111,240,.25)}
.btn-primary:hover{box-shadow:0 8px 30px rgba(124,111,240,.35)}
.btn-secondary{background:var(--surface);color:var(--text);border:1px solid var(--border)}
.btn-secondary:hover{background:var(--bg3);border-color:var(--accent)}
.hero-stats{display:flex;gap:48px;justify-content:center;margin-top:48px;flex-wrap:wrap}
.hero-stat{text-align:center}
.hero-stat .num{font-size:2rem;font-weight:800;background:var(--gradient);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.hero-stat .label{font-size:.85rem;color:var(--text2);margin-top:4px}

/* ── Sections ── */
section{padding:100px 0}
.section-label{display:inline-block;padding:4px 12px;border-radius:6px;background:var(--surface);border:1px solid var(--border);font-size:.75rem;font-weight:600;color:var(--accent2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px}
.section-title{font-size:clamp(1.8rem,4vw,2.8rem);font-weight:800;margin-bottom:16px;line-height:1.2}
.section-sub{color:var(--text2);max-width:600px;font-size:1.05rem;line-height:1.7;margin-bottom:48px}

/* ── Features ── */
.features{background:var(--bg2)}
.feature-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:24px}
.feature-card{padding:32px;border-radius:var(--radius);background:var(--surface);border:1px solid var(--border);transition:transform .3s,border-color .3s}
.feature-card:hover{transform:translateY(-4px);border-color:var(--accent)}
.feature-card .icon{width:48px;height:48px;border-radius:12px;margin-bottom:16px;display:flex;align-items:center;justify-content:center;font-size:1.3rem}
.feature-card h3{font-size:1.1rem;font-weight:600;margin-bottom:8px}
.feature-card p{color:var(--text2);font-size:.9rem;line-height:1.6}

/* ── Workflow ── */
.workflow-steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:24px;position:relative}
.workflow-step{text-align:center;padding:32px 20px;border-radius:var(--radius);background:var(--surface);border:1px solid var(--border);position:relative}
.workflow-step .step-num{width:40px;height:40px;border-radius:50%;background:var(--gradient);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:1rem;color:#fff;margin:0 auto 16px}
.workflow-step h4{font-size:1rem;font-weight:600;margin-bottom:8px}
.workflow-step p{color:var(--text2);font-size:.85rem;line-height:1.5}

/* ── Templates ── */
.template-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px}
.template-card{padding:24px;border-radius:var(--radius);background:var(--surface);border:1px solid var(--border);cursor:pointer;transition:transform .2s,border-color .2s}
.template-card:hover{transform:translateY(-3px);border-color:var(--accent)}
.template-card .tmpl-icon{font-size:2rem;margin-bottom:12px}
.template-card h4{font-size:1rem;font-weight:600;margin-bottom:4px}
.template-card p{color:var(--text2);font-size:.85rem;margin-bottom:12px}
.template-card .tags{display:flex;gap:6px;flex-wrap:wrap}
.template-card .tags span{padding:2px 8px;border-radius:4px;background:var(--bg3);color:var(--text2);font-size:.7rem;font-weight:500}

/* ── Testimonials ── */
.testimonials{background:var(--bg2)}
.testimonial-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:24px}
.testimonial-card{padding:28px;border-radius:var(--radius);background:var(--surface);border:1px solid var(--border)}
.testimonial-card .stars{color:#f0c05e;margin-bottom:12px;font-size:1rem}
.testimonial-card blockquote{color:var(--text2);font-size:.9rem;line-height:1.7;margin-bottom:16px;font-style:italic}
.testimonial-card .author{display:flex;align-items:center;gap:12px}
.testimonial-card .author .avatar{width:36px;height:36px;border-radius:50%;background:var(--gradient);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:.8rem;color:#fff}
.testimonial-card .author .name{font-weight:600;font-size:.85rem}
.testimonial-card .author .role{color:var(--text2);font-size:.75rem}

/* ── CTA ── */
.cta{text-align:center;position:relative;overflow:hidden}
.cta-box{padding:80px 40px;border-radius:var(--radius);background:var(--surface);border:1px solid var(--border);position:relative;overflow:hidden}
.cta-box::before{content:'';position:absolute;inset:0;background:var(--gradient);opacity:.05;pointer-events:none}
.cta h2{font-size:clamp(1.6rem,3vw,2.4rem);font-weight:800;margin-bottom:12px}
.cta p{color:var(--text2);margin-bottom:32px;max-width:500px;margin-left:auto;margin-right:auto}
.cta .btn-group{display:flex;gap:16px;justify-content:center;flex-wrap:wrap}

/* ── Footer ── */
footer{padding:48px 0;border-top:1px solid var(--border)}
.footer-grid{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:40px}
@media(max-width:768px){.footer-grid{grid-template-columns:1fr 1fr}}
.footer-brand .logo{margin-bottom:12px}
.footer-brand p{color:var(--text2);font-size:.85rem;max-width:300px;line-height:1.6}
.footer-col h4{font-size:.85rem;font-weight:600;margin-bottom:16px;text-transform:uppercase;letter-spacing:.06em;color:var(--text2)}
.footer-col a{display:block;color:var(--text2);font-size:.85rem;margin-bottom:10px;transition:color .2s}
.footer-col a:hover{color:var(--text)}
.footer-bottom{margin-top:32px;padding-top:24px;border-top:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px;color:var(--text2);font-size:.8rem}

/* ── Modal ── */
.modal-overlay{position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.6);backdrop-filter:blur(8px);display:none;align-items:center;justify-content:center;padding:24px}
.modal-overlay.active{display:flex}
.modal{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:40px;max-width:500px;width:100%;max-height:90vh;overflow-y:auto}
.modal h3{font-size:1.4rem;font-weight:700;margin-bottom:8px}
.modal p{color:var(--text2);font-size:.9rem;margin-bottom:24px}
.modal .form-group{margin-bottom:16px}
.modal label{display:block;font-size:.85rem;font-weight:500;margin-bottom:6px;color:var(--text2)}
.modal input,.modal select{width:100%;padding:12px 16px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:.9rem;font-family:var(--font);outline:none;transition:border-color .2s}
.modal input:focus,.modal select:focus{border-color:var(--accent)}
.modal .btn{width:100%;justify-content:center;margin-top:8px}
.modal-close{position:absolute;top:16px;right:16px;background:none;border:none;color:var(--text2);font-size:1.5rem;cursor:pointer}

/* ── Responsive ── */
@media(max-width:768px){
  .nav-links{position:fixed;top:64px;left:0;right:0;background:rgba(10,10,15,.95);backdrop-filter:blur(20px);flex-direction:column;padding:24px;gap:16px;border-bottom:1px solid var(--border);display:none}
  .nav-links.open{display:flex}
  .mobile-toggle{display:flex}
  .hero-stats{gap:24px}
  section{padding:60px 0}
  .cta-box{padding:40px 24px}
}
@media(max-width:480px){
  .hero h1{font-size:2rem}
  .hero-actions{flex-direction:column;align-items:stretch}
  .hero-actions .btn{justify-content:center}
  .feature-grid,.template-grid,.testimonial-grid{grid-template-columns:1fr}
}
</style>
</head>
<body>

<!-- Nav -->
<nav>
<div class="container">
<a href="#" class="logo"><div class="logo-icon">C</div>Orchestra <span>Create</span></a>
<div class="nav-links" id="navLinks">
<a href="#features">Features</a>
<a href="#workflow">Workflow</a>
<a href="#templates">Templates</a>
<a href="#testimonials">Testimonials</a>
<a href="#cta" class="nav-cta">Get Started</a>
</div>
<button class="mobile-toggle" id="mobileToggle" aria-label="Menu"><span></span><span></span><span></span></button>
</div>
</nav>

<!-- Hero -->
<section class="hero">
<div class="hero-bg"><div class="orb"></div><div class="orb"></div><div class="orb"></div></div>
<div class="container hero-content">
<div class="hero-badge"><span class="dot"></span>Now in Early Access</div>
<h1>Full-Scale<br><span class="gradient-text">Digital Design</span><br>with <span class="gradient-text2">AI</span></h1>
<p>Orchestrate your entire creative workflow — from concept sketches to production-ready deployments. Build products, websites, brand systems, and interactive experiences with an AI that thinks like a designer.</p>
<div class="hero-actions">
<button class="btn btn-primary" onclick="openModal()">Start Creating →</button>
<a href="#features" class="btn btn-secondary">Explore Features</a>
</div>
<div class="hero-stats">
<div class="hero-stat"><div class="num">10+</div><div class="label">Project Templates</div></div>
<div class="hero-stat"><div class="num">6</div><div class="label">Design Languages</div></div>
<div class="hero-stat"><div class="num">∞</div><div class="label">Creative Freedom</div></div>
</div>
</div>
</section>

<!-- Features -->
<section class="features" id="features">
<div class="container">
<div class="section-label">Capabilities</div>
<h2 class="section-title">Everything you need to <span class="gradient-text">build</span></h2>
<p class="section-sub">From wireframes to deployment. Orchestra Create handles the full lifecycle of digital design projects.</p>
<div class="feature-grid">
<div class="feature-card"><div class="icon" style="background:rgba(124,111,240,.15);color:#7c6ff0">🎨</div><h3>Concept to Code</h3><p>Describe your vision in natural language. AI generates production-ready code for web apps, brand systems, prototypes, and more.</p></div>
<div class="feature-card"><div class="icon" style="background:rgba(94,224,192,.15);color:#5ee0c0">⚡</div><h3>Adaptive Workflows</h3><p>Supports Rust, TypeScript, Python, Mojo, and more. Scaffold projects, read/write files, run bash, git, and Docker sandboxes.</p></div>
<div class="feature-card"><div class="icon" style="background:rgba(240,111,191,.15);color:#f06fbf">🔍</div><h3>Design Intelligence</h3><p>Analyze layouts, audit accessibility, optimize performance. Built-in code quality checks, linting, and security scanning.</p></div>
<div class="feature-card"><div class="icon" style="background:rgba(124,111,240,.15);color:#7c6ff0">🔄</div><h3>Iterate in Real-Time</h3><p>AI-powered review and refactor cycles. Generate multiple variants, run A/B tests, and track every change with git.</p></div>
<div class="feature-card"><div class="icon" style="background:rgba(94,224,192,.15);color:#5ee0c0">📦</div><h3>Deploy Anywhere</h3><p>One-click deploy to Docker, Kubernetes, or cloud. Built-in CI/CD pipelines for Jenkins, GitLab, and ArgoCD.</p></div>
<div class="feature-card"><div class="icon" style="background:rgba(240,111,191,.15);color:#f06fbf">🧠</div><h3>Context-Aware AI</h3><p>Remembers your project structure, design decisions, and preferences across sessions. Layered context with working memory.</p></div>
</div>
</div>
</section>

<!-- Workflow -->
<section id="workflow">
<div class="container">
<div class="section-label">How It Works</div>
<h2 class="section-title">Your creative <span class="gradient-text2">workflow</span></h2>
<p class="section-sub">From a single prompt to a fully-realized design project in minutes.</p>
<div class="workflow-steps">
<div class="workflow-step"><div class="step-num">1</div><h4>Describe</h4><p>Tell Orchestra what you want to build in plain language — no technical expertise needed.</p></div>
<div class="workflow-step"><div class="step-num">2</div><h4>Generate</h4><p>AI selects the right template, scaffolds the project, and produces initial design output.</p></div>
<div class="workflow-step"><div class="step-num">3</div><h4>Refine</h4><p>Iterate with natural language feedback. AI reviews, refactors, and improves the work.</p></div>
<div class="workflow-step"><div class="step-num">4</div><h4>Deploy</h4><p>Push to production with built-in CI/CD, containerization, and Kubernetes orchestration.</p></div>
</div>
</div>
</section>

<!-- Templates -->
<section class="features" id="templates">
<div class="container">
<div class="section-label">Project Types</div>
<h2 class="section-title">Start from a <span class="gradient-text">template</span></h2>
<p class="section-sub">Choose from 10+ scaffold templates designed for different project types and tech stacks.</p>
<div class="template-grid">
<div class="template-card" onclick="openModal('web')"><div class="tmpl-icon">🌐</div><h4>Web Application</h4><p>Full-stack web app with Python/FastAPI backend and modern frontend.</p><div class="tags"><span>Python</span><span>FastAPI</span><span>HTML/CSS</span></div></div>
<div class="template-card" onclick="openModal('rust')"><div class="tmpl-icon">🦀</div><h4>Rust CLI Tool</h4><p>High-performance CLI application with clap, tokio, and CI pipeline.</p><div class="tags"><span>Rust</span><span>CLI</span><span>Tokio</span></div></div>
<div class="template-card" onclick="openModal('ts')"><div class="tmpl-icon">📘</div><h4>TypeScript Library</h4><p>TypeScript library or CLI with full type definitions and docs.</p><div class="tags"><span>TypeScript</span><span>Node</span><span>npm</span></div></div>
<div class="template-card" onclick="openModal('mojo')"><div class="tmpl-icon">🔥</div><h4>Mojo Project</h4><p>High-performance AI/ML project with the Mojo programming language.</p><div class="tags"><span>Mojo</span><span>AI</span><span>MAX</span></div></div>
<div class="template-card" onclick="openModal('design')"><div class="tmpl-icon">🎨</div><h4>Design System</h4><p>Complete brand system with typography, colors, components, and docs.</p><div class="tags"><span>CSS</span><span>Design</span><span>Tokens</span></div></div>
<div class="template-card" onclick="openModal('api')"><div class="tmpl-icon">🔌</div><h4>API Service</h4><p>RESTful API service with Express or FastAPI, auto-docs, and tests.</p><div class="tags"><span>API</span><span>REST</span><span>OpenAPI</span></div></div>
</div>
</div>
</section>

<!-- Testimonials -->
<section class="testimonials" id="testimonials">
<div class="container">
<div class="section-label">Testimonials</div>
<h2 class="section-title">What creators are <span class="gradient-text2">saying</span></h2>
<p class="section-sub">Trusted by designers, developers, and agencies building at scale.</p>
<div class="testimonial-grid">
<div class="testimonial-card"><div class="stars">★★★★★</div><blockquote>"Orchestra Create cut our design-to-deployment time by 70%. It's like having a full creative team in a terminal."</blockquote><div class="author"><div class="avatar">JM</div><div><div class="name">Jamie Morano</div><div class="role">Creative Director, Studio Kraft</div></div></div></div>
<div class="testimonial-card"><div class="stars">★★★★★</div><blockquote>"The iterative workflow is incredible. I describe what I want, review the output, give feedback, and it just keeps getting better."</blockquote><div class="author"><div class="avatar">AL</div><div><div class="name">Alex Liu</div><div class="role">Independent Developer</div></div></div></div>
<div class="testimonial-card"><div class="stars">★★★★★</div><blockquote>"We use Orchestra Create for all our client projects. The multi-channel support and CI/CD integration alone saved us months of setup."</blockquote><div class="author"><div class="avatar">SR</div><div><div class="name">Sarah Rivera</div><div class="role">CTO, DesignLab</div></div></div></div>
</div>
</div>
</section>

<!-- CTA -->
<section class="cta" id="cta">
<div class="container">
<div class="cta-box">
<h2>Ready to <span class="gradient-text">build</span> something amazing?</h2>
<p>Join the early access program. Start creating full-scale digital design projects with AI today.</p>
<div class="btn-group">
<button class="btn btn-primary" onclick="openModal()">Get Started Free</button>
<a href="#" class="btn btn-secondary" onclick="openModal('demo')">Request Demo</a>
</div>
</div>
</div>
</section>

<!-- Footer -->
<footer>
<div class="container">
<div class="footer-grid">
<div class="footer-brand"><a href="#" class="logo"><div class="logo-icon">C</div>Orchestra <span>Create</span></a><p>Build full-scale digital design projects with AI. From concept to deployment, orchestrate your entire creative workflow.</p></div>
<div class="footer-col"><h4>Product</h4><a href="#features">Features</a><a href="#templates">Templates</a><a href="#workflow">Workflow</a><a href="#cta">Pricing</a></div>
<div class="footer-col"><h4>Resources</h4><a href="#">Documentation</a><a href="#">API Reference</a><a href="#">Community</a><a href="#">Blog</a></div>
<div class="footer-col"><h4>Company</h4><a href="#">About</a><a href="#">Careers</a><a href="#">Contact</a><a href="#">Legal</a></div>
</div>
<div class="footer-bottom"><span>&copy; 2026 Orchestra. All rights reserved.</span><span>Built with AI, designed for humans.</span></div>
</div>
</footer>

<!-- Modal -->
<div class="modal-overlay" id="modal">
<div class="modal" style="position:relative">
<button class="modal-close" onclick="closeModal()" style="position:absolute;top:16px;right:16px;background:none;border:none;color:var(--text2);font-size:1.5rem;cursor:pointer">×</button>
<h3 id="modalTitle">Get Started with Orchestra Create</h3>
<p id="modalDesc">Tell us about your project and we'll help you get going.</p>
<form onsubmit="handleSubmit(event)">
<div class="form-group"><label>Project Type</label><select id="projectType"><option>Web Application</option><option>Design System</option><option>Rust CLI Tool</option><option>TypeScript Library</option><option>Mojo Project</option><option>API Service</option></select></div>
<div class="form-group"><label>Your Email</label><input type="email" id="email" placeholder="you@example.com" required></div>
<div class="form-group"><label>Project Description</label><input type="text" id="description" placeholder="e.g. A portfolio site with dark mode"></div>
<button type="submit" class="btn btn-primary">Submit →</button>
</form>
</div>
</div>

<script>
const navLinks=document.getElementById('navLinks');const toggle=document.getElementById('mobileToggle');
toggle?.addEventListener('click',()=>navLinks.classList.toggle('open'));
document.querySelectorAll('.nav-links a').forEach(a=>a.addEventListener('click',()=>navLinks.classList.remove('open')));

function openModal(type){document.getElementById('modal').classList.add('active')
if(type==='demo'){document.getElementById('modalTitle').textContent='Request a Demo'
document.getElementById('modalDesc').textContent='See Orchestra Create in action. We will reach out within 24 hours.'}}
function closeModal(){document.getElementById('modal').classList.remove('active')}
document.getElementById('modal').addEventListener('click',e=>{if(e.target===e.currentTarget)closeModal()})
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal()})

function handleSubmit(e){e.preventDefault()
const type=document.getElementById('projectType').value
const email=document.getElementById('email').value
const desc=document.getElementById('description').value||'Not specified'
alert(`Thanks, ${email}! We will follow up about your ${type} project: "${desc}"`)
closeModal()}
</script>
</body>
</html>"""


CREATE_HTML_MINIFIED = None  # Full version above; minified not needed for dev
