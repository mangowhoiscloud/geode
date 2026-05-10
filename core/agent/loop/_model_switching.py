"""Model drift sync, escalation, and per-model context adaptation.

Extracted from the monolithic ``core/agent/loop.py`` (Tier 3 #7). Each
function takes the ``AgenticLoop`` as the first parameter (``loop``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .loop import AgenticLoop

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


def sync_model_from_settings(loop: AgenticLoop) -> bool:
    """Check if settings.model diverged and apply the change safely.

    Called at the top of each agentic round — between LLM calls, never
    mid-call.  This replaces the old pattern of calling update_model()
    from inside a tool handler, which swapped the adapter while the
    current round was still processing tool results.

    v0.52.2 — refuse the drift if the target provider has no eligible
    profile. Prior shape would silently overwrite the loop's chosen
    model with a stale settings value pointing at an exhausted
    provider (e.g. just-registered Codex Plus → drift back to GLM
    without quota → 5×4=20 retry storm). Pattern from OpenClaw
    ``evaluate_eligibility`` + ``_LAST_VERDICTS`` cached health view.

    Returns True if the model was changed (caller should rebuild
    system_prompt), False otherwise.
    """
    try:
        from core.config import settings

        if settings.model == loop.model:
            return False
        if not loop._drift_target_is_healthy(settings.model):
            log.warning(
                "Model drift refused: target=%s has no eligible profile — "
                "keeping loop=%s. Run `/login use <plan>` to enable target.",
                settings.model,
                loop.model,
            )
            return False
        log.info(
            "Model drift detected: loop=%s settings=%s — syncing",
            loop.model,
            settings.model,
        )
        loop.update_model(settings.model)
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


def update_model(
    loop: AgenticLoop,
    model: str,
    provider: str | None = None,
    reason: str = "user_switch",
) -> None:
    """Update model and provider without reconstructing the loop.

    Resolves a fresh adapter when the provider changes. Within the
    same provider, the adapter is reused (it owns its own client).
    Also syncs the SessionMeter so status lines show the correct model.

    v0.52.5 — sets ``self._prompt_dirty = True`` whenever the model
    changes so the run-loop rebuilds the system prompt before the
    next LLM call. Without this, a sync that does not go through
    ``_sync_model_from_settings()`` would leave the system prompt's
    model card pinned to the previous model.

    v0.90.0 — the only callers of ``update_model`` are now the
    settings drift sync + the user-facing ``/model`` command;
    auto-escalation paths were removed.
    """
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

    # Fire MODEL_SWITCHED hook + IPC event for observability
    if old_model != model:
        from core.ui.agentic_ui import emit_model_switched

        emit_model_switched(old_model, model, reason)
        if loop._hooks:
            from core.hooks import HookEvent

            loop._hooks.trigger(
                HookEvent.MODEL_SWITCHED,
                {
                    "from_model": old_model,
                    "to_model": model,
                    "reason": reason,
                },
            )

        # Inject model-switch breadcrumb so the new model knows the switch
        # happened (Claude Code SDK pattern: createModelSwitchBreadcrumbs).
        if not loop.context.is_empty:
            # v0.52.8 — strip stale "Understood. I am now <prev>" acks
            # left by earlier model switches in the same session. Without
            # this, the new model reads "I am gpt-5.4-mini" assistant
            # messages and asserts the wrong identity (production
            # incident 2026-04-27 — gpt-5.5 answered "I am gpt-5.4-mini").
            loop._purge_stale_model_switch_acks()
            loop.context.add_user_message(
                f"[system] Model switched: {old_model} -> {model}. "
                "You are now the new model. Do not reference the previous "
                "model's responses as current state."
            )
            loop.context.add_assistant_message(f"Understood. I am now {model}.")

    # Proactively adapt context for the new model's context window
    loop._adapt_context_for_model(model)


def purge_stale_model_switch_acks(loop: AgenticLoop) -> None:
    """Remove prior ``Understood. I am now <prev_model>.`` assistant acks.

    v0.52.8 — added after a production incident where gpt-5.5 (post
    ``/model`` switch from gpt-5.4-mini) silently inherited the prior
    model's identity from a lingering history message. The OpenAI
    gpt-5.5 system card explicitly says it should identify as
    "GPT-5.5", so the bug was not model behaviour — it was our
    breadcrumb pollution. Each model switch should leave **only one**
    active "I am now <model>" ack at any time.

    Conservative: only matches the exact ``Understood. I am now ``
    prefix we ourselves emit; never touches user content. Mutates
    ``self.context.messages`` in place.
    """
    msgs = loop.context.messages
    prefix = "Understood. I am now "
    kept: list[Any] = []
    for msg in msgs:
        if msg.get("role") != "assistant":
            kept.append(msg)
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and content.startswith(prefix):
            continue
        kept.append(msg)
    msgs.clear()
    msgs.extend(kept)


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
