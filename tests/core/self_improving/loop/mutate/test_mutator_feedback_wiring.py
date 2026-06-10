"""PR-MUTATOR-HISTORY-FEEDBACK + PR-MUTATOR-DEDUP-GUARD (2026-05-27)
— runner integration tests (Codex MCP review fix-up).

Pure-helper tests live in ``test_mutator_feedback.py``. This file
exercises the *wiring*: ``build_runner_context`` honours the config
windows, ``_build_user_prompt`` injects the feedback block, and
``SelfImprovingLoopRunner.propose`` raises ``RepetitiveMutationError``
without writing to any SoT.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture()
def isolated_mutator_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Path]]:
    """Point every SoT / audit log at a clean tmp dir + neutralise the
    baseline / meta-review / wrapper readers so ``build_runner_context``
    runs deterministically without touching the operator's home dir.
    """
    audit_log = tmp_path / "mutations.jsonl"
    wrapper_path = tmp_path / "wrapper-sections.json"
    wrapper_path.write_text(json.dumps({"role": "Be concise."}), encoding="utf-8")

    # Force the runner's audit log location.
    monkeypatch.setattr("core.self_improving.loop.mutate.runner.MUTATION_AUDIT_LOG_PATH", audit_log)
    monkeypatch.setattr(
        "core.self_improving.loop.observe.mutations_reader.MUTATION_AUDIT_LOG_PATH",
        audit_log,
    )

    # Neutralise the upstream readers — RunnerContext fields we don't
    # care about default to None / empty.
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_baseline",
        lambda: None,
    )
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_latest_meta_review",
        lambda: None,
    )
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.pick_regression_target_dim",
        lambda _snapshot: "",
    )
    monkeypatch.setattr(
        "core.self_improving.train.load_wrapper_prompt_sections",
        lambda: {"role": "Be concise."},
    )

    # Neutralise non-prompt policy reads — return empty so the test
    # focuses on history feedback / dedup, not policy surface size.
    monkeypatch.setattr(
        "core.self_improving.loop.mutate.policies.load_policy",
        lambda kind: {} if kind != "prompt" else {"role": "Be concise."},
    )

    yield {"audit_log": audit_log, "wrapper": wrapper_path}


def _write_apply_row(
    audit_log: Path,
    *,
    mutation_id: str,
    target_kind: str = "prompt",
    target_section: str = "role",
    new_value: str = "Be concise.",
    expected_dim: dict[str, float] | None = None,
) -> None:
    """Helper — append an ``applied`` row to ``mutations.jsonl``."""
    row: dict[str, object] = {
        "ts": 1779800000.0,
        "kind": "applied",
        "mutation_id": mutation_id,
        "target_kind": target_kind,
        "target_section": target_section,
        "previous_value": "",
        "new_value": new_value,
        "rationale": "",
        "target_dim": "",
        "expected_dim": expected_dim or {},
        "rollback_condition": "",
        "baseline_fitness": None,
    }
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    with audit_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _write_attribution_row(
    audit_log: Path,
    *,
    mutation_id: str,
    observed_dim: dict[str, float],
    attribution_score: float = 1.0,
) -> None:
    """Helper — append an ``attribution`` row to ``mutations.jsonl``.

    The feedback block's kind × dim matrix needs a matched apply +
    attribution pair on ``mutation_id`` to produce a non-empty rollup.
    """
    row: dict[str, object] = {
        "ts": 1779800001.0,
        "kind": "attribution",
        "mutation_id": mutation_id,
        "observed_dim": observed_dim,
        "ci95": dict.fromkeys(observed_dim, 0.05),
        "significant": dict.fromkeys(observed_dim, True),
        "attribution_score": attribution_score,
        "missing_baseline": False,
    }
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    with audit_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _patch_config(
    monkeypatch: pytest.MonkeyPatch,
    *,
    feedback_window: int,
    dedup_window: int,
    dedup_threshold: float = 0.85,
) -> None:
    """Force the loader to return a config with specific windows.

    Avoids touching ``~/.geode/config.toml``."""
    from core.config.self_improving import (
        AutoresearchConfig,
        SelfImprovingLoopConfig,
    )

    def _fake_loader(_path: object = None) -> SelfImprovingLoopConfig:
        cfg = SelfImprovingLoopConfig()
        cfg.autoresearch = AutoresearchConfig(
            mutator_feedback_window=feedback_window,
            mutator_dedup_window=dedup_window,
            mutator_dedup_threshold=dedup_threshold,
        )
        return cfg

    monkeypatch.setattr(
        "core.config.self_improving.load_self_improving_loop_config",
        _fake_loader,
    )


def test_build_runner_context_disables_feedback_when_window_zero(
    isolated_mutator_state: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``mutator_feedback_window=0`` the context's
    ``mutator_feedback_block`` is empty and the user prompt drops it."""
    from core.self_improving.loop.mutate.runner import (
        _build_user_prompt,
        build_runner_context,
    )

    _patch_config(monkeypatch, feedback_window=0, dedup_window=0)
    _write_apply_row(
        isolated_mutator_state["audit_log"],
        mutation_id="m1",
        expected_dim={"safety": 0.5},
    )

    ctx = build_runner_context()
    assert ctx.mutator_feedback_block == ""
    assert ctx.recent_applies_for_dedup == ()
    assert "Recent mutation feedback" not in _build_user_prompt(ctx)


