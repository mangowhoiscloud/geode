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


def test_loop_affine_cache_sweeps_closed_loop_entries() -> None:
    """Codex MCP review 2026-06-12 — a cached client can hold a strong
    reference back to its (closed) loop, keeping the weak key alive
    forever. get() must sweep closed-loop entries so throwaway loops do
    not leak one client each."""
    cache = LoopAffineClientCache("test")

    class _ClientHoldingItsLoop:
        def __init__(self) -> None:
            self.loop = asyncio.get_running_loop()  # strong back-reference

    async def _seed() -> None:
        cache.get(_ClientHoldingItsLoop)

    asyncio.run(_seed())  # loop now closed; entry survives via back-ref
    assert cache.bound_loop_count() == 1

    async def _touch() -> None:
        cache.get(object)

    asyncio.run(_touch())  # any next get() sweeps the dead entry
    # The back-ref entry must be swept; the _touch entry's plain-object
    # value holds no loop back-ref, so its weak key dies with the loop —
    # a broken sweep would leave the back-ref entry behind (count 1).
    assert cache.bound_loop_count() == 0, "closed-loop entry must be swept"


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
    main loop and the CLIPoller loop) must ALL be loop-affine. Covers
    anthropic + openai + glm (Codex MCP review 2026-06-12 — the original
    pin only exercised anthropic)."""
    from core.llm.providers import anthropic as anthropic_provider
    from core.llm.providers import glm as glm_provider
    from core.llm.providers import openai as openai_provider

    monkeypatch.setattr(anthropic_provider, "_resolve_anthropic_key", lambda: "test-key")
    monkeypatch.setattr(openai_provider, "_resolve_openai_key", lambda: "test-key")
    monkeypatch.setattr(glm_provider, "_resolve_glm_endpoint", lambda: ("test-key", "https://e"))

    getters = [
        (anthropic_provider._async_clients, anthropic_provider.get_async_anthropic_client),
        (openai_provider._async_openai_clients, openai_provider._get_async_openai_client),
        (glm_provider._async_glm_clients, glm_provider._get_async_glm_client),
    ]
    for cache, getter in getters:
        cache.invalidate()

        async def _get(_getter: Any = getter) -> object:
            return _getter()

        client_a = asyncio.run(_get())
        client_b = asyncio.run(_get())
        assert client_a is not client_b, getter.__name__
        cache.invalidate()


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

    assert _tool_deadline_s("glob_files") == _TOOL_DEADLINE_DEFAULT_S
    assert _TOOL_DEADLINE_DEFAULT_S >= 60.0, (
        "Anthropic server-side web_search legitimately takes 25-50s — a "
        "tighter default would kill healthy calls"
    )
    for tool_name, deadline in _TOOL_DEADLINE_OVERRIDES_S.items():
        assert deadline > _TOOL_DEADLINE_DEFAULT_S, tool_name


def test_deadline_override_keys_match_registered_handler_names() -> None:
    """Codex MCP review 2026-06-12 — the original table keyed
    ``computer_use`` while the registered handler is ``computer``, so the
    600s override silently never applied. Every override key must be an
    actually-registered handler name."""
    from core.agent.tool_executor.executor import _TOOL_DEADLINE_OVERRIDES_S
    from core.cli.tool_handlers import _build_tool_handlers

    registered = set(_build_tool_handlers().keys())
    # ``computer`` registers only when GEODE_COMPUTER_USE_ENABLED + pyautogui
    # are present — pin its name against the builder source instead.
    single_tool_src = (REPO_ROOT / "core" / "cli" / "tool_handlers" / "single_tool.py").read_text(
        encoding="utf-8"
    )
    conditional = {"computer"} if '"computer"' in single_tool_src else set()
    unknown = sorted(set(_TOOL_DEADLINE_OVERRIDES_S) - registered - conditional)
    assert not unknown, (
        f"deadline override keys with no registered handler (dead overrides): {unknown}"
    )


def test_dispatch_tolerates_legacy_adapter_without_model_kwarg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex MCP review 2026-06-12 — the registry is open to external
    plugin adapters; one still on the pre-hint ``aweb_search`` signature
    must keep working instead of raising TypeError when dispatch forwards
    ``model=``."""
    from core.llm.adapters.base import WebSearchResult
    from core.llm.adapters.dispatch import web_search_via_adapters

    class _LegacyAdapter:
        name = "legacy-external"
        provider = "anthropic"
        source = "payg"
        supports_web_search = True

        async def aweb_search(self, query: str, *, max_results: int = 5) -> WebSearchResult:
            return WebSearchResult(query=query, text="legacy ok", adapter_name=self.name)

    monkeypatch.setattr("core.llm.adapters.dispatch.list_adapters", lambda: [_LegacyAdapter()])
    monkeypatch.setattr("core.llm.adapters._source_inference.infer_source", lambda provider: "payg")

    result = asyncio.run(web_search_via_adapters("q", model="claude-opus-4-8"))
    assert result.text == "legacy ok"


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


