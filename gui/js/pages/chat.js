// Orchestra — Chat interface
(function () {
  const { icons } = window;

  let state = {
    messages: [],
    model: null,
    modelOpen: false,
    composerValue: '',
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
    return `
      <div class="composer">
        <div class="composer__box">
          <textarea
            data-composer
            placeholder="Message Orchestra… (⇧+Enter for newline)"
            rows="1"
          >${escapeHTML(state.composerValue)}</textarea>
          <div class="composer__row">
            <div class="composer__tools">
              <button class="composer__chip" title="Attach">
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
              <button class="composer__chip" title="Tools">
                <span class="icon">${icons.tools(14)}</span>
                <span>Tools</span>
              </button>
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
    const ta = document.querySelector('[data-composer]');
    if (ta) {
      ta.addEventListener('input', (e) => {
        state.composerValue = e.target.value;
        e.target.style.height = 'auto';
        e.target.style.height = Math.min(200, e.target.scrollHeight) + 'px';
      });
      ta.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
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

    // Close dropdown on outside click
    document.addEventListener('click', () => {
      if (state.modelOpen) {
        state.modelOpen = false;
        updateComposer();
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
    return `Here's what I did with **"${userText.slice(0, 80)}${userText.length > 80 ? '…' : ''}"**:

1. Parsed intent and matched it to the most relevant agent.
2. Gathered context from your workspace (recent tasks + pinned docs).
3. Produced a draft below — ready for review or one-click execution.

> This is a **demo reply**. In production, Orchestra would route this to the agent with live tool execution. Try a prompt from the suggestions above to see richer output.`;
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

    // Wire copy buttons on code blocks
    document.querySelectorAll('.codeblock__btn[data-action="copy"]').forEach(btn => {
      btn.addEventListener('click', () => {
        const pre = btn.closest('.codeblock').querySelector('pre');
        if (!pre) return;
        const text = pre.innerText;
        try {
          navigator.clipboard.writeText(text);
          const orig = btn.innerHTML;
          btn.innerHTML = `${icons.check(12)} Copied`;
          setTimeout(() => btn.innerHTML = orig, 1200);
        } catch(e) {}
      });
    });
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.pages = window.Orchestra.pages || {};
  window.Orchestra.pages.chat = { mount };
})();
