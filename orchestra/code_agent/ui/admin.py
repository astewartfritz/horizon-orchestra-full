ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin — Orchestra</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d1117;--bg2:#161b22;--bg3:#21262d;
  --border:#30363d;--text:#e6edf3;--muted:#8b949e;
  --blue:#58a6ff;--green:#3fb950;--purple:#a78bfa;
  --red:#f85149;--orange:#f0883e;--radius:10px;
}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh}
.layout{display:flex;min-height:100vh}
.sidebar{width:240px;border-right:1px solid var(--border);background:var(--bg2);flex-shrink:0;padding:24px 0;display:flex;flex-direction:column}
.sidebar-logo{display:flex;align-items:center;gap:10px;padding:0 20px 20px;border-bottom:1px solid var(--border);margin-bottom:16px}
.sidebar-logo svg{width:24px;height:24px}
.logo-text{font-size:16px;font-weight:800;letter-spacing:-.3px}
.sidebar-section{font-size:10px;font-weight:700;color:var(--muted);letter-spacing:.8px;text-transform:uppercase;padding:8px 20px 6px}
.nav-item{display:flex;align-items:center;gap:8px;padding:8px 20px;font-size:13px;color:var(--muted);cursor:pointer;border:none;background:none;text-align:left;font-family:inherit;width:100%;border-left:2px solid transparent;transition:all .15s}
.nav-item:hover{color:var(--text);background:rgba(255,255,255,.03)}
.nav-item.active{color:var(--text);border-left-color:var(--blue);background:rgba(88,166,255,.06)}
.nav-back{display:flex;align-items:center;gap:8px;padding:8px 20px 16px;font-size:13px;color:var(--muted);cursor:pointer;text-decoration:none;border-bottom:1px solid var(--border);margin-bottom:8px}
.nav-back:hover{color:var(--text)}
.main{flex:1;overflow-y:auto;padding:32px 36px;max-width:900px}
.page{display:none}.page.active{display:block}
.page-title{font-size:22px;font-weight:800;margin-bottom:4px}
.page-sub{font-size:13px;color:var(--muted);margin-bottom:28px}
.card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:20px 22px;margin-bottom:16px}
.card-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
.card-title{font-size:14px;font-weight:700}
.card-sub{font-size:12px;color:var(--muted);margin-top:2px}
.field-label{font-size:12px;color:var(--muted);margin-bottom:6px;display:block}
.field-input{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:9px 12px;color:var(--text);font-size:13px;font-family:inherit;outline:none;transition:border-color .15s;margin-bottom:12px}
.field-input:focus{border-color:var(--blue)}
.field-input::placeholder{color:#484f58}
.field-row{display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap}
.field-row .field-input{margin-bottom:0;flex:1;min-width:160px}
select.field-input{cursor:pointer}
.btn{padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;transition:opacity .15s;border:none;white-space:nowrap}
.btn-primary{background:var(--blue);color:#fff}.btn-primary:hover{opacity:.85}
.btn-danger{background:var(--red);color:#fff}.btn-danger:hover{opacity:.85}
.btn-ghost{background:transparent;color:var(--muted);border:1px solid var(--border)}.btn-ghost:hover{color:var(--text)}
.btn-sm{padding:5px 12px;font-size:12px}
.badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600}
.badge-owner{background:rgba(167,139,250,.15);color:var(--purple)}
.badge-admin{background:rgba(88,166,255,.15);color:var(--blue)}
.badge-member{background:rgba(63,185,80,.15);color:var(--green)}
.badge-viewer{background:rgba(139,148,158,.15);color:var(--muted)}
.badge-pending{background:rgba(240,136,62,.15);color:var(--orange)}
.badge-free{background:rgba(139,148,158,.12);color:var(--muted)}
.badge-pro{background:rgba(88,166,255,.15);color:var(--blue)}
.badge-enterprise{background:rgba(167,139,250,.15);color:var(--purple)}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;padding:8px 12px;border-bottom:1px solid var(--border)}
td{padding:10px 12px;border-bottom:1px solid rgba(48,54,61,.5);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.02)}
.empty{text-align:center;padding:32px;color:var(--muted);font-size:13px}
.toast{position:fixed;bottom:24px;right:24px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:12px 18px;font-size:13px;color:var(--text);z-index:9999;opacity:0;transform:translateY(8px);transition:all .25s;pointer-events:none;max-width:320px}
.toast.show{opacity:1;transform:translateY(0)}
.toast.success{border-color:var(--green);color:var(--green)}
.toast.error{border-color:var(--red);color:var(--red)}
.org-selector{display:flex;align-items:center;gap:10px;margin-bottom:24px;flex-wrap:wrap}
.org-selector select{max-width:320px}
.stat-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:20px}
.stat{background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:14px 16px}
.stat-val{font-size:22px;font-weight:800;margin-bottom:2px}
.stat-lbl{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.compliance-row{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--border)}
.compliance-row:last-child{border-bottom:none}
.compliance-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.dot-green{background:var(--green)}.dot-orange{background:var(--orange)}.dot-red{background:var(--red)}
.compliance-label{font-size:13px;flex:1}
.compliance-detail{font-size:12px;color:var(--muted)}
@media(max-width:680px){
  .layout{flex-direction:column}
  .sidebar{width:100%;flex-direction:row;flex-wrap:wrap;padding:12px;border-right:none;border-bottom:1px solid var(--border)}
  .sidebar-logo{border-bottom:none;margin-bottom:0;padding:0 12px 0 0}
  .nav-item{padding:6px 12px;border-left:none;border-bottom:2px solid transparent}
  .nav-item.active{border-left-color:transparent;border-bottom-color:var(--blue)}
  .nav-back,.sidebar-section{display:none}
  .main{padding:16px}
}
</style>
</head>
<body>
<div class="layout">
  <!-- Sidebar -->
  <div class="sidebar">
    <div class="sidebar-logo">
      <svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="#58a6ff" stroke-width="2"/><path d="M8 12h8M12 8v8" stroke="#58a6ff" stroke-width="2" stroke-linecap="round"/></svg>
      <span class="logo-text">Orchestra</span>
    </div>
    <a class="nav-back" href="/app">← Back to app</a>
    <div class="sidebar-section">Organization</div>
    <button class="nav-item active" onclick="showPage('overview')">Overview</button>
    <button class="nav-item" onclick="showPage('members')">Members</button>
    <button class="nav-item" onclick="showPage('invites')">Invitations</button>
    <button class="nav-item" onclick="showPage('teams')">Teams</button>
    <div class="sidebar-section" style="margin-top:12px">Access</div>
    <button class="nav-item" onclick="showPage('access-control')" id="nav-access-control">&#x1F512; User Approvals</button>
    <div class="sidebar-section" style="margin-top:12px">System</div>
    <button class="nav-item" onclick="showPage('compliance')">Compliance</button>
    <button class="nav-item" onclick="showPage('settings')">Org Settings</button>
  </div>

  <!-- Main content -->
  <div class="main">
    <!-- Org selector -->
    <div class="org-selector">
      <label class="field-label" style="margin:0;white-space:nowrap">Organization:</label>
      <select class="field-input" id="orgSelect" onchange="switchOrg(this.value)" style="margin:0;max-width:280px"></select>
      <button class="btn btn-primary btn-sm" onclick="showCreateOrg()">+ New org</button>
    </div>

    <!-- Create org modal inline -->
    <div id="createOrgCard" class="card" style="display:none;margin-bottom:24px">
      <div class="card-title" style="margin-bottom:14px">Create new organization</div>
      <label class="field-label">Name</label>
      <input id="newOrgName" class="field-input" placeholder="Acme Corp">
      <label class="field-label">Plan</label>
      <select id="newOrgPlan" class="field-input">
        <option value="free">Free</option>
        <option value="pro">Pro</option>
        <option value="enterprise">Enterprise</option>
      </select>
      <div style="display:flex;gap:10px">
        <button class="btn btn-primary" onclick="createOrg()">Create</button>
        <button class="btn btn-ghost" onclick="document.getElementById('createOrgCard').style.display='none'">Cancel</button>
      </div>
    </div>

    <!-- Overview -->
    <div id="page-overview" class="page active">
      <div class="page-title">Overview</div>
      <div class="page-sub" id="overviewSub">Loading…</div>
      <div class="stat-row" id="statsRow">
        <div class="stat"><div class="stat-val" id="statMembers">—</div><div class="stat-lbl">Members</div></div>
        <div class="stat"><div class="stat-val" id="statTeams">—</div><div class="stat-lbl">Teams</div></div>
        <div class="stat"><div class="stat-val" id="statInvites">—</div><div class="stat-lbl">Pending Invites</div></div>
        <div class="stat"><div class="stat-val" id="statPlan">—</div><div class="stat-lbl">Plan</div></div>
      </div>
      <div class="card">
        <div class="card-title">Org details</div>
        <table id="overviewTable" style="margin-top:12px">
          <tbody id="overviewBody"></tbody>
        </table>
      </div>
    </div>

    <!-- Members -->
    <div id="page-members" class="page">
      <div class="page-title">Members</div>
      <div class="page-sub">Manage org membership and roles.</div>
      <div class="card">
        <div class="card-header">
          <div><div class="card-title">Current members</div></div>
          <button class="btn btn-primary btn-sm" onclick="showPage('invites')">Invite member</button>
        </div>
        <table>
          <thead><tr><th>User ID</th><th>Role</th><th>Status</th><th>Joined</th><th>Actions</th></tr></thead>
          <tbody id="membersBody"><tr><td colspan="5" class="empty">Loading…</td></tr></tbody>
        </table>
      </div>
    </div>

    <!-- Invites -->
    <div id="page-invites" class="page">
      <div class="page-title">Invitations</div>
      <div class="page-sub">Send email invites or cancel pending ones.</div>
      <div class="card">
        <div class="card-title" style="margin-bottom:14px">Send invitation</div>
        <div class="field-row">
          <input id="inviteEmail" class="field-input" placeholder="colleague@company.com" type="email">
          <select id="inviteRole" class="field-input" style="max-width:140px">
            <option value="member">Member</option>
            <option value="admin">Admin</option>
            <option value="viewer">Viewer</option>
          </select>
          <button class="btn btn-primary" onclick="sendInvite()">Send invite</button>
        </div>
      </div>
      <div class="card">
        <div class="card-title" style="margin-bottom:12px">Pending invitations</div>
        <table>
          <thead><tr><th>Email</th><th>Role</th><th>Expires</th><th>Invited by</th><th></th></tr></thead>
          <tbody id="invitesBody"><tr><td colspan="5" class="empty">Loading…</td></tr></tbody>
        </table>
      </div>
    </div>

    <!-- Teams -->
    <div id="page-teams" class="page">
      <div class="page-title">Teams</div>
      <div class="page-sub">Organize members into teams for project-level access.</div>
      <div class="card">
        <div class="card-title" style="margin-bottom:14px">Create team</div>
        <div class="field-row">
          <input id="teamName" class="field-input" placeholder="Team name">
          <input id="teamDesc" class="field-input" placeholder="Description (optional)">
          <button class="btn btn-primary" onclick="createTeam()">Create</button>
        </div>
      </div>
      <div id="teamsContainer"></div>
    </div>

    <!-- Compliance -->
    <div id="page-compliance" class="page">
      <div class="page-title">Compliance</div>
      <div class="page-sub">System-level compliance posture for this organization.</div>
      <div class="card">
        <div id="complianceChecks">Loading…</div>
      </div>
    </div>

    <!-- Org Settings -->
    <div id="page-settings" class="page">
      <div class="page-title">Org Settings</div>
      <div class="page-sub">Update organization name and plan.</div>
      <div class="card">
        <label class="field-label">Organization name</label>
        <input id="settingsName" class="field-input">
        <label class="field-label">Plan</label>
        <select id="settingsPlan" class="field-input">
          <option value="free">Free</option>
          <option value="pro">Pro</option>
          <option value="enterprise">Enterprise</option>
        </select>
        <div style="display:flex;gap:10px;margin-top:4px">
          <button class="btn btn-primary" onclick="saveOrgSettings()">Save changes</button>
        </div>
      </div>
      <div class="card" style="border-color:rgba(248,81,73,.3)">
        <div class="card-title" style="color:var(--red)">Danger zone</div>
        <div class="card-sub" style="margin-top:4px;margin-bottom:14px">Permanently delete this organization and all its data.</div>
        <button class="btn btn-danger" onclick="confirmDeleteOrg()">Delete organization</button>
      </div>
    </div>

    <!-- Access Control page -->
    <div id="page-access-control" class="page">
      <div class="page-title">&#x1F512; User Approvals</div>
      <div class="page-sub">Control who can use Orchestra. New sign-ups are pending until you approve them.</div>
      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
          <div style="font-size:13px;font-weight:600">All users</div>
          <button class="btn btn-primary btn-sm" onclick="loadAccessControl()">&#x21BB; Refresh</button>
        </div>
        <div id="user-list"><div style="color:#8b949e;padding:12px">Loading…</div></div>
      </div>
      <div class="card" style="margin-top:20px;border-color:rgba(88,166,255,.25);background:rgba(31,111,235,.06)">
        <div class="card-title" style="color:#58a6ff">How it works</div>
        <ul style="margin:10px 0 0 16px;color:#8b949e;font-size:12px;line-height:1.8">
          <li>Your account (<strong style="color:#e6edf3">ashtonfritz3@gmail.com</strong>) always has unlimited access — no rate limits, no billing gates.</li>
          <li>Everyone else who signs up starts as <strong style="color:#f0883e">PENDING</strong> and cannot use the API until you approve them.</li>
          <li>Approved users get normal access with standard rate limits.</li>
          <li>You can remove any user at any time.</li>
        </ul>
      </div>
    </div>

  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let _token = localStorage.getItem('orchestra_token') || '';
