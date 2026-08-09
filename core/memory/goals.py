"""Durable multi-turn goal control state.

The table is a mutable projection in ``sessions.db``.  Append-only goal
transitions remain in ``session_events`` for trajectory and replay consumers.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from core.memory.sqlite_store import short_sqlite_connection


class GoalStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    BUDGET_LIMITED = "budget_limited"
    COMPLETE = "complete"


_UNFINISHED = frozenset({GoalStatus.ACTIVE})
_CREATE_GOALS_SQL = """\
CREATE TABLE IF NOT EXISTS thread_goals (
    session_id        TEXT PRIMARY KEY,
    goal_id           TEXT NOT NULL UNIQUE,
    objective         TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (
        status IN ('active', 'blocked', 'budget_limited', 'complete')
    ),
    token_budget      INTEGER,
    tokens_used       INTEGER NOT NULL DEFAULT 0,
    time_used_seconds REAL NOT NULL DEFAULT 0,
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL
)
"""


@dataclass(frozen=True, slots=True)
class ThreadGoal:
    session_id: str
    goal_id: str
    objective: str
    status: GoalStatus
    token_budget: int | None
    tokens_used: int
    time_used_seconds: float
    created_at: float
    updated_at: float

    @property
    def remaining_tokens(self) -> int | None:
        if self.token_budget is None:
            return None
        return max(0, self.token_budget - self.tokens_used)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["remaining_tokens"] = self.remaining_tokens
        return payload


def ensure_goal_schema(conn: sqlite3.Connection) -> None:
    """Create the additive goal projection table."""
    conn.execute(_CREATE_GOALS_SQL)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_thread_goals_status "
        "ON thread_goals (status, updated_at DESC)"
    )


class GoalStore:
    """Short-connection store sharing the project-local ``sessions.db``."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            from core.paths import resolve_sessions_dir

            db_path = resolve_sessions_dir() / "sessions.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def get(self, session_id: str) -> ThreadGoal | None:
        if not session_id:
            return None
        with short_sqlite_connection(self._db_path, ensure_goal_schema) as conn:
            row = conn.execute(
                "SELECT * FROM thread_goals WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def create(
        self,
        session_id: str,
        objective: str,
        *,
        token_budget: int | None = None,
    ) -> ThreadGoal:
        objective = objective.strip()
        if not session_id:
            raise ValueError("create_goal requires an active session")
        if not objective:
            raise ValueError("objective must not be empty")
        if len(objective) > 4_000:
            raise ValueError("objective must be at most 4000 characters")
        if token_budget is not None and token_budget <= 0:
            raise ValueError("token_budget must be positive")

        now = time.time()
        goal_id = f"g-{uuid.uuid4().hex[:16]}"
        with short_sqlite_connection(self._db_path, ensure_goal_schema, immediate=True) as conn:
            existing = conn.execute(
                "SELECT status FROM thread_goals WHERE session_id = ?", (session_id,)
            ).fetchone()
            if existing is not None and GoalStatus(str(existing["status"])) in _UNFINISHED:
                raise ValueError("cannot create a goal while this session has an unfinished goal")
            conn.execute(
                """INSERT INTO thread_goals
                       (session_id, goal_id, objective, status, token_budget,
                        tokens_used, time_used_seconds, created_at, updated_at)
                   VALUES (?, ?, ?, 'active', ?, 0, 0, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                       goal_id=excluded.goal_id,
                       objective=excluded.objective,
                       status='active',
                       token_budget=excluded.token_budget,
                       tokens_used=0,
                       time_used_seconds=0,
                       created_at=excluded.created_at,
                       updated_at=excluded.updated_at""",
                (session_id, goal_id, objective, token_budget, now, now),
            )
            row = conn.execute(
                "SELECT * FROM thread_goals WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("goal was not persisted")
        return self._from_row(row)

    def update_terminal(self, session_id: str, status: GoalStatus) -> ThreadGoal:
        if status not in {GoalStatus.COMPLETE, GoalStatus.BLOCKED}:
            raise ValueError("update_goal may only set complete or blocked")
        with short_sqlite_connection(self._db_path, ensure_goal_schema, immediate=True) as conn:
            cursor = conn.execute(
                """UPDATE thread_goals SET status = ?, updated_at = ?
                   WHERE session_id = ? AND status = 'active'""",
                (status.value, time.time(), session_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("no active goal exists for this session")
            row = conn.execute(
                "SELECT * FROM thread_goals WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("goal disappeared after update")
        return self._from_row(row)

    def account(
        self,
        session_id: str,
        *,
        goal_id: str,
        tokens: int,
        elapsed_seconds: float,
    ) -> ThreadGoal | None:
        """Account one completed turn and enforce a configured token budget."""
        with short_sqlite_connection(self._db_path, ensure_goal_schema, immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM thread_goals WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            goal = self._from_row(row)
            if goal.goal_id != goal_id or goal.status is GoalStatus.BUDGET_LIMITED:
                return goal
            used = goal.tokens_used + max(0, int(tokens))
            elapsed = goal.time_used_seconds + max(0.0, float(elapsed_seconds))
            status = (
                GoalStatus.BUDGET_LIMITED
                if goal.status is GoalStatus.ACTIVE
                and goal.token_budget is not None
                and used >= goal.token_budget
                else goal.status
            )
            conn.execute(
                """UPDATE thread_goals
                   SET status = ?, tokens_used = ?, time_used_seconds = ?, updated_at = ?
                   WHERE session_id = ? AND goal_id = ?""",
                (status.value, used, elapsed, time.time(), session_id, goal.goal_id),
            )
            updated = conn.execute(
                "SELECT * FROM thread_goals WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._from_row(updated) if updated is not None else None

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ThreadGoal:
        return ThreadGoal(
            session_id=str(row["session_id"]),
            goal_id=str(row["goal_id"]),
            objective=str(row["objective"]),
            status=GoalStatus(str(row["status"])),
            token_budget=int(row["token_budget"]) if row["token_budget"] is not None else None,
            tokens_used=int(row["tokens_used"]),
            time_used_seconds=float(row["time_used_seconds"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )
