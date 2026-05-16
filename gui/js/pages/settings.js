// Orchestra — Settings page
(function () {
  const { icons } = window;

  let state = {
    tab: 'profile',
    showKey: false,
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
            <textarea class="input" style="height:80px;padding:10px 12px;line-height:1.5" placeholder="Tell Orchestra a bit about how you work…">Prefers concise output with linked evidence. Reviews agent diffs before approval. Based in Brooklyn, NY.</textarea>
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
    const masked = '••••••••••••••••••••••••••••r7Bq';
    const revealed = 'sk-orch-7a2f84Qb9c1d3eKm0f2gH4iJ8lN6Or7Bq';
    return `
      <div class="card" style="padding:28px">
        <h3>API keys</h3>
        <p style="color:var(--text-2);font-size:13px;margin-top:6px;margin-bottom:20px">Keys grant agents access to Orchestra on your behalf. Rotate immediately if exposed.</p>

        <div style="padding:18px;background:var(--bg-2);border-radius:10px;border:1px solid var(--border-subtle);margin-bottom:12px">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
            <div style="display:flex;align-items:center;gap:10px">
              <div style="width:32px;height:32px;border-radius:8px;background:var(--accent-dim);color:var(--accent);display:grid;place-items:center">${icons.key(14)}</div>
              <div>
                <div style="font-weight:500">Production key</div>
                <div style="font-size:11.5px;color:var(--text-3)">Created Mar 04 · Last used 2m ago</div>
              </div>
            </div>
            <span class="badge badge--success">Active</span>
          </div>
          <div style="display:flex;gap:8px;align-items:center">
            <code style="flex:1;padding:8px 12px;background:var(--bg-0);border-radius:6px;font-size:12.5px;color:var(--text);border:1px solid var(--border-subtle);font-family:var(--font-mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${state.showKey ? revealed : masked}</code>
            <button class="icon-btn" data-toggle-key title="${state.showKey ? 'Hide' : 'Reveal'}">${state.showKey ? icons.eyeOff(14) : icons.eye(14)}</button>
            <button class="icon-btn" title="Copy">${icons.copy(14)}</button>
            <button class="icon-btn" style="color:var(--danger)" title="Revoke">${icons.trash(14)}</button>
          </div>
        </div>

        <div style="padding:18px;background:var(--bg-2);border-radius:10px;border:1px solid var(--border-subtle);margin-bottom:12px">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
            <div style="display:flex;align-items:center;gap:10px">
              <div style="width:32px;height:32px;border-radius:8px;background:var(--bg-3);color:var(--text-2);display:grid;place-items:center">${icons.key(14)}</div>
              <div>
                <div style="font-weight:500">Staging key</div>
                <div style="font-size:11.5px;color:var(--text-3)">Created Feb 11 · Last used 1d ago</div>
              </div>
            </div>
            <span class="badge">Active</span>
          </div>
          <div style="display:flex;gap:8px;align-items:center">
            <code style="flex:1;padding:8px 12px;background:var(--bg-0);border-radius:6px;font-size:12.5px;color:var(--text);border:1px solid var(--border-subtle);font-family:var(--font-mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">••••••••••••••••••••••••••••Kq2x</code>
            <button class="icon-btn">${icons.eye(14)}</button>
            <button class="icon-btn">${icons.copy(14)}</button>
            <button class="icon-btn" style="color:var(--danger)">${icons.trash(14)}</button>
          </div>
        </div>

        <button class="btn btn--ghost" style="margin-top:8px">${icons.plus(14)} Create new key</button>
      </div>
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

  function renderSubscription() {
    return `
      <div class="card" style="padding:28px;background:linear-gradient(135deg,var(--bg-1),rgba(110,110,245,0.06));border:1px solid rgba(110,110,245,0.2);position:relative;overflow:hidden">
        <div style="position:absolute;top:-40px;right:-40px;width:220px;height:220px;border-radius:999px;background:radial-gradient(circle,var(--accent-dim),transparent 70%);pointer-events:none"></div>
        <div style="position:relative">
          <div class="badge badge--accent" style="margin-bottom:12px">Current plan</div>
          <h2 style="font-size:28px;margin-bottom:4px">Orchestra Max</h2>
          <div style="display:flex;align-items:baseline;gap:6px;margin-bottom:20px">
            <div style="font-size:32px;font-weight:600">$250</div>
            <div style="color:var(--text-2)">/ month · billed annually</div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-bottom:24px">
            <div>
              <div style="font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em">Agent calls</div>
              <div style="font-size:22px;font-weight:600;margin-top:4px">1.4M <span style="font-size:12px;color:var(--text-3);font-weight:400">/ 5M</span></div>
              <div style="height:4px;background:var(--bg-3);border-radius:999px;margin-top:8px"><div style="height:100%;width:28%;background:var(--accent);border-radius:999px"></div></div>
            </div>
            <div>
              <div style="font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em">Compute hours</div>
              <div style="font-size:22px;font-weight:600;margin-top:4px">312h <span style="font-size:12px;color:var(--text-3);font-weight:400">/ 1000h</span></div>
              <div style="height:4px;background:var(--bg-3);border-radius:999px;margin-top:8px"><div style="height:100%;width:31%;background:var(--teal);border-radius:999px"></div></div>
            </div>
            <div>
              <div style="font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em">Storage</div>
              <div style="font-size:22px;font-weight:600;margin-top:4px">48 GB <span style="font-size:12px;color:var(--text-3);font-weight:400">/ 500 GB</span></div>
              <div style="height:4px;background:var(--bg-3);border-radius:999px;margin-top:8px"><div style="height:100%;width:10%;background:var(--success);border-radius:999px"></div></div>
            </div>
          </div>
          <div style="display:flex;gap:8px">
            <button class="btn btn--primary">Manage billing</button>
            <button class="btn btn--ghost">View invoices</button>
            <button class="btn btn--subtle">Downgrade</button>
          </div>
        </div>
      </div>

      <div class="card" style="padding:24px;margin-top:16px">
        <h4 style="margin-bottom:12px">Plan history</h4>
        <div style="display:flex;flex-direction:column;gap:8px">
          <div style="display:flex;align-items:center;padding:10px 0;border-bottom:1px solid var(--border-subtle);font-size:13px"><span style="flex:1">Upgraded to Max</span><span style="color:var(--text-3);font-family:var(--font-mono);font-size:12px">Mar 04, 2025</span></div>
          <div style="display:flex;align-items:center;padding:10px 0;border-bottom:1px solid var(--border-subtle);font-size:13px"><span style="flex:1">Started Pro trial</span><span style="color:var(--text-3);font-family:var(--font-mono);font-size:12px">Feb 11, 2025</span></div>
          <div style="display:flex;align-items:center;padding:10px 0;font-size:13px"><span style="flex:1">Created account</span><span style="color:var(--text-3);font-family:var(--font-mono);font-size:12px">Feb 10, 2025</span></div>
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

  function wire() {
    document.querySelectorAll('[data-tab]').forEach(el => {
      el.addEventListener('click', () => {
        state.tab = el.dataset.tab;
        document.querySelector('[data-settings-body]').innerHTML = renderBody();
        document.querySelectorAll('[data-tab]').forEach(x => x.classList.toggle('is-active', x === el));
        wireBody();
      });
    });
    wireBody();
  }

  function wireBody() {
    document.querySelectorAll('[data-switch]').forEach(s => {
      s.addEventListener('click', () => s.classList.toggle('on'));
    });
    const keyToggle = document.querySelector('[data-toggle-key]');
    if (keyToggle) {
      keyToggle.addEventListener('click', () => {
        state.showKey = !state.showKey;
        document.querySelector('[data-settings-body]').innerHTML = renderBody();
        wireBody();
      });
    }
  }

  function mount(root) {
    root.innerHTML = render();
    wire();
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.pages = window.Orchestra.pages || {};
  window.Orchestra.pages.settings = { mount };
})();
