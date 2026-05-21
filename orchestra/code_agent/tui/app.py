from __future__ import annotations

import asyncio
import time
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal, Container
from textual.screen import Screen
from textual.widgets import (
    Button, Header, Footer, Input, Label, ListItem, ListView,
    Markdown, RichLog, Select, Static,
)
from textual.reactive import reactive

from orchestra.code_agent import Agent, AgentConfig
from orchestra.code_agent.cache.base import DiskCache
from orchestra.code_agent.cache.patch_llm import CachedLLM
from orchestra.code_agent.config import LLMConfig
from orchestra.code_agent.cost.tracker import CostTracker
from orchestra.code_agent.session import Session, SessionManager
from orchestra.code_agent.tools import CORE_TOOLS


TIER_BAR = {
    "critical": "red",
    "important": "yellow",
    "normal": "blue",
    "low": "white",
}


class ChatMessage(Static):
    def __init__(self, role: str, content: str, **kwargs):
        super().__init__(**kwargs)
        self.role = role
        self.content = content
        label = {"user": "You", "assistant": "Agent", "tool": "Tool", "system": "System"}.get(role, role)
        self.update(f"[bold]{label}:[/]\n{content}")


class SessionItem(ListItem):
    def __init__(self, session_data: dict, **kwargs):
        super().__init__(**kwargs)
        self.session_data = session_data
        task = session_data.get("task", "")[:50]
        sid = session_data.get("id", "")[:8]
        status = "done" if session_data.get("finished") else "..."
        if session_data.get("finished"):
            self._display_label = f"[bold #238636]{sid}[/] {task}\n[#8b949e]done[/]"
        else:
            self._display_label = f"[bold #58a6ff]{sid}[/] {task}\n[#e0af68]running...[/]"

    def compose(self) -> ComposeResult:
        yield Label(self._display_label)


class ContextPanel(Static):
    """Live context window visualization panel."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tokens_used = 0
        self._tokens_max = 128000
        self._entries = 0
        self._tiers: dict[str, int] = {}
        self._tier_tokens: dict[str, int] = {}

    def update_from_agent(self, agent: Agent | None) -> None:
        if agent and hasattr(agent, "context_manager") and agent.context_manager:
            vd = agent.context_manager.visual_data()
            s = vd["stats"]
            self._tokens_used = s["used_tokens"]
            self._tokens_max = s["max_tokens"]
            self._entries = s["entries"]
            self._tiers = s["tiers"]
            self._tier_tokens = s["tier_tokens"]
        self.refresh()

    def on_mount(self) -> None:
        self.refresh()

    def _make_bar(self, blocks: list[dict], free_pct: float, width: int = 30) -> str:
        result = ""
        filled = 0
        for b in blocks:
            n = max(1, int(b["pct"] / 100 * width)) if b["pct"] > 0 else 0
            n = min(n, width - filled)
            if n > 0:
                color = TIER_BAR.get(b["tier"], "white")
                result += f"[{color} on {color}]{' ' * n}[/]"
                filled += n
        free_n = width - filled
        if free_n > 0:
            result += f"[#30363d on #30363d]{' ' * free_n}[/]"
        return result

    def _fmt(self, n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)

    def render(self) -> str:
        pct = (self._tokens_used / (self._tokens_max - 4000) * 100) if self._tokens_max > 4000 else 0
        pct = min(pct, 100)

        blocks = []
        effective = self._tokens_max - 4000
        for tier in ["critical", "important", "normal", "low"]:
            t_tokens = self._tier_tokens.get(tier, 0)
            if t_tokens > 0:
                blocks.append({"tier": tier, "pct": t_tokens / effective * 100})

        bar = self._make_bar(blocks, 100 - pct)

        out = []
        out.append("[bold #58a6ff] Context Window [/]")
        out.append("")
        out.append(f"  {bar}")
        out.append(f"  [bold]{self._fmt(self._tokens_used)}[/] [#8b949e]/ {self._fmt(self._tokens_max)} tokens ({pct:.0f}%)[/]")
        out.append(f"  [#8b949e]{self._entries} entries[/]")
        out.append("")

        out.append(f"  [bold #8b949e]Tier Breakdown[/]")
        for tier in ["critical", "important", "normal", "low"]:
            count = self._tiers.get(tier, 0)
            tokens = self._tier_tokens.get(tier, 0)
            if count == 0:
                continue
            color = TIER_BAR.get(tier, "white")
            share = (tokens / self._tokens_used * 100) if self._tokens_used > 0 else 0
            out.append(f"  [{color}]■[/] {tier:>12}  {count} entries  {self._fmt(tokens)} ({share:.0f}%)")

        if self._tokens_used == 0:
            out.append("  [#8b949e](empty — run a task to populate)[/]")

        return "\n".join(out)


class CodeAgentTUI(App):
    TITLE = "Code Agent"
    SUB_TITLE = "Autonomous AI Software Engineering"
    CSS = """
