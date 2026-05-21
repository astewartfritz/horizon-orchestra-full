from __future__ import annotations

MILES_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no,viewport-fit=cover">
<meta name="theme-color" content="#09090E">
<title>M.I.L.E.S — Orchestra</title>
<script src="https://cdn.jsdelivr.net/npm/marked@15.0.7/marked.min.js"></script>
<style>
:root {
  --bg:       #09090E;
  --bg-2:     #111118;
  --bg-3:     #16161f;
  --bg-4:     #1e1e2a;
  --border:   rgba(255,255,255,.07);
  --text:     #E8E8F0;
  --text-2:   #9898B0;
  --text-3:   #5A5A72;
  --accent:   #6E6EF5;
  --accent-2: #00C9B8;
  --grad:     linear-gradient(135deg,#6E6EF5,#00C9B8);
  --grad-glow:0 0 40px rgba(110,110,245,.18);
  --r:        8px;
  --r-lg:     14px;
  --ease:     cubic-bezier(.4,0,.2,1);
  --dur:      .18s;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Inter','Segoe UI',sans-serif;-webkit-font-smoothing:antialiased}
button{font-family:inherit;cursor:pointer}
a{text-decoration:none;color:inherit}
code{font-family:'SF Mono','Fira Code','JetBrains Mono',monospace}

/* ── Layout ── */
#app{display:flex;flex-direction:column;height:100vh;overflow:hidden}

/* ── Header ── */
#header{
  display:flex;align-items:center;gap:12px;
  padding:12px 22px;
  background:rgba(9,9,14,.85);
  backdrop-filter:blur(14px);
  border-bottom:1px solid var(--border);
  flex-shrink:0;position:relative;z-index:10;
}
#back-btn{
  display:inline-flex;align-items:center;gap:6px;
  padding:5px 12px;border-radius:var(--r);
  background:var(--bg-3);border:1px solid var(--border);
  font-size:12px;color:var(--text-2);
  transition:all var(--dur) var(--ease);
}
#back-btn:hover{color:var(--text);border-color:rgba(255,255,255,.15)}
#back-btn svg{flex-shrink:0}
.miles-wordmark{
  display:flex;align-items:center;gap:10px;
}
.miles-logo{
  width:32px;height:32px;border-radius:9px;
  background:var(--grad);
  display:grid;place-items:center;
  font-size:13px;font-weight:800;color:#fff;letter-spacing:-.5px;
  box-shadow:var(--grad-glow);
  flex-shrink:0;
}
.miles-name{
  font-size:15px;font-weight:700;
  background:var(--grad);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}
.miles-sub{font-size:11px;color:var(--text-3);margin-top:1px}
#status-pill{
  margin-left:auto;
  display:inline-flex;align-items:center;gap:6px;
  padding:4px 12px;border-radius:999px;
  font-size:11px;font-weight:500;
  background:var(--bg-3);border:1px solid var(--border);
  color:var(--text-3);
  transition:all .3s var(--ease);
}
#status-pill .dot{
  width:6px;height:6px;border-radius:50%;
  background:var(--text-3);flex-shrink:0;
  transition:background .3s;
}
#status-pill.running{color:var(--accent);border-color:rgba(110,110,245,.3)}
#status-pill.running .dot{background:var(--accent);animation:pulse-dot 1.2s ease-in-out infinite}
#status-pill.done{color:var(--accent-2);border-color:rgba(0,201,184,.3)}
#status-pill.done .dot{background:var(--accent-2)}
@keyframes pulse-dot{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.7)}}

