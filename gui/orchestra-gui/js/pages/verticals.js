// Orchestra — Verticals page
(function () {
  const { icons } = window;

  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  const VERTICALS = [
    {
      id: 'healthcare',
      name: 'Healthcare',
      agents: 5,
      tools: 75,
      color: '#F0596A',
      icon: 'medical',
      desc: 'Oncology routing, genomics pipelines, medication safety, and clinic scheduling.',
    },
    {
      id: 'legal',
      name: 'Legal',
      agents: 4,
      tools: 59,
      color: '#8282F7',
      icon: 'gavel',
      desc: 'Contract review, compliance mapping, case briefing, and regulatory gap analysis.',
    },
    {
      id: 'logistics',
      name: 'Logistics',
      agents: 5,
      tools: 70,
      color: '#00C9B8',
      icon: 'truck',
      desc: 'Multi-stop route optimization, inventory monitoring, and dispatch management.',
    },
    {
      id: 'financial',
      name: 'Financial Services',
      agents: 3,
      tools: 35,
      color: '#34D399',
      icon: 'wallet',
      desc: 'Monte Carlo risk models, bank reconciliation, and AML/KYC screening.',
    },
    {
      id: 'manufact',
      name: 'Manufacturing',
      agents: 3,
      tools: 30,
      color: '#F5B971',
      icon: 'factory',
      desc: 'Digital twin simulations, defect detection, and SPC-based quality control.',
    },
    {
      id: 'retail',
      name: 'Retail',
      agents: 3,
      tools: 28,
      color: '#C792EA',
      icon: 'shop',
      desc: 'Assortment planning, markdown optimization, and voice-of-customer extraction.',
    },
    {
      id: 'energy',
      name: 'Energy',
      agents: 3,
      tools: 25,
      color: '#F5B971',
      icon: 'bolt',
      desc: 'Load forecasting, emissions anomaly detection, and grid outage correlation.',
    },
    {
      id: 'realestate',
      name: 'Real Estate',
      agents: 2,
      tools: 15,
      color: '#89DDFF',
      icon: 'building',
      desc: 'Automated valuation models, cap-rate analysis, and CRE deal pipeline tracking.',
    },
    {
      id: 'nursing',
      name: 'Nursing',
      agents: 6,
      tools: 32,
      color: '#F0596A',
      icon: 'nursing',
      desc: 'Acuity-based shift scheduling, vitals monitoring, and RRT escalation triggers.',
    },
  ];

  function hexToAlpha(hex, alpha) {
    const r = parseInt(hex.slice(1,3), 16);
    const g = parseInt(hex.slice(3,5), 16);
    const b = parseInt(hex.slice(5,7), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }

  function verticalCard(v) {
    return `
      <div class="card card--hover" data-vertical-nav="${v.id}" style="cursor:pointer;padding:24px;position:relative;overflow:hidden">
        <div style="position:absolute;top:-30px;right:-30px;width:120px;height:120px;border-radius:999px;background:radial-gradient(circle,${hexToAlpha(v.color,0.12)},transparent 70%);pointer-events:none"></div>
        <div style="display:flex;align-items:flex-start;gap:16px;margin-bottom:16px">
          <div style="width:44px;height:44px;border-radius:var(--r);background:${hexToAlpha(v.color,0.15)};color:${v.color};display:grid;place-items:center;flex-shrink:0">
            ${icons[v.icon] ? icons[v.icon](20) : icons.sparkles(20)}
          </div>
          <div style="flex:1;min-width:0">
            <div style="font-size:16px;font-weight:600;letter-spacing:-0.01em;margin-bottom:2px">${escapeHTML(v.name)}</div>
            <div style="display:flex;gap:12px;font-size:11.5px;color:var(--text-3)">
              <span style="color:${v.color};font-weight:500">${v.agents} agents</span>
              <span>·</span>
              <span>${v.tools} tools</span>
            </div>
          </div>
        </div>
        <p style="font-size:13px;color:var(--text-2);line-height:1.55;margin-bottom:16px">${escapeHTML(v.desc)}</p>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <div style="display:flex;gap:4px">
            ${Array.from({length: v.agents}, (_, i) => `
              <div style="width:20px;height:20px;border-radius:999px;background:${hexToAlpha(v.color,0.2)};border:1.5px solid ${hexToAlpha(v.color,0.4)};display:grid;place-items:center;font-size:9px;color:${v.color}">
                ${icons.agents ? icons.agents(9) : ''}
              </div>`).join('')}
          </div>
          <span style="font-size:12px;color:var(--text-3);display:flex;align-items:center;gap:4px">
            View agents ${icons.chevronRight(12)}
          </span>
        </div>
      </div>
    `;
  }

  function render() {
    const totalAgents = VERTICALS.reduce((s, v) => s + v.agents, 0);
    const totalTools  = VERTICALS.reduce((s, v) => s + v.tools, 0);

    return `
      <div class="page page--verticals">
        <div class="page__inner" style="max-width:1200px">
          <div class="page-header">
            <div>
              <h1>Verticals</h1>
              <div class="sub">${VERTICALS.length} industry verticals · ${totalAgents} agents · ${totalTools} tools</div>
            </div>
            <div style="display:flex;gap:8px">
              <button class="btn btn--ghost">${icons.refresh(13)} Sync</button>
              <a class="btn btn--primary" href="#/agents">${icons.agents(13)} All agents</a>
            </div>
          </div>

          <div class="grid grid--3" style="gap:16px">
            ${VERTICALS.map(verticalCard).join('')}
          </div>
        </div>
      </div>
    `;
  }

  function mount(root) {
    root.innerHTML = render();

    root.querySelectorAll('[data-vertical-nav]').forEach(el => {
      el.addEventListener('click', () => {
        const v = el.dataset.verticalNav;
        location.hash = `#/agents?v=${v}`;
      });
    });
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.pages = window.Orchestra.pages || {};
  window.Orchestra.pages.verticals = { mount };
})();
