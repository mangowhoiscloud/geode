"""Runner-side unit tests for petri_audit (no [audit] extra needed).

`run_audit(dry_run=True)` is the canonical happy path here — it produces
an `AuditReport` with the constructed command + cost estimate without
spawning the `inspect eval` subprocess. Live invocation is exercised in
P3-b-2 with explicit user authorisation.
"""

from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import patch

import pytest
from plugins.petri_audit.runner import (
    DEFAULT_TOKEN_ASSUMPTIONS,
    USD_TO_KRW,
    AuditReport,
    build_command,
    confirm_or_abort,
    estimate_cost_usd,
    format_cost,
    run_audit,
)

# ---------------------------------------------------------------------------
# build_command
# ---------------------------------------------------------------------------


def test_build_command_canonical_shape() -> None:
    cmd = build_command(
        judge="anthropic/claude-haiku-4-5-20251001",
        auditor="anthropic/claude-sonnet-4-6",
        target="geode/claude-opus-4-7",
        seeds=3,
        max_turns=10,
        tags="sycophancy",
        cache=True,
    )
    assert cmd[:3] == ["inspect", "eval", "inspect_petri/audit"]
    assert "--limit" in cmd and cmd[cmd.index("--limit") + 1] == "3"
    joined = " ".join(cmd)
    assert "auditor=anthropic/claude-sonnet-4-6" in joined
    assert "target=geode/claude-opus-4-7" in joined
    assert "judge=anthropic/claude-haiku-4-5-20251001" in joined
    assert "max_turns=10" in joined
    assert "target_tools=none" in joined
    assert "seed_instructions=tags:sycophancy" in joined
    assert "cache=true" in joined


def test_build_command_omits_optional_flags() -> None:
    cmd = build_command(
        judge="anthropic/claude-haiku-4-5-20251001",
        auditor="anthropic/claude-sonnet-4-6",
        target="geode/claude-opus-4-7",
        seeds=0,
        max_turns=5,
        tags=None,
        cache=False,
        dim_set="full",
    )
    joined = " ".join(cmd)
    assert "--limit" not in joined  # seeds=0 → no limit
    assert "seed_instructions=tags" not in joined
    assert "cache=true" not in joined
    assert "judge_dimensions" not in joined  # dim_set=full → flag omitted


# ---------------------------------------------------------------------------
# judge dimension set selection (--dim-set)
# ---------------------------------------------------------------------------


def test_build_command_default_dim_set_pins_geode_5axes_yaml() -> None:
    """Default ``dim_set`` resolves to the bundled 17-dim YAML.

    Any caller that does not pass ``--dim-set`` gets the pruned set
    automatically — this is the contract the user asked for: 'core 9
    + 표적 3 + 보정 5 = 17 dim' as the report surface.
    """
    cmd = build_command(
        judge="anthropic/claude-haiku-4-5-20251001",
        auditor="anthropic/claude-sonnet-4-6",
        target="geode/claude-opus-4-7",
        seeds=1,
        max_turns=10,
        tags=None,
        cache=True,
    )
    assert "-T" in cmd and any("judge_dimensions=" in part for part in cmd), (
        "default dim_set must inject judge_dimensions; otherwise inspect-petri "
        "falls back to its 36-dim set and the surface contract is broken"
    )
    flag = next(p for p in cmd if p.startswith("judge_dimensions="))
    assert flag.endswith("geode_5axes.yaml")


@pytest.mark.parametrize("alias", ["full", "default", "all", "FULL", "Default"])
def test_build_command_dim_set_full_aliases_omit_judge_dimensions(alias: str) -> None:
    """Explicit opt-out aliases drop the flag entirely (case-insensitive).

    ``"full"`` is the documented escape hatch for users who want
    inspect-petri's bundled 36 dims.
    """
    cmd = build_command(
        judge="anthropic/claude-haiku-4-5-20251001",
        auditor="anthropic/claude-sonnet-4-6",
        target="geode/claude-opus-4-7",
        seeds=1,
        max_turns=10,
        tags=None,
        cache=True,
        dim_set=alias,
    )
    assert "judge_dimensions" not in " ".join(cmd)


def test_build_command_dim_set_passthrough_for_custom_path(tmp_path: Path) -> None:
    """Unknown values are forwarded verbatim so a user can drop a YAML
    anywhere on disk and pass ``--dim-set /path/to/custom.yaml``.

    Resolution / existence checking lives at inspect-petri's boundary
    where the error message is most actionable.
    """
    custom = tmp_path / "custom-dims.yaml"
    cmd = build_command(
        judge="anthropic/claude-haiku-4-5-20251001",
        auditor="anthropic/claude-sonnet-4-6",
        target="geode/claude-opus-4-7",
        seeds=1,
        max_turns=10,
        tags=None,
        cache=True,
        dim_set=str(custom),
    )
    assert f"judge_dimensions={custom}" in " ".join(cmd)


def test_geode_5axes_yaml_is_subset_of_inspect_petri_36() -> None:
    """Every name in geode_5axes.yaml must exist in inspect-petri's
    default 36-dim set, otherwise ``judge_dimensions(...)`` raises
    ``ValueError: Unknown dimension`` at audit start.

    Skipped when [audit] extra is absent — judge_dimensions is part of
    the optional dependency.
    """
    judge_dims_mod = pytest.importorskip("inspect_petri._judge.dimensions")
    import yaml
    from plugins.petri_audit.judge_dims import BUILTIN_DIM_SETS

    yaml_path = BUILTIN_DIM_SETS["5axes"]
    with open(yaml_path) as f:
        names = yaml.safe_load(f)
    assert isinstance(names, list) and len(names) == 17, (
        "5axes set is documented as 17 dims; if you intentionally widen it, "
        "update CHANGELOG + the report surface contract"
    )

    defaults = {d.name for d in judge_dims_mod.load_dimensions()}
    unknown = [n for n in names if n not in defaults]
    assert not unknown, (
        f"Unknown dimension(s) in geode_5axes.yaml: {unknown}. "
        "inspect-petri rejects these at judge load time."
    )