let _currentOrg = null;
let _orgs = [];

// ── Helpers ───────────────────────────────────────────────────────────────
function toast(msg, type='') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show ' + type;
  setTimeout(() => { el.className = 'toast'; }, 3500);
}
async function api(method, path, body) {
  const r = await fetch(path, {
    method,
    headers: {'Content-Type':'application/json', 'Authorization': 'Bearer '+_token},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 204) return null;
  const j = await r.json().catch(() => null);
  if (!r.ok) throw new Error((j && (j.detail || j.error)) || r.statusText);
  return j;
}
function fmtDate(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleDateString();
}
function roleBadge(role) {
  return `<span class="badge badge-${role}">${role}</span>`;
}
function planBadge(plan) {
  return `<span class="badge badge-${plan}">${plan}</span>`;
}

// ── Navigation ────────────────────────────────────────────────────────────
function showPage(id) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + id).classList.add('active');
  const btns = document.querySelectorAll('.nav-item');
  btns.forEach(b => { if (b.textContent.toLowerCase().includes(id)) b.classList.add('active'); });
  if (id === 'overview') loadOverview();
  else if (id === 'members') loadMembers();
  else if (id === 'invites') loadInvites();
  else if (id === 'teams') loadTeams();
  else if (id === 'compliance') loadCompliance();
  else if (id === 'settings') loadSettings();
}

