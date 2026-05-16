// Orchestra — Top bar
(function () {
  const { icons } = window;

  const pageTitles = {
    '#/':           { parent: 'Workspace',    current: 'Home' },
    '#/chat':       { parent: 'Workspace',    current: 'Chat' },
    '#/tasks':      { parent: 'Workspace',    current: 'Tasks' },
    '#/agents':     { parent: 'Intelligence', current: 'Agents' },
    '#/verticals':  { parent: 'Intelligence', current: 'Verticals' },
    '#/coord':      { parent: 'Intelligence', current: 'Coordination' },
    '#/tools':      { parent: 'Intelligence', current: 'Tools' },
    '#/settings':   { parent: 'System',       current: 'Settings' },
  };

  // BUG 4: Notification data
  const NOTIFICATIONS = [
    {
      icon: 'file',
      color: '#F5B971',
      text: 'ContractReview flagged 3 risks in NorthPeak MSA',
      time: '2m ago',
      href: '#/tasks',
    },
    {
      icon: 'beaker',
      color: '#00C9B8',
      text: 'AutoResearch swarm completed: 4 improvements found',
      time: '15m ago',
      href: '#/tasks',
    },
    {
      icon: 'shield',
      color: '#F0596A',
      text: 'NEWS2 Alert: Patient pt-0847 score ≥7 — RRT activated',
      time: '1h ago',
      href: '#/agents',
    },
    {
      icon: 'github',
      color: '#6E6EF5',
      text: 'GitHub push: commit abc1234 to main (14 files)',
      time: '3h ago',
      href: '#/tasks',
    },
  ];

  let notifOpen  = false;
  let avatarOpen = false;

  function render() {
    const el = document.querySelector('.topbar');
    if (!el) return;

    el.innerHTML = `
      <div class="topbar__left">
        <button class="icon-btn mobile-toggle" data-action="mobile-open" aria-label="Open menu">
          ${icons.menu(18)}
        </button>
        <div class="topbar__crumbs">
          <span class="parent">Orchestra</span>
          <span class="sep">/</span>
          <span class="parent" data-topbar-parent>Workspace</span>
          <span class="sep">/</span>
          <span class="current" data-topbar-current>Home</span>
        </div>
      </div>

      <div class="topbar__search">
        <span class="search-icon">${icons.search(15)}</span>
        <input type="text" placeholder="Search agents, tasks, docs…" aria-label="Search" />
        <span class="search-kbd">
          <span class="kbd">⌘</span>
          <span class="kbd">K</span>
        </span>
      </div>

      <div class="topbar__right" style="position:relative">
        <button class="icon-btn" aria-label="New task" title="New task">${icons.plus(16)}</button>

        <!-- BUG 4: Notification bell -->
        <div style="position:relative" data-notif-root>
          <button class="icon-btn has-badge" data-badge="4" aria-label="Notifications" data-action="toggle-notif">
            ${icons.bell(18)}
          </button>
          <!-- notification dropdown rendered dynamically -->
        </div>

        <button class="icon-btn" aria-label="Settings" title="Settings" data-goto="#/settings">${icons.settings(17)}</button>

        <!-- BUG 5: User avatar -->
        <div style="position:relative" data-avatar-root>
          <button class="avatar" aria-label="Account" data-action="toggle-avatar">${MOCK.user.initials}</button>
          <!-- avatar dropdown rendered dynamically -->
        </div>
      </div>
    `;

    el.querySelector('[data-action="mobile-open"]').addEventListener('click', () => {
      document.querySelector('.app').classList.add('mobile-open');
    });
    el.querySelector('[data-goto="#/settings"]').addEventListener('click', () => {
      location.hash = '#/settings';
    });

    // BUG 4: Wire notification bell
    el.querySelector('[data-action="toggle-notif"]').addEventListener('click', (e) => {
      e.stopPropagation();
      notifOpen = !notifOpen;
      avatarOpen = false;
      renderDropdowns();
    });

    // BUG 5: Wire avatar button
    el.querySelector('[data-action="toggle-avatar"]').addEventListener('click', (e) => {
      e.stopPropagation();
      avatarOpen = !avatarOpen;
      notifOpen = false;
      renderDropdowns();
    });

    // Close on outside click
    document.addEventListener('click', (e) => {
      if (!e.target.closest('[data-notif-root]') && !e.target.closest('[data-avatar-root]')) {
        if (notifOpen || avatarOpen) {
          notifOpen = false;
          avatarOpen = false;
          renderDropdowns();
        }
      }
    });
  }

  function renderDropdowns() {
    renderNotifDropdown();
    renderAvatarDropdown();
  }

  function renderNotifDropdown() {
    const root = document.querySelector('[data-notif-root]');
    if (!root) return;
    // Remove existing dropdown
    root.querySelector('.topbar-dropdown')?.remove();
    if (!notifOpen) return;

    const d = document.createElement('div');
    d.className = 'topbar-dropdown';
    d.style.cssText = `
      position:absolute;top:calc(100% + 8px);right:0;width:340px;
      background:var(--bg-2);border:1px solid var(--border);border-radius:var(--r-lg);
      box-shadow:var(--shadow-lg);z-index:300;overflow:hidden
    `;
    d.innerHTML = `
      <div style="padding:14px 16px 10px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border-subtle)">
        <div style="font-size:14px;font-weight:600">Notifications</div>
        <span class="badge badge--accent">${NOTIFICATIONS.length}</span>
      </div>
      ${NOTIFICATIONS.map((n, i) => `
        <div style="display:flex;gap:12px;align-items:flex-start;padding:12px 16px;cursor:pointer;transition:background var(--dur);border-bottom:${i < NOTIFICATIONS.length-1 ? '1px solid var(--border-subtle)' : 'none'}" class="notif-item" data-notif-href="${n.href}">
          <div style="width:30px;height:30px;border-radius:var(--r-sm);background:rgba(${hexColor(n.color)},0.14);color:${n.color};display:grid;place-items:center;flex-shrink:0;margin-top:1px">
            ${icons[n.icon] ? icons[n.icon](14) : icons.sparkles(14)}
          </div>
          <div style="flex:1;min-width:0">
            <div style="font-size:13px;color:var(--text);line-height:1.45;margin-bottom:3px">${escapeHTML(n.text)}</div>
            <div style="font-size:11px;color:var(--text-3)">${icons.clock(10)} ${escapeHTML(n.time)}</div>
          </div>
        </div>`).join('')}
      <div style="padding:10px 16px;border-top:1px solid var(--border-subtle)">
        <button style="font-size:12.5px;color:var(--text-2);cursor:pointer;width:100%;text-align:center;transition:color var(--dur)" data-mark-all-read>Mark all read</button>
      </div>
    `;
    root.appendChild(d);

    // Wire notification clicks
    d.querySelectorAll('.notif-item').forEach(item => {
      item.addEventListener('mouseenter', () => item.style.background = 'var(--bg-3)');
      item.addEventListener('mouseleave', () => item.style.background = '');
      item.addEventListener('click', () => {
        notifOpen = false;
        renderDropdowns();
        location.hash = item.dataset.notifHref;
      });
    });
    d.querySelector('[data-mark-all-read]')?.addEventListener('click', () => {
      notifOpen = false;
      renderDropdowns();
      window.Orchestra.toast('All notifications marked as read', 'success');
    });
  }

  function renderAvatarDropdown() {
    const root = document.querySelector('[data-avatar-root]');
    if (!root) return;
    root.querySelector('.topbar-dropdown')?.remove();
    if (!avatarOpen) return;

    const d = document.createElement('div');
    d.className = 'topbar-dropdown';
    d.style.cssText = `
      position:absolute;top:calc(100% + 8px);right:0;width:240px;
      background:var(--bg-2);border:1px solid var(--border);border-radius:var(--r-lg);
      box-shadow:var(--shadow-lg);z-index:300;overflow:hidden
    `;
    d.innerHTML = `
      <!-- User info -->
      <div style="padding:14px 16px;border-bottom:1px solid var(--border-subtle)">
        <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:2px">Ashton Fritz</div>
        <div style="font-size:12px;color:var(--text-3)">ashtonfritz3@gmail.com</div>
      </div>

      <!-- Menu items -->
      <div style="padding:6px">
        <button class="avatar-menu-item" data-goto="#/settings">
          ${icons.user(14)} Profile
        </button>
        <button class="avatar-menu-item" data-action="shortcuts">
          ${icons.command(14)} Keyboard Shortcuts
        </button>
        <button class="avatar-menu-item" style="justify-content:space-between">
          <span style="display:flex;align-items:center;gap:10px">${icons.sparkles(14)} Theme</span>
          <span class="badge badge--accent" style="height:18px;font-size:10px">Dark</span>
        </button>
        <div style="height:1px;background:var(--border-subtle);margin:6px 0"></div>
        <button class="avatar-menu-item" style="color:var(--danger)" data-action="signout">
          ${icons.logout(14)} Sign Out
        </button>
      </div>
    `;
    root.appendChild(d);

    // Add hover styles
    d.querySelectorAll('.avatar-menu-item').forEach(item => {
      item.style.cssText += `
        display:flex;align-items:center;gap:10px;width:100%;padding:8px 12px;
        border-radius:var(--r-sm);font-size:13px;color:var(--text-2);
        cursor:pointer;transition:background var(--dur) var(--ease),color var(--dur) var(--ease);
        background:none;border:none;text-align:left;
      `;
      item.addEventListener('mouseenter', () => { item.style.background = 'var(--bg-3)'; item.style.color = 'var(--text)'; });
      item.addEventListener('mouseleave', () => { item.style.background = ''; item.style.color = item.dataset.goto ? 'var(--text-2)' : (item.dataset.action === 'signout' ? 'var(--danger)' : 'var(--text-2)'); });
    });

    d.querySelector('[data-goto="#/settings"]')?.addEventListener('click', () => {
      avatarOpen = false;
      renderDropdowns();
      location.hash = '#/settings';
    });
    d.querySelector('[data-action="shortcuts"]')?.addEventListener('click', () => {
      avatarOpen = false;
      renderDropdowns();
      window.Orchestra.toast('Keyboard shortcuts: ⌘K search · ⇧Enter newline · Esc close panels', 'info');
    });
    d.querySelector('[data-action="signout"]')?.addEventListener('click', () => {
      avatarOpen = false;
      renderDropdowns();
      window.Orchestra.toast('Signed out (demo — no actual auth)', 'info');
    });
  }

  function hexColor(hex) {
    const r = parseInt(hex.slice(1,3), 16);
    const g = parseInt(hex.slice(3,5), 16);
    const b = parseInt(hex.slice(5,7), 16);
    return `${r},${g},${b}`;
  }

  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function setTitle(hash) {
    const bare = hash.split('?')[0];
    const info = pageTitles[bare] || pageTitles['#/'];
    const parent = document.querySelector('[data-topbar-parent]');
    const current = document.querySelector('[data-topbar-current]');
    if (parent) parent.textContent = info.parent;
    if (current) current.textContent = info.current;
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.topbar = { render, setTitle };
})();
