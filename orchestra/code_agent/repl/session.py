from __future__ import annotations

import asyncio
import time
from typing import Any

from orchestra.code_agent import Agent, AgentConfig
from orchestra.code_agent.cache.base import DiskCache
from orchestra.code_agent.cache.patch_llm import CachedLLM
from orchestra.code_agent.llm.base import Message

REPL_HELP = """
Commands:
  /help       Show this help
  /tools      List available tools
  /config     Show current config
  /cache      Toggle caching (on/off)
  /history    Show message history
  /clear      Clear conversation
  /exit       Exit REPL
  /save       Save session
  /load <id>  Load session
  /stats      Show usage statistics
"""


class REPLSession:
    def __init__(self, config: AgentConfig | None = None):
        self.config = config or AgentConfig()
        self.agent = Agent(self.config)
        self.cache_enabled = False
        self.cache = DiskCache() if self.cache_enabled else None
        self.start_time = time.time()
        self.prompt_count = 0
        self.history: list[dict[str, str]] = []

    async def run(self) -> None:
        print("Code Agent REPL — type /help for commands, /exit to quit")
        print(f"Model: {self.config.llm.provider}/{self.config.llm.model}\n")

        while True:
            try:
                user_input = input(">>> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                await self._handle_command(user_input)
                continue

            self.prompt_count += 1
            self.history.append({"role": "user", "content": user_input})

            print("\n[Agent thinking...]", end="", flush=True)
            start = time.time()

            if self.cache_enabled and self.cache:
                self.agent.llm = CachedLLM(self.agent.llm, self.cache)

            try:
                result = await asyncio.wait_for(
                    self.agent.run(user_input), timeout=300
                )
            except asyncio.TimeoutError:
                result = "Timed out."
            except Exception as e:
                result = f"Error: {e}"

            elapsed = time.time() - start
            print(f"\r[{elapsed:.1f}s]")
            print(result)
            self.history.append({"role": "assistant", "content": result})

    async def _handle_command(self, cmd: str) -> None:
        parts = cmd.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        match command:
            case "/help":
                print(REPL_HELP)
            case "/tools":
                print(self.agent.get_tools_summary())
            case "/config":
                cfg = self.config
                print(f"Provider: {cfg.llm.provider}")
                print(f"Model: {cfg.llm.model}")
                print(f"Max iterations: {cfg.max_iterations}")
                print(f"Cache: {'on' if self.cache_enabled else 'off'}")
                print(f"Workspace: {cfg.workspace}")
            case "/cache":
                self.cache_enabled = not self.cache_enabled
                if self.cache_enabled:
                    self.cache = DiskCache()
                print(f"Cache: {'ON' if self.cache_enabled else 'OFF'}")
            case "/history":
                for h in self.history[-20:]:
                    role = h["role"].upper()[:4]
                    content = h["content"][:80].replace("\n", "\\n")
                    print(f"  [{role}] {content}")
            case "/clear":
                self.agent.messages = []
                self.agent.state = __import__("code_agent.agent", fromlist=[""]).AgentState()
                self.history = []
                print("Conversation cleared")
            case "/exit":
                print("Goodbye")
                raise SystemExit(0)
            case "/save":
                from orchestra.code_agent.session import Session, SessionManager
                s = Session.create(cmd[:80], self.config)
                for h in self.history:
                    s.add_message(Message(role=h["role"], content=h["content"]))
                SessionManager().save(s)
                print(f"Session saved: {s.id}")
            case "/load":
                from orchestra.code_agent.session import SessionManager
                mgr = SessionManager()
                s = mgr.load(arg)
                if not s:
                    print(f"Session not found: {arg}")
                    return
                self.history = [{"role": m["role"], "content": m["content"]}
                                for m in s.messages]
                print(f"Loaded session {arg} ({len(self.history)} messages)")
            case "/stats":
                elapsed = time.time() - self.start_time
                print(f"Session duration: {elapsed:.0f}s")
                print(f"Prompt count: {self.prompt_count}")
                print(f"History messages: {len(self.history)}")
                s = self.agent.state
                print(f"Iterations: {s.iterations}")
                print(f"Tool rounds: {s.tool_rounds}")
            case _:
                print(f"Unknown command: {command}. Type /help for commands.")


def run_repl(config: AgentConfig | None = None) -> None:
    session = REPLSession(config)
    asyncio.run(session.run())
