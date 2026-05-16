// Orchestra — Coordination page
(function () {
  const { icons } = window;

  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  const COORD_FAMILIES = [
    {
      id: 'market',
      name: 'Market-Based Auctions',
      icon: 'wallet',
      color: '#34D399',
      algorithms: ['Contract Net Protocol (CNP)', 'VCG Mechanism', 'Double Auction', 'Resource Allocation'],
      desc: 'Agents bid on tasks using economic primitives. CNP broadcasts a call for proposals; the best offer wins resources via VCG or double-auction clearing.',
      use: 'Task allocation, compute resource bidding, multi-agent job scheduling.',
    },
    {
      id: 'dcop',
      name: 'Distributed Constraint Optimization',
      icon: 'coord',
      color: '#6E6EF5',
      algorithms: ['ADOPT', 'DPOP', 'Max-Sum', 'DSA / MGM'],
      desc: 'Agents collaboratively minimize a global cost function defined by local constraints. DPOP achieves optimal solutions via dynamic programming on a pseudo-tree.',
      use: 'Shift scheduling, sensor network calibration, multi-robot path planning.',
    },
    {
      id: 'meta',
      name: 'Metaheuristic Coordination',
      icon: 'activity',
      color: '#F5B971',
      algorithms: ['GA / NSGA-II', 'PSO', 'ACO', 'Simulated Annealing', 'Tabu Search', 'Harmony Search', 'Differential Evolution'],
      desc: 'Population-based or trajectory-based search strategies that explore large solution spaces. NSGA-II handles multi-objective problems; ACO uses pheromone trails.',
      use: 'Vehicle routing, hyperparameter optimization, circuit layout, workflow scheduling.',
    },
    {
      id: 'negotiation',
      name: 'Negotiation Scheduling',
      icon: 'gavel',
      color: '#C792EA',
      algorithms: ['Rubinstein Bargaining', 'MECA Protocol', 'Deadline-Aware Negotiation', 'Multi-Issue Negotiation'],
      desc: 'Bilateral or multi-lateral protocols where agents exchange offers and counter-offers. Rubinstein alternating-offers guarantees convergence under discounting.',
      use: 'Service-level agreement negotiation, coalition formation, supply chain contracts.',
    },
    {
      id: 'marl',
      name: 'Multi-Agent Reinforcement Learning',
      icon: 'sparkles',
      color: '#00C9B8',
      algorithms: ['QMIX', 'MAPPO', 'Reward Shaping', 'Cooperative / Competitive Environments'],
      desc: 'Agents learn coordination policies through joint reward signals. QMIX enables centralized training with decentralized execution via monotonic value mixing.',
      use: 'Autonomous vehicle fleets, trading agent swarms, game-theoretic AI opponents.',
    },
  ];

  function hexToAlpha(hex, alpha) {
    const r = parseInt(hex.slice(1,3), 16);
    const g = parseInt(hex.slice(3,5), 16);
    const b = parseInt(hex.slice(5,7), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }

  function familyCard(f) {
    return `
      <div class="card" style="padding:24px;position:relative;overflow:hidden">
        <div style="position:absolute;top:-40px;right:-40px;width:140px;height:140px;border-radius:999px;background:radial-gradient(circle,${hexToAlpha(f.color,0.1)},transparent 70%);pointer-events:none"></div>
        <div style="display:flex;gap:14px;align-items:flex-start;margin-bottom:14px">
          <div style="width:44px;height:44px;border-radius:var(--r);background:${hexToAlpha(f.color,0.15)};color:${f.color};display:grid;place-items:center;flex-shrink:0">
            ${icons[f.icon] ? icons[f.icon](20) : icons.sparkles(20)}
          </div>
          <div>
            <div style="font-size:15px;font-weight:600;letter-spacing:-0.01em;margin-bottom:2px">${escapeHTML(f.name)}</div>
            <div style="font-size:11.5px;color:var(--text-3)">${f.algorithms.length} algorithms</div>
          </div>
        </div>

        <p style="font-size:13px;color:var(--text-2);line-height:1.6;margin-bottom:14px">${escapeHTML(f.desc)}</p>

        <div style="margin-bottom:14px">
          <div style="font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-3);margin-bottom:8px;font-weight:600">Algorithms</div>
          <div style="display:flex;flex-wrap:wrap;gap:6px">
            ${f.algorithms.map(a => `
              <span style="display:inline-flex;align-items:center;height:22px;padding:0 10px;background:${hexToAlpha(f.color,0.12)};color:${f.color};border-radius:999px;font-size:11.5px;font-weight:500;border:1px solid ${hexToAlpha(f.color,0.25)}">
                ${escapeHTML(a)}
              </span>`).join('')}
          </div>
        </div>

        <div style="padding-top:12px;border-top:1px solid var(--border-subtle)">
          <div style="font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-3);margin-bottom:4px;font-weight:600">Use cases</div>
          <div style="font-size:12.5px;color:var(--text-2)">${escapeHTML(f.use)}</div>
        </div>
      </div>
    `;
  }

  function render() {
    const totalAlgos = COORD_FAMILIES.reduce((s, f) => s + f.algorithms.length, 0);
    return `
      <div class="page page--coordination">
        <div class="page__inner" style="max-width:1200px">
          <div class="page-header">
            <div>
              <h1>Coordination</h1>
              <div class="sub">${COORD_FAMILIES.length} algorithm families · ${totalAlgos} algorithms. Govern how Orchestra agents negotiate, compete, and cooperate.</div>
            </div>
            <div style="display:flex;gap:8px">
              <button class="btn btn--ghost">${icons.refresh(13)} Docs</button>
              <button class="btn btn--primary" data-action="open-config">${icons.plus(13)} Configure</button>
            </div>
          </div>

          <!-- Summary stats -->
          <div class="grid grid--4" style="margin-bottom:32px">
            ${[
              { label: 'Families',    value: COORD_FAMILIES.length,  icon: 'verticals', color: '#6E6EF5' },
              { label: 'Algorithms',  value: totalAlgos,             icon: 'coord',     color: '#00C9B8' },
              { label: 'Active runs', value: 3,                      icon: 'activity',  color: '#34D399' },
              { label: 'Avg latency', value: '1.4s',                 icon: 'clock',     color: '#F5B971' },
            ].map(s => `
              <div class="card" style="padding:20px">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
                  <div style="font-size:12.5px;color:var(--text-2);font-weight:500">${escapeHTML(s.label)}</div>
                  <div style="width:28px;height:28px;border-radius:var(--r-sm);background:rgba(${s.color === '#6E6EF5' ? '110,110,245' : s.color === '#00C9B8' ? '0,201,184' : s.color === '#34D399' ? '52,211,153' : '245,185,113'},0.14);color:${s.color};display:grid;place-items:center">
                    ${icons[s.icon] ? icons[s.icon](13) : icons.sparkles(13)}
                  </div>
                </div>
                <div style="font-size:28px;font-weight:600;letter-spacing:-0.03em">${escapeHTML(String(s.value))}</div>
              </div>`).join('')}
          </div>

          <div class="grid grid--2" style="gap:16px">
            ${COORD_FAMILIES.map(familyCard).join('')}
          </div>
        </div>
      </div>
    `;
  }

  function openConfigModal() {
    const existing = document.querySelector('[data-coord-config-modal]');
    if (existing) existing.remove();

    const div = document.createElement('div');
    div.setAttribute('data-coord-config-modal', '');
    div.style.cssText = 'position:fixed;inset:0;background:rgba(9,9,14,0.7);backdrop-filter:blur(6px);z-index:200;display:flex;align-items:center;justify-content:center';
    div.innerHTML = `
      <div style="background:var(--bg-2);border:1px solid var(--border);border-radius:var(--r-xl);width:460px;max-width:92vw;box-shadow:var(--shadow-lg);overflow:hidden" onclick="event.stopPropagation()">
        <div style="padding:24px 28px;border-bottom:1px solid var(--border-subtle);display:flex;align-items:center;justify-content:space-between">
          <div>
            <h3 style="font-size:17px">Coordination engine</h3>
            <div style="color:var(--text-2);font-size:12.5px;margin-top:3px">Configure global coordination parameters.</div>
          </div>
          <button style="display:grid;place-items:center;width:32px;height:32px;border-radius:var(--r-sm);color:var(--text-3);transition:background var(--dur)" data-close-config>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
          </button>
        </div>
        <div style="padding:24px 28px;display:flex;flex-direction:column;gap:16px">
          <div class="field">
            <label>Max agents</label>
            <input class="input" type="number" id="coord-max-agents" value="100" min="1" max="1000" />
          </div>
          <div class="field">
            <label>Default algorithm</label>
            <select class="input" id="coord-algorithm" style="height:36px;padding:0 12px">
              <option value="CNP">CNP — Contract Net Protocol</option>
              <option value="DPOP">DPOP — Distributed Pseudo-tree Opt.</option>
              <option value="GA">GA — Genetic Algorithm (NSGA-II)</option>
              <option value="MAPPO">MAPPO — Multi-Agent PPO</option>
            </select>
          </div>
          <div class="field">
            <label>Timeout <span style="color:var(--text-3);font-weight:400;font-size:11.5px">(seconds)</span></label>
            <input class="input" type="number" id="coord-timeout" value="300" min="1" max="3600" />
          </div>
        </div>
        <div style="padding:16px 28px;border-top:1px solid var(--border-subtle);display:flex;gap:8px;justify-content:flex-end">
          <button class="btn btn--ghost" data-close-config>Cancel</button>
          <button class="btn btn--primary" data-apply-config>${icons.check ? icons.check(13) : ''} Apply</button>
        </div>
      </div>
    `;
    document.body.appendChild(div);

    // Close handlers
    div.addEventListener('click', (e) => { if (e.target === div) div.remove(); });
    div.querySelectorAll('[data-close-config]').forEach(btn => {
      btn.addEventListener('click', () => div.remove());
    });

    // Apply handler
    div.querySelector('[data-apply-config]').addEventListener('click', () => {
      div.remove();
      window.Orchestra.toast('Configuration applied', 'success');
    });
  }

  function mount(root) {
    root.innerHTML = render();

    // Wire Configure button
    root.querySelector('[data-action="open-config"]')?.addEventListener('click', openConfigModal);
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.pages = window.Orchestra.pages || {};
  // Register action via global delegation (survives re-renders)
  window.Orchestra = window.Orchestra || {};
  window.Orchestra._actionHandlers = window.Orchestra._actionHandlers || {};
  window.Orchestra._actionHandlers['open-config'] = openConfigModal;

  window.Orchestra.pages = window.Orchestra.pages || {};
  window.Orchestra.pages.coordination = { mount };
})();
