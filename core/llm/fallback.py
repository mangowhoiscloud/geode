"""LLM fallback infrastructure — retry with backoff.

Shared by all providers (Anthropic, OpenAI, GLM).
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

log = logging.getLogger(__name__)


class RetryAction(StrEnum):
    """What the shared retry substrate should do with one classified error."""

    RETRY = "retry"
    NEXT_MODEL = "next_model"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Explicit call-site retry behavior over the shared LLM taxonomy."""

    name: str
    max_attempts: int
    base_delay_s: float
    max_delay_s: float
    jitter: bool
    retry_categories: frozenset[str]
    terminal_categories: frozenset[str]
    next_model_categories: frozenset[str] = frozenset()
    filter_models: bool = True
    fallback_after_exhaustion: bool = False
    refresh_auth_once: bool = False
    sleep_after_final_failure: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("retry policy name is empty")
        if self.max_attempts < 1:
            raise ValueError("retry policy max_attempts must be positive")
        if self.base_delay_s < 0 or self.max_delay_s < self.base_delay_s:
            raise ValueError("retry policy delay bounds are invalid")
        category_sets = (
            self.retry_categories,
            self.terminal_categories,
            self.next_model_categories,
        )
        overlap = (
            (category_sets[0] & category_sets[1])
            | (category_sets[0] & category_sets[2])
            | (category_sets[1] & category_sets[2])
        )
        if overlap:
            raise ValueError(f"retry policy has conflicting categories: {sorted(overlap)}")

    def action_for(self, error_type: str) -> RetryAction:
        if error_type in self.terminal_categories:
            return RetryAction.TERMINAL
        if error_type in self.retry_categories:
            return RetryAction.RETRY
        if error_type in self.next_model_categories:
            return RetryAction.NEXT_MODEL
        return RetryAction.TERMINAL

    def delay_for(self, failure_number: int) -> float:
        """Return the delay after a one-based failure number."""
        if failure_number < 1:
            raise ValueError("failure_number must be positive")
        ceiling = min(self.base_delay_s * (2 ** (failure_number - 1)), self.max_delay_s)
        return random.uniform(0, ceiling) if self.jitter else ceiling


@dataclass(frozen=True, slots=True)
class RetryAttempt:
    """One normalized retry event shared by hooks and activity sinks."""

    policy: str
    model: str
    error_type: str
    classification: str
    attempt: int
    max_attempts: int
    delay_s: float
    elapsed_s: float | None

    def payload(self) -> dict[str, Any]:
        payload = {
            "retry_policy": self.policy,
            "model": self.model,
            "exception_type": self.error_type,
            "classification": self.classification,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "delay_s": self.delay_s,
        }
        if self.elapsed_s is not None:
            payload["elapsed_s"] = self.elapsed_s
        return payload


@dataclass(frozen=True, slots=True)
class RetryOutcome[T]:
    """Success or exhaustion from :func:`run_with_retry_policy`."""

    succeeded: bool
    value: T | None
    model: str | None
    last_error: Exception | None = None


_TERMINAL_ERRORS = frozenset(
    {"auth", "bad_request", "billing", "context_overflow", "stream_interrupted"}
)
_TRANSIENT_ERRORS = frozenset({"connection", "rate_limit", "server", "timeout"})


def interactive_retry_policy(*, max_attempts: int = 5) -> RetryPolicy:
    """Operator-facing retry: quota is terminal and there is no model fallback."""
    return RetryPolicy(
        name="interactive",
        max_attempts=max_attempts,
        base_delay_s=2.0,
        max_delay_s=30.0,
        jitter=False,
        retry_categories=frozenset({"connection", "server", "timeout", "unknown"}),
        terminal_categories=_TERMINAL_ERRORS | {"rate_limit"},
    )


def auxiliary_retry_policy(
    *,
    max_attempts: int | None = None,
    base_delay_s: float | None = None,
    max_delay_s: float | None = None,
) -> RetryPolicy:
    """Unattended retry: bounded jittered backoff and opt-in model-chain traversal."""
    from core.config import settings

    return RetryPolicy(
        name="auxiliary",
        max_attempts=max_attempts if max_attempts is not None else settings.llm_max_retries,
        base_delay_s=(base_delay_s if base_delay_s is not None else settings.llm_retry_base_delay),
        max_delay_s=max_delay_s if max_delay_s is not None else settings.llm_retry_max_delay,
        jitter=True,
        retry_categories=_TRANSIENT_ERRORS,
        terminal_categories=_TERMINAL_ERRORS,
        next_model_categories=frozenset({"unknown"}),
        fallback_after_exhaustion=True,
    )


