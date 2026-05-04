// Orchestra — Cards (metric, tile, agent)
(function () {
  const { icons } = window;

  function escapeHTML(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // Generate a smooth sparkline as SVG path given array of numbers.
  function sparkline(values, { w = 260, h = 36, color = '#6E6EF5', gradient = true } = {}) {
    if (!values || !values.length) return '';
    const max = Math.max(...values);
    const min = Math.min(...values);
    const range = Math.max(1, max - min);
    const step = w / (values.length - 1);
    const pts = values.map((v, i) => [i * step, h - 4 - ((v - min) / range) * (h - 8)]);

    // Smooth with simple Bezier
    let d = `M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
    for (let i = 1; i < pts.length; i++) {
      const [x0, y0] = pts[i - 1];
      const [x1, y1] = pts[i];
      const cx = (x0 + x1) / 2;
      d += ` Q ${cx.toFixed(1)} ${y0.toFixed(1)} ${x1.toFixed(1)} ${y1.toFixed(1)}`;
    }
    const area = d + ` L ${w} ${h} L 0 ${h} Z`;
    const id = 'sp-' + Math.random().toString(36).slice(2, 8);

    return `
      <svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none" class="metric__spark">
        ${gradient ? `
          <defs>
            <linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="${color}" stop-opacity="0.35"/>
              <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
            </linearGradient>
          </defs>
          <path d="${area}" fill="url(#${id})" />` : ''}
        <path d="${d}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    `;
  }

  function metricCard({ label, value, unit = '', trend = null, trendLabel = '', iconKey = 'activity', accent = 'accent', sparkValues = null, sparkColor }) {
    const trendIcon = trend > 0 ? icons.trend(11) : icons.trendDown(11);
    const trendCls = trend > 0 ? 'up' : 'down';
    return `
      <div class="metric">
        <div class="metric__head">
          <div class="metric__label">${escapeHTML(label)}</div>
          <div class="metric__icon ${accent}">${icons[iconKey] ? icons[iconKey](14) : icons.activity(14)}</div>
        </div>
        <div class="metric__value">${escapeHTML(String(value))}${unit ? `<span class="unit">${escapeHTML(unit)}</span>` : ''}</div>
        ${sparkValues ? sparkline(sparkValues, { color: sparkColor || 'var(--accent)', w: 260 }) : ''}
        <div class="metric__foot">
          ${trend !== null ? `
            <span class="metric__trend ${trendCls}">
              ${trendIcon}
              <span>${trend > 0 ? '+' : ''}${trend}%</span>
            </span>
            <span>${escapeHTML(trendLabel)}</span>
          ` : `<span>&nbsp;</span><span>&nbsp;</span>`}
        </div>
      </div>`;
  }

  function tileCard(t) {
    return `
      <a class="tile" href="${t.href}" style="--tile-glow:${t.tint}">
        <div class="tile__arrow">${icons.arrowUpRight(14)}</div>
        <div class="tile__icon">${icons[t.icon] ? icons[t.icon](18) : icons.sparkles(18)}</div>
        <div>
          <div class="tile__title">${escapeHTML(t.title)}</div>
          <div class="tile__desc">${escapeHTML(t.desc)}</div>
        </div>
      </a>`;
  }

  function agentCard(a) {
    const statusCls = a.status === 'online' ? 'online' : a.status === 'busy' ? 'busy' : 'off';
    const iconHTML = icons[a.icon] ? icons[a.icon](18) : icons.sparkles(18);
    return `
      <div class="agent-card" data-agent-id="${a.id}" style="color:${a.color}">
        <div class="agent-card__icon" style="background:${hexToAlpha(a.color, 0.14)};color:${a.color}">
          ${iconHTML}
        </div>
        <div class="agent-card__body">
          <div class="agent-card__head">
            <div class="agent-card__name" style="color:var(--text)">${escapeHTML(a.name)}</div>
            <span class="dot ${statusCls}" title="${a.status}"></span>
          </div>
          <div class="agent-card__desc">${escapeHTML(a.desc)}</div>
          <div class="agent-card__meta">
            <span>${a.tools} tools</span>
            <span class="sep"></span>
            <span style="text-transform:capitalize">${a.vertical}</span>
            <span class="sep"></span>
            <span>v2.4</span>
          </div>
        </div>
      </div>`;
  }

  function hexToAlpha(hex, a) {
    const h = hex.replace('#', '');
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${a})`;
  }

  window.Orchestra = window.Orchestra || {};
  window.Orchestra.cards = { metricCard, tileCard, agentCard, sparkline, hexToAlpha };
})();
