// Orchestra — Agents page
(function () {
  const { icons } = window;
  const { agentCard, hexToAlpha } = window.Orchestra.cards;

  let state = {
    filter: 'all',
    query: '',
    selected: null,
  };

  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function getParams() {
    const h = location.hash;
    const q = h.split('?')[1] || '';
    const params = new URLSearchParams(q);
    return params;
  }

  function render() {
    const p = getParams();
    if (p.get('v')) state.filter = p.get('v');

    return `
      <div class="page page--agents">
        <div class="page__inner">
          <div class="page-header">
            <div>
              <h1>Agents</h1>
              <div class="sub">${window.MOCK.agents.length} agents across ${window.MOCK.verticals.length} verticals. Each agent owns a toolbelt and reports to the Coordinator.</div>
            </div>
            <div style="display:flex;gap:8px">
              <button class="btn btn--ghost">${icons.refresh(13)} Sync</button>
              <button class="btn btn--primary">${icons.plus(13)} Build agent</button>
            </div>
          </div>

          <!-- Vertical filter bar -->
          <div class="tabs" data-agent-tabs>
            <button class="tab ${state.filter === 'all' ? 'is-active' : ''}" data-filter="all">All <span style="color:var(--text-3);margin-left:6px">${window.MOCK.agents.length}</span></button>
            ${window.MOCK.verticals.map(v => `
              <button class="tab ${state.filter === v.id ? 'is-active' : ''}" data-filter="${v.id}">
                <span style="color:${v.color};margin-right:6px;vertical-align:-2px;display:inline-block">${icons[v.icon] ? icons[v.icon](13) : icons.sparkles(13)}</span>
                ${escapeHTML(v.name)}
                <span style="color:var(--text-3);margin-left:6px">${v.agents}</span>
              </button>
            `).join('')}
          </div>

          <!-- Search -->
          <div style="display:flex;gap:12px;margin-bottom:20px;align-items:center">
            <div style="position:relative;flex:1;max-width:400px">
              <span style="position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--text-3)">${icons.search(14)}</span>
              <input class="input" data-agent-search placeholder="Filter agents by name or capability…" style="padding-left:36px" value="${escapeHTML(state.query)}" />
            </div>
            <span style="color:var(--text-3);font-size:12.5px;margin-left:auto" data-agent-count></span>
          </div>

          <!-- Grid -->
          <div class="grid grid--2" data-agent-grid>
            ${renderCards()}
          </div>
        </div>

        <!-- Detail panel -->
        <div class="detail-overlay" data-detail-overlay></div>
        <aside class="detail-panel" data-detail-panel>
          <div class="detail-panel__head">
            <div style="flex:1" data-detail-head></div>
            <button class="icon-btn" data-close-detail aria-label="Close">${icons.x(16)}</button>
          </div>
          <div class="detail-panel__body" data-detail-body></div>
        </aside>
      </div>
    `;
  }

  function filteredAgents() {
    const q = state.query.toLowerCase();
    return window.MOCK.agents.filter(a => {
      const matchesV = state.filter === 'all' || a.vertical === state.filter;
      const matchesQ = !q || a.name.toLowerCase().includes(q) || a.desc.toLowerCase().includes(q);
      return matchesV && matchesQ;
    });
  }

  function renderCards() {
    const list = filteredAgents();
    if (list.length === 0) {
      return `<div class="empty" style="grid-column:1/-1">
        <div class="icon-lg">${icons.search(36)}</div>
        <div>No agents match your filters.</div>
      </div>`;
    }
    return list.map(agentCard).join('');
  }

  function updateCount() {
    const el = document.querySelector('[data-agent-count]');
    if (el) el.textContent = `${filteredAgents().length} of ${window.MOCK.agents.length} shown`;
  }

  function updateGrid() {
    const g = document.querySelector('[data-agent-grid]');
    if (g) g.innerHTML = renderCards();
    updateCount();
    wireCards();
  }

  function wireTabs() {
    document.querySelectorAll('[data-filter]').forEach(t => {
      t.addEventListener('click', () => {
        state.filter = t.dataset.filter;
        document.querySelectorAll('[data-filter]').forEach(x => x.classList.toggle('is-active', x === t));
        updateGrid();
      });
    });
  }

  function wireSearch() {
    const el = document.querySelector('[data-agent-search]');
    if (el) el.addEventListener('input', () => {
      state.query = el.value;
      updateGrid();
    });
  }

  function wireCards() {
    document.querySelectorAll('[data-agent-id]').forEach(c => {
      c.addEventListener('click', () => openDetail(c.dataset.agentId));
    });
  }

  function openDetail(id) {
    const a = window.MOCK.agents.find(x => x.id === id);
    if (!a) return;
    state.selected = id;

    const head = document.querySelector('[data-detail-head]');
    const body = document.querySelector('[data-detail-body]');
    const panel = document.querySelector('[data-detail-panel]');
    const overlay = document.querySelector('[data-detail-overlay]');

    head.innerHTML = `
      <div style="display:flex;gap:14px;align-items:center">
        <div class="agent-card__icon" style="background:${hexToAlpha(a.color,0.14)};color:${a.color}">
          ${icons[a.icon] ? icons[a.icon](18) : icons.sparkles(18)}
        </div>
        <div>
          <div style="display:flex;align-items:center;gap:8px">
            <h3 style="font-size:18px">${escapeHTML(a.name)}</h3>
            <span class="dot ${a.status === 'online' ? 'online' : 'busy'}"></span>
          </div>
          <div style="font-size:12.5px;color:var(--text-2)"><span style="text-transform:capitalize">${a.vertical}</span> · ${a.tools} tools</div>
        </div>
      </div>
    `;

    body.innerHTML = `
      <p style="color:var(--text-2);line-height:1.55;margin-bottom:24px">${escapeHTML(a.desc)}</p>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:24px">
        <div style="padding:14px;background:var(--bg-2);border-radius:10px;border:1px solid var(--border-subtle)">
          <div style="font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em">Success rate</div>
          <div style="font-size:22px;font-weight:600;margin-top:4px">${(92 + (a.tools % 7)).toFixed(1)}%</div>
        </div>
        <div style="padding:14px;background:var(--bg-2);border-radius:10px;border:1px solid var(--border-subtle)">
          <div style="font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em">Avg latency</div>
          <div style="font-size:22px;font-weight:600;margin-top:4px">${(1.2 + (a.tools % 4) * 0.3).toFixed(1)}s</div>
        </div>
      </div>

      <h4 style="font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-3);margin-bottom:12px">Toolbelt (${a.tools})</h4>
      <div style="display:flex;flex-direction:column;gap:6px;margin-bottom:24px">
        ${sampleTools(a).map(t => `
          <div style="display:flex;align-items:center;gap:12px;padding:10px 12px;background:var(--bg-2);border-radius:8px;border:1px solid var(--border-subtle)">
            <span style="color:var(--accent)">${icons[t.icon] ? icons[t.icon](14) : icons.sparkles(14)}</span>
            <div style="flex:1;min-width:0">
              <div style="font-size:13px;font-weight:500">${escapeHTML(t.name)}</div>
              <div style="font-size:11.5px;color:var(--text-2)">${escapeHTML(t.desc)}</div>
            </div>
          </div>`).join('')}
      </div>

      <h4 style="font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-3);margin-bottom:12px">Recent invocations</h4>
      <div style="display:flex;flex-direction:column;gap:6px">
        ${sampleInvocations(a).map(inv => `
          <div style="display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--bg-2);border-radius:8px;border:1px solid var(--border-subtle);font-size:12.5px">
            <span class="badge badge--${inv.status === 'ok' ? 'success' : 'danger'}">${inv.status === 'ok' ? '✓' : '✗'}</span>
            <span style="flex:1">${escapeHTML(inv.desc)}</span>
            <span style="color:var(--text-3);font-size:11px">${escapeHTML(inv.when)}</span>
          </div>`).join('')}
      </div>

      <div style="display:flex;gap:8px;margin-top:24px">
        <button class="btn btn--primary" style="flex:1;justify-content:center" data-close-detail>${icons.chat(13)} Chat with ${escapeHTML(a.name)}</button>
        <button class="btn btn--ghost">${icons.settings(13)} Configure</button>
      </div>
    `;

    panel.classList.add('is-open');
    overlay.classList.add('is-open');
  }

  function closeDetail() {
    state.selected = null;
    document.querySelector('[data-detail-panel]')?.classList.remove('is-open');
    document.querySelector('[data-detail-overlay]')?.classList.remove('is-open');
  }

  function sampleTools(a) {
    const pool = [
      { name: 'search.semantic',    desc: 'Hybrid BM25 + embedding search across docs.', icon: 'search' },
      { name: 'db.query',           desc: 'Parameterized SQL with RLS enforcement.',      icon: 'file' },
      { name: 'fs.read',            desc: 'Read project files with path scoping.',        icon: 'folder' },
      { name: 'fs.write',           desc: 'Atomic write with change previews.',           icon: 'file' },
      { name: 'web.fetch',          desc: 'Fetch URLs with content-type guards.',         icon: 'globe' },
      { name: 'shell.run',          desc: 'Sandboxed command execution.',                 icon: 'terminal' },
      { name: 'ai.plan',            desc: 'Decompose goals into agent subtasks.',         icon: 'sparkles' },
      { name: 'graph.viz',          desc: 'Render dependency and data flow graphs.',      icon: 'graph' },
      { name: 'report.publish',     desc: 'Publish reports to shared workspace.',         icon: 'arrowUpRight' },
    ];
    const n = Math.min(a.tools, pool.length);
    return pool.slice(0, n);
  }

  function sampleInvocations(a) {
    return [
      { status: 'ok',   desc: `${a.name} ran end-to-end on cohort 2041`,     when: '2m ago' },
      { status: 'ok',   desc: 'Scheduled nightly batch completed cleanly',   when: '6h ago' },
      { status: 'ok',   desc: 'Manual invocation from @ashton',              when: '1d ago' },
      { status: 'fail', desc: 'Timeout reading cold-storage BAM',            when: '2d ago' },
    ];
  }

  function mount(root) {
    root.innerHTML = render();
    wireTabs();
    wireSearch();
    wireCards();
    updateCount();

    document.addEventListener('click', (e) => {
      if (e.target.closest('[data-close-detail]') || e.target === document.querySelector('[data-detail-overlay]')) {
        closeDetail();
      }
    });
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.pages = window.Orchestra.pages || {};
  window.Orchestra.pages.agents = { mount };
})();
