from __future__ import annotations

from fastapi import FastAPI, HTTPException


def register_skills_routes(app: FastAPI) -> None:
    @app.get("/api/skillsv2/stats")
    async def skillsv2_stats():
        from orchestra.code_agent.skills.v2 import SkillManagerV2, CreditStore, EvalStore
        try:
            mgr = SkillManagerV2()
            stats = mgr.stats()
            cs = CreditStore()
            ev = EvalStore()
            result = {"library": stats.get("library", stats)}
            try:
                result["credit_curve"] = cs.curve_data()
            except Exception:
                result["credit_curve"] = {"steps": []}
            try:
                result["comparison"] = ev.comparison()
            except Exception:
                result["comparison"] = []
            return result
        except Exception as e:
            import traceback; traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/skillsv2/list")
    async def skillsv2_list(limit: int = 50):
        from orchestra.code_agent.skills.v2 import SkillManagerV2
        mgr = SkillManagerV2()
        try:
            skills = mgr.library.list_all(limit=limit)
            return {"skills": [s.to_dict() for s in skills]}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/skillsv2/skill/{skill_id}")
    async def skillsv2_get(skill_id: int):
        from orchestra.code_agent.skills.v2 import SkillManagerV2
        mgr = SkillManagerV2()
        try:
            s = mgr.library.get(skill_id)
            if not s:
                raise HTTPException(status_code=404, detail="Skill not found")
            return {"skill": s.to_dict()}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/skillsv2/prune")
    async def skillsv2_prune():
        from orchestra.code_agent.skills.v2 import SkillManagerV2
        mgr = SkillManagerV2()
        removed = mgr.library.prune() if hasattr(mgr.library, 'prune') else 0
        return {"removed": removed, "remaining": mgr.library.count()}

    @app.delete("/api/skillsv2/skill/{skill_id}")
    async def skillsv2_delete(skill_id: int):
        from orchestra.code_agent.skills.v2 import SkillManagerV2
        mgr = SkillManagerV2()
        ok = mgr.library.remove(skill_id)
        return {"removed": ok}

    @app.post("/api/skillsv2/seed")
    async def skillsv2_seed():
        from orchestra.code_agent.skills.seed import seed_library
        count = seed_library()
        return {"seeded": count}
