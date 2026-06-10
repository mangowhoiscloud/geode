"""PR-G4 — ``/self-improving run`` summary now carries source telemetry.

Pins:
- The final summary line includes ``model=...`` and ``source=...``.
- ``_resolve_run_summary_telemetry`` resolves model with G1a inherit
  (None default_model → Settings.model).
- The resolver returns ``("?", "?")`` on config-import failure rather
  than crashing the slash.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _stub_runner_proposal() -> tuple[MagicMock, MagicMock]:
    from core.self_improving.loop.mutate.runner import Mutation, Proposal

    mutation = Mutation(
        target_section="role.intro",
        new_value="improved",
        rationale="test",
        target_kind="prompt",
    )
    proposal = Proposal(
        mutation=mutation,
        target_sections={"role.intro": "baseline"},
        original_sections={"role.intro": "baseline"},
        baseline_fitness=0.7,
    )
    runner = MagicMock()
    runner.audit_log_path = Path("/tmp/dummy.jsonl")  # noqa: S108 — test stub
    runner.propose.return_value = proposal
    runner.apply_proposal.return_value = mutation
    return runner, proposal


def test_summary_line_includes_model_and_source(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """After ``y`` confirmation, the summary line must surface
    ``model=...`` and ``source=...`` so the operator knows which
    channel was billed."""
    from core.cli.commands import self_improving

    runner, _ = _stub_runner_proposal()
    monkeypatch.setattr(self_improving, "_build_runner", lambda: runner)
    monkeypatch.setattr(self_improving, "_prompt_confirmation", lambda _p: "apply")
    monkeypatch.setattr(
        self_improving,
        "_resolve_run_summary_telemetry",
        lambda: ("claude-sonnet-4-6", "claude-cli"),
    )
    self_improving._cmd_run([])
    out = capsys.readouterr().out
    assert "summary:" in out
    assert "applied=1" in out
    assert "model=claude-sonnet-4-6" in out
    assert "source=claude-cli" in out


def test_resolve_telemetry_inherits_settings_model_when_default_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G1a inherit — when ``MutatorConfig.default_model is None``, the
    telemetry resolver must fall back to ``Settings.model`` so the
    summary line shows what the runner actually invoked."""
    from core.cli.commands import self_improving

    class _StubMutator:
        default_model = None
        source = "auto"

    class _StubAutoresearch:
        mutator = _StubMutator()

    class _StubCfg:
        # Step J-b.1 — mutator now lives under autoresearch (control SoT).
        autoresearch = _StubAutoresearch()

    class _StubSettings:
        model = "claude-opus-4-7"

    monkeypatch.setattr(
        "core.config.self_improving.load_self_improving_loop_config",
        lambda: _StubCfg(),
    )
    monkeypatch.setattr("core.config.settings", _StubSettings())
    model, source = self_improving._resolve_run_summary_telemetry()
    assert model == "claude-opus-4-7"  # inherited from Settings.model
    assert source == "auto"


def test_resolve_telemetry_uses_explicit_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operator-set ``default_model`` wins over the inherit fallback."""
    from core.cli.commands import self_improving

    class _StubMutator:
        default_model = "claude-haiku-4-5-20251001"
        source = "api_key"

    class _StubAutoresearch:
        mutator = _StubMutator()

    class _StubCfg:
        autoresearch = _StubAutoresearch()

    monkeypatch.setattr(
        "core.config.self_improving.load_self_improving_loop_config",
        lambda: _StubCfg(),
    )
    model, source = self_improving._resolve_run_summary_telemetry()
    assert model == "claude-haiku-4-5-20251001"
    assert source == "api_key"


def test_resolve_telemetry_returns_placeholders_on_config_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive — config-import failure (e.g. test stub) returns
    ``("?", "?")`` so the slash never crashes on the summary line."""
    from core.cli.commands import self_improving

    def _broken_loader() -> None:
        raise ImportError("simulated config layer missing")

    monkeypatch.setattr(
        "core.config.self_improving.load_self_improving_loop_config",
        _broken_loader,
    )
    model, source = self_improving._resolve_run_summary_telemetry()
    assert model == "?"
    assert source == "?"
