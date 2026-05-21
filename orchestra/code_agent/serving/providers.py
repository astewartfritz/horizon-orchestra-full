from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from typing import Any, AsyncGenerator

import httpx

from orchestra.code_agent.llm.base import Message, LLMError
from orchestra.code_agent.serving.base import BaseProvider, ProviderConfig, ProviderMetadata
from orchestra.code_agent.telemetry.metrics import LLMMetrics
from orchestra.code_agent.telemetry.langfuse import get_tracer as get_lf_tracer
from orchestra.code_agent.telemetry.otel import record_llm_call as _otel_llm


class OpenAIProvider(BaseProvider):
    def __init__(self, model: str = "gpt-4o", config: ProviderConfig | None = None):
        super().__init__(model, config)
        cfg = self.config
        self.base_url = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="openai",
            supported_models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
            supports_streaming=True,
            supports_structured=True,
            supports_tools=True,
            supports_system_prompt=True,
        )

    async def check_health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.config.api_key or ''}"},
                )
                return resp.status_code == 200
        except Exception:
            return False

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        return headers

    def _build_body(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message_to_dict(m) for m in messages],
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        if stream:
            body["stream"] = True
        return body

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
    ) -> Message:
        if stream and not tools:
            return await self._chat_stream_internal(messages)
        return await self._chat_nonstream(messages, tools, tool_choice)

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[str, None]:
        url = f"{self.base_url}/chat/completions"
        body = self._build_body(messages, tools, stream=True)

        _t = httpx.Timeout(self.config.timeout, connect=10, pool=None)
        async with httpx.AsyncClient(timeout=_t) as client:
            async with client.stream("POST", url, json=body, headers=self._build_headers()) as resp:
                if resp.status_code != 200:
                    text = await resp.aread()
                    raise LLMError(f"API error {resp.status_code}: {text.decode()[:500]}")

                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        if not data_str:
                            continue
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content", "")
                        if token:
                            yield token

    async def _chat_stream_internal(self, messages: list[Message]) -> Message:
        content = ""
        async for token in self.chat_stream(messages):
            content += token
            if self._on_token:
                self._on_token(token)
        return Message(role="assistant", content=content)

    async def _chat_nonstream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> Message:
        _start = time.time()
        url = f"{self.base_url}/chat/completions"
        body = self._build_body(messages, tools, tool_choice)

        if self._cost_tracker:
            self._cost_tracker.start_task("chat", self.model)

        LLMMetrics.configure(self.__class__.__name__.replace("Provider", "").lower() or "unknown", self.model)
        t = httpx.Timeout(self.config.timeout, connect=10, pool=None)
        async with httpx.AsyncClient(timeout=t) as client:
            resp = await client.post(url, json=body, headers=self._build_headers())
            if resp.status_code != 200:
                LLMMetrics.record_call(time.time() - _start, status="error")
                _otel_llm(model=self.model, status="error", latency=time.time() - _start)
                get_lf_tracer().generation(
                    name="llm_chat",
                    model=self.model,
                    provider=self.__class__.__name__.replace("Provider", ""),
                    latency=time.time() - _start,
                    status="error",
                )
                raise LLMError(f"API error {resp.status_code}: {resp.text}")

            data = resp.json()
            choice = data["choices"][0]
            msg = choice["message"]
            pt = ct = 0
            if "usage" in data:
                u = data["usage"]
                pt = u.get("prompt_tokens", 0)
                ct = u.get("completion_tokens", 0)
            LLMMetrics.record_call(time.time() - _start, status="ok", prompt_tokens=pt, completion_tokens=ct)
            _otel_llm(model=self.model, prompt_tokens=pt, completion_tokens=ct, latency=time.time() - _start)
            get_lf_tracer().generation(
                name="llm_chat",
                model=self.model,
                provider=self.__class__.__name__.replace("Provider", ""),
                messages=[{"role": m.role, "content": m.content[:200]} for m in messages[-2:]],
                response=msg.get("content", "")[:500] or "",
                prompt_tokens=pt,
                completion_tokens=ct,
                latency=time.time() - _start,
            )

            if self._cost_tracker and "usage" in data:
                self._cost_tracker.record_usage(pt, ct, u.get("cached_tokens", 0) if "usage" in data else 0)
                self._cost_tracker.end_task()

            return Message(
                role="assistant",
                content=msg.get("content") or "",
                tool_calls=msg.get("tool_calls"),
            )

    async def chat_structured(
        self,
        messages: list[Message],
        response_model: type[Any],
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        try:
            from pydantic import BaseModel as PydanticModel
        except ImportError:
            raise LLMError("pydantic required for structured output")

        schema = response_model.model_json_schema()
        tool_def = {
            "type": "function",
            "function": {
                "name": "respond",
                "description": f"Structured response matching {response_model.__name__}",
                "parameters": schema,
            },
        }

        url = f"{self.base_url}/chat/completions"
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message_to_dict(m) for m in messages],
            "tools": [tool_def],
            "tool_choice": {"type": "function", "function": {"name": "respond"}},
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            resp = await client.post(url, json=body, headers=self._build_headers())
            if resp.status_code != 200:
                raise LLMError(f"API error {resp.status_code}: {resp.text}")

            data = resp.json()
            msg = data["choices"][0]["message"]
            tcs = msg.get("tool_calls", [])
            if tcs:
                args_str = tcs[0]["function"]["arguments"]
                args = json.loads(args_str)
                return response_model(**args)

            fallback = msg.get("content", "")
            return response_model.model_validate_json(fallback)


