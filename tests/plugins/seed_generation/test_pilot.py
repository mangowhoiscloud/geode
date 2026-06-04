"""Tests for ``plugins.seed_generation.agents.pilot`` (direct-audit Pilot).

PR-PILOT-UNIFY-DIM-EXTRACT (2026-06-04) — the Pilot no longer spawns an LLM
sub-agent that reformats audit scores into JSON. It calls
``plugins.petri_audit.runner.run_audit`` directly per candidate and reads the
archived ``.eval`` with ``core.audit.dim_extractor.extract_dim_aggregates`` —
the SAME authoritative converter + raw-Petri scale the campaign
(``core/self_improving/train.py``) uses.

These tests pin the unification invariants:

- a real ``.eval`` → correct ``dim_means`` straight from
  ``extract_dim_aggregates`` (no LLM in the loop, no zero-fill, no raise);
- a failed audit (no ``.eval`` / aborted) → candidate dropped gracefully;
- scale-parity: the pilot's ``dim_means`` for a candidate IS exactly what
  ``extract_dim_aggregates`` returns on the same ``.eval`` (proves seed-gen
  and campaign share one scale).

``run_audit`` + ``extract_dim_aggregates`` are monkeypatched (the real ones
spawn an ``inspect eval`` subprocess + need the ``[audit]`` extra). The Pilot
imports them lazily inside ``_run_one_audit``, so the patches target the
source modules.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import plugins.petri_audit.runner as petri_runner
import pytest
from core.audit import dim_extractor
from plugins.seed_generation.agents.pilot import Pilot
from plugins.seed_generation.orchestrator import PipelineState


class _FakeReport:
    """Minimal stand-in for ``plugins.petri_audit.runner.AuditReport``."""

    def __init__(
        self,
        *,
        archived_raw: str | None,
        aborted: bool = False,
        notes: list[str] | None = None,
        returncode: int | None = 0,
        stderr: str = "",
    ) -> None:
        self.archived_raw = archived_raw
        self.aborted = aborted
        self.notes = notes or []
        self.returncode = returncode
        self.stderr = stderr


def _patch_audit(
    monkeypatch: pytest.MonkeyPatch,
    *,
    report_by_path: dict[str, _FakeReport] | None = None,
    default_report: _FakeReport | None = None,
    aggregates_by_archive: dict[str, dict[str, Any]] | None = None,
    record_calls: list[dict[str, Any]] | None = None,
) -> None:
    """Wire fake ``run_audit`` + ``extract_dim_aggregates`` into the Pilot.

    ``report_by_path`` keys on the candidate's ``seed_select`` path; missing
    paths fall back to ``default_report``. ``aggregates_by_archive`` keys on
    the report's ``archived_raw`` path.
    """
    reports = report_by_path or {}
    aggregates = aggregates_by_archive or {}

    def fake_run_audit(**kwargs: Any) -> _FakeReport:
        if record_calls is not None:
            record_calls.append(dict(kwargs))
        seed_select = str(kwargs.get("seed_select"))
        report = reports.get(seed_select, default_report)
        assert report is not None, f"no fake report for {seed_select!r}"
        return report

    def fake_extract(eval_path: Any) -> dict[str, Any]:
        # The Pilot calls ``extract_dim_aggregates(Path(archive))``; match on
        # the same ``str(Path(...))`` normalisation so the fake's keys line up
        # whether the test passes a raw string or a Path-normalised one.
        key = str(Path(str(eval_path)))
        for archive, agg in aggregates.items():
            if str(Path(archive)) == key:
                return agg
        return {"dim_means": {}, "dim_stderr": {}}

    monkeypatch.setattr(petri_runner, "run_audit", fake_run_audit)
    monkeypatch.setattr(dim_extractor, "extract_dim_aggregates", fake_extract)


def _make_state(n: int = 3) -> PipelineState:
    state = PipelineState(
        run_id="t-pilot",
        target_dim="broken_tool_use",
        gen_tag="gen2",
        candidates_requested=n,
    )
    state.candidates = [
        {
            "id": f"gen2-{i:03d}-cand",
            "path": f"/fake-run/candidates/gen2-{i:03d}-cand.md",
            "target_dim": "broken_tool_use",
        }
        for i in range(n)
    ]
    return state


def test_pilot_validates_empty_candidates() -> None:
    state = PipelineState(run_id="t", target_dim="broken_tool_use", gen_tag="g")
    result = asyncio.run(Pilot().aexecute(state))
    assert not result.success
    assert result.error_category == "validation"


def test_pilot_dim_means_come_from_extract_dim_aggregates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real ``.eval`` → dim_means straight from the canonical extractor."""
    state = _make_state(1)
    path = state.candidates[0]["path"]
    archive = "archive://run-000.eval"
    real_means = {"broken_tool_use": 3.4, "input_hallucination": 2.1, "overrefusal": 1.0}
    _patch_audit(
        monkeypatch,
        report_by_path={path: _FakeReport(archived_raw=archive)},
        aggregates_by_archive={
            archive: {
                "dim_means": real_means,
                "dim_stderr": {"broken_tool_use": 0.2, "input_hallucination": 0.18},
            }
        },
    )
    result = asyncio.run(Pilot().aexecute(state))
    assert result.success
    pilot = result.output["pilot_scores"]["gen2-000-cand"]
    # Exactly the extractor's output — no LLM reformat, no rescaling.
    assert pilot["dim_means"] == real_means
    assert pilot["status"] == "ok"
    assert pilot["candidate_id"] == "gen2-000-cand"


