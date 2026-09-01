from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from evals.benchmarks.skill_attribution import SkillArm
from evals.benchmarks.skill_attribution_native import (
    NativeArmRecord,
    NativeSplit,
    NativeTaskFamily,
    analyze_native_skill_pairs,
    load_native_skill_suite,
    native_model_view,
    pair_native_skill_arms,
    preflight_native_tool_surfaces,
    validate_native_run_spec,
    verify_native_skill_output,
)

FIXTURE = Path("evals/benchmarks/fixtures/skill-attribution-native.json")


def _record(case, repetition: int, arm: SkillArm) -> NativeArmRecord:
    with_skill = arm is SkillArm.WITH_SKILL
    positive = not case.negative_control
    return NativeArmRecord(
        attempt_id=f"{case.case_id}-{repetition}-{arm.value}",
        case_id=case.case_id,
        repetition=repetition,
        arm=arm,
        available_skills=(case.target_skill,) if with_skill else (),
        tool_schema_sha256="a" * 64,
        response_schema_sha256=case.response_schema_sha256,
        workspace_sha256=case.workspace_sha256,
        reset_state_sha256=case.workspace_sha256,
        verifier_sha256=case.verifier_sha256,
        verifier_passed=(positive and with_skill) or case.negative_control,
        skill_selected=positive and with_skill,
        skill_activated=positive and with_skill,
        irrelevant_actions=0,
        input_tokens=12 if with_skill else 10,
        output_tokens=5,
        elapsed_seconds=2.0 if with_skill else 1.0,
        safety_violations=0,
    )


