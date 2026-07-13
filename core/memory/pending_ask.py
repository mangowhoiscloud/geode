"""Pending operator asks — durable question/answer correlation for headless runs.

When an autonomous run (scheduled job, daemon session) terminates with
``termination_reason="user_clarification_needed"``, the question previously
died with the run: the cron surface has no human in the loop and the loop's
final text went nowhere. This module persists that question as a *pending
ask* keyed to the run's session checkpoint, notifies the operator through
the configured notification adapter, and resolves the first operator reply
back into a session continuation.

Answer contract (inspired by frontier notification harnesses):

- **First valid reply wins.** Later replies get ``already_answered`` with
  who/when, never a second continuation.
- **Expiry.** Asks older than :data:`ASK_TTL_HOURS` refuse resolution with
  ``expired``. The TTL matches session-checkpoint cleanup (72h) because a
  continuation without its checkpoint is impossible anyway.
- **Durable answer, best-effort continuation.** ``resolve()`` claims the
  answer atomically on disk first; the continuation runs after the claim.
  A failed continuation never un-answers the ask.

Trust model: replies arrive only through surfaces that are already
operator-authenticated — the gateway path accepts messages only from
exact-match channel bindings (:class:`core.messaging.binding.ChannelManager`),
and the CLI path runs as the operator.

Storage: one JSON file per ask under ``resolve_pending_asks_dir()``
(``~/.geode/projects/{id}/pending_asks/``) — the same visibility domain as
the session checkpoints the asks reference. Cross-process first-reply-wins
is enforced with an ``fcntl`` lock file in the same directory.
"""

from __future__ import annotations

import fcntl
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.memory.atomic_write import atomic_write_json
from core.paths import resolve_pending_asks_dir

if TYPE_CHECKING:
    from core.memory.session_checkpoint import SessionCheckpoint, SessionState

log = logging.getLogger(__name__)

ASK_TTL_HOURS = 72.0
# Resolved asks older than this are removed by the opportunistic purge in
# ``create()``. Generous on purpose: the files are tiny audit records.
PURGE_AGE_HOURS = 24.0 * 14