Screen {
    background: #0d1117;
}

#sidebar {
    width: 28;
    background: #161b22;
    border-right: solid #30363d;
    padding: 1;
}

#sidebar Label {
    color: #8b949e;
    margin-bottom: 1;
}

#context-panel-container {
    width: 36;
    background: #161b22;
    border-left: solid #30363d;
    padding: 1;
    overflow-y: auto;
}

#main {
    height: 100%;
}

#header {
    background: #161b22;
    border-bottom: solid #30363d;
    padding: 1 2;
    height: 3;
}

#header Label {
    color: #58a6ff;
    text-style: bold;
    width: 1fr;
}

#config-bar {
    background: #161b22;
    border-bottom: solid #30363d;
    padding: 0 2;
    height: 3;
    align: center middle;
}

#config-bar > * {
    margin: 0 1;
}

#chat-area {
    height: 1fr;
    overflow-y: auto;
    padding: 1 2;
}

#chat-area > * {
    margin-bottom: 1;
}

#input-container {
    border-top: solid #30363d;
    padding: 1 2;
    height: 5;
    background: #161b22;
}

#message-input {
    width: 1fr;
}

#send-btn {
    width: 10;
    background: #238636;
    color: white;
}

#spinner {
    height: 1;
    color: #8b949e;
}

#tool-output {
    background: #0d1117;
    border: solid #30363d;
    height: 10;
    margin: 1;
}

.session-item {
    padding: 0 1;
}

.session-item:hover {
    background: #1c2128;
}

ListView {
    background: #161b22;
}

Button {
    background: #21262d;
    color: #c9d1d9;
}

Button:hover {
    background: #30363d;
}

Select {
    background: #0d1117;
    color: #c9d1d9;
    border: solid #30363d;
}

Select:focus {
    border: solid #58a6ff;
}

Input {
    background: #0d1117;
    color: #c9d1d9;
    border: solid #30363d;
}

Input:focus {
    border: solid #58a6ff;
}

RichLog {
    background: #0d1117;
}

Markdown {
    background: #161b22;
    padding: 1;
    margin: 0 1;
}

Tooltip {
    background: #1c2128;
    color: #c9d1d9;
}

#context-panel Static {
    padding: 0 1;
}

#ctx-toggle {
    width: 100%;
    background: #21262d;
    color: #8b949e;
}

