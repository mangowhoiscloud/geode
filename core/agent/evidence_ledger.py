"""Append-only evidence rows for GEODE runtime decisions."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict


class EvidenceRow(TypedDict):
    schema_version: int
    ts: float
    seq: int
    session_id: str
    component: str
    level: str
    event: str
    kind: str
    summary: str
    payload_hash: str
    payload: dict[str, Any]


_SENSITIVE_KEYS = {"api_key", "authorization", "password", "secret", "token", "text"}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in _SENSITIVE_KEYS and item:
                out[key] = f"<redacted:length={len(str(item))}>"
            else:
                out[key] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        from core.observability.redaction import redact_secrets

        return redact_secrets(value)
    return value


def evidence_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def default_evidence_path(session_id: str) -> Path:
    from core.paths import GEODE_HOME

    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in session_id)
    return GEODE_HOME / "evidence" / f"{safe or 'session'}.jsonl"


@dataclass
class EvidenceLedger:
    session_id: str
    path: Path | None = None
    rows: list[EvidenceRow] = field(default_factory=list)
    component: str = "agentic_loop"
    _seq: int = 0

    @classmethod
    def for_session(cls, session_id: str) -> EvidenceLedger:
        return cls(session_id=session_id, path=default_evidence_path(session_id))

    def append(self, *, kind: str, summary: str, payload: dict[str, Any]) -> EvidenceRow:
        redacted = _redact(payload)
        self._seq += 1
        row: EvidenceRow = {
            "schema_version": 1,
            "ts": time.time(),
            "seq": self._seq,
            "session_id": self.session_id,
            "component": self.component,
            "level": "info",
            "event": kind,
            "kind": kind,
            "summary": summary[:500],
            "payload_hash": evidence_hash(redacted),
            "payload": redacted,
        }
        self.rows.append(row)
        if self.path is not None:
            from core.memory.atomic_write import append_jsonl

            append_jsonl(self.path, dict(row))
        return row

    def append_preflight(
        self,
        *,
        capability_graph: dict[str, Any],
        preflight: dict[str, Any],
    ) -> EvidenceRow:
        return self.append(
            kind="task_preflight",
            summary="Provider capability graph matched against the user task.",
            payload={"capability_graph": capability_graph, "preflight": preflight},
        )

    def append_final(self, *, result: Any) -> EvidenceRow:
        tool_calls = getattr(result, "tool_calls", []) or []
        payload = {
            "termination_reason": getattr(result, "termination_reason", ""),
            "rounds": getattr(result, "rounds", 0),
            "tool_count": len(tool_calls),
            "error": getattr(result, "error", None),
        }
        return self.append(
            kind="final_result",
            summary=f"Agent finished with {payload['termination_reason'] or 'unknown'}.",
            payload=payload,
        )
