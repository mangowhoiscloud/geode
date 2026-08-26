"""Paired causal evaluation of one runtime skill at a time."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


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
