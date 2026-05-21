"""Mutator auto-trigger — OL-A1 (2026-05-22).

Connects the existing :class:`SelfImprovingLoopRunner` (manually invoked
pre-OL-A1) to the scheduler service so the loop fires on a cron schedule
without an operator at the keyboard.

The wrapper does three things on top of ``SelfImprovingLoopRunner.run_once``:

1. **Filesystem lock** (``~/.geode/self-improving-loop/auto_trigger.lock``
   via :mod:`fcntl.flock` LOCK_EX | LOCK_NB) — prevents two cron-fires (or
   one cron fire + one manual ``geode self-improve mutate``) from racing
   on the same SoT files. If acquisition fails (another holder), the
   firing is a no-op (logged at INFO).
2. **Min-interval gate** (``auto_trigger_last_run.txt``) — even when the
   lock is free, if the previous successful firing landed less than
   ``min_interval_minutes`` ago, skip. Cron expressions can over-fire
   on restart / clock skew; this is the cheap defensive floor.
3. **Source-aware dispatch is inherited** — the wrapper does NOT carry
   its own 4-backend (Claude Code / Codex CLI / Anthropic PAYG / OpenAI
   PAYG) selection. It calls :func:`SelfImprovingLoopRunner.run_once`,
   which already dispatches via PR-PAPERCLIP (#1433) based on
   ``[self_improving_loop.mutator].source``. One credential vocabulary.

The wrapper returns a status dict (instead of raising) so the
scheduler's :class:`HookEvent.TRIGGER_FIRED` handler does not crash the
scheduler loop when a single firing fails. Telemetry-wise, every
firing emits ``HookEvent.SELF_IMPROVING_AUTO_TRIGGER_*`` (out of scope
for OL-A1 — added in OL-A2).
"""

from __future__ import annotations

import fcntl
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.paths import GLOBAL_SELF_IMPROVING_LOOP_DIR

log = logging.getLogger(__name__)

__all__ = [
    "AUTO_TRIGGER_LOCK_PATH",
    "AUTO_TRIGGER_TIMESTAMP_PATH",
    "AUTO_TRIGGER_TRIGGER_ID",
    "AutoTriggerStatus",
    "acquire_auto_trigger_lock",
    "auto_trigger_mutator",
    "is_min_interval_satisfied",
    "read_last_run_timestamp",
    "register_auto_trigger",
    "release_auto_trigger_lock",
    "write_last_run_timestamp",
]

AUTO_TRIGGER_TRIGGER_ID = "self_improving_loop_auto_trigger"
"""Single canonical trigger_id used by the scheduler so operators can
identify the firing in ``/schedule list`` and the audit log."""

AUTO_TRIGGER_LOCK_PATH: Path = GLOBAL_SELF_IMPROVING_LOOP_DIR / "auto_trigger.lock"
"""Filesystem lockfile path. Lock is advisory (fcntl LOCK_EX | LOCK_NB)
so a kernel-level crash releases it automatically — no stale-lock
manual cleanup needed."""

AUTO_TRIGGER_TIMESTAMP_PATH: Path = GLOBAL_SELF_IMPROVING_LOOP_DIR / "auto_trigger_last_run.txt"
"""Plain-text Unix timestamp of the last *successful* firing. Failed
firings (lock-blocked, interval-blocked, run_once raised) deliberately
do NOT update this — only a successful mutation cycle counts so a
flapping config doesn't lock the schedule out for hours."""


@dataclass(frozen=True, slots=True)
class AutoTriggerStatus:
    """Return shape from :func:`auto_trigger_mutator`.

    Six terminal states:

    * ``fired`` — runner.run_once completed; ``mutation`` carries the
      Mutation summary (target_section + new_value len), timestamp
      updated.
    * ``lock_busy`` — another holder; no-op.
    * ``interval_blocked`` — last_run_timestamp is too recent.
    * ``runner_error`` — run_once raised; ``error`` carries the
      repr; timestamp NOT updated (next cron fire retries).
    * ``disabled`` — caller explicitly passed ``enabled=False``;
      defensive guard in case wiring misroutes.
    * ``parse_error`` — runner.run_once raised ``ValueError``
      (mutation parse / validation); ``error`` carries the message.
      Treated separately from ``runner_error`` so telemetry can
      distinguish "LLM produced garbage" from "infra crashed".
    """

    state: str
    detail: str = ""


