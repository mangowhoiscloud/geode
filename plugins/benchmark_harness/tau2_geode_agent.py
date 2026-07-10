#!/usr/bin/env python3
"""Run tau2 with GEODE as the agent under test.

This script intentionally does not patch the upstream tau2 checkout. It imports
the harness from ``--harness-dir``, registers ``geode_agent`` and
``geode_user`` implementations in tau2's in-process registry, and then calls
``tau2.run.run_domain``.

The resulting run still uses tau2's domain tools, world-state diff evaluator,
and output layout. Diagnostic runs may route the user through GEODE, but a
contract-backed comparison requires tau2's native user implementation so a
candidate core mutation cannot change both the agent and its assay.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import site
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from plugins.crucible.contract import (
    ContractError,
    ExperimentContract,
    load_contract,
    validate_candidate_diff,
    validate_checkout,
    validate_measurement_files,
    validate_test_parent,
)
from plugins.crucible.verifiers.tau2 import TAU2_ADAPTER

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HARNESS_DIR = REPO_ROOT / "artifacts" / "eval" / "harnesses" / "tau2-bench"
DEFAULT_TRAJECTORY_SNAPSHOT_DIR = (
    REPO_ROOT / "artifacts" / "eval" / "runs" / "crucible" / "trajectory-snapshots"
)


def _tau2_data_root(harness_dir: Path) -> Path:
    """Return the only task/output root allowed for this harness checkout."""
    harness_root = harness_dir.resolve()
    data_root = (harness_root / "data").resolve()
    try:
        data_root.relative_to(harness_root)
    except ValueError as exc:
        raise ContractError("tau2 data root must stay inside the harness checkout") from exc
    return data_root


def _pin_tau2_data_root(harness_dir: Path) -> tuple[Path, str | None]:
    """Override ambient dotenv/env routing before tau2 imports DATA_DIR."""
    expected = _tau2_data_root(harness_dir)
    previous = os.environ.get("TAU2_DATA_DIR")
    os.environ["TAU2_DATA_DIR"] = str(expected)
    return expected, previous


def _restore_tau2_data_root(previous: str | None) -> None:
    if previous is None:
        os.environ.pop("TAU2_DATA_DIR", None)
    else:
        os.environ["TAU2_DATA_DIR"] = previous


def _assert_tau2_data_root(expected: Path) -> None:
    from tau2.utils.utils import DATA_DIR

    if Path(DATA_DIR).resolve() != expected:
        raise ContractError(
            f"tau2 imported DATA_DIR {Path(DATA_DIR).resolve()} instead of {expected}"
        )


def _prepend_tau2_src(harness_dir: Path) -> None:
    src_dir = harness_dir / "src"
    if not src_dir.exists():
        raise SystemExit(f"tau2 source directory not found: {src_dir}")
    venv_dir = harness_dir / ".venv"
    if venv_dir.exists():
        for site_packages in site.getsitepackages([str(venv_dir)]):
            site_path = Path(site_packages)
            if site_path.exists():
                sys.path.insert(0, str(site_path))
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(src_dir))


def _result_text(result: Any) -> str:
    text = str(getattr(result, "text", "") or "").strip()
    if text:
        return text
    reason = str(getattr(result, "termination_reason", "") or "unknown")
    return f"GEODE ended without user-visible text. termination_reason={reason}"


def _assert_tau2_route_ready(
    result: Any,
    *,
    projected_tool_calls: list[Any],
    role: str,
) -> None:
    """Fail fast when the model route returns no benchmark-usable action."""

    text = str(getattr(result, "text", "") or "").strip()
    if text or projected_tool_calls:
        return
    raw_tool_calls = getattr(result, "tool_calls", []) or []
    termination_reason = str(getattr(result, "termination_reason", "") or "unknown")
    rounds = getattr(result, "rounds", 0)
    raise RuntimeError(
        "GEODE tau2 route readiness failed for "
        f"{role}: empty visible output and no projected tau2 tool calls "
        f"(termination_reason={termination_reason}, rounds={rounds}, "
        f"raw_tool_calls={len(raw_tool_calls)}). This is infrastructure evidence, "
        "not tau2 performance evidence. Fix the model route before a measured run, "
        "or pass --allow-empty-geode-turn only for debugging."
    )


def _tool_description(tool: Any) -> str:
    schema = getattr(tool, "openai_schema", None)
    if isinstance(schema, dict):
        fn = schema.get("function")
        if isinstance(fn, dict):
            desc = fn.get("description")
            if isinstance(desc, str) and desc.strip():
                return desc.strip()
    short = str(getattr(tool, "short_desc", "") or "").strip()
    long = str(getattr(tool, "long_desc", "") or "").strip()
    return "\n\n".join(part for part in (short, long) if part) or str(tool.name)


def _tool_parameters(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "openai_schema", None)
    if isinstance(schema, dict):
        fn = schema.get("function")
        if isinstance(fn, dict):
            params = fn.get("parameters")
            if isinstance(params, dict):
                return params
    params_model = getattr(tool, "params", None)
    model_json_schema = getattr(params_model, "model_json_schema", None)
    if callable(model_json_schema):
        maybe_schema = model_json_schema()
        if isinstance(maybe_schema, dict):
            return maybe_schema
    return {"type": "object", "properties": {}, "additionalProperties": False}


def _jsonish(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


@dataclass
class Tau2GeodeTool:
    """GEODE tool wrapper around a tau2 environment tool."""

    tau2_tool: Any
    mutates_state: bool = True

    @property
    def name(self) -> str:
        return str(self.tau2_tool.name)

    @property
    def description(self) -> str:
        return _tool_description(self.tau2_tool)

    @property
    def parameters(self) -> dict[str, Any]:
        return _tool_parameters(self.tau2_tool)

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("_tool_context", None)
        if self.mutates_state:
            return {
                "result": (
                    f"Recorded {self.name} for tau2 orchestrator execution. "
                    "The official tau2 environment will apply this tool call."
                ),
                "projected_to_tau2": True,
            }
        raw = await asyncio.to_thread(self.tau2_tool, **kwargs)
        return {"result": _jsonish(raw)}


@dataclass
class GeodeTau2State:
    loop: Any
    messages_seen: int = 0


def _message_to_prompt(message: Any, *, recipient: str) -> str:
    raw_role = getattr(message, "role", "user") or "user"
    role = str(getattr(raw_role, "value", raw_role) or "user").lower()
    if "." in role:
        role = role.rsplit(".", 1)[-1]
    tool_messages = getattr(message, "tool_messages", None)
    if tool_messages:
        payload = [
            {
                "id": getattr(tool_message, "id", ""),
                "requestor": getattr(tool_message, "requestor", ""),
                "content": getattr(tool_message, "content", ""),
                "error": getattr(tool_message, "error", False),
            }
            for tool_message in tool_messages
        ]
        return f"Tool results to {recipient} from tau2 orchestrator:\n{_jsonish(payload)}"
    content = str(getattr(message, "content", "") or "").strip()
    if content:
        if role == "tool":
            return f"Tool result to {recipient} from tau2 orchestrator:\n{content}"
        return f"Message to {recipient} from {role}:\n{content}"
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        return (
            f"Message to {recipient} from {role} containing tool calls:\n"
            f"{_jsonish([tc.model_dump() for tc in tool_calls])}"
        )
    return f"Message to {recipient} from {role}: [empty]"


def _tool_mutates_state(tool: Any) -> bool:
    """Read tau2's decorated mutability marker; unknown tools fail safe."""

    marker = getattr(getattr(tool, "_func", None), "__mutates_state__", None)
    return marker if isinstance(marker, bool) else True


