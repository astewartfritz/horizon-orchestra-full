// Orchestra — App entry, router
(function () {
  const routes = {
    '#/':           'home',
    '':             'home',
    '#/chat':       'chat',
    '#/tasks':      'tasks',
    '#/agents':     'agents',
    '#/verticals':  'verticals',
    '#/coord':      'coordination',
    '#/tools':      'tools',
    '#/settings':   'settings',
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

  // ─── Toast system ───────────────────────────────────────────────────
  let toastContainer = null;

  function showToast(message, type = 'info') {
    if (!toastContainer) {
      toastContainer = document.createElement('div');
      toastContainer.style.cssText = `
        position:fixed;bottom:24px;right:24px;z-index:9999;
        display:flex;flex-direction:column;gap:8px;pointer-events:none;
      `;
      document.body.appendChild(toastContainer);
    }

    const colors = {
      success: { bg: 'var(--success-dim)', border: 'rgba(52,211,153,0.25)', text: 'var(--success)', icon: '✓' },
      info:    { bg: 'var(--accent-dim)',   border: 'var(--accent-ring)',    text: 'var(--accent)',  icon: 'i' },
      warn:    { bg: 'var(--warn-dim)',     border: 'rgba(245,185,113,0.25)', text: 'var(--warn)',  icon: '!' },
      error:   { bg: 'var(--danger-dim)',   border: 'rgba(240,89,106,0.25)', text: 'var(--danger)', icon: '✗' },
    };
    const c = colors[type] || colors.info;

    const toast = document.createElement('div');
    toast.style.cssText = `
      display:flex;align-items:center;gap:10px;
      padding:12px 16px;
      background:var(--bg-2);
      border:1px solid ${c.border};
      border-radius:var(--r);
      box-shadow:var(--shadow-lg);
      font-size:13px;
      color:var(--text);
      min-width:260px;max-width:380px;
      pointer-events:auto;
      animation:toastIn 280ms var(--ease);
      opacity:1;transition:opacity 300ms,transform 300ms;
    `;
    toast.innerHTML = `
      <span style="width:20px;height:20px;border-radius:999px;background:${c.bg};color:${c.text};display:grid;place-items:center;font-size:11px;font-weight:700;flex-shrink:0">${c.icon}</span>
      <span style="flex:1">${message}</span>
      <button style="color:var(--text-3);flex-shrink:0;display:grid;place-items:center" data-dismiss-toast>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
      </button>
    `;

    toast.querySelector('[data-dismiss-toast]').addEventListener('click', () => dismiss(toast));
    toastContainer.appendChild(toast);

    const timer = setTimeout(() => dismiss(toast), 3000);
    function dismiss(t) {
      clearTimeout(timer);
      t.style.opacity = '0';
      t.style.transform = 'translateX(20px)';
      setTimeout(() => t.remove(), 300);
    }
  }

  // Inject toast animation keyframes
  const style = document.createElement('style');
  style.textContent = `
    @keyframes toastIn {
      from { opacity: 0; transform: translateX(20px); }
      to   { opacity: 1; transform: translateX(0); }
    }
    .composer__file-chip {
      display:inline-flex;align-items:center;gap:6px;
      padding:4px 10px;background:var(--accent-dim);color:var(--accent);
      border-radius:999px;font-size:12px;font-weight:500;
      border:1px solid var(--accent-ring);
    }
    .composer__chip-remove {
      display:inline-flex;align-items:center;justify-content:center;
      padding:2px;color:var(--accent);opacity:0.7;
    }
    .composer__chip-remove:hover { opacity:1; }
    .composer__chips {
      padding:6px 14px 0;
      display:flex;flex-wrap:wrap;gap:6px;
    }
    .composer__chip--active {
      background:var(--accent-dim) !important;
      color:var(--accent) !important;
      border-color:var(--accent-ring) !important;
    }
    .composer__tool-badge {
      display:inline-flex;align-items:center;
      padding:1px 6px;background:var(--accent);color:white;
      border-radius:999px;font-size:10px;font-weight:600;margin-left:2px;
    }
    .dropdown__menu--tools {
      max-height:260px;overflow-y:auto;
    }
    .dropdown__item--tool {
      display:flex;align-items:center;gap:10px;padding:8px 14px;cursor:pointer;
      font-size:13px;color:var(--text-2);transition:background var(--dur) var(--ease);
    }
    .dropdown__item--tool:hover { background:var(--bg-3);color:var(--text); }
    .dropdown__item--tool.is-selected { color:var(--text); }
    .activity__item--clickable:hover {
      background:var(--bg-2);
      border-radius:var(--r-sm);
      margin-left:-8px;margin-right:-8px;padding-left:8px;padding-right:8px;
    }
  `;
  document.head.appendChild(style);

  function init() {
    // Paint shell
    window.Orchestra.sidebar.render();
    window.Orchestra.topbar.render();

    // Expose toast globally
    window.Orchestra.toast = showToast;

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

  // ─── Global Event Delegation ──────────────────────────────────────────
  // Catches ALL button clicks with data-action attributes via delegation
  // This ensures handlers work even when DOM is re-rendered
  document.addEventListener('click', function(e) {
    const actionEl = e.target.closest('[data-action]');
    if (!actionEl) return;
    
    const action = actionEl.dataset.action;
    const handlers = window.Orchestra._actionHandlers || {};
    if (handlers[action]) {
      e.preventDefault();
      e.stopPropagation();
      handlers[action](e, actionEl);
    }
  });

  // Registry for action handlers
  window.Orchestra._actionHandlers = window.Orchestra._actionHandlers || {};
  
  window.Orchestra.registerAction = function(name, handler) {
    window.Orchestra._actionHandlers[name] = handler;
  };
