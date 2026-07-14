"""Tests for core.agent.worker — subprocess worker data contracts and bootstrap."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from core.agent.loop.models import AgenticResult
from core.agent.worker import (
    _FAILURE_TERMINATION_REASONS,
    WorkerRequest,
    WorkerResult,
    _build_schema_retry_prompt,
    _needs_schema_retry,
    _resolve_worker_outcome,
)

# ---------------------------------------------------------------------------
# WorkerRequest / WorkerResult serialization
# ---------------------------------------------------------------------------


class TestWorkerRequest:
    def test_roundtrip(self) -> None:
        req = WorkerRequest(
            task_id="t-001",
            task_type="analyze",
            description="Analyze Project Orion",
            args={"subject_id": "Project Orion"},
            denied_tools=["delegate_task", "run_bash"],
            model="claude-opus-4-6",
            provider="anthropic",
            timeout_s=120.0,
        )
        data = req.to_dict()
        restored = WorkerRequest.from_dict(data)
        assert restored.task_id == "t-001"
        assert restored.description == "Analyze Project Orion"
        assert "delegate_task" in restored.denied_tools

    def test_defaults(self) -> None:
        req = WorkerRequest.from_dict({"task_id": "t-002"})
        # PR-CONFIG-SLOP-SWEEP — model/provider are inherit-sentinels ("")
        # resolved to the runtime's effective model in ``_run_agentic``,
        # not a frozen (and stale-prone) literal.
        assert req.model == ""
        assert req.provider == ""
        assert req.subagent_max_tokens == 32768
        # PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S6) — default
        # wall-clock cap lifted 120s → 600s. Operator overrides via
        # GEODE_SUBAGENT_TIMEOUT_S env or per-request payload.
        assert req.timeout_s == 600.0
        assert req.denied_tools == []
        assert req.isolation == ""

    def test_json_serializable(self) -> None:
        req = WorkerRequest(task_id="t-003", description="hello")
        raw = json.dumps(req.to_dict())
        parsed = json.loads(raw)
        assert parsed["task_id"] == "t-003"

    def test_reasoning_depth_roundtrip(self) -> None:
        """v0.55.0 R5 — pre-fix ``from_dict`` silently dropped ``effort``,
        ``thinking_budget``, ``time_budget_s`` so every sub-agent ran at
        the dataclass defaults. Wired in v0.55.0 to mirror Hermes
        (``delegate_tool.py:608`` parent-inherit) + Claude Code
        (``loadAgentsDir.ts:116`` agent-level effort frontmatter)."""
        req = WorkerRequest(
            task_id="t-r5",
            description="reasoning-heavy subtask",
            effort="max",
            thinking_budget=8192,
            time_budget_s=180.0,
        )
        data = req.to_dict()
        restored = WorkerRequest.from_dict(data)
        assert restored.effort == "max"
        assert restored.thinking_budget == 8192
        assert restored.time_budget_s == 180.0

    def test_reasoning_depth_defaults(self) -> None:
        """Defaults preserved when fields omitted from dict."""
        req = WorkerRequest.from_dict({"task_id": "t-default"})
        assert req.effort == "high"
        assert req.thinking_budget == 0
        assert req.time_budget_s == 0.0

    def test_toolkit_roundtrip(self) -> None:
        """CSP-1 — ``toolkit`` survives the parent→worker IPC boundary."""
        req = WorkerRequest(
            task_id="t-csp1",
            description="seed generator spawn",
            toolkit="seed_generation",
        )
        data = req.to_dict()
        assert data["toolkit"] == "seed_generation"
        restored = WorkerRequest.from_dict(data)
        assert restored.toolkit == "seed_generation"

    def test_toolkit_default_empty(self) -> None:
        """Default ``toolkit`` is empty string — legacy callers unaffected."""
        req = WorkerRequest.from_dict({"task_id": "t-bc"})
        assert req.toolkit == ""


class TestWorkerResult:
    def test_roundtrip(self) -> None:
        res = WorkerResult(
            task_id="t-001",
            success=True,
            output="Full response text",
            summary="Full response text"[:500],
            duration_ms=1234.5,
        )
        data = res.to_dict()
        restored = WorkerResult.from_dict(data)
        assert restored.task_id == "t-001"
        assert restored.success is True
        assert restored.output == "Full response text"
        assert restored.duration_ms == 1234.5

    def test_error_result(self) -> None:
        res = WorkerResult(
            task_id="t-002",
            success=False,
            error="Timeout after 120s",
        )
        data = res.to_dict()
        assert data["error"] == "Timeout after 120s"
        # None-valued fields should be excluded
        restored = WorkerResult.from_dict(data)
        assert restored.success is False

    def test_none_error_excluded(self) -> None:
        """to_dict() should omit None-valued fields."""
        res = WorkerResult(task_id="t-003", success=True)
        data = res.to_dict()
        assert "error" not in data

    def test_usage_fields_roundtrip(self) -> None:
        """PR-SEEDGEN-TOKENS — token + cost fields survive IPC serialization.

        The worker runs the sub-agent in a subprocess; without these
        fields the parent dropped ``agentic_result.usage`` entirely and
        every seed-gen run reported zero tokens. Pin the roundtrip so the
        regression cannot return silently.
        """
        res = WorkerResult(
            task_id="t-usage",
            success=True,
            output="done",
            prompt_tokens=4096,
            completion_tokens=512,
            usd_spent=0.0231,
        )
        restored = WorkerResult.from_dict(res.to_dict())
        assert restored.prompt_tokens == 4096
        assert restored.completion_tokens == 512
        assert restored.usd_spent == 0.0231

    def test_usage_defaults_zero(self) -> None:
        """Subscription / CLI calls expose no usage → fields default to 0.

        ``from_dict`` of a legacy payload (no usage keys) must not raise
        and must leave the counts at 0 — we never fabricate tokens.
        """
        restored = WorkerResult.from_dict({"task_id": "t-sub", "success": True})
        assert restored.prompt_tokens == 0
        assert restored.completion_tokens == 0
        assert restored.usd_spent == 0.0


# ---------------------------------------------------------------------------
# Worker subprocess integration (no LLM call)
# ---------------------------------------------------------------------------


class TestWorkerSubprocess:
    """Test the worker as an actual subprocess (stdin/stdout JSON protocol)."""

    def test_empty_stdin_returns_error(self) -> None:
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "core.agent.worker"],
            input="\n",
            capture_output=True,
            text=True,
            timeout=15,
        )
        result = json.loads(proc.stdout.strip())
        assert result["success"] is False
        assert "Empty stdin" in result["error"]

    def test_invalid_json_returns_error(self) -> None:
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "core.agent.worker"],
            input="not-json\n",
            capture_output=True,
            text=True,
            timeout=15,
        )
        result = json.loads(proc.stdout.strip())
        assert result["success"] is False
        assert "Invalid JSON" in result["error"]

    def test_missing_task_id_returns_error(self) -> None:
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "core.agent.worker"],
            input=json.dumps({"description": "hello"}) + "\n",
            capture_output=True,
            text=True,
            timeout=15,
        )
        result = json.loads(proc.stdout.strip())
        assert result["success"] is False
        assert "task_id" in result.get("error", "").lower() or result["task_id"] == "unknown"

    def test_result_backup_file_created(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Worker should save a backup result file."""
        monkeypatch.setattr("core.agent.worker.WORKER_DIR", tmp_path)
        # Import and call main directly to test backup
        from core.agent.worker import WorkerResult, _save_result_backup

        result = WorkerResult(task_id="bk-001", success=True, output="test")
        _save_result_backup(result)
        backup = tmp_path / "bk-001.result.json"
        assert backup.exists()
        data = json.loads(backup.read_text())
        assert data["task_id"] == "bk-001"


