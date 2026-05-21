"""Tests for the Orchestra Build Orchestrator."""
from __future__ import annotations

import pytest

from orchestra.code_agent.build_orchestrator.models import (
    BuildProfile,
    BuildStatus,
    BuildStep,
    BuildResult,
    BuildTask,
    BuildType,
    Patch,
    PatchStatus,
    Platform,
    BuildMetrics,
)
from orchestra.code_agent.build_orchestrator.profiles import BuildProfileManager
from orchestra.code_agent.build_orchestrator.engine import BuildEngine
from orchestra.code_agent.build_orchestrator.patches import PatchManager


# ── Models ──

class TestBuildProfile:
    def test_auto_id(self):
        p = BuildProfile(name="test")
        assert len(p.id) == 12

    def test_full_label(self):
        p = BuildProfile(name="test", platform=Platform.WINDOWS, build_type=BuildType.DEBUG, target_cpu="x64")
        assert p.full_label == "win-debug-x64"

    def test_gn_arg_string(self):
        p = BuildProfile(name="test", gn_args=dict(custom_flag="true"))
        assert "custom_flag=true" in p.gn_arg_string

    def test_gn_command(self):
        p = BuildProfile(name="test-profile")
        assert "gn gen" in p.gn_command

    def test_official_label(self):
        p = BuildProfile(name="test", is_official=True)
        assert p.full_label


class TestBuildStep:
    def test_auto_timestamp(self):
        s = BuildStep(name="gn gen")
        assert s.start_time


class TestBuildResult:
    def test_size_mb(self):
        r = BuildResult(total_size_bytes=104857600)
        assert r.size_mb == 100.0

    def test_zero_size(self):
        r = BuildResult()
        assert r.size_mb == 0.0


class TestBuildTask:
    def test_auto_id(self):
        t = BuildTask(profile_name="test")
        assert len(t.id) == 12

    def test_is_running(self):
        t = BuildTask(status=BuildStatus.BUILDING)
        assert t.is_running

    def test_not_running(self):
        t = BuildTask(status=BuildStatus.COMPLETED)
        assert not t.is_running

    def test_is_terminal_completed(self):
        assert BuildTask(status=BuildStatus.COMPLETED).is_terminal

    def test_is_terminal_failed(self):
        assert BuildTask(status=BuildStatus.FAILED).is_terminal

    def test_not_terminal(self):
        assert not BuildTask(status=BuildStatus.PENDING).is_terminal

    def test_progress_empty(self):
        t = BuildTask()
        assert t.progress_pct == 0.0

    def test_progress_some(self):
        t = BuildTask(steps=[
            BuildStep(name="a", status=BuildStatus.COMPLETED),
            BuildStep(name="b", status=BuildStatus.PENDING),
        ])
        assert t.progress_pct == 50.0

    def test_current_step(self):
        t = BuildTask(steps=[
            BuildStep(name="configure", status=BuildStatus.COMPLETED),
            BuildStep(name="build", status=BuildStatus.BUILDING),
        ])
        assert t.current_step == "build"

    def test_current_step_idle(self):
        t = BuildTask()
        assert t.current_step == "idle"


class TestPatch:
    def test_auto_id(self):
        p = Patch(name="test")
        assert len(p.id) == 12

    def test_is_applied(self):
        p = Patch(status=PatchStatus.APPLIED)
        assert p.is_applied

    def test_not_applied(self):
        p = Patch(status=PatchStatus.UNAPPLIED)
        assert not p.is_applied


class TestBuildMetrics:
    def test_success_rate(self):
        m = BuildMetrics(total_tasks=10, successful_builds=7)
        assert m.success_rate == 70.0

    def test_zero_rate(self):
        m = BuildMetrics()
        assert m.success_rate == 0.0


# ── BuildProfileManager ──

