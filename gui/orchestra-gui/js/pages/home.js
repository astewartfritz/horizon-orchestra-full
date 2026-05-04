// Orchestra — Home dashboard
(function () {
  const { icons } = window;
  const { metricCard, tileCard, sparkline, hexToAlpha } = window.Orchestra.cards;

  // Pre-generate mock sparkline data
  function wave(seed, len = 20, base = 50, amp = 20) {
    const out = [];
    let x = seed;
    for (let i = 0; i < len; i++) {
      x = (x * 9301 + 49297) % 233280;
      const r = x / 233280;
      out.push(base + Math.sin(i / 2) * amp + (r - 0.5) * amp * 0.6);
    }
    return out;
  }

  function greeting() {
    const h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 18) return 'Good afternoon';
    return 'Good evening';
  }

  function dateStr() {
    return new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
  }

  function render() {
    const M = window.MOCK;
    const cpu = M.health.cpu;
    const gpu = M.health.gpu;
    const mem = M.health.memory;
    const net = M.health.network;

    return `
      <div class="page page--home split">
        <div class="split__main">
          <div class="page" style="padding-top:0">
            <div class="page__inner">
              <div class="page-header">
                <div>
                  <h1>${greeting()}, ${MOCK.user.name.split(' ')[0]}</h1>
                  <div class="sub">${dateStr()} · Orchestra is watching ${M.agents.length} agents across ${M.verticals.length} verticals</div>
                </div>
                <div style="display:flex;gap:8px">
                  <button class="btn btn--ghost">${icons.refresh(13)} Refresh</button>
                  <button class="btn btn--primary" data-action="new-task">${icons.plus(13)} New task</button>
                </div>
              </div>

              <div class="grid grid--4" style="margin-bottom:32px">
                ${metricCard({
                  label: 'Active Agents', value: M.metrics.activeAgents,
                  iconKey: 'agents', accent: 'accent',
                  trend: 12, trendLabel: 'vs last week',
                  sparkValues: wave(1, 20, 22, 4), sparkColor: '#6E6EF5',
                })}
                ${metricCard({
                  label: 'Tasks Today', value: M.metrics.tasksToday,
                  iconKey: 'tasks', accent: 'teal',
                  trend: 8, trendLabel: 'vs yesterday',
                  sparkValues: wave(2, 20, 130, 25), sparkColor: '#00C9B8',
                })}
                ${metricCard({
                  label: 'Verticals Online', value: M.metrics.verticals,
                  iconKey: 'verticals', accent: 'success',
                  trend: 0, trendLabel: 'all operational',
                  sparkValues: wave(3, 20, 9, 0.5), sparkColor: '#34D399',
                })}
                ${metricCard({
                  label: 'Tests Passing', value: M.metrics.testsPassing.toLocaleString(), unit: '/ 1,450',
                  iconKey: 'shield', accent: 'warn',
                  trend: 2, trendLabel: 'this hour',
                  sparkValues: wave(4, 20, 1440, 10), sparkColor: '#F5B971',
                })}
              </div>

              <!-- Quick launch -->
              <div class="section-title">
                <h3>Quick launch</h3>
                <a class="action" href="#/agents">View all →</a>
              </div>
              <div class="grid grid--3" style="margin-bottom:36px">
                ${M.tiles.map(tileCard).join('')}
              </div>

              <!-- System health + activity -->
              <div class="grid grid--2" style="gap:20px;align-items:stretch">
                <div class="card" style="padding:24px">
                  <div class="section-title">
                    <h3>System health</h3>
                    <span class="badge badge--success"><span class="dot online"></span> All green</span>
                  </div>
                  <div>
                    ${healthRow('CPU', cpu, '#6E6EF5', wave(11, 40, cpu, 10))}
                    ${healthRow('GPU', gpu, '#F5B971', wave(12, 40, gpu, 8))}
                    ${healthRow('Memory', mem, '#00C9B8', wave(13, 40, mem, 6))}
                    ${healthRow('Network', net, '#34D399', wave(14, 40, net, 12))}
                  </div>
                  <div style="display:flex;gap:24px;margin-top:20px;padding-top:16px;border-top:1px solid var(--border-subtle);font-size:12.5px;color:var(--text-2)">
                    <div><span style="color:var(--text);font-weight:500">${(cpu/100*32).toFixed(1)} cores</span> in use</div>
                    <div><span style="color:var(--text);font-weight:500">${(gpu/100*4).toFixed(1)}</span> of 4 GPUs</div>
                    <div><span style="color:var(--text);font-weight:500">${(mem/100*128).toFixed(0)} GB</span> / 128 GB</div>
                  </div>
                </div>

                <!-- BUG 7: Activity feed items navigable to relevant pages -->
                <div class="card" style="padding:24px">
                  <div class="section-title">
                    <h3>Live activity</h3>
                    <span class="action">Stream</span>
                  </div>
                  <div class="activity">
                    ${M.activity.map((a, i) => `
                      <div class="activity__item activity__item--clickable" data-activity-idx="${i}" style="cursor:pointer">
                        <div class="activity__icon" style="background:${hexToAlpha(a.color, 0.14)};color:${a.color}">
                          ${icons[a.icon] ? icons[a.icon](14) : icons.sparkles(14)}
                        </div>
                        <div class="activity__body">
                          <div class="activity__title">
                            <strong>${escapeHTML(a.who)}</strong>
                            <span class="op"> ${escapeHTML(a.op)} </span>
                            <span class="what">${escapeHTML(a.what)}</span>
                          </div>
                          <div class="activity__meta">${icons.clock(10)} <span>${escapeHTML(a.time)}</span></div>
                        </div>
                      </div>
                    `).join('')}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        <aside class="split__side">
          ${rightPanelHTML()}
        </aside>
      </div>
    `;
  }

  function healthRow(label, val, color, spark) {
    return `
      <div class="health-row">
        <div class="health-row__label">${label}</div>
        <div class="health-row__bar"><div class="fill" style="width:${val}%;background:linear-gradient(90deg, ${color}, ${hexToAlpha(color,0.6)})"></div></div>
        <div class="health-row__val">${val}%</div>
      </div>`;
  }

  function rightPanelHTML() {
    const M = window.MOCK;
    return `
      <div class="rpanel">
        <div class="rpanel__section">
          <h4>${icons.star(11)} Favorites</h4>
          ${M.favorites.map(f => `
            <a class="fav" href="${f.href}">
              <span class="icon">${icons[f.icon] ? icons[f.icon](14) : icons.sparkles(14)}</span>
              <span>${escapeHTML(f.label)}</span>
            </a>`).join('')}
        </div>

        <!-- BUG 6: Running tasks clickable to navigate to #/tasks -->
        <div class="rpanel__section">
          <h4>${icons.activity(11)} Running tasks
            <span class="badge badge--accent" style="margin-left:auto">${M.runningTasks.length}</span>
          </h4>
          ${M.runningTasks.map(t => `
            <div class="task-mini" data-task-id="${t.id}" style="cursor:pointer">
              <div class="task-mini__head">
                <span class="pulse"></span>
                <span class="task-mini__title">${escapeHTML(t.title)}</span>
              </div>
              <div class="task-mini__progress"><div class="fill" style="width:${t.progress * 100}%"></div></div>
              <div class="task-mini__meta">
                <span>${escapeHTML(t.agent)}</span>
                <span>${escapeHTML(t.eta)} left</span>
              </div>
            </div>`).join('')}
          <a class="btn btn--ghost btn--sm" href="#/tasks" style="margin-top:8px;width:100%;justify-content:center">View all tasks ${icons.chevronRight(12)}</a>
        </div>

        <div class="rpanel__section">
          <h4>${icons.miles(11)} MILES suggestions</h4>
          ${M.milesSuggestions.map(s => `
            <div class="suggestion">
              <span class="m-icon">${icons.miles(14)}</span>
              <div class="s-text">
                <div class="s-title">${escapeHTML(s.title)}</div>
                <div class="s-body">${escapeHTML(s.body)}</div>
              </div>
            </div>`).join('')}
        </div>
      </div>`;
  }

  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Determine which page an activity item links to
  function activityNavTarget(a) {
    // If icon suggests an agent type — agent pages
    const agentIcons = ['medical', 'beaker', 'dna', 'nursing'];
    const taskIcons  = ['file', 'truck', 'shield', 'wallet', 'graph', 'factory', 'bolt'];
    if (agentIcons.includes(a.icon)) return '#/agents';
    if (taskIcons.includes(a.icon)) return '#/tasks';
    return '#/agents';
  }

  function mount(root) {
    root.innerHTML = render();

    // Wire "New task" button → navigate to chat with toast
    root.querySelectorAll('.btn.btn--primary').forEach(btn => {
      if (btn.textContent.includes('New task')) {
        btn.addEventListener('click', () => {
          window.Orchestra.toast('Starting new task…', 'info');
          setTimeout(() => { location.hash = '#/chat'; }, 300);
        });
      }
    });

    // Wire "Stream" action span → navigate to #/tasks
    root.querySelectorAll('.action').forEach(el => {
      if (el.textContent.trim() === 'Stream') {
        el.style.cursor = 'pointer';
        el.addEventListener('click', () => {
          location.hash = '#/tasks';
        });
      }
    });

    // BUG 6: Wire running task items → #/tasks with task selected
    root.querySelectorAll('[data-task-id]').forEach(el => {
      el.addEventListener('click', () => {
        const id = el.dataset.taskId;
        // Store the task id for the tasks page to pick up
        window._homeSelectedTaskId = id;
        location.hash = '#/tasks';
      });
    });

    // BUG 7: Wire activity feed items → relevant pages
    root.querySelectorAll('[data-activity-idx]').forEach(el => {
      el.addEventListener('click', () => {
        const idx = parseInt(el.dataset.activityIdx, 10);
        const a = window.MOCK.activity[idx];
        if (a) location.hash = activityNavTarget(a);
      });
    });
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.pages = window.Orchestra.pages || {};
  // Register global actions
  window.Orchestra = window.Orchestra || {};
  window.Orchestra._actionHandlers = window.Orchestra._actionHandlers || {};
  window.Orchestra._actionHandlers['new-task'] = () => {
    if (window.Orchestra.toast) window.Orchestra.toast('Starting new task…', 'info');
    setTimeout(() => { location.hash = '#/chat'; }, 300);
  };

  window.Orchestra.pages = window.Orchestra.pages || {};
  window.Orchestra.pages.home = { mount };
})();