class TestResolveWorkerOutcome:
    """PR-DEFECT-AB (2026-05-24) — gate ``WorkerResult.success`` on the
    AgenticLoop's actual termination signal instead of ``bool(text)``.

    The seed-generation smoke (v0.99.52) revealed that proximity / critic
    sub-agents ingested the loop's ``_build_model_action_result`` fallback
    UI string ("! Unexpected error. Auto-retrying.") as legitimate
    content, because the worker reported ``success=True`` whenever the
    loop produced any non-empty string. The cases below pin the new
    contract so the regression cannot return silently.
    """

    def test_happy_path_real_response_is_success(self) -> None:
        result = AgenticResult(
            text="The answer is 42.",
            tool_calls=[],
            rounds=3,
            termination_reason="unknown",
            error=None,
        )
        success, summary, text = _resolve_worker_outcome(result)
        assert success is True
        assert text == "The answer is 42."
        assert summary == "The answer is 42."

    def test_convergence_detected_is_failure(self) -> None:
        """``convergence_detected`` is a failure exit — the loop bailed after
        detecting a repeating error pattern. agent_loop.py sets BOTH
        ``error="convergence_detected"`` AND
        ``termination_reason="convergence_detected"``, and the text is the
        diagnostic ("Detected repeating failure pattern. Breaking loop to
        avoid infinite retry."), not a real answer. Pinning this case so a
        future refactor that reorders the convergence path doesn't
        accidentally promote the bail-out to a legitimate response.
        """
        result = AgenticResult(
            text="Detected repeating failure pattern. Breaking loop to avoid infinite retry.",
            termination_reason="convergence_detected",
            error="convergence_detected",
        )
        success, summary, _text = _resolve_worker_outcome(result)
        assert success is False
        assert "convergence_detected" in summary

    @pytest.mark.parametrize(
        "termination_reason",
        sorted(_FAILURE_TERMINATION_REASONS),
    )
    def test_failure_termination_reasons_force_failure(self, termination_reason: str) -> None:
        """The five explicit failure sentinels must override ``bool(text)``.

        Each of these sentinels means the loop is emitting fallback UI
        text instead of a real LLM response, so downstream consumers
        MUST see ``success=False`` even though ``text`` is non-empty.
        """
        result = AgenticResult(
            text="! Unexpected error. Auto-retrying.",
            termination_reason=termination_reason,
        )
        success, summary, _text = _resolve_worker_outcome(result)
        assert success is False, (
            f"termination_reason={termination_reason!r} must force success=False"
        )
        assert "Sub-agent failed" in summary
        assert f"termination_reason={termination_reason}" in summary

    def test_error_field_forces_failure_even_with_text(self) -> None:
        """A non-None ``error`` always means failure, regardless of ``text`` or termination."""
        result = AgenticResult(
            text="partial output before crash",
            termination_reason="unknown",
            error="LLM provider timeout after 120s",
        )
        success, summary, _text = _resolve_worker_outcome(result)
        assert success is False
        assert "LLM provider timeout after 120s" in summary

    def test_empty_text_is_failure(self) -> None:
        result = AgenticResult(text="", termination_reason="unknown")
        success, summary, text = _resolve_worker_outcome(result)
        assert success is False
        assert text == ""
        # No error + unknown termination + no text — falls back to generic message.
        assert summary == "No response from sub-agent"

    def test_none_result_is_failure(self) -> None:
        success, summary, text = _resolve_worker_outcome(None)
        assert success is False
        assert text == ""
        assert summary == "No response from sub-agent"

    def test_user_clarification_needed_is_success(self) -> None:
        """The question IS the legitimate output, not fallback UI."""
        result = AgenticResult(
            text="What time zone should I use?",
            termination_reason="user_clarification_needed",
        )
        success, _summary, _text = _resolve_worker_outcome(result)
        assert success is True

    def test_input_blocked_is_success(self) -> None:
        """The diagnostic message IS the legitimate output."""
        result = AgenticResult(
            text="Input rejected by policy filter.",
            termination_reason="input_blocked",
        )
        success, _summary, _text = _resolve_worker_outcome(result)
        assert success is True

    def test_user_cancelled_is_success(self) -> None:
        """Operator-requested halt — text is the legitimate "Interrupted."
        marker (see agent_loop.py:705). No ``error`` is set, so the worker
        surfaces this as a clean exit and the parent decides what to do
        with the half-finished task rather than the parent treating it as
        a sub-agent failure."""
        result = AgenticResult(
            text="Interrupted.",
            termination_reason="user_cancelled",
        )
        success, _summary, _text = _resolve_worker_outcome(result)
        assert success is True

    def test_summary_truncates_at_500_chars(self) -> None:
        long_text = "x" * 1000
        result = AgenticResult(text=long_text, termination_reason="unknown")
        _success, summary, _text = _resolve_worker_outcome(result)
        assert len(summary) == 500

    def test_failure_sentinels_are_complete_catalog(self) -> None:
        """Lock the failure sentinel set against accidental shrinkage.

        If a new failure-tagged ``termination_reason`` is added to
        ``agent_loop.py`` without being added to
        ``_FAILURE_TERMINATION_REASONS``, this test won't catch it
        directly — but it pins the existing six so removal would
        require explicit acknowledgment.
        """
        expected = frozenset(
            {
                "model_action_required",
                "context_exhausted",
                "llm_error",
                "billing_error",
                "cost_budget_exceeded",
                "convergence_detected",
            }
        )
        assert expected == _FAILURE_TERMINATION_REASONS