#ctx-toggle:hover {
    background: #30363d;
}
"""

    BINDINGS = [
        Binding("ctrl+n", "new_session", "New Session"),
        Binding("ctrl+l", "clear_chat", "Clear Chat"),
        Binding("ctrl+s", "save_session", "Save Session"),
        Binding("ctrl+c", "toggle_context", "Context Panel"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.agent = Agent(AgentConfig(memory_type="none"))
        self.session_mgr = SessionManager()
        self.cost_tracker = CostTracker()
        self.cache_enabled = False
        self.current_session: Session | None = None
        self._running = False
        self._context_visible = True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Container(id="sidebar"):
                yield Label("Sessions")
                yield ListView(id="session-list")
                yield Button("+ New", id="new-btn", variant="default")
                yield Label(f"\nTools: {len(CORE_TOOLS)}")
                yield Label(f"Cache: off")
            with Vertical(id="main"):
                yield RichLog(id="chat-area", highlight=True, markup=True)
                yield Static(id="spinner")
                with Horizontal(id="config-bar"):
                    yield Select(
                        [(p, p) for p in ["openai", "anthropic", "ollama"]],
                        prompt="Provider",
                        id="provider-select",
                        value="openai",
                    )
                    yield Input(value="gpt-4o", placeholder="Model", id="model-input", classes="config-input")
                    yield Input(placeholder="API Key", password=True, id="key-input", classes="config-input")
                    yield Button("Cache", id="cache-toggle", variant="default")
                    yield Button("Context", id="ctx-toggle", variant="default")
                with Horizontal(id="input-container"):
                    yield Input(placeholder="Describe the task...", id="message-input")
                    yield Button("Send", id="send-btn", variant="primary")
            with Container(id="context-panel-container"):
                yield ContextPanel(id="context-panel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#message-input", Input).focus()
        self._refresh_sessions()
        self._update_context()

    def _refresh_sessions(self) -> None:
        list_view = self.query_one("#session-list", ListView)
        list_view.clear()
        sessions = self.session_mgr.list_sessions()
        for s in sessions:
            item = SessionItem(s)
            list_view.append(item)

    def _update_context(self) -> None:
        panel = self.query_one("#context-panel", ContextPanel)
        panel.update_from_agent(self.agent)

    async def action_new_session(self) -> None:
        self.current_session = None
        self.agent = Agent(AgentConfig(memory_type="none"))
        chat = self.query_one("#chat-area", RichLog)
        chat.clear()
        chat.write("[dim]New session started[/]")
        self._refresh_sessions()
        self._update_context()

    async def action_clear_chat(self) -> None:
        chat = self.query_one("#chat-area", RichLog)
        chat.clear()
        self.agent.messages = []
        self._update_context()

    async def action_save_session(self) -> None:
        if self.current_session:
            self.session_mgr.save(self.current_session)
            self.notify(f"Session saved: {self.current_session.id[:8]}", timeout=3)
            self._refresh_sessions()

    async def action_toggle_context(self) -> None:
        self._context_visible = not self._context_visible
        container = self.query_one("#context-panel-container")
        if self._context_visible:
            container.styles.width = 36
        else:
            container.styles.width = 0
        self.notify(f"Context panel {'shown' if self._context_visible else 'hidden'}", timeout=1)

    @on(Button.Pressed, "#send-btn")
    async def on_send(self) -> None:
        input_w = self.query_one("#message-input", Input)
        task = input_w.value.strip()
        if not task or self._running:
            return

        input_w.value = ""
        self._running = True

        provider = self.query_one("#provider-select", Select).value or "openai"
        model = self.query_one("#model-input", Input).value or "gpt-4o"
        api_key = self.query_one("#key-input", Input).value or None

        cfg = AgentConfig(
            llm=LLMConfig(provider=str(provider), model=model, api_key=api_key),
            memory_type="none",
        )
        self.agent = Agent(cfg)

        if self.cache_enabled and api_key:
            self.agent.llm = CachedLLM(self.agent.llm, DiskCache())

        chat = self.query_one("#chat-area", RichLog)
        spinner = self.query_one("#spinner", Static)
        chat.write(f"\n[bold #58a6ff]You:[/] {task}")
        spinner.update("[italic #8b949e]Agent is thinking...[/]")

        if not self.current_session:
            self.current_session = Session.create(task, cfg)
        self.current_session.add_message(
            __import__("code_agent.llm.base", fromlist=[""]).Message(role="user", content=task)
        )

        # Add to context manager
        self.agent.context_manager.add(task, tier="important", source="user")

        tokens = []
        start = time.time()

        def on_token(tok: str) -> None:
            tokens.append(tok)

        self.agent.llm.on_token(on_token)

        try:
            result = await asyncio.wait_for(self.agent.run(task, stream=False), timeout=300)
        except asyncio.TimeoutError:
            result = "Timed out after 300s."
        except Exception as e:
            result = f"Error: {e}"

        elapsed = time.time() - start
        spinner.update("")

        chat.write(f"\n[bold #238636]Agent:[/] {result}")
        chat.write(f"[dim #8b949e]({elapsed:.1f}s, {self.agent.state.iterations} iters)[/]")

        self.current_session.add_message(
            __import__("code_agent.llm.base", fromlist=[""]).Message(role="assistant", content=result)
        )
        self.current_session.finished = True
        self.current_session.result = result
        self.session_mgr.save(self.current_session)
        self._refresh_sessions()
        self._running = False

        self.cost_tracker.start_task(task, model)
        self.cost_tracker.record_usage(
            sum(len(t) for t in tokens) // 4,
            len("".join(tokens)) // 4,
        )
        self.cost_tracker.end_task()

        self._update_context()

    @on(Button.Pressed, "#new-btn")
    def on_new_click(self) -> None:
        self.run_action("new_session")

    @on(Button.Pressed, "#cache-toggle")
    def on_toggle_cache(self) -> None:
        self.cache_enabled = not self.cache_enabled
        btn = self.query_one("#cache-toggle", Button)
        btn.label = "Cache ON" if self.cache_enabled else "Cache OFF"
        self.notify(f"Cache {'enabled' if self.cache_enabled else 'disabled'}", timeout=2)

    @on(Button.Pressed, "#ctx-toggle")
    def on_ctx_toggle(self) -> None:
        self.run_action("toggle_context")

    @on(ListView.Selected, "#session-list")
    async def on_session_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, SessionItem):
            sid = item.session_data.get("id", "")
            session = self.session_mgr.load(sid)
            if session:
                self.current_session = session
                chat = self.query_one("#chat-area", RichLog)
                chat.clear()
                for m in session.messages:
                    role = m.get("role", "")
                    content = m.get("content", "")
                    if content:
                        label = {"user": "You", "assistant": "Agent"}.get(role, role)
                        chat.write(f"[bold]{label}:[/] {content[:2000]}")
                # Update context panel from session messages
                from orchestra.code_agent.context.manager import ContextManager
                cm = ContextManager()
                for m in session.messages:
                    role = m.get("role", "unknown")
                    c = m.get("content", "")
                    if c:
                        t = "critical" if role == "system" else "important" if role == "user" else "normal"
                        cm.add(c, tier=t, source=role)
                self.agent.context_manager = cm
                self._update_context()

    @on(Input.Submitted, "#message-input")
    async def on_input_submit(self) -> None:
        await self.on_send()


def run_tui():
    app = CodeAgentTUI()
    app.run()
