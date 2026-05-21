"""3-tier quota banner + abort dialog for GEODE's REPL.

PR-γ1 of the 2026-05-19 self-improving-loop config consolidation plan. Renders a
``bottom_toolbar`` callable that the prompt_toolkit ``PromptSession``
plumbs into the REPL frame. The banner colour reflects current
subscription quota usage against the
``[self_improving_loop] warn_threshold`` / ``abort_threshold`` from
:mod:`core.config.self_improving_loop`:

- **green**  — usage < warn_threshold (subscription healthy)
- **yellow** — warn ≤ usage < abort (approaching limit)
- **red**    — usage ≥ abort, *or* an abort was triggered (e.g. by a
  ``CredentialResolutionError(subscription_only=True)`` raised inside
  the runtime).

The abort dialog is a one-shot full-screen prompt_toolkit
``message_dialog`` rendered when strict-mode (PR-β1) refuses to fall
through to PAYG. Its body is the same Stripe-style actionable message
the resolver attached to the exception, so the operator sees the
remedy without paging through logs.

Refresh: the banner state is held in a thread-safe singleton; an
optional background helper (``QuotaBannerRefresher``) periodically
invokes ``app.invalidate()`` so the banner repaints even when the user
is idle (prompt_toolkit issue #277 pattern). Tests inject the
``invalidate`` callable so the prompt_toolkit dependency stays out of
the unit-test scope.

Reference: ``docs/plans/2026-05-19-self-improving-loop-config-consolidation.md``
Phase γ + frontier survey (Codex CLI status_line, Hermes TUI status bar).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

log = logging.getLogger(__name__)

__all__ = [
    "AbortDialog",
    "QuotaAbortError",
    "QuotaBannerRefresher",
    "QuotaState",
    "SubscriptionQuotaBanner",
    "current_banner",
    "render_abort_message",
]


class QuotaAbortError(RuntimeError):
    """Raised by :meth:`SubscriptionQuotaBanner.enforce_or_raise` when the
    banner is in aborted state — either from a credential-resolver trip
    or from automatic threshold breach (OL-P2).

    Callers that opt into the gate (`enforce_or_raise()` before the LLM
    call) get this exception; the existing call sites that do NOT call
    it stay backwards-compat. Keeps OL-P2 surface tight — operators flip
    enforcement on per-caller rather than getting a system-wide hard gate.
    """

    def __init__(self, *, provider: str, reason: str) -> None:
        super().__init__(f"quota aborted ({provider}): {reason}")
        self.provider = provider
        self.reason = reason


Tier = Literal["green", "yellow", "red"]


@dataclass(frozen=True)
class QuotaState:
    """Current subscription quota snapshot.

    Captures everything the banner needs to render. Updated by the
    runtime after each LLM call via :meth:`SubscriptionQuotaBanner.set_state`.

    ``aborted`` is True when a strict-mode resolution raised
    ``CredentialResolutionError(subscription_only=True)`` — the banner
    locks to red regardless of the usage ratio because no further LLM
    calls will succeed until the operator opts in or swaps account.
    """

    provider: str = ""
    used_tokens: int = 0
    total_tokens: int = 0
    aborted: bool = False
    abort_reason: str = ""

    @property
    def usage_ratio(self) -> float:
        """``used / total`` clamped to [0.0, 1.0]; 0 when total ≤ 0."""
        if self.total_tokens <= 0:
            return 0.0
        ratio = self.used_tokens / self.total_tokens
        if ratio < 0.0:
            return 0.0
        if ratio > 1.0:
            return 1.0
        return ratio


class SubscriptionQuotaBanner:
    """Thread-safe banner state holder + bottom_toolbar renderer.

    Lifecycle: one instance per REPL session, instantiated by
    ``core.cli.prompt_session`` when the session is created. Runtime
    code (LLM call wrapper, ``CredentialResolutionError`` handler)
    updates the state via :meth:`set_state` / :meth:`trip_abort`. The
    prompt_toolkit ``bottom_toolbar`` parameter binds to
    :meth:`render`.
    """

    def __init__(
        self,
        *,
        warn_threshold: float = 0.5,
        abort_threshold: float = 0.9,
    ) -> None:
        self._lock = threading.Lock()
        self._state = QuotaState()
        self._warn = warn_threshold
        self._abort = abort_threshold

    @property
    def state(self) -> QuotaState:
        """Snapshot of the current state (immutable dataclass)."""
        with self._lock:
            return self._state

    def set_state(
        self,
        *,
        provider: str,
        used_tokens: int,
        total_tokens: int,
    ) -> None:
        """Replace the quota counters. Auto-trips ``trip_abort`` when the
        new ratio crosses ``abort_threshold`` (OL-P2 — enforcement
        wiring). Otherwise preserves the existing ``aborted`` flag.
        """
        with self._lock:
            new_state = QuotaState(
                provider=provider,
                used_tokens=used_tokens,
                total_tokens=total_tokens,
                aborted=self._state.aborted,
                abort_reason=self._state.abort_reason,
            )
            # OL-P2 (2026-05-22) — actual enforcement on threshold
            # breach. Pre-OL-P2 the banner only DISPLAYED red when usage
            # crossed abort_threshold; the abort flag itself was only
            # set by credential-resolver. Now an actual usage breach
            # auto-trips so downstream call gates (and the bottom_toolbar
            # render) reflect the policy without operator intervention.
            ratio = new_state.usage_ratio
            if not new_state.aborted and ratio >= self._abort:
                new_state = QuotaState(
                    provider=provider,
                    used_tokens=used_tokens,
                    total_tokens=total_tokens,
                    aborted=True,
                    abort_reason=(
                        f"quota usage {ratio:.1%} >= abort_threshold {self._abort:.1%} ({provider})"
                    ),
                )
            self._state = new_state

    def trip_abort(self, *, reason: str) -> None:
        """Lock the banner to red until :meth:`clear_abort` is called.

        Called by the ``CredentialResolutionError(subscription_only=True)``
        handler. ``reason`` is the resolver's actionable message — the
        same string the abort dialog renders.
        """
        with self._lock:
            self._state = QuotaState(
                provider=self._state.provider,
                used_tokens=self._state.used_tokens,
                total_tokens=self._state.total_tokens,
                aborted=True,
                abort_reason=reason,
            )

    def clear_abort(self) -> None:
        """Reset the ``aborted`` flag after the operator resolves the cause
        (e.g. swapped account, opt-in to fallback, or upped subscription).
        """
        with self._lock:
            self._state = QuotaState(
                provider=self._state.provider,
                used_tokens=self._state.used_tokens,
                total_tokens=self._state.total_tokens,
                aborted=False,
                abort_reason="",
            )

    def enforce_or_raise(self) -> None:
        """OL-P2 opt-in call gate — raise :class:`QuotaAbortError` when
        the banner is in aborted state.

        Callers wrap the LLM call entry-point::

            try:
                current_banner() and current_banner().enforce_or_raise()
            except QuotaAbortError as exc:
                # surface the abort to the operator + skip the call
                ...

        Backwards-compat: existing call sites that do NOT call this gate
        continue working unchanged. The banner state stays purely
        visual for them. OL-P2 ships the gate as opt-in so per-channel
        rollout is possible (e.g., Petri auditor first, daemon REPL
        last, OAuth flow exempt).
        """
        state = self.state
        if state.aborted:
            raise QuotaAbortError(
                provider=state.provider or "unknown",
                reason=state.abort_reason or "no reason given",
            )

    def tier(self) -> Tier:
        """Compute the colour tier from the current state.

        Aborted state forces red. Otherwise compare usage ratio against
        the configured thresholds.
        """
        state = self.state
        if state.aborted:
            return "red"
        ratio = state.usage_ratio
        if ratio >= self._abort:
            return "red"
        if ratio >= self._warn:
            return "yellow"
        return "green"

    def render(self) -> str:
        """Return a prompt_toolkit HTML string for ``bottom_toolbar``.

        Format::

            ⬤ green   subscription healthy (12% used)
            ⬤ yellow  approaching limit (62% of <provider>)
            ⬤ red     aborted — see /status

        Renders empty string when no provider is set yet (cold start) so
        the banner doesn't flash an unconfigured state.
        """
        state = self.state
        if not state.provider and state.total_tokens == 0 and not state.aborted:
            return ""
        tier = self.tier()
        pct = round(state.usage_ratio * 100)
        if tier == "red":
            if state.aborted:
                return (
                    '<style fg="red" bg="black"> ⬤ </style>'
                    "<b> subscription aborted</b>"
                    " — see /status for resolution"
                )
            return (
                f'<style fg="red" bg="black"> ⬤ </style>'
                f"<b> {state.provider}: {pct}% used</b>"
                f" — abort threshold {int(self._abort * 100)}%"
            )
        if tier == "yellow":
            return (
                f'<style fg="yellow"> ⬤ </style>'
                f"{state.provider}: {pct}% used"
                f" — approaching {int(self._abort * 100)}% limit"
            )
        return f'<style fg="green"> ⬤ </style>{state.provider}: {pct}% used — healthy'


# Module-level singleton + ContextVar accessor.
_active_banner: SubscriptionQuotaBanner | None = None
_active_lock = threading.Lock()


def current_banner() -> SubscriptionQuotaBanner | None:
    """Return the banner active in this process, if any.

    Runtime code consults this to update quota state without having to
    pass the banner instance through every call site.
    """
    with _active_lock:
        return _active_banner


def _set_current_banner(banner: SubscriptionQuotaBanner | None) -> None:
    global _active_banner
    with _active_lock:
        _active_banner = banner


# ---------------------------------------------------------------------------
# Background refresh — prompt_toolkit issue #277 pattern
# ---------------------------------------------------------------------------


class QuotaBannerRefresher:
    """Background thread that periodically invalidates the prompt app.

    prompt_toolkit only repaints the ``bottom_toolbar`` on keystrokes by
    default. Quota state changes asynchronously (LLM call completes,
    resolver trips abort) so we need to schedule a repaint. Issue #277
    recommends a daemon thread + ``app.invalidate()`` at a fixed cadence.

    Tests inject ``invalidate`` and ``sleep`` callables so the threading
    + prompt_toolkit dependency stays out of unit-test scope.
    """

    def __init__(
        self,
        *,
        invalidate: Callable[[], None],
        interval_seconds: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._invalidate = invalidate
        self._interval = interval_seconds
        self._sleep = sleep
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Spawn the background daemon thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="quota-banner-refresher",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, join: bool = True, timeout: float = 1.0) -> None:
        """Signal the thread to exit. ``atexit`` / signal handler caller."""
        self._stop.set()
        if join and self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._invalidate()
            except Exception:
                log.warning("quota banner refresher invalidate raised", exc_info=True)
            self._sleep(self._interval)


# ---------------------------------------------------------------------------
# Abort dialog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AbortDialog:
    """Bundle of strings the operator sees when strict-mode aborts.

    Separated from the prompt_toolkit ``message_dialog`` call so the
    text is unit-testable without booting the full-screen app. The CLI
    integration layer is responsible for rendering this struct via
    ``prompt_toolkit.shortcuts.message_dialog``.
    """

    title: str
    body: str
    button_label: str = "Dismiss"


def render_abort_message(provider: str, resolver_message: str) -> AbortDialog:
    """Compose the abort dialog body from a strict-mode resolution error.

    ``resolver_message`` is :attr:`CredentialResolutionError.args[0]`
    when ``subscription_only=True`` — it already contains the 3
    actionable remedies (wait / opt-in fallback / pin per-role). The
    dialog wraps it with a title that names the offending provider.
    """
    return AbortDialog(
        title=f"Subscription quota exhausted — {provider}",
        body=resolver_message,
    )


# Installer used by core/cli/prompt_session.py
def install_banner(banner: SubscriptionQuotaBanner) -> None:
    """Bind ``banner`` as the process-wide active banner.

    Called once during REPL startup. Replaces any prior banner; the
    previous instance is left to garbage-collect after its refresher
    is stopped by the caller (REPL teardown does both).
    """
    _set_current_banner(banner)


def uninstall_banner() -> None:
    """Detach the active banner (used during REPL teardown / test cleanup).

    Also clears the Anthropic quota setter callback registered via
    :func:`core.llm.providers.anthropic.register_quota_setter` so a
    teardown test doesn't leave a dangling reference to the just-detached
    banner. Defensive import — anthropic SDK may not be loadable in
    every test environment.
    """
    _set_current_banner(None)
    try:
        from core.llm.providers.anthropic import register_quota_setter

        register_quota_setter(None)
    except Exception:  # pragma: no cover - defensive
        log.debug("anthropic quota setter clear failed", exc_info=True)