def _agent_system_prompt(
    domain_policy: str,
) -> str:
    return (
        "Agent: GEODE running inside tau2-bench.\n"
        "Follow the domain policy exactly. Use the provided tools to change the "
        "environment state when the user asks for an operation. Do not invent "
        "tool results or missing user facts. When calling a tool, provide every "
        "required argument, but leave optional arguments unset unless the user, "
        "the policy, or a prior tool result explicitly supplied that value. Do "
        "not add inferred descriptions, notes, dates, preferences, quantities, "
        "or metadata. When the requested state change is complete, answer the "
        "user concisely and do not ask for unrelated follow-up details.\n\n"
        "<policy>\n"
        f"{domain_policy}\n"
        "</policy>"
    )


def _user_system_prompt(
    instructions: str | None,
    *,
    use_tools: bool,
) -> str:
    from tau2.user.user_simulator import get_global_user_sim_guidelines

    guidelines = get_global_user_sim_guidelines(use_tools=use_tools)
    return (
        "Role: simulated tau2 benchmark user running through GEODE.\n"
        "Boundary: not the assistant; customer/user in the scenario.\n"
        "Follow the scenario and simulator guidelines exactly. If the task is "
        "complete or the conversation should end, use tau2's required stop token "
        "when the guidelines call for it.\n\n"
        f"{guidelines}\n\n"
        "<scenario>\n"
        f"{instructions or ''}\n"
        "</scenario>"
    )


def _build_loop(
    *,
    tools: list[Any] | None,
    system_prompt: str,
    model: str,
    provider: str,
    source: str,
    effort: str,
    time_budget_s: float,
    max_tokens: int,
    max_rounds: int,
) -> Any:
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop
    from core.agent.tool_executor import ToolExecutor
    from core.tools.registry import ToolRegistry

    tool_registry = ToolRegistry()
    handlers: dict[str, Any] = {}
    for tau2_tool in tools or []:
        wrapped = Tau2GeodeTool(tau2_tool, mutates_state=_tool_mutates_state(tau2_tool))
        tool_registry.register(wrapped)
        handlers[wrapped.name] = wrapped.aexecute

    executor = ToolExecutor(action_handlers=handlers, auto_approve=True, hitl_level=0)
    allowed_tool_names = set(handlers)
    return AgenticLoop(
        ConversationContext(max_turns=200),
        executor,
        model=model,
        provider=provider,
        source=source,
        effort=effort,
        max_tokens=max_tokens,
        max_rounds=max_rounds,
        time_budget_s=time_budget_s,
        tool_registry=tool_registry,
        allowed_tool_names=allowed_tool_names,
        system_prompt_override=system_prompt,
        quiet=True,
        enable_goal_decomposition=False,
    )


