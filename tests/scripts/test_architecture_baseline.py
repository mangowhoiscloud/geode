"""Tests for the generated architecture inventory."""

from __future__ import annotations

import asyncio
import contextvars
import importlib
import json
from collections.abc import Callable
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from scripts import architecture_baseline as baseline

_CONTEXT_SETTERS = {
    "core/agent/cognitive_state_ctx.py:_active_state": "core.agent.cognitive_state_ctx.set_cognitive_state",
    "core/agent/cognitive_state_ctx.py:_active_session_id": "core.agent.cognitive_state_ctx.set_session_id",
    "core/agent/cognitive_state_ctx.py:_active_turn_id": "core.agent.cognitive_state_ctx.set_turn_id",
    "core/agent/cognitive_state_ctx.py:_active_parent_session_key": "core.agent.cognitive_state_ctx.set_parent_session_key",
    "core/agent/cognitive_state_ctx.py:_active_parent_session_id": "core.agent.cognitive_state_ctx.set_parent_session_id",
    "core/agent/safety.py:_skip_permissions_var": "core.agent.safety.set_skip_permissions",
    "core/cli/commands/_state.py:_conversation_ctx": "core.cli.commands._state.set_conversation_context",
    "core/cli/session_state.py:_readiness_ctx": "core.cli.session_state._set_readiness",
    "core/cli/session_state.py:_current_loop_ctx": "core.cli.session_state.set_current_loop",
    "core/hooks/tool_hooks.py:_tool_hooks_ctx": "core.hooks.tool_hooks.set_tool_hooks",
    "core/mcp/calendar_port.py:_calendar_ctx": "core.mcp.calendar_port.set_calendar",
    "core/mcp/notification_port.py:_notification_ctx": "core.mcp.notification_port.set_notification",
    "core/observability/session_metrics.py:_current_metrics": "core.observability.session_metrics.set_current_session_metrics",
    "core/observability/session_timeline.py:_CURRENT_SESSION_TIMELINE": "core.observability.session_timeline.set_current_session_timeline",
    "core/orchestration/tool_offload.py:_offload_store_ctx": "core.orchestration.tool_offload.set_offload_store",
    "core/tools/memory_tools.py:_default_session_store_ctx": "core.tools.memory_tools.set_default_session_store",
    "core/tools/memory_tools.py:_project_memory_ctx": "core.tools.memory_tools.set_project_memory",
    "core/tools/memory_tools.py:_org_memory_ctx": "core.tools.memory_tools.set_org_memory",
    "core/tools/memory_tools.py:_hooks_ctx": "core.tools.memory_tools.set_memory_hooks",
    "core/tools/profile_tools.py:_user_profile_ctx": "core.tools.profile_tools.set_user_profile",
}
_UNSET = object()


def _resolve_callable(path: str) -> Callable[..., object]:
    module_name, function_name = path.rsplit(".", 1)
    return cast(Callable[..., object], getattr(importlib.import_module(module_name), function_name))


def _python_module(path: str) -> str:
    module_name = path.removesuffix(".py").replace("/", ".")
    return module_name.removesuffix(".__init__")


def _noop() -> None:
    pass


def _set_context_local_value(surface: object, name: str, value: object) -> None:
    setattr(surface, name, value)


def _context_value(label: str, variable: contextvars.ContextVar[object], surface: object) -> object:
    context_local_attributes = {
        "core/ui/agentic_ui/_state.py:_ipc_writer_local": "writer",
        "core/ui/agentic_ui/_state.py:_pipeline_subject_local": "subject_id",
        "core/ui/agentic_ui/_state.py:_meter_local": "meter",
        "core/ui/console.py:_ConsoleProxy._local": "console",
    }
    if attribute := context_local_attributes.get(label):
        return getattr(surface, attribute, None)
    try:
        return variable.get()
    except LookupError:
        return _UNSET


