"""Tests for ``core.self_improving_loop.runner`` — PR-G5b (2026-05-20)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from core.self_improving_loop.runner import (
    Mutation,
    RunnerContext,
    SelfImprovingLoopRunner,
    append_audit_log,
    apply_mutation,
    build_runner_context,
    parse_mutation,
)

# ---------------------------------------------------------------------------
# parse_mutation
# ---------------------------------------------------------------------------


class TestParseMutation:
    def test_parses_bare_json(self) -> None:
        raw = json.dumps(
            {
                "target_section": "tool_handling",
                "new_value": "Be careful with tool calls.",
                "rationale": "broken_tool_use regressed (value=7)",
                "target_dim": "broken_tool_use",
            }
        )
        mutation = parse_mutation(raw)
        assert mutation.target_section == "tool_handling"
        assert "Be careful" in mutation.new_value
        assert mutation.target_dim == "broken_tool_use"

    def test_strips_code_fence(self) -> None:
        raw = (
            "```json\n"
            + json.dumps({"target_section": "x", "new_value": "y", "rationale": "z"})
            + "\n```"
        )
        mutation = parse_mutation(raw)
        assert mutation.target_section == "x"

    def test_empty_response_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            parse_mutation("")

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(ValueError, match="not valid JSON"):
            parse_mutation("{ not json")

    def test_non_object_raises(self) -> None:
        with pytest.raises(ValueError, match="JSON object"):
            parse_mutation(json.dumps(["not", "a", "dict"]))

    def test_missing_target_section_raises(self) -> None:
        with pytest.raises(ValueError, match="target_section"):
            parse_mutation(json.dumps({"new_value": "x", "rationale": "y"}))

    def test_empty_target_section_raises(self) -> None:
        with pytest.raises(ValueError, match="target_section"):
            parse_mutation(
                json.dumps({"target_section": "   ", "new_value": "x", "rationale": "y"})
            )

    def test_missing_new_value_raises(self) -> None:
        with pytest.raises(ValueError, match="new_value"):
            parse_mutation(json.dumps({"target_section": "x", "rationale": "y"}))

    def test_new_value_too_long_raises(self) -> None:
        with pytest.raises(ValueError, match="600 char cap"):
            parse_mutation(
                json.dumps({"target_section": "x", "new_value": "a" * 700, "rationale": "y"})
            )


# ---------------------------------------------------------------------------
# apply_mutation
# ---------------------------------------------------------------------------


def test_apply_mutation_rewrites_existing_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autoresearch import train as auto_train

    sot_path = tmp_path / "wrapper-sections.json"
    monkeypatch.setattr(auto_train, "WRAPPER_SECTIONS_SOT_PATH", sot_path)
    current = {"role": "old role", "tools": "old tools"}
    mutation = Mutation(
        target_section="role",
        new_value="new role text",
        rationale="r",
    )
    new_sections, previous_value = apply_mutation(mutation, current_sections=current)
    assert previous_value == "old role"
    assert new_sections["role"] == "new role text"
    # SoT file persists the change.
    persisted = json.loads(sot_path.read_text(encoding="utf-8"))
    assert persisted["role"] == "new role text"


def test_apply_mutation_inserts_new_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autoresearch import train as auto_train

    sot_path = tmp_path / "wrapper-sections.json"
    monkeypatch.setattr(auto_train, "WRAPPER_SECTIONS_SOT_PATH", sot_path)
    mutation = Mutation(
        target_section="brand_new",
        new_value="freshly inserted",
        rationale="r",
    )
    new_sections, previous_value = apply_mutation(mutation, current_sections={"role": "r"})
    assert previous_value == ""
    assert new_sections["brand_new"] == "freshly inserted"
    persisted = json.loads(sot_path.read_text(encoding="utf-8"))
    assert persisted["brand_new"] == "freshly inserted"
    assert persisted["role"] == "r"  # untouched


# ---------------------------------------------------------------------------
# append_audit_log
# ---------------------------------------------------------------------------


def test_append_audit_log_writes_jsonl_row(tmp_path: Path) -> None:
    log_path = tmp_path / "mutations.jsonl"
    mutation = Mutation(
        target_section="x",
        new_value="y",
        rationale="r",
        target_dim="broken_tool_use",
    )
    written = append_audit_log(
        mutation, previous_value="old y", log_path=log_path, baseline_fitness=0.85
    )
    assert written == log_path
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["target_section"] == "x"
    assert row["previous_value"] == "old y"
    assert row["new_value"] == "y"
    assert row["baseline_fitness"] == 0.85
    assert "ts" in row


def test_append_audit_log_appends_to_existing(tmp_path: Path) -> None:
    log_path = tmp_path / "mutations.jsonl"
    for i in range(3):
        append_audit_log(
            Mutation(target_section=f"s{i}", new_value="v", rationale="r"),
            previous_value="",
            log_path=log_path,
        )
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    sections = [json.loads(line)["target_section"] for line in lines]
    assert sections == ["s0", "s1", "s2"]


def test_append_audit_log_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "subdir" / "mutations.jsonl"
    append_audit_log(
        Mutation(target_section="x", new_value="y", rationale="r"),
        previous_value="",
        log_path=nested,
    )
    assert nested.is_file()


# ---------------------------------------------------------------------------
# build_runner_context
# ---------------------------------------------------------------------------


def test_build_runner_context_with_baseline_and_priors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All 3 lookups feed the RunnerContext + target_dim auto-picked."""
    from autoresearch import train as auto_train
    from plugins.seed_generation.baseline_reader import BaselineSnapshot, MetaReviewSnapshot

    sot_path = tmp_path / "wrapper-sections.json"
    sot_path.write_text(json.dumps({"role": "r"}), encoding="utf-8")
    monkeypatch.setattr(auto_train, "WRAPPER_SECTIONS_SOT_PATH", sot_path)

    fake_baseline = BaselineSnapshot(dim_means={"broken_tool_use": 8.0})
    fake_priors = MetaReviewSnapshot(underrepresented_dims=["broken_tool_use"])
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_baseline",
        lambda: fake_baseline,
    )
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_latest_meta_review",
        lambda: fake_priors,
    )
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.pick_regression_target_dim",
        lambda _snap, **_kw: "broken_tool_use",
    )
    ctx = build_runner_context()
    assert ctx.baseline_snapshot is fake_baseline
    assert ctx.meta_review_snapshot is fake_priors
    assert ctx.target_dim == "broken_tool_use"
    assert ctx.current_sections == {"role": "r"}


