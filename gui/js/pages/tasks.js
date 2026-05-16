// Orchestra — Tasks page (live execution view)
(function () {
  const { icons } = window;

  let state = {
    selectedId: null,
    tab: 'active', // 'active' | 'history'
    liveTimer: null,
  };

  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function render() {
    if (!state.selectedId) {
      state.selectedId = window.MOCK.runningTasks[0]?.id;
    }
    const selected = window.MOCK.runningTasks.find(t => t.id === state.selectedId)
      || window.MOCK.runningTasks[0];

    return `
      <div class="page page--tasks">
        <div class="page__inner" style="max-width:none;padding:24px 32px 48px">
          <div class="page-header">
            <div>
              <h1>Task runner</h1>
              <div class="sub">Watch agents execute in real-time. Intervene, approve, or branch at any step.</div>
            </div>
            <div style="display:flex;gap:8px">
              <button class="btn btn--ghost">${icons.refresh(13)} Refresh</button>
              <button class="btn btn--primary">${icons.plus(13)} New task</button>
            </div>
          </div>

          <div class="tabs">
            <button class="tab ${state.tab === 'active' ? 'is-active' : ''}" data-tab="active">
              Active <span class="badge badge--accent" style="margin-left:8px">${window.MOCK.runningTasks.length}</span>
            </button>
            <button class="tab ${state.tab === 'history' ? 'is-active' : ''}" data-tab="history">
              History <span style="color:var(--text-3);margin-left:8px">${window.MOCK.completedTasks.length}</span>
            </button>
          </div>

          ${state.tab === 'active' ? renderActive(selected) : renderHistory()}
        </div>
      </div>
    `;
  }

  function renderActive(sel) {
    return `
      <div style="display:grid;grid-template-columns:320px 1fr;gap:20px;min-height:600px">
        <!-- Left: task list -->
        <div style="display:flex;flex-direction:column;gap:10px">
          ${window.MOCK.runningTasks.map(t => `
            <div class="task-mini" data-select-task="${t.id}"
                 style="${t.id === sel?.id ? 'border-color:rgba(110,110,245,0.4);background:var(--bg-2)' : ''}">
              <div class="task-mini__head">
                <span class="pulse"></span>
                <span class="task-mini__title">${escapeHTML(t.title)}</span>
                <span style="font-family:var(--font-mono);font-size:11px;color:var(--text-3)">${escapeHTML(t.id)}</span>
              </div>
              <div class="task-mini__progress"><div class="fill" data-progress-fill="${t.id}" style="width:${t.progress * 100}%"></div></div>
              <div class="task-mini__meta">
                <span>${escapeHTML(t.agent)}</span>
                <span>${Math.round(t.progress * 100)}% · ${escapeHTML(t.eta)} left</span>
              </div>
            </div>
          `).join('')}
        </div>

        <!-- Right: detail -->
        <div class="card" style="padding:0;overflow:hidden;display:flex;flex-direction:column;min-height:600px">
          ${sel ? renderDetail(sel) : `<div class="empty">Select a task to view execution</div>`}
        </div>
      </div>
    `;
  }

  function renderDetail(t) {
    const done = t.steps.filter(s => s.status === 'done').length;
    return `
      <div style="padding:20px 24px;border-bottom:1px solid var(--border-subtle)">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:16px">
          <div>
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">
              <span class="dot online"></span>
              <span style="color:var(--text-2);font-size:12px;font-family:var(--font-mono)">${escapeHTML(t.id)}</span>
              <span class="badge badge--accent">${escapeHTML(t.agent)}</span>
            </div>
            <h3 style="font-size:18px">${escapeHTML(t.title)}</h3>
          </div>
          <div style="display:flex;gap:8px">
            <button class="btn btn--ghost btn--sm">${icons.play(12)} Resume</button>
            <button class="btn btn--ghost btn--sm">Pause</button>
            <button class="btn btn--ghost btn--sm" style="color:var(--danger)">Abort</button>
          </div>
        </div>

        <div style="display:flex;gap:24px;margin-top:14px;font-size:12.5px;color:var(--text-2)">
          <div><span style="color:var(--text);font-weight:500">${done}</span> / ${t.steps.length} steps</div>
          <div>Elapsed <span style="color:var(--text);font-weight:500">${escapeHTML(t.elapsed)}</span></div>
          <div>ETA <span style="color:var(--text);font-weight:500">${escapeHTML(t.eta)}</span></div>
          <div style="margin-left:auto;font-family:var(--font-mono);color:var(--text-3)">pid 0x${Math.floor(Math.random() * 65535).toString(16).padStart(4, '0')}</div>
        </div>

        <div style="margin-top:14px;height:4px;background:var(--bg-3);border-radius:999px;overflow:hidden">
          <div style="height:100%;width:${t.progress * 100}%;background:linear-gradient(90deg,var(--accent),var(--teal));transition:width 600ms"></div>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:0;flex:1;min-height:0">
        <!-- Plan -->
        <div style="padding:20px 24px;border-right:1px solid var(--border-subtle);overflow-y:auto">
          <h4 style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-3);margin-bottom:12px">Execution plan</h4>
          ${window.Orchestra.checklist.render({ title: 'Steps', items: t.steps })}

          <h4 style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-3);margin:20px 0 12px">Diff preview</h4>
          ${window.Orchestra.codediff.renderDiff({
            path: 'output/plan.yaml',
            adds: 8, rems: 2,
            lines: [
              { kind: 'ctx', n: 14, text: 'strategy: time-window-vrp' },
              { kind: 'rem', n: 15, text: 'max_stops_per_driver: 14' },
              { kind: 'add', n: 15, text: 'max_stops_per_driver: 18' },
              { kind: 'ctx', n: 16, text: 'drivers:' },
              { kind: 'add', n: 17, text: '  - id: D-004  # rebalanced from cluster 7' },
              { kind: 'add', n: 18, text: '    stops: [S-12, S-47, S-81, S-103]' },
              { kind: 'ctx', n: 19, text: '  - id: D-005' },
              { kind: 'rem', n: 20, text: '    stops: [S-12, S-47]' },
              { kind: 'add', n: 20, text: '    stops: [S-200, S-201, S-202]' },
            ],
          })}
        </div>

        <!-- Terminal + state -->
        <div style="padding:20px 24px;overflow-y:auto;background:var(--bg-0)">
          <h4 style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-3);margin-bottom:12px">Live output</h4>
          ${window.Orchestra.terminal.render({ title: t.id + ' · orchestra', lines: t.terminal, running: true })}

          <h4 style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-3);margin:20px 0 12px">Tool invocations</h4>
          <div class="tool-calls">
            <div class="tool-call done"><span class="icon">${icons.file(12)}</span><span>fs.read manifest.json</span></div>
            <div class="tool-call done"><span class="icon">${icons.terminal(12)}</span><span>shell: solver init</span></div>
            <div class="tool-call is-working"><span class="icon">${icons.terminal(12)}</span><span>shell: OR-Tools search</span></div>
            <div class="tool-call"><span class="icon">${icons.report ? icons.report(12) : icons.file(12)}</span><span>report.publish</span></div>
          </div>

          <h4 style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-3);margin:20px 0 12px">Metrics</h4>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
            <div style="padding:12px;background:var(--bg-1);border-radius:10px;border:1px solid var(--border-subtle)">
              <div style="font-size:11px;color:var(--text-3)">Best solution</div>
              <div style="font-size:18px;font-weight:600;font-family:var(--font-mono)">1,288 mi</div>
              <div style="font-size:11px;color:var(--success);margin-top:2px">↓ 8.8% from baseline</div>
            </div>
            <div style="padding:12px;background:var(--bg-1);border-radius:10px;border:1px solid var(--border-subtle)">
              <div style="font-size:11px;color:var(--text-3)">Iterations</div>
              <div style="font-size:18px;font-weight:600;font-family:var(--font-mono)" data-iterations>1,412</div>
              <div style="font-size:11px;color:var(--text-2);margin-top:2px">@ 282 it/s</div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function renderHistory() {
    return `
      <div class="card" style="padding:0;overflow:hidden">
        <table class="md" style="width:100%;border-collapse:collapse;margin:0;border-radius:0;border:none">
          <thead>
            <tr style="background:var(--bg-2)">
              <th style="padding:12px 16px;text-align:left;font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em;font-weight:600">Task</th>
              <th style="padding:12px 16px;text-align:left;font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em;font-weight:600">Agent</th>
              <th style="padding:12px 16px;text-align:left;font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em;font-weight:600">Status</th>
              <th style="padding:12px 16px;text-align:left;font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em;font-weight:600">Duration</th>
              <th style="padding:12px 16px;text-align:left;font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em;font-weight:600">When</th>
              <th style="padding:12px 16px"></th>
            </tr>
          </thead>
          <tbody>
            ${window.MOCK.completedTasks.map(t => `
              <tr style="border-top:1px solid var(--border-subtle)">
                <td style="padding:12px 16px">
                  <div style="font-weight:500">${escapeHTML(t.title)}</div>
                  <div style="font-size:11px;color:var(--text-3);font-family:var(--font-mono);margin-top:2px">${escapeHTML(t.id)}</div>
                </td>
                <td style="padding:12px 16px;color:var(--text-2)">${escapeHTML(t.agent)}</td>
                <td style="padding:12px 16px">
                  <span class="badge badge--${t.status === 'success' ? 'success' : 'danger'}">
                    ${t.status === 'success' ? '✓ Success' : '✗ Failed'}
                  </span>
                </td>
                <td style="padding:12px 16px;font-family:var(--font-mono);font-size:12.5px">${escapeHTML(t.duration)}</td>
                <td style="padding:12px 16px;color:var(--text-2);font-size:12.5px">${escapeHTML(t.when)}</td>
                <td style="padding:12px 16px;text-align:right">
                  <button class="icon-btn" aria-label="Details">${icons.chevronRight(14)}</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  function wire() {
    document.querySelectorAll('[data-tab]').forEach(el => {
      el.addEventListener('click', () => {
        state.tab = el.dataset.tab;
        mount(document.querySelector('.main .page-root'));
      });
    });

    document.querySelectorAll('[data-select-task]').forEach(el => {
      el.addEventListener('click', () => {
        state.selectedId = el.dataset.selectTask;
        mount(document.querySelector('.main .page-root'));
      });
    });
  }

  // Live-ish animation: tick iteration counter + inch progress bars
  function startLive() {
    stopLive();
    state.liveTimer = setInterval(() => {
      const it = document.querySelector('[data-iterations]');
      if (it) {
        const n = parseInt(it.textContent.replace(/,/g, '')) + Math.floor(Math.random() * 20 + 15);
        it.textContent = n.toLocaleString();
      }
      // Advance each task's visible progress subtly
      window.MOCK.runningTasks.forEach(t => {
        if (t.progress < 0.97) {
          t.progress = Math.min(0.97, t.progress + 0.004 + Math.random() * 0.005);
          const f = document.querySelector(`[data-progress-fill="${t.id}"]`);
          if (f) f.style.width = (t.progress * 100) + '%';
        }
      });

      // Append a line to the terminal
      const term = document.querySelector('.term__body');
      if (term && Math.random() < 0.35) {
        const msgs = [
          { kind: 'out', text: `Search: ${Math.floor(Math.random()*30+5)}s | best: ${Math.floor(1200 + Math.random()*100)}mi | improved x${Math.floor(Math.random()*5+1)}` },
          { kind: 'out', text: `Checking driver ${Math.floor(Math.random() * 18 + 1).toString().padStart(3,'0')} constraints…` },
          { kind: 'ok',  text: '✓ Feasibility ok' },
        ];
        window.Orchestra.terminal.append(term.closest('.term'), msgs[Math.floor(Math.random()*msgs.length)]);
      }
    }, 1200);
  }

  function stopLive() {
    if (state.liveTimer) { clearInterval(state.liveTimer); state.liveTimer = null; }
  }

  function mount(root) {
    root.innerHTML = render();
    wire();
    if (state.tab === 'active') startLive(); else stopLive();
  }

  function unmount() { stopLive(); }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.pages = window.Orchestra.pages || {};
  window.Orchestra.pages.tasks = { mount, unmount };
})();