/* ── Engine bar ── */
#engine-bar{
  display:flex;align-items:center;gap:8px;
  padding:7px 22px;
  background:var(--bg-2);
  border-bottom:1px solid var(--border);
  flex-shrink:0;
  font-size:11.5px;color:var(--text-3);
}
#engine-bar label{display:flex;align-items:center;gap:6px}
#engine-select{
  background:var(--bg-3);border:1px solid var(--border);
  color:var(--text-2);font-size:11.5px;padding:3px 8px;
  border-radius:var(--r);font-family:inherit;
  transition:border-color var(--dur);
}
#engine-select:focus{outline:none;border-color:var(--accent)}
#workspace-input{
  flex:1;max-width:340px;
  background:var(--bg-3);border:1px solid var(--border);
  color:var(--text-2);font-size:11.5px;padding:3px 10px;
  border-radius:var(--r);font-family:inherit;
  transition:border-color var(--dur);
}
#workspace-input::placeholder{color:var(--text-3)}
#workspace-input:focus{outline:none;border-color:rgba(110,110,245,.5)}

/* ── Messages ── */
#messages-wrap{flex:1;overflow-y:auto;min-height:0;scroll-behavior:smooth}
#messages{display:flex;flex-direction:column;gap:0;padding:20px 0 12px}

/* Welcome */
#welcome{
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  flex:1;padding:60px 32px;text-align:center;
  min-height:340px;
}
#welcome.hidden{display:none}
.welcome-icon{
  width:72px;height:72px;border-radius:20px;
  background:var(--grad);
  display:grid;place-items:center;
  font-size:28px;font-weight:800;color:#fff;
  box-shadow:0 0 60px rgba(110,110,245,.25);
  margin-bottom:22px;
}
#welcome h2{
  font-size:26px;font-weight:700;letter-spacing:-.4px;
  background:var(--grad);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
  margin-bottom:10px;
}
#welcome p{font-size:14px;color:var(--text-2);line-height:1.65;max-width:460px;margin-bottom:28px}
.example-chips{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;max-width:520px}
.example-chip{
  padding:8px 16px;border-radius:999px;
  background:var(--bg-3);border:1px solid var(--border);
  font-size:12.5px;color:var(--text-2);
  transition:all var(--dur) var(--ease);cursor:pointer;
}
.example-chip:hover{background:var(--bg-4);border-color:rgba(110,110,245,.4);color:var(--text)}

/* Message rows */
.msg-row{padding:6px 22px;display:flex;flex-direction:column;gap:0}
.msg-row:hover{background:rgba(255,255,255,.015)}
.msg-row.user{align-items:flex-end}
.msg-row.assistant{align-items:flex-start}
.msg-label{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--text-3);margin-bottom:5px;padding:0 2px}
.msg-bubble{
  max-width:76%;border-radius:var(--r-lg);
  padding:12px 16px;font-size:13.5px;line-height:1.65;
  word-break:break-word;
}
.msg-row.user .msg-bubble{
  background:rgba(110,110,245,.12);
  border:1px solid rgba(110,110,245,.22);
  color:var(--text);
}
.msg-row.assistant .msg-bubble{
  background:var(--bg-2);
  border:1px solid var(--border);
  color:var(--text-2);
  max-width:84%;
}
.msg-bubble.streaming{position:relative}
.msg-bubble.streaming::after{
  content:'';display:inline-block;width:2px;height:16px;
  background:var(--accent);vertical-align:text-bottom;margin-left:3px;
  animation:blink .7s step-end infinite;
}
@keyframes blink{50%{opacity:0}}

