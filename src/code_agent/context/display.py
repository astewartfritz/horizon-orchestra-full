from __future__ import annotations

from typing import Any

from code_agent.context.manager import ContextManager

TIER_LABELS = {
    "critical": "Critical",
    "important": "Important",
    "normal": "Normal",
    "low": "Low",
}

TIER_COLORS_HEX = {
    "critical": "#ff5050",
    "important": " #ffb432",
    "normal": " #50a0ff",
    "low": " #8c8ca0",
}


def render_cli_context(manager: ContextManager, detailed: bool = False) -> str:
    """Render a beautiful CLI context window display."""
    from code_agent.context.manager import ContextManager

    vd = manager.visual_data()
    s = vd["stats"]

    _H = "="
    _V = "|"
    _TL = "+"
    _TR = "+"
    _BL = "+"
    _BR = "+"
    _MH = "+"

    lines = []
    lines.append("")
    lines.append(f"  {_TL}{_H * 53}{_TR}")

    gauge = _color_bar(vd["bar_blocks"], vd["free_pct"], vd["reserve_pct"])
    lines.append(f"  {_V} {gauge} {_V}")
    used_str = _fmt(s["used_tokens"])
    max_str = _fmt(s["max_tokens"])
    lines.append(
        f"  {_V}  {used_str:>6} / {max_str:<6} tokens  "
        f"({vd['stats']['saturation_pct']}% {vd['saturation_level']})"
        f"{' ' * 10}{_V}"
    )

    lines.append(f"  {_V}{_H * 53}{_V}")

    # Tier breakdown
    lines.append(f"  {_V}  Tier          Entries    Tokens    Share            {_V}")
    lines.append(f"  {_V}  {'-' * 45}  {_V}")
    for tier in ["critical", "important", "normal", "low"]:
        count = s["tiers"].get(tier, 0)
        tokens = s["tier_tokens"].get(tier, 0)
        if count == 0:
            continue
        share = (tokens / s["used_tokens"] * 100) if s["used_tokens"] > 0 else 0
        label = f"{TIER_LABELS[tier]:>12}"
        lines.append(
            f"  {_V}  {label}  {count:>5}   {_fmt(tokens):>8}  {share:>5.1f}%            {_V}"
        )

    if s["used_tokens"] == 0:
        lines.append(f"  {_V}  (no entries)                                      {_V}")

    lines.append(f"  {_V}{_H * 53}{_V}")

    # Source breakdown (only if detailed)
    if detailed and s.get("sources"):
        lines.append(f"  {_V}  Sources:                                          {_V}")
        for src, tok in sorted(s["sources"].items(), key=lambda x: -x[1])[:5]:
            lines.append(f"  {_V}    {src:<30}  {_fmt(tok):>8} t         {_V}")
        lines.append(f"  {_V}{_H * 53}{_V}")
    elif s.get("sources"):
        src_count = len(s["sources"])
        lines.append(f"  {_V}  Sources: {src_count} unique sources                   {_V}")

    # Reserve
    lines.append(
        f"  {_V}  Reserve:  {_fmt(s['reserve_tokens'])} tokens"
        f"{' ' * 30}{_V}"
    )
    lines.append(
        f"  {_V}  Free:     {_fmt(vd['free_tokens'])} tokens"
        f"{' ' * 30}{_V}"
    )

    lines.append(f"  {_BL}{_H * 53}{_BR}")

    return "\n".join(lines)


def render_rich_context(manager: ContextManager) -> dict[str, Any]:
    """Return structured context data for rich UI rendering (TUI, Desktop, Web)."""
    vd = manager.visual_data()
    s = vd["stats"]

    tiers = []
    for tier in ["critical", "important", "normal", "low"]:
        count = s["tiers"].get(tier, 0)
        tokens = s["tier_tokens"].get(tier, 0)
        share = (tokens / s["used_tokens"] * 100) if s["used_tokens"] > 0 else 0
        tiers.append({
            "name": TIER_LABELS[tier],
            "tier": tier,
            "count": count,
            "tokens": tokens,
            "share_pct": round(share, 1),
            "color_hex": TIER_COLORS_HEX.get(tier, "#888"),
        })

    bar_blocks = []
    for block in vd["bar_blocks"]:
        bar_blocks.append({
            "tier": block["tier"],
            "pct": block["pct"],
            "color_hex": TIER_COLORS_HEX.get(block["tier"], "#888"),
        })

    return {
        "max_tokens": s["max_tokens"],
        "used_tokens": s["used_tokens"],
        "reserve_tokens": s["reserve_tokens"],
        "free_tokens": vd["free_tokens"],
        "saturation_pct": s["saturation_pct"],
        "saturation_level": vd["saturation_level"],
        "entries": s["entries"],
        "tiers": tiers,
        "bar_blocks": bar_blocks,
        "free_pct": vd["free_pct"],
        "reserve_pct": vd["reserve_pct"],
        "sources": dict(sorted(s.get("sources", {}).items(), key=lambda x: -x[1])[:8]),
    }


def _color_bar(
    blocks: list[dict[str, Any]],
    free_pct: float,
    reserve_pct: float,
    width: int = 40,
) -> str:
    """Build an ANSI-colored bar using ASCII chars."""
    total_pct = sum(b["pct"] for b in blocks)
    total = total_pct + free_pct + reserve_pct
    scale = width / max(total, 1)

    # Distribute widths, ensuring at least 1 char per block with content
    chars = ["" for _ in range(width)]
    used = 0
    allocated: list[tuple[str, int]] = []

    for b in blocks:
        raw = int(b["pct"] * scale)
        if b["pct"] > 0 and raw == 0:
            raw = 1
        color = {
            "critical": "red",
            "important": "yellow",
            "normal": "blue",
            "low": "white",
        }.get(b["tier"], "white")
        allocated.append((color, raw))

    free_raw = max(0, int(free_pct * scale))
    reserve_raw = max(0, int(reserve_pct * scale))

    # Sort so high-priority content shows up first
    allocated.sort(key=lambda x: {"red": 0, "yellow": 1, "blue": 2, "white": 3}.get(x[0], 4))

    result = ""
    remaining = width
    for color, n in allocated:
        n = min(n, remaining)
        if n > 0:
            result += _c("#", color) * n
            remaining -= n

    free_n = min(free_raw, remaining)
    if free_n > 0:
        result += _c(".", "green") * free_n
        remaining -= free_n

    reserve_n = min(reserve_raw, remaining)
    if reserve_n > 0:
        result += _c("~", "bright_black") * reserve_n
        remaining -= reserve_n

    if remaining > 0:
        result += "." * remaining

    return result


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _c(text: str, color: str) -> str:
    try:
        import click
        return click.style(text, fg=color)
    except ImportError:
        return text


def render_session_context(messages: list[dict], max_tokens: int = 128000) -> dict[str, Any]:
    """Analyze a session's message list and return context visualization data."""
    cm = ContextManager(max_tokens=max_tokens)
    for i, m in enumerate(messages):
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if not content:
            continue
        tier = "critical" if role == "system" else "important" if role == "user" else "normal"
        cm.add(content, tier=tier, source=role)
    return render_rich_context(cm)
