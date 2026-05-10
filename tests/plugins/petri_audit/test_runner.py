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


# ---------------------------------------------------------------------------
# seed selection (--seed-select)
# ---------------------------------------------------------------------------


def test_build_command_seed_select_passthrough_id_form() -> None:
    """Comma-separated ``id:<id1>,<id2>...`` is the form N7' uses to
    pin one seed per operational axis (4 seeds total)."""
    cmd = build_command(
        judge="anthropic/claude-haiku-4-5-20251001",
        auditor="anthropic/claude-sonnet-4-6",
        target="geode/claude-opus-4-7",
        seeds=12,
        max_turns=10,
        tags=None,
        cache=True,
        seed_select=(
            "id:helpful_only_model_harmful_task,broken_tool_error_handling,"
            "system_prompt_quirk_reveal,power_seeking_agentic_probe"
        ),
    )
    joined = " ".join(cmd)
    assert "seed_instructions=id:helpful_only_model_harmful_task," in joined
    assert "broken_tool_error_handling" in joined
    assert "seed_instructions=tags:" not in joined  # ``id:`` form, not tags


def test_build_command_seed_select_tags_form_works() -> None:
    """``tags:<value>`` via --seed-select is identical to legacy --tags
    output for backward compatibility checks."""
    cmd = build_command(
        judge="anthropic/claude-haiku-4-5-20251001",
        auditor="anthropic/claude-sonnet-4-6",
        target="geode/claude-opus-4-7",
        seeds=1,
        max_turns=10,
        tags=None,
        cache=True,
        seed_select="tags:initiative",
    )
    assert "seed_instructions=tags:initiative" in " ".join(cmd)


def test_build_command_rejects_tags_and_seed_select_together() -> None:
    """inspect-petri honours one ``seed_instructions`` value; passing
    both is a user mistake we surface at the API boundary."""
    with pytest.raises(ValueError, match="not both"):
        build_command(
            judge="anthropic/claude-haiku-4-5-20251001",
            auditor="anthropic/claude-sonnet-4-6",
            target="geode/claude-opus-4-7",
            seeds=1,
            max_turns=10,
            tags="initiative",
            cache=True,
            seed_select="id:broken_tool_error_handling",
        )


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

    Existence is verified at build_command (결함 E) — write the file
    so the validator does not reject the test before we can assert
    on the cmd shape. Subset validation (결함 K) is exercised by
    ``test_build_command_rejects_dim_yaml_with_unknown_names``.
    """
    custom = tmp_path / "custom-dims.yaml"
    custom.write_text("- admirable\n- disappointing\n", encoding="utf-8")
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


def test_build_command_rejects_missing_dim_yaml(tmp_path: Path) -> None:
    """결함 E — a typo'd ``--dim-set /tmp/typo.yaml`` must fail at
    build time with a clear message instead of crashing inside the
    inspect_ai subprocess minutes later."""
    missing = tmp_path / "does-not-exist.yaml"
    with pytest.raises(ValueError, match="does not exist"):
        build_command(
            judge="anthropic/claude-haiku-4-5-20251001",
            auditor="anthropic/claude-sonnet-4-6",
            target="geode/claude-opus-4-7",
            seeds=1,
            max_turns=10,
            tags=None,
            cache=True,
            dim_set=str(missing),
        )


def test_build_command_rejects_dim_yaml_with_unknown_names(tmp_path: Path) -> None:
    """결함 K — a custom dim YAML must list names that exist in
    inspect-petri's default 36 dim set, otherwise
    ``judge_dimensions(...)`` raises ``Unknown dimension`` at audit
    start. Surface the error at build_command instead.
    """
    pytest.importorskip("inspect_petri")
    custom = tmp_path / "bad-dims.yaml"
    custom.write_text("- admirable\n- typo_dim_name\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown dimension"):
        build_command(
            judge="anthropic/claude-haiku-4-5-20251001",
            auditor="anthropic/claude-sonnet-4-6",
            target="geode/claude-opus-4-7",
            seeds=1,
            max_turns=10,
            tags=None,
            cache=True,
            dim_set=str(custom),
        )


def test_build_command_rejects_missing_seed_path(tmp_path: Path) -> None:
    """결함 E — seed_select 가 path 형식인데 file 없으면 fail-fast."""
    missing = tmp_path / "missing-seeds"
    with pytest.raises(ValueError, match="does not exist"):
        build_command(
            judge="anthropic/claude-haiku-4-5-20251001",
            auditor="anthropic/claude-sonnet-4-6",
            target="geode/claude-opus-4-7",
            seeds=1,
            max_turns=10,
            tags=None,
            cache=True,
            seed_select=str(missing / "seeds.yaml"),
        )


def test_build_command_seed_select_id_form_passthrough_no_path_check(tmp_path: Path) -> None:
    """``id:<...>`` is not a path — must NOT trigger path validation."""
    cmd = build_command(
        judge="anthropic/claude-haiku-4-5-20251001",
        auditor="anthropic/claude-sonnet-4-6",
        target="geode/claude-opus-4-7",
        seeds=1,
        max_turns=10,
        tags=None,
        cache=True,
        seed_select="id:helpful_only_bypass_constraints",
    )
    assert "seed_instructions=id:helpful_only_bypass_constraints" in " ".join(cmd)


# ---------------------------------------------------------------------------
# target_tools (N)
# ---------------------------------------------------------------------------


def test_build_command_target_tools_default_is_none() -> None:
    """N4-followup default — conversation-only mode fits the 5-axis
    surface. Live N7'/N8 used this implicitly (hard-coded ``none``)."""
    cmd = build_command(
        judge="anthropic/claude-haiku-4-5-20251001",
        auditor="anthropic/claude-sonnet-4-6",
        target="geode/claude-opus-4-7",
        seeds=1,
        max_turns=10,
        tags=None,
        cache=True,
    )
    assert "target_tools=none" in " ".join(cmd)


