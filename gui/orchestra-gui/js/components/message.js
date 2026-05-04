// Orchestra — Chat message rendering (markdown + blocks)
(function () {
  const { icons } = window;

  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Minimal markdown renderer (paragraphs, headings, bold/italic, inline code, lists, blockquote, links, hr)
  function renderMarkdown(md) {
    const lines = md.split('\n');
    let out = [];
    let i = 0;

    const inline = (s) => {
      s = escapeHTML(s);
      // inline code
      s = s.replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`);
      // bold
      s = s.replace(/\*\*([^*]+)\*\*/g, (_, c) => `<strong>${c}</strong>`);
      // italic
      s = s.replace(/(^|[\s(])\*([^*\n]+)\*/g, (m, pre, c) => `${pre}<em>${c}</em>`);
      // links [text](url)
      s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, t, u) => `<a href="${u}">${t}</a>`);
      return s;
    };

    while (i < lines.length) {
      const ln = lines[i];
      if (/^\s*$/.test(ln)) { i++; continue; }

      // Headings
      const h = /^(#{1,3})\s+(.*)$/.exec(ln);
      if (h) {
        const level = h[1].length;
        out.push(`<h${level}>${inline(h[2])}</h${level}>`);
        i++; continue;
      }
      // HR
      if (/^---+\s*$/.test(ln)) {
        out.push('<hr />');
        i++; continue;
      }
      // Blockquote (single-line consolidated)
      if (/^>\s?/.test(ln)) {
        let block = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) {
          block.push(lines[i].replace(/^>\s?/, ''));
          i++;
        }
        out.push(`<blockquote>${inline(block.join(' '))}</blockquote>`);
        continue;
      }
      // Unordered list
      if (/^\s*[-*]\s+/.test(ln)) {
        let items = [];
        while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
          items.push(`<li>${inline(lines[i].replace(/^\s*[-*]\s+/, ''))}</li>`);
          i++;
        }
        out.push(`<ul>${items.join('')}</ul>`);
        continue;
      }
      // Ordered list
      if (/^\s*\d+\.\s+/.test(ln)) {
        let items = [];
        while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
          items.push(`<li>${inline(lines[i].replace(/^\s*\d+\.\s+/, ''))}</li>`);
          i++;
        }
        out.push(`<ol>${items.join('')}</ol>`);
        continue;
      }
      // Paragraph (consume until blank line)
      let para = [ln];
      i++;
      while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^(#{1,3}\s|>|\s*[-*]\s|\s*\d+\.\s|---+\s*$)/.test(lines[i])) {
        para.push(lines[i]); i++;
      }
      out.push(`<p>${inline(para.join(' '))}</p>`);
    }
    return out.join('\n');
  }

  function renderToolCalls(calls) {
    return `<div class="tool-calls">${
      calls.map(c => {
        const state = c.state || 'working';
        return `<div class="tool-call ${state === 'working' ? 'is-working' : 'done'}">
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

  function renderMessage(m) {
    const isUser = m.role === 'user';
    const time = m.time || '';

    if (isUser) {
      return `
        <div class="msg msg--user">
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

    // Assistant: renders blocks or plain text
    const blocks = (m.blocks || [{ type: 'md', content: m.text || '' }]).map(b => {
      if (b.type === 'md') return `<div class="md">${renderMarkdown(b.content)}</div>`;
      if (b.type === 'code') return window.Orchestra.codediff.renderCodeBlock({ code: b.code, lang: b.lang, title: b.title });
      if (b.type === 'diff') return window.Orchestra.codediff.renderDiff(b);
      if (b.type === 'tool-calls') return renderToolCalls(b.calls);
      if (b.type === 'checklist') return window.Orchestra.checklist.render(b);
      if (b.type === 'thinking') return renderThinking(b.text);
      if (b.type === 'terminal') return window.Orchestra.terminal.render({ title: b.title, lines: b.lines, running: b.running });
      if (b.type === 'attach') return `
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
      <div class="msg msg--assistant">
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
