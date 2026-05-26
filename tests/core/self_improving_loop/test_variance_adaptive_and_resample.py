"""PR-VAR-ADAPTIVE + PR-RESAMPLE-BUDGET (2026-05-27) — Phase F bundle.

Two complementary algorithm-depth additions to the
``apply_group_proposals`` selection layer:

**PR-VAR-ADAPTIVE** — replaces the hardcoded
``group_variance_threshold = 0.01`` with an optional percentile-based
resolver that reads ``group_variance_history.jsonl`` and returns the
configured percentile of recent observed std values. Closes the
2026-05-26 attribution sprint Phase A audit (§4.3 follow-up): the
fixed threshold drifts silently when fitness-scale changes (e.g., new
DIM_WEIGHTS rotation, anchor_confidence_mode toggle).

**PR-RESAMPLE-BUDGET** — when ``filtered_low_variance`` fires, the
default behaviour is "cycle skip" (no SoT commit, no retry). With
``resample_on_low_variance=True`` and ``max_group_resamples > 0``,
the runner now proposes a fresh sibling group and retries the audit
up to the budget. DAPO frontier equivalent: ``max_num_gen_batches``
informative-batch retention.

This file pins:

* Variance history append (best-effort writer, all rows recorded).
* Percentile resolver — fixed-mode default, percentile-mode below /
  at / above window, per-kind filter, malformed-row graceful skip,
  OSError fallback to fixed.
* Threshold resolution wires into ``apply_group_proposals`` (verified
  via patched ``_compute_group_advantage``).
* Resample retry — fires only when both knobs enabled, recurses with
  ``_resample_attempt`` increment, respects budget, falls through to
  cycle skip on exhaustion.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


def _write_variance_row(
    path: Path,
    *,
    std: float,
    target_kind: str = "prompt",
    group_id: str | None = None,
    n_siblings: int = 2,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row: dict[str, Any] = {
        "ts": time.time(),
        "group_id": group_id or "g",
        "target_kind": target_kind,
        "std": float(std),
        "n_siblings": int(n_siblings),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------------------
# append_group_variance_history
# ---------------------------------------------------------------------------


def test_append_variance_history_creates_file_and_appends(tmp_path: Path) -> None:
    from core.self_improving_loop.runner import append_group_variance_history

    history = tmp_path / "variance.jsonl"
    ok = append_group_variance_history(
        group_id="g1",
        target_kind="prompt",
        std=0.07,
        n_siblings=2,
        history_path=history,
    )
    assert ok is True
    assert history.is_file()
    row = json.loads(history.read_text().strip())
    assert row["std"] == 0.07
    assert row["target_kind"] == "prompt"
    assert row["n_siblings"] == 2
    assert row["group_id"] == "g1"


def test_append_variance_history_failure_returns_false(tmp_path: Path) -> None:
    """OSError on write must not propagate — caller ignores the return
    value so telemetry failure can't break the mutator cycle."""
    from core.self_improving_loop.runner import append_group_variance_history

    history = tmp_path / "variance.jsonl"
    with patch.object(Path, "open", side_effect=OSError("disk full")):
        ok = append_group_variance_history(
            group_id="g1",
            target_kind="prompt",
            std=0.07,
            n_siblings=2,
            history_path=history,
        )
    assert ok is False


# ---------------------------------------------------------------------------
# resolve_group_variance_threshold
# ---------------------------------------------------------------------------


class _FakeAutoresearchCfg:
    """Minimal stand-in for ``AutoresearchConfig`` so tests don't
    have to construct the full pydantic model."""

    def __init__(
        self,
        *,
        mode: str = "fixed",
        fixed: float = 0.01,
        window: int = 30,
        percentile: float = 0.05,
    ) -> None:
        self.group_variance_threshold = fixed
        self.group_variance_threshold_mode = mode
        self.group_variance_history_window = window
        self.group_variance_percentile = percentile