def test_pilot_scale_parity_with_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scale-parity: pilot dim_means == extract_dim_aggregates on the SAME .eval.

    This is the unification proof — the seed-gen pilot reports the identical
    numbers the campaign's ``run_audit`` → ``extract_dim_aggregates`` would.
    """
    state = _make_state(1)
    path = state.candidates[0]["path"]
    archive = "archive://parity.eval"
    extractor_output = {
        "dim_means": {"broken_tool_use": 5.0, "stuck_in_loops": 2.5, "overrefusal": 1.0},
        "dim_stderr": {"broken_tool_use": 0.3},
        "sample_count": {"broken_tool_use": 3},
    }
    _patch_audit(
        monkeypatch,
        report_by_path={path: _FakeReport(archived_raw=archive)},
        aggregates_by_archive={archive: extractor_output},
    )
    result = asyncio.run(Pilot().aexecute(state))
    pilot = result.output["pilot_scores"]["gen2-000-cand"]
    # Byte-for-byte the extractor's dim_means (the campaign's scale).
    assert pilot["dim_means"] == extractor_output["dim_means"]
    assert pilot["dim_stderr"] == extractor_output["dim_stderr"]


def test_pilot_drops_candidate_when_audit_aborted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Audit aborted (no .eval — e.g. [audit] extra missing) → drop gracefully."""
    state = _make_state(1)
    path = state.candidates[0]["path"]
    _patch_audit(
        monkeypatch,
        report_by_path={
            path: _FakeReport(archived_raw=None, aborted=True, notes=["inspect not found"])
        },
    )
    result = asyncio.run(Pilot().aexecute(state))
    assert not result.success
    assert result.error_category == "pilot_failed"
    assert "inspect not found" in (result.error_message or "")


def test_pilot_drops_candidate_when_no_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Audit ran but produced no .eval archive → drop gracefully (no raise)."""
    state = _make_state(1)
    path = state.candidates[0]["path"]
    _patch_audit(
        monkeypatch,
        report_by_path={path: _FakeReport(archived_raw=None, aborted=False)},
    )
    result = asyncio.run(Pilot().aexecute(state))
    assert not result.success
    assert result.error_category == "pilot_failed"


def test_pilot_drops_candidate_on_nonzero_returncode(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-zero inspect_ai exit is a failure even if a partial .eval archived.

    Matches the campaign's semantics (``train.py:run_audit`` raises on
    returncode != 0; ``cli_audit`` suppresses emission). Without this check a
    partial / failed audit could merge as ``ok``.
    """
    state = _make_state(1)
    path = state.candidates[0]["path"]
    archive = "archive://partial.eval"
    _patch_audit(
        monkeypatch,
        report_by_path={
            path: _FakeReport(archived_raw=archive, returncode=1, stderr="boom\ntraceback")
        },
        # Even though the extractor WOULD return scores, the returncode gate
        # fires first → the candidate is dropped before extraction matters.
        aggregates_by_archive={archive: {"dim_means": {"broken_tool_use": 3.0}, "dim_stderr": {}}},
    )
    result = asyncio.run(Pilot().aexecute(state))
    assert not result.success
    assert result.error_category == "pilot_failed"
    assert "exit=1" in (result.error_message or "")


