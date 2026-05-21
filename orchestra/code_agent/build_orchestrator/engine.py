"""Build engine — build execution, monitoring, and output parsing."""
from __future__ import annotations

import random
import re
import time
from datetime import datetime, timezone
from typing import Any

from orchestra.code_agent.build_orchestrator.models import (
    BuildMetrics,
    BuildProfile,
    BuildResult,
    BuildStatus,
    BuildStep,
    BuildTask,
    BuildType,
    Platform,
)


PREGENERATED_TASKS: list[dict] = [
    dict(profile_name="chromium-debug-win", platform=Platform.WINDOWS, build_type=BuildType.DEBUG,
         status=BuildStatus.COMPLETED, duration_ms=2854000, steps=5,
         result=dict(binary_paths=["out/chromium-debug-win/chrome.exe",
                                    "out/chromium-debug-win/chrome.dll"],
                      total_size_bytes=324000000, num_object_files=185000, compile_time_ms=2340000,
                      link_time_ms=514000),
         warnings=32, errors=0),
    dict(profile_name="chromium-debug-linux", platform=Platform.LINUX, build_type=BuildType.DEBUG,
         status=BuildStatus.COMPLETED, duration_ms=3120000, steps=5,
         result=dict(binary_paths=["out/chromium-debug-linux/chrome",
                                    "out/chromium-debug-linux/libchrome.so"],
                      total_size_bytes=418000000, num_object_files=198000, compile_time_ms=2580000,
                      link_time_ms=540000),
         warnings=28, errors=0),
    dict(profile_name="chromium-asan", platform=Platform.LINUX, build_type=BuildType.ASAN,
         status=BuildStatus.FAILED, duration_ms=1245000, steps=4,
         result=dict(binary_paths=[], total_size_bytes=0, errors=[
             "FAILED: obj/base/base/task_scheduler_impl.o",
             "error: 'std::unique_ptr' in asan mode requires -fsanitize=vptr",
         ]),
         warnings=5, errors=2),
    dict(profile_name="chromium-release-win", platform=Platform.WINDOWS, build_type=BuildType.RELEASE,
         status=BuildStatus.COMPLETED, duration_ms=8950000, steps=5,
         result=dict(binary_paths=["out/chromium-release-win/chrome.exe"],
                      total_size_bytes=89200000, num_object_files=310000, compile_time_ms=7400000,
                      link_time_ms=1550000),
         warnings=12, errors=0),
    dict(profile_name="horizon-frontier-dev", platform=Platform.WINDOWS, build_type=BuildType.DEBUG,
         status=BuildStatus.PENDING, duration_ms=0, steps=0),
    dict(profile_name="chromium-debug-android", platform=Platform.ANDROID, build_type=BuildType.DEBUG,
         status=BuildStatus.FAILED, duration_ms=4560000, steps=4,
         result=dict(binary_paths=[], total_size_bytes=0, errors=[
             "ERROR at //build/config/android/config.gni:123: Assertion failed.",
             "android_sdk_root not set. Set target_os=\"android\" and provide android_sdk_root.",
         ]),
         warnings=15, errors=1),
    dict(profile_name="chromium-debug-mac", platform=Platform.MAC, build_type=BuildType.DEBUG,
         status=BuildStatus.COMPLETED, duration_ms=3560000, steps=5,
         result=dict(binary_paths=["out/chromium-debug-mac/Chromium.app/Contents/MacOS/Chromium"],
                      total_size_bytes=456000000, num_object_files=175000, compile_time_ms=2900000,
                      link_time_ms=660000),
         warnings=22, errors=0),
]


STEPS_TEMPLATE = [
    ("depot_tools sync", "gclient sync --with_branch_heads"),
    ("gn gen", "gn gen out/{profile_id}"),
    ("gn args check", "gn args out/{profile_id} --list"),
    ("ninja build", "ninja -C out/{profile_id} -j$(nproc) chrome"),
    ("build verify", "ninja -C out/{profile_id} -j$(nproc) chrome_public_apk"),
]

STEPS_SHORT = [
    ("depot_tools sync", "gclient sync --with_branch_heads"),
    ("gn gen", "gn gen out/{profile_id}"),
    ("ninja build", "ninja -C out/{profile_id} chrome"),
    ("build verify", "verify build output"),
]