# ---------------------------------------------------------------------------
# PR-GATEWAY-BRIDGE-FRONTIER — remaining disposable-loop residue removed
# ---------------------------------------------------------------------------


def test_webhook_bridge_marshals_into_main_loop_not_a_throwaway_loop() -> None:
    """Source pin — frontier convergence (hermes cron-ticker
    ``run_coroutine_threadsafe`` into the one long-lived gateway loop;
    openclaw single-loop lane dispatch): the stdlib webhook server's
    thread-side bridge must submit to the main serve loop, never build a
    disposable ``asyncio.Runner`` loop per request."""
    src = (REPO_ROOT / "core" / "cli" / "typer_serve.py").read_text(encoding="utf-8")
    assert "run_coroutine_threadsafe" in src
    assert "run_process_coroutine(_gateway_processor" not in src, (
        "webhook bridge reverted to a throwaway event loop per request"
    )


def test_sync_llm_judge_inside_running_loop_downgrades_to_rule_based(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behavioral pin — the sync judge wrapper called from INSIDE a running
    loop must downgrade to the rule-based fallback (effective_mode marks
    the downgrade) instead of bridging through ThreadPoolExecutor +
    ``asyncio.run`` (a disposable loop per call, removed
    PR-GATEWAY-BRIDGE-FRONTIER)."""
    from core.agent.loop.agent_loop import AgenticResult
    from core.agent.verify import VerifyMode, _verify_llm_judge

    monkeypatch.setenv("GEODE_VERIFY_MODE", "llm_judge")
    result = AgenticResult(text="OK", tool_calls=[], rounds=1, termination_reason="natural")

    async def _call_from_inside_loop() -> Any:
        return _verify_llm_judge(result, loop=object())

    verdict = asyncio.run(_call_from_inside_loop())
    assert verdict.mode is VerifyMode.LLM_JUDGE
    assert verdict.effective_mode is VerifyMode.RULE_BASED, (
        "sync judge inside a running loop must downgrade, not thread-bridge"
    )


def test_verify_judge_has_no_thread_pool_loop_bridge() -> None:
    """Source pin — no ThreadPoolExecutor + asyncio.run bridge in the sync
    judge wrapper (the comment on the old branch claimed per-call loops
    protected shared clients — exactly backwards pre-loop-affinity)."""
    src = (REPO_ROOT / "core" / "agent" / "verify.py").read_text(encoding="utf-8")
    # Match the executable pattern, not the docstring documenting its removal.
    assert "ThreadPoolExecutor(" not in src
    assert "import concurrent.futures" not in src


def test_web_search_deadline_covers_client_timeout_with_retry() -> None:
    """Coherence pin — the operator watched a healthy web_search retry get
    killed at 119.9s (2026-06-12 02:0x): per-attempt client timeout 60s ×
    (1 try + 1 dispatch retry) stacked exactly onto the 120s harness
    deadline. The three knobs must stay ordered:

        client timeout × (retries + 1) + slack <= tool deadline
    """
    from core.agent.tool_executor.executor import _tool_deadline_s
    from core.llm.adapters._capability_impls import ANTHROPIC_WEB_SEARCH_TIMEOUT_S
    from core.llm.adapters.dispatch import _CONNECTION_TRANSIENT_RETRIES

    attempts = _CONNECTION_TRANSIENT_RETRIES + 1
    slack_s = 10.0
    assert _tool_deadline_s("general_web_search") >= (
        ANTHROPIC_WEB_SEARCH_TIMEOUT_S * attempts + slack_s
    ), (
        "general_web_search: deadline no longer covers client-timeout x retry "
        "— healthy retries will be killed at the boundary again"
    )
