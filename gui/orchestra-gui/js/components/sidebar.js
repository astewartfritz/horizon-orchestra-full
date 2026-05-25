// Orchestra — Sidebar
(function () {
  const { icons } = window;

  const navItems = [
    { group: 'Workspace' },
    { id: 'home',     label: 'Home',        icon: 'home',     href: '#/' },
    { id: 'chat',     label: 'Chat',        icon: 'chat',     href: '#/chat', badge: '3' },
    { id: 'tasks',    label: 'Tasks',       icon: 'tasks',    href: '#/tasks', badge: '3' },
    { group: 'Intelligence' },
    { id: 'agents',   label: 'Agents',      icon: 'agents',   href: '#/agents' },
    { id: 'verticals',label: 'Verticals',   icon: 'verticals',href: '#/verticals' },
    { id: 'coord',    label: 'Coordination',icon: 'coord',    href: '#/coord' },
    { id: 'tools',    label: 'Tools',       icon: 'tools',    href: '#/tools' },
    { group: 'System' },
    { id: 'terminal', label: 'Terminal',    icon: 'terminal', href: '#/terminal' },
    { id: 'settings', label: 'Settings',    icon: 'settings', href: '#/settings' },
  ];

  function renderSidebar() {
    const el = document.querySelector('.sidebar');
    if (!el) return;

    el.innerHTML = `
      <div class="sidebar__brand">
        <div class="logo">${icons.logo(28)}</div>
        <div class="name">Orchestra</div>
      </div>

      <div class="sidebar__miles" data-action="open-miles">
        <div class="miles-icon">${icons.miles(18)}</div>
        <div class="miles-text">
          <div class="miles-title">MILES AI</div>
          <div class="miles-sub">Ask anything · ⌘M</div>
        </div>
      </div>

      <nav class="sidebar__nav">
        ${navItems.map(item => {
          if (item.group) return `<div class="sidebar__group">${item.group}</div>`;
          return `
            <a class="nav-item" href="${item.href}" data-nav="${item.id}">
              <span class="icon">${icons[item.icon](18)}</span>
              <span class="label">${item.label}</span>
              ${item.badge ? `<span class="nav-badge">${item.badge}</span>` : ''}
            </a>`;
        }).join('')}
      </nav>

      <div class="sidebar__footer">
        <div class="sidebar__user">
          <div class="avatar">${MOCK.user.initials}</div>
          <div class="meta">
            <div class="name">${MOCK.user.name.split(' ')[0]} ${MOCK.user.name.split(' ')[1][0]}.</div>
            <div class="plan">${MOCK.user.plan.split(' — ')[0]} plan</div>
          </div>
        </div>
        <button class="sidebar__collapse" data-action="toggle-sidebar" aria-label="Collapse sidebar">
          ${icons.collapse(14)}
        </button>
      </div>
    `;

    // Wire collapse toggle
    el.querySelector('[data-action="toggle-sidebar"]').addEventListener('click', () => {
      document.querySelector('.app').classList.toggle('collapsed');
    });

    // Wire MILES button → dedicated MILES page
    el.querySelector('[data-action="open-miles"]').addEventListener('click', () => {
      location.hash = '#/miles';
    });
  }

  function setActiveNav(path) {
    // normalize: '#/chat' -> 'chat', '' or '#/' -> 'home'
    let key = (path || '').replace(/^#\//, '').split(/[?&]/)[0] || 'home';
    if (key === '') key = 'home';
    // map aliases
    const aliasMap = { 'coord': 'coord', 'tools': 'tools', 'verticals': 'verticals' };
    if (aliasMap[key]) key = aliasMap[key];
    document.querySelectorAll('.nav-item').forEach(el => {
      el.classList.toggle('is-active', el.dataset.nav === key);
    });
    // Highlight the MILES button when on the MILES page
    const milesBtn = document.querySelector('[data-action="open-miles"]');
    if (milesBtn) milesBtn.classList.toggle('is-active', key === 'miles');
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.sidebar = { render: renderSidebar, setActive: setActiveNav };
})();
