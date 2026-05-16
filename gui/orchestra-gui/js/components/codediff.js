// Orchestra — Code blocks & diff viewer (with lightweight syntax highlighting)
(function () {
  const { icons } = window;

  // Very small, safe tokenizer for TypeScript/JavaScript/Python/JSON/Lua-ish code.
  // Returns HTML string with <span class="tok-*"> wrappers.
  function escapeHTML(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  const KEYWORDS_TS = new Set([
    'const','let','var','function','return','if','else','for','while','do','switch','case','break',
    'continue','new','class','extends','implements','interface','type','export','import','from',
    'async','await','of','in','typeof','instanceof','try','catch','finally','throw','yield',
    'public','private','protected','readonly','static','void','null','undefined','true','false',
    'this','super','default','as','enum','namespace','declare'
  ]);
  const KEYWORDS_PY = new Set([
    'def','return','if','elif','else','for','while','break','continue','class','import','from',
    'as','pass','try','except','finally','raise','with','lambda','yield','global','nonlocal',
    'None','True','False','and','or','not','in','is','async','await'
  ]);

  function tokenizeCode(code, lang) {
    lang = (lang || '').toLowerCase();
    const isPy = /^python|^py$/.test(lang);
    const kws = isPy ? KEYWORDS_PY : KEYWORDS_TS;

    // Strategy: scan char-by-char, emit spans for strings, comments, numbers, keywords, identifiers
    let out = '';
    let i = 0;
    const n = code.length;

    const isLetter = c => /[A-Za-z_$]/.test(c);
    const isWord = c => /[A-Za-z0-9_$]/.test(c);
    const isDigit = c => /[0-9]/.test(c);

    while (i < n) {
      const c = code[i];

      // Line comment: // (TS) or # (Py) or -- (Lua inside)
      if (!isPy && c === '/' && code[i + 1] === '/') {
        let j = i; while (j < n && code[j] !== '\n') j++;
        out += `<span class="tok-com">${escapeHTML(code.slice(i, j))}</span>`;
        i = j; continue;
      }
      if (isPy && c === '#') {
        let j = i; while (j < n && code[j] !== '\n') j++;
        out += `<span class="tok-com">${escapeHTML(code.slice(i, j))}</span>`;
        i = j; continue;
      }
      // Block comment /* ... */
      if (!isPy && c === '/' && code[i + 1] === '*') {
        let j = i + 2; while (j < n && !(code[j] === '*' && code[j + 1] === '/')) j++;
        j = Math.min(n, j + 2);
        out += `<span class="tok-com">${escapeHTML(code.slice(i, j))}</span>`;
        i = j; continue;
      }
      // Strings: ' " ` (with escape handling)
      if (c === '"' || c === "'" || c === '`') {
        const quote = c;
        let j = i + 1;
        while (j < n) {
          if (code[j] === '\\') { j += 2; continue; }
          if (code[j] === quote) { j++; break; }
          j++;
        }
        out += `<span class="tok-str">${escapeHTML(code.slice(i, j))}</span>`;
        i = j; continue;
      }
      // Numbers
      if (isDigit(c)) {
        let j = i; while (j < n && /[0-9._xXa-fA-F]/.test(code[j])) j++;
        out += `<span class="tok-num">${escapeHTML(code.slice(i, j))}</span>`;
        i = j; continue;
      }
      // Identifiers / keywords
      if (isLetter(c)) {
        let j = i; while (j < n && isWord(code[j])) j++;
        const word = code.slice(i, j);
        const after = code[j];
        if (kws.has(word)) {
          out += `<span class="tok-kw">${escapeHTML(word)}</span>`;
        } else if (after === '(') {
          out += `<span class="tok-fn">${escapeHTML(word)}</span>`;
        } else if (/^[A-Z]/.test(word)) {
          out += `<span class="tok-cls">${escapeHTML(word)}</span>`;
        } else {
          out += `<span class="tok-prop">${escapeHTML(word)}</span>`;
        }
        i = j; continue;
      }
      // Punctuation
      if (/[{}()\[\];,.:<>=+\-*/%!?&|^~]/.test(c)) {
        out += `<span class="tok-punct">${escapeHTML(c)}</span>`;
        i++; continue;
      }
      // Whitespace or other
      out += escapeHTML(c);
      i++;
    }
    return out;
  }

  // Render code block
  function renderCodeBlock({ code, lang = '', title = '' }) {
    const lines = code.split('\n');
    const pad = String(lines.length).length;

    const rendered = lines.map((ln, idx) => {
      const n = String(idx + 1).padStart(pad, ' ');
      const html = tokenizeCode(ln, lang) || '&nbsp;';
      return `<div class="codeblock__line"><span class="codeblock__ln">${n}</span><span class="codeblock__code">${html}</span></div>`;
    }).join('');

    return `
      <div class="codeblock">
        <div class="codeblock__head">
          <span class="codeblock__lang">${title || lang || 'code'}</span>
          <div class="codeblock__actions">
            <button class="codeblock__btn" data-action="copy">${icons.copy(12)} Copy</button>
          </div>
        </div>
        <div class="codeblock__body"><pre>${rendered}</pre></div>
      </div>
    `;
  }

  // Render diff
  function renderDiff({ path, adds = 0, rems = 0, lines = [] }) {
    const body = lines.map(line => {
      const kindClass = line.kind === 'add' ? 'add' : line.kind === 'rem' ? 'rem' : 'ctx';
      const marker = line.kind === 'add' ? '+' : line.kind === 'rem' ? '-' : ' ';
      return `
        <div class="diff__line ${kindClass}">
          <span class="ln">${line.n ?? ''}</span>
          <span class="marker">${marker}</span>
          <span class="content">${escapeHTML(line.text)}</span>
        </div>`;
    }).join('');

    return `
      <div class="diff">
        <div class="diff__head">
          <span class="path">${escapeHTML(path)}</span>
          <div class="diff__stats">
            <span class="add">+${adds}</span>
            <span class="rem">−${rems}</span>
          </div>
        </div>
        <div class="diff__body">${body}</div>
      </div>
    `;
  }

  // Animated typing effect for code: reveals line by line.
  // Accepts a DOM element whose .codeblock__body pre already contains rendered HTML.
  function animateReveal(containerEl, { perLine = 35 } = {}) {
    const linesEls = containerEl.querySelectorAll('.codeblock__line, .diff__line');
    linesEls.forEach((el, idx) => {
      el.style.opacity = '0';
      el.style.transform = 'translateY(4px)';
      setTimeout(() => {
        el.style.transition = 'opacity 220ms ease, transform 220ms ease';
        el.style.opacity = '1';
        el.style.transform = 'translateY(0)';
      }, idx * perLine);
    });
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.codediff = { renderCodeBlock, renderDiff, tokenizeCode, animateReveal };
})();
