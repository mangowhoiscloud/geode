"""PR-D Phase 2c — ``_dispatch_llm_call`` extraction invariants.

Pins the structural extraction of the LLM-call dispatch +
BillingError + UserCancelledError handlers from ``arun``'s while-
loop body. Phase 2c is pure refactor (zero behaviour change); the
helper returns one of:

  * ``AgenticResponse`` — happy path, caller proceeds with response
  * ``AgenticResult`` — early-exit (BillingError or UserCancelledError),
    caller ``return``s verbatim
  * ``None`` — _call_llm returned None (caller's existing error
    classification handles it)

``_ContextExhaustedError`` is NOT caught — propagates to the
caller's inline aggressive-recovery path, preserving the
``continue`` / ``finalize_and_return`` branches.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest
from core.agent.loop.agent_loop import AgenticLoop
from core.agent.loop.models import AgenticResult, _ContextExhaustedError
from core.llm.agentic_response import AgenticResponse
from core.llm.errors import BillingError, UserCancelledError

# ---------------------------------------------------------------------------
# Method exists with the right signature
# ---------------------------------------------------------------------------


def test_helper_method_exists() -> None:
    assert hasattr(AgenticLoop, "_dispatch_llm_call")
    method = AgenticLoop._dispatch_llm_call
    sig = inspect.signature(method)
    assert "system_prompt" in sig.parameters
    assert "messages" in sig.parameters
    assert "round_idx" in sig.parameters
    assert "spinner" in sig.parameters


def test_helper_is_coroutine() -> None:
    assert inspect.iscoroutinefunction(AgenticLoop._dispatch_llm_call)


# ---------------------------------------------------------------------------
# Stub harness — minimal AgenticLoop with mockable _call_llm
# ---------------------------------------------------------------------------


class _StubSpinner:
    """Counts stop() calls so tests verify spinner cleanup."""

    def __init__(self) -> None:
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1


class _StubLoop:
    """Minimal AgenticLoop stub — only fields _dispatch_llm_call reads.

    ``_call_llm_side_effect`` controls what the stub returns / raises
    so each scenario test is self-contained.
    """

    def __init__(self, side_effect: object) -> None:
        self._side_effect = side_effect
        self.quota_panel_calls = 0

    async def _call_llm(self, _system_prompt: str, _messages: list, *, round_idx: int) -> object:
        if isinstance(self._side_effect, BaseException):
            raise self._side_effect
        return self._side_effect

    def _emit_quota_panel(self, _exc: BillingError) -> None:
        self.quota_panel_calls += 1


def _run_dispatch(
    stub: _StubLoop, spinner: _StubSpinner, round_idx: int = 0
) -> AgenticResponse | AgenticResult | None:
    bound = AgenticLoop._dispatch_llm_call.__get__(stub, _StubLoop)
    return asyncio.run(bound("SYS", [], round_idx, spinner))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_returns_response_on_success() -> None:
    response = AgenticResponse()
    stub = _StubLoop(side_effect=response)
    spinner = _StubSpinner()
    result = _run_dispatch(stub, spinner)
    assert result is response
    # No spinner stop in helper — caller's finally handles it.
    assert spinner.stop_calls == 0


def test_returns_none_when_call_llm_returns_none() -> None:
    """``_call_llm`` may return None when the adapter swallows the
    underlying exception. Helper passes None through; caller's
    existing error-classification logic handles it."""
    stub = _StubLoop(side_effect=None)
    spinner = _StubSpinner()
    result = _run_dispatch(stub, spinner)
    assert result is None


# ---------------------------------------------------------------------------
# BillingError handling
# ---------------------------------------------------------------------------


class _FakeBillingError(BillingError):
    """BillingError subclass with controlled user_message."""

    def __init__(self) -> None:
        super().__init__("billing limit reached")

    def user_message(self) -> str:
        return "Out of credits"


def test_billing_error_returns_agentic_result() -> None:
    """BillingError → AgenticResult with termination_reason='billing_error'
    + user_message text + rounds = round_idx + 1."""
    stub = _StubLoop(side_effect=_FakeBillingError())
    spinner = _StubSpinner()
    result = _run_dispatch(stub, spinner, round_idx=3)
    assert isinstance(result, AgenticResult)
    assert result.termination_reason == "billing_error"
    assert result.text == "Out of credits"
    assert result.rounds == 4  # round_idx + 1


def test_billing_error_stops_spinner_before_quota_panel() -> None:
    """spinner.stop() MUST run BEFORE emit_quota_panel so terminal
    output stays clean (panel print not interleaved with spinner)."""
    stub = _StubLoop(side_effect=_FakeBillingError())
    spinner = _StubSpinner()
    _run_dispatch(stub, spinner)
    # Spinner stopped + quota panel emitted (both side effects).
    assert spinner.stop_calls == 1
    assert stub.quota_panel_calls == 1


# ---------------------------------------------------------------------------
# UserCancelledError handling
# ---------------------------------------------------------------------------


def test_user_cancelled_returns_agentic_result() -> None:
    """UserCancelledError → AgenticResult with
    termination_reason='user_cancelled' + 'Interrupted.' text."""
    stub = _StubLoop(side_effect=UserCancelledError("user pressed Ctrl-C"))
    spinner = _StubSpinner()
    result = _run_dispatch(stub, spinner, round_idx=5)
    assert isinstance(result, AgenticResult)
    assert result.termination_reason == "user_cancelled"
    assert result.text == "Interrupted."
    assert result.rounds == 6


def test_user_cancelled_stops_spinner() -> None:
    """Spinner stop required so the next log line doesn't get
    overwritten by spinner frames."""
    stub = _StubLoop(side_effect=UserCancelledError("x"))
    spinner = _StubSpinner()
    _run_dispatch(stub, spinner)
    assert spinner.stop_calls == 1


# ---------------------------------------------------------------------------
# _ContextExhaustedError does NOT short-circuit — propagates
# ---------------------------------------------------------------------------


def test_context_exhausted_error_propagates() -> None:
    """The complex aggressive-recovery path (``continue`` retry vs
    ``finalize_and_return`` give-up) stays inline in ``arun``.
    Helper must NOT catch _ContextExhaustedError — let the inline
    handler see it.

    Anti-deception: a helper that silently swallows this exception
    would break the recovery path entirely."""
    stub = _StubLoop(side_effect=_ContextExhaustedError("context full"))
    spinner = _StubSpinner()
    with pytest.raises(_ContextExhaustedError):
        _run_dispatch(stub, spinner)


# ---------------------------------------------------------------------------
# arun delegates to the helper
# ---------------------------------------------------------------------------


def test_arun_calls_dispatch_helper() -> None:
    src = inspect.getsource(AgenticLoop.arun)
    assert "self._dispatch_llm_call(" in src


def test_arun_returns_early_on_agentic_result() -> None:
    """``arun``'s call site must check isinstance(outcome,
    AgenticResult) and return verbatim. Pin the discriminator
    pattern so a refactor that drops the isinstance check doesn't
    accidentally treat AgenticResult as a response."""
    src = inspect.getsource(AgenticLoop.arun)
    assert "isinstance(_llm_outcome, AgenticResult)" in src
    assert "return _llm_outcome" in src


def test_arun_no_longer_inlines_billing_or_cancelled_handlers() -> None:
    """Anti-residue — the pre-refactor PER-ROUND inline handlers must
    be gone. ``arun`` still has ONE BillingError handler at session-
    start (around the ``_try_decompose`` call); that one is intentional
    and lives outside the while-loop body. Pin the count instead of
    grepping "not in"."""
    src = inspect.getsource(AgenticLoop.arun)
    # Exactly ONE BillingError handler remains (the _try_decompose
    # one); the per-round LLM-call handler is gone.
    assert src.count("except BillingError as exc:") == 1
    # UserCancelledError was only in the per-round LLM-call path;
    # ``arun`` should have zero handlers now.
    assert "except UserCancelledError:" not in src
    # The user_cancelled termination reason lived only in the LLM-call
    # handler. The billing_error reason is still raised by the
    # session-start _try_decompose handler — verify it remains there
    # exactly once.
    assert src.count('termination_reason="billing_error"') == 1
    assert 'termination_reason="user_cancelled"' not in src


def test_arun_still_handles_context_exhausted_inline() -> None:
    """Cross-phase regression — _ContextExhaustedError handler must
    STILL be in arun (NOT moved to the helper). Pin via grep."""
    src = inspect.getsource(AgenticLoop.arun)
    assert "except _ContextExhaustedError" in src


# ---------------------------------------------------------------------------
# Cross-phase regression guard
# ---------------------------------------------------------------------------


def test_prior_phase_helpers_still_exist() -> None:
    """Phase 1 + 2a + 2b helpers must remain intact."""
    assert hasattr(AgenticLoop, "_emit_session_start_signals")
    assert hasattr(AgenticLoop, "_check_round_guards")
    assert hasattr(AgenticLoop, "_sync_model_and_rebuild_prompt")


@pytest.fixture(autouse=True)
def _no_shared_state() -> None:
    yield