def test_pilot_drops_candidate_when_extractor_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """A .eval that yields zero scored samples → empty dim_means → drop.

    No zero-fill: an empty measurement must not be merged into the Ranker's
    difficulty-selection input.
    """
    state = _make_state(1)
    path = state.candidates[0]["path"]
    archive = "archive://empty.eval"
    _patch_audit(
        monkeypatch,
        report_by_path={path: _FakeReport(archived_raw=archive)},
        aggregates_by_archive={archive: {"dim_means": {}, "dim_stderr": {}}},
    )
    result = asyncio.run(Pilot().aexecute(state))
    assert not result.success
    assert result.error_category == "pilot_failed"


def test_pilot_low_engagement_when_few_dims(monkeypatch: pytest.MonkeyPatch) -> None:
    """Audit ran but < _MIN_ENGAGED_DIMS non-zero → low_engagement, still merged."""
    state = _make_state(1)
    path = state.candidates[0]["path"]
    archive = "archive://sparse.eval"
    _patch_audit(
        monkeypatch,
        report_by_path={path: _FakeReport(archived_raw=archive)},
        aggregates_by_archive={
            archive: {
                # only ONE non-zero dim (the rest scored 0) → below the bar.
                "dim_means": {"broken_tool_use": 4.0, "overrefusal": 0.0, "stuck_in_loops": 0.0},
                "dim_stderr": {"broken_tool_use": 0.1},
            }
        },
    )
    result = asyncio.run(Pilot().aexecute(state))
    assert result.success
    pilot = result.output["pilot_scores"]["gen2-000-cand"]
    assert pilot["status"] == "low_engagement"
    # low_engagement still carries the real measurement (Ranker deprioritises).
    assert pilot["dim_means"]["broken_tool_use"] == 4.0


def test_pilot_partial_failure_keeps_good_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    """One candidate's audit fails; the others' real scores still come through."""
    state = _make_state(3)
    paths = [c["path"] for c in state.candidates]
    _patch_audit(
        monkeypatch,
        report_by_path={
            paths[0]: _FakeReport(archived_raw="archive://a.eval"),
            paths[1]: _FakeReport(archived_raw=None, aborted=True, notes=["boom"]),
            paths[2]: _FakeReport(archived_raw="archive://c.eval"),
        },
        aggregates_by_archive={
            "archive://a.eval": {
                "dim_means": {"broken_tool_use": 2.0, "overrefusal": 1.0, "stuck_in_loops": 1.5},
                "dim_stderr": {},
            },
            "archive://c.eval": {
                "dim_means": {"broken_tool_use": 3.0, "overrefusal": 2.0, "stuck_in_loops": 1.0},
                "dim_stderr": {},
            },
        },
    )
    result = asyncio.run(Pilot().aexecute(state))
    assert result.success
    scores = result.output["pilot_scores"]
    assert set(scores) == {"gen2-000-cand", "gen2-002-cand"}
    assert "gen2-001-cand" not in scores


def test_pilot_passes_campaign_target_and_dim_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_audit is called with the campaign's gpt-5.5 target + 'subset' dims."""
    state = _make_state(1)
    path = state.candidates[0]["path"]
    calls: list[dict[str, Any]] = []
    _patch_audit(
        monkeypatch,
        report_by_path={path: _FakeReport(archived_raw="archive://x.eval")},
        aggregates_by_archive={
            "archive://x.eval": {
                "dim_means": {"broken_tool_use": 2.0, "overrefusal": 1.0, "stuck_in_loops": 1.0},
                "dim_stderr": {},
            }
        },
        record_calls=calls,
    )
    asyncio.run(Pilot().aexecute(state))
    assert len(calls) == 1
    call = calls[0]
    assert call["target"] == "gpt-5.5"
    assert call["dim_set"] == "subset"
    assert call["dry_run"] is False
    assert call["seed_select"] == path
    # multisample so rank_by_difficulty uses a central estimate, not one draw.
    assert call["seeds"] >= 2


def test_pilot_drops_candidate_without_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """A candidate dict missing ``path`` is dropped, not crashed."""
    state = _make_state(1)
    state.candidates[0].pop("path")
    _patch_audit(monkeypatch, default_report=_FakeReport(archived_raw="archive://never.eval"))
    result = asyncio.run(Pilot().aexecute(state))
    assert not result.success
    assert result.error_category == "pilot_failed"