/* Tool events */
.tool-row{
  padding:3px 22px;
}
.tool-card{
  display:flex;align-items:center;gap:8px;
  padding:6px 12px;border-radius:var(--r);
  background:var(--bg-2);border:1px solid var(--border);
  font-size:12px;color:var(--text-3);
  max-width:84%;cursor:default;
}
.tool-card .tc-icon{font-size:14px;flex-shrink:0}
.tool-card .tc-name{font-weight:600;color:var(--text-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px}
.tool-card .tc-status{
  margin-left:auto;font-size:10px;padding:1px 8px;border-radius:999px;flex-shrink:0;
}
.tool-card .tc-status.running{background:rgba(110,110,245,.15);color:var(--accent)}
.tool-card .tc-status.done{background:rgba(0,201,184,.12);color:var(--accent-2)}
.tool-card .tc-status.error{background:rgba(240,89,106,.12);color:#F0596A}
.tool-card .tc-args{font-family:monospace;font-size:10.5px;color:var(--text-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:300px}

/* Error msg */
.error-row{
  padding:4px 22px;
}
.error-card{
  padding:10px 14px;border-radius:var(--r);
  background:rgba(240,89,106,.08);border:1px solid rgba(240,89,106,.2);
  font-size:12.5px;color:#F0596A;max-width:84%;
}

/* markdown in assistant bubbles */
.msg-bubble h1,.msg-bubble h2,.msg-bubble h3{font-weight:600;margin:12px 0 6px;letter-spacing:-.02em}
.msg-bubble h1{font-size:18px}.msg-bubble h2{font-size:15px}.msg-bubble h3{font-size:13.5px}
.msg-bubble p{margin-bottom:8px}.msg-bubble p:last-child{margin-bottom:0}
.msg-bubble ul,.msg-bubble ol{padding-left:22px;margin:8px 0}
.msg-bubble li{margin-bottom:5px;line-height:1.5}
.msg-bubble code{background:rgba(110,110,245,.1);padding:1px 6px;border-radius:4px;font-size:12.5px;color:#A5A5FF}
.msg-bubble pre{background:var(--bg-3);border:1px solid var(--border);border-radius:var(--r);padding:14px;overflow-x:auto;margin:10px 0}
.msg-bubble pre code{background:none;padding:0;font-size:12px;color:var(--text-2)}
.msg-bubble blockquote{border-left:3px solid var(--border);padding-left:12px;color:var(--text-3);margin:8px 0;font-style:italic}
.msg-bubble table{border-collapse:collapse;margin:8px 0;font-size:12.5px;width:100%}
.msg-bubble th,.msg-bubble td{border:1px solid var(--border);padding:6px 10px;text-align:left}
.msg-bubble th{background:var(--bg-3);font-weight:600}
.msg-bubble a{color:var(--accent);text-decoration:none}.msg-bubble a:hover{text-decoration:underline}

/* ── Input area ── */
#input-area{
  border-top:1px solid var(--border);
  padding:12px 22px 18px;
  background:var(--bg-2);
  flex-shrink:0;
}
#input-form{display:flex;gap:8px;align-items:flex-end}
#task-input{
  flex:1;
  background:var(--bg);border:1px solid var(--border);
  border-radius:var(--r-lg);padding:11px 16px;
  color:var(--text);font-size:14px;
  resize:none;font-family:inherit;line-height:1.5;
  min-height:44px;max-height:160px;
  transition:border-color var(--dur) var(--ease);
}
#task-input:focus{outline:none;border-color:rgba(110,110,245,.5);box-shadow:0 0 0 3px rgba(110,110,245,.08)}
#task-input::placeholder{color:var(--text-3)}
#task-input:disabled{opacity:.4}
#send-btn{
  background:var(--grad);color:#fff;border:none;
  border-radius:var(--r-lg);padding:0 22px;height:44px;
  font-size:13.5px;font-weight:600;white-space:nowrap;
  display:flex;align-items:center;gap:7px;
  box-shadow:0 3px 14px rgba(110,110,245,.3);
  transition:opacity var(--dur),transform var(--dur),box-shadow var(--dur);
}
#send-btn:hover:not(:disabled){opacity:.9;transform:translateY(-1px);box-shadow:0 5px 20px rgba(110,110,245,.38)}
#send-btn:active:not(:disabled){transform:scale(.97)}
#send-btn:disabled{opacity:.35;cursor:not-allowed}
#send-btn.stop{background:linear-gradient(135deg,#F0596A,#C0334A)}
#hint{font-size:11px;color:var(--text-3);margin-top:8px;text-align:center}

/* ── Scrollbar ── */
#messages-wrap::-webkit-scrollbar{width:4px}
#messages-wrap::-webkit-scrollbar-track{background:transparent}
#messages-wrap::-webkit-scrollbar-thumb{background:var(--bg-4);border-radius:999px}
#messages-wrap::-webkit-scrollbar-thumb:hover{background:var(--text-3)}

/* ── Responsive ── */
@media(max-width:640px){
  .msg-bubble{max-width:92%}
  #engine-bar{flex-wrap:wrap;gap:6px}
  #workspace-input{max-width:100%;flex:unset;width:100%}
}
</style>
</head>
<body>
<div id="app">

  <!-- Header -->
  <div id="header">
    <a id="back-btn" href="/">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
      Orchestra
    </a>
    <div class="miles-wordmark">
      <div class="miles-logo">M</div>
      <div>
        <div class="miles-name">M.I.L.E.S</div>
        <div class="miles-sub">Machine Intelligence Learning &amp; Execution System</div>
      </div>
    </div>
    <div id="status-pill">
      <div class="dot"></div>
      <span id="status-text">Ready</span>
    </div>
  </div>

  <!-- Engine bar -->
  <div id="engine-bar">
    <label>
      Engine:
      <select id="engine-select">
        <option value="claude_code">Claude Code</option>
        <option value="auto">Auto (Nemotron router)</option>
        <option value="codex">Codex</option>
      </select>
    </label>
    <label style="margin-left:12px;flex:1">
      Workspace:
      <input id="workspace-input" type="text" placeholder="path to project (leave blank for server default)" />
    </label>
  </div>

  <!-- Messages -->
  <div id="messages-wrap">
    <div id="messages">
      <!-- Welcome screen -->
      <div id="welcome">
        <div class="welcome-icon">M</div>
        <h2>Ask M.I.L.E.S</h2>
        <p>Your autonomous AI assistant, powered by Orchestra.<br>Give me any task — I'll plan, reason, and execute it using Claude Code.</p>
        <div class="example-chips">
          <button class="example-chip" onclick="setTask('Analyze this codebase and summarize its architecture')">Analyze codebase</button>
          <button class="example-chip" onclick="setTask('Fix any bugs you find in the current project')">Fix bugs</button>
          <button class="example-chip" onclick="setTask('Write unit tests for the main module')">Write tests</button>
          <button class="example-chip" onclick="setTask('Refactor the authentication module for clarity')">Refactor auth</button>
          <button class="example-chip" onclick="setTask('Generate a README for this project')">Generate README</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Input -->
  <div id="input-area">
    <form id="input-form" onsubmit="return false">
      <textarea id="task-input" rows="1" placeholder="Give M.I.L.E.S a task…"></textarea>
      <button id="send-btn" onclick="sendTask()">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
        Send
      </button>
    </form>
    <div id="hint">Enter to send &nbsp;·&nbsp; Shift+Enter for newline &nbsp;·&nbsp; Esc to stop</div>
  </div>

</div>

<script>
(function(){
  'use strict';

  // ── State ─────────────────────────────────────────────────────────────
  let activeTaskId = null;
  let activeSource = null;
  let streamingBubble = null;
  let streamingText = '';
  let sessionId = '';

  const wrap = document.getElementById('messages-wrap');
  const msgs = document.getElementById('messages');
  const welcome = document.getElementById('welcome');
  const taskInput = document.getElementById('task-input');
  const sendBtn = document.getElementById('send-btn');
  const statusPill = document.getElementById('status-pill');
  const statusText = document.getElementById('status-text');

  // ── Helpers ───────────────────────────────────────────────────────────
  function setStatus(state, text) {
    statusPill.className = state || '';
    statusText.textContent = text;
  }

  function scrollBottom() {
    wrap.scrollTop = wrap.scrollHeight;
  }

  function hideWelcome() {
    welcome.classList.add('hidden');
  }

  function autoGrow(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }

  function setTask(t) {
    taskInput.value = t;
    taskInput.focus();
    autoGrow(taskInput);
  }

  // ── Markdown ──────────────────────────────────────────────────────────
  function renderMd(text) {
    if (typeof marked === 'undefined') return escHtml(text);
    try {
      return marked.parse(text, {breaks: true, gfm: true});
    } catch(_) {
      return escHtml(text);
    }
  }

  function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── Append user message ───────────────────────────────────────────────
  function appendUser(text) {
    const row = document.createElement('div');
    row.className = 'msg-row user';
    row.innerHTML = `
      <div class="msg-label">You</div>
      <div class="msg-bubble">${escHtml(text)}</div>`;
    msgs.appendChild(row);
    scrollBottom();
  }

  // ── Start streaming assistant bubble ─────────────────────────────────
  function startAssistant() {
    const row = document.createElement('div');
    row.className = 'msg-row assistant';
    row.innerHTML = `
      <div class="msg-label">M.I.L.E.S</div>
      <div class="msg-bubble streaming"></div>`;
    msgs.appendChild(row);
    streamingBubble = row.querySelector('.msg-bubble');
    streamingText = '';
    scrollBottom();
    return streamingBubble;
  }

  function appendToStream(chunk) {
    if (!streamingBubble) startAssistant();
    streamingText += chunk;
    streamingBubble.innerHTML = renderMd(streamingText);
    scrollBottom();
  }

  function finalizeStream(text) {
    if (streamingBubble) {
      streamingBubble.classList.remove('streaming');
      if (text) {
        streamingText = text;
        streamingBubble.innerHTML = renderMd(text);
      } else if (streamingText) {
        streamingBubble.innerHTML = renderMd(streamingText);
      } else {
        streamingBubble.innerHTML = '';
      }
      streamingBubble = null;
      streamingText = '';
    }
  }

  function appendResult(text) {
    finalizeStream(text);
    const row = document.createElement('div');
    row.className = 'msg-row assistant';
    row.innerHTML = `
      <div class="msg-label">M.I.L.E.S</div>
      <div class="msg-bubble">${renderMd(text)}</div>`;
    msgs.appendChild(row);
    scrollBottom();
  }

  // ── Tool card ─────────────────────────────────────────────────────────
  const toolIcons = {
    Read:'📖', Write:'✏️', Edit:'✏️', Bash:'⚡', Glob:'🔍', Grep:'🔍',
    WebSearch:'🌐', WebFetch:'🌐', Agent:'🤖',
  };

  function appendTool(name, args, status) {
    const icon = toolIcons[name] || '🔧';
    let argsStr = '';
    if (args && typeof args === 'object') {
      const first = Object.values(args)[0];
      if (typeof first === 'string') argsStr = first.slice(0, 80);
    }
    const row = document.createElement('div');
    row.className = 'tool-row';
    row.dataset.toolRow = name;
    row.innerHTML = `
      <div class="tool-card">
        <span class="tc-icon">${icon}</span>
        <span class="tc-name">${escHtml(name)}</span>
        ${argsStr ? `<span class="tc-args">${escHtml(argsStr)}</span>` : ''}
        <span class="tc-status running">running</span>
      </div>`;
    msgs.appendChild(row);
    scrollBottom();
    return row;
  }

  // ── Error card ────────────────────────────────────────────────────────
  function appendError(msg) {
    const row = document.createElement('div');
    row.className = 'error-row';
    row.innerHTML = `<div class="error-card">⚠ ${escHtml(msg)}</div>`;
    msgs.appendChild(row);
    scrollBottom();
  }

  // ── SSE event handler ─────────────────────────────────────────────────
  function handleEvent(ev) {
    const data = ev.data;
    let msg;
    try { msg = JSON.parse(data); } catch(_) { return; }

    const t = msg.type;
    const d = msg.data || {};

    if (t === 'task_start') {
      setStatus('running', 'Thinking…');
      startAssistant();
    } else if (t === 'tool_start') {
      setStatus('running', escHtml(d.name || 'Working…'));
      appendTool(d.name || '?', d.input || {}, 'running');
    } else if (t === 'tool_result') {
      // Mark last tool row done
      const rows = msgs.querySelectorAll('.tool-row');
      if (rows.length) {
        const last = rows[rows.length - 1];
        const s = last.querySelector('.tc-status');
        if (s) { s.textContent = 'done'; s.className = 'tc-status done'; }
      }
    } else if (t === 'response' || t === 'text') {
      appendToStream(d.text || d.content || '');
    } else if (t === 'error') {
      appendError(d.message || 'Unknown error');
    } else if (t === 'done') {
      const result = d.result || '';
      if (result && result.trim() && result !== 'No output') {
        finalizeStream(result);
      } else {
        finalizeStream('');
      }
      if (d.claude_session_id) sessionId = d.claude_session_id;
      setStatus('done', d.agent ? 'Done · ' + d.agent : 'Done');
      setTimeout(() => setStatus('', 'Ready'), 3000);
      setSending(false);
      activeTaskId = null;
      activeSource = null;
    }
  }

  // ── Start task ────────────────────────────────────────────────────────
  async function sendTask() {
    if (activeTaskId) { cancelTask(); return; }
    const task = taskInput.value.trim();
    if (!task) return;

    hideWelcome();
    appendUser(task);
    taskInput.value = '';
    autoGrow(taskInput);
    setSending(true);
    setStatus('running', 'Starting…');

    const engine = document.getElementById('engine-select').value;
    const workspace = document.getElementById('workspace-input').value.trim();

    let resp;
    try {
      resp = await fetch('/api/chat/agentic', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          task,
          engine,
          workspace: workspace || '',
          session_id: sessionId,
          claude_session_id: sessionId,
        }),
      });
    } catch(e) {
      appendError('Failed to reach Orchestra API: ' + e.message);
      setSending(false);
      setStatus('', 'Ready');
      return;
    }

    if (!resp.ok) {
      appendError('API error: ' + resp.status);
      setSending(false);
      setStatus('', 'Ready');
      return;
    }

    const json = await resp.json();
    activeTaskId = json.task_id;

    const source = new EventSource('/api/chat/' + activeTaskId + '/stream');
    activeSource = source;

    source.onmessage = handleEvent;
    source.onerror = function() {
      source.close();
      if (activeTaskId) {
        finalizeStream('');
        appendError('Stream disconnected.');
        setSending(false);
        setStatus('', 'Ready');
        activeTaskId = null;
        activeSource = null;
      }
    };
  }

  function cancelTask() {
    if (!activeTaskId) return;
    if (activeSource) { activeSource.close(); activeSource = null; }
    fetch('/api/chat/' + activeTaskId + '/cancel', {method:'POST'}).catch(()=>{});
    activeTaskId = null;
    finalizeStream('');
    appendError('Task cancelled.');
    setSending(false);
    setStatus('', 'Ready');
  }

  function setSending(on) {
    taskInput.disabled = on;
    sendBtn.textContent = '';
    if (on) {
      sendBtn.className = 'stop';
      sendBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="2"/></svg> Stop';
      sendBtn.onclick = cancelTask;
    } else {
      sendBtn.className = '';
      sendBtn.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg> Send';
      sendBtn.onclick = sendTask;
    }
  }

  // ── Keyboard ──────────────────────────────────────────────────────────
  taskInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendTask(); }
    if (e.key === 'Escape') cancelTask();
  });
  taskInput.addEventListener('input', function() { autoGrow(this); });

  // Expose for example chips
  window.setTask = setTask;
  window.sendTask = sendTask;

})();
</script>
</body>
</html>"""