// ── Orgs ──────────────────────────────────────────────────────────────────
async function loadOrgs() {
  if (!_token) { return promptLogin(); }
  try {
    _orgs = await api('GET', '/api/orgs');
    const sel = document.getElementById('orgSelect');
    sel.innerHTML = '';
    if (!_orgs.length) {
      sel.innerHTML = '<option value="">No organizations</option>';
      return;
    }
    _orgs.forEach(o => {
      const opt = document.createElement('option');
      opt.value = o.id; opt.textContent = o.name + ' (' + o.plan + ')';
      sel.appendChild(opt);
    });
    _currentOrg = _orgs[0];
    sel.value = _currentOrg.id;
    loadOverview();
  } catch(e) { toast(e.message, 'error'); }
}

function switchOrg(id) {
  _currentOrg = _orgs.find(o => o.id === id) || null;
  const active = document.querySelector('.page.active');
  if (active) showPage(active.id.replace('page-',''));
}

function showCreateOrg() {
  document.getElementById('createOrgCard').style.display = 'block';
}
async function createOrg() {
  const name = document.getElementById('newOrgName').value.trim();
  const plan = document.getElementById('newOrgPlan').value;
  if (!name) { toast('Name required', 'error'); return; }
  try {
    const org = await api('POST', '/api/orgs', {name, plan});
    toast('Organization created', 'success');
    document.getElementById('createOrgCard').style.display = 'none';
    document.getElementById('newOrgName').value = '';
    await loadOrgs();
    document.getElementById('orgSelect').value = org.id;
    switchOrg(org.id);
  } catch(e) { toast(e.message, 'error'); }
}

