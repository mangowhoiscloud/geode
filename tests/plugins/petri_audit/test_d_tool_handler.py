"""eval_dspy_optimize tool handler wiring tests."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_eval_dspy_optimize_handler_registered() -> None:
    from core.cli.tool_handlers.audit import _build_audit_handlers

    handlers = _build_audit_handlers()
    assert "eval_dspy_optimize" in handlers
    assert callable(handlers["eval_dspy_optimize"])


def test_eval_dspy_optimize_missing_args_returns_error() -> None:
    from core.cli.tool_handlers.audit import _build_audit_handlers

    handlers = _build_audit_handlers()
    result = handlers["eval_dspy_optimize"]()
    assert result["status"] == "error"
    assert "judge, generator, eval_log_path are required" in result["error"]


def test_eval_dspy_optimize_same_family_returns_error(tmp_path: Path) -> None:
    from core.cli.tool_handlers.audit import _build_audit_handlers

    log = tmp_path / "fake.eval"
    log.write_bytes(b"")
    handlers = _build_audit_handlers()
    result = handlers["eval_dspy_optimize"](
        judge="claude-haiku-4-5-20251001",
        generator="claude-opus-4-7",
        eval_log_path=str(log),
        output_dir=str(tmp_path),
    )
    assert result["status"] == "error"
    assert "M1" in result["error"]


def test_eval_dspy_optimize_dry_run_happy_path(tmp_path: Path) -> None:
    from core.cli.tool_handlers.audit import _build_audit_handlers

    log = tmp_path / "fake.eval"
    log.write_bytes(b"")
    handlers = _build_audit_handlers()
    result = handlers["eval_dspy_optimize"](
        judge="claude-haiku-4-5-20251001",
        generator="gpt-5.4",
        eval_log_path=str(log),
        output_dir=str(tmp_path),
        dry_run=True,
    )
    assert result["status"] == "ok"
    assert result["tool"] == "eval_dspy_optimize"
    optimize = result["optimize"]
    assert optimize["dry_run"] is True
    assert optimize["judge_family"] == "anthropic"
    assert optimize["generator_family"] == "openai"
    assert "M2" in optimize["next_step"]


def test_eval_dspy_optimize_in_expensive_tools() -> None:
    from core.agent.safety import EXPENSIVE_TOOLS

    assert "eval_dspy_optimize" in EXPENSIVE_TOOLS
    assert EXPENSIVE_TOOLS["eval_dspy_optimize"] >= 5.0


def test_eval_dspy_optimize_in_definitions_json() -> None:
    import json
    from pathlib import Path as _Path

    defs_path = _Path(__file__).resolve().parents[3] / "core" / "tools" / "definitions.json"
    defs = json.loads(defs_path.read_text())
    tool = next((d for d in defs if d.get("name") == "eval_dspy_optimize"), None)
    assert tool is not None
    assert tool["category"] == "evaluation"
    assert tool["cost_tier"] == "expensive"
    properties = tool["input_schema"]["properties"]
    for required_field in ("judge", "generator", "eval_log_path", "dry_run"):
        assert required_field in properties
    description = tool["description"]
    # M1/M2/M3/M10 라벨이 description 안에 명시돼 있어야 자연어 라우팅 시
    # AgenticLoop가 잠금 효과를 인지.
    for mid in ("M1", "M2", "M3", "M10"):
        assert mid in description, f"description must mention {mid}"


def test_eval_dspy_optimize_in_aggregate_handlers() -> None:
    """`_build_tool_handlers` must expose eval_dspy_optimize."""
    from core.cli.tool_handlers import _build_tool_handlers

    handlers = _build_tool_handlers(verbose=False)
    assert "eval_dspy_optimize" in handlers


# ---------------------------------------------------------------------------
# family_of / same_family — M1 helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_id, expected",
    [
        ("claude-opus-4-7", "anthropic"),
        ("claude-haiku-4-5-20251001", "anthropic"),
        ("gpt-5.5", "openai"),
        ("o3", "openai"),
        ("o4-mini", "openai"),
        ("glm-5", "zhipuai"),
        ("anthropic/claude-opus-4-7", "anthropic"),
        ("openai/gpt-5.4", "openai"),
        ("openai-api/glm/glm-5.1", "zhipuai"),
        ("geode/claude-opus-4-7", "anthropic"),
        ("geode/glm-5", "zhipuai"),
        ("mystery", "unknown"),
        ("", "unknown"),
    ],
)
def test_family_of(model_id: str, expected: str) -> None:
    from plugins.petri_audit.models import family_of

    assert family_of(model_id) == expected


def test_same_family_unknown_returns_false() -> None:
    from plugins.petri_audit.models import same_family

    # Two unknown ids must NOT count as same-family.
    assert same_family("mystery-a", "mystery-b") is False
    assert same_family("mystery-a", "claude-opus-4-7") is False


def test_same_family_cross_family_pairs() -> None:
    from plugins.petri_audit.models import same_family

    assert same_family("claude-haiku-4-5-20251001", "gpt-5.5") is False
    assert same_family("claude-opus-4-7", "claude-haiku-4-5-20251001") is True
    assert same_family("gpt-5.4", "gpt-5.4-mini") is True
