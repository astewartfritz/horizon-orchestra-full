"""Horizon Orchestra — Gemma 4 Native Provider.

Provides direct integration with Google's Gemma 4 model family via:

1. **Gemini API** — hosted inference through Google AI Studio
   (OpenAI-compatible layer for chat + native SDK for multimodal/thinking).
2. **Local vLLM** — self-hosted on GPU (OpenAI-compatible).
3. **Ollama** — local quantised inference (OpenAI-compatible).
4. **HuggingFace Transformers** — direct weight loading.

Key capabilities wired:
- Native function calling (all variants)
- Thinking / reasoning mode (31B, 26B MoE, E4B)
- Vision: images, video frames, OCR, chart understanding (all variants)
- Audio: ASR, speech translation (E2B, E4B only)
- System prompt support (native ``system`` role)
- 256K context (31B, 26B) / 128K context (E2B, E4B)

This module is used by the agent loop and architectures when a Gemma 4
model is selected.  For standard chat completions, the OpenAI-compatible
layer in ``router.py`` is sufficient.  This provider adds:
- ``think()`` — reasoning-mode generation with thinking budget
- ``multimodal()`` — image/audio/video input processing
- ``function_call()`` — structured tool use with Gemma 4's native format
- ``generate_ollama_modelfile()`` — Ollama Modelfile for local deployment
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator

from .router import ModelRouter, ModelConfig

try:
    from google import genai
    from google.genai import types as genai_types
    HAS_GENAI = True
except ImportError:
    genai = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]
    HAS_GENAI = False

try:
    from openai import AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    AsyncOpenAI = None  # type: ignore[assignment]
    HAS_OPENAI = False

__all__ = [
    "Gemma4Provider",
    "Gemma4Config",
    "ThinkingResponse",
    "MultimodalInput",
    "Gemma4FunctionCall",
    "generate_ollama_modelfile",
    "generate_vllm_command",
]

log = logging.getLogger("orchestra.gemma4_provider")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Gemma4Config:
    """Configuration for Gemma 4 provider."""
    model: str = "gemma-4-31b"
    thinking_budget: int = 8192        # max thinking tokens
    max_output_tokens: int = 16384
    temperature: float = 0.6
    enable_thinking: bool = True       # use thinking mode when available
    backend: str = "gemini"            # "gemini", "openai_compat", "transformers"


@dataclass
class ThinkingResponse:
    """Response from thinking-mode generation."""
    thinking: str               # model's internal reasoning
    answer: str                 # final answer after thinking
    model: str = ""
    thinking_tokens: int = 0
    answer_tokens: int = 0
    total_tokens: int = 0


@dataclass
class MultimodalInput:
    """A single multimodal input element."""
    type: str                   # "text", "image_url", "image_bytes", "audio_bytes", "video_frames"
    content: str | bytes = ""   # text string, URL, or raw bytes
    mime_type: str = ""         # e.g. "image/png", "audio/wav"


@dataclass
class Gemma4FunctionCall:
    """A structured function call from Gemma 4."""
    name: str
    arguments: dict[str, Any]
    call_id: str = ""


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class Gemma4Provider:
    """Native Gemma 4 provider with multimodal, thinking, and function calling.

    This wraps both the Gemini API (native SDK) and OpenAI-compatible
    backends (vLLM, Ollama, OpenRouter) to expose Gemma 4-specific
    features uniformly.
    """

    def __init__(
        self,
        router: ModelRouter | None = None,
        config: Gemma4Config | None = None,
    ) -> None:
        self.router = router or ModelRouter()
        self.config = config or Gemma4Config()
        self._genai_client: Any = None

    # -- Gemini SDK client ---------------------------------------------------

    def _get_genai_client(self) -> Any:
        """Lazy-initialise the google-genai client."""
        if self._genai_client is not None:
            return self._genai_client

        if not HAS_GENAI:
            raise RuntimeError(
                "google-genai SDK is required for native Gemma 4 features. "
                "Install with: pip install google-genai"
            )
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable is required.")

        self._genai_client = genai.Client(api_key=api_key)
        return self._genai_client

    # -- thinking mode -------------------------------------------------------

    async def think(
        self,
        prompt: str,
        model: str | None = None,
        system_prompt: str = "",
        thinking_budget: int | None = None,
        max_output_tokens: int | None = None,
    ) -> ThinkingResponse:
        """Generate with thinking mode enabled.

        Gemma 4 31B, 26B MoE, and E4B support configurable thinking
        budgets.  The model reasons step-by-step before producing
        the final answer.

        Args:
            prompt: The user prompt.
            model: Model name (default from config).
            system_prompt: Optional system instructions.
            thinking_budget: Max tokens for thinking (0 to disable).
            max_output_tokens: Max tokens for the answer.

        Returns:
            ThinkingResponse with separated thinking and answer text.
        """
        model = model or self.config.model
        cfg = self.router.get_config(model)
        budget = thinking_budget if thinking_budget is not None else self.config.thinking_budget
        max_out = max_output_tokens or self.config.max_output_tokens

        if cfg.provider == "gemini" and HAS_GENAI:
            return await self._think_gemini(prompt, cfg, system_prompt, budget, max_out)
        else:
            # OpenAI-compatible backend — use extra_body for thinking
            return await self._think_openai_compat(prompt, model, system_prompt, budget, max_out)

    async def _think_gemini(
        self,
        prompt: str,
        cfg: ModelConfig,
        system_prompt: str,
        thinking_budget: int,
        max_output_tokens: int,
    ) -> ThinkingResponse:
        """Thinking via native Gemini SDK."""
        client = self._get_genai_client()

        thinking_config = genai_types.ThinkingConfig(
            thinking_budget=thinking_budget,
        )
        gen_config = genai_types.GenerateContentConfig(
            thinking_config=thinking_config,
            max_output_tokens=max_output_tokens,
            temperature=self.config.temperature,
        )
        if system_prompt:
            gen_config.system_instruction = system_prompt

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=cfg.model_id,
            contents=prompt,
            config=gen_config,
        )

        thinking_text = ""
        answer_text = ""
        for part in response.candidates[0].content.parts:
            if hasattr(part, "thought") and part.thought:
                thinking_text += part.text
            else:
                answer_text += part.text

        usage = getattr(response, "usage_metadata", None)
        return ThinkingResponse(
            thinking=thinking_text,
            answer=answer_text,
            model=cfg.model_id,
            thinking_tokens=getattr(usage, "thoughts_token_count", 0) if usage else 0,
            answer_tokens=getattr(usage, "candidates_token_count", 0) if usage else 0,
            total_tokens=getattr(usage, "total_token_count", 0) if usage else 0,
        )

    async def _think_openai_compat(
        self,
        prompt: str,
        model_name: str,
        system_prompt: str,
        thinking_budget: int,
        max_output_tokens: int,
    ) -> ThinkingResponse:
        """Thinking via OpenAI-compatible API (vLLM, Ollama, OpenRouter)."""
        client, model_id = self.router.get_client(model_name)

        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # vLLM and some providers support thinking via extra params
        response = await client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=max_output_tokens,
            temperature=self.config.temperature,
            extra_body={
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": thinking_budget,
                },
            },
        )

        # Parse thinking from response (format varies by backend)
        content = response.choices[0].message.content or ""

        # Try to extract <think>...</think> blocks (common in local backends)
        thinking_text = ""
        answer_text = content
        if "<think>" in content and "</think>" in content:
            start = content.index("<think>") + len("<think>")
            end = content.index("</think>")
            thinking_text = content[start:end].strip()
            answer_text = content[end + len("</think>"):].strip()

        usage = response.usage
        return ThinkingResponse(
            thinking=thinking_text,
            answer=answer_text,
            model=model_id,
            thinking_tokens=0,
            answer_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            total_tokens=getattr(usage, "total_tokens", 0) if usage else 0,
        )

    # -- multimodal input ----------------------------------------------------

    async def multimodal(
        self,
        inputs: list[MultimodalInput],
        model: str | None = None,
        system_prompt: str = "",
        max_output_tokens: int | None = None,
    ) -> str:
        """Process multimodal inputs (text + images + audio + video).

        Gemma 4 natively handles interleaved text, images (variable
        resolution), video frames, and audio (E2B/E4B).

        Args:
            inputs: List of MultimodalInput elements in any order.
            model: Model name (default from config).
            system_prompt: Optional system instructions.
            max_output_tokens: Max response tokens.

        Returns:
            Generated text response.
        """
        model = model or self.config.model
        cfg = self.router.get_config(model)
        max_out = max_output_tokens or self.config.max_output_tokens

        if cfg.provider == "gemini" and HAS_GENAI:
            return await self._multimodal_gemini(inputs, cfg, system_prompt, max_out)
        else:
            return await self._multimodal_openai_compat(inputs, model, system_prompt, max_out)

    async def _multimodal_gemini(
        self,
        inputs: list[MultimodalInput],
        cfg: ModelConfig,
        system_prompt: str,
        max_output_tokens: int,
    ) -> str:
        """Multimodal via native Gemini SDK."""
        client = self._get_genai_client()

        parts: list[Any] = []
        for inp in inputs:
            if inp.type == "text":
                parts.append(inp.content)
            elif inp.type == "image_url":
                parts.append(genai_types.Part.from_uri(
                    file_uri=str(inp.content),
                    mime_type=inp.mime_type or "image/jpeg",
                ))
            elif inp.type == "image_bytes":
                parts.append(genai_types.Part.from_bytes(
                    data=inp.content if isinstance(inp.content, bytes) else base64.b64decode(inp.content),
                    mime_type=inp.mime_type or "image/png",
                ))
            elif inp.type == "audio_bytes":
                if not cfg.supports_audio:
                    log.warning("Model %s does not support audio; skipping audio input", cfg.model_id)
                    continue
                parts.append(genai_types.Part.from_bytes(
                    data=inp.content if isinstance(inp.content, bytes) else base64.b64decode(inp.content),
                    mime_type=inp.mime_type or "audio/wav",
                ))
            elif inp.type == "video_frames":
                # Video as sequential image frames
                parts.append(genai_types.Part.from_bytes(
                    data=inp.content if isinstance(inp.content, bytes) else base64.b64decode(inp.content),
                    mime_type=inp.mime_type or "video/mp4",
                ))

        gen_config = genai_types.GenerateContentConfig(
            max_output_tokens=max_output_tokens,
            temperature=self.config.temperature,
        )
        if system_prompt:
            gen_config.system_instruction = system_prompt

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=cfg.model_id,
            contents=parts,
            config=gen_config,
        )

        return response.text or ""

    async def _multimodal_openai_compat(
        self,
        inputs: list[MultimodalInput],
        model_name: str,
        system_prompt: str,
        max_output_tokens: int,
    ) -> str:
        """Multimodal via OpenAI-compatible API (vision support)."""
        client, model_id = self.router.get_client(model_name)

        # Build OpenAI-format content array
        content_parts: list[dict[str, Any]] = []
        for inp in inputs:
            if inp.type == "text":
                content_parts.append({"type": "text", "text": str(inp.content)})
            elif inp.type == "image_url":
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": str(inp.content)},
                })
            elif inp.type == "image_bytes":
                b64 = inp.content if isinstance(inp.content, str) else base64.b64encode(inp.content).decode()
                mime = inp.mime_type or "image/png"
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                })
            # Audio/video not supported via OpenAI-compat; skip with warning
            elif inp.type in ("audio_bytes", "video_frames"):
                log.warning(
                    "Audio/video input requires Gemini SDK; skipping for OpenAI-compat backend"
                )

        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": content_parts})

        response = await client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=max_output_tokens,
            temperature=self.config.temperature,
        )

        return response.choices[0].message.content or ""

    # -- function calling ----------------------------------------------------

    async def function_call(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        model: str | None = None,
        system_prompt: str = "",
        max_output_tokens: int | None = None,
    ) -> tuple[str, list[Gemma4FunctionCall]]:
        """Generate with function-calling tools.

        Gemma 4 has native function-calling support.  Tools are defined
        in OpenAI format and the model returns structured tool calls.

        Args:
            prompt: User prompt.
            tools: OpenAI-format tool definitions.
            model: Model name.
            system_prompt: System instructions.
            max_output_tokens: Max response tokens.

        Returns:
            Tuple of (text_content, list_of_function_calls).
        """
        model = model or self.config.model
        max_out = max_output_tokens or self.config.max_output_tokens

        client, model_id = self.router.get_client(model)

        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await client.chat.completions.create(
            model=model_id,
            messages=messages,
            tools=tools if tools else None,
            tool_choice="auto" if tools else None,
            max_tokens=max_out,
            temperature=self.config.temperature,
        )

        choice = response.choices[0]
        text = choice.message.content or ""
        calls: list[Gemma4FunctionCall] = []

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                calls.append(Gemma4FunctionCall(
                    name=tc.function.name,
                    arguments=args,
                    call_id=tc.id,
                ))

        return text, calls

    # -- model info ----------------------------------------------------------

    def get_model_card(self, model: str | None = None) -> dict[str, Any]:
        """Return capability card for a Gemma 4 model."""
        model = model or self.config.model
        cfg = self.router.get_config(model)

        return {
            "name": model,
            "model_id": cfg.model_id,
            "provider": cfg.provider,
            "family": "gemma-4",
            "architecture": cfg.architecture,
            "parameters_b": cfg.parameters_b,
            "max_context": cfg.max_context,
            "capabilities": {
                "reasoning": "reasoning" in cfg.strengths,
                "coding": "coding" in cfg.strengths,
                "agentic": "agentic" in cfg.strengths,
                "vision": cfg.supports_vision,
                "audio": cfg.supports_audio,
                "thinking": cfg.supports_thinking,
                "tool_use": cfg.supports_tools,
                "long_context": "long_context" in cfg.strengths,
                "on_device": "on_device" in cfg.strengths,
                "multilingual": True,   # 140+ languages
            },
            "license": "Apache-2.0",
            "quantization": _QUANT_TABLE.get(model, {}),
            "cost": {
                "input_per_1m": cfg.cost_input,
                "output_per_1m": cfg.cost_output,
            },
        }


# ---------------------------------------------------------------------------
# Quantisation reference table (memory requirements)
# ---------------------------------------------------------------------------

_QUANT_TABLE: dict[str, dict[str, str]] = {
    "gemma-4-31b": {"bf16": "58.3 GB", "sfp8": "30.4 GB", "q4_0": "17.4 GB"},
    "gemma-4-26b-moe": {"bf16": "48 GB", "sfp8": "25 GB", "q4_0": "15.6 GB"},
    "gemma-4-e4b": {"bf16": "15 GB", "sfp8": "7.5 GB", "q4_0": "5 GB"},
    "gemma-4-e2b": {"bf16": "9.6 GB", "sfp8": "4.6 GB", "q4_0": "3.2 GB"},
}


# ---------------------------------------------------------------------------
# Deployment helpers
# ---------------------------------------------------------------------------

def generate_ollama_modelfile(
    variant: str = "31b",
    quantisation: str = "Q4_K_M",
    context_length: int = 256_000,
) -> str:
    """Generate an Ollama Modelfile for local Gemma 4 deployment.

    Args:
        variant: "31b", "26b-a4b", "e4b", or "e2b".
        quantisation: Quantisation level (e.g. "Q4_K_M", "Q8_0").
        context_length: Context window size.

    Returns:
        Modelfile content as a string.
    """
    model_map = {
        "31b": "google/gemma-4-31B-it",
        "26b-a4b": "google/gemma-4-26B-A4B-it",
        "e4b": "google/gemma-4-E4B-it",
        "e2b": "google/gemma-4-E2B-it",
    }
    hf_id = model_map.get(variant, model_map["31b"])

    return f"""\