class AnthropicProvider(BaseProvider):
    def __init__(self, model: str = "claude-sonnet-4-20250514", config: ProviderConfig | None = None):
        super().__init__(model, config)
        self.base_url = (config.base_url or "https://api.anthropic.com/v1").rstrip("/")

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="anthropic",
            supported_models=["claude-sonnet-4-20250514", "claude-sonnet-4", "claude-3-opus", "claude-3-haiku"],
            supports_streaming=True,
            supports_structured=False,
            supports_tools=True,
            supports_system_prompt=True,
        )

    async def check_health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.base_url}/models",
                    headers={"x-api-key": self.config.api_key or "", "anthropic-version": "2023-06-01"},
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
    ) -> Message:
        if stream:
            content = ""
            async for token in self.chat_stream(messages, tools):
                content += token
                if self._on_token:
                    self._on_token(token)
            return Message(role="assistant", content=content)
        return await self._chat_nonstream(messages, tools)

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[str, None]:
        url = f"{self.base_url}/messages"
        body, system_content, headers = self._build_request(messages, tools)
        body["stream"] = True

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    text = await resp.aread()
                    raise LLMError(f"Anthropic error {resp.status_code}: {text.decode()[:500]}")

                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if not data_str:
                            continue
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        if data.get("type") == "content_block_delta":
                            delta = data.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield delta.get("text", "")

    def _build_request(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], str | None, dict[str, str]]:
        headers = {
            "x-api-key": self.config.api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)

        system_content = None
        api_messages = []
        for m in messages:
            if m.role == "system":
                system_content = m.content
            elif m.role == "tool":
                api_messages.append({
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content},
                    ],
                })
            elif m.role == "assistant" and m.tool_calls:
                content: list[dict] = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    args = json.loads(tc["function"]["arguments"])
                    content.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": args,
                    })
                api_messages.append({"role": "assistant", "content": content})
            else:
                api_messages.append({"role": m.role, "content": m.content})

        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.config.max_tokens,
            "messages": api_messages,
            "temperature": self.config.temperature,
        }
        if system_content:
            body["system"] = system_content
        if tools:
            body["tools"] = [
                {"name": t["function"]["name"], "description": t["function"]["description"], "input_schema": t["function"]["parameters"]}
                for t in tools
            ]

        return body, system_content, headers

    async def _chat_nonstream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> Message:
        url = f"{self.base_url}/messages"
        body, _, headers = self._build_request(messages, tools)

        if self._cost_tracker:
            self._cost_tracker.start_task("chat", self.model)

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
            if resp.status_code != 200:
                raise LLMError(f"Anthropic error {resp.status_code}: {resp.text}")

            data = resp.json()
            content_blocks = data.get("content", [])

            tool_calls = []
            text_content = ""
            for block in content_blocks:
                if block["type"] == "text":
                    text_content += block["text"]
                elif block["type"] == "tool_use":
                    tool_calls.append({
                        "id": block["id"],
                        "type": "function",
                        "function": {"name": block["name"], "arguments": json.dumps(block["input"])},
                    })

            return Message(
                role="assistant",
                content=text_content,
                tool_calls=tool_calls if tool_calls else None,
            )


class OllamaProvider(OpenAIProvider):
    def __init__(self, model: str = "llama3.1", config: ProviderConfig | None = None):
        cfg = config or ProviderConfig()
        if not cfg.base_url:
            cfg.base_url = "http://localhost:11434/v1"
        super().__init__(model, cfg)
        self._warmed = False

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="ollama",
            supported_models=["llama3.1", "llama3", "mistral", "codellama", "nemo-mistral", "nemotron-mini", "nemotron", "llava", "bakllava"],
            supports_streaming=True,
            supports_structured=False,
            supports_tools=True,
            supports_system_prompt=True,
        )

    async def _warmup(self) -> None:
        if self._warmed:
            return
        try:
            base = self.base_url.replace("/v1", "").replace("/v1/", "")
            body = {"model": self.model, "prompt": "ok", "stream": False, "keep_alive": "5m"}
            async with httpx.AsyncClient(timeout=120) as client:
                await client.post(f"{base}/api/generate", json=body)
            self._warmed = True
        except Exception:
            pass

    async def check_health(self) -> bool:
        try:
            base = self.base_url.replace("/v1", "").replace("/v1/", "")
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{base}/api/tags")
                healthy = resp.status_code == 200
            if healthy:
                await self._warmup()
            return healthy
        except Exception:
            return False

    def _build_body(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        body = super()._build_body(messages, tools, tool_choice, stream)
        body["keep_alive"] = "-1m"
        return body

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
    ) -> Message:
        await self._warmup()
        return await super().chat(messages, tools, tool_choice, stream)

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[str, None]:
        await self._warmup()
        async for token in super().chat_stream(messages, tools):
            yield token

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        return headers


