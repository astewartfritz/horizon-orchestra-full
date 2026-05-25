// Orchestra — Top bar (with live notification polling)
(function () {
  const { icons } = window;
  const API = window.ORCH_API || 'http://localhost:3000';

  let notifCount = 0;
  let lastSeen = Date.now() / 1000 - 1;
  const notifHistory = [];
  let notifOpen = false;
  let pollInterval = null;

  const pageTitles = {
    '#/':         { parent: 'Workspace', current: 'Home' },
    '#/chat':     { parent: 'Workspace', current: 'Chat' },
    '#/tasks':    { parent: 'Workspace', current: 'Tasks' },
    '#/agents':   { parent: 'Intelligence', current: 'Agents' },
    '#/coord':    { parent: 'Intelligence', current: 'Coordination' },
    '#/tools':    { parent: 'Intelligence', current: 'Tools' },
    '#/terminal': { parent: 'System', current: 'Terminal' },
    '#/settings': { parent: 'System', current: 'Settings' },
  };

  function badgeAttr() {
    return notifCount > 0 ? `data-badge="${Math.min(notifCount, 99)}" class="icon-btn has-badge"` : 'class="icon-btn"';
  }

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
        <div style="position:relative">
          <button ${badgeAttr()} data-notif-bell aria-label="Notifications">${icons.bell(18)}</button>
          <div class="notif-dropdown${notifOpen ? ' is-open' : ''}" id="notif-dropdown">
            ${renderNotifDropdown()}
          </div>
        </div>
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
    el.querySelector('[data-notif-bell]').addEventListener('click', (e) => {
      e.stopPropagation();
      notifOpen = !notifOpen;
      if (notifOpen) {
        notifCount = 0;
        updateBadge();
      }
      const dd = document.getElementById('notif-dropdown');
      if (dd) {
        dd.classList.toggle('is-open', notifOpen);
        dd.innerHTML = renderNotifDropdown();
        wireNotifDropdown(dd);
      }
    });
    document.addEventListener('click', () => {
      if (notifOpen) {
        notifOpen = false;
        const dd = document.getElementById('notif-dropdown');
        if (dd) dd.classList.remove('is-open');
      }
    });
  }

  function renderNotifDropdown() {
    if (notifHistory.length === 0) {
      return `
        <div class="notif-dropdown__header">Notifications</div>
        <div class="notif-dropdown__empty">No recent notifications.</div>
      `;
    }
    return `
      <div class="notif-dropdown__header">
        <span>Notifications</span>
        <button class="btn btn--subtle btn--sm" data-action="clear-notifs">Clear</button>
      </div>
      <div class="notif-dropdown__list">
        ${notifHistory.slice(0, 15).map(n => `
          <div class="notif-item ${n.status === 'failed' ? 'notif-item--error' : ''}">
            <div class="notif-item__icon">${n.status === 'complete' ? '✓' : '✗'}</div>
            <div class="notif-item__body">
              <div class="notif-item__title">${escapeHTML(n.title || 'Task update')}</div>
              <div class="notif-item__body-text">${escapeHTML((n.body || '').slice(0, 70))}</div>
              ${n.duration ? `<div class="notif-item__meta">${n.duration}s</div>` : ''}
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }

  function wireNotifDropdown(dd) {
    const clearBtn = dd.querySelector('[data-action="clear-notifs"]');
    if (clearBtn) {
      clearBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        notifHistory.length = 0;
        notifCount = 0;
        updateBadge();
        dd.innerHTML = renderNotifDropdown();
      });
    }
  }

  function escapeHTML(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function updateBadge() {
    const bell = document.querySelector('[data-notif-bell]');
    if (!bell) return;
    if (notifCount > 0) {
      bell.setAttribute('data-badge', Math.min(notifCount, 99));
      bell.classList.add('has-badge');
    } else {
      bell.removeAttribute('data-badge');
      bell.classList.remove('has-badge');
    }
  }

  async function pollNotifications() {
    try {
      const r = await fetch(`${API}/v1/notifications?user_id=default&since=${lastSeen}`, { signal: AbortSignal.timeout(5000) });
      if (!r.ok) return;
      const items = await r.json();
      if (!Array.isArray(items) || items.length === 0) return;

      items.forEach(n => {
        notifHistory.unshift(n);
        notifCount++;
        lastSeen = Math.max(lastSeen, n.completed_at || lastSeen);

        if (window.Orchestra?.toast) {
          const isOk = n.status === 'complete';
          window.Orchestra.toast.show(
            isOk ? `Done: ${(n.body || '').slice(0, 60)}` : `Failed: ${(n.body || '').slice(0, 60)}`,
            isOk ? 'success' : 'error',
            5000
          );
        }
        if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
          try {
            new Notification('Orchestra — ' + (n.status === 'complete' ? 'Task complete' : 'Task failed'), {
              body: (n.body || '').slice(0, 100),
            });
          } catch(e) {}
        }
      });
      notifHistory.splice(20);
      updateBadge();
    } catch (e) {}
  }

  function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    setTimeout(pollNotifications, 5000);
    pollInterval = setInterval(pollNotifications, 15000);
  }

  function stopPolling() {
    if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
  }

  function setTitle(hash) {
    const info = pageTitles[hash] || pageTitles['#/'];
    const parent = document.querySelector('[data-topbar-parent]');
    const current = document.querySelector('[data-topbar-current]');
    if (parent) parent.textContent = info.parent;
    if (current) current.textContent = info.current;
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.topbar = { render, setTitle, startPolling, stopPolling };
})();
