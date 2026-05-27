from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TargetTechnology(Enum):
    FPGA_ARTIX7 = "xilinx-artix-7"
    FPGA_KINTEX = "xilinx-kintex-7"
    FPGA_VIRTEX = "xilinx-virtex-7"
    FPGA_ICE40 = "lattice-ice40"
    FPGA_ECP5 = "lattice-ecp5"
    ASIC_180NM = "asic-180nm"
    ASIC_45NM = "asic-45nm"
    ASIC_7NM = "asic-7nm"


@dataclass
class FPGATarget:
    family: str = "artix7"
    device: str = "xc7a35t"
    package: str = "csg324"
    speed_grade: str = "-1"
    lut_size: int = 4
    has_dsp: bool = True
    has_block_ram: bool = True
    max_freq_mhz: float = 200.0

    def part_number(self) -> str:
        return f"{self.device}{self.package}{self.speed_grade}"


@dataclass
class MappingResult:
    target_technology: TargetTechnology
    target_name: str = ""
    dsp_usage: int = 0
    lut_usage: int = 0
    ff_usage: int = 0
    bram_usage: int = 0
    max_freq_mhz: float = 0.0
    slack_ns: float = 0.0
    utilization_pct: float = 0.0
    estimated_power_mw: float = 0.0
    meets_timing: bool = False
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "target": self.target_name,
            "dsp": self.dsp_usage,
            "lut": self.lut_usage,
            "ff": self.ff_usage,
            "bram": self.bram_usage,
            "freq_mhz": self.max_freq_mhz,
            "slack_ns": self.slack_ns,
            "utilization_pct": self.utilization_pct,
            "timing_met": self.meets_timing,
        }


TECHNOLOGY_SPECS: dict[TargetTechnology, dict[str, Any]] = {
    TargetTechnology.FPGA_ARTIX7: {
        "max_lut": 20800, "max_ff": 41600, "max_bram": 50, "max_dsp": 90,
        "max_freq": 200.0, "default_device": "xc7a35t",
    },
    TargetTechnology.FPGA_KINTEX: {
        "max_lut": 203800, "max_ff": 407600, "max_bram": 445, "max_dsp": 840,
        "max_freq": 400.0, "default_device": "xc7k70t",
    },
    TargetTechnology.FPGA_ICE40: {
        "max_lut": 5280, "max_ff": 10560, "max_bram": 8, "max_dsp": 0,
        "max_freq": 100.0, "default_device": "ice40hx8k",
    },
    TargetTechnology.ASIC_45NM: {
        "max_lut": 10000000, "max_ff": 20000000, "max_bram": 0, "max_dsp": 0,
        "max_freq": 1000.0, "default_device": "",
    },
}


class TechnologyMapper:
    def __init__(self, target: TargetTechnology = TargetTechnology.FPGA_ARTIX7):
        self.target = target
        self.spec = TECHNOLOGY_SPECS.get(target, TECHNOLOGY_SPECS[TargetTechnology.FPGA_ARTIX7])

    def estimate_resources(self, datapath_snapshot: dict[str, Any]) -> MappingResult:
        result = MappingResult(
            target_technology=self.target,
            target_name=self.target.value,
        )

        comps = datapath_snapshot.get("components", [])
        for comp in comps:
            if isinstance(comp, dict):
                cname = comp.get("name", "")
                cwidth = comp.get("config", {}).get("data_width", 32)
            else:
                cname = getattr(comp, "name", "")
                cwidth = getattr(comp, "data_width", 32) if hasattr(comp, "data_width") else 32

            if "RF" in cname or "register" in cname.lower():
                nregs = 0
                if isinstance(comp, dict):
                    nregs = comp.get("num_registers", 32)
                else:
                    nregs = getattr(comp, "num_registers", 32)
                result.ff_usage += nregs * cwidth
            elif "ALU" in cname:
                result.lut_usage += cwidth * 4
                result.dsp_usage += 1 if cwidth <= 32 else 4
            elif "MUL" in cname or "mul" in cname.lower():
                result.dsp_usage += cwidth // 16
            elif "div" in cname.lower():
                result.lut_usage += cwidth * 8

        # Pipeline registers
        stages = datapath_snapshot.get("pipeline", {}).get("stages", [])
        result.ff_usage += len(stages) * 100

        result.max_freq_mhz = self.spec["max_freq"]
        result.utilization_pct = max(
            result.lut_usage / self.spec["max_lut"] * 100 if self.spec["max_lut"] else 0,
            result.ff_usage / self.spec["max_ff"] * 100 if self.spec["max_ff"] else 0,
        )
        result.utilization_pct = min(100.0, round(result.utilization_pct, 2))
        result.meets_timing = result.utilization_pct < 90

        if result.utilization_pct > 85:
            result.warnings.append(f"Utilization {result.utilization_pct}% exceeds 85% threshold")
        if result.dsp_usage > self.spec["max_dsp"]:
            result.warnings.append(f"DSP usage {result.dsp_usage} exceeds limit {self.spec['max_dsp']}")

        return result

    def suggest_alternative(self, result: MappingResult) -> list[TargetTechnology]:
        if result.utilization_pct > 85:
            suggestions = []
            for tech in TargetTechnology:
                if tech == self.target:
                    continue
                spec = TECHNOLOGY_SPECS.get(tech, {})
                if spec.get("max_lut", 0) > result.lut_usage:
                    suggestions.append(tech)
            return suggestions
        return []