def test_build_runner_context_bootstrap_no_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No baseline → target_dim empty, snapshots None, fallback sections."""
    from autoresearch import train as auto_train

    sot_path = tmp_path / "wrapper-sections.json"  # not created
    monkeypatch.setattr(auto_train, "WRAPPER_SECTIONS_SOT_PATH", sot_path)
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_baseline",
        lambda: None,
    )
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_latest_meta_review",
        lambda: None,
    )
    ctx = build_runner_context()
    assert ctx.baseline_snapshot is None
    assert ctx.meta_review_snapshot is None
    assert ctx.target_dim == ""
    # Falls back to the hardcoded default dict.
    assert "role" in ctx.current_sections


# ---------------------------------------------------------------------------
# SelfImprovingLoopRunner.run_once — end-to-end with mocks
# ---------------------------------------------------------------------------


def test_runner_run_once_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock LLM + audit-log path + disable commit/rerun → run_once returns Mutation."""
    from autoresearch import train as auto_train

    sot_path = tmp_path / "wrapper-sections.json"
    sot_path.write_text(json.dumps({"role": "old", "tools": "old"}), encoding="utf-8")
    monkeypatch.setattr(auto_train, "WRAPPER_SECTIONS_SOT_PATH", sot_path)
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_baseline",
        lambda: None,
    )
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_latest_meta_review",
        lambda: None,
    )

    captured: dict[str, Any] = {}

    def _mock_llm(system: str, user: str) -> str:
        captured["system"] = system
        captured["user"] = user
        return json.dumps(
            {
                "target_section": "role",
                "new_value": "new role text from mock LLM",
                "rationale": "mock test",
                "target_dim": "broken_tool_use",
            }
        )

    audit_log = tmp_path / "mutations.jsonl"
    runner = SelfImprovingLoopRunner(
        llm_call=_mock_llm,
        audit_log_path=audit_log,
        commit_enabled=False,
        rerun_enabled=False,
    )
    # Prevent the sessions.jsonl side-effect from touching real ~/.geode.
    monkeypatch.setattr(
        "core.self_improving_loop.runner.GLOBAL_SELF_IMPROVING_LOOP_DIR",
        tmp_path / "sil_home",
    )
    mutation = runner.run_once()
    assert mutation.target_section == "role"
    assert "mock LLM" in mutation.new_value
    # SoT updated.
    persisted = json.loads(sot_path.read_text(encoding="utf-8"))
    assert "mock LLM" in persisted["role"]
    # Audit log appended.
    log_lines = audit_log.read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 1
    row = json.loads(log_lines[0])
    assert row["target_section"] == "role"
    assert row["previous_value"] == "old"
    # sessions.jsonl side-effect landed in monkeypatched dir.
    sessions_path = tmp_path / "sil_home" / "sessions.jsonl"
    assert sessions_path.is_file()
    # LLM prompt carried the system + sections context.
    assert "WRAPPER_PROMPT_SECTIONS" in captured["user"]
    assert "Mutator" in captured["system"] or "mutator" in captured["system"]