# ---------------------------------------------------------------------------
# Engine providers — local coding agents (OpenCode, Claude Code, Codex)
# ---------------------------------------------------------------------------


class _EngineBase(BaseProvider):
    """Base for local coding-engine providers that run as CLI subprocesses."""

    CLI_NAME: str = ""
    DEFAULT_MODEL: str = ""

    def __init__(self, model: str, config: ProviderConfig | None = None):
        if not model:
            model = self.DEFAULT_MODEL
        super().__init__(model, config)
        self._cli_path: str | None = None

    async def check_health(self) -> bool:
        cli = self._cli_path or self.CLI_NAME
        return shutil.which(cli) is not None

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
    ) -> Message:
        prompt = self._last_user_message(messages)
        if stream:
            content = ""
            async for token in self._stream_cli(prompt):
                content += token
            return Message(role="assistant", content=content)
        output = await self._run_cli(prompt)
        return Message(role="assistant", content=output)

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[str, None]:
        prompt = self._last_user_message(messages)
        async for token in self._stream_cli(prompt):
            yield token

    def _last_user_message(self, messages: list[Message]) -> str:
        for msg in reversed(messages):
            if msg.role == "user":
                return msg.content
        return messages[-1].content if messages else ""

    async def _run_cli(self, prompt: str) -> str:
        cli = self._cli_path or self.CLI_NAME
        try:
            proc = await asyncio.create_subprocess_exec(
                cli, prompt,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            output = (stdout or b"").decode("utf-8", errors="replace")
            err = (stderr or b"").decode("utf-8", errors="replace")
            if proc.returncode != 0:
                return f"Error (exit {proc.returncode}):\n{err[:5000]}"
            return output
        except FileNotFoundError:
            return f"CLI '{cli}' not found on PATH"
        except Exception as exc:
            return f"Error: {exc}"

    async def _stream_cli(self, prompt: str) -> AsyncGenerator[str, None]:
        cli = self._cli_path or self.CLI_NAME
        try:
            proc = await asyncio.create_subprocess_exec(
                cli, prompt,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                yield line.decode("utf-8", errors="replace")
            await proc.wait()
        except FileNotFoundError:
            yield f"CLI '{cli}' not found on PATH\n"
        except Exception as exc:
            yield f"Error: {exc}\n"


class OpenCodeProvider(_EngineBase):
    CLI_NAME = "opencode"
    DEFAULT_MODEL = "opencode"

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="opencode",
            supported_models=["opencode"],
            supports_streaming=True,
            supports_structured=False,
            supports_tools=True,
            supports_system_prompt=False,
        )


class ClaudeCodeProvider(_EngineBase):
    CLI_NAME = "claude"
    DEFAULT_MODEL = "claude-code"

    def __init__(self, model: str, config: ProviderConfig | None = None):
        super().__init__(model, config)
        # Claude Code uses `claude` (Anthropic's CLI) — the subcommand may
        # be `claude code ...` — check both spellings
        self._cli_path = (
            shutil.which("claude-code") or shutil.which("claude") or None
        )

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="claude_code",
            supported_models=["claude-code", "claude-code-4"],
            supports_streaming=True,
            supports_structured=False,
            supports_tools=True,
            supports_system_prompt=False,
        )

    async def _run_cli(self, prompt: str) -> str:
        cli = self._cli_path or "claude"
        try:
            proc = await asyncio.create_subprocess_exec(
                cli, "code", prompt,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            output = (stdout or b"").decode("utf-8", errors="replace")
            err = (stderr or b"").decode("utf-8", errors="replace")
            if proc.returncode != 0:
                return f"Error (exit {proc.returncode}):\n{err[:5000]}"
            return output
        except FileNotFoundError:
            return f"CLI '{cli}' not found on PATH"
        except Exception as exc:
            return f"Error: {exc}"

    async def _stream_cli(self, prompt: str) -> AsyncGenerator[str, None]:
        cli = self._cli_path or "claude"
        try:
            proc = await asyncio.create_subprocess_exec(
                cli, "code", prompt,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                yield line.decode("utf-8", errors="replace")
            await proc.wait()
        except FileNotFoundError:
            yield f"CLI '{cli}' not found on PATH\n"
        except Exception as exc:
            yield f"Error: {exc}\n"


class CodexProvider(_EngineBase):
    CLI_NAME = "codex"
    DEFAULT_MODEL = "codex-mini-latest"

    def __init__(self, model: str, config: ProviderConfig | None = None):
        super().__init__(model, config)
        self._api_key = config.api_key if config else os.environ.get("OPENAI_API_KEY", "")

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="codex",
            supported_models=["codex-mini-latest", "codex"],
            supports_streaming=True,
            supports_structured=False,
            supports_tools=True,
            supports_system_prompt=False,
        )