class TestSubAgentReasoningWiring:
    """v0.55.0 R5 — verify ``_run_agentic`` actually plumbs the
    request's reasoning depth fields into ``AgenticLoop()``. Pre-fix
    these kwargs were never threaded through, so every sub-agent ran
    at the dataclass defaults (effort='high', thinking_budget=0,
    time_budget_s=0.0) regardless of what the parent put on the wire.
    """

    def test_loop_receives_reasoning_kwargs(self, monkeypatch, tmp_path) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        captured: dict = {}

        def _fake_loop(*args, **kwargs):
            captured.update(kwargs)
            mock_loop = MagicMock()
            # PR-DEFECT-AB (2026-05-24): _resolve_worker_outcome now reads
            # ``.error`` + ``.termination_reason`` off the loop's return,
            # so the stub must be a real AgenticResult (or close enough)
            # rather than a bare MagicMock whose attribute access yields
            # another MagicMock that breaks ``"; ".join(cause_bits)``.
            mock_loop.arun = AsyncMock(
                return_value=AgenticResult(
                    text="ok",
                    tool_calls=[],
                    rounds=1,
                    error=None,
                    termination_reason="unknown",
                )
            )
            return mock_loop

        # Stub out everything _run_agentic touches except the bit we test.
        monkeypatch.setattr("core.agent.worker.WORKER_DIR", tmp_path)
        with (
            patch("core.cli.tool_handlers._build_tool_handlers", return_value={}),
            patch("core.agent.tool_executor.ToolExecutor"),
            patch("core.agent.conversation.ConversationContext"),
            patch("core.agent.loop.AgenticLoop", side_effect=_fake_loop),
        ):
            from core.agent.worker import WorkerRequest, _run_agentic

            request = WorkerRequest(
                task_id="r5-test",
                description="reasoning subtask",
                effort="max",
                thinking_budget=8192,
                time_budget_s=240.0,
            )
            _run_agentic(request)

        assert captured.get("effort") == "max"
        assert captured.get("thinking_budget") == 8192
        assert captured.get("time_budget_s") == 240.0