def _usage_dict(result: Any) -> dict[str, Any] | None:
    result_usage = getattr(result, "usage", None)
    if result_usage is None:
        return None
    to_dict = getattr(result_usage, "to_dict", None)
    if callable(to_dict):
        maybe_dict = to_dict()
        if isinstance(maybe_dict, Mapping):
            return {str(key): value for key, value in maybe_dict.items()}
        return None
    raw = getattr(result_usage, "__dict__", None)
    return {str(key): value for key, value in raw.items()} if isinstance(raw, dict) else None


def _tau2_tool_calls(result: Any, *, requestor: str) -> list[Any]:
    from tau2.data_model.message import ToolCall

    calls = []
    for idx, entry in enumerate(getattr(result, "tool_calls", []) or []):
        if not isinstance(entry, dict):
            continue
        result_payload = entry.get("result")
        if isinstance(result_payload, dict) and result_payload.get("error"):
            continue
        tool_name = str(entry.get("tool", "") or "")
        tool_input = entry.get("input")
        if not tool_name or not isinstance(tool_input, dict):
            continue
        projected_args = {key: value for key, value in tool_input.items() if value is not None}
        calls.append(
            ToolCall(
                id=str(entry.get("tool_use_id") or f"geode_{requestor}_{idx}"),
                name=tool_name,
                arguments=projected_args,
                requestor=requestor,
            )
        )
    return calls


def register_geode_tau2_participants(
    *,
    agent_model: str,
    agent_provider: str,
    agent_source: str,
    agent_effort: str,
    agent_time_budget_s: float,
    agent_max_tokens: int,
    agent_max_rounds: int,
    user_model: str,
    user_provider: str,
    user_source: str,
    user_effort: str,
    user_time_budget_s: float,
    user_max_tokens: int,
    user_max_rounds: int,
    fail_on_empty_geode_turn: bool = True,
) -> None:
    from core.llm.adapters.registry import bootstrap_builtins
    from tau2.agent.base_agent import HalfDuplexAgent
    from tau2.data_model.message import AssistantMessage, UserMessage
    from tau2.registry import registry
    from tau2.user.user_simulator_base import HalfDuplexUser

    bootstrap_builtins()

    class GeodeTau2Agent(HalfDuplexAgent[GeodeTau2State]):
        def get_init_state(self, message_history: list[Any] | None = None) -> GeodeTau2State:
            loop = _build_loop(
                tools=self.tools,
                system_prompt=_agent_system_prompt(self.domain_policy),
                model=agent_model,
                provider=agent_provider,
                source=agent_source,
                effort=agent_effort,
                time_budget_s=agent_time_budget_s,
                max_tokens=agent_max_tokens,
                max_rounds=agent_max_rounds,
            )
            state = GeodeTau2State(loop=loop)
            if message_history:
                state.messages_seen = len(message_history)
            return state

        def generate_next_message(
            self, message: Any, state: GeodeTau2State
        ) -> tuple[Any, GeodeTau2State]:
            started = time.monotonic()
            prompt = _message_to_prompt(message, recipient="assistant agent")
            result = asyncio.run(state.loop.arun(prompt))
            state.messages_seen += 1
            tool_calls = _tau2_tool_calls(result, requestor="assistant")
            if fail_on_empty_geode_turn:
                _assert_tau2_route_ready(
                    result,
                    projected_tool_calls=tool_calls,
                    role="assistant agent",
                )
            if tool_calls:
                assistant = AssistantMessage(
                    role="assistant",
                    tool_calls=tool_calls,
                    usage=_usage_dict(result),
                    raw_data={
                        "geode_rounds": getattr(result, "rounds", 0),
                        "geode_termination_reason": getattr(result, "termination_reason", ""),
                        "geode_tool_call_count": len(tool_calls),
                        "geode_tool_projection": "tau2_orchestrator",
                    },
                    generation_time_seconds=time.monotonic() - started,
                )
                return assistant, state
            assistant = AssistantMessage.text(
                _result_text(result),
                usage=_usage_dict(result),
                raw_data={
                    "geode_rounds": getattr(result, "rounds", 0),
                    "geode_termination_reason": getattr(result, "termination_reason", ""),
                    "geode_tool_call_count": len(getattr(result, "tool_calls", []) or []),
                },
                generation_time_seconds=time.monotonic() - started,
            )
            return assistant, state

        def set_seed(self, seed: int) -> None:
            return None

    def create_geode_agent(tools: list[Any], domain_policy: str, **_: Any) -> Any:
        return GeodeTau2Agent(tools=tools, domain_policy=domain_policy)

    class GeodeTau2User(HalfDuplexUser[GeodeTau2State]):
        def __init__(
            self,
            instructions: str | None = None,
            tools: list[Any] | None = None,
            **_: Any,
        ) -> None:
            super().__init__(instructions=instructions, tools=tools)

        def get_init_state(self, message_history: list[Any] | None = None) -> GeodeTau2State:
            loop = _build_loop(
                tools=self.tools,
                system_prompt=_user_system_prompt(
                    self.instructions,
                    use_tools=bool(self.tools),
                ),
                model=user_model,
                provider=user_provider,
                source=user_source,
                effort=user_effort,
                time_budget_s=user_time_budget_s,
                max_tokens=user_max_tokens,
                max_rounds=user_max_rounds,
            )
            state = GeodeTau2State(loop=loop)
            if message_history:
                state.messages_seen = len(message_history)
            return state

        def generate_next_message(
            self, message: Any, state: GeodeTau2State
        ) -> tuple[Any, GeodeTau2State]:
            started = time.monotonic()
            prompt = _message_to_prompt(message, recipient="simulated user")
            result = asyncio.run(state.loop.arun(prompt))
            state.messages_seen += 1
            tool_calls = _tau2_tool_calls(result, requestor="user")
            if fail_on_empty_geode_turn:
                _assert_tau2_route_ready(
                    result,
                    projected_tool_calls=tool_calls,
                    role="simulated user",
                )
            if tool_calls:
                user_message = UserMessage(
                    role="user",
                    tool_calls=tool_calls,
                    usage=_usage_dict(result),
                    raw_data={
                        "geode_role": "user_simulator",
                        "geode_rounds": getattr(result, "rounds", 0),
                        "geode_termination_reason": getattr(result, "termination_reason", ""),
                        "geode_tool_call_count": len(tool_calls),
                        "geode_tool_projection": "tau2_orchestrator",
                    },
                    generation_time_seconds=time.monotonic() - started,
                )
                return user_message, state
            user_message = UserMessage.text(
                _result_text(result),
                usage=_usage_dict(result),
                raw_data={
                    "geode_role": "user_simulator",
                    "geode_rounds": getattr(result, "rounds", 0),
                    "geode_termination_reason": getattr(result, "termination_reason", ""),
                    "geode_tool_call_count": len(getattr(result, "tool_calls", []) or []),
                },
                generation_time_seconds=time.monotonic() - started,
            )
            return user_message, state

        def set_seed(self, seed: int) -> None:
            return None

    registry.register_agent_factory(create_geode_agent, "geode_agent")
    registry.register_user(GeodeTau2User, "geode_user")


