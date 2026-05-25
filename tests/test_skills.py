"""Tests for orchestra/skills/base.py and orchestra/skills/validation.py.

Covers:
  - Skill ABC enforcement (can't instantiate without implementing abstracts)
  - SkillRegistry: register, get, list_skills, register_tools injection
  - run_code_in_sandbox: happy path, timeout, non-JSON stdout
  - DataValidationSkill: dispatch, all error-input paths, get_tool_definitions
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestra.skills.base import Skill, SkillRegistry, run_code_in_sandbox
from orchestra.skills.validation import DataValidationSkill
from orchestra.agent_loop import ToolRegistry


# ---------------------------------------------------------------------------
# Concrete Skill for testing
# ---------------------------------------------------------------------------

class EchoSkill(Skill):
    name = "echo_skill"
    description = "Echo skill for tests"

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "echo_skill",
                    "description": "Echo params",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                        },
                        "required": ["text"],
                    },
                },
            }
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"echoed": params.get("text", ""), "action": action}


class ErrorSkill(Skill):
    name = "error_skill"
    description = "Always raises"

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return []

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("error skill always fails")


# ---------------------------------------------------------------------------
# Skill ABC enforcement
# ---------------------------------------------------------------------------

class TestSkillABC:
    def test_cannot_instantiate_abstract_skill(self):
        with pytest.raises(TypeError):
            Skill()  # type: ignore[abstract]

    def test_concrete_skill_instantiates(self):
        s = EchoSkill()
        assert s.name == "echo_skill"
        assert s.description == "Echo skill for tests"


# ---------------------------------------------------------------------------
# SkillRegistry
# ---------------------------------------------------------------------------

class TestSkillRegistry:
    def test_register_and_get(self):
        reg = SkillRegistry()
        skill = EchoSkill()
        reg.register(skill)
        retrieved = reg.get("echo_skill")
        assert retrieved is skill

    def test_get_unknown_returns_none(self):
        reg = SkillRegistry()
        assert reg.get("nonexistent") is None

    def test_list_skills(self):
        reg = SkillRegistry()
        reg.register(EchoSkill())
        skills = reg.list_skills()
        assert len(skills) == 1
        assert skills[0]["name"] == "echo_skill"
        assert skills[0]["description"] == "Echo skill for tests"

    def test_register_multiple_skills(self):
        reg = SkillRegistry()
        reg.register(EchoSkill())
        reg.register(DataValidationSkill())
        assert reg.get("echo_skill") is not None
        assert reg.get("data_validation") is not None
        assert len(reg.list_skills()) == 2

    def test_register_tools_injects_into_tool_registry(self):
        skill_reg = SkillRegistry()
        skill_reg.register(EchoSkill())

        tool_reg = ToolRegistry()
        skill_reg.register_tools(tool_reg)

        assert "echo_skill" in tool_reg.names

    def test_register_tools_skips_empty_tool_definitions(self):
        skill_reg = SkillRegistry()
        skill_reg.register(ErrorSkill())  # get_tool_definitions() returns []

        tool_reg = ToolRegistry()
        skill_reg.register_tools(tool_reg)
        # ErrorSkill has no tool definitions, so nothing should be injected
        assert len(tool_reg.names) == 0

    @pytest.mark.asyncio
    async def test_injected_tool_calls_skill_execute(self):
        skill_reg = SkillRegistry()
        skill_reg.register(EchoSkill())

        tool_reg = ToolRegistry()
        skill_reg.register_tools(tool_reg)

        result = await tool_reg.execute("echo_skill", {"text": "hello"})
        assert result.success is True
        data = json.loads(result.result)
        assert data["echoed"] == "hello"
        assert data["action"] == "echo_skill"

    @pytest.mark.asyncio
    async def test_injected_tool_captures_skill_exception_as_json_error(self):
        """ToolRegistry.execute wraps handler exceptions — validate the error path."""
        skill_reg = SkillRegistry()
        skill_reg.register(ErrorSkill())
        # ErrorSkill has no definitions, so inject manually
        tool_reg = ToolRegistry()

        async def _bad(**kwargs: Any) -> str:
            raise RuntimeError("forced failure")

        tool_reg.register("error_skill", "Fails", {}, _bad)
        result = await tool_reg.execute("error_skill", {})
        assert result.success is False


# ---------------------------------------------------------------------------
# run_code_in_sandbox
# ---------------------------------------------------------------------------

class TestRunCodeInSandbox:
    @pytest.mark.asyncio
    async def test_simple_print_captured(self):
        code = "import json; print(json.dumps({'value': 42}))"
        result = await run_code_in_sandbox(code)
        assert result.get("exit_code") == 0
        assert result.get("data", {}).get("value") == 42

    @pytest.mark.asyncio
    async def test_non_json_stdout_stored_as_stdout_key(self):
        code = "print('hello world')"
        result = await run_code_in_sandbox(code)
        assert "stdout" in result
        assert "hello world" in result["stdout"]

    @pytest.mark.asyncio
    async def test_stderr_captured(self):
        code = "import sys; sys.stderr.write('oops\\n')"
        result = await run_code_in_sandbox(code)
        assert "stderr" in result
        assert "oops" in result["stderr"]

    @pytest.mark.asyncio
    async def test_nonzero_exit_code(self):
        code = "import sys; sys.exit(1)"
        result = await run_code_in_sandbox(code)
        assert result.get("exit_code") == 1

    @pytest.mark.asyncio
    async def test_timeout_returns_error_dict(self):
        code = "import time; time.sleep(9999)"
        result = await run_code_in_sandbox(code, timeout=1)
        assert "error" in result
        assert "timed out" in result["error"].lower()
        assert result.get("timeout") == 1


# ---------------------------------------------------------------------------
# DataValidationSkill — dispatch and error paths
# ---------------------------------------------------------------------------

class TestDataValidationSkillDispatch:
    def setup_method(self):
        self.skill = DataValidationSkill()

    def test_name_and_description(self):
        assert self.skill.name == "data_validation"
        assert "validat" in self.skill.description.lower()

    def test_get_tool_definitions_returns_six_tools(self):
        defs = self.skill.get_tool_definitions()
        assert len(defs) == 6
        names = {d["function"]["name"] for d in defs}
        expected = {
            "validate_schema",
            "validate_quality_score",
            "validate_anomalies",
            "validate_duplicates",
            "validate_referential",
            "validate_freshness",
        }
        assert names == expected

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        result = await self.skill.execute("totally_unknown_action", {})
        assert "error" in result
        assert "Unknown" in result["error"]

    @pytest.mark.asyncio
    async def test_schema_missing_file_path_returns_error(self):
        result = await self.skill.execute("validate_schema", {})
        assert result.get("error") == "file_path required"

    @pytest.mark.asyncio
    async def test_quality_score_missing_file_path_returns_error(self):
        result = await self.skill.execute("validate_quality_score", {})
        assert result.get("error") == "file_path required"

    @pytest.mark.asyncio
    async def test_anomalies_missing_file_path_returns_error(self):
        result = await self.skill.execute("validate_anomalies", {})
        assert result.get("error") == "file_path required"

    @pytest.mark.asyncio
    async def test_duplicates_missing_file_path_returns_error(self):
        result = await self.skill.execute("validate_duplicates", {})
        assert result.get("error") == "file_path required"

    @pytest.mark.asyncio
    async def test_referential_missing_params_returns_error(self):
        # All four keys required
        result = await self.skill.execute("validate_referential", {
            "primary_file": "a.csv",
            # missing primary_key, foreign_file, foreign_key
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_freshness_missing_date_column_returns_error(self):
        result = await self.skill.execute("validate_freshness", {
            "file_path": "data.csv",
            # missing date_column
        })
        assert "error" in result


# ---------------------------------------------------------------------------
# DataValidationSkill — sandbox integration (with mocked subprocess)
# ---------------------------------------------------------------------------

class TestDataValidationSkillSandbox:
    """Run the sandbox code generation methods with mocked subprocess output."""

    def setup_method(self):
        self.skill = DataValidationSkill()

    def _mock_sandbox(self, stdout_json: dict[str, Any]):
        """Patch run_code_in_sandbox to return a preset result."""
        return patch(
            "orchestra.skills.validation.run_code_in_sandbox",
            new=AsyncMock(return_value={"exit_code": 0, "data": stdout_json}),
        )

    @pytest.mark.asyncio
    async def test_schema_returns_sandbox_result(self):
        expected = {
            "valid": True,
            "actual_schema": {"id": "int64", "name": "object"},
            "issues": [],
            "issue_count": 0,
            "shape": [100, 2],
        }
        with self._mock_sandbox(expected):
            result = await self.skill.execute("validate_schema", {
                "file_path": "fake.csv",
                "expected_schema": {"id": "int64", "name": "object"},
            })
        assert result["exit_code"] == 0
        assert result["data"]["valid"] is True

    @pytest.mark.asyncio
    async def test_quality_score_returns_grade(self):
        expected = {
            "scores": {"completeness": 98.0, "uniqueness": 99.0, "consistency": 100.0, "validity": 100.0, "overall": 99.0},
            "grade": "A",
            "shape": [200, 5],
            "per_column": {},
        }
        with self._mock_sandbox(expected):
            result = await self.skill.execute("validate_quality_score", {"file_path": "fake.csv"})
        assert result["data"]["grade"] == "A"

    @pytest.mark.asyncio
    async def test_duplicates_returns_counts(self):
        expected = {
            "total_rows": 500,
            "duplicate_rows": 10,
            "duplicate_groups": 5,
            "duplicate_pct": 1.0,
            "checked_columns": ["id"],
            "sample_duplicates": [],
        }
        with self._mock_sandbox(expected):
            result = await self.skill.execute("validate_duplicates", {
                "file_path": "fake.csv",
                "columns": ["id"],
            })
        assert result["data"]["duplicate_rows"] == 10

    @pytest.mark.asyncio
    async def test_referential_valid_integrity(self):
        expected = {
            "valid": True,
            "primary_unique": 1000,
            "foreign_unique": 800,
            "orphan_count": 0,
            "unused_primary_count": 200,
            "orphan_values": [],
            "integrity_pct": 100.0,
        }
        with self._mock_sandbox(expected):
            result = await self.skill.execute("validate_referential", {
                "primary_file": "orders.csv",
                "primary_key": "order_id",
                "foreign_file": "items.csv",
                "foreign_key": "order_id",
            })
        assert result["data"]["valid"] is True
        assert result["data"]["orphan_count"] == 0

    @pytest.mark.asyncio
    async def test_freshness_returns_age(self):
        expected = {
            "date_column": "created_at",
            "earliest": "2026-01-01",
            "latest": "2026-05-20",
            "age_hours": 5.2,
            "span_days": 140.0,
            "fresh": True,
            "row_count": 5000,
            "null_dates": 0,
        }
        with self._mock_sandbox(expected):
            result = await self.skill.execute("validate_freshness", {
                "file_path": "events.csv",
                "date_column": "created_at",
            })
        assert result["data"]["fresh"] is True
        assert result["data"]["age_hours"] == 5.2
