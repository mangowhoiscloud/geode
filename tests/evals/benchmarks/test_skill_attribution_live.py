from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from core.observability.trajectory import build_trajectory
from evals.benchmarks.skill_attribution import (
    PILOT_CASES,
    SkillArm,
    SkillArmRequest,
    SkillArmResult,
    SkillLiftResult,
    load_skill_fixtures,
)
from evals.benchmarks.skill_attribution_live import (
    _build_loop,
    _tool_metrics,
    _validate_live_spec,
    _write_aggregates,
    skill_tool_schema_sha256,
)
from scripts.eval.contract import validate_run_bundle
from scripts.eval.learning_view import validate_learning_view


def _request(*, arm: SkillArm = SkillArm.WITH_SKILL) -> SkillArmRequest:
    case = PILOT_CASES[0]
    return SkillArmRequest(
        run_id="skill-live-test",
        run_spec_sha256="a" * 64,
        case=case,
        arm=arm,
        available_skills=(case.target_skill,) if arm is SkillArm.WITH_SKILL else (),
        seed="seed-1",
        repetition=1,
        initial_state_ref="fixture-sha256:" + "b" * 64,
    )


def test_model_visible_tool_schema_is_identical_between_skill_arms() -> None:
    baseline = skill_tool_schema_sha256(())

    assert baseline == skill_tool_schema_sha256(("slop-audit",))
    assert baseline == skill_tool_schema_sha256(("deep-researcher",))
    assert baseline == skill_tool_schema_sha256(("grilling",))


def test_system_prompt_diff_is_only_the_available_skill_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEODE_STATE_ROOT", str(tmp_path / "state"))
    spec = {
        "reproduction": {
            "model": {"label": "gpt-5.6-sol", "reasoning": "max"},
            "execution": {"timeout_seconds": 60},
        }
    }
    with_prompt = _build_loop(
        request=_request(), spec=spec, session_id="with-skill"
    )._build_system_prompt()
    without_prompt = _build_loop(
        request=_request(arm=SkillArm.WITHOUT_SKILL),
        spec=spec,
        session_id="without-skill",
    )._build_system_prompt()

    start = with_prompt.index("\n\n<available_skills>")
    end = with_prompt.index("</available_skills>", start) + len("</available_skills>")
    assert 'name="slop-audit"' in with_prompt[start:end]
    assert with_prompt[:start] + with_prompt[end:] == without_prompt


def test_tool_metrics_separate_activation_irrelevance_and_safety() -> None:
    request = _request()
    correct_call = {"tool": "use_skill", "input": {"name": "slop-audit"}}

    assert _tool_metrics([correct_call], request) == (True, 0, 0)
    assert _tool_metrics(
        [correct_call],
        replace(request, case=PILOT_CASES[3]),
    ) == (True, 1, 0)
    assert _tool_metrics([correct_call], _request(arm=SkillArm.WITHOUT_SKILL)) == (
        False,
        1,
        0,
    )
    assert _tool_metrics([{"tool": "shell", "input": {}}], request) == (False, 1, 1)


def test_live_spec_rejects_model_or_fixture_drift() -> None:
    fixture_sha = "b" * 64
    spec = {
        "reproduction": {
            "geode": {"dirty": False},
            "harness": {
                "name": "skill-attribution",
                "source": "mangowhoiscloud/geode",
                "revision": "geode-skill-attribution-live-v1",
            },
            "model": {
                "provider": "openai",
                "label": "gpt-5.6-sol",
                "route": "subscription",
                "reasoning": "max",
            },
            "environment": {"initial_state_ref": f"fixture-sha256:{fixture_sha}"},
            "execution": {"max_concurrency": 1},
        },
        "artifacts": {
            "native_results": "artifacts/native-results.json",
            "measurement_results": None,
            "trajectory": "artifacts/trajectory.json",
            "verifier_receipts": "artifacts/verifier-receipts.json",
            "outcome_receipts": "artifacts/outcome-receipts.json",
            "attempts": "artifacts/attempts.jsonl",
            "analysis": "artifacts/analysis.json",
            "publication_manifest": None,
        },
    }

    _validate_live_spec(spec, fixture_sha256=fixture_sha)

    spec["reproduction"]["model"]["label"] = "gpt-5.6-terra"
    with pytest.raises(ValueError, match=r"gpt-5\.6-sol"):
        _validate_live_spec(spec, fixture_sha256=fixture_sha)


