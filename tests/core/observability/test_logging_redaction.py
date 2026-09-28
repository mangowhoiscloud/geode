"""PR-OBS-LOGGING-CONFIG — automatic secret redaction + JSON file format.

Frontier convergence: openclaw/hermes redact at the logger/formatter level
(not per call site), and openclaw/paperclip write structured JSONL. These
guards pin both: a leaked API key never reaches a handler's output, and
``GEODE_LOG_FORMAT=json`` makes the file handler emit valid JSON lines.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest
from core.observability.logging_config import (
    _JsonFormatter,
    _RedactingTextFormatter,
)

_FAKE_ANTHROPIC = "sk-ant-api03-" + "A" * 40  # matches the redaction pattern


def _record(msg: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)


def test_text_formatter_redacts_interpolated_message() -> None:
    fmt = _RedactingTextFormatter("%(message)s")
    out = fmt.format(_record("token=%s done", _FAKE_ANTHROPIC))
    assert _FAKE_ANTHROPIC not in out
    assert "[REDACTED]" in out
    assert "done" in out  # surrounding text preserved


def test_json_formatter_emits_valid_redacted_line() -> None:
    fmt = _JsonFormatter()
    line = fmt.format(_record("leak %s here", _FAKE_ANTHROPIC))
    parsed = json.loads(line)  # one valid JSON object
    assert set(parsed) >= {"ts", "level", "logger", "msg"}
    assert parsed["level"] == "INFO"
    assert _FAKE_ANTHROPIC not in line
    assert "[REDACTED]" in parsed["msg"]


def test_json_formatter_redacts_exception_text() -> None:
    fmt = _JsonFormatter()
    try:
        raise RuntimeError(f"boom with {_FAKE_ANTHROPIC}")
    except RuntimeError:
        import sys

        rec = _record("failed")
        rec.exc_info = sys.exc_info()
        line = fmt.format(rec)
    assert _FAKE_ANTHROPIC not in line


@pytest.fixture
def captured_root() -> Iterator[io.StringIO]:
    """A root-attached StreamHandler with the redacting formatter, so the
    end-to-end ``log.info(...)`` path is exercised, not just the formatter."""
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(_RedactingTextFormatter("%(message)s"))
    root = logging.getLogger()
    root.addHandler(h)
    try:
        yield buf
    finally:
        root.removeHandler(h)


def test_end_to_end_log_call_is_redacted(captured_root: io.StringIO) -> None:
    logging.getLogger("t.redact").warning("creds: %s", _FAKE_ANTHROPIC)
    assert _FAKE_ANTHROPIC not in captured_root.getvalue()
    assert "[REDACTED]" in captured_root.getvalue()


@pytest.mark.parametrize(
    "message",
    [
        "Authorization: Bearer opaque-custom-secret",
        "headers={'Authorization': 'Basic opaque-custom-secret'}",
        '{"refresh_token": "opaque-custom-secret", "attempt": 2}',
        "OPENAI_API_KEY=opaque-custom-secret status=failed",
        "{'api_key': 'opaque-custom-secret with spaces', 'status': 'failed'}",
    ],
)
@pytest.mark.parametrize("fmt", [_JsonFormatter(), _RedactingTextFormatter("%(message)s")])
def test_opaque_credentials_are_scrubbed_from_messages_and_exceptions(message, fmt) -> None:
    import sys

    try:
        raise RuntimeError(message)
    except RuntimeError:
        record = _record("request failed: %s", message)
        record.exc_info = sys.exc_info()
        rendered = fmt.format(record)
    assert "opaque-custom-secret" not in rendered
    assert "[REDACTED]" in rendered
    assert "RuntimeError" in rendered


def test_error_context_is_correlated_bounded_and_excludes_arbitrary_extras() -> None:
    record = _record("operation failed")
    record.request_id = "request-123"
    record.session_id = "session-456"
    record.command = "/login"
    record.error_type = "permission"
    record.exception_type = "PermissionError"
    record.payload = {"password": "opaque-extra-secret"}
    parsed = json.loads(_JsonFormatter().format(record))
    assert parsed["request_id"] == "request-123"
    assert parsed["session_id"] == "session-456"
    assert parsed["error_type"] == "permission"
    assert parsed["exception_type"] == "PermissionError"
    assert "payload" not in parsed
    assert '"request_id": "request-123"' in _RedactingTextFormatter().format(record)

    record.request_id = "api_key=opaque-context-secret"
    record.session_id = "s" * 1_000
    record.command = "/login\nforged"
    for fmt in (_JsonFormatter(), _RedactingTextFormatter()):
        rendered = fmt.format(record)
        assert "opaque-context-secret" not in rendered
        assert "opaque-extra-secret" not in rendered
        assert "s" * 129 not in rendered
        assert "\nforged" not in rendered