// ── Overview ──────────────────────────────────────────────────────────────
async function loadOverview() {
  if (!_currentOrg) return;
  const o = _currentOrg;
  document.getElementById('overviewSub').textContent = o.slug + ' · created ' + fmtDate(o.created_at);
  document.getElementById('statPlan').innerHTML = planBadge(o.plan);

  try {
    const [members, teams, invites] = await Promise.all([
      api('GET', '/api/orgs/'+o.id+'/members'),
      api('GET', '/api/orgs/'+o.id+'/teams'),
      api('GET', '/api/orgs/'+o.id+'/invites?status=pending').catch(() => []),
    ]);
    document.getElementById('statMembers').textContent = members.length;
    document.getElementById('statTeams').textContent = teams.length;
    document.getElementById('statInvites').textContent = invites.length;
    document.getElementById('overviewBody').innerHTML = `
      <tr><td style="color:var(--muted);width:140px">Name</td><td>${o.name}</td></tr>
      <tr><td style="color:var(--muted)">Slug</td><td><code>${o.slug}</code></td></tr>
      <tr><td style="color:var(--muted)">Plan</td><td>${planBadge(o.plan)}</td></tr>
      <tr><td style="color:var(--muted)">Owner</td><td><code>${o.owner_user_id}</code></td></tr>
      <tr><td style="color:var(--muted)">Created</td><td>${fmtDate(o.created_at)}</td></tr>
    `;
  } catch(e) { toast(e.message, 'error'); }
}