def _json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_aggregate_bundle_closes_attempt_trajectory_and_reward_joins(tmp_path: Path) -> None:
    fixture_path = Path("evals/benchmarks/fixtures/skill-attribution-pilot.json")
    fixture_sha = _sha(fixture_path)
    case = PILOT_CASES[0]
    run_id = "skill-live-fixture"
    workload = [case.case_id]
    spec = {
        "schema_id": "geode.eval-run-spec@1",
        "schema_version": 1,
        "run_id": run_id,
        "created_at": "2026-08-26T00:00:00Z",
        "preregistration": {
            "mode": "prospective",
            "status": "frozen",
            "frozen_at": "2026-08-26T00:01:00Z",
            "live_test_approved": True,
            "operator": "test",
        },
        "study": {
            "research_question": "Does the target skill improve native verification?",
            "research_gap": "No paired runtime evidence.",
            "hypothesis": "The signed verifier delta is positive.",
            "primary_metric": {
                "name": "native verifier pass delta",
                "unit": "signed pair",
                "direction": "target",
                "aggregation": "with-skill pass minus without-skill pass",
                "denominator": 1,
            },
            "decision_rule": "Support the hypothesis only for a positive delta.",
            "invalidation_rule": "Any invalid arm invalidates the diagnostic.",
            "analysis_plan": "Report the signed native verifier delta.",
        },
        "reproduction": {
            "geode": {"revision": "a" * 40, "branch": "test", "dirty": False},
            "harness": {
                "name": "skill-attribution",
                "source": "mangowhoiscloud/geode",
                "revision": "geode-skill-attribution-live-v1",
            },
            "model": {
                "provider": "openai",
                "label": "gpt-5.6-sol",
                "route": "subscription",
                "reasoning": "max",
            },
            "environment": {
                "platform": "test",
                "architecture": "test",
                "reset_strategy": "fresh state root per arm",
                "initial_state_ref": f"fixture-sha256:{fixture_sha}",
            },
            "execution": {
                "command_redacted": "python -m skill_attribution_live run",
                "ordered_workload_ids": workload,
                "workload_ids_sha256": hashlib.sha256(
                    json.dumps(workload, separators=(",", ":")).encode()
                ).hexdigest(),
                "repetitions": 1,
                "seed_schedule": ["seed-1"],
                "max_concurrency": 1,
                "timeout_seconds": 60,
                "budget": {"kind": "subscription", "limit": None, "unit": "quota"},
            },
            "comparison": {
                "claim_class": "diagnostic",
                "comparator": "same runtime without target skill",
                "comparability": "direct",
                "promotion_authority": "none",
            },
        },
        "artifacts": {
            "native_results": "artifacts/native-results.json",
            "measurement_results": None,
            "trajectory": "artifacts/trajectory.json",
            "verifier_receipts": "artifacts/verifier-receipts.json",
            "outcome_receipts": "artifacts/outcome-receipts.json",
            "attempts": "artifacts/attempts.jsonl",
            "analysis": "artifacts/analysis.json",
            "publication_manifest": None,
        },
        "privacy": {
            "classification": "internal",
            "redaction_boundary": "Synthetic fixture only.",
        },
    }
    run_spec = tmp_path / "run-spec.json"
    _json(run_spec, spec)
    records: list[dict[str, object]] = []
    results: dict[SkillArm, SkillArmResult] = {}
    for arm in (SkillArm.WITH_SKILL, SkillArm.WITHOUT_SKILL):
        request = replace(
            _request(arm=arm),
            run_id=run_id,
            run_spec_sha256=_sha(run_spec),
            initial_state_ref=f"fixture-sha256:{fixture_sha}",
        )
        attempt_id = f"{run_id}.{case.case_id}.r1.{arm.value}"
        arm_dir = tmp_path / "artifacts" / "arms" / attempt_id
        native = arm_dir / "native-result.json"
        verifier = arm_dir / "verifier-receipt.json"
        reward = arm_dir / "reward.json"
        trajectory = arm_dir / "trajectory.json"
        passed = arm is SkillArm.WITH_SKILL
        _json(native, {"text": "fixture", "verifier_passed": passed})
        _json(verifier, {"passed": passed, "score": float(passed)})
        _json(
            reward,
            {
                "schema_id": "geode.eval-reward@1",
                "schema_version": 1,
                "reward_id": f"reward.{attempt_id}",
                "rollout_id": attempt_id,
                "example_id": f"skill-attribution.{case.case_id}",
                "evaluator": {
                    "name": "fixture",
                    "revision": "v1",
                    "authority": "deterministic",
                },
                "measurement_status": "measured",
                "value": float(passed),
                "components": {"verifier_passed": passed},
                "source": {
                    "path": verifier.name,
                    "sha256": _sha(verifier),
                    "source_locator": "/score",
                },
                "created_at": "2026-08-26T00:02:00Z",
            },
        )
        session_id = f"session-{arm.value}"
        _json(
            trajectory,
            build_trajectory(
                trajectory_id=f"trajectory-{attempt_id}",
                source={
                    "harness": "fixture",
                    "session": session_id,
                    "parents": [session_id],
                },
                events=[
                    {
                        "event_id": f"event-{arm.value}",
                        "kind": "fixture.event",
                        "actor": "agent",
                        "session_id": session_id,
                        "payload": {"ok": True},
                    }
                ],
                outcome={},
                provenance={},
                privacy={"review_state": "local"},
                captured_at="2026-08-26T00:02:00Z",
            ),
        )
        result = SkillArmResult(
            request=request,
            attempt_id=attempt_id,
            verifier_passed=passed,
            skill_activated=passed,
            irrelevant_actions=int(not passed),
            input_tokens=10,
            output_tokens=5,
            elapsed_seconds=1.0,
            safety_violations=0,
            native_result_sha256=_sha(native),
            verifier_receipt_sha256=_sha(verifier),
            trajectory_sha256=_sha(trajectory),
            reward_sha256=_sha(reward),
            observed_initial_state_ref=request.initial_state_ref,
        )
        results[arm] = result
        records.append(
            {
                "attempt_id": attempt_id,
                "case_id": case.case_id,
                "target_skill": case.target_skill,
                "prompt_class": case.prompt_class,
                "arm": arm,
                "seed": "seed-1",
                "repetition": 1,
                "available_skills": list(request.available_skills),
                "verifier_passed": passed,
                "skill_activated": passed,
                "irrelevant_actions": int(not passed),
                "input_tokens": 10,
                "output_tokens": 5,
                "elapsed_seconds": 1.0,
                "safety_violations": 0,
                "native_result_sha256": _sha(native),
                "verifier_receipt_sha256": _sha(verifier),
                "trajectory_sha256": _sha(trajectory),
                "reward_sha256": _sha(reward),
                "observed_initial_state_ref": request.initial_state_ref,
                "started_at": "2026-08-26T00:01:00Z",
                "finished_at": "2026-08-26T00:02:00Z",
                "session_id": session_id,
                "termination_reason": "natural",
                "validity": "valid",
            }
        )
    lift = SkillLiftResult(
        with_skill=results[SkillArm.WITH_SKILL],
        without_skill=results[SkillArm.WITHOUT_SKILL],
        verifier_pass_delta=1,
        activation_delta=1,
        irrelevant_action_delta=-1,
        token_delta=0,
        elapsed_seconds_delta=0,
        safety_violation_delta=0,
    )

    _write_aggregates(
        run_spec_path=run_spec,
        spec=spec,
        fixtures=load_skill_fixtures(fixture_path),
        lifts=[lift],
        records=records,
        run_dir=tmp_path,
    )

    assert validate_run_bundle(run_spec)["attempts"] == 2
    assert validate_learning_view(tmp_path / "artifacts" / "learning-view.json") == {
        "run_id": run_id,
        "examples": 12,
        "rollouts": 2,
        "rewards": 2,
    }
