from __future__ import annotations

from typing import Any


MODEL_PRICING = {
    "gpt-4o": {"input": 2.50, "output": 10.00, "per": 1_000_000},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "per": 1_000_000},
    "gpt-4": {"input": 30.00, "output": 60.00, "per": 1_000_000},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50, "per": 1_000_000},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00, "per": 1_000_000},
    "claude-3-opus": {"input": 15.00, "output": 75.00, "per": 1_000_000},
    "claude-3-haiku": {"input": 0.25, "output": 1.25, "per": 1_000_000},
}


class CostEstimator:
    """Estimate token usage and cost before running an agent task."""

    def __init__(self, model: str = "gpt-4o"):
        self.model = model
        self.pricing = MODEL_PRICING.get(model, {"input": 2.50, "output": 10.00, "per": 1_000_000})

    def estimate_tokens(self, text: str) -> int:
        try:
            import tiktoken
            enc = tiktoken.encoding_for_model(self.model)
            return len(enc.encode(text))
        except Exception:
            return len(text) // 4

    def estimate_task(self, task: str, context_size: int = 5000, expected_turns: int = 5) -> dict[str, Any]:
        task_tokens = self.estimate_tokens(task)
        system_prompt_tokens = 500

        input_per_turn = task_tokens + system_prompt_tokens + context_size
        output_per_turn = 1000

        total_input = input_per_turn * expected_turns
        total_output = output_per_turn * expected_turns

        input_cost = (total_input / self.pricing["per"]) * self.pricing["input"]
        output_cost = (total_output / self.pricing["per"]) * self.pricing["output"]

        return {
            "model": self.model,
            "task_tokens": task_tokens,
            "expected_turns": expected_turns,
            "estimated_input_tokens": total_input,
            "estimated_output_tokens": total_output,
            "estimated_total_tokens": total_input + total_output,
            "estimated_cost_usd": round(input_cost + output_cost, 6),
            "input_cost": round(input_cost, 6),
            "output_cost": round(output_cost, 6),
            "pricing_input_per_m": self.pricing["input"],
            "pricing_output_per_m": self.pricing["output"],
        }

    def estimate_file(self, file_path: str, task_description: str = "Analyze {file}") -> dict[str, Any]:
        import os
        size = os.path.getsize(file_path)
        task = task_description.replace("{file}", file_path)
        context_size = self.estimate_tokens(open(file_path, "rb").read().decode("utf-8", errors="ignore"))
        return self.estimate_task(task, context_size=context_size)

    def compare_models(self, task: str) -> list[dict[str, Any]]:
        results = []
        original_model = self.model
        for model_name in MODEL_PRICING:
            self.model = model_name
            self.pricing = MODEL_PRICING[model_name]
            results.append(self.estimate_task(task))
        self.model = original_model
        self.pricing = MODEL_PRICING.get(original_model, {"input": 2.50, "output": 10.00, "per": 1_000_000})
        return sorted(results, key=lambda r: r["estimated_cost_usd"])
