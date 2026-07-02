"""PR-SUBAGENT-ROLES — built-in sub-agent role registry + result validation.

Pins the opt-in capability registry (``core/agent/subagent_roles.py``):
registry lookup, allowlist → denied-set inversion (the existing
``ToolExecutor.denied_tools`` rail), the parent-side output validator
(direct JSON / fenced-JSON recovery / structured-error fallback — NEVER a
raised JSONDecodeError), the ``delegate_task`` → ``SubTask.role`` →
``WorkerRequest`` wiring, and the unknown-role legacy passthrough.

No live LLM — all spawn paths are mocked.
"""

from __future__ import annotations

import json

import pytest
from core.agent.sub_agent import SubAgentManager, SubTask
from core.agent.subagent_roles import (
    SUBAGENT_ROLES,
    ResearchFindings,
    SubAgentRole,
    get_role,
    output_schema_line,
    role_denied_tools,
    validate_role_output,
)
from core.orchestration.isolated_execution import IsolatedRunner, IsolationResult
from core.tools.base import load_all_tool_definitions, load_tool_definition

# ---------------------------------------------------------------------------
# Registry lookup
# ---------------------------------------------------------------------------


class TestRegistryLookup:
    def test_four_builtin_roles_registered(self) -> None:
        assert set(SUBAGENT_ROLES) == {"repo_researcher", "patcher", "verifier", "reviewer"}

    def test_get_role_returns_registered_role(self) -> None:
        role = get_role("repo_researcher")
        assert role is not None
        assert role.role == "repo_researcher"
        assert role.output_model is ResearchFindings
        assert set(role.tools) == {"glob_files", "grep_files", "read_document", "session_search"}

    def test_get_role_unknown_returns_none(self) -> None:
        assert get_role("nonexistent_role") is None
        assert get_role("") is None

    def test_every_role_tool_exists_in_definitions_json(self) -> None:
        """A role allowlist naming a tool that doesn't exist would silently
        degrade the sub-agent's capability (filter_handlers WARNING path)."""
        known = {d["name"] for d in load_all_tool_definitions()}
        for role in SUBAGENT_ROLES.values():
            unknown = set(role.tools) - known
            assert not unknown, f"role {role.role!r} references unknown tools: {unknown}"

    def test_every_role_declares_output_model_and_description(self) -> None:
        for role in SUBAGENT_ROLES.values():
            assert role.output_model is not None
            assert role.description


# ---------------------------------------------------------------------------
# Allowlist → denied-set inversion (existing ToolExecutor.denied_tools rail)
# ---------------------------------------------------------------------------


class TestRoleDeniedTools:
    def test_denied_is_all_minus_allowed(self) -> None:
        role = SUBAGENT_ROLES["reviewer"]
        all_tools = ["grep_files", "read_document", "run_bash", "write_file"]
        denied = role_denied_tools(role, all_tools)
        # provider-native tools are always in the inversion universe
        assert denied == {"run_bash", "write_file", "computer", "computer_use"}

    def test_repo_researcher_denies_run_bash_and_writes(self) -> None:
        role = SUBAGENT_ROLES["repo_researcher"]
        all_tools = [d["name"] for d in load_all_tool_definitions()]
        denied = role_denied_tools(role, all_tools)
        assert "run_bash" in denied
        assert "write_file" in denied
        assert "edit_file" in denied
        assert "delegate_task" in denied
        # Allowlisted tools are NOT denied.
        assert not denied & set(role.tools)

    def test_verifier_keeps_run_bash(self) -> None:
        role = SUBAGENT_ROLES["verifier"]
        all_tools = [d["name"] for d in load_all_tool_definitions()]
        denied = role_denied_tools(role, all_tools)
        assert "run_bash" not in denied
        assert "write_file" in denied


# ---------------------------------------------------------------------------
# Output validator
# ---------------------------------------------------------------------------

_VALID_FINDINGS = {
    "findings": [
        {"claim": "loop retries twice", "evidence_path": "core/agent/loop.py", "confidence": 0.9}
    ]
}