// ── Members ───────────────────────────────────────────────────────────────
async function loadMembers() {
  if (!_currentOrg) return;
  try {
    const members = await api('GET', '/api/orgs/'+_currentOrg.id+'/members');
    const tbody = document.getElementById('membersBody');
    if (!members.length) { tbody.innerHTML = '<tr><td colspan="5" class="empty">No members</td></tr>'; return; }
    tbody.innerHTML = members.map(m => `
      <tr>
        <td><code style="font-size:12px">${m.user_id.slice(0,12)}…</code></td>
        <td>
          <select onchange="updateRole('${m.user_id}', this.value)" style="background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:3px 6px;font-size:12px">
            ${['owner','admin','member','viewer'].map(r => `<option value="${r}" ${m.role===r?'selected':''}>${r}</option>`).join('')}
          </select>
        </td>
        <td><span class="badge badge-${m.status==='active'?'member':'viewer'}">${m.status}</span></td>
        <td>${fmtDate(m.joined_at)}</td>
        <td><button class="btn btn-danger btn-sm" onclick="removeMember('${m.user_id}')">Remove</button></td>
      </tr>
    `).join('');
  } catch(e) { toast(e.message,'error'); }
}
async function updateRole(userId, role) {
  try {
    await api('PATCH', '/api/orgs/'+_currentOrg.id+'/members/'+userId, {role});
    toast('Role updated', 'success');
  } catch(e) { toast(e.message,'error'); loadMembers(); }
}
async function removeMember(userId) {
  if (!confirm('Remove this member from the org?')) return;
  try {
    await api('DELETE', '/api/orgs/'+_currentOrg.id+'/members/'+userId);
    toast('Member removed', 'success');
    loadMembers();
  } catch(e) { toast(e.message,'error'); }
}