# ``ask <id> <answer>`` / ``/ask <id>: <answer>`` — the reply grammar for
# bound channels. The id is the hex ask_id (prefix allowed at lookup).
_ASK_REPLY_RE = re.compile(
    r"^\s*/?ask\s+([0-9a-fA-F]{4,32})\s*[::]?\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)

# resolve() outcomes
RESOLVED = "answered"
ALREADY_ANSWERED = "already_answered"
EXPIRED = "expired"
NOT_FOUND = "not_found"


@dataclass
class PendingAsk:
    """One persisted operator question awaiting (or holding) its answer."""

    ask_id: str
    question: str
    session_id: str  # session-checkpoint id the continuation resumes
    source: str  # e.g. "scheduled:daily-report"
    created_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending | answered | expired
    answer: str = ""
    answered_at: float = 0.0
    answered_by: str = ""
    notified_channel: str = ""
    notified_recipient: str = ""

    def is_stale(self, *, now: float | None = None) -> bool:
        """True when the pending TTL has elapsed."""
        ref = time.time() if now is None else now
        return (ref - self.created_at) > ASK_TTL_HOURS * 3600

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PendingAsk:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


class PendingAskStore:
    """File-backed ask store with cross-process first-reply-wins."""

    def __init__(self, asks_dir: Path | str | None = None) -> None:
        self._dir = Path(asks_dir) if asks_dir else resolve_pending_asks_dir()

    @property
    def asks_dir(self) -> Path:
        return self._dir

    def _path(self, ask_id: str) -> Path:
        return self._dir / f"{ask_id}.json"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Cross-process exclusive section over this store's directory."""
        self._dir.mkdir(parents=True, exist_ok=True)
        lock_path = self._dir / ".lock"
        with open(lock_path, "w", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def create(self, question: str, *, session_id: str, source: str) -> PendingAsk:
        """Persist a new pending ask (8-hex id, collision-checked)."""
        self._dir.mkdir(parents=True, exist_ok=True)
        self.purge_stale()
        for _attempt in range(8):
            ask_id = uuid.uuid4().hex[:8]
            if not self._path(ask_id).exists():
                break
        else:  # pragma: no cover — 8 collisions on 32-bit ids
            ask_id = uuid.uuid4().hex[:16]
        ask = PendingAsk(
            ask_id=ask_id,
            question=question,
            session_id=session_id,
            source=source,
        )
        atomic_write_json(self._path(ask_id), ask.to_dict(), indent=2)
        return ask

    def get(self, ask_id: str) -> PendingAsk | None:
        """Load one ask by exact id. Returns None when missing/corrupt."""
        path = self._path(ask_id)
        if not path.exists():
            return None
        try:
            return PendingAsk.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            log.warning("Failed to load pending ask %s: %s", ask_id, exc)
            return None

    def find(self, id_or_prefix: str) -> PendingAsk | None:
        """Resolve an ask by exact id, else by unique id prefix."""
        if not id_or_prefix:
            return None
        exact = self.get(id_or_prefix)
        if exact is not None:
            return exact
        prefix = id_or_prefix.lower()
        matches = [a for a in self.list_asks() if a.ask_id.startswith(prefix)]
        if len(matches) == 1:
            return matches[0]
        return None

    def list_asks(self) -> list[PendingAsk]:
        """All asks, newest first."""
        if not self._dir.exists():
            return []
        asks = []
        for path in self._dir.glob("*.json"):
            ask = self.get(path.stem)
            if ask is not None:
                asks.append(ask)
        asks.sort(key=lambda a: a.created_at, reverse=True)
        return asks

    def list_pending(self) -> list[PendingAsk]:
        """Pending, non-stale asks — the operator's open questions."""
        return [a for a in self.list_asks() if a.status == "pending" and not a.is_stale()]

    def resolve(
        self,
        ask_id: str,
        answer: str,
        *,
        answered_by: str,
    ) -> tuple[str, PendingAsk | None]:
        """Claim an answer (first reply wins).

        Returns ``(outcome, ask)`` where outcome is one of
        :data:`RESOLVED` / :data:`ALREADY_ANSWERED` / :data:`EXPIRED` /
        :data:`NOT_FOUND`. The read-check-write runs under an ``fcntl``
        lock so two processes (daemon gateway + CLI) cannot both claim.
        """
        if not self._path(ask_id).exists():
            return NOT_FOUND, None
        with self._locked():
            ask = self.get(ask_id)
            if ask is None:
                return NOT_FOUND, None
            if ask.status == "answered":
                return ALREADY_ANSWERED, ask
            if ask.status == "expired" or ask.is_stale():
                if ask.status != "expired":
                    ask.status = "expired"
                    atomic_write_json(self._path(ask_id), ask.to_dict(), indent=2)
                return EXPIRED, ask
            ask.status = "answered"
            ask.answer = answer
            ask.answered_at = time.time()
            ask.answered_by = answered_by
            atomic_write_json(self._path(ask_id), ask.to_dict(), indent=2)
            return RESOLVED, ask

    def record_notified(self, ask: PendingAsk, *, channel: str, recipient: str) -> None:
        """Stamp where the ask was delivered (audit trail).

        Re-reads the ask under the store lock and updates ONLY the
        notified fields — a reply that raced the notification send must
        never be clobbered by this stale write-back.
        """
        with self._locked():
            current = self.get(ask.ask_id)
            if current is None:
                return
            current.notified_channel = channel
            current.notified_recipient = recipient
            atomic_write_json(self._path(current.ask_id), current.to_dict(), indent=2)
        ask.notified_channel = channel
        ask.notified_recipient = recipient

    def purge_stale(self, *, max_age_hours: float = PURGE_AGE_HOURS) -> int:
        """Remove ask files older than *max_age_hours*. Returns count removed."""
        if not self._dir.exists():
            return 0
        cutoff = time.time() - max_age_hours * 3600
        removed = 0
        for path in self._dir.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
        return removed


def parse_ask_reply(text: str) -> tuple[str, str] | None:
    """Parse ``ask <id> <answer>`` shaped replies.

    Accepts an optional leading slash, an optional colon after the id, any
    id case, and a multi-line answer. Returns ``(id_or_prefix, answer)`` or
    None when *text* is not an ask reply.
    """
    match = _ASK_REPLY_RE.match(text or "")
    if match is None:
        return None
    return match.group(1).lower(), match.group(2).strip()


def format_ask_notification(ask: PendingAsk) -> str:
    """Operator-facing notification body for a new pending ask."""
    return (
        f"[ask {ask.ask_id}] {ask.source} needs your input "
        f"(session {ask.session_id}):\n\n"
        f"{ask.question}\n\n"
        f"Reply in a bound channel with: ask {ask.ask_id} <answer>\n"
        f'Or run: geode ask answer {ask.ask_id} "<answer>"'
    )


async def apublish_clarification_ask(
    question: str,
    *,
    session_id: str,
    source: str,
    store: PendingAskStore | None = None,
) -> PendingAsk | None:
    """Persist a pending ask and best-effort notify the operator.

    Never raises: emission runs on autonomous paths (scheduler drain) where
    a notification failure must not disturb the run result. Returns the
    persisted ask, or None when even persistence failed.
    """
    try:
        store = store or PendingAskStore()
        ask = store.create(question, session_id=session_id, source=source)
    except Exception:
        log.warning("Pending-ask persistence failed (source=%s)", source, exc_info=True)
        return None

    try:
        from core.config import settings
        from core.mcp.notification_port import get_notification

        adapter = get_notification()
        if adapter is None:
            log.info(
                "Pending ask %s persisted; no notification adapter configured "
                "— visible via 'geode ask list'",
                ask.ask_id,
            )
            return ask
        channel = settings.notification_channel
        recipient = settings.notification_recipient
        result = await adapter.asend_message(
            channel,
            recipient,
            format_ask_notification(ask),
            severity="warning",
        )
        if result.success:
            store.record_notified(ask, channel=channel, recipient=recipient)
        else:
            log.warning(
                "Pending ask %s notification failed on %s: %s",
                ask.ask_id,
                channel,
                result.error,
            )
    except Exception:
        log.warning("Pending-ask notification failed (ask=%s)", ask.ask_id, exc_info=True)
    return ask


def _fmt_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


async def ahandle_ask_reply(
    content: str,
    *,
    answered_by: str,
    run_continuation: Callable[[SessionState, str], Awaitable[str]],
    store: PendingAskStore | None = None,
    checkpoint: SessionCheckpoint | None = None,
) -> str | None:
    """Route an ``ask <id> <answer>`` reply into its session continuation.

    Returns None when *content* is not an ask reply (caller proceeds with
    normal routing). Otherwise returns the operator-facing response text:
    the continuation result on a winning claim, or the first-reply-wins /
    expiry / unknown-id verdict.
    """
    parsed = parse_ask_reply(content)
    if parsed is None:
        return None
    id_or_prefix, answer = parsed

    store = store or PendingAskStore()
    ask = store.find(id_or_prefix)
    if ask is None:
        # A bare "ask ..." message whose id matches nothing is most likely
        # ordinary chat ("ask cafe about deployment") — fall through to
        # normal routing. The explicit "/ask" form keeps the hard error.
        if not content.lstrip().startswith("/"):
            return None
        return f"Unknown ask id '{id_or_prefix}' — see pending asks with: geode ask list"

    outcome, resolved = store.resolve(ask.ask_id, answer, answered_by=answered_by)
    if outcome == ALREADY_ANSWERED and resolved is not None:
        return (
            f"Ask {resolved.ask_id} was already answered by {resolved.answered_by} "
            f"at {_fmt_ts(resolved.answered_at)} (first reply wins)."
        )
    if outcome == EXPIRED:
        return f"Ask {ask.ask_id} expired (older than {ASK_TTL_HOURS:.0f}h) — not resumed."
    if outcome != RESOLVED or resolved is None:
        return f"Ask {ask.ask_id} could not be resolved ({outcome})."

    if checkpoint is None:
        from core.memory.session_checkpoint import SessionCheckpoint as _Checkpoint

        checkpoint = _Checkpoint()
    state = checkpoint.load(resolved.session_id)
    if state is None:
        return (
            f"Answer recorded for ask {resolved.ask_id}, but its session checkpoint "
            f"({resolved.session_id}) is gone — no continuation was run."
        )
    try:
        text = await run_continuation(state, answer)
    except Exception as exc:
        log.warning("Ask %s continuation failed", resolved.ask_id, exc_info=True)
        return f"Answer recorded for ask {resolved.ask_id}, but the continuation failed: {exc}"
    return text or f"Ask {resolved.ask_id} answered; continuation produced no text."
