// Orchestra — Interactive terminal page (WebSocket shell session)
(function () {
  const { icons } = window;

  function wsBase() {
    const api = window.ORCH_API || 'http://localhost:3000';
    return api.replace(/^http/, 'ws');
  }

  const MAX_LINES = 5000;

  let _root = null;
  let _ws = null;
  let _connected = false;
  let _running = false;
  let _lines = [];      // [{kind, text}]
  let _history = [];    // command strings
  let _histIdx = -1;
  let _cwd = '';
  let _reconnectTimer = null;

  // ── Escape ──────────────────────────────────────────────────────────────────
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ── State mutations ──────────────────────────────────────────────────────────
  function pushLine(kind, text) {
    _lines.push({ kind, text });
    if (_lines.length > MAX_LINES) _lines.splice(0, _lines.length - MAX_LINES);
  }

  // ── DOM helpers ──────────────────────────────────────────────────────────────
  function el(sel) { return _root && _root.querySelector(sel); }

  function appendOutputLine(kind, text) {
    const out = el('[data-term-out]');
    if (!out) return;
    const span = document.createElement('span');
    span.className = `term-line term-line--${kind}`;
    span.textContent = text;
    out.appendChild(span);
    out.appendChild(document.createTextNode('\n'));
    // Autoscroll
    const body = el('[data-term-body]');
    if (body) body.scrollTop = body.scrollHeight;
  }

  function setStatus(connected) {
    _connected = connected;
    const s = el('[data-term-status]');
    if (!s) return;
    s.className = `term-page__status ${connected ? 'term-page__status--ok' : 'term-page__status--off'}`;
    s.textContent = connected ? '● connected' : '● disconnected';
    updateInputState();
  }

  function updateInputState() {
    const inp = el('[data-term-input]');
    const btn = el('[data-term-run]');
    if (inp) inp.disabled = !_connected || _running;
    if (btn) btn.disabled = !_connected || _running;
  }

  function showPrompt() {
    const prompt = el('[data-term-prompt]');
    if (prompt) prompt.textContent = (_cwd ? _cwd.split(/[\\/]/).pop() || _cwd : '$') + ' $';
  }

  // ── WebSocket ────────────────────────────────────────────────────────────────
  function connect() {
    if (_ws && (_ws.readyState === WebSocket.CONNECTING || _ws.readyState === WebSocket.OPEN)) return;

    const url = `${wsBase()}/v1/terminal/ws`;
    let ws;
    try {
      ws = new WebSocket(url);
    } catch (e) {
      appendOutputLine('err', `[Orchestra] Cannot open WebSocket: ${e.message}`);
      scheduleReconnect();
      return;
    }

    _ws = ws;

    ws.onopen = () => {
      // If JWT secret is configured the server expects an auth frame first.
      // For local dev (no secret) the server skips auth and sends "ready" immediately.
      // We optimistically send a no-op auth frame that works either way.
      ws.send(JSON.stringify({ token: '' }));
    };

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }

      switch (msg.type) {
        case 'ready':
          _cwd = msg.cwd || '';
          setStatus(true);
          _running = false;
          showPrompt();
          appendOutputLine('info', `[Orchestra] Shell ready  cwd=${_cwd}  (${msg.shell || 'sh'})`);
          updateInputState();
          focusInput();
          break;

        case 'output':
          pushLine('out', msg.line);
          appendOutputLine('out', msg.line);
          break;

        case 'done':
          _running = false;
          updateInputState();
          focusInput();
          break;

        case 'timeout':
          _running = false;
          appendOutputLine('err', '[Orchestra] Command timed out (60s)');
          updateInputState();
          focusInput();
          break;

        case 'exit':
          appendOutputLine('info', `[Orchestra] Shell exited (code ${msg.code ?? '?'})`);
          setStatus(false);
          scheduleReconnect();
          break;

        case 'error':
          appendOutputLine('err', `[Orchestra] ${msg.message || 'Unknown error'}`);
          break;

        case 'pong':
          break;

        default:
          break;
      }
    };

    ws.onerror = () => {
      appendOutputLine('err', '[Orchestra] WebSocket error — is the server running?');
    };

    ws.onclose = () => {
      setStatus(false);
      _running = false;
      updateInputState();
      scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    if (_reconnectTimer) return;
    appendOutputLine('info', '[Orchestra] Reconnecting in 4s…');
    _reconnectTimer = setTimeout(() => {
      _reconnectTimer = null;
      connect();
    }, 4000);
  }

  function disconnect() {
    if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
    if (_ws) { _ws.onclose = null; _ws.close(); _ws = null; }
    _connected = false;
    _running = false;
  }

  // ── Command dispatch ─────────────────────────────────────────────────────────
  function runCommand(command) {
    if (!command.trim() || !_connected || _running) return;

    // Push to history (deduplicate consecutive)
    if (!_history.length || _history[_history.length - 1] !== command) {
      _history.push(command);
      if (_history.length > 200) _history.shift();
    }
    _histIdx = -1;

    // Echo the command
    appendOutputLine('cmd', `$ ${command}`);

    _running = true;
    updateInputState();
    _ws.send(JSON.stringify({ type: 'run', command }));
  }

  function focusInput() {
    const inp = el('[data-term-input]');
    if (inp) inp.focus();
  }

  // ── Render ───────────────────────────────────────────────────────────────────
  function render() {
    return `
      <div class="page page--terminal">
        <div class="term-page__header">
          <div class="term-page__title">${icons.terminal(14)} Terminal</div>
          <div class="term-page__actions">
            <span class="term-page__status term-page__status--off" data-term-status>● disconnected</span>
            <button class="btn btn--subtle btn--sm" data-term-clear title="Clear output">Clear</button>
            <button class="btn btn--subtle btn--sm" data-term-reconnect title="Reconnect shell">Reconnect</button>
          </div>
        </div>

        <div class="term-page__body" data-term-body>
          <pre class="term-page__out" data-term-out></pre>
        </div>

        <div class="term-page__bar">
          <span class="term-page__prompt" data-term-prompt>$ </span>
          <input
            class="term-page__input"
            type="text"
            placeholder="enter command…"
            autocomplete="off"
            autocorrect="off"
            autocapitalize="off"
            spellcheck="false"
            data-term-input
            disabled
          />
          <button class="term-page__send" data-term-run title="Run (Enter)" disabled>
            ${icons.send(13)}
          </button>
        </div>
      </div>
    `;
  }

  // ── Mount / unmount ──────────────────────────────────────────────────────────
  function mount(container) {
    _root = container;
    _lines = [];
    _history = [];
    _histIdx = -1;
    _cwd = '';

    container.innerHTML = render();

    // Wire clear
    container.querySelector('[data-term-clear]').addEventListener('click', () => {
      _lines = [];
      const out = el('[data-term-out]');
      if (out) out.textContent = '';
    });

    // Wire reconnect
    container.querySelector('[data-term-reconnect]').addEventListener('click', () => {
      disconnect();
      connect();
    });

    // Wire run button
    container.querySelector('[data-term-run]').addEventListener('click', () => {
      const inp = el('[data-term-input]');
      if (!inp) return;
      const cmd = inp.value.trim();
      if (cmd) { inp.value = ''; runCommand(cmd); }
    });

    // Wire input keyboard
    container.querySelector('[data-term-input]').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const cmd = e.target.value.trim();
        if (cmd) { e.target.value = ''; runCommand(cmd); }
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (!_history.length) return;
        _histIdx = _histIdx < 0 ? _history.length - 1 : Math.max(0, _histIdx - 1);
        e.target.value = _history[_histIdx] || '';
        return;
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (_histIdx < 0) return;
        _histIdx = Math.min(_history.length - 1, _histIdx + 1);
        e.target.value = (_histIdx >= _history.length - 1 && _histIdx >= 0)
          ? (_histIdx === _history.length - 1 ? _history[_histIdx] : '')
          : _history[_histIdx] || '';
        if (_histIdx >= _history.length) { _histIdx = -1; e.target.value = ''; }
        return;
      }
      // Ctrl+C: clear input / signal running process (best-effort)
      if (e.key === 'c' && (e.ctrlKey || e.metaKey) && !e.target.value) {
        e.preventDefault();
        appendOutputLine('info', '^C');
        _running = false;
        updateInputState();
      }
    });

    connect();
  }

  function unmount() {
    disconnect();
    _root = null;
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.pages = window.Orchestra.pages || {};
  window.Orchestra.pages.terminal = { mount, unmount };
})();