class TestBuildProfileManager:
    def test_create(self):
        mgr = BuildProfileManager()
        p = mgr.create("custom", Platform.WINDOWS, BuildType.RELEASE)
        assert mgr.get(p.id) is not None

    def test_get_not_found(self):
        mgr = BuildProfileManager()
        assert mgr.get("nonexistent") is None

    def test_get_by_name(self):
        mgr = BuildProfileManager()
        p = mgr.get_by_name("chromium-debug-win")
        assert p is not None

    def test_get_by_name_not_found(self):
        mgr = BuildProfileManager()
        assert mgr.get_by_name("nonexistent") is None

    def test_update(self):
        mgr = BuildProfileManager()
        pid = list(mgr._profiles.keys())[0]
        assert mgr.update(pid, label="Updated Label")
        assert mgr.get(pid).label == "Updated Label"

    def test_update_not_found(self):
        mgr = BuildProfileManager()
        assert not mgr.update("nonexistent", label="X")

    def test_delete(self):
        mgr = BuildProfileManager()
        pid = list(mgr._profiles.keys())[0]
        assert mgr.delete(pid)
        assert mgr.get(pid) is None

    def test_delete_not_found(self):
        mgr = BuildProfileManager()
        assert not mgr.delete("nonexistent")

    def test_list_filter_platform(self):
        mgr = BuildProfileManager()
        results = mgr.list(platform=Platform.WINDOWS)
        assert all(p.platform == Platform.WINDOWS for p in results)

    def test_list_filter_tag(self):
        mgr = BuildProfileManager()
        results = mgr.list(tag="horizon-frontier")
        assert all("horizon-frontier" in p.tags for p in results)

    def test_list_platforms(self):
        mgr = BuildProfileManager()
        platforms = mgr.list_platforms()
        assert "win" in platforms
        assert "linux" in platforms

    def test_list_types(self):
        mgr = BuildProfileManager()
        types = mgr.list_types()
        assert "debug" in types
        assert "release" in types

    def test_count(self):
        mgr = BuildProfileManager()
        assert mgr.count() > 10

    def test_get_gn_command(self):
        mgr = BuildProfileManager()
        pid = list(mgr._profiles.keys())[0]
        cmd = mgr.get_gn_command(pid)
        assert "gn gen" in cmd

    def test_get_gn_command_not_found(self):
        mgr = BuildProfileManager()
        assert mgr.get_gn_command("nonexistent") == ""

    def test_compare(self):
        mgr = BuildProfileManager()
        ids = list(mgr._profiles.keys())[:2]
        result = mgr.compare(ids[0], ids[1])
        assert "a_only" in result
        assert "b_only" in result
        assert "common" in result

    def test_compare_not_found(self):
        mgr = BuildProfileManager()
        assert mgr.compare("nonexistent", "nope") == {}


# ── BuildEngine ──

class TestBuildEngine:
    def test_create_task(self):
        mgr = BuildProfileManager()
        p = mgr.get_by_name("chromium-debug-win")
        eng = BuildEngine()
        t = eng.create_task(p)
        assert t.id in eng._tasks

    def test_get_task(self):
        eng = BuildEngine()
        tid = list(eng._tasks.keys())[0]
        assert eng.get_task(tid) is not None

    def test_get_task_not_found(self):
        eng = BuildEngine()
        assert eng.get_task("nonexistent") is None

    def test_list_tasks(self):
        eng = BuildEngine()
        tasks = eng.list_tasks()
        assert len(tasks) > 0

    def test_list_tasks_filter_status(self):
        eng = BuildEngine()
        completed = eng.list_tasks(status=BuildStatus.COMPLETED)
        assert all(t.status == BuildStatus.COMPLETED for t in completed)

    def test_cancel_task(self):
        eng = BuildEngine()
        t = eng.create_task(BuildProfile(name="test"))
        assert eng.cancel_task(t.id)
        assert eng.get_task(t.id).status == BuildStatus.CANCELLED

    def test_cancel_not_found(self):
        eng = BuildEngine()
        assert not eng.cancel_task("nonexistent")

    def test_cancel_terminal(self):
        eng = BuildEngine()
        tasks = eng.list_tasks(status=BuildStatus.COMPLETED)
        if tasks:
            assert not eng.cancel_task(tasks[0].id)

    def test_delete_task(self):
        eng = BuildEngine()
        tid = list(eng._tasks.keys())[0]
        assert eng.delete_task(tid)
        assert eng.get_task(tid) is None

    def test_delete_not_found(self):
        eng = BuildEngine()
        assert not eng.delete_task("nonexistent")

    def test_get_metrics(self):
        eng = BuildEngine()
        m = eng.get_metrics()
        assert isinstance(m.total_tasks, int)
        assert m.total_tasks > 0

    def test_parse_build_output_empty(self):
        eng = BuildEngine()
        r = eng.parse_build_output("")
        assert r["errors"] == []
        assert r["warnings"] == []

    def test_parse_build_output_with_errors(self):
        eng = BuildEngine()
        r = eng.parse_build_output("FAILED: obj/base/base/location.o\nerror: undefined symbol")
        assert len(r["errors"]) == 2

    def test_parse_build_output_with_progress(self):
        eng = BuildEngine()
        r = eng.parse_build_output("[123/456] Building stuff")
        assert r["progress"] == {"current": 123, "total": 456}

    def test_estimate_build_time(self):
        eng = BuildEngine()
        p = BuildProfile(name="test", platform=Platform.WINDOWS, build_type=BuildType.RELEASE)
        e = eng.estimate_build_time(p)
        assert e["estimated_ms"] > 0
        assert e["estimated_minutes"] > 0

    def test_suggest_parallelism(self):
        eng = BuildEngine()
        s = eng.suggest_parallelism(Platform.LINUX)
        assert s["recommended_jobs"] > 0

    def test_simulate_build(self):
        mgr = BuildProfileManager()
        p = mgr.get_by_name("chromium-debug-win")
        eng = BuildEngine()
        t = eng.create_task(p)
        result = eng.simulate_build(t.id)
        assert result is not None
        assert result.status == BuildStatus.COMPLETED