def _run_spec(path: Path, suite, split: NativeSplit, *, approved: bool) -> Path:
    cases = suite.cases_for(split)
    workload = [case.case_id for case in cases]
    repetitions = 1 if split is NativeSplit.DESIGN else 3
    workload_hash = hashlib.sha256(
        json.dumps(workload, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    payload = {
        "schema_id": "geode.eval-run-spec@1",
        "schema_version": 1,
        "run_id": f"native-skill-{split.value}-test",
        "created_at": "2026-09-01T00:00:00Z",
        "preregistration": {
            "mode": "prospective",
            "status": "frozen",
            "frozen_at": "2026-09-01T00:01:00Z",
            "live_test_approved": approved,
            "operator": "test",
        },
        "study": {
            "research_question": "Does target Skill availability improve native outcomes?",
            "research_gap": "Synthetic tasks do not establish native capability.",
            "hypothesis": "Family-conditioned source-example ITT is positive.",
            "primary_metric": {
                "name": "family-conditioned source-example ITT",
                "unit": "signed verifier pass",
                "direction": "maximize",
                "aggregation": "mean pair delta by source example within family",
                "denominator": len(cases),
            },
            "decision_rule": "Diagnostic only; report null or adverse results unchanged.",
            "invalidation_rule": "Invalidate any treatment, workspace, or verifier drift.",
            "analysis_plan": "Report each family and process metric separately.",
        },
        "reproduction": {
            "geode": {"revision": "a" * 40, "branch": "test", "dirty": False},
            "harness": {
                "name": "skill-attribution-native",
                "source": "mangowhoiscloud/geode",
                "revision": "geode-skill-attribution-native-v1",
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
                "reset_strategy": "fresh isolated fixture before every arm",
                "initial_state_ref": f"suite-sha256:{suite.sha256}:split:{split.value}",
            },
            "execution": {
                "command_redacted": "pytest native Skill contract",
                "ordered_workload_ids": workload,
                "workload_ids_sha256": workload_hash,
                "repetitions": repetitions,
                "seed_schedule": [
                    f"unseeded-repetition-{index}" for index in range(1, repetitions + 1)
                ],
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
            "redaction_boundary": "Fixtures contain only public or synthetic data.",
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_native_suite_freezes_split_family_and_model_visibility() -> None:
    suite = load_native_skill_suite(FIXTURE)

    assert len(suite.cases_for(NativeSplit.DESIGN)) == 6
    assert len(suite.cases_for(NativeSplit.EVALUATION)) == 12
    assert {case.family for case in suite.cases} == set(NativeTaskFamily)
    assert not {case.example_id for case in suite.cases_for(NativeSplit.DESIGN)}.intersection(
        case.example_id for case in suite.cases_for(NativeSplit.EVALUATION)
    )
    assert all("verifier" not in native_model_view(case) for case in suite.cases)
    repository_case = next(
        case for case in suite.cases if case.case_id == "repository-eval-placeholder-body"
    )
    repository_view = json.dumps(native_model_view(repository_case))
    assert "src/export.py" in repository_view
    assert "def export_report" not in repository_view


def test_native_suite_rejects_verifier_terms_in_delegated_briefs(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    case = next(row for row in payload["cases"] if row["case_id"] == "delegation-eval-risk-owners")
    case["model_fixture"]["subtasks"][0]["brief"] += " evaluator-only receipts"
    path = tmp_path / "leaked.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="leaks verifier terms"):
        load_native_skill_suite(path)


def test_native_suite_rejects_nonfinite_json_and_non_https_sources(tmp_path: Path) -> None:
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text(
        FIXTURE.read_text(encoding="utf-8").replace(
            '"schema_version": 1', '"schema_version": NaN', 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="non-finite JSON value"):
        load_native_skill_suite(nonfinite)

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    case = next(
        row for row in payload["cases"] if row["case_id"] == "web-design-codex-skill-loading"
    )
    case["model_fixture"]["sources"][0]["url"] = "http://example.invalid/source"
    insecure = tmp_path / "insecure.json"
    insecure.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid source identity"):
        load_native_skill_suite(insecure)


def test_native_verifier_separates_outcome_from_skill_activation() -> None:
    suite = load_native_skill_suite(FIXTURE)
    case = next(case for case in suite.cases if case.case_id == "web-design-codex-skill-loading")
    receipt = verify_native_skill_output(
        case,
        json.dumps(
            {
                "answer": "The explicit item injects full skill instructions; name-only lookup can add latency.",
                "source_ids": ["codex-app-server"],
            }
        ),
        ("general_web_search", "web_fetch"),
    )

    assert receipt.passed is True
    assert "use_skill" not in case.required_tool_names
    assert replace(receipt, missing_tools=("web_fetch",), passed=False).passed is False


def test_native_pair_rejects_treatment_and_workspace_drift() -> None:
    case = load_native_skill_suite(FIXTURE).cases[0]
    with_skill = _record(case, 1, SkillArm.WITH_SKILL)
    without_skill = _record(case, 1, SkillArm.WITHOUT_SKILL)

    pair = pair_native_skill_arms(case, with_skill, without_skill)
    assert pair.outcome_delta == 1
    assert pair.selection_delta == 1
    assert pair.activation_delta == 1

    with pytest.raises(ValueError, match="workspace, reset, response, or verifier"):
        pair_native_skill_arms(
            case,
            replace(with_skill, reset_state_sha256="b" * 64),
            without_skill,
        )
    with pytest.raises(ValueError, match="more than target-Skill availability"):
        pair_native_skill_arms(
            case,
            replace(with_skill, available_skills=(case.target_skill, "extra")),
            without_skill,
        )


def test_native_analysis_clusters_repetitions_and_never_builds_a_composite() -> None:
    suite = load_native_skill_suite(FIXTURE)
    pairs = []
    for case in suite.cases_for(NativeSplit.EVALUATION):
        for repetition in range(1, 4):
            pairs.append(
                pair_native_skill_arms(
                    case,
                    _record(case, repetition, SkillArm.WITH_SKILL),
                    _record(case, repetition, SkillArm.WITHOUT_SKILL),
                )
            )

    analyses = analyze_native_skill_pairs(suite, pairs)

    assert len(analyses) == 3
    assert all(result.source_examples == 3 for result in analyses)
    assert all(result.pairs == 9 for result in analyses)
    assert all(result.outcome_itt == 1.0 for result in analyses)
    assert all(result.outcome_ci95 == (1.0, 1.0) for result in analyses)
    assert all(result.negative_control_pairs == 3 for result in analyses)
    assert all(result.negative_control_pass_rate == 1.0 for result in analyses)
    assert all(result.negative_control_activation_rate == 0.0 for result in analyses)
    assert all(result.decision == "diagnostic-only" for result in analyses)


def test_native_tool_preflight_uses_matched_production_schemas() -> None:
    digests = preflight_native_tool_surfaces(load_native_skill_suite(FIXTURE))

    assert set(digests) == {family.value for family in NativeTaskFamily}
    assert all(len(digest) == 64 for digest in digests.values())


def test_native_run_spec_binds_one_split_and_requires_live_approval(tmp_path: Path) -> None:
    suite = load_native_skill_suite(FIXTURE)
    run_spec = _run_spec(tmp_path / "run-spec.json", suite, NativeSplit.DESIGN, approved=False)

    validate_native_run_spec(run_spec, suite, split=NativeSplit.DESIGN)
    with pytest.raises(ValueError, match="explicit approval"):
        validate_native_run_spec(run_spec, suite, split=NativeSplit.DESIGN, execute=True)
