// Orchestra — First-run onboarding wizard
(function () {
  const { icons } = window;
  const API = window.ORCH_API || 'http://localhost:3000';
  const STORAGE_KEY = 'orchestraOnboarded';

  let step = 1; // 1 = Welcome, 2 = API Key, 3 = Try it
  let apiKeyValue = '';
  let apiSaving = false;
  let apiSaved = false;

  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ── Check whether to show ──────────────────────────────────────────────────
  function check() {
    if (localStorage.getItem(STORAGE_KEY)) return;
    show();
  }

  function markDone() {
    localStorage.setItem(STORAGE_KEY, '1');
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  function renderStep() {
    switch (step) {
      case 1: return renderWelcome();
      case 2: return renderApiKey();
      case 3: return renderTryIt();
      default: return renderWelcome();
    }
  }

  function renderProgressDots() {
    return `
      <div class="ob-dots">
        ${[1, 2, 3].map(n => `<div class="ob-dot ${step === n ? 'is-active' : step > n ? 'is-done' : ''}"></div>`).join('')}
      </div>`;
  }

  function renderWelcome() {
    return `
      <div class="ob-step">
        <div class="ob-icon" style="background:linear-gradient(135deg,var(--accent),var(--teal))">
          ${icons.logo ? icons.logo(32) : icons.sparkles(32)}
        </div>
        <h2 class="ob-title">Welcome to Orchestra</h2>
        <p class="ob-body">Orchestra is an AI task runner that coordinates agents across your tools, files, and APIs — so you can delegate entire workflows, not just individual questions.</p>
        <ul class="ob-features">
          <li>${icons.check(13)} <span>Real-time streaming with tool visibility</span></li>
          <li>${icons.check(13)} <span>Multi-step agent coordination (A→E architectures)</span></li>
          <li>${icons.check(13)} <span>Background jobs with live notifications</span></li>
          <li>${icons.check(13)} <span>Integrates with GitHub, Slack, Google Drive, and more</span></li>
        </ul>
        <div class="ob-actions">
          <button class="btn btn--subtle btn--sm" data-ob-skip>Skip setup</button>
          <button class="btn btn--primary" data-ob-next>Get started →</button>
        </div>
      </div>`;
  }

  function renderApiKey() {
    return `
      <div class="ob-step">
        <div class="ob-icon" style="background:var(--accent-dim);color:var(--accent)">
          ${icons.key(28)}
        </div>
        <h2 class="ob-title">Connect an AI provider</h2>
        <p class="ob-body">Orchestra needs an API key to send tasks to a language model. Your Anthropic key is the easiest way to get started.</p>

        <div class="ob-field">
          <label>Anthropic API key</label>
          <input
            class="input"
            type="password"
            placeholder="sk-ant-…"
            value="${escapeHTML(apiKeyValue)}"
            data-ob-key-input
            autocomplete="off"
            style="font-family:var(--font-mono)"
          />
          <div style="font-size:12px;color:var(--text-3);margin-top:6px">
            Get your key at <strong>console.anthropic.com</strong> → API Keys.
            It is stored server-side and never sent to the browser.
          </div>
        </div>

        ${apiSaved ? `
          <div style="display:flex;align-items:center;gap:8px;margin-top:12px;color:var(--success);font-size:13.5px">
            ${icons.check(14)} Key saved successfully
          </div>` : ''}

        <div class="ob-actions">
          <button class="btn btn--ghost" data-ob-back>← Back</button>
          <div style="display:flex;gap:8px">
            <button class="btn btn--subtle btn--sm" data-ob-skip-key>Skip for now</button>
            <button
              class="btn btn--primary"
              data-ob-save-key
              ${apiSaving ? 'disabled' : ''}
            >${apiSaving ? 'Saving…' : apiSaved ? 'Next →' : 'Save &amp; continue'}</button>
          </div>
        </div>
      </div>`;
  }

  function renderTryIt() {
    const prompts = [
      { title: 'Research task',   text: 'Summarize the latest AI safety papers from the last 30 days.' },
      { title: 'Code task',       text: 'Write a Python script that monitors a folder and logs new files to a CSV.' },
      { title: 'Analysis task',   text: 'Analyze the attached CSV and produce a summary with key trends.' },
      { title: 'Automation task', text: 'Check my GitHub repo for open issues older than 14 days and draft responses.' },
    ];

    return `
      <div class="ob-step">
        <div class="ob-icon" style="background:var(--success-dim);color:var(--success)">
          ${icons.sparkles(28)}
        </div>
        <h2 class="ob-title">You're ready. Try a task.</h2>
        <p class="ob-body">Pick a template below or jump straight to the chat. Orchestra will plan, use tools, and show you every step as it works.</p>

        <div class="ob-prompts">
          ${prompts.map(p => `
            <button class="ob-prompt" data-ob-prompt="${escapeHTML(p.text)}">
              <div class="ob-prompt__title">${escapeHTML(p.title)}</div>
              <div class="ob-prompt__text">${escapeHTML(p.text)}</div>
            </button>`).join('')}
        </div>

        <div class="ob-actions" style="margin-top:24px">
          <button class="btn btn--ghost" data-ob-back>← Back</button>
          <button class="btn btn--primary" data-ob-finish>Open chat →</button>
        </div>
      </div>`;
  }

  // ── DOM ─────────────────────────────────────────────────────────────────────
  function getOverlay() { return document.getElementById('onboarding-overlay'); }
  function getPanel()   { return document.getElementById('onboarding-panel'); }

  function repaint() {
    const panel = getPanel();
    if (!panel) return;
    panel.innerHTML = renderProgressDots() + renderStep();
    wireStep();
  }

  function show() {
    const overlay = getOverlay();
    if (!overlay) return;
    overlay.classList.add('is-open');
    repaint();
  }

  function close(navigateTo) {
    const overlay = getOverlay();
    if (overlay) overlay.classList.remove('is-open');
    markDone();
    if (navigateTo) location.hash = navigateTo;
  }

  async function doSaveKey() {
    const val = apiKeyValue.trim();
    if (!val) {
      step = 3;
      repaint();
      return;
    }
    apiSaving = true;
    repaint();
    try {
      const r = await fetch(`${API}/v1/config/keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ anthropic_api_key: val }),
        signal: AbortSignal.timeout(8000),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      apiSaved = true;
      if (window.Orchestra?.toast) window.Orchestra.toast.show('Anthropic key saved', 'success', 3000);
      setTimeout(() => { step = 3; repaint(); }, 600);
    } catch (e) {
      if (window.Orchestra?.toast) window.Orchestra.toast.show('Failed to save key — you can add it later in Settings', 'error', 5000);
      step = 3;
    } finally {
      apiSaving = false;
      repaint();
    }
  }

  function wireStep() {
    const panel = getPanel();
    if (!panel) return;

    const keyInput = panel.querySelector('[data-ob-key-input]');
    if (keyInput) {
      keyInput.addEventListener('input', (e) => { apiKeyValue = e.target.value; });
      keyInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') doSaveKey(); });
    }

    panel.querySelector('[data-ob-next]')?.addEventListener('click', () => { step++; repaint(); });
    panel.querySelector('[data-ob-back]')?.addEventListener('click', () => { step = Math.max(1, step - 1); repaint(); });
    panel.querySelector('[data-ob-skip]')?.addEventListener('click', () => close('#/chat'));
    panel.querySelector('[data-ob-skip-key]')?.addEventListener('click', () => { step = 3; repaint(); });
    panel.querySelector('[data-ob-save-key]')?.addEventListener('click', doSaveKey);
    panel.querySelector('[data-ob-finish]')?.addEventListener('click', () => close('#/chat'));

    panel.querySelectorAll('[data-ob-prompt]').forEach(btn => {
      btn.addEventListener('click', () => {
        close('#/chat');
        // Pre-fill composer after navigation
        setTimeout(() => {
          const ta = document.querySelector('[data-composer]');
          if (ta) {
            ta.value = btn.dataset.obPrompt;
            ta.dispatchEvent(new Event('input'));
            ta.focus();
          }
        }, 150);
      });
    });
  }

  // ── Close on overlay click ─────────────────────────────────────────────────
  document.addEventListener('click', (e) => {
    const overlay = getOverlay();
    if (overlay && e.target === overlay) close();
  });

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.onboarding = { check, show };
})();