SAMPLE_ERRORS = [
    "FAILED: obj/base/base/location.o",
    "error: undefined symbol: base::debug::SetCrashKeyString",
    "ERROR at //build/config/compiler/BUILD.gn:142:19: Assertion failed.",
    "FAILED: obj/third_party/blink/renderer/core/core/event_target.o",
    "In file included from ../../base/task/thread_pool/task_scheduler_impl.cc:5:",
    "fatal error: 'base/atomicops.h' file not found",
    "ld.lld: error: undefined symbol: v8::internal::compiler::Select",
    "FAILED: obj/v8/v8_compiler/code-generator.o",
    "ninja: build stopped: subcommand failed.",
    "ERROR: Unable to find the Android SDK. Set android_sdk_root in GN args.",
]

SAMPLE_WARNINGS = [
    "warning: 'RegisterClass' was hidden by 'RegisterClassA'",
    "warning: non-virtual destructor might cause undefined behavior",
    "clang: warning: argument unused during compilation: '-mcrc32'",
    "warning: implicit conversion loses integer precision",
    "warning: unused parameter 'callback'",
    "warning: 'override' keyword missing",
    "warning: deprecated declaration",
    "warning: declaration shadows a local variable",
    "warning: suggest braces around initialization of subobject",
    "warning: redundant move in return statement",
]


