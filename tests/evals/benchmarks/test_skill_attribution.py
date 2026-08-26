from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from evals.benchmarks.skill_attribution import (
    PILOT_CASES,
    PromptClass,
    SkillArm,
    SkillArmRequest,
    SkillArmResult,
    SkillCase,
    run_skill_suite,
    validate_skill_case_matrix,
)


def _write_run_spec(
    path: Path,
    cases: tuple[SkillCase, ...],
    *,
    approved: bool = True,
    repetitions: int = 2,
) -> Path:
    workload = [case.case_id for case in cases]
    workload_hash = hashlib.sha256(
        json.dumps(workload, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    payload = {
        "schema_id": "geode.eval-run-spec@1",
        "schema_version": 1,
        "run_id": "skill-lift-test",
        "created_at": "2026-08-26T00:00:00Z",
        "preregistration": {
            "mode": "prospective",
            "status": "frozen",
            "frozen_at": "2026-08-26T00:01:00Z",
            "live_test_approved": approved,
            "operator": "test",
        },
        "study": {
            "research_question": "Does the target skill improve native verifier outcomes?",
            "research_gap": "Repository scans do not measure causal runtime skill value.",
            "hypothesis": "The with-skill arm has a positive verifier-pass delta.",
            "primary_metric": {
                "name": "verifier pass delta",
                "unit": "signed pair",
                "direction": "maximize",
                "aggregation": "with-skill pass minus without-skill pass",
                "denominator": len(cases) * repetitions,
            },
            "decision_rule": "Supported only when the mean signed verifier delta is positive.",
            "invalidation_rule": "Invalidate any pair with identity or initial-state drift.",
            "analysis_plan": "Report verifier lift first and process metrics separately.",
        },
        "reproduction": {
            "geode": {"revision": "a" * 40, "branch": "test", "dirty": False},
            "harness": {
                "name": "skill-attribution",
                "source": "geode",
                "revision": "test-v1",
            },
            "model": {
                "provider": "test",
                "label": "fake-model",
                "route": "none",
                "reasoning": "deterministic",
            },
            "environment": {
                "platform": "test",
                "architecture": "test",
                "reset_strategy": "fresh fixture before every arm",
                "initial_state_ref": "fixture-sha256:" + "c" * 64,
            },
            "execution": {
                "command_redacted": "pytest fake skill runner",
                "ordered_workload_ids": workload,
                "workload_ids_sha256": workload_hash,
                "repetitions": repetitions,
                "seed_schedule": [f"seed-{index}" for index in range(repetitions)],
                "max_concurrency": 1,
                "timeout_seconds": 60,
                "budget": {"kind": "wall-time", "limit": 60, "unit": "seconds"},
            },
            "comparison": {
                "claim_class": "diagnostic",
                "comparator": "same runtime without target skill",
                "comparability": "direct",
                "promotion_authority": "none",
            },
        },
        "artifacts": {
            "native_results": None,
            "measurement_results": None,
            "trajectory": None,
            "verifier_receipts": None,
            "outcome_receipts": None,
            "attempts": "artifacts/attempts.jsonl",
            "analysis": "artifacts/analysis.json",
            "publication_manifest": None,
        },
        "privacy": {
            "classification": "internal",
            "redaction_boundary": "The fake fixture contains no private or model-generated data.",
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _result(request: SkillArmRequest) -> SkillArmResult:
    enabled = request.arm is SkillArm.WITH_SKILL
    return SkillArmResult(
        request=request,
        attempt_id=f"{request.case.case_id}-{request.repetition}-{request.arm}",
        verifier_passed=enabled,
        skill_activated=enabled,
        irrelevant_actions=int(not enabled),
        input_tokens=10 + int(enabled),
        output_tokens=5,
        elapsed_seconds=2.0 + int(enabled),
        safety_violations=0,
        native_result_sha256="b" * 64,
        verifier_receipt_sha256="c" * 64,
        trajectory_sha256="d" * 64,
        reward_sha256="e" * 64,
        observed_initial_state_ref=request.initial_state_ref,
    )


def test_pilot_matrix_covers_four_prompt_classes_per_skill() -> None:
    rows = validate_skill_case_matrix(PILOT_CASES)
    assert {row.target_skill for row in rows} == {
        "deep-researcher",
        "grilling",
        "slop-audit",
    }
    assert len(rows) == 12


def test_runner_changes_only_skill_availability_and_reports_native_lift(tmp_path: Path) -> None:
    cases = PILOT_CASES[:4]
    spec = _write_run_spec(tmp_path / "run-spec.json", cases)
    observed: list[SkillArmRequest] = []

    def run(request: SkillArmRequest) -> SkillArmResult:
        observed.append(request)
        return _result(request)

    results = run_skill_suite(spec, cases, ("geode-context",), run)

    assert len(results) == 8
    assert [request.arm for request in observed[:4]] == [
        SkillArm.WITH_SKILL,
        SkillArm.WITHOUT_SKILL,
        SkillArm.WITHOUT_SKILL,
        SkillArm.WITH_SKILL,
    ]
    assert all(result.verifier_pass_delta == 1 for result in results)
    assert all(result.activation_delta == 1 for result in results)
    assert all(result.irrelevant_action_delta == -1 for result in results)
    assert all(result.token_delta == 1 for result in results)
    assert all(result.elapsed_seconds_delta == 1.0 for result in results)
    for result in results:
        assert result.with_skill.request.available_skills == (
            "geode-context",
            "slop-audit",
        )
        assert result.without_skill.request.available_skills == ("geode-context",)
        assert result.with_skill.request.case == result.without_skill.request.case


def test_runner_fails_closed_on_unapproved_live_run_and_result_drift(tmp_path: Path) -> None:
    cases = PILOT_CASES[:4]
    unapproved = _write_run_spec(
        tmp_path / "unapproved.json",
        cases,
        approved=False,
        repetitions=1,
    )
    with pytest.raises(ValueError, match="explicit live-test approval"):
        run_skill_suite(unapproved, cases, (), _result)

    approved = _write_run_spec(tmp_path / "approved.json", cases, repetitions=1)

    def drift(request: SkillArmRequest) -> SkillArmResult:
        result = _result(request)
        return replace(result, observed_initial_state_ref="different-state")

    with pytest.raises(ValueError, match="changed the frozen initial state"):
        run_skill_suite(approved, cases, (), drift)


def test_case_matrix_rejects_missing_prompt_class() -> None:
    cases = tuple(case for case in PILOT_CASES[:4] if case.prompt_class is not PromptClass.EXPLICIT)
    with pytest.raises(ValueError, match="all four prompt classes"):
        validate_skill_case_matrix(cases)
