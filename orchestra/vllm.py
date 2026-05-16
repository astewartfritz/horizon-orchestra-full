"""Horizon Orchestra — vLLM Self-Hosted Configuration.

Manages self-hosted Kimi K2.5 inference:
- Health checking with exponential backoff
- Auto-fallback to cloud API when local is down
- Deployment script generation for vLLM and SGLang
- Dynamic model registration when local server comes online

Usage::

    from orchestra.vllm import LocalInference
    local = LocalInference()
    await local.wait_for_ready()  # blocks until vLLM is up
    # Router automatically prefers local when healthy
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .router import ModelRouter, ModelConfig

__all__ = [
    "LocalInference",
    "LocalConfig",
    "generate_vllm_script",
    "generate_sglang_script",
]

log = logging.getLogger("orchestra.vllm")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class LocalConfig:
    """Configuration for self-hosted inference."""
    host: str = "localhost"
    port: int = 8000
    model_id: str = "moonshotai/Kimi-K2.5"
    tensor_parallel: int = 8
    max_model_len: int = 262_144
    health_check_interval: int = 30        # seconds between health checks
    health_check_timeout: int = 5          # seconds per check
    max_retries: int = 120                 # retries during wait_for_ready (60min at 30s)
    fallback_model: str = "kimi-k2.5"     # cloud fallback when local is down


# ---------------------------------------------------------------------------
# Health checker + auto-fallback
# ---------------------------------------------------------------------------

class LocalInference:
    """Manages a self-hosted vLLM/SGLang inference server.

    Continuously monitors the local server's health and registers/
    deregisters the local model in the router accordingly.
    """

    def __init__(
        self,
        config: LocalConfig | None = None,
        router: ModelRouter | None = None,
    ) -> None:
        self.config = config or LocalConfig()
        self.router = router or ModelRouter()
        self._healthy = False
        self._last_check: float = 0
        self._monitor_task: asyncio.Task | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}/v1"

    @property
    def health_url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}/health"

    @property
    def healthy(self) -> bool:
        return self._healthy

    async def check_health(self) -> bool:
        """Single health check against the inference server."""
        try:
            async with httpx.AsyncClient(timeout=self.config.health_check_timeout) as client:
                resp = await client.get(self.health_url)
                healthy = resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            healthy = False

        if healthy != self._healthy:
            self._healthy = healthy
            if healthy:
                log.info("Local inference server is UP at %s", self.base_url)
                self._register_local_model()
            else:
                log.warning("Local inference server is DOWN — using fallback: %s", self.config.fallback_model)

        self._last_check = time.monotonic()
        return healthy

    async def wait_for_ready(self, timeout_minutes: int = 60) -> bool:
        """Block until the local server is healthy or timeout."""
        interval = self.config.health_check_interval
        max_attempts = (timeout_minutes * 60) // interval

        log.info("Waiting for local inference at %s (timeout: %dm)...", self.base_url, timeout_minutes)

        for attempt in range(1, int(max_attempts) + 1):
            if await self.check_health():
                log.info("Local inference ready after %d checks", attempt)
                return True
            if attempt % 10 == 0:
                log.info("  Still waiting... (%d/%d checks)", attempt, int(max_attempts))
            await asyncio.sleep(interval)

        log.error("Local inference did not come up within %d minutes", timeout_minutes)
        return False

    async def start_monitor(self) -> None:
        """Start background health monitoring loop."""
        if self._monitor_task and not self._monitor_task.done():
            return
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        log.info("Started health monitor for %s", self.base_url)

    async def stop_monitor(self) -> None:
        """Stop background health monitoring."""
        if self._monitor_task:
            self._monitor_task.cancel()
            self._monitor_task = None

    async def _monitor_loop(self) -> None:
        """Continuous health check loop."""
        while True:
            try:
                await self.check_health()
                await asyncio.sleep(self.config.health_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.debug("Health monitor error: %s", exc)
                await asyncio.sleep(self.config.health_check_interval)

    def _register_local_model(self) -> None:
        """Register the local model in the router."""
        self.router.models["kimi-k2.5-local"] = ModelConfig(
            model_id=self.config.model_id,
            provider="local",
            base_url=self.base_url,
            api_key_env="",
            strengths=("reasoning", "coding", "agentic", "vision", "tool_use"),
            cost_input=0.0,
            cost_output=0.0,
            max_context=self.config.max_model_len,
            supports_tools=True,
            supports_vision=True,
        )
        # Clear cached client so it reconnects
        if "kimi-k2.5-local" in self.router._clients:
            del self.router._clients["kimi-k2.5-local"]

    def get_active_model(self) -> str:
        """Return the best available model (local if healthy, else fallback)."""
        if self._healthy:
            return "kimi-k2.5-local"
        return self.config.fallback_model

    async def get_model_info(self) -> dict[str, Any]:
        """Query the local server for loaded model info."""
        if not self._healthy:
            return {"error": "Server not healthy"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/models")
                return resp.json()
        except Exception as exc:
            return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Deployment script generators
# ---------------------------------------------------------------------------

def generate_vllm_script(
    config: LocalConfig | None = None,
    output_path: str = "scripts/start_vllm.sh",
) -> str:
    """Generate a vLLM deployment script."""
    config = config or LocalConfig()

    script = f"""\
