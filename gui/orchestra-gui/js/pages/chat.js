// Orchestra — Chat interface
(function () {
  const { icons } = window;

  const TOOLS_LIST = [
    { id: 'search',   label: 'Search Web',      icon: 'globe' },
    { id: 'code',     label: 'Run Code',         icon: 'terminal' },
    { id: 'read',     label: 'Read File',        icon: 'file' },
    { id: 'browse',   label: 'Browse Page',      icon: 'arrowUpRight' },
    { id: 'image',    label: 'Generate Image',   icon: 'sparkles' },
  ];

  let state = {
    messages: [],
    model: null,
    modelOpen: false,
    toolsOpen: false,
    activeTools: new Set(),
    composerValue: '',
    attachedFile: null,
  };

  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function render() {
    return `
      <div class="page page--chat chat">
        <div class="chat__stream" data-chat-stream>
          ${renderStream()}
        </div>
        ${renderComposer()}
      </div>
    `;
  }

  function renderStream() {
    if (state.messages.length === 0) {
      return `
        <div class="chat__welcome">
          <h1>How can Orchestra help today?</h1>
          <p>Start with a task, drop a file, or try a suggestion below.</p>
          <div class="chat__welcome-grid">
            ${window.MOCK.chatPrompts.map(p => `
              <div class="chat__prompt" data-prompt="${escapeHTML(p.title + ': ' + p.sub)}">
                <div class="p-title">${escapeHTML(p.title)}</div>
                <div class="p-sub">${escapeHTML(p.sub)}</div>
              </div>`).join('')}
          </div>
        </div>`;
    }
    return `
      <div class="chat__stream-inner">
        ${state.messages.map(m => window.Orchestra.message.render(m)).join('')}
      </div>
    `;
  }

  function renderComposer() {
    const m = state.model || window.MOCK.models.find(x => x.selected) || window.MOCK.models[0];
    const activeCount = state.activeTools.size;
    return `
      <div class="composer">
        <!-- Hidden file input for attach -->
        <input type="file" data-file-input style="display:none" />

        ${state.attachedFile ? `
          <div class="composer__chips">
            <div class="composer__file-chip">
              ${icons.paperclip(11)}
              <span>${escapeHTML(state.attachedFile)}</span>
              <button class="composer__chip-remove" data-action="remove-file">${icons.x(10)}</button>
            </div>
          </div>` : ''}

        <div class="composer__box">
          <textarea
            data-composer
            placeholder="Message Orchestra… (⇧+Enter for newline)"
            rows="1"
          >${escapeHTML(state.composerValue)}</textarea>
          <div class="composer__row">
            <div class="composer__tools">
              <button class="composer__chip" data-action="attach" title="Attach file">
                <span class="icon">${icons.paperclip(14)}</span>
                <span>Attach</span>
              </button>
              <div class="dropdown ${state.modelOpen ? 'is-open' : ''}" data-dropdown="model">
                <button class="composer__chip model" data-action="toggle-model">
                  <span class="icon" style="color:var(--accent)">${icons.sparkles(13)}</span>
                  <span>${escapeHTML(m.name)}</span>
                  <span style="color:var(--text-3)">${icons.chevronDown(12)}</span>
                </button>
                <div class="dropdown__menu">
                  ${window.MOCK.models.map(opt => `
                    <div class="dropdown__item ${opt.id === m.id ? 'is-selected' : ''}" data-model="${opt.id}">
                      <span class="mdot" style="background:${opt.id === m.id ? 'var(--accent)' : 'var(--bg-4)'}"></span>
                      <div style="flex:1">
                        <div class="mname">${escapeHTML(opt.name)}</div>
                        <div class="mdesc">${escapeHTML(opt.desc)}</div>
                      </div>
                      ${opt.id === m.id ? `<span style="color:var(--accent)">${icons.check(12)}</span>` : ''}
                    </div>`).join('')}
                </div>
              </div>

              <!-- Tools button with dropdown -->
              <div class="dropdown ${state.toolsOpen ? 'is-open' : ''}" data-dropdown="tools" style="position:relative">
                <button class="composer__chip ${activeCount > 0 ? 'composer__chip--active' : ''}" data-action="toggle-tools" title="Tools">
                  <span class="icon">${icons.tools(14)}</span>
                  <span>Tools</span>
                  ${activeCount > 0 ? `<span class="composer__tool-badge">${activeCount} active</span>` : ''}
                </button>
                <div class="dropdown__menu dropdown__menu--tools" style="min-width:200px">
                  <div style="padding:10px 14px 6px;font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em;font-weight:600">Available tools</div>
                  ${TOOLS_LIST.map(t => `
                    <div class="dropdown__item dropdown__item--tool ${state.activeTools.has(t.id) ? 'is-selected' : ''}" data-tool="${t.id}">
                      <span style="color:${state.activeTools.has(t.id) ? 'var(--accent)' : 'var(--text-3)'}">${icons[t.icon] ? icons[t.icon](14) : icons.sparkles(14)}</span>
                      <span style="flex:1">${escapeHTML(t.label)}</span>
                      ${state.activeTools.has(t.id) ? `<span style="color:var(--accent)">${icons.check(12)}</span>` : ''}
                    </div>`).join('')}
                </div>
              </div>
            </div>
            <button class="composer__send" data-action="send" aria-label="Send">
              ${icons.send(14)}
            </button>
          </div>
        </div>
        <div class="composer__footer">
          <div>Orchestra may make mistakes. Review agent actions before approving.</div>
          <div><span class="kbd">Enter</span> to send · <span class="kbd">⇧</span><span class="kbd">Enter</span> for new line</div>
        </div>
      </div>
    `;
  }

  function autoscroll() {
    const stream = document.querySelector('[data-chat-stream]');
    if (!stream) return;
    stream.scrollTop = stream.scrollHeight;
  }

  function updateStream() {
    const stream = document.querySelector('[data-chat-stream]');
    if (!stream) return;
    stream.innerHTML = renderStream();
    autoscroll();
  }

  function updateComposer() {
    const box = document.querySelector('.composer');
    if (!box) return;
    box.outerHTML = renderComposer();
    wireComposer();
  }

  function wireComposer() {
    // BUG 1: Hidden file input + attach button
    const attachBtn = document.querySelector('[data-action="attach"]');
    const fileInput = document.querySelector('[data-file-input]');
    if (attachBtn && fileInput) {
      attachBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        fileInput.click();
      });
      fileInput.addEventListener('change', () => {
        if (fileInput.files && fileInput.files[0]) {
          state.attachedFile = fileInput.files[0].name;
          updateComposer();
        }
      });
    }

    // Remove attached file
    const removeFile = document.querySelector('[data-action="remove-file"]');
    if (removeFile) {
      removeFile.addEventListener('click', (e) => {
        e.stopPropagation();
        state.attachedFile = null;
        updateComposer();
      });
    }

    // BUG 3: Textarea with Shift+Enter newline support
    const ta = document.querySelector('[data-composer]');
    if (ta) {
      ta.addEventListener('input', (e) => {
        state.composerValue = e.target.value;
        e.target.style.height = 'auto';
        e.target.style.height = Math.min(200, e.target.scrollHeight) + 'px';
      });
      ta.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.shiftKey) {
          // BUG 3 FIX: Shift+Enter inserts a newline, does NOT send
          e.preventDefault();
          const start = ta.selectionStart;
          const end = ta.selectionEnd;
          const val = ta.value;
          ta.value = val.substring(0, start) + '\n' + val.substring(end);
          ta.selectionStart = ta.selectionEnd = start + 1;
          state.composerValue = ta.value;
          ta.style.height = 'auto';
          ta.style.height = Math.min(200, ta.scrollHeight) + 'px';
        } else if (e.key === 'Enter' && !e.shiftKey) {
          // Plain Enter sends
          e.preventDefault();
          sendMessage();
        }
      });
      // initial resize
      ta.style.height = 'auto';
      ta.style.height = Math.min(200, ta.scrollHeight) + 'px';
    }

    const sendBtn = document.querySelector('[data-action="send"]');
    if (sendBtn) sendBtn.addEventListener('click', sendMessage);

    const toggleModel = document.querySelector('[data-action="toggle-model"]');
    if (toggleModel) toggleModel.addEventListener('click', (e) => {
      e.stopPropagation();
      state.modelOpen = !state.modelOpen;
      state.toolsOpen = false;
      updateComposer();
    });

    document.querySelectorAll('[data-model]').forEach(item => {
      item.addEventListener('click', () => {
        const id = item.dataset.model;
        state.model = window.MOCK.models.find(x => x.id === id);
        state.modelOpen = false;
        updateComposer();
      });
    });

    // BUG 2: Tools button toggle
    const toggleTools = document.querySelector('[data-action="toggle-tools"]');
    if (toggleTools) toggleTools.addEventListener('click', (e) => {
      e.stopPropagation();
      state.toolsOpen = !state.toolsOpen;
      state.modelOpen = false;
      updateComposer();
    });

    document.querySelectorAll('[data-tool]').forEach(item => {
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = item.dataset.tool;
        if (state.activeTools.has(id)) {
          state.activeTools.delete(id);
        } else {
          state.activeTools.add(id);
        }
        updateComposer();
      });
    });

    // Close dropdowns on outside click
    document.addEventListener('click', (e) => {
      if (!e.target.closest('[data-dropdown]')) {
        if (state.modelOpen || state.toolsOpen) {
          state.modelOpen = false;
          state.toolsOpen = false;
          updateComposer();
        }
      }
    }, { once: true });
  }

  function wirePrompts() {
    document.querySelectorAll('[data-prompt]').forEach(p => {
      p.addEventListener('click', () => {
        const ta = document.querySelector('[data-composer]');
        if (!ta) return;
        ta.value = p.dataset.prompt;
        state.composerValue = ta.value;
        ta.focus();
        ta.dispatchEvent(new Event('input'));
      });
    });
  }

  function sendMessage() {
    const text = state.composerValue.trim();
    if (!text) return;
    state.messages.push({ role: 'user', text, time: nowStr() });
    state.composerValue = '';
    state.attachedFile = null;
    updateStream();
    updateComposer();
    wirePrompts();

    // Simulate an assistant response with staged reveal.
    simulateAssistant(text);
  }

  function nowStr() {
    return new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  }

  function simulateAssistant(userText) {
    const msg = {
      role: 'assistant',
      time: nowStr(),
      blocks: [
        { type: 'thinking', text: 'Interpreting request' },
        { type: 'tool-calls', calls: [
          { icon: 'globe', label: 'Searching context', state: 'working' },
        ]},
      ],
    };
    state.messages.push(msg);
    updateStream();

    setTimeout(() => {
      msg.blocks = [
        { type: 'tool-calls', calls: [
          { icon: 'globe', label: 'Searching context', state: 'done' },
          { icon: 'file', label: 'Reading workspace files', state: 'working' },
        ]},
        { type: 'checklist', title: 'Plan', items: [
          { text: 'Interpret user intent', status: 'done' },
          { text: 'Route to the right agent', status: 'working' },
          { text: 'Execute and summarize', status: 'pending' },
        ]},
      ];
      updateStream();
    }, 900);

    setTimeout(() => {
      msg.blocks = [
        { type: 'tool-calls', calls: [
          { icon: 'globe', label: 'Searching context', state: 'done' },
          { icon: 'file', label: 'Reading workspace files', state: 'done' },
          { icon: 'terminal', label: 'Invoking agent', state: 'done' },
        ]},
        { type: 'md', content: buildReply(userText) },
      ];
      updateStream();
    }, 2100);
  }

  function buildReply(userText) {
    return `Here's what I did with **"${userText.slice(0, 80)}${userText.length > 80 ? '…' : ''}"**:\n\n1. Parsed intent and matched it to the most relevant agent.\n2. Gathered context from your workspace (recent tasks + pinned docs).\n3. Produced a draft below — ready for review or one-click execution.\n\n> This is a **demo reply**. In production, Orchestra would route this to the agent with live tool execution. Try a prompt from the suggestions above to see richer output.`;
  }

  function wireCopyButtons() {
    // Use event delegation on the stream container so copy buttons work
    // even after updateStream() re-renders content.
    const stream = document.querySelector('[data-chat-stream]');
    if (!stream || stream._copyDelegated) return;
    stream._copyDelegated = true;
    stream.addEventListener('click', (e) => {
      const btn = e.target.closest('.codeblock__btn[data-action="copy"]');
      if (!btn) return;
      const codeblock = btn.closest('.codeblock');
      if (!codeblock) return;
      const pre = codeblock.querySelector('pre');
      if (!pre) return;
      const text = pre.innerText;
      navigator.clipboard.writeText(text).then(() => {
        const orig = btn.innerHTML;
        btn.textContent = '\u2713 Copied';
        setTimeout(() => { btn.innerHTML = orig; }, 2000);
      }).catch(() => {
        // Fallback for browsers without clipboard API
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.cssText = 'position:fixed;opacity:0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        const orig = btn.innerHTML;
        btn.textContent = '\u2713 Copied';
        setTimeout(() => { btn.innerHTML = orig; }, 2000);
      });
    });
  }

  function mount(root) {
    // Pre-populate with mock messages on first visit
    if (state.messages.length === 0) {
      state.messages = JSON.parse(JSON.stringify(window.MOCK.messages));
    }
    root.innerHTML = render();
    autoscroll();
    wireComposer();
    wirePrompts();
    wireCopyButtons();
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.pages = window.Orchestra.pages || {};
  window.Orchestra.pages.chat = { mount };
})();
