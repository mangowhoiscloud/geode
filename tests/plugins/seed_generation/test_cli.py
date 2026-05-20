"""Tests for ``plugins.seed_generation.cli`` — Typer sub-app + slash command + human gate.

P-checklist application (cycle-skill SKILL.md):

- **P1 Stub Fidelity Audit** — `_dispatch_pipeline` is monkeypatched so
  the heavy SubAgentManager / Pipeline imports don't fire in unit tests;
  the gate-flow assertions stay below.
- **P7 Caller-Callee Contract** — exit codes are stable (0 = success,
  1 = user abort / pre-flight failure, 2 = run error) so a CI wrapper
  can branch on them deterministically.
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import patch

import pytest
from plugins.seed_generation.cli import (
    cmd_audit_seeds_slash,
    render_pre_flight_report,
    run_audit_seeds,
)
from plugins.seed_generation.picker import PickerResult, RoleBinding, VoterBinding
from plugins.seed_generation.pre_flight import PreFlightIssue, PreFlightReport


def _good_picker() -> PickerResult:
    bindings = {
        "generator": RoleBinding(
            role="generator",
            model="claude-sonnet-4-6",
            provider="anthropic",
            source="api_key",
            kind="completion",
        ),
        "proximity": RoleBinding(
            role="proximity",
            model="text-embedding-3-small",
            provider="openai",
            source="api_key",
            kind="embedding",
        ),
    }
    voters = [
        VoterBinding(model="claude-sonnet-4-6", provider="anthropic", source="api_key"),
        VoterBinding(model="gpt-5.5", provider="openai", source="api_key"),
        VoterBinding(model="claude-haiku-4-5", provider="anthropic", source="api_key"),
    ]
    return PickerResult(
        bindings=bindings,
        voters=voters,
        diversity_providers=2,
        subscription_paths_in_use=frozenset(),
    )


def test_run_audit_seeds_yes_flag_skips_prompt() -> None:
    """--yes bypasses the interactive prompt and proceeds straight to dispatch."""
    out, err = io.StringIO(), io.StringIO()
    dispatched: dict[str, Any] = {}

    def _capture_dispatch(**kwargs: Any) -> None:
        dispatched.update(kwargs)

    with (
        patch("plugins.seed_generation.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_generation.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_generation.cli._dispatch_pipeline", side_effect=_capture_dispatch),
    ):
        code = run_audit_seeds(
            target_dim="broken_tool_use",
            yes=True,
            stdout=out,
            stderr=err,
        )
    assert code == 0
    assert dispatched["target_dim"] == "broken_tool_use"


def test_run_audit_seeds_user_says_no_aborts() -> None:
    out, err = io.StringIO(), io.StringIO()

    def _decline(_o: io.StringIO, _e: io.StringIO) -> bool:
        return False

    with (
        patch("plugins.seed_generation.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_generation.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_generation.cli._dispatch_pipeline") as mock_dispatch,
    ):
        code = run_audit_seeds(
            target_dim="broken_tool_use",
            yes=False,
            stdout=out,
            stderr=err,
            confirm_fn=_decline,
        )
    assert code == 1
    assert "aborted" in err.getvalue().lower()
    mock_dispatch.assert_not_called()


def test_run_audit_seeds_user_says_yes_dispatches() -> None:
    out, err = io.StringIO(), io.StringIO()

    def _accept(_o: io.StringIO, _e: io.StringIO) -> bool:
        return True

    with (
        patch("plugins.seed_generation.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_generation.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_generation.cli._dispatch_pipeline") as mock_dispatch,
    ):
        code = run_audit_seeds(
            target_dim="broken_tool_use",
            yes=False,
            stdout=out,
            stderr=err,
            confirm_fn=_accept,
        )
    assert code == 0
    mock_dispatch.assert_called_once()


def test_run_audit_seeds_pre_flight_error_aborts() -> None:
    out, err = io.StringIO(), io.StringIO()
    bad_report = PreFlightReport(
        issues=[
            PreFlightIssue(
                severity="error",
                code="auth.unreachable",
                message="anthropic.api_key missing",
                fix="set ANTHROPIC_API_KEY",
            )
        ]
    )
    with (
        patch("plugins.seed_generation.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_generation.cli.run_pre_flight", return_value=bad_report),
        patch("plugins.seed_generation.cli._dispatch_pipeline") as mock_dispatch,
    ):
        code = run_audit_seeds(
            target_dim="broken_tool_use",
            yes=True,
            stdout=out,
            stderr=err,
        )
    assert code == 1
    mock_dispatch.assert_not_called()
    assert "pre-flight failed" in err.getvalue()


def test_run_audit_seeds_dispatch_exception_returns_2() -> None:
    out, err = io.StringIO(), io.StringIO()

    def _crashing_dispatch(**_kwargs: Any) -> None:
        msg = "test crash"
        raise RuntimeError(msg)

    with (
        patch("plugins.seed_generation.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_generation.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_generation.cli._dispatch_pipeline", side_effect=_crashing_dispatch),
    ):
        code = run_audit_seeds(
            target_dim="broken_tool_use",
            yes=True,
            stdout=out,
            stderr=err,
        )
    assert code == 2
    assert "test crash" in err.getvalue()


def test_run_audit_seeds_emits_cost_summary_to_stdout() -> None:
    out, err = io.StringIO(), io.StringIO()
    with (
        patch("plugins.seed_generation.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_generation.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_generation.cli._dispatch_pipeline"),
    ):
        run_audit_seeds(
            target_dim="broken_tool_use",
            yes=True,
            stdout=out,
            stderr=err,
        )
    summary = out.getvalue()
    assert "seed-generation cost preview" in summary
    assert "candidates: 15" in summary  # default


def test_render_pre_flight_report_empty() -> None:
    rendered = render_pre_flight_report(PreFlightReport())
    assert "passed" in rendered


def test_render_pre_flight_report_includes_severity_and_fix() -> None:
    report = PreFlightReport(
        issues=[
            PreFlightIssue(
                severity="error",
                code="auth.unreachable",
                message="claude-cli down",
                fix="run `claude login`",
            ),
            PreFlightIssue(
                severity="warning",
                code="budget.absurd_high",
                message="hard 200 > 100",
                fix="lower hard cap",
            ),
        ]
    )
    rendered = render_pre_flight_report(report)
    assert "[  error]" in rendered
    assert "[warning]" in rendered
    assert "claude login" in rendered
    assert "lower hard cap" in rendered


def test_cmd_audit_seeds_slash_parses_target_dim() -> None:
    """Slash command parses --target-dim and dispatches."""
    with (
        patch("plugins.seed_generation.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_generation.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_generation.cli._dispatch_pipeline") as mock_dispatch,
    ):
        code = cmd_audit_seeds_slash("--target-dim broken_tool_use --yes")
    assert code == 0
    mock_dispatch.assert_called_once()
    args = mock_dispatch.call_args.kwargs
    assert args["target_dim"] == "broken_tool_use"


def test_cmd_audit_seeds_slash_requires_target_dim() -> None:
    code = cmd_audit_seeds_slash("--yes")
    assert code == 2


def test_cmd_audit_seeds_slash_handles_quote_parse_error() -> None:
    """Unclosed quote → exit 2, no dispatch."""
    code = cmd_audit_seeds_slash('--target-dim "unclosed')
    assert code == 2


def test_cmd_audit_seeds_slash_parses_short_flags() -> None:
    """`-d` shorthand works."""
    with (
        patch("plugins.seed_generation.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_generation.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_generation.cli._dispatch_pipeline") as mock_dispatch,
    ):
        cmd_audit_seeds_slash("-d broken_tool_use -y")
    assert mock_dispatch.call_args.kwargs["target_dim"] == "broken_tool_use"


def test_cmd_audit_seeds_slash_parses_candidates_count() -> None:
    with (
        patch("plugins.seed_generation.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_generation.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_generation.cli._dispatch_pipeline") as mock_dispatch,
    ):
        cmd_audit_seeds_slash("--target-dim x --candidates 5 --yes")
    assert mock_dispatch.call_args.kwargs["candidates_requested"] == 5


def test_cmd_audit_seeds_slash_rejects_unknown_flag() -> None:
    """Unknown flag → exit 2 (strict argparse, no silent typo)."""
    code = cmd_audit_seeds_slash("--target-dim x --future-flag y --yes")
    assert code == 2


def test_cmd_audit_seeds_slash_rejects_invalid_candidates_int() -> None:
    """`--candidates not-a-number` → exit 2."""
    code = cmd_audit_seeds_slash("--target-dim x --candidates banana --yes")
    assert code == 2


def test_audit_seeds_app_help_smoke() -> None:
    """`geode audit-seeds --help` smoke test (Typer app instantiation)."""
    from plugins.seed_generation.cli import audit_seeds_app

    assert audit_seeds_app.info.name == "audit-seeds"
    assert audit_seeds_app.registered_commands  # generate is registered


def test_run_audit_seeds_quiet_suppresses_tos_notice() -> None:
    """--quiet keeps the ToS notice out of stderr."""
    out, err = io.StringIO(), io.StringIO()
    picker = _good_picker()
    # Force a subscription path so the ToS would otherwise fire
    sub_picker = PickerResult(
        bindings=picker.bindings,
        voters=picker.voters,
        diversity_providers=picker.diversity_providers,
        subscription_paths_in_use=frozenset({"claude-cli"}),
    )
    with (
        patch("plugins.seed_generation.cli.pick_bindings", return_value=sub_picker),
        patch("plugins.seed_generation.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_generation.cli._dispatch_pipeline"),
    ):
        run_audit_seeds(
            target_dim="broken_tool_use",
            yes=True,
            quiet=True,
            stdout=out,
            stderr=err,
        )
    assert "ToS notice" not in err.getvalue()


# ── PR-δ2: ``--gen-tag`` / ``--candidates`` default to self_improving_loop config ──


def test_get_seed_generation_config_returns_loader_value() -> None:
    """``_get_seed_generation_config`` reads ``[self_improving_loop.seed_generation]``."""
    from types import SimpleNamespace

    from plugins.seed_generation import cli as cli_mod

    fake = SimpleNamespace(candidates_default=42, default_gen_tag="genQ")
    with patch(
        "core.config.self_improving_loop.load_self_improving_loop_config",
        return_value=SimpleNamespace(seed_generation=fake),
    ):
        cfg = cli_mod._get_seed_generation_config()
    assert cfg.candidates_default == 42
    assert cfg.default_gen_tag == "genQ"


def test_get_seed_generation_config_falls_back_when_loader_raises() -> None:
    """A raising loader yields the module-level fallback (gen1 / 15)."""
    from plugins.seed_generation import cli as cli_mod

    def _boom() -> object:
        raise RuntimeError("simulated load failure")

    with patch("core.config.self_improving_loop.load_self_improving_loop_config", _boom):
        cfg = cli_mod._get_seed_generation_config()
    assert cfg.candidates_default == 15
    assert cfg.default_gen_tag == "gen1"


def test_audit_seeds_generate_uses_config_defaults() -> None:
    """When the user omits ``--gen-tag`` / ``--candidates``, the Typer
    command resolves them through ``_get_seed_generation_config`` before
    delegating to ``run_audit_seeds``."""
    from types import SimpleNamespace

    from plugins.seed_generation.cli import audit_seeds_app
    from typer.testing import CliRunner

    captured: dict[str, Any] = {}

    def _capture_run(**kwargs: Any) -> int:
        captured.update(kwargs)
        return 0

    fake_cfg = SimpleNamespace(
        seed_generation=SimpleNamespace(candidates_default=8, default_gen_tag="gen7"),
    )
    with (
        patch(
            "core.config.self_improving_loop.load_self_improving_loop_config", return_value=fake_cfg
        ),
        patch("plugins.seed_generation.cli.run_audit_seeds", _capture_run),
    ):
        result = CliRunner().invoke(
            audit_seeds_app,
            ["--target-dim", "broken_tool_use"],
        )
    assert result.exit_code == 0, result.output
    assert captured["gen_tag"] == "gen7"
    assert captured["candidates"] == 8


# ── PR-P2 — SessionJournal events for cost preview, preflight, cost divergence ──


def _journal_rows(journal_path: Any) -> list[dict[str, Any]]:
    import json
    from pathlib import Path

    p = Path(journal_path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_run_audit_seeds_emits_cost_preview_into_session_journal(tmp_path: Any) -> None:
    """``run_audit_seeds`` opens a SessionJournal scope and emits
    ``cost_preview`` with predicted-spend breakdown before any pipeline
    work begins. Verifies the outer-scope wiring introduced in PR-P2."""
    import json

    journal_path = tmp_path / "journal.jsonl"
    with (
        patch("plugins.seed_generation.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_generation.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_generation.cli._dispatch_pipeline"),
        patch("core.observability.session_journal.SessionJournal") as MockJournal,
    ):
        # Force the constructor to bind our temp path so we can read the artifact.
        from core.observability import SessionJournal as RealJournal

        MockJournal.side_effect = lambda **kwargs: RealJournal(
            session_id=kwargs["session_id"],
            gen_tag=kwargs["gen_tag"],
            component=kwargs["component"],
            path=journal_path,
        )
        # Re-import the symbol used inside run_audit_seeds since the import is
        # local — patching the constructor on the module class is enough.
        out, err = io.StringIO(), io.StringIO()
        with patch("core.observability.SessionJournal", MockJournal):
            run_audit_seeds(
                target_dim="broken_tool_use",
                yes=True,
                stdout=out,
                stderr=err,
            )

    events = [json.loads(line) for line in journal_path.read_text("utf-8").splitlines() if line]
    cost_events = [e for e in events if e["event"] == "cost_preview"]
    assert len(cost_events) == 1
    payload = cost_events[0]["payload"]
    assert "estimated_usd_total" in payload
    assert payload["candidate_count"] == 15
    assert "voter_count" in payload


def test_run_audit_seeds_emits_preflight_passed_when_clean(tmp_path: Any) -> None:
    journal_path = tmp_path / "journal.jsonl"
    from core.observability import SessionJournal as RealJournal

    def _bind(**kwargs: Any) -> Any:
        return RealJournal(
            session_id=kwargs["session_id"],
            gen_tag=kwargs["gen_tag"],
            component=kwargs["component"],
            path=journal_path,
        )

    out, err = io.StringIO(), io.StringIO()
    with (
        patch("plugins.seed_generation.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_generation.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_generation.cli._dispatch_pipeline"),
        patch("core.observability.SessionJournal", side_effect=_bind),
    ):
        run_audit_seeds(target_dim="broken_tool_use", yes=True, stdout=out, stderr=err)

    events = _journal_rows(journal_path)
    passed = [e for e in events if e["event"] == "preflight_passed"]
    failed = [e for e in events if e["event"] == "preflight_failed"]
    assert len(passed) == 1
    assert passed[0]["payload"]["issue_count"] == 0
    assert failed == []


def test_run_audit_seeds_emits_preflight_failed_with_issue_list(tmp_path: Any) -> None:
    """The dominant pre-PR observability gap — preflight error path now
    surfaces the structured issue list before exit code 1."""
    journal_path = tmp_path / "journal.jsonl"
    bad_report = PreFlightReport(
        issues=[
            PreFlightIssue(
                severity="error",
                code="auth.unreachable",
                message="anthropic.api_key missing",
                fix="set ANTHROPIC_API_KEY",
            ),
            PreFlightIssue(
                severity="warning",
                code="diversity.collapsed",
                message="only 1 provider",
                fix="spread judges",
            ),
        ]
    )

    from core.observability import SessionJournal as RealJournal

    def _bind(**kwargs: Any) -> Any:
        return RealJournal(
            session_id=kwargs["session_id"],
            gen_tag=kwargs["gen_tag"],
            component=kwargs["component"],
            path=journal_path,
        )

    out, err = io.StringIO(), io.StringIO()
    with (
        patch("plugins.seed_generation.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_generation.cli.run_pre_flight", return_value=bad_report),
        patch("plugins.seed_generation.cli._dispatch_pipeline") as mock_dispatch,
        patch("core.observability.SessionJournal", side_effect=_bind),
    ):
        code = run_audit_seeds(
            target_dim="broken_tool_use",
            yes=True,
            stdout=out,
            stderr=err,
        )

    assert code == 1
    mock_dispatch.assert_not_called()
    events = _journal_rows(journal_path)
    failed = [e for e in events if e["event"] == "preflight_failed"]
    assert len(failed) == 1
    assert failed[0]["level"] == "error"
    payload = failed[0]["payload"]
    assert payload["issue_count"] == 2
    codes = {issue["code"] for issue in payload["issues"]}
    assert codes == {"auth.unreachable", "diversity.collapsed"}


def test_run_audit_seeds_emits_user_aborted_on_decline(tmp_path: Any) -> None:
    journal_path = tmp_path / "journal.jsonl"
    from core.observability import SessionJournal as RealJournal

    def _bind(**kwargs: Any) -> Any:
        return RealJournal(
            session_id=kwargs["session_id"],
            gen_tag=kwargs["gen_tag"],
            component=kwargs["component"],
            path=journal_path,
        )

    out, err = io.StringIO(), io.StringIO()
    with (
        patch("plugins.seed_generation.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_generation.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_generation.cli._dispatch_pipeline"),
        patch("core.observability.SessionJournal", side_effect=_bind),
    ):
        code = run_audit_seeds(
            target_dim="broken_tool_use",
            yes=False,
            stdout=out,
            stderr=err,
            confirm_fn=lambda _o, _e: False,
        )

    assert code == 1
    events = _journal_rows(journal_path)
    aborted = [e for e in events if e["event"] == "user_aborted"]
    assert len(aborted) == 1
    assert aborted[0]["payload"]["stage"] == "confirm_prompt"


def test_emit_cost_divergence_info_when_within_threshold(tmp_path: Any) -> None:
    """Predicted vs actual within ±50 % stays at ``info`` level."""
    from plugins.seed_generation.cli import _emit_cost_divergence

    from core.observability import SessionJournal

    journal = SessionJournal(
        session_id="t", gen_tag="t", component="seed-generation", path=tmp_path / "j.jsonl"
    )
    _emit_cost_divergence(journal, predicted_usd=10.0, actual_usd=11.0)
    rows = _journal_rows(journal.path)
    assert len(rows) == 1
    assert rows[0]["event"] == "cost_divergence"
    assert rows[0]["level"] == "info"
    assert rows[0]["payload"]["predicted_usd"] == 10.0
    assert rows[0]["payload"]["actual_usd"] == 11.0
    assert rows[0]["payload"]["delta_usd"] == pytest.approx(1.0)
    assert rows[0]["payload"]["ratio"] == pytest.approx(0.1, rel=1e-3)


def test_emit_cost_divergence_warn_when_overspend(tmp_path: Any) -> None:
    """Actual > 1.5 × predicted → ``warn`` level so a dashboard can highlight."""
    from plugins.seed_generation.cli import _emit_cost_divergence

    from core.observability import SessionJournal

    journal = SessionJournal(
        session_id="t", gen_tag="t", component="seed-generation", path=tmp_path / "j.jsonl"
    )
    _emit_cost_divergence(journal, predicted_usd=2.0, actual_usd=5.0)
    rows = _journal_rows(journal.path)
    assert rows[0]["level"] == "warn"
    assert rows[0]["payload"]["ratio"] == pytest.approx(1.5)


def test_emit_cost_divergence_ratio_none_when_predicted_zero(tmp_path: Any) -> None:
    """Subscription-only run with $0 predicted PAYG → ratio is ``None``,
    level stays ``info`` (we can't compute a meaningful overshoot %)."""
    from plugins.seed_generation.cli import _emit_cost_divergence

    from core.observability import SessionJournal

    journal = SessionJournal(
        session_id="t", gen_tag="t", component="seed-generation", path=tmp_path / "j.jsonl"
    )
    _emit_cost_divergence(journal, predicted_usd=0.0, actual_usd=0.42)
    rows = _journal_rows(journal.path)
    assert rows[0]["level"] == "info"
    assert rows[0]["payload"]["ratio"] is None
    assert rows[0]["payload"]["actual_usd"] == 0.42


def test_audit_seeds_generate_cli_overrides_win_over_config() -> None:
    """Explicit ``--gen-tag`` / ``--candidates`` still override the config."""
    from types import SimpleNamespace

    from plugins.seed_generation.cli import audit_seeds_app
    from typer.testing import CliRunner

    captured: dict[str, Any] = {}

    def _capture_run(**kwargs: Any) -> int:
        captured.update(kwargs)
        return 0

    fake_cfg = SimpleNamespace(
        seed_generation=SimpleNamespace(candidates_default=8, default_gen_tag="gen7"),
    )
    with (
        patch(
            "core.config.self_improving_loop.load_self_improving_loop_config", return_value=fake_cfg
        ),
        patch("plugins.seed_generation.cli.run_audit_seeds", _capture_run),
    ):
        result = CliRunner().invoke(
            audit_seeds_app,
            [
                "--target-dim",
                "broken_tool_use",
                "--gen-tag",
                "gen9",
                "--candidates",
                "20",
            ],
        )
    assert result.exit_code == 0, result.output
    assert captured["gen_tag"] == "gen9"
    assert captured["candidates"] == 20


# ---------------------------------------------------------------------------
# G3 — --target-dim auto-pick from baseline.json + snapshot propagation
# ---------------------------------------------------------------------------


def test_resolve_target_dim_explicit_returns_loaded_snapshot() -> None:
    """G3.fix1 (2026-05-20) — explicit `--target-dim` still loads the
    baseline so generator/critic/evolver receive evidence injection.

    Pre-fix the explicit branch returned ``(dim, None)`` and downstream
    sub-agents saw no evidence — Codex MCP LLM-as-Judge flagged this
    as a Conditional-read-parity violation. The explicit-dim case must
    now also load `baseline.json`; the auto-pick log line stays absent
    so the caller knows the dim was operator-supplied, not auto-picked.
    """
    from plugins.seed_generation.baseline_reader import BaselineSnapshot
    from plugins.seed_generation.cli import _resolve_target_dim

    fake_snapshot = BaselineSnapshot(dim_means={"broken_tool_use": 6.0})
    err = io.StringIO()
    with patch(
        "plugins.seed_generation.baseline_reader.load_baseline",
        return_value=fake_snapshot,
    ):
        dim, snapshot = _resolve_target_dim("broken_tool_use", err=err)
    assert dim == "broken_tool_use"
    assert snapshot is fake_snapshot
    # No auto-pick log line when operator supplied an explicit dim.
    assert "auto" not in err.getvalue()


def test_resolve_target_dim_explicit_returns_none_when_no_baseline() -> None:
    """Explicit dim + missing baseline → ``(dim, None)`` (graceful, no error).

    Bootstrap runs (no audit yet) with an explicit ``--target-dim`` are
    valid; the runner just doesn't get evidence to inject.
    """
    from plugins.seed_generation.cli import _resolve_target_dim

    err = io.StringIO()
    with patch("plugins.seed_generation.baseline_reader.load_baseline", return_value=None):
        dim, snapshot = _resolve_target_dim("broken_tool_use", err=err)
    assert dim == "broken_tool_use"
    assert snapshot is None
    assert "auto" not in err.getvalue()


def test_resolve_target_dim_auto_picks_from_baseline() -> None:
    """--target-dim auto / unset → reader.pick_regression_target_dim."""
    from plugins.seed_generation.baseline_reader import BaselineSnapshot
    from plugins.seed_generation.cli import _resolve_target_dim

    fake_snapshot = BaselineSnapshot(
        dim_means={"broken_tool_use": 4.0, "input_hallucination": 8.0},
    )
    err = io.StringIO()
    with (
        patch("plugins.seed_generation.cli.load_baseline", return_value=fake_snapshot)
        if False
        else patch(
            "plugins.seed_generation.baseline_reader.load_baseline",
            return_value=fake_snapshot,
        ),
        patch(
            "plugins.seed_generation.baseline_reader.pick_regression_target_dim",
            return_value="input_hallucination",
        ),
    ):
        dim, snapshot = _resolve_target_dim(None, err=err)
    assert dim == "input_hallucination"
    assert snapshot is fake_snapshot
    assert "auto" in err.getvalue()
    assert "input_hallucination" in err.getvalue()


def test_resolve_target_dim_no_baseline_returns_none() -> None:
    """Auto-pick without baseline → (None, None), actionable error msg."""
    from plugins.seed_generation.cli import _resolve_target_dim

    err = io.StringIO()
    with patch("plugins.seed_generation.baseline_reader.load_baseline", return_value=None):
        dim, snapshot = _resolve_target_dim(None, err=err)
    assert dim is None
    assert snapshot is None
    assert "no autoresearch baseline" in err.getvalue()


def test_run_audit_seeds_auto_picks_target_dim() -> None:
    """End-to-end: bare --target-dim → baseline auto-pick → dispatch with picked dim."""
    from plugins.seed_generation.baseline_reader import BaselineSnapshot

    out, err = io.StringIO(), io.StringIO()
    dispatched: dict[str, Any] = {}

    def _capture_dispatch(**kwargs: Any) -> None:
        dispatched.update(kwargs)

    fake_snapshot = BaselineSnapshot(dim_means={"broken_tool_use": 6.0})
    with (
        patch(
            "plugins.seed_generation.baseline_reader.load_baseline",
            return_value=fake_snapshot,
        ),
        patch(
            "plugins.seed_generation.baseline_reader.pick_regression_target_dim",
            return_value="broken_tool_use",
        ),
        patch("plugins.seed_generation.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_generation.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_generation.cli._dispatch_pipeline", side_effect=_capture_dispatch),
    ):
        code = run_audit_seeds(
            target_dim=None,
            yes=True,
            stdout=out,
            stderr=err,
        )
    assert code == 0
    assert dispatched["target_dim"] == "broken_tool_use"
    assert dispatched["baseline_snapshot"] is fake_snapshot


def test_run_audit_seeds_no_baseline_returns_1() -> None:
    """Auto-pick fails → exit 1 before any pipeline / picker work."""
    out, err = io.StringIO(), io.StringIO()
    with (
        patch("plugins.seed_generation.baseline_reader.load_baseline", return_value=None),
        patch("plugins.seed_generation.cli.pick_bindings") as mock_pick,
    ):
        code = run_audit_seeds(target_dim=None, yes=True, stdout=out, stderr=err)
    assert code == 1
    # picker not even invoked because the gate fired before.
    mock_pick.assert_not_called()


# ---------------------------------------------------------------------------
# G4 — _load_priors_snapshot + meta_review_snapshot propagation
# ---------------------------------------------------------------------------


def test_load_priors_returns_none_for_bootstrap() -> None:
    """No prior meta_review → snapshot None, helper returns None silently."""
    from plugins.seed_generation.cli import _load_priors_snapshot

    err = io.StringIO()
    with patch(
        "plugins.seed_generation.baseline_reader.load_latest_meta_review",
        return_value=None,
    ):
        snapshot = _load_priors_snapshot(err=err)
    assert snapshot is None
    assert err.getvalue() == ""  # silent on bootstrap


def test_load_priors_logs_summary_on_hit() -> None:
    from plugins.seed_generation.baseline_reader import MetaReviewSnapshot
    from plugins.seed_generation.cli import _load_priors_snapshot

    fake_snapshot = MetaReviewSnapshot(
        next_gen_priors=[{"target_dim": "d1", "weight": 0.5}],
        underrepresented_dims=["d2", "d3"],
    )
    err = io.StringIO()
    with patch(
        "plugins.seed_generation.baseline_reader.load_latest_meta_review",
        return_value=fake_snapshot,
    ):
        snapshot = _load_priors_snapshot(err=err)
    assert snapshot is fake_snapshot
    assert "1 priors" in err.getvalue()
    assert "2 underrepresented" in err.getvalue()


def test_run_audit_seeds_passes_meta_review_snapshot_to_dispatch() -> None:
    """End-to-end: priors loaded → meta_review_snapshot reaches _dispatch_pipeline."""
    from plugins.seed_generation.baseline_reader import MetaReviewSnapshot

    out, err = io.StringIO(), io.StringIO()
    dispatched: dict[str, Any] = {}

    def _capture_dispatch(**kwargs: Any) -> None:
        dispatched.update(kwargs)

    fake_priors = MetaReviewSnapshot(
        next_gen_priors=[{"target_dim": "broken_tool_use", "weight": 0.5}],
        underrepresented_dims=["broken_tool_use"],
    )
    with (
        patch(
            "plugins.seed_generation.baseline_reader.load_latest_meta_review",
            return_value=fake_priors,
        ),
        patch("plugins.seed_generation.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_generation.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_generation.cli._dispatch_pipeline", side_effect=_capture_dispatch),
    ):
        code = run_audit_seeds(
            target_dim="broken_tool_use",
            yes=True,
            stdout=out,
            stderr=err,
        )
    assert code == 0
    assert dispatched["meta_review_snapshot"] is fake_priors