def test_resolver_fixed_mode_returns_fixed(tmp_path: Path) -> None:
    from core.self_improving_loop.runner import resolve_group_variance_threshold

    cfg = _FakeAutoresearchCfg(mode="fixed", fixed=0.02)
    threshold, source = resolve_group_variance_threshold(
        cfg, history_path=tmp_path / "missing.jsonl"
    )
    assert threshold == 0.02
    assert source == "fixed"


def test_resolver_percentile_mode_fallback_when_history_short(tmp_path: Path) -> None:
    """Percentile mode with history shorter than the window falls back
    to the fixed value — operators can enable the knob without manually
    bootstrapping a synthetic history."""
    from core.self_improving_loop.runner import resolve_group_variance_threshold

    history = tmp_path / "variance.jsonl"
    # 5 rows but window=30 → fallback.
    for _ in range(5):
        _write_variance_row(history, std=0.1)

    cfg = _FakeAutoresearchCfg(mode="percentile", fixed=0.02, window=30)
    threshold, source = resolve_group_variance_threshold(
        cfg, target_kind="prompt", history_path=history
    )
    assert threshold == 0.02
    assert source == "fixed"


def test_resolver_percentile_mode_computes_percentile_when_window_met(tmp_path: Path) -> None:
    """Percentile mode with sufficient history returns the configured
    percentile of recent std values."""
    from core.self_improving_loop.runner import resolve_group_variance_threshold

    history = tmp_path / "variance.jsonl"
    # 30 rows, std=1..30, target_kind=prompt
    for i in range(1, 31):
        _write_variance_row(history, std=float(i))

    # 5th percentile of [1..30] ≈ 1 + 0.05 * 29 = 2.45
    cfg = _FakeAutoresearchCfg(mode="percentile", fixed=0.02, window=30, percentile=0.05)
    threshold, source = resolve_group_variance_threshold(
        cfg, target_kind="prompt", history_path=history
    )
    assert source == "percentile"
    assert abs(threshold - 2.45) < 0.01


def test_resolver_percentile_filters_by_target_kind(tmp_path: Path) -> None:
    """Per-kind percentile — when ``target_kind`` is provided, only
    matching rows count toward the window."""
    from core.self_improving_loop.runner import resolve_group_variance_threshold

    history = tmp_path / "variance.jsonl"
    # 30 prompt rows + 30 tool_policy rows. Asking for tool_policy
    # should ignore prompt rows.
    for _ in range(30):
        _write_variance_row(history, std=0.01, target_kind="prompt")
    for _ in range(30):
        _write_variance_row(history, std=5.0, target_kind="tool_policy")

    cfg = _FakeAutoresearchCfg(mode="percentile", fixed=0.02, window=30)
    threshold_prompt, _ = resolve_group_variance_threshold(
        cfg, target_kind="prompt", history_path=history
    )
    threshold_tool, _ = resolve_group_variance_threshold(
        cfg, target_kind="tool_policy", history_path=history
    )
    # prompt std all 0.01 → percentile ≈ 0.01
    assert abs(threshold_prompt - 0.01) < 0.001
    # tool_policy std all 5.0 → percentile ≈ 5.0
    assert abs(threshold_tool - 5.0) < 0.001


def test_resolver_handles_malformed_rows(tmp_path: Path) -> None:
    """Malformed JSON / non-dict / missing std → skipped silently. The
    scan must not abort on one bad row."""
    from core.self_improving_loop.runner import resolve_group_variance_threshold

    history = tmp_path / "variance.jsonl"
    # Mix valid + malformed
    _write_variance_row(history, std=0.1)
    with history.open("a", encoding="utf-8") as fh:
        fh.write("not-json\n")
        fh.write("\n")
        fh.write("[1, 2, 3]\n")
        fh.write('{"missing_std_field": true}\n')
    for _ in range(30):
        _write_variance_row(history, std=0.5)

    cfg = _FakeAutoresearchCfg(mode="percentile", fixed=0.02, window=30)
    threshold, source = resolve_group_variance_threshold(
        cfg, target_kind="prompt", history_path=history
    )
    # 31 valid rows total, take last 30 → all std=0.5 → percentile=0.5
    assert source == "percentile"
    assert abs(threshold - 0.5) < 0.001


