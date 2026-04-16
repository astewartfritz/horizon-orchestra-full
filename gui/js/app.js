// Orchestra — App entry, router
(function () {
  const routes = {
    '#/':         'home',
    '':           'home',
    '#/chat':     'chat',
    '#/tasks':    'tasks',
    '#/agents':   'agents',
    '#/coord':    'agents',    // maps to agents view for now
    '#/tools':    'agents',
    '#/settings': 'settings',
  };

  function routeKey(hash) {
    // strip query
    const bare = (hash || '').split('?')[0];
    return routes[bare] !== undefined ? routes[bare] : 'home';
  }

  let currentPage = null;
  function go() {
    // Unmount previous page
    if (currentPage && window.Orchestra.pages[currentPage]?.unmount) {
      window.Orchestra.pages[currentPage].unmount();
    }

    const hash = location.hash || '#/';
    const key = routeKey(hash);
    currentPage = key;

    // Close mobile sidebar on route
    document.querySelector('.app')?.classList.remove('mobile-open');

    const root = document.querySelector('.page-root');
    if (!root) return;
    // fresh element for animation
    root.innerHTML = '';
    const page = window.Orchestra.pages[key];
    if (page && page.mount) {
      page.mount(root);
    } else {
      root.innerHTML = `<div class="page"><div class="page__inner"><h1>Not found</h1></div></div>`;
    }

    // Update sidebar and topbar
    const bare = hash.split('?')[0];
    window.Orchestra.sidebar.setActive(bare);
    window.Orchestra.topbar.setTitle(bare);
  }

  function init() {
    // Paint shell
    window.Orchestra.sidebar.render();
    window.Orchestra.topbar.render();

    // Mobile overlay
    const overlay = document.createElement('div');
    overlay.className = 'mobile-overlay';
    overlay.addEventListener('click', () => document.querySelector('.app').classList.remove('mobile-open'));
    document.querySelector('.app').appendChild(overlay);

    // Initial route
    go();

    // Hash changes
    window.addEventListener('hashchange', go);

    // Global ⌘K to focus search
    window.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        const input = document.querySelector('.topbar__search input');
        if (input) input.focus();
      }
      if (e.key === 'Escape') {
        document.querySelectorAll('.detail-panel.is-open').forEach(p => p.classList.remove('is-open'));
        document.querySelectorAll('.detail-overlay.is-open').forEach(p => p.classList.remove('is-open'));
      }
    });
  }

  document.addEventListener('DOMContentLoaded', init);
})();
