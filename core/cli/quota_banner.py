"""3-tier quota banner + abort dialog for GEODE's REPL.

PR-γ1 of the 2026-05-19 outer-loop config consolidation plan. Renders a
``bottom_toolbar`` callable that the prompt_toolkit ``PromptSession``
plumbs into the REPL frame. The banner colour reflects current
subscription quota usage against the
``[outer_loop] warn_threshold`` / ``abort_threshold`` from
:mod:`core.config.outer_loop`:

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

Reference: ``docs/plans/2026-05-19-outer-loop-config-consolidation.md``
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
    "QuotaBannerRefresher",
    "QuotaState",
    "SubscriptionQuotaBanner",
    "current_banner",
    "render_abort_message",
]


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

    family: str = ""
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
        family: str,
        used_tokens: int,
        total_tokens: int,
    ) -> None:
        """Replace the quota counters. Does not touch the ``aborted`` flag."""
        with self._lock:
            self._state = QuotaState(
                family=family,
                used_tokens=used_tokens,
                total_tokens=total_tokens,
                aborted=self._state.aborted,
                abort_reason=self._state.abort_reason,
            )

    def trip_abort(self, *, reason: str) -> None:
        """Lock the banner to red until :meth:`clear_abort` is called.

        Called by the ``CredentialResolutionError(subscription_only=True)``
        handler. ``reason`` is the resolver's actionable message — the
        same string the abort dialog renders.
        """
        with self._lock:
            self._state = QuotaState(
                family=self._state.family,
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
                family=self._state.family,
                used_tokens=self._state.used_tokens,
                total_tokens=self._state.total_tokens,
                aborted=False,
                abort_reason="",
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
            ⬤ yellow  approaching limit (62% of <family>)
            ⬤ red     aborted — see /status

        Renders empty string when no family is set yet (cold start) so
        the banner doesn't flash an unconfigured state.
        """
        state = self.state
        if not state.family and state.total_tokens == 0 and not state.aborted:
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
                f"<b> {state.family}: {pct}% used</b>"
                f" — abort threshold {int(self._abort * 100)}%"
            )
        if tier == "yellow":
            return (
                f'<style fg="yellow"> ⬤ </style>'
                f"{state.family}: {pct}% used"
                f" — approaching {int(self._abort * 100)}% limit"
            )
        return f'<style fg="green"> ⬤ </style>{state.family}: {pct}% used — healthy'


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


def render_abort_message(family: str, resolver_message: str) -> AbortDialog:
    """Compose the abort dialog body from a strict-mode resolution error.

    ``resolver_message`` is :attr:`CredentialResolutionError.args[0]`
    when ``subscription_only=True`` — it already contains the 3
    actionable remedies (wait / opt-in fallback / pin per-role). The
    dialog wraps it with a title that names the offending family.
    """
    return AbortDialog(
        title=f"Subscription quota exhausted — {family}",
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
    """Detach the active banner (used during REPL teardown / test cleanup)."""
    _set_current_banner(None)
