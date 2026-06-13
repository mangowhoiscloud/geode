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
