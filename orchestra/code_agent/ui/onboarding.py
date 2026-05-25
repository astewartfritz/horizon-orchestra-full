ONBOARDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Welcome to Orchestra</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d1117;--bg2:#161b22;--bg3:#21262d;
  --border:#30363d;--text:#e6edf3;--muted:#8b949e;
  --blue:#58a6ff;--green:#3fb950;--purple:#a78bfa;
  --red:#f85149;--orange:#f0883e;
}
html,body{height:100%;overflow:hidden}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center}

/* Outer shell */
.shell{width:100%;max-width:600px;padding:24px;height:100%;display:flex;flex-direction:column;overflow-y:auto}
@media(max-width:480px){.shell{padding:16px}}

/* Progress bar */
.progress{display:flex;gap:6px;margin-bottom:36px;justify-content:center}
.step-dot{width:8px;height:8px;border-radius:50%;background:var(--border);transition:background .3s}
.step-dot.active{background:var(--blue)}
.step-dot.done{background:var(--green)}

/* Step card */
.step{display:none;flex:1;flex-direction:column;justify-content:center}
.step.active{display:flex;animation:fadeUp .3s ease}
@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}

.step-label{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px}
.step-title{font-size:26px;font-weight:800;margin-bottom:8px;line-height:1.2}
.step-sub{font-size:14px;color:var(--muted);margin-bottom:28px;line-height:1.6}

/* Vertical picker cards */
.vertical-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:24px}
@media(max-width:420px){.vertical-grid{grid-template-columns:1fr}}
.vertical-card{
  border:2px solid var(--border);border-radius:12px;padding:16px;cursor:pointer;
  transition:all .2s;background:var(--bg2);
}
.vertical-card:hover{border-color:rgba(88,166,255,.4);background:rgba(88,166,255,.04)}
.vertical-card.selected{border-color:var(--blue);background:rgba(88,166,255,.08)}
.vertical-card.selected .vc-icon{filter:none}
.vc-icon{font-size:28px;margin-bottom:8px;filter:grayscale(.6)}
.vc-label{font-size:14px;font-weight:700;margin-bottom:2px}
.vc-desc{font-size:12px;color:var(--muted);line-height:1.4}

