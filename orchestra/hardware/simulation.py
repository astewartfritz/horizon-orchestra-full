from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SimulationResult:
    success: bool = False
    tool: str = ""
    log: str = ""
    passed: int = 0
    failed: int = 0
    total: int = 0
    waveforms: list[str] = field(default_factory=list)
    coverage: float = 0.0
    sim_time_ns: float = 0.0
    errors: list[str] = field(default_factory=list)
    signals: dict[str, list[int]] = field(default_factory=dict)


class SimulationTool:
    def __init__(self, tool_path: str | None = None, work_dir: str | Path | None = None):
        self.tool_path = tool_path or self._find_tool()
        self.work_dir = Path(work_dir or tempfile.mkdtemp())
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def _find_tool(self) -> str:
        raise NotImplementedError

    def simulate(self, verilog_sources: list[str | Path], top_module: str = "top",
                 testbench: str | None = None, **kwargs: Any) -> SimulationResult:
        raise NotImplementedError

    def check_available(self) -> bool:
        try:
            subprocess.run([self.tool_path, "-V"],
                           capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False


class IverilogSimulation(SimulationTool):
    def _find_tool(self) -> str:
        return "iverilog"

    def simulate(self, verilog_sources: list[str | Path], top_module: str = "top",
                 testbench: str | None = None,
                 sim_time_ns: float = 1000.0,
                 vcd_output: str | None = None,
                 **kwargs: Any) -> SimulationResult:
        result = SimulationResult(tool="Icarus Verilog (iverilog)")

        if not self.check_available():
            result.success = False
            result.log = "Icarus Verilog not found. Install with: conda install -c conda-forge iverilog"
            result.errors.append("iverilog not available")
            return result

        vvp_path = self.work_dir / "sim.vvp"
        sources = [str(s) for s in verilog_sources]

        if testbench:
            tb_path = self.work_dir / "testbench.v"
            tb_path.write_text(testbench)
            sources.append(str(tb_path))

        compile_proc = subprocess.run(
            [self.tool_path, "-o", str(vvp_path), "-g2012"] + sources,
            capture_output=True, text=True, timeout=60,
        )

        if compile_proc.returncode != 0:
            result.success = False
            result.log = compile_proc.stdout + compile_proc.stderr
            result.errors.append(compile_proc.stderr[:2000])
            return result

        vvp_bin = "vvp"
        run_proc = subprocess.run(
            [vvp_bin, str(vvp_path)],
            capture_output=True, text=True, timeout=60,
        )

        result.log = run_proc.stdout + run_proc.stderr
        result.success = run_proc.returncode == 0

        output_lines = run_proc.stdout.split("\n")
        for line in output_lines:
            if "PASSED" in line or "passed" in line.lower():
                result.passed += 1
                result.total += 1
            elif "FAILED" in line or "failed" in line.lower():
                result.failed += 1
                result.total += 1
            if "Error:" in line:
                result.errors.append(line.strip())

        if vcd_output:
            vcd_path = self.work_dir / vcd_output
            if vcd_path.exists():
                result.waveforms.append(str(vcd_path))

        return result
