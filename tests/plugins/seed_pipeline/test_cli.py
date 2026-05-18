"""Tests for ``plugins.seed_pipeline.cli`` — Typer sub-app + slash command + human gate.

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

from plugins.seed_pipeline.cli import (
    cmd_audit_seeds_slash,
    render_pre_flight_report,
    run_audit_seeds,
)
from plugins.seed_pipeline.picker import PickerResult, RoleBinding, VoterBinding
from plugins.seed_pipeline.pre_flight import PreFlightIssue, PreFlightReport


def _good_picker() -> PickerResult:
    bindings = {
        "generator": RoleBinding(
            role="generator",
            model="claude-sonnet-4-6",
            family="anthropic",
            source="api_key",
            kind="completion",
        ),
        "proximity": RoleBinding(
            role="proximity",
            model="text-embedding-3-small",
            family="openai",
            source="api_key",
            kind="embedding",
        ),
    }
    voters = [
        VoterBinding(model="claude-sonnet-4-6", family="anthropic", source="api_key"),
        VoterBinding(model="gpt-5.5", family="openai", source="api_key"),
        VoterBinding(model="claude-haiku-4-5", family="anthropic", source="api_key"),
    ]
    return PickerResult(
        bindings=bindings,
        voters=voters,
        diversity_families=2,
        subscription_paths_in_use=frozenset(),
    )


def test_run_audit_seeds_yes_flag_skips_prompt() -> None:
    """--yes bypasses the interactive prompt and proceeds straight to dispatch."""
    out, err = io.StringIO(), io.StringIO()
    dispatched: dict[str, Any] = {}

    def _capture_dispatch(**kwargs: Any) -> None:
        dispatched.update(kwargs)

    with (
        patch("plugins.seed_pipeline.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_pipeline.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_pipeline.cli._dispatch_pipeline", side_effect=_capture_dispatch),
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
        patch("plugins.seed_pipeline.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_pipeline.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_pipeline.cli._dispatch_pipeline") as mock_dispatch,
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
        patch("plugins.seed_pipeline.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_pipeline.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_pipeline.cli._dispatch_pipeline") as mock_dispatch,
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
        patch("plugins.seed_pipeline.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_pipeline.cli.run_pre_flight", return_value=bad_report),
        patch("plugins.seed_pipeline.cli._dispatch_pipeline") as mock_dispatch,
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
        patch("plugins.seed_pipeline.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_pipeline.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_pipeline.cli._dispatch_pipeline", side_effect=_crashing_dispatch),
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
        patch("plugins.seed_pipeline.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_pipeline.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_pipeline.cli._dispatch_pipeline"),
    ):
        run_audit_seeds(
            target_dim="broken_tool_use",
            yes=True,
            stdout=out,
            stderr=err,
        )
    summary = out.getvalue()
    assert "seed-pipeline cost preview" in summary
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
        patch("plugins.seed_pipeline.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_pipeline.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_pipeline.cli._dispatch_pipeline") as mock_dispatch,
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
        patch("plugins.seed_pipeline.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_pipeline.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_pipeline.cli._dispatch_pipeline") as mock_dispatch,
    ):
        cmd_audit_seeds_slash("-d broken_tool_use -y")
    assert mock_dispatch.call_args.kwargs["target_dim"] == "broken_tool_use"


def test_cmd_audit_seeds_slash_parses_candidates_count() -> None:
    with (
        patch("plugins.seed_pipeline.cli.pick_bindings", return_value=_good_picker()),
        patch("plugins.seed_pipeline.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_pipeline.cli._dispatch_pipeline") as mock_dispatch,
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
    from plugins.seed_pipeline.cli import audit_seeds_app

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
        diversity_families=picker.diversity_families,
        subscription_paths_in_use=frozenset({"claude-cli"}),
    )
    with (
        patch("plugins.seed_pipeline.cli.pick_bindings", return_value=sub_picker),
        patch("plugins.seed_pipeline.cli.run_pre_flight", return_value=PreFlightReport()),
        patch("plugins.seed_pipeline.cli._dispatch_pipeline"),
    ):
        run_audit_seeds(
            target_dim="broken_tool_use",
            yes=True,
            quiet=True,
            stdout=out,
            stderr=err,
        )
    assert "ToS notice" not in err.getvalue()


# ── PR-δ2: ``--gen-tag`` / ``--candidates`` default to outer_loop config ──


def test_get_seed_pipeline_config_returns_loader_value() -> None:
    """``_get_seed_pipeline_config`` reads ``[outer_loop.seed_pipeline]``."""
    from types import SimpleNamespace

    from plugins.seed_pipeline import cli as cli_mod

    fake = SimpleNamespace(candidates_default=42, default_gen_tag="genQ")
    with patch(
        "core.config.outer_loop.load_outer_loop_config",
        return_value=SimpleNamespace(seed_pipeline=fake),
    ):
        cfg = cli_mod._get_seed_pipeline_config()
    assert cfg.candidates_default == 42
    assert cfg.default_gen_tag == "genQ"


def test_get_seed_pipeline_config_falls_back_when_loader_raises() -> None:
    """A raising loader yields the module-level fallback (gen1 / 15)."""
    from plugins.seed_pipeline import cli as cli_mod

    def _boom() -> object:
        raise RuntimeError("simulated load failure")

    with patch("core.config.outer_loop.load_outer_loop_config", _boom):
        cfg = cli_mod._get_seed_pipeline_config()
    assert cfg.candidates_default == 15
    assert cfg.default_gen_tag == "gen1"


def test_audit_seeds_generate_uses_config_defaults() -> None:
    """When the user omits ``--gen-tag`` / ``--candidates``, the Typer
    command resolves them through ``_get_seed_pipeline_config`` before
    delegating to ``run_audit_seeds``."""
    from types import SimpleNamespace

    from plugins.seed_pipeline.cli import audit_seeds_app
    from typer.testing import CliRunner

    captured: dict[str, Any] = {}

    def _capture_run(**kwargs: Any) -> int:
        captured.update(kwargs)
        return 0

    fake_cfg = SimpleNamespace(
        seed_pipeline=SimpleNamespace(candidates_default=8, default_gen_tag="gen7"),
    )
    with (
        patch("core.config.outer_loop.load_outer_loop_config", return_value=fake_cfg),
        patch("plugins.seed_pipeline.cli.run_audit_seeds", _capture_run),
    ):
        result = CliRunner().invoke(
            audit_seeds_app,
            ["--target-dim", "broken_tool_use"],
        )
    assert result.exit_code == 0, result.output
    assert captured["gen_tag"] == "gen7"
    assert captured["candidates"] == 8


def test_audit_seeds_generate_cli_overrides_win_over_config() -> None:
    """Explicit ``--gen-tag`` / ``--candidates`` still override the config."""
    from types import SimpleNamespace

    from plugins.seed_pipeline.cli import audit_seeds_app
    from typer.testing import CliRunner

    captured: dict[str, Any] = {}

    def _capture_run(**kwargs: Any) -> int:
        captured.update(kwargs)
        return 0

    fake_cfg = SimpleNamespace(
        seed_pipeline=SimpleNamespace(candidates_default=8, default_gen_tag="gen7"),
    )
    with (
        patch("core.config.outer_loop.load_outer_loop_config", return_value=fake_cfg),
        patch("plugins.seed_pipeline.cli.run_audit_seeds", _capture_run),
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
