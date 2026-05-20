"""Invariants for the ``/self-improving`` slash command (PR-OPS-1).

Pins the registry wiring (routing + COMMAND_MAP + dispatcher), the
status sub-action output shape (baseline block + mutations block),
and the not-yet-wired hints for deferred sub-actions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Registry wiring — slash must resolve to a handler
# ---------------------------------------------------------------------------


def test_self_improving_registered_in_command_registry() -> None:
    from core.cli.routing import COMMAND_REGISTRY, RunLocation

    spec = COMMAND_REGISTRY.get("/self-improving")
    assert spec is not None
    assert spec.location is RunLocation.THIN
    assert spec.handler_path == "core.cli.commands.self_improving:cmd_self_improving"


def test_sil_alias_resolves_to_self_improving() -> None:
    from core.cli.routing import lookup

    spec_via_alias = lookup("/sil")
    spec_canonical = lookup("/self-improving")
    assert spec_via_alias is not None
    assert spec_canonical is not None
    assert spec_via_alias.name == spec_canonical.name == "/self-improving"


def test_self_improving_in_command_map() -> None:
    """Both ``/self-improving`` and ``/sil`` must map to the same action
    string the dispatcher branches on."""
    from core.cli.commands._state import COMMAND_MAP

    assert COMMAND_MAP["/self-improving"] == "self-improving"
    assert COMMAND_MAP["/sil"] == "self-improving"


# ---------------------------------------------------------------------------
# Default action — no args dispatches to status
# ---------------------------------------------------------------------------


def test_no_args_dispatches_to_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/self-improving`` (empty args) must behave as ``status``."""
    from core.cli.commands import self_improving

    called: list[bool] = []

    def _fake_status() -> None:
        called.append(True)

    monkeypatch.setattr(self_improving, "_cmd_status", _fake_status)
    self_improving.cmd_self_improving("")
    assert called == [True]


def test_status_action_dispatches_to_status(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.cli.commands import self_improving

    called: list[bool] = []
    monkeypatch.setattr(self_improving, "_cmd_status", lambda: called.append(True))
    self_improving.cmd_self_improving("status")
    assert called == [True]


# ---------------------------------------------------------------------------
# Reserved sub-actions — print deferred-to-PR-OPS-2/3 hint
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["run", "history", "rollback", "config"])
def test_reserved_actions_emit_design_doc_hint(
    action: str, capsys: pytest.CaptureFixture[str]
) -> None:
    from core.cli.commands.self_improving import cmd_self_improving

    cmd_self_improving(action)
    out = capsys.readouterr().out
    assert "PR-OPS-2/3" in out
    assert "self-improving-loop-ux.md" in out


def test_unknown_action_emits_help_hint(capsys: pytest.CaptureFixture[str]) -> None:
    from core.cli.commands.self_improving import cmd_self_improving

    cmd_self_improving("nonsense-action")
    out = capsys.readouterr().out
    assert "Unknown action" in out
    assert "status" in out  # currently-available action listed


# ---------------------------------------------------------------------------
# Status output — empty-state safety
# ---------------------------------------------------------------------------


