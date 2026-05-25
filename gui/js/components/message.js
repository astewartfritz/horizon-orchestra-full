// Orchestra — Chat message rendering (markdown + blocks)
(function () {
  const { icons } = window;

  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Minimal markdown renderer
  function renderMarkdown(md) {
    const lines = md.split('\n');
    let out = [];
    let i = 0;

    const inline = (s) => {
      s = escapeHTML(s);
      s = s.replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`);
      s = s.replace(/\*\*([^*]+)\*\*/g, (_, c) => `<strong>${c}</strong>`);
      s = s.replace(/(^|[\s(])\*([^*\n]+)\*/g, (m, pre, c) => `${pre}<em>${c}</em>`);
      s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, t, u) => `<a href="${u}" target="_blank" rel="noopener">${t}</a>`);
      return s;
    };

    // Fenced code blocks
    const processCodeBlock = () => {
      const match = /^```(\w*)/.exec(lines[i]);
      if (!match) return false;
      const lang = match[1] || 'text';
      i++;
      let code = [];
      while (i < lines.length && !lines[i].startsWith('```')) {
        code.push(lines[i]); i++;
      }
      i++; // consume closing ```
      const escaped = escapeHTML(code.join('\n'));
      out.push(`
        <div class="codeblock">
          <div class="codeblock__header">
            <span class="codeblock__lang">${escapeHTML(lang)}</span>
            <button class="codeblock__btn" data-action="copy">${icons.copy(12)} Copy</button>
          </div>
          <pre><code>${escaped}</code></pre>
        </div>`);
      return true;
    };

    while (i < lines.length) {
      const ln = lines[i];
      if (/^\s*$/.test(ln)) { i++; continue; }
      if (processCodeBlock()) continue;

      const h = /^(#{1,3})\s+(.*)$/.exec(ln);
      if (h) { out.push(`<h${h[1].length + 2}>${inline(h[2])}</h${h[1].length + 2}>`); i++; continue; }

      if (/^---+\s*$/.test(ln)) { out.push('<hr />'); i++; continue; }

      if (/^>\s?/.test(ln)) {
        let block = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) { block.push(lines[i].replace(/^>\s?/, '')); i++; }
        out.push(`<blockquote>${inline(block.join(' '))}</blockquote>`);
        continue;
      }
      if (/^\s*[-*]\s+/.test(ln)) {
        let items = [];
        while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
          items.push(`<li>${inline(lines[i].replace(/^\s*[-*]\s+/, ''))}</li>`); i++;
        }
        out.push(`<ul>${items.join('')}</ul>`);
        continue;
      }
      if (/^\s*\d+\.\s+/.test(ln)) {
        let items = [];
        while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
          items.push(`<li>${inline(lines[i].replace(/^\s*\d+\.\s+/, ''))}</li>`); i++;
        }
        out.push(`<ol>${items.join('')}</ol>`);
        continue;
      }

      let para = [ln]; i++;
      while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^(#{1,3}\s|>|\s*[-*]\s|\s*\d+\.\s|---+\s*$|```)/.test(lines[i])) {
        para.push(lines[i]); i++;
      }
      out.push(`<p>${inline(para.join(' '))}</p>`);
    }
    return out.join('\n');
  }

  function renderToolCalls(calls) {
    return `<div class="tool-calls">${
      calls.map(c => {
        const s = c.state || 'working';
        return `<div class="tool-call ${s === 'working' ? 'is-working' : s === 'error' ? 'is-error' : 'done'}">
          <span class="icon">${icons[c.icon] ? icons[c.icon](12) : icons.sparkles(12)}</span>
          <span>${escapeHTML(c.label)}</span>
        </div>`;
      }).join('')
    }</div>`;
  }

  function renderThinking(text) {
    return `
      <div class="thinking">
        <span class="thinking__dots"><span></span><span></span><span></span></span>
        <span>${escapeHTML(text || 'Thinking')}</span>
      </div>
    `;
  }

  function renderError(b) {
    const actionHtml = b.action
      ? `<a href="${escapeHTML(b.action.href)}" class="btn btn--ghost btn--sm error-block__action">${escapeHTML(b.action.label)}</a>`
      : '';
    const retryHtml = b.retry
      ? `<button class="btn btn--ghost btn--sm error-block__action" data-retry="${escapeHTML(b.retry)}">Retry</button>`
      : '';
    return `
      <div class="error-block">
        <div class="error-block__icon">
          <svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
            <path d="M7.5 1.5L13.5 12H1.5L7.5 1.5Z"/>
            <path d="M7.5 5.5V8.5"/>
            <circle cx="7.5" cy="10.5" r=".5" fill="currentColor"/>
          </svg>
        </div>
        <div class="error-block__body">
          <div class="error-block__title">${escapeHTML(b.title || 'Error')}</div>
          <div class="error-block__hint">${escapeHTML(b.hint || '')}</div>
          ${(actionHtml || retryHtml) ? `<div class="error-block__actions">${actionHtml}${retryHtml}</div>` : ''}
        </div>
      </div>
    `;
  }

  function renderMessage(m, idx) {
    const isUser = m.role === 'user';
    const time = m.time || '';

    if (isUser) {
      return `
        <div class="msg msg--user" data-msg-idx="${idx !== undefined ? idx : ''}">
          <div class="msg__body">
            <div class="bubble">${escapeHTML(m.text)}</div>
            <div class="msg__meta">
              <span>You</span>
              <span>·</span>
              <span>${escapeHTML(time)}</span>
            </div>
          </div>
        </div>`;
    }

    const blocks = (m.blocks || [{ type: 'md', content: m.text || '' }]).map(b => {
      if (b.type === 'md')       return `<div class="md">${renderMarkdown(b.content)}</div>`;
      if (b.type === 'code')     return window.Orchestra.codediff.renderCodeBlock({ code: b.code, lang: b.lang, title: b.title });
      if (b.type === 'diff')     return window.Orchestra.codediff.renderDiff(b);
      if (b.type === 'tool-calls') return renderToolCalls(b.calls);
      if (b.type === 'checklist') return window.Orchestra.checklist.render(b);
      if (b.type === 'thinking') return renderThinking(b.text);
      if (b.type === 'terminal') return window.Orchestra.terminal.render({ title: b.title, lines: b.lines, running: b.running });
      if (b.type === 'error')    return renderError(b);
      if (b.type === 'attach')   return `
        <div class="attach">
          <div class="attach__icon">${icons.file(14)}</div>
          <div class="attach__body">
            <div class="attach__name">${escapeHTML(b.name)}</div>
            <div class="attach__size">${escapeHTML(b.size || '')}</div>
          </div>
        </div>`;
      return '';
    }).join('');

    return `
      <div class="msg msg--assistant" data-msg-idx="${idx !== undefined ? idx : ''}">
        <div class="msg__avatar">${icons.logo(18).replace('<svg', '<svg style="width:18px;height:18px"')}</div>
        <div class="msg__body">
          <div class="bubble">${blocks}</div>
          <div class="msg__actions">
            <button aria-label="Copy" title="Copy">${icons.copy(13)}</button>
            <button aria-label="Regenerate" title="Regenerate">${icons.refresh(13)}</button>
            <button aria-label="Good">${icons.thumbUp(13)}</button>
            <button aria-label="Bad">${icons.thumbDown(13)}</button>
          </div>
        </div>
      </div>`;
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.message = { render: renderMessage, renderMarkdown };
})();
