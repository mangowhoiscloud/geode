"""Paired causal evaluation of one runtime skill at a time."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

SKILL_FIXTURE_SCHEMA = "geode.skill-attribution-fixtures.v1"
SKILL_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "minLength": 1},
        "evidence_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        },
        "finding_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        },
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "options": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 2,
                    },
                    "recommendation": {"type": "string", "minLength": 1},
                },
                "required": ["id", "options", "recommendation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer", "evidence_ids", "finding_ids", "questions"],
    "additionalProperties": False,
}


class PromptClass(StrEnum):
    EXPLICIT = "explicit"
    IMPLICIT = "implicit"
    CONTEXTUAL = "contextual"
    NEGATIVE_CONTROL = "negative-control"


class SkillArm(StrEnum):
    WITH_SKILL = "with-skill"
    WITHOUT_SKILL = "without-skill"


@dataclass(frozen=True, slots=True)
class SkillCase:
    case_id: str
    target_skill: str
    prompt_class: PromptClass
    prompt: str


@dataclass(frozen=True, slots=True)
class SkillArmRequest:
    run_id: str
    run_spec_sha256: str
    case: SkillCase
    arm: SkillArm
    available_skills: tuple[str, ...]
    seed: str
    repetition: int
    initial_state_ref: str


@dataclass(frozen=True, slots=True)
class SkillArmResult:
    request: SkillArmRequest
    attempt_id: str
    verifier_passed: bool
    skill_activated: bool
    irrelevant_actions: int
    input_tokens: int
    output_tokens: int
    elapsed_seconds: float
    safety_violations: int
    native_result_sha256: str
    verifier_receipt_sha256: str
    trajectory_sha256: str
    reward_sha256: str
    observed_initial_state_ref: str


@dataclass(frozen=True, slots=True)
class SkillLiftResult:
    with_skill: SkillArmResult
    without_skill: SkillArmResult
    verifier_pass_delta: int
    activation_delta: int
    irrelevant_action_delta: int
    token_delta: int
    elapsed_seconds_delta: float
    safety_violation_delta: int


@dataclass(frozen=True, slots=True)
class SkillFixture:
    case_id: str
    context: str
    required_evidence_ids: tuple[str, ...]
    required_finding_ids: tuple[str, ...]
    required_answer_terms: tuple[str, ...]
    required_question_ids: tuple[str, ...]
    max_questions: int


@dataclass(frozen=True, slots=True)
class SkillVerification:
    passed: bool
    missing_evidence_ids: tuple[str, ...]
    unexpected_evidence_ids: tuple[str, ...]
    missing_finding_ids: tuple[str, ...]
    unexpected_finding_ids: tuple[str, ...]
    missing_answer_terms: tuple[str, ...]
    missing_question_ids: tuple[str, ...]
    unexpected_question_ids: tuple[str, ...]
    malformed_question_ids: tuple[str, ...]
    parse_error: str | None = None


PILOT_CASES = (
    SkillCase(
        "slop-explicit",
        "slop-audit",
        PromptClass.EXPLICIT,
        "Task: run the repository slop audit and report only evidence-backed findings.",
    ),
    SkillCase(
        "slop-implicit",
        "slop-audit",
        PromptClass.IMPLICIT,
        "Task: find redundant or placeholder implementation in this repository.",
    ),
    SkillCase(
        "slop-contextual",
        "slop-audit",
        PromptClass.CONTEXTUAL,
        "Task: review this cleanup after duplicate facades were removed and verify "
        "no stubs remain.",
    ),
    SkillCase(
        "slop-negative",
        "slop-audit",
        PromptClass.NEGATIVE_CONTROL,
        "Task: explain what a Python wheel is without inspecting repository code.",
    ),
    SkillCase(
        "research-explicit",
        "deep-researcher",
        PromptClass.EXPLICIT,
        "Task: use the deep-research workflow to compare two primary-source papers.",
    ),
    SkillCase(
        "research-implicit",
        "deep-researcher",
        PromptClass.IMPLICIT,
        "Task: investigate competing agent-context designs and cite primary sources.",
    ),
    SkillCase(
        "research-contextual",
        "deep-researcher",
        PromptClass.CONTEXTUAL,
        "Task: reconcile conflicting benchmark claims before recommending a runtime change.",
    ),
    SkillCase(
        "research-negative",
        "deep-researcher",
        PromptClass.NEGATIVE_CONTROL,
        "Task: rename a local variable in the provided function.",
    ),
    SkillCase(
        "grill-explicit",
        "grilling",
        PromptClass.EXPLICIT,
        "Task: grill this migration plan for hidden dependencies before implementation.",
    ),
    SkillCase(
        "grill-implicit",
        "grilling",
        PromptClass.IMPLICIT,
        "Task: stress-test this architecture decision and surface unresolved choices.",
    ),
    SkillCase(
        "grill-contextual",
        "grilling",
        PromptClass.CONTEXTUAL,
        "Task: the owner is unsure between two package boundaries; identify the decision frontier.",
    ),
    SkillCase(
        "grill-negative",
        "grilling",
        PromptClass.NEGATIVE_CONTROL,
        "Task: summarize the already-approved release notes without reopening decisions.",
    ),
)


def load_skill_fixtures(
    path: Path,
    cases: Iterable[SkillCase] = PILOT_CASES,
) -> tuple[SkillFixture, ...]:
    """Load the evaluator-owned fixture and bind it to the frozen case order."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != SKILL_FIXTURE_SCHEMA:
        raise ValueError(f"skill fixture schema must be {SKILL_FIXTURE_SCHEMA}")
    raw_rows = payload.get("cases")
    if not isinstance(raw_rows, list):
        raise ValueError("skill fixture cases must be a list")

    rows: dict[str, SkillFixture] = {}
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            raise ValueError(f"skill fixture case {index} must be an object")
        case_id = _required_string(raw, "case_id", case_index=index)
        if case_id in rows:
            raise ValueError(f"duplicate skill fixture case: {case_id}")
        fixture = SkillFixture(
            case_id=case_id,
            context=_required_string(raw, "context", case_index=index),
            required_evidence_ids=_string_tuple(raw, "required_evidence_ids", index),
            required_finding_ids=_string_tuple(raw, "required_finding_ids", index),
            required_answer_terms=_string_tuple(raw, "required_answer_terms", index),
            required_question_ids=_string_tuple(raw, "required_question_ids", index),
            max_questions=_non_negative_int(raw, "max_questions", index),
        )
        if fixture.max_questions < len(fixture.required_question_ids):
            raise ValueError(f"skill fixture case {case_id} max_questions is too small")
        rows[case_id] = fixture

    case_ids = tuple(case.case_id for case in validate_skill_case_matrix(cases))
    if set(rows) != set(case_ids):
        missing = sorted(set(case_ids) - set(rows))
        unexpected = sorted(set(rows) - set(case_ids))
        raise ValueError(
            f"skill fixture case IDs differ from the frozen matrix: "
            f"missing={missing}, unexpected={unexpected}"
        )
    return tuple(rows[case_id] for case_id in case_ids)