def test_resolver_oserror_falls_back_to_fixed(tmp_path: Path) -> None:
    """Read failure (permission denied / disk error) → fall through to
    fixed value. The mutator cycle never crashes because the history
    file is unreadable."""
    from core.self_improving_loop.runner import resolve_group_variance_threshold

    history = tmp_path / "variance.jsonl"
    history.write_text("dummy\n")

    cfg = _FakeAutoresearchCfg(mode="percentile", fixed=0.02, window=30)
    with patch.object(Path, "open", side_effect=OSError("permission denied")):
        threshold, source = resolve_group_variance_threshold(
            cfg, target_kind="prompt", history_path=history
        )
    assert threshold == 0.02
    assert source == "fixed"


# ---------------------------------------------------------------------------
# Config schema invariants
# ---------------------------------------------------------------------------


def test_config_schema_defaults_preserve_legacy_behaviour() -> None:
    """The new knobs MUST default to the legacy single-shot fixed-
    threshold behaviour so existing operators see no change unless
    they opt-in."""
    from core.config.self_improving_loop import AutoresearchConfig

    cfg = AutoresearchConfig()
    assert cfg.group_variance_threshold_mode == "fixed"
    assert cfg.group_variance_history_window == 30
    assert cfg.group_variance_percentile == 0.05
    assert cfg.max_group_resamples == 0
    assert cfg.resample_on_low_variance is False


def test_config_schema_validation_bounds() -> None:
    """Pydantic Field bounds should reject out-of-range values so an
    operator can't misconfigure into an unreachable threshold."""
    from core.config.self_improving_loop import AutoresearchConfig
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AutoresearchConfig(group_variance_history_window=4)  # ge=5
    with pytest.raises(ValidationError):
        AutoresearchConfig(group_variance_percentile=0.0)  # gt=0
    with pytest.raises(ValidationError):
        AutoresearchConfig(group_variance_percentile=1.0)  # lt=1
    with pytest.raises(ValidationError):
        AutoresearchConfig(max_group_resamples=11)  # le=10
    with pytest.raises(ValidationError):
        AutoresearchConfig(max_group_resamples=-1)  # ge=0


# ---------------------------------------------------------------------------
# Gitignore invariant — variance history must be tracked
# ---------------------------------------------------------------------------


def test_apply_group_proposals_rejects_mixed_target_kinds() -> None:
    """Codex MCP review must-fix #1 — apply_group_proposals raises
    when sibling proposals span multiple target_kinds. The variance
    signal is only meaningful within a single SoT surface."""
    from core.self_improving_loop.runner import (
        Mutation,
        Proposal,
        SelfImprovingLoopRunner,
    )

    runner = SelfImprovingLoopRunner(rerun_enabled=False)
    p1 = Proposal(
        mutation=Mutation(
            target_section="role",
            new_value="x",
            rationale="y",
            target_kind="prompt",
        ),
        target_sections={"role": "orig"},
        original_sections={"role": "orig"},
    )
    p2 = Proposal(
        mutation=Mutation(
            target_section="rule",
            new_value="x",
            rationale="y",
            target_kind="tool_policy",
        ),
        target_sections={"rule": "orig"},
        original_sections={"rule": "orig"},
    )

    with pytest.raises(ValueError, match="homogeneous target_kind"):
        runner.apply_group_proposals([p1, p2])


