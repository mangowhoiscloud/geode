"""PR-MUTATION-EMIT-WIRE (2026-05-27) — verify MUTATION_*/BASELINE_PROMOTED
emit at the three lifecycle points the reserve docstring documents.

PR-HOOKEVENT-RESERVE (2026-05-26) added the enum members; this PR is
the writer-side wiring. These tests pin:

- :func:`core.self_improving.loop.mutate.runner.append_audit_log` fires
  ``HookEvent.MUTATION_APPLIED`` with the documented payload schema
  after the row write succeeds.
- :func:`core.self_improving.train._revert_sot_after_reject` fires
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
from core.self_improving import gate, ledger
from core.self_improving.loop._hooks import (
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
    from core.self_improving.loop.mutate.runner import Mutation, append_audit_log

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


def test_write_baseline_emits_baseline_promoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_write_baseline`` fires ``HookEvent.BASELINE_PROMOTED`` after
    ``BASELINE_PATH.write_text`` succeeds with the documented payload
    schema (``baseline_path``, ``prior_baseline_path``, ``ts``,
    ``run_id``, ``reason``). The reason flips to ``operator_force``
    when ``manual_promote=True``, ``gate_approved`` otherwise."""

    hooks = HookSystem()
    captured: list[dict[str, Any]] = []
    hooks.register(
        HookEvent.BASELINE_PROMOTED,
        lambda event, data: captured.append(data),
        name="capture_baseline_promoted",
    )
    set_self_improving_loop_hooks(hooks)

    fake_baseline_path = tmp_path / "baseline.json"
    monkeypatch.setattr(ledger, "BASELINE_PATH", fake_baseline_path)

    # Fresh promote — no prior file.
    ledger._write_baseline(
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
    ledger._write_baseline(
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
    from core.self_improving import train
    from core.self_improving.loop.mutate.runner import Mutation, append_audit_log

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

    success, detail = gate._revert_sot_after_reject("revert-test-mid", audit_log_path=audit_log)
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


def test_rollback_sot_emits_mutation_reverted(monkeypatch: pytest.MonkeyPatch) -> None:
    """PR-MUTATION-REVERTED-ROLLBACK-WIRE (2026-05-27) — when the
    runner's :meth:`_rollback_sot` triggers (audit-log write fails OR
    audit subprocess crashes / exits non-zero), it must fire
    ``HookEvent.MUTATION_REVERTED`` with the caller-supplied
    ``reason`` (``audit_log_write_fail`` / ``audit_subprocess_crash`` /
    ``audit_subprocess_nonzero``) so observability readers can
    distinguish the trigger from the promote-gate reject path."""
    from core.self_improving.loop.mutate.runner import Mutation, SelfImprovingLoopRunner

    hooks = HookSystem()
    captured: list[dict[str, Any]] = []
    hooks.register(
        HookEvent.MUTATION_REVERTED,
        lambda event, data: captured.append(data),
        name="capture_rollback_revert",
    )
    set_self_improving_loop_hooks(hooks)

    written: list[dict[str, str]] = []
    monkeypatch.setattr(
        "core.self_improving.train.write_wrapper_prompt_sections",
        lambda sections: written.append(dict(sections)),
    )

    mutation = Mutation(
        mutation_id="rollback-mid",
        target_kind="prompt",
        target_section="evolver.system",
        new_value="newval",
        rationale="rollback test",
        target_dim="dim_z",
    )

    # Simulate the audit-log-write-fail caller (OSError branch).
    SelfImprovingLoopRunner._rollback_sot(
        {"evolver.system": "pre-mutation"},
        mutation=mutation,
        exc=OSError("disk full"),
        audit_run_id="audit-osfail-1",
        reason="audit_log_write_fail",
    )
    assert written == [{"evolver.system": "pre-mutation"}]
    assert len(captured) == 1
    payload = captured[0]
    assert payload["mutation_id"] == "rollback-mid"
    assert payload["target_kind"] == "prompt"
    assert payload["target_path"] == "prompt.evolver.system"
    assert payload["reason"] == "audit_log_write_fail"
    assert payload["run_id"] == "audit-osfail-1"

    # Simulate the audit-subprocess-crash caller — same function, different reason.
    SelfImprovingLoopRunner._rollback_sot(
        {"evolver.system": "pre-mutation"},
        mutation=mutation,
        exc=RuntimeError("subprocess died"),
        audit_run_id="audit-crash-2",
        reason="audit_subprocess_crash",
    )
    assert len(captured) == 2
    assert captured[1]["reason"] == "audit_subprocess_crash"
    assert captured[1]["run_id"] == "audit-crash-2"

    # Default reason path (caller didn't thread one) — must still emit
    # so listeners are not silently dropped.
    SelfImprovingLoopRunner._rollback_sot(
        {"evolver.system": "pre-mutation"},
        mutation=mutation,
        exc=Exception("unknown"),
    )
    assert len(captured) == 3
    assert captured[2]["reason"] == "post_apply_failure"
    assert captured[2]["run_id"] == ""


def test_rollback_sot_policy_kind_emits_mutation_reverted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex MCP fold — also cover the non-prompt branch
    (``write_policy``). The original ``test_rollback_sot_emits_mutation_reverted``
    only stubbed ``write_wrapper_prompt_sections`` so the
    ``write_policy`` half of the dispatch was uncovered."""
    from core.self_improving.loop.mutate.runner import Mutation, SelfImprovingLoopRunner

    hooks = HookSystem()
    captured: list[dict[str, Any]] = []
    hooks.register(
        HookEvent.MUTATION_REVERTED,
        lambda event, data: captured.append(data),
        name="capture_policy_rollback",
    )
    set_self_improving_loop_hooks(hooks)

    written: list[tuple[str, dict[str, str]]] = []
    monkeypatch.setattr(
        "core.self_improving.loop.mutate.policies.write_policy",
        lambda kind, sections: written.append((kind, dict(sections))),
    )

    mutation = Mutation(
        mutation_id="policy-rollback-mid",
        target_kind="tool_policy",
        target_section="lane_caps",
        new_value="newval",
        rationale="policy rollback test",
        target_dim="dim_a",
    )
    SelfImprovingLoopRunner._rollback_sot(
        {"lane_caps": "prior"},
        mutation=mutation,
        exc=OSError("disk full"),
        audit_run_id="audit-policy-rb",
        reason="audit_log_write_fail",
    )
    assert written == [("tool_policy", {"lane_caps": "prior"})]
    assert len(captured) == 1
    assert captured[0]["target_kind"] == "tool_policy"
    assert captured[0]["reason"] == "audit_log_write_fail"


def test_propose_emits_mutation_proposed(monkeypatch: pytest.MonkeyPatch) -> None:
    """PR-MUTATION-PROPOSED-WIRE (2026-05-27) —
    :meth:`SelfImprovingLoopRunner.propose` emits ``MUTATION_PROPOSED``
    after the proposal is built (LLM parse + dedup gate + SoT load
    succeeded) but BEFORE any apply. Payload uses the same schema as
    the other MUTATION_* variants; ``run_id`` is empty because the
    audit_run_id is minted later in apply_proposal."""
    import json

    from core.self_improving.loop.mutate.runner import SelfImprovingLoopRunner

    hooks = HookSystem()
    captured: list[dict[str, Any]] = []
    hooks.register(
        HookEvent.MUTATION_PROPOSED,
        lambda event, data: captured.append(data),
        name="capture_mutation_proposed",
    )
    set_self_improving_loop_hooks(hooks)

    # Stub the LLM call + context build so we don't hit real models or files.
    canned_response = json.dumps(
        {
            "mutation_id": "proposed-mid",
            "target_kind": "prompt",
            "target_section": "evolver.system",
            "new_value": "new prompt body",
            "rationale": "test propose emit",
            "target_dim": "dim_x",
            "expected_dim": "dim_x",
        }
    )

    def _stub_llm(system: str, user: str) -> str:
        return canned_response

    from core.self_improving.loop.mutate import runner as runner_mod

    stub_ctx = runner_mod.RunnerContext(
        current_sections={"evolver.system": "old prompt"},
        current_policies={"prompt": {"evolver.system": "old prompt"}},
    )
    monkeypatch.setattr(runner_mod, "build_runner_context", lambda: stub_ctx)

    sil = SelfImprovingLoopRunner(llm_call=_stub_llm)
    proposal = sil.propose()

    assert proposal.mutation.mutation_id == "proposed-mid"
    assert len(captured) == 1
    payload = captured[0]
    assert payload["mutation_id"] == "proposed-mid"
    assert payload["target_kind"] == "prompt"
    assert payload["target_path"] == "prompt.evolver.system"
    assert payload["run_id"] == ""  # not minted yet at propose time
    assert isinstance(payload["ts"], float)


def test_rollback_sot_no_emit_when_rollback_write_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex MCP fold — the emit must be INSIDE the try block so a
    rollback-write failure (rare: disk full while writing the rollback
    itself) short-circuits BEFORE emit. Otherwise listeners would see
    a 'reverted' signal when the SoT is actually divergent."""
    from core.self_improving.loop.mutate.runner import Mutation, SelfImprovingLoopRunner

    hooks = HookSystem()
    captured: list[dict[str, Any]] = []
    hooks.register(
        HookEvent.MUTATION_REVERTED,
        lambda event, data: captured.append(data),
        name="capture_no_emit_on_writer_fail",
    )
    set_self_improving_loop_hooks(hooks)

    def _writer_fails(sections: dict[str, str]) -> None:
        raise OSError("rollback writer disk full")

    monkeypatch.setattr("core.self_improving.train.write_wrapper_prompt_sections", _writer_fails)

    mutation = Mutation(
        mutation_id="writer-fail-mid",
        target_kind="prompt",
        target_section="evolver.system",
        new_value="newval",
        rationale="writer-fail test",
        target_dim="dim_b",
    )
    # ``_rollback_sot`` swallows the writer failure (logged, not raised)
    # so the call returns normally. The pin is on the emit side: NO
    # event captured.
    SelfImprovingLoopRunner._rollback_sot(
        {"evolver.system": "prior"},
        mutation=mutation,
        exc=OSError("original audit-log fail"),
        audit_run_id="audit-doomed",
        reason="audit_log_write_fail",
    )
    assert captured == []


def test_reject_and_revert_emits_mutation_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """PR-AUDIT-AB — the gate/policy reject path fires MUTATION_REJECTED
    (the loop's dominant outcome finally has telemetry) BEFORE the SoT
    revert, with the documented payload schema."""

    captured: list[tuple[HookEvent, dict[str, Any]]] = []
    hooks = HookSystem()
    hooks.register(
        HookEvent.MUTATION_REJECTED,
        lambda event, data: captured.append((event, data)),
        name="rejected_probe",
    )
    set_self_improving_loop_hooks(hooks)

    monkeypatch.setenv("GEODE_SIL_MUTATION_ID", "mut-reject-1")
    monkeypatch.setenv("GEODE_SIL_AUDIT_RUN_ID", "run-77")
    monkeypatch.setattr(gate, "_revert_sot_after_reject", lambda mid: (True, "reverted-ok"))

    reason = gate._reject_and_revert("margin below floor", rejected_by="gate")

    assert reason == "margin below floor; SoT reverted (reverted-ok)"
    assert len(captured) == 1
    _event, payload = captured[0]
    assert payload["mutation_id"] == "mut-reject-1"
    assert payload["run_id"] == "run-77"
    assert payload["reason"] == "margin below floor"
    assert payload["rejected_by"] == "gate"


def test_reject_and_revert_no_emit_without_mutation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manual audits (no GEODE_SIL_MUTATION_ID) have no mutation to
    reject — no emit, reason unchanged."""

    captured: list[Any] = []
    hooks = HookSystem()
    hooks.register(
        HookEvent.MUTATION_REJECTED,
        lambda event, data: captured.append(data),
        name="rejected_probe",
    )
    set_self_improving_loop_hooks(hooks)

    monkeypatch.delenv("GEODE_SIL_MUTATION_ID", raising=False)
    reason = gate._reject_and_revert("manual reject", rejected_by="gate")

    assert reason == "manual reject"
    assert captured == []
