#!/usr/bin/env python3
"""Horizon Orchestra CLI backend."""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable
import urllib.error
import urllib.request


C = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "magenta": "\033[35m",
    "blue": "\033[34m",
    "white": "\033[97m",
}

SEPARATOR = "-" * 48
SECRET_CONFIG_MARKERS = ("key", "token", "secret", "password")


AGENTS = {
    "planner": {
        "icon": "P",
        "label": "Planner",
        "color": C["magenta"],
        "system": (
            "You are the Planner agent in Horizon Orchestra. "
            "Decompose the task into brief numbered steps tagged with [Agent]. "
            "Be concise and do not write code."
        ),
    },
    "researcher": {
        "icon": "R",
        "label": "Researcher",
        "color": C["blue"],
        "system": (
            "You are the Researcher agent in Horizon Orchestra. "
            "Provide concise technical findings and recommendations without code."
        ),
    },
    "coder": {
        "icon": "C",
        "label": "Coder",
        "color": C["cyan"],
        "system": (
            "You are the Coder agent in Horizon Orchestra. "
            "Write complete, production-quality code with basic error handling."
        ),
    },
    "tester": {
        "icon": "T",
        "label": "Tester",
        "color": C["yellow"],
        "system": (
            "You are the Tester agent in Horizon Orchestra. "
            "Write runnable tests that cover happy paths and edge cases."
        ),
    },
    "reviewer": {
        "icon": "V",
        "label": "Reviewer",
        "color": C["green"],
        "system": (
            "You are the Reviewer agent in Horizon Orchestra. "
            "Audit for bugs, security issues, missing handling, and finish with PASS or ISSUES FOUND."
        ),
    },
    "writer": {
        "icon": "W",
        "label": "Writer",
        "color": C["white"],
        "system": (
            "You are the Writer agent in Horizon Orchestra. "
            "Produce concise technical documentation in markdown."
        ),
    },
}


def detect_agents(task: str) -> list[str]:
    """Choose an orchestration pipeline for the user's task."""
    task_lower = task.lower()
    pipeline = ["planner"]

    research_triggers = [
        "research",
        "find",
        "best",
        "compare",
        "what is",
        "how does",
        "explain",
        "analyze",
    ]
    code_triggers = [
        "build",
        "create",
        "implement",
        "code",
        "function",
        "class",
        "script",
        "fix",
        "debug",
        "refactor",
        "add",
        "make",
    ]
    test_triggers = ["test", "spec", "pytest", "jest", "coverage", "unit", "integration"]
    write_triggers = ["document", "documentation", "readme", "docs", "explain", "summarize", "write up"]

    if any(token in task_lower for token in research_triggers):
        pipeline.append("researcher")

    if any(token in task_lower for token in code_triggers):
        pipeline.extend(["coder", "tester", "reviewer"])
    elif any(token in task_lower for token in test_triggers):
        pipeline.extend(["tester", "reviewer"])

    if any(token in task_lower for token in write_triggers):
        pipeline.append("writer")

    if pipeline == ["planner"]:
        pipeline.extend(["coder", "reviewer"])

    seen: set[str] = set()
    return [agent for agent in pipeline if not (agent in seen or seen.add(agent))]


def agent_header(agent_key: str, step: int, total: int) -> None:
    """Print a consistent agent banner."""
    ag = AGENTS[agent_key]
    print(f"\n{ag['color']}{SEPARATOR}{C['reset']}")
    print(f"{ag['color']}{ag['icon']} {C['bold']}{ag['label']}{C['reset']}{C['dim']} [{step}/{total}]{C['reset']}")
    print(f"{ag['color']}{SEPARATOR}{C['reset']}")


def is_sensitive_config_key(key: str) -> bool:
    """Return True when a config key likely contains a secret."""
    key_lower = key.lower()
    return any(marker in key_lower for marker in SECRET_CONFIG_MARKERS)


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    """Hide secret values before printing config."""
    redacted: dict[str, Any] = {}
    for key, value in config.items():
        if is_sensitive_config_key(key) and value:
            redacted[key] = "***REDACTED***"
        else:
            redacted[key] = value
    return redacted


