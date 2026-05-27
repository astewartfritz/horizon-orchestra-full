SETTINGS_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Settings — Orchestra</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0d1117; --bg2: #161b22; --bg3: #21262d;
  --border: #30363d; --text: #e6edf3; --muted: #8b949e;
  --blue: #58a6ff; --green: #3fb950; --purple: #a78bfa;
  --red: #f85149; --orange: #f0883e; --radius: 10px;
}
body { background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; min-height:100vh; }
.layout { display:flex; min-height:100vh; }
.sidebar { width:220px; border-right:1px solid var(--border); background:var(--bg2); flex-shrink:0; padding:24px 0; display:flex; flex-direction:column; }
.sidebar-back { display:flex; align-items:center; gap:8px; padding:0 20px 20px; color:var(--muted); font-size:13px; text-decoration:none; border-bottom:1px solid var(--border); margin-bottom:16px; }
.sidebar-back:hover { color:var(--text); }
.sidebar-section { font-size:10px; font-weight:700; color:var(--muted); letter-spacing:.8px; text-transform:uppercase; padding:0 20px 8px; }
.nav-item { display:block; padding:8px 20px; font-size:13px; color:var(--muted); cursor:pointer; border:none; background:none; text-align:left; font-family:inherit; width:100%; border-left:2px solid transparent; transition:all .15s; }
.nav-item:hover { color:var(--text); background:rgba(255,255,255,.03); }
.nav-item.active { color:var(--text); border-left-color:var(--blue); background:rgba(88,166,255,.06); }
.main { flex:1; overflow-y:auto; }
.section { display:none; max-width:680px; padding:32px 36px; }
.section.active { display:block; }
.section-title { font-size:20px; font-weight:800; margin-bottom:4px; }
.section-sub { font-size:13px; color:var(--muted); margin-bottom:28px; }
.card { background:var(--bg2); border:1px solid var(--border); border-radius:var(--radius); padding:20px 22px; margin-bottom:16px; }
.card-title { font-size:13px; font-weight:700; margin-bottom:4px; }
.card-desc { font-size:12px; color:var(--muted); margin-bottom:14px; line-height:1.5; }
.field-label { font-size:12px; color:var(--muted); margin-bottom:6px; display:block; }
.field-input { width:100%; background:var(--bg); border:1px solid var(--border); border-radius:8px; padding:9px 12px; color:var(--text); font-size:13px; font-family:inherit; outline:none; transition:border-color .15s; margin-bottom:12px; }
.field-input:focus { border-color:var(--blue); }
.field-input::placeholder { color:#484f58; }
.field-row { display:flex; gap:10px; align-items:flex-end; }
.field-row .field-input { margin-bottom:0; flex:1; }
.btn { padding:8px 18px; border-radius:8px; font-size:13px; font-weight:600; cursor:pointer; font-family:inherit; transition:opacity .15s; border:none; }
.btn-primary { background:var(--blue); color:#fff; }
.btn-primary:hover { opacity:.85; }
.btn-secondary { background:var(--bg3); border:1px solid var(--border); color:var(--muted); }
.btn-secondary:hover { color:var(--text); }
.btn-danger { background:rgba(248,81,73,.15); border:1px solid rgba(248,81,73,.3); color:var(--red); }
.btn-danger:hover { background:rgba(248,81,73,.25); }
.btn-purple { background:linear-gradient(135deg,#7c3aed,#6d28d9); color:#fff; }
.btn-purple:hover { opacity:.9; }
.status-dot { display:inline-block; width:7px; height:7px; border-radius:50%; margin-right:5px; }
.dot-green { background:var(--green); }
.dot-red { background:var(--red); }
.dot-orange { background:var(--orange); }
.connected-bar { display:flex; align-items:center; gap:10px; padding:10px 14px; background:rgba(63,185,80,.06); border:1px solid rgba(63,185,80,.2); border-radius:8px; margin-bottom:12px; }
.badge { font-size:11px; padding:2px 8px; border-radius:8px; font-weight:600; }
.badge-green { background:rgba(63,185,80,.12); color:var(--green); border:1px solid rgba(63,185,80,.25); }
.badge-purple { background:rgba(167,139,250,.12); color:var(--purple); border:1px solid rgba(167,139,250,.25); }
.badge-muted { background:var(--bg3); color:var(--muted); border:1px solid var(--border); }
.badge-orange { background:rgba(240,136,46,.12); color:var(--orange); border:1px solid rgba(240,136,46,.25); }
.radio-group { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
.radio-btn { padding:7px 16px; border:1px solid var(--border); border-radius:8px; font-size:12px; cursor:pointer; font-family:inherit; background:var(--bg3); color:var(--muted); transition:all .15s; }
.radio-btn.selected { border-color:var(--blue); background:rgba(88,166,255,.1); color:var(--blue); font-weight:600; }
.divider { border:none; border-top:1px solid var(--border); margin:20px 0; }
.theme-preview { display:flex; gap:8px; margin-bottom:12px; }
.theme-card { flex:1; border:2px solid var(--border); border-radius:8px; overflow:hidden; cursor:pointer; transition:border-color .15s; }
.theme-card.selected { border-color:var(--blue); }
.theme-card-preview { height:60px; }
.theme-card-label { font-size:11px; text-align:center; padding:6px; color:var(--muted); }
.model-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:12px; }
.model-card { border:1px solid var(--border); border-radius:8px; padding:10px 12px; cursor:pointer; transition:border-color .15s,background .15s; }
.model-card:hover { background:var(--bg3); }
.model-card.selected { border-color:var(--blue); background:rgba(88,166,255,.06); }
.model-name { font-size:12px; font-weight:700; }
.model-desc { font-size:10px; color:var(--muted); margin-top:2px; }
.toast-s { position:fixed; bottom:24px; right:24px; background:#238636; color:#fff; padding:10px 18px; border-radius:8px; font-size:13px; z-index:9999; display:none; }
@media (max-width:600px) { .sidebar { display:none; } .section { padding:20px 16px; } }
</style>
</head>
<body>
<div class="layout">
  <!-- Sidebar -->
  <nav class="sidebar">
    <a class="sidebar-back" href="/">&#x2190; Orchestra</a>
    <div class="sidebar-section">Settings</div>
    <button class="nav-item active" onclick="showSection('model')">&#x1F9E0; AI Model</button>
    <button class="nav-item" onclick="showSection('workspace')">&#x1F4C1; Workspace</button>
    <button class="nav-item" onclick="showSection('github')">&#x1F419; GitHub</button>
    <button class="nav-item" onclick="showSection('billing')">&#x1F4B3; Billing</button>
    <button class="nav-item" onclick="showSection('mcp')">&#x1F50C; MCP Servers</button>
    <button class="nav-item" onclick="showSection('appearance')">&#x1F3A8; Appearance</button>
    <button class="nav-item" onclick="showSection('notifications')">&#x1F514; Notifications</button>
    <div style="flex:1"></div>
    <div style="padding:16px 20px;font-size:11px;color:var(--muted);border-top:1px solid var(--border)">
      Orchestra &mdash; <span id="ver">v1.0</span>
    </div>
  </nav>

  <!-- Main content -->
  <main class="main">

    <!-- AI Model -->
    <div class="section active" id="sec-model">
      <div class="section-title">AI Model</div>
      <div class="section-sub">Choose which language model powers your agents.</div>

      <div class="card">
        <div class="card-title">Provider</div>
        <div class="card-desc">Select your preferred AI provider. You can change this per-session in the main chat.</div>
        <div class="radio-group" id="provider-group">
          <button class="radio-btn selected" data-val="anthropic" onclick="selectProvider(this)">Anthropic</button>
          <button class="radio-btn" data-val="openai" onclick="selectProvider(this)">OpenAI</button>
          <button class="radio-btn" data-val="moonshot" onclick="selectProvider(this)">Moonshot (Kimi)</button>
          <button class="radio-btn" data-val="ollama" onclick="selectProvider(this)">Ollama (local)</button>
          <button class="radio-btn" data-val="openrouter" onclick="selectProvider(this)">OpenRouter</button>
        </div>
        <label class="field-label" for="s-api-key">API Key <span id="key-required" style="color:var(--red);font-size:10px">* required</span></label>
        <div class="field-row">
          <input class="field-input" type="password" id="s-api-key" placeholder="Paste your API key">
          <button class="btn btn-primary" onclick="saveModelSettings()">Save</button>
        </div>
        <div id="key-hint" style="font-size:11px;color:var(--muted);margin-top:-6px"></div>
      </div>

      <div class="card">
        <div class="card-title">Default Model</div>
        <div class="card-desc">The model used for new sessions.</div>
        <div class="model-grid" id="model-grid"></div>
        <div style="font-size:11px;color:var(--muted)">All models are available in the main chat's model selector.</div>
      </div>
    </div>

    <!-- Workspace -->
    <div class="section" id="sec-workspace">
      <div class="section-title">Workspace</div>
      <div class="section-sub">The folder agents read from and write to by default.</div>
      <div class="card">
        <div class="card-title">Project folder</div>
        <div class="card-desc">Set the absolute path to your codebase. Agents will use this as their working directory.</div>
        <label class="field-label">Current workspace</label>
        <div class="field-row">
          <input class="field-input" type="text" id="s-workspace" placeholder="e.g. C:\\Users\\you\\project or /home/you/project">
          <button class="btn btn-primary" onclick="saveWorkspace()">Set</button>
        </div>
        <div id="ws-status" style="font-size:11px;color:var(--muted);margin-top:-6px"></div>
      </div>
    </div>

    <!-- GitHub -->
    <div class="section" id="sec-github">
      <div class="section-title">GitHub</div>
      <div class="section-sub">Connect your GitHub account to browse repos, clone code, and create pull requests.</div>
      <div id="gh-connected-card" class="card" style="display:none">
        <div class="connected-bar">
          <img id="s-gh-avatar" src="" width="28" height="28" style="border-radius:50%">
          <div style="flex:1">
            <div style="font-size:13px;font-weight:700" id="s-gh-user"></div>
            <div style="font-size:11px;color:var(--muted)" id="s-gh-repos"></div>
          </div>
          <span class="badge badge-green">Connected</span>
        </div>
        <button class="btn btn-danger" onclick="sGhDisconnect()">Disconnect</button>
      </div>
      <div id="gh-disconnected-card" class="card">
        <div class="card-title">Personal Access Token</div>
        <div class="card-desc">
          Create a token at <a href="https://github.com/settings/tokens/new?scopes=repo,read:user" target="_blank" style="color:var(--blue)">github.com/settings/tokens</a> with <strong>repo</strong> and <strong>read:user</strong> scopes.
        </div>
        <label class="field-label">Token</label>
        <div class="field-row">
          <input class="field-input" type="password" id="s-gh-token" placeholder="ghp_xxxxxxxxxxxxxxxxxxxx">
          <button class="btn btn-primary" onclick="sGhConnect()">Connect</button>
        </div>
        <div id="gh-error" style="font-size:11px;color:var(--red);margin-top:-6px;display:none"></div>
      </div>
      <div class="card">
        <div class="card-title">Environment variable</div>
        <div class="card-desc">You can also set <code style="background:var(--bg3);padding:1px 5px;border-radius:4px">GITHUB_TOKEN</code> in your shell environment. Orchestra picks it up automatically on start.</div>
      </div>
    </div>

    <!-- Billing -->
    <div class="section" id="sec-billing">
      <div class="section-title">Billing</div>
      <div class="section-sub">Manage your Orchestra Pro subscription.</div>
      <div id="billing-pro-card" class="card" style="display:none">
        <div class="connected-bar">
          <span style="font-size:18px">&#x2728;</span>
          <div style="flex:1">
            <div style="font-size:13px;font-weight:700">Orchestra Pro</div>
            <div style="font-size:11px;color:var(--muted)" id="billing-period"></div>
          </div>
          <span class="badge badge-purple">Active</span>
        </div>
        <div style="display:flex;gap:8px;margin-top:4px">
          <button class="btn btn-secondary" onclick="openPortal()">Manage subscription</button>
          <a href="/billing" target="_blank"><button class="btn btn-secondary">View billing page</button></a>
        </div>
      </div>
      <div id="billing-free-card" class="card">
        <div class="card-title">Free plan</div>
        <div class="card-desc">Upgrade to Pro to unlock autonomous code execution, all agent engines, MCP tools, and the full Finance suite.</div>
        <div style="display:flex;gap:10px;align-items:center">
          <button class="btn btn-purple" onclick="window.open('/billing','_blank')">Upgrade to Pro &mdash; $50/mo &#x2192;</button>
        </div>
      </div>
    </div>

    <!-- MCP -->
    <div class="section" id="sec-mcp">
      <div class="section-title">MCP Servers</div>
      <div class="section-sub">Model Context Protocol servers add tools to your agents.</div>
      <div class="card">
        <div id="mcp-settings-list" style="display:flex;flex-direction:column;gap:8px">
          <div style="color:var(--muted);font-size:12px">Loading&#x2026;</div>
        </div>
        <hr class="divider">
        <div style="display:flex;gap:8px">
          <button class="btn btn-primary" onclick="sConnectAllMCP()">Connect all ready servers</button>
        </div>
        <div style="font-size:11px;color:var(--muted);margin-top:8px">
          Add API keys as environment variables and restart to enable keyed servers.
        </div>
      </div>
    </div>

    <!-- Appearance -->
    <div class="section" id="sec-appearance">
      <div class="section-title">Appearance</div>
      <div class="section-sub">Customise how Orchestra looks.</div>
      <div class="card">
        <div class="card-title">Theme</div>
        <div class="theme-preview">
          <div class="theme-card selected" id="theme-dark" onclick="sSetTheme('dark')">
            <div class="theme-card-preview" style="background:#0d1117;border-bottom:1px solid #30363d;display:flex;padding:8px;gap:4px;flex-direction:column">
              <div style="height:6px;width:60%;background:#58a6ff;border-radius:3px"></div>
              <div style="height:4px;width:80%;background:#30363d;border-radius:2px"></div>
              <div style="height:4px;width:50%;background:#30363d;border-radius:2px"></div>
            </div>
            <div class="theme-card-label">Dark</div>
          </div>
          <div class="theme-card" id="theme-light" onclick="sSetTheme('light')">
            <div class="theme-card-preview" style="background:#f6f8fa;border-bottom:1px solid #d0d7de;display:flex;padding:8px;gap:4px;flex-direction:column">
              <div style="height:6px;width:60%;background:#0969da;border-radius:3px"></div>
              <div style="height:4px;width:80%;background:#d0d7de;border-radius:2px"></div>
              <div style="height:4px;width:50%;background:#d0d7de;border-radius:2px"></div>
            </div>
            <div class="theme-card-label" style="color:#636c76">Light</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Notifications -->
    <div class="section" id="sec-notifications">
      <div class="section-title">Notifications</div>
      <div class="section-sub">Get notified when long-running tasks complete.</div>
      <div class="card">
        <div class="card-title">Browser notifications</div>
        <div class="card-desc">Receive a browser push when an agent finishes a task, even if you&rsquo;ve switched tabs.</div>
        <button class="btn btn-primary" id="notif-btn" onclick="requestBrowserNotif()">Enable browser notifications</button>
        <div id="notif-status" style="font-size:11px;color:var(--muted);margin-top:10px"></div>
      </div>
      <div class="card">
        <div class="card-title">Email notifications</div>
        <div class="card-desc">Get an email when your task completes. Requires a Pro subscription.</div>
        <label class="field-label">Your email</label>
        <div class="field-row">
          <input class="field-input" type="email" id="s-email" placeholder="you@example.com">
          <button class="btn btn-primary" onclick="saveEmail()">Save</button>
        </div>
      </div>
    </div>

  </main>
</div>

<div class="toast-s" id="toast-s">Settings saved</div>

<script>
var LOCAL_ID_KEY = 'orchestra_customer_id';
function getLocalId() {
  var id = localStorage.getItem(LOCAL_ID_KEY);
  if (!id) { id = 'lcl_' + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2); localStorage.setItem(LOCAL_ID_KEY, id); }
  return id;
}

// ── Section navigation ────────────────────────────────────────────────────
function showSection(name) {
  document.querySelectorAll('.section').forEach(function(s) { s.classList.remove('active'); });
  document.querySelectorAll('.nav-item').forEach(function(n) { n.classList.remove('active'); });
  var s = document.getElementById('sec-' + name);
  if (s) s.classList.add('active');
  var nav = document.querySelector('.nav-item[onclick*="\\'' + name + '\\'"]');
  if (nav) nav.classList.add('active');

  if (name === 'mcp') loadMCPSettings();
  if (name === 'billing') loadBillingSettings();
  if (name === 'github') loadGitHubSettings();
}

function toast(msg) {
  var t = document.getElementById('toast-s');
  t.textContent = msg;
  t.style.display = 'block';
  setTimeout(function(){ t.style.display = 'none'; }, 2500);
}

// ── Model settings ────────────────────────────────────────────────────────
var _modelsByProvider = {
  anthropic:   [['claude-opus-4-7','Opus 4.7','Most capable, best for complex tasks'],['claude-sonnet-4-6','Sonnet 4.6','Fast and smart — best value'],['claude-haiku-4-5-20251001','Haiku 4.5','Fastest, great for quick tasks']],
  openai:      [['gpt-4o','GPT-4o','Flagship multimodal'],['gpt-4o-mini','GPT-4o mini','Fast and cheap'],['o1','o1','Deep reasoning']],
  moonshot:    [['kimi-k2.5','Kimi K2.5','262K ctx, reasoning, coding, vision'],['kimi-k2.5-openrouter','Kimi K2.5 (OpenRouter)','via OpenRouter fallback'],['kimi-k2.5-together','Kimi K2.5 (Together)','via Together fallback']],
  ollama:      [['llama3.2','Llama 3.2','Meta — local, free'],['gemma3','Gemma 3','Google — local'],['deepseek-r1:8b','DeepSeek R1','Reasoning model']],
  openrouter:  [['openai/gpt-4o','GPT-4o','via OpenRouter'],['anthropic/claude-opus-4','Claude Opus 4','via OpenRouter'],['meta-llama/llama-3.1-70b','Llama 3.1 70B','via OpenRouter']],
};
var _selectedProvider = localStorage.getItem('ca_provider') || 'anthropic';
var _selectedModel = localStorage.getItem('ca_model') || 'claude-opus-4-7';

function selectProvider(btn) {
  _selectedProvider = btn.dataset.val;
  document.querySelectorAll('#provider-group .radio-btn').forEach(function(b) { b.classList.remove('selected'); });
  btn.classList.add('selected');
  renderModelGrid();
  var noKey = _selectedProvider === 'ollama';
  document.getElementById('key-required').style.display = noKey ? 'none' : '';
  document.getElementById('s-api-key').placeholder = 'Paste your API key';
  var hints = { anthropic:'console.anthropic.com/settings/keys', openai:'platform.openai.com/api-keys', moonshot:'platform.moonshot.ai/api-keys', openrouter:'openrouter.ai/keys' };
  var h = hints[_selectedProvider];
  document.getElementById('key-hint').innerHTML = h ? 'Get your key at <a href="https://'+h+'" target="_blank" style="color:var(--blue)">'+h+'</a>' : '';
  loadKeyStatus();
}

function renderModelGrid() {
  var models = _modelsByProvider[_selectedProvider] || [];
  document.getElementById('model-grid').innerHTML = models.map(function(m) {
    var sel = m[0] === _selectedModel ? ' selected' : '';
    return '<div class="model-card'+sel+'" onclick="selectModel(this,\''+m[0]+'\')">'
      + '<div class="model-name">'+m[1]+'</div>'
      + '<div class="model-desc">'+m[2]+'</div>'
      + '</div>';
  }).join('');
}

function selectModel(el, val) {
  _selectedModel = val;
  document.querySelectorAll('.model-card').forEach(function(c) { c.classList.remove('selected'); });
  el.classList.add('selected');
}

async function saveModelSettings() {
  var key = document.getElementById('s-api-key').value.trim();
  try {
    localStorage.setItem('ca_provider', _selectedProvider);
    localStorage.setItem('ca_model', _selectedModel);
    // Store API key server-side (encrypted), not in localStorage
    if (key && _selectedProvider !== 'ollama') {
      var r = await fetch('/api/keys/' + _selectedProvider, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: key, label: _selectedProvider})
      });
      if (r.ok) {
        document.getElementById('s-api-key').value = '';
        document.getElementById('s-api-key').placeholder = '•••••••• (saved)';
      } else {
        var err = await r.json().catch(function(){return {};});
        toast('Key error: ' + (err.detail || r.status));
        return;
      }
    }
    if (window.opener) {
      window.opener.postMessage({ type:'settings_update', provider:_selectedProvider, model:_selectedModel }, '*');
    }
  } catch(e) { toast('Save failed: ' + e.message); return; }
  toast('Model settings saved');
}

async function loadKeyStatus() {
  if (_selectedProvider === 'ollama') { document.getElementById('key-hint').textContent = 'No key needed for local Ollama.'; return; }
  try {
    var r = await fetch('/api/keys/' + _selectedProvider + '/check');
    var d = await r.json();
    if (d.configured) {
      document.getElementById('s-api-key').placeholder = '•••••••• (saved server-side)';
    }
  } catch(e) {}
}

// ── Workspace ─────────────────────────────────────────────────────────────
function saveWorkspace() {
  var ws = document.getElementById('s-workspace').value.trim();
  try { localStorage.setItem('orchestra_workspace', ws); } catch(e) {}
  if (window.opener) window.opener.postMessage({ type:'settings_update', workspace:ws }, '*');
  document.getElementById('ws-status').textContent = ws ? '✓ Workspace set to: ' + ws : 'Cleared';
  toast('Workspace saved');
}

// ── GitHub ────────────────────────────────────────────────────────────────
async function loadGitHubSettings() {
  var token = localStorage.getItem('gh_token') || '';
  if (!token) return;
  try {
    var r = await fetch('/api/github/status', { headers: token ? {'X-GitHub-Token':token} : {} });
    var d = await r.json();
    if (d.connected) {
      document.getElementById('gh-disconnected-card').style.display = 'none';
      document.getElementById('gh-connected-card').style.display = '';
      document.getElementById('s-gh-avatar').src = d.user.avatar_url || '';
      document.getElementById('s-gh-user').textContent = d.user.login || '';
      document.getElementById('s-gh-repos').textContent = (d.user.public_repos||0) + ' repos';
    }
  } catch(e) {}
}

async function sGhConnect() {
  var token = document.getElementById('s-gh-token').value.trim();
  if (!token) return;
  var err = document.getElementById('gh-error');
  err.style.display = 'none';
  try {
    var r = await fetch('/api/github/status', { headers: {'X-GitHub-Token':token} });
    var d = await r.json();
    if (d.connected) {
      // Store token server-side, not in localStorage
      await fetch('/api/keys/github', {
        method: 'PUT',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({key: token, label: 'GitHub PAT'})
      });
      document.getElementById('s-gh-token').value = '';
      await loadGitHubSettings();
      toast('GitHub connected as ' + d.user.login);
    } else {
      err.textContent = 'Token invalid or expired.';
      err.style.display = '';
    }
  } catch(e) {
    err.textContent = e.message;
    err.style.display = '';
  }
}

async function sGhDisconnect() {
  await fetch('/api/keys/github', {method: 'DELETE'}).catch(function(){});
  document.getElementById('gh-disconnected-card').style.display = '';
  document.getElementById('gh-connected-card').style.display = 'none';
  toast('GitHub disconnected');
}

// ── Billing ───────────────────────────────────────────────────────────────
async function loadBillingSettings() {
  try {
    var r = await fetch('/api/billing/status', { headers: {'X-Customer-Id': getLocalId()} });
    var d = await r.json();
    if (d.active) {
      document.getElementById('billing-free-card').style.display = 'none';
      document.getElementById('billing-pro-card').style.display = '';
      var ts = d.current_period_end ? new Date(d.current_period_end*1000).toLocaleDateString() : '';
      document.getElementById('billing-period').textContent = ts ? 'Renews ' + ts : 'Active';
    }
  } catch(e) {}
}

async function openPortal() {
  try {
    var r = await fetch('/api/billing/portal', {
      method: 'POST',
      headers: {'Content-Type':'application/json','X-Customer-Id':getLocalId()},
      body: '{}'
    });
    var d = await r.json();
    if (d.url) window.open(d.url, '_blank');
  } catch(e) { alert('Could not open portal: ' + e.message); }
}

// ── MCP ───────────────────────────────────────────────────────────────────
async function loadMCPSettings() {
  try {
    var r = await fetch('/api/mcp/status');
    var d = await r.json();
    var list = document.getElementById('mcp-settings-list');
    var servers = d.servers || [];
    if (!servers.length) { list.innerHTML = '<div style="color:var(--muted);font-size:12px">No MCP servers configured.</div>'; return; }
    list.innerHTML = servers.map(function(s) {
      var dot = s.connected ? 'dot-green' : (s.ready ? 'dot-orange' : 'dot-red');
      var badge = s.connected ? 'badge-green' : (s.ready ? 'badge-orange' : 'badge-muted');
      var badgeText = s.connected ? 'Connected' : (s.ready ? 'Ready' : 'Needs key');
      var keyStr = s.needs_keys && s.needs_keys.length ? ' — set ' + s.needs_keys.join(', ') : '';
      return '<div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)">'
        + '<span class="status-dot '+dot+'"></span>'
        + '<div style="flex:1;min-width:0"><div style="font-size:12px;font-weight:600">'+s.name+'</div><div style="font-size:11px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+(s.description||'')+keyStr+'</div></div>'
        + '<span class="badge '+badge+'">'+badgeText+'</span>'
        + (s.ready && !s.connected ? '<button onclick="sMCPConnect(\''+s.name+'\')" style="background:none;border:1px solid var(--border);color:var(--muted);padding:3px 8px;border-radius:5px;font-size:11px;cursor:pointer;font-family:inherit">Connect</button>' : '')
        + '</div>';
    }).join('');
  } catch(e) {}
}

async function sMCPConnect(name) {
  await fetch('/api/mcp/connect/'+name, {method:'POST'});
  await loadMCPSettings();
  toast('Connecting ' + name + '…');
}

async function sConnectAllMCP() {
  await fetch('/api/mcp/connect', {method:'POST'});
  toast('Connecting all ready servers…');
  setTimeout(loadMCPSettings, 2000);
}

// ── Appearance ────────────────────────────────────────────────────────────
function sSetTheme(t) {
  document.getElementById('theme-dark').classList.toggle('selected', t === 'dark');
  document.getElementById('theme-light').classList.toggle('selected', t === 'light');
  try { localStorage.setItem('orchestra-theme', t); } catch(e) {}
  if (window.opener) window.opener.postMessage({ type:'theme_change', theme:t }, '*');
  toast('Theme set to ' + t);
}

// ── Notifications ─────────────────────────────────────────────────────────
function updateNotifStatus() {
  var s = document.getElementById('notif-status');
  var b = document.getElementById('notif-btn');
  if (!('Notification' in window)) { s.textContent = 'Browser notifications not supported.'; b.disabled = true; return; }
  if (Notification.permission === 'granted') { s.textContent = '✓ Browser notifications are enabled.'; b.textContent = 'Enabled'; b.disabled = true; }
  else if (Notification.permission === 'denied') { s.textContent = 'Notifications blocked. Enable in browser settings.'; b.disabled = true; }
  else { s.textContent = 'Click the button to enable.'; }
}

function requestBrowserNotif() {
  Notification.requestPermission().then(function(p) { updateNotifStatus(); if (p === 'granted') toast('Notifications enabled!'); });
}

function saveEmail() {
  var email = document.getElementById('s-email').value.trim();
  try { localStorage.setItem('orchestra_email', email); } catch(e) {}
  toast('Email saved');
}

// ── Init ──────────────────────────────────────────────────────────────────
(function() {
  // Load saved values
  try {
    var p = localStorage.getItem('ca_provider') || 'anthropic';
    var m = localStorage.getItem('ca_model') || 'claude-opus-4-7';
    var k = localStorage.getItem('ca_api_key') || '';
    var ws = localStorage.getItem('orchestra_workspace') || '';
    var em = localStorage.getItem('orchestra_email') || '';
    var theme = localStorage.getItem('orchestra-theme') || 'dark';

    _selectedProvider = p;
    _selectedModel = m;

    // Set provider radio
    document.querySelectorAll('#provider-group .radio-btn').forEach(function(b) {
      b.classList.toggle('selected', b.dataset.val === p);
    });
    renderModelGrid();
    if (k) document.getElementById('s-api-key').value = k;
    if (ws) document.getElementById('s-workspace').value = ws;
    if (em) document.getElementById('s-email').value = em;

    // Theme cards
    document.getElementById('theme-dark').classList.toggle('selected', theme === 'dark');
    document.getElementById('theme-light').classList.toggle('selected', theme === 'light');

    // Notification status
    updateNotifStatus();

    // Handle hash nav
    var hash = location.hash.replace('#','');
    if (hash) showSection(hash);
  } catch(e) {}
})();

// Handle messages from parent window (settings sync)
window.addEventListener('message', function(e) {
  if (e.data && e.data.type === 'request_settings') {
    var k = localStorage.getItem('ca_api_key') || '';
    var p = localStorage.getItem('ca_provider') || 'anthropic';
    var m = localStorage.getItem('ca_model') || 'claude-opus-4-7';
    e.source.postMessage({ type:'settings_update', provider:p, model:m, api_key:k }, '*');
  }
});
</script>
</body>
</html>
"""