# ---------------------------------------------------------------------------
# PR-WORKER-SCHEMA-AWARE-RETRY (2026-05-26) — schema-aware retry contract
# ---------------------------------------------------------------------------


_SAMPLE_ROLE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidate_id", "score"],
    "properties": {
        "candidate_id": {"type": "string"},
        "score": {"type": "number"},
    },
}


class TestNeedsSchemaRetry:
    """``_needs_schema_retry`` decides whether the worker re-issues the
    loop with a validator-feedback follow-up turn. The role's prompt-level
    PR-HANDOFF-SCHEMAS gate is best-effort; this helper is the last
    safety net before the parent records ``phase_failed``.
    """

    def test_none_result_triggers_retry(self) -> None:
        assert _needs_schema_retry(None, _SAMPLE_ROLE_SCHEMA) is True

    def test_empty_text_triggers_retry(self) -> None:
        result = AgenticResult(text="", termination_reason="unknown")
        assert _needs_schema_retry(result, _SAMPLE_ROLE_SCHEMA) is True

    def test_whitespace_only_text_triggers_retry(self) -> None:
        result = AgenticResult(text="   \n\n   ", termination_reason="unknown")
        assert _needs_schema_retry(result, _SAMPLE_ROLE_SCHEMA) is True

    def test_prose_without_json_triggers_retry(self) -> None:
        result = AgenticResult(
            text="I think the answer is somewhere around 7 but I'm not sure.",
            termination_reason="unknown",
        )
        assert _needs_schema_retry(result, _SAMPLE_ROLE_SCHEMA) is True

    def test_malformed_json_triggers_retry(self) -> None:
        result = AgenticResult(
            text='{"candidate_id": "c1", "score":',  # truncated
            termination_reason="unknown",
        )
        assert _needs_schema_retry(result, _SAMPLE_ROLE_SCHEMA) is True

    def test_missing_required_keys_triggers_retry(self) -> None:
        result = AgenticResult(
            text='{"candidate_id": "c1"}',  # missing ``score``
            termination_reason="unknown",
        )
        assert _needs_schema_retry(result, _SAMPLE_ROLE_SCHEMA) is True

    def test_explicit_error_triggers_retry(self) -> None:
        result = AgenticResult(
            text='{"candidate_id": "c1", "score": 0.7}',
            termination_reason="unknown",
            error="LLM provider timeout",
        )
        assert _needs_schema_retry(result, _SAMPLE_ROLE_SCHEMA) is True

    @pytest.mark.parametrize(
        "termination_reason",
        sorted(_FAILURE_TERMINATION_REASONS),
    )
    def test_failure_termination_triggers_retry(self, termination_reason: str) -> None:
        """Even with a syntactically valid JSON in ``text``, a failure-
        tagged ``termination_reason`` means the loop bailed — re-issuing
        gives it a fresh shot at the schema."""
        result = AgenticResult(
            text='{"candidate_id": "c1", "score": 0.7}',
            termination_reason=termination_reason,
        )
        assert _needs_schema_retry(result, _SAMPLE_ROLE_SCHEMA) is True

    def test_happy_path_does_not_retry(self) -> None:
        result = AgenticResult(
            text='{"candidate_id": "c1", "score": 0.7}',
            termination_reason="unknown",
        )
        assert _needs_schema_retry(result, _SAMPLE_ROLE_SCHEMA) is False

    def test_json_embedded_in_prose_does_not_retry(self) -> None:
        """``_last_balanced_json_object`` already tolerates JSON wrapped in
        prose (PR-HANDOFF-SCHEMAS parser fallback). The retry helper
        should match the parser, otherwise it would burn budget on
        cases the parent will accept anyway."""
        result = AgenticResult(
            text=(
                "After careful review, here is my answer:\n\n"
                '{"candidate_id": "c1", "score": 0.7}\n\n'
                "Let me know if you need anything else."
            ),
            termination_reason="unknown",
        )
        assert _needs_schema_retry(result, _SAMPLE_ROLE_SCHEMA) is False

    def test_schema_without_required_treats_any_object_as_valid(self) -> None:
        """``response_schema`` without a ``required`` list means the
        caller didn't pin specific keys — any parseable object passes."""
        schema_no_required: dict = {
            "type": "object",
            "additionalProperties": True,
            "properties": {"candidate_id": {"type": "string"}},
        }
        result = AgenticResult(text="{}", termination_reason="unknown")
        assert _needs_schema_retry(result, schema_no_required) is False

    def test_non_dict_root_triggers_retry(self) -> None:
        """The role contract is always an object; a bare list or scalar
        cannot satisfy ``required`` and must be retried."""
        result = AgenticResult(
            text='["c1", 0.7]',
            termination_reason="unknown",
        )
        assert _needs_schema_retry(result, _SAMPLE_ROLE_SCHEMA) is True

    @pytest.mark.parametrize(
        "termination_reason",
        ["input_blocked", "user_cancelled", "user_clarification_needed"],
    )
    def test_no_retry_success_exits_do_not_trigger_retry(self, termination_reason: str) -> None:
        """Codex MCP catch (2026-05-26) — the success exits whose text
        is intentional non-JSON must not be re-issued, otherwise the
        retry would override the cancel / block / clarification intent
        and invalidate ``_resolve_worker_outcome``'s success
        classification."""
        result = AgenticResult(
            text="Interrupted." if termination_reason == "user_cancelled" else "non-JSON body",
            termination_reason=termination_reason,
        )
        assert _needs_schema_retry(result, _SAMPLE_ROLE_SCHEMA) is False


