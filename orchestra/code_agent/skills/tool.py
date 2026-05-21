from orchestra.code_agent.tools.base import Tool, ToolSpec, ToolResult


class SkillTool(Tool):
    def __init__(self, manager):
        self._manager = manager
        super().__init__()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="skill",
            description="Search the skill library for reusable procedures.",
            parameters={
                "action": {"type": "string", "enum": ["search", "list", "get"], "description": "Action to perform"},
                "query": {"type": "string", "description": "Search query"},
                "skill_id": {"type": "integer", "description": "Skill ID to retrieve"},
            },
        )

    async def run(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "list")
        if action == "search":
            query = kwargs.get("query", "")
            if not query:
                return ToolResult(error="query required")
            skills = await self._manager.retrieve(query, top_k=5)
            if not skills:
                return ToolResult(output="No matching skills found.")
            lines = ["Matching skills:"] + [f"  [{s.id}] {s.body[:100]}" for s in skills]
            return ToolResult(output="\n".join(lines))
        elif action == "get":
            sid = kwargs.get("skill_id", 0)
            s = self._manager.library.get(sid)
            if not s:
                return ToolResult(error=f"Skill #{sid} not found")
            return ToolResult(output=f"# Skill {s.id}\n\n{s.body}")
        else:
            skills = self._manager.library.list_all(limit=20)
            if not skills:
                return ToolResult(output="Skill library is empty.")
            lines = ["Available skills:"] + [f"  [{s.id}] {s.body[:80]} (used {s.usage_count}x)" for s in skills]
            return ToolResult(output="\n".join(lines))