// ── Invites ───────────────────────────────────────────────────────────────
async function loadInvites() {
  if (!_currentOrg) return;
  try {
    const invites = await api('GET', '/api/orgs/'+_currentOrg.id+'/invites?status=pending');
    const tbody = document.getElementById('invitesBody');
    if (!invites.length) { tbody.innerHTML = '<tr><td colspan="5" class="empty">No pending invitations</td></tr>'; return; }
    tbody.innerHTML = invites.map(i => `
      <tr>
        <td>${i.email}</td>
        <td>${roleBadge(i.role)}</td>
        <td>${fmtDate(i.expires_at)}</td>
        <td><code style="font-size:11px">${i.invited_by.slice(0,8)}…</code></td>
        <td><button class="btn btn-danger btn-sm" onclick="cancelInvite('${i.id}')">Cancel</button></td>
      </tr>
    `).join('');
  } catch(e) { toast(e.message,'error'); }
}
async function sendInvite() {
  const email = document.getElementById('inviteEmail').value.trim();
  const role = document.getElementById('inviteRole').value;
  if (!email) { toast('Email required','error'); return; }
  try {
    await api('POST', '/api/orgs/'+_currentOrg.id+'/invites', {email, role});
    toast('Invitation sent to '+email, 'success');
    document.getElementById('inviteEmail').value = '';
    loadInvites();
  } catch(e) { toast(e.message,'error'); }
}
async function cancelInvite(id) {
  try {
    await api('DELETE', '/api/orgs/'+_currentOrg.id+'/invites/'+id);
    toast('Invitation cancelled','success');
    loadInvites();
  } catch(e) { toast(e.message,'error'); }
}

// ── Teams ─────────────────────────────────────────────────────────────────
async function loadTeams() {
  if (!_currentOrg) return;
  try {
    const teams = await api('GET', '/api/orgs/'+_currentOrg.id+'/teams');
    const container = document.getElementById('teamsContainer');
    if (!teams.length) { container.innerHTML = '<div class="card"><div class="empty">No teams yet — create one above.</div></div>'; return; }
    container.innerHTML = teams.map(t => `
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">${t.name}</div>
            <div class="card-sub">${t.description || 'No description'}</div>
          </div>
          <button class="btn btn-danger btn-sm" onclick="deleteTeam('${t.id}')">Delete</button>
        </div>
        <div id="team-members-${t.id}">Loading…</div>
        <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
          <input id="tm-uid-${t.id}" class="field-input" placeholder="User ID" style="flex:1;min-width:160px;margin:0">
          <select id="tm-role-${t.id}" class="field-input" style="max-width:110px;margin:0">
            <option value="member">Member</option>
            <option value="lead">Lead</option>
          </select>
          <button class="btn btn-primary btn-sm" onclick="addToTeam('${t.id}')">Add</button>
        </div>
      </div>
    `).join('');
    teams.forEach(t => loadTeamMembers(t.id));
  } catch(e) { toast(e.message,'error'); }
}
async function loadTeamMembers(teamId) {
  try {
    const members = await api('GET', '/api/orgs/'+_currentOrg.id+'/teams/'+teamId+'/members');
    const el = document.getElementById('team-members-'+teamId);
    if (!members.length) { el.innerHTML = '<div style="font-size:12px;color:var(--muted)">No members yet</div>'; return; }
    el.innerHTML = '<table><tbody>' + members.map(m => `
      <tr>
        <td><code style="font-size:12px">${m.user_id.slice(0,12)}…</code></td>
        <td>${roleBadge(m.role)}</td>
        <td><button class="btn btn-ghost btn-sm" onclick="removeFromTeam('${teamId}','${m.user_id}')">Remove</button></td>
      </tr>
    `).join('') + '</tbody></table>';
  } catch(e) {}
}
async function createTeam() {
  const name = document.getElementById('teamName').value.trim();
  const description = document.getElementById('teamDesc').value.trim();
  if (!name) { toast('Team name required','error'); return; }
  try {
    await api('POST', '/api/orgs/'+_currentOrg.id+'/teams', {name, description});
    toast('Team created','success');
    document.getElementById('teamName').value = '';
    document.getElementById('teamDesc').value = '';
    loadTeams();
  } catch(e) { toast(e.message,'error'); }
}
async function deleteTeam(id) {
  if (!confirm('Delete this team?')) return;
  try {
    await api('DELETE', '/api/orgs/'+_currentOrg.id+'/teams/'+id);
    toast('Team deleted','success');
    loadTeams();
  } catch(e) { toast(e.message,'error'); }
}
async function addToTeam(teamId) {
  const userId = document.getElementById('tm-uid-'+teamId).value.trim();
  const role = document.getElementById('tm-role-'+teamId).value;
  if (!userId) { toast('User ID required','error'); return; }
  try {
    await api('POST', '/api/orgs/'+_currentOrg.id+'/teams/'+teamId+'/members', {user_id: userId, role});
    toast('Added to team','success');
    document.getElementById('tm-uid-'+teamId).value = '';
    loadTeamMembers(teamId);
  } catch(e) { toast(e.message,'error'); }
}
async function removeFromTeam(teamId, userId) {
  try {
    await api('DELETE', '/api/orgs/'+_currentOrg.id+'/teams/'+teamId+'/members/'+userId);
    toast('Removed from team','success');
    loadTeamMembers(teamId);
  } catch(e) { toast(e.message,'error'); }
}

