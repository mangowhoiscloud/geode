"""Workaround for openai>=2.26 streaming parser vs ChatGPT Codex backend.

PR-CODEX-OUTPUT-NULL (2026-05-28). When the OpenAI Python SDK's
``responses.stream()`` helper consumes a ``response.completed`` SSE event,
``ResponseStreamState.accumulate_event`` calls
``openai.lib._parsing._responses.parse_response(response=event.response, ...)``.
``parse_response`` immediately runs ``for output in response.output:`` —
which raises ``TypeError: 'NoneType' object is not iterable`` whenever
``response.output`` is ``None``.

The ChatGPT subscription backend at ``chatgpt.com/backend-api/codex``
delivers exactly this shape: the actual output items arrive as separate
``response.output_item.done`` SSE events while the final
``response.completed`` event carries ``output: null`` (the snapshot lives
in the SDK's accumulator, not in the completed payload). Hermes pins
``openai==2.24.0`` (which predates the parse_response call) so they
never hit this; GEODE's ``openai>=2.26.0`` resolves to 2.30.0 and hits
it on every Codex subscription call.

The CodexOAuthAdapter already collects ``response.output_item.done``
events into a local ``accumulated`` list (``codex_oauth.py:118-126``)
and assigns them onto the final response in
``translate_codex_response``, so the SDK's structured parsing failure
is purely a crash-on-iteration artifact — coercing the iteration source
to ``[]`` when ``None`` lets the SDK reach its completion state and our
own accumulator pipeline takes over from there.

The patch is idempotent and applies only once per process; it is
installed lazily on the first import of any module that needs the Codex
backend so non-OpenAI processes (pure-Anthropic, claude-cli only) don't
pay for it. We restore the original symbol on test teardown via
:func:`_for_test_restore` so the unit test can exercise the unpatched
crash before re-applying the patch.

Removable once a future ``openai`` SDK release fixes
``parse_response`` to handle ``response.output is None`` (filed
upstream — see CHANGELOG entry).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

log = logging.getLogger(__name__)


_PATCHED: bool = False
_ORIGINAL_PARSE_RESPONSE: Any = None
# install() is reached concurrently when a multi-threaded harness (e.g.
# tau2 at max_concurrency>1) fires its first Codex calls at once. The
# unlocked check-then-act let a second thread capture the already-patched
# function as "original" and rebind the module global to it — every
# subsequent call then recursed into itself (RecursionError, 2026-07-04
# sub55 incident). The lock + closure capture below close both holes.
_INSTALL_LOCK = threading.Lock()


def install() -> None:
    """Patch ``openai.lib._parsing._responses.parse_response`` once.

    Subsequent calls are no-ops. The patch wraps the original function with
    a ``response.output = response.output or []`` coercion so the inner
    ``for output in response.output:`` loop becomes a safe no-op when the
    Codex backend sends a null-output completion event.
    """
    global _PATCHED, _ORIGINAL_PARSE_RESPONSE

    with _INSTALL_LOCK:
        if _PATCHED:
            return

        try:
            import openai.lib._parsing._responses as _parse_mod
            import openai.lib.streaming.responses._responses as _stream_mod
        except ImportError:
            log.debug("openai SDK not installed; skipping Codex workaround patch")
            return

        current = _parse_mod.parse_response
        if getattr(current, "_geode_codex_null_output_patch", False):
            _PATCHED = True
            return

        _ORIGINAL_PARSE_RESPONSE = current
        original = current

        def _patched(*, text_format: Any, input_tools: Any, response: Any) -> Any:
            if getattr(response, "output", None) is None:
                # In-place mutation is safe: the SDK constructs ``event.response``
                # fresh per ``response.completed`` event and the SDK consumer
                # (``accumulate_event`` at line 360 of the streaming module)
                # only forwards the parsed return value, never re-reads the
                # mutated input.
                try:
                    response.output = []
                except (AttributeError, TypeError, ValueError):
                    # Pydantic v2 may reject the attribute set on a frozen model
                    # — fall back to a model_copy with the field overridden.
                    try:
                        response = response.model_copy(update={"output": []})
                    except Exception:
                        log.warning(
                            "codex-sdk-workaround: failed to coerce response.output "
                            "from None to []; parse_response will likely raise"
                        )
            return original(
                text_format=text_format,
                input_tools=input_tools,
                response=response,
            )

        _patched._geode_codex_null_output_patch = True  # type: ignore[attr-defined]
        _parse_mod.parse_response = _patched
        # The streaming module imports ``parse_response`` at module load
        # (``from ..._parsing._responses import ..., parse_response``) so
        # patching only the source isn't enough — the streaming module's
        # local reference must be rebound too. ``setattr`` keeps mypy
        # quiet about the private-attribute access.
        setattr(_stream_mod, "parse_response", _patched)  # noqa: B010
        _PATCHED = True
        log.debug("codex-sdk-workaround: parse_response patched for output=None coercion")


def _for_test_restore() -> None:
    """Restore the original ``parse_response`` for unit tests that need
    to exercise the unpatched crash. Re-call :func:`install` afterwards
    to re-apply the patch."""
    global _PATCHED, _ORIGINAL_PARSE_RESPONSE

    if _ORIGINAL_PARSE_RESPONSE is None:
        return
    try:
        import openai.lib._parsing._responses as _parse_mod
        import openai.lib.streaming.responses._responses as _stream_mod

        _parse_mod.parse_response = _ORIGINAL_PARSE_RESPONSE
        setattr(_stream_mod, "parse_response", _ORIGINAL_PARSE_RESPONSE)  # noqa: B010
    except ImportError:
        pass
    _PATCHED = False
    _ORIGINAL_PARSE_RESPONSE = None
