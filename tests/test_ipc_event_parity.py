"""IPC event parity test — ensures all produced events are consumed.

Root cause prevention: PR #638 added emit_llm_retry/emit_llm_error/
emit_retry_wait to agentic_ui.py but forgot to register them in
ipc_client.py, causing raw dicts to leak to the user console.

This test extracts all send_event("event_name") calls from the
production code and verifies each one appears in ipc_client.py's
recognized event type list.
"""

from __future__ import annotations

import re
from pathlib import Path


def _extract_produced_events() -> set[str]:
    """Extract all event type strings from send_event() calls in core/."""
    root = Path(__file__).resolve().parent.parent / "core"
    pattern = re.compile(r'send_event\(\s*"([a-z_]+)"')
    # Also catch multi-line: send_event(\n    "event_name",
    pattern_ml = re.compile(r'send_event\(\s*\n\s*"([a-z_]+)"')

    events: set[str] = set()
    for py in root.rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        text = py.read_text(encoding="utf-8")
        events.update(pattern.findall(text))
        events.update(pattern_ml.findall(text))
    return events


def _extract_consumed_events() -> set[str]:
    """Extract all event types registered in ipc_client.py's rtype check."""
    ipc_path = Path(__file__).resolve().parent.parent / "core" / "cli" / "ipc_client.py"
    text = ipc_path.read_text(encoding="utf-8")

    # Find the block: if rtype in ( ... ):
    pattern = re.compile(r'"([a-z_]+)"')
    # Extract from the rtype in (...) block
    in_block = False
    events: set[str] = set()
    for line in text.splitlines():
        if "if rtype in (" in line:
            in_block = True
        if in_block:
            events.update(pattern.findall(line))
            if "):" in line and in_block and len(events) > 2:
                break
    return events


class TestIPCEventParity:
    """Every send_event() type must be registered in ipc_client.py."""

    def test_all_produced_events_are_consumed(self):
        produced = _extract_produced_events()
        consumed = _extract_consumed_events()

        missing = produced - consumed
        assert not missing, (
            f"IPC event types produced but NOT registered in ipc_client.py: {sorted(missing)}. "
            f"Add them to the rtype list in ipc_client.py to prevent raw dict console leak."
        )

    def test_produced_events_not_empty(self):
        """Sanity check: extraction should find events."""
        produced = _extract_produced_events()
        assert len(produced) >= 15, f"Expected 15+ events, got {len(produced)}"

    def test_consumed_events_not_empty(self):
        """Sanity check: extraction should find registered events."""
        consumed = _extract_consumed_events()
        assert len(consumed) >= 20, f"Expected 20+ events, got {len(consumed)}"