def acquire_auto_trigger_lock(
    lock_path: Path | None = None,
) -> int | None:
    """Open + flock the auto-trigger lockfile.

    Returns the file descriptor (caller must release via
    :func:`release_auto_trigger_lock`) on success, ``None`` when the
    lock is already held by another process (graceful — no exception).
    """
    target = lock_path if lock_path is not None else AUTO_TRIGGER_LOCK_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_CREAT | os.O_WRONLY, 0o600)
    except OSError as exc:
        log.warning("auto_trigger: cannot open lockfile %s: %s", target, exc)
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        log.info("auto_trigger: lock %s already held; skipping firing", target)
        return None
    return fd


def release_auto_trigger_lock(fd: int) -> None:
    """Release the advisory lock + close the fd. Always-safe — best-
    effort; close failures are swallowed (the OS reaps the fd anyway
    on process exit)."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError as exc:
        log.debug("auto_trigger: LOCK_UN failed (fd=%d): %s", fd, exc)
    try:
        os.close(fd)
    except OSError as exc:
        log.debug("auto_trigger: close failed (fd=%d): %s", fd, exc)


def read_last_run_timestamp(timestamp_path: Path | None = None) -> float | None:
    """Read the last-run Unix timestamp from disk. Returns ``None`` when
    the file does not exist or is unparseable (treated as "never
    fired" — first-time bootstrap path)."""
    target = timestamp_path if timestamp_path is not None else AUTO_TRIGGER_TIMESTAMP_PATH
    try:
        raw = target.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return float(raw)
    except ValueError:
        log.warning("auto_trigger: %s contains non-numeric content; ignoring", target)
        return None


def write_last_run_timestamp(timestamp: float, timestamp_path: Path | None = None) -> bool:
    """Persist the timestamp atomically. Returns True on success,
    False when the write fails (logged at WARNING — not raised, the
    firing already succeeded)."""
    target = timestamp_path if timestamp_path is not None else AUTO_TRIGGER_TIMESTAMP_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{timestamp}\n", encoding="utf-8")
    except OSError as exc:
        log.warning("auto_trigger: failed to write last-run timestamp: %s", exc)
        return False
    return True


def is_min_interval_satisfied(
    *,
    min_interval_minutes: int,
    now: float | None = None,
    timestamp_path: Path | None = None,
) -> bool:
    """True when enough time has elapsed since the last fire (or when
    no previous fire is recorded). Operator-side gate that complements
    the lockfile.
    """
    last_run = read_last_run_timestamp(timestamp_path)
    if last_run is None:
        return True
    current = now if now is not None else time.time()
    elapsed_minutes = (current - last_run) / 60.0
    return elapsed_minutes >= min_interval_minutes


def auto_trigger_mutator(
    *,
    enabled: bool,
    min_interval_minutes: int,
    runner_factory: Callable[[], Any] | None = None,
    lock_path: Path | None = None,
    timestamp_path: Path | None = None,
    now: float | None = None,
) -> AutoTriggerStatus:
    """One mutator firing — guarded by lockfile + min-interval.

    Args:
        enabled: Defensive gate. When False, return ``disabled``
            without touching disk. The wiring layer should also avoid
            registering the trigger in this case; this is belt+suspenders.
        min_interval_minutes: Floor between successful firings (see
            :class:`SchedulerConfig.min_interval_minutes`).
        runner_factory: Zero-arg callable returning an object with
            ``run_once() -> Mutation`` method. Defaults to
            :class:`SelfImprovingLoopRunner` constructed with no args.
            Tests inject mocks; production wires the real runner.
        lock_path: Lockfile path override (tests).
        timestamp_path: Timestamp path override (tests).
        now: Wall-clock override (tests).

    Returns:
        :class:`AutoTriggerStatus` describing the terminal state. Never
        raises — exceptions inside ``run_once`` are caught and packed
        into the ``runner_error`` / ``parse_error`` states.
    """
    if not enabled:
        return AutoTriggerStatus(state="disabled")

    if not is_min_interval_satisfied(
        min_interval_minutes=min_interval_minutes,
        now=now,
        timestamp_path=timestamp_path,
    ):
        return AutoTriggerStatus(
            state="interval_blocked",
            detail=f"min_interval_minutes={min_interval_minutes}",
        )

    fd = acquire_auto_trigger_lock(lock_path)
    if fd is None:
        return AutoTriggerStatus(state="lock_busy")

    try:
        # Codex MCP catch (PR-OL-A1 fix-up): re-check interval AFTER
        # acquiring the lock. Otherwise a second process can pass the
        # pre-lock interval check using a stale timestamp, then acquire
        # the lock right after the first holder writes a fresh
        # timestamp and releases — both fires land < min_interval apart.
        if not is_min_interval_satisfied(
            min_interval_minutes=min_interval_minutes,
            now=now,
            timestamp_path=timestamp_path,
        ):
            return AutoTriggerStatus(
                state="interval_blocked",
                detail=f"min_interval_minutes={min_interval_minutes} (post-lock re-check)",
            )

        # Codex MCP catch (PR-OL-A1 fix-up): runner construction itself
        # can raise (lazy import failure, runner __init__ side-effects).
        # Catch here so the "never raises" contract holds — the lock is
        # still released by the outer finally.
        try:
            runner = _resolve_runner(runner_factory)
        except Exception as exc:
            log.exception("auto_trigger: runner factory raised")
            return AutoTriggerStatus(state="runner_error", detail=repr(exc))

        try:
            mutation = runner.run_once()
        except ValueError as exc:
            log.warning("auto_trigger: mutator parse/validation failure: %s", exc)
            return AutoTriggerStatus(state="parse_error", detail=str(exc))
        except Exception as exc:
            log.exception("auto_trigger: runner.run_once raised")
            return AutoTriggerStatus(state="runner_error", detail=repr(exc))

        current = now if now is not None else time.time()
        write_last_run_timestamp(current, timestamp_path)
        target_section = getattr(mutation, "target_section", "<unknown>")
        return AutoTriggerStatus(state="fired", detail=f"target_section={target_section}")
    finally:
        release_auto_trigger_lock(fd)


def _resolve_runner(factory: Callable[[], Any] | None) -> Any:
    """Build the runner. Lazy-imports :class:`SelfImprovingLoopRunner`
    so module import doesn't drag the runner's deps in at startup
    (cold-start budget — runner pulls anthropic adapter etc.)."""
    if factory is not None:
        return factory()
    from core.self_improving_loop.runner import SelfImprovingLoopRunner

    return SelfImprovingLoopRunner()


def register_auto_trigger(
    trigger_manager: Any,
    *,
    enabled: bool,
    cron: str,
    min_interval_minutes: int,
    runner_factory: Callable[[], Any] | None = None,
) -> bool:
    """Register the auto-trigger with the scheduler. No-op when disabled.

    Wiring contract: this is the *only* function `core/wiring/automation.py`
    needs to call. Returns True when the trigger was registered, False
    when ``enabled=False`` (so the wiring layer can log the skip).

    The callback closes over ``min_interval_minutes`` + ``runner_factory``
    so the scheduler's bare ``callback(data)`` invocation forwards into
    :func:`auto_trigger_mutator` with the right config. The callback
    swallows every exception (logs at WARNING) — `TriggerManager`'s own
    error isolation is the second layer of defense.
    """
    if not enabled:
        log.info("auto_trigger: [self_improving_loop.scheduler] enabled=False; skip register")
        return False

    from core.scheduler.triggers import TriggerConfig, TriggerType

    def _scheduler_callback(_data: dict[str, Any]) -> None:
        try:
            status = auto_trigger_mutator(
                enabled=True,
                min_interval_minutes=min_interval_minutes,
                runner_factory=runner_factory,
            )
            log.info(
                "auto_trigger fired: state=%s detail=%s",
                status.state,
                status.detail,
            )
        except Exception:
            log.exception("auto_trigger callback raised; scheduler loop continues")

    trigger_manager.register(
        TriggerConfig(
            trigger_id=AUTO_TRIGGER_TRIGGER_ID,
            trigger_type=TriggerType.SCHEDULED,
            name="Self-improving loop auto-trigger (OL-A1)",
            cron_expr=cron,
            callback=_scheduler_callback,
            enabled=True,
        )
    )
    log.info(
        "auto_trigger registered: cron=%r min_interval_minutes=%d",
        cron,
        min_interval_minutes,
    )
    return True
