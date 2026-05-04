// Orchestra — Animated checklist
(function () {
  const { icons } = window;

  function iconFor(status) {
    if (status === 'done') return icons.check(10);
    return '';
  }

  function renderItem(item) {
    const cls = `check check--${item.status}`;
    return `
      <li class="${cls}" data-status="${item.status}">
        <span class="check__box">${iconFor(item.status)}</span>
        <span class="check__label">${escapeHTML(item.text)}</span>
        ${item.meta ? `<span class="check__meta">${escapeHTML(item.meta)}</span>` : ''}
      </li>
    `;
  }

  function render({ title = 'Plan', items = [] }) {
    return `
      <div class="checklist">
        <div class="checklist__head">
          ${icons.flag(12)}
          <span>${escapeHTML(title)}</span>
        </div>
        <ul style="list-style:none; padding:0; margin:0;">
          ${items.map(renderItem).join('')}
        </ul>
      </div>
    `;
  }

  // Animate transitions: pending -> working -> done with stagger.
  // Accepts container element that contains <li class="check">.
  function animate(containerEl, items, opts = {}) {
    const stepMs = opts.stepMs || 850;
    const lis = containerEl.querySelectorAll('.check');
    lis.forEach((li, i) => {
      // Staggered fade-in already via CSS anim. Here we advance statuses over time.
      const target = items[i];
      if (!target) return;
      if (target.status !== 'pending') return; // initial state already set
      // For items that start "pending", leave them; no auto-advance.
    });
  }

  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.checklist = { render, animate };
})();