class HorizonCLI:
    """Core CLI for config, model management, and provider calls."""

    def __init__(self) -> None:
        self.config_dir = Path.home() / ".horizon"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "config.json"
        self.state_file = self.config_dir / "state.json"
        self.config = self.load_config()
        self.models = self._default_models()
        self.current_model = self.config.get("default_model", "groq-llama4-scout")

    def _default_models(self) -> dict[str, dict[str, Any]]:
        return {
            "groq-llama4-scout": {
                "name": "Llama 4 Scout (Groq)",
                "provider": "groq",
                "context": 131072,
                "api_type": "openai",
                "endpoint": "https://api.groq.com/openai/v1/chat/completions",
                "model_id": "meta-llama/llama-4-scout-17b-16e-instruct",
            },
            "groq-llama4-maverick": {
                "name": "Llama 4 Maverick (Groq)",
                "provider": "groq",
                "context": 131072,
                "api_type": "openai",
                "endpoint": "https://api.groq.com/openai/v1/chat/completions",
                "model_id": "meta-llama/llama-4-maverick-17b-128e-instruct",
            },
            "claude-sonnet": {
                "name": "Claude Sonnet",
                "provider": "anthropic",
                "context": 200000,
                "api_type": "anthropic",
                "endpoint": "https://api.anthropic.com/v1/messages",
                "model_id": "claude-sonnet-4-0",
            },
            "claude-opus": {
                "name": "Claude Opus",
                "provider": "anthropic",
                "context": 200000,
                "api_type": "anthropic",
                "endpoint": "https://api.anthropic.com/v1/messages",
                "model_id": "claude-opus-4-0",
            },
            "gpt-4o": {
                "name": "GPT-4o",
                "provider": "openai",
                "context": 128000,
                "api_type": "openai",
                "endpoint": "https://api.openai.com/v1/chat/completions",
                "model_id": "gpt-4o",
            },
            "gpt-4o-mini": {
                "name": "GPT-4o Mini",
                "provider": "openai",
                "context": 128000,
                "api_type": "openai",
                "endpoint": "https://api.openai.com/v1/chat/completions",
                "model_id": "gpt-4o-mini",
            },
            "ollama-llama3": {
                "name": "Llama 3 (Ollama)",
                "provider": "ollama",
                "context": 32768,
                "api_type": "ollama",
                "endpoint": "http://localhost:11434/api/chat",
                "model_id": "llama3",
            },
            "ollama-mistral": {
                "name": "Mistral (Ollama)",
                "provider": "ollama",
                "context": 32768,
                "api_type": "ollama",
                "endpoint": "http://localhost:11434/api/chat",
                "model_id": "mistral",
            },
        }

    def load_config(self) -> dict[str, Any]:
        if not self.config_file.exists():
            return {}
        try:
            return json.loads(self.config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def save_config(self) -> None:
        self.config_file.write_text(json.dumps(self.config, indent=2), encoding="utf-8")

    def save_state(self, state: dict[str, Any] | None = None) -> None:
        payload = state or {
            "current_model": self.current_model,
            "provider": self.config.get("provider"),
        }
        try:
            self.state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            # State persistence should not break the interactive session.
            return

    def _api_key_name(self, provider: str) -> str | None:
        return {
            "groq": "GROQ_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "ollama": None,
        }.get(provider)

    def _resolve_api_key(self, provider: str) -> str | None:
        key_name = self._api_key_name(provider)
        if not key_name:
            return None
        return self.config.get(key_name) or os.environ.get(key_name)

    def _call_api(
        self,
        model_key: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        model = self.models.get(model_key)
        if not model:
            return {"error": f"Unknown model '{model_key}'."}

        api_type = model.get("api_type")
        if api_type == "openai":
            return self._call_openai_compatible(model, messages, temperature, max_tokens)
        if api_type == "anthropic":
            return self._call_anthropic(model, messages, temperature, max_tokens)
        if api_type == "ollama":
            return self._call_ollama(model, messages, temperature, max_tokens)
        return {"error": f"Unsupported API type '{api_type}'."}

    def _call_openai_compatible(
        self,
        model: dict[str, Any],
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        provider = model.get("provider", "openai")
        api_key = self._resolve_api_key(provider)
        if not api_key:
            key_name = self._api_key_name(provider)
            return {
                "error": f"No {provider.title()} API key.",
                "hint": f"Run: horizon config --set {key_name}=...",
            }

        payload = {
            "model": model["model_id"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            model["endpoint"],
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        return self._request_json(req, extractor=self._extract_openai_response)

    def _call_anthropic(
        self,
        model: dict[str, Any],
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        api_key = self._resolve_api_key("anthropic")
        if not api_key:
            return {
                "error": "No Anthropic API key.",
                "hint": "Run: horizon config --set ANTHROPIC_API_KEY=...",
            }

        system_chunks = [msg["content"] for msg in messages if msg["role"] == "system"]
        non_system = [{"role": msg["role"], "content": msg["content"]} for msg in messages if msg["role"] != "system"]
        payload = {
            "model": model["model_id"],
            "system": "\n\n".join(system_chunks),
            "messages": non_system,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            model["endpoint"],
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        return self._request_json(req, extractor=self._extract_anthropic_response)

    def _call_ollama(
        self,
        model: dict[str, Any],
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        payload = {
            "model": model["model_id"],
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        req = urllib.request.Request(
            model["endpoint"],
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._request_json(req, extractor=self._extract_ollama_response)

    def _request_json(
        self,
        req: urllib.request.Request,
        extractor: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
            return extractor(data)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            return {"error": self._parse_error_message(body)}
        except urllib.error.URLError as exc:
            return {"error": f"Network error: {exc.reason}"}
        except TimeoutError:
            return {"error": "Request timed out."}
        except json.JSONDecodeError:
            return {"error": "Received invalid JSON from provider."}
        except Exception as exc:  # pragma: no cover - last-resort safety net
            return {"error": str(exc)}

    def _parse_error_message(self, body: str) -> str:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return body[:300] or "Unknown provider error."

        if isinstance(payload, dict):
            if isinstance(payload.get("error"), dict):
                return payload["error"].get("message", body[:300] or "Unknown provider error.")
            if isinstance(payload.get("error"), str):
                return payload["error"]
            if isinstance(payload.get("message"), str):
                return payload["message"]
        return body[:300] or "Unknown provider error."

    def _extract_openai_response(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            choice = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return {"error": "No response content returned by provider."}
        return {
            "content": choice,
            "model": data.get("model", ""),
            "usage": data.get("usage", {}),
        }

    def _extract_anthropic_response(self, data: dict[str, Any]) -> dict[str, Any]:
        content = data.get("content", [])
        text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
        if not text_parts:
            return {"error": "No response content returned by provider."}
        return {
            "content": "".join(text_parts),
            "model": data.get("model", ""),
            "usage": data.get("usage", {}),
        }

    def _extract_ollama_response(self, data: dict[str, Any]) -> dict[str, Any]:
        message = data.get("message", {})
        content = message.get("content")
        if not content:
            return {"error": "No response content returned by provider."}
        return {
            "content": content,
            "model": data.get("model", ""),
            "usage": {"eval_count": data.get("eval_count")},
        }

    def show_models(self) -> None:
        for key, model in self.models.items():
            print(f"{key:22} {model['provider']:10} {model['name']}")

    def handle_config_command(self, args: list[str]) -> int:
        if not args:
            print(json.dumps(redact_config(self.config), indent=2))
            return 0
        if args[0] != "--set" or len(args) < 2 or "=" not in args[1]:
            print("Usage: horizon config --set KEY=value")
            return 1
        key, value = args[1].split("=", 1)
        if not key.strip():
            print("Usage: horizon config --set KEY=value")
            return 1
        self.config[key] = value
        if key == "default_model":
            self.current_model = value
        elif key == "provider":
            self.config["provider"] = value
        self.save_config()
        print(f"Saved {key}")
        return 0

    def run(self) -> int:
        cmd = sys.argv[1] if len(sys.argv) > 1 else None
        if cmd == "config":
            return self.handle_config_command(sys.argv[2:])
        if cmd == "models":
            self.show_models()
            return 0
        if cmd == "init":
            run_init()
            return 0
        if cmd == "session":
            run_session(self.load_config())
            return 0
        if cmd in (None, "help", "--help", "-h"):
            if self.config_file.exists():
                run_session(self.load_config())
            else:
                run_init()
            return 0

        print(f"Unknown command: {cmd}")
        print("Available: init, session, models, config")
        return 1


def run_agent(cli: HorizonCLI, agent_key: str, task: str, context: str, model_key: str) -> str:
    """Run a single agent stage."""
    agent = AGENTS[agent_key]
    messages = [{"role": "system", "content": agent["system"]}]
    if context:
        messages.append(
            {
                "role": "user",
                "content": f"Prior work from the pipeline:\n\n{context}\n\nOriginal task: {task}",
            }
        )
    else:
        messages.append({"role": "user", "content": task})

    result = cli._call_api(model_key, messages)
    if "error" in result:
        print(f"{C['red']}x {result['error']}{C['reset']}")
        if "hint" in result:
            print(f"  {result['hint']}")
        return ""

    output = result.get("content", "")
    print(output)
    return output


def run_orchestration(cli: HorizonCLI, task: str, model_key: str) -> None:
    """Run the full multi-agent pipeline."""
    pipeline = detect_agents(task)
    total = len(pipeline)

    print(f"\n{C['dim']}Task: {task}{C['reset']}")
    print(f"{C['dim']}Pipeline: {' -> '.join(agent.capitalize() for agent in pipeline)}{C['reset']}")

    context_log: list[str] = []
    for index, agent_key in enumerate(pipeline, start=1):
        agent_header(agent_key, index, total)
        prior_context = "\n\n---\n\n".join(context_log)
        output = run_agent(cli, agent_key, task, prior_context, model_key)
        if output:
            context_log.append(f"[{AGENTS[agent_key]['label']}]\n{output}")

    print(f"\n{C['green']}{SEPARATOR}{C['reset']}")
    print(f"{C['green']}{C['bold']}Pipeline complete ({total} agents){C['reset']}")
    print(f"{C['green']}{SEPARATOR}{C['reset']}\n")


def run_init() -> None:
    """Interactive setup wizard."""
    cli = HorizonCLI()
    config = dict(cli.config)

    print(f"\n{C['cyan']}{C['bold']}Horizon Orchestra - Setup{C['reset']}")
    print("-" * 42)
    print(f"\n{C['bold']}Step 1 - Compute provider{C['reset']}")
    print(f" 1 Groq Llama 4 - fastest - low cost {C['green']}<- recommended{C['reset']}")
    print(" 2 Anthropic Claude Sonnet / Opus")
    print(" 3 OpenAI GPT-4o")
    print(" 4 Ollama local - free - no API key")

    choice = input(f"\n{C['cyan']}Provider [1]: {C['reset']}").strip() or "1"
    providers = {"1": "groq", "2": "anthropic", "3": "openai", "4": "ollama"}
    provider = providers.get(choice, "groq")
    config["provider"] = provider

    key_name = cli._api_key_name(provider)
    if key_name:
        existing = config.get(key_name) or os.environ.get(key_name, "")
        if existing:
            print(f"\n{C['green']}Found {key_name} in config or env{C['reset']}")
            config[key_name] = existing
        else:
            value = getpass.getpass(f"\n{key_name}: ").strip()
            config[key_name] = value

    model_options = {
        "groq": {"1": "groq-llama4-scout", "2": "groq-llama4-maverick"},
        "anthropic": {"1": "claude-sonnet", "2": "claude-opus"},
        "openai": {"1": "gpt-4o", "2": "gpt-4o-mini"},
        "ollama": {"1": "ollama-llama3", "2": "ollama-mistral"},
    }
    model_labels = {
        "groq": ["Llama 4 Scout - faster, cheaper", "Llama 4 Maverick - more capable"],
        "anthropic": ["Claude Sonnet", "Claude Opus"],
        "openai": ["GPT-4o", "GPT-4o Mini"],
        "ollama": ["Llama 3 (local)", "Mistral (local)"],
    }

    print(f"\n{C['bold']}Step 2 - Default model{C['reset']}")
    for index, label in enumerate(model_labels[provider], start=1):
        print(f" {index} {label}")
    model_choice = input(f"\n{C['cyan']}Model [1]: {C['reset']}").strip() or "1"
    config["default_model"] = model_options[provider].get(model_choice, model_options[provider]["1"])

    cli.config = config
    cli.current_model = config["default_model"]
    cli.save_config()

    print(f"\n{C['green']}Configured: {provider} / {config['default_model']}{C['reset']}")
    print("\nLaunching Horizon Orchestra...\n")
    run_session(config)


def run_session(config: dict[str, Any]) -> None:
    """Interactive orchestration session."""
    cli = HorizonCLI()
    cli.config.update(config)

    model_key = cli.config.get("default_model", "groq-llama4-scout")
    if model_key not in cli.models:
        model_key = "groq-llama4-scout"
    cli.current_model = model_key
    model_name = cli.models[model_key]["name"]

    print(f"{C['cyan']}{'=' * 52}{C['reset']}")
    print(f"{C['cyan']}{C['bold']} HORIZON ORCHESTRA{C['reset']}")
    print(f"{C['dim']} {model_name}{C['reset']}")
    print(f"{C['cyan']}{'=' * 52}{C['reset']}")
    print(f"{C['dim']} Commands: /model <key> /agents /status /clear /exit{C['reset']}")
    print(f"{C['dim']} Type any task - agents will be auto-routed.{C['reset']}\n")

    session_messages: list[dict[str, str]] = []

    while True:
        try:
            user_input = input(f"{C['cyan']}horizon>{C['reset']} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{C['dim']}Session ended.{C['reset']}\n")
            break

        if not user_input:
            continue

        if user_input in ("/exit", "/quit"):
            print(f"{C['dim']}Session ended.{C['reset']}\n")
            break

        if user_input == "/clear":
            session_messages = []
            print(f"{C['dim']}Context cleared.{C['reset']}")
            continue

        if user_input == "/agents":
            print(f"\n{C['bold']}Active agents:{C['reset']}")
            for agent in AGENTS.values():
                print(f" {agent['icon']} {agent['label']}")
            print(f"\n{C['dim']}Model: {model_name} | Provider: {cli.config.get('provider')}{C['reset']}\n")
            continue

        if user_input == "/status":
            print(f"\n Model   : {model_name}")
            print(f" Provider: {cli.config.get('provider')}")
            print(f" Turns   : {len(session_messages)}\n")
            continue

        if user_input.startswith("/model "):
            new_key = user_input.split(" ", 1)[1].strip()
            if new_key in cli.models:
                model_key = new_key
                model_name = cli.models[new_key]["name"]
                cli.current_model = new_key
                cli.save_state()
                print(f"{C['green']}Switched to {model_name}{C['reset']}")
            else:
                print(f"{C['red']}Unknown model. Run 'horizon models' for choices.{C['reset']}")
            continue

        session_messages.append({"role": "user", "content": user_input})
        run_orchestration(cli, user_input, model_key)
        session_messages.append({"role": "assistant", "content": f"[Orchestration complete for: {user_input}]"})
        cli.save_state({"current_model": model_key, "turns": len(session_messages)})


if __name__ == "__main__":
    raise SystemExit(HorizonCLI().run())
