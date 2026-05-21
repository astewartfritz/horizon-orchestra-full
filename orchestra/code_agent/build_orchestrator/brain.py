"""AI-native build analysis — error diagnosis, fix suggestions, and LLM copilot."""
from __future__ import annotations

import random
from typing import Any

from orchestra.code_agent.build_orchestrator.engine import BuildEngine
from orchestra.code_agent.build_orchestrator.patches import PatchManager
from orchestra.code_agent.build_orchestrator.profiles import BuildProfileManager

ERROR_FIXES: dict[str, str] = {
    "undefined symbol": (
        "Add the missing target to `deps` in the BUILD.gn file for the source file, "
        "or ensure the symbol is exported from the dependent library."
    ),
    "FAILED:.*chromium": (
        "Check for pending merges in the target. Run `git status` to verify the "
        "source tree is clean, then retry the build with `ninja -C out/Default chrome -j1`."
    ),
    "Assertion failed": (
        "The GN assertion failed. Check the referenced BUILD.gn file to verify the "
        "condition. If this is from a patch, verify the patch applies cleanly."
    ),
    "file not found": (
        "The header file is missing. Run `gclient sync` to ensure all dependencies "
        "are fetched. If the file is new, add it to the BUILD.gn file."
    ),
    "android_sdk_root": (
        "Set `android_sdk_root` in your GN args. Use the `src/build/android/envsetup.sh` "
        "script or set the path explicitly: `gn args out/Default --args=\"android_sdk_root=\\\"/path/to/sdk\\\"\"`"
    ),
    "ld.lld": (
        "Linker error. Common fixes:\n"
        "1. Ensure all .o files are listed in the target sources\n"
        "2. Check for missing libraries in lib_dirs/libs\n"
        "3. Verify all symbols are defined in the dependency graph"
    ),
    "ASAN": (
        "AddressSanitizer detected a memory error. Common causes:\n"
        "1. Use-after-free: check object lifetimes\n"
        "2. Buffer overflow: verify array bounds\n"
        "3. Memory leak: ensure proper destruction\n"
        "4. Run with `ASAN_OPTIONS=detect_leaks=1` for more detail"
    ),
}


FIX_RECOMMENDATIONS = [
    "Set `clang_use_chrome_plugins = false` to suppress Clang plugin warnings",
    "Enable `use_jumbo_build = true` to reduce compile time by merging translation units",
    "Set `symbol_level = 0` for faster link times during iteration",
    "Use `is_component_build = true` for faster incremental builds",
    "Set `dcheck_always_on = false` to skip debug assertions in release builds",
    "Increase `-j` parallelism if you have enough RAM (2GB per ninja job)",
    "Enable `blink_symbol_level = 0` to reduce Blink compilation time",
    "Use `treat_warnings_as_errors = false` during development",
    "Enable `fieldtrial_testing_like_official_build = true` for field trial testing",
    "Set `is_official_build = true` for optimized release builds with full LTO",
    "Set `is_clang = true` with `clang_use_chrome_plugins = false` for clear error messages",
    "Enable `enable_nacl = false` to remove PNaCl from the build (deprecated)",
]


