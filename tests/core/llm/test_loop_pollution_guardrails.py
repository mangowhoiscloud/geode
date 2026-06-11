"""Guardrails for PR-LOOP-POLLUTION-FIX (2026-06-12).

Incident (serve daemon, 2026-06-12 00:08): three parallel ``web_search``
tool calls each ran on a throwaway ``asyncio.Runner`` loop (sync delegate
handler residue of the pre-async-only era) while sharing ONE process-global
cached httpx client. The pool's asyncio primitives were bound to a foreign
loop — one call insta-failed (``Event ... is bound to a different event
loop``), two hung forever (``sample`` showed two zombie ``asyncio_N``
worker loops; the operator stared at a spinner for 50+ minutes; the
Anthropic socket sat in CLOSE_WAIT).

These tests pin the four-layer repair so refactors / new adapters / new
tools cannot silently reintroduce the pollution:

1. **No throwaway loops on the tool path** — every delegated handler is a
   coroutine function (awaited on the session loop), and every delegated
   tool class backs it with an async ``aexecute``.
2. **Loop-affine clients** — ``LoopAffineClientCache`` returns the same
   client within a loop, a DIFFERENT client on a different loop; builtin
   adapters and provider getters all route through it (no single-slot
   ``self._client = ...`` caching anywhere in the adapters package).
3. **Harness wall-clock deadline** — a hung handler resolves as a
   structured ``{"timeout": True}`` error instead of an eternal spinner.
4. **Pollution canary** — ``run_process_coroutine`` from a ``to_thread``
   worker logs a warning naming the regression.

Plus PR-WEB-SEARCH-MODEL-HINT: the session model is honoured for the
search call when documented capable, escalated to ANTHROPIC_PRIMARY
otherwise — and every web_search-capable adapter accepts the ``model``
hint (model/adapter-onboarding parity ratchet).
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from pathlib import Path
from typing import Any

import pytest
from core.llm.loop_affinity import LoopAffineClientCache

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# 1. Tool dispatch path spawns no throwaway loops
# ---------------------------------------------------------------------------


def test_every_delegated_handler_is_async_native() -> None:
    """A sync delegated handler would be bridged via ``asyncio.to_thread``
    + ``run_process_coroutine`` — one new event loop per tool call, the
    exact pollution source. Every handler built from ``_DELEGATED_TOOLS``
    must be a coroutine function. Covers future tool additions
    automatically because it iterates the registry."""
    from core.cli.tool_handlers.delegated import _build_delegated_handlers

    handlers = _build_delegated_handlers()
    assert len(handlers) >= 15
    sync_offenders = [
        name for name, handler in handlers.items() if not inspect.iscoroutinefunction(handler)
    ]
    assert not sync_offenders, (
        f"sync delegated handlers reintroduce per-call event loops "
        f"(PR-LOOP-POLLUTION-FIX): {sync_offenders}"
    )


def test_every_delegated_tool_class_has_async_aexecute() -> None:
    """The async handler awaits ``tool.aexecute`` — a delegated tool whose
    ``aexecute`` is sync (or missing) would crash at call time. Import
    each registered class and verify."""
    import importlib

    from core.cli.tool_handlers.delegated import _DELEGATED_TOOLS

    for tool_name, (module_path, class_name) in _DELEGATED_TOOLS.items():
        tool_cls = getattr(importlib.import_module(module_path), class_name)
        aexecute = inspect.getattr_static(tool_cls, "aexecute", None)
        assert aexecute is not None, f"{tool_name}: {class_name} lacks aexecute"
        assert inspect.iscoroutinefunction(aexecute), (
            f"{tool_name}: {class_name}.aexecute must be a coroutine function"
        )


def test_safe_delegate_is_a_coroutine_function() -> None:
    from core.cli.tool_handlers.clarification import _safe_delegate

    assert inspect.iscoroutinefunction(_safe_delegate), (
        "_safe_delegate reverted to sync — that re-routes delegated tools "
        "through run_process_coroutine (one event loop per call)"
    )


def test_run_process_coroutine_warns_from_to_thread_worker(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Pollution canary — calling run_process_coroutine from a thread named
    like asyncio's to_thread workers must emit the loop-pollution warning."""
    from core.async_runtime import run_process_coroutine

    async def _noop() -> str:
        return "ok"

    results: list[str] = []

    def _worker() -> None:
        results.append(run_process_coroutine(_noop()))

    with caplog.at_level("WARNING", logger="core.async_runtime"):
        thread = threading.Thread(target=_worker, name="asyncio_99")
        thread.start()
        thread.join(timeout=10)

    assert results == ["ok"]
    assert any("loop-pollution canary" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# 2. Loop-affine client caching
# ---------------------------------------------------------------------------


def test_loop_affine_cache_same_loop_reuses_client() -> None:
    cache = LoopAffineClientCache("test")
    builds: list[int] = []

    async def _twice() -> tuple[object, object]:
        first = cache.get(lambda: builds.append(1) or object())
        second = cache.get(lambda: builds.append(1) or object())
        return first, second

    first, second = asyncio.run(_twice())
    assert first is second
    assert len(builds) == 1


def test_loop_affine_cache_different_loop_builds_new_client() -> None:
    """The incident contract: a client built on loop A must NOT be served
    to loop B — loop B gets its own."""
    cache = LoopAffineClientCache("test")

    async def _get() -> object:
        return cache.get(object)

    client_a = asyncio.run(_get())
    client_b = asyncio.run(_get())
    assert client_a is not client_b


def test_loop_affine_cache_no_running_loop_builds_uncached() -> None:
    cache = LoopAffineClientCache("test")
    first = cache.get(object)
    second = cache.get(object)
    assert first is not second
    assert cache.bound_loop_count() == 0


def test_loop_affine_cache_invalidate_drops_entries() -> None:
    cache = LoopAffineClientCache("test")

    async def _get() -> object:
        return cache.get(object)

    async def _get_after_invalidate() -> tuple[object, object]:
        first = cache.get(object)
        cache.invalidate()
        second = cache.get(object)
        return first, second

    first, second = asyncio.run(_get_after_invalidate())
    assert first is not second


def test_no_single_slot_client_cache_left_in_adapters() -> None:
    """Source ratchet — a new or refactored adapter that reintroduces
    ``self._client = ...`` single-slot caching reopens the cross-loop
    pollution. The adapters package must contain zero such assignments
    (the loop-affine cache is the only sanctioned client cache)."""
    adapters_dir = REPO_ROOT / "core" / "llm" / "adapters"
    offenders: list[str] = []
    for source_path in sorted(adapters_dir.glob("*.py")):
        for line_no, line in enumerate(
            source_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "self._client =" in line or "self._client=" in line:
                offenders.append(f"{source_path.name}:{line_no}")
    assert not offenders, (
        f"single-slot client caches found (use LoopAffineClientCache): {offenders}"
    )


def test_builtin_adapters_with_get_client_use_loop_affine_cache() -> None:
    """Registry-wide parity ratchet over the REAL builtin set — every
    adapter that owns an SDK client must hold it in a
    ``LoopAffineClientCache``. A new adapter wired into
    ``bootstrap_builtins`` is covered automatically."""
    from core.llm.adapters import registry as registry_mod

    fresh: dict[str, Any] = {}
    original = registry_mod._REGISTRY
    registry_mod._REGISTRY = fresh
    try:
        registry_mod.bootstrap_builtins()
        adapters = registry_mod.list_adapters()
    finally:
        registry_mod._REGISTRY = original

    assert len(adapters) >= 8
    checked = 0
    for adapter in adapters:
        if not hasattr(adapter, "_get_client"):
            continue  # subprocess adapters (claude-cli / codex-cli) own no SDK client
        cache = getattr(adapter, "_clients", None)
        assert isinstance(cache, LoopAffineClientCache), (
            f"{adapter.name}: _get_client without a LoopAffineClientCache "
            "— cross-loop pollution risk (PR-LOOP-POLLUTION-FIX)"
        )
        checked += 1
    assert checked >= 6


def test_provider_async_clients_are_per_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """The provider-level getters (main agentic path — crosses the gateway
    main loop and the CLIPoller loop) must also be loop-affine."""
    from core.llm.providers import anthropic as anthropic_provider

    monkeypatch.setattr(anthropic_provider, "_resolve_anthropic_key", lambda: "test-key")
    anthropic_provider._async_clients.invalidate()

    async def _get() -> object:
        return anthropic_provider.get_async_anthropic_client()

    client_a = asyncio.run(_get())
    client_b = asyncio.run(_get())
    assert client_a is not client_b
    anthropic_provider._async_clients.invalidate()


# ---------------------------------------------------------------------------
# 3. Harness wall-clock deadline — hangs resolve as structured timeouts
# ---------------------------------------------------------------------------


def test_hung_tool_handler_resolves_as_timeout_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The incident's second failure mode: a coroutine awaiting a
    foreign-loop primitive hangs with no exception. The executor deadline
    must convert ANY hang into a {'timeout': True} error so the turn (and
    the operator's spinner) completes."""
    from core.agent.tool_executor import executor as executor_mod
    from core.agent.tool_executor.executor import ToolExecutor

    monkeypatch.setattr(executor_mod, "_TOOL_DEADLINE_DEFAULT_S", 0.2)

    async def _hang_forever(**_kwargs: Any) -> dict[str, Any]:
        await asyncio.Event().wait()  # never set — models the foreign-loop hang
        return {"unreachable": True}

    tool_executor = ToolExecutor(action_handlers={"hang_tool": _hang_forever}, auto_approve=True)

    result = asyncio.run(tool_executor.aexecute("hang_tool", {}))

    assert result.get("timeout") is True
    assert "wall-clock deadline" in result.get("error", "")


def test_fast_tool_handler_unaffected_by_deadline() -> None:
    from core.agent.tool_executor.executor import ToolExecutor

    async def _fast(**_kwargs: Any) -> dict[str, Any]:
        return {"ok": True}

    tool_executor = ToolExecutor(action_handlers={"fast_tool": _fast}, auto_approve=True)
    result = asyncio.run(tool_executor.aexecute("fast_tool", {}))
    assert result.get("ok") is True


def test_deadline_overrides_cover_long_running_tools() -> None:
    from core.agent.tool_executor.executor import (
        _TOOL_DEADLINE_DEFAULT_S,
        _TOOL_DEADLINE_OVERRIDES_S,
        _tool_deadline_s,
    )

    assert _tool_deadline_s("general_web_search") == _TOOL_DEADLINE_DEFAULT_S
    assert _TOOL_DEADLINE_DEFAULT_S >= 60.0, (
        "Anthropic server-side web_search legitimately takes 25-50s — a "
        "tighter default would kill healthy calls"
    )
    for tool_name, deadline in _TOOL_DEADLINE_OVERRIDES_S.items():
        assert deadline > _TOOL_DEADLINE_DEFAULT_S, tool_name


# ---------------------------------------------------------------------------
# PR-WEB-SEARCH-MODEL-HINT — capability-based search model selection
# ---------------------------------------------------------------------------


def test_resolve_web_search_model_honours_documented_models() -> None:
    from core.config import ANTHROPIC_PRIMARY
    from core.llm.adapters._capability_impls import resolve_web_search_model
    from core.llm.model_capabilities import ANTHROPIC_WEB_SEARCH_20260209_MODELS

    for model_id in ANTHROPIC_WEB_SEARCH_20260209_MODELS:
        assert resolve_web_search_model(model_id) == model_id

    # Outside the documented set (incl. empty / foreign-provider hints) →
    # escalate to the provider primary instead of risking an undocumented
    # model+tool pairing.
    assert resolve_web_search_model("") == ANTHROPIC_PRIMARY
    assert resolve_web_search_model("claude-haiku-4-5") == ANTHROPIC_PRIMARY
    assert resolve_web_search_model("gpt-5.5") == ANTHROPIC_PRIMARY


def test_every_web_search_capable_adapter_accepts_model_hint() -> None:
    """Model/adapter-onboarding parity ratchet — dispatch forwards
    ``model=`` to every adapter, so an adapter advertising web_search
    without accepting the kwarg would TypeError at runtime. Iterates the
    real builtin set so new adapters are covered automatically."""
    from core.llm.adapters import registry as registry_mod

    fresh: dict[str, Any] = {}
    original = registry_mod._REGISTRY
    registry_mod._REGISTRY = fresh
    try:
        registry_mod.bootstrap_builtins()
        adapters = registry_mod.list_adapters()
    finally:
        registry_mod._REGISTRY = original

    checked = 0
    for adapter in adapters:
        if not getattr(adapter, "supports_web_search", False):
            continue
        signature = inspect.signature(adapter.aweb_search)
        assert "model" in signature.parameters, (
            f"{adapter.name}.aweb_search must accept the ``model`` hint kwarg "
            "(dispatch forwards it unconditionally)"
        )
        checked += 1
    assert checked >= 5


def test_web_tools_forward_session_model_to_dispatch() -> None:
    """Source pin — both web-search tool surfaces must pass the session
    model from ToolContext into dispatch."""
    for relative in ("core/tools/web_tools.py", "core/tools/web_search.py"):
        src = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert 'getattr(ctx, "model", "")' in src, relative
        assert "model=session_model" in src, relative


# ---------------------------------------------------------------------------
# IPC handshake noise — benign client drops must not raise unhandled
# ---------------------------------------------------------------------------


def test_ipc_client_handler_catches_connection_reset() -> None:
    """Source pin — the thin CLI's probe connection drops abruptly on every
    connect; pre-fix that surfaced as ``asyncio ERROR Unhandled exception
    in client_connected_cb`` noise (serve.log 2026-06-12 00:07:58)."""
    src = (REPO_ROOT / "core" / "server" / "ipc_server" / "poller.py").read_text(encoding="utf-8")
    handler_src = src.split("async def _handle_async_client", 1)[1].split(
        "async def _handle_client_async", 1
    )[0]
    assert "ConnectionResetError" in handler_src
    assert "BrokenPipeError" in handler_src