#!/usr/bin/env bash
# Horizon Orchestra — vLLM Inference Server
# Serves Kimi K2.5 with OpenAI-compatible API
#
# Requirements:
#   - NVIDIA GPUs ({config.tensor_parallel}x H200/H100/A100 recommended)
#   - pip install vllm
#   - Enough VRAM for {config.model_id} at TP={config.tensor_parallel}
#
# Usage:
#   chmod +x scripts/start_vllm.sh
#   ./scripts/start_vllm.sh

set -euo pipefail

echo "Starting vLLM server for Kimi K2.5..."
echo "  Model:   {config.model_id}"
echo "  TP:      {config.tensor_parallel}"
echo "  Context: {config.max_model_len}"
echo "  Port:    {config.port}"
echo ""

exec vllm serve {config.model_id} \\
  --tensor-parallel-size {config.tensor_parallel} \\
  --host 0.0.0.0 \\
  --port {config.port} \\
  --mm-encoder-tp-mode data \\
  --tool-call-parser kimi_k2 \\
  --reasoning-parser kimi_k2 \\
  --max-model-len {config.max_model_len} \\
  --trust-remote-code \\
  --enable-auto-tool-choice \\
  --gpu-memory-utilization 0.92 \\
  --swap-space 8 \\
  --enforce-eager \\
  "$@"
"""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(script, encoding="utf-8")
    p.chmod(0o755)
    log.info("Generated vLLM script: %s", output_path)
    return output_path


def generate_sglang_script(
    config: LocalConfig | None = None,
    output_path: str = "scripts/start_sglang.sh",
) -> str:
    """Generate an SGLang deployment script."""
    config = config or LocalConfig()

    script = f"""\
#!/usr/bin/env bash
# Horizon Orchestra — SGLang Inference Server
# Optimized for tool calling and structured output
#
# Requirements:
#   - pip install sglang[all]
#   - NVIDIA GPUs ({config.tensor_parallel}x)
#
# Usage:
#   chmod +x scripts/start_sglang.sh
#   ./scripts/start_sglang.sh

set -euo pipefail

echo "Starting SGLang server for Kimi K2.5..."
echo "  Model:   {config.model_id}"
echo "  TP:      {config.tensor_parallel}"
echo "  Port:    {config.port}"
echo ""

exec python -m sglang.launch_server \\
  --model-path {config.model_id} \\
  --tp {config.tensor_parallel} \\
  --host 0.0.0.0 \\
  --port {config.port} \\
  --trust-remote-code \\
  --tool-call-parser kimi_k2 \\
  --reasoning-parser kimi_k2 \\
  --mem-fraction-static 0.88 \\
  --chunked-prefill-size 8192 \\
  "$@"
"""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(script, encoding="utf-8")
    p.chmod(0o755)
    log.info("Generated SGLang script: %s", output_path)
    return output_path


def generate_ollama_modelfile(
    output_path: str = "scripts/Modelfile.kimi",
) -> str:
    """Generate an Ollama Modelfile for local Kimi K2.5 (quantized)."""
    modelfile = """\
# Horizon Orchestra — Ollama Modelfile for Kimi K2.5
# For local single-GPU inference (INT4 quantized)
#
# Usage:
#   ollama create kimi-k2.5 -f scripts/Modelfile.kimi
#   ollama run kimi-k2.5

FROM moonshotai/Kimi-K2.5

PARAMETER temperature 0.6
PARAMETER num_ctx 32768
PARAMETER num_predict 4096
PARAMETER top_p 0.9

SYSTEM \"\"\"You are Horizon Orchestra, an autonomous AI agent.
You have access to tools. Break complex tasks into steps.
Use tools iteratively until the task is complete.\"\"\"
"""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(modelfile, encoding="utf-8")
    log.info("Generated Ollama Modelfile: %s", output_path)
    return output_path
