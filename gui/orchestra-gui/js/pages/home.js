// Orchestra — Home (command center)
(function () {
  const { icons } = window;

  function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function greeting() {
    const h = new Date().getHours();
    return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
  }

  function dateStr() {
    return new Date().toLocaleDateString('en-US', { weekday:'long', month:'long', day:'numeric' });
  }

  // ── Mock widget data ───────────────────────────────────────────────────────

  const WEATHER = {
    city: 'Dallas, TX', temp: 76, feel: 73, high: 83, low: 67,
    condition: 'Partly Cloudy', icon: '⛅',
    forecast: [
      { day:'Tue', icon:'🌤', h:85, l:69 },
      { day:'Wed', icon:'🌧', h:74, l:61 },
      { day:'Thu', icon:'☀️', h:88, l:70 },
      { day:'Fri', icon:'☀️', h:91, l:72 },
    ],
  };

  const NEWS = [
    { source:'Reuters',        time:'12m', title:'Fed signals two rate cuts in 2026 as inflation cools to 2.1%', tag:'Markets' },
    { source:'TechCrunch',     time:'34m', title:'Anthropic releases Claude 4 Opus with 2M context and live tool use', tag:'AI' },
    { source:'WSJ',            time:'1h',  title:'NorthPeak Capital closes $800M Series C for AI infrastructure fund', tag:'Finance' },
    { source:'GitHub Blog',    time:'2h',  title:'GitHub Copilot now supports multi-file reasoning across repositories', tag:'Dev' },
    { source:'Bloomberg',      time:'3h',  title:'Manufacturing PMI hits 18-month high as supply chains stabilize', tag:'Economy' },
  ];

  const GITHUB = {
    repo: 'orchestra-full',
    stats: { prs: 3, issues: 7, commits: 14 },
    items: [
      { type:'pr',     state:'open',   num:2041, title:'feat: MILES multi-channel ingestion',        time:'2h',  author:'ashton' },
      { type:'pr',     state:'merged', num:2039, title:'fix: CSP headers for inline style injection', time:'4h',  author:'jordanl' },
      { type:'issue',  state:'open',   num:388,  title:'T-7024 MSA redline crashes at parse step',    time:'8h',  author:'dev-bot' },
      { type:'commit', state:'push',   num:null, title:'chore: update miles.js live feed interval',   time:'1h',  author:'ashton' },
    ],
  };

  const MESSAGES = [
    { channel:'#engineering', from:'Jordan L.',  time:'9m',  unread:true,  text:'PR #2041 needs a second review — blocking the deploy.' },
    { channel:'#legal',       from:'Sarah K.',   time:'22m', unread:true,  text:'NorthPeak legal sent rev 7. ContractReview is scanning.' },
    { channel:'#ops',         from:'LineTwin',   time:'1h',  unread:false, text:'Line B throughput nominal after the 3am maintenance.' },
    { channel:'Direct',       from:'Alex R.',    time:'2h',  unread:false, text:'Can we move the 1:1 to Thursday? Something came up.' },
  ];

  const TODAY = [
    { time:'9:00',  title:'Eng standup',           dur:'30m', done:true,  type:'meeting' },
    { time:'10:00', title:'Eng sync',               dur:'1h',  done:true,  type:'meeting' },
    { time:'2:30',  title:'NorthPeak negotiation',  dur:'1h',  done:false, type:'meeting', flag:true },
    { time:'4:00',  title:'1:1 with Jordan',        dur:'30m', done:false, type:'meeting' },
    { time:'5:00',  title:'Submit weekly KPI pack', dur:null,  done:false, type:'task' },
  ];

  // ── Render ─────────────────────────────────────────────────────────────────

  function render() {
    const M = window.MOCK;
    const unread = MESSAGES.filter(m => m.unread).length;
    const nextEvent = TODAY.find(e => !e.done);

    return `
      <div class="page page--command">

        <!-- ── Top bar ──────────────────────────────────────────────── -->
        <div class="cmd-topbar">
          <div class="cmd-topbar__left">
            <div class="cmd-topbar__greeting">${greeting()}, ${esc(M.user.name.split(' ')[0])}</div>
            <div class="cmd-topbar__date">${dateStr()}${nextEvent ? ` &nbsp;·&nbsp; Next: <strong>${esc(nextEvent.title)}</strong> at ${esc(nextEvent.time)}` : ''}</div>
          </div>
          <div class="cmd-topbar__right">
            ${unread ? `<div class="cmd-unread-badge" data-action-goto="#/chat">${icons.chat(13)} ${unread} unread</div>` : ''}
            <button class="cmd-miles-btn" data-action="open-miles">
              <span class="cmd-miles-btn__icon">${icons.miles(15)}</span>
              <span class="cmd-miles-btn__label">Ask M.I.L.E.S</span>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
            </button>
          </div>
        </div>

        <!-- ── Widget grid ──────────────────────────────────────────── -->
        <div class="cmd-grid">

          <!-- Weather -->
          <div class="cmd-widget cmd-widget--weather">
            <div class="cmd-w-head">
              <span class="cmd-w-title">${icons.globe(12)} Weather</span>
              <span class="cmd-w-city">${esc(WEATHER.city)}</span>
            </div>
            <div class="cmd-weather__main">
              <div class="cmd-weather__icon">${WEATHER.icon}</div>
              <div>
                <div class="cmd-weather__temp">${WEATHER.temp}°F</div>
                <div class="cmd-weather__cond">${esc(WEATHER.condition)}</div>
                <div class="cmd-weather__hl">H: ${WEATHER.high}° &nbsp; L: ${WEATHER.low}° &nbsp; Feels ${WEATHER.feel}°</div>
              </div>
            </div>
            <div class="cmd-forecast">
              ${WEATHER.forecast.map(f => `
                <div class="cmd-forecast-day">
                  <div class="cmd-fc-day">${f.day}</div>
                  <div class="cmd-fc-icon">${f.icon}</div>
                  <div class="cmd-fc-temp">${f.h}° <span>${f.l}°</span></div>
                </div>`).join('')}
            </div>
          </div>

          <!-- News -->
          <div class="cmd-widget cmd-widget--news">
            <div class="cmd-w-head">
              <span class="cmd-w-title">${icons.file(12)} News</span>
              <span class="cmd-w-sub">Top stories</span>
            </div>
            <div class="cmd-news-list">
              ${NEWS.map(n => `
                <div class="cmd-news-item">
                  <div class="cmd-news-meta">
                    <span class="cmd-news-source">${esc(n.source)}</span>
                    <span class="cmd-news-tag">${esc(n.tag)}</span>
                    <span class="cmd-news-time">${esc(n.time)}</span>
                  </div>
                  <div class="cmd-news-title">${esc(n.title)}</div>
                </div>`).join('')}
            </div>
          </div>

          <!-- GitHub -->
          <div class="cmd-widget cmd-widget--github">
            <div class="cmd-w-head">
              <span class="cmd-w-title">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.58 2 12.26c0 4.54 2.87 8.39 6.84 9.75.5.09.68-.22.68-.49l-.01-1.71c-2.78.62-3.37-1.37-3.37-1.37-.45-1.18-1.11-1.49-1.11-1.49-.91-.64.07-.63.07-.63 1 .07 1.53 1.05 1.53 1.05.89 1.57 2.34 1.12 2.91.85.09-.66.35-1.12.63-1.37-2.22-.26-4.56-1.14-4.56-5.07 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.3.1-2.71 0 0 .84-.27 2.75 1.05a9.3 9.3 0 0 1 2.5-.34c.85 0 1.7.11 2.5.34 1.91-1.32 2.75-1.05 2.75-1.05.55 1.41.2 2.45.1 2.71.64.72 1.03 1.63 1.03 2.75 0 3.94-2.34 4.81-4.57 5.06.36.32.68.94.68 1.9l-.01 2.82c0 .27.18.59.69.49C19.14 20.65 22 16.8 22 12.26 22 6.58 17.52 2 12 2z"/></svg>
                GitHub
              </span>
              <span class="cmd-w-sub">${esc(GITHUB.repo)}</span>
            </div>
            <div class="cmd-gh-stats">
              <div class="cmd-gh-stat"><strong>${GITHUB.stats.prs}</strong> open PRs</div>
              <div class="cmd-gh-stat-div"></div>
              <div class="cmd-gh-stat"><strong>${GITHUB.stats.issues}</strong> issues</div>
              <div class="cmd-gh-stat-div"></div>
              <div class="cmd-gh-stat"><strong>${GITHUB.stats.commits}</strong> commits today</div>
            </div>
            <div class="cmd-gh-list">
              ${GITHUB.items.map(it => `
                <div class="cmd-gh-item">
                  <span class="cmd-gh-icon cmd-gh-icon--${it.type} cmd-gh-icon--${it.state}">
                    ${it.type === 'pr' ? prIcon(it.state) : it.type === 'issue' ? issueIcon(it.state) : commitIcon()}
                  </span>
                  <span class="cmd-gh-text">${esc(it.title)}</span>
                  <span class="cmd-gh-time">${esc(it.time)}</span>
                </div>`).join('')}
            </div>
          </div>

          <!-- Messages -->
          <div class="cmd-widget cmd-widget--messages">
            <div class="cmd-w-head">
              <span class="cmd-w-title">${icons.chat(12)} Messages</span>
              ${unread ? `<span class="badge badge--accent" style="margin-left:auto;font-size:10px">${unread} new</span>` : ''}
            </div>
            <div class="cmd-msg-list">
              ${MESSAGES.map(m => `
                <div class="cmd-msg-item ${m.unread?'cmd-msg-item--unread':''}">
                  <div class="cmd-msg-avatar">${esc(m.from.split(' ').map(w=>w[0]).join('').slice(0,2))}</div>
                  <div class="cmd-msg-body">
                    <div class="cmd-msg-top">
                      <span class="cmd-msg-from">${esc(m.from)}</span>
                      <span class="cmd-msg-ch">${esc(m.channel)}</span>
                      <span class="cmd-msg-time">${esc(m.time)}</span>
                    </div>
                    <div class="cmd-msg-text">${esc(m.text)}</div>
                  </div>
                </div>`).join('')}
            </div>
            <a class="cmd-w-footer-link" href="#/chat">Open chat ${icons.chevronRight(11)}</a>
          </div>

          <!-- Today / Calendar -->
          <div class="cmd-widget cmd-widget--calendar">
            <div class="cmd-w-head">
              <span class="cmd-w-title">${icons.calendar(12)} Today</span>
              <span class="cmd-w-sub">${dateStr().split(',')[0]}</span>
            </div>
            <div class="cmd-cal-list">
              ${TODAY.map(e => `
                <div class="cmd-cal-row ${e.done?'cmd-cal-row--done':''}${e.flag?' cmd-cal-row--flag':''}">
                  <div class="cmd-cal-time">${esc(e.time)}</div>
                  <div class="cmd-cal-dot cmd-cal-dot--${e.type}${e.done?' cmd-cal-dot--done':''}"></div>
                  <div class="cmd-cal-body">
                    <div class="cmd-cal-title">${esc(e.title)}</div>
                    ${e.dur ? `<div class="cmd-cal-dur">${esc(e.dur)}</div>` : ''}
                  </div>
                  ${e.flag ? `<span class="cmd-cal-flag">prep needed</span>` : ''}
                </div>`).join('')}
            </div>
          </div>

          <!-- Agents quick status -->
          <div class="cmd-widget cmd-widget--agents">
            <div class="cmd-w-head">
              <span class="cmd-w-title">${icons.agents(12)} Agents</span>
              <span class="cmd-w-sub">${window.MOCK.agents.length} total</span>
            </div>
            <div class="cmd-agent-stats">
              <div class="cmd-agent-stat">
                <div class="cmd-agent-stat__val" style="color:var(--success)">${window.MOCK.agents.filter(a=>a.status==='online').length}</div>
                <div class="cmd-agent-stat__lbl">Online</div>
              </div>
              <div class="cmd-agent-stat">
                <div class="cmd-agent-stat__val" style="color:var(--warn)">${window.MOCK.agents.filter(a=>a.status==='busy').length}</div>
                <div class="cmd-agent-stat__lbl">Busy</div>
              </div>
              <div class="cmd-agent-stat">
                <div class="cmd-agent-stat__val">${window.MOCK.runningTasks.length}</div>
                <div class="cmd-agent-stat__lbl">Running</div>
              </div>
              <div class="cmd-agent-stat">
                <div class="cmd-agent-stat__val" style="color:var(--text-3)">0</div>
                <div class="cmd-agent-stat__lbl">Failed</div>
              </div>
            </div>
            <div class="cmd-agent-list">
              ${window.MOCK.runningTasks.map(t => `
                <div class="cmd-agent-task">
                  <span class="pulse" style="flex-shrink:0"></span>
                  <span class="cmd-agent-task__name">${esc(t.agent)}</span>
                  <div class="cmd-agent-task__bar"><div style="width:${Math.round(t.progress*100)}%;background:var(--accent)"></div></div>
                  <span class="cmd-agent-task__eta">${esc(t.eta)}</span>
                </div>`).join('')}
            </div>
            <a class="cmd-w-footer-link" href="#/agents">All agents ${icons.chevronRight(11)}</a>
          </div>

        </div>
      </div>
    `;
  }

  // ── Icon helpers ───────────────────────────────────────────────────────────
  function prIcon(state) {
    const c = state === 'merged' ? '#8282F7' : state === 'open' ? '#34D399' : '#F0596A';
    return `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="2"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="6" r="3"/><path d="M6 9v6M18 9a9 9 0 0 1-9 9"/></svg>`;
  }
  function issueIcon(state) {
    const c = state === 'open' ? '#F0596A' : '#8282F7';
    return `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="2"><circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
  }
  function commitIcon() {
    return `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="2"><circle cx="12" cy="12" r="3"/><line x1="3" y1="12" x2="9" y2="12"/><line x1="15" y1="12" x2="21" y2="12"/></svg>`;
  }

  // ── Mount ──────────────────────────────────────────────────────────────────
  function mount(root) {
    injectStyles();
    root.innerHTML = render();

    root.querySelector('[data-action="open-miles"]')
      ?.addEventListener('click', () => { location.hash = '#/miles'; });

    root.querySelector('[data-action-goto="#/chat"]')
      ?.addEventListener('click', () => { location.hash = '#/chat'; });

    root.querySelectorAll('[data-action="new-task"]').forEach(el =>
      el.addEventListener('click', () => {
        window.Orchestra.toast('Starting new task…', 'info');
        setTimeout(() => { location.hash = '#/chat'; }, 300);
      }));
  }

  // ── Styles ─────────────────────────────────────────────────────────────────
  function injectStyles() {
    if (document.getElementById('cmd-styles')) return;
    const s = document.createElement('style');
    s.id = 'cmd-styles';
    s.textContent = `

    /* ── Page ──────────────────────────────────────────── */
    .page--command {
      padding: 24px 28px 36px;
      display: flex; flex-direction: column; gap: 20px;
      overflow-y: auto; height: 100%;
      box-sizing: border-box;
    }

    /* ── Top bar ────────────────────────────────────────── */
    .cmd-topbar {
      display: flex; align-items: center; justify-content: space-between;
      gap: 16px; flex-shrink: 0;
      animation: cinematicIn 500ms cubic-bezier(0.2,0.7,0.2,1) both;
    }
    .cmd-topbar__greeting {
      font-size: 20px; font-weight: 700; line-height: 1.2;
      background: linear-gradient(135deg, var(--text) 0%, var(--accent) 50%, var(--teal) 100%);
      background-size: 300% 300%;
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text;
      animation: auroraText 10s ease-in-out infinite;
    }
    .cmd-topbar__date {
      font-size: 12.5px; color: var(--text-3); margin-top: 3px;
    }
    .cmd-topbar__date strong { color: var(--text-2); font-weight: 500; }
    .cmd-topbar__right {
      display: flex; align-items: center; gap: 10px; flex-shrink: 0;
    }
    .cmd-unread-badge {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 6px 12px; border-radius: 999px; font-size: 12px; font-weight: 500;
      background: var(--accent-dim); border: 1px solid var(--accent-ring); color: var(--accent);
      cursor: pointer;
    }

    /* MILES button — Higgsfield liquid gradient CTA */
    .cmd-miles-btn {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 9px 18px; border-radius: 999px;
      background: linear-gradient(135deg, #6E6EF5, #00C9B8, #A855F7, #6E6EF5);
      background-size: 300% 300%;
      color: white; font-size: 13.5px; font-weight: 600;
      cursor: pointer; border: none;
      box-shadow: 0 3px 18px rgba(110,110,245,.35);
      animation: liquidFlow 4s ease-in-out infinite;
      position: relative; overflow: hidden;
    }
    .cmd-miles-btn:hover  { animation-duration: 1.8s; transform: translateY(-1px); box-shadow: 0 6px 28px rgba(110,110,245,.5); }
    .cmd-miles-btn:active { transform: scale(.97); }
    .cmd-miles-btn__icon { display: flex; align-items: center; }
    .cmd-miles-btn__label { letter-spacing: .01em; }

    /* ── Widget grid ────────────────────────────────────── */
    .cmd-grid {
      display: grid;
      grid-template-columns: 220px 1fr 280px;
      grid-template-rows: auto auto;
      gap: 16px;
    }

    /* Widget base — glassmorphism + aurora mesh */
    .cmd-widget {
      background: var(--glass-bg-soft, rgba(17,17,24,.5));
      backdrop-filter: blur(18px) saturate(160%);
      -webkit-backdrop-filter: blur(18px) saturate(160%);
      border: 1px solid var(--glass-border, rgba(255,255,255,.07));
      border-radius: var(--r-lg, 10px);
      padding: 16px 18px;
      display: flex; flex-direction: column; gap: 12px;
      min-width: 0;
      position: relative; overflow: hidden;
      transition: border-color .2s ease, box-shadow .2s ease, transform .2s ease;
      animation: cinematicIn 550ms cubic-bezier(0.2,0.7,0.2,1) both;
    }
    .cmd-widget::before {
      content: '';
      position: absolute; inset: -30%;
      background:
        radial-gradient(ellipse at 20% 20%, rgba(110,110,245,.07) 0%, transparent 55%),
        radial-gradient(ellipse at 80% 80%, rgba(0,201,184,.06) 0%, transparent 55%);
      background-size: 200% 200%, 200% 200%;
      animation: aurora 16s ease-in-out infinite;
      pointer-events: none;
    }
    .cmd-widget::after {
      content: '';
      position: absolute;
      inset: 0; border-radius: inherit;
      background: radial-gradient(
        circle at var(--mouse-x, 50%) var(--mouse-y, 50%),
        rgba(110,110,245,.08) 0%, transparent 55%
      );
      pointer-events: none; opacity: 0;
      transition: opacity .2s ease;
    }
    .cmd-widget:hover::after { opacity: 1; }
    .cmd-widget:hover {
      border-color: rgba(110,110,245,.18);
      box-shadow: 0 8px 32px rgba(0,0,0,.25);
      transform: translateY(-1px);
    }
    .cmd-widget > * { position: relative; z-index: 1; }
    .cmd-w-head {
      display: flex; align-items: center; gap: 7px;
      font-size: 11px; font-weight: 600; color: var(--text-3);
      text-transform: uppercase; letter-spacing: .05em;
      flex-shrink: 0;
    }
    .cmd-w-title { display: flex; align-items: center; gap: 5px; }
    .cmd-w-sub   { margin-left: auto; font-weight: 400; text-transform: none; letter-spacing: 0; font-size: 11px; }
    .cmd-w-footer-link {
      margin-top: auto; padding-top: 10px;
      display: flex; align-items: center; gap: 4px;
      font-size: 11.5px; color: var(--text-3);
      border-top: 1px solid var(--border-subtle);
      cursor: pointer; text-decoration: none;
      transition: color .15s;
    }
    .cmd-w-footer-link:hover { color: var(--accent); }

    /* Grid placement + staggered cinematic entrance */
    .cmd-widget--weather   { grid-column: 1; grid-row: 1 / 3; animation-delay: 80ms; }
    .cmd-widget--news      { grid-column: 2; grid-row: 1;      animation-delay: 140ms; }
    .cmd-widget--github    { grid-column: 3; grid-row: 1;      animation-delay: 200ms; }
    .cmd-widget--messages  { grid-column: 2; grid-row: 2;      animation-delay: 260ms; }
    .cmd-widget--calendar  { grid-column: 3; grid-row: 2;      animation-delay: 320ms; }
    .cmd-widget--agents    { grid-column: 1 / -1; grid-row: 3; animation-delay: 380ms; }

    /* ── Weather ────────────────────────────────────────── */
    .cmd-weather__main {
      display: flex; align-items: center; gap: 14px;
    }
    .cmd-weather__icon { font-size: 36px; line-height: 1; }
    .cmd-weather__temp { font-size: 32px; font-weight: 700; color: var(--text); line-height: 1.1; }
    .cmd-weather__cond { font-size: 12.5px; color: var(--text-2); margin-top: 2px; }
    .cmd-weather__hl   { font-size: 11px; color: var(--text-3); margin-top: 4px; }
    .cmd-forecast {
      display: flex; gap: 0;
      border-top: 1px solid var(--border-subtle); padding-top: 12px;
      justify-content: space-between;
    }
    .cmd-forecast-day {
      display: flex; flex-direction: column; align-items: center; gap: 3px;
      flex: 1;
    }
    .cmd-fc-day  { font-size: 10.5px; color: var(--text-3); font-weight: 500; }
    .cmd-fc-icon { font-size: 16px; }
    .cmd-fc-temp { font-size: 11.5px; font-weight: 600; color: var(--text); }
    .cmd-fc-temp span { color: var(--text-3); font-weight: 400; }

    /* ── News ───────────────────────────────────────────── */
    .cmd-news-list { display: flex; flex-direction: column; gap: 0; }
    .cmd-news-item {
      padding: 10px 0;
      border-bottom: 1px solid var(--border-subtle);
      cursor: pointer;
      transition: background .15s;
    }
    .cmd-news-item:last-child { border-bottom: none; padding-bottom: 0; }
    .cmd-news-item:first-child { padding-top: 0; }
    .cmd-news-item:hover .cmd-news-title { color: var(--accent); }
    .cmd-news-meta {
      display: flex; align-items: center; gap: 7px;
      margin-bottom: 4px;
    }
    .cmd-news-source { font-size: 10.5px; font-weight: 600; color: var(--text-3); }
    .cmd-news-tag {
      font-size: 9.5px; padding: 1px 6px; border-radius: 999px;
      background: var(--bg-3); color: var(--text-3); font-weight: 500;
    }
    .cmd-news-time { margin-left: auto; font-size: 10.5px; color: var(--text-3); }
    .cmd-news-title { font-size: 12.5px; color: var(--text-2); line-height: 1.45; font-weight: 500; transition: color .15s; }

    /* ── GitHub ─────────────────────────────────────────── */
    .cmd-gh-stats {
      display: flex; align-items: center; gap: 10px;
      padding: 10px 12px;
      background: var(--bg-3); border-radius: var(--r); font-size: 12px; color: var(--text-2);
    }
    .cmd-gh-stats strong { color: var(--text); font-weight: 600; }
    .cmd-gh-stat-div { width: 1px; height: 14px; background: var(--border-subtle); }
    .cmd-gh-list { display: flex; flex-direction: column; gap: 7px; }
    .cmd-gh-item {
      display: flex; align-items: center; gap: 8px;
      font-size: 12px; color: var(--text-2);
    }
    .cmd-gh-icon { display: flex; align-items: center; flex-shrink: 0; }
    .cmd-gh-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .cmd-gh-time { font-size: 10.5px; color: var(--text-3); flex-shrink: 0; }

    /* ── Messages ───────────────────────────────────────── */
    .cmd-msg-list { display: flex; flex-direction: column; gap: 2px; }
    .cmd-msg-item {
      display: flex; align-items: flex-start; gap: 10px;
      padding: 8px 10px; border-radius: var(--r);
      cursor: pointer; transition: background .15s;
    }
    .cmd-msg-item:hover { background: var(--bg-3); }
    .cmd-msg-item--unread { background: rgba(110,110,245,.04); }
    .cmd-msg-avatar {
      width: 30px; height: 30px; border-radius: 50%; flex-shrink: 0;
      background: var(--accent-dim); border: 1px solid var(--accent-ring);
      display: grid; place-items: center;
      font-size: 10px; font-weight: 600; color: var(--accent);
    }
    .cmd-msg-body { flex: 1; min-width: 0; }
    .cmd-msg-top {
      display: flex; align-items: baseline; gap: 7px; margin-bottom: 2px;
    }
    .cmd-msg-from { font-size: 12.5px; font-weight: 600; color: var(--text); }
    .cmd-msg-ch   { font-size: 11px; color: var(--text-3); flex: 1; }
    .cmd-msg-time { font-size: 10.5px; color: var(--text-3); flex-shrink: 0; }
    .cmd-msg-text { font-size: 12px; color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .cmd-msg-item--unread .cmd-msg-text { color: var(--text); }

    /* ── Calendar ───────────────────────────────────────── */
    .cmd-cal-list { display: flex; flex-direction: column; gap: 0; }
    .cmd-cal-row {
      display: flex; align-items: flex-start; gap: 10px;
      padding: 7px 0; border-bottom: 1px solid var(--border-subtle);
    }
    .cmd-cal-row:last-child { border-bottom: none; }
    .cmd-cal-row--done .cmd-cal-title { color: var(--text-3); text-decoration: line-through; }
    .cmd-cal-row--flag .cmd-cal-title { color: var(--warn); }
    .cmd-cal-time { font-size: 10.5px; color: var(--text-3); width: 36px; flex-shrink: 0; padding-top: 2px; }
    .cmd-cal-dot {
      width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; margin-top: 4px;
      background: var(--accent);
    }
    .cmd-cal-dot--task { background: var(--warn); }
    .cmd-cal-dot--done { background: var(--bg-4); }
    .cmd-cal-body { flex: 1; min-width: 0; }
    .cmd-cal-title { font-size: 12.5px; font-weight: 500; color: var(--text); line-height: 1.3; }
    .cmd-cal-dur   { font-size: 11px; color: var(--text-3); margin-top: 1px; }
    .cmd-cal-flag {
      font-size: 10px; color: var(--warn); font-weight: 500;
      padding: 2px 7px; border-radius: 999px;
      background: var(--warn-dim, rgba(245,185,113,.1));
      border: 1px solid rgba(245,185,113,.25); flex-shrink: 0;
    }

    /* ── Agents row ─────────────────────────────────────── */
    .cmd-widget--agents {
      flex-direction: row; align-items: center; gap: 20px; padding: 14px 20px;
    }
    .cmd-widget--agents .cmd-w-head { flex-shrink: 0; }
    .cmd-agent-stats {
      display: flex; gap: 24px; align-items: center; flex-shrink: 0;
    }
    .cmd-agent-stat { text-align: center; }
    .cmd-agent-stat__val { font-size: 18px; font-weight: 700; color: var(--text); line-height: 1; }
    .cmd-agent-stat__lbl { font-size: 10px; color: var(--text-3); margin-top: 2px; text-transform: uppercase; letter-spacing: .04em; }
    .cmd-agent-list {
      flex: 1; display: flex; gap: 16px; align-items: center; overflow: hidden;
    }
    .cmd-agent-task {
      display: flex; align-items: center; gap: 8px; min-width: 0;
      flex: 1; max-width: 260px;
    }
    .cmd-agent-task__name { font-size: 12px; color: var(--text-2); white-space: nowrap; flex-shrink: 0; }
    .cmd-agent-task__bar  {
      flex: 1; height: 4px; background: var(--bg-4); border-radius: 999px; overflow: hidden;
      min-width: 40px;
    }
    .cmd-agent-task__bar > div { height: 100%; border-radius: 999px; transition: width .6s; }
    .cmd-agent-task__eta { font-size: 10.5px; color: var(--text-3); flex-shrink: 0; }

    /* ── Responsive ─────────────────────────────────────── */
    @media (max-width: 1100px) {
      .cmd-grid {
        grid-template-columns: 1fr 1fr;
        grid-template-rows: auto;
      }
      .cmd-widget--weather  { grid-column: 1;     grid-row: auto; }
      .cmd-widget--news     { grid-column: 1 / -1; grid-row: auto; }
      .cmd-widget--github   { grid-column: 2;     grid-row: auto; }
      .cmd-widget--messages { grid-column: 1;     grid-row: auto; }
      .cmd-widget--calendar { grid-column: 2;     grid-row: auto; }
      .cmd-widget--agents   { grid-column: 1 / -1; flex-direction: column; align-items: stretch; }
      .cmd-agent-list { flex-wrap: wrap; }
    }
    @media (max-width: 680px) {
      .page--command { padding: 14px; gap: 14px; }
      .cmd-grid { grid-template-columns: 1fr; }
      .cmd-widget--weather, .cmd-widget--news, .cmd-widget--github,
      .cmd-widget--messages, .cmd-widget--calendar, .cmd-widget--agents {
        grid-column: 1; grid-row: auto;
      }
      .cmd-miles-btn__label { display: none; }
    }
    `;
    document.head.appendChild(s);
  }

  // Register global action
  window.Orchestra = window.Orchestra || {};
  window.Orchestra._actionHandlers = window.Orchestra._actionHandlers || {};
  window.Orchestra._actionHandlers['open-miles'] = () => { location.hash = '#/miles'; };
  window.Orchestra._actionHandlers['new-task'] = () => {
    if (window.Orchestra.toast) window.Orchestra.toast('Starting new task…', 'info');
    setTimeout(() => { location.hash = '#/chat'; }, 300);
  };

  window.Orchestra.pages = window.Orchestra.pages || {};
  window.Orchestra.pages.home = { mount };
})();