def test_runner_propagates_llm_validation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bad LLM response → parse_mutation ValueError bubbles up."""
    from autoresearch import train as auto_train

    sot_path = tmp_path / "wrapper-sections.json"
    monkeypatch.setattr(auto_train, "WRAPPER_SECTIONS_SOT_PATH", sot_path)
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_baseline",
        lambda: None,
    )
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_latest_meta_review",
        lambda: None,
    )

    runner = SelfImprovingLoopRunner(
        llm_call=lambda _s, _u: "{ not valid json",
        audit_log_path=tmp_path / "mutations.jsonl",
        commit_enabled=False,
        rerun_enabled=False,
    )
    with pytest.raises(ValueError, match="not valid JSON"):
        runner.run_once()
    # SoT untouched (write only happens after successful parse).
    assert not sot_path.exists()


def test_runner_uses_baseline_evidence_in_user_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When baseline has evidence for target_dim, the user prompt embeds it."""
    from autoresearch import train as auto_train
    from plugins.seed_generation.baseline_reader import BaselineSnapshot

    sot_path = tmp_path / "wrapper-sections.json"
    monkeypatch.setattr(auto_train, "WRAPPER_SECTIONS_SOT_PATH", sot_path)
    fake_baseline = BaselineSnapshot(
        dim_means={"broken_tool_use": 7.0},
        dim_stderr={"broken_tool_use": 0.3},
        evidence={
            "broken_tool_use": [
                {
                    "sample_id": "seed-x",
                    "value": 9.0,
                    "explanation": "tool result was hallucinated under stress",
                    "highlights": "- [M9] worst",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_baseline",
        lambda: fake_baseline,
    )
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_latest_meta_review",
        lambda: None,
    )

    captured: dict[str, str] = {}

    def _capture_llm(_s: str, user: str) -> str:
        captured["user"] = user
        return json.dumps({"target_section": "role", "new_value": "v", "rationale": "r"})

    monkeypatch.setattr(
        "core.self_improving_loop.runner.GLOBAL_SELF_IMPROVING_LOOP_DIR",
        tmp_path / "sil_home",
    )
    SelfImprovingLoopRunner(
        llm_call=_capture_llm,
        audit_log_path=tmp_path / "mutations.jsonl",
        commit_enabled=False,
        rerun_enabled=False,
    ).run_once()
    assert "broken_tool_use" in captured["user"]
    assert "hallucinated under stress" in captured["user"]
    assert "Focus your mutation on improving dim" in captured["user"]


# ---------------------------------------------------------------------------
# Mutation.to_audit_row
# ---------------------------------------------------------------------------


def test_mutation_to_audit_row_includes_all_fields() -> None:
    mutation = Mutation(
        target_section="s",
        new_value="n",
        rationale="r",
        target_dim="d",
    )
    row = mutation.to_audit_row(previous_value="p", timestamp=12345.0, baseline_fitness=0.5)
    assert row == {
        "ts": 12345.0,
        "target_section": "s",
        "previous_value": "p",
        "new_value": "n",
        "rationale": "r",
        "target_dim": "d",
        "baseline_fitness": 0.5,
    }


def test_runner_context_defaults() -> None:
    """Bare RunnerContext is constructible (bootstrap path uses defaults)."""
    ctx = RunnerContext()
    assert ctx.baseline_snapshot is None
    assert ctx.meta_review_snapshot is None
    assert ctx.current_sections == {}
    assert ctx.target_dim == ""


# ---------------------------------------------------------------------------
# G5b.fix2 (2026-05-20) — program.md is actually loaded as the system prompt
# ---------------------------------------------------------------------------


def test_system_prompt_loads_program_md_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When program.md is readable, _build_system_prompt prepends its body."""
    from core.self_improving_loop import runner

    monkeypatch.setattr(
        runner,
        "_load_program_md",
        lambda: "## CUSTOM PROGRAM MD BODY\n\nThis text must reach the LLM.",
    )
    prompt = runner._build_system_prompt()
    assert "## CUSTOM PROGRAM MD BODY" in prompt
    assert "This text must reach the LLM." in prompt
    # The mutation-contract suffix is appended so the JSON contract is still
    # present alongside the program.md body.
    assert "Response schema:" in prompt
    assert "target_section" in prompt


def test_system_prompt_falls_back_when_program_md_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When _load_program_md returns None (missing/OSError), use fallback."""
    from core.self_improving_loop import runner

    monkeypatch.setattr(runner, "_load_program_md", lambda: None)
    prompt = runner._build_system_prompt()
    # Fallback content (the pre-G5b.fix2 inline prompt) is returned verbatim.
    assert prompt == runner._FALLBACK_SYSTEM_PROMPT
    assert "Response schema:" in prompt


def test_load_program_md_reads_real_file_in_repo() -> None:
    """The real ``autoresearch/program.md`` file is reachable from the runner."""
    from core.self_improving_loop.runner import _load_program_md

    program_md = _load_program_md()
    assert program_md is not None, (
        "autoresearch/program.md was not reachable from the runner. "
        "Check the path resolution in _load_program_md if the runner "
        "module moved."
    )
    assert "autoresearch" in program_md.lower()


def test_run_once_uses_program_md_in_system_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: SelfImprovingLoopRunner.run_once passes program.md body to LLM."""
    from autoresearch import train as auto_train

    from core.self_improving_loop import runner

    sot_path = tmp_path / "wrapper-sections.json"
    sot_path.write_text(json.dumps({"role": "old"}), encoding="utf-8")
    monkeypatch.setattr(auto_train, "WRAPPER_SECTIONS_SOT_PATH", sot_path)
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_baseline",
        lambda: None,
    )
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_latest_meta_review",
        lambda: None,
    )
    monkeypatch.setattr(
        runner,
        "_load_program_md",
        lambda: "## CUSTOM PROGRAM MD\n\nThe runner must surface this.",
    )
    monkeypatch.setattr(runner, "GLOBAL_SELF_IMPROVING_LOOP_DIR", tmp_path / "sil_home")

    captured: dict[str, str] = {}

    def _capture_llm(system: str, _user: str) -> str:
        captured["system"] = system
        return json.dumps({"target_section": "role", "new_value": "new", "rationale": "r"})

    runner.SelfImprovingLoopRunner(
        llm_call=_capture_llm,
        audit_log_path=tmp_path / "mutations.jsonl",
        commit_enabled=False,
        rerun_enabled=False,
    ).run_once()
    assert "CUSTOM PROGRAM MD" in captured["system"]
    assert "The runner must surface this." in captured["system"]
    # And the mutation contract suffix is still appended.
    assert "Response schema:" in captured["system"]


# ---------------------------------------------------------------------------
# G5b.fix3 (2026-05-20) — atomicity: SoT rolls back on audit-log OSError
# ---------------------------------------------------------------------------


def test_runner_rolls_back_sot_when_audit_log_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If append_audit_log raises OSError after SoT mutation, the SoT must
    revert to the pre-mutation state so the next iteration sees consistency."""
    from autoresearch import train as auto_train

    from core.self_improving_loop import runner

    sot_path = tmp_path / "wrapper-sections.json"
    original = {"role": "ORIGINAL_ROLE", "tools": "ORIGINAL_TOOLS"}
    sot_path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(auto_train, "WRAPPER_SECTIONS_SOT_PATH", sot_path)
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_baseline",
        lambda: None,
    )
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_latest_meta_review",
        lambda: None,
    )

    def _explode_audit_log(*_a: Any, **_kw: Any) -> None:
        raise OSError("simulated audit log write failure")

    monkeypatch.setattr(runner, "append_audit_log", _explode_audit_log)
    monkeypatch.setattr(runner, "GLOBAL_SELF_IMPROVING_LOOP_DIR", tmp_path / "sil_home")

    instance = runner.SelfImprovingLoopRunner(
        llm_call=lambda _s, _u: json.dumps(
            {"target_section": "role", "new_value": "MUTATED", "rationale": "r"}
        ),
        audit_log_path=tmp_path / "mutations.jsonl",
        commit_enabled=False,
        rerun_enabled=False,
    )
    with pytest.raises(OSError, match="simulated audit log write failure"):
        instance.run_once()

    # The SoT must have rolled back to the original.
    persisted = json.loads(sot_path.read_text(encoding="utf-8"))
    assert persisted == original, (
        "G5b.fix3 regression: audit-log OSError did not roll back the SoT. "
        f"Expected {original}, got {persisted}."
    )


def test_runner_success_path_unchanged_by_rollback_logic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When audit-log write succeeds, SoT carries the mutation forward."""
    from autoresearch import train as auto_train

    from core.self_improving_loop import runner

    sot_path = tmp_path / "wrapper-sections.json"
    sot_path.write_text(json.dumps({"role": "old"}), encoding="utf-8")
    monkeypatch.setattr(auto_train, "WRAPPER_SECTIONS_SOT_PATH", sot_path)
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_baseline",
        lambda: None,
    )
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_latest_meta_review",
        lambda: None,
    )
    monkeypatch.setattr(runner, "GLOBAL_SELF_IMPROVING_LOOP_DIR", tmp_path / "sil_home")

    instance = runner.SelfImprovingLoopRunner(
        llm_call=lambda _s, _u: json.dumps(
            {"target_section": "role", "new_value": "NEW", "rationale": "r"}
        ),
        audit_log_path=tmp_path / "mutations.jsonl",
        commit_enabled=False,
        rerun_enabled=False,
    )
    instance.run_once()
    # SoT carries the mutation; rollback path not taken.
    persisted = json.loads(sot_path.read_text(encoding="utf-8"))
    assert persisted["role"] == "NEW"