def verify_skill_output(text: str, fixture: SkillFixture) -> SkillVerification:
    """Deterministically verify one model response against its native fixture."""
    try:
        payload = _response_object(text)
        answer = _required_string(payload, "answer")
        evidence_ids = set(_string_tuple(payload, "evidence_ids"))
        finding_ids = set(_string_tuple(payload, "finding_ids"))
        questions = payload.get("questions")
        if not isinstance(questions, list):
            raise ValueError("response questions must be a list")
        question_ids: set[str] = set()
        malformed_questions: list[str] = []
        for index, question in enumerate(questions):
            if not isinstance(question, Mapping):
                raise ValueError(f"response question {index} must be an object")
            question_id = _required_string(question, "id", case_index=index)
            if question_id in question_ids:
                raise ValueError(f"duplicate response question ID: {question_id}")
            question_ids.add(question_id)
            options = question.get("options")
            recommendation = question.get("recommendation")
            if (
                not isinstance(options, list)
                or len(options) < 2
                or any(not isinstance(option, str) or not option.strip() for option in options)
                or not isinstance(recommendation, str)
                or not recommendation.strip()
            ):
                malformed_questions.append(question_id)
        if len(questions) > fixture.max_questions:
            malformed_questions.append("<question-count>")
    except (json.JSONDecodeError, ValueError) as exc:
        return SkillVerification(
            passed=False,
            missing_evidence_ids=fixture.required_evidence_ids,
            unexpected_evidence_ids=(),
            missing_finding_ids=fixture.required_finding_ids,
            unexpected_finding_ids=(),
            missing_answer_terms=fixture.required_answer_terms,
            missing_question_ids=fixture.required_question_ids,
            unexpected_question_ids=(),
            malformed_question_ids=(),
            parse_error=str(exc),
        )

    required_evidence = set(fixture.required_evidence_ids)
    required_findings = set(fixture.required_finding_ids)
    required_questions = set(fixture.required_question_ids)
    answer_lower = answer.lower()
    issues = (
        tuple(sorted(required_evidence - evidence_ids)),
        tuple(sorted(evidence_ids - required_evidence)),
        tuple(sorted(required_findings - finding_ids)),
        tuple(sorted(finding_ids - required_findings)),
        tuple(term for term in fixture.required_answer_terms if term.lower() not in answer_lower),
        tuple(sorted(required_questions - question_ids)),
        tuple(sorted(question_ids - required_questions)),
        tuple(malformed_questions),
    )
    return SkillVerification(
        passed=not any(issues),
        missing_evidence_ids=issues[0],
        unexpected_evidence_ids=issues[1],
        missing_finding_ids=issues[2],
        unexpected_finding_ids=issues[3],
        missing_answer_terms=issues[4],
        missing_question_ids=issues[5],
        unexpected_question_ids=issues[6],
        malformed_question_ids=issues[7],
    )


