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
from html import escape
from pathlib import Path
from typing import Any

from core.memory.sqlite_store import short_sqlite_connection


class GoalStatus(StrEnum):
    EMPTY = "empty"
    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    BUDGET_LIMITED = "budget_limited"
    COMPLETE = "complete"


_UNFINISHED = frozenset({GoalStatus.ACTIVE, GoalStatus.PAUSED})
_CREATE_GOALS_SQL = """\
CREATE TABLE IF NOT EXISTS thread_goals (
    session_id        TEXT PRIMARY KEY,
    goal_id           TEXT NOT NULL UNIQUE,
    objective         TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (
        status IN ('active', 'paused', 'blocked', 'budget_limited', 'complete')
    ),
    token_budget      INTEGER,
    tokens_used       INTEGER NOT NULL DEFAULT 0,
    time_used_seconds REAL NOT NULL DEFAULT 0,
    revision          INTEGER NOT NULL DEFAULT 0,
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
    revision: int = 0

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
    existing = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'thread_goals'"
    ).fetchone()
    if existing is not None and "'paused'" not in str(existing[0]):
        conn.execute("ALTER TABLE thread_goals RENAME TO thread_goals_legacy")
        conn.execute(_CREATE_GOALS_SQL)
        conn.execute(
            """INSERT INTO thread_goals
                   (session_id, goal_id, objective, status, token_budget, tokens_used,
                    time_used_seconds, revision, created_at, updated_at)
               SELECT session_id, goal_id, objective, status, token_budget, tokens_used,
                      time_used_seconds, 0, created_at, updated_at
               FROM thread_goals_legacy"""
        )
        conn.execute("DROP TABLE thread_goals_legacy")
    else:
        conn.execute(_CREATE_GOALS_SQL)
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(thread_goals)")}
    if "revision" not in columns:
        try:
            conn.execute("ALTER TABLE thread_goals ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(thread_goals)")}
            if "revision" not in columns:
                raise
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

    def status(self, session_id: str) -> GoalStatus:
        """Return the explicit state-machine state, including no stored goal."""
        goal = self.get(session_id)
        return goal.status if goal is not None else GoalStatus.EMPTY

    def clear(
        self,
        session_id: str,
        *,
        expected_goal_id: str | None = None,
        expected_revision: int | None = None,
    ) -> ThreadGoal | None:
        """Transition the session to ``empty`` by removing its goal projection."""
        if not session_id:
            raise ValueError("clear_goal requires an active session")
        with short_sqlite_connection(self._db_path, ensure_goal_schema, immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM thread_goals WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is not None:
                if expected_goal_id is not None and str(row["goal_id"]) != expected_goal_id:
                    raise ValueError("stale goal update: goal_id no longer matches")
                if expected_revision is not None and int(row["revision"]) != expected_revision:
                    raise ValueError("stale goal update: revision no longer matches")
                conn.execute(
                    "DELETE FROM thread_goals WHERE session_id = ? AND revision = ?",
                    (session_id, int(row["revision"])),
                )
        return self._from_row(row) if row is not None else None

    def list_active(self) -> list[ThreadGoal]:
        """Return active Goals oldest-first for fair idle admission."""
        with short_sqlite_connection(self._db_path, ensure_goal_schema) as conn:
            rows = conn.execute(
                "SELECT * FROM thread_goals WHERE status = 'active' ORDER BY updated_at ASC"
            ).fetchall()
        return [self._from_row(row) for row in rows]

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
                       revision=0,
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

    def update_terminal(
        self,
        session_id: str,
        status: GoalStatus,
        *,
        expected_goal_id: str | None = None,
        expected_revision: int | None = None,
    ) -> ThreadGoal:
        if status not in {GoalStatus.COMPLETE, GoalStatus.BLOCKED}:
            raise ValueError("update_goal may only set complete or blocked")
        with short_sqlite_connection(self._db_path, ensure_goal_schema, immediate=True) as conn:
            if expected_goal_id is None:
                row = conn.execute(
                    "SELECT goal_id FROM thread_goals WHERE session_id = ? AND status = 'active'",
                    (session_id,),
                ).fetchone()
                expected_goal_id = str(row["goal_id"]) if row is not None else ""
            cursor = conn.execute(
                """UPDATE thread_goals SET status = ?, revision = revision + 1,
                                           updated_at = ?
                   WHERE session_id = ? AND goal_id = ? AND status = 'active'
                     AND (? IS NULL OR revision = ?)""",
                (
                    status.value,
                    time.time(),
                    session_id,
                    expected_goal_id,
                    expected_revision,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                current = conn.execute(
                    "SELECT goal_id, status FROM thread_goals WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if current is not None and str(current["status"]) == GoalStatus.ACTIVE.value:
                    raise ValueError("stale goal update: identity or revision no longer matches")
                raise ValueError("no active goal exists for this session")
            row = conn.execute(
                "SELECT * FROM thread_goals WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("goal disappeared after update")
        return self._from_row(row)

    def update_operator(
        self,
        session_id: str,
        action: str,
        *,
        expected_goal_id: str,
        expected_revision: int,
        objective: str = "",
    ) -> ThreadGoal:
        """Apply an operator-owned pause/resume/edit transition with CAS."""
        action = action.strip().lower()
        if action not in {"pause", "resume", "edit"}:
            raise ValueError("goal action must be pause, resume, or edit")
        objective = objective.strip()
        if action == "edit" and (not objective or len(objective) > 4000):
            raise ValueError("edited objective must contain 1-4000 characters")
        with short_sqlite_connection(self._db_path, ensure_goal_schema, immediate=True) as conn:
            if action == "edit":
                cursor = conn.execute(
                    """UPDATE thread_goals SET objective = ?, revision = revision + 1,
                                                   updated_at = ?
                       WHERE session_id = ? AND goal_id = ?
                         AND revision = ? AND status IN ('active', 'paused')""",
                    (
                        objective,
                        time.time(),
                        session_id,
                        expected_goal_id,
                        expected_revision,
                    ),
                )
            else:
                expected = GoalStatus.PAUSED if action == "resume" else GoalStatus.ACTIVE
                target = GoalStatus.ACTIVE if action == "resume" else GoalStatus.PAUSED
                cursor = conn.execute(
                    """UPDATE thread_goals SET status = ?, revision = revision + 1,
                                                updated_at = ?
                       WHERE session_id = ? AND goal_id = ? AND revision = ? AND status = ?""",
                    (
                        target.value,
                        time.time(),
                        session_id,
                        expected_goal_id,
                        expected_revision,
                        expected.value,
                    ),
                )
            if cursor.rowcount != 1:
                raise ValueError("stale or illegal goal transition")
            row = conn.execute(
                "SELECT * FROM thread_goals WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("goal disappeared after operator update")
        return self._from_row(row)

    def render_prompt(self, session_id: str) -> str:
        goal = self.get(session_id)
        if goal is None:
            return '<goal_state status="empty" />'
        remaining = goal.remaining_tokens if goal.remaining_tokens is not None else "unbounded"
        return (
            '<goal_state authority="typed_projection">\n'
            f"<goal_id>{goal.goal_id}</goal_id>\n"
            f"<status>{goal.status.value}</status>\n"
            f"<objective>{escape(goal.objective, quote=False)}</objective>\n"
            f"<tokens_used>{goal.tokens_used}</tokens_used>\n"
            f"<revision>{goal.revision}</revision>\n"
            f"<remaining_tokens>{remaining}</remaining_tokens>\n"
            "Only explicit user controls may pause, resume, edit, or clear this goal.\n"
            "</goal_state>"
        )

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
                   SET status = ?, tokens_used = ?, time_used_seconds = ?,
                       revision = revision + 1, updated_at = ?
                   WHERE session_id = ? AND goal_id = ? AND revision = ?""",
                (
                    status.value,
                    used,
                    elapsed,
                    time.time(),
                    session_id,
                    goal.goal_id,
                    goal.revision,
                ),
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
            revision=int(row["revision"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )
