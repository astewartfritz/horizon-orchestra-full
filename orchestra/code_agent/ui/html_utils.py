"""HTML utility functions extracted from html.py."""
from __future__ import annotations


def escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def render_context_html(cd: dict) -> str:
    pct = cd["saturation_pct"]
    level = cd.get("saturation_level", "empty")
    badge_class = level if level != "empty" else "empty"

    html = """
<h3>Context Window
  <span class="ctx-header-actions">
    <button onclick="toggleContext()" title="Close context">x</button>
  </span>
</h3>

<div class="ctx-section">
  <div class="ctx-gauge">"""

    for block in cd.get("bar_blocks", []):
        w = max(0.5, block["pct"])
        html += f'<div class="ctx-gauge-block" style="width:{w}%;background:{block["color_hex"].strip()}"></div>'

    free_pct = cd.get("free_pct", 0)
    reserve_pct = cd.get("reserve_pct", 0)
    if free_pct > 0:
        html += f'<div class="ctx-gauge-free" style="width:{free_pct}%"></div>'
    if reserve_pct > 0:
        html += f'<div class="ctx-gauge-reserve" style="width:{reserve_pct}%"></div>'

    html += """  </div>
  <div class="ctx-stat-row">
    <span class="lbl">Tokens</span>
    <span class="val">""" + f"{fmt_tokens(cd['used_tokens'])} / {fmt_tokens(cd['max_tokens'])}" + f"""</span>
  </div>
  <div class="ctx-stat-row">
    <span class="lbl">Saturation</span>
    <span class="val"><span class="ctx-badge {badge_class}">{level.upper()}</span> {pct}%</span>
  </div>
</div>

<div class="ctx-section">
  <h4>Tier Breakdown</h4>"""

    for t in cd.get("tiers", []):
        if t["count"] == 0:
            continue
        html += f"""
  <div class="ctx-tier">
    <div class="ctx-dot" style="background:{t['color_hex'].strip()}"></div>
    <span>{t['name']}</span>
    <span class="ctx-tier-tokens">{fmt_tokens(t['tokens'])}</span>
    <span class="ctx-tier-count">{t['count']} entries</span>
  </div>"""

    if not cd.get("tiers") or all(t["count"] == 0 for t in cd["tiers"]):
        html += '<div style="color:#8b949e;font-size:11px;padding:4px 0">No entries yet</div>'

    html += """</div>

<div class="ctx-section">
  <h4>Stats</h4>
  <div class="ctx-stat-row"><span class="lbl">Entries</span><span class="val">${cd['entries']}</span></div>
  <div class="ctx-stat-row"><span class="lbl">Free</span><span class="val">${fmt_tokens(cd['free_tokens'])}</span></div>
  <div class="ctx-stat-row"><span class="lbl">Reserve</span><span class="val">${fmt_tokens(cd['reserve_tokens'])}</span></div>
  <div class="ctx-stat-row"><span class="lbl">Used</span><span class="val">${fmt_tokens(cd['used_tokens'])}</span></div>
</div>"""

    sources = cd.get("sources", {})
    if sources:
        html += '<div class="ctx-section"><h4>Sources</h4>'
        for src, tok in list(sources.items())[:6]:
            html += f'<div class="ctx-stat-row"><span class="lbl">{src}</span><span class="val">{fmt_tokens(tok)}</span></div>'
        html += '</div>'

    entries = cd.get("entries_list", [])
    if entries:
        html += '<div class="ctx-section"><h4>Building <span class="ctx-section-count">' + str(len(entries)) + '</span></h4>'
        html += '<div class="ctx-entries">'
        for i, entry in enumerate(entries):
            preview = entry.get("content", "")[:100]
            if len(entry.get("content", "")) > 100:
                preview += "..."
            tier = entry.get("tier", "normal")
            source = entry.get("source", "")
            tokens = entry.get("tokens", 0)
            color = {"critical": "#ff5050", "important": "#ffb432", "normal": "#50a0ff", "low": "#8c8ca0"}.get(tier, "#888")
            pending_class = " pending" if i >= len(entries) - 3 else ""
            html += f'<div class="ctx-entry{pending_class}">'
            html += f'<div class="ctx-entry-dot" style="background:{color}"></div>'
            html += '<div class="ctx-entry-body">'
            html += '<div class="ctx-entry-head">'
            if source:
                html += f'<span class="ctx-entry-source">{source}</span>'
            html += f'<span class="ctx-entry-tokens">{fmt_tokens(tokens)}</span>'
            html += '</div>'
            full_content = entry.get("content", "")
            if len(full_content) > 100:
                html += f'<div class="ctx-entry-text" id="ctx-text-{i}">{escape_html(preview)}</div>'
                html += f'<button class="ctx-entry-expand" onclick="toggleCtxEntry({i})">more</button>'
            else:
                html += f'<div class="ctx-entry-text">{escape_html(preview)}</div>'
            html += '</div></div>'
        html += '</div></div>'

    html += """
<div class="ctx-actions">
  <button onclick="htmx.ajax('POST', '/api/context/add-demo', {target:'#ctx-inner',swap:'innerHTML'})" title="Add demo data">Demo</button>
  <button onclick="htmx.ajax('POST', '/api/context/clear', {target:'#ctx-inner',swap:'innerHTML'})" title="Clear context">Clear</button>
</div>"""

    return html