def build_skill_prompt(case: SkillCase, fixture: SkillFixture) -> str:
    """Render the arm-identical synthetic task without leaking verifier answers."""
    if case.case_id != fixture.case_id:
        raise ValueError("skill case and fixture identities differ")
    return (
        f"Task:\n{case.prompt}\n\n"
        f"Synthetic fixture context:\n{fixture.context}\n\n"
        "Output contract:\n"
        "Return one JSON object with exactly these fields: answer (string), "
        "evidence_ids (string array), finding_ids (string array), and questions "
        "(array of objects with id, at least two non-empty options, and one "
        "non-empty recommendation). Use only identifiers present in the supplied "
        "context. Use empty arrays when no evidence, finding, or question applies."
    )


def _response_object(text: str) -> dict[str, Any]:
    from core.agent.subagent_protocol import _last_balanced_json_object

    candidate = _last_balanced_json_object(text)
    if candidate is None:
        raise ValueError("response does not contain a JSON object")
    payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise ValueError("response JSON must be an object")
    return payload


def _required_string(
    payload: Mapping[str, Any],
    field: str,
    *,
    case_index: int | None = None,
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        prefix = f"skill fixture case {case_index}" if case_index is not None else "response"
        raise ValueError(f"{prefix} {field} must be a non-empty string")
    return value.strip()


def _string_tuple(
    payload: Mapping[str, Any],
    field: str,
    case_index: int | None = None,
) -> tuple[str, ...]:
    value = payload.get(field)
    prefix = f"skill fixture case {case_index}" if case_index is not None else "response"
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError(f"{prefix} {field} must contain unique non-empty strings")
    return tuple(item.strip() for item in value)


def _non_negative_int(payload: Mapping[str, Any], field: str, case_index: int) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"skill fixture case {case_index} {field} must be non-negative")
    return value


def validate_skill_case_matrix(cases: Iterable[SkillCase]) -> tuple[SkillCase, ...]:
    """Require one complete four-class matrix per target skill."""
    rows = tuple(cases)
    if not rows or len({row.case_id for row in rows}) != len(rows):
        raise ValueError("skill cases require unique non-empty case IDs")
    expected = frozenset(PromptClass)
    by_skill: dict[str, set[PromptClass]] = {}
    for row in rows:
        if not row.case_id.strip() or not row.target_skill.strip() or not row.prompt.strip():
            raise ValueError("skill case fields must be non-empty")
        classes = by_skill.setdefault(row.target_skill, set())
        if row.prompt_class in classes:
            raise ValueError(f"duplicate prompt class for skill: {row.target_skill}")
        classes.add(row.prompt_class)
    if any(classes != expected for classes in by_skill.values()):
        raise ValueError("each target skill requires all four prompt classes")
    return rows


