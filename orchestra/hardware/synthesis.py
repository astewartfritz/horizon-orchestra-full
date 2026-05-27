from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SynthesisResult:
    success: bool = False
    tool: str = ""
    log: str = ""
    cell_count: int = 0
    frequency_mhz: float = 0.0
    area_um2: float = 0.0
    power_mw: float = 0.0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    output_files: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class SynthesisTool:
    def __init__(self, tool_path: str | None = None, work_dir: str | Path | None = None):
        self.tool_path = tool_path or self._find_tool()
        self.work_dir = Path(work_dir or tempfile.mkdtemp())
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def _find_tool(self) -> str:
        raise NotImplementedError

    def synthesize(self, verilog_sources: list[str | Path], top_module: str = "top",
                   **kwargs: Any) -> SynthesisResult:
        raise NotImplementedError

    def check_available(self) -> bool:
        try:
            subprocess.run([self.tool_path, "--version"],
                           capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False


class YosysSynthesis(SynthesisTool):
    def _find_tool(self) -> str:
        return "yosys"

    def synthesize(self, verilog_sources: list[str | Path], top_module: str = "top",
                   target_freq_mhz: float = 100.0,
                   target_tech: str = "cmos", **kwargs: Any) -> SynthesisResult:
        result = SynthesisResult(tool="Yosys")

        if not self.check_available():
            result.success = False
            result.log = "Yosys not found. Install with: conda install -c conda-forge yosys"
            result.errors.append("Yosys binary not available")
            return result

        sources = [str(s) for s in verilog_sources]
        script_path = self.work_dir / "synth.ys"

        script_lines = [
            f"read_verilog {' '.join(sources)}",
            f"hierarchy -top {top_module}",
            "proc; opt; fsm; opt; memory; opt",
            f"techmap; opt",
            f"stat -top {top_module}",
            f"check -top {top_module}",
            f"write_json {self.work_dir / 'synth_result.json'}",
        ]
        script_path.write_text("\n".join(script_lines))

        proc = subprocess.run(
            [self.tool_path, "-s", str(script_path)],
            capture_output=True, text=True, timeout=120,
        )

        result.log = proc.stdout + proc.stderr
        result.success = proc.returncode == 0

        if proc.returncode != 0:
            result.errors.append(proc.stderr[:2000])

        for line in proc.stdout.split("\n"):
            if "Warning:" in line:
                result.warnings.append(line.strip())
            if "Error:" in line:
                result.errors.append(line.strip())

        # Parse stats
        for line in proc.stdout.split("\n"):
            if "Number of cells:" in line:
                try:
                    result.cell_count = int(line.split(":")[1].strip())
                except (ValueError, IndexError):
                    pass
            if "Estimated frequency:" in line:
                try:
                    freq_str = line.split(":")[1].strip().replace("MHz", "").strip()
                    result.frequency_mhz = float(freq_str)
                except (ValueError, IndexError):
                    pass
            if "Chip area:" in line:
                try:
                    area_str = line.split(":")[1].strip().replace("um^2", "").strip()
                    result.area_um2 = float(area_str)
                except (ValueError, IndexError):
                    pass

        result.output_files = [str(f) for f in self.work_dir.glob("*")]
        return result
