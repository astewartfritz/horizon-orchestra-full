from __future__ import annotations

import os
import time
import uuid
from typing import Any, AsyncGenerator

from code_agent.llm.base import LLMError, Message
from code_agent.serving.base import BaseProvider, ProviderConfig, ProviderMetadata


class VLLMProvider(BaseProvider):
    """Provider that uses vLLM's AsyncLLM engine for local model serving.

    Leverages vLLM's high-performance inference engine (PagedAttention,
    continuous batching, CUDA kernels) for running LLMs locally.
    Requires: pip install code-agent[vllm] or pip install vllm
    """

    def __init__(self, model: str, config: ProviderConfig | None = None):
        super().__init__(model, config)
        self._engine: Any = None
        self._tokenizer: Any = None
        self._model_config: Any = None

    async def _ensure_engine(self) -> None:
        if self._engine is not None:
            return
        try:
            from vllm.engine.arg_utils import AsyncEngineArgs
            from vllm.v1.engine.async_llm import AsyncLLM
        except ImportError:
            raise LLMError(
                "vLLM is not installed. Install with: pip install vllm "
                "or: pip install code-agent[vllm]"
            )

        args = AsyncEngineArgs(
            model=self.model,
            max_model_len=self.config.max_tokens * 2,
            gpu_memory_utilization=float(
                os.environ.get("VLLM_GPU_MEMORY_UTILIZATION", "0.90")
            ),
            dtype=os.environ.get("VLLM_DTYPE", "auto"),
            tensor_parallel_size=int(
                os.environ.get("VLLM_TENSOR_PARALLEL_SIZE", "1")
            ),
            enable_prefix_caching=True,
            max_num_seqs=int(os.environ.get("VLLM_MAX_NUM_SEQS", "256")),
            seed=self.config.extra_headers.get("seed") if self.config.extra_headers else None,
            enforce_eager=os.environ.get("VLLM_ENFORCE_EAGER", "").lower() == "true",
        )

        self._engine = await AsyncLLM.from_engine_args(args)
        self._model_config = self._engine.model_config

    def _get_tokenizer(self):
        if self._tokenizer is None:
            from transformers import AutoTokenizer
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model, trust_remote_code=True
            )
        return self._tokenizer

    def _messages_to_prompt(self, messages: list[Message]) -> str:
        tokenizer = self._get_tokenizer()
        openai_messages = []
        for msg in messages:
            d = {"role": msg.role, "content": msg.content or ""}
            if msg.tool_calls:
                d["tool_calls"] = [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("function", {}).get("name", ""),
                            "arguments": tc.get("function", {}).get("arguments", "{}"),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            if msg.tool_call_id:
                d["tool_call_id"] = msg.tool_call_id
            openai_messages.append(d)

        return tokenizer.apply_chat_template(
            openai_messages,
            tokenize=False,
            add_generation_prompt=True,
        )

    def _build_sampling_params(self, tools: list[dict] | None = None):
        from vllm.sampling_params import SamplingParams

        kwargs: dict[str, Any] = {
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stop": None,
        }

        if self.config.temperature == 0.0:
            kwargs["temperature"] = 0.0

        if tools:
            from vllm.entrypoints.chat_utils import parse_tool_choice
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        return SamplingParams(**kwargs)

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
    ) -> Message:
        await self._ensure_engine()

        prompt = self._messages_to_prompt(messages)
        sampling_params = self._build_sampling_params(tools)

        request_id = f"chat-{uuid.uuid4().hex[:12]}"
        full_text = ""

        async for output in self._engine.generate(
            prompt, sampling_params, request_id
        ):
            for completion in output.outputs:
                delta = completion.text
                if delta:
                    full_text += delta
                    if stream and self._on_token:
                        self._on_token(delta)

        return Message(role="assistant", content=full_text.strip())

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[str, None]:
        await self._ensure_engine()

        prompt = self._messages_to_prompt(messages)
        sampling_params = self._build_sampling_params(tools)

        request_id = f"stream-{uuid.uuid4().hex[:12]}"

        async for output in self._engine.generate(
            prompt, sampling_params, request_id
        ):
            for completion in output.outputs:
                delta = completion.text
                if delta:
                    yield delta

    async def chat_structured(
        self,
        messages: list[Message],
        response_model: type[Any],
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        await self._ensure_engine()

        prompt = self._messages_to_prompt(messages)

        schema = response_model.model_json_schema() if hasattr(response_model, "model_json_schema") else {}
        from vllm.sampling_params import SamplingParams, StructuredOutputsParams

        sampling_params = SamplingParams(
            temperature=self.config.temperature or 0.0,
            max_tokens=self.config.max_tokens,
            structured_outputs=StructuredOutputsParams(json=schema),
        )

        request_id = f"struct-{uuid.uuid4().hex[:12]}"
        full_text = ""

        async for output in self._engine.generate(
            prompt, sampling_params, request_id
        ):
            for completion in output.outputs:
                if completion.text:
                    full_text += completion.text

        import json
        try:
            data = json.loads(full_text.strip())
            if hasattr(response_model, "model_validate"):
                return response_model.model_validate(data)
            return response_model(**data)
        except Exception as e:
            raise LLMError(f"Failed to parse structured output: {e}\nRaw: {full_text[:500]}")

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="vllm",
            supported_models=["*"],
            supports_streaming=True,
            supports_structured=True,
            supports_tools=True,
            supports_system_prompt=True,
        )

    async def check_health(self) -> bool:
        try:
            await self._ensure_engine()
            await self._engine.check_health()
            return True
        except Exception:
            return False

    async def shutdown(self) -> None:
        if self._engine is not None:
            self._engine.shutdown()
            self._engine = None