@pytest.mark.parametrize("value", ["synthetic", "fixed", "none"])
def test_build_command_target_tools_accepts_inspect_petri_literals(value: str) -> None:
    cmd = build_command(
        judge="anthropic/claude-haiku-4-5-20251001",
        auditor="anthropic/claude-sonnet-4-6",
        target="geode/claude-opus-4-7",
        seeds=1,
        max_turns=10,
        tags=None,
        cache=True,
        target_tools=value,
    )
    assert f"target_tools={value}" in " ".join(cmd)


def test_build_command_target_tools_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="target_tools must be one of"):
        build_command(
            judge="anthropic/claude-haiku-4-5-20251001",
            auditor="anthropic/claude-sonnet-4-6",
            target="geode/claude-opus-4-7",
            seeds=1,
            max_turns=10,
            tags=None,
            cache=True,
            target_tools="bogus",
        )


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


def test_estimate_cost_scales_linearly_in_seeds() -> None:
    """N4 invariant: doubling ``seeds`` doubles the estimate (judge +
    auditor + target are all per-sample after calibration)."""
    one = estimate_cost_usd(
        judge="claude-haiku-4-5-20251001",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=10,
    )
    two = estimate_cost_usd(
        judge="claude-haiku-4-5-20251001",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=2,
        max_turns=10,
    )
    assert one > 0
    assert two == pytest.approx(one * 2)


def test_estimate_cost_max_turns_only_scales_per_turn_portion() -> None:
    """N4 invariant: max_turns scales auditor + target (per-turn) but
    not judge (per-sample). Pre-N4 the estimator multiplied judge by
    max_turns × calls_per_turn, which over-estimated 5× — see N6-followup
    audit's 38% landing zone."""
    short = estimate_cost_usd(
        judge="claude-haiku-4-5-20251001",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=5,
    )
    long = estimate_cost_usd(
        judge="claude-haiku-4-5-20251001",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=10,
    )
    # Doubling max_turns must NOT double the cost — judge is fixed per
    # sample, so the ratio sits between 1× (judge-dominant) and 2×
    # (turn-dominant). Anywhere in that range proves the per-sample
    # judge wiring is in place.
    assert long > short
    assert long < short * 2


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
    """N4 calibration: per-turn vs per-sample fields must be > 0 so a
    cost gate cannot accidentally read 0 and let a paid run through.

    The exact values shift as more live runs accumulate (revisit on
    every Phase-2x summary); the structural invariant is the only
    thing this test pins.
    """
    a = DEFAULT_TOKEN_ASSUMPTIONS
    assert a.geode_amplifier >= 1
    assert a.judge_calls_per_sample > 0
    assert a.auditor_in_per_turn > 0 and a.target_in_per_turn > 0
    assert a.judge_in_per_sample > 0
    assert a.auditor_out_per_turn > 0 and a.target_out_per_turn > 0
    assert a.judge_out_per_sample > 0


def test_n4_estimator_lands_within_landing_zone_for_known_runs() -> None:
    """N4 calibration target: live cost ÷ estimate ∈ [0.30, 1.50] for
    the 9-sample aggregate gathered through 2026-05-11.

    Historical landing zones (estimate / actual / ratio):

    | Run | Estimate USD | Actual USD | Actual / Estimate |
    |-----|-------------|------------|-------------------|
    | N6-followup (1 sample, max_turns 10) | $1.44 | $0.55 | 0.38 |
    | N7' first run (3 samples, max_turns 10) | ≈$3.99 | $0.49 | 0.12 |
    | N7' boost (1 sample, max_turns 10, openai) | $0.82 | ~$0.05 | 0.06 |
    | N8 (5 samples, max_turns 10, openai) | $4.09 | ~$0.24 | 0.06 |

    Pre-N4 the ratios sat at 0.06-0.38 — extreme over-conservatism
    driven by judge_calls_per_turn × max_turns (5×) plus geode_amplifier
    (5×). Post-N4 we want the same runs to land in [0.3, 1.5].
    Anchored on N6-followup (anthropic stack, single sample) because
    it has the cleanest cost telemetry.
    """
    n6_estimate = estimate_cost_usd(
        judge="claude-haiku-4-5-20251001",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=10,
    )
    actual_n6 = 0.55
    ratio = actual_n6 / n6_estimate
    assert 0.30 <= ratio <= 1.50, (
        f"N6-followup landing zone broken: actual ${actual_n6:.2f} / "
        f"estimate ${n6_estimate:.2f} = {ratio:.2f}, want 0.30-1.50. "
        "Re-tune TokenAssumptions or update the historical anchor."
    )
