"""Model drift sync, escalation, and per-model context adaptation.

Extracted from the monolithic ``core/agent/loop.py`` (Tier 3 #7). Each
function takes the ``AgenticLoop`` as the first parameter (``loop``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .agent_loop import AgenticLoop

log = logging.getLogger(__name__)


def _resolve_provider(model: str) -> str:
    """Late-bound lookup so ``monkeypatch.setattr("core.agent.loop._resolve_provider", ...)``
    reaches this module's call sites. The package re-exports the real
    implementation under the same name (see ``core/agent/loop/__init__.py``)."""
    from core.agent import loop as _loop_pkg

    return _loop_pkg._resolve_provider(model)


def _resolve_agentic_adapter(provider: str):  # type: ignore[no-untyped-def]
    """Late-bound lookup so ``monkeypatch.setattr("core.agent.loop.resolve_agentic_adapter", ...)``
    reaches this module's call sites."""
    from core.agent import loop as _loop_pkg

    return _loop_pkg.resolve_agentic_adapter(provider)


def _settings_model_target(loop: AgenticLoop) -> str | None:
    """Return the action-model drift target when sync should apply, else None.

    PR-CL-A6 (2026-05-23) — when ``settings.act_model`` is set, the drift
    target is the action model (not ``settings.model``). Without this fix
    a session that constructed the loop with ``act_model=sonnet`` would
    revert to ``settings.model=opus`` on the next sync, undoing the
    Plan/Act split (Codex MCP HIGH #1).
    """
    if getattr(loop, "_disable_settings_drift", False):
        return None

    from core.config import settings

    # Action loop's intended model — ``act_model`` wins when set; falls
    # back to ``settings.model`` for callers that haven't configured the
    # Plan/Act knob (pre-A6 behaviour). ``isinstance(..., str)`` filters
    # MagicMock attrs in test fixtures that auto-create non-string values
    # (Codex MCP CI catch 2026-05-23).
    act_raw = getattr(settings, "act_model", "")
    act_model = act_raw.strip() if isinstance(act_raw, str) else ""
    target_model = act_model or settings.model
    if target_model == loop.model:
        return None
    if not loop._drift_target_is_healthy(target_model):
        log.warning(
            "Model drift refused: target=%s has no eligible profile — "
            "keeping loop=%s. Run `/login use <plan>` to enable target.",
            target_model,
            loop.model,
        )
        return None
    log.info(
        "Model drift detected: loop=%s target=%s — syncing",
        loop.model,
        target_model,
    )
    return str(target_model)


async def sync_model_from_settings_async(loop: AgenticLoop) -> bool:
    """Async variant of ``sync_model_from_settings`` for the agent loop.

    PR-MIC (2026-05-23) — passes ``reason="drift_sync"`` so the
    ``MODEL_SWITCHED`` hook + UI surface the actual trigger (Settings
    drift between rounds) instead of the default ``"user_switch"``
    label, which mis-attributed automatic sync to the operator and
    surfaced as a confusing ``Model: gpt-5.5 → claude-opus-4-6
    (user_switch)`` line in the REPL header.
    """
    try:
        target = _settings_model_target(loop)
        if target is None:
            return False
        await loop.update_model_async(target, reason="drift_sync")
        return True
    except Exception:
        log.debug("Model drift check failed", exc_info=True)
    return False


def drift_target_is_healthy(loop: AgenticLoop, target_model: str) -> bool:
    """Return False if no profile in target_model's provider can serve a call.

    Uses ProfileRotator.resolve to mirror the actual selection path the
    next LLM call would take. None ⇒ all profiles missing/cooled-down/
    disabled. We refuse the drift rather than silently swap to a model
    the next call cannot fulfil.
    """
    try:
        target_provider = _resolve_provider(target_model)
        from core.wiring.container import get_profile_rotator

        rotator = get_profile_rotator()
        if rotator is None:
            # Rotator not initialised yet (early bootstrap) — accept drift.
            return True
        return rotator.resolve(target_provider) is not None
    except Exception:
        log.debug("Drift health check failed for %s", target_model, exc_info=True)
        # On any introspection failure, accept the drift to avoid
        # blocking legitimate user-initiated /model switches.
        return True