// ── Compliance ────────────────────────────────────────────────────────────
async function loadCompliance() {
  try {
    const data = await api('GET', '/api/admin/readiness');
    const checks = data.checks || [];
    const el = document.getElementById('complianceChecks');
    el.innerHTML = `<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
      <div style="font-size:28px;font-weight:800;color:${data.score>=80?'var(--green)':data.score>=60?'var(--orange)':'var(--red)'}">${data.score}%</div>
      <div><div style="font-size:14px;font-weight:700">Compliance score</div><div style="font-size:12px;color:var(--muted)">${data.passed}/${data.total} checks passing</div></div>
    </div>` + checks.map(c => `
      <div class="compliance-row">
        <div class="compliance-dot ${c.passed?'dot-green':'dot-red'}"></div>
        <div class="compliance-label">${c.name.replace(/_/g,' ')}</div>
        <div class="compliance-detail">${c.detail||''}</div>
      </div>
    `).join('');
  } catch(e) { document.getElementById('complianceChecks').textContent = 'Unable to load compliance data.'; }
}

// ── Org Settings ──────────────────────────────────────────────────────────
function loadSettings() {
  if (!_currentOrg) return;
  document.getElementById('settingsName').value = _currentOrg.name;
  document.getElementById('settingsPlan').value = _currentOrg.plan;
}
async function saveOrgSettings() {
  const name = document.getElementById('settingsName').value.trim();
  const plan = document.getElementById('settingsPlan').value;
  if (!name) { toast('Name required','error'); return; }
  try {
    const updated = await api('PATCH', '/api/orgs/'+_currentOrg.id, {name, plan});
    _currentOrg = updated;
    _orgs = _orgs.map(o => o.id === updated.id ? updated : o);
    const sel = document.getElementById('orgSelect');
    const opt = sel.querySelector(`option[value="${updated.id}"]`);
    if (opt) opt.textContent = updated.name + ' (' + updated.plan + ')';
    toast('Settings saved','success');
  } catch(e) { toast(e.message,'error'); }
}
async function confirmDeleteOrg() {
  if (!_currentOrg) return;
  const name = prompt(`Type the org name "${_currentOrg.name}" to confirm deletion:`);
  if (name !== _currentOrg.name) { toast('Name mismatch — not deleted','error'); return; }
  try {
    await api('DELETE', '/api/orgs/'+_currentOrg.id);
    toast('Organization deleted','success');
    await loadOrgs();
  } catch(e) { toast(e.message,'error'); }
}

function promptLogin() {
  toast('Please log in to access admin panel', 'error');
  setTimeout(() => { window.location.href = '/'; }, 2000);
}