def _slug(value: str) -> str:
    value = value.strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-._")
    return value or "unnamed"


def _trajectory_snapshot_paths(snapshot_dir: Path, run_id: str) -> tuple[Path, Path]:
    slug = _slug(run_id)
    return snapshot_dir / f"{slug}.trajectory.json", snapshot_dir / f"{slug}.snapshot.json"


def _write_trajectory_snapshot(
    *,
    harness_dir: Path,
    snapshot_dir: Path,
    run_id: str,
    metadata: dict[str, Any],
) -> tuple[Path, Path] | None:
    results_path = _tau2_data_root(harness_dir) / "simulations" / run_id / "results.json"
    if not results_path.exists():
        print(f"trajectory snapshot skipped: results not found at {results_path}", file=sys.stderr)
        return None
    trajectory_path, snapshot_path = _trajectory_snapshot_paths(snapshot_dir, run_id)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(results_path, trajectory_path)
    raw_artifact_sha256 = hashlib.sha256(trajectory_path.read_bytes()).hexdigest()
    snapshot = {
        "schema": "crucible_tau2_trajectory_snapshot.v3",
        "filename_convention": {
            "run_id": (
                "crucible-tau2-<stage>-<domain>-<arm>-"
                "<agent_route>-<user_route>-n<tasks>k<trials>-<yyyymmdd>-<seq>"
            ),
            "trajectory": "<run-id>.trajectory.json",
            "snapshot": "<run-id>.snapshot.json",
        },
        "run_id": run_id,
        "raw_results": str(results_path),
        "trajectory_snapshot": str(trajectory_path),
        "raw_artifact_sha256": raw_artifact_sha256,
        "snapshot_metadata": str(snapshot_path),
        **metadata,
    }
    snapshot_tmp = snapshot_path.with_name(f".{snapshot_path.name}.tmp-{os.getpid()}")
    snapshot_tmp.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
    os.replace(snapshot_tmp, snapshot_path)
    print(f"trajectory snapshot wrote {trajectory_path}")
    print(f"trajectory metadata wrote {snapshot_path}")
    return trajectory_path, snapshot_path


def _require_contract_snapshot(
    contract: ExperimentContract | None,
    written: tuple[Path, Path] | None,
) -> None:
    """Fail closed when a contract-backed run produced no durable evidence."""
    if contract is not None and written is None:
        raise RuntimeError("contract-backed run did not produce a trajectory snapshot")


def _validate_contract_output_paths(
    *,
    harness_dir: Path,
    snapshot_dir: Path,
    run_id: str,
) -> None:
    """Require a simple, fresh run ID so tau2 cannot resume or overwrite rows."""
    if run_id in {".", ".."} or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id) is None:
        raise ContractError("contract --save-to must be a simple, path-free run ID")
    trajectory_path, snapshot_path = _trajectory_snapshot_paths(snapshot_dir, run_id)
    raw_run_dir = _tau2_data_root(harness_dir) / "simulations" / run_id
    collisions = [path for path in (raw_run_dir, trajectory_path, snapshot_path) if path.exists()]
    if collisions:
        raise ContractError(
            "contract run output must be fresh; refusing existing path(s): "
            + ", ".join(str(path) for path in collisions)
        )