def _bind_context_boundary(
    label: str,
    variable: contextvars.ContextVar[object],
    surface: object,
    marker: object,
    tmp_path: Path,
) -> tuple[object, Callable[[], object], bool]:
    if setter_path := _CONTEXT_SETTERS.get(label):
        setter = _resolve_callable(setter_path)
        if label == "core/mcp/notification_port.py:_notification_ctx":
            module = importlib.import_module("core.mcp.notification_port")
            previous_fallback = module._notification_fallback
            setter(marker)

            def restore_notification() -> None:
                setter(None)
                module._notification_fallback = previous_fallback

            return marker, restore_notification, True
        setter(marker)
        cleanup: Callable[[], object] = _noop
        resets = False
        if label == "core/hooks/tool_hooks.py:_tool_hooks_ctx":
            cleanup = partial(_resolve_callable("core.hooks.tool_hooks.clear_tool_hooks"), marker)
            resets = True
        elif label == "core/tools/memory_tools.py:_hooks_ctx":
            cleanup = partial(
                _resolve_callable("core.tools.memory_tools.clear_memory_hooks"), marker
            )
            resets = True
        elif label in {
            "core/cli/commands/_state.py:_conversation_ctx",
            "core/mcp/calendar_port.py:_calendar_ctx",
            "core/mcp/notification_port.py:_notification_ctx",
            "core/observability/session_metrics.py:_current_metrics",
            "core/observability/session_timeline.py:_CURRENT_SESSION_TIMELINE",
            "core/tools/memory_tools.py:_project_memory_ctx",
            "core/tools/memory_tools.py:_org_memory_ctx",
            "core/tools/profile_tools.py:_user_profile_ctx",
        }:
            cleanup = partial(setter, None)
            resets = True
        return marker, cleanup, resets

    if label == "core/agent/cognitive_state_ctx.py:_active_tool_call_id":
        module = importlib.import_module("core.agent.cognitive_state_ctx")
        token = module.set_tool_call_id(marker)
        return marker, partial(module.reset_tool_call_id, token), True
    if label == "core/cli/session_state.py:_scheduler_service_ctx":
        variable.set(marker)
        return marker, _noop, False
    if label == "core/cli/session_state.py:_user_task_graph_ctx":
        module = importlib.import_module("core.cli.session_state")
        graph = module._get_user_task_graph()
        return graph, _noop, False
    if label == "core/llm/adapters/dispatch.py:_session_adapter_usage_ctx":
        module = importlib.import_module("core.llm.adapters.dispatch")
        module.begin_session_adapter_tracking()
        return variable.get(), module.end_session_adapter_tracking, True
    if label == "core/llm/platform_hints.py:_current_surface":
        module = importlib.import_module("core.llm.platform_hints")
        token = module.set_current_surface("cli")
        return variable.get(), partial(variable.reset, token), True
    if label == "core/llm/token_tracker.py:_tracker_ctx":
        module = importlib.import_module("core.llm.token_tracker")
        tracker = module.get_tracker()
        tracker.accumulator.record(module.LLMUsage(model="probe", input_tokens=1, output_tokens=1))
        return tracker, module.reset_tracker, True
    if label == "core/observability/run_dir.py:_active_run_dir":
        module = importlib.import_module("core.observability.run_dir")
        scope = module.run_dir_scope(tmp_path / "run-dir")
        return scope.__enter__(), partial(scope.__exit__, None, None, None), True
    if label == "core/runtime_audit.py:_runtime_audit_active":
        module = importlib.import_module("core.runtime_audit")
        token = module.set_runtime_audit_active(True)
        return True, partial(module.reset_runtime_audit_active, token), True
    if label == "core/tools/personal_data.py:_safety_policies":
        module = importlib.import_module("core.tools.personal_data")
        policy = object()
        registration = SimpleNamespace(safety=policy)
        base = SimpleNamespace(tool_names=("probe",), registration_for=lambda _name: registration)
        module.set_bound_tool_data_policies(SimpleNamespace(base=base))
        return variable.get(), partial(module.set_bound_tool_data_policies, None), True
    if label == "core/ui/agentic_ui/_state.py:_ipc_writer_local":
        _set_context_local_value(surface, "writer", marker)
        return marker, partial(_set_context_local_value, surface, "writer", None), True
    if label == "core/ui/agentic_ui/_state.py:_pipeline_subject_local":
        module = importlib.import_module("core.ui.agentic_ui._state")
        module.set_pipeline_subject("probe")
        return "probe", _noop, False
    if label == "core/ui/agentic_ui/_state.py:_meter_local":
        module = importlib.import_module("core.ui.agentic_ui._state")
        return module.init_session_meter("probe"), _noop, False
    if label == "core/ui/console.py:_ConsoleProxy._local":
        module = importlib.import_module("core.ui.console")
        module.set_thread_console(marker)
        return marker, module.reset_thread_console, True
    if label == ("geode_product/self_improving/loop/observe/run_timeline.py:_current_run_timeline"):
        module = importlib.import_module("geode_product.self_improving.loop.observe.run_timeline")
        scope = module.run_timeline_scope(marker)
        return scope.__enter__(), partial(scope.__exit__, None, None, None), True
    raise AssertionError(f"missing lifecycle boundary probe: {label}")


def test_build_baseline_is_deterministic_and_internally_consistent() -> None:
    first = baseline.build_baseline()
    second = baseline.build_baseline()

    assert first == second
    assert first["schema_version"] == 4
    assert baseline.serialize_baseline(first) == baseline.serialize_baseline(second)

    for package in ("core", "geode_product", "plugins", "tests"):
        inventory = first["packages"][package]
        assert inventory["python_files"] > 0
        assert inventory["python_loc"] >= inventory["python_files"]

    tools = first["tools"]
    assert tools["definition_count"] == len(tools["definition_names"])
    assert tools["schema_count"] == len(tools["schema_names"])
    assert tools["execution_registration_count"] == len(tools["execution_registration_names"])
    assert set(tools["handler_registration_origins"]) == set(tools["handler_registration_names"])
    assert tools["duplicate_definition_names"] == []
    assert tools["schema_errors"] == []
    assert tools["definition_only"] == []
    assert tools["execution_only"] == [
        "computer",
        "doctor_slack",
        "recall_tool_result",
    ]