# Gemma 4 {variant.upper()} — Horizon Orchestra Modelfile
# Deploy: ollama create gemma4-orchestra -f Modelfile

FROM {hf_id}

PARAMETER num_ctx {context_length}
PARAMETER temperature 0.6
PARAMETER top_p 0.95
PARAMETER top_k 40
PARAMETER repeat_penalty 1.05

SYSTEM \"\"\"
You are Horizon Orchestra, an autonomous AI agent powered by Gemma 4.
You have access to tools for web search, code execution, file I/O,
browser automation, and persistent memory.  Use them iteratively
to complete the user's task.
When using tools, respond with valid JSON function calls.
When finished, respond with your complete final answer.
\"\"\"

TEMPLATE \"\"\"{{{{ if .System }}}}<start_of_turn>system
{{{{ .System }}}}<end_of_turn>
{{{{ end }}}}{{{{ if .Prompt }}}}<start_of_turn>user
{{{{ .Prompt }}}}<end_of_turn>
<start_of_turn>model
{{{{ end }}}}{{{{ .Response }}}}<end_of_turn>\"\"\"
"""


def generate_vllm_command(
    variant: str = "31b",
    tensor_parallel: int = 1,
    max_model_len: int = 256_000,
    port: int = 8000,
    quantisation: str | None = None,
) -> str:
    """Generate a vLLM serve command for Gemma 4.

    Args:
        variant: "31b", "26b-a4b", "e4b", or "e2b".
        tensor_parallel: Number of GPUs for tensor parallelism.
        max_model_len: Maximum sequence length.
        port: Port to serve on.
        quantisation: Optional quantisation (e.g. "awq", "gptq").

    Returns:
        Shell command string.
    """
    model_map = {
        "31b": "google/gemma-4-31B-it",
        "26b-a4b": "google/gemma-4-26B-A4B-it",
        "e4b": "google/gemma-4-E4B-it",
        "e2b": "google/gemma-4-E2B-it",
    }
    hf_id = model_map.get(variant, model_map["31b"])

    cmd_parts = [
        "vllm serve",
        hf_id,
        f"--tensor-parallel-size {tensor_parallel}",
        f"--max-model-len {max_model_len}",
        f"--port {port}",
        "--trust-remote-code",
        "--enable-auto-tool-choice",
        "--tool-call-parser hermes",
        "--dtype bfloat16",
    ]

    if quantisation:
        cmd_parts.append(f"--quantization {quantisation}")

    # GPU recommendations
    gpu_note = {
        "31b": "# Requires: 1x H100 80GB (bf16) or 1x RTX 4090 24GB (Q4)",
        "26b-a4b": "# Requires: 1x A100 40GB (bf16) or 1x RTX 4090 24GB (Q4)",
        "e4b": "# Requires: 1x RTX 3080 10GB+ (bf16) or CPU-only (Q4)",
        "e2b": "# Requires: 1x RTX 3060 8GB+ (bf16) or CPU-only (Q4)",
    }

    return f"{gpu_note.get(variant, '')}\n{' \\\\\n    '.join(cmd_parts)}"


def generate_docker_service(
    variant: str = "31b",
    gpu_count: int = 1,
) -> dict[str, Any]:
    """Generate a Docker Compose service block for Gemma 4 via vLLM.

    Returns a dict suitable for insertion into docker-compose.yml.
    """
    model_map = {
        "31b": "google/gemma-4-31B-it",
        "26b-a4b": "google/gemma-4-26B-A4B-it",
        "e4b": "google/gemma-4-E4B-it",
        "e2b": "google/gemma-4-E2B-it",
    }
    hf_id = model_map.get(variant, model_map["31b"])
    ctx = 256_000 if variant in ("31b", "26b-a4b") else 128_000

    return {
        "image": "vllm/vllm-openai:nightly",
        "deploy": {
            "resources": {
                "reservations": {
                    "devices": [{
                        "driver": "nvidia",
                        "count": gpu_count,
                        "capabilities": ["gpu"],
                    }],
                },
            },
        },
        "command": (
            f"--model {hf_id} "
            f"--tensor-parallel-size {gpu_count} "
            f"--max-model-len {ctx} "
            "--trust-remote-code "
            "--enable-auto-tool-choice "
            "--tool-call-parser hermes "
            "--dtype bfloat16 "
            "--host 0.0.0.0 --port 8000"
        ),
        "ports": ["8000:8000"],
        "restart": "unless-stopped",
        "healthcheck": {
            "test": ["CMD", "curl", "-f", "http://localhost:8000/health"],
            "interval": "30s",
            "timeout": "10s",
            "retries": 3,
        },
    }
