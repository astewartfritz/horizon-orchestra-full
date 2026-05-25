// Orchestra — App entry, router, global infrastructure
(function () {
  // ── API base ──────────────────────────────────────────────────────────────
  // Override by setting window.ORCH_API before this script loads.
  window.ORCH_API = window.ORCH_API || 'http://localhost:3000';

  // ── Toast system ──────────────────────────────────────────────────────────
  (function buildToast() {
    const container = document.getElementById('toast-container');
    if (!container) return;

    function show(message, type = 'info', duration = 4000) {
      const el = document.createElement('div');
      el.className = `toast toast--${type}`;
      const icons = { success: '✓', error: '✗', info: 'ℹ', warn: '!' };
      el.innerHTML = `
        <span class="toast__icon">${icons[type] || 'ℹ'}</span>
        <span class="toast__msg">${String(message).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</span>
        <button class="toast__close" aria-label="Dismiss">×</button>
      `;
      el.querySelector('.toast__close').addEventListener('click', () => dismiss(el));
      container.appendChild(el);
      requestAnimationFrame(() => el.classList.add('toast--visible'));
      if (duration > 0) setTimeout(() => dismiss(el), duration);
    }

    function dismiss(el) {
      el.classList.remove('toast--visible');
      setTimeout(() => el.remove(), 280);
    }

    window.Orchestra = window.Orchestra || {};
    window.Orchestra.toast = { show };
  })();

  // ── Router ────────────────────────────────────────────────────────────────
  const routes = {
    '#/':          'chat',
    '':            'chat',
    '#/home':      'home',
    '#/chat':      'chat',
    '#/tasks':     'tasks',
    '#/agents':    'agents',
    '#/coord':     'agents',
    '#/tools':     'agents',
    '#/terminal':  'terminal',
    '#/settings':  'settings',
  };

  function routeKey(hash) {
    const bare = (hash || '').split('?')[0];
    return routes[bare] !== undefined ? routes[bare] : 'home';
  }

  let currentPage = null;
  function go() {
    if (currentPage && window.Orchestra.pages[currentPage]?.unmount) {
      window.Orchestra.pages[currentPage].unmount();
    }

    const hash = location.hash || '#/';
    const key = routeKey(hash);
    currentPage = key;

    document.querySelector('.app')?.classList.remove('mobile-open');

    const root = document.querySelector('.page-root');
    if (!root) return;
    root.innerHTML = '';
    const page = window.Orchestra.pages[key];
    if (page && page.mount) {
      page.mount(root);
    } else {
      root.innerHTML = `<div class="page"><div class="page__inner"><h1>Not found</h1></div></div>`;
    }

    const bare = hash.split('?')[0];
    window.Orchestra.sidebar.setActive(bare);
    window.Orchestra.topbar.setTitle(bare);
  }

  function init() {
    window.Orchestra.sidebar.render();
    window.Orchestra.topbar.render();

    // Mobile overlay
    const overlay = document.createElement('div');
    overlay.className = 'mobile-overlay';
    overlay.addEventListener('click', () => document.querySelector('.app').classList.remove('mobile-open'));
    document.querySelector('.app').appendChild(overlay);

    // Initial route
    go();
    window.addEventListener('hashchange', go);

    // Global hotkeys
    window.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        const input = document.querySelector('.topbar__search input');
        if (input) input.focus();
      }
      if (e.key === 'Escape') {
        document.querySelectorAll('.detail-panel.is-open').forEach(p => p.classList.remove('is-open'));
        document.querySelectorAll('.detail-overlay.is-open').forEach(p => p.classList.remove('is-open'));
        // Close onboarding on Escape
        const ob = document.getElementById('onboarding-overlay');
        if (ob && ob.classList.contains('is-open')) ob.classList.remove('is-open');
      }
    });

    // Start notification polling
    if (window.Orchestra.topbar?.startPolling) {
      window.Orchestra.topbar.startPolling();
    }

    // Request browser notification permission (non-blocking)
    if ('Notification' in window && Notification.permission === 'default') {
      setTimeout(() => Notification.requestPermission(), 3000);
    }

    // Show onboarding for first-time visitors
    if (window.Orchestra.onboarding?.check) {
      setTimeout(() => window.Orchestra.onboarding.check(), 800);
    }
  }

  document.addEventListener('DOMContentLoaded', init);
})();