class TestBuildSchemaRetryPrompt:
    def test_empty_prior_text_yields_explicit_empty_diag(self) -> None:
        prior = AgenticResult(text="", termination_reason="unknown")
        prompt = _build_schema_retry_prompt(_SAMPLE_ROLE_SCHEMA, prior)
        assert "Your previous response was empty." in prompt
        # Schema is embedded.
        assert '"candidate_id"' in prompt
        # The retry gate language matches the PR-HANDOFF-SCHEMAS prompt-side gate.
        assert "start with `{`" in prompt
        assert "end with `}`" in prompt

    def test_prose_prior_text_is_excerpted(self) -> None:
        prior = AgenticResult(
            text="I'm going to think about this in detail before answering.",
            termination_reason="unknown",
        )
        prompt = _build_schema_retry_prompt(_SAMPLE_ROLE_SCHEMA, prior)
        # The first-attempt excerpt is quoted (truncated repr) so the
        # model sees what it produced.
        assert "did not parse" in prompt
        assert "think about this in detail" in prompt

    def test_long_prior_text_truncated_at_800_chars(self) -> None:
        prior = AgenticResult(text="x" * 5000, termination_reason="unknown")
        prompt = _build_schema_retry_prompt(_SAMPLE_ROLE_SCHEMA, prior)
        assert "…(truncated)" in prompt

    def test_long_schema_truncated_at_4096_chars(self) -> None:
        big_schema: dict = {
            "type": "object",
            "required": ["k"],
            "properties": {
                f"k{i}": {"type": "string", "description": "x" * 200} for i in range(50)
            },
        }
        prompt = _build_schema_retry_prompt(big_schema, None)
        assert "schema truncated" in prompt


