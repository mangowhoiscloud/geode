"""Prospective native-task contract for runtime Skill attribution."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from evals.benchmarks.skill_attribution import PromptClass, SkillArm

NATIVE_SUITE_SCHEMA = "geode.skill-attribution-native-suite@1"
NATIVE_HARNESS_REVISION = "geode-skill-attribution-native-v1"
DESIGN_REPETITIONS = 1
EVALUATION_REPETITIONS = 3
CAUSAL_DESIGN = {
    "estimand": (
        "family-conditioned source-example ITT of target Skill availability on "
        "deterministic verifier pass"
    ),
    "grouping": "example_id; repetitions and both arms stay in one split",
    "uncertainty": "95% deterministic percentile cluster bootstrap over example means",
    "negative_controls": "excluded from primary ITT and reported as false-use rates",
    "null_rule": "report null or adverse estimates without changing tasks or verifiers",
    "promotion_authority": "none",
    "design_repetitions": DESIGN_REPETITIONS,
    "evaluation_repetitions": EVALUATION_REPETITIONS,
}


class NativeTaskFamily(StrEnum):
    WEB = "web"
    REPOSITORY = "repository"
    DELEGATION = "delegation"


class NativeSplit(StrEnum):
    DESIGN = "design"
    EVALUATION = "evaluation"


@dataclass(frozen=True, slots=True)
class _FamilyContract:
    target_skill: str
    allowed_tools: frozenset[str]
    id_field: str
    response_schema: Mapping[str, Any]


def _response_schema(id_field: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "minLength": 1},
            id_field: {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
        "required": ["answer", id_field],
        "additionalProperties": False,
    }


_FAMILY_CONTRACTS = {
    NativeTaskFamily.WEB: _FamilyContract(
        target_skill="deep-researcher",
        allowed_tools=frozenset({"use_skill", "general_web_search", "web_fetch"}),
        id_field="source_ids",
        response_schema=_response_schema("source_ids"),
    ),
    NativeTaskFamily.REPOSITORY: _FamilyContract(
        target_skill="slop-audit",
        allowed_tools=frozenset({"use_skill", "glob_files", "grep_files", "read_document"}),
        id_field="finding_ids",
        response_schema=_response_schema("finding_ids"),
    ),
    NativeTaskFamily.DELEGATION: _FamilyContract(
        target_skill="deep-researcher",
        allowed_tools=frozenset({"use_skill", "delegate_task"}),
        id_field="delegation_ids",
        response_schema=_response_schema("delegation_ids"),
    ),
}


def _canonical_sha256(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(data).hexdigest()


def _string_tuple(value: object, *, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError(f"{label} must contain unique non-empty strings")
    return tuple(item.strip() for item in value)


def _strict_json_object(path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"{path}: non-finite JSON value: {value}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{path}: duplicate JSON key: {key}")
            result[key] = value
        return result

    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: native Skill suite must be an object")
    return payload


@dataclass(frozen=True, slots=True)
class NativeSkillCase:
    case_id: str
    example_id: str
    split: NativeSplit
    family: NativeTaskFamily
    prompt_class: PromptClass
    prompt: str
    negative_control: bool
    model_fixture: Mapping[str, Any]
    required_ids: tuple[str, ...]
    required_answer_terms: tuple[str, ...]
    required_tool_names: tuple[str, ...]
    forbidden_tool_names: tuple[str, ...]

    @property
    def target_skill(self) -> str:
        return _FAMILY_CONTRACTS[self.family].target_skill

    @property
    def allowed_tools(self) -> frozenset[str]:
        return _FAMILY_CONTRACTS[self.family].allowed_tools

    @property
    def response_schema(self) -> Mapping[str, Any]:
        return _FAMILY_CONTRACTS[self.family].response_schema

    @property
    def workspace_sha256(self) -> str:
        return _canonical_sha256(self.model_fixture)

    @property
    def verifier_sha256(self) -> str:
        return _canonical_sha256(
            {
                "required_ids": self.required_ids,
                "required_answer_terms": self.required_answer_terms,
                "required_tool_names": self.required_tool_names,
                "forbidden_tool_names": self.forbidden_tool_names,
            }
        )

    @property
    def response_schema_sha256(self) -> str:
        return _canonical_sha256(self.response_schema)


@dataclass(frozen=True, slots=True)
class NativeSkillSuite:
    path: Path
    sha256: str
    cases: tuple[NativeSkillCase, ...]

    def cases_for(self, split: NativeSplit) -> tuple[NativeSkillCase, ...]:
        return tuple(case for case in self.cases if case.split is split)


def load_native_skill_suite(path: Path) -> NativeSkillSuite:
    """Load the frozen design without exposing verifier fields to model inputs."""
    payload = _strict_json_object(path)
    if payload.get("schema_id") != NATIVE_SUITE_SCHEMA:
        raise ValueError(f"native Skill suite schema must be {NATIVE_SUITE_SCHEMA}")
    if payload.get("schema_version") != 1 or payload.get("causal_design") != CAUSAL_DESIGN:
        raise ValueError("native Skill suite causal design differs from the preregistration")
    rows = payload.get("cases")
    if not isinstance(rows, list):
        raise ValueError("native Skill suite cases must be a list")

    cases: list[NativeSkillCase] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"native Skill case {index} must be an object")
        case_id = str(row.get("case_id") or "").strip()
        example_id = str(row.get("example_id") or "").strip()
        prompt = str(row.get("prompt") or "").strip()
        if not case_id or not example_id or not prompt or case_id in seen:
            raise ValueError(f"native Skill case {index} has invalid identity or prompt")
        seen.add(case_id)
        family = NativeTaskFamily(str(row.get("family")))
        split = NativeSplit(str(row.get("split")))
        prompt_class = PromptClass(str(row.get("prompt_class")))
        negative_control = row.get("negative_control")
        if not isinstance(negative_control, bool):
            raise ValueError(f"native Skill case {case_id} negative_control must be boolean")
        if negative_control != (prompt_class is PromptClass.NEGATIVE_CONTROL):
            raise ValueError(f"native Skill case {case_id} prompt class/control mismatch")
        model_fixture = row.get("model_fixture")
        verifier = row.get("verifier")
        if not isinstance(model_fixture, Mapping) or not isinstance(verifier, Mapping):
            raise ValueError(f"native Skill case {case_id} requires model and verifier fixtures")
        case = NativeSkillCase(
            case_id=case_id,
            example_id=example_id,
            split=split,
            family=family,
            prompt_class=prompt_class,
            prompt=prompt,
            negative_control=negative_control,
            model_fixture=dict(model_fixture),
            required_ids=_string_tuple(
                verifier.get("required_ids"), label=f"{case_id} required_ids"
            ),
            required_answer_terms=_string_tuple(
                verifier.get("required_answer_terms"),
                label=f"{case_id} required_answer_terms",
            ),
            required_tool_names=_string_tuple(
                verifier.get("required_tool_names"),
                label=f"{case_id} required_tool_names",
            ),
            forbidden_tool_names=_string_tuple(
                verifier.get("forbidden_tool_names"),
                label=f"{case_id} forbidden_tool_names",
            ),
        )
        _validate_native_case(case)
        cases.append(case)

    _validate_case_matrix(cases)
    raw = path.read_bytes()
    return NativeSkillSuite(path=path, sha256=hashlib.sha256(raw).hexdigest(), cases=tuple(cases))


def _validate_native_case(case: NativeSkillCase) -> None:
    contract = _FAMILY_CONTRACTS[case.family]
    Draft202012Validator.check_schema(contract.response_schema)
    if not set(case.required_tool_names).issubset(contract.allowed_tools):
        raise ValueError(f"native Skill case {case.case_id} requires unavailable tools")
    if not set(case.forbidden_tool_names).issubset(contract.allowed_tools):
        raise ValueError(f"native Skill case {case.case_id} forbids unavailable tools")
    if set(case.required_tool_names).intersection(case.forbidden_tool_names):
        raise ValueError(f"native Skill case {case.case_id} both requires and forbids a tool")
    if case.negative_control:
        if case.required_ids or case.required_tool_names:
            raise ValueError(f"negative control {case.case_id} cannot require IDs or tools")
        if set(case.forbidden_tool_names) != set(contract.allowed_tools):
            raise ValueError(f"negative control {case.case_id} must forbid the full tool surface")
    else:
        native_tools = contract.allowed_tools - {"use_skill"}
        if not case.required_ids or not set(case.required_tool_names).intersection(native_tools):
            raise ValueError(f"positive case {case.case_id} must verify native tool work")
        visible = (
            case.prompt
            + "\n"
            + json.dumps(_model_fixture_view(case), ensure_ascii=False, sort_keys=True)
        ).casefold()
        leaked = [term for term in case.required_answer_terms if term.casefold() in visible]
        if leaked:
            raise ValueError(f"positive case {case.case_id} leaks verifier terms: {leaked}")
        _validate_fixture_ids(case)


def _validate_fixture_ids(case: NativeSkillCase) -> None:
    if case.family is NativeTaskFamily.WEB:
        sources = case.model_fixture.get("sources")
        if not isinstance(sources, list):
            raise ValueError(f"web case {case.case_id} requires source fixtures")
        fixture_ids: set[str] = set()
        for source in sources:
            if not isinstance(source, Mapping):
                raise ValueError(f"web case {case.case_id} has malformed source fixture")
            source_id = str(source.get("id") or "")
            source_url = str(source.get("url") or "")
            digest = str(source.get("sha256") or "")
            if (
                not source_id
                or not source_url.startswith("https://")
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
            ):
                raise ValueError(f"web case {case.case_id} has invalid source identity")
            fixture_ids.add(source_id)
        if len(fixture_ids) != len(sources):
            raise ValueError(f"web case {case.case_id} has duplicate source identity")
    elif case.family is NativeTaskFamily.REPOSITORY:
        files = case.model_fixture.get("files")
        if (
            not isinstance(files, Mapping)
            or not files
            or any(
                not str(path).strip() or not isinstance(body, str) for path, body in files.items()
            )
        ):
            raise ValueError(f"repository case {case.case_id} requires file fixtures")
        finding_paths = {required.rsplit(":", 1)[0] for required in case.required_ids}
        if not finding_paths.issubset(str(path) for path in files):
            raise ValueError(f"repository case {case.case_id} finding points outside its fixture")
        fixture_ids = set(case.required_ids)
    else:
        subtasks = case.model_fixture.get("subtasks")
        if not isinstance(subtasks, list) or any(
            not isinstance(subtask, Mapping)
            or not str(subtask.get("id") or "").strip()
            or not str(subtask.get("brief") or "").strip()
            for subtask in subtasks
        ):
            raise ValueError(f"delegation case {case.case_id} requires subtask fixtures")
        fixture_ids = {str(subtask.get("id") or "") for subtask in subtasks}
        if len(fixture_ids) != len(subtasks):
            raise ValueError(f"delegation case {case.case_id} has duplicate subtask identity")
    if set(case.required_ids) != fixture_ids:
        raise ValueError(f"native Skill case {case.case_id} verifier IDs differ from its fixture")


def _validate_case_matrix(cases: Sequence[NativeSkillCase]) -> None:
    if len({case.example_id for case in cases}) != len(cases):
        raise ValueError("native Skill source examples must have unique example IDs")
    expected = (
        {(family, NativeSplit.DESIGN, False): 1 for family in NativeTaskFamily}
        | {(family, NativeSplit.DESIGN, True): 1 for family in NativeTaskFamily}
        | {(family, NativeSplit.EVALUATION, False): 3 for family in NativeTaskFamily}
        | {(family, NativeSplit.EVALUATION, True): 1 for family in NativeTaskFamily}
    )
    observed = {
        key: sum(
            case.family is key[0] and case.split is key[1] and case.negative_control is key[2]
            for case in cases
        )
        for key in expected
    }
    if observed != expected:
        raise ValueError(f"native Skill case matrix differs from preregistration: {observed}")
    design_ids = {case.example_id for case in cases if case.split is NativeSplit.DESIGN}
    evaluation_ids = {case.example_id for case in cases if case.split is NativeSplit.EVALUATION}
    if design_ids.intersection(evaluation_ids):
        raise ValueError("design and final-evaluation source lineages overlap")


def _model_fixture_view(case: NativeSkillCase) -> dict[str, Any]:
    if case.family is NativeTaskFamily.REPOSITORY:
        files = case.model_fixture.get("files", {})
        if not isinstance(files, Mapping):
            raise ValueError(f"repository case {case.case_id} has malformed file fixtures")
        return {
            "workspace_sha256": case.workspace_sha256,
            "paths": sorted(str(path) for path in files),
        }
    return dict(case.model_fixture)


def native_model_view(case: NativeSkillCase) -> dict[str, Any]:
    """Return direct model context; repository file bodies stay tool-only."""
    return {
        "case_id": case.case_id,
        "prompt": case.prompt,
        "model_fixture": _model_fixture_view(case),
        "allowed_tools": sorted(case.allowed_tools),
        "response_schema": dict(case.response_schema),
    }


@dataclass(frozen=True, slots=True)
class NativeVerifierReceipt:
    passed: bool
    missing_ids: tuple[str, ...]
    unexpected_ids: tuple[str, ...]
    missing_answer_terms: tuple[str, ...]
    missing_tools: tuple[str, ...]
    forbidden_tools: tuple[str, ...]
    parse_error: str | None = None


def verify_native_skill_output(
    case: NativeSkillCase,
    text: str,
    tool_names: Sequence[str],
) -> NativeVerifierReceipt:
    """Apply the frozen task-family output and native-tool receipt contract."""
    try:
        from core.agent.subagent_protocol import _last_balanced_json_object

        candidate = _last_balanced_json_object(text)
        if candidate is None:
            raise ValueError("response does not contain a JSON object")
        payload = json.loads(candidate)
        errors = sorted(
            Draft202012Validator(case.response_schema).iter_errors(payload),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            raise ValueError(errors[0].message)
        if not isinstance(payload, Mapping):
            raise ValueError("response JSON must be an object")
        contract = _FAMILY_CONTRACTS[case.family]
        observed_ids = set(_string_tuple(payload[contract.id_field], label=contract.id_field))
        answer = str(payload["answer"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return NativeVerifierReceipt(
            passed=False,
            missing_ids=case.required_ids,
            unexpected_ids=(),
            missing_answer_terms=case.required_answer_terms,
            missing_tools=case.required_tool_names,
            forbidden_tools=(),
            parse_error=str(exc),
        )

    required_ids = set(case.required_ids)
    used_tools = set(tool_names)
    missing_ids = tuple(sorted(required_ids - observed_ids))
    unexpected_ids = tuple(sorted(observed_ids - required_ids))
    missing_terms = tuple(
        term for term in case.required_answer_terms if term.casefold() not in answer.casefold()
    )
    missing_tools = tuple(sorted(set(case.required_tool_names) - used_tools))
    forbidden_tools = tuple(sorted(set(case.forbidden_tool_names).intersection(used_tools)))
    issues = (missing_ids, unexpected_ids, missing_terms, missing_tools, forbidden_tools)
    return NativeVerifierReceipt(
        passed=not any(issues),
        missing_ids=missing_ids,
        unexpected_ids=unexpected_ids,
        missing_answer_terms=missing_terms,
        missing_tools=missing_tools,
        forbidden_tools=forbidden_tools,
    )


@dataclass(frozen=True, slots=True)
class NativeArmRecord:
    attempt_id: str
    case_id: str
    repetition: int
    arm: SkillArm
    available_skills: tuple[str, ...]
    tool_schema_sha256: str
    response_schema_sha256: str
    workspace_sha256: str
    reset_state_sha256: str
    verifier_sha256: str
    verifier_passed: bool
    skill_selected: bool
    skill_activated: bool
    irrelevant_actions: int
    input_tokens: int
    output_tokens: int
    elapsed_seconds: float
    safety_violations: int


@dataclass(frozen=True, slots=True)
class NativePairResult:
    case_id: str
    example_id: str
    family: NativeTaskFamily
    negative_control: bool
    repetition: int
    outcome_delta: int
    selection_delta: int
    activation_delta: int
    token_delta: int
    elapsed_seconds_delta: float
    irrelevant_action_delta: int
    safety_violation_delta: int
    with_outcome: bool
    with_selected: bool
    with_activated: bool


def pair_native_skill_arms(
    case: NativeSkillCase,
    with_skill: NativeArmRecord,
    without_skill: NativeArmRecord,
) -> NativePairResult:
    """Reject every treatment drift except target-Skill availability."""
    if with_skill.arm is not SkillArm.WITH_SKILL or without_skill.arm is not SkillArm.WITHOUT_SKILL:
        raise ValueError("native Skill pair arms are reversed")
    if with_skill.case_id != case.case_id or without_skill.case_id != case.case_id:
        raise ValueError("native Skill pair case identity drifted")
    if with_skill.repetition != without_skill.repetition or with_skill.repetition < 1:
        raise ValueError("native Skill pair repetition identity drifted")
    if with_skill.attempt_id == without_skill.attempt_id:
        raise ValueError("native Skill pair attempt IDs must be distinct")
    expected = (
        case.response_schema_sha256,
        case.workspace_sha256,
        case.workspace_sha256,
        case.verifier_sha256,
    )
    controls_with = (
        with_skill.response_schema_sha256,
        with_skill.workspace_sha256,
        with_skill.reset_state_sha256,
        with_skill.verifier_sha256,
    )
    controls_without = (
        without_skill.response_schema_sha256,
        without_skill.workspace_sha256,
        without_skill.reset_state_sha256,
        without_skill.verifier_sha256,
    )
    if controls_with != expected or controls_without != expected:
        raise ValueError("native Skill pair workspace, reset, response, or verifier drifted")
    if with_skill.tool_schema_sha256 != without_skill.tool_schema_sha256:
        raise ValueError("native Skill pair model-visible tool schema drifted")
    if (
        set(with_skill.available_skills)
        != set(without_skill.available_skills) | {case.target_skill}
        or case.target_skill in without_skill.available_skills
    ):
        raise ValueError("native Skill pair changed more than target-Skill availability")
    for record in (with_skill, without_skill):
        if (
            not record.attempt_id.strip()
            or len(record.available_skills) != len(set(record.available_skills))
            or any(not skill.strip() for skill in record.available_skills)
        ):
            raise ValueError("native Skill arm attempt and availability identity is invalid")
        if record.skill_activated and not record.skill_selected:
            raise ValueError("native Skill activation requires prior selection")
        numeric = (
            record.irrelevant_actions,
            record.input_tokens,
            record.output_tokens,
            record.elapsed_seconds,
            record.safety_violations,
        )
        if any(not math.isfinite(value) or value < 0 for value in numeric):
            raise ValueError("native Skill arm metrics must be finite and non-negative")
        for digest in (
            record.tool_schema_sha256,
            record.response_schema_sha256,
            record.workspace_sha256,
            record.reset_state_sha256,
            record.verifier_sha256,
        ):
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("native Skill arm identity requires lowercase SHA-256 digests")
    return NativePairResult(
        case_id=case.case_id,
        example_id=case.example_id,
        family=case.family,
        negative_control=case.negative_control,
        repetition=with_skill.repetition,
        outcome_delta=int(with_skill.verifier_passed) - int(without_skill.verifier_passed),
        selection_delta=int(with_skill.skill_selected) - int(without_skill.skill_selected),
        activation_delta=int(with_skill.skill_activated) - int(without_skill.skill_activated),
        token_delta=(with_skill.input_tokens + with_skill.output_tokens)
        - (without_skill.input_tokens + without_skill.output_tokens),
        elapsed_seconds_delta=with_skill.elapsed_seconds - without_skill.elapsed_seconds,
        irrelevant_action_delta=with_skill.irrelevant_actions - without_skill.irrelevant_actions,
        safety_violation_delta=with_skill.safety_violations - without_skill.safety_violations,
        with_outcome=with_skill.verifier_passed,
        with_selected=with_skill.skill_selected,
        with_activated=with_skill.skill_activated,
    )


@dataclass(frozen=True, slots=True)
class NativeFamilyAnalysis:
    family: NativeTaskFamily
    source_examples: int
    pairs: int
    outcome_itt: float
    outcome_ci95: tuple[float, float]
    selection_delta: float
    activation_delta: float
    token_delta: float
    elapsed_seconds_delta: float
    irrelevant_action_delta: float
    safety_violation_delta: float
    negative_control_pairs: int
    negative_control_pass_rate: float
    negative_control_selection_rate: float
    negative_control_activation_rate: float
    decision: str = "diagnostic-only"


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("cannot average an empty metric")
    return sum(values) / len(values)


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _cluster_interval(values: Sequence[float], *, family: NativeTaskFamily) -> tuple[float, float]:
    rng = random.Random(f"geode-r11.2:{family.value}")
    draws = [_mean([values[rng.randrange(len(values))] for _ in values]) for _ in range(10_000)]
    return (_percentile(draws, 0.025), _percentile(draws, 0.975))


def analyze_native_skill_pairs(
    suite: NativeSkillSuite,
    pairs: Sequence[NativePairResult],
) -> tuple[NativeFamilyAnalysis, ...]:
    """Report the preregistered family-conditioned ITT without a composite."""
    cases = {case.case_id: case for case in suite.cases_for(NativeSplit.EVALUATION)}
    expected_repetitions = EVALUATION_REPETITIONS
    expected = {
        (case.case_id, repetition)
        for case in cases.values()
        for repetition in range(1, expected_repetitions + 1)
    }
    observed = {(pair.case_id, pair.repetition) for pair in pairs}
    if len(observed) != len(pairs) or observed != expected:
        raise ValueError(
            "native Skill analysis pair lineage differs from the frozen evaluation split"
        )
    for pair in pairs:
        case = cases.get(pair.case_id)
        if (
            case is None
            or pair.example_id != case.example_id
            or pair.family is not case.family
            or pair.negative_control is not case.negative_control
        ):
            raise ValueError("native Skill analysis pair metadata drifted")

    analyses: list[NativeFamilyAnalysis] = []
    for family in NativeTaskFamily:
        family_pairs = [pair for pair in pairs if pair.family is family]
        positive = [pair for pair in family_pairs if not pair.negative_control]
        controls = [pair for pair in family_pairs if pair.negative_control]
        by_example: dict[str, list[float]] = {}
        for pair in positive:
            by_example.setdefault(pair.example_id, []).append(float(pair.outcome_delta))
        example_means = [_mean(values) for values in by_example.values()]
        analyses.append(
            NativeFamilyAnalysis(
                family=family,
                source_examples=len(example_means),
                pairs=len(positive),
                outcome_itt=_mean(example_means),
                outcome_ci95=_cluster_interval(example_means, family=family),
                selection_delta=_mean([float(pair.selection_delta) for pair in positive]),
                activation_delta=_mean([float(pair.activation_delta) for pair in positive]),
                token_delta=_mean([float(pair.token_delta) for pair in positive]),
                elapsed_seconds_delta=_mean([pair.elapsed_seconds_delta for pair in positive]),
                irrelevant_action_delta=_mean(
                    [float(pair.irrelevant_action_delta) for pair in positive]
                ),
                safety_violation_delta=_mean(
                    [float(pair.safety_violation_delta) for pair in positive]
                ),
                negative_control_pairs=len(controls),
                negative_control_pass_rate=_mean([float(pair.with_outcome) for pair in controls]),
                negative_control_selection_rate=_mean(
                    [float(pair.with_selected) for pair in controls]
                ),
                negative_control_activation_rate=_mean(
                    [float(pair.with_activated) for pair in controls]
                ),
            )
        )
    return tuple(analyses)


def preflight_native_tool_surfaces(suite: NativeSkillSuite) -> dict[str, str]:
    """Bind each family to the production tool plan without making a model call."""
    from evals.benchmarks.skill_attribution_live import skill_tool_schema_sha256

    digests: dict[str, str] = {}
    for family in NativeTaskFamily:
        case = next(case for case in suite.cases if case.family is family)
        without = skill_tool_schema_sha256(
            (), target_skill=case.target_skill, allowed_tools=case.allowed_tools
        )
        with_skill = skill_tool_schema_sha256(
            (case.target_skill,),
            target_skill=case.target_skill,
            allowed_tools=case.allowed_tools,
        )
        if with_skill != without:
            raise ValueError(f"native Skill tool surface differs between {family} arms")
        digests[family.value] = without
    return digests


def validate_native_run_spec(
    run_spec_path: Path,
    suite: NativeSkillSuite,
    *,
    split: NativeSplit,
    execute: bool = False,
) -> Mapping[str, Any]:
    """Bind one design or final-evaluation run to the existing run-spec authority."""
    from scripts.eval.contract import validate_run_spec

    spec = validate_run_spec(run_spec_path)
    expected_cases = suite.cases_for(split)
    execution = spec["reproduction"]["execution"]
    repetitions = DESIGN_REPETITIONS if split is NativeSplit.DESIGN else EVALUATION_REPETITIONS
    if tuple(execution["ordered_workload_ids"]) != tuple(case.case_id for case in expected_cases):
        raise ValueError("native Skill run workload differs from the frozen split")
    if int(execution["repetitions"]) != repetitions or int(execution["max_concurrency"]) != 1:
        raise ValueError("native Skill run repetition or serial-execution contract drifted")
    seed_schedule = execution["seed_schedule"]
    if (
        not isinstance(seed_schedule, list)
        or len(seed_schedule) != repetitions
        or len(seed_schedule) != len(set(seed_schedule))
        or any(
            not isinstance(label, str) or not label.startswith("unseeded-repetition-")
            for label in seed_schedule
        )
    ):
        raise ValueError("native Skill run requires unique explicit unseeded repetition labels")
    expected_state = f"suite-sha256:{suite.sha256}:split:{split.value}"
    reproduction = spec["reproduction"]
    if reproduction["environment"]["initial_state_ref"] != expected_state:
        raise ValueError("native Skill run initial-state identity drifted")
    if reproduction["harness"] != {
        "name": "skill-attribution-native",
        "source": "mangowhoiscloud/geode",
        "revision": NATIVE_HARNESS_REVISION,
    }:
        raise ValueError("native Skill run harness identity drifted")
    comparison = reproduction["comparison"]
    if comparison["promotion_authority"] != "none" or comparison["comparator"] != (
        "same runtime without target skill"
    ):
        raise ValueError("native Skill run comparator or promotion authority drifted")
    if spec["study"]["primary_metric"]["name"] != "family-conditioned source-example ITT":
        raise ValueError("native Skill run primary estimand drifted")
    if reproduction["geode"]["dirty"] is not False:
        raise ValueError("native Skill run requires a clean GEODE revision")
    if execute and spec["preregistration"]["live_test_approved"] is not True:
        raise ValueError("native Skill live execution requires explicit approval")
    return spec
