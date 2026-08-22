"""Typed dependency frontier for ``/grill`` decision interviews."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from enum import StrEnum
from html import escape
from pathlib import Path
from typing import Any

from core.memory.sqlite_store import short_sqlite_connection

_MAX_NODES = 24


class GrillStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class GrillOption:
    label: str
    consequence: str

    @classmethod
    def from_dict(cls, raw: Any) -> GrillOption:
        if not isinstance(raw, dict) or set(raw) != {"label", "consequence"}:
            raise ValueError("each grill option requires only label and consequence")
        label = str(raw["label"]).strip()
        consequence = str(raw["consequence"]).strip()
        if not label or not consequence:
            raise ValueError("grill option label and consequence must not be empty")
        if len(label) > 120 or len(consequence) > 1000:
            raise ValueError("grill option label or consequence is too long")
        return cls(label, consequence)


@dataclass(frozen=True, slots=True)
class GrillNode:
    id: str
    question: str
    depends_on: tuple[str, ...]
    options: tuple[GrillOption, ...]
    recommended: str
    recommendation_reason: str

    @classmethod
    def from_dict(cls, raw: Any) -> GrillNode:
        required = {
            "id",
            "question",
            "depends_on",
            "options",
            "recommended",
            "recommendation_reason",
        }
        if not isinstance(raw, dict) or set(raw) != required:
            raise ValueError(f"each grill node requires exactly {sorted(required)}")
        node_id = str(raw["id"]).strip()
        question = str(raw["question"]).strip()
        dependencies = raw["depends_on"]
        raw_options = raw["options"]
        recommended = str(raw["recommended"]).strip()
        reason = str(raw["recommendation_reason"]).strip()
        if not node_id or len(node_id) > 64 or not question or len(question) > 1000:
            raise ValueError("grill node id/question is empty or too long")
        if not isinstance(dependencies, list) or any(
            not str(item).strip() for item in dependencies
        ):
            raise ValueError("depends_on must be a list of non-empty node ids")
        depends_on = tuple(str(item).strip() for item in dependencies)
        if len(depends_on) != len(set(depends_on)):
            raise ValueError(f"grill node {node_id!r} repeats a dependency")
        if not isinstance(raw_options, list) or not 2 <= len(raw_options) <= 3:
            raise ValueError("each grill node requires two or three options")
        options = tuple(GrillOption.from_dict(item) for item in raw_options)
        labels = [item.label for item in options]
        if len(labels) != len(set(labels)):
            raise ValueError(f"grill node {node_id!r} repeats an option label")
        if recommended not in labels or not reason or len(reason) > 1000:
            raise ValueError("recommended must name one option and include a reason")
        return cls(node_id, question, depends_on, options, recommended, reason)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GrillSession:
    session_id: str
    grill_id: str
    subject: str
    status: GrillStatus
    nodes: tuple[GrillNode, ...]
    answers: dict[str, str]
    revision: int
    created_at: float
    updated_at: float

    @property
    def frontier(self) -> tuple[GrillNode, ...]:
        answered = set(self.answers)
        return tuple(
            node
            for node in self.nodes
            if node.id not in answered and set(node.depends_on) <= answered
        )

    @property
    def unresolved(self) -> tuple[str, ...]:
        return tuple(node.id for node in self.nodes if node.id not in self.answers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "grill_id": self.grill_id,
            "subject": self.subject,
            "status": self.status.value,
            "nodes": [node.to_dict() for node in self.nodes],
            "answers": dict(self.answers),
            "frontier": [node.id for node in self.frontier],
            "unresolved": list(self.unresolved),
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


_SCHEMA = """\
CREATE TABLE IF NOT EXISTS thread_grills (
    session_id   TEXT PRIMARY KEY,
    grill_id     TEXT NOT NULL UNIQUE,
    subject      TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('draft', 'active', 'complete')),
    nodes_json   TEXT NOT NULL,
    answers_json TEXT NOT NULL,
    revision     INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
)
"""


def ensure_grill_schema(conn: sqlite3.Connection) -> None:
    conn.execute(_SCHEMA)
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(thread_grills)")}
    if "revision" not in columns:
        try:
            conn.execute("ALTER TABLE thread_grills ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(thread_grills)")}
            if "revision" not in columns:
                raise


def validate_grill_nodes(nodes: tuple[GrillNode, ...]) -> None:
    if not 1 <= len(nodes) <= _MAX_NODES:
        raise ValueError(f"grill tree requires 1-{_MAX_NODES} nodes")
    ids = [node.id for node in nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("grill node ids must be unique")
    known = set(ids)
    for node in nodes:
        if node.id in node.depends_on or not set(node.depends_on) <= known:
            raise ValueError(f"grill node {node.id!r} has an invalid dependency")
    pending = {node.id: set(node.depends_on) for node in nodes}
    resolved: set[str] = set()
    while ready := {node_id for node_id, deps in pending.items() if deps <= resolved}:
        resolved.update(ready)
        for node_id in ready:
            pending.pop(node_id)
    if pending:
        raise ValueError("grill dependencies must be acyclic")


class GrillStore:
    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            from core.paths import resolve_sessions_dir

            db_path = resolve_sessions_dir() / "sessions.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def get(self, session_id: str) -> GrillSession | None:
        with short_sqlite_connection(self._db_path, ensure_grill_schema) as conn:
            row = conn.execute(
                "SELECT * FROM thread_grills WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def start(self, session_id: str, subject: str) -> GrillSession:
        subject = subject.strip()
        if not session_id or not subject or len(subject) > 4000:
            raise ValueError("grill requires an active session and a 1-4000 character subject")
        now = time.time()
        grill_id = f"grill-{uuid.uuid4().hex[:16]}"
        with short_sqlite_connection(self._db_path, ensure_grill_schema, immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM thread_grills WHERE session_id = ?", (session_id,)
            ).fetchone()
            current = self._from_row(row) if row is not None else None
            if current is not None and current.status in {
                GrillStatus.DRAFT,
                GrillStatus.ACTIVE,
            }:
                if current.subject != subject:
                    raise ValueError(
                        "an active grill already owns this thread; "
                        "complete it before starting another"
                    )
                return current
            conn.execute(
                """INSERT INTO thread_grills
                       (session_id, grill_id, subject, status, nodes_json, answers_json,
                        revision, created_at, updated_at)
                   VALUES (?, ?, ?, 'draft', '[]', '{}', 0, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                       grill_id=excluded.grill_id, subject=excluded.subject, status='draft',
                       nodes_json='[]', answers_json='{}', revision=0,
                       created_at=excluded.created_at,
                       updated_at=excluded.updated_at""",
                (session_id, grill_id, subject, now, now),
            )
        result = self.get(session_id)
        if result is None:
            raise RuntimeError("grill session was not persisted")
        return result

    def define(self, session_id: str, raw_nodes: Any) -> GrillSession:
        if not isinstance(raw_nodes, list):
            raise ValueError("nodes must be a list")
        nodes = tuple(GrillNode.from_dict(item) for item in raw_nodes)
        validate_grill_nodes(nodes)
        current = self._require(session_id)
        if current.status is GrillStatus.COMPLETE:
            raise ValueError("completed grill sessions cannot be redefined")
        if current.answers:
            old_nodes = {node.id: node for node in current.nodes}
            new_nodes = {node.id: node for node in nodes}
            if any(new_nodes.get(node_id) != old_nodes.get(node_id) for node_id in current.answers):
                raise ValueError("a redefined tree cannot change answered nodes")
        return self._update(current, status=GrillStatus.ACTIVE, nodes=nodes)

    def answer(self, session_id: str, node_id: str, answer: str) -> GrillSession:
        current = self._require(session_id)
        answer = answer.strip()
        if current.status is not GrillStatus.ACTIVE or not answer or len(answer) > 120:
            raise ValueError("answer requires an active grill and a 1-120 character option label")
        frontier_ids = {node.id for node in current.frontier}
        if node_id not in frontier_ids:
            raise ValueError(f"node {node_id!r} is not on the current answerable frontier")
        node = next(item for item in current.frontier if item.id == node_id)
        if answer not in {option.label for option in node.options}:
            raise ValueError(f"answer for node {node_id!r} must name one of its option labels")
        answers = {**current.answers, node_id: answer}
        return self._update(current, answers=answers)

    def complete(self, session_id: str) -> GrillSession:
        current = self._require(session_id)
        if current.status is not GrillStatus.ACTIVE or current.unresolved:
            raise ValueError(f"grill cannot complete with unresolved nodes: {current.unresolved}")
        return self._update(current, status=GrillStatus.COMPLETE)

    def render_prompt(self, session_id: str) -> str:
        current = self.get(session_id)
        if current is None:
            return ""
        lines = [
            '<grill_state authority="typed_projection">',
            f"<grill_id>{current.grill_id}</grill_id>",
            f"<status>{current.status.value}</status>",
            f"<subject>{escape(current.subject, quote=False)}</subject>",
            f"<answered>{len(current.answers)}</answered>",
            f"<total>{len(current.nodes)}</total>",
        ]
        for node in current.frontier[:6]:
            lines.append(
                f'<frontier_node id="{escape(node.id, quote=True)}">'
                f"{escape(node.question, quote=False)}</frontier_node>"
            )
        lines.append("Use get_grill/update_grill; prose cannot mutate or complete this state.")
        lines.append("</grill_state>")
        return "\n".join(lines)

    def _require(self, session_id: str) -> GrillSession:
        current = self.get(session_id)
        if current is None:
            raise ValueError("no grill session exists for this thread")
        return current

    def _update(
        self,
        current: GrillSession,
        *,
        status: GrillStatus | None = None,
        nodes: tuple[GrillNode, ...] | None = None,
        answers: dict[str, str] | None = None,
    ) -> GrillSession:
        with short_sqlite_connection(self._db_path, ensure_grill_schema, immediate=True) as conn:
            cursor = conn.execute(
                """UPDATE thread_grills
                   SET status = ?, nodes_json = ?, answers_json = ?,
                       revision = revision + 1, updated_at = ?
                   WHERE session_id = ? AND grill_id = ? AND revision = ?""",
                (
                    (status or current.status).value,
                    json.dumps([node.to_dict() for node in (nodes or current.nodes)]),
                    json.dumps(answers if answers is not None else current.answers),
                    time.time(),
                    current.session_id,
                    current.grill_id,
                    current.revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("stale grill session update")
        return self._require(current.session_id)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> GrillSession:
        nodes = tuple(GrillNode.from_dict(item) for item in json.loads(str(row["nodes_json"])))
        validate_grill_nodes(nodes) if nodes else None
        answers = {
            str(key): str(value) for key, value in json.loads(str(row["answers_json"])).items()
        }
        if not set(answers) <= {node.id for node in nodes}:
            raise ValueError("stored grill answers reference unknown nodes")
        return GrillSession(
            session_id=str(row["session_id"]),
            grill_id=str(row["grill_id"]),
            subject=str(row["subject"]),
            status=GrillStatus(str(row["status"])),
            nodes=nodes,
            answers=answers,
            revision=int(row["revision"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )
