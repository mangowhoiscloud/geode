"""PR-MUTATION-EMIT-WIRE (2026-05-27) — verify MUTATION_*/BASELINE_PROMOTED
emit at the three lifecycle points the reserve docstring documents.

PR-HOOKEVENT-RESERVE (2026-05-26) added the enum members; this PR is
the writer-side wiring. These tests pin:

- :func:`core.self_improving_loop.runner.append_audit_log` fires
  ``HookEvent.MUTATION_APPLIED`` with the documented payload schema
  after the row write succeeds.
- :func:`autoresearch.train._revert_sot_after_reject` fires
  ``HookEvent.MUTATION_REVERTED`` with ``reason="promote_gate_reject"``
  after the SoT roll-back succeeds.
- The ``set_self_improving_loop_hooks`` setter installs a no-op
  context until called (lazy-wire contract identical to
  ``core.llm.router._hooks``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from core.hooks.system import HookEvent, HookSystem
from core.self_improving_loop._hooks import (
    _fire_hook,
    set_self_improving_loop_hooks,
)


@pytest.fixture(autouse=True)
def _reset_hooks_ctx() -> Any:
    """Drop the module-level ``_hooks_ctx`` between tests so the lazy
    no-op contract is honored at each test's entry."""
    set_self_improving_loop_hooks(None)
    yield
    set_self_improving_loop_hooks(None)


def test_fire_hook_is_noop_when_unwired() -> None:
    """Until ``set_self_improving_loop_hooks`` fires with a real
    HookSystem, every ``_fire_hook`` call must be a silent no-op
    (cold-start import, unit-test isolation)."""
    _fire_hook(
        HookEvent.MUTATION_APPLIED,
        {"mutation_id": "test-no-op", "target_kind": "prompt"},
    )


def test_fire_hook_dispatches_when_wired() -> None:
    """After the setter installs a HookSystem, ``_fire_hook``
    dispatches the event to registered handlers."""
    hooks = HookSystem()
    captured: list[tuple[HookEvent, dict[str, Any]]] = []

    def _capture(event: HookEvent, data: dict[str, Any]) -> None:
        captured.append((event, data))

    hooks.register(HookEvent.MUTATION_APPLIED, _capture, name="test_capture")
    set_self_improving_loop_hooks(hooks)

    _fire_hook(
        HookEvent.MUTATION_APPLIED,
        {"mutation_id": "wired-mid", "target_kind": "prompt", "ts": 1.0},
    )
    assert len(captured) == 1
    event, data = captured[0]
    assert event == HookEvent.MUTATION_APPLIED
    assert data["mutation_id"] == "wired-mid"


def test_append_audit_log_emits_mutation_applied(tmp_path: Path) -> None:
    """``append_audit_log`` fires ``HookEvent.MUTATION_APPLIED`` with the
    documented payload schema (mutation_id, target_kind, target_path,
    ts, run_id, kind) after the row write completes."""
    from core.self_improving_loop.runner import Mutation, append_audit_log

    hooks = HookSystem()
    captured: list[dict[str, Any]] = []
    hooks.register(
        HookEvent.MUTATION_APPLIED,
        lambda event, data: captured.append(data),
        name="capture_mutation_applied",
    )
    set_self_improving_loop_hooks(hooks)

    mutation = Mutation(
        mutation_id="test-mid-001",
        target_kind="prompt",
        target_section="evolver.system",
        new_value="updated value",
        rationale="unit test rationale",
        target_dim="dim_x",
    )
    log_path = tmp_path / "mutations.jsonl"
    returned = append_audit_log(
        mutation,
        previous_value="previous value",
        log_path=log_path,
        audit_run_id="run-abc-123",
        kind="applied",
    )

    # Row write succeeded
    assert returned == log_path
    rows = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["mutation_id"] == "test-mid-001"

    # Emit happened with the documented schema
    assert len(captured) == 1
    payload = captured[0]
    assert payload["mutation_id"] == "test-mid-001"
    assert payload["target_kind"] == "prompt"
    assert payload["target_path"] == str(log_path)
    assert payload["run_id"] == "run-abc-123"
    assert payload["kind"] == "applied"
    assert isinstance(payload["ts"], float)


def test_append_audit_log_emit_sibling_kind(tmp_path: Path) -> None:
    """Sibling rows (``kind="applied_sibling"``) also emit MUTATION_APPLIED
    — listeners distinguish by the ``kind`` extra field. group sampling
    + dedup-detection downstream readers need the sibling rows."""
    from core.self_improving_loop.runner import Mutation, append_audit_log

    hooks = HookSystem()
    captured: list[dict[str, Any]] = []
    hooks.register(
        HookEvent.MUTATION_APPLIED,
        lambda event, data: captured.append(data),
        name="capture_sibling_kind",
    )
    set_self_improving_loop_hooks(hooks)

    mutation = Mutation(
        mutation_id="sibling-mid",
        target_kind="tool_policy",
        target_section="some_section",
        new_value="value",
        rationale="sibling sample",
        target_dim="dim_y",
    )
    append_audit_log(
        mutation,
        previous_value="",
        log_path=tmp_path / "mutations.jsonl",
        audit_run_id="sibling-run-id",
        kind="applied_sibling",
        group_id="group-001",
        group_advantage=0.1,
    )
    assert len(captured) == 1
    assert captured[0]["kind"] == "applied_sibling"
    assert captured[0]["target_kind"] == "tool_policy"


def test_write_baseline_emits_baseline_promoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_write_baseline`` fires ``HookEvent.BASELINE_PROMOTED`` after
    ``BASELINE_PATH.write_text`` succeeds with the documented payload
    schema (``baseline_path``, ``prior_baseline_path``, ``ts``,
    ``run_id``, ``reason``). The reason flips to ``operator_force``
    when ``manual_promote=True``, ``gate_approved`` otherwise."""
    from autoresearch import train

    hooks = HookSystem()
    captured: list[dict[str, Any]] = []
    hooks.register(
        HookEvent.BASELINE_PROMOTED,
        lambda event, data: captured.append(data),
        name="capture_baseline_promoted",
    )
    set_self_improving_loop_hooks(hooks)

    fake_baseline_path = tmp_path / "baseline.json"
    monkeypatch.setattr(train, "BASELINE_PATH", fake_baseline_path)

    # Fresh promote — no prior file.
    train._write_baseline(
        dim_means={"axis_a": 0.5},
        dim_stderr={"axis_a": 0.1},
        session_id="session-001",
        commit="abc1234",
        manual_promote=False,
    )
    assert fake_baseline_path.exists()
    assert len(captured) == 1
    payload = captured[0]
    assert payload["baseline_path"] == str(fake_baseline_path)
    assert payload["prior_baseline_path"] == ""  # fresh — no prior
    assert payload["run_id"] == "session-001"
    assert payload["reason"] == "gate_approved"
    assert isinstance(payload["ts"], float)

    # Overwrite — prior path populated.
    train._write_baseline(
        dim_means={"axis_a": 0.6},
        dim_stderr={"axis_a": 0.1},
        session_id="session-002",
        commit="def5678",
        manual_promote=True,
    )
    assert len(captured) == 2
    second = captured[1]
    assert second["prior_baseline_path"] == str(fake_baseline_path)
    assert second["reason"] == "operator_force"
    assert second["run_id"] == "session-002"


def test_revert_sot_after_reject_emits_mutation_reverted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_revert_sot_after_reject`` fires ``HookEvent.MUTATION_REVERTED``
    with ``reason="promote_gate_reject"`` after the SoT roll-back
    succeeds. ``run_id`` carries ``GEODE_SIL_AUDIT_RUN_ID`` (the
    audit correlation key), NOT the mutation_id."""
    from core.self_improving_loop.runner import Mutation, append_audit_log

    from autoresearch import train

    # Seed a mutations.jsonl row that the revert function can look up.
    audit_log = tmp_path / "mutations.jsonl"
    seeded_mutation = Mutation(
        mutation_id="revert-test-mid",
        target_kind="prompt",
        target_section="evolver.system",
        new_value="new-value",
        rationale="seed for revert",
        target_dim="dim_x",
    )
    # We have to wire the hooks *after* the seed write so the
    # MUTATION_APPLIED emit doesn't pollute the captured-reverted list.
    set_self_improving_loop_hooks(None)
    append_audit_log(
        seeded_mutation,
        previous_value="prior-value",
        log_path=audit_log,
        audit_run_id="audit-run-xyz",
        kind="applied",
    )

    # Stub the SoT load + write so we don't touch real ~/.geode files.
    monkeypatch.setattr(
        train, "load_wrapper_prompt_sections", lambda: {"evolver.system": "new-value"}
    )
    written: list[dict[str, str]] = []
    monkeypatch.setattr(
        train, "write_wrapper_prompt_sections", lambda sections: written.append(dict(sections))
    )

    # Audit run ID env (matches what the runner sets when spawning the
    # audit subprocess).
    monkeypatch.setenv("GEODE_SIL_AUDIT_RUN_ID", "audit-run-xyz")

    # Now wire hooks and call the revert.
    hooks = HookSystem()
    captured: list[dict[str, Any]] = []
    hooks.register(
        HookEvent.MUTATION_REVERTED,
        lambda event, data: captured.append(data),
        name="capture_mutation_reverted",
    )
    set_self_improving_loop_hooks(hooks)

    success, detail = train._revert_sot_after_reject("revert-test-mid", audit_log_path=audit_log)
    assert success
    assert detail == "prompt.evolver.system"
    # SoT write happened (prior-value restored)
    assert written == [{"evolver.system": "prior-value"}]
    # Emit happened with correct schema
    assert len(captured) == 1
    payload = captured[0]
    assert payload["mutation_id"] == "revert-test-mid"
    assert payload["target_kind"] == "prompt"
    assert payload["target_path"] == "prompt.evolver.system"
    assert payload["reason"] == "promote_gate_reject"
    assert payload["run_id"] == "audit-run-xyz"  # audit_run_id, NOT mutation_id
    assert isinstance(payload["ts"], float)