def test_inventory_lists_traceable_architecture_details() -> None:
    measured = baseline.build_baseline()

    assert measured["hook_events"]["count"] == len(measured["hook_events"]["members"])
    assert measured["built_in_adapters"]["count"] == len(measured["built_in_adapters"]["classes"])
    assert measured["context_vars"]["count"] == len(measured["context_vars"]["items"])
    assert measured["core_to_product_imports"] == {
        "site_count": 0,
        "file_count": 0,
        "sites": [],
    }
    assert measured["self_improving_facades"] == {
        "count": len(baseline.SELF_IMPROVING_FACADE_TARGETS),
        "items": [
            {"path": path, "target": target}
            for path, target in sorted(baseline.SELF_IMPROVING_FACADE_TARGETS.items())
        ],
    }
    assert measured["import_linter"]["ignored_edge_count"] == sum(
        len(contract["ignored_edges"]) for contract in measured["import_linter"]["contracts"]
    )
    assert measured["coordinators"]["AgenticLoop"]["constructor_arg_count"] > 0
    assert measured["coordinators"]["RuntimeCoreConfig"]["field_count"] > 0

    serialized = baseline.serialize_baseline(measured)
    assert str(baseline.REPO_ROOT) not in serialized
    assert json.loads(serialized) == measured


def test_context_var_inventory_has_complete_lifecycle_classification() -> None:
    inventory = baseline.build_baseline()["context_vars"]

    assert inventory["classification_counts"] == {
        "request_identity": 7,
        "request_local_mutable_state": 9,
        "diagnostic_scope": 7,
        "cache": 1,
        "service_locator": 11,
    }
    assert inventory["service_locator_count"] == 11
    assert inventory["lifecycle_source"] == baseline.CONTEXT_VAR_LIFECYCLES.as_posix()
    assert {
        f"{item['path']}:{item['symbol']}"
        for item in inventory["items"]
        if item["classification"] == "service_locator"
    } == {
        "core/cli/session_state.py:_current_loop_ctx",
        "core/cli/session_state.py:_scheduler_service_ctx",
        "core/hooks/tool_hooks.py:_tool_hooks_ctx",
        "core/mcp/calendar_port.py:_calendar_ctx",
        "core/mcp/notification_port.py:_notification_ctx",
        "core/orchestration/tool_offload.py:_offload_store_ctx",
        "core/tools/memory_tools.py:_default_session_store_ctx",
        "core/tools/memory_tools.py:_hooks_ctx",
        "core/tools/memory_tools.py:_org_memory_ctx",
        "core/tools/memory_tools.py:_project_memory_ctx",
        "core/tools/profile_tools.py:_user_profile_ctx",
    }
    for item in inventory["items"]:
        assert item["async_propagation_test"] == baseline.CONTEXT_VAR_PROPAGATION_TEST
        assert all(item[field] for field in baseline.CONTEXT_VAR_LIFECYCLE_FIELDS)


def test_context_var_inventory_propagates_and_resets(tmp_path: Path) -> None:
    """Every measured binding crosses a child task through its production boundary."""

    async def exercise(
        label: str,
        variable: contextvars.ContextVar[object],
        surface: object,
        marker: object,
    ) -> tuple[object, object, object, object, bool]:
        async def read() -> object:
            await asyncio.sleep(0)
            return _context_value(label, variable, surface)

        before = _context_value(label, variable, surface)
        if label == "geode_product/benchmark_harness/tau2_runtime_contract.py:_CURRENT_ATTEMPT":
            module = importlib.import_module(
                "geode_product.benchmark_harness.tau2_runtime_contract"
            )

            async def read_attempt() -> tuple[str, str, int, int, int]:
                await asyncio.sleep(0)
                attempt = variable.get()
                assert attempt is not None
                return (
                    attempt.attempt_id,
                    attempt.task_id,
                    attempt.trial,
                    attempt.attempt,
                    attempt.seed,
                )

            def run_attempt() -> tuple[object, object]:
                tracker = module.Tau2AttemptTracker("probe-run")

                def original(
                    run: Callable[[], object], *_args: object, **_kwargs: object
                ) -> object:
                    return run()

                wrapped = tracker.wrap(original)
                observed = wrapped(
                    lambda: asyncio.run(read_attempt()),
                    SimpleNamespace(id="probe-task"),
                    0,
                    0,
                )
                return observed, _context_value(label, variable, surface)

            observed, worker_after = await asyncio.to_thread(run_attempt)
            expected = ("probe-run:probe-task:0:1", "probe-task", 0, 1, 0)
            return expected, observed, before, worker_after, True
        expected, cleanup, resets = _bind_context_boundary(
            label, variable, surface, marker, tmp_path
        )
        try:
            observed = await asyncio.create_task(read())
        finally:
            cleanup()
        return expected, observed, before, _context_value(label, variable, surface), resets

    items = baseline.build_baseline()["context_vars"]["items"]
    variables = []
    for item in items:
        value: Any = importlib.import_module(_python_module(item["path"]))
        for part in item["symbol"].split("."):
            value = getattr(value, part)
        surface = value
        variable = value._ctx if item["implementation"] == "ContextLocal" else value
        variables.append((f"{item['path']}:{item['symbol']}", variable, surface))
    unset = object()
    for label, variable, surface in variables:
        assert isinstance(variable, contextvars.ContextVar)
        previous = variable.get(unset)
        marker = object()
        expected, observed, before, after, resets = contextvars.Context().run(
            asyncio.run, exercise(label, variable, surface, marker)
        )
        assert observed is expected or observed == expected, f"{label} did not propagate"
        if label == "core/llm/token_tracker.py:_tracker_ctx":
            assert after is expected and cast(Any, after).summary()["call_count"] == 0
        elif resets:
            assert after is before or after == before, f"{label} did not reset"
        else:
            assert after is not before and after != before, f"{label} reset unexpectedly"
        assert variable.get(unset) is previous, f"{label} did not reset"


