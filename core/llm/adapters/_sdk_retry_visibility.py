"""Surface OpenAI/httpx SDK-level retries to the agentic UI.

PR-ADAPTER-TIMEOUT-AND-SERIALIZATION (2026-05-28). The OpenAI SDK logs
``Retrying request to /responses in 0.49 seconds`` via the
``openai._base_client`` Python logger at ``INFO`` level. GEODE used to
print that line only into the serve log file, so an operator watching
the CLI saw the spinner with no signal that the SDK was actively
retrying — the operator's 2026-05-28 10-minute hang showed exactly
this gap (one SDK retry, hidden from the UI).

This module installs a ``logging.Handler`` on the ``openai._base_client``
logger that scrapes the retry message and re-emits it through the
existing :func:`emit_llm_retry` event — same UI affordance GEODE's own
agent-loop-side retry surface uses. Idempotent across the process.

Why a logging filter (not an httpx event hook): the SDK manages retries
internally inside ``AsyncAPIClient._request`` and does not emit an
event_hook for them. The log line is the only stable surface the SDK
already exposes for this signal.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

_INSTALLED: bool = False
_RETRY_PATTERN = re.compile(r"Retrying request to .+ in ([0-9.]+) seconds")


class _OpenAISdkRetryEventBridge(logging.Handler):
    """Logging handler — parses SDK retry-log lines + emits UI event."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            return
        match = _RETRY_PATTERN.search(message)
        if match is None:
            return
        try:
            delay_s = max(1, int(float(match.group(1))))
        except (TypeError, ValueError):
            delay_s = 1
        try:
            from core.ui.agentic_ui import emit_llm_retry

            # OpenAI SDK exposes ``max_retries`` via client config but not on
            # the log record itself. Hardcoded ``(attempt=1, max_attempts=2)``
            # is a deliberate floor — the UI carries the "retry happening"
            # signal regardless of which attempt; full attempt tracking
            # would require monkey-patching the SDK retry loop.
            emit_llm_retry(delay_s=delay_s, attempt=1, max_attempts=2)
        except Exception:
            log.debug("failed to surface SDK retry log to UI", exc_info=True)


def install() -> None:
    """Attach the retry-event bridge once per process. Safe to call from
    any adapter client builder."""
    global _INSTALLED
    if _INSTALLED:
        return
    handler = _OpenAISdkRetryEventBridge(level=logging.INFO)
    logging.getLogger("openai._base_client").addHandler(handler)
    _INSTALLED = True
    log.debug("openai SDK retry → UI bridge installed")


def _for_test_reset() -> None:
    global _INSTALLED
    _INSTALLED = False
    sdk_logger = logging.getLogger("openai._base_client")
    sdk_logger.handlers = [
        h for h in sdk_logger.handlers if not isinstance(h, _OpenAISdkRetryEventBridge)
    ]
