"""LLM fallback infrastructure — retry with backoff.

Shared by all providers (Anthropic, OpenAI, GLM).
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    # Module-level retry constants are exposed as ``MAX_RETRIES`` etc. for
    # backward compatibility (5+ external import sites). The values are
    # actually resolved lazily via ``__getattr__`` so module load no longer
    # forces a Settings instance — and therefore the heavy pydantic_settings
    # tree — into the cold-start path.
    MAX_RETRIES: int
    RETRY_BASE_DELAY: float
    RETRY_MAX_DELAY: float


def __getattr__(name: str) -> Any:
    if name in ("MAX_RETRIES", "RETRY_BASE_DELAY", "RETRY_MAX_DELAY"):
        from core.config import settings

        if name == "MAX_RETRIES":
            return settings.llm_max_retries
        if name == "RETRY_BASE_DELAY":
            return settings.llm_retry_base_delay
        return settings.llm_retry_max_delay
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


@dataclass
class StreamProgress:
    """Per-attempt replay-safety signal for streamed LLM calls.

    Replay-safety rule: a transient failure DURING streaming may be
    silently auto-retried (full re-call) only while no visible assistant
    output (text or tool-use delta) has been surfaced to a consumer.
    Once visible output has been emitted, a full re-call would duplicate
    the already-shown output — the retry boundary must raise
    :class:`core.llm.errors.StreamInterruptedError` instead and let the
    caller / session layer decide.

    Contract:

    - The stream consumer calls :meth:`note_delta` for every delta it
      surfaces. Only ``"text"`` / ``"tool_use"`` kinds count as visible
      (:class:`core.llm.adapters.base.StreamEvent` kind vocabulary);
      ``"thinking"`` / reasoning deltas are not user-visible output and
      never flip the flag.
    - The retry loop calls :meth:`reset` at the start of EVERY attempt,
      so the guard always reflects the attempt that just failed — never
      stale progress from a previous attempt or a previous call.
    """

    visible_output_emitted: bool = False
    partial_chars: int = 0

    _VISIBLE_KINDS: ClassVar[frozenset[str]] = frozenset({"text", "tool_use"})

    def note_delta(self, kind: str, chars: int = 0) -> None:
        """Record one surfaced stream delta (visible kinds only flip the flag)."""
        if kind in self._VISIBLE_KINDS:
            self.visible_output_emitted = True
            self.partial_chars += chars

    def reset(self) -> None:
        """Clear per-attempt state — called by the retry loop before each attempt."""
        self.visible_output_emitted = False
        self.partial_chars = 0


def _guard_stream_replay(
    stream_progress: StreamProgress | None,
    exc: Exception,
    *,
    provider_label: str,
    model: str,
) -> None:
    """Block a silent retry when the failed attempt already surfaced output.

    No-op when no progress signal is threaded (legacy buffered callers) or
    when the failed attempt emitted nothing visible. Otherwise raises
    ``StreamInterruptedError`` chaining ``exc`` — replay-unsafe boundary.
    """
    if stream_progress is None or not stream_progress.visible_output_emitted:
        return
    from core.llm.errors import StreamInterruptedError

    log.error(
        "%s stream died mid-output (model=%s, %d visible chars already surfaced) "
        "— auto-retry suppressed to avoid duplicating shown output",
        provider_label,
        model,
        stream_progress.partial_chars,
    )
    raise StreamInterruptedError(
        f"{provider_label} stream interrupted after visible output was surfaced "
        f"({stream_progress.partial_chars} chars); auto-retry suppressed as "
        f"replay-unsafe. Original error: {type(exc).__name__}: {exc}",
        visible_output_emitted=True,
        partial_chars=stream_progress.partial_chars,
    ) from exc


def _is_auth_error(exc: Exception) -> bool:
    """Check if exception is an authentication/401 error from any provider."""
    try:
        import anthropic

        if isinstance(exc, anthropic.AuthenticationError):
            return True
    except ImportError:
        pass
    # OpenAI AuthenticationError
    exc_name = type(exc).__name__
    return exc_name == "AuthenticationError" or "401" in str(exc)[:50]


def _try_oauth_refresh(provider_label: str) -> bool:
    """Attempt OAuth token refresh for managed profiles + reset clients.

    Returns True if a token was refreshed and clients were reset.
    """
    try:
        from core.wiring.container import get_profile_rotator

        rotator = get_profile_rotator()
        if not rotator:
            return False

        provider = "anthropic" if "LLM" in provider_label else "openai"
        profile = rotator.resolve(provider)
        if not profile or not profile.managed_by:
            return False

        # claude-code OAuth disabled (Anthropic ToS violation)
        if profile.managed_by == "codex-cli":
            from core.auth.codex_cli_oauth import (
                refresh_codex_cli_token,
            )
            from core.llm.providers.openai import reset_openai_client

            if refresh_codex_cli_token(profile):
                reset_openai_client()
                return True
    except Exception as exc:
        log.debug("OAuth refresh failed: %s", exc)
    return False


def _resolve_rotator_provider(provider_label: str) -> str:
    """Map provider_label (e.g. 'LLM', 'OpenAI', 'GLM') to rotator provider name."""
    label = provider_label.lower()
    if label in ("llm", "anthropic"):
        return "anthropic"
    if label in ("openai",):
        return "openai"
    if label in ("glm", "zhipuai"):
        return "glm"
    return label


def _notify_success(provider: str) -> None:
    """Notify ProfileRotator of LLM call success (non-blocking)."""
    try:
        from core.llm.credentials import notify_llm_success

        notify_llm_success(provider)
    except Exception:
        log.debug("Profile notify_success failed for %s", provider, exc_info=True)


def _notify_failure(provider: str, exc: Exception) -> None:
    """Notify ProfileRotator of LLM call failure (non-blocking)."""
    try:
        from core.llm.credentials import notify_llm_failure

        notify_llm_failure(provider, exc)
    except Exception:
        log.debug("Profile notify_failure failed for %s", provider, exc_info=True)


def _resolve_plan_for_billing_error(model: str) -> dict[str, str]:
    """Resolve Plan metadata for a model so BillingError carries context.

    v0.53.0 — used to render plan-aware quota-exhausted panels. Returns
    ``provider``, ``plan_id``, ``plan_display_name``, ``upgrade_url``.
    Empty values when routing fails (caller falls back to generic msg).
    """
    try:
        from core.llm.strategies.plan_registry import resolve_routing

        target = resolve_routing(model)
        if target is None:
            return {}
        plan = target.plan
        return {
            "provider": plan.provider,
            "plan_id": plan.id,
            "plan_display_name": plan.display_name,
            "upgrade_url": plan.upgrade_url or "",
        }
    except Exception:
        log.debug("Plan resolution for billing error failed", exc_info=True)
        return {}


def retry_with_backoff_generic(
    fn: Any,
    *,
    model: str,
    fallback_models: list[str],
    retryable_errors: tuple[type[Exception], ...],
    bad_request_error: type[Exception] | None = None,
    billing_message: str = "API billing/credit error.",
    max_retries: int | None = None,
    retry_base_delay: float | None = None,
    retry_max_delay: float | None = None,
    provider_label: str = "LLM",
    on_retry: Any | None = None,
    stream_progress: StreamProgress | None = None,
) -> Any:
    """Generic retry with exponential backoff + model fallback.

    Shared by Anthropic (``_retry_with_backoff``) and OpenAI
    (``OpenAIAdapter._retry_with_backoff``) to eliminate DRY violation.

    Stage 1: Retry same model with exponential backoff.
    Stage 2: On persistent failure, try fallback models.

    Args:
        fn: Callable accepting ``model`` keyword argument.
        model: Primary model name.
        fallback_models: Ordered fallback model chain.
        retryable_errors: Tuple of exception types that trigger retry.
        bad_request_error: Exception type for bad-request errors (e.g.
            ``anthropic.BadRequestError``, ``openai.BadRequestError``).
            If None, bad-request handling is skipped.
        billing_message: Error message for billing/credit errors.
        max_retries: Per-model retry count.
        retry_base_delay: Base delay in seconds.
        retry_max_delay: Max delay cap in seconds.
        provider_label: Label for log messages (e.g. "LLM", "OpenAI").
        stream_progress: Optional replay-safety signal for callers whose
            ``fn`` surfaces stream deltas to a consumer mid-call. Reset
            before every attempt; when the attempt that just failed had
            emitted visible output, the transient is NOT retried —
            ``StreamInterruptedError`` is raised instead (see
            :class:`StreamProgress`). ``None`` (all current callers,
            which buffer the full response inside ``fn``) keeps the
            legacy always-retry behavior.
    """
    models_to_try = [model] + [m for m in fallback_models if m != model]

    # Resolve None defaults from settings (function defaults stay lazy so the
    # cold-start path doesn't pull pydantic_settings).
    from core.config import settings as _cfg

    if max_retries is None:
        max_retries = _cfg.llm_max_retries
    if retry_base_delay is None:
        retry_base_delay = _cfg.llm_retry_base_delay
    if retry_max_delay is None:
        retry_max_delay = _cfg.llm_retry_max_delay

    # C2: filter out fallback models that exceed cost ratio limit
    if _cfg.llm_max_fallback_cost_ratio > 0 and len(models_to_try) > 1:
        from core.llm.token_tracker import MODEL_PRICING

        primary_price = MODEL_PRICING.get(model)
        if primary_price and primary_price.input > 0:
            filtered = [model]
            for fb_model in models_to_try[1:]:
                fb_price = MODEL_PRICING.get(fb_model)
                if fb_price and fb_price.input > 0:
                    ratio = fb_price.input / primary_price.input
                    if ratio > _cfg.llm_max_fallback_cost_ratio:
                        log.warning(
                            "C2: fallback %s→%s cost ratio %.1fx exceeds limit %.1fx — skipping",
                            model,
                            fb_model,
                            ratio,
                            _cfg.llm_max_fallback_cost_ratio,
                        )
                        continue
                filtered.append(fb_model)
            models_to_try = filtered

    last_error: Exception | None = None
    t0_retry = time.monotonic()

    # Resolve provider name for rotator notification (strip "LLM"/"OpenAI" labels)
    _provider_for_rotator = _resolve_rotator_provider(provider_label)

    for model_idx, current_model in enumerate(models_to_try):
        for attempt in range(max_retries):
            if stream_progress is not None:
                # New attempt — the guard must reflect only the attempt
                # that is about to run, never a previous attempt's output.
                stream_progress.reset()
            try:
                result = fn(model=current_model)
                _notify_success(_provider_for_rotator)
                return result
            except retryable_errors as exc:
                # v0.52.2 — short-circuit billing-fatal errors. RateLimitError
                # with code=1113 (GLM "Insufficient balance") or
                # insufficient_quota (OpenAI) cannot be cured by waiting; the
                # 5×exp-backoff retry loop wastes ~40s per failure across all
                # fallback models for an error that needs user action.
                from core.llm.errors import (
                    BillingError,
                    extract_billing_message,
                    is_billing_fatal,
                )

                if is_billing_fatal(exc):
                    msg = extract_billing_message(exc)
                    log.error(
                        "Billing-fatal error on %s (model=%s) — no retry: %s",
                        provider_label,
                        current_model,
                        msg,
                    )
                    # v0.53.0 — attach plan context so the UI can render a
                    # plan-aware quota-exhausted panel.
                    plan_meta = _resolve_plan_for_billing_error(current_model)
                    raise BillingError(
                        msg or billing_message,
                        provider=plan_meta.get("provider", ""),
                        plan_id=plan_meta.get("plan_id", ""),
                        plan_display_name=plan_meta.get("plan_display_name", ""),
                        upgrade_url=plan_meta.get("upgrade_url", ""),
                    ) from exc
                # Replay-safety boundary — a transient that killed the
                # stream AFTER visible output was surfaced must not be
                # silently re-called (duplicate output). Raises
                # StreamInterruptedError; no-op for buffered callers.
                _guard_stream_replay(
                    stream_progress, exc, provider_label=provider_label, model=current_model
                )
                last_error = exc
                delay = random.uniform(0, min(retry_base_delay * (2**attempt), retry_max_delay))
                elapsed = time.monotonic() - t0_retry
                log.warning(
                    "%s call failed (model=%s, attempt=%d/%d): %s. Retrying in %.1fs",
                    provider_label,
                    current_model,
                    attempt + 1,
                    max_retries,
                    type(exc).__name__,
                    delay,
                )
                if on_retry is not None:
                    import contextlib

                    with contextlib.suppress(Exception):
                        on_retry(
                            model=current_model,
                            attempt=attempt + 1,
                            max_retries=max_retries,
                            delay_s=delay,
                            elapsed_s=elapsed,
                            error_type=type(exc).__name__,
                        )
                time.sleep(delay)
            except Exception as exc:
                if bad_request_error is not None and isinstance(exc, bad_request_error):
                    # v0.52.6 — short-circuit "Unsupported parameter" /
                    # "Invalid value" 400-class errors. Same backend will
                    # reject every retry with the same body. Re-raise so
                    # the outer except (non-retryable_errors) catches and
                    # surfaces the original message.
                    from core.llm.errors import is_request_fatal

                    if is_request_fatal(exc):
                        log.error(
                            "Request-fatal 400 on %s (model=%s) — no retry: %s",
                            provider_label,
                            current_model,
                            str(exc)[:200],
                        )
                        raise
                    error_msg = str(exc)
                    if "billing" in error_msg.lower() or "credit" in error_msg.lower():
                        from core.llm.errors import BillingError

                        raise BillingError(billing_message) from exc
                    if any(
                        k in error_msg.lower()
                        for k in ("token", "context", "prompt exceeds", "max length")
                    ):
                        log.error(
                            "Context overflow detected (model=%s): %s",
                            current_model,
                            error_msg,
                        )
                # C1+C2: OAuth 401 auto-refresh — re-read token + reset client + 1 retry
                if _is_auth_error(exc) and attempt == 0:
                    refreshed = _try_oauth_refresh(provider_label)
                    if refreshed:
                        # Same replay-safety boundary as the transient
                        # branch — the refresh retry is also a full
                        # re-call of an attempt that may have surfaced
                        # visible output.
                        _guard_stream_replay(
                            stream_progress,
                            exc,
                            provider_label=provider_label,
                            model=current_model,
                        )
                        log.info(
                            "OAuth token refreshed for %s, retrying",
                            provider_label,
                        )
                        continue  # retry with refreshed token
                raise

        if model_idx < len(models_to_try) - 1:
            next_model = models_to_try[model_idx + 1]
            log.warning(
                "All retries exhausted for model=%s. Falling back to %s",
                current_model,
                next_model,
            )

    if last_error is None:
        raise RuntimeError("All retries exhausted with no error recorded")
    _notify_failure(_provider_for_rotator, last_error)
    log.error("All %s models and retries exhausted. Last error: %s", provider_label, last_error)
    raise last_error


async def retry_with_backoff_generic_async(
    fn: Any,
    *,
    model: str,
    fallback_models: list[str],
    retryable_errors: tuple[type[Exception], ...],
    bad_request_error: type[Exception] | None = None,
    billing_message: str = "API billing/credit error.",
    max_retries: int | None = None,
    retry_base_delay: float | None = None,
    retry_max_delay: float | None = None,
    provider_label: str = "LLM",
    on_retry: Any | None = None,
    stream_progress: StreamProgress | None = None,
) -> Any:
    """Async retry with exponential backoff + model fallback.

    Same contract as :func:`retry_with_backoff_generic`, including the
    ``stream_progress`` replay-safety boundary (see :class:`StreamProgress`).
    """
    models_to_try = [model] + [m for m in fallback_models if m != model]

    from core.config import settings as _cfg

    if max_retries is None:
        max_retries = _cfg.llm_max_retries
    if retry_base_delay is None:
        retry_base_delay = _cfg.llm_retry_base_delay
    if retry_max_delay is None:
        retry_max_delay = _cfg.llm_retry_max_delay

    if _cfg.llm_max_fallback_cost_ratio > 0 and len(models_to_try) > 1:
        from core.llm.token_tracker import MODEL_PRICING

        primary_price = MODEL_PRICING.get(model)
        if primary_price and primary_price.input > 0:
            filtered = [model]
            for fb_model in models_to_try[1:]:
                fb_price = MODEL_PRICING.get(fb_model)
                if fb_price and fb_price.input > 0:
                    ratio = fb_price.input / primary_price.input
                    if ratio > _cfg.llm_max_fallback_cost_ratio:
                        log.warning(
                            "C2: fallback %s→%s cost ratio %.1fx exceeds limit %.1fx — skipping",
                            model,
                            fb_model,
                            ratio,
                            _cfg.llm_max_fallback_cost_ratio,
                        )
                        continue
                filtered.append(fb_model)
            models_to_try = filtered

    last_error: Exception | None = None
    t0_retry = time.monotonic()
    _provider_for_rotator = _resolve_rotator_provider(provider_label)

    for model_idx, current_model in enumerate(models_to_try):
        for attempt in range(max_retries):
            if stream_progress is not None:
                # New attempt — the guard must reflect only the attempt
                # that is about to run, never a previous attempt's output.
                stream_progress.reset()
            try:
                result = await fn(model=current_model)
                _notify_success(_provider_for_rotator)
                return result
            except retryable_errors as exc:
                from core.llm.errors import (
                    BillingError,
                    extract_billing_message,
                    is_billing_fatal,
                )

                if is_billing_fatal(exc):
                    msg = extract_billing_message(exc)
                    log.error(
                        "Billing-fatal error on %s (model=%s) — no retry: %s",
                        provider_label,
                        current_model,
                        msg,
                    )
                    plan_meta = _resolve_plan_for_billing_error(current_model)
                    raise BillingError(
                        msg or billing_message,
                        provider=plan_meta.get("provider", ""),
                        plan_id=plan_meta.get("plan_id", ""),
                        plan_display_name=plan_meta.get("plan_display_name", ""),
                        upgrade_url=plan_meta.get("upgrade_url", ""),
                    ) from exc
                # Replay-safety boundary — see the sync variant above.
                _guard_stream_replay(
                    stream_progress, exc, provider_label=provider_label, model=current_model
                )
                last_error = exc
                delay = random.uniform(0, min(retry_base_delay * (2**attempt), retry_max_delay))
                elapsed = time.monotonic() - t0_retry
                log.warning(
                    "%s async call failed (model=%s, attempt=%d/%d): %s. Retrying in %.1fs",
                    provider_label,
                    current_model,
                    attempt + 1,
                    max_retries,
                    type(exc).__name__,
                    delay,
                )
                if on_retry is not None:
                    import contextlib

                    with contextlib.suppress(Exception):
                        on_retry(
                            model=current_model,
                            attempt=attempt + 1,
                            max_retries=max_retries,
                            delay_s=delay,
                            elapsed_s=elapsed,
                            error_type=type(exc).__name__,
                        )
                await asyncio.sleep(delay)
            except Exception as exc:
                if bad_request_error is not None and isinstance(exc, bad_request_error):
                    from core.llm.errors import is_request_fatal

                    if is_request_fatal(exc):
                        log.error(
                            "Request-fatal 400 on %s (model=%s) — no retry: %s",
                            provider_label,
                            current_model,
                            str(exc)[:200],
                        )
                        raise
                    error_msg = str(exc)
                    if "billing" in error_msg.lower() or "credit" in error_msg.lower():
                        from core.llm.errors import BillingError

                        raise BillingError(billing_message) from exc
                    if any(
                        k in error_msg.lower()
                        for k in ("token", "context", "prompt exceeds", "max length")
                    ):
                        log.error(
                            "Context overflow detected (model=%s): %s",
                            current_model,
                            error_msg,
                        )
                if _is_auth_error(exc) and attempt == 0:
                    refreshed = _try_oauth_refresh(provider_label)
                    if refreshed:
                        # Same replay-safety boundary as the transient branch.
                        _guard_stream_replay(
                            stream_progress,
                            exc,
                            provider_label=provider_label,
                            model=current_model,
                        )
                        log.info("OAuth token refreshed for %s, retrying", provider_label)
                        continue
                raise

        if model_idx < len(models_to_try) - 1:
            next_model = models_to_try[model_idx + 1]
            log.warning(
                "All async retries exhausted for model=%s. Falling back to %s",
                current_model,
                next_model,
            )

    if last_error is None:
        raise RuntimeError("All retries exhausted with no error recorded")
    _notify_failure(_provider_for_rotator, last_error)
    log.error(
        "All %s models and async retries exhausted. Last error: %s",
        provider_label,
        last_error,
    )
    raise last_error
