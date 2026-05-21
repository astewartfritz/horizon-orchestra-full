"""Data models for the Orchestra Build Orchestrator."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class BuildStatus(Enum):
    PENDING = "pending"
    CONFIGURING = "configuring"
    BUILDING = "building"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BuildType(Enum):
    DEBUG = "debug"
    RELEASE = "release"
    ASAN = "asan"
    CFI = "cfi"
    TSAN = "tsan"
    MSAN = "msan"
    SIZE = "size"
    COVERAGE = "coverage"


class Platform(Enum):
    WINDOWS = "win"
    LINUX = "linux"
    MAC = "mac"
    ANDROID = "android"
    IOS = "ios"
    CHROMEOS = "chromeos"
    FUCHSIA = "fuchsia"


class PatchStatus(Enum):
    APPLIED = "applied"
    UNAPPLIED = "unapplied"
    CONFLICT = "conflict"
    PARTIAL = "partial"
    OBSOLETE = "obsolete"


@dataclass
class BuildProfile:
    id: str = ""
    name: str = ""
    label: str = ""
    description: str = ""
    platform: Platform = Platform.WINDOWS
    build_type: BuildType = BuildType.DEBUG
    target_cpu: str = "x64"
    gn_args: dict[str, Any] = field(default_factory=dict)
    is_official: bool = False
    symbol_level: int = 1
    component_build: bool = False
    use_jumbo: bool = False
    enable_nacl: bool = False
    enable_rust: bool = True
    ffmpeg_branding: str = "Chrome"
    proprietary_codecs: bool = True
    treat_warnings_as_errors: bool = False
    extra_gn_flags: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.label:
            self.label = self.name

    @property
    def gn_arg_string(self) -> str:
        args = dict(self.gn_args)
        args["is_debug"] = str(self.build_type == BuildType.DEBUG).lower()
        args["is_official_build"] = str(self.is_official).lower()
        args["symbol_level"] = str(self.symbol_level)
        args["is_component_build"] = str(self.component_build).lower()
        args["use_jumbo_build"] = str(self.use_jumbo).lower()
        args["target_cpu"] = f'"{self.target_cpu}"'
        args["enable_nacl"] = str(self.enable_nacl).lower()
        args["enable_rust"] = str(self.enable_rust).lower()
        args["ffmpeg_branding"] = f'"{self.ffmpeg_branding}"'
        args["proprietary_codecs"] = str(self.proprietary_codecs).lower()
        args["treat_warnings_as_errors"] = str(self.treat_warnings_as_errors).lower()
        lines = [f'  {k}={v}' for k, v in sorted(args.items())]
        return "\n".join(lines) if lines else "  # no custom args"

    @property
    def gn_command(self) -> str:
        return f'gn gen out/{self.id} --args=\"{self.gn_arg_string}\"'

    @property
    def full_label(self) -> str:
        return f"{self.platform.value}-{self.build_type.value}-{self.target_cpu}"


@dataclass
class BuildStep:
    name: str = ""
    command: str = ""
    status: BuildStatus = BuildStatus.PENDING
    start_time: str = ""
    end_time: str = ""
    duration_ms: float = 0.0
    output: str = ""
    exit_code: int = -1

    def __post_init__(self):
        if not self.start_time:
            self.start_time = datetime.now(timezone.utc).isoformat()


@dataclass
class BuildResult:
    binary_paths: list[str] = field(default_factory=list)
    total_size_bytes: int = 0
    build_id: str = ""
    architecture: str = "x64"
    num_object_files: int = 0
    link_time_ms: float = 0.0
    compile_time_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def size_mb(self) -> float:
        return round(self.total_size_bytes / (1024 * 1024), 2)


@dataclass
class BuildMetrics:
    total_tasks: int = 0
    successful_builds: int = 0
    failed_builds: int = 0
    cancelled_builds: int = 0
    avg_build_time_ms: float = 0.0
    total_binary_size_mb: float = 0.0
    total_warnings: int = 0
    total_errors: int = 0
    active_tasks: int = 0
    last_build_time: str = ""

    @property
    def success_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return round(self.successful_builds / self.total_tasks * 100, 1)


@dataclass
class BuildTask:
    id: str = ""
    profile_id: str = ""
    profile_name: str = ""
    platform: Platform = Platform.WINDOWS
    build_type: BuildType = BuildType.DEBUG
    status: BuildStatus = BuildStatus.PENDING
    steps: list[BuildStep] = field(default_factory=list)
    result: BuildResult | None = None
    start_time: str = ""
    end_time: str = ""
    duration_ms: float = 0.0
    triggered_by: str = "manual"
    commit_sha: str = ""
    branch: str = "main"
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.start_time:
            self.start_time = datetime.now(timezone.utc).isoformat()

    @property
    def is_running(self) -> bool:
        return self.status in (BuildStatus.CONFIGURING, BuildStatus.BUILDING)

    @property
    def is_terminal(self) -> bool:
        return self.status in (BuildStatus.COMPLETED, BuildStatus.FAILED, BuildStatus.CANCELLED)

    @property
    def current_step(self) -> str:
        for step in reversed(self.steps):
            if step.status == BuildStatus.BUILDING:
                return step.name
        return "idle"

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def completed_steps(self) -> int:
        return sum(1 for s in self.steps if s.status == BuildStatus.COMPLETED)

    @property
    def progress_pct(self) -> float:
        if not self.steps:
            return 0.0
        return round(self.completed_steps / len(self.steps) * 100, 1)


@dataclass
class Patch:
    id: str = ""
    name: str = ""
    description: str = ""
    author: str = ""
    target_dir: str = ""
    content: str = ""
    source_path: str = ""
    status: PatchStatus = PatchStatus.UNAPPLIED
    applies_to: list[str] = field(default_factory=list)
    created_at: str = ""
    applied_at: str = ""
    conflict_details: str = ""
    tags: list[str] = field(default_factory=list)
    version: int = 1

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    @property
    def is_applied(self) -> bool:
        return self.status == PatchStatus.APPLIED