def run_skill_suite(
    run_spec_path: Path,
    cases: Iterable[SkillCase],
    base_skills: Iterable[str],
    run_arm: Callable[[SkillArmRequest], SkillArmResult],
) -> tuple[SkillLiftResult, ...]:
    """Run matched arms after validating the existing GEODE run-spec contract."""
    from scripts.eval.contract import validate_run_spec

    rows = validate_skill_case_matrix(cases)
    spec = validate_run_spec(run_spec_path)
    if spec["preregistration"]["live_test_approved"] is not True:
        raise ValueError("skill evaluation requires explicit live-test approval")
    execution = spec["reproduction"]["execution"]
    case_ids = tuple(row.case_id for row in rows)
    if tuple(execution["ordered_workload_ids"]) != case_ids:
        raise ValueError("run spec workload order differs from the skill case matrix")
    if int(execution["max_concurrency"]) != 1:
        raise ValueError("paired skill evaluation requires max_concurrency=1")

    baseline = tuple(base_skills)
    if len(set(baseline)) != len(baseline) or any(not skill.strip() for skill in baseline):
        raise ValueError("base skills must be unique and non-empty")
    targets = {row.target_skill for row in rows}
    if targets.intersection(baseline):
        raise ValueError("target skills must be absent from the without-skill arm")

    run_spec_sha256 = hashlib.sha256(run_spec_path.read_bytes()).hexdigest()
    initial_state_ref = str(spec["reproduction"]["environment"]["initial_state_ref"])
    results: list[SkillLiftResult] = []
    attempt_ids: set[str] = set()
    seeds = tuple(str(seed) for seed in execution["seed_schedule"])
    for repetition, seed in enumerate(seeds, start=1):
        for case_index, case in enumerate(rows):
            arm_order = (
                (SkillArm.WITH_SKILL, SkillArm.WITHOUT_SKILL)
                if (case_index + repetition) % 2
                else (SkillArm.WITHOUT_SKILL, SkillArm.WITH_SKILL)
            )
            pair: dict[SkillArm, SkillArmResult] = {}
            for arm in arm_order:
                available = baseline + ((case.target_skill,) if arm is SkillArm.WITH_SKILL else ())
                request = SkillArmRequest(
                    run_id=str(spec["run_id"]),
                    run_spec_sha256=run_spec_sha256,
                    case=case,
                    arm=arm,
                    available_skills=available,
                    seed=seed,
                    repetition=repetition,
                    initial_state_ref=initial_state_ref,
                )
                result = run_arm(request)
                _validate_arm_result(result, request)
                if result.attempt_id in attempt_ids:
                    raise ValueError("skill arm attempt IDs must be unique")
                attempt_ids.add(result.attempt_id)
                pair[arm] = result
            with_skill = pair[SkillArm.WITH_SKILL]
            without_skill = pair[SkillArm.WITHOUT_SKILL]
            results.append(
                SkillLiftResult(
                    with_skill=with_skill,
                    without_skill=without_skill,
                    verifier_pass_delta=int(with_skill.verifier_passed)
                    - int(without_skill.verifier_passed),
                    activation_delta=int(with_skill.skill_activated)
                    - int(without_skill.skill_activated),
                    irrelevant_action_delta=with_skill.irrelevant_actions
                    - without_skill.irrelevant_actions,
                    token_delta=(with_skill.input_tokens + with_skill.output_tokens)
                    - (without_skill.input_tokens + without_skill.output_tokens),
                    elapsed_seconds_delta=with_skill.elapsed_seconds
                    - without_skill.elapsed_seconds,
                    safety_violation_delta=with_skill.safety_violations
                    - without_skill.safety_violations,
                )
            )
    return tuple(results)


def _validate_arm_result(result: SkillArmResult, request: SkillArmRequest) -> None:
    if not isinstance(result, SkillArmResult) or result.request != request:
        raise ValueError("skill arm result does not match the frozen request")
    if result.observed_initial_state_ref != request.initial_state_ref:
        raise ValueError("skill arm changed the frozen initial state")
    if not result.attempt_id.strip():
        raise ValueError("skill arm result requires an attempt ID")
    numeric = (
        result.irrelevant_actions,
        result.input_tokens,
        result.output_tokens,
        result.elapsed_seconds,
        result.safety_violations,
    )
    if any(not math.isfinite(value) or value < 0 for value in numeric):
        raise ValueError("skill arm metrics must be non-negative")
    for digest in (
        result.native_result_sha256,
        result.verifier_receipt_sha256,
        result.trajectory_sha256,
        result.reward_sha256,
    ):
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("skill arm evidence requires lowercase SHA-256 digests")