// ── Access Control (User Approvals) ──────────────────────────────────────
function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const page = document.getElementById('page-' + name);
  if (page) page.classList.add('active');
  const btn = document.getElementById('nav-' + name) || [...document.querySelectorAll('.nav-item')].find(b => b.textContent.includes(name));
  if (btn) btn.classList.add('active');
  if (name === 'access-control') loadAccessControl();
}

async function loadAccessControl() {
  const el = document.getElementById('user-list');
  if (!el) return;
  el.innerHTML = '<div style="color:#8b949e;padding:12px">Loading…</div>';
  try {
    const r = await fetch('/api/admin/users', { headers: _token ? { Authorization: 'Bearer ' + _token } : {} });
    if (r.status === 403) { el.innerHTML = '<div style="color:#f85149;padding:12px">Access denied — owner credentials required.</div>'; return; }
    const d = await r.json();
    const users = d.users || [];
    if (!users.length) { el.innerHTML = '<div style="color:#8b949e;padding:12px">No users yet.</div>'; return; }
    el.innerHTML = users.map(u => {
      const badge = u.is_owner ? '<span style="background:#1f6feb22;color:#58a6ff;border:1px solid #1f6feb55;border-radius:4px;font-size:10px;padding:1px 7px;font-weight:700">OWNER</span>'
        : u.approved ? '<span style="background:#23863622;color:#3fb950;border:1px solid #23863655;border-radius:4px;font-size:10px;padding:1px 7px;font-weight:700">APPROVED</span>'
        : '<span style="background:#f0883e22;color:#f0883e;border:1px solid #f0883e55;border-radius:4px;font-size:10px;padding:1px 7px;font-weight:700">PENDING</span>';
      const actions = u.is_owner ? '' : !u.approved
        ? `<button onclick="approveUser('${u.id}',this)" style="background:#238636;border:none;color:#fff;padding:4px 14px;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600">Approve</button>
           <button onclick="rejectUser('${u.id}',this)" style="background:#da3633;border:none;color:#fff;padding:4px 14px;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600;margin-left:6px">Reject</button>`
        : `<button onclick="rejectUser('${u.id}',this)" style="background:none;border:1px solid #30363d;color:#8b949e;padding:4px 12px;border-radius:6px;cursor:pointer;font-size:12px">Remove</button>`;
      return `<div style="display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid #21262d">
        <div style="flex:1;min-width:0">
          <div style="font-size:13px;font-weight:600">${u.email}</div>
          <div style="font-size:11px;color:#8b949e;margin-top:2px">${u.name || '—'} &middot; ${u.tier || 'free'} &middot; joined ${new Date((u.created_at||0)*1000).toLocaleDateString()}</div>
        </div>
        ${badge}
        <div style="display:flex;gap:6px">${actions}</div>
      </div>`;
    }).join('');
  } catch(e) { el.innerHTML = '<div style="color:#f85149;padding:12px">Error: ' + e.message + '</div>'; }
}

async function approveUser(id, btn) {
  btn.disabled = true; btn.textContent = '…';
  const r = await fetch('/api/admin/users/' + id + '/approve', { method: 'POST', headers: _token ? { Authorization: 'Bearer ' + _token } : {} });
  if (r.ok) loadAccessControl(); else { btn.disabled = false; btn.textContent = 'Approve'; alert('Failed'); }
}

async function rejectUser(id, btn) {
  if (!confirm('Remove this user?')) return;
  btn.disabled = true;
  const r = await fetch('/api/admin/users/' + id, { method: 'DELETE', headers: _token ? { Authorization: 'Bearer ' + _token } : {} });
  if (r.ok) loadAccessControl(); else { btn.disabled = false; alert('Failed'); }
}

// ── Boot ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Try to get token from cookies too
  const cookie = document.cookie.split(';').map(c => c.trim()).find(c => c.startsWith('session='));
  if (cookie && !_token) _token = cookie.split('=')[1];
  loadOrgs();
});
</script>
</body>
</html>"""
