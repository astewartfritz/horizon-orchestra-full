BILLING_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Orchestra Pro — Billing</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0d1117; --bg2: #161b22; --bg3: #21262d;
    --border: #30363d; --text: #e6edf3; --muted: #8b949e;
    --purple: #a78bfa; --purple-dim: rgba(167,139,250,.15);
    --green: #3fb950; --green-dim: rgba(63,185,80,.12);
    --radius: 12px;
  }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 40px 16px 80px; }
  .back { align-self: flex-start; margin-bottom: 32px; color: var(--muted); font-size: 13px; text-decoration: none; display: flex; align-items: center; gap: 6px; transition: color .15s; }
  .back:hover { color: var(--text); }
  .hero { text-align: center; margin-bottom: 48px; }
  .hero h1 { font-size: 36px; font-weight: 800; background: linear-gradient(135deg,#a78bfa,#818cf8,#60a5fa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; margin-bottom: 12px; }
  .hero p { color: var(--muted); font-size: 16px; max-width: 460px; margin: 0 auto; line-height: 1.6; }
  .plans { display: flex; gap: 20px; width: 100%; max-width: 760px; flex-wrap: wrap; justify-content: center; margin-bottom: 40px; }
  .plan { flex: 1; min-width: 300px; background: var(--bg2); border: 1px solid var(--border); border-radius: var(--radius); padding: 28px 24px; display: flex; flex-direction: column; gap: 20px; }
  .plan.pro { border-color: rgba(167,139,250,.5); background: linear-gradient(160deg, rgba(167,139,250,.06) 0%, var(--bg2) 60%); }
  .plan-header { display: flex; justify-content: space-between; align-items: flex-start; }
  .plan-name { font-size: 18px; font-weight: 700; }
  .plan-badge { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 10px; background: var(--purple-dim); color: var(--purple); border: 1px solid rgba(167,139,250,.3); }
  .plan-price { display: flex; align-items: baseline; gap: 4px; }
  .plan-price .amount { font-size: 40px; font-weight: 800; }
  .plan-price .period { color: var(--muted); font-size: 14px; }
  .features { display: flex; flex-direction: column; gap: 10px; }
  .feat { display: flex; align-items: flex-start; gap: 10px; font-size: 14px; color: var(--muted); }
  .feat .icon { flex-shrink: 0; margin-top: 1px; }
  .feat .icon.yes { color: var(--green); }
  .feat .icon.no { color: #484f58; }
  .feat span { line-height: 1.4; }
  .cta { margin-top: auto; }
  .btn-pro { width: 100%; padding: 13px; background: linear-gradient(135deg,#7c3aed,#6d28d9); color: #fff; border: none; border-radius: 8px; font-size: 15px; font-weight: 700; cursor: pointer; font-family: inherit; transition: opacity .15s, transform .15s; }
  .btn-pro:hover { opacity: .9; transform: translateY(-1px); }
  .btn-pro:disabled { opacity: .5; cursor: not-allowed; transform: none; }
  .btn-free { width: 100%; padding: 13px; background: var(--bg3); color: var(--muted); border: 1px solid var(--border); border-radius: 8px; font-size: 15px; font-weight: 600; cursor: default; font-family: inherit; }
  .current-plan { background: var(--green-dim); border: 1px solid rgba(63,185,80,.3); border-radius: var(--radius); padding: 16px 20px; max-width: 760px; width: 100%; display: none; align-items: center; gap: 12px; margin-bottom: 24px; font-size: 14px; }
  .current-plan .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); flex-shrink: 0; }
  .manage-link { color: var(--purple); text-decoration: none; margin-left: auto; font-size: 13px; cursor: pointer; }
  .notice { max-width: 760px; width: 100%; text-align: center; font-size: 12px; color: var(--muted); margin-top: 16px; }
  .banner { max-width: 760px; width: 100%; border-radius: var(--radius); padding: 14px 18px; margin-bottom: 24px; font-size: 14px; display: none; }
  .banner.success { background: var(--green-dim); border: 1px solid rgba(63,185,80,.3); color: var(--green); }
  .banner.error { background: rgba(248,81,73,.1); border: 1px solid rgba(248,81,73,.3); color: #f85149; }
  .no-key-notice { background: rgba(240,136,46,.08); border: 1px solid rgba(240,136,46,.25); border-radius: 10px; padding: 14px 18px; max-width: 760px; width: 100%; font-size: 13px; color: #f0883e; display: none; margin-bottom: 16px; }
  .no-key-notice code { background: rgba(240,136,46,.15); padding: 1px 5px; border-radius: 4px; font-family: monospace; }
  @media (max-width: 480px) { .hero h1 { font-size: 28px; } .plan-price .amount { font-size: 34px; } }
</style>
</head>
<body>
<a class="back" href="/">&#8592; Back to Orchestra</a>

<div class="hero">
  <h1>Orchestra Pro</h1>
  <p>From reading code to <strong>rewriting it</strong>. Give Orchestra the keys to your entire stack.</p>
</div>

<div class="banner success" id="banner-success">&#x2713;&nbsp; You're now subscribed to Orchestra Pro. Welcome aboard.</div>
<div class="banner error" id="banner-error"></div>

<div class="current-plan" id="current-plan-banner">
  <div class="dot"></div>
  <span id="current-plan-text">Orchestra Pro — Active</span>
  <a class="manage-link" onclick="openPortal()">Manage billing &#x2192;</a>
</div>

<div class="no-key-notice" id="no-key-notice">
  <strong>Stripe not configured.</strong> Set <code>STRIPE_SECRET_KEY</code> and <code>STRIPE_PUBLISHABLE_KEY</code> in your environment to enable payments. Restart the server after setting them.
</div>

<div class="plans">
  <!-- Free -->
  <div class="plan">
    <div class="plan-header">
      <span class="plan-name">Free</span>
    </div>
    <div class="plan-price">
      <span class="amount">$0</span>
      <span class="period">/ month</span>
    </div>
    <div class="features">
      <div class="feat"><span class="icon yes">&#x2713;</span><span>Generate code snippets with AI</span></div>
      <div class="feat"><span class="icon yes">&#x2713;</span><span>View and inspect output</span></div>
      <div class="feat"><span class="icon yes">&#x2713;</span><span>Chat with the base agent</span></div>
      <div class="feat"><span class="icon yes">&#x2713;</span><span>Finance dashboard (read-only)</span></div>
      <div class="feat"><span class="icon no">&#x2715;</span><span>Autonomous code execution</span></div>
      <div class="feat"><span class="icon no">&#x2715;</span><span>Real file writes &amp; git commits</span></div>
      <div class="feat"><span class="icon no">&#x2715;</span><span>Multi-agent swarms (Claude Code, Codex)</span></div>
      <div class="feat"><span class="icon no">&#x2715;</span><span>MCP tool execution</span></div>
      <div class="feat"><span class="icon no">&#x2715;</span><span>Full Finance engine (write transactions)</span></div>
    </div>
    <div class="cta">
      <button class="btn-free">Current plan</button>
    </div>
  </div>

  <!-- Pro -->
  <div class="plan pro">
    <div class="plan-header">
      <span class="plan-name" style="color:var(--purple)">Pro</span>
      <span class="plan-badge">MOST POPULAR</span>
    </div>
    <div class="plan-price">
      <span class="amount" style="color:var(--purple)">$50</span>
      <span class="period">/ month</span>
    </div>
    <div class="features">
      <div class="feat"><span class="icon yes">&#x2713;</span><span>Everything in Free</span></div>
      <div class="feat"><span class="icon yes" style="color:var(--purple)">&#x2713;</span><span><strong>Autonomous code execution</strong> — agents write, edit, and run code on your machine</span></div>
      <div class="feat"><span class="icon yes" style="color:var(--purple)">&#x2713;</span><span>Real file writes, git commits &amp; pull requests</span></div>
      <div class="feat"><span class="icon yes" style="color:var(--purple)">&#x2713;</span><span>All agent engines — Claude Code, Codex, OpenClaw, auto-routing</span></div>
      <div class="feat"><span class="icon yes" style="color:var(--purple)">&#x2713;</span><span>MCP server tools (filesystem, fetch, memory, browser)</span></div>
      <div class="feat"><span class="icon yes" style="color:var(--purple)">&#x2713;</span><span>Full Finance engine — live transactions &amp; analytics</span></div>
      <div class="feat"><span class="icon yes" style="color:var(--purple)">&#x2713;</span><span>Multi-agent swarms &amp; pipelines</span></div>
      <div class="feat"><span class="icon yes" style="color:var(--purple)">&#x2713;</span><span>Priority support</span></div>
    </div>
    <div class="cta">
      <button class="btn-pro" id="upgrade-btn" onclick="startCheckout()">Upgrade to Pro &#x2192;</button>
    </div>
  </div>
</div>

<p class="notice">Cancel any time. Billed monthly. Secured by Stripe.</p>

<script>
var LOCAL_ID_KEY = 'orchestra_customer_id';

function getLocalId() {
  var id = localStorage.getItem(LOCAL_ID_KEY);
  if (!id) {
    id = 'lcl_' + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
    localStorage.setItem(LOCAL_ID_KEY, id);
  }
  return id;
}

async function loadStatus() {
  try {
    var r = await fetch('/api/billing/status', {
      headers: { 'X-Customer-Id': getLocalId() }
    });
    var d = await r.json();

    if (!d.stripe_configured) {
      document.getElementById('no-key-notice').style.display = 'block';
      document.getElementById('upgrade-btn').disabled = true;
      document.getElementById('upgrade-btn').textContent = 'Stripe not configured';
    }

    if (d.active) {
      document.getElementById('current-plan-banner').style.display = 'flex';
      document.getElementById('current-plan-text').textContent = 'Orchestra Pro — Active';
      document.getElementById('upgrade-btn').textContent = 'Already subscribed';
      document.getElementById('upgrade-btn').disabled = true;
    }
  } catch(e) {}
}

async function startCheckout() {
  var btn = document.getElementById('upgrade-btn');
  btn.disabled = true;
  btn.textContent = 'Loading…';
  try {
    var r = await fetch('/api/billing/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Customer-Id': getLocalId() },
      body: JSON.stringify({})
    });
    var d = await r.json();
    if (d.url) {
      window.location.href = d.url;
    } else {
      showError(d.detail || 'Could not start checkout');
      btn.disabled = false;
      btn.textContent = 'Upgrade to Pro →';
    }
  } catch(e) {
    showError(e.message);
    btn.disabled = false;
    btn.textContent = 'Upgrade to Pro →';
  }
}

async function openPortal() {
  try {
    var r = await fetch('/api/billing/portal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Customer-Id': getLocalId() },
      body: JSON.stringify({})
    });
    var d = await r.json();
    if (d.url) window.location.href = d.url;
  } catch(e) { showError(e.message); }
}

function showError(msg) {
  var el = document.getElementById('banner-error');
  el.textContent = msg;
  el.style.display = 'block';
}

// Success banner
var params = new URLSearchParams(location.search);
if (params.get('success') === '1') {
  document.getElementById('banner-success').style.display = 'block';
  // Clear query param without reload
  history.replaceState({}, '', '/billing');
}

loadStatus();
</script>
</body>
</html>
"""
