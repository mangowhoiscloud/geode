"""Explicit model selection, escalation, and per-model context adaptation.

Extracted from the monolithic ``core/agent/loop.py`` (Tier 3 #7). Each
function takes the ``AgenticLoop`` as the first parameter (``loop``).
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from core.config.session import SessionModelConfig

if TYPE_CHECKING:
    from core.llm.adapters.base import LLMAdapter

    from .agent_loop import AgenticLoop

log = logging.getLogger(__name__)


def _resolve_provider(model: str) -> str:
    """Late-bound lookup so ``monkeypatch.setattr("core.agent.loop._resolve_provider", ...)``
    reaches this module's call sites. The package re-exports the real
    implementation under the same name (see ``core/agent/loop/__init__.py``)."""
    from core.agent import loop as _loop_pkg

    return _loop_pkg._resolve_provider(model)


def _resolve_path_b_adapter(
    provider: str,
    source: str,
) -> LLMAdapter | None:
    """Resolve a Path-B :class:`LLMAdapter` for ``(provider, source)``.

    PR-MAINPATH-4 (2026-05-24) — mirrors the
    ``AgenticLoop.__init__``-side normalisation introduced in
    PR-MAINPATH-1's fix-up commit (``openai-codex`` → ``openai``
    because the Path-B registry uses a narrower provider vocabulary,
    with the Codex source encoded on the ``source`` axis as
    ``subscription``). Hard-fail contract preserved per Codex MCP
    2026-05-23 HIGH 2 — ``resolve_for`` raises when the registered
    ``(provider, source)`` pair is missing.

    PR-MAINPATH-67 (2026-05-24) — the legacy
    ``_resolve_agentic_adapter`` shim was deleted alongside the rest
    of the legacy resolver surface; this function is now the sole
    adapter factory used by ``/model`` switching.
    """
    from core.llm.adapters import CONCRETE_SOURCES
    from core.llm.adapters.registry import active_registry_snapshot, normalize_registry_provider

    if source not in CONCRETE_SOURCES:
        return None
    return active_registry_snapshot().resolve_for(normalize_registry_provider(provider), source)


def _resolve_model_route(
    loop: AgenticLoop,
    model: str,
    provider: str | None = None,
) -> tuple[str, str]:
    """Preserve explicit pins; re-infer only when an inferred provider changes."""
    new_provider = provider or _resolve_provider(model)
    source = loop._source
    if new_provider != loop._provider and not getattr(loop, "_source_explicit", False):
        from core.llm.adapters._source_inference import infer_source

        source = infer_source(new_provider)
    return new_provider, source


def _apply_model_update(
    loop: AgenticLoop,
    model: str,
    provider: str | None = None,
    *,
    source: str | None = None,
) -> tuple[str, bool]:
    """Publish synchronously; a tool projection failure preserves the old route."""
    loop_fields = (
        "model",
        "_provider",
        "_source",
        "_new_adapter",
        "_prompt_dirty",
        "_bound_tool_plan",
        "_tools",
        "_transient_tools",
        "_transient_deferred_tool_names",
        "_capability_graph",
        "_preflight_hint",
    )
    processor_fields = ("_model", "_provider", "_source", "_adapter_name")
    executor_fields = (
        "_bound_tool_plan",
        "_handlers",
        "_tool_input_schemas",
        "_bound_allowed_tools",
    )
    snapshots = [
        (owner, {name: getattr(owner, name) for name in names if hasattr(owner, name)})
        for owner, names in (
            (loop, loop_fields),
            (loop._tool_processor, processor_fields),
            (getattr(loop, "executor", None), executor_fields),
        )
    ]
    try:
        return _publish_model_update(loop, model, provider, source=source)
    except BaseException:
        for owner, fields in snapshots:
            for name, value in fields.items():
                setattr(owner, name, value)
        raise


def validate_session_model_config(loop: AgenticLoop, candidate: SessionModelConfig) -> None:
    """Resolve all requested routes before any live selection is published."""
    from core.config import settings
    from core.config.judgment import resolve_judgment_route
    from core.llm.adapters._anthropic_common import anthropic_effort_kwargs
    from core.llm.adapters._openai_common import get_openai_model_spec, validate_reasoning_effort
    from core.llm.adapters.registry import normalize_registry_provider
    from core.llm.errors import LLMRequestValidationError
    from core.llm.model_catalog import require_model_source_available
    from core.llm.providers.glm import get_glm_model_spec

    for model, source in (
        (candidate.model, candidate.source),
        (candidate.reflection_model, candidate.reflection_source),
        (candidate.judge_model, candidate.judge_source),
    ):
        if not model:
            if source:
                raise LLMRequestValidationError("An inherited model cannot pin a separate source")
            continue
        provider = normalize_registry_provider(_resolve_provider(model))
        require_model_source_available(model, provider=provider, source=source)
        loop._adapter_registry_snapshot.resolve_for(provider, source)
        openai_model = model.removeprefix("openrouter/openai/")
        if provider == "openai" or model.startswith("openrouter/openai/"):
            spec = get_openai_model_spec(openai_model)
            if spec.reasoning_effort_values is not None:
                validate_reasoning_effort(candidate.effort, spec=spec)
        elif provider == "anthropic":
            anthropic_effort_kwargs(model, candidate.effort)
        elif provider == "glm":
            spec_glm = get_glm_model_spec(model)
            if (
                spec_glm
                and spec_glm.reasoning_effort_values
                and candidate.effort not in spec_glm.reasoning_effort_values
            ):
                raise LLMRequestValidationError(
                    f"{model} does not support effort {candidate.effort!r}"
                )
    if (
        candidate.judgment_engine == "jev"
        and resolve_judgment_route(
            settings, engine=candidate.judgment_engine, provider=candidate.jev_provider
        )
        is None
    ):
        raise LLMRequestValidationError("The selected judgment route has no usable credentials")


async def apply_session_model_config(
    loop: AgenticLoop, candidate: SessionModelConfig, *, reason: str = "user_switch"
) -> bool:
    """Apply one admitted candidate to this session, never process defaults."""
    validate_session_model_config(loop, candidate)
    current = loop._model_settings.updated(
        {"model": loop.model, "effort": loop._effort, "source": loop._source}
    )
    if candidate == current:
        return False
    await update_model_async(
        loop,
        candidate.model,
        _resolve_provider(candidate.model),
        reason,
        source=candidate.source,
        model_settings=candidate,
    )
    return True


async def apply_pending_model_config(loop: AgenticLoop, messages: list[dict[str, Any]]) -> None:
    """Commit a tool-requested selection only after its whole batch completed."""
    candidate = loop._pending_model_settings
    loop._pending_model_settings = None
    if candidate is not None:
        await apply_session_model_config(loop, candidate)
        # Adaptation and model breadcrumbs operate on the complete context.
        # Keep the current turn on that same history, including tool results.
        messages[:] = loop.context.get_messages()


def _publish_model_update(
    loop: AgenticLoop,
    model: str,
    provider: str | None = None,
    *,
    source: str | None = None,
) -> tuple[str, bool]:
    """Apply the route already checked by adaptation, or resolve a direct update."""
    old_model = loop.model
    old_route = (loop._provider, loop._source)
    if source is None:
        new_provider, new_source = _resolve_model_route(loop, model, provider)
    else:
        new_provider, new_source = provider or _resolve_provider(model), source
    if (new_provider, new_source) != (loop._provider, loop._source):
        if new_source != loop._source:
            log.info(
                "AgenticLoop source re-inferred on provider switch: %s (%s) -> %s (%s)",
                loop._source,
                old_model,
                new_source,
                model,
            )
        from core.llm.adapters.registry import use_registry_snapshot

        with use_registry_snapshot(loop._adapter_registry_snapshot):
            new_adapter = _resolve_path_b_adapter(new_provider, new_source)
        loop._provider = new_provider
        loop._source = new_source
        loop._new_adapter = new_adapter
    loop.model = model
    loop._tool_processor._model = model
    loop._tool_processor._provider = getattr(
        loop._new_adapter, "provider", getattr(loop, "_provider", "")
    )
    loop._tool_processor._source = getattr(
        loop._new_adapter, "source", getattr(loop, "_source", "")
    )
    loop._tool_processor._adapter_name = getattr(loop._new_adapter, "name", "")
    if old_model != model or old_route != (new_provider, new_source):
        loop._prompt_dirty = True
        reproject_bound = getattr(loop, "_reproject_bound_tool_plan", None)
        if callable(reproject_bound):
            reproject_bound()
        refresh_tools = getattr(loop, "refresh_tools", None)
        if callable(refresh_tools):
            refresh_tools()

    # Sync SessionMeter so "Worked for" status line shows the correct model
    from core.ui.agentic_ui import update_session_model

    update_session_model(model)
    log.info("AgenticLoop model updated: %s (provider=%s)", model, loop._provider)
    return old_model, old_model != model


def _inject_model_switch_breadcrumb(loop: AgenticLoop, old_model: str, model: str) -> int:
    """PR-SIL-5THEME C5 (2026-05-23) — returns purged_count for X2 telemetry.

    Pre-PR: `None` 반환 (caller 가 무시했었음). 이제 ``purge_stale_model_switch_acks``
    의 count 를 forward 해서 update_model_async 가 ``MODEL_SWITCHED`` hook
    payload 에 동봉 가능하게.
    """
    if loop.context.is_empty:
        return 0
    # v0.52.8 — strip stale "Understood. I am now <prev>" acks
    # left by earlier model switches in the same session. Without
    # this, the new model reads "I am gpt-5.4-mini" assistant
    # messages and asserts the wrong identity (production
    # incident 2026-04-27 — gpt-5.5 answered "I am gpt-5.4-mini").
    purged = purge_stale_model_switch_acks(loop)
    loop.context.add_user_message(
        f"[system] Model switched: {old_model} -> {model}. "
        "Current model identity has changed. Do not reference the "
        "previous model's responses as current state."
    )
    loop.context.add_assistant_message(f"Understood. Current model: {model}.")
    return purged


async def update_model_async(
    loop: AgenticLoop,
    model: str,
    provider: str | None = None,
    reason: str = "user_switch",
    *,
    source: str | None = None,
    model_settings: SessionModelConfig | None = None,
) -> None:
    """Async model update path used from ``AgenticLoop.arun``."""
    # Summarize with the current route before selecting the smaller target.
    # Never route maintenance through a new credential source implicitly.
    target_provider, target_source = _resolve_model_route(loop, model, provider)
    if source is not None:
        target_source = source
    if reason != "resume" and (model, target_provider, target_source) != (
        loop.model,
        loop._provider,
        loop._source,
    ):
        await adapt_context_for_model(loop, model, target_provider, source=target_source)
    old_model, changed = _apply_model_update(loop, model, target_provider, source=target_source)
    if model_settings is not None:
        loop._model_settings = model_settings
        loop._effort = model_settings.effort
        loop._source_explicit = True
    elif hasattr(loop, "_model_settings"):
        loop._model_settings = loop._model_settings.updated(
            {"model": model, "source": target_source}
        )
    if changed:
        from core.ui.agentic_ui import emit_model_switched

        emit_model_switched(old_model, model, reason)

        # PR-SIL-5THEME C5 (2026-05-23) — D4 X2 telemetry. breadcrumb +
        # stale-ack purge 가 끝난 *후* MODEL_SWITCHED 발화 → payload 에
        # purged_count 동봉 가능. 이전엔 trigger 가 breadcrumb 보다 먼저
        # 발화돼 purge 정보가 hook 에 안 들어갔다. operator 가
        # v0.52.5-style stale-ack 회귀를 stream 으로 추적 가능.
        purged_count = (
            0 if reason == "resume" else _inject_model_switch_breadcrumb(loop, old_model, model)
        )

        if loop._hooks:
            from core.hooks import HookEvent

            await loop._hooks.trigger_async(
                HookEvent.MODEL_SWITCHED,
                {
                    "from_model": old_model,
                    "to_model": model,
                    "reason": reason,
                    # PR-SIL-5THEME C5 — D4 X2 telemetry 의 stale-ack
                    # 카운트. 0 면 첫 switch / clean 상태, ≥1 이면 직전
                    # switch 의 ack 가 history 에 남아 있던 상태.
                    "purged_ack_count": purged_count,
                },
            )


def purge_stale_model_switch_acks(loop: AgenticLoop) -> int:
    """Remove prior runtime-generated model-switch assistant acknowledgements.

    v0.52.8 — added after a production incident where gpt-5.5 (post
    ``/model`` switch from gpt-5.4-mini) silently inherited the prior
    model's identity from a lingering history message. The OpenAI
    gpt-5.5 system card explicitly says it should identify as
    "GPT-5.5", so the bug was not model behaviour — it was our
    breadcrumb pollution. Each model switch should leave **only one**
    active "I am now <model>" ack at any time.

    PR-MIC (2026-05-23) — handles Anthropic-style block-form content
    too. Previously only ``isinstance(content, str)`` matched, so an
    ack stored as ``[{"type": "text", "text": "Understood. I am now …"}]``
    silently survived. Conservative: only matches the exact
    legacy ``Understood. I am now `` and current ``Understood. Current model: ``
    prefixes in either representation. Never touches user content.

    PR-SIL-5THEME C5 (2026-05-23) — D4 X2 telemetry. Returns purged
    count so caller can forward to ``MODEL_SWITCHED`` hook payload.
    이전엔 silent — operator 가 stale-ack purge fire 여부 추적 불가
    (v0.52.5 같은 incident 의 회귀 발견이 매번 production debug 필요).
    Backward compat: 기존 caller 가 ``None`` 반환 가정한 경우 없음
    (이 함수는 caller 가 결과 무시했었음).
    """
    msgs = loop.context.messages
    prefixes = ("Understood. I am now ", "Understood. Current model: ")
    kept: list[Any] = []
    purged = 0
    for msg in msgs:
        if msg.get("role") != "assistant":
            kept.append(msg)
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and content.startswith(prefixes):
            purged += 1
            continue
        if isinstance(content, list):
            # Block-form (Anthropic / multimodal): drop the message
            # when any text-block begins with our self-emitted prefix.
            text_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
            if any(
                isinstance(b.get("text"), str) and b["text"].startswith(prefixes)
                for b in text_blocks
            ):
                purged += 1
                continue
        kept.append(msg)
    msgs.clear()
    msgs.extend(kept)
    return purged


async def adapt_context_for_model(
    loop: AgenticLoop,
    target_model: str,
    provider: str | None = None,
    *,
    source: str | None = None,
) -> None:
    """Fit history to the target budget, summarizing with the previous route."""
    from core.config import settings
    from core.orchestration.context_budget import resolve_context_budget_policy
    from core.orchestration.context_monitor import (
        check_context,
        summarize_tool_results,
    )

    if loop.context.is_empty:
        return

    if source is None:
        target_provider, target_source = _resolve_model_route(loop, target_model, provider)
    else:
        target_provider, target_source = provider or _resolve_provider(target_model), source
    policy = resolve_context_budget_policy(
        target_model, provider=target_provider, source=target_source
    )
    messages = deepcopy(loop.context.messages)
    metrics = check_context(messages, target_model, policy=policy)
    if not metrics.is_warning:
        return

    original_tokens = metrics.estimated_tokens
    log.info(
        "Context adaptation: %.0f%% (%d/%d prompt budget) for %s",
        metrics.usage_pct,
        metrics.estimated_tokens,
        metrics.prompt_budget_tokens,
        target_model,
    )

    # Phase 1: Summarize large tool results (preserves conversation structure)
    summarize_tool_results(messages, metrics.policy or metrics.context_window)

    # Await the previous model while its provider/source/effort are still bound.
    metrics = check_context(messages, target_model, policy=policy)
    if metrics.is_critical:
        # Apply the summary to the actual owned history so PostCompact observes
        # its committed result. Cheap reduction above remains staged on failure.
        messages = loop.context.messages
        await loop._ctx_mgr._apply_overflow_strategy(
            {
                "strategy": "compact",
                "keep_recent": metrics.policy.resolve_keep_recent(settings.compact_keep_recent)
                if metrics.policy
                else settings.compact_keep_recent,
                "policy": metrics.policy,
                "trigger": "model_switch",
                "hard": False,
            },
            messages,
            settings,
            loop.model,
            loop._provider,
        )

    metrics = check_context(messages, target_model, policy=policy)
    if metrics.is_critical:
        from core.agent.loop import _ContextExhaustedError

        raise _ContextExhaustedError(
            "Context does not fit target model; current model retained. "
            "Retry /compact or explicitly use /compact --prune before switching."
        )
    loop.context.messages[:] = messages
    log.info(
        "Context adapted: %d → %d tokens (%.0f%% of %s window)",
        original_tokens,
        metrics.estimated_tokens,
        metrics.usage_pct,
        target_model,
    )


def fallback_chain_suggestions(loop: AgenticLoop) -> list[str]:
    """Return remaining models in the current adapter's fallback chain.

    Used by the loop to populate ``suggested_models`` in the
    ``model_action_required`` diagnostic. The user picks one and runs
    ``/model <id>``; we never auto-switch.

    PR-MAINPATH-67 (2026-05-24) — reads from the Path-B adapter
    (``loop._new_adapter``). Path-B adapters that don't expose a
    ``fallback_chain`` attribute return an empty list, matching the
    v0.99.19 shipped default (no silent fallback).
    """
    current = loop.model
    chain = list(getattr(loop._new_adapter, "fallback_chain", []) or [])
    if current in chain:
        idx = chain.index(current)
        return chain[idx + 1 :]
    return chain