def test_context_var_imports_use_canonical_package_names() -> None:
    assert _python_module("core/ui/__init__.py") == "core.ui"
    assert _python_module("core/ui/console.py") == "core.ui.console"


def test_context_var_inventory_detects_aliased_constructors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        "from contextvars import ContextVar as CV\n"
        "from core.ui.context_local import ContextLocal as Local\n"
        "import core.ui.context_local as context_local\n"
        "Alias = CV\n"
        'if True:\n    ambient = CV[str]("ambient")\n'
        'class Holder:\n    local = Local("local")\n'
        'qualified = context_local.ContextLocal("qualified")\n'
        'aliased = Alias("aliased")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text(
        json.dumps(
            {
                "core/sample.py:ambient": {
                    "classification": "request_identity",
                    "owner": "test",
                    "setter": "test",
                    "resetter": "test",
                    "lifetime": "test",
                    "teardown": "test",
                },
                "core/sample.py:Holder.local": {
                    "classification": "request_local_mutable_state",
                    "owner": "test",
                    "setter": "test",
                    "resetter": "test",
                    "lifetime": "test",
                    "teardown": "test",
                },
                "core/sample.py:qualified": {
                    "classification": "request_local_mutable_state",
                    "owner": "test",
                    "setter": "test",
                    "resetter": "test",
                    "lifetime": "test",
                    "teardown": "test",
                },
                "core/sample.py:aliased": {
                    "classification": "request_identity",
                    "owner": "test",
                    "setter": "test",
                    "resetter": "test",
                    "lifetime": "test",
                    "teardown": "test",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    measured = baseline._context_vars(tmp_path)["items"]
    assert [item["symbol"] for item in measured] == [
        "ambient",
        "Holder.local",
        "qualified",
        "aliased",
    ]
    assert measured[1]["has_default"] is True


def test_context_var_inventory_detects_relative_context_local_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "core" / "ui"
    package.mkdir(parents=True)
    (package / "sample.py").write_text(
        "from .context_local import ContextLocal as Local\n"
        "from core.ui import context_local\n"
        'direct = Local("direct")\n'
        'qualified = context_local.ContextLocal("qualified")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text(
        json.dumps(
            {
                f"core/ui/sample.py:{symbol}": {
                    "classification": "request_local_mutable_state",
                    "owner": "test",
                    "setter": "test",
                    "resetter": "test",
                    "lifetime": "test",
                    "teardown": "test",
                }
                for symbol in ("direct", "qualified")
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    assert [item["symbol"] for item in baseline._context_vars(tmp_path)["items"]] == [
        "direct",
        "qualified",
    ]


def test_context_var_inventory_detects_assigned_module_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        "import contextvars\n"
        "import core.ui.context_local as context_local\n"
        "cv = contextvars\n"
        "local = context_local\n"
        'direct = cv.ContextVar("direct")\n'
        'wrapped = local.ContextLocal("wrapped")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text(
        json.dumps(
            {
                f"core/sample.py:{symbol}": {
                    "classification": "request_local_mutable_state",
                    "owner": "test",
                    "setter": "test",
                    "resetter": "test",
                    "lifetime": "test",
                    "teardown": "test",
                }
                for symbol in ("direct", "wrapped")
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    assert [item["symbol"] for item in baseline._context_vars(tmp_path)["items"]] == [
        "direct",
        "wrapped",
    ]


def test_context_var_inventory_detects_reexported_constructors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "source.py").write_text(
        "import contextvars\n"
        "from contextvars import ContextVar as CV\n"
        "Alias = contextvars.ContextVar\n",
        encoding="utf-8",
    )
    (core / "sample.py").write_text(
        "from core.source import Alias\n"
        "from core import source\n"
        'direct = Alias("direct")\n'
        'qualified = source.CV("qualified")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text(
        json.dumps(
            {
                f"core/sample.py:{symbol}": {
                    "classification": "request_local_mutable_state",
                    "owner": "test",
                    "setter": "test",
                    "resetter": "test",
                    "lifetime": "test",
                    "teardown": "test",
                }
                for symbol in ("direct", "qualified")
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    assert [item["symbol"] for item in baseline._context_vars(tmp_path)["items"]] == [
        "direct",
        "qualified",
    ]


@pytest.mark.parametrize(
    "consumer",
    [
        'from core.source import cv\nstate = cv.ContextVar("state")\n',
        'import core.source as source\nstate = source.cv.ContextVar("state")\n',
        'import core\nstate = core.source.cv.ContextVar("state")\n',
        'from core import source\ncv = source.cv\nstate = cv.ContextVar("state")\n',
        'import core.source\nmodule = core\nstate = module.source.cv.ContextVar("state")\n',
    ],
)
def test_context_var_inventory_detects_reexported_constructor_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    consumer: str,
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "source.py").write_text("import contextvars as cv\n", encoding="utf-8")
    (core / "__init__.py").write_text("from core import source\n", encoding="utf-8")
    (core / "sample.py").write_text(consumer, encoding="utf-8")
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text(
        json.dumps(
            {
                "core/sample.py:state": {
                    "classification": "request_identity",
                    "owner": "test",
                    "setter": "test",
                    "resetter": "test",
                    "lifetime": "test",
                    "teardown": "test",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    assert baseline._context_vars(tmp_path)["count"] == 1


def test_context_var_inventory_scans_product_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    product = tmp_path / "geode_product"
    product.mkdir()
    (product / "sample.py").write_text(
        'from contextvars import ContextVar\ncurrent = ContextVar("current")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text(
        json.dumps(
            {
                "geode_product/sample.py:current": {
                    "classification": "request_identity",
                    "owner": "test",
                    "setter": "test",
                    "resetter": "test",
                    "lifetime": "test",
                    "teardown": "test",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    measured = baseline._context_vars(tmp_path)["items"]
    assert [(item["path"], item["symbol"]) for item in measured] == [
        ("geode_product/sample.py", "current")
    ]


@pytest.mark.parametrize(
    ("postponed", "rejected"),
    [(False, True), (True, False)],
)
def test_context_var_inventory_checks_only_runtime_annotations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postponed: bool,
    rejected: bool,
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    future = "from __future__ import annotations\n" if postponed else ""
    (core / "sample.py").write_text(
        f'{future}from contextvars import ContextVar\ndef probe(value: ContextVar("hidden")):\n    pass\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    if rejected:
        with pytest.raises(ValueError, match="ContextVar"):
            baseline._context_vars(tmp_path)
    else:
        assert baseline._context_vars(tmp_path)["count"] == 0


def test_context_var_inventory_skips_postponed_assignment_annotations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        "from __future__ import annotations\n"
        "from contextvars import ContextVar\n"
        'state: ContextVar("not-runtime")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    assert baseline._context_vars(tmp_path)["count"] == 0


@pytest.mark.parametrize("postponed", [False, True])
def test_context_var_inventory_checks_nested_runtime_annotations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postponed: bool,
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    future = "from __future__ import annotations\n" if postponed else ""
    (core / "sample.py").write_text(
        f"{future}from contextvars import ContextVar\n"
        'def make():\n    def inner(value: ContextVar("hidden")):\n        pass\n'
        '    return inner.__annotations__["value"]\nstate = make()\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    if postponed:
        assert baseline._context_vars(tmp_path)["count"] == 0
    else:
        with pytest.raises(ValueError, match="factories must assign directly"):
            baseline._context_vars(tmp_path)


@pytest.mark.parametrize(
    "factory",
    [
        'factory = lambda: ContextVar("state")',
        'def factory():\n    return ContextVar("state")',
    ],
)
def test_context_var_inventory_rejects_separately_invoked_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    factory: str,
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        f"from contextvars import ContextVar\n{factory}\nstate = factory()\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="factories must assign directly"):
        baseline._context_vars(tmp_path)


@pytest.mark.parametrize(
    "factory",
    [
        'from functools import partial\nstate = partial(ContextVar, "state")()',
        'def make(constructor):\n    return constructor("state")\nstate = make(ContextVar)',
        'import contextvars\ndef make(module):\n    return module.ContextVar("state")\nstate = make(contextvars)',
    ],
)
def test_context_var_inventory_rejects_forwarded_constructor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    factory: str,
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        f"from contextvars import ContextVar\n{factory}\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="must not be passed through factories"):
        baseline._context_vars(tmp_path)


def test_context_var_inventory_rejects_constructor_stored_in_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        "from contextvars import ContextVar\n"
        'constructors = {"ctx": ContextVar}\n'
        'state = constructors["ctx"]("state")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="must not be stored in containers"):
        baseline._context_vars(tmp_path)


@pytest.mark.parametrize(
    "assignment",
    ["Factory = ContextVar if enabled else object", "Factory = True and ContextVar"],
)
def test_context_var_inventory_rejects_indirect_constructor_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    assignment: str,
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        f'from contextvars import ContextVar\n{assignment}\nstate = Factory("state")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="must reference one constructor directly"):
        baseline._context_vars(tmp_path)


def test_context_var_inventory_rejects_conditional_constructor_module_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        "import contextvars\n"
        "module = contextvars if enabled else object\n"
        'state = module.ContextVar("state")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="must reference one constructor directly"):
        baseline._context_vars(tmp_path)


def test_context_var_inventory_ignores_function_local_type_annotation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        "from contextvars import ContextVar\ndef probe():\n    value: ContextVar[str]\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    assert baseline._context_vars(tmp_path)["count"] == 0


@pytest.mark.parametrize(
    "factory",
    [
        'def factory():\n    from contextvars import ContextVar\n    return ContextVar("state")',
        'def factory():\n    import contextvars as cv\n    return cv.ContextVar("state")',
        'def factory():\n    from core.alias import CV\n    return CV("state")',
        'from contextvars import ContextVar\ndef factory():\n    CV = ContextVar\n    return CV("state")',
        'from contextvars import ContextVar\ndef factory(CV=ContextVar):\n    return CV("state")',
        'import contextvars\ndef factory(cv=contextvars):\n    return cv.ContextVar("state")',
        'import contextvars\ndef factory():\n    cv = contextvars\n    return cv.ContextVar("state")',
        'import contextvars\ndef factory():\n    return contextvars\nstate = factory().ContextVar("state")',
        'def factory():\n    import core.alias as alias\n    return alias.CV("state")',
    ],
)
def test_context_var_inventory_rejects_function_local_constructor_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    factory: str,
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "alias.py").write_text("from contextvars import ContextVar as CV\n", encoding="utf-8")
    (core / "sample.py").write_text(f"{factory}\nstate = factory()\n", encoding="utf-8")
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="ContextVar"):
        baseline._context_vars(tmp_path)


@pytest.mark.parametrize(
    "factory",
    [
        'def factory():\n    yield contextvars\nstate = next(factory()).ContextVar("state")',
        'def factory():\n    yield from (contextvars,)\nstate = next(factory()).ContextVar("state")',
        'def factory():\n    return [contextvars]\nstate = factory()[0].ContextVar("state")',
    ],
)
def test_context_var_inventory_rejects_context_module_factory_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    factory: str,
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        f"import contextvars\n{factory}\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="factories must assign directly"):
        baseline._context_vars(tmp_path)


def test_context_var_inventory_rejects_unpacked_constructor_keywords(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        'from contextvars import ContextVar\nstate = ContextVar("state", **{"default": None})\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="must not unpack keywords"):
        baseline._context_vars(tmp_path)


@pytest.mark.parametrize(
    "assignment",
    [
        "CV, other = ContextVar, object",
        "[CV] = [ContextVar]",
        "CV = Alias = ContextVar",
    ],
)
def test_context_var_inventory_rejects_unsupported_constructor_alias_assignment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    assignment: str,
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        f'from contextvars import ContextVar\n{assignment}\nstate = CV("state")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="constructor aliases must assign one"):
        baseline._context_vars(tmp_path)


def test_context_value_handles_context_vars_without_defaults() -> None:
    assert _context_value("probe", contextvars.ContextVar("probe"), object()) is _UNSET


def test_notification_probe_preserves_process_fallback(tmp_path: Path) -> None:
    module = importlib.import_module("core.mcp.notification_port")
    previous_fallback = module._notification_fallback
    fallback = object()
    marker = object()
    module._notification_fallback = fallback

    def exercise() -> None:
        _expected, cleanup, _resets = _bind_context_boundary(
            "core/mcp/notification_port.py:_notification_ctx",
            module._notification_ctx,
            module._notification_ctx,
            marker,
            tmp_path,
        )
        assert module._notification_fallback is marker
        cleanup()

    try:
        contextvars.Context().run(exercise)
        assert module._notification_fallback is fallback
    finally:
        module._notification_fallback = previous_fallback


@pytest.mark.parametrize(
    "source",
    [
        'if (ambient := ContextVar("ambient")):\n    pass',
        'if (Factory := ContextVar):\n    state = Factory("state")',
        'import contextvars\nFactory = contextvars.__dict__["ContextVar"]\nstate = Factory("state")',
        'for Factory in [ContextVar]:\n    state = Factory("state")',
        'states = [Factory("state") for Factory in (ContextVar,)]',
        'state = [ContextVar][0]("state")',
        'Factory = (ContextVar,)[0]\nstate = Factory("state")',
        'match ContextVar:\n    case Factory:\n        state = Factory("state")',
    ],
)
def test_context_var_inventory_rejects_unsupported_alias_expression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        f"from contextvars import ContextVar\n{source}\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="constructors must assign directly"):
        baseline._context_vars(tmp_path)


def test_context_var_inventory_allows_contextvars_runtime_helpers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        "import contextvars\ndef snapshot():\n    return contextvars.copy_context()\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    assert baseline._context_vars(tmp_path)["count"] == 0


def test_context_var_inventory_rejects_context_local_subclass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        "from core.ui.context_local import ContextLocal\n"
        "class Derived(ContextLocal):\n"
        "    pass\n"
        'state = Derived("state")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="constructors must assign directly"):
        baseline._context_vars(tmp_path)


@pytest.mark.parametrize(
    "factory",
    [
        'factories = {"ctx": lambda: ContextVar("ctx")}',
        'state = (lambda CV=ContextVar: CV)()("state")',
    ],
)
def test_context_var_inventory_rejects_lambda_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, factory: str
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        f"from contextvars import ContextVar\n{factory}\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="factories must assign directly"):
        baseline._context_vars(tmp_path)


def test_context_var_inventory_rejects_extra_context_local_backing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context_local = tmp_path / "core" / "ui" / "context_local.py"
    context_local.parent.mkdir(parents=True)
    context_local.write_text(
        "from contextvars import ContextVar\n"
        "class ContextLocal:\n"
        "    def __init__(self, name):\n"
        '        object.__setattr__(self, "_ctx", ContextVar(name))\n'
        '        object.__setattr__(self, "_extra", ContextVar(name + "-extra"))\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="exactly one direct _ctx ContextVar backing"):
        baseline._context_vars(Path("."))


def test_context_var_inventory_detects_context_local_in_its_defining_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context_local = tmp_path / "core" / "ui" / "context_local.py"
    context_local.parent.mkdir(parents=True)
    context_local.write_text(
        "from contextvars import ContextVar\n"
        "class ContextLocal:\n"
        "    def __init__(self, name):\n"
        '        object.__setattr__(self, "_ctx", ContextVar(name))\n'
        'local = ContextLocal("local")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text(
        json.dumps(
            {
                "core/ui/context_local.py:local": {
                    "classification": "request_local_mutable_state",
                    "owner": "test",
                    "setter": "test",
                    "resetter": "test",
                    "lifetime": "test",
                    "teardown": "test",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)
    monkeypatch.chdir(tmp_path)

    measured = baseline._context_vars(Path("."))["items"]

    assert [(item["symbol"], item["implementation"]) for item in measured] == [
        ("local", "ContextLocal")
    ]


@pytest.mark.parametrize(
    "consumer",
    [
        "from core.factory import make\nstate = make()\n",
        "import core.factory as factory\nstate = factory.make()\n",
    ],
)
def test_context_var_inventory_rejects_imported_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, consumer: str
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "factory.py").write_text(
        'from contextvars import ContextVar\ndef make():\n    return ContextVar("hidden")\n',
        encoding="utf-8",
    )
    (core / "sample.py").write_text(
        consumer,
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="factories must assign directly"):
        baseline._context_vars(tmp_path)


def test_context_var_inventory_rejects_reexported_factory_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "factory.py").write_text(
        'from contextvars import ContextVar\ndef make():\n    return ContextVar("hidden")\nalias = make\n',
        encoding="utf-8",
    )
    (core / "sample.py").write_text(
        "from core.factory import alias\nstate = alias()\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="factories must assign directly"):
        baseline._context_vars(tmp_path)


def test_context_var_inventory_rejects_imported_class_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "factory.py").write_text(
        "from contextvars import ContextVar\n"
        "class Factory:\n"
        "    @staticmethod\n"
        "    def make():\n"
        '        return ContextVar("hidden")\n',
        encoding="utf-8",
    )
    (core / "sample.py").write_text(
        "from core.factory import Factory\nstate = Factory.make()\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="factories must assign directly"):
        baseline._context_vars(tmp_path)


@pytest.mark.parametrize(
    "source",
    [
        'def make():\n    return ContextVar("hidden")\ndef handler(state=make()):\n    pass\n',
        'import asyncio\nasync def make():\n    return ContextVar("hidden")\nstate = asyncio.run(make())\n',
    ],
)
def test_context_var_inventory_rejects_definition_time_and_async_factories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        f"from contextvars import ContextVar\n{source}",
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="factories must assign directly"):
        baseline._context_vars(tmp_path)


@pytest.mark.parametrize(
    "source",
    [
        "pending = (ContextVar(str(i)) for i in range(2))\nstates = tuple(pending)\n",
        "for state in (ContextVar(str(i)) for i in range(2)):\n    pass\n",
    ],
)
def test_context_var_inventory_rejects_deferred_generator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        f"from contextvars import ContextVar\n{source}",
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="generators must not be deferred"):
        baseline._context_vars(tmp_path)


@pytest.mark.parametrize(
    "source",
    [
        "states = tuple(ContextVar(str(i)) for i in range(2))\n",
        "state = next(ContextVar(str(i)) for i in range(2))\n",
        "states = [*(ContextVar(str(i)) for i in range(2))]\n",
        'states = tuple(x for _ in [1] for x in [ContextVar("hidden")])\n',
        'states = [*(x for _ in [1] for x in [ContextVar("hidden")])]\n',
    ],
)
def test_context_var_inventory_rejects_eager_generator_consumers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        f"from contextvars import ContextVar\n{source}",
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="ContextVar"):
        baseline._context_vars(tmp_path)


def test_context_var_inventory_rejects_duplicate_lifecycle_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        "from contextvars import ContextVar\n"
        "if enabled:\n"
        '    state = ContextVar("enabled")\n'
        "else:\n"
        '    state = ContextVar("disabled")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text(
        json.dumps(
            {
                "core/sample.py:state": {
                    field: "request_identity" if field == "classification" else "test"
                    for field in baseline.CONTEXT_VAR_LIFECYCLE_FIELDS
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="duplicate ContextVar lifecycle declarations"):
        baseline._context_vars(tmp_path)


def test_context_var_inventory_rejects_duplicate_manifest_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        'from contextvars import ContextVar\nstate = ContextVar("state")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text(
        '{"core/sample.py:state": {}, "core/sample.py:state": {}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="duplicate JSON object key"):
        baseline._context_vars(tmp_path)


def test_context_var_inventory_rejects_class_scoped_constructor_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        "from contextvars import ContextVar as Local\n"
        'module_state = Local("module")\n'
        "class Holder:\n"
        "    from core.ui.context_local import ContextLocal as Local\n"
        '    class_state = Local("class")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="must be imported at module scope"):
        baseline._context_vars(tmp_path)


def test_context_var_inventory_rejects_immediately_invoked_lambda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        'from contextvars import ContextVar\nstate = (lambda: ContextVar("state"))()\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="factories must assign directly"):
        baseline._context_vars(tmp_path)


def test_context_var_inventory_rejects_chained_assignment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        'from contextvars import ContextVar\nleft = right = ContextVar("hidden")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="must assign one module/class name"):
        baseline._context_vars(tmp_path)


def test_context_var_inventory_rejects_unpacked_assignment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = tmp_path / "core"
    core.mkdir()
    (core / "sample.py").write_text(
        'from contextvars import ContextVar\nleft, right = ContextVar("left"), ContextVar("right")\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="must assign one module/class name"):
        baseline._context_vars(tmp_path)


def test_context_var_inventory_rejects_an_unclassified_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycles = json.loads(
        (baseline.REPO_ROOT / baseline.CONTEXT_VAR_LIFECYCLES).read_text(encoding="utf-8")
    )
    lifecycles.pop("core/tools/profile_tools.py:_user_profile_ctx")
    manifest = tmp_path / "context-var-lifecycles.json"
    manifest.write_text(json.dumps(lifecycles), encoding="utf-8")
    monkeypatch.setattr(baseline, "CONTEXT_VAR_LIFECYCLES", manifest)

    with pytest.raises(ValueError, match="ContextVar lifecycle drift"):
        baseline._context_vars(baseline.REPO_ROOT)


def test_product_import_inventory_catches_static_and_dynamic_edges(tmp_path: Path) -> None:
    path = tmp_path / "core" / "sample.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        'from geode_product import wiring\nHANDLER = "plugins.petri_audit.runner:run_audit"\n',
        encoding="utf-8",
    )

    measured = baseline._product_imports(tmp_path)

    assert measured["site_count"] == 2
    assert [site["module"] for site in measured["sites"]] == [
        "geode_product",
        "plugins.petri_audit.runner:run_audit",
    ]


def test_nested_tool_schema_validation_fails_closed() -> None:
    errors = baseline._schema_errors(
        {
            "name": "broken_tool",
            "description": "Broken nested schema fixture.",
            "category": "system",
            "cost_tier": "cheap",
            "input_schema": {
                "type": "object",
                "properties": {
                    "values": {
                        "type": "array",
                        "items": {"type": "imaginary"},
                    }
                },
                "required": [],
            },
        }
    )

    assert any(
        "input_schema.properties.values.items.type has unsupported values" in error
        for error in errors
    )


def test_tool_inventory_refuses_to_normalize_duplicate_definitions(tmp_path: Path) -> None:
    definitions_path = tmp_path / "core" / "tools" / "definitions.json"
    definitions_path.parent.mkdir(parents=True)
    definitions = json.loads(
        (baseline.REPO_ROOT / "core" / "tools" / "definitions.json").read_text(encoding="utf-8")
    )
    definitions.append(definitions[0])
    definitions_path.write_text(json.dumps(definitions), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate definitions"):
        baseline._tool_inventory(tmp_path)


def test_replace_managed_block_updates_exactly_one_region(tmp_path: Path) -> None:
    path = tmp_path / "document.md"
    original = "before\n<!-- start -->\nstale\n<!-- end -->\nafter\n"

    updated = baseline.replace_managed_block(
        original,
        start_marker="<!-- start -->",
        end_marker="<!-- end -->",
        replacement="<!-- start -->\nfresh\n<!-- end -->",
        path=path,
    )

    assert updated == "before\n<!-- start -->\nfresh\n<!-- end -->\nafter\n"


@pytest.mark.parametrize(
    "text",
    [
        "no markers",
        "<!-- start -->\nmissing end",
        "<!-- start --><!-- end --><!-- end -->",
    ],
)
def test_replace_managed_block_fails_closed_on_bad_markers(text: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="expected exactly one"):
        baseline.replace_managed_block(
            text,
            start_marker="<!-- start -->",
            end_marker="<!-- end -->",
            replacement="replacement",
            path=tmp_path / "bad.md",
        )


def test_committed_consumers_match_current_snapshot() -> None:
    measured = baseline.build_baseline()
    expected = baseline.expected_files(measured)

    assert baseline._drifted(expected) == []
