"""Build Orchestrator interactive dashboard."""

BUILD_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Orchestra Build Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#0a0a0f;--bg2:#12121a;--surface:#1e1e2e;--border:#2a2a3e;--text:#e4e4f0;--text2:#9494b0;--accent:#6366f1;--accent2:#22d3ee;--green:#34d399;--red:#ef4444;--yellow:#fbbf24;--radius:12px;--font:'Inter',system-ui,sans-serif;--mono:'JetBrains Mono',monospace}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:var(--font);line-height:1.5}
nav{display:flex;align-items:center;gap:16px;padding:12px 24px;background:var(--bg2);border-bottom:1px solid var(--border);flex-wrap:wrap}
nav .logo{font-weight:700;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.tabs{display:flex;gap:4px;background:var(--surface);border-radius:8px;padding:4px;margin:0 auto;flex-wrap:wrap}
.tab-btn{padding:8px 20px;border:none;border-radius:6px;background:transparent;color:var(--text2);cursor:pointer;font-size:.85rem;font-weight:500;transition:all .2s}
.tab-btn:hover{color:var(--text);background:rgba(255,255,255,.05)}
.tab-btn.active{background:var(--accent);color:#fff}
.content{max-width:1400px;margin:0 auto;padding:24px}
.tab-content{display:none}
.tab-content.active{display:block}
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:24px}
.kpi{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:20px}
.kpi .label{font-size:.8rem;color:var(--text2);margin-bottom:4px}
.kpi .value{font-size:1.5rem;font-weight:700}
.kpi .sub{font-size:.75rem;color:var(--text2);margin-top:4px}
.card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:20px;margin-bottom:16px}
.card h3{font-size:1rem;font-weight:600;margin-bottom:12px;color:var(--text2)}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th{text-align:left;padding:10px 12px;border-bottom:1px solid var(--border);color:var(--text2);font-weight:500;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em}
td{padding:10px 12px;border-bottom:1px solid var(--border)}
tr:hover td{background:rgba(255,255,255,.02)}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.75rem;font-weight:500}
.tag-win{background:rgba(0,120,215,.2);color:#60a5fa}
.tag-linux{background:rgba(252,211,77,.15);color:#fbbf24}
.tag-mac{background:rgba(147,197,253,.15);color:#93c5fd}
.tag-android{background:rgba(52,211,153,.15);color:#34d399}
.tag-ios{background:rgba(168,85,247,.15);color:#a855f7}
.status{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:100px;font-size:.75rem;font-weight:500}
.status-completed,.status-applied{background:rgba(52,211,153,.15);color:#34d399}
.status-failed,.status-conflict{background:rgba(239,68,68,.15);color:#ef4444}
.status-building,.status-running{background:rgba(99,102,241,.15);color:#818cf8}
.status-pending,.status-unapplied{background:rgba(148,148,176,.15);color:#9494b0}
.status-cancelled{background:rgba(251,191,36,.15);color:#fbbf24}
.bar{height:6px;background:var(--border);border-radius:3px;overflow:hidden;margin-top:8px}
.bar-fill{height:100%;border-radius:3px;background:linear-gradient(90deg,var(--accent),var(--accent2));transition:width .5s}
pre{font-family:var(--mono);font-size:.8rem;background:var(--surface);padding:16px;border-radius:8px;overflow-x:auto;white-space:pre-wrap;word-break:break-all;max-height:400px;overflow-y:auto}
textarea{width:100%;background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:12px;font-family:var(--mono);font-size:.85rem;resize:vertical;min-height:60px}
.btn{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:8px;font-weight:500;font-size:.85rem;border:none;cursor:pointer;transition:all .2s;margin:2px}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary:hover{opacity:.9}
.btn-green{background:var(--green);color:#000}
.btn-green:hover{opacity:.9}
.btn-red{background:var(--red);color:#fff}
.btn-red:hover{opacity:.9}
.btn-sm{padding:4px 10px;font-size:.75rem}
.gn-args{font-family:var(--mono);font-size:.8rem;background:var(--surface);padding:12px;border-radius:6px;white-space:pre-wrap;word-break:break-all;margin-top:8px}
.flex-row{display:flex;gap:16px;align-items:center;flex-wrap:wrap}
.mb-8{margin-bottom:8px}
.mt-8{margin-top:8px}
@media(max-width:768px){.tabs{overflow-x:auto;flex-wrap:nowrap}.tab-btn{padding:6px 12px;white-space:nowrap}.kpi-row{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<nav>
<div class="logo">&#9889; Build Engine</div>
<div class="tabs">
<button class="tab-btn active" onclick="switchTab('profiles',this)">Profiles</button>
<button class="tab-btn" onclick="switchTab('builds',this)">Builds</button>
<button class="tab-btn" onclick="switchTab('patches',this)">Patches</button>
<button class="tab-btn" onclick="switchTab('brain',this)">AI Brain</button>
<button class="tab-btn" onclick="switchTab('metrics',this)">Metrics</button>
</div>
</nav>
<div class="content">

<div id="tab-profiles" class="tab-content active">
<div class="kpi-row" id="profileKpis"></div>
<div class="flex-row mb-8">
<button class="btn btn-primary" onclick="loadProfiles()">&#8635; Refresh</button>
</div>
<div class="card">
<h3>Build Profiles</h3>
<div style="overflow-x:auto"><table><thead><tr><th>Name</th><th>Platform</th><th>Type</th><th>CPU</th><th>Args</th><th>Tags</th><th>Actions</th></tr></thead><tbody id="profileTable"></tbody></table></div>
</div>
<div class="card" id="profileDetail" style="display:none">
<h3 id="profileDetailName">Profile Detail</h3>
<div id="profileDetailBody"></div>
</div>
</div>

<div id="tab-builds" class="tab-content">
<div class="kpi-row" id="buildKpis"></div>
<div class="flex-row mb-8">
<button class="btn btn-primary" onclick="loadBuilds()">&#8635; Refresh</button>
<button class="btn btn-green" onclick="showNewBuild()">+ New Build</button>
</div>
<div class="card" id="newBuildCard" style="display:none">
<h3>Start New Build</h3>
<select id="newBuildProfile" style="width:100%;background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:10px 12px;font-size:.85rem;margin-bottom:8px"></select>
<input id="newBuildBranch" value="main" placeholder="Branch" style="width:100%;background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:10px 12px;font-size:.85rem;margin-bottom:8px">
<input id="newBuildCommit" placeholder="Commit SHA" style="width:100%;background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:10px 12px;font-size:.85rem;margin-bottom:8px">
<textarea id="newBuildNotes" placeholder="Notes" rows="2"></textarea>
<button class="btn btn-primary mt-8" onclick="startBuild()">Start Build</button>
</div>
<div class="card" style="overflow-x:auto">
<h3>Build Tasks</h3>
<table><thead><tr><th>Profile</th><th>Platform</th><th>Status</th><th>Progress</th><th>Duration</th><th>Actions</th></tr></thead><tbody id="buildTable"></tbody></table>
</div>
<div class="card" id="buildDetail" style="display:none">
<h3 id="buildDetailTitle">Build Detail</h3>
<div id="buildDetailBody"></div>
</div>
</div>

<div id="tab-patches" class="tab-content">
<div class="kpi-row" id="patchKpis"></div>
<div class="flex-row mb-8">
<button class="btn btn-primary" onclick="loadPatches()">&#8635; Refresh</button>
</div>
<div class="card" style="overflow-x:auto">
<h3>Patches</h3>
<table><thead><tr><th>Name</th><th>Target</th><th>Status</th><th>Author</th><th>Version</th><th>Actions</th></tr></thead><tbody id="patchTable"></tbody></table>
</div>
<div class="card" id="patchDetail" style="display:none">
<h3 id="patchDetailName">Patch Detail</h3>
<div id="patchDetailBody"></div>
</div>
</div>

<div id="tab-brain" class="tab-content">
<div class="kpi-row" id="brainKpis"></div>
<div class="card">
<h3>Build Copilot</h3>
<textarea id="aiPrompt" placeholder="Ask about build errors, optimizations, GN args, or patches..." rows="3"></textarea>
<button class="btn btn-primary mt-8" onclick="askCopilot()">Ask Build Copilot</button>
<div id="aiResponse" style="margin-top:12px;display:none"><pre id="aiResponseText"></pre></div>
</div>
<div class="card">
<h3>Known Error Fixes</h3>
<div id="errorFixes"></div>
</div>
<div class="card">
<h3>Parallelism Suggestions</h3>
<select id="parallelismPlatform" style="background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:8px 12px;margin-bottom:8px">
<option value="win">Windows</option>
<option value="linux">Linux</option>
<option value="mac">macOS</option>
<option value="android">Android</option>
</select>
<button class="btn btn-primary" onclick="loadParallelism()">Get Suggestions</button>
<div id="parallelismResult" style="margin-top:8px"></div>
</div>
</div>

<div id="tab-metrics" class="tab-content">
<div class="kpi-row" id="metricsKpis"></div>
<div class="card"><h3>Full Metrics</h3><pre id="metricsJson"></pre></div>
</div>

</div>
<script>
let profiles = {}, tasks = {}, patches = {};

async function api(path, opts={}){try{const r=await fetch('/api/build'+(path.startsWith('/')?'':'/')+path,{headers:{'Content-Type':'application/json'},...opts});return await r.json()}catch{return null}}

function switchTab(tab,btn){document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));document.querySelectorAll('.tab-content').forEach(v=>v.classList.remove('active'));btn.classList.add('active');document.getElementById('tab-'+tab).classList.add('active');if(tab==='profiles')loadProfiles();if(tab==='builds')loadBuilds();if(tab==='patches')loadPatches();if(tab==='brain')loadBrain();if(tab==='metrics')loadMetrics()}

function renderKpis(el,items){el.innerHTML=items.map(i=>'<div class="kpi"><div class="label">'+i.label+'</div><div class="value">'+i.value+'</div>'+(i.sub?'<div class="sub">'+i.sub+'</div>':'')+'</div>').join('')}

function statusHtml(s){const m={completed:'completed',failed:'failed',building:'building',pending:'pending',cancelled:'cancelled',configuring:'building',applied:'applied',unapplied:'unapplied',conflict:'conflict',partial:'building',running:'running',obsolete:'cancelled'};return '<span class="status status-'+(m[s]||'pending')+'">'+s+'</span>'}

function tagHtml(t,p){if(!t||t==='')return'';return'<span class="tag tag-'+p+'">'+t+'</span>'}

// ── Profiles ──
async function loadProfiles(){const d=await api('profiles');if(!d)return;profiles=d;const rows=Object.entries(d);renderKpis(document.getElementById('profileKpis'),[{label:'Total Profiles',value:rows.length},{label:'Platforms',value:new Set(rows.map(([,v])=>v.platform)).size},{label:'Types',value:new Set(rows.map(([,v])=>v.build_type)).size}]);document.getElementById('profileTable').innerHTML=rows.map(([id,v])=>'<tr><td><a href="#" onclick="showProfile(\''+id+'\');return false" style="color:'+(v.name.includes('horizon')?'var(--accent2)':'var(--text)')+'">'+v.name+'</a></td><td>'+tagHtml(v.platform,v.platform)+'</td><td>'+statusHtml(v.build_type)+'</td><td>'+v.target_cpu+'</td><td style="font-size:.75rem;font-family:var(--mono)">'+(v.is_official?'<span style="color:var(--yellow)">official</span> ':'')+(v.full_label||'')+'</td><td>'+v.tags.map(t=>'<span class="tag tag-linux">'+t+'</span> ').join('')+'</td><td><button class="btn btn-sm btn-primary" onclick="useProfileForBuild(\''+id+'\')">Build</button></td></tr>').join('')}

async function showProfile(id){const d=await api('profiles/'+id);if(!d)return;document.getElementById('profileDetail').style.display='block';document.getElementById('profileDetailName').textContent=d.name+' ('+d.full_label+')';document.getElementById('profileDetailBody').innerHTML='<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:.85rem"><div><strong>Platform:</strong> '+d.platform+'</div><div><strong>Type:</strong> '+d.build_type+'</div><div><strong>CPU:</strong> '+d.target_cpu+'</div><div><strong>Symbol Level:</strong> '+d.symbol_level+'</div><div><strong>Component Build:</strong> '+d.component_build+'</div><div><strong>Jumbo Build:</strong> '+d.use_jumbo+'</div><div><strong>Official:</strong> '+d.is_official+'</div><div><strong>Tags:</strong> '+(d.tags||[]).join(', ')+'</div></div><div class="mt-8"><strong>GN Command:</strong><div class="gn-args">'+d.gn_command+'</div></div><div class="mt-8"><strong>GN Args:</strong><div class="gn-args">'+(d.gn_arg_string||'none')+'</div></div>';if(d.id){const est=await api('profiles/'+d.id+'/estimate');if(est)document.getElementById('profileDetailBody').innerHTML+='<div class="mt-8"><strong>Estimated Build Time:</strong> '+est.estimated_minutes+' min</div>';const opt=await api('profiles/'+d.id+'/optimize');if(opt&&opt.suggestions&&opt.suggestions.length){document.getElementById('profileDetailBody').innerHTML+='<div class="mt-8"><strong>Optimizations:</strong></div>';opt.suggestions.forEach(s=>{document.getElementById('profileDetailBody').innerHTML+='<div style="font-size:.8rem;padding:8px;background:var(--surface);border-radius:6px;margin:4px 0">&#9889; <strong>'+s.setting+':</strong> '+s.reason+' <span style="color:var(--text2)">('+s.savings+')</span></div>'})}}}

function useProfileForBuild(id){switchTab('builds',document.querySelectorAll('.tab-btn')[1]);document.getElementById('newBuildCard').style.display='block';document.getElementById('newBuildProfile').value=id;scrollTo(0,document.getElementById('newBuildCard').offsetTop-100)}

// ── Builds ──
async function loadBuilds(){const d=await api('tasks?limit=100');if(!d)return;tasks=d;const rows=Object.entries(d);let success=0,fail=0;rows.forEach(([,v])=>{if(v.status==='completed')success++;if(v.status==='failed')fail++});renderKpis(document.getElementById('buildKpis'),[{label:'Total Builds',value:rows.length},{label:'Successful',value:success,sub:rows.length?Math.round(success/rows.length*100)+'%':''},{label:'Failed',value:fail,sub:rows.length?Math.round(fail/rows.length*100)+'%':''},{label:'Running',value:rows.filter(([,v])=>v.status==='running'||v.status==='building'||v.status==='configuring').length}]);document.getElementById('buildTable').innerHTML=rows.map(([id,v])=>'<tr><td><a href="#" onclick="showBuild(\''+id+'\');return false">'+v.profile_name+'</a></td><td>'+tagHtml(v.platform,v.platform)+'</td><td>'+statusHtml(v.status)+'</td><td><div style="min-width:80px">'+v.progress_pct+'%<div class="bar"><div class="bar-fill" style="width:'+v.progress_pct+'%"></div></div></div></td><td>'+(v.duration_ms>0?Math.round(v.duration_ms/1000)+'s':'—')+'</td><td>'+(v.status==='pending'||v.status==='paused'?'<button class="btn btn-sm btn-green" onclick="runBuild(\''+id+'\')">Run</button>':'')+' '+(v.status==='running'||v.status==='building'?'<button class="btn btn-sm btn-red" onclick="cancelBuild(\''+id+'\')">Cancel</button>':'')+' <button class="btn btn-sm btn-primary" onclick="showBuild(\''+id+'\')">View</button></td></tr>').join('');const opts=document.getElementById('newBuildProfile');if(opts.options.length===0){Object.entries(profiles).forEach(([id,v])=>{const o=document.createElement('option');o.value=id;o.textContent=v.name;opts.appendChild(o)})}}

async function showBuild(id){const t=tasks[id]||await api('tasks/'+id);if(!t)return;document.getElementById('buildDetail').style.display='block';document.getElementById('buildDetailTitle').textContent=t.profile_name+' — '+t.id.slice(0,8);let html='<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;font-size:.85rem"><div><strong>Status:</strong> '+statusHtml(t.status)+'</div><div><strong>Platform:</strong> '+t.platform+'</div><div><strong>Type:</strong> '+t.build_type+'</div><div><strong>Branch:</strong> '+(t.branch||'—')+'</div><div><strong>Commit:</strong> '+(t.commit_sha?t.commit_sha.slice(0,8):'—')+'</div><div><strong>Triggered:</strong> '+t.triggered_by+'</div><div><strong>Duration:</strong> '+(t.duration_ms>0?Math.round(t.duration_ms/1000)+'s':'—')+'</div><div><strong>Progress:</strong> '+t.progress_pct+'%</div></div>';if(t.steps&&t.steps.length){html+='<div class="mt-8"><strong>Steps:</strong></div>';t.steps.forEach(s=>{html+='<div style="font-size:.8rem;padding:6px 8px;background:var(--surface);border-radius:4px;margin:2px 0;display:flex;justify-content:space-between"><span>'+statusHtml(s.status)+' '+s.name+'</span><span style="color:var(--text2)">'+(s.duration_ms?Math.round(s.duration_ms)+'ms':'')+'</span></div>'})}if(t.result){html+='<div class="mt-8"><strong>Result:</strong></div>';(t.result.errors||[]).length&&html+='<div style="color:var(--red);font-size:.8rem"><strong>Errors ('+t.result.errors.length+'):</strong></div><pre>'+t.result.errors.join('\\n').slice(0,500)+'</pre>';(t.result.warnings||[]).length&&html+='<div style="color:var(--yellow);font-size:.8rem;margin-top:8px"><strong>Warnings ('+t.result.warnings.length+'):</strong></div><pre>'+t.result.warnings.slice(0,5).join('\\n')+'</pre>';t.result.size_mb>0&&(html+='<div style="font-size:.85rem;margin-top:8px"><strong>Binary Size:</strong> '+t.result.size_mb+' MB</div>')}document.getElementById('buildDetailBody').innerHTML=html}

async function runBuild(id){const d=await api('tasks/'+id+'/build',{method:'POST'});if(d)loadBuilds()}
async function cancelBuild(id){const d=await api('tasks/'+id+'/cancel',{method:'POST'});if(d)loadBuilds()}
async function showNewBuild(){document.getElementById('newBuildCard').style.display='block'}
async function startBuild(){const pid=document.getElementById('newBuildProfile').value;if(!pid)return alert('Select a profile');const d=await api('tasks',{method:'POST',body:JSON.stringify({profile_id:pid,branch:document.getElementById('newBuildBranch').value,commit_sha:document.getElementById('newBuildCommit').value,notes:document.getElementById('newBuildNotes').value})});if(d){document.getElementById('newBuildCard').style.display='none';loadBuilds();showBuild(d.id)}}

// ── Patches ──
async function loadPatches(){const d=await api('patches');if(!d)return;patches=d;const rows=Object.entries(d);let applied=0,conflict=0;rows.forEach(([,v])=>{if(v.is_applied)applied++;if(v.status==='conflict')conflict++});renderKpis(document.getElementById('patchKpis'),[{label:'Total Patches',value:rows.length},{label:'Applied',value:applied},{label:'Conflicts',value:conflict,sub:conflict?'<span style="color:var(--red)">Needs attention</span>':''}]);document.getElementById('patchTable').innerHTML=rows.map(([id,v])=>'<tr><td><a href="#" onclick="showPatch(\''+id+'\');return false">'+v.name+'</a></td><td style="font-family:var(--mono);font-size:.75rem">'+v.target_dir+'</td><td>'+statusHtml(v.status)+'</td><td>'+v.author+'</td><td>v'+v.version+'</td><td>'+(v.is_applied?'<button class="btn btn-sm btn-primary" onclick="unapplyPatch(\''+id+'\')">Unapply</button>':'<button class="btn btn-sm btn-green" onclick="applyPatch(\''+id+'\')">Apply</button>')+'</td></tr>').join('')}

async function showPatch(id){const d=await api('patches/'+id);if(!d)return;document.getElementById('patchDetail').style.display='block';document.getElementById('patchDetailName').textContent=d.name+' v'+d.version;document.getElementById('patchDetailBody').innerHTML='<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:.85rem"><div><strong>Status:</strong> '+statusHtml(d.status)+'</div><div><strong>Author:</strong> '+d.author+'</div><div><strong>Target:</strong> '+d.target_dir+'</div><div><strong>Created:</strong> '+new Date(d.created_at).toLocaleDateString()+'</div>'+(d.applied_at?'<div><strong>Applied:</strong> '+new Date(d.applied_at).toLocaleDateString()+'</div>':'')+'<div><strong>Tags:</strong> '+(d.tags||[]).join(', ')+'</div>'+(d.conflict_details?'<div style="color:var(--red)"><strong>Conflict:</strong> '+d.conflict_details+'</div>':'')+'</div>'}

async function applyPatch(id){const d=await api('patches/'+id+'/apply',{method:'POST'});if(d)loadPatches()}
async function unapplyPatch(id){const d=await api('patches/'+id+'/unapply',{method:'POST'});if(d)loadPatches()}

// ── Brain ──
async function loadBrain(){const s=await api('brain/summary');if(s)renderKpis(document.getElementById('brainKpis'),[{label:'Builds',value:(s.builds||{}).total||0,sub:(s.builds||{}).success_rate+'% success'},{label:'Patches',value:s.patches?.total||0,sub:s.patches?.applied+' applied'},{label:'Profiles',value:s.profiles||0}]);const fixes=await api('brain/fixes');if(fixes&&fixes.patterns)document.getElementById('errorFixes').innerHTML=fixes.patterns.map(p=>'<div style="padding:6px 8px;background:var(--surface);border-radius:4px;margin:3px 0;font-family:var(--mono);font-size:.8rem">'+p+'</div>').join('')}

async function askCopilot(){const p=document.getElementById('aiPrompt').value;if(!p)return;document.getElementById('aiResponse').style.display='block';document.getElementById('aiResponseText').textContent='Thinking...';const d=await api('brain/query',{method:'POST',body:JSON.stringify({prompt:p})});document.getElementById('aiResponseText').textContent=d?.response||'No response'}

async function loadParallelism(){const p=document.getElementById('parallelismPlatform').value;const d=await api('brain/parallelism?platform='+p);if(d)document.getElementById('parallelismResult').innerHTML='<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;font-size:.85rem"><div class="kpi"><div class="label">Recommended</div><div class="value">-j'+d.recommended_jobs+'</div></div><div class="kpi"><div class="label">Low Memory</div><div class="value">-j'+d.low_memory_jobs+'</div></div><div class="kpi"><div class="label">High Perf</div><div class="value">-j'+d.high_perf_jobs+'</div></div></div>'}

// ── Metrics ──
async function loadMetrics(){const d=await api('metrics');if(!d)return;renderKpis(document.getElementById('metricsKpis'),[{label:'Total Builds',value:d.total_tasks,sub:d.success_rate+'% success'},{label:'Avg Build Time',value:Math.round(d.avg_build_time_ms/6000)/10+'m'},{label:'Binary Size',value:d.total_binary_size_mb+' MB'},{label:'Active',value:d.active_tasks},{label:'Patches',value:d.patches_applied+'/'+d.patches_total},{label:'Errors',value:d.total_errors,sub:d.total_warnings+' warnings'}]);document.getElementById('metricsJson').textContent=JSON.stringify(d,null,2)}

loadProfiles();
</script>
</body>
</html>"""