class TestSchemaAwareRetryWiring:
    """``_run_agentic`` must call the loop a second time exactly once
    when ``response_schema`` is set and the first attempt fails the
    retry helper. With no schema, no retry. With a schema and a passing
    first attempt, no retry."""

    def _patch_bootstrap(self, monkeypatch, tmp_path, side_effect_seq):
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_loop = MagicMock()
        mock_loop.arun = AsyncMock(side_effect=side_effect_seq)

        monkeypatch.setattr("core.agent.worker.WORKER_DIR", tmp_path)
        return mock_loop, patch, MagicMock

    def test_retry_fires_once_when_schema_set_and_first_is_empty(
        self, monkeypatch, tmp_path
    ) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_loop = MagicMock()
        mock_loop.arun = AsyncMock(
            side_effect=[
                AgenticResult(text="", termination_reason="unknown"),
                AgenticResult(
                    text='{"candidate_id": "c1", "score": 0.7}',
                    termination_reason="unknown",
                ),
            ]
        )

        monkeypatch.setattr("core.agent.worker.WORKER_DIR", tmp_path)
        with (
            patch("core.cli.tool_handlers._build_tool_handlers", return_value={}),
            patch("core.agent.tool_executor.ToolExecutor"),
            patch("core.agent.conversation.ConversationContext"),
            patch("core.agent.loop.AgenticLoop", return_value=mock_loop),
        ):
            from core.agent.worker import _run_agentic

            request = WorkerRequest(
                task_id="retry-1",
                description="seed scoring",
                response_schema=_SAMPLE_ROLE_SCHEMA,
            )
            result = _run_agentic(request)

        assert mock_loop.arun.await_count == 2, (
            "expected exactly one retry when first attempt is empty"
        )
        assert result.success is True
        assert "candidate_id" in result.output

    def test_no_retry_when_first_attempt_passes(self, monkeypatch, tmp_path) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_loop = MagicMock()
        mock_loop.arun = AsyncMock(
            return_value=AgenticResult(
                text='{"candidate_id": "c1", "score": 0.7}',
                termination_reason="unknown",
            )
        )

        monkeypatch.setattr("core.agent.worker.WORKER_DIR", tmp_path)
        with (
            patch("core.cli.tool_handlers._build_tool_handlers", return_value={}),
            patch("core.agent.tool_executor.ToolExecutor"),
            patch("core.agent.conversation.ConversationContext"),
            patch("core.agent.loop.AgenticLoop", return_value=mock_loop),
        ):
            from core.agent.worker import _run_agentic

            request = WorkerRequest(
                task_id="retry-2",
                description="seed scoring",
                response_schema=_SAMPLE_ROLE_SCHEMA,
            )
            _run_agentic(request)

        assert mock_loop.arun.await_count == 1, (
            "no retry expected when first attempt satisfies the schema"
        )

    def test_no_retry_when_response_schema_is_none(self, monkeypatch, tmp_path) -> None:
        """Free-form callers (REPL, gateway, ad-hoc CLI) never opt into
        the structured retry — an empty response is the caller's
        problem, not ours."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_loop = MagicMock()
        mock_loop.arun = AsyncMock(
            return_value=AgenticResult(text="", termination_reason="unknown")
        )

        monkeypatch.setattr("core.agent.worker.WORKER_DIR", tmp_path)
        with (
            patch("core.cli.tool_handlers._build_tool_handlers", return_value={}),
            patch("core.agent.tool_executor.ToolExecutor"),
            patch("core.agent.conversation.ConversationContext"),
            patch("core.agent.loop.AgenticLoop", return_value=mock_loop),
        ):
            from core.agent.worker import _run_agentic

            request = WorkerRequest(
                task_id="retry-3",
                description="free-form task",
                response_schema=None,
            )
            _run_agentic(request)

        assert mock_loop.arun.await_count == 1, (
            "no retry expected when caller did not declare a schema"
        )

    def test_retry_caps_at_one_even_if_second_attempt_also_fails(
        self, monkeypatch, tmp_path
    ) -> None:
        """The retry budget is exactly one. A third pass would burn
        cost without changing the underlying behaviour — the role
        contract is the same prompt."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_loop = MagicMock()
        mock_loop.arun = AsyncMock(
            return_value=AgenticResult(text="", termination_reason="unknown")
        )

        monkeypatch.setattr("core.agent.worker.WORKER_DIR", tmp_path)
        with (
            patch("core.cli.tool_handlers._build_tool_handlers", return_value={}),
            patch("core.agent.tool_executor.ToolExecutor"),
            patch("core.agent.conversation.ConversationContext"),
            patch("core.agent.loop.AgenticLoop", return_value=mock_loop),
        ):
            from core.agent.worker import _run_agentic

            request = WorkerRequest(
                task_id="retry-4",
                description="seed scoring",
                response_schema=_SAMPLE_ROLE_SCHEMA,
            )
            result = _run_agentic(request)

        assert mock_loop.arun.await_count == 2, (
            "retry must cap at exactly one — third pass not allowed"
        )
        # Phase still reports failure so the parent records ``phase_failed``.
        assert result.success is False

    @pytest.mark.parametrize(
        "termination_reason",
        ["input_blocked", "user_cancelled", "user_clarification_needed"],
    )
    def test_no_retry_on_success_exits_even_with_schema_set(
        self, monkeypatch, tmp_path, termination_reason: str
    ) -> None:
        """Codex MCP catch (2026-05-26) — when the loop terminates with
        ``input_blocked`` / ``user_cancelled`` / ``user_clarification_needed``
        the text is intentional and the parent must surface it as-is.
        Re-calling the loop on these terminations would be semantically
        wrong (cancel intent overridden) and a budget burn."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_loop = MagicMock()
        mock_loop.arun = AsyncMock(
            return_value=AgenticResult(
                text="non-JSON body",
                termination_reason=termination_reason,
            )
        )

        monkeypatch.setattr("core.agent.worker.WORKER_DIR", tmp_path)
        with (
            patch("core.cli.tool_handlers._build_tool_handlers", return_value={}),
            patch("core.agent.tool_executor.ToolExecutor"),
            patch("core.agent.conversation.ConversationContext"),
            patch("core.agent.loop.AgenticLoop", return_value=mock_loop),
        ):
            from core.agent.worker import _run_agentic

            request = WorkerRequest(
                task_id="no-retry-success",
                description="seed scoring",
                response_schema=_SAMPLE_ROLE_SCHEMA,
            )
            _run_agentic(request)

        assert mock_loop.arun.await_count == 1, (
            f"termination_reason={termination_reason!r} must not trigger retry "
            "even with response_schema set"
        )

    def test_retry_skipped_when_elapsed_past_half_of_timeout_s(self, monkeypatch, tmp_path) -> None:
        """Codex MCP catch (2026-05-26) — ``AgenticLoop.arun`` resets
        ``_loop_start_time`` per call so the retry would get another
        full ``time_budget_s``. Guard the retry on
        ``elapsed_before_retry < 0.5 * request.timeout_s`` so a worker
        pegged near its wall-clock cap doesn't get pushed past it."""
        from unittest.mock import AsyncMock, MagicMock, patch

        async def _slow_arun(_prompt: str) -> AgenticResult:
            return AgenticResult(text="", termination_reason="unknown")

        mock_loop = MagicMock()
        mock_loop.arun = AsyncMock(side_effect=_slow_arun)

        # Fake the wall-clock so ``time.time() - started`` looks like
        # 80% of the cap by the time we hit the retry gate.
        real_time = __import__("time").time
        baseline = real_time()
        call_count = {"n": 0}

        def _fake_time() -> float:
            call_count["n"] += 1
            # First call (``started = time.time()``) returns baseline.
            # Subsequent calls return baseline + 80s — with timeout_s=100
            # that's 80%, past the 50% gate.
            if call_count["n"] == 1:
                return baseline
            return baseline + 80.0

        monkeypatch.setattr("core.agent.worker.WORKER_DIR", tmp_path)
        monkeypatch.setattr("core.agent.worker.time.time", _fake_time)
        with (
            patch("core.cli.tool_handlers._build_tool_handlers", return_value={}),
            patch("core.agent.tool_executor.ToolExecutor"),
            patch("core.agent.conversation.ConversationContext"),
            patch("core.agent.loop.AgenticLoop", return_value=mock_loop),
        ):
            from core.agent.worker import _run_agentic

            request = WorkerRequest(
                task_id="retry-budget-gate",
                description="seed scoring",
                response_schema=_SAMPLE_ROLE_SCHEMA,
                timeout_s=100.0,
            )
            _run_agentic(request)

        assert mock_loop.arun.await_count == 1, (
            "retry must be vetoed when elapsed time > 50%% of wall-clock cap"
        )

    def test_retry_passes_feedback_prompt_with_schema_to_loop(self, monkeypatch, tmp_path) -> None:
        """The second ``arun`` call must include the schema text + the
        explicit ``start with `{` and end with `}``` enforcement — that
        is the entire point of the retry."""
        from unittest.mock import AsyncMock, MagicMock, patch

        prompts_seen: list[str] = []

        async def _capture_arun(prompt: str) -> AgenticResult:
            prompts_seen.append(prompt)
            if len(prompts_seen) == 1:
                return AgenticResult(text="", termination_reason="unknown")
            return AgenticResult(
                text='{"candidate_id": "c1", "score": 0.7}',
                termination_reason="unknown",
            )

        mock_loop = MagicMock()
        mock_loop.arun = AsyncMock(side_effect=_capture_arun)

        monkeypatch.setattr("core.agent.worker.WORKER_DIR", tmp_path)
        with (
            patch("core.cli.tool_handlers._build_tool_handlers", return_value={}),
            patch("core.agent.tool_executor.ToolExecutor"),
            patch("core.agent.conversation.ConversationContext"),
            patch("core.agent.loop.AgenticLoop", return_value=mock_loop),
        ):
            from core.agent.worker import _run_agentic

            request = WorkerRequest(
                task_id="retry-5",
                description="original prompt text",
                response_schema=_SAMPLE_ROLE_SCHEMA,
            )
            _run_agentic(request)

        assert len(prompts_seen) == 2
        # First attempt is the caller's prompt verbatim.
        assert "original prompt text" in prompts_seen[0]
        # Retry carries the validator feedback + schema body.
        assert "start with `{`" in prompts_seen[1]
        assert "candidate_id" in prompts_seen[1]