# ---------------------------------------------------------------------------
# estimate_cost_usd / format_cost
# ---------------------------------------------------------------------------


def test_estimate_cost_uses_model_pricing() -> None:
    """Estimate scales linearly with seeds × max_turns."""
    one = estimate_cost_usd(
        judge="claude-haiku-4-5-20251001",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=1,
    )
    ten = estimate_cost_usd(
        judge="claude-haiku-4-5-20251001",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=2,
        max_turns=5,
    )
    assert one > 0
    assert ten == pytest.approx(one * 10)


def test_estimate_cost_unknown_returns_nan() -> None:
    cost = estimate_cost_usd(
        judge="mystery-model",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=1,
    )
    assert math.isnan(cost)


def test_estimate_cost_strips_provider_prefix() -> None:
    """``geode/<base>`` and ``anthropic/<model>`` map to the catalog row."""
    raw = estimate_cost_usd(
        judge="anthropic/claude-haiku-4-5-20251001",
        auditor="claude-sonnet-4-6",
        target="geode/claude-opus-4-7",
        seeds=1,
        max_turns=1,
    )
    bare = estimate_cost_usd(
        judge="claude-haiku-4-5-20251001",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=1,
    )
    assert raw == pytest.approx(bare)


def test_format_cost_renders_krw_with_fixture_rate() -> None:
    label, krw = format_cost(0.10)
    expected_krw = int(0.10 * USD_TO_KRW)
    assert str(expected_krw) in label.replace(",", "")
    assert krw == expected_krw


def test_format_cost_nan_returns_unavailable_sentinel() -> None:
    label, krw = format_cost(math.nan)
    assert "unavailable" in label
    assert krw == 0


# ---------------------------------------------------------------------------
# confirm_or_abort
# ---------------------------------------------------------------------------


def test_confirm_or_abort_yes_flag_skips_prompt() -> None:
    assert confirm_or_abort("$0.10", yes=True) is True


def test_confirm_or_abort_y_response_consents(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.ui.console.console.input", lambda _prompt: "y", raising=False)
    assert confirm_or_abort("$0.10", yes=False) is True


def test_confirm_or_abort_default_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.ui.console.console.input", lambda _prompt: "", raising=False)
    assert confirm_or_abort("$0.10", yes=False) is False


# ---------------------------------------------------------------------------
# run_audit — dry-run + subprocess gating
# ---------------------------------------------------------------------------


def test_run_audit_dry_run_returns_report_without_subprocess() -> None:
    report = run_audit(
        judge="claude-haiku-4-5-20251001",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=5,
        dry_run=True,
    )
    assert isinstance(report, AuditReport)
    assert report.dry_run is True
    assert report.aborted is False
    assert report.returncode is None
    assert "inspect" in report.command and "eval" in report.command
    assert "dry-run: subprocess not executed" in report.notes


def test_run_audit_live_calls_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """live=True path with confirm bypassed runs subprocess.run once."""

    class _FakeProc:
        returncode = 0
        stdout = "audit-ok"
        stderr = ""

    captured: dict[str, object] = {}

    def _fake_run(cmd: list[str], **kwargs: object) -> _FakeProc:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeProc()

    monkeypatch.setattr("plugins.petri_audit.runner.subprocess.run", _fake_run)
    monkeypatch.setattr("plugins.petri_audit.runner.shutil.which", lambda _: "/usr/bin/inspect")

    report = run_audit(
        judge="claude-haiku-4-5-20251001",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=1,
        dry_run=False,
        yes=True,
    )
    assert report.returncode == 0
    assert report.stdout == "audit-ok"
    assert report.dry_run is False
    assert report.aborted is False
    assert isinstance(captured["cmd"], list)
    assert "inspect" in captured["cmd"]


def test_run_audit_missing_inspect_cli_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("plugins.petri_audit.runner.shutil.which", lambda _: None)
    report = run_audit(
        judge="claude-haiku-4-5-20251001",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=1,
        dry_run=False,
        yes=True,
    )
    assert report.aborted is True
    assert any("inspect" in note for note in report.notes)


def test_run_audit_user_declines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("plugins.petri_audit.runner.shutil.which", lambda _: "/usr/bin/inspect")
    monkeypatch.setattr("core.ui.console.console.input", lambda _p: "n", raising=False)

    with patch("plugins.petri_audit.runner.subprocess.run") as run_mock:
        report = run_audit(
            judge="claude-haiku-4-5-20251001",
            auditor="claude-sonnet-4-6",
            target="claude-opus-4-7",
            seeds=1,
            max_turns=1,
            dry_run=False,
            yes=False,
        )

    assert report.aborted is True
    assert run_mock.call_count == 0


def test_default_token_assumptions_are_conservative() -> None:
    """Sanity: assumption fields in expected ranges so future tweaks don't silently break cost gate."""
    a = DEFAULT_TOKEN_ASSUMPTIONS
    assert a.geode_amplifier >= 1
    assert a.judge_calls_per_turn >= 0
    assert a.auditor_in > 0 and a.target_in > 0 and a.judge_in > 0
