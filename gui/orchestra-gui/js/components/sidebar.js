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
    {
      id: 'verticals', label: 'Verticals', icon: 'verticals', expand: true,
      children: [
        { id: 'v-healthcare', label: 'Healthcare', color: '#F0596A', href: '#/verticals?v=healthcare' },
        { id: 'v-legal',      label: 'Legal',       color: '#8282F7', href: '#/verticals?v=legal' },
        { id: 'v-financial',  label: 'Financial',   color: '#34D399', href: '#/verticals?v=financial' },
      ],
    },
    { id: 'coord',    label: 'Coordination',icon: 'coord',    href: '#/coord' },
    { id: 'tools',    label: 'Tools',       icon: 'tools',    href: '#/tools' },
    { group: 'Communications' },
    { id: 'mail',     label: 'Horizon Mail', icon: 'mail',    href: '#/mail' },
    { group: 'System' },
    { id: 'terminal', label: 'Terminal',    icon: 'terminal', href: '#/terminal' },
    { id: 'settings', label: 'Settings',    icon: 'settings', href: '#/settings' },
  ];

  const expandState = {};

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
          if (item.expand) {
            const open = !!expandState[item.id];
            return `
              <div class="nav-expand-wrap">
                <div class="nav-item nav-expand ${open ? 'is-open' : ''}" data-expand="${item.id}" data-nav="${item.id}">
                  <span class="icon">${icons[item.icon] ? icons[item.icon](18) : ''}</span>
                  <span class="label">${item.label}</span>
                  <span class="nav-expand__chevron">${icons.chevronRight ? icons.chevronRight(11) : '›'}</span>
                </div>
                <div class="nav-sub ${open ? 'is-open' : ''}" id="nav-sub-${item.id}">
                  ${(item.children || []).map(c => `
                    <a class="nav-item nav-sub-item" href="${c.href}" data-nav="${c.id}">
                      <span class="nav-sub-dot" style="color:${c.color}">●</span>
                      <span class="label">${c.label}</span>
                    </a>`).join('')}
                </div>
              </div>`;
          }
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

    // Wire expandable nav items
    el.querySelectorAll('[data-expand]').forEach(trigger => {
      trigger.addEventListener('click', (e) => {
        e.preventDefault();
        const key = trigger.dataset.expand;
        expandState[key] = !expandState[key];
        trigger.classList.toggle('is-open', expandState[key]);
        const sub = document.getElementById(`nav-sub-${key}`);
        if (sub) sub.classList.toggle('is-open', expandState[key]);
      });
    });

    // Wire MILES button → dedicated MILES page
    el.querySelector('[data-action="open-miles"]').addEventListener('click', () => {
      location.hash = '#/miles';
    });
  }

  function setActiveNav(path) {
    let key = (path || '').replace(/^#\//, '').split(/[?&]/)[0] || 'home';
    if (key === '') key = 'home';
    const vParam = (path || '').match(/[?&]v=([^&]+)/)?.[1];
    const childKey = vParam ? `v-${vParam}` : null;

    document.querySelectorAll('.nav-item').forEach(el => {
      const isChild = el.classList.contains('nav-sub-item');
      if (isChild) {
        el.classList.toggle('is-active', el.dataset.nav === childKey);
      } else {
        el.classList.toggle('is-active', el.dataset.nav === key);
      }
    });

    // Auto-open parent expand when a child is active
    if (childKey && key === 'verticals') {
      expandState['verticals'] = true;
      const trigger = document.querySelector('[data-expand="verticals"]');
      const sub = document.getElementById('nav-sub-verticals');
      if (trigger) trigger.classList.add('is-open');
      if (sub) sub.classList.add('is-open');
    }

    const milesBtn = document.querySelector('[data-action="open-miles"]');
    if (milesBtn) milesBtn.classList.toggle('is-active', key === 'miles');
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.sidebar = { render: renderSidebar, setActive: setActiveNav };
})();