def provider_retry_policy(
    *,
    max_attempts: int | None = None,
    base_delay_s: float | None = None,
    max_delay_s: float | None = None,
) -> RetryPolicy:
    """Provider compatibility retry with OAuth and legacy final sleep."""
    from core.config import settings

    return RetryPolicy(
        name="provider",
        max_attempts=max_attempts if max_attempts is not None else settings.llm_max_retries,
        base_delay_s=(base_delay_s if base_delay_s is not None else settings.llm_retry_base_delay),
        max_delay_s=max_delay_s if max_delay_s is not None else settings.llm_retry_max_delay,
        jitter=True,
        retry_categories=_TRANSIENT_ERRORS,
        terminal_categories=_TERMINAL_ERRORS,
        filter_models=False,
        fallback_after_exhaustion=True,
        refresh_auth_once=True,
        sleep_after_final_failure=True,
    )


if TYPE_CHECKING:
    from core.llm.errors import BillingError

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

        # Only GEODE-managed Codex profiles have a refresh operation here.
        if profile.managed_by == "codex-cli":
            from core.auth.codex_cli_oauth import (
                refresh_codex_cli_token,
            )
            from core.llm.adapters.registry import invalidate_provider_clients

            if refresh_codex_cli_token(profile):
                # Live path is the adapter cache (the providers/ sync client
                # this used to reset was deleted 2026-07-29 as dead code).
                invalidate_provider_clients("openai")
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


def _resolve_plan_for_billing_error(
    model: str,
    *,
    routing_sources: Any | None = None,
) -> dict[str, str]:
    """Resolve Plan metadata for a model so BillingError carries context.

    v0.53.0 — used to render plan-aware quota-exhausted panels. Returns
    ``provider``, ``plan_id``, ``plan_display_name``, ``upgrade_url``.
    Empty values when routing fails (caller falls back to generic msg).
    """
    try:
        from core.llm.strategies.plan_registry import resolve_routing

        target = resolve_routing(model, sources=routing_sources)
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


CONNECTION_TRANSIENT_ERROR_NAMES: frozenset[str] = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "ReadError",
        "ReadTimeout",
        "WriteError",
        "RemoteProtocolError",
    }
)