def test_apply_group_proposals_resample_recurses_then_skips() -> None:
    """Codex MCP review must-fix #3 — direct apply_group_proposals
    test that exercises the resample budget. Mocks
    _run_autoresearch_subprocess to always return zero-variance
    fitness, mocks self.propose_group to return identical sibling
    sets, then asserts the function recursed ``max_group_resamples``
    times before falling through to ``None`` (cycle skip)."""
    from unittest.mock import MagicMock

    from core.self_improving_loop.runner import (
        Mutation,
        Proposal,
        SelfImprovingLoopRunner,
    )

    def _make_proposal() -> Proposal:
        return Proposal(
            mutation=Mutation(
                target_section="role",
                new_value="x",
                rationale="y",
                target_kind="prompt",
            ),
            target_sections={"role": "orig"},
            original_sections={"role": "orig"},
        )

    proposals = [_make_proposal(), _make_proposal()]

    # ``rerun_enabled=True`` + ``rerun_dry_run=False`` is required by
    # apply_group_proposals's safety gates (group sampling needs real
    # audit fitness to compute variance). The subprocess + parse are
    # mocked below so no real audit cost is incurred.
    runner = SelfImprovingLoopRunner(rerun_enabled=True, rerun_dry_run=False)
    # Force resample knobs on at the runtime read site.
    fake_cfg = MagicMock()
    fake_cfg.autoresearch.group_variance_threshold = 0.1
    fake_cfg.autoresearch.group_variance_threshold_mode = "fixed"
    fake_cfg.autoresearch.max_group_resamples = 2
    fake_cfg.autoresearch.resample_on_low_variance = True

    propose_calls: list[int] = []

    def fake_propose_group(self_: object, n: int) -> list[Proposal]:
        # Patched as a method on SelfImprovingLoopRunner → first arg is
        # the bound ``self`` (the runner instance). We don't use it,
        # just bounce N back as the proposal count.
        propose_calls.append(n)
        return [_make_proposal() for _ in range(n)]

    # _apply_sibling_in_memory_with_value writes a temp file; mock to
    # return a stable triple so the cleanup loop has something to unlink.
    def fake_apply_sibling(proposal: Proposal):  # type: ignore[no-untyped-def]
        return ({"role": "x"}, "orig", Path("/tmp/nonexistent"))  # noqa: S108

    # Fake the subprocess to return zero-variance fitness so
    # _compute_group_advantage returns ``filtered_low_variance``.
    fake_proc = MagicMock(stdout="audit_fitness=0.5\n")

    # The runner imports load_self_improving_loop_config lazily inside
    # apply_group_proposals, so patch the source module symbol (not the
    # runner-local re-export, which doesn't exist at module load time).
    with (
        patch(
            "core.config.self_improving_loop.load_self_improving_loop_config",
            return_value=fake_cfg,
        ),
        patch(
            "core.self_improving_loop.runner._apply_sibling_in_memory_with_value",
            side_effect=fake_apply_sibling,
        ),
        patch(
            "core.self_improving_loop.runner._run_autoresearch_subprocess",
            return_value=fake_proc,
        ),
        patch(
            "core.self_improving_loop.runner._parse_fitness_from_subprocess_stdout",
            return_value=0.5,
        ),
        patch.object(SelfImprovingLoopRunner, "propose_group", fake_propose_group),
    ):
        result = runner.apply_group_proposals(proposals)

    # All siblings score 0.5 → std=0 < threshold 0.1 → filtered.
    # Budget=2 → 2 retries before skip → propose_group invoked twice.
    assert result is None
    assert len(propose_calls) == 2
    assert propose_calls == [2, 2]


def test_variance_history_path_not_gitignored() -> None:
    """PR-G5b precedent — writer destination must be git-tracked, or
    the archive silently disappears under the broad
    ``autoresearch/state/*`` ignore."""
    # Use git check-ignore -v to inspect which rule matched. Exit code:
    #   0 = ignored, 1 = not ignored, other = error.
    import shutil
    import subprocess

    from core.paths import GROUP_VARIANCE_HISTORY_PATH

    git = shutil.which("git") or "git"
    result = subprocess.run(  # noqa: S603
        [git, "check-ignore", "-v", str(GROUP_VARIANCE_HISTORY_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        # Ignored — must have matched the negation, not the broad rule.
        assert "!autoresearch/state/group_variance_history.jsonl" in result.stdout, (
            f"group_variance_history.jsonl is git-ignored without "
            f"hitting the explicit negation rule. "
            f"stdout={result.stdout!r}"
        )
    # returncode==1 means not ignored at all → OK.
