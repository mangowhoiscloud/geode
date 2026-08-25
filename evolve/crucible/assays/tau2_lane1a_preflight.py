"""Build the Crucible Tau2 Lane 1A no-model identity and reset receipt."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import random
import site
import sys
import tomllib
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from evals.benchmarks.manifest import get_benchmark
from evals.benchmarks.tau2.turn_supervisor import _agent_system_prompt

from evolve.crucible.artifacts import write_exclusive_json
from evolve.crucible.assays.verifiers.tau2 import tau2_task_unit
from evolve.crucible.contract import (
    ContractError,
    TaskUnit,
    _run_git,
    task_pack_sha256,
    tracked_tree_sha256,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TAU2_LANE1A_BENCHMARK_REVISION = get_benchmark("tau2-bench").commit
TAU2_LANE1A_HARNESS_REVISION = TAU2_LANE1A_BENCHMARK_REVISION  # v1.0.x compatibility
TAU2_LANE1A_PACKAGE_VERSION = "1.0.1"
TAU2_LANE1A_DOMAINS = ("airline", "retail", "telecom")
TAU2_LANE1A_TASK_COUNTS = {"airline": 50, "retail": 114, "telecom": 114}
TAU2_LANE1A_ORDERED_ID_SHA256 = {
    "airline": "bbe145f76529d0cd492df47e6de4f55ad7bbcd20c8c6347a9d54d46b068180d0",
    "retail": "72ebb6673ba42e72f2a994fe1dd7df5712d90fb98f878ff0ac31e5a01623c2d2",
    "telecom": "2b7fc8242e27a6fbc098eb6a36a06e7dab5877c7975aec4df8beb25acc333d46",
}
TAU2_LANE1A_AGGREGATE_ID_SHA256 = "235aed57b2fae0ce1c067d704e4f50fd56b03dfe0c4420d654a6441288d376ba"
TAU2_LANE1A_TASK_PACK_SHA256 = {
    1: "a3957a9a3056fc879a06eaa2774fbb4b234afdf247168ba6d0b217602d9aa0ec",
    4: "4cb14548611f00eca89df0992a9e5b5aa1ad320acc2d2c6c0e11045b07eb35e6",
}
TAU2_LANE1A_SOURCE_TASK_PACK_SHA256 = {
    1: "0d80c76af8f7551a234df8720a5049c9ca1f781df28f7741e994c431a98a4ec3",
    4: "2aa1a0b436ed90756b722692b25ad50d03868b5cb2c1ba34096cd410e806b82b",
}
TAU2_LANE1A_USER_LLM_ARGS: Mapping[str, Any] = {
    "max_tokens": 8192,
    "num_retries": 0,
    "reasoning_effort": "low",
    "temperature": 0.0,
    "timeout": 180,
}
TAU2_LANE1A_RUNTIME_DISTRIBUTIONS = {
    "litellm": "litellm",
    "loguru": "loguru",
    "openai": "openai",
    "pandas": "pandas",
    "pydantic": "pydantic",
}


def _model_visible_tau2_tool_schemas(tools: list[Any] | None) -> list[dict[str, Any]]:
    """Return the exact post-policy schemas exposed to the frozen GEODE route."""
    from core.agent.loop import get_agentic_tools
    from core.llm.adapters import build_openai_responses_kwargs
    from core.llm.adapters.translation import build_adapter_request
    from core.wiring.runtime import build_policy_sources
    from evals.benchmarks.tau2.tool_bridge import _tau2_tool_registry

    registry, handlers = _tau2_tool_registry(tools)
    allowed = set(handlers)
    schemas = get_agentic_tools(
        registry,
        force_include=allowed,
        provider="openai",
        source="subscription",
        policy_sources=build_policy_sources(),
    )
    request = build_adapter_request(
        model="gpt-5.4",
        system="Tau2 Lane 1A no-model schema probe",
        messages=[],
        tools=[schema for schema in schemas if schema.get("name") in allowed],
        tool_choice={"type": "auto"},
        max_tokens=32768,
        temperature=0.0,
        thinking_budget=0,
        effort="high",
    )
    shaped = build_openai_responses_kwargs(
        request,
        backend="codex",
        adapter_name="tau2-preflight",
    )
    return list(shaped.get("tools", []))


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _environment_db_hashes(environment: Any) -> dict[str, str | None]:
    return {
        "agent_db_sha256": environment.get_db_hash(),
        "user_db_sha256": environment.get_user_db_hash(),
    }


def _apply_tau2_initial_state(environment: Any, task: Any) -> None:
    initial_state = task.initial_state
    environment.set_state(
        initialization_data=(
            initial_state.initialization_data if initial_state is not None else None
        ),
        initialization_actions=(
            initial_state.initialization_actions if initial_state is not None else None
        ),
        message_history=(
            deepcopy(initial_state.message_history)
            if initial_state is not None and initial_state.message_history is not None
            else []
        ),
    )


def _mutate_first_scalar(value: Any) -> bool:
    """Mutate one existing in-memory DB scalar for an isolation probe."""
    if hasattr(value, "__dict__"):
        for name, item in vars(value).items():
            replacement = _preflight_scalar_replacement(item)
            if replacement is not item:
                object.__setattr__(value, name, replacement)
                return True
            if _mutate_first_scalar(item):
                return True
    elif isinstance(value, dict):
        for key, item in value.items():
            replacement = _preflight_scalar_replacement(item)
            if replacement is not item:
                value[key] = replacement
                return True
            if _mutate_first_scalar(item):
                return True
    elif isinstance(value, list):
        for index, item in enumerate(value):
            replacement = _preflight_scalar_replacement(item)
            if replacement is not item:
                value[index] = replacement
                return True
            if _mutate_first_scalar(item):
                return True
    elif isinstance(value, tuple):
        return any(_mutate_first_scalar(item) for item in value)
    return False


def _preflight_scalar_replacement(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, str):
        return value + "__geode_reset_probe__"
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 1.0
    return value


def _attest_tau2_resets(
    domain: str,
    tasks: list[Any],
    environment_constructor: Any,
) -> dict[str, Any]:
    """Prove task initialization is isolated to a fresh upstream environment."""
    source = _environment_db_hashes(environment_constructor())
    if source["agent_db_sha256"] is None:
        raise ContractError(f"tau2 {domain} environment has no agent DB hash")
    if domain == "telecom" and source["user_db_sha256"] is None:
        raise ContractError("tau2 telecom environment has no user DB hash")

    task_states: list[dict[str, Any]] = []
    for task in tasks:
        mutated = environment_constructor()
        guard = environment_constructor()
        _apply_tau2_initial_state(mutated, task)
        _apply_tau2_initial_state(guard, task)
        initialized = _environment_db_hashes(guard)
        if _environment_db_hashes(mutated) != initialized:
            raise ContractError(f"tau2 {domain} duplicate initial state drifted for task {task.id}")
        if not _mutate_first_scalar(mutated.tools.db):
            raise ContractError(f"tau2 {domain} agent DB cannot be mutated for reset probe")
        if domain == "telecom" and not _mutate_first_scalar(mutated.user_tools.db):
            raise ContractError("tau2 telecom user DB cannot be mutated for reset probe")
        mutated_hashes = _environment_db_hashes(mutated)
        if mutated_hashes["agent_db_sha256"] == initialized["agent_db_sha256"]:
            raise ContractError(f"tau2 {domain} agent DB reset probe made no change")
        if (
            domain == "telecom"
            and mutated_hashes["user_db_sha256"] == initialized["user_db_sha256"]
        ):
            raise ContractError("tau2 telecom user DB reset probe made no change")
        guard_after = _environment_db_hashes(guard)
        rebuilt = environment_constructor()
        _apply_tau2_initial_state(rebuilt, task)
        rebuilt_hashes = _environment_db_hashes(rebuilt)
        if guard_after != initialized or rebuilt_hashes != initialized:
            raise ContractError(f"tau2 {domain} reset isolation failed for task {task.id}")
        task_states.append(
            {
                "task_id": str(task.id),
                "initialized": initialized,
                "mutated_probe": mutated_hashes,
                "guard_after_probe": guard_after,
                "rebuilt": rebuilt_hashes,
            }
        )

    return {
        "strategy": "fresh upstream environment per simulation, then task initial_state",
        "source": source,
        "fresh_environment_count": len(tasks) * 3 + 1,
        "probe": "per task: initialize A/B, mutate A DB(s), prove B unchanged and rebuilt C == B",
        "guard_unchanged": True,
        "rebuilt_matches_guard": True,
        "task_initial_states": task_states,
        "task_initial_states_sha256": _canonical_sha256(task_states),
    }


def _tau2_native_user_prompt_hashes(
    tasks: list[Any],
    environment_constructor: Any,
) -> dict[str, Any]:
    """Hash the prompt the native user actually receives, not get_info metadata."""
    from tau2.runner.build import build_user

    prompts: list[dict[str, str]] = []
    tool_schemas: list[dict[str, str]] = []
    for task in tasks:
        user = build_user(
            "user_simulator",
            environment_constructor(),
            task,
            llm="gpt-5.2",
            llm_args=dict(TAU2_LANE1A_USER_LLM_ARGS),
        )
        prompts.append(
            {
                "task_id": str(task.id),
                "system_prompt_sha256": hashlib.sha256(
                    str(user.system_prompt).encode("utf-8")
                ).hexdigest(),
            }
        )
        tool_schemas.append(
            {
                "task_id": str(task.id),
                "openai_schemas_sha256": _canonical_sha256(
                    [tool.openai_schema for tool in (user.tools or [])]
                ),
            }
        )
    return {
        "authority": "build_user(...).system_prompt",
        "task_system_prompts": prompts,
        "task_system_prompts_sha256": _canonical_sha256(prompts),
        "task_user_tool_schemas_sha256": _canonical_sha256(tool_schemas),
        "tool_schema_boundary": "actual pre-provider native-user OpenAI schemas",
    }


def _tau2_import_origins(harness_dir: Path, modules: tuple[Any, ...]) -> dict[str, str]:
    """Fail closed unless imported Tau2 code came from the pinned checkout."""
    expected_root = (harness_dir / "src" / "tau2").resolve()
    origins: dict[str, str] = {}
    for module in modules:
        raw_path = getattr(module, "__file__", None)
        if not isinstance(raw_path, str):
            raise ContractError(f"tau2 module {module.__name__} has no source path")
        source_path = Path(raw_path).resolve()
        if not source_path.is_relative_to(expected_root):
            raise ContractError(
                f"tau2 module {module.__name__} was not imported from the pinned checkout"
            )
        origins[str(module.__name__)] = source_path.relative_to(harness_dir).as_posix()
    return origins


def _git_output(root: Path, *args: str) -> str:
    return _run_git(root, *args).strip()


def _tau2_producer_identity() -> dict[str, Any]:
    status = _git_output(REPO_ROOT, "status", "--porcelain")
    if status:
        raise ContractError("tau2 Lane 1A requires a clean GEODE producer checkout")
    return {
        "revision": _git_output(REPO_ROOT, "rev-parse", "HEAD"),
        "branch": _git_output(REPO_ROOT, "branch", "--show-current"),
        "dirty": False,
        "sources": {
            "evolve/crucible/assays/tau2_geode_agent.py": _file_sha256(
                REPO_ROOT / "evolve/crucible/assays/tau2_geode_agent.py"
            ),
            "evolve/crucible/assays/tau2_lane1a_preflight.py": _file_sha256(
                REPO_ROOT / "evolve/crucible/assays/tau2_lane1a_preflight.py"
            ),
            "evals/benchmarks/tau2/tool_bridge.py": _file_sha256(
                REPO_ROOT / "evals/benchmarks/tau2/tool_bridge.py"
            ),
            "evals/benchmarks/tau2/agent_policy.md": _file_sha256(
                REPO_ROOT / "evals/benchmarks/tau2/agent_policy.md"
            ),
        },
    }


def _tau2_policy_identity() -> dict[str, Any]:
    from core.paths import (
        AUTORESEARCH_TOOL_DESCRIPTIONS_PATH,
        AUTORESEARCH_TOOL_POLICY_PATH,
        OPERATOR_LOCAL_TOOL_DESCRIPTIONS_PATH,
        OPERATOR_LOCAL_TOOL_POLICY_PATH,
    )

    override_names = ("GEODE_TOOL_DESCRIPTIONS_OVERRIDE", "GEODE_TOOL_POLICY_OVERRIDE")
    active_overrides = [name for name in override_names if os.environ.get(name)]
    operator_paths = (
        OPERATOR_LOCAL_TOOL_DESCRIPTIONS_PATH,
        OPERATOR_LOCAL_TOOL_POLICY_PATH,
    )
    if active_overrides or any(path.exists() for path in operator_paths):
        raise ContractError("tau2 Lane 1A forbids ambient tool policy overrides")
    repo_paths = (
        AUTORESEARCH_TOOL_DESCRIPTIONS_PATH,
        AUTORESEARCH_TOOL_POLICY_PATH,
    )
    return {
        "environment_overrides": "absent",
        "operator_local_overrides": "absent",
        "repository_policy_files": {
            path.relative_to(REPO_ROOT).as_posix(): _file_sha256(path) if path.exists() else None
            for path in repo_paths
        },
    }


def _tau2_runtime_identity(harness_dir: Path) -> dict[str, Any]:
    """Bind the mixed GEODE/Tau2 interpreter without publishing local paths."""
    harness_roots = [
        Path(path).resolve()
        for path in site.getsitepackages([str(harness_dir / ".venv")])
        if Path(path).is_dir()
    ]
    allowed_roots = [
        ("selected-python-prefix", Path(path).resolve())
        for path in site.getsitepackages([sys.prefix])
        if Path(path).is_dir()
    ]
    allowed_roots.extend(("tau2-harness-venv", root) for root in harness_roots)
    distributions: dict[str, dict[str, str]] = {}
    for distribution, module_name in TAU2_LANE1A_RUNTIME_DISTRIBUTIONS.items():
        module = importlib.import_module(module_name)
        raw_path = getattr(module, "__file__", None)
        module_path = Path(raw_path).resolve() if isinstance(raw_path, str) else None
        origin_row = next(
            (
                (label, root)
                for label, root in allowed_roots
                if module_path is not None and module_path.is_relative_to(root)
            ),
            None,
        )
        if origin_row is None:
            raise ContractError(
                f"tau2 dependency {distribution} was not imported from a frozen runtime root"
            )
        origin, origin_root = origin_row
        normalized_name = distribution.replace("-", "_").lower()
        installed = next(
            (
                candidate
                for candidate in importlib.metadata.distributions(path=[str(origin_root)])
                if str(candidate.metadata.get("Name", "")).replace("-", "_").lower()
                == normalized_name
            ),
            None,
        )
        if installed is None:
            raise ContractError(f"tau2 dependency {distribution} has no matching metadata")
        distributions[distribution] = {
            "version": installed.version,
            "origin": origin,
        }
    tau2_distribution = next(
        (
            candidate
            for root in harness_roots
            for candidate in importlib.metadata.distributions(path=[str(root)])
            if str(candidate.metadata.get("Name", "")).replace("-", "_").lower() == "tau2"
        ),
        None,
    )
    if tau2_distribution is None or tau2_distribution.version != TAU2_LANE1A_PACKAGE_VERSION:
        actual = tau2_distribution.version if tau2_distribution is not None else "[missing]"
        raise ContractError(
            f"tau2 frozen runtime requires {TAU2_LANE1A_PACKAGE_VERSION}, got {actual}"
        )
    return {
        "python": {
            "implementation": sys.implementation.name,
            "version": ".".join(map(str, sys.version_info[:3])),
            "cache_tag": str(sys.implementation.cache_tag),
        },
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "geode_uv_lock_sha256": _file_sha256(REPO_ROOT / "uv.lock"),
        "tau2_pyproject_sha256": _file_sha256(harness_dir / "pyproject.toml"),
        "tau2_uv_lock_sha256": _file_sha256(harness_dir / "uv.lock"),
        "tau2": {
            "version": tau2_distribution.version,
            "origin": "tau2-harness-venv",
        },
        "distributions": distributions,
    }


def _tau2_lane1a_preflight_receipt(harness_dir: Path) -> dict[str, Any]:
    """Freeze Tau2 base identity and reset evidence without model/account calls."""
    from evolve.crucible.assays.tau2_geode_agent import _tau2_data_root

    harness_dir = harness_dir.resolve()
    revision = _git_output(harness_dir, "rev-parse", "HEAD")
    if revision != TAU2_LANE1A_BENCHMARK_REVISION:
        raise ContractError(
            "tau2 Lane 1A requires upstream revision "
            f"{TAU2_LANE1A_BENCHMARK_REVISION}, got {revision}"
        )
    if _git_output(harness_dir, "status", "--porcelain"):
        raise ContractError("tau2 Lane 1A requires a clean upstream checkout")
    package = tomllib.loads((harness_dir / "pyproject.toml").read_text(encoding="utf-8"))
    package_version = str(package.get("project", {}).get("version", ""))
    if package_version != TAU2_LANE1A_PACKAGE_VERSION:
        raise ContractError(
            f"tau2 Lane 1A requires package {TAU2_LANE1A_PACKAGE_VERSION}, "
            f"got {package_version or '[missing]'}"
        )

    tau2 = importlib.import_module("tau2")
    tau2_evaluator = importlib.import_module("tau2.evaluator.evaluator")
    tau2_agent_metrics = importlib.import_module("tau2.metrics.agent_metrics")
    tau2_registry = importlib.import_module("tau2.registry")
    tau2_build = importlib.import_module("tau2.runner.build")
    tau2_helpers = importlib.import_module("tau2.runner.helpers")

    registry = tau2_registry.registry
    get_tasks = tau2_helpers.get_tasks
    import_origins = _tau2_import_origins(
        harness_dir,
        (
            tau2,
            tau2_registry,
            tau2_helpers,
            tau2_build,
            tau2_evaluator,
            tau2_agent_metrics,
        ),
    )

    policy_identity = _tau2_policy_identity()
    data_root = _tau2_data_root(harness_dir) / "tau2"
    source_paths = {
        "airline": ("db.json", "policy.md", "tasks.json", "split_tasks.json"),
        "retail": ("db.json", "policy.md", "tasks.json", "split_tasks.json"),
        "telecom": (
            "db.toml",
            "user_db.toml",
            "main_policy.md",
            "tech_support_manual.md",
            "tasks.json",
            "split_tasks.json",
        ),
    }
    domains: list[dict[str, Any]] = []
    aggregate_units: list[TaskUnit] = []
    aggregate_raw_source_units: list[TaskUnit] = []
    for domain in TAU2_LANE1A_DOMAINS:
        domain_root = data_root / "domains" / domain
        raw_tasks = json.loads((domain_root / "tasks.json").read_text(encoding="utf-8"))
        split = json.loads((domain_root / "split_tasks.json").read_text(encoding="utf-8"))
        if not isinstance(raw_tasks, list) or not isinstance(split, dict):
            raise ContractError(f"tau2 {domain} task sources have an invalid shape")
        split_ids = split.get("base")
        if not isinstance(split_ids, list) or len(set(map(str, split_ids))) != len(split_ids):
            raise ContractError(f"tau2 {domain} base split is missing or contains duplicates")
        split_id_set = set(map(str, split_ids))
        raw_ids = [str(task.get("id")) for task in raw_tasks]
        if len(raw_ids) != len(set(raw_ids)):
            raise ContractError(f"tau2 {domain} tasks.json contains duplicate IDs")
        if not split_id_set.issubset(set(raw_ids)):
            raise ContractError(f"tau2 {domain} base split contains unknown task IDs")
        source_order = [
            str(task.get("id")) for task in raw_tasks if str(task.get("id")) in split_id_set
        ]
        tasks = get_tasks(
            task_set_name=domain,
            task_split_name="base",
            task_ids=None,
            num_tasks=None,
        )
        ordered_ids = [str(task.id) for task in tasks]
        if ordered_ids != source_order:
            raise ContractError(f"tau2 {domain} loader order differs from tasks.json order")
        ordered_ids_sha256 = _canonical_sha256(ordered_ids)
        if ordered_ids_sha256 != TAU2_LANE1A_ORDERED_ID_SHA256[domain]:
            raise ContractError(f"tau2 {domain} ordered base task identity drifted")
        expected_count = TAU2_LANE1A_TASK_COUNTS[domain]
        if len(tasks) != expected_count or len(split_ids) != expected_count:
            raise ContractError(
                f"tau2 {domain} base count drifted: loader={len(tasks)}, split={len(split_ids)}"
            )
        units = [
            tau2_task_unit(
                task.model_dump(mode="json"),
                field=f"tau2 {domain} base task[{index}]",
            )
            for index, task in enumerate(tasks)
        ]
        raw_by_id = {str(task["id"]): task for task in raw_tasks}
        raw_source_units = [
            tau2_task_unit(raw_by_id[task_id], field=f"tau2 {domain} source task[{index}]")
            for index, task_id in enumerate(ordered_ids)
        ]
        task_model = type(tasks[0])
        normalized_source_units = [
            tau2_task_unit(
                task_model.model_validate(raw_by_id[task_id]).model_dump(mode="json"),
                field=f"tau2 {domain} normalized source task[{index}]",
            )
            for index, task_id in enumerate(ordered_ids)
        ]
        if normalized_source_units != units:
            raise ContractError(
                f"tau2 {domain} normalized source tasks differ from loaded runtime identities"
            )
        probe_environment = registry.get_env_constructor(domain)()
        agent_tool_schemas = _model_visible_tau2_tool_schemas(probe_environment.get_tools() or [])
        aggregate_units.extend(
            TaskUnit(
                task_id=f"{domain}/{unit.task_id}",
                family_id=f"{domain}/{unit.family_id}",
                content_sha256=unit.content_sha256,
            )
            for unit in units
        )
        aggregate_raw_source_units.extend(
            TaskUnit(
                task_id=f"{domain}/{unit.task_id}",
                family_id=f"{domain}/{unit.family_id}",
                content_sha256=unit.content_sha256,
            )
            for unit in raw_source_units
        )
        source_pack = {trials: task_pack_sha256(raw_source_units, trials) for trials in (1, 4)}
        loaded_pack = {trials: task_pack_sha256(units, trials) for trials in (1, 4)}
        domains.append(
            {
                "domain": domain,
                "task_count": len(tasks),
                "ordered_task_ids": ordered_ids,
                "ordered_task_ids_sha256": ordered_ids_sha256,
                "tasks": [unit.to_dict() for unit in units],
                "source_task_pack_sha256": source_pack,
                "source_normalization": "upstream Task.model_validate(...).model_dump(mode=json)",
                "loaded_runtime_task_pack_sha256": loaded_pack,
                "source_files": {
                    name: _file_sha256(domain_root / name) for name in source_paths[domain]
                },
                "geode_agent_system_prompt_sha256": hashlib.sha256(
                    _agent_system_prompt(probe_environment.get_policy()).encode("utf-8")
                ).hexdigest(),
                "agent_tool_schema_sha256": _canonical_sha256(agent_tool_schemas),
                "agent_tool_schema_boundary": (
                    "actual post-policy Codex Responses schemas in provider order"
                ),
                "agent_tool_policy_inputs": policy_identity,
                "reset": _attest_tau2_resets(
                    domain,
                    tasks,
                    registry.get_env_constructor(domain),
                ),
                "native_user_prompt": _tau2_native_user_prompt_hashes(
                    tasks,
                    registry.get_env_constructor(domain),
                ),
            }
        )

    evaluator_paths = (
        "src/tau2/run.py",
        "src/tau2/runner/batch.py",
        "src/tau2/runner/build.py",
        "src/tau2/runner/helpers.py",
        "src/tau2/runner/simulation.py",
        "src/tau2/evaluator/evaluator.py",
        "src/tau2/evaluator/evaluator_env.py",
        "src/tau2/evaluator/evaluator_action.py",
        "src/tau2/evaluator/evaluator_communicate.py",
        "src/tau2/evaluator/evaluator_nl_assertions.py",
        "src/tau2/runner/checkpoint.py",
    )
    scorer_paths = (
        "src/tau2/metrics/agent_metrics.py",
        "src/tau2/scripts/leaderboard/prepare_submission.py",
        "src/tau2/scripts/leaderboard/submission.py",
        "src/tau2/scripts/leaderboard/leaderboard.py",
    )
    prompt_paths = (
        "data/tau2/user_simulator/simulation_guidelines.md",
        "data/tau2/user_simulator/simulation_guidelines_tools.md",
    )
    seed_rng = random.Random(300)
    trial_seeds = [seed_rng.randint(0, 1_000_000) for _ in range(4)]
    aggregate_ids = [unit.task_id for unit in aggregate_units]
    aggregate_id_sha256 = _canonical_sha256(aggregate_ids)
    if aggregate_id_sha256 != TAU2_LANE1A_AGGREGATE_ID_SHA256:
        raise ContractError("tau2 aggregate ordered base task identity drifted")
    aggregate_task_pack_sha256 = {
        trials: task_pack_sha256(aggregate_units, trials) for trials in (1, 4)
    }
    aggregate_source_task_pack_sha256 = {
        trials: task_pack_sha256(aggregate_raw_source_units, trials) for trials in (1, 4)
    }
    if aggregate_source_task_pack_sha256 != TAU2_LANE1A_SOURCE_TASK_PACK_SHA256:
        raise ContractError("tau2 raw source aggregate task pack identity drifted")
    if aggregate_task_pack_sha256 != TAU2_LANE1A_TASK_PACK_SHA256:
        raise ContractError("tau2 aggregate base task pack identity drifted")
    user_llm_args = dict(TAU2_LANE1A_USER_LLM_ARGS)
    receipt: dict[str, Any] = {
        "schema_id": "geode.tau2-lane1a-preflight-receipt.v1",
        "claim_class": "no-model-preflight",
        "promotion_authority": "none",
        "harness": {
            "repository": "sierra-research/tau2-bench",
            "revision": revision,
            "package": "tau2",
            "package_version": package_version,
            "clean_checkout": True,
            "tracked_tree_sha256": tracked_tree_sha256(harness_dir),
            "import_origins": import_origins,
        },
        "producer": _tau2_producer_identity(),
        "runtime": _tau2_runtime_identity(harness_dir),
        "workload": {
            "split": "base",
            "domain_order": list(TAU2_LANE1A_DOMAINS),
            "task_count": len(aggregate_units),
            "ordered_task_ids": aggregate_ids,
            "ordered_task_ids_sha256": aggregate_id_sha256,
            "task_pack_definition": (
                "raw pinned source identity plus upstream Task-model-normalized content "
                "equal to the loaded runtime identity, ordered with trials_per_task"
            ),
            "source_task_pack_sha256": aggregate_source_task_pack_sha256,
            "loaded_runtime_task_pack_sha256": aggregate_task_pack_sha256,
            "domains": domains,
        },
        "profile": {
            "agent": {
                "implementation": "geode_agent",
                "model": "gpt-5.4",
                "provider": "openai",
                "route": "subscription",
                "reasoning_effort": "high",
                "runtime_owner": "candidate",
                "per_turn_time_budget_seconds": 600,
                "max_tokens": 32768,
                "max_rounds": 0,
                "max_rounds_semantics": "unlimited; bounded by per-turn and simulation wall clocks",
            },
            "user": {
                "implementation": "user_simulator",
                "model": "gpt-5.2",
                "declared_reasoning_effort": str(user_llm_args["reasoning_effort"]),
                "llm_args_user": user_llm_args,
                "configured_route": "OpenAI API/PAYG via upstream LiteLLM",
                "observed_route": "not_tested",
                "provider_owner": "upstream LiteLLM",
                "runtime_owner": "evaluator",
                "generation_shape": "one upstream LiteLLM generation per user turn",
                "per_generation_max_tokens": 8192,
                "per_generation_timeout_seconds": 180,
                "per_generation_retries": 0,
                "total_wall_budget": "bounded by the shared simulation timeout",
                "total_invocations": "bounded by max_steps=200",
                "geode_user_flags_control_native_user": False,
            },
            "trials": 4,
            "seed_root": 300,
            "trial_seeds": trial_seeds,
            "seed_application": {
                "native_user_simulator": "trial seed injected into llm_args_user",
                "geode_agent": "set_seed is unsupported/no-op on the subscription adapter",
                "claim": "task/trial identity only; not deterministic replay",
            },
            "max_steps": 200,
            "max_errors": 10,
            "max_retries": 0,
            "max_concurrency": 1,
            "timeout_seconds": 3600,
            "dialog_max_steps": 200,
            "upstream_defaults": {
                "max_steps": 200,
                "max_errors": 10,
                "max_retries": 3,
                "max_concurrency": 3,
            },
            "geode_adapter_defaults_not_used": {
                "max_steps": 20,
                "max_errors": 1,
                "max_retries": 0,
                "max_concurrency": 1,
            },
            "retry_policy": (
                "no in-run retries; infrastructure reruns require a new external attempt lineage"
            ),
        },
        "prompt_sources": {path: _file_sha256(harness_dir / path) for path in prompt_paths}
        | {
            "evals/benchmarks/tau2/agent_policy.md": _file_sha256(
                REPO_ROOT / "evals/benchmarks/tau2/agent_policy.md"
            )
        },
        "score_authority": {
            "flow": "run_simulation -> evaluate_simulation(EvaluationType.ALL) -> results.json",
            "result": "data/tau2/simulations/<run-id>/results.json",
            "success": "reward within 0.000001 of 1.0",
            "domain_metrics": (
                "compute_metrics: per-task pass^1..pass^4 across four trials, then "
                "arithmetic mean across tasks and percentage conversion"
            ),
            "headline": (
                "arithmetic mean of airline, retail, and telecom pass_1 percentages; "
                "not pooled 278-task accuracy"
            ),
            "infrastructure_errors": (
                "excluded by upstream compute_metrics and forbidden by the Lane 1 exit gate"
            ),
            "required_coverage": "278 tasks x 4 trials",
            "sources": {path: _file_sha256(harness_dir / path) for path in evaluator_paths},
            "scorer_sources": {path: _file_sha256(harness_dir / path) for path in scorer_paths},
        },
        "execution_attestation": {
            "model_calls": 0,
            "account_calls": 0,
            "auth": "not_tested",
            "quota": "not_tested",
            "route_readiness": "not_tested",
            "account_isolation": {
                "candidate": "subscription OAuth credential class",
                "evaluator_user": "separate PAYG API credential class",
                "observed": "not_tested",
            },
            "score_generated": False,
        },
    }
    receipt["receipt_payload_sha256"] = _canonical_sha256(receipt)
    return receipt


def _write_tau2_lane1a_preflight_receipt(harness_dir: Path, path: Path) -> None:
    resolved = path.resolve()
    if resolved.is_relative_to(harness_dir.resolve()) or resolved.is_relative_to(
        REPO_ROOT.resolve()
    ):
        raise ContractError("tau2 preflight receipt must be outside both source checkouts")
    receipt = _tau2_lane1a_preflight_receipt(harness_dir)
    if receipt["producer"] != _tau2_producer_identity():
        raise ContractError("tau2 Lane 1A producer changed while building the receipt")
    if (
        _git_output(harness_dir, "rev-parse", "HEAD") != receipt["harness"]["revision"]
        or _git_output(harness_dir, "status", "--porcelain")
        or tracked_tree_sha256(harness_dir) != receipt["harness"]["tracked_tree_sha256"]
    ):
        raise ContractError("tau2 Lane 1A harness changed while building the receipt")
    write_exclusive_json(path, receipt)