class TestValidateRoleOutput:
    def test_happy_path_direct_json(self) -> None:
        role = SUBAGENT_ROLES["repo_researcher"]
        result = validate_role_output(role, json.dumps(_VALID_FINDINGS))
        assert result is not None
        assert result["validated"] is True
        assert result["data"] == _VALID_FINDINGS

    def test_fenced_json_recovery(self) -> None:
        role = SUBAGENT_ROLES["repo_researcher"]
        raw = (
            "Here is what I found after searching the repo:\n\n"
            "```json\n" + json.dumps(_VALID_FINDINGS) + "\n```\n\nLet me know if you need more."
        )
        result = validate_role_output(role, raw)
        assert result is not None
        assert result["validated"] is True
        assert result["data"] == _VALID_FINDINGS

    def test_failure_returns_structured_error_no_exception(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        role = SUBAGENT_ROLES["repo_researcher"]
        raw = "I could not complete the task because" + " x" * 1500  # long prose, no JSON
        with caplog.at_level("WARNING", logger="core.agent.subagent_roles"):
            result = validate_role_output(role, raw)
        assert result is not None
        assert result["validated"] is False
        assert result.get("error")
        # First 2000 chars of the raw text, capped.
        assert result["raw"] == raw[:2000]
        assert len(result["raw"]) <= 2000
        # Fail-loud: degraded result is observable in the log.
        assert any("failed" in rec.message for rec in caplog.records)

    def test_valid_json_wrong_schema_is_structured_error(self) -> None:
        role = SUBAGENT_ROLES["verifier"]
        result = validate_role_output(role, '{"findings": []}')  # researcher shape, not verifier
        assert result is not None
        assert result["validated"] is False
        assert "ValidationError" in result["error"]

    def test_empty_output_is_structured_error(self) -> None:
        role = SUBAGENT_ROLES["reviewer"]
        result = validate_role_output(role, "")
        assert result is not None
        assert result["validated"] is False
        assert "EmptyOutput" in result["error"]

    def test_no_output_model_returns_none(self) -> None:
        bare = SubAgentRole(role="bare", tools=("grep_files",), output_model=None, description="d")
        assert validate_role_output(bare, '{"anything": 1}') is None

    def test_verifier_happy_path(self) -> None:
        role = SUBAGENT_ROLES["verifier"]
        payload = {
            "passed": False,
            "checks": [{"name": "pytest", "passed": False, "detail": "2 failed"}],
        }
        result = validate_role_output(role, json.dumps(payload))
        assert result is not None
        assert result["validated"] is True
        assert result["data"]["passed"] is False


# ---------------------------------------------------------------------------
# Prompt-side schema line
# ---------------------------------------------------------------------------


class TestOutputSchemaLine:
    def test_schema_line_carries_json_schema(self) -> None:
        line = output_schema_line(SUBAGENT_ROLES["patcher"])
        assert "ONLY a JSON object" in line
        assert '"patches"' in line

    def test_no_output_model_yields_empty(self) -> None:
        bare = SubAgentRole(role="bare", tools=(), output_model=None, description="d")
        assert output_schema_line(bare) == ""


# ---------------------------------------------------------------------------
# SubAgentManager wiring — WorkerRequest + parse site
# ---------------------------------------------------------------------------


def _manager() -> SubAgentManager:
    return SubAgentManager(IsolatedRunner())


def _role_task(role: str, task_id: str = "t1") -> SubTask:
    return SubTask(
        task_id=task_id, description="find the retry logic", task_type="analyze", role=role
    )


class TestWorkerRequestRoleWiring:
    def test_role_narrows_denied_tools(self) -> None:
        req = _manager()._build_worker_request(_role_task("repo_researcher"))
        denied = set(req.denied_tools)
        assert "run_bash" in denied
        assert "write_file" in denied
        assert "delegate_task" in denied
        for allowed in SUBAGENT_ROLES["repo_researcher"].tools:
            assert allowed not in denied

    def test_role_supplies_allowlist_when_no_agent_toolkit(self) -> None:
        # Without this, filter_handlers Tier 3 applies the minimal
        # ``_default`` toolkit and strips role tools (verifier's run_bash).
        req = _manager()._build_worker_request(_role_task("verifier"))
        assert req.agent_allowed_tools == ["run_bash"]

    def test_role_appends_schema_line_to_prompt(self) -> None:
        req = _manager()._build_worker_request(_role_task("repo_researcher"))
        assert req.description.startswith("find the retry logic")
        assert "ONLY a JSON object" in req.description
        assert '"findings"' in req.description

    def test_unknown_role_passthrough_default_surface(self) -> None:
        baseline = _manager()._build_worker_request(
            SubTask(task_id="t0", description="find the retry logic", task_type="analyze")
        )
        req = _manager()._build_worker_request(_role_task("no_such_role"))
        # Unknown role = current default behaviour unchanged.
        assert set(req.denied_tools) == set(baseline.denied_tools)
        assert req.agent_allowed_tools == baseline.agent_allowed_tools
        assert req.description == baseline.description

    def test_no_role_leaves_legacy_denied_set(self) -> None:
        req = _manager()._build_worker_request(
            SubTask(task_id="t0", description="d", task_type="analyze")
        )
        assert set(req.denied_tools) == {"delegate_task"}
        assert "ONLY a JSON object" not in req.description


class TestParseSiteValidation:
    def test_valid_role_output_marks_validated(self) -> None:
        mgr = _manager()
        isolation = IsolationResult(
            session_id="s1", success=True, output=json.dumps(_VALID_FINDINGS)
        )
        result = mgr._to_sub_result(_role_task("repo_researcher"), isolation)
        assert result.success is True
        assert result.output["validated"] is True
        assert result.output["data"] == _VALID_FINDINGS

    def test_fenced_role_output_recovers(self) -> None:
        mgr = _manager()
        isolation = IsolationResult(
            session_id="s1",
            success=True,
            output="prose first\n```json\n" + json.dumps(_VALID_FINDINGS) + "\n```",
        )
        result = mgr._to_sub_result(_role_task("repo_researcher"), isolation)
        assert result.output["validated"] is True

    def test_garbage_role_output_is_structured_error_not_raise(self) -> None:
        mgr = _manager()
        isolation = IsolationResult(session_id="s1", success=True, output="total garbage {not json")
        result = mgr._to_sub_result(_role_task("repo_researcher"), isolation)
        # No exception reached us; the degraded result is observable.
        assert result.success is True
        assert result.output["validated"] is False
        assert result.output["raw"].startswith("total garbage")

    def test_unknown_role_keeps_legacy_parse(self) -> None:
        mgr = _manager()
        isolation = IsolationResult(session_id="s1", success=True, output='{"a": 1}')
        result = mgr._to_sub_result(_role_task("no_such_role"), isolation)
        assert result.output == {"a": 1}
        assert "validated" not in result.output

    def test_no_role_keeps_legacy_raw_fallback(self) -> None:
        mgr = _manager()
        isolation = IsolationResult(session_id="s1", success=True, output="plain prose")
        result = mgr._to_sub_result(
            SubTask(task_id="t1", description="d", task_type="analyze"), isolation
        )
        assert result.output == {"raw": "plain prose"}

    def test_failed_isolation_unaffected_by_role(self) -> None:
        mgr = _manager()
        isolation = IsolationResult(session_id="s1", success=False, error="boom")
        result = mgr._to_sub_result(_role_task("repo_researcher"), isolation)
        assert result.success is False
        assert result.error == "boom"


# ---------------------------------------------------------------------------
# Drift invariant — definitions.json role enum ↔ SUBAGENT_ROLES keys
# ---------------------------------------------------------------------------


class TestSchemaDriftInvariant:
    def test_delegate_task_role_enum_matches_registry(self) -> None:
        """Dual-SoT pin (CLAUDE.md drift-invariant rule): the ``role`` enum
        in ``core/tools/definitions.json`` must track the registry keys, in
        both single-task and batch-item positions."""
        schema = load_tool_definition("delegate_task")["input_schema"]
        top_enum = schema["properties"]["role"]["enum"]
        item_enum = schema["properties"]["tasks"]["items"]["properties"]["role"]["enum"]
        assert set(top_enum) == set(SUBAGENT_ROLES)
        assert set(item_enum) == set(SUBAGENT_ROLES)


def test_role_denied_tools_includes_provider_native_computer() -> None:
    """Provider-injected tools (not in definitions.json) must be denied for
    restricted roles — the inversion universe includes PROVIDER_NATIVE_TOOLS."""
    from core.agent.subagent_roles import SUBAGENT_ROLES, role_denied_tools

    role = SUBAGENT_ROLES["repo_researcher"]
    denied = role_denied_tools(role, ["grep_files", "read_document"])
    assert "computer" in denied
    assert "computer_use" in denied