# ---------------------------------------------------------------------------
# Minimal worker hook bundle (trajectory audit 2026-07-03)
# ---------------------------------------------------------------------------


class TestWorkerHookBundle:
    """Subprocess sub-agents previously ran with ``hooks=None`` so their
    tool trajectory (Episode rows + operational event rows) was silently lost.
    ``build_worker_hooks`` injects only the two trajectory rails."""

    def test_run_agentic_injects_worker_hooks(self) -> None:
        import inspect

        from core.agent import worker

        src = inspect.getsource(worker._run_agentic)
        assert "build_worker_hooks" in src
        assert "hooks=worker_hooks" in src

    def test_build_worker_hooks_records_episode_and_event(self, tmp_path: Path) -> None:
        from core.agent.cognitive_state_ctx import set_session_id
        from core.hooks import HookEvent
        from core.memory.episodic import EpisodicStore, set_episodic_store
        from core.wiring.bootstrap import build_worker_hooks

        episodes_path = tmp_path / "episodes.jsonl"
        set_episodic_store(EpisodicStore(path=episodes_path))
        set_session_id("wk-hooks-1")
        try:
            hooks = build_worker_hooks(
                session_key="wk-hooks-1",
                run_id="wk-hooks-1",
                log_dir=tmp_path,
            )
            hooks.trigger(
                HookEvent.TOOL_EXEC_ENDED,
                {
                    "tool_name": "read_document",
                    "tool_input": {"path": "notes.md"},
                    "has_error": False,
                    "result": {"ok": True},
                    "duration_ms": 3.0,
                },
            )

            # Episodic rail — the child's tool call landed as an Episode row.
            episode = json.loads(episodes_path.read_text(encoding="utf-8").strip())
            assert episode["tool_name"] == "read_document"
            assert episode["session_id"] == "wk-hooks-1"
            assert episode["success"] is True

            # SQL rail — the canonical sink captured the same event.
            from core.observability.event_store import HookEventStore

            reader = HookEventStore(tmp_path / "events.db")
            assert [row.event for row in reader.read()] == ["tool_exec_ended"]
            reader.close()
            hooks.close()
        finally:
            set_episodic_store(None)
            set_session_id("")

    def test_build_worker_hooks_event_sink_covers_all_events(self, tmp_path: Path) -> None:
        """Lifecycle events beyond TOOL_EXEC_ENDED also land in SQLite."""
        from core.hooks import HookEvent
        from core.wiring.bootstrap import build_worker_hooks

        hooks = build_worker_hooks(
            session_key="wk-hooks-2",
            run_id="wk-hooks-2",
            log_dir=tmp_path,
        )
        hooks.trigger(HookEvent.SESSION_ENDED, {"session_id": "wk-hooks-2"})

        from core.observability.event_store import HookEventStore

        reader = HookEventStore(tmp_path / "events.db")
        events = [row.event for row in reader.read()]
        assert HookEvent.SESSION_ENDED.value in events
        reader.close()
        hooks.close()
