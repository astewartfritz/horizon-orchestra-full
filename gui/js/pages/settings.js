// Orchestra — Settings page
(function () {
  const { icons } = window;
  const API = window.ORCH_API || 'http://localhost:3000';

  let state = {
    tab: 'profile',
    apiKeys: null,    // null = loading, {} = loaded {anthropic, openai, openrouter}
    apiInputs: {},    // {provider: inputValue}
    apiSaving: {},    // {provider: bool}
    usage: null,
    tiers: null,
  };

  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  const tabs = [
    { id: 'profile',       label: 'Profile' },
    { id: 'api',           label: 'API keys' },
    { id: 'models',        label: 'Models' },
    { id: 'subscription',  label: 'Subscription' },
    { id: 'integrations',  label: 'Integrations' },
    { id: 'security',      label: 'Security' },
  ];

  // ── Data loaders ────────────────────────────────────────────────────────────
  async function loadApiKeys() {
    try {
      const r = await fetch(`${API}/v1/config/keys`, { signal: AbortSignal.timeout(8000) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      state.apiKeys = await r.json();
    } catch (e) {
      state.apiKeys = { error: true };
    }
    if (state.tab === 'api') repaintBody();
  }

  function providerPayload(provider, value) {
    const map = { anthropic: 'anthropic_api_key', openai: 'openai_api_key', openrouter: 'openrouter_api_key' };
    return { [map[provider] || (provider + '_api_key')]: value.trim() };
  }

  async function saveApiKey(provider, value) {
    if (!value.trim()) return;
    state.apiSaving[provider] = true;
    repaintBody();
    try {
      const r = await fetch(`${API}/v1/config/keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(providerPayload(provider, value)),
        signal: AbortSignal.timeout(8000),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      if (window.Orchestra?.toast) window.Orchestra.toast.show(`${capitalize(provider)} key saved`, 'success', 3000);
      state.apiInputs[provider] = '';
      // Refresh key status
      const status = await fetch(`${API}/v1/config/keys`).then(x => x.json()).catch(() => null);
      if (status) state.apiKeys = status;
    } catch (e) {
      if (window.Orchestra?.toast) window.Orchestra.toast.show(`Failed to save ${provider} key`, 'error', 4000);
    } finally {
      state.apiSaving[provider] = false;
      repaintBody();
    }
  }

  async function loadUsage() {
    try {
      const [usageRes, tiersRes] = await Promise.all([
        fetch(`${API}/v1/usage/dashboard`, { signal: AbortSignal.timeout(8000) }),
        fetch(`${API}/v1/billing/tiers`, { signal: AbortSignal.timeout(8000) }),
      ]);
      state.usage = usageRes.ok ? await usageRes.json() : { error: true };
      state.tiers = tiersRes.ok ? await tiersRes.json() : null;
    } catch (e) {
      state.usage = { error: true };
    }
    if (state.tab === 'subscription') repaintBody();
  }

  function capitalize(s) {
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  function render() {
    return `
      <div class="page page--settings">
        <div class="page__inner" style="max-width:1080px">
          <div class="page-header">
            <div>
              <h1>Settings</h1>
              <div class="sub">Configure Orchestra for your workspace. Changes sync across devices.</div>
            </div>
          </div>

          <div style="display:grid;grid-template-columns:220px 1fr;gap:32px;align-items:start">
            <nav style="display:flex;flex-direction:column;gap:2px;position:sticky;top:0">
              ${tabs.map(t => `
                <button data-tab="${t.id}" class="nav-item ${state.tab === t.id ? 'is-active' : ''}" style="height:36px;text-align:left;justify-content:flex-start">
                  <span class="label" style="text-align:left">${escapeHTML(t.label)}</span>
                </button>
              `).join('')}
            </nav>

            <div data-settings-body>
              ${renderBody()}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function renderBody() {
    switch (state.tab) {
      case 'profile':      return renderProfile();
      case 'api':          return renderApi();
      case 'models':       return renderModels();
      case 'subscription': return renderSubscription();
      case 'integrations': return renderIntegrations();
      case 'security':     return renderSecurity();
      default: return renderProfile();
    }
  }

  function repaintBody() {
    const body = document.querySelector('[data-settings-body]');
    if (body) { body.innerHTML = renderBody(); wireBody(); }
  }

  function renderProfile() {
    return `
      <div class="card" style="padding:28px">
        <h3 style="margin-bottom:6px">Profile</h3>
        <p style="color:var(--text-2);font-size:13px;margin-bottom:24px">This information appears on your account and in agent audit logs.</p>

        <div style="display:flex;align-items:center;gap:20px;margin-bottom:28px;padding-bottom:24px;border-bottom:1px solid var(--border-subtle)">
          <div style="width:72px;height:72px;border-radius:999px;background:linear-gradient(135deg,var(--accent),var(--teal));display:grid;place-items:center;color:white;font-size:24px;font-weight:600">
            ${window.MOCK.user.initials}
          </div>
          <div>
            <div style="font-weight:600;font-size:16px">${escapeHTML(window.MOCK.user.name)}</div>
            <div style="color:var(--text-2);font-size:13px;margin-top:2px">${escapeHTML(window.MOCK.user.email)}</div>
            <div style="display:flex;gap:8px;margin-top:10px">
              <button class="btn btn--ghost btn--sm">Upload photo</button>
              <button class="btn btn--subtle btn--sm">Remove</button>
            </div>
          </div>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">
          <div class="field"><label>Full name</label><input class="input" value="${escapeHTML(window.MOCK.user.name)}"/></div>
          <div class="field"><label>Display name</label><input class="input" value="Ashton"/></div>
          <div class="field"><label>Email</label><input class="input" value="${escapeHTML(window.MOCK.user.email)}"/></div>
          <div class="field"><label>Role</label><input class="input" value="Head of AI Platform"/></div>
          <div class="field" style="grid-column:1/-1"><label>Bio</label>
            <textarea class="input" style="height:80px;padding:10px 12px;line-height:1.5" placeholder="Tell Orchestra a bit about how you work…">Prefers concise output with linked evidence. Reviews agent diffs before approval.</textarea>
          </div>
        </div>

        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:20px">
          <button class="btn btn--ghost">Cancel</button>
          <button class="btn btn--primary">Save changes</button>
        </div>
      </div>
    `;
  }

  function renderApi() {
    if (!state.apiKeys) {
      return `
        <div class="card" style="padding:28px">
          <h3>API keys</h3>
          <p style="color:var(--text-2);font-size:13px;margin-top:6px;margin-bottom:24px">Keys let Orchestra call AI providers on your behalf. They are stored server-side and never exposed to the browser.</p>
          <div style="display:flex;align-items:center;gap:10px;color:var(--text-3);padding:20px 0">
            <div class="spinner" style="width:16px;height:16px;border:2px solid var(--border-subtle);border-top-color:var(--accent);border-radius:999px;animation:spin 0.7s linear infinite"></div>
            Loading key status…
          </div>
        </div>`;
    }

    if (state.apiKeys.error) {
      return `
        <div class="card" style="padding:28px">
          <h3>API keys</h3>
          <p style="color:var(--text-2);font-size:13px;margin-top:6px;margin-bottom:16px">Keys let Orchestra call AI providers on your behalf.</p>
          <div class="error-block">
            <div class="error-block__icon">${icons.alertTriangle ? icons.alertTriangle(15) : '⚠'}</div>
            <div class="error-block__body">
              <div class="error-block__title">Could not load key status</div>
              <div class="error-block__hint">Make sure the Orchestra server is running: <code>python run.py</code></div>
            </div>
          </div>
          <button class="btn btn--ghost" style="margin-top:16px" data-action="reload-keys">Try again</button>
        </div>`;
    }

    const providers = [
      { id: 'anthropic',  label: 'Anthropic', desc: 'Powers Claude models (claude-3-5-sonnet, claude-3-opus, etc.)', placeholder: 'sk-ant-…' },
      { id: 'openai',     label: 'OpenAI',    desc: 'Powers GPT-4o, GPT-4-turbo, and o3 models.',                  placeholder: 'sk-…' },
      { id: 'openrouter', label: 'OpenRouter', desc: 'Unified access to 100+ models via a single key.',             placeholder: 'sk-or-…' },
    ];

    return `
      <div class="card" style="padding:28px">
        <h3>API keys</h3>
        <p style="color:var(--text-2);font-size:13px;margin-top:6px;margin-bottom:24px">Keys let Orchestra call AI providers on your behalf. They are stored server-side and never exposed to the browser.</p>

        <div style="display:flex;flex-direction:column;gap:16px">
          ${providers.map(p => {
            const isSet = !!state.apiKeys[p.id];
            const saving = !!state.apiSaving[p.id];
            const inputVal = state.apiInputs[p.id] || '';
            return `
              <div style="padding:18px;background:var(--bg-2);border-radius:10px;border:1px solid var(--border-subtle)">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
                  <div style="display:flex;align-items:center;gap:10px">
                    <div style="width:32px;height:32px;border-radius:8px;background:${isSet ? 'var(--accent-dim)' : 'var(--bg-3)'};color:${isSet ? 'var(--accent)' : 'var(--text-3)'};display:grid;place-items:center">${icons.key(14)}</div>
                    <div>
                      <div style="font-weight:500">${escapeHTML(p.label)}</div>
                      <div style="font-size:11.5px;color:var(--text-3)">${escapeHTML(p.desc)}</div>
                    </div>
                  </div>
                  ${isSet
                    ? `<span class="badge badge--success">Connected</span>`
                    : `<span class="badge">Not set</span>`}
                </div>
                <div style="display:flex;gap:8px;align-items:center">
                  <input
                    class="input"
                    type="password"
                    placeholder="${isSet ? '••••••••••••••••••••••••' : escapeHTML(p.placeholder)}"
                    value="${escapeHTML(inputVal)}"
                    data-key-input="${p.id}"
                    style="flex:1;font-family:var(--font-mono);font-size:12.5px"
                    autocomplete="off"
                  />
                  <button
                    class="btn btn--primary btn--sm"
                    data-save-key="${p.id}"
                    ${saving || !inputVal.trim() ? 'disabled' : ''}
                  >${saving ? 'Saving…' : isSet ? 'Update' : 'Save'}</button>
                </div>
              </div>`;
          }).join('')}
        </div>

        <div style="margin-top:20px;padding:14px;background:var(--bg-2);border-radius:8px;border:1px solid var(--border-subtle);font-size:12.5px;color:var(--text-3)">
          ${icons.lock ? icons.lock(13) : '🔒'} Keys are written to a <code>.env</code> file on the server and loaded at runtime. They are never logged or returned to the browser.
        </div>
      </div>
    `;
  }

  function renderSubscription() {
    if (!state.usage) {
      return `
        <div class="card" style="padding:28px">
          <h3>Subscription &amp; Usage</h3>
          <div style="display:flex;align-items:center;gap:10px;color:var(--text-3);padding:20px 0">
            <div class="spinner" style="width:16px;height:16px;border:2px solid var(--border-subtle);border-top-color:var(--accent);border-radius:999px;animation:spin 0.7s linear infinite"></div>
            Loading usage data…
          </div>
        </div>`;
    }

    const u = state.usage;
    const tiers = state.tiers || [];
    const jobs = u.jobs_total || 0;
    const byStatus = u.jobs_by_status || {};
    const done = byStatus.complete || 0;
    const failed = byStatus.failed || 0;
    const avgDur = u.avg_duration_seconds != null ? u.avg_duration_seconds.toFixed(1) : '—';
    const computeHrs = u.total_compute_seconds != null ? (u.total_compute_seconds / 3600).toFixed(1) : '—';

    const doneRate = jobs > 0 ? Math.round((done / jobs) * 100) : 0;

    return `
      <div class="card" style="padding:28px;margin-bottom:16px">
        <h3 style="margin-bottom:4px">Usage this month</h3>
        <p style="color:var(--text-2);font-size:13px;margin-bottom:20px">Live data from your Orchestra server.</p>

        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:20px">
          <div style="padding:16px;background:var(--bg-2);border-radius:10px;border:1px solid var(--border-subtle)">
            <div style="font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em">Total jobs</div>
            <div style="font-size:28px;font-weight:600;margin-top:6px">${jobs.toLocaleString()}</div>
          </div>
          <div style="padding:16px;background:var(--bg-2);border-radius:10px;border:1px solid var(--border-subtle)">
            <div style="font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em">Success rate</div>
            <div style="font-size:28px;font-weight:600;margin-top:6px;color:${doneRate >= 90 ? 'var(--success)' : doneRate >= 70 ? 'var(--warn)' : 'var(--danger)'}">${doneRate}%</div>
          </div>
          <div style="padding:16px;background:var(--bg-2);border-radius:10px;border:1px solid var(--border-subtle)">
            <div style="font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em">Compute used</div>
            <div style="font-size:28px;font-weight:600;margin-top:6px">${computeHrs}h</div>
          </div>
        </div>

        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px">
          <div style="padding:12px;background:var(--bg-2);border-radius:8px;border:1px solid var(--border-subtle)">
            <div style="font-size:11.5px;color:var(--text-3)">Completed</div>
            <div style="font-weight:600;color:var(--success);margin-top:2px">${done.toLocaleString()}</div>
          </div>
          <div style="padding:12px;background:var(--bg-2);border-radius:8px;border:1px solid var(--border-subtle)">
            <div style="font-size:11.5px;color:var(--text-3)">Failed</div>
            <div style="font-weight:600;color:var(--danger);margin-top:2px">${failed.toLocaleString()}</div>
          </div>
          <div style="padding:12px;background:var(--bg-2);border-radius:8px;border:1px solid var(--border-subtle)">
            <div style="font-size:11.5px;color:var(--text-3)">Avg duration</div>
            <div style="font-weight:600;margin-top:2px">${avgDur}s</div>
          </div>
        </div>

        ${u.error ? `<div style="margin-top:16px;padding:12px;background:rgba(240,89,106,0.06);border-radius:8px;font-size:13px;color:var(--danger)">Could not load live usage — showing cached data.</div>` : ''}
      </div>

      ${tiers.length > 0 ? `
      <div class="card" style="padding:28px">
        <h3 style="margin-bottom:4px">Plans</h3>
        <p style="color:var(--text-2);font-size:13px;margin-bottom:20px">All plans include the full Orchestra feature set. Upgrade to increase job limits.</p>
        <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px">
          ${tiers.map(t => {
            const tierId = t.tier || t.id || '';
            const price = t.price_monthly != null ? t.price_monthly : (t.price != null ? t.price : 0);
            return `
            <div style="padding:18px;background:var(--bg-2);border-radius:10px;border:1px solid ${tierId === 'pro' ? 'var(--accent)' : 'var(--border-subtle)'};position:relative">
              ${tierId === 'pro' ? `<div style="position:absolute;top:-10px;left:16px;background:var(--accent);color:white;font-size:10.5px;font-weight:600;padding:2px 8px;border-radius:4px;letter-spacing:.04em">POPULAR</div>` : ''}
              <div style="font-weight:600;font-size:15px;margin-bottom:2px">${escapeHTML(t.name)}</div>
              <div style="font-size:22px;font-weight:700;margin:8px 0 4px">${price === 0 ? 'Free' : `$${price}`}<span style="font-size:12px;font-weight:400;color:var(--text-3)">${price > 0 ? '/mo' : ''}</span></div>
              <ul style="margin:12px 0 16px;padding:0 0 0 16px;font-size:13px;color:var(--text-2);display:flex;flex-direction:column;gap:4px">
                ${(t.features || []).map(f => `<li>${escapeHTML(f)}</li>`).join('')}
              </ul>
              <button class="btn ${tierId === 'pro' ? 'btn--primary' : 'btn--ghost'} btn--sm" style="width:100%">${price === 0 ? 'Current plan' : 'Upgrade'}</button>
            </div>`;
          }).join('')}
        </div>
      </div>` : ''}
    `;
  }

  function renderModels() {
    return `
      <div class="card" style="padding:28px">
        <h3>Model configuration</h3>
        <p style="color:var(--text-2);font-size:13px;margin-top:6px;margin-bottom:24px">Defaults are applied to all new agent invocations unless the agent explicitly overrides them.</p>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px">
          <div class="field">
            <label>Default model</label>
            <select class="input" style="padding:0 12px">
              ${window.MOCK.models.map(m => `<option ${m.selected ? 'selected' : ''}>${escapeHTML(m.name)} — ${escapeHTML(m.desc)}</option>`).join('')}
            </select>
          </div>
          <div class="field">
            <label>Fallback model</label>
            <select class="input" style="padding:0 12px">
              ${window.MOCK.models.map(m => `<option>${escapeHTML(m.name)}</option>`).join('')}
            </select>
          </div>
          <div class="field">
            <label>Temperature <span style="color:var(--text-3);font-weight:400;font-size:11.5px">(0.0 – 2.0)</span></label>
            <input class="input" value="0.7"/>
          </div>
          <div class="field">
            <label>Max context</label>
            <input class="input" value="1,000,000 tokens"/>
          </div>
        </div>

        <div style="border-top:1px solid var(--border-subtle);padding-top:20px">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
            <div>
              <div style="font-weight:500">Stream responses</div>
              <div style="font-size:12.5px;color:var(--text-2)">Tokens render as they arrive from the model.</div>
            </div>
            <div class="switch on" data-switch></div>
          </div>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
            <div>
              <div style="font-weight:500">Enable tool use</div>
              <div style="font-size:12.5px;color:var(--text-2)">Allow agents to invoke fs, web, shell, and registered skills.</div>
            </div>
            <div class="switch on" data-switch></div>
          </div>
          <div style="display:flex;align-items:center;justify-content:space-between">
            <div>
              <div style="font-weight:500">Require approval for writes</div>
              <div style="font-size:12.5px;color:var(--text-2)">Block fs.write and shell.run until you confirm.</div>
            </div>
            <div class="switch on" data-switch></div>
          </div>
        </div>
      </div>
    `;
  }

  function renderIntegrations() {
    return `
      <div class="card" style="padding:28px">
        <h3>Integrations</h3>
        <p style="color:var(--text-2);font-size:13px;margin-top:6px;margin-bottom:20px">Connect services to let agents read, write, and orchestrate across your stack.</p>

        <div class="grid grid--2" style="gap:12px">
          ${window.MOCK.integrations.map(i => `
            <div class="integ">
              <div class="integ__icon" style="${i.connected ? 'color:var(--accent);background:var(--accent-dim)' : ''}">${icons[i.icon](18)}</div>
              <div class="integ__body">
                <div class="integ__name">${escapeHTML(i.name)}</div>
                <div class="integ__status ${i.connected ? 'connected' : ''}">${escapeHTML(i.status)}</div>
              </div>
              <button class="btn ${i.connected ? 'btn--ghost' : 'btn--primary'} btn--sm">${i.connected ? 'Manage' : 'Connect'}</button>
            </div>`).join('')}
        </div>
      </div>
    `;
  }

  function renderSecurity() {
    return `
      <div class="card" style="padding:28px;margin-bottom:16px">
        <div style="display:flex;align-items:center;gap:14px;margin-bottom:18px">
          <div style="width:44px;height:44px;border-radius:10px;background:var(--success-dim);color:var(--success);display:grid;place-items:center">
            ${icons.shield(20)}
          </div>
          <div style="flex:1">
            <h3 style="margin-bottom:2px">BeyondGuardrails</h3>
            <div style="font-size:13px;color:var(--text-2)">Multi-layer policy enforcement across every agent call. All checks green.</div>
          </div>
          <span class="badge badge--success"><span class="dot online"></span> Active</span>
        </div>
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px">
          ${[
            { label: 'PII scrubbing', val: 'On' },
            { label: 'Output moderation', val: 'Strict' },
            { label: 'Tool allowlist', val: '47 tools' },
            { label: 'Prompt injection', val: 'Blocking' },
            { label: 'Egress policy', val: '12 rules' },
            { label: 'Audit retention', val: '90 days' },
          ].map(x => `
            <div style="padding:12px;background:var(--bg-2);border-radius:8px;border:1px solid var(--border-subtle)">
              <div style="font-size:11.5px;color:var(--text-3)">${x.label}</div>
              <div style="font-weight:500;margin-top:2px">${x.val}</div>
            </div>`).join('')}
        </div>
      </div>

      <div class="card" style="padding:28px">
        <div style="display:flex;align-items:center;gap:14px;margin-bottom:18px">
          <div style="width:44px;height:44px;border-radius:10px;background:var(--accent-dim);color:var(--accent);display:grid;place-items:center">
            ${icons.file(20)}
          </div>
          <div style="flex:1">
            <h3 style="margin-bottom:2px">Audit ledger</h3>
            <div style="font-size:13px;color:var(--text-2)">Immutable, append-only log of agent and user actions.</div>
          </div>
          <button class="btn btn--ghost btn--sm">${icons.arrowUpRight(13)} Export</button>
        </div>
        <div style="background:var(--bg-0);border:1px solid var(--border-subtle);border-radius:10px;overflow:hidden;font-family:var(--font-mono);font-size:12px">
          ${window.MOCK.audit.map((a, i) => `
            <div style="display:grid;grid-template-columns:90px 1fr auto;gap:12px;padding:10px 14px;${i > 0 ? 'border-top:1px solid var(--border-subtle)' : ''};${a.level === 'err' ? 'background:rgba(240,89,106,0.05)' : a.level === 'warn' ? 'background:rgba(245,185,113,0.04)' : ''}">
              <span style="color:var(--text-3)">${a.t}</span>
              <span><span style="color:${a.level === 'err' ? 'var(--danger)' : a.level === 'warn' ? 'var(--warn)' : 'var(--accent)'}">${a.who}</span> <span style="color:var(--text-2)">${a.what}</span></span>
              <span style="color:var(--text-3);text-transform:uppercase;font-size:10px;letter-spacing:.08em">${a.level}</span>
            </div>`).join('')}
        </div>
      </div>
    `;
  }

  // ── Wiring ──────────────────────────────────────────────────────────────────
  function wire() {
    document.querySelectorAll('[data-tab]').forEach(el => {
      el.addEventListener('click', () => {
        state.tab = el.dataset.tab;
        document.querySelectorAll('[data-tab]').forEach(x => x.classList.toggle('is-active', x === el));
        if (state.tab === 'api' && !state.apiKeys) loadApiKeys();
        else if (state.tab === 'subscription' && !state.usage) loadUsage();
        repaintBody();
      });
    });
    wireBody();
  }

  function wireBody() {
    document.querySelectorAll('[data-switch]').forEach(s => {
      s.addEventListener('click', () => s.classList.toggle('on'));
    });

    // API key inputs — track value changes for button enable/disable
    document.querySelectorAll('[data-key-input]').forEach(input => {
      input.addEventListener('input', (e) => {
        state.apiInputs[input.dataset.keyInput] = e.target.value;
        const btn = document.querySelector(`[data-save-key="${input.dataset.keyInput}"]`);
        if (btn) btn.disabled = !e.target.value.trim();
      });
    });

    // Save key buttons
    document.querySelectorAll('[data-save-key]').forEach(btn => {
      btn.addEventListener('click', () => {
        const provider = btn.dataset.saveKey;
        const val = state.apiInputs[provider] || '';
        saveApiKey(provider, val);
      });
    });

    // Reload keys on error
    const reloadBtn = document.querySelector('[data-action="reload-keys"]');
    if (reloadBtn) {
      reloadBtn.addEventListener('click', () => {
        state.apiKeys = null;
        repaintBody();
        loadApiKeys();
      });
    }
  }

  function mount(root) {
    root.innerHTML = render();
    wire();
    // Pre-load data for whichever tab is active
    if (state.tab === 'api') loadApiKeys();
    else if (state.tab === 'subscription') loadUsage();
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.pages = window.Orchestra.pages || {};
  window.Orchestra.pages.settings = { mount };
})();
