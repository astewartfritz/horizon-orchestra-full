from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class PipelineStage(Enum):
    FETCH = auto()
    DECODE = auto()
    EXECUTE = auto()
    MEMORY = auto()
    WRITEBACK = auto()


@dataclass
class DatapathComponent:
    name: str = ""
    latency_ns: float = 0.0
    area_um2: float = 0.0
    power_mw: float = 0.0
    config: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.name} (latency={self.latency_ns}ns, area={self.area_um2}um2)"


@dataclass
class RegisterFile(DatapathComponent):
    num_registers: int = 32
    data_width: int = 32
    num_read_ports: int = 2
    num_write_ports: int = 1

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"RF_{self.num_registers}x{self.data_width}"
        self.config.update({
            "num_registers": self.num_registers,
            "data_width": self.data_width,
            "read_ports": self.num_read_ports,
            "write_ports": self.num_write_ports,
        })
        if not self.latency_ns:
            self.latency_ns = 0.5
        if not self.area_um2:
            self.area_um2 = self.num_registers * 50.0

    def address_bits(self) -> int:
        import math
        return math.ceil(math.log2(self.num_registers))


@dataclass
class ALU(DatapathComponent):
    supported_ops: list[str] = field(default_factory=lambda: [
        "add", "sub", "and", "or", "xor", "sll", "srl", "slt"
    ])
    data_width: int = 32
    has_mul: bool = False
    has_div: bool = False
    has_fpu: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            ext = ""
            if self.has_mul:
                ext += "M"
            if self.has_fpu:
                ext += "F"
            self.name = f"ALU_{self.data_width}b{ext}"
        self.config.update({
            "data_width": self.data_width,
            "ops": self.supported_ops,
            "has_mul": self.has_mul,
            "has_div": self.has_div,
            "has_fpu": self.has_fpu,
        })
        if not self.latency_ns:
            self.latency_ns = 2.0 if self.has_mul else 1.0
        if not self.area_um2:
            base = self.data_width * 10.0
            if self.has_mul:
                base *= 4
            if self.has_fpu:
                base *= 8
            self.area_um2 = base

    def op_count(self) -> int:
        return len(self.supported_ops)


@dataclass
class Pipeline:
    stages: list[PipelineStage] = field(default_factory=lambda: list(PipelineStage))
    hazard_detection: bool = True
    forwarding: bool = True
    branch_predictor: str = "static-not-taken"

    def stage_count(self) -> int:
        return len(self.stages)

    def has_bypass(self) -> bool:
        return self.forwarding

    def description(self) -> str:
        names = [s.name for s in self.stages]
        return f"{len(names)}-stage: {' → '.join(names)}"


@dataclass
class Datapath:
    name: str
    pipeline: Pipeline = field(default_factory=Pipeline)
    register_file: RegisterFile = field(default_factory=RegisterFile)
    alu: ALU = field(default_factory=ALU)
    components: list[DatapathComponent] = field(default_factory=list)
    clock_freq_mhz: float = 100.0

    def __post_init__(self) -> None:
        if not self.components:
            self.components = [self.register_file, self.alu]

    def add_component(self, component: DatapathComponent) -> None:
        self.components.append(component)

    def cycle_time_ns(self) -> float:
        return 1000.0 / self.clock_freq_mhz

    def critical_path_ns(self) -> float:
        path_map = {
            PipelineStage.FETCH: 1.0,
            PipelineStage.DECODE: 0.5,
            PipelineStage.EXECUTE: self.alu.latency_ns,
            PipelineStage.MEMORY: 0.8,
            PipelineStage.WRITEBACK: 0.3,
        }
        comp_map = {c.name: c.latency_ns for c in self.components}

        total = 0.0
        for stage in PipelineStage:
            if stage in self.pipeline.stages:
                stage_ns = path_map.get(stage, 0.5)
                # Allow component overrides if a component matches stage semantics
                for cname, clat in comp_map.items():
                    if stage.name.lower() in cname.lower():
                        stage_ns = clat
                        break
                total += stage_ns
        return total

    def is_timing_met(self) -> bool:
        return self.critical_path_ns() <= self.cycle_time_ns()

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "pipeline": self.pipeline.description(),
            "register_file": f"{self.register_file.num_registers}x{self.register_file.data_width}",
            "alu_ops": self.alu.op_count(),
            "clock_mhz": self.clock_freq_mhz,
            "cycle_ns": self.cycle_time_ns(),
            "critical_path_ns": self.critical_path_ns(),
            "timing_met": self.is_timing_met(),
            "components": [c.name for c in self.components],
        }


FIVE_STAGE_PIPELINE = Pipeline(
    stages=[
        PipelineStage.FETCH,
        PipelineStage.DECODE,
        PipelineStage.EXECUTE,
        PipelineStage.MEMORY,
        PipelineStage.WRITEBACK,
    ],
    hazard_detection=True,
    forwarding=True,
    branch_predictor="static-not-taken",
)