def exception_chain(exc: BaseException, *, limit: int = 4) -> list[BaseException]:
    """Return a short, cycle-safe cause/context chain."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(chain) < limit:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def is_connection_transient(exc: Exception) -> bool:
    """Return whether a non-billing error chain is connection-class transient."""
    from core.llm.errors import BillingError, is_billing_fatal

    chain = exception_chain(exc)
    for link in chain:
        if isinstance(link, BillingError):
            return False
        if isinstance(link, Exception) and is_billing_fatal(link):
            return False
    return any(type(link).__name__ in CONNECTION_TRANSIENT_ERROR_NAMES for link in chain)


def classify_retry_error(
    exc: Exception,
    *,
    compatibility_retryable_errors: tuple[type[Exception], ...] = (),
    compatibility_bad_request_error: type[Exception] | None = None,
) -> str:
    """Project provider exceptions onto the single retry classification alphabet."""
    from core.llm.errors import (
        BillingError,
        classify_llm_error,
        is_billing_fatal,
        is_request_fatal,
    )

    if any(
        isinstance(link, BillingError) or (isinstance(link, Exception) and is_billing_fatal(link))
        for link in exception_chain(exc)
    ):
        return "billing"
    if _is_auth_error(exc):
        return "auth"
    if is_request_fatal(exc):
        return "bad_request"
    if (
        compatibility_bad_request_error is not None
        and isinstance(exc, compatibility_bad_request_error)
        and any(marker in str(exc).lower() for marker in ("billing", "credit"))
    ):
        return "billing"
    classified, _severity, _hint = classify_llm_error(exc)
    if classified != "unknown":
        return classified
    if is_connection_transient(exc):
        return "connection"
    status = getattr(exc, "status_code", None)
    if status == 429:
        return "rate_limit"
    if isinstance(status, int) and status >= 500:
        return "server"
    if compatibility_bad_request_error is not None and isinstance(
        exc, compatibility_bad_request_error
    ):
        return "bad_request"
    if (
        classified == "unknown"
        and compatibility_retryable_errors
        and isinstance(exc, compatibility_retryable_errors)
    ):
        return "server"
    return classified


def billing_error_from_exception(
    exc: Exception,
    *,
    model: str,
    message: str,
    routing_sources: Any | None,
) -> BillingError:
    from core.llm.errors import BillingError, extract_billing_message

    plan_meta = _resolve_plan_for_billing_error(model, routing_sources=routing_sources)
    return BillingError(
        extract_billing_message(exc) or message,
        provider=plan_meta.get("provider", ""),
        plan_id=plan_meta.get("plan_id", ""),
        plan_display_name=plan_meta.get("plan_display_name", ""),
        upgrade_url=plan_meta.get("upgrade_url", ""),
    )


async def run_with_retry_policy(
    models: list[str],
    call_fn: Any,
    *,
    policy: RetryPolicy,
    provider_label: str = "LLM",
    billing_message: str = "API billing/credit error.",
    on_retry: Any | None = None,
    stream_progress: StreamProgress | None = None,
    routing_sources: Any | None = None,
    compatibility_retryable_errors: tuple[type[Exception], ...] = (),
    compatibility_bad_request_error: type[Exception] | None = None,
    refresh_auth: Any | None = None,
) -> RetryOutcome[Any]:
    """Run one model chain on an explicit policy and shared taxonomy."""
    from core.config import is_model_allowed

    allowed_models = (
        [model for model in models if is_model_allowed(model)] if policy.filter_models else models
    )
    if not allowed_models:
        log.error("Retry policy %s: all models blocked: %s", policy.name, models)
        return RetryOutcome(False, None, None)

    last_error: Exception | None = None
    started_at = time.monotonic()
    for model_index, current_model in enumerate(allowed_models):
        advance_model = False
        for attempt_index in range(policy.max_attempts):
            if stream_progress is not None:
                stream_progress.reset()
            try:
                return RetryOutcome(True, await call_fn(current_model), current_model)
            except Exception as exc:
                from core.llm.errors import BillingError

                if isinstance(exc, BillingError):
                    raise
                classification = classify_retry_error(
                    exc,
                    compatibility_retryable_errors=compatibility_retryable_errors,
                    compatibility_bad_request_error=compatibility_bad_request_error,
                )
                if classification == "billing":
                    raise billing_error_from_exception(
                        exc,
                        model=current_model,
                        message=billing_message,
                        routing_sources=routing_sources,
                    ) from exc
                if classification == "auth" and policy.refresh_auth_once and attempt_index == 0:
                    refresh = refresh_auth or (lambda: _try_oauth_refresh(provider_label))
                    if refresh():
                        _guard_stream_replay(
                            stream_progress,
                            exc,
                            provider_label=provider_label,
                            model=current_model,
                        )
                        log.info("OAuth token refreshed for %s, retrying", provider_label)
                        continue

                action = policy.action_for(classification)
                if action is RetryAction.TERMINAL:
                    raise
                last_error = exc
                if action is RetryAction.NEXT_MODEL:
                    advance_model = True
                    break

                _guard_stream_replay(
                    stream_progress,
                    exc,
                    provider_label=provider_label,
                    model=current_model,
                )
                failure_number = attempt_index + 1
                delay = policy.delay_for(failure_number)
                event = RetryAttempt(
                    policy=policy.name,
                    model=current_model,
                    error_type=type(exc).__name__,
                    classification=classification,
                    attempt=failure_number,
                    max_attempts=policy.max_attempts,
                    delay_s=delay,
                    elapsed_s=time.monotonic() - started_at,
                )
                log.warning(
                    "%s call failed (model=%s, attempt=%d/%d, class=%s): %s; retry in %.1fs",
                    provider_label,
                    current_model,
                    failure_number,
                    policy.max_attempts,
                    classification,
                    type(exc).__name__,
                    delay,
                )
                if on_retry is not None:
                    try:
                        on_retry(event)
                    except Exception:
                        log.debug("Retry telemetry callback failed", exc_info=True)
                if attempt_index < policy.max_attempts - 1 or policy.sleep_after_final_failure:
                    await asyncio.sleep(delay)
                if attempt_index == policy.max_attempts - 1:
                    advance_model = policy.fallback_after_exhaustion

        if not advance_model:
            break
        if model_index < len(allowed_models) - 1:
            log.warning(
                "Retry policy %s exhausted model=%s; falling back to %s",
                policy.name,
                current_model,
                allowed_models[model_index + 1],
            )

    return RetryOutcome(False, None, None, last_error)


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
    routing_sources: Any | None = None,
) -> Any:
    """Compatibility wrapper over the canonical policy runner."""
    models_to_try = [model] + [m for m in fallback_models if m != model]

    from core.config import settings as _cfg

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

    policy = provider_retry_policy(
        max_attempts=max_retries,
        base_delay_s=retry_base_delay,
        max_delay_s=retry_max_delay,
    )

    async def _call(current_model: str) -> Any:
        return await fn(model=current_model)

    def _emit(event: RetryAttempt) -> None:
        if on_retry is None:
            return
        on_retry(
            model=event.model,
            attempt=event.attempt,
            max_retries=event.max_attempts,
            delay_s=event.delay_s,
            elapsed_s=event.elapsed_s,
            error_type=event.error_type,
        )

    outcome = await run_with_retry_policy(
        models_to_try,
        _call,
        policy=policy,
        provider_label=provider_label,
        billing_message=billing_message,
        on_retry=_emit,
        stream_progress=stream_progress,
        routing_sources=routing_sources,
        compatibility_retryable_errors=retryable_errors,
        compatibility_bad_request_error=bad_request_error,
    )
    provider = _resolve_rotator_provider(provider_label)
    if outcome.succeeded:
        _notify_success(provider)
        return outcome.value
    if outcome.last_error is None:
        raise RuntimeError("All retries exhausted with no error recorded")
    _notify_failure(provider, outcome.last_error)
    log.error(
        "All %s models and async retries exhausted. Last error: %s",
        provider_label,
        outcome.last_error,
    )
    raise outcome.last_error