# ── PatchManager ──

class TestPatchManager:
    def test_create(self):
        mgr = PatchManager()
        p = mgr.create("my-patch", "chrome/browser", author="Test")
        assert mgr.get(p.id) is not None

    def test_get_not_found(self):
        mgr = PatchManager()
        assert mgr.get("nonexistent") is None

    def test_list(self):
        mgr = PatchManager()
        assert len(mgr.list()) > 0

    def test_list_filter_status(self):
        mgr = PatchManager()
        applied = mgr.list(status=PatchStatus.APPLIED)
        assert all(p.status == PatchStatus.APPLIED for p in applied)

    def test_list_filter_tag(self):
        mgr = PatchManager()
        results = mgr.list(tag="horizon-frontier")
        assert all("horizon-frontier" in p.tags for p in results)

    def test_apply(self):
        mgr = PatchManager()
        unapplied = [p for p in mgr.list() if p.status == PatchStatus.UNAPPLIED]
        if unapplied:
            assert mgr.apply(unapplied[0].id)
            assert mgr.get(unapplied[0].id).is_applied

    def test_apply_already_applied(self):
        mgr = PatchManager()
        applied = [p for p in mgr.list() if p.status == PatchStatus.APPLIED]
        if applied:
            assert not mgr.apply(applied[0].id)

    def test_apply_conflict(self):
        mgr = PatchManager()
        conflict = [p for p in mgr.list() if p.status == PatchStatus.CONFLICT]
        if conflict:
            assert not mgr.apply(conflict[0].id)

    def test_unapply(self):
        mgr = PatchManager()
        applied = [p for p in mgr.list() if p.status == PatchStatus.APPLIED]
        if applied:
            assert mgr.unapply(applied[0].id)
            assert not mgr.get(applied[0].id).is_applied

    def test_unapply_not_found(self):
        mgr = PatchManager()
        assert not mgr.unapply("nonexistent")

    def test_delete(self):
        mgr = PatchManager()
        pid = list(mgr._patches.keys())[0]
        assert mgr.delete(pid)
        assert mgr.get(pid) is None

    def test_delete_not_found(self):
        mgr = PatchManager()
        assert not mgr.delete("nonexistent")

    def test_update(self):
        mgr = PatchManager()
        pid = list(mgr._patches.keys())[0]
        assert mgr.update(pid, description="Updated desc")
        assert mgr.get(pid).version > 1

    def test_update_not_found(self):
        mgr = PatchManager()
        assert not mgr.update("nonexistent", description="X")

    def test_get_metrics(self):
        mgr = PatchManager()
        m = mgr.get_metrics()
        assert "total" in m
        assert "applied" in m
        assert "by_tag" in m

    def test_detect_conflicts(self):
        mgr = PatchManager()
        tids = list(mgr._patches.keys())[:3]
        conflicts = mgr.detect_conflicts(tids)
        assert isinstance(conflicts, list)