class BuildEngine:
    """Manages Chromium build lifecycle — create, execute, monitor, and analyze builds."""

    def __init__(self):
        self._tasks: dict[str, BuildTask] = {}
        self._seed_pregenerated()

    def _seed_pregenerated(self):
        for data in PREGENERATED_TASKS:
            task = BuildTask(**{k: v for k, v in data.items() if k != "result" and k != "steps" and k != "warnings" and k != "errors"})
            if data.get("steps", 0) > 0:
                self._build_steps_for(task, data["steps"])
                task.status = data["status"]
            if data["status"] == BuildStatus.COMPLETED:
                task.result = BuildResult(
                    errors=[],
                    warnings=[random.choice(SAMPLE_WARNINGS) for _ in range(data.get("warnings", 0))],
                    **data["result"],
                )
            elif data["status"] == BuildStatus.FAILED:
                res_data = data.get("result", {})
                task.result = BuildResult(
                    warnings=[random.choice(SAMPLE_WARNINGS) for _ in range(data.get("warnings", 0))],
                    **res_data,
                )
            task.end_time = datetime.now(timezone.utc).isoformat()
            self._tasks[task.id] = task

    def _build_steps_for(self, task: BuildTask, count: int):
        steps = STEPS_SHORT if count <= 4 else STEPS_TEMPLATE
        for i, (name, cmd) in enumerate(steps[:count]):
            step = BuildStep(
                name=name,
                command=cmd.format(profile_id=task.profile_name or task.profile_id),
                status=BuildStatus.COMPLETED,
            )
            task.steps.append(step)
        if task.steps:
            task.steps[-1].status = task.status

    def create_task(self, profile: BuildProfile, triggered_by: str = "manual",
                    branch: str = "main", commit_sha: str = "", notes: str = "",
                    tags: list[str] | None = None) -> BuildTask:
        task = BuildTask(
            profile_id=profile.id,
            profile_name=profile.name,
            platform=profile.platform,
            build_type=profile.build_type,
            triggered_by=triggered_by,
            branch=branch,
            commit_sha=commit_sha or "",
            notes=notes,
            tags=tags or [],
        )
        for name, cmd in STEPS_TEMPLATE:
            step = BuildStep(
                name=name,
                command=cmd.format(profile_id=profile.name or profile.id),
            )
            task.steps.append(step)
        self._tasks[task.id] = task
        return task

    def get_task(self, task_id: str) -> BuildTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self, status: BuildStatus | None = None,
                   profile_name: str | None = None,
                   platform: Platform | None = None,
                   limit: int = 50) -> list[BuildTask]:
        results = list(self._tasks.values())
        if status:
            results = [t for t in results if t.status == status]
        if profile_name:
            results = [t for t in results if t.profile_name == profile_name]
        if platform:
            results = [t for t in results if t.platform == platform]
        results.sort(key=lambda t: t.start_time, reverse=True)
        return results[:limit]

    def cancel_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task or task.is_terminal:
            return False
        task.status = BuildStatus.CANCELLED
        task.end_time = datetime.now(timezone.utc).isoformat()
        return True

    def delete_task(self, task_id: str) -> bool:
        if task_id not in self._tasks:
            return False
        del self._tasks[task_id]
        return True

    def get_metrics(self) -> BuildMetrics:
        tasks = list(self._tasks.values())
        completed_tasks = [t for t in tasks if t.status == BuildStatus.COMPLETED]
        failed_tasks = [t for t in tasks if t.status == BuildStatus.FAILED]
        cancelled_tasks = [t for t in tasks if t.status == BuildStatus.CANCELLED]
        active = [t for t in tasks if t.is_running]

        avg_time = 0.0
        total_size = 0.0
        total_warnings = 0
        total_errors = 0
        last_build = ""

        for t in completed_tasks:
            avg_time += t.duration_ms
            if t.result:
                total_size += t.result.size_mb
                total_warnings += len(t.result.warnings)
                total_errors += len(t.result.errors)
            if t.end_time > last_build:
                last_build = t.end_time

        if completed_tasks:
            avg_time /= len(completed_tasks)

        return BuildMetrics(
            total_tasks=len(tasks),
            successful_builds=len(completed_tasks),
            failed_builds=len(failed_tasks),
            cancelled_builds=len(cancelled_tasks),
            avg_build_time_ms=round(avg_time, 1),
            total_binary_size_mb=round(total_size, 2),
            total_warnings=total_warnings,
            total_errors=total_errors,
            active_tasks=len(active),
            last_build_time=last_build,
        )

    def simulate_build(self, task_id: str) -> BuildTask | None:
        """Simulate running a build — transitions steps through building->completed/failed."""
        task = self._tasks.get(task_id)
        if not task or task.is_terminal:
            return task
        task.status = BuildStatus.CONFIGURING
        for i, step in enumerate(task.steps):
            step.status = BuildStatus.BUILDING
            step.start_time = datetime.now(timezone.utc).isoformat()
            time.sleep(0.05)
            if i == len(task.steps) - 1:
                step.status = BuildStatus.COMPLETED
                step.exit_code = 0
            else:
                step.status = BuildStatus.COMPLETED
                step.exit_code = 0
            step.end_time = datetime.now(timezone.utc).isoformat()
        task.status = BuildStatus.COMPLETED
        task.end_time = datetime.now(timezone.utc).isoformat()
        task.result = BuildResult(
            binary_paths=[f"out/{task.profile_name}/chrome.exe"],
            total_size_bytes=random.randint(80000000, 500000000),
            build_id=task.id,
            compile_time_ms=round(random.uniform(200000, 8000000), 1),
            link_time_ms=round(random.uniform(30000, 1500000), 1),
            warnings=[random.choice(SAMPLE_WARNINGS) for _ in range(random.randint(5, 40))],
        )
        return task

    def parse_build_output(self, output: str) -> dict:
        errors = re.findall(r'(?:FAILED|ERROR|error):\s*(.*?)(?:\n|$)', output)
        warnings = re.findall(r'(?:warning):\s*(.*?)(?:\n|$)', output, re.IGNORECASE)
        progress = re.findall(r'\[(\d+)/(\d+)\]', output)
        current = int(progress[-1][0]) if progress else 0
        total = int(progress[-1][1]) if progress else 0
        link_errors = [e for e in errors if "ld.lld" in e or "LINK" in e]
        compile_errors = [e for e in errors if all(x not in e for x in ["ld.lld", "LINK"])]
        return {
            "errors": errors,
            "warnings": warnings,
            "compile_errors": compile_errors,
            "link_errors": link_errors,
            "progress": {"current": current, "total": total} if total > 0 else None,
            "error_count": len(errors),
            "warning_count": len(warnings),
        }

    def estimate_build_time(self, profile: BuildProfile) -> dict:
        base = {
            Platform.WINDOWS: 2400000,
            Platform.LINUX: 2100000,
            Platform.MAC: 3000000,
            Platform.ANDROID: 4500000,
            Platform.IOS: 5000000,
        }.get(profile.platform, 3000000)
        if profile.component_build:
            base = int(base * 0.4)
        if profile.use_jumbo:
            base = int(base * 0.7)
        if profile.is_official:
            base = int(base * 1.8)
        if profile.symbol_level > 1:
            base = int(base * 1.3)
        return {
            "estimated_ms": base,
            "estimated_seconds": round(base / 1000, 1),
            "estimated_minutes": round(base / 60000, 1),
            "factors": {
                "base": base,
                "component_build_discount": 0.4 if profile.component_build else 1.0,
                "jumbo_discount": 0.7 if profile.use_jumbo else 1.0,
                "official_penalty": 1.8 if profile.is_official else 1.0,
                "symbol_penalty": 1.3 if profile.symbol_level > 1 else 1.0,
            },
        }

    def suggest_parallelism(self, platform: Platform) -> dict:
        jobs = {
            Platform.WINDOWS: 8,
            Platform.LINUX: 16,
            Platform.MAC: 10,
            Platform.ANDROID: 8,
        }.get(platform, 8)
        return {
            "recommended_jobs": jobs,
            "low_memory_jobs": max(2, jobs // 4),
            "high_perf_jobs": jobs * 2,
            "ram_per_job_mb": 2048,
        }
