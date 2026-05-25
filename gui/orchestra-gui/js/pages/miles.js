// M.I.L.E.S — Machine Intelligence Learning and Execution System
(function () {
  const { icons } = window;

  // ── State ─────────────────────────────────────────────────────────────────
  const state = {
    messages: [],
    context: { calendar: true, slack: true, memory: true, email: true },
    model: 'kimi-k2.5',
    modelOpen: false,
    isTyping: false,
    activeTab: 'chat',        // 'chat' | 'history' | 'patterns'
    liveEvents: [],
    composerValue: '',
    micActive: false,
  };

  // ── Data ──────────────────────────────────────────────────────────────────

  const MODELS = [
    { id: 'kimi-k2.5',    name: 'Kimi K2.5',    desc: '1M context · reasoning', selected: true },
    { id: 'claude-opus',  name: 'Claude Opus 4', desc: 'Best for complex tasks' },
    { id: 'gpt-5',        name: 'GPT-5.4',       desc: 'Fast · general purpose' },
    { id: 'gemma-4',      name: 'Gemma 4 Pro',   desc: 'Local fallback' },
  ];

  const CHANNELS = [
    { id: 'slack',     name: 'Slack',     icon: 'slack',    status: 'online',         detail: '#orchestra-ops',       color: '#34D399' },
    { id: 'gmail',     name: 'Gmail',     icon: 'mail',     status: 'online',         detail: 'ashton@orchestra.ai',  color: '#34D399' },
    { id: 'telegram',  name: 'Telegram',  icon: 'chat',     status: 'polling',        detail: 'Long-poll active',     color: '#F5B971' },
    { id: 'whatsapp',  name: 'WhatsApp',  icon: 'send',     status: 'webhook',        detail: 'Webhook ready',        color: '#F5B971' },
    { id: 'instagram', name: 'Instagram', icon: 'star',     status: 'unconfigured',   detail: 'Token required',       color: 'var(--text-3)' },
    { id: 'imessage',  name: 'iMessage',  icon: 'chat',     status: 'unconfigured',   detail: 'macOS only',           color: 'var(--text-3)' },
  ];

  const CONTEXT_CHIPS = [
    { id: 'calendar', label: 'Calendar', icon: 'calendar' },
    { id: 'slack',    label: 'Slack',    icon: 'slack' },
    { id: 'memory',   label: 'Memory',   icon: 'sparkles' },
    { id: 'email',    label: 'Email',    icon: 'mail' },
  ];

  const TODAY_SCHEDULE = [
    { time: '9:00 AM',  title: 'Eng standup',                  dur: '30m',  type: 'meeting', done: true  },
    { time: '10:00 AM', title: 'Eng sync',                      dur: '35m',  type: 'meeting', done: true  },
    { time: '2:30 PM',  title: 'NorthPeak negotiation call',    dur: '60m',  type: 'meeting', done: false },
    { time: '4:00 PM',  title: '1:1 with Jordan',               dur: '30m',  type: 'meeting', done: false },
    { time: '5:00 PM',  title: 'Submit weekly KPI pack',        dur: null,   type: 'task',    done: false },
  ];

  const LEARNED_PATTERNS = [
    { icon: 'clock',    text: 'Checks tasks first thing at 9 AM, 4 days a week.' },
    { icon: 'calendar', text: 'Monday mornings: planning mode. Prefers no interruptions.' },
    { icon: 'file',     text: 'Prefers bullet summaries over long-form paragraphs.' },
    { icon: 'activity', text: 'Responds to contract flags within 12 minutes on average.' },
    { icon: 'star',     text: 'Most productive window: 10 AM – 1 PM CT.' },
  ];

  const INITIAL_LIVE_EVENTS = [
    { icon: 'medical', color: '#F0596A', text: 'OncoNavigator completed trial matching', age: 0 },
    { icon: 'truck',   color: '#6E6EF5', text: 'RouteOptimizer reshaped Tuesday cluster', age: 9 },
    { icon: 'shield',  color: '#34D399', text: 'KYCSentinel cleared 147 counterparties', age: 21 },
    { icon: 'file',    color: '#F5B971', text: 'ContractReview flagged 3 risks in NorthPeak MSA', age: 35 },
  ];

  // ── Pre-loaded conversation ───────────────────────────────────────────────

  function buildInitialMessages() {
    const name = window.MOCK.user.name.split(' ')[0];
    return [
      // MILES greeting + proactive alert
      {
        role: 'assistant', time: '9:02 AM',
        blocks: [
          { type: 'md', content: `Good morning, **${name}**. I'm M.I.L.E.S — your personal AI assistant powered by Claude Code.\n\nI've scanned your calendar, email, Slack, and active agents. Here's what needs your attention today:` },
          {
            type: 'alert-cards',
            cards: [
              { level: 'critical', icon: 'file',    color: '#F0596A', title: 'T-7024 failed overnight',       body: 'MSA redline crashed at parse step. Schema fix available — 1-click retry.' },
              { level: 'high',     icon: 'shield',  color: '#F5B971', title: 'KYCSentinel flagged GR-884',    body: 'PEP match detected. Review required before 2:30 PM NorthPeak call.' },
              { level: 'info',     icon: 'calendar',color: '#6E6EF5', title: 'NorthPeak call in 5h 28m',      body: 'Prep note from last session ready. ContractReview has rev 7 redlines.' },
            ],
          },
          { type: 'action-row', actions: [
            { label: 'Retry T-7024',       style: 'primary', key: 'retry-task' },
            { label: 'Review KYC flag',    style: 'ghost',   key: 'review-kyc' },
            { label: 'Open prep note',     style: 'ghost',   key: 'open-prep' },
          ]},
        ],
      },
      // User asks for briefing
      {
        role: 'user', time: '9:03 AM',
        text: 'Give me a full morning briefing.',
      },
      // MILES full briefing response
      {
        role: 'assistant', time: '9:03 AM',
        blocks: [
          { type: 'tool-calls', calls: [
            { icon: 'calendar', label: 'Reading calendar (today)',         state: 'done' },
            { icon: 'mail',     label: 'Scanning inbox (last 12 hours)',   state: 'done' },
            { icon: 'slack',    label: 'Summarizing #orchestra-ops',       state: 'done' },
            { icon: 'activity', label: 'Polling agent health',             state: 'done' },
          ]},
          { type: 'md', content: `## Morning Briefing — Monday, May 19\n\n**Calendar (4 events)**\n- 9:00 AM ✓ Eng standup\n- 10:00 AM ✓ Eng sync\n- 2:30 PM NorthPeak negotiation — prep required\n- 4:00 PM 1:1 with Jordan\n\n**Active agents (3 running)**\n- RouteOptimizer · T-7041 · ETA 1m 20s\n- GenomIX · T-7042 · ETA 4m 10s\n- ContractReview · T-7043 · ETA 20s ← nearly done\n\n**Inbox (2 unread flagged)**\n- Jordan: "Can we move prep notes to 1pm?" → I can draft a reply.\n- NorthPeak legal: Rev 7 attached — ContractReview already scanning.\n\n**Slack (3 threads need response)**\n- #engineering: PR #2041 approved, merge blocked on CI\n- #legal: counterparty list from KYC team\n- #ops: Line B downtime escalation (LineTwin predicted 4h)\n\n**What I'd focus on first:** Retry T-7024 before the 2:30 call — ContractReview will have redlines ready in time.` },
        ],
      },
    ];
  }

  // ── Renderers ─────────────────────────────────────────────────────────────

  function escapeHTML(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function nowStr() {
    return new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  }

  // Markdown: headers, bold, code, lists, hr, line breaks
  function md(text) {
    return escapeHTML(text)
      .replace(/^## (.+)$/gm, '<div class="md-h2">$1</div>')
      .replace(/^### (.+)$/gm, '<div class="md-h3">$1</div>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/^---$/gm, '<hr class="md-hr"/>')
      .replace(/^[-•] (.+)$/gm, '<div class="md-li">$1</div>')
      .replace(/\n\n/g, '<div class="md-gap"></div>')
      .replace(/\n/g, '<br>');
  }

  function renderBlock(block) {
    switch (block.type) {
      case 'md': return `<div class="miles-block miles-block--md">${md(block.content)}</div>`;

      case 'tool-calls': return `
        <div class="miles-block miles-block--tools">
          ${block.calls.map(c => `
            <div class="tool-call tool-call--${c.state}">
              <span class="tc-icon" style="color:${c.state==='done'?'var(--success)':c.state==='working'?'var(--accent)':'var(--text-3)'}">
                ${icons[c.icon] ? icons[c.icon](12) : icons.sparkles(12)}
              </span>
              <span class="tc-label">${escapeHTML(c.label)}</span>
              <span class="tc-state">
                ${c.state==='done'
                  ? `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2.5"><path d="M20 6 9 17l-5-5"/></svg>`
                  : c.state==='working'
                  ? `<span class="tc-spin"></span>`
                  : `<span style="width:8px;height:8px;border-radius:999px;background:var(--bg-4);display:block"></span>`}
              </span>
            </div>`).join('')}
        </div>`;

      case 'alert-cards': return `
        <div class="miles-block miles-block--alerts">
          ${block.cards.map(c => `
            <div class="alert-card alert-card--${c.level}">
              <div class="alert-card__icon" style="color:${c.color}">
                ${icons[c.icon] ? icons[c.icon](14) : icons.sparkles(14)}
              </div>
              <div class="alert-card__body">
                <div class="alert-card__title">${escapeHTML(c.title)}</div>
                <div class="alert-card__text">${escapeHTML(c.body)}</div>
              </div>
              <div class="alert-card__level">${c.level}</div>
            </div>`).join('')}
        </div>`;

      case 'action-row': return `
        <div class="miles-block miles-block--actions">
          ${block.actions.map(a => `
            <button class="miles-action-btn miles-action-btn--${a.style}" data-miles-action-key="${a.key}">
              ${escapeHTML(a.label)}
            </button>`).join('')}
        </div>`;

      case 'thinking': return `
        <div class="miles-block miles-block--thinking">
          <span class="thinking-dot"></span>
          <span class="thinking-text">${escapeHTML(block.text)}</span>
        </div>`;

      default: return '';
    }
  }

  function renderMessage(msg) {
    if (msg.role === 'user') {
      return `
        <div class="miles-msg miles-msg--user">
          <div class="miles-msg__body">
            <div class="miles-msg__bubble">${md(msg.text || '')}</div>
            <div class="miles-msg__meta">${escapeHTML(msg.time || nowStr())}</div>
          </div>
          <div class="miles-msg__avatar miles-msg__avatar--user">${escapeHTML(window.MOCK.user.initials)}</div>
        </div>`;
    }
    return `
      <div class="miles-msg miles-msg--assistant">
        <div class="miles-msg__avatar">
          ${milesAvatarSVG(18)}
        </div>
        <div class="miles-msg__body">
          ${(msg.blocks || []).map(renderBlock).join('')}
          <div class="miles-msg__meta">${escapeHTML(msg.time || nowStr())}</div>
        </div>
      </div>`;
  }

  function milesAvatarSVG(size = 18) {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none">
      <defs><linearGradient id="mav" x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
        <stop stop-color="#8282F7"/><stop offset="1" stop-color="#00C9B8"/>
      </linearGradient></defs>
      <path d="M12 3l2.3 5.2L20 9l-4 3.9.9 5.6L12 15.9 7.1 18.5 8 12.9 4 9l5.7-.8L12 3z"
        stroke="url(#mav)" stroke-width="1.7" stroke-linejoin="round"/>
      <circle cx="12" cy="11" r="2" fill="url(#mav)"/>
    </svg>`;
  }

  // ── Full page render ──────────────────────────────────────────────────────

  function render() {
    return `
      <div class="page page--miles">

        <!-- ── Header ─────────────────────────────────── -->
        <div class="mp-header">
          <div class="mp-header__left">
            <div class="mp-hero-icon" data-miles-pulse>
              <svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 24 24" fill="none">
                <defs><linearGradient id="mh1" x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
                  <stop stop-color="#8282F7"/><stop offset="1" stop-color="#00C9B8"/>
                </linearGradient></defs>
                <path d="M12 3l2.3 5.2L20 9l-4 3.9.9 5.6L12 15.9 7.1 18.5 8 12.9 4 9l5.7-.8L12 3z"
                  stroke="url(#mh1)" stroke-width="1.7" stroke-linejoin="round"/>
                <circle cx="12" cy="11" r="2" fill="url(#mh1)"/>
              </svg>
            </div>
            <div>
              <div class="mp-header__name">
                M.I.L.E.S
                <span class="mp-status"><span class="dot online"></span>Online</span>
              </div>
              <div class="mp-header__sub">Machine Intelligence Learning and Execution System</div>
            </div>
          </div>
          <div class="mp-header__right">
            <div class="mp-cc-badge">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/></svg>
              Powered by Claude Code
            </div>
            <div class="mp-header__stats">
              <div class="mp-stat"><span class="mp-stat__val">${window.MOCK.agents.length}</span><span class="mp-stat__lbl">agents</span></div>
              <div class="mp-stat-div"></div>
              <div class="mp-stat"><span class="mp-stat__val">${window.MOCK.runningTasks.length}</span><span class="mp-stat__lbl">running</span></div>
              <div class="mp-stat-div"></div>
              <div class="mp-stat"><span class="mp-stat__val">${CHANNELS.filter(c=>c.status!=='unconfigured').length}</span><span class="mp-stat__lbl">channels</span></div>
            </div>
            <button class="btn btn--ghost btn--sm" data-goto="#/settings">${icons.settings(13)} Configure</button>
          </div>
        </div>

        <!-- ── Body ───────────────────────────────────── -->
        <div class="mp-body">

          <!-- LEFT: Chat ────────────────────────────── -->
          <div class="mp-chat">

            <!-- Tabs -->
            <div class="mp-tabs">
              <button class="mp-tab ${state.activeTab==='chat'?'is-active':''}" data-tab="chat">
                ${icons.chat(13)} Conversation
              </button>
              <button class="mp-tab ${state.activeTab==='history'?'is-active':''}" data-tab="history">
                ${icons.clock(13)} History
              </button>
              <button class="mp-tab ${state.activeTab==='patterns'?'is-active':''}" data-tab="patterns">
                ${icons.sparkles(13)} Learned
              </button>
              <div class="mp-tabs__spacer"></div>
              <button class="mp-tab-action" data-action="clear-chat">${icons.trash(12)} Clear</button>
            </div>

            <!-- Tab panels -->
            <div class="mp-tab-content" data-tab-content>
              ${renderTabContent()}
            </div>

            <!-- Composer (always visible) -->
            ${renderComposer()}
          </div>

          <!-- RIGHT: Info panel ─────────────────────── -->
          <div class="mp-panel">

            <!-- Live activity -->
            <div class="mp-section">
              <div class="mp-section__head">
                <span class="mp-section__live"><span class="dot online"></span> Live</span>
                Agent activity
              </div>
              <div class="mp-live-feed" data-live-feed>
                ${renderLiveFeed()}
              </div>
            </div>

            <!-- Today's schedule -->
            <div class="mp-section">
              <div class="mp-section__head">${icons.calendar(12)} Today</div>
              <div class="mp-schedule">
                ${TODAY_SCHEDULE.map(e => `
                  <div class="mp-sched-row ${e.done?'is-done':''}">
                    <div class="mp-sched-time">${e.time}</div>
                    <div class="mp-sched-dot ${e.type==='task'?'mp-sched-dot--task':''}"></div>
                    <div class="mp-sched-body">
                      <div class="mp-sched-title">${escapeHTML(e.title)}</div>
                      ${e.dur ? `<div class="mp-sched-meta">${e.dur}</div>` : ''}
                    </div>
                  </div>`).join('')}
              </div>
            </div>

            <!-- Channels -->
            <div class="mp-section">
              <div class="mp-section__head">
                ${icons.coord(12)} Channels
                <span class="badge badge--success" style="margin-left:auto;font-size:10px">
                  ${CHANNELS.filter(c=>c.status!=='unconfigured').length} active
                </span>
              </div>
              <div class="mp-channels">
                ${CHANNELS.map(ch => `
                  <div class="mp-ch-row" title="${escapeHTML(ch.detail)}">
                    <span class="mp-ch-icon" style="color:${ch.color}">
                      ${icons[ch.icon] ? icons[ch.icon](13) : icons.chat(13)}
                    </span>
                    <span class="mp-ch-name">${ch.name}</span>
                    <span class="mp-ch-status">
                      ${ch.status==='online'
                        ? `<span class="dot online"></span>`
                        : ch.status==='polling'
                        ? `<span class="dot warn" style="animation:blink 2s infinite"></span>`
                        : ch.status==='webhook'
                        ? `<span style="font-size:9px;color:var(--warn);font-weight:600">WH</span>`
                        : `<span style="font-size:9px;color:var(--text-3)">—</span>`}
                    </span>
                  </div>`).join('')}
              </div>
            </div>

          </div>
        </div>
      </div>
    `;
  }

  function renderTabContent() {
    if (state.activeTab === 'chat') {
      return `
        <div class="mp-messages" data-messages>
          ${state.messages.map(renderMessage).join('')}
          <div class="mp-typing" data-typing style="display:none">
            <div class="mp-typing__avatar">${milesAvatarSVG(14)}</div>
            <div class="mp-typing__dots"><span></span><span></span><span></span></div>
          </div>
        </div>`;
    }
    if (state.activeTab === 'history') {
      return `
        <div class="mp-history">
          ${[
            { date: 'Today',      summary: 'Morning briefing, T-7024 retry, NorthPeak prep',        msgs: 6  },
            { date: 'Yesterday',  summary: 'KYC batch review, Week 48 rotation, Line B forecast',   msgs: 12 },
            { date: 'Friday',     summary: 'KPI pack generation, MSA rev 6 review, Slack digest',    msgs: 9  },
            { date: 'Thursday',   summary: 'Route optimization, variant pipeline run',               msgs: 7  },
            { date: 'Wednesday',  summary: 'AML screening batch, clinic scheduler config',           msgs: 14 },
          ].map((h, i) => `
            <div class="mp-history-row" data-history-idx="${i}">
              <div class="mp-history-date">${h.date}</div>
              <div class="mp-history-summary">${escapeHTML(h.summary)}</div>
              <div class="mp-history-meta">${h.msgs} messages</div>
            </div>`).join('')}
        </div>`;
    }
    if (state.activeTab === 'patterns') {
      return `
        <div class="mp-patterns">
          <div class="mp-patterns__header">
            <div class="mp-patterns__title">What M.I.L.E.S has learned about you</div>
            <div class="mp-patterns__sub">Behavioral patterns observed across ${window.MOCK.agents.length} sessions</div>
          </div>
          ${LEARNED_PATTERNS.map(p => `
            <div class="mp-pattern-row">
              <div class="mp-pattern-icon">${icons[p.icon] ? icons[p.icon](14) : icons.sparkles(14)}</div>
              <div class="mp-pattern-text">${escapeHTML(p.text)}</div>
            </div>`).join('')}
          <div class="mp-patterns__footer">
            <button class="btn btn--ghost btn--sm" style="width:100%;justify-content:center">
              ${icons.refresh(12)} Re-analyze patterns
            </button>
          </div>
        </div>`;
    }
    return '';
  }

  function renderComposer() {
    const activeCtx = Object.entries(state.context).filter(([,v])=>v).map(([k])=>k);
    const model = MODELS.find(m => m.id === state.model) || MODELS[0];
    return `
      <div class="mp-composer">
        <!-- Context chips -->
        <div class="mp-ctx-chips">
          ${CONTEXT_CHIPS.map(c => `
            <button class="mp-ctx-chip ${state.context[c.id]?'is-on':''}" data-ctx="${c.id}" title="${c.label}">
              ${icons[c.icon] ? icons[c.icon](11) : icons.sparkles(11)}
              ${c.label}
            </button>`).join('')}
          <div style="flex:1"></div>
          <div class="mp-model-picker ${state.modelOpen?'is-open':''}" data-model-root>
            <button class="mp-model-btn" data-toggle-model>
              ${icons.sparkles(11)} ${escapeHTML(model.name)}
              ${icons.chevronDown(10)}
            </button>
            ${state.modelOpen ? `
              <div class="mp-model-menu">
                ${MODELS.map(m => `
                  <div class="mp-model-item ${m.id===state.model?'is-active':''}" data-pick-model="${m.id}">
                    <div>
                      <div class="mp-model-name">${escapeHTML(m.name)}</div>
                      <div class="mp-model-desc">${escapeHTML(m.desc)}</div>
                    </div>
                    ${m.id===state.model ? `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2.5"><path d="M20 6 9 17l-5-5"/></svg>` : ''}
                  </div>`).join('')}
              </div>` : ''}
          </div>
        </div>

        <!-- Input row -->
        <div class="mp-composer__box">
          <textarea
            class="mp-composer__input"
            data-miles-input
            placeholder="Ask M.I.L.E.S anything… (Enter to send, Shift+Enter for newline)"
            rows="1"
          ></textarea>
          <div class="mp-composer__btns">
            <button class="mp-mic-btn ${state.micActive?'is-active':''}" data-mic-btn title="Voice input">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round">
                <rect x="9" y="2" width="6" height="12" rx="3"/>
                <path d="M5 10a7 7 0 0 0 14 0M12 19v3M9 22h6"/>
              </svg>
            </button>
            <button class="mp-send-btn" data-miles-send title="Send (Enter)">
              ${icons.send(14)}
            </button>
          </div>
        </div>
        <div class="mp-composer__footer">
          <span>M.I.L.E.S uses ${escapeHTML(activeCtx.join(', '))} as context</span>
          <span><kbd>Enter</kbd> send · <kbd>⌘M</kbd> focus · <kbd>⌘K</kbd> search</span>
        </div>
      </div>
    `;
  }

  function renderLiveFeed() {
    return state.liveEvents.slice(0, 4).map(e => `
      <div class="mp-live-row">
        <div class="mp-live-icon" style="color:${e.color}">
          ${icons[e.icon] ? icons[e.icon](12) : icons.sparkles(12)}
        </div>
        <div class="mp-live-text">${escapeHTML(e.text)}</div>
        <div class="mp-live-age">${e.age === 0 ? 'now' : e.age + 'm'}</div>
      </div>`).join('');
  }

  // ── Response engine ───────────────────────────────────────────────────────

  const QUICK_RESPONSES = {
    brief: {
      blocks: [
        { type: 'tool-calls', calls: [
          { icon: 'calendar', label: 'Reading calendar',     state: 'done' },
          { icon: 'mail',     label: 'Scanning inbox',       state: 'done' },
          { icon: 'activity', label: 'Polling agent health', state: 'done' },
        ]},
        { type: 'md', content: `## Morning Briefing\n\n**2 urgent items** need your attention before the 2:30 PM call.\n\n- T-7024 failed at parse step — schema fix is ready\n- KYCSentinel flagged GR-884 as a PEP match\n\n**3 agents running:** RouteOptimizer, GenomIX, ContractReview.\n\n**Recommendation:** Retry T-7024 now (< 1 min) so redlines are ready for NorthPeak.` },
        { type: 'action-row', actions: [
          { label: 'Retry T-7024', style: 'primary', key: 'retry-task' },
          { label: 'Full detail',  style: 'ghost',   key: 'full-brief' },
        ]},
      ],
    },
    remind: {
      blocks: [
        { type: 'md', content: `## Active Reminders\n\n**🔴 [CRITICAL]** NorthPeak negotiation prep\nEmail Jordan with revision notes before 1:00 PM or you'll walk in blind.\n\n**🟠 [HIGH]** Weekly KPI pack\nDue today at 5:00 PM. I can generate it in 30 seconds.\n\n**🟡 [MEDIUM]** GenomIX requeue\nBatch CG-882-A needs a re-run after midnight quota reset.` },
        { type: 'action-row', actions: [
          { label: 'Generate KPI pack', style: 'primary', key: 'gen-kpi' },
          { label: 'Draft Jordan email', style: 'ghost',  key: 'draft-email' },
        ]},
      ],
    },
    suggest: {
      blocks: [
        { type: 'md', content: `## Suggested Focus\n\n**[HIGH]** Retry MSA redline (T-7024)\nKnown bug patched 2h ago. Retry takes ~1 minute.\n\n**[HIGH]** Consolidate 3 oncology trials\nNCT-4401, NCT-4489, and NCT-4521 overlap for cohort 2041. Saves ~6 weeks of enrollment.\n\n**[MEDIUM]** Export KPI pack before 2:30 PM call\nFresh numbers could strengthen your NorthPeak position.\n\n**[LOW]** Add NOAA weather overlay to GridSense\nTuesday forecast is +7% demand but no weather layer is configured.` },
      ],
    },
    channels: {
      blocks: [
        {
          type: 'alert-cards',
          cards: [
            { level: 'info',    icon: 'slack', color: '#34D399', title: 'Slack · online',         body: '3 threads need response in #engineering, #legal, #ops.' },
            { level: 'info',    icon: 'mail',  color: '#34D399', title: 'Gmail · online',          body: '2 unread flagged — Jordan + NorthPeak legal.' },
            { level: 'info',    icon: 'chat',  color: '#F5B971', title: 'Telegram · polling',      body: 'Long-poll active. 0 new messages.' },
            { level: 'info',    icon: 'send',  color: '#F5B971', title: 'WhatsApp · webhook ready', body: 'Set WHATSAPP_TOKEN + PHONE_ID to go live.' },
          ],
        },
        { type: 'md', content: 'Run `horizon miles channels start --slack --telegram` to begin polling. Add users with `horizon miles channels opt-in <channel> <id>`.' },
      ],
    },
    default: {
      blocks: [
        { type: 'thinking', text: 'Checking context across calendar, Slack, and active tasks…' },
        { type: 'md', content: `I've reviewed your current context. Here's what's most relevant:\n\n- **3 agents running** — all progressing normally\n- **2 urgent items** flagged since this morning\n- **Next meeting** in 5h 28m (NorthPeak — prep available)\n\nWhat would you like to dig into? I can help with tasks, agents, channels, or anything in your workflow.` },
      ],
    },
  };

  function detectIntent(text) {
    const t = text.toLowerCase();
    if (/brief|briefing|morning|today|schedule|summary/.test(t))   return 'brief';
    if (/remind|reminder|due|deadline|urgent/.test(t))              return 'remind';
    if (/suggest|focus|priorit|recommend|what should|what next/.test(t)) return 'suggest';
    if (/channel|slack|telegram|gmail|whatsapp|instagram|ingest/.test(t)) return 'channels';
    return 'default';
  }

  // ── Mount & wire ──────────────────────────────────────────────────────────

  let liveInterval = null;

  function mount(root) {
    injectStyles();
    state.messages = buildInitialMessages();
    state.liveEvents = [...INITIAL_LIVE_EVENTS];
    root.innerHTML = render();
    wireAll(root);
    scrollToBottom();

    // Tick live feed every 8 seconds
    liveInterval = setInterval(() => tickLiveFeed(root), 8000);

    // Probe API connection and update status badge
    if (typeof window.OrchestraAPI !== 'undefined') {
      window.OrchestraAPI.ping().then(ok => {
        const badge = root.querySelector('.mp-cc-badge');
        if (!badge) return;
        if (ok) {
          badge.style.borderColor = 'rgba(52,211,153,0.35)';
          badge.style.color = '#34D399';
          badge.innerHTML = badge.innerHTML.replace('Powered by Claude Code', 'Connected · Claude Code');
        } else {
          badge.style.borderColor = 'rgba(240,89,106,0.3)';
          badge.style.color = 'var(--danger)';
          badge.innerHTML = badge.innerHTML.replace('Powered by Claude Code', 'API offline · mock mode');
        }
      });
    }
  }

  function unmount() {
    if (liveInterval) { clearInterval(liveInterval); liveInterval = null; }
  }

  function wireAll(root) {
    // Tabs
    root.querySelectorAll('[data-tab]').forEach(btn => {
      btn.addEventListener('click', () => {
        state.activeTab = btn.dataset.tab;
        rerender(root);
      });
    });

    // Clear chat
    root.querySelector('[data-action="clear-chat"]')?.addEventListener('click', () => {
      state.messages = [];
      state.activeTab = 'chat';
      rerender(root);
      window.Orchestra.toast('Conversation cleared', 'info');
    });

    // Context chips
    root.querySelectorAll('[data-ctx]').forEach(btn => {
      btn.addEventListener('click', () => {
        const k = btn.dataset.ctx;
        state.context[k] = !state.context[k];
        rerenderComposer(root);
      });
    });

    // Model picker toggle
    root.querySelector('[data-toggle-model]')?.addEventListener('click', (e) => {
      e.stopPropagation();
      state.modelOpen = !state.modelOpen;
      rerenderComposer(root);
    });
    root.querySelectorAll('[data-pick-model]').forEach(item => {
      item.addEventListener('click', () => {
        state.model = item.dataset.pickModel;
        state.modelOpen = false;
        rerenderComposer(root);
        window.Orchestra.toast(`Model: ${MODELS.find(m=>m.id===state.model)?.name}`, 'info');
      });
    });
    document.addEventListener('click', (e) => {
      if (state.modelOpen && !e.target.closest('[data-model-root]')) {
        state.modelOpen = false;
        rerenderComposer(root);
      }
    });

    // Mic button
    root.querySelector('[data-mic-btn]')?.addEventListener('click', () => {
      state.micActive = !state.micActive;
      rerenderComposer(root);
      if (state.micActive) window.Orchestra.toast('Voice input active (demo)', 'info');
    });

    // Composer input
    wireComposerInput(root);

    // History row clicks
    root.querySelectorAll('[data-history-idx]').forEach(row => {
      row.addEventListener('click', () => {
        window.Orchestra.toast('Loading session history…', 'info');
      });
    });

    // Pattern re-analyze
    root.querySelectorAll('.mp-patterns__footer .btn').forEach(btn => {
      btn.addEventListener('click', () => window.Orchestra.toast('Re-analyzing patterns…', 'info'));
    });

    // Action buttons (accept/dismiss cards)
    wireActionButtons(root);

    // Settings goto
    root.querySelector('[data-goto="#/settings"]')?.addEventListener('click', () => {
      location.hash = '#/settings';
    });
  }

  function wireComposerInput(root) {
    const input = root.querySelector('[data-miles-input]');
    const send  = root.querySelector('[data-miles-send]');
    if (!input) return;

    input.addEventListener('input', () => {
      state.composerValue = input.value;
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 130) + 'px';
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.shiftKey) {
        e.preventDefault();
        const s = input.selectionStart, end = input.selectionEnd;
        input.value = input.value.slice(0, s) + '\n' + input.value.slice(end);
        input.selectionStart = input.selectionEnd = s + 1;
        state.composerValue = input.value;
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 130) + 'px';
      } else if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend(root);
      }
    });
    send?.addEventListener('click', () => handleSend(root));
  }

  function wireActionButtons(root) {
    root.querySelectorAll('[data-miles-action-key]').forEach(btn => {
      btn.addEventListener('click', () => {
        const key = btn.dataset.milesActionKey;
        const messages = {
          'retry-task':   'Retrying T-7024 — ContractReview agent queued.',
          'review-kyc':   'Opening KYC flag for GR-884…',
          'open-prep':    'Opening NorthPeak prep note…',
          'full-brief':   'Loading full briefing…',
          'gen-kpi':      'Generating weekly KPI pack — ETA 30s.',
          'draft-email':  'Drafting email to Jordan…',
        };
        window.Orchestra.toast(messages[key] || `Action: ${key}`, 'success');
        btn.disabled = true;
        btn.style.opacity = '0.5';
      });
    });
  }

  function handleSend(root) {
    const text = (state.composerValue || '').trim();
    if (!text || state.isTyping) return;
    state.composerValue = '';
    state.messages.push({ role: 'user', text, time: nowStr() });
    state.activeTab = 'chat';
    state.isTyping = true;
    rerender(root);
    scrollToBottom();

    const typingEl = root.querySelector('[data-typing]');
    if (typingEl) typingEl.style.display = 'flex';

    // Pulse the header icon while thinking
    root.querySelector('[data-miles-pulse]')?.classList.add('is-thinking');

    // Try real API first, fall back to mock on failure
    const apiAvailable = typeof window.OrchestraAPI !== 'undefined';

    if (apiAvailable) {
      const modelId = window.OrchestraAPI.resolveModel(state.model);
      const activeCtx = Object.entries(state.context).filter(([,v])=>v).map(([k])=>k);
      const systemNote = activeCtx.length
        ? `Active context sources: ${activeCtx.join(', ')}.`
        : '';

      window.OrchestraAPI.query(text, { model: modelId, system: `You are M.I.L.E.S — a concise, intelligent executive assistant powered by Orchestra. Give direct, actionable responses. Use markdown for structure. ${systemNote}`.trim() })
        .then(response => {
          state.isTyping = false;
          root.querySelector('[data-miles-pulse]')?.classList.remove('is-thinking');
          state.messages.push({
            role: 'assistant',
            time: nowStr(),
            blocks: [{ type: 'md', content: response }],
          });
          rerenderMessages(root);
          wireActionButtons(root);
          scrollToBottom();
        })
        .catch(err => {
          state.isTyping = false;
          root.querySelector('[data-miles-pulse]')?.classList.remove('is-thinking');
          // Fall back to mock response with error notice
          const intent = detectIntent(text);
          const response = QUICK_RESPONSES[intent] || QUICK_RESPONSES.default;
          state.messages.push({
            role: 'assistant',
            time: nowStr(),
            blocks: [
              { type: 'thinking', text: `API unavailable (${err.message}) — showing cached response.` },
              ...response.blocks,
            ],
          });
          rerenderMessages(root);
          wireActionButtons(root);
          scrollToBottom();
        });
    } else {
      // No API client loaded — use mock
      const delay = 800 + Math.random() * 700;
      setTimeout(() => {
        state.isTyping = false;
        root.querySelector('[data-miles-pulse]')?.classList.remove('is-thinking');
        const intent = detectIntent(text);
        const response = QUICK_RESPONSES[intent] || QUICK_RESPONSES.default;
        state.messages.push({ role: 'assistant', time: nowStr(), blocks: response.blocks });
        rerenderMessages(root);
        wireActionButtons(root);
        scrollToBottom();
      }, delay);
    }
  }

  // ── Partial re-renders ────────────────────────────────────────────────────

  function rerender(root) {
    const tabContent = root.querySelector('[data-tab-content]');
    const composer   = root.querySelector('.mp-composer');

    // Update tab buttons
    root.querySelectorAll('[data-tab]').forEach(btn => {
      btn.classList.toggle('is-active', btn.dataset.tab === state.activeTab);
    });

    if (tabContent) {
      tabContent.innerHTML = renderTabContent();
      wireComposerInput(root);
      wireActionButtons(root);
      root.querySelectorAll('[data-history-idx]').forEach(row => {
        row.addEventListener('click', () => window.Orchestra.toast('Loading session history…', 'info'));
      });
      root.querySelectorAll('.mp-patterns__footer .btn').forEach(btn => {
        btn.addEventListener('click', () => window.Orchestra.toast('Re-analyzing patterns…', 'info'));
      });
    }
    if (composer) {
      const tmp = document.createElement('div');
      tmp.innerHTML = renderComposer();
      composer.replaceWith(tmp.firstElementChild);
      wireComposerInput(root);
      wireContextChips(root);
      wireModelPicker(root);
      root.querySelector('[data-mic-btn]')?.addEventListener('click', () => {
        state.micActive = !state.micActive;
        rerenderComposer(root);
        if (state.micActive) window.Orchestra.toast('Voice input active (demo)', 'info');
      });
    }
  }

  function rerenderMessages(root) {
    const msgs = root.querySelector('[data-messages]');
    if (!msgs) return;
    msgs.innerHTML = state.messages.map(renderMessage).join('') +
      `<div class="mp-typing" data-typing style="display:none">
        <div class="mp-typing__avatar">${milesAvatarSVG(14)}</div>
        <div class="mp-typing__dots"><span></span><span></span><span></span></div>
      </div>`;
  }

  function rerenderComposer(root) {
    const old = root.querySelector('.mp-composer');
    if (!old) return;
    const tmp = document.createElement('div');
    tmp.innerHTML = renderComposer();
    old.replaceWith(tmp.firstElementChild);
    wireComposerInput(root);
    wireContextChips(root);
    wireModelPicker(root);
    root.querySelector('[data-mic-btn]')?.addEventListener('click', () => {
      state.micActive = !state.micActive;
      rerenderComposer(root);
      if (state.micActive) window.Orchestra.toast('Voice input active (demo)', 'info');
    });
  }

  function wireContextChips(root) {
    root.querySelectorAll('[data-ctx]').forEach(btn => {
      btn.addEventListener('click', () => {
        state.context[btn.dataset.ctx] = !state.context[btn.dataset.ctx];
        rerenderComposer(root);
      });
    });
  }

  function wireModelPicker(root) {
    root.querySelector('[data-toggle-model]')?.addEventListener('click', (e) => {
      e.stopPropagation();
      state.modelOpen = !state.modelOpen;
      rerenderComposer(root);
    });
    root.querySelectorAll('[data-pick-model]').forEach(item => {
      item.addEventListener('click', () => {
        state.model = item.dataset.pickModel;
        state.modelOpen = false;
        rerenderComposer(root);
        window.Orchestra.toast(`Model: ${MODELS.find(m=>m.id===state.model)?.name}`, 'info');
      });
    });
  }

  function tickLiveFeed(root) {
    const NEW_EVENTS = [
      { icon: 'beaker',  color: '#F0596A', text: 'RxCheck screened new prescription batch',   age: 0 },
      { icon: 'bolt',    color: '#F5B971', text: 'GridSense: demand up 4% vs baseline',        age: 0 },
      { icon: 'graph',   color: '#34D399', text: 'RiskModeler updated P&L attribution',        age: 0 },
      { icon: 'factory', color: '#00C9B8', text: 'LineTwin: Line B throughput nominal',        age: 0 },
      { icon: 'nursing', color: '#00C9B8', text: 'SafeSign: no critical vitals alerts',        age: 0 },
    ];
    const next = NEW_EVENTS[Math.floor(Math.random() * NEW_EVENTS.length)];
    // age existing events
    state.liveEvents = state.liveEvents.map(e => ({ ...e, age: e.age + 8 }));
    state.liveEvents.unshift(next);
    if (state.liveEvents.length > 6) state.liveEvents.pop();
    const feed = root.querySelector('[data-live-feed]');
    if (feed) {
      feed.innerHTML = renderLiveFeed();
      // flash the new row
      const first = feed.querySelector('.mp-live-row');
      if (first) {
        first.style.background = 'rgba(110,110,245,0.08)';
        setTimeout(() => { first.style.background = ''; }, 1000);
      }
    }
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      const msgs = document.querySelector('[data-messages]');
      if (msgs) msgs.scrollTop = msgs.scrollHeight;
    });
  }

  // ── Styles ────────────────────────────────────────────────────────────────

  function injectStyles() {
    if (document.getElementById('miles-page-styles')) return;
    const s = document.createElement('style');
    s.id = 'miles-page-styles';
    s.textContent = `
      /* ─ Page ──────────────────────────────────── */
      .page--miles {
        padding: 0 !important;
        height: 100%; display: flex; flex-direction: column; overflow: hidden;
      }

      /* ─ Header ────────────────────────────────── */
      .mp-header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 14px 24px 12px; flex-shrink: 0;
        border-bottom: 1px solid var(--border-subtle);
        gap: 16px;
      }
      .mp-header__left  { display: flex; align-items: center; gap: 14px; }
      .mp-header__right { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
      .mp-hero-icon {
        width: 50px; height: 50px; border-radius: var(--r-lg);
        background: linear-gradient(135deg, rgba(130,130,247,0.14), rgba(0,201,184,0.12));
        border: 1px solid rgba(130,130,247,0.22);
        display: grid; place-items: center; flex-shrink: 0;
        transition: box-shadow .4s;
      }
      .mp-hero-icon.is-thinking {
        box-shadow: 0 0 0 4px rgba(130,130,247,0.15), 0 0 18px rgba(0,201,184,0.12);
        animation: mp-pulse 1.8s ease-in-out infinite;
      }
      @keyframes mp-pulse {
        0%,100% { box-shadow: 0 0 0 3px rgba(130,130,247,.12), 0 0 16px rgba(0,201,184,.1); }
        50%      { box-shadow: 0 0 0 6px rgba(130,130,247,.2),  0 0 28px rgba(0,201,184,.18); }
      }
      .mp-header__name {
        font-size: 16px; font-weight: 700; letter-spacing: .05em;
        background: linear-gradient(135deg, #8282F7, #00C9B8);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        background-clip: text;
        display: flex; align-items: center; gap: 10px;
      }
      .mp-status {
        display: flex; align-items: center; gap: 5px;
        font-size: 11.5px; font-weight: 400; letter-spacing: 0;
        -webkit-text-fill-color: var(--text-2); color: var(--text-2);
      }
      .mp-header__sub { font-size: 11.5px; color: var(--text-3); margin-top: 2px; }
      .mp-cc-badge {
        display: inline-flex; align-items: center; gap: 5px; padding: 4px 11px;
        background: linear-gradient(135deg, rgba(130,130,247,.11), rgba(0,201,184,.07));
        border: 1px solid rgba(130,130,247,.22); border-radius: 999px;
        font-size: 11.5px; font-weight: 500; color: #8282F7;
      }
      .mp-header__stats {
        display: flex; align-items: center; gap: 8px;
        font-size: 12px; color: var(--text-2);
      }
      .mp-stat { display: flex; flex-direction: column; align-items: center; gap: 1px; }
      .mp-stat__val { font-size: 14px; font-weight: 600; color: var(--text); line-height: 1; }
      .mp-stat__lbl { font-size: 9.5px; color: var(--text-3); text-transform: uppercase; letter-spacing: .05em; }
      .mp-stat-div  { width: 1px; height: 20px; background: var(--border-subtle); }

      /* ─ Body split ─────────────────────────────── */
      .mp-body {
        display: flex; flex: 1; min-height: 0; overflow: hidden;
      }

      /* ─ Left: Chat col ─────────────────────────── */
      .mp-chat {
        flex: 1; min-width: 0; display: flex; flex-direction: column;
        border-right: 1px solid var(--border-subtle); overflow: hidden;
      }

      /* Tabs */
      .mp-tabs {
        display: flex; align-items: center; gap: 2px;
        padding: 10px 16px 0; flex-shrink: 0;
        border-bottom: 1px solid var(--border-subtle);
      }
      .mp-tab {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 7px 13px; font-size: 12.5px; font-weight: 500; color: var(--text-2);
        border-radius: var(--r-sm) var(--r-sm) 0 0;
        cursor: pointer; white-space: nowrap;
        border-bottom: 2px solid transparent;
        transition: color var(--dur) var(--ease), border-color var(--dur) var(--ease);
      }
      .mp-tab:hover { color: var(--text); }
      .mp-tab.is-active { color: var(--text); border-bottom-color: #8282F7; }
      .mp-tabs__spacer { flex: 1; }
      .mp-tab-action {
        display: inline-flex; align-items: center; gap: 5px;
        padding: 5px 10px; font-size: 11.5px; color: var(--text-3);
        border-radius: var(--r-sm); cursor: pointer;
        transition: background var(--dur), color var(--dur);
      }
      .mp-tab-action:hover { background: var(--bg-3); color: var(--text); }

      /* Tab content */
      .mp-tab-content { flex: 1; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }

      /* Messages */
      .mp-messages {
        flex: 1; overflow-y: auto; padding: 20px 20px 4px;
        display: flex; flex-direction: column; gap: 20px;
        scroll-behavior: smooth;
      }

      /* Message bubbles */
      .miles-msg { display: flex; gap: 12px; align-items: flex-start; }
      .miles-msg--user { flex-direction: row-reverse; }
      .miles-msg__avatar {
        width: 32px; height: 32px; border-radius: 50%; flex-shrink: 0;
        background: linear-gradient(135deg, rgba(130,130,247,.16), rgba(0,201,184,.1));
        border: 1px solid rgba(130,130,247,.2);
        display: grid; place-items: center;
      }
      .miles-msg__avatar--user {
        background: var(--accent-dim); border-color: var(--accent-ring);
        color: var(--accent); font-size: 10.5px; font-weight: 600;
      }
      .miles-msg__body { max-width: 76%; display: flex; flex-direction: column; gap: 6px; }
      .miles-msg--user .miles-msg__body { align-items: flex-end; }
      .miles-msg__bubble {
        padding: 11px 15px; border-radius: var(--r-lg);
        font-size: 13.5px; line-height: 1.6; color: var(--text);
        background: linear-gradient(135deg, rgba(130,130,247,.1), rgba(0,201,184,.05));
        border: 1px solid rgba(130,130,247,.18);
      }
      .miles-msg__meta {
        font-size: 11px; color: var(--text-3); padding: 0 4px;
      }
      .miles-msg--user .miles-msg__meta { text-align: right; }

      /* Message blocks */
      .miles-block { }
      .miles-block--md {
        font-size: 13.5px; line-height: 1.65; color: var(--text);
      }
      .miles-block--md strong { font-weight: 600; color: var(--text); }
      .miles-block--md code {
        background: var(--bg-3); padding: 2px 6px;
        border-radius: 4px; font-size: 12px; font-family: var(--font-mono, monospace);
      }
      .miles-block--md .md-h2 {
        font-size: 14px; font-weight: 700; margin: 10px 0 6px;
        letter-spacing: -0.01em; color: var(--text);
      }
      .miles-block--md .md-h3 {
        font-size: 13px; font-weight: 600; margin: 8px 0 4px; color: var(--text);
      }
      .miles-block--md .md-li {
        padding: 2px 0 2px 8px; position: relative; color: var(--text-2);
      }
      .miles-block--md .md-li::before {
        content: '·'; position: absolute; left: 0; color: var(--text-3);
      }
      .miles-block--md .md-hr { border: none; border-top: 1px solid var(--border-subtle); margin: 10px 0; }
      .miles-block--md .md-gap { height: 8px; }

      /* Tool calls */
      .miles-block--tools {
        display: flex; flex-direction: column; gap: 5px;
        padding: 10px 14px;
        background: var(--bg-2); border: 1px solid var(--border-subtle);
        border-radius: var(--r);
      }
      .tool-call {
        display: flex; align-items: center; gap: 8px;
        font-size: 12.5px; color: var(--text-2);
      }
      .tc-icon { flex-shrink: 0; }
      .tc-label { flex: 1; }
      .tc-state { display: flex; align-items: center; }
      .tc-spin {
        width: 10px; height: 10px; border-radius: 50%;
        border: 1.5px solid rgba(110,110,245,.3); border-top-color: var(--accent);
        animation: spin .7s linear infinite; display: block;
      }
      @keyframes spin { to { transform: rotate(360deg); } }

      /* Alert cards */
      .miles-block--alerts {
        display: flex; flex-direction: column; gap: 6px;
      }
      .alert-card {
        display: flex; align-items: flex-start; gap: 10px;
        padding: 10px 13px;
        border-radius: var(--r);
        border-left: 3px solid;
        background: var(--bg-2);
        border-top: 1px solid var(--border-subtle);
        border-right: 1px solid var(--border-subtle);
        border-bottom: 1px solid var(--border-subtle);
      }
      .alert-card--critical { border-left-color: var(--danger); }
      .alert-card--high     { border-left-color: var(--warn);   }
      .alert-card--info     { border-left-color: var(--accent);  }
      .alert-card__icon { margin-top: 1px; flex-shrink: 0; }
      .alert-card__body { flex: 1; }
      .alert-card__title { font-size: 12.5px; font-weight: 600; color: var(--text); }
      .alert-card__text  { font-size: 12px; color: var(--text-2); margin-top: 2px; line-height: 1.45; }
      .alert-card__level {
        font-size: 9.5px; text-transform: uppercase; letter-spacing: .06em;
        color: var(--text-3); font-weight: 600; flex-shrink: 0; margin-top: 2px;
      }

      /* Action rows */
      .miles-block--actions { display: flex; gap: 8px; flex-wrap: wrap; }
      .miles-action-btn {
        padding: 7px 14px; border-radius: 999px; font-size: 12.5px; font-weight: 500;
        cursor: pointer; transition: opacity var(--dur), transform var(--dur);
      }
      .miles-action-btn--primary {
        background: linear-gradient(135deg, #6E6EF5, #00C9B8); color: white; border: none;
      }
      .miles-action-btn--ghost {
        background: var(--bg-2); color: var(--text-2);
        border: 1px solid var(--border);
      }
      .miles-action-btn:hover { opacity: .85; }
      .miles-action-btn:active { transform: scale(.97); }
      .miles-action-btn:disabled { opacity: .4; pointer-events: none; }

      /* Thinking block */
      .miles-block--thinking {
        display: flex; align-items: center; gap: 8px;
        font-size: 12.5px; color: var(--text-3); font-style: italic;
        padding: 6px 0;
      }
      .thinking-dot {
        width: 7px; height: 7px; border-radius: 50%; background: var(--accent);
        animation: mp-pulse-dot 1.4s ease-in-out infinite; flex-shrink: 0;
      }
      @keyframes mp-pulse-dot {
        0%,100% { opacity: .4; transform: scale(1); }
        50%      { opacity: 1;  transform: scale(1.3); }
      }

      /* Typing indicator */
      .mp-typing {
        display: flex; align-items: center; gap: 10px; padding: 0 0 8px;
        flex-shrink: 0;
      }
      .mp-typing__avatar {
        width: 28px; height: 28px;
        background: linear-gradient(135deg, rgba(130,130,247,.14), rgba(0,201,184,.1));
        border: 1px solid rgba(130,130,247,.2);
        border-radius: 50%; display: grid; place-items: center;
      }
      .mp-typing__dots { display: flex; gap: 4px; }
      .mp-typing__dots span {
        width: 5px; height: 5px; border-radius: 50%; background: var(--text-3);
        animation: mp-type-dot 1.2s ease-in-out infinite;
      }
      .mp-typing__dots span:nth-child(2) { animation-delay: .2s; }
      .mp-typing__dots span:nth-child(3) { animation-delay: .4s; }
      @keyframes mp-type-dot {
        0%,60%,100% { opacity: .3; transform: scale(1); }
        30% { opacity: 1; transform: scale(1.25); }
      }

      /* History tab */
      .mp-history { flex: 1; overflow-y: auto; padding: 12px 20px; display: flex; flex-direction: column; gap: 2px; }
      .mp-history-row {
        display: flex; align-items: baseline; gap: 12px;
        padding: 10px 12px; border-radius: var(--r);
        cursor: pointer; transition: background var(--dur);
      }
      .mp-history-row:hover { background: var(--bg-2); }
      .mp-history-date  { font-size: 12px; font-weight: 600; color: var(--text); width: 72px; flex-shrink: 0; }
      .mp-history-summary { flex: 1; font-size: 12.5px; color: var(--text-2); line-height: 1.4; }
      .mp-history-meta  { font-size: 11px; color: var(--text-3); flex-shrink: 0; }

      /* Patterns tab */
      .mp-patterns { flex: 1; overflow-y: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
      .mp-patterns__header { padding-bottom: 12px; border-bottom: 1px solid var(--border-subtle); }
      .mp-patterns__title { font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 4px; }
      .mp-patterns__sub   { font-size: 12px; color: var(--text-3); }
      .mp-pattern-row {
        display: flex; align-items: flex-start; gap: 12px;
        padding: 10px 12px; border-radius: var(--r); background: var(--bg-2);
        border: 1px solid var(--border-subtle);
      }
      .mp-pattern-icon { color: #8282F7; flex-shrink: 0; margin-top: 1px; }
      .mp-pattern-text { font-size: 13px; color: var(--text-2); line-height: 1.5; }
      .mp-patterns__footer { margin-top: 4px; }

      /* ─ Composer ───────────────────────────────── */
      .mp-composer {
        border-top: 1px solid var(--border-subtle); flex-shrink: 0;
        padding: 10px 16px 12px; display: flex; flex-direction: column; gap: 8px;
      }
      .mp-ctx-chips {
        display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
      }
      .mp-ctx-chip {
        display: inline-flex; align-items: center; gap: 5px;
        padding: 4px 11px; border-radius: 999px; font-size: 11.5px; font-weight: 500;
        background: var(--bg-2); border: 1px solid var(--border); color: var(--text-3);
        cursor: pointer; transition: all var(--dur) var(--ease);
      }
      .mp-ctx-chip.is-on {
        background: linear-gradient(135deg, rgba(130,130,247,.12), rgba(0,201,184,.07));
        border-color: rgba(130,130,247,.3); color: var(--text);
      }
      .mp-ctx-chip:hover { color: var(--text); }

      /* Model picker */
      .mp-model-picker { position: relative; }
      .mp-model-btn {
        display: inline-flex; align-items: center; gap: 5px;
        padding: 4px 11px; border-radius: 999px; font-size: 11.5px; font-weight: 500;
        background: var(--bg-2); border: 1px solid var(--border); color: var(--text-2);
        cursor: pointer; transition: all var(--dur);
      }
      .mp-model-btn:hover { color: var(--text); border-color: var(--accent-ring); }
      .mp-model-menu {
        position: absolute; bottom: calc(100% + 6px); right: 0;
        background: var(--bg-2); border: 1px solid var(--border);
        border-radius: var(--r-lg); box-shadow: var(--shadow-lg);
        z-index: 200; width: 220px; overflow: hidden;
      }
      .mp-model-item {
        display: flex; align-items: center; gap: 10px;
        padding: 10px 14px; cursor: pointer; font-size: 12.5px; color: var(--text-2);
        transition: background var(--dur);
      }
      .mp-model-item:hover { background: var(--bg-3); color: var(--text); }
      .mp-model-item.is-active { color: var(--text); }
      .mp-model-name { font-weight: 500; font-size: 12.5px; color: var(--text); }
      .mp-model-desc { font-size: 11px; color: var(--text-3); margin-top: 1px; }

      /* Input box */
      .mp-composer__box {
        display: flex; align-items: flex-end; gap: 8px;
      }
      .mp-composer__input {
        flex: 1; background: var(--bg-2); border: 1px solid var(--border);
        border-radius: var(--r-lg); padding: 10px 14px;
        font-size: 13.5px; color: var(--text); resize: none;
        line-height: 1.5; min-height: 42px; max-height: 130px;
        transition: border-color var(--dur); font-family: inherit;
      }
      .mp-composer__input:focus {
        outline: none; border-color: rgba(130,130,247,.4);
        box-shadow: 0 0 0 3px rgba(130,130,247,.07);
      }
      .mp-composer__input::placeholder { color: var(--text-3); }
      .mp-composer__btns { display: flex; align-items: center; gap: 6px; }
      .mp-mic-btn {
        width: 34px; height: 34px; border-radius: 50%;
        background: var(--bg-2); border: 1px solid var(--border);
        color: var(--text-3); display: grid; place-items: center;
        cursor: pointer; transition: all var(--dur);
      }
      .mp-mic-btn:hover { color: var(--text); border-color: var(--accent-ring); }
      .mp-mic-btn.is-active {
        background: rgba(240,89,106,.12); border-color: rgba(240,89,106,.3);
        color: var(--danger); animation: mp-pulse-dot 1s infinite;
      }
      .mp-send-btn {
        width: 36px; height: 36px; border-radius: 50%;
        background: linear-gradient(135deg, #6E6EF5, #00C9B8);
        display: grid; place-items: center; color: white;
        cursor: pointer; border: none;
        transition: opacity var(--dur), transform var(--dur);
      }
      .mp-send-btn:hover  { opacity: .88; transform: scale(1.05); }
      .mp-send-btn:active { transform: scale(.95); }
      .mp-composer__footer {
        display: flex; justify-content: space-between;
        font-size: 11px; color: var(--text-3); padding: 0 2px;
      }
      .mp-composer__footer kbd {
        display: inline-block; padding: 1px 5px;
        background: var(--bg-3); border: 1px solid var(--border);
        border-radius: 4px; font-family: inherit; font-size: 10px;
      }

      /* ─ Right panel ────────────────────────────── */
      .mp-panel {
        width: 272px; flex-shrink: 0; overflow-y: auto;
        padding: 12px 0; display: flex; flex-direction: column; gap: 0;
      }
      .mp-section { border-bottom: 1px solid var(--border-subtle); padding-bottom: 4px; margin-bottom: 4px; }
      .mp-section__head {
        display: flex; align-items: center; gap: 7px;
        padding: 8px 16px 6px;
        font-size: 11px; font-weight: 600; color: var(--text-3);
        text-transform: uppercase; letter-spacing: .05em;
      }
      .mp-section__live {
        display: flex; align-items: center; gap: 4px;
        color: var(--success); margin-right: 2px;
      }

      /* Live feed */
      .mp-live-feed { padding: 0 0 4px; }
      .mp-live-row {
        display: flex; align-items: flex-start; gap: 9px;
        padding: 7px 16px;
        transition: background .4s ease;
        border-radius: 0;
      }
      .mp-live-icon { flex-shrink: 0; margin-top: 1px; }
      .mp-live-text { flex: 1; font-size: 11.5px; color: var(--text-2); line-height: 1.4; }
      .mp-live-age  { font-size: 10.5px; color: var(--text-3); flex-shrink: 0; white-space: nowrap; margin-top: 1px; }

      /* Schedule */
      .mp-schedule { padding: 4px 16px 8px; display: flex; flex-direction: column; gap: 0; }
      .mp-sched-row {
        display: flex; align-items: flex-start; gap: 10px;
        padding: 6px 0; border-bottom: 1px solid var(--border-subtle);
      }
      .mp-sched-row:last-child { border-bottom: none; }
      .mp-sched-row.is-done .mp-sched-title { color: var(--text-3); text-decoration: line-through; }
      .mp-sched-time { font-size: 10.5px; color: var(--text-3); width: 58px; flex-shrink: 0; padding-top: 2px; }
      .mp-sched-dot {
        width: 7px; height: 7px; border-radius: 50%; background: var(--accent);
        flex-shrink: 0; margin-top: 4px;
      }
      .mp-sched-dot--task { background: var(--warn); }
      .mp-sched-row.is-done .mp-sched-dot { background: var(--bg-4); }
      .mp-sched-title { font-size: 12.5px; color: var(--text); font-weight: 500; line-height: 1.35; }
      .mp-sched-meta  { font-size: 11px; color: var(--text-3); margin-top: 2px; }

      /* Channels */
      .mp-channels { padding: 2px 0 6px; }
      .mp-ch-row {
        display: flex; align-items: center; gap: 9px;
        padding: 6px 16px;
        transition: background var(--dur);
        cursor: default;
      }
      .mp-ch-row:hover { background: var(--bg-2); }
      .mp-ch-icon { flex-shrink: 0; }
      .mp-ch-name { flex: 1; font-size: 12.5px; color: var(--text-2); }
      .mp-ch-status { display: flex; align-items: center; }

      @keyframes blink {
        0%,100% { opacity: 1; } 50% { opacity: .35; }
      }

      /* Responsive */
      @media (max-width: 1000px) { .mp-panel { display: none; } .mp-chat { border-right: none; } }
      @media (max-width: 640px) {
        .mp-header__sub, .mp-cc-badge, .mp-header__stats { display: none; }
        .mp-header { padding: 10px 14px; }
      }
    `;
    document.head.appendChild(s);
  }

  // ── Register ──────────────────────────────────────────────────────────────
  window.Orchestra = window.Orchestra || {};
  window.Orchestra.pages = window.Orchestra.pages || {};
  window.Orchestra.pages.miles = { mount, unmount };

  // ⌘M — navigate to MILES and focus input
  window.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'm') {
      e.preventDefault();
      if (location.hash !== '#/miles') {
        location.hash = '#/miles';
      }
      setTimeout(() => {
        const input = document.querySelector('[data-miles-input]');
        if (input) input.focus();
      }, 80);
    }
  });
})();
