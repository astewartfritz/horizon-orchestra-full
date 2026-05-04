// Orchestra — Tasks page (live execution view)
(function () {
  const { icons } = window;

  let state = {
    selectedId: null,
    tab: 'active', // 'active' | 'history'
    liveTimer: null,
    historySelectedId: null,
  };

  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function render() {
    // BUG 6: Support auto-selecting a task set from home page
    if (window._homeSelectedTaskId) {
      state.selectedId = window._homeSelectedTaskId;
      window._homeSelectedTaskId = null;
    }

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
              <button class="btn btn--primary">${icons.plus(13)} New task" data-action="new-task</button>
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

        <!-- BUG 9: History detail panel -->
        ${state.tab === 'history' ? `
          <div class="detail-overlay ${state.historySelectedId ? 'is-open' : ''}" data-history-overlay></div>
          <aside class="detail-panel ${state.historySelectedId ? 'is-open' : ''}" data-history-panel>
            <div class="detail-panel__head">
              <div style="flex:1" data-history-head></div>
              <button class="icon-btn" data-close-history aria-label="Close">${icons.x(16)}</button>
            </div>
            <div class="detail-panel__body" data-history-body></div>
          </aside>` : ''}
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
    const isPaused = t._paused || false;
    return `
      <div style="padding:20px 24px;border-bottom:1px solid var(--border-subtle)">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:16px">
          <div>
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">
              <span class="dot ${isPaused ? 'busy' : 'online'}" data-status-dot="${t.id}"></span>
              <span style="color:var(--text-2);font-size:12px;font-family:var(--font-mono)">${escapeHTML(t.id)}</span>
              <span class="badge badge--accent">${escapeHTML(t.agent)}</span>
            </div>
            <h3 style="font-size:18px">${escapeHTML(t.title)}</h3>
          </div>
          <div style="display:flex;gap:8px">
            <button class="btn btn--ghost btn--sm" data-task-action="resume" data-action="task-resume" data-task-id="${t.id}">${icons.play(12)} Resume</button>
            <button class="btn btn--ghost btn--sm" data-task-action="pause" data-task-id="${t.id}" data-action="task-pause">Pause</button>
            <button class="btn btn--ghost btn--sm" style="color:var(--danger)" data-task-action="abort" data-task-id="${t.id}" data-action="task-abort">Abort</button>
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
              <tr style="border-top:1px solid var(--border-subtle);cursor:pointer;transition:background var(--dur) var(--ease)" data-history-task="${t.id}" class="history-row">
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
                  <button class="icon-btn" aria-label="Details" data-history-detail="${t.id}">${icons.chevronRight(14)}</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  // BUG 9: History detail panel render
  function renderHistoryDetail(t) {
    const summaries = {
      'T-7028': 'Processed 1,248 transactions across 5 bank accounts. Identified 3 variance lines totaling $4,212. All cleared within tolerance except variance ID VAR-009 which was flagged for manual review.',
      'T-7027': 'Published Week 48 shift schedule across 12 nursing units. Balanced acuity scores within 8% of target. 3 nurses swapped from high-acuity to medium-acuity wards based on patient load.',
      'T-7026': 'Digital twin simulation completed for Line B. Predicted 4h downtime window at 14:00–18:00 UTC Thursday. Recommended pre-emptive maintenance on conveyor segment C7.',
      'T-7025': 'Screened 147 counterparties against 12 sanctions lists and PEP registries. 145 cleared. 2 flagged for enhanced due diligence (GR-884, GR-912).',
      'T-7024': 'Failed during clause parsing at section 7.3. Root cause: malformed table in MSA revision 7 PDF. Schema patch available — ready to retry.',
      'T-7023': 'Annotated 4,218 variants for sample CG-882-A. 12 variants classified as Pathogenic, 31 as Likely Pathogenic. Clinical report generated and published to workspace.',
    };
    const summary = summaries[t.id] || 'Task completed. See logs for details.';

    return `
      <div style="display:flex;gap:14px;align-items:flex-start">
        <div>
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
            <span class="badge badge--${t.status === 'success' ? 'success' : 'danger'}">
              ${t.status === 'success' ? '✓ Completed' : '✗ Failed'}
            </span>
            <span style="font-family:var(--font-mono);font-size:12px;color:var(--text-3)">${escapeHTML(t.id)}</span>
          </div>
          <h3 style="font-size:17px;margin-bottom:4px">${escapeHTML(t.title)}</h3>
          <div style="font-size:12.5px;color:var(--text-2)">${escapeHTML(t.agent)} · ${escapeHTML(t.when)}</div>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:20px">
        <div style="padding:14px;background:var(--bg-2);border-radius:10px;border:1px solid var(--border-subtle)">
          <div style="font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em">Duration</div>
          <div style="font-size:20px;font-weight:600;font-family:var(--font-mono);margin-top:4px">${escapeHTML(t.duration)}</div>
        </div>
        <div style="padding:14px;background:var(--bg-2);border-radius:10px;border:1px solid var(--border-subtle)">
          <div style="font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em">Status</div>
          <div style="font-size:20px;font-weight:600;margin-top:4px;color:${t.status === 'success' ? 'var(--success)' : 'var(--danger)'}">
            ${t.status === 'success' ? 'Success' : 'Failed'}
          </div>
        </div>
      </div>

      <div style="margin-top:20px;padding:16px;background:var(--bg-2);border-radius:10px;border:1px solid var(--border-subtle)">
        <h4 style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-3);margin-bottom:10px">Summary</h4>
        <p style="color:var(--text-2);font-size:13px;line-height:1.6">${escapeHTML(summary)}</p>
      </div>

      <div style="margin-top:20px">
        <h4 style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-3);margin-bottom:12px">Timeline</h4>
        ${[
          { label: 'Task queued',    time: 'Start' },
          { label: 'Agent assigned', time: '+0s' },
          { label: 'Execution began',time: '+2s' },
          { label: 'Task completed', time: t.duration },
        ].map(e => `
          <div style="display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid var(--border-subtle);font-size:12.5px">
            <span style="color:var(--text-3);font-family:var(--font-mono);width:60px">${escapeHTML(e.time)}</span>
            <span style="color:var(--text-2)">${escapeHTML(e.label)}</span>
          </div>`).join('')}
      </div>

      <div style="display:flex;gap:8px;margin-top:24px">
        <button class="btn btn--primary" style="flex:1;justify-content:center">${icons.refresh(13)} Re-run</button>
        <button class="btn btn--ghost">${icons.file(13)} View logs</button>
      </div>
    `;
  }

  function openHistoryDetail(id) {
    state.historySelectedId = id;
    const t = window.MOCK.completedTasks.find(x => x.id === id);
    if (!t) return;

    const head = document.querySelector('[data-history-head]');
    const body = document.querySelector('[data-history-body]');
    const panel = document.querySelector('[data-history-panel]');
    const overlay = document.querySelector('[data-history-overlay]');

    if (head) head.innerHTML = `<h3 style="font-size:16px">${escapeHTML(t.title)}</h3>`;
    if (body) body.innerHTML = renderHistoryDetail(t);
    if (panel) panel.classList.add('is-open');
    if (overlay) overlay.classList.add('is-open');
  }

  function closeHistoryDetail() {
    state.historySelectedId = null;
    document.querySelector('[data-history-panel]')?.classList.remove('is-open');
    document.querySelector('[data-history-overlay]')?.classList.remove('is-open');
  }

  function showAbortConfirm(taskId) {
    // Remove existing confirm if any
    document.querySelector('[data-abort-confirm]')?.remove();
    const div = document.createElement('div');
    div.setAttribute('data-abort-confirm', '');
    div.style.cssText = 'position:fixed;inset:0;background:rgba(9,9,14,0.7);backdrop-filter:blur(6px);z-index:300;display:flex;align-items:center;justify-content:center';
    div.innerHTML = `
      <div style="background:var(--bg-2);border:1px solid var(--border);border-radius:var(--r-xl);width:360px;max-width:92vw;box-shadow:var(--shadow-lg);padding:28px;" onclick="event.stopPropagation()">
        <h3 style="font-size:17px;margin-bottom:8px">Abort this task?</h3>
        <p style="color:var(--text-2);font-size:13px;line-height:1.55;margin-bottom:24px">This cannot be undone. The task will be moved to history as Aborted.</p>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button class="btn btn--ghost" data-abort-cancel>Cancel</button>
          <button class="btn btn--primary" style="background:var(--danger);border-color:var(--danger)" data-abort-confirm-btn data-action="task-abort">Abort</button>
        </div>
      </div>
    `;
    document.body.appendChild(div);
    div.querySelector('[data-abort-cancel]').addEventListener('click', () => div.remove());
    div.addEventListener('click', (e) => { if (e.target === div) div.remove(); });
    div.querySelector('[data-abort-confirm-btn]').addEventListener('click', () => {
      const t = window.MOCK.runningTasks.find(x => x.id === taskId);
      if (t) {
        // Remove from active, add to history
        window.MOCK.runningTasks = window.MOCK.runningTasks.filter(x => x.id !== taskId);
        window.MOCK.completedTasks.unshift({
          id: t.id,
          title: t.title,
          agent: t.agent,
          status: 'failed',
          duration: t.elapsed || '0s',
          when: 'just now',
        });
        if (state.selectedId === taskId) {
          state.selectedId = window.MOCK.runningTasks[0]?.id || null;
        }
      }
      div.remove();
      window.Orchestra.toast('Task aborted', 'error');
      mount(document.querySelector('.main .page-root'));
    });
  }

  function wire() {
    // Wire "New task" button
    document.querySelectorAll('.btn.btn--primary').forEach(btn => {
      if (btn.textContent.includes('New task')) {
        btn.addEventListener('click', () => {
          window.Orchestra.toast('Starting new task…', 'info');
          setTimeout(() => { location.hash = '#/chat'; }, 300);
        });
      }
    });

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

    // Wire Resume / Pause / Abort buttons using delegated listener on the page root
    // Attach directly to current task action buttons to avoid duplicates on re-mount
    document.querySelectorAll('[data-task-action]').forEach(btn => {
      btn.addEventListener('click', () => {
        const action = btn.dataset.taskAction;
        const taskId = btn.dataset.taskId;
        const t = window.MOCK.runningTasks.find(x => x.id === taskId);
        if (!t) return;
        if (action === 'resume') {
          t._paused = false;
          window.Orchestra.toast('Task resumed', 'success');
          mount(document.querySelector('.main .page-root'));
        } else if (action === 'pause') {
          t._paused = true;
          window.Orchestra.toast('Task paused', 'warn');
          mount(document.querySelector('.main .page-root'));
        } else if (action === 'abort') {
          showAbortConfirm(taskId);
        }
      });
    });

    // BUG 9: Wire history rows and chevrons
    document.querySelectorAll('[data-history-task]').forEach(el => {
      el.addEventListener('click', (e) => {
        const id = el.dataset.historyTask;
        openHistoryDetail(id);
      });
      // Hover style
      el.addEventListener('mouseenter', () => el.style.background = 'var(--bg-2)');
      el.addEventListener('mouseleave', () => el.style.background = '');
    });

    document.querySelectorAll('[data-close-history]').forEach(btn => {
      btn.addEventListener('click', closeHistoryDetail);
    });

    document.querySelector('[data-history-overlay]')?.addEventListener('click', closeHistoryDetail);
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
  // Register global task actions
  window.Orchestra = window.Orchestra || {};
  window.Orchestra._actionHandlers = window.Orchestra._actionHandlers || {};
  window.Orchestra._actionHandlers['task-pause'] = () => {
    if (window.Orchestra.toast) window.Orchestra.toast('Task paused', 'info');
  };
  window.Orchestra._actionHandlers['task-resume'] = () => {
    if (window.Orchestra.toast) window.Orchestra.toast('Task resumed', 'success');
  };
  window.Orchestra._actionHandlers['task-abort'] = () => {
    // Inline confirm
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:9999;display:grid;place-items:center';
    overlay.innerHTML = '<div style="background:#17171F;padding:28px;border-radius:14px;max-width:380px;border:1px solid #2A2A38"><h3 style="color:#EEEEF5;margin:0 0 8px">Abort task?</h3><p style="color:#8888A8;font-size:14px;margin:0 0 20px">This cannot be undone. The task will be terminated immediately.</p><div style="display:flex;gap:8px;justify-content:flex-end"><button onclick="this.closest(\x27[style*=fixed]\x27).remove()" style="padding:8px 16px;border-radius:8px;border:1px solid #2A2A38;background:transparent;color:#EEEEF5;cursor:pointer">Cancel</button><button onclick="this.closest(\x27[style*=fixed]\x27).remove();window.Orchestra.toast(\x27Task aborted\x27,\x27error\x27)" style="padding:8px 16px;border-radius:8px;border:none;background:#F0596A;color:white;cursor:pointer;font-weight:600" data-action="task-abort">Abort</button></div></div>';
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  };

  window.Orchestra.pages = window.Orchestra.pages || {};
  window.Orchestra.pages.tasks = { mount, unmount };
})();
