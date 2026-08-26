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
    build_skill_prompt,
    load_skill_fixtures,
    run_skill_suite,
    skill_response_schema,
    validate_skill_case_matrix,
    verify_skill_output,
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


def test_native_fixture_covers_the_frozen_case_matrix() -> None:
    fixture_path = Path("evals/benchmarks/fixtures/skill-attribution-pilot.json")
    fixtures = load_skill_fixtures(fixture_path)

    assert tuple(fixture.case_id for fixture in fixtures) == tuple(
        case.case_id for case in PILOT_CASES
    )


def test_native_fixture_rejects_required_ids_hidden_from_context(tmp_path: Path) -> None:
    source = Path("evals/benchmarks/fixtures/skill-attribution-pilot.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["cases"][4]["context"] = payload["cases"][4]["context"].replace("f1", "hidden")
    fixture_path = tmp_path / "fixtures.json"
    fixture_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=r"hides required IDs.*f1"):
        load_skill_fixtures(fixture_path)


def test_native_fixture_rejects_model_visible_answer_terms_and_semantic_ids(
    tmp_path: Path,
) -> None:
    source = Path("evals/benchmarks/fixtures/skill-attribution-pilot.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["cases"][0]["context"] += " This is a repeated implementation."
    leaked_path = tmp_path / "leaked.json"
    leaked_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=r"leaks required answer terms.*repeated implementation"):
        load_skill_fixtures(leaked_path)

    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["cases"][0]["required_finding_ids"][0] = "duplicate-normalize"
    payload["cases"][0]["context"] = payload["cases"][0]["context"].replace(
        "f1", "duplicate-normalize"
    )
    semantic_path = tmp_path / "semantic.json"
    semantic_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=r"finding IDs must be opaque"):
        load_skill_fixtures(semantic_path)

    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["cases"][8]["required_question_ids"][0] = "state-owner"
    payload["cases"][8]["context"] = payload["cases"][8]["context"].replace("q1", "state-owner")
    question_path = tmp_path / "semantic-question.json"
    question_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=r"question IDs must be opaque"):
        load_skill_fixtures(question_path)


def test_skill_prompt_is_arm_independent_and_uses_the_strict_response_shape() -> None:
    fixture = load_skill_fixtures(Path("evals/benchmarks/fixtures/skill-attribution-pilot.json"))[0]
    prompt = build_skill_prompt(PILOT_CASES[0], fixture)
    finding_schema = skill_response_schema(PILOT_CASES[0])
    decision_schema = skill_response_schema(PILOT_CASES[8])

    assert PILOT_CASES[0].prompt in prompt
    assert fixture.context in prompt
    assert "with-skill" not in prompt
    assert "without-skill" not in prompt
    assert set(finding_schema["required"]) == {"answer", "evidence_ids", "finding_ids"}
    assert set(decision_schema["required"]) == {"answer", "evidence_ids", "questions"}
    assert "questions" not in finding_schema["properties"]
    assert "finding_ids" not in decision_schema["properties"]
    assert finding_schema["additionalProperties"] is False
    assert "uniqueItems" not in json.dumps((finding_schema, decision_schema))

    with pytest.raises(ValueError, match="identities differ"):
        build_skill_prompt(PILOT_CASES[1], fixture)


def test_native_verifier_requires_exact_evidence_findings_and_question_shape() -> None:
    fixture_path = Path("evals/benchmarks/fixtures/skill-attribution-pilot.json")
    fixtures = {row.case_id: row for row in load_skill_fixtures(fixture_path)}
    slop = fixtures["slop-explicit"]
    grill = fixtures["grill-explicit"]

    slop_result = verify_skill_output(
        json.dumps(
            {
                "answer": (
                    "Repeated implementation, empty implementation, and deferred cleanup found"
                ),
                "evidence_ids": ["alpha.py:1", "beta.py:1", "gamma.py:1", "delta.py:1"],
                "finding_ids": ["f1", "f2", "f3"],
            }
        ),
        PILOT_CASES[0],
        slop,
    )
    assert slop_result.passed is True

    grill_result = verify_skill_output(
        json.dumps(
            {
                "answer": "The ordering and reversibility boundaries remain unresolved",
                "evidence_ids": [],
                "questions": [
                    {
                        "id": question_id,
                        "options": ["A", "B"],
                        "recommendation": "Choose A after resolving the boundary",
                    }
                    for question_id in (
                        "q1",
                        "q2",
                        "q3",
                    )
                ],
            }
        ),
        PILOT_CASES[8],
        grill,
    )
    assert grill_result.passed is True

    malformed_grill = verify_skill_output(
        json.dumps(
            {
                "answer": "ordering reversibility",
                "evidence_ids": [],
                "questions": [
                    {"id": "q1", "options": ["A", 2], "recommendation": "A"},
                    {
                        "id": "q2",
                        "options": ["A", "B"],
                        "recommendation": "A",
                    },
                    {
                        "id": "q3",
                        "options": ["A", "B"],
                        "recommendation": "A",
                    },
                ],
            }
        ),
        PILOT_CASES[8],
        grill,
    )
    assert malformed_grill.passed is False
    assert malformed_grill.malformed_question_ids == ("q1",)

    extra_finding = verify_skill_output(
        json.dumps(
            {
                "answer": "distribution archive install",
                "evidence_ids": [],
                "finding_ids": ["invented"],
            }
        ),
        PILOT_CASES[3],
        fixtures["slop-negative"],
    )
    assert extra_finding.passed is False
    assert extra_finding.unexpected_finding_ids == ("invented",)

    duplicate_evidence = verify_skill_output(
        json.dumps(
            {
                "answer": (
                    "Repeated implementation, empty implementation, and deferred cleanup found"
                ),
                "evidence_ids": ["alpha.py:1", "alpha.py:1"],
                "finding_ids": ["f1", "f2", "f3"],
            }
        ),
        PILOT_CASES[0],
        slop,
    )
    assert duplicate_evidence.passed is False
    assert duplicate_evidence.parse_error == (
        "response evidence_ids must contain unique non-empty strings"
    )
