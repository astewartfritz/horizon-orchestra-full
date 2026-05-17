from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class EdgeMode(str, Enum):
    OLLAMA = "ollama"
    GGUF = "gguf"
    ONNX = "onnx"
    OFFLINE = "offline"
    PRIVACY = "privacy"


@dataclass
class EdgeAdapter:
    """On-device SLM adapter for edge inference.

    Supports multiple edge modes:
      OLLAMA  → local Ollama server (http://localhost:11434)
      GGUF    → llama.cpp GGUF model file
      ONNX    → ONNX Runtime quantized model
      OFFLINE → mock/cached responses (no network)
      PRIVACY → strict local-only, no data leaves device
    """

    mode: EdgeMode = EdgeMode.OLLAMA
    model_path: str = ""
    ollama_model: str = "qwen2.5:1.5b"
    ollama_base_url: str = "http://localhost:11434"
    cache_ttl: float = 300.0
    enable_cache: bool = True
    privacy_mode: bool = True

    _cache: dict[str, tuple[str, float]] = field(default_factory=dict)
    _client: Any = None

    async def infer(self, prompt: str, lane: str = "general") -> tuple[str | None, str | None]:
        if self.privacy_mode:
            return await self._infer_local(prompt, lane)
        return await self._infer_local(prompt, lane)

    async def _infer_local(self, prompt: str, lane: str) -> tuple[str | None, str | None]:
        cache_key = f"{lane}:{hash(prompt)}"
        if self.enable_cache and cache_key in self._cache:
            result, expiry = self._cache[cache_key]
            if time.time() < expiry:
                return result, None

        if self.mode == EdgeMode.OFFLINE:
            result = self._mock_infer(prompt, lane)
        elif self.mode == EdgeMode.OLLAMA:
            result = await self._ollama_infer(prompt)
        elif self.mode == EdgeMode.GGUF:
            result = await self._gguf_infer(prompt)
        elif self.mode == EdgeMode.ONNX:
            result = await self._onnx_infer(prompt)
        else:
            result = self._mock_infer(prompt, lane)

        if result[0] and self.enable_cache:
            self._cache[cache_key] = (result[0], time.time() + self.cache_ttl)

        return result

    async def _ollama_infer(self, prompt: str) -> tuple[str | None, str | None]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.ollama_base_url}/api/generate",
                    json={
                        "model": self.ollama_model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"num_predict": 512, "temperature": 0.3},
                    },
                )
                data = resp.json()
                return data.get("response", ""), None
        except Exception as e:
            logger.warning(f"Edge Ollama inference failed: {e}")
            return None, str(e)

    async def _gguf_infer(self, prompt: str) -> tuple[str | None, str | None]:
        try:
            from llama_cpp import Llama
            llm = Llama(
                model_path=self.model_path,
                n_ctx=2048, n_threads=4, verbose=False,
            )
            output = llm(prompt, max_tokens=512, temperature=0.3, echo=False)
            return output.get("choices", [{}])[0].get("text", ""), None
        except ImportError:
            return None, "llama_cpp not installed"
        except Exception as e:
            return None, str(e)

    async def _onnx_infer(self, prompt: str) -> tuple[str | None, str | None]:
        try:
            import onnxruntime as ort
            session = ort.InferenceSession(self.model_path)
            input_name = session.get_inputs()[0].name
            result = session.run(None, {input_name: [prompt]})
            return str(result[0]) if result else "", None
        except ImportError:
            return None, "onnxruntime not installed"
        except Exception as e:
            return None, str(e)

    def _mock_infer(self, prompt: str, lane: str) -> tuple[str, None]:
        return (f"[Edge {lane}] Mock response for: {prompt[:50]}...", None)

    def clear_cache(self):
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        return len(self._cache)