def _reserve_contract_run_id(harness_dir: Path, run_id: str) -> Path:
    """Atomically reserve a raw tau2 output directory across processes."""
    raw_run_dir = _tau2_data_root(harness_dir) / "simulations" / run_id
    try:
        raw_run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ContractError(f"contract run ID is already reserved: {run_id}") from exc
    return raw_run_dir


def _codex_empty_text_dumps() -> set[Path]:
    from core.paths import GLOBAL_DIAGNOSTICS_DIR

    dump_dir = GLOBAL_DIAGNOSTICS_DIR / "codex-oauth-empty-text"
    if not dump_dir.exists():
        return set()
    return {path.resolve() for path in dump_dir.glob("*.json") if path.is_file()}


def _raise_on_new_codex_empty_text_dumps(before: set[Path]) -> None:
    after = _codex_empty_text_dumps()
    new_dumps = sorted(after - before)
    if not new_dumps:
        return
    sample = ", ".join(str(path) for path in new_dumps[:3])
    suffix = "" if len(new_dumps) <= 3 else f", ... (+{len(new_dumps) - 3} more)"
    raise RuntimeError(
        "GEODE tau2 route readiness failed: codex-oauth empty output_text "
        f"occurred during the run ({len(new_dumps)} dump(s): {sample}{suffix}). "
        "This is infrastructure contamination, not tau2 performance evidence. "
        "Fix the subscription route before a measured run, or pass "
        "--allow-empty-geode-turn only for debugging."
    )


def _resolve_num_tasks(task_ids: list[str] | None, num_tasks: int | None) -> int:
    """Make an explicit task pack atomic instead of silently slicing it."""
    if num_tasks is not None and num_tasks <= 0:
        raise ValueError("--num-tasks must be greater than zero")
    if not task_ids:
        return num_tasks if num_tasks is not None else 1
    if num_tasks is None:
        return len(task_ids)
    if num_tasks != len(task_ids):
        raise ValueError(
            "--num-tasks must equal the number of explicit --task-ids "
            f"({num_tasks} != {len(task_ids)})"
        )
    return num_tasks


def _validate_tau2_task_order(config: Any) -> None:
    """Fail when tau2's loader would reorder an explicitly frozen task pack."""
    requested = tuple(config.task_ids or ())
    if not requested:
        return
    from tau2.registry import registry
    from tau2.runner.helpers import get_tasks

    selected = get_tasks(
        task_set_name=config.task_set_name or config.domain,
        task_split_name=config.task_split_name,
        task_ids=list(requested),
        num_tasks=None,
    )
    task_filter = registry.get_agent_task_filter(config.effective_agent)
    if task_filter is not None:
        selected = [task for task in selected if task_filter(task)]
    actual = tuple(str(task.id) for task in selected)
    if actual != requested:
        raise ValueError(
            "tau2 loader order does not match ordered --task-ids "
            f"(requested={requested!r}, selected={actual!r})"
        )


def _validate_contract_run_args(
    contract: ExperimentContract,
    *,
    stage: str,
    agent_route: str,
    user_route: str,
    task_ids: list[str] | None,
    num_tasks: int,
    num_trials: int,
    assay_config: Mapping[str, Any],
) -> None:
    """Keep a contract-backed run inside its frozen identity boundary."""
    declared = tuple(PurePosixPath(path) for path in contract.evaluator_paths)
    missing_evaluator_paths = [
        required
        for required in TAU2_ADAPTER.required_evaluator_paths
        if not any(
            frozen == PurePosixPath(required) or frozen in PurePosixPath(required).parents
            for frozen in declared
        )
    ]
    if missing_evaluator_paths:
        raise ContractError(
            "evaluator_paths do not cover the tau2 measurement bundle: "
            + ", ".join(missing_evaluator_paths)
        )
    if stage != contract.stage:
        raise ContractError(
            f"trajectory stage {stage!r} does not match contract stage {contract.stage!r}"
        )
    if agent_route != contract.agent_route:
        raise ContractError("agent route does not match the frozen contract")
    if user_route != contract.user_route:
        raise ContractError("user route does not match the frozen contract")
    if tuple(task_ids or ()) != contract.task_ids:
        raise ContractError("ordered --task-ids do not match the frozen contract")
    if num_tasks != len(contract.task_ids):
        raise ContractError("--num-tasks does not cover the frozen task pack")
    if num_trials != contract.trials_per_task:
        raise ContractError("--num-trials does not match the frozen task pack")
    if dict(assay_config) != contract.assay_config:
        raise ContractError("resolved tau2 assay config does not match the frozen contract")
    TAU2_ADAPTER.validate_config(assay_config)