def _apply_model_update(
    loop: AgenticLoop,
    model: str,
    provider: str | None = None,
) -> tuple[str, bool]:
    """Apply model/provider mutation and return ``(old_model, changed)``."""
    old_model = loop.model
    new_provider = provider or _resolve_provider(model)
    if new_provider != loop._provider:
        loop._provider = new_provider
        loop._adapter = _resolve_agentic_adapter(new_provider)
    loop.model = model
    loop._tool_processor._model = model
    if old_model != model:
        loop._prompt_dirty = True

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
    purged = loop._purge_stale_model_switch_acks()
    loop.context.add_user_message(
        f"[system] Model switched: {old_model} -> {model}. "
        "You are now the new model. Do not reference the previous "
        "model's responses as current state."
    )
    loop.context.add_assistant_message(f"Understood. I am now {model}.")
    return purged


async def update_model_async(
    loop: AgenticLoop,
    model: str,
    provider: str | None = None,
    reason: str = "user_switch",
) -> None:
    """Async model update path used from ``AgenticLoop.arun``."""
    old_model, changed = _apply_model_update(loop, model, provider)
    if changed:
        from core.ui.agentic_ui import emit_model_switched

        emit_model_switched(old_model, model, reason)

        # PR-SIL-5THEME C5 (2026-05-23) — D4 X2 telemetry. breadcrumb +
        # stale-ack purge 가 끝난 *후* MODEL_SWITCHED 발화 → payload 에
        # purged_count 동봉 가능. 이전엔 trigger 가 breadcrumb 보다 먼저
        # 발화돼 purge 정보가 hook 에 안 들어갔다. operator 가
        # v0.52.5-style stale-ack 회귀를 stream 으로 추적 가능.
        purged_count = _inject_model_switch_breadcrumb(loop, old_model, model)

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

    # Proactively adapt context for the new model's context window
    loop._adapt_context_for_model(model)


def purge_stale_model_switch_acks(loop: AgenticLoop) -> int:
    """Remove prior ``Understood. I am now <prev_model>.`` assistant acks.

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
    ``Understood. I am now `` prefix we ourselves emit, in either
    representation. Never touches user content.

    PR-SIL-5THEME C5 (2026-05-23) — D4 X2 telemetry. Returns purged
    count so caller can forward to ``MODEL_SWITCHED`` hook payload.
    이전엔 silent — operator 가 stale-ack purge fire 여부 추적 불가
    (v0.52.5 같은 incident 의 회귀 발견이 매번 production debug 필요).
    Backward compat: 기존 caller 가 ``None`` 반환 가정한 경우 없음
    (이 함수는 caller 가 결과 무시했었음).
    """
    msgs = loop.context.messages
    prefix = "Understood. I am now "
    kept: list[Any] = []
    purged = 0
    for msg in msgs:
        if msg.get("role") != "assistant":
            kept.append(msg)
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and content.startswith(prefix):
            purged += 1
            continue
        if isinstance(content, list):
            # Block-form (Anthropic / multimodal): drop the message
            # when any text-block begins with our self-emitted prefix.
            text_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
            if any(
                isinstance(b.get("text"), str) and b["text"].startswith(prefix) for b in text_blocks
            ):
                purged += 1
                continue
        kept.append(msg)
    msgs.clear()
    msgs.extend(kept)
    return purged


def adapt_context_for_model(loop: AgenticLoop, target_model: str) -> None:
    """Proactively adapt conversation context when switching to a smaller model.

    Hybrid approach (Research 방안 E):
    Phase 1: Summarize large tool_result blocks (most effective)
    Phase 2: Token-aware adaptive pruning
    Phase 3: Log warning if still over budget (minimal mode)
    """
    from core.orchestration.context_monitor import (
        adaptive_prune,
        check_context,
        summarize_tool_results,
    )

    if loop.context.is_empty:
        return

    metrics = check_context(loop.context.messages, target_model)
    if not metrics.is_warning:
        return  # Under 80% — no adaptation needed

    original_tokens = metrics.estimated_tokens
    log.info(
        "Context adaptation: %.0f%% (%d/%d tokens) for %s",
        metrics.usage_pct,
        metrics.estimated_tokens,
        metrics.context_window,
        target_model,
    )

    # Phase 1: Summarize large tool results (preserves conversation structure)
    summarize_tool_results(loop.context.messages, metrics.context_window)

    # Phase 2: Token-aware pruning if still over budget
    metrics = check_context(loop.context.messages, target_model)
    if metrics.is_critical:
        pruned = adaptive_prune(loop.context.messages, metrics.context_window)
        loop.context.messages = pruned

    # Phase 3: Final check — log result
    metrics = check_context(loop.context.messages, target_model)
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
    """
    current = loop.model
    chain = list(getattr(loop._adapter, "fallback_chain", []) or [])
    if current in chain:
        idx = chain.index(current)
        return chain[idx + 1 :]
    return chain
