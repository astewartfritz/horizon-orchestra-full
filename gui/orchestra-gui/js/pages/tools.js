// Orchestra — Tools page
(function () {
  const { icons } = window;

  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Generate tool entries from all agents
  function buildToolCatalog() {
    const TOOL_TEMPLATES = [
      { name: 'search.semantic',    icon: 'search',     desc: 'Hybrid BM25 + embedding search across documents and vector stores.' },
      { name: 'db.query',           icon: 'file',       desc: 'Parameterized SQL queries with row-level security enforcement.' },
      { name: 'fs.read',            icon: 'folder',     desc: 'Read project files with sandboxed path scoping.' },
      { name: 'fs.write',           icon: 'file',       desc: 'Atomic write operations with change preview and approval gates.' },
      { name: 'web.fetch',          icon: 'globe',      desc: 'Fetch external URLs with content-type guards and sanitization.' },
      { name: 'shell.run',          icon: 'terminal',   desc: 'Sandboxed command execution in isolated compute environments.' },
      { name: 'ai.plan',            icon: 'sparkles',   desc: 'Decompose high-level goals into structured agent subtasks.' },
      { name: 'graph.viz',          icon: 'graph',      desc: 'Render dependency and data flow graphs from structured data.' },
      { name: 'report.publish',     icon: 'arrowUpRight', desc: 'Publish reports and artifacts to the shared workspace.' },
      { name: 'ai.embed',           icon: 'sparkles',   desc: 'Generate semantic embeddings for documents and queries.' },
      { name: 'schedule.book',      icon: 'calendar',   desc: 'Book appointments and manage calendar availability.' },
      { name: 'notify.send',        icon: 'bell',       desc: 'Send notifications via email, Slack, or webhook endpoints.' },
      { name: 'data.transform',     icon: 'activity',   desc: 'Apply data transformations, normalization, and feature engineering.' },
      { name: 'ml.predict',         icon: 'sparkles',   desc: 'Run inference against trained ML models for predictions.' },
      { name: 'audit.log',          icon: 'shield',     desc: 'Write immutable audit entries to the ledger.' },
      { name: 'ocr.extract',        icon: 'file',       desc: 'Extract structured text and tables from PDF and image documents.' },
      { name: 'api.call',           icon: 'globe',      desc: 'Make authenticated REST API calls with retry and timeout policies.' },
      { name: 'queue.push',         icon: 'arrowUpRight', desc: 'Push messages to distributed queues (SQS, Kafka, Pub/Sub).' },
    ];

    const tools = [];
    window.MOCK.agents.forEach(agent => {
      const n = Math.min(agent.tools, TOOL_TEMPLATES.length);
      for (let i = 0; i < n; i++) {
        const tmpl = TOOL_TEMPLATES[i % TOOL_TEMPLATES.length];
        tools.push({
          name: tmpl.name,
          icon: tmpl.icon,
          desc: tmpl.desc,
          agent: agent.name,
          agentId: agent.id,
          vertical: agent.vertical,
          color: agent.color,
        });
      }
    });
    return tools;
  }

  const ALL_TOOLS = buildToolCatalog();

  let state = {
    query: '',
    vertical: 'all',
  };

  function verticalColor(vid) {
    const v = window.MOCK.verticals.find(x => x.id === vid);
    return v ? v.color : '#6E6EF5';
  }

  function hexToAlpha(hex, alpha) {
    const r = parseInt(hex.slice(1,3), 16);
    const g = parseInt(hex.slice(3,5), 16);
    const b = parseInt(hex.slice(5,7), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }

  function filteredTools() {
    const q = state.query.toLowerCase();
    return ALL_TOOLS.filter(t => {
      const matchV = state.vertical === 'all' || t.vertical === state.vertical;
      const matchQ = !q ||
        t.name.toLowerCase().includes(q) ||
        t.agent.toLowerCase().includes(q) ||
        t.desc.toLowerCase().includes(q);
      return matchV && matchQ;
    });
  }

  function render() {
    const filtered = filteredTools();
    return `
      <div class="page page--tools">
        <div class="page__inner" style="max-width:1100px">
          <div class="page-header">
            <div>
              <h1>Tools</h1>
              <div class="sub">408 tools across 9 verticals. Each tool is owned by one or more agents and enforces strict access policies.</div>
            </div>
            <div style="display:flex;gap:8px">
              <button class="btn btn--ghost">${icons.refresh(13)} Sync</button>
              <button class="btn btn--primary" data-action="open-register-tool">${icons.plus(13)} Register tool</button>
            </div>
          </div>

          <!-- Filter bar -->
          <div style="display:flex;gap:12px;margin-bottom:24px;align-items:center;flex-wrap:wrap">
            <div style="position:relative;flex:1;max-width:380px">
              <span style="position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--text-3)">${icons.search(14)}</span>
              <input class="input" data-tools-search placeholder="Search tools, agents, or descriptions…" style="padding-left:36px" value="${escapeHTML(state.query)}" />
            </div>
            <select class="input" data-tools-vertical style="height:36px;padding:0 12px;max-width:200px">
              <option value="all">All verticals</option>
              ${window.MOCK.verticals.map(v => `
                <option value="${v.id}" ${state.vertical === v.id ? 'selected' : ''}>${escapeHTML(v.name)}</option>
              `).join('')}
            </select>
            <span style="font-size:12.5px;color:var(--text-3);margin-left:auto" data-tools-count>${filtered.length} tools shown</span>
          </div>

          <!-- Tool list -->
          <div class="card" style="padding:0;overflow:hidden">
            <div style="display:grid;grid-template-columns:220px 1fr 180px;padding:10px 16px;background:var(--bg-2);border-bottom:1px solid var(--border-subtle)">
              <div style="font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em;font-weight:600">Tool</div>
              <div style="font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em;font-weight:600">Description</div>
              <div style="font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em;font-weight:600">Owner agent</div>
            </div>
            <div data-tools-list>
              ${renderToolRows(filtered)}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function renderToolRows(toolList) {
    if (toolList.length === 0) {
      return `<div class="empty" style="padding:48px"><div class="icon-lg">${icons.search(36)}</div><div>No tools match your filters.</div></div>`;
    }
    return toolList.slice(0, 200).map((t, i) => `
      <div style="display:grid;grid-template-columns:220px 1fr 180px;padding:12px 16px;border-top:${i > 0 ? '1px solid var(--border-subtle)' : 'none'};align-items:center;transition:background var(--dur) var(--ease)" class="tool-row">
        <div style="display:flex;align-items:center;gap:10px">
          <span style="color:${t.color};width:18px;flex-shrink:0">${icons[t.icon] ? icons[t.icon](14) : icons.sparkles(14)}</span>
          <code style="font-size:12px;color:var(--text);font-family:var(--font-mono)">${escapeHTML(t.name)}</code>
        </div>
        <div style="font-size:12.5px;color:var(--text-2);padding-right:24px;line-height:1.45">${escapeHTML(t.desc)}</div>
        <div style="display:flex;align-items:center;gap:8px">
          <div style="width:20px;height:20px;border-radius:999px;background:${hexToAlpha(t.color,0.15)};color:${t.color};display:grid;place-items:center;flex-shrink:0">
            ${icons.agents ? icons.agents(9) : ''}
          </div>
          <span style="font-size:12px;color:var(--text-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHTML(t.agent)}</span>
        </div>
      </div>`).join('');
  }

  function openRegisterToolModal() {
    const existing = document.querySelector('[data-register-tool-modal]');
    if (existing) existing.remove();

    const agentOptions = window.MOCK.agents.map(a =>
      `<option value="${a.id}">${escapeHTML(a.name)}</option>`
    ).join('');

    const div = document.createElement('div');
    div.setAttribute('data-register-tool-modal', '');
    div.style.cssText = 'position:fixed;inset:0;background:rgba(9,9,14,0.7);backdrop-filter:blur(6px);z-index:200;display:flex;align-items:center;justify-content:center';
    div.innerHTML = `
      <div style="background:var(--bg-2);border:1px solid var(--border);border-radius:var(--r-xl);width:460px;max-width:92vw;box-shadow:var(--shadow-lg);overflow:hidden" onclick="event.stopPropagation()">
        <div style="padding:24px 28px;border-bottom:1px solid var(--border-subtle);display:flex;align-items:center;justify-content:space-between">
          <div>
            <h3 style="font-size:17px">Register a tool</h3>
            <div style="color:var(--text-2);font-size:12.5px;margin-top:3px">Add a new tool to an agent’s toolbelt.</div>
          </div>
          <button style="display:grid;place-items:center;width:32px;height:32px;border-radius:var(--r-sm);color:var(--text-3);transition:background var(--dur)" data-close-register>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
          </button>
        </div>
        <div style="padding:24px 28px;display:flex;flex-direction:column;gap:16px">
          <div class="field">
            <label>Tool name</label>
            <input class="input" id="reg-tool-name" placeholder="e.g. payments.charge" />
          </div>
          <div class="field">
            <label>Description</label>
            <textarea class="input" id="reg-tool-desc" placeholder="What does this tool do?" style="height:80px;padding:10px 12px;line-height:1.5"></textarea>
          </div>
          <div class="field">
            <label>Owning agent</label>
            <select class="input" id="reg-tool-agent" style="height:36px;padding:0 12px">
              ${agentOptions}
            </select>
          </div>
        </div>
        <div style="padding:16px 28px;border-top:1px solid var(--border-subtle);display:flex;gap:8px;justify-content:flex-end">
          <button class="btn btn--ghost" data-close-register>Cancel</button>
          <button class="btn btn--primary" data-register-tool-btn>${icons.plus ? icons.plus(13) : ''} Register</button>
        </div>
      </div>
    `;
    document.body.appendChild(div);

    // Close handlers
    div.addEventListener('click', (e) => { if (e.target === div) div.remove(); });
    div.querySelectorAll('[data-close-register]').forEach(btn => {
      btn.addEventListener('click', () => div.remove());
    });

    // Register button
    div.querySelector('[data-register-tool-btn]').addEventListener('click', () => {
      const nameEl = div.querySelector('#reg-tool-name');
      const agentEl = div.querySelector('#reg-tool-agent');
      const descEl = div.querySelector('#reg-tool-desc');
      const name = (nameEl?.value || '').trim();
      if (!name) {
        nameEl?.focus();
        return;
      }
      const agentId = agentEl?.value || '';
      const agentObj = window.MOCK.agents.find(a => a.id === agentId);
      // Add to the tool catalog
      ALL_TOOLS.push({
        name,
        icon: 'sparkles',
        desc: (descEl?.value || '').trim() || 'Custom tool.',
        agent: agentObj?.name || 'Unknown',
        agentId,
        vertical: agentObj?.vertical || 'all',
        color: agentObj?.color || '#6E6EF5',
      });
      div.remove();
      window.Orchestra.toast('Tool registered: ' + name, 'success');
      // Refresh the tools list
      const listEl = document.querySelector('[data-tools-list]');
      const countEl = document.querySelector('[data-tools-count]');
      const filtered = filteredTools();
      if (listEl) {
        listEl.innerHTML = renderToolRows(filtered);
        listEl.querySelectorAll('.tool-row').forEach(row => {
          row.addEventListener('mouseenter', () => row.style.background = 'var(--bg-2)');
          row.addEventListener('mouseleave', () => row.style.background = '');
        });
      }
      if (countEl) countEl.textContent = `${filtered.length} tools shown`;
    });
  }

  function mount(root) {
    root.innerHTML = render();

    // Wire Register tool button
    root.querySelector('[data-action="open-register-tool"]')?.addEventListener('click', openRegisterToolModal);

    // Add hover styles to tool rows via JS
    root.querySelectorAll('.tool-row').forEach(row => {
      row.addEventListener('mouseenter', () => row.style.background = 'var(--bg-2)');
      row.addEventListener('mouseleave', () => row.style.background = '');
    });

    const searchInput = root.querySelector('[data-tools-search]');
    const vertSelect  = root.querySelector('[data-tools-vertical]');
    const countEl    = root.querySelector('[data-tools-count]');
    const listEl     = root.querySelector('[data-tools-list]');

    function update() {
      const filtered = filteredTools();
      if (countEl) countEl.textContent = `${filtered.length} tools shown`;
      if (listEl) {
        listEl.innerHTML = renderToolRows(filtered);
        listEl.querySelectorAll('.tool-row').forEach(row => {
          row.addEventListener('mouseenter', () => row.style.background = 'var(--bg-2)');
          row.addEventListener('mouseleave', () => row.style.background = '');
        });
      }
    }

    if (searchInput) {
      searchInput.addEventListener('input', () => {
        state.query = searchInput.value;
        update();
      });
    }
    if (vertSelect) {
      vertSelect.addEventListener('change', () => {
        state.vertical = vertSelect.value;
        update();
      });
    }
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.pages = window.Orchestra.pages || {};
  // Register action via global delegation
  window.Orchestra = window.Orchestra || {};
  window.Orchestra._actionHandlers = window.Orchestra._actionHandlers || {};
  window.Orchestra._actionHandlers['open-register-tool'] = openRegisterToolModal;

  window.Orchestra.pages = window.Orchestra.pages || {};
  window.Orchestra.pages.tools = { mount };
})();
