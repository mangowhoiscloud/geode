"""IPC event parity test — ensures all produced events are consumed.

Root cause prevention: PR #638 added retry/error emitters to agentic_ui.py but
forgot to register their event vocabulary in
ipc_client.py, causing raw dicts to leak to the user console.

This test extracts all send_event("event_name") calls from production code
and verifies each one appears in the versioned public event vocabulary.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.ipc_protocol import IPC_EVENT_TYPES


def _extract_produced_events() -> set[str]:
    """Extract all event type strings from send_event() calls in core/."""
    root = Path(__file__).resolve().parents[2] / "core"
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


class TestIPCEventParity:
    """Every send_event() type must be registered in ipc_client.py."""

    def test_all_produced_events_are_consumed(self):
        produced = _extract_produced_events()
        consumed = set(IPC_EVENT_TYPES)

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
        consumed = set(IPC_EVENT_TYPES)
        assert len(consumed) >= 20, f"Expected 20+ events, got {len(consumed)}"