class BuildBrain:
    """AI-native build analysis and optimization for Chromium builds."""

    def __init__(self, engine: BuildEngine | None = None,
                 profiles: BuildProfileManager | None = None,
                 patches: PatchManager | None = None):
        self.engine = engine or BuildEngine()
        self.profiles = profiles or BuildProfileManager()
        self.patches = patches or PatchManager()
        self._llm_available = False
        self._init_llm()

    def _init_llm(self) -> None:
        try:
            from orchestra.code_agent.serving.providers import get_provider
            self._provider = get_provider()
            self._llm_available = self._provider is not None
        except Exception:
            self._llm_available = False

    def analyze_errors(self, task_id: str) -> dict:
        task = self.engine.get_task(task_id)
        if not task:
            return {"error": "Task not found"}
        if not task.result:
            return {"analysis": "No build results available", "fixes": []}

        errors = task.result.errors
        if not errors:
            return {"analysis": "No errors found", "fixes": []}

        analyzed = []
        for err in errors:
            matched = None
            for pattern, fix in ERROR_FIXES.items():
                import re
                if re.search(pattern, err, re.IGNORECASE):
                    matched = {"error": err, "suggestion": fix, "matched_pattern": pattern}
                    break
            if not matched:
                matched = {
                    "error": err,
                    "suggestion": "Review the error message and check the affected source file. "
                                   "Search the Chromium bug tracker or code search for similar issues.",
                    "matched_pattern": "unknown",
                }
            analyzed.append(matched)

        return {
            "analysis": f"Found {len(errors)} error(s)",
            "error_count": len(errors),
            "fixes": analyzed,
            "severity": "critical" if any("FAILED" in e for e in errors) else "warning",
        }

    def suggest_optimizations(self, profile_id: str) -> list[dict]:
        profile = self.profiles.get(profile_id)
        if not profile:
            return []

        suggestions = []
        if profile.symbol_level > 1:
            suggestions.append(dict(
                setting="symbol_level",
                current=str(profile.symbol_level),
                recommended="1",
                reason="Reduces link time significantly while keeping useful stack traces",
                savings="~20% link time reduction",
            ))
        if not profile.component_build and profile.build_type.value == "debug":
            suggestions.append(dict(
                setting="is_component_build",
                current="false",
                recommended="true",
                reason="Dramatically faster incremental builds during development",
                savings="~60% incremental build time",
            ))
        if not profile.use_jumbo:
            suggestions.append(dict(
                setting="use_jumbo_build",
                current="false",
                recommended="true",
                reason="Merges translation units + parallel compile, speeds full builds",
                savings="~30% full build time",
            ))
        if profile.treat_warnings_as_errors:
            suggestions.append(dict(
                setting="treat_warnings_as_errors",
                current="true",
                recommended="false",
                reason="Prevents non-critical warnings from blocking development builds",
                savings="Fewer build breaks from warnings",
            ))

        return suggestions

    def get_summary(self) -> dict:
        metrics = self.engine.get_metrics()
        patch_stats = self.patches.get_metrics()
        return {
            "builds": {
                "total": metrics.total_tasks,
                "successful": metrics.successful_builds,
                "failed": metrics.failed_builds,
                "success_rate": metrics.success_rate,
                "active": metrics.active_tasks,
            },
            "patches": {
                "total": patch_stats["total"],
                "applied": patch_stats["applied"],
                "conflict": patch_stats["conflict"],
            },
            "profiles": self.profiles.count(),
            "last_build": metrics.last_build_time,
        }

    def analyze_build_config(self, profile_id: str) -> dict:
        profile = self.profiles.get(profile_id)
        if not profile:
            return {"error": "Profile not found"}
        estimate = self.engine.estimate_build_time(profile)
        optimizations = self.suggest_optimizations(profile_id)
        return {
            "profile": profile.name,
            "platform": profile.platform.value,
            "build_type": profile.build_type.value,
            "estimated_time_min": estimate["estimated_minutes"],
            "estimated_time_s": estimate["estimated_seconds"],
            "optimizations": optimizations,
            "parallelism": self.engine.suggest_parallelism(profile.platform),
        }

    async def llm_analyze(self, prompt: str, context: dict | None = None) -> str:
        if not self._llm_available:
            return self._build_offline_response(prompt, context)
        try:
            resp = await self._provider.chat(messages=[
                {"role": "system", "content": (
                    "You are a Chromium build expert. Answer questions about build "
                    "configuration, error diagnosis, GN args, patch management, and "
                    "build optimization. Be concise and specific."
                )},
                {"role": "user", "content": f"Context: {context or {}}\n\nQuestion: {prompt}"},
            ])
            return resp.get("content", "")
        except Exception as e:
            return self._build_offline_response(prompt, context)

    def _build_offline_response(self, prompt: str, context: dict | None = None) -> str:
        prompt_lower = prompt.lower()
        if "error" in prompt_lower or "fail" in prompt_lower or "broken" in prompt_lower:
            metrics = self.engine.get_metrics()
            return (
                f"There are {metrics.failed_builds} failed build(s) out of "
                f"{metrics.total_tasks} total. The success rate is {metrics.success_rate}%. "
                f"Run 'build analysis' for detailed error diagnosis or check the build logs. "
                f"For common errors like undefined symbols or assertion failures, review "
                f"the relevant BUILD.gn files and ensure all dependencies are properly declared."
            )
        if "optim" in prompt_lower or "speed" in prompt_lower or "fast" in prompt_lower:
            return (
                "Build optimization tips:\n"
                "1. Use `is_component_build = true` for 60% faster incremental builds\n"
                "2. Enable `use_jumbo_build = true` for 30% faster full builds\n"
                "3. Set `symbol_level = 0` during iteration to reduce link times\n"
                "4. Use enough parallelism: `-j$(nproc)` or `-j8` on 16GB+ machines\n"
                "5. Consider `blink_symbol_level = 0` to speed Blink compilation\n"
                "6. Use ccache or sccache for cached compilations"
            )
        if "patch" in prompt_lower:
            stats = self.patches.get_metrics()
            return (
                f"Currently {stats['applied']} of {stats['total']} patches applied. "
                f"{stats['conflict']} patch(es) have conflicts. "
                f"Tags: {', '.join(f'{k}={v}' for k, v in stats['by_tag'].items())}. "
                f"Check individual patches for details."
            )
        if "profile" in prompt_lower or "gn arg" in prompt_lower:
            return (
                f"There are {self.profiles.count()} build profiles configured. "
                f"Platforms: {', '.join(self.profiles.list_platforms())}. "
                f"Types: {', '.join(self.profiles.list_types())}. "
                f"Use 'profile list' to see all available profiles."
            )
        metrics = self.engine.get_metrics()
        return (
            f"Build Orchestrator Status:\n"
            f"- {metrics.total_tasks} total builds ({metrics.successful_builds} successful, "
            f"{metrics.failed_builds} failed)\n"
            f"- Success rate: {metrics.success_rate}%\n"
            f"- Active tasks: {metrics.active_tasks}\n"
            f"- {self.profiles.count()} build profiles\n"
            f"- {self.patches.get_metrics()['total']} patches managed\n"
            f"Type 'build help' for available commands."
        )
