from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from code_agent.rl.buffer import ExperienceBuffer
from code_agent.rl.policy import RoutingPolicy

logger = logging.getLogger(__name__)


@dataclass
class TrainingReport:
    policy_updates: int
    preference_pairs: int
    lora_trained: bool
    duration_ms: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_updates": self.policy_updates,
            "preference_pairs": self.preference_pairs,
            "lora_trained": self.lora_trained,
            "duration_ms": round(self.duration_ms, 1),
            "timestamp": self.timestamp,
        }


class OrchestraTrainer:
    """Trains the routing policy from accumulated experience signals.

    Two training modes:
    1. **Policy table update** (always available):
       Re-reads all buffer signals and re-applies EMA updates so the policy
       converges toward the empirically best agents per task category.

    2. **LoRA fine-tuning** (optional — requires transformers + peft + datasets):
       Builds preference pairs from the buffer and fine-tunes a small routing
       classifier via DPO. Falls back gracefully if libraries are absent.
    """

    def __init__(
        self,
        buffer: ExperienceBuffer,
        policy: RoutingPolicy,
        lora_model_id: str = "distilbert-base-uncased",
        lora_output_dir: str = ".orchestra-lora",
        min_pairs_for_lora: int = 50,
    ):
        self._buffer = buffer
        self._policy = policy
        self._lora_model_id = lora_model_id
        self._lora_output_dir = lora_output_dir
        self._min_pairs_for_lora = min_pairs_for_lora
        self._reports: list[TrainingReport] = []

    def train(self, run_lora: bool = False) -> TrainingReport:
        """Run a full training cycle; return a report."""
        start = time.time()

        # 1. Re-apply all buffer signals to policy
        updates = self._update_policy_from_buffer()

        # 2. Count preference pairs
        pairs = self._buffer.preference_pairs()
        n_pairs = len(pairs)

        # 3. Optionally run LoRA
        lora_done = False
        if run_lora and n_pairs >= self._min_pairs_for_lora:
            lora_done = self._run_lora(pairs)

        report = TrainingReport(
            policy_updates=updates,
            preference_pairs=n_pairs,
            lora_trained=lora_done,
            duration_ms=(time.time() - start) * 1000,
        )
        self._reports.append(report)
        if len(self._reports) > 50:
            self._reports = self._reports[-50:]
        return report

    def _update_policy_from_buffer(self) -> int:
        """Re-apply EMA updates for all buffered signals."""
        signals = self._buffer.recent(limit=10_000)
        updates = 0
        for s in signals:
            try:
                self._policy.update(
                    agent_name=s["agent_name"],
                    task_category=s["task_category"],
                    reward=s["reward"],
                )
                updates += 1
            except Exception as e:
                logger.debug("Policy update failed: %s", e)
        return updates

    def _run_lora(self, pairs: list[dict]) -> bool:
        """Fine-tune a small DistilBERT classifier on preference pairs via LoRA.

        Returns True if successful, False if dependencies are unavailable.
        """
        try:
            from transformers import (
                AutoModelForSequenceClassification,
                AutoTokenizer,
                Trainer,
                TrainingArguments,
            )
            from peft import LoraConfig, TaskType, get_peft_model
            import torch
        except ImportError:
            logger.info(
                "LoRA fine-tuning skipped: transformers/peft/torch not installed. "
                "Policy table learning is active."
            )
            return False

        try:
            logger.info("Starting LoRA fine-tuning on %d preference pairs", len(pairs))

            # Build a simple classification dataset:
            # input = task_preview, label = winner_agent_index
            # (maps agents to integer IDs for classification)
            agent_ids: dict[str, int] = {}
            examples: list[dict] = []
            for p in pairs:
                winner = p["winner"]
                task = p["task"]
                if winner not in agent_ids:
                    agent_ids[winner] = len(agent_ids)
                examples.append({"text": task, "label": agent_ids[winner]})

            if len(agent_ids) < 2:
                logger.info("LoRA skipped: need ≥2 distinct winning agents, got %d", len(agent_ids))
                return False

            tokenizer = AutoTokenizer.from_pretrained(self._lora_model_id)
            model = AutoModelForSequenceClassification.from_pretrained(
                self._lora_model_id, num_labels=len(agent_ids)
            )

            lora_cfg = LoraConfig(
                task_type=TaskType.SEQ_CLS,
                r=8,
                lora_alpha=16,
                target_modules=["q_lin", "k_lin"],
                lora_dropout=0.1,
            )
            model = get_peft_model(model, lora_cfg)

            # Tokenise
            encodings = tokenizer(
                [e["text"] for e in examples],
                truncation=True, padding=True, max_length=128, return_tensors="pt"
            )
            labels = torch.tensor([e["label"] for e in examples])

            class _DS(torch.utils.data.Dataset):
                def __len__(self):
                    return len(labels)
                def __getitem__(self, idx):
                    return {k: v[idx] for k, v in encodings.items()} | {"labels": labels[idx]}

            args = TrainingArguments(
                output_dir=self._lora_output_dir,
                num_train_epochs=3,
                per_device_train_batch_size=8,
                logging_steps=50,
                save_strategy="no",
                no_cuda=not torch.cuda.is_available(),
                report_to="none",
            )
            trainer = Trainer(model=model, args=args, train_dataset=_DS())
            trainer.train()
            model.save_pretrained(self._lora_output_dir)
            tokenizer.save_pretrained(self._lora_output_dir)

            # Persist agent→id mapping alongside the model
            import json, os
            with open(os.path.join(self._lora_output_dir, "agent_ids.json"), "w") as f:
                json.dump(agent_ids, f)

            logger.info("LoRA fine-tuning complete → %s", self._lora_output_dir)
            return True

        except Exception as e:
            logger.error("LoRA training failed: %s", e)
            return False

    def last_reports(self, n: int = 10) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._reports[-n:]]
