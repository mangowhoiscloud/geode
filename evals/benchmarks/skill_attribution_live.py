"""Live GPT subscription runner for the frozen skill-attribution suite."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess  # nosec B404 -- fixed git and Python child-process invocations only
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.benchmarks.skill_attribution import (
    PILOT_CASES,
    SKILL_FIXTURE_SCHEMA,
    PromptClass,
    SkillArm,
    SkillArmRequest,
    SkillArmResult,
    SkillCase,
    SkillFixture,
    SkillLiftResult,
    build_skill_prompt,
    load_skill_fixtures,
    run_skill_suite,
    skill_response_schema,
    verify_skill_output,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_HARNESS_REVISION = "geode-skill-attribution-live-v2"
VERIFIER_REVISION = "v2"
_GRILL_TOOLS = frozenset({"get_grill", "update_grill", "use_skill"})
_SKILL_ONLY_TOOLS = frozenset({"use_skill"})
SYSTEM_PROMPT = (
    "Agent: GEODE skill-attribution evaluation. "
    "Runtime: frozen synthetic fixture with evaluator-owned scoring. "
    "Mode: use only the supplied fixture context and visible tools; do not inspect "
    "host files, other sessions, or the network. Load an available Skill only when "
    "it materially applies. Finish with the requested JSON object."
)
_EXPECTED_ARTIFACTS = {
    "native_results": "artifacts/native-results.json",
    "measurement_results": None,
    "trajectory": "artifacts/trajectory.json",
    "verifier_receipts": "artifacts/verifier-receipts.json",
    "outcome_receipts": "artifacts/outcome-receipts.json",
    "attempts": "artifacts/attempts.jsonl",
    "analysis": "artifacts/analysis.json",
    "publication_manifest": None,
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        for row in rows:
            handle.write(
                (
                    json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                    + "\n"
                ).encode()
            )
        handle.flush()
        os.fsync(handle.fileno())


def _request_payload(request: SkillArmRequest) -> dict[str, Any]:
    return {
        "run_id": request.run_id,
        "run_spec_sha256": request.run_spec_sha256,
        "case": {
            "case_id": request.case.case_id,
            "target_skill": request.case.target_skill,
            "prompt_class": request.case.prompt_class,
            "prompt": request.case.prompt,
        },
        "arm": request.arm,
        "available_skills": list(request.available_skills),
        "seed": request.seed,
        "repetition": request.repetition,
        "initial_state_ref": request.initial_state_ref,
    }


def _load_request(path: Path) -> SkillArmRequest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {
        "run_id",
        "run_spec_sha256",
        "case",
        "arm",
        "available_skills",
        "seed",
        "repetition",
        "initial_state_ref",
    }:
        raise ValueError("skill arm request has an invalid shape")
    case_raw = raw["case"]
    if not isinstance(case_raw, dict) or set(case_raw) != {
        "case_id",
        "target_skill",
        "prompt_class",
        "prompt",
    }:
        raise ValueError("skill arm request case has an invalid shape")
    available = raw["available_skills"]
    if not isinstance(available, list) or any(not isinstance(item, str) for item in available):
        raise ValueError("skill arm request available_skills must be strings")
    return SkillArmRequest(
        run_id=str(raw["run_id"]),
        run_spec_sha256=str(raw["run_spec_sha256"]),
        case=SkillCase(
            case_id=str(case_raw["case_id"]),
            target_skill=str(case_raw["target_skill"]),
            prompt_class=PromptClass(str(case_raw["prompt_class"])),
            prompt=str(case_raw["prompt"]),
        ),
        arm=SkillArm(str(raw["arm"])),
        available_skills=tuple(available),
        seed=str(raw["seed"]),
        repetition=int(raw["repetition"]),
        initial_state_ref=str(raw["initial_state_ref"]),
    )


def _attempt_id(request: SkillArmRequest) -> str:
    return f"{request.run_id}.{request.case.case_id}.r{request.repetition}.{request.arm.value}"


def _skill_registry(available_skills: Sequence[str]) -> Any:
    from core.skills.skills import SkillLoader, SkillRegistry

    loader = SkillLoader(skills_dir=REPO_ROOT / ".geode" / "skills")
    registry = SkillRegistry()
    for name in available_skills:
        path = REPO_ROOT / ".geode" / "skills" / name / "SKILL.md"
        skill = loader.load_file(path)
        if skill.name != name:
            raise ValueError(f"skill identity differs from directory: {name}")
        registry.register(skill)
    if tuple(registry.list_all()) != tuple(sorted(available_skills)):
        raise ValueError("skill registry differs from the frozen arm")
    return registry


def _allowed_tools(target_skill: str) -> frozenset[str]:
    if target_skill == "grilling":
        return _GRILL_TOOLS
    if target_skill in {"deep-researcher", "slop-audit"}:
        return _SKILL_ONLY_TOOLS
    raise ValueError(f"unsupported skill tool surface: {target_skill}")


def _skill_tool_plan(
    available_skills: Sequence[str], *, target_skill: str
) -> tuple[Any, dict[str, Any], Any, Any]:
    from core.agent.loop._tool_factory import project_bound_tool_plan
    from core.tools.composition import compose_tool_plan
    from core.wiring.runtime import build_middleware_registry, build_policy_sources

    registry = _skill_registry(available_skills)
    allowed_tools = _allowed_tools(target_skill)
    policy_sources = build_policy_sources()
    bound, transient = compose_tool_plan(skill_registry=registry)
    bound = project_bound_tool_plan(
        bound,
        provider="openai",
        source="subscription",
        policy_sources=policy_sources,
        force_include=allowed_tools,
    ).filtered(allowed_tool_names=allowed_tools)
    transient = {name: handler for name, handler in transient.items() if name in allowed_tools}
    visible = frozenset((*bound.tool_names, *transient))
    if visible != allowed_tools:
        raise ValueError(f"skill evaluation tool surface drifted: {sorted(visible)}")
    middleware = build_middleware_registry(policy_sources=policy_sources)
    return bound, transient, registry, (policy_sources, middleware)


def skill_tool_schema_sha256(available_skills: Sequence[str], *, target_skill: str) -> str:
    """Return the model-visible schema digest for a no-model arm preflight."""
    bound, _transient, _registry, _services = _skill_tool_plan(
        available_skills, target_skill=target_skill
    )
    from core.tools.plan import thaw_tool_schema

    schemas = [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": thaw_tool_schema(spec.input_schema),
        }
        for spec in bound.ordered_specs
    ]
    return _canonical_sha256(schemas)


def _build_loop(*, request: SkillArmRequest, spec: Mapping[str, Any], session_id: str) -> Any:
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop, AgenticLoopConfig
    from core.agent.tool_executor import ToolExecutor
    from core.llm.adapters.registry import bootstrap_builtins

    allowed_tools = _allowed_tools(request.case.target_skill)
    bound, transient, registry, services = _skill_tool_plan(
        request.available_skills, target_skill=request.case.target_skill
    )
    policy_sources, middleware = services
    bootstrap_builtins(policy_sources=policy_sources)
    executor = ToolExecutor(
        bound_tool_plan=bound,
        transient_handlers=transient,
        auto_approve=True,
        allowed_tools=allowed_tools,
        middleware_registry=middleware,
    )
    model = spec["reproduction"]["model"]
    execution = spec["reproduction"]["execution"]
    return AgenticLoop(
        ConversationContext(max_turns=40),
        executor,
        config=AgenticLoopConfig(
            source="subscription",
            effort=str(model["reasoning"]),
            max_tokens=8192,
            max_rounds=0,
            time_budget_s=float(execution["timeout_seconds"]),
            allowed_tool_names=set(allowed_tools),
            force_include_allowed_tools=True,
            system_prompt_override=SYSTEM_PROMPT,
            session_id=session_id,
            response_schema=skill_response_schema(request.case),
            disable_settings_drift=True,
        ),
        model=str(model["label"]),
        provider="openai",
        skill_registry=registry,
        quiet=True,
        policy_sources=policy_sources,
    )


def _tool_metrics(
    calls: Sequence[Mapping[str, Any]], request: SkillArmRequest
) -> tuple[bool, int, int]:
    correct = 0
    unexpected = 0
    for call in calls:
        tool = str(call.get("tool") or call.get("name") or "")
        arguments = call.get("input")
        requested_skill = str(arguments.get("name") or "") if isinstance(arguments, Mapping) else ""
        is_correct = (
            request.arm is SkillArm.WITH_SKILL
            and tool == "use_skill"
            and requested_skill == request.case.target_skill
        )
        correct += int(is_correct)
        unexpected += int(tool not in _allowed_tools(request.case.target_skill))
    if request.case.prompt_class is PromptClass.NEGATIVE_CONTROL:
        irrelevant = len(calls)
    else:
        irrelevant = len(calls) - int(correct > 0)
    return correct > 0, max(0, irrelevant), unexpected


def _requires_grill_state(request: SkillArmRequest) -> bool:
    return (
        request.case.target_skill == "grilling"
        and request.case.prompt_class is not PromptClass.NEGATIVE_CONTROL
    )


async def _execute_arm(
    *,
    request: SkillArmRequest,
    fixture: SkillFixture,
    spec: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    from core.agent.loop.models import is_successful_task_termination
    from core.memory.grills import GrillStore
    from core.observability.trajectory import export_trajectory, trajectory_from_sessions

    attempt_id = _attempt_id(request)
    session_id = f"s-skill-{hashlib.sha256(attempt_id.encode()).hexdigest()[:16]}"
    loop = _build_loop(request=request, spec=spec, session_id=session_id)
    timeline = getattr(loop, "_timeline", None)
    if timeline is None:
        raise RuntimeError("skill evaluation requires the canonical session timeline")
    if _requires_grill_state(request):
        GrillStore(timeline.db_path).start(session_id, request.case.prompt)

    started_at = _utc_now()
    started = time.monotonic()
    result = await loop.arun(build_skill_prompt(request.case, fixture))
    elapsed = time.monotonic() - started
    finished_at = _utc_now()
    usage = result.usage.to_dict() if result.usage is not None else {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    calls = [dict(call) for call in result.tool_calls]
    activated, irrelevant, safety_violations = _tool_metrics(calls, request)
    verification = verify_skill_output(result.text or "", request.case, fixture)
    termination = str(result.termination_reason)
    valid = not result.error and is_successful_task_termination(result.termination_reason)
    passed = bool(valid and verification.passed)

    native_path = output_dir / "native-result.json"
    native = {
        "schema_id": "geode.skill-attribution-native-result@1",
        "schema_version": 1,
        "attempt_id": attempt_id,
        "case_id": request.case.case_id,
        "arm": request.arm,
        "session_id": session_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": elapsed,
        "model": dict(spec["reproduction"]["model"]),
        "termination_reason": termination,
        "error": result.error,
        "text": result.text or "",
        "tool_calls": calls,
        "usage": usage,
        "verifier_passed": passed,
        "validity": "valid" if valid else "invalid",
    }
    _write_json(native_path, native)

    verifier_path = output_dir / "verifier-receipt.json"
    verifier = {
        "schema_id": "geode.skill-attribution-verifier@2",
        "schema_version": 2,
        "attempt_id": attempt_id,
        "case_id": request.case.case_id,
        "fixture_schema": SKILL_FIXTURE_SCHEMA,
        "passed": passed,
        "score": float(passed) if valid else None,
        "valid_runtime_result": bool(valid),
        "verification": asdict(verification),
    }
    _write_json(verifier_path, verifier)

    trajectory_path = output_dir / "trajectory.json"
    trajectory = trajectory_from_sessions(
        [session_id],
        trajectory_id=f"trajectory-{attempt_id}",
        source={
            "harness": "skill-attribution",
            "run": request.run_id,
            "session": session_id,
            "parents": [session_id],
        },
        db_path=timeline.db_path,
        outcome={
            "validity": "valid" if valid else "invalid",
            "verifier_passed": passed,
            "termination_reason": termination,
        },
        provenance={
            "adapter": LIVE_HARNESS_REVISION,
            "store": "sessions.db:session_events",
            "run_spec_sha256": request.run_spec_sha256,
        },
        privacy={
            "review_state": "local",
            "content_policy": "digest",
            "native_results_embedded": False,
        },
        artifact_digests=[
            {"path": native_path.name, "sha256": _sha256(native_path)},
            {"path": verifier_path.name, "sha256": _sha256(verifier_path)},
        ],
        content_policy="digest",
        trajectory_class=("benchmark", "dialogue", "tool", "lifecycle"),
    )
    export_trajectory(trajectory_path, trajectory)

    reward_path = output_dir / "reward.json"
    reward = {
        "schema_id": "geode.eval-reward@1",
        "schema_version": 1,
        "reward_id": f"reward.{attempt_id}",
        "rollout_id": attempt_id,
        "example_id": f"skill-attribution.{request.case.case_id}",
        "evaluator": {
            "name": "skill-attribution-native-verifier",
            "revision": VERIFIER_REVISION,
            "authority": "deterministic",
        },
        "measurement_status": "measured" if valid else "missing",
        "value": float(passed) if valid else None,
        "components": {
            "verifier_passed": passed if valid else None,
            "skill_activated": activated,
            "safety_violations": safety_violations,
        },
        "source": {
            "path": verifier_path.name,
            "sha256": _sha256(verifier_path),
            "source_locator": "/score",
        },
        "created_at": finished_at,
    }
    _write_json(reward_path, reward)

    arm_result = {
        "schema_id": "geode.skill-attribution-arm-result@1",
        "schema_version": 1,
        "request_sha256": _canonical_sha256(_request_payload(request)),
        "attempt_id": attempt_id,
        "verifier_passed": passed,
        "skill_activated": activated,
        "irrelevant_actions": irrelevant,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "elapsed_seconds": elapsed,
        "safety_violations": safety_violations,
        "native_result_sha256": _sha256(native_path),
        "verifier_receipt_sha256": _sha256(verifier_path),
        "trajectory_sha256": _sha256(trajectory_path),
        "reward_sha256": _sha256(reward_path),
        "observed_initial_state_ref": request.initial_state_ref,
        "started_at": started_at,
        "finished_at": finished_at,
        "session_id": session_id,
        "termination_reason": termination,
        "validity": "valid" if valid else "invalid",
        "paths": {
            "native_result": native_path.name,
            "verifier_receipt": verifier_path.name,
            "trajectory": trajectory_path.name,
            "reward": reward_path.name,
        },
    }
    _write_json(output_dir / "arm-result.json", arm_result)
    return arm_result


def _arm_result(request: SkillArmRequest, payload: Mapping[str, Any]) -> SkillArmResult:
    if payload.get("request_sha256") != _canonical_sha256(_request_payload(request)):
        raise ValueError("arm result request digest differs from the frozen request")
    return SkillArmResult(
        request=request,
        attempt_id=str(payload["attempt_id"]),
        verifier_passed=bool(payload["verifier_passed"]),
        skill_activated=bool(payload["skill_activated"]),
        irrelevant_actions=int(payload["irrelevant_actions"]),
        input_tokens=int(payload["input_tokens"]),
        output_tokens=int(payload["output_tokens"]),
        elapsed_seconds=float(payload["elapsed_seconds"]),
        safety_violations=int(payload["safety_violations"]),
        native_result_sha256=str(payload["native_result_sha256"]),
        verifier_receipt_sha256=str(payload["verifier_receipt_sha256"]),
        trajectory_sha256=str(payload["trajectory_sha256"]),
        reward_sha256=str(payload["reward_sha256"]),
        observed_initial_state_ref=str(payload["observed_initial_state_ref"]),
    )


def _validate_live_spec(spec: Mapping[str, Any], *, fixture_sha256: str) -> None:
    reproduction = spec["reproduction"]
    model = reproduction["model"]
    execution = reproduction["execution"]
    if reproduction["harness"] != {
        "name": "skill-attribution",
        "source": "mangowhoiscloud/geode",
        "revision": LIVE_HARNESS_REVISION,
    }:
        raise ValueError("live skill run requires the pinned native harness identity")
    if model != {
        "provider": "openai",
        "label": "gpt-5.6-sol",
        "route": "subscription",
        "reasoning": "max",
    }:
        raise ValueError("live skill run requires gpt-5.6-sol subscription at max effort")
    if int(execution["max_concurrency"]) != 1:
        raise ValueError("live skill run must be serial")
    seed_schedule = execution.get("seed_schedule")
    if (
        not isinstance(seed_schedule, list)
        or any(
            not isinstance(label, str) or not label.startswith("unseeded-repetition-")
            for label in seed_schedule
        )
        or len(seed_schedule) != len(set(seed_schedule))
    ):
        raise ValueError(
            "live skill run requires unique explicit unseeded repetition labels; "
            "the subscription route does not claim decoder-seed control"
        )
    if spec["artifacts"] != _EXPECTED_ARTIFACTS:
        raise ValueError("live skill run artifact paths differ from the native bundle")
    expected_state = f"fixture-sha256:{fixture_sha256}"
    if reproduction["environment"]["initial_state_ref"] != expected_state:
        raise ValueError("live skill run initial_state_ref differs from the fixture digest")
    if reproduction["geode"]["dirty"] is not False:
        raise ValueError("live skill run requires a clean GEODE revision")


def _git_output(*args: str) -> str:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git executable is required for live-run revision checks")
    return subprocess.run(  # noqa: S603  # nosec B603 -- internal git argv only
        [git, *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _validate_repository(spec: Mapping[str, Any]) -> None:
    expected = str(spec["reproduction"]["geode"]["revision"])
    if _git_output("rev-parse", "HEAD") != expected:
        raise ValueError("current GEODE revision differs from the frozen run spec")
    if _git_output("status", "--short"):
        raise ValueError("current GEODE worktree is dirty")


def _run_arm_process(
    *,
    request: SkillArmRequest,
    run_spec_path: Path,
    fixture_path: Path,
    run_dir: Path,
    timeout: float,
) -> tuple[SkillArmResult, dict[str, Any]]:
    attempt_id = _attempt_id(request)
    arm_dir = run_dir / "artifacts" / "arms" / attempt_id
    arm_dir.mkdir(parents=True)
    request_path = arm_dir / "request.json"
    _write_json(request_path, _request_payload(request))
    state_root = run_dir / "private" / "state" / attempt_id
    if state_root.exists():
        raise FileExistsError(f"arm state root already exists: {attempt_id}")
    env = dict(os.environ)
    env["GEODE_STATE_ROOT"] = str(state_root)
    completed = subprocess.run(  # noqa: S603  # nosec B603 -- fixed module argv
        [
            sys.executable,
            "-m",
            "evals.benchmarks.skill_attribution_live",
            "_arm",
            "--request",
            str(request_path),
            "--run-spec",
            str(run_spec_path),
            "--fixture",
            str(fixture_path),
            "--output-dir",
            str(arm_dir),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        timeout=timeout + 60,
    )
    (run_dir / "private" / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "private" / "logs" / f"{attempt_id}.stdout.log").write_bytes(completed.stdout)
    (run_dir / "private" / "logs" / f"{attempt_id}.stderr.log").write_bytes(completed.stderr)
    if completed.returncode != 0:
        raise RuntimeError(f"skill arm process failed: {attempt_id}")
    payload = json.loads((arm_dir / "arm-result.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("skill arm result must be an object")
    return _arm_result(request, payload), payload


def _aggregate_trajectory(
    *, run_id: str, records: Sequence[Mapping[str, Any]], artifacts_dir: Path
) -> Path:
    from core.observability.trajectory import build_trajectory, export_trajectory

    events: list[dict[str, Any]] = []
    runtime_refs: list[dict[str, Any]] = []
    evidence_refs: list[dict[str, Any]] = []
    sessions: list[str] = []
    digests: list[dict[str, Any]] = []
    for record in records:
        attempt_id = str(record["attempt_id"])
        trajectory_path = artifacts_dir / "arms" / attempt_id / "trajectory.json"
        trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
        events.extend(trajectory["events"])
        runtime_refs.extend(trajectory["runtime_event_refs"])
        evidence_refs.extend(trajectory["evidence_refs"])
        sessions.append(str(record["session_id"]))
        digests.append(
            {
                "path": trajectory_path.relative_to(artifacts_dir).as_posix(),
                "sha256": _sha256(trajectory_path),
            }
        )
    native_path = artifacts_dir / "native-results.json"
    verifier_path = artifacts_dir / "verifier-receipts.json"
    outcome_path = artifacts_dir / "outcome-receipts.json"
    digests.extend(
        {"path": path.name, "sha256": _sha256(path)}
        for path in (native_path, verifier_path, outcome_path)
    )
    combined = build_trajectory(
        trajectory_id=f"trajectory-{run_id}",
        source={
            "harness": "skill-attribution",
            "run": run_id,
            "session": run_id,
            "parents": sessions,
        },
        events=events,
        outcome={
            "valid_arms": sum(record["validity"] == "valid" for record in records),
            "arm_count": len(records),
        },
        provenance={
            "adapter": LIVE_HARNESS_REVISION,
            "store": "per-arm sessions.db:session_events",
        },
        privacy={
            "review_state": "local",
            "content_policy": "digest",
            "native_results_embedded": False,
        },
        trajectory_class=("benchmark", "dialogue", "tool", "lifecycle"),
        integrity={"scope_complete": True, "replay_complete": False},
        runtime_event_refs=runtime_refs,
        evidence_refs=evidence_refs,
        artifact_digests=digests,
    )
    path = artifacts_dir / "trajectory.json"
    export_trajectory(path, combined)
    return path


def _write_aggregates(
    *,
    run_spec_path: Path,
    spec: Mapping[str, Any],
    fixtures: Sequence[SkillFixture],
    lifts: Sequence[SkillLiftResult],
    records: Sequence[Mapping[str, Any]],
    run_dir: Path,
) -> None:
    artifacts = run_dir / "artifacts"
    numerator = sum(int(lift.verifier_pass_delta) for lift in lifts)
    denominator = len(lifts)
    any_invalid = any(record["validity"] != "valid" for record in records)
    primary = {
        "name": str(spec["study"]["primary_metric"]["name"]),
        "value": "not-measurable" if any_invalid else numerator / denominator,
        "numerator": None if any_invalid else numerator,
        "denominator": None if any_invalid else denominator,
    }
    native = {
        "schema_id": "geode.skill-attribution-native-results@1",
        "schema_version": 1,
        "run_id": spec["run_id"],
        "run_spec_sha256": _sha256(run_spec_path),
        "primary_metric": primary,
        "arms": list(records),
        "pairs": [asdict(lift) for lift in lifts],
    }
    native_path = artifacts / "native-results.json"
    _write_json(native_path, native)

    verifier_path = artifacts / "verifier-receipts.json"
    _write_json(
        verifier_path,
        {
            "schema_id": "geode.skill-attribution-verifier-results@2",
            "schema_version": 2,
            "run_id": spec["run_id"],
            "receipts": [
                {
                    "attempt_id": record["attempt_id"],
                    "passed": record["verifier_passed"],
                    "path": f"arms/{record['attempt_id']}/verifier-receipt.json",
                    "sha256": record["verifier_receipt_sha256"],
                }
                for record in records
            ],
        },
    )
    outcome_path = artifacts / "outcome-receipts.json"
    _write_json(
        outcome_path,
        {
            "schema_id": "geode.skill-attribution-outcome-receipts@1",
            "schema_version": 1,
            "run_id": spec["run_id"],
            "receipts": [
                {
                    "attempt_id": record["attempt_id"],
                    "path": f"arms/{record['attempt_id']}/reward.json",
                    "sha256": record["reward_sha256"],
                }
                for record in records
            ],
        },
    )
    trajectory_path = _aggregate_trajectory(
        run_id=str(spec["run_id"]), records=records, artifacts_dir=artifacts
    )
    common_evidence = [
        {"kind": "native-result", "path": native_path.name, "sha256": _sha256(native_path)},
        {
            "kind": "verifier-receipt",
            "path": verifier_path.name,
            "sha256": _sha256(verifier_path),
        },
        {
            "kind": "trajectory",
            "path": trajectory_path.name,
            "sha256": _sha256(trajectory_path),
        },
        {
            "kind": "outcome-receipt",
            "path": outcome_path.name,
            "sha256": _sha256(outcome_path),
        },
    ]
    attempts: list[dict[str, Any]] = []
    first_in_pair: dict[tuple[str, int], str] = {}
    for sequence, record in enumerate(records):
        pair_key = (str(record["case_id"]), int(record["repetition"]))
        parent: str | None = first_in_pair.setdefault(pair_key, str(record["attempt_id"]))
        if parent == record["attempt_id"]:
            parent = None
        validity = str(record["validity"])
        passed = bool(record["verifier_passed"])
        attempts.append(
            {
                "schema_id": "geode.eval-attempt@1",
                "schema_version": 1,
                "run_id": spec["run_id"],
                "attempt_id": record["attempt_id"],
                "parent_attempt_id": parent,
                "sequence": sequence,
                "timing": {
                    "status": "exact",
                    "started_at": record["started_at"],
                    "finished_at": record["finished_at"],
                    "source_ref": f"native-results.json#/arms/{sequence}",
                },
                "validity": validity,
                "outcome": ("passed" if passed else "failed") if validity == "valid" else "unknown",
                "change": {
                    "surface": "runtime skill availability",
                    "description": (
                        f"target skill {record['target_skill']} is {record['arm']} "
                        "for the matched arm"
                    ),
                },
                "expected_effect": (
                    "The with-skill arm improves native verification without excess "
                    "negative-control activation."
                ),
                "observed_result": (
                    f"verifier_passed={passed}; activated={record['skill_activated']}; "
                    f"irrelevant_actions={record['irrelevant_actions']}"
                ),
                "failure_class": None if validity == "valid" else "runtime-invalid",
                "error_ref": None,
                "evidence_refs": common_evidence,
                "selected_for_analysis": True,
            }
        )
    attempts_path = artifacts / "attempts.jsonl"
    _write_jsonl(attempts_path, attempts)

    metric = {
        "name": primary["name"],
        "value": primary["value"],
        "numerator": primary["numerator"],
        "denominator": primary["denominator"],
        "unit": spec["study"]["primary_metric"]["unit"],
        "source_ref": native_path.name,
        "source_locator": (
            None
            if any_invalid
            else {
                "value": "/primary_metric/value",
                "numerator": "/primary_metric/numerator",
                "denominator": "/primary_metric/denominator",
            }
        ),
    }
    hypothesis_status = (
        "invalidated" if any_invalid else "supported" if numerator > 0 else "not-supported"
    )
    analysis = {
        "schema_id": "geode.eval-analysis@1",
        "schema_version": 1,
        "run_id": spec["run_id"],
        "analyzed_at": _utc_now(),
        "run_spec_sha256": _sha256(run_spec_path),
        "attempts_sha256": _sha256(attempts_path),
        "selected_attempt_ids": [record["attempt_id"] for record in records],
        "answer": (
            "The run is invalid because at least one arm lacked a valid runtime result."
            if any_invalid
            else f"The mean signed native-verifier delta is {numerator}/{denominator}."
        ),
        "metrics": [metric],
        "decision": {
            "outcome": "diagnostic-only",
            "hypothesis_status": hypothesis_status,
            "rationale": (
                "This preregistered diagnostic reports verifier lift without release "
                "or promotion authority."
            ),
        },
        "limitations": [
            "One synthetic 12-case matrix does not establish general task or "
            "repository performance.",
            "Subscription service behavior can vary even when the frozen route and "
            "effort are unchanged.",
            "Values in seed_schedule are explicit unseeded repetition labels, not "
            "decoder RNG controls.",
        ],
        "evidence_refs": common_evidence,
    }
    _write_json(artifacts / "analysis.json", analysis)
    _write_learning_view(
        spec=spec,
        fixtures=fixtures,
        records=records,
        artifacts_dir=artifacts,
    )


def _write_learning_view(
    *,
    spec: Mapping[str, Any],
    fixtures: Sequence[SkillFixture],
    records: Sequence[Mapping[str, Any]],
    artifacts_dir: Path,
) -> None:
    fixture_by_id = {fixture.case_id: fixture for fixture in fixtures}
    fixture_revision = str(spec["reproduction"]["environment"]["initial_state_ref"])
    examples = [
        {
            "schema_id": "geode.eval-example@1",
            "schema_version": 1,
            "example_id": f"skill-attribution.{case.case_id}",
            "suite": "skill-attribution",
            "dataset": {"name": "skill-attribution-pilot", "revision": fixture_revision},
            "source_task_id": case.case_id,
            "stratum_id": case.prompt_class,
            "input_sha256": _canonical_sha256(
                {"prompt": case.prompt, "context": fixture_by_id[case.case_id].context}
            ),
        }
        for case in PILOT_CASES
    ]
    rollouts: list[dict[str, Any]] = []
    rewards: list[dict[str, Any]] = []
    model = spec["reproduction"]["model"]
    revision = spec["reproduction"]["geode"]["revision"]
    for index, record in enumerate(records):
        attempt_id = str(record["attempt_id"])
        relative_root = f"arms/{attempt_id}"
        valid = record["validity"] == "valid"
        rollouts.append(
            {
                "schema_id": "geode.eval-rollout@1",
                "schema_version": 1,
                "run_id": spec["run_id"],
                "rollout_id": attempt_id,
                "example_id": f"skill-attribution.{record['case_id']}",
                "rollout_index": index,
                "seed": record["seed"],
                "policy": {
                    "model": model["label"],
                    "provider": model["provider"],
                    "source": model["route"],
                    "effort": model["reasoning"],
                    "geode_revision": revision,
                },
                "rollout_attempt_ids": [attempt_id],
                "selected_attempt_id": attempt_id if valid else None,
                "trajectory": {
                    "path": f"{relative_root}/trajectory.json",
                    "sha256": record["trajectory_sha256"],
                    "trajectory_id": f"trajectory-{attempt_id}",
                    "session_ids": [record["session_id"]],
                },
                "native_result": {
                    "path": f"{relative_root}/native-result.json",
                    "sha256": record["native_result_sha256"],
                    "source_locator": "/text",
                },
                "timing": {
                    "started_at": record["started_at"],
                    "finished_at": record["finished_at"],
                    "wall_seconds": record["elapsed_seconds"],
                },
                "validity": record["validity"],
                "termination_reason": record["termination_reason"],
                "selected_for_reward": valid,
            }
        )
        if valid:
            reward_path = artifacts_dir / relative_root / "reward.json"
            reward = json.loads(reward_path.read_text(encoding="utf-8"))
            reward["source"]["path"] = f"{relative_root}/verifier-receipt.json"
            rewards.append(reward)
    files = {
        "examples": artifacts_dir / "examples.jsonl",
        "rollouts": artifacts_dir / "rollouts.jsonl",
        "rewards": artifacts_dir / "rewards.jsonl",
    }
    _write_jsonl(files["examples"], examples)
    _write_jsonl(files["rollouts"], rollouts)
    _write_jsonl(files["rewards"], rewards)
    row_counts = {
        "examples": len(examples),
        "rollouts": len(rollouts),
        "rewards": len(rewards),
    }
    _write_json(
        artifacts_dir / "learning-view.json",
        {
            "schema_id": "geode.eval-learning-view@2",
            "schema_version": 2,
            "run_id": spec["run_id"],
            "created_at": _utc_now(),
            "record_order": ["example", "rollout", "trajectory", "reward"],
            "files": {
                name: {
                    "path": path.name,
                    "sha256": _sha256(path),
                    "rows": row_counts[name],
                    "record_schema": f"geode.eval-{name.removesuffix('s')}@1",
                }
                for name, path in files.items()
            },
        },
    )


def run_live_skill_suite(
    *, run_spec_path: Path, fixture_path: Path, output_dir: Path
) -> dict[str, Any]:
    from scripts.eval.contract import validate_run_bundle, validate_run_spec
    from scripts.eval.learning_view import validate_learning_view

    run_spec_path = run_spec_path.resolve()
    fixture_path = fixture_path.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError("output directory must not exist; retries use a fresh root")
    spec = validate_run_spec(run_spec_path)
    fixtures = load_skill_fixtures(fixture_path)
    fixture_sha256 = _sha256(fixture_path)
    _validate_live_spec(spec, fixture_sha256=fixture_sha256)
    _validate_repository(spec)
    tool_digests: dict[str, str] = {}
    for skill in sorted({case.target_skill for case in PILOT_CASES}):
        with_digest = skill_tool_schema_sha256((skill,), target_skill=skill)
        without_digest = skill_tool_schema_sha256((), target_skill=skill)
        if with_digest != without_digest:
            raise ValueError(f"model-visible tool schemas differ between {skill} arms")
        tool_digests[skill] = without_digest
    output_dir.mkdir(parents=True)
    frozen_spec = output_dir / "run-spec.json"
    with frozen_spec.open("xb") as handle:
        handle.write(run_spec_path.read_bytes())
        handle.flush()
        os.fsync(handle.fileno())
    frozen_fixture = output_dir / "fixture.json"
    with frozen_fixture.open("xb") as handle:
        handle.write(fixture_path.read_bytes())
        handle.flush()
        os.fsync(handle.fileno())
    records: list[dict[str, Any]] = []
    timeout = float(spec["reproduction"]["execution"]["timeout_seconds"])

    def run_arm(request: SkillArmRequest) -> SkillArmResult:
        result, payload = _run_arm_process(
            request=request,
            run_spec_path=frozen_spec,
            fixture_path=frozen_fixture,
            run_dir=output_dir,
            timeout=timeout,
        )
        records.append(
            {
                **payload,
                "case_id": request.case.case_id,
                "target_skill": request.case.target_skill,
                "prompt_class": request.case.prompt_class,
                "arm": request.arm,
                "seed": request.seed,
                "repetition": request.repetition,
                "available_skills": list(request.available_skills),
            }
        )
        return result

    lifts = run_skill_suite(frozen_spec, PILOT_CASES, (), run_arm)
    _write_aggregates(
        run_spec_path=frozen_spec,
        spec=spec,
        fixtures=fixtures,
        lifts=lifts,
        records=records,
        run_dir=output_dir,
    )
    run_bundle = validate_run_bundle(frozen_spec)
    learning_view = validate_learning_view(output_dir / "artifacts" / "learning-view.json")
    result = {
        "schema_id": "geode.skill-attribution-runner-result@2",
        "schema_version": 2,
        "run_id": spec["run_id"],
        "run_spec_sha256": _sha256(frozen_spec),
        "fixture_sha256": fixture_sha256,
        "tool_schema_sha256_by_target": tool_digests,
        "arms": len(records),
        "pairs": len(lifts),
        "run_bundle": run_bundle,
        "learning_view": learning_view,
    }
    _write_json(output_dir / "runner-result.json", result)
    return result


def _run_child(args: argparse.Namespace) -> None:
    from scripts.eval.contract import validate_run_spec

    state_root = os.environ.get("GEODE_STATE_ROOT", "")
    if not state_root or Path(state_root).exists():
        raise ValueError("arm process requires a fresh explicit GEODE_STATE_ROOT")
    request = _load_request(args.request.resolve())
    spec_path = args.run_spec.resolve()
    if _sha256(spec_path) != request.run_spec_sha256:
        raise ValueError("arm request run-spec digest mismatch")
    spec = validate_run_spec(spec_path)
    fixture_by_id = {
        fixture.case_id: fixture for fixture in load_skill_fixtures(args.fixture.resolve())
    }
    expected = next(case for case in PILOT_CASES if case.case_id == request.case.case_id)
    if request.case != expected:
        raise ValueError("arm request case differs from the frozen matrix")
    asyncio.run(
        _execute_arm(
            request=request,
            fixture=fixture_by_id[request.case.case_id],
            spec=spec,
            output_dir=args.output_dir.resolve(),
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--run-spec", type=Path, required=True)
    run.add_argument("--fixture", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    arm = subparsers.add_parser("_arm")
    arm.add_argument("--request", type=Path, required=True)
    arm.add_argument("--run-spec", type=Path, required=True)
    arm.add_argument("--fixture", type=Path, required=True)
    arm.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "_arm":
        _run_child(args)
        return
    result = run_live_skill_suite(
        run_spec_path=args.run_spec,
        fixture_path=args.fixture,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
