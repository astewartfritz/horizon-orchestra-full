from __future__ import annotations

import cProfile
import io
import pstats
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Hotspot:
    function: str
    filename: str
    lineno: int
    cumulative_time: float
    call_count: int
    per_call: float
    cum_per_call: float


@dataclass
class ProfileResult:
    total_time: float
    hotspots: list[Hotspot] = field(default_factory=list)
    call_count: int = 0
    output_path: str = ""


class CodeProfiler:
    def __init__(self):
        self.results: dict[str, ProfileResult] = {}

    def profile_function(self, func, *args, **kwargs) -> ProfileResult:
        profiler = cProfile.Profile()
        profiler.enable()
        start = time.perf_counter()
        try:
            func(*args, **kwargs)
        except Exception:
            pass
        profiler.disable()
        elapsed = time.perf_counter() - start

        s = io.StringIO()
        ps = pstats.Stats(profiler, stream=s).sort_stats("cumulative")
        ps.print_stats(30)

        hotspots = []
        ps2 = pstats.Stats(profiler, stream=io.StringIO()).sort_stats("cumulative")
        for func_name, (cc, nc, tt, ct, callers) in ps2.stats.items():
            filename, lineno, fn_name = func_name
            if fn_name.startswith("_"):
                continue
            hotspots.append(Hotspot(
                function=fn_name,
                filename=filename,
                lineno=lineno,
                cumulative_time=ct,
                call_count=cc,
                per_call=tt / cc if cc else 0,
                cum_per_call=ct / cc if cc else 0,
            ))

        hotspots.sort(key=lambda h: h.cumulative_time, reverse=True)
        result = ProfileResult(total_time=elapsed, hotspots=hotspots[:20], call_count=sum(h.call_count for h in hotspots))
        self.results[func.__name__] = result
        return result

    def profile_code(self, code: str, globals_dict: Optional[dict] = None, locals_dict: Optional[dict] = None) -> ProfileResult:
        compiled = compile(code, "<profile>", "exec")
        namespace = {}
        if globals_dict:
            namespace.update(globals_dict)
        if locals_dict:
            namespace.update(locals_dict)

        profiler = cProfile.Profile()
        profiler.enable()
        start = time.perf_counter()
        try:
            exec(compiled, namespace)
        except Exception:
            pass
        profiler.disable()
        elapsed = time.perf_counter() - start

        hotspots = []
        ps = pstats.Stats(profiler, stream=io.StringIO()).sort_stats("cumulative")
        for func_name, (cc, nc, tt, ct, callers) in ps.stats.items():
            filename, lineno, fn_name = func_name
            if fn_name.startswith("_"):
                continue
            hotspots.append(Hotspot(
                function=fn_name, filename=filename, lineno=lineno,
                cumulative_time=ct, call_count=cc, per_call=tt / cc if cc else 0, cum_per_call=ct / cc if cc else 0,
            ))

        hotspots.sort(key=lambda h: h.cumulative_time, reverse=True)
        return ProfileResult(total_time=elapsed, hotspots=hotspots[:20], call_count=sum(h.call_count for h in hotspots))

    def profile_script(self, script_path: str) -> ProfileResult:
        path = Path(script_path)
        code = path.read_text(encoding="utf-8")
        return self.profile_code(code, {"__name__": "__main__", "__file__": str(path.resolve())})

    def save_flamegraph(self, result: ProfileResult, output_path: str) -> str:
        lines = []
        for h in result.hotspots:
            frames = [f"{h.filename}:{h.function}:{h.lineno}"]
            lines.append(f"{';'.join(frames)} {h.cumulative_time:.6f}")
        Path(output_path).write_text("\n".join(lines), encoding="utf-8")
        result.output_path = output_path
        return output_path

    def summary_text(self, result: ProfileResult) -> str:
        lines = [
            f"Total time: {result.total_time:.4f}s",
            f"Total calls: {result.call_count}",
            "",
            "Hotspots (by cumulative time):",
            f"{'Function':<30} {'File':<30} {'Cum Time':<10} {'Calls':<8} {'Per Call':<10}",
            "-" * 90,
        ]
        for h in result.hotspots[:15]:
            lines.append(f"{h.function:<30} {Path(h.filename).name:<30} {h.cumulative_time:<10.4f} {h.call_count:<8} {h.per_call:<10.6f}")
        return "\n".join(lines)