def _validate_contract_runtime_policy(args: argparse.Namespace) -> None:
    """Keep contract runs on the code-only mutation path.

    Debug and retry knobs remain available for diagnostics, but they cannot be
    mixed into an identity-preflight run under the same git SHA.
    """
    violations: list[str] = []
    exact_defaults = {"max_retries": 0}
    for field, expected in exact_defaults.items():
        if getattr(args, field) != expected:
            violations.append(f"--{field.replace('_', '-')}={expected}")
    disabled = {
        "allow_empty_geode_turn": "--allow-empty-geode-turn",
        "auto_resume": "--auto-resume",
        "disable_codex_output_replay": "--disable-codex-output-replay",
        "disable_tool_search_defer": "--disable-tool-search-defer",
        "enable_cognitive_reflection": "--enable-cognitive-reflection",
        "no_trajectory_snapshot": "--no-trajectory-snapshot",
    }
    for field, flag in disabled.items():
        if getattr(args, field):
            violations.append(f"omit {flag}")
    if not args.save_to:
        violations.append("set --save-to")
    if violations:
        raise ContractError(
            "contract runs require the code-only runtime policy: " + "; ".join(violations)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness-dir", type=Path, default=DEFAULT_HARNESS_DIR)
    parser.add_argument("--domain", default="mock")
    parser.add_argument("--task-set-name", default=None)
    parser.add_argument("--task-split-name", default="base")
    parser.add_argument("--task-ids", nargs="*", default=None)
    parser.add_argument(
        "--num-tasks",
        type=int,
        default=None,
        help=(
            "Number of tasks to run. Defaults to every explicit --task-ids value, "
            "or 1 when no explicit task pack is supplied."
        ),
    )
    parser.add_argument("--num-trials", type=int, default=1)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--seed", type=int, default=300)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument(
        "--max-errors",
        type=int,
        default=1,
        help="Maximum consecutive tau2 tool errors inside one simulation.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=0,
        help=(
            "Maximum tau2 task retries after a failed simulation. Crucible strict "
            "runs default to 0."
        ),
    )
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--save-to", default=None)
    parser.add_argument("--user", default="geode_user")
    parser.add_argument("--user-llm", default="gpt-5.5")
    parser.add_argument("--user-llm-args", default='{"temperature": 0.0}')
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--source", default="subscription")
    parser.add_argument("--effort", default="xhigh")
    parser.add_argument("--user-provider", default="openai")
    parser.add_argument("--user-source", default="subscription")
    parser.add_argument("--user-effort", default="high")
    parser.add_argument("--user-time-budget-s", type=float, default=120.0)
    parser.add_argument("--user-max-tokens", type=int, default=8192)
    parser.add_argument(
        "--user-max-rounds",
        type=int,
        default=0,
        help="Maximum GEODE AgenticLoop rounds per simulated-user tau2 turn; 0 is unlimited.",
    )
    parser.add_argument("--time-budget-s", type=float, default=180.0)
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument(
        "--agent-max-rounds",
        type=int,
        default=0,
        help="Maximum GEODE AgenticLoop rounds per assistant tau2 turn; 0 is unlimited.",
    )
    parser.add_argument(
        "--trajectory-snapshot-dir",
        type=Path,
        default=DEFAULT_TRAJECTORY_SNAPSHOT_DIR,
        help=(
            "Directory for Crucible trajectory snapshots. Requires --save-to; "
            "writes <run-id>.trajectory.json and <run-id>.snapshot.json."
        ),
    )
    parser.add_argument("--no-trajectory-snapshot", action="store_true")
    parser.add_argument("--trajectory-stage", default="train")
    parser.add_argument("--trajectory-arm", choices=["baseline", "candidate"], default=None)
    parser.add_argument(
        "--experiment-contract",
        type=Path,
        default=None,
        help=(
            "Frozen Crucible experiment JSON. Required with an explicit "
            "--trajectory-arm; runs without a contract are diagnostic-only."
        ),
    )
    parser.add_argument(
        "--parent-experiment-contract",
        type=Path,
        default=None,
        help="Frozen train contract required when --experiment-contract has stage=test.",
    )
    parser.add_argument(
        "--allow-empty-geode-turn",
        action="store_true",
        help=(
            "Debug only: convert an empty GEODE turn into fallback text. By default, "
            "empty visible output with no projected tau2 tool call is an infra "
            "readiness failure and stops the run."
        ),
    )
    parser.add_argument(
        "--enable-cognitive-reflection",
        action="store_true",
        help=(
            "Debug only: leave AgenticLoop cognitive reflection enabled. Measured tau2 "
            "runs disable it so hidden reflection calls cannot spend quota or mask "
            "route-readiness failures."
        ),
    )
    parser.add_argument(
        "--disable-codex-output-replay",
        action="store_true",
        help=(
            "Debug only: do not replay prior Codex response.output items. Measured "
            "tau2 subscription runs keep output replay enabled because OpenAI "
            "Responses docs recommend passing prior output items for manual "
            "multi-turn state."
        ),
    )
    parser.add_argument(
        "--disable-tool-search-defer",
        action="store_true",
        help=(
            "Tau2 probe control: disable hosted tool-search/defer_loading during "
            "this run. Domain-specific tau2 tool sets are small enough that the "
            "extra hosted tool-search calls can cost more than the schema context "
            "they save."
        ),
    )
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--auto-resume", action="store_true")
    parser.add_argument("--verbose-logs", action="store_true")
    parser.add_argument(
        "--retrieval-config",
        default=None,
        help=(
            "tau2 retrieval config name, useful for banking_knowledge. "
            "Example: bm25 avoids the default alltools shell sandbox."
        ),
    )
    parser.add_argument("--retrieval-config-kwargs", default="{}")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        num_tasks = _resolve_num_tasks(args.task_ids, args.num_tasks)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        user_llm_args = TAU2_ADAPTER.parse_json_object(
            args.user_llm_args,
            "--user-llm-args",
        )
        retrieval_config_kwargs = TAU2_ADAPTER.parse_json_object(
            args.retrieval_config_kwargs,
            "--retrieval-config-kwargs",
        )
    except ContractError as exc:
        raise SystemExit(str(exc)) from exc
    agent_route = TAU2_ADAPTER.agent_route_from_args(args)
    user_route = TAU2_ADAPTER.user_route_from_args(args)
    assay_config = TAU2_ADAPTER.resolved_config(
        args,
        user_llm_args=user_llm_args,
        retrieval_config_kwargs=retrieval_config_kwargs,
    )
    if args.trajectory_arm is not None and args.experiment_contract is None:
        raise SystemExit("--trajectory-arm requires --experiment-contract")
    if args.experiment_contract is not None and args.trajectory_arm is None:
        raise SystemExit("--experiment-contract requires an explicit --trajectory-arm")
    experiment_contract: ExperimentContract | None = None
    if args.experiment_contract is not None:
        try:
            experiment_contract = load_contract(args.experiment_contract)
            _validate_contract_runtime_policy(args)
            _validate_contract_run_args(
                experiment_contract,
                stage=args.trajectory_stage,
                agent_route=agent_route,
                user_route=user_route,
                task_ids=args.task_ids,
                num_tasks=num_tasks,
                num_trials=args.num_trials,
                assay_config=assay_config,
            )
            validate_checkout(
                experiment_contract,
                REPO_ROOT,
                arm=args.trajectory_arm,
            )
            validate_candidate_diff(experiment_contract, REPO_ROOT)
            validate_measurement_files(
                experiment_contract,
                repo_root=REPO_ROOT,
                harness_root=args.harness_dir.resolve(),
            )
            if experiment_contract.stage == "test":
                if args.parent_experiment_contract is None:
                    raise ContractError("test contract runs require --parent-experiment-contract")
                validate_test_parent(
                    experiment_contract,
                    load_contract(args.parent_experiment_contract),
                )
            elif args.parent_experiment_contract is not None:
                raise ContractError("--parent-experiment-contract is only valid for test contracts")
            _validate_contract_output_paths(
                harness_dir=args.harness_dir.resolve(),
                snapshot_dir=args.trajectory_snapshot_dir.resolve(),
                run_id=args.save_to,
            )
            _reserve_contract_run_id(args.harness_dir.resolve(), args.save_to)
        except ContractError as exc:
            raise SystemExit(f"invalid Crucible experiment contract: {exc}") from exc
    expected_tau2_data_dir, previous_tau2_data_dir = _pin_tau2_data_root(args.harness_dir)
    _prepend_tau2_src(args.harness_dir.resolve())

    from tau2.data_model.simulation import TextRunConfig
    from tau2.run import run_domain

    try:
        _assert_tau2_data_root(expected_tau2_data_dir)
    except ContractError as exc:
        _restore_tau2_data_root(previous_tau2_data_dir)
        raise SystemExit(f"invalid tau2 data root: {exc}") from exc

    register_geode_tau2_participants(
        agent_model=args.model,
        agent_provider=args.provider,
        agent_source=args.source,
        agent_effort=args.effort,
        agent_time_budget_s=args.time_budget_s,
        agent_max_tokens=args.max_tokens,
        agent_max_rounds=args.agent_max_rounds,
        user_model=args.user_llm,
        user_provider=args.user_provider,
        user_source=args.user_source,
        user_effort=args.user_effort,
        user_time_budget_s=args.user_time_budget_s,
        user_max_tokens=args.user_max_tokens,
        user_max_rounds=args.user_max_rounds,
        fail_on_empty_geode_turn=not args.allow_empty_geode_turn,
    )

    config = TextRunConfig(
        domain=args.domain,
        agent="geode_agent",
        user=args.user,
        llm_agent=args.model,
        llm_args_agent={"reasoning_effort": args.effort},
        llm_user=args.user_llm,
        llm_args_user=user_llm_args,
        task_set_name=args.task_set_name,
        task_split_name=args.task_split_name,
        task_ids=args.task_ids,
        num_tasks=num_tasks,
        num_trials=args.num_trials,
        seed=args.seed,
        max_concurrency=args.max_concurrency,
        max_steps=args.max_steps,
        max_errors=args.max_errors,
        max_retries=args.max_retries,
        timeout=args.timeout,
        save_to=args.save_to,
        log_level=args.log_level,
        auto_resume=args.auto_resume,
        verbose_logs=args.verbose_logs,
        retrieval_config=args.retrieval_config,
        retrieval_config_kwargs=retrieval_config_kwargs,
    )
    try:
        _validate_tau2_task_order(config)
    except ValueError as exc:
        _restore_tau2_data_root(previous_tau2_data_dir)
        raise SystemExit(str(exc)) from exc
    previous_fail_empty_text = os.environ.get("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT")
    previous_fail_adapter_error = os.environ.get("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR")
    previous_disable_output_replay = os.environ.get("GEODE_CODEX_DISABLE_OUTPUT_REPLAY")
    before_empty_text_dumps = set() if args.allow_empty_geode_turn else _codex_empty_text_dumps()
    if not args.allow_empty_geode_turn:
        os.environ["GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT"] = "1"
        os.environ["GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR"] = "1"
    if args.disable_codex_output_replay:
        os.environ["GEODE_CODEX_DISABLE_OUTPUT_REPLAY"] = "1"
    from core.config import settings

    previous_reflection_enabled = getattr(settings, "cognitive_reflection_enabled", None)
    previous_tool_search_defer = getattr(settings, "tool_search_defer", None)
    previous_tool_search_defer_codex = getattr(settings, "tool_search_defer_codex", None)
    if not args.enable_cognitive_reflection:
        object.__setattr__(settings, "cognitive_reflection_enabled", False)
    if args.disable_tool_search_defer:
        object.__setattr__(settings, "tool_search_defer", False)
        object.__setattr__(settings, "tool_search_defer_codex", False)
    run_error: BaseException | None = None
    try:
        run_domain(config)
    except BaseException as exc:
        run_error = exc
    finally:
        if previous_fail_empty_text is None:
            os.environ.pop("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT", None)
        else:
            os.environ["GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT"] = previous_fail_empty_text
        if previous_fail_adapter_error is None:
            os.environ.pop("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", None)
        else:
            os.environ["GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR"] = previous_fail_adapter_error
        if previous_disable_output_replay is None:
            os.environ.pop("GEODE_CODEX_DISABLE_OUTPUT_REPLAY", None)
        else:
            os.environ["GEODE_CODEX_DISABLE_OUTPUT_REPLAY"] = previous_disable_output_replay
        if previous_reflection_enabled is not None:
            object.__setattr__(
                settings,
                "cognitive_reflection_enabled",
                previous_reflection_enabled,
            )
        if previous_tool_search_defer is not None:
            object.__setattr__(settings, "tool_search_defer", previous_tool_search_defer)
        if previous_tool_search_defer_codex is not None:
            object.__setattr__(
                settings,
                "tool_search_defer_codex",
                previous_tool_search_defer_codex,
            )
        _restore_tau2_data_root(previous_tau2_data_dir)
    final_error = run_error
    failure_class: str | None = "run_error" if run_error is not None else None
    if not args.allow_empty_geode_turn:
        try:
            _raise_on_new_codex_empty_text_dumps(before_empty_text_dumps)
        except RuntimeError as exc:
            if final_error is None:
                final_error = exc
                failure_class = "route_contamination"
            else:
                failure_class = "run_error_and_route_contamination"

    if not args.no_trajectory_snapshot and args.save_to:
        if experiment_contract is None:
            arm = "diagnostic"
            candidate_surface = "unfrozen_git"
        else:
            arm = str(args.trajectory_arm)
            candidate_surface = "git_revision"
        contract_metadata = (
            {
                "experiment_contract_id": experiment_contract.contract_id,
                "baseline_sha": experiment_contract.baseline_sha,
                "candidate_sha": experiment_contract.candidate_sha,
                "evaluator_sha256": experiment_contract.evaluator_sha256,
                "harness_sha256": experiment_contract.harness_sha256,
                "task_pack_sha256": experiment_contract.task_pack_sha256,
                "assay_config_sha256": experiment_contract.assay_config_sha256,
                "contract_validation": "identity_preflight",
                "promotion_authority": "none",
            }
            if experiment_contract is not None
            else {"promotion_authority": "none"}
        )
        written = _write_trajectory_snapshot(
            harness_dir=args.harness_dir.resolve(),
            snapshot_dir=args.trajectory_snapshot_dir.resolve(),
            run_id=args.save_to,
            metadata={
                "stage": args.trajectory_stage,
                "domain": args.domain,
                "arm": arm,
                "candidate_surface": candidate_surface,
                "agent_route": agent_route,
                "user_route": user_route,
                "num_tasks": num_tasks,
                "num_trials": args.num_trials,
                "task_ids": args.task_ids or [],
                "max_steps": args.max_steps,
                "agent_max_rounds": args.agent_max_rounds,
                "user_max_rounds": args.user_max_rounds,
                "tool_search_defer": not args.disable_tool_search_defer,
                "tau2_data_dir": str(expected_tau2_data_dir),
                "max_concurrency": args.max_concurrency,
                "seed": args.seed,
                "assay_config": assay_config,
                "execution_status": "complete" if final_error is None else "invalid",
                "failure_class": failure_class,
                "argv": sys.argv,
                **contract_metadata,
            },
        )
        if final_error is None:
            _require_contract_snapshot(experiment_contract, written)
    if final_error is not None:
        raise final_error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