/* Input styles */
.field-label{font-size:12px;color:var(--muted);margin-bottom:6px;display:block}
.field-input{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px 14px;color:var(--text);font-size:14px;font-family:inherit;outline:none;transition:border-color .15s;margin-bottom:16px}
.field-input:focus{border-color:var(--blue)}
.field-input::placeholder{color:#484f58}
.field-group{position:relative}
.field-group .field-input{padding-right:40px}
.field-toggle{position:absolute;right:12px;top:50%;transform:translateY(-50%);background:none;border:none;color:var(--muted);cursor:pointer;font-size:13px}

/* API key grid */
.api-keys{display:flex;flex-direction:column;gap:12px;margin-bottom:8px}
.api-key-row{display:flex;flex-direction:column;gap:4px}
.api-key-row .provider-badge{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}

/* Action buttons */
.btn-row{display:flex;gap:10px;margin-top:auto;padding-top:20px}
.btn{padding:11px 22px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit;border:none;transition:opacity .15s;min-height:44px}
.btn-primary{background:var(--blue);color:#fff;flex:1}.btn-primary:hover{opacity:.85}
.btn-ghost{background:transparent;color:var(--muted);border:1px solid var(--border)}.btn-ghost:hover{color:var(--text)}
.btn-success{background:var(--green);color:#000;flex:1}

/* Skip link */
.skip{display:block;text-align:center;margin-top:12px;font-size:12px;color:var(--muted);cursor:pointer;min-height:44px;line-height:44px}
.skip:hover{color:var(--text)}

/* Checkmark animation */
.check-anim{display:flex;align-items:center;justify-content:center;width:64px;height:64px;border-radius:50%;background:rgba(63,185,80,.12);margin:0 auto 24px}
.check-anim svg{width:36px;height:36px}

/* Summary list */
.summary{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:20px}
.summary-row{display:flex;align-items:center;gap:10px;padding:6px 0;font-size:13px;border-bottom:1px solid rgba(48,54,61,.5)}
.summary-row:last-child{border-bottom:none}
.summary-key{color:var(--muted);width:110px;flex-shrink:0}
.summary-val{font-weight:600;flex:1}
.summary-val.ok{color:var(--green)}
.summary-val.skip{color:var(--muted)}
</style>
</head>
<body>
<div class="shell">
  <!-- Progress dots -->
  <div class="progress">
    <div class="step-dot active" id="dot0"></div>
    <div class="step-dot" id="dot1"></div>
    <div class="step-dot" id="dot2"></div>
    <div class="step-dot" id="dot3"></div>
    <div class="step-dot" id="dot4"></div>
  </div>

  <!-- Step 0: Welcome -->
  <div class="step active" id="step0">
    <div class="step-label">Welcome</div>
    <div class="step-title">Let's get you set up</div>
    <div class="step-sub">Orchestra is an autonomous AI assistant for healthcare, legal, and finance professionals. This wizard takes about 2 minutes.</div>
    <div class="btn-row">
      <button class="btn btn-primary" onclick="nextStep()">Get started →</button>
    </div>
    <a class="skip" onclick="skipAll()">Skip setup and go to app</a>
  </div>

  <!-- Step 1: Vertical picker -->
  <div class="step" id="step1">
    <div class="step-label">Step 1 of 4</div>
    <div class="step-title">What do you work on?</div>
    <div class="step-sub">Orchestra uses this to tailor prompts, compliance rules, and model selection.</div>
    <div class="vertical-grid" id="verticalGrid">
      <div class="vertical-card" onclick="selectVertical('healthcare', this)">
        <div class="vc-icon">🏥</div>
        <div class="vc-label">Healthcare</div>
        <div class="vc-desc">Clinical notes, HIPAA compliance, patient records, medical research</div>
      </div>
      <div class="vertical-card" onclick="selectVertical('legal', this)">
        <div class="vc-icon">⚖️</div>
        <div class="vc-label">Legal</div>
        <div class="vc-desc">Contract review, client matter files, privilege management, GDPR</div>
      </div>
      <div class="vertical-card" onclick="selectVertical('finance', this)">
        <div class="vc-icon">📈</div>
        <div class="vc-label">Finance</div>
        <div class="vc-desc">LBO models, EDGAR filings, portfolio analysis, quant research</div>
      </div>
      <div class="vertical-card" onclick="selectVertical('engineering', this)">
        <div class="vc-icon">💻</div>
        <div class="vc-label">Engineering</div>
        <div class="vc-desc">Code generation, debugging, architecture, CI/CD automation</div>
      </div>
      <div class="vertical-card" onclick="selectVertical('research', this)">
        <div class="vc-icon">🔬</div>
        <div class="vc-label">Research</div>
        <div class="vc-desc">Literature review, experiments, data analysis, paper writing</div>
      </div>
      <div class="vertical-card" onclick="selectVertical('general', this)">
        <div class="vc-icon">🌐</div>
        <div class="vc-label">General</div>
        <div class="vc-desc">Mixed tasks, writing, planning, and everything else</div>
      </div>
    </div>
    <div class="btn-row">
      <button class="btn btn-ghost" onclick="prevStep()">Back</button>
      <button class="btn btn-primary" onclick="nextStep()">Continue</button>
    </div>
    <a class="skip" onclick="nextStep()">Skip this step</a>
  </div>

  <!-- Step 2: Org name -->
  <div class="step" id="step2">
    <div class="step-label">Step 2 of 4</div>
    <div class="step-title">Name your organization</div>
    <div class="step-sub">This creates your org workspace. You can invite teammates later from the admin panel.</div>
    <label class="field-label">Organization name</label>
    <input id="orgName" class="field-input" placeholder="Acme Legal LLP" maxlength="80">
    <div class="btn-row">
      <button class="btn btn-ghost" onclick="prevStep()">Back</button>
      <button class="btn btn-primary" onclick="nextStep()">Continue</button>
    </div>
    <a class="skip" onclick="nextStep()">Skip — use personal workspace</a>
  </div>

  <!-- Step 3: API keys -->
  <div class="step" id="step3">
    <div class="step-label">Step 3 of 4</div>
    <div class="step-title">Connect your AI providers</div>
    <div class="step-sub">Keys are encrypted and stored server-side. Add at least one to enable AI features. You can add more later in Settings.</div>
    <div class="api-keys">
      <div class="api-key-row">
        <span class="provider-badge">Anthropic</span>
        <div class="field-group">
          <input id="keyAnthropic" class="field-input" type="password" placeholder="sk-ant-…" autocomplete="off">
          <button class="field-toggle" onclick="toggleKey('keyAnthropic', this)">Show</button>
        </div>
      </div>
      <div class="api-key-row">
        <span class="provider-badge">OpenAI</span>
        <div class="field-group">
          <input id="keyOpenAI" class="field-input" type="password" placeholder="sk-…" autocomplete="off">
          <button class="field-toggle" onclick="toggleKey('keyOpenAI', this)">Show</button>
        </div>
      </div>
      <div class="api-key-row">
        <span class="provider-badge">Moonshot (Kimi)</span>
        <div class="field-group">
          <input id="keyMoonshot" class="field-input" type="password" placeholder="sk-…" autocomplete="off">
          <button class="field-toggle" onclick="toggleKey('keyMoonshot', this)">Show</button>
        </div>
      </div>
    </div>
    <div class="btn-row">
      <button class="btn btn-ghost" onclick="prevStep()">Back</button>
      <button class="btn btn-primary" onclick="saveAndNext()">Save keys</button>
    </div>
    <a class="skip" onclick="nextStep()">Skip — I'll add keys later</a>
  </div>

  <!-- Step 4: Done -->
  <div class="step" id="step4">
    <div class="check-anim">
      <svg viewBox="0 0 36 36" fill="none"><circle cx="18" cy="18" r="17" stroke="#3fb950" stroke-width="2"/><path d="M11 18l5 5 9-10" stroke="#3fb950" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </div>
    <div class="step-label">All set!</div>
    <div class="step-title">Welcome to Orchestra</div>
    <div class="step-sub">Here's what we've configured for you:</div>
    <div class="summary" id="summary"></div>
    <div class="btn-row">
      <button class="btn btn-success" onclick="launchApp()">Open Orchestra →</button>
    </div>
    <a class="skip" onclick="window.location.href='/admin'">Go to admin panel</a>
  </div>
</div>

<script>
const _token = localStorage.getItem('orchestra_token') || '';
let _currentStep = 0;
let _vertical = '';
let _orgCreated = null;
let _keysSaved = [];

const STEPS = 5;

function updateDots() {
  for (let i = 0; i < STEPS; i++) {
    const d = document.getElementById('dot' + i);
    if (i < _currentStep) { d.className = 'step-dot done'; }
    else if (i === _currentStep) { d.className = 'step-dot active'; }
    else { d.className = 'step-dot'; }
  }
}

function showStep(n) {
  document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
  document.getElementById('step' + n).classList.add('active');
  _currentStep = n;
  updateDots();
}

function nextStep() {
  if (_currentStep < STEPS - 1) showStep(_currentStep + 1);
  if (_currentStep === STEPS - 1) buildSummary();
}
function prevStep() {
  if (_currentStep > 0) showStep(_currentStep - 1);
}

function selectVertical(v, el) {
  _vertical = v;
  document.querySelectorAll('.vertical-card').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
}

function toggleKey(id, btn) {
  const input = document.getElementById(id);
  const isText = input.type === 'text';
  input.type = isText ? 'password' : 'text';
  btn.textContent = isText ? 'Show' : 'Hide';
}

async function saveAndNext() {
  const keys = [
    { provider: 'anthropic', value: document.getElementById('keyAnthropic').value.trim(), name: 'ANTHROPIC_API_KEY' },
    { provider: 'openai', value: document.getElementById('keyOpenAI').value.trim(), name: 'OPENAI_API_KEY' },
    { provider: 'moonshot', value: document.getElementById('keyMoonshot').value.trim(), name: 'MOONSHOT_API_KEY' },
  ].filter(k => k.value);

  for (const k of keys) {
    try {
      await fetch('/api/api-keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + _token },
        body: JSON.stringify({ name: k.name, value: k.value, provider: k.provider }),
      });
      _keysSaved.push(k.provider);
    } catch(e) {}
  }
  nextStep();
}

async function createOrg() {
  const name = document.getElementById('orgName').value.trim();
  if (!name || !_token) return;
  try {
    const r = await fetch('/api/orgs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + _token },
      body: JSON.stringify({ name }),
    });
    if (r.ok) _orgCreated = await r.json();
  } catch(e) {}
}

// Override nextStep for step 2 (org creation)
const _origNext = nextStep;
async function nextStep() {
  if (_currentStep === 2) { await createOrg(); }
  if (_currentStep < STEPS - 1) showStep(_currentStep + 1);
  if (_currentStep === STEPS - 1) buildSummary();
}

function buildSummary() {
  const verticalLabel = {
    healthcare: '🏥 Healthcare', legal: '⚖️ Legal', finance: '📈 Finance',
    engineering: '💻 Engineering', research: '🔬 Research', general: '🌐 General',
  }[_vertical] || 'Not selected';

  const orgRow = _orgCreated
    ? `<div class="summary-row"><span class="summary-key">Organization</span><span class="summary-val ok">${_orgCreated.name}</span></div>`
    : `<div class="summary-row"><span class="summary-key">Organization</span><span class="summary-val skip">Personal workspace</span></div>`;

  const keysRow = _keysSaved.length
    ? `<div class="summary-row"><span class="summary-key">API keys</span><span class="summary-val ok">${_keysSaved.join(', ')} ✓</span></div>`
    : `<div class="summary-row"><span class="summary-key">API keys</span><span class="summary-val skip">None added (local models only)</span></div>`;

  document.getElementById('summary').innerHTML = `
    <div class="summary-row"><span class="summary-key">Vertical</span><span class="summary-val">${verticalLabel}</span></div>
    ${orgRow}
    ${keysRow}
  `;
  // Persist vertical preference
  if (_vertical) localStorage.setItem('orchestra_vertical', _vertical);
}

function launchApp() {
  localStorage.setItem('orchestra_onboarded', '1');
  window.location.href = '/app';
}

function skipAll() {
  localStorage.setItem('orchestra_onboarded', '1');
  window.location.href = '/app';
}

// If already onboarded, go straight to app
if (localStorage.getItem('orchestra_onboarded') === '1') {
  window.location.href = '/app';
}
</script>
</body>
</html>"""
