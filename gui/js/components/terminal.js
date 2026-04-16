// Orchestra — Terminal output block
(function () {
  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function render({ title = 'orchestra', lines = [], running = false }) {
    const body = lines.map(l => {
      const kind = l.kind || 'out';
      return `<span class="term__line ${kind}">${escapeHTML(l.text)}</span>`;
    }).join('\n');

    return `
      <div class="term">
        <div class="term__head">
          <div class="term__dots"><span></span><span></span><span></span></div>
          <span class="term__title">${escapeHTML(title)}</span>
        </div>
        <div class="term__body">${body}${running ? '<span class="term__cursor"></span>' : ''}</div>
      </div>
    `;
  }

  // Live append a line and autoscroll.
  function append(containerEl, { kind = 'out', text = '' }) {
    const body = containerEl.querySelector('.term__body');
    if (!body) return;
    const cursor = body.querySelector('.term__cursor');
    const span = document.createElement('span');
    span.className = `term__line ${kind}`;
    span.textContent = text;
    if (cursor) {
      body.insertBefore(document.createTextNode('\n'), cursor);
      body.insertBefore(span, cursor);
    } else {
      body.appendChild(document.createTextNode('\n'));
      body.appendChild(span);
    }
    body.scrollTop = body.scrollHeight;
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.terminal = { render, append };
})();
