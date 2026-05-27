from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FitnessMetric:
    name: str
    weight: float = 1.0
    higher_is_better: bool = True
    description: str = ""

    def normalize(self, raw: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
        if max_val == min_val:
            return 1.0
        normalized = (raw - min_val) / (max_val - min_val)
        normalized = max(0.0, min(1.0, normalized))
        if not self.higher_is_better:
            normalized = 1.0 - normalized
        return normalized


@dataclass
class FitnessScore:
    overall: float = 0.0
    metrics: dict[str, float] = field(default_factory=dict)
    raw_metrics: dict[str, float] = field(default_factory=dict)
    details: str = ""


DEFAULT_METRICS = [
    FitnessMetric("timing", weight=3.0, higher_is_better=True,
                  description="Whether critical path meets cycle time"),
    FitnessMetric("area", weight=1.5, higher_is_better=False,
                  description="Estimated die area in um^2"),
    FitnessMetric("power", weight=1.5, higher_is_better=False,
                  description="Estimated power in mW"),
    FitnessMetric("instruction_count", weight=2.0, higher_is_better=True,
                  description="Number of supported instructions"),
    FitnessMetric("pipeline_depth", weight=1.0, higher_is_better=True,
                  description="Optimal pipeline stages"),
    FitnessMetric("hazard_handling", weight=1.5, higher_is_better=True,
                  description="Quality of hazard mitigation (forwarding, stalling)"),
    FitnessMetric("register_efficiency", weight=0.5, higher_is_better=True,
                  description="Register utilization efficiency"),
    FitnessMetric("bypass_coverage", weight=1.0, higher_is_better=True,
                  description="Forwarding path coverage"),
]


class FitnessEvaluator:
    def __init__(self, metrics: list[FitnessMetric] | None = None):
        self.metrics = metrics or DEFAULT_METRICS.copy()

    def evaluate(self, isa_snapshot: dict[str, Any],
                 datapath_snapshot: dict[str, Any],
                 rtl_snapshot: dict[str, Any]) -> FitnessScore:
        raw = {}
        raw["timing"] = self._eval_timing(datapath_snapshot)
        raw["area"] = self._eval_area(datapath_snapshot)
        raw["power"] = self._eval_power(datapath_snapshot)
        raw["instruction_count"] = self._eval_instruction_count(isa_snapshot)
        raw["pipeline_depth"] = self._eval_pipeline_depth(datapath_snapshot)
        raw["hazard_handling"] = self._eval_hazard_handling(datapath_snapshot)
        raw["register_efficiency"] = self._eval_register_efficiency(datapath_snapshot)
        raw["bypass_coverage"] = self._eval_bypass_coverage(datapath_snapshot)

        normalized = {}
        weighted_sum = 0.0
        total_weight = 0.0

        for metric in self.metrics:
            if metric.name in raw:
                ranges = {
                    "timing": (0, 1),
                    "area": (0, 50000),
                    "power": (0, 1000),
                    "instruction_count": (0, 50),
                    "pipeline_depth": (2, 7),
                    "hazard_handling": (0, 1),
                    "register_efficiency": (0, 1),
                    "bypass_coverage": (0, 1),
                }
                lo, hi = ranges.get(metric.name, (0, 1))
                norm = metric.normalize(raw[metric.name], lo, hi)
                normalized[metric.name] = round(norm, 4)
                weighted_sum += norm * metric.weight
                total_weight += metric.weight

        overall = round(weighted_sum / total_weight, 4) if total_weight else 0.0
        return FitnessScore(
            overall=overall,
            metrics=normalized,
            raw_metrics=raw,
        )

    def _eval_timing(self, dp: dict[str, Any]) -> float:
        if dp.get("timing_met", False):
            slack = dp.get("cycle_ns", 10) - dp.get("critical_path_ns", 0)
            return min(1.0, slack / dp.get("cycle_ns", 10) + 0.5) if dp.get("cycle_ns", 0) else 1.0
        return 0.0

    def _eval_area(self, dp: dict[str, Any]) -> float:
        comps = dp.get("components", [])
        if not comps:
            return 500.0
        if isinstance(comps[0], dict):
            areas = [c.get("area_um2", 0) for c in comps]
        else:
            areas = [getattr(c, "area_um2", 0) for c in comps]
        return sum(areas) if areas else 500.0

    def _eval_power(self, dp: dict[str, Any]) -> float:
        comps = dp.get("components", [])
        if not comps:
            return 50.0
        if isinstance(comps[0], dict):
            powers = [c.get("power_mw", 0) for c in comps]
        else:
            powers = [getattr(c, "power_mw", 0) for c in comps]
        return sum(powers) if powers else 50.0

    def _eval_instruction_count(self, isa: dict[str, Any]) -> float:
        instrs = isa.get("instructions", [])
        return float(len(instrs))

    def _eval_pipeline_depth(self, dp: dict[str, Any]) -> float:
        pipe = dp.get("pipeline", {})
        stages = pipe.get("stages", [])
        return float(len(stages))

    def _eval_hazard_handling(self, dp: dict[str, Any]) -> float:
        pipe = dp.get("pipeline", {})
        score = 0.0
        if pipe.get("hazard_detection", False):
            score += 0.5
        if pipe.get("forwarding", False):
            score += 0.3
        predictor = pipe.get("branch_predictor", "none")
        if predictor and predictor != "none":
            score += 0.2
        return score

    def _eval_register_efficiency(self, dp: dict[str, Any]) -> float:
        rf = dp.get("register_file", {})
        if isinstance(rf, dict):
            nregs = rf.get("num_registers", 32)
            ports = rf.get("read_ports", 2) + rf.get("write_ports", 1)
        else:
            nregs = getattr(rf, "num_registers", 32)
            ports = getattr(rf, "num_read_ports", 2) + getattr(rf, "num_write_ports", 1)
        return min(1.0, ports / (nregs ** 0.5))

    def _eval_bypass_coverage(self, dp: dict[str, Any]) -> float:
        pipe = dp.get("pipeline", {})
        if pipe.get("forwarding", False):
            stages = pipe.get("stages", [])
            stage_count = len(stages)
            if stage_count >= 5:
                return 0.9
            elif stage_count >= 3:
                return 0.7
            return 0.5
        return 0.0

    def compare(self, scores: list[FitnessScore]) -> list[tuple[int, float]]:
        indexed = list(enumerate(scores))
        indexed.sort(key=lambda x: x[1].overall, reverse=True)
        return indexed
