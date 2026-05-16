"""API routes for the Orchestra Build Orchestrator."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from code_agent.build_orchestrator.engine import BuildEngine
from code_agent.build_orchestrator.models import BuildType, PatchStatus, Platform
from code_agent.build_orchestrator.patches import PatchManager
from code_agent.build_orchestrator.profiles import BuildProfileManager
from code_agent.build_orchestrator.brain import BuildBrain


def register_build_routes(app: Any, prefix: str = "/api/build") -> None:
    profiles = BuildProfileManager()
    engine = BuildEngine()
    patches = PatchManager()
    brain = BuildBrain(engine, profiles, patches)
    router = APIRouter(prefix=prefix)

    # ── Health ──
    @router.get("/health")
    async def health():
        return {"status": "ok", "service": "orchestra-build"}

    # ── Build Profiles ──
    @router.get("/profiles")
    async def list_profiles(platform: str | None = None,
                            build_type: str | None = None,
                            tag: str | None = None):
        pf = Platform(platform) if platform else None
        bt = BuildType(build_type) if build_type else None
        results = profiles.list(platform=pf, build_type=bt, tag=tag)
        return {p.id: {"name": p.name, "label": p.label, "platform": p.platform.value,
                        "build_type": p.build_type.value, "target_cpu": p.target_cpu,
                        "is_official": p.is_official, "tags": p.tags,
                        "full_label": p.full_label}
                for p in results}

    @router.get("/profiles/{profile_id}")
    async def get_profile(profile_id: str):
        p = profiles.get(profile_id)
        if not p:
            raise HTTPException(status_code=404, detail="Profile not found")
        return {
            "id": p.id, "name": p.name, "label": p.label, "description": p.description,
            "platform": p.platform.value, "build_type": p.build_type.value,
            "target_cpu": p.target_cpu, "gn_args": p.gn_args, "is_official": p.is_official,
            "symbol_level": p.symbol_level, "component_build": p.component_build,
            "use_jumbo": p.use_jumbo, "tags": p.tags,
            "gn_command": p.gn_command, "gn_arg_string": p.gn_arg_string,
        }

    @router.post("/profiles")
    async def create_profile(body: dict[str, Any]):
        name = body.get("name", "")
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        platform = Platform(body.get("platform", "win"))
        build_type = BuildType(body.get("build_type", "debug"))
        p = profiles.create(name=name, platform=platform, build_type=build_type,
                            target_cpu=body.get("target_cpu", "x64"),
                            gn_args=body.get("gn_args", {}),
                            tags=body.get("tags", []),
                            **{k: v for k, v in body.items()
                               if k not in ("name", "platform", "build_type", "target_cpu", "gn_args", "tags")})
        return {"id": p.id, "name": p.name, "full_label": p.full_label}

    @router.put("/profiles/{profile_id}")
    async def update_profile(profile_id: str, body: dict[str, Any]):
        ok = profiles.update(profile_id, **body)
        if not ok:
            raise HTTPException(status_code=404, detail="Profile not found")
        return {"status": "updated"}

    @router.delete("/profiles/{profile_id}")
    async def delete_profile(profile_id: str):
        ok = profiles.delete(profile_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Profile not found")
        return {"status": "deleted"}

    @router.get("/profiles/{profile_id}/gn-command")
    async def profile_gn_command(profile_id: str):
        cmd = profiles.get_gn_command(profile_id)
        if not cmd:
            raise HTTPException(status_code=404, detail="Profile not found")
        return {"command": cmd}

    @router.get("/profiles/{profile_id}/estimate")
    async def profile_estimate(profile_id: str):
        p = profiles.get(profile_id)
        if not p:
            raise HTTPException(status_code=404, detail="Profile not found")
        return engine.estimate_build_time(p)

    @router.get("/profiles/{profile_id}/optimize")
    async def profile_optimize(profile_id: str):
        return {"suggestions": brain.suggest_optimizations(profile_id)}

    @router.get("/profiles/{profile_id}/analyze")
    async def profile_analyze(profile_id: str):
        return brain.analyze_build_config(profile_id)

    @router.post("/profiles/compare")
    async def compare_profiles(body: dict[str, Any]):
        return profiles.compare(body.get("id_a", ""), body.get("id_b", ""))

    # ── Build Tasks ──
    @router.get("/tasks")
    async def list_tasks(status: str | None = None,
                         profile: str | None = None,
                         platform: str | None = None,
                         limit: int = 50):
        st = None
        if status:
            try:
                from code_agent.build_orchestrator.models import BuildStatus
                st = BuildStatus(status)
            except ValueError:
                pass
        pf = Platform(platform) if platform else None
        results = engine.list_tasks(status=st, profile_name=profile,
                                    platform=pf, limit=limit)
        return {t.id: {
            "profile_name": t.profile_name, "platform": t.platform.value,
            "build_type": t.build_type.value, "status": t.status.value,
            "progress_pct": t.progress_pct, "duration_ms": t.duration_ms,
            "current_step": t.current_step, "triggered_by": t.triggered_by,
            "start_time": t.start_time, "end_time": t.end_time,
        } for t in results}

    @router.get("/tasks/{task_id}")
    async def get_task(task_id: str):
        t = engine.get_task(task_id)
        if not t:
            raise HTTPException(status_code=404, detail="Task not found")
        return {
            "id": t.id, "profile_id": t.profile_id, "profile_name": t.profile_name,
            "platform": t.platform.value, "build_type": t.build_type.value,
            "status": t.status.value, "triggered_by": t.triggered_by,
            "branch": t.branch, "commit_sha": t.commit_sha,
            "start_time": t.start_time, "end_time": t.end_time,
            "duration_ms": t.duration_ms, "progress_pct": t.progress_pct,
            "completed_steps": t.completed_steps, "total_steps": t.total_steps,
            "current_step": t.current_step, "notes": t.notes,
            "steps": [{"name": s.name, "command": s.command, "status": s.status.value,
                        "duration_ms": s.duration_ms, "exit_code": s.exit_code}
                      for s in t.steps],
            "result": {
                "binary_paths": t.result.binary_paths if t.result else [],
                "size_mb": t.result.size_mb if t.result else 0,
                "errors": t.result.errors if t.result else [],
                "warnings": t.result.warnings if t.result else [],
            } if t.result else None,
        }

    @router.post("/tasks")
    async def create_task(body: dict[str, Any]):
        pid = body.get("profile_id", "")
        profile = profiles.get(pid)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        task = engine.create_task(
            profile=profile,
            triggered_by=body.get("triggered_by", "manual"),
            branch=body.get("branch", "main"),
            commit_sha=body.get("commit_sha", ""),
            notes=body.get("notes", ""),
            tags=body.get("tags", []),
        )
        return {"id": task.id, "profile_name": task.profile_name,
                "status": task.status.value, "total_steps": task.total_steps}

    @router.post("/tasks/{task_id}/build")
    async def run_build(task_id: str):
        t = engine.get_task(task_id)
        if not t:
            raise HTTPException(status_code=404, detail="Task not found")
        if t.is_running:
            raise HTTPException(status_code=400, detail="Build already running")
        task = engine.simulate_build(task_id)
        return {
            "id": task.id, "status": task.status.value,
            "duration_ms": task.duration_ms,
            "result": {
                "size_mb": task.result.size_mb if task.result else 0,
                "warnings": len(task.result.warnings) if task.result else 0,
            } if task.result else None,
        }

    @router.post("/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str):
        ok = engine.cancel_task(task_id)
        if not ok:
            raise HTTPException(status_code=400, detail="Cannot cancel (not running or not found)")
        return {"status": "cancelled"}

    @router.delete("/tasks/{task_id}")
    async def delete_task(task_id: str):
        ok = engine.delete_task(task_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"status": "deleted"}

    @router.get("/tasks/{task_id}/analyze")
    async def analyze_task(task_id: str):
        return brain.analyze_errors(task_id)

    @router.get("/tasks/{task_id}/output")
    async def task_output(task_id: str):
        t = engine.get_task(task_id)
        if not t:
            raise HTTPException(status_code=404, detail="Task not found")
        output = ""
        for s in t.steps:
            output += f"[{s.status.value}] {s.name}: {s.command}\n"
        if t.result:
            for e in t.result.errors:
                output += f"ERROR: {e}\n"
            for w in t.result.warnings:
                output += f"WARNING: {w}\n"
        return {"output": output[:5000]}

    # ── Patches ──
    @router.get("/patches")
    async def list_patches(status: str | None = None, tag: str | None = None):
        st = PatchStatus(status) if status else None
        results = patches.list(status=st, tag=tag)
        return {p.id: {"name": p.name, "target_dir": p.target_dir,
                        "status": p.status.value, "author": p.author,
                        "tags": p.tags, "version": p.version,
                        "is_applied": p.is_applied}
                for p in results}

    @router.get("/patches/{patch_id}")
    async def get_patch(patch_id: str):
        p = patches.get(patch_id)
        if not p:
            raise HTTPException(status_code=404, detail="Patch not found")
        return {
            "id": p.id, "name": p.name, "description": p.description,
            "author": p.author, "target_dir": p.target_dir,
            "status": p.status.value, "tags": p.tags,
            "version": p.version, "is_applied": p.is_applied,
            "created_at": p.created_at, "applied_at": p.applied_at,
            "conflict_details": p.conflict_details,
            "source_path": p.source_path,
        }

    @router.post("/patches")
    async def create_patch(body: dict[str, Any]):
        p = patches.create(
            name=body.get("name", ""),
            target_dir=body.get("target_dir", ""),
            description=body.get("description", ""),
            author=body.get("author", ""),
            content=body.get("content", ""),
            source_path=body.get("source_path", ""),
            tags=body.get("tags", []),
        )
        return {"id": p.id, "name": p.name, "status": p.status.value}

    @router.post("/patches/{patch_id}/apply")
    async def apply_patch(patch_id: str):
        ok = patches.apply(patch_id)
        if not ok:
            raise HTTPException(status_code=400, detail="Cannot apply (already applied, has conflicts, or not found)")
        return {"status": "applied"}

    @router.post("/patches/{patch_id}/unapply")
    async def unapply_patch(patch_id: str):
        ok = patches.unapply(patch_id)
        if not ok:
            raise HTTPException(status_code=400, detail="Cannot unapply (not applied or not found)")
        return {"status": "unapplied"}

    @router.put("/patches/{patch_id}")
    async def update_patch(patch_id: str, body: dict[str, Any]):
        ok = patches.update(patch_id, **{k: v for k, v in body.items() if k != "id"})
        if not ok:
            raise HTTPException(status_code=404, detail="Patch not found")
        return {"status": "updated"}

    @router.delete("/patches/{patch_id}")
    async def delete_patch(patch_id: str):
        ok = patches.delete(patch_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Patch not found")
        return {"status": "deleted"}

    @router.get("/patches/conflicts")
    async def detect_conflicts(target: str = ""):
        tids = [x.strip() for x in target.split(",") if x.strip()]
        if not tids:
            tids = [p.id for p in patches.list()]
        return {"conflicts": patches.detect_conflicts(tids)}

    # ── Build Brain ──
    @router.get("/brain/summary")
    async def brain_summary():
        return brain.get_summary()

    @router.post("/brain/query")
    async def ai_query(body: dict[str, Any]):
        prompt = body.get("prompt", "")
        context = body.get("context")
        result = await brain.llm_analyze(prompt=prompt, context=context)
        return {"response": result}

    @router.get("/brain/parallelism")
    async def parallelism(platform: str = "win"):
        pf = Platform(platform) if platform else Platform.WINDOWS
        return engine.suggest_parallelism(pf)

    @router.get("/brain/fixes")
    async def known_fixes():
        from code_agent.build_orchestrator.brain import ERROR_FIXES
        return {"patterns": list(ERROR_FIXES.keys())}

    # ── Metrics ──
    @router.get("/metrics")
    async def metrics():
        m = engine.get_metrics()
        return {
            "total_tasks": m.total_tasks,
            "successful_builds": m.successful_builds,
            "failed_builds": m.failed_builds,
            "cancelled_builds": m.cancelled_builds,
            "success_rate": m.success_rate,
            "avg_build_time_ms": m.avg_build_time_ms,
            "active_tasks": m.active_tasks,
            "total_binary_size_mb": m.total_binary_size_mb,
            "total_warnings": m.total_warnings,
            "total_errors": m.total_errors,
            "last_build_time": m.last_build_time,
            "profile_count": profiles.count(),
            "patches_applied": patches.get_metrics()["applied"],
            "patches_total": patches.get_metrics()["total"],
        }

    # ── Platforms and Types ──
    @router.get("/platforms")
    async def list_platforms():
        return {"platforms": profiles.list_platforms()}

    @router.get("/types")
    async def list_types():
        return {"types": profiles.list_types()}

    app.include_router(router)
