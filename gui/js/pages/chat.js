// Orchestra — Chat interface (real backend streaming)
(function () {
  const { icons } = window;
  const API = window.ORCH_API || 'http://localhost:3000';

  let state = {
    messages: [],
    model: null,
    modelOpen: false,
    composerValue: '',
    streaming: false,
  };

  // ── Error classification ──────────────────────────────────────────────────
  function classifyError(msg) {
    const m = (msg || '').toLowerCase();
    if (m.includes('api_key') || m.includes('api key') || m.includes('401') || m.includes('unauthorized')) {
      return {
        title: 'API key required',
        hint: 'Add your Anthropic or OpenRouter key in Settings → API Keys.',
        action: { label: 'Open Settings', href: '#/settings' },
      };
    }
    if (m.includes('rate limit') || m.includes('429') || m.includes('quota exceeded')) {
      return { title: 'Rate limit reached', hint: 'You\'ve hit the usage limit. Wait a moment or upgrade your plan.', action: null };
    }
    if (m.includes('econnrefused') || m.includes('failed to fetch') || m.includes('networkerror') || m.includes('load failed') || m.includes('network')) {
      return {
        title: 'Cannot reach backend',
        hint: 'The Orchestra server isn\'t running. Start it with: python run.py',
        action: null,
      };
    }
    if (m.includes('timeout') || m.includes('timed out')) {
      return { title: 'Request timed out', hint: 'The task took too long. Try a shorter prompt or use a background job.', action: null };
    }
    if (m.includes('model') && m.includes('not found')) {
      return { title: 'Model unavailable', hint: 'The selected model isn\'t configured. Try switching in the dropdown.', action: null };
    }
    return { title: 'Something went wrong', hint: (msg || 'Unknown error').slice(0, 180), action: null };
  }

  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ── Render ────────────────────────────────────────────────────────────────
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
    const dis = state.streaming ? 'disabled' : '';
    return `
      <div class="composer">
        <div class="composer__box${state.streaming ? ' is-streaming' : ''}">
          <textarea
            data-composer
            placeholder="${state.streaming ? 'Orchestra is working…' : 'Message Orchestra… (⇧+Enter for newline)'}"
            rows="1"
            ${dis}
          >${escapeHTML(state.composerValue)}</textarea>
          <div class="composer__row">
            <div class="composer__tools">
              <button class="composer__chip" title="Attach" ${dis}>
                <span class="icon">${icons.paperclip(14)}</span>
                <span>Attach</span>
              </button>
              <div class="dropdown ${state.modelOpen ? 'is-open' : ''}" data-dropdown="model">
                <button class="composer__chip model" data-action="toggle-model" ${dis}>
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
              <button class="composer__chip" title="Tools" ${dis}>
                <span class="icon">${icons.tools(14)}</span>
                <span>Tools</span>
              </button>
            </div>
            <button class="composer__send${state.streaming ? ' is-streaming' : ''}" data-action="send" aria-label="Send" ${dis}>
              ${state.streaming ? '<span class="send-dots"><span></span><span></span><span></span></span>' : icons.send(14)}
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

  // ── DOM helpers ───────────────────────────────────────────────────────────
  function autoscroll() {
    const stream = document.querySelector('[data-chat-stream]');
    if (stream) stream.scrollTop = stream.scrollHeight;
  }

  function updateStream() {
    const stream = document.querySelector('[data-chat-stream]');
    if (!stream) return;
    stream.innerHTML = renderStream();
    autoscroll();
    wireCodeCopy();
    wireRetry();
  }

  function updateComposer() {
    const box = document.querySelector('.composer');
    if (!box) return;
    box.outerHTML = renderComposer();
    wireComposer();
  }

  // ── Wiring ────────────────────────────────────────────────────────────────
  function wireComposer() {
    const ta = document.querySelector('[data-composer]');
    if (ta) {
      ta.addEventListener('input', (e) => {
        if (state.streaming) return;
        state.composerValue = e.target.value;
        e.target.style.height = 'auto';
        e.target.style.height = Math.min(200, e.target.scrollHeight) + 'px';
      });
      ta.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
      });
      ta.style.height = 'auto';
      ta.style.height = Math.min(200, ta.scrollHeight) + 'px';
    }
    const sendBtn = document.querySelector('[data-action="send"]');
    if (sendBtn) sendBtn.addEventListener('click', sendMessage);

    const toggleModel = document.querySelector('[data-action="toggle-model"]');
    if (toggleModel) {
      toggleModel.addEventListener('click', (e) => {
        e.stopPropagation();
        if (state.streaming) return;
        state.modelOpen = !state.modelOpen;
        updateComposer();
      });
    }
    document.querySelectorAll('[data-model]').forEach(item => {
      item.addEventListener('click', () => {
        state.model = window.MOCK.models.find(x => x.id === item.dataset.model);
        state.modelOpen = false;
        updateComposer();
      });
    });
    document.addEventListener('click', () => {
      if (state.modelOpen) { state.modelOpen = false; updateComposer(); }
    }, { once: true });
  }

  function wirePrompts() {
    document.querySelectorAll('[data-prompt]').forEach(p => {
      p.addEventListener('click', () => {
        if (state.streaming) return;
        const ta = document.querySelector('[data-composer]');
        if (!ta) return;
        ta.value = p.dataset.prompt;
        state.composerValue = ta.value;
        ta.focus();
        ta.dispatchEvent(new Event('input'));
      });
    });
  }

  function wireCodeCopy() {
    document.querySelectorAll('.codeblock__btn[data-action="copy"]').forEach(btn => {
      if (btn._wired) return;
      btn._wired = true;
      btn.addEventListener('click', () => {
        const pre = btn.closest('.codeblock')?.querySelector('pre');
        if (!pre) return;
        try {
          navigator.clipboard.writeText(pre.innerText);
          const orig = btn.innerHTML;
          btn.innerHTML = `${icons.check(12)} Copied`;
          setTimeout(() => { btn.innerHTML = orig; }, 1200);
        } catch(e) {}
      });
    });
  }

  function wireRetry() {
    document.querySelectorAll('[data-retry]').forEach(btn => {
      if (btn._wired) return;
      btn._wired = true;
      btn.addEventListener('click', () => {
        const text = btn.dataset.retry;
        if (!text || state.streaming) return;
        // Remove the errored assistant message
        const msgEl = btn.closest('[data-msg-idx]');
        if (msgEl) {
          const idx = parseInt(msgEl.dataset.msgIdx, 10);
          if (!isNaN(idx)) state.messages.splice(idx, 1);
        }
        state.composerValue = text;
        sendMessage();
      });
    });
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function nowStr() {
    return new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  }

  function formatToolName(name) {
    return (name || 'Tool').replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  }

  function guessToolIcon(name) {
    const n = (name || '').toLowerCase();
    if (n.includes('web') || n.includes('search') || n.includes('browser') || n.includes('url')) return 'globe';
    if (n.includes('file') || n.includes('read') || n.includes('write') || n.includes('edit')) return 'file';
    if (n.includes('bash') || n.includes('shell') || n.includes('exec') || n.includes('terminal')) return 'terminal';
    if (n.includes('git') || n.includes('github')) return 'github';
    if (n.includes('email') || n.includes('gmail') || n.includes('mail')) return 'mail';
    if (n.includes('memory') || n.includes('recall')) return 'database';
    if (n.includes('code') || n.includes('python') || n.includes('js')) return 'code';
    return 'sparkles';
  }

  // ── Send & Stream ─────────────────────────────────────────────────────────
  function sendMessage() {
    const text = state.composerValue.trim();
    if (!text || state.streaming) return;
    state.messages.push({ role: 'user', text, time: nowStr() });
    state.composerValue = '';
    state.streaming = true;
    updateStream();
    updateComposer();
    wirePrompts();
    streamAssistant(text);
  }

  function streamAssistant(userText) {
    const msg = {
      role: 'assistant',
      time: nowStr(),
      blocks: [{ type: 'thinking', text: 'Connecting to Orchestra…' }],
    };
    state.messages.push(msg);
    updateStream();

    const toolCalls = [];
    let thinkingText = 'Planning…';
    const params = new URLSearchParams({ task: userText, user_id: 'default', architecture: 'A' });

    let es;
    try {
      es = new EventSource(`${API}/v1/run/stream?${params}`);
    } catch (err) {
      const { title, hint, action } = classifyError(err.message);
      msg.blocks = [{ type: 'error', title, hint, action, retry: userText }];
      state.streaming = false;
      updateStream();
      updateComposer();
      return;
    }

    function finishStream() {
      state.streaming = false;
      updateComposer();
      wireCodeCopy();
      wireRetry();
    }

    es.onmessage = (e) => {
      if (e.data === '[DONE]') {
        es.close();
        finishStream();
        return;
      }
      let ev;
      try { ev = JSON.parse(e.data); } catch { return; }

      if (ev.type === 'thinking') {
        thinkingText = ev.content || thinkingText;
        msg.blocks = [{ type: 'thinking', text: thinkingText }];
        if (toolCalls.length) msg.blocks.push({ type: 'tool-calls', calls: [...toolCalls] });

      } else if (ev.type === 'tool_call') {
        toolCalls.push({ icon: guessToolIcon(ev.tool), label: formatToolName(ev.tool), state: 'working' });
        msg.blocks = [
          { type: 'thinking', text: thinkingText },
          { type: 'tool-calls', calls: [...toolCalls] },
        ];

      } else if (ev.type === 'tool_result') {
        const call = toolCalls.find(c => c.label === formatToolName(ev.tool) && c.state === 'working');
        if (call) call.state = ev.success ? 'done' : 'error';
        msg.blocks = [
          { type: 'thinking', text: thinkingText },
          { type: 'tool-calls', calls: [...toolCalls] },
        ];

      } else if (ev.type === 'final') {
        msg.blocks = [
          ...(toolCalls.length ? [{ type: 'tool-calls', calls: toolCalls.map(c => ({ ...c, state: 'done' })) }] : []),
          { type: 'md', content: ev.content || '' },
        ];
        msg.time = nowStr();
        es.close();
        finishStream();
        if (window.Orchestra?.toast) window.Orchestra.toast.show('Task complete', 'success', 3000);
        return;

      } else if (ev.type === 'error') {
        const { title, hint, action } = classifyError(ev.message);
        msg.blocks = [{ type: 'error', title, hint, action, retry: userText }];
        es.close();
        finishStream();
        if (window.Orchestra?.toast) window.Orchestra.toast.show(title, 'error', 5000);
        return;
      }

      updateStream();
    };

    es.onerror = () => {
      if (!state.streaming) return;
      es.close();
      const { title, hint } = classifyError('failed to fetch');
      msg.blocks = [{ type: 'error', title, hint, retry: userText }];
      finishStream();
      updateStream();
      if (window.Orchestra?.toast) window.Orchestra.toast.show(title, 'error', 5000);
    };
  }

  // ── Mount / Unmount ───────────────────────────────────────────────────────
  function mount(root) {
    state.messages = [];
    state.streaming = false;
    root.innerHTML = render();
    autoscroll();
    wireComposer();
    wirePrompts();
    wireCodeCopy();
  }

  function unmount() {
    state.streaming = false;
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.pages = window.Orchestra.pages || {};
  window.Orchestra.pages.chat = { mount, unmount };
})();
