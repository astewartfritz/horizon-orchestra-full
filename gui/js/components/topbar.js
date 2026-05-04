// Orchestra — Top bar
(function () {
  const { icons } = window;

  const pageTitles = {
    '#/':         { parent: 'Workspace', current: 'Home' },
    '#/chat':     { parent: 'Workspace', current: 'Chat' },
    '#/tasks':    { parent: 'Workspace', current: 'Tasks' },
    '#/agents':   { parent: 'Intelligence', current: 'Agents' },
    '#/coord':    { parent: 'Intelligence', current: 'Coordination' },
    '#/tools':    { parent: 'Intelligence', current: 'Tools' },
    '#/settings': { parent: 'System', current: 'Settings' },
  };

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

      <div class="topbar__right">
        <button class="icon-btn" aria-label="New task" title="New task">${icons.plus(16)}</button>
        <button class="icon-btn has-badge" data-badge="4" aria-label="Notifications">${icons.bell(18)}</button>
        <button class="icon-btn" aria-label="Settings" title="Settings" data-goto="#/settings">${icons.settings(17)}</button>
        <button class="avatar" aria-label="Account">${MOCK.user.initials}</button>
      </div>
    `;

    el.querySelector('[data-action="mobile-open"]').addEventListener('click', () => {
      document.querySelector('.app').classList.add('mobile-open');
    });
    el.querySelector('[data-goto="#/settings"]').addEventListener('click', () => {
      location.hash = '#/settings';
    });
  }

  function setTitle(hash) {
    const info = pageTitles[hash] || pageTitles['#/'];
    const parent = document.querySelector('[data-topbar-parent]');
    const current = document.querySelector('[data-topbar-current]');
    if (parent) parent.textContent = info.parent;
    if (current) current.textContent = info.current;
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.topbar = { render, setTitle };
})();