def test_build_runner_context_populates_feedback_block_when_enabled(
    isolated_mutator_state: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``mutator_feedback_window>0`` and a matched apply +
    attribution pair, the user prompt surfaces the kind × dim feedback
    block."""
    from core.self_improving.loop.mutate.runner import (
        _build_user_prompt,
        build_runner_context,
    )

    _patch_config(monkeypatch, feedback_window=5, dedup_window=0)
    _write_apply_row(
        isolated_mutator_state["audit_log"],
        mutation_id="m1",
        expected_dim={"safety": 1.0},
    )
    _write_attribution_row(
        isolated_mutator_state["audit_log"],
        mutation_id="m1",
        observed_dim={"safety": 0.6},
    )

    ctx = build_runner_context()
    assert "Recent mutation feedback" in ctx.mutator_feedback_block
    assert "safety" in ctx.mutator_feedback_block
    assert "Recent mutation feedback" in _build_user_prompt(ctx)


def test_build_runner_context_populates_dedup_window_independent_of_feedback(
    isolated_mutator_state: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two windows are independent — feedback can be off while
    dedup is on. Pins the conditional-read parity that Codex MCP
    flagged: the runner must populate ``recent_applies_for_dedup``
    even when ``feedback_window=0``."""
    from core.self_improving.loop.mutate.runner import build_runner_context

    _patch_config(monkeypatch, feedback_window=0, dedup_window=5)
    _write_apply_row(isolated_mutator_state["audit_log"], mutation_id="m1")

    ctx = build_runner_context()
    assert ctx.mutator_feedback_block == ""
    assert len(ctx.recent_applies_for_dedup) == 1
    assert ctx.recent_applies_for_dedup[0].mutation_id == "m1"


def test_propose_raises_repetitive_mutation_error_without_sot_write(
    isolated_mutator_state: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the mock LLM echoes a near-identical prior apply, ``propose``
    raises ``RepetitiveMutationError`` and the wrapper SoT is left
    untouched (no SoT write happened — only ``apply_proposal`` would
    persist)."""
    from core.self_improving.loop.mutate.mutator_feedback import RepetitiveMutationError
    from core.self_improving.loop.mutate.runner import SelfImprovingLoopRunner

    _patch_config(monkeypatch, feedback_window=0, dedup_window=10, dedup_threshold=0.85)
    audit_log = isolated_mutator_state["audit_log"]
    _write_apply_row(
        audit_log,
        mutation_id="m1",
        target_kind="prompt",
        target_section="role",
        new_value="Be concise and explicit.",
    )

    def _fake_llm(_system: str, _user: str) -> str:
        return json.dumps(
            {
                "target_section": "role",
                "new_value": "Be concise and very explicit.",
                "rationale": "iterate on conciseness",
                "target_dim": "",
                "target_kind": "prompt",
                "expected_dim": {},
            }
        )

    wrapper = isolated_mutator_state["wrapper"]
    pre_wrapper_content = wrapper.read_text(encoding="utf-8")

    runner = SelfImprovingLoopRunner(llm_call=_fake_llm)
    with pytest.raises(RepetitiveMutationError):
        runner.propose()

    # SoT untouched — propose() never writes; the dedup raise happened
    # before any apply path.
    assert wrapper.read_text(encoding="utf-8") == pre_wrapper_content