def test_status_with_no_baseline_and_no_mutations(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Fresh clone: neither baseline.json nor mutations.jsonl exists.
    Status must render empty-state hints, NOT raise."""
    fake_audit = tmp_path / "autoresearch" / "state" / "mutations.jsonl"
    fake_audit.parent.mkdir(parents=True)
    # don't create the file — empty-state path
    monkeypatch.setattr(
        "core.self_improving_loop.runner.MUTATION_AUDIT_LOG_PATH",
        fake_audit,
    )
    from core.cli.commands.self_improving import _cmd_status

    _cmd_status()
    out = capsys.readouterr().out
    assert "no baseline yet" in out
    assert "no mutations recorded" in out


def test_status_renders_baseline_block(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "autoresearch" / "state"
    state_dir.mkdir(parents=True)
    baseline_path = state_dir / "baseline.json"
    fake_audit = state_dir / "mutations.jsonl"
    baseline_path.write_text(
        json.dumps(
            {
                "fitness": 0.7345,
                "timestamp": "2026-05-21T12:34:56",
                "promote_reason": "fitness 0.7100 → 0.7345 (margin 0.0500)",
            }
        ),
        encoding="utf-8",
    )
    fake_audit.touch()
    monkeypatch.setattr(
        "core.self_improving_loop.runner.MUTATION_AUDIT_LOG_PATH",
        fake_audit,
    )
    from core.cli.commands.self_improving import _cmd_status

    _cmd_status()
    out = capsys.readouterr().out
    assert "0.7345" in out
    assert "2026-05-21T12:34:56" in out
    assert "fitness 0.7100" in out


def test_status_renders_recent_mutations(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "autoresearch" / "state"
    state_dir.mkdir(parents=True)
    fake_audit = state_dir / "mutations.jsonl"
    rows = [
        {
            "ts": "2026-05-21T10:00:00",
            "mutation_id": "mut-abc123",
            "kind": "applied",
            "target_kind": "tool_policy",
            "target_section": "delegate_task.priority",
        },
        {
            "ts": "2026-05-21T11:00:00",
            "mutation_id": "mut-def456",
            "kind": "rejected",
            "target_kind": "prompt",
            "target_section": "role.intro",
        },
    ]
    fake_audit.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "core.self_improving_loop.runner.MUTATION_AUDIT_LOG_PATH",
        fake_audit,
    )
    from core.cli.commands.self_improving import _cmd_status

    _cmd_status()
    out = capsys.readouterr().out
    assert "applied" in out
    assert "rejected" in out
    assert "mut-abc123" in out
    assert "mut-def456" in out
    assert "tool_policy.delegate_task.priority" in out
    assert "prompt.role.intro" in out


def test_status_tolerates_malformed_baseline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """A truncated JSON write (mid-promote) must not crash status."""
    state_dir = tmp_path / "autoresearch" / "state"
    state_dir.mkdir(parents=True)
    baseline_path = state_dir / "baseline.json"
    fake_audit = state_dir / "mutations.jsonl"
    baseline_path.write_text("{not valid json", encoding="utf-8")
    fake_audit.touch()
    monkeypatch.setattr(
        "core.self_improving_loop.runner.MUTATION_AUDIT_LOG_PATH",
        fake_audit,
    )
    from core.cli.commands.self_improving import _cmd_status

    _cmd_status()
    out = capsys.readouterr().out
    assert "no baseline yet" in out


def test_status_tolerates_partial_jsonl_row(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """The audit ledger is append-only, so a partial final row during
    concurrent write must not crash status."""
    state_dir = tmp_path / "autoresearch" / "state"
    state_dir.mkdir(parents=True)
    fake_audit = state_dir / "mutations.jsonl"
    good_row: dict[str, Any] = {
        "ts": "2026-05-21T10:00:00",
        "mutation_id": "mut-xyz789",
        "kind": "applied",
        "target_kind": "retrieval",
        "target_section": "top_k.embedding",
    }
    fake_audit.write_text(
        json.dumps(good_row) + "\n{not-valid-json-truncated\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "core.self_improving_loop.runner.MUTATION_AUDIT_LOG_PATH",
        fake_audit,
    )
    from core.cli.commands.self_improving import _cmd_status

    _cmd_status()
    out = capsys.readouterr().out
    assert "mut-xyz789" in out
    # malformed row silently skipped — never appears in output
    assert "not-valid-json" not in out


# ---------------------------------------------------------------------------
# Frontmatter schema parity — co-scientist generator emits Petri-compatible tags
# ---------------------------------------------------------------------------


def test_seed_generator_contract_requires_tags_field() -> None:
    """The seed_generator agent contract (`.claude/agents/seed_generator.md`)
    must require BOTH the co-scientist canonical ``target_dims`` field and
    a Petri-compatible ``tags`` field so a mixed pool (seed_generation
    survivors + plugins/petri_audit/seeds/) keeps dim attribution
    readable by both consumers."""
    from core.paths import get_project_root

    contract = (get_project_root() / ".claude" / "agents" / "seed_generator.md").read_text(
        encoding="utf-8"
    )
    assert "`target_dims`" in contract
    assert "`tags`" in contract
    assert "Petri" in contract  # rationale must be documented in the contract


def test_generator_description_includes_tags_hint() -> None:
    """The per-spawn description prompt must remind the sub-agent to
    emit ``tags`` so the agent has a concrete instruction even without
    re-reading the system prompt."""
    import inspect

    from plugins.seed_generation.agents import generator

    src = inspect.getsource(generator.Generator._build_description)
    assert "tags" in src
    assert "geode_specific" in src
