"""Neutral contract and bounds for optional per-run event projections."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from core.observability.redaction import redact_secrets

RUN_EVENT_SCHEMA_ID = "geode.run-event@1"
RUN_EVENT_SCHEMA_VERSION = 1
RUN_EVENT_MAX_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class RunIdentity:
    session_id: str
    component: str
    gen_tag: str = ""


class RunEventSink(Protocol):
    component: str

    def append(
        self,
        event: str,
        *,
        level: str = "info",
        payload: dict[str, Any] | None = None,
        ts: float | None = None,
        actor_type: str = "orchestrator",
        actor_id: str = "pipeline",
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        task_id: str | None = None,
        turn_id: str = "",
        call_id: str = "",
    ) -> None: ...


RunEventSinkProvider = Callable[[], RunEventSink | None]


def bound_run_field(value: Any, max_chars: int) -> str:
    text = redact_secrets(str(value or ""))
    if len(text) <= max_chars:
        return text
    suffix = ":" + sha256(text.encode()).hexdigest()[:16]
    return text[: max_chars - len(suffix)] + suffix


def compact_run_events(
    path: Path,
    max_bytes: int,
    *,
    identity: RunIdentity,
    ordinal: int,
) -> None:
    from core.memory.atomic_write import atomic_write_text

    lines = path.read_text(encoding="utf-8").splitlines()
    kept: list[str] = []
    retained = 0
    budget = max(1, max_bytes // 2)
    for line in reversed(lines):
        size = len(line.encode()) + 1
        if kept and retained + size > budget:
            break
        kept.append(line)
        retained += size
    dropped = max(0, len(lines) - len(kept))
    now = time.time()
    marker = json.dumps(
        {
            "schema_id": RUN_EVENT_SCHEMA_ID,
            "schema_version": RUN_EVENT_SCHEMA_VERSION,
            "event_id": sha256(
                f"{identity.session_id}:projection.truncated:{ordinal}:{dropped}".encode()
            ).hexdigest()[:32],
            "occurred_at": now,
            "ts": now,
            "ordinal": max(0, ordinal - len(kept)),
            "seq": max(0, ordinal - len(kept)),
            "session_id": bound_run_field(identity.session_id, 256) or "unbound-run",
            "turn_id": "",
            "call_id": "",
            "gen_tag": bound_run_field(identity.gen_tag, 256),
            "component": bound_run_field(identity.component, 256) or "runtime",
            "level": "warning",
            "kind": "projection.truncated",
            "event": "projection.truncated",
            "actor_type": "system",
            "actor_id": "projection",
            "action": "projection.truncated",
            "entity_type": "artifact",
            "entity_id": path.name,
            "task_id": "",
            "payload": {"dropped_rows": dropped},
        },
        separators=(",", ":"),
    )
    retained_lines = list(reversed(kept))
    candidate = marker + "\n"
    if retained_lines:
        with_rows = marker + "\n" + "\n".join(retained_lines) + "\n"
        if len(with_rows.encode()) <= max_bytes:
            candidate = with_rows
    atomic_write_text(path, candidate)


__all__ = [
    "RUN_EVENT_MAX_BYTES",
    "RUN_EVENT_SCHEMA_ID",
    "RUN_EVENT_SCHEMA_VERSION",
    "RunEventSink",
    "RunEventSinkProvider",
    "RunIdentity",
    "bound_run_field",
    "compact_run_events",
]
