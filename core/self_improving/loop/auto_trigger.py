"""Mutator auto-trigger — OL-A1 (2026-05-22).

Connects the existing :class:`SelfImprovingLoopRunner` (manually invoked
pre-OL-A1) to the scheduler service so the loop fires on a cron schedule
without an operator at the keyboard.

The wrapper does three things on top of ``SelfImprovingLoopRunner.run_once``:

1. **Filesystem lock** (``~/.geode/autoresearch/handoff/auto_trigger.lock``
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
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.paths import GLOBAL_AUTORESEARCH_HANDOFF_DIR

log = logging.getLogger(__name__)

__all__ = [
    "AUTO_TRIGGER_HISTORY_PATH",
    "AUTO_TRIGGER_LOCK_PATH",
    "AUTO_TRIGGER_TIMESTAMP_PATH",
    "AUTO_TRIGGER_TRIGGER_ID",
    "STATE_TO_HOOK_EVENT",
    "AutoTriggerStatus",
    "acquire_auto_trigger_lock",
    "append_history_entry",
    "auto_trigger_mutator",
    "count_fired_generations",
    "is_min_interval_satisfied",
    "read_last_run_timestamp",
    "register_auto_trigger",
    "release_auto_trigger_lock",
    "write_last_run_timestamp",
]

AUTO_TRIGGER_TRIGGER_ID = "self_improving_loop_auto_trigger"
"""Single canonical trigger_id used by the scheduler so operators can
identify the firing in ``/schedule list`` and the audit log."""

AUTO_TRIGGER_LOCK_PATH: Path = GLOBAL_AUTORESEARCH_HANDOFF_DIR / "auto_trigger.lock"
"""Filesystem lockfile path. Lock is advisory (fcntl LOCK_EX | LOCK_NB)
so a kernel-level crash releases it automatically — no stale-lock
manual cleanup needed."""

AUTO_TRIGGER_TIMESTAMP_PATH: Path = GLOBAL_AUTORESEARCH_HANDOFF_DIR / "auto_trigger_last_run.txt"
"""Plain-text Unix timestamp of the last *successful* firing. Failed
firings (lock-blocked, interval-blocked, run_once raised) deliberately
do NOT update this — only a successful mutation cycle counts so a
flapping config doesn't lock the schedule out for hours."""

AUTO_TRIGGER_HISTORY_PATH: Path = GLOBAL_AUTORESEARCH_HANDOFF_DIR / "auto_trigger_history.jsonl"
"""Append-only JSONL audit log — one row per firing (terminal state).

Schema: ``{"ts": float, "state": str, "detail": str, "trigger_id": str}``.

Unlike :data:`AUTO_TRIGGER_TIMESTAMP_PATH` which records only
*successful* fires for the interval gate, the history log captures
**every** firing including no-ops (``lock_busy`` / ``interval_blocked``
/ ``disabled``) and errors. OL-A3 ``geode self-improve audit`` viewer
consumes this file to render the auto-trigger timeline.

Stored under ``~/.geode/autoresearch/handoff/`` (outside the repo) so
the file is operator-private and not subject to the repo's
``.gitignore`` rules — no "claims to be git-tracked but isn't" risk."""


STATE_TO_HOOK_EVENT: dict[str, str] = {
    "fired": "SELF_IMPROVING_AUTO_TRIGGER_FIRED",
    "lock_busy": "SELF_IMPROVING_AUTO_TRIGGER_LOCK_BUSY",
    "interval_blocked": "SELF_IMPROVING_AUTO_TRIGGER_INTERVAL_BLOCKED",
    "runner_error": "SELF_IMPROVING_AUTO_TRIGGER_RUNNER_ERROR",
    "parse_error": "SELF_IMPROVING_AUTO_TRIGGER_PARSE_ERROR",
    # PR-MAX-GEN (2026-05-26) — generation cap state. HookEvent reserved
    # in ``core/hooks/system.py`` alongside the sibling auto-trigger
    # events; same ``{trigger_id, ts, detail}`` payload schema.
    "max_generation_reached": "SELF_IMPROVING_AUTO_TRIGGER_MAX_GENERATION_REACHED",
}
"""Maps terminal :class:`AutoTriggerStatus.state` → HookEvent enum name.

The ``disabled`` state is intentionally NOT in this map — when the
defensive guard at the top of :func:`auto_trigger_mutator` returns
early, the wiring layer should have already prevented registration
(``enabled=False`` skips ``trigger_manager.register``). Emitting
``disabled`` would generate a useless event on every cron tick from
some misconfigured caller. The wiring's own startup log line is the
SoT for "trigger was registered or skipped"."""


@dataclass(frozen=True, slots=True)
class AutoTriggerStatus:
    """Return shape from :func:`auto_trigger_mutator`.

    Seven terminal states:

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
    * ``max_generation_reached`` — PR-MAX-GEN (2026-05-26):
      ``max_generation`` was set non-zero and the auto-trigger
      history already contains that many ``fired`` rows. Hard stop
      on unbounded firing. ``detail`` carries ``current/max``.
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


def count_fired_generations(history_path: Path | None = None) -> int:
    """Count ``state="fired"`` rows in the auto-trigger history log.

    PR-MAX-GEN (2026-05-26) — Phase A audit (§5.6) found that
    ``auto_trigger_mutator`` had no max-generation gate, only the
    ``min_interval_minutes`` floor. With min_interval=60 and cron fires
    every hour, a misconfigured operator could accumulate hundreds of
    fired generations without any hard stop. This counter is the data
    feed for the new ``max_generation`` gate.

    Best-effort read — missing file / malformed JSON / non-dict rows
    are all skipped silently. The audit log is append-only so future-
    proof: each call re-counts (no in-memory cache invalidation).

    Returns 0 when the history log is absent (fresh repo / never fired).
    """
    target = history_path if history_path is not None else AUTO_TRIGGER_HISTORY_PATH
    if not target.is_file():
        return 0
    n = 0
    try:
        with target.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and row.get("state") == "fired":
                    n += 1
    except OSError:
        log.warning("auto_trigger: history read failed", exc_info=True)
        return n
    return n


def append_history_entry(
    *,
    state: str,
    detail: str,
    ts: float,
    trigger_id: str = AUTO_TRIGGER_TRIGGER_ID,
    history_path: Path | None = None,
) -> bool:
    """Append one JSONL row to the auto-trigger history log.

    Best-effort: any OSError (parent missing, disk full, permission
    denied) is logged at WARNING and the function returns False. The
    caller (:func:`auto_trigger_mutator`) ignores the return value
    because telemetry failure must not affect the state machine.

    Codex MCP PR-OL-C2 lesson applied — mkdir + write_text inside the
    same try block.
    """
    target = history_path if history_path is not None else AUTO_TRIGGER_HISTORY_PATH
    row = {"ts": ts, "state": state, "detail": detail, "trigger_id": trigger_id}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        log.warning("auto_trigger: history append failed: %s", exc)
        return False
    return True


def _emit_state_event(
    hooks: Any,
    *,
    state: str,
    detail: str,
    ts: float,
    trigger_id: str,
) -> None:
    """Emit the HookEvent variant for the given terminal state.

    ``hooks`` is the :class:`core.hooks.HookSystem` instance (typed as
    Any to avoid the import cost at module load — telemetry must not
    drag the hook system into the cold path of the manual REPL caller).
    When ``hooks`` is None, the function is a no-op so unit tests and
    one-off CLI invocations can use the auto-trigger without wiring
    the hook system.

    Exception isolation: a misbehaving hook handler must NOT crash the
    auto-trigger. We swallow any exception and log at WARNING — same
    contract as :meth:`HookSystem.trigger` itself, which also isolates,
    but defending against a buggy custom hook injection.
    """
    if hooks is None:
        return
    hook_event_name = STATE_TO_HOOK_EVENT.get(state)
    if hook_event_name is None:
        return  # "disabled" — intentionally not telemetry-emitted
    try:
        from core.hooks import HookEvent

        event = getattr(HookEvent, hook_event_name)
        hooks.trigger(event, {"trigger_id": trigger_id, "ts": ts, "detail": detail})
    except Exception:
        log.exception("auto_trigger: hook emit failed for state=%s", state)


def _finalize_status(
    state: str,
    detail: str,
    *,
    hooks: Any,
    history_path: Path | None,
    ts: float,
    trigger_id: str = AUTO_TRIGGER_TRIGGER_ID,
) -> AutoTriggerStatus:
    """Single exit point — emit HookEvent + append history + return status.

    Every ``return AutoTriggerStatus(...)`` in :func:`auto_trigger_mutator`
    goes through this helper so the three side-effects (hook, audit
    log, return value) cannot drift apart.
    """
    _emit_state_event(hooks, state=state, detail=detail, ts=ts, trigger_id=trigger_id)
    append_history_entry(
        state=state, detail=detail, ts=ts, trigger_id=trigger_id, history_path=history_path
    )
    return AutoTriggerStatus(state=state, detail=detail)


def auto_trigger_mutator(
    *,
    enabled: bool,
    min_interval_minutes: int,
    max_generation: int = 0,
    runner_factory: Callable[[], Any] | None = None,
    lock_path: Path | None = None,
    timestamp_path: Path | None = None,
    history_path: Path | None = None,
    hooks: Any = None,
    now: float | None = None,
) -> AutoTriggerStatus:
    """One mutator firing — guarded by lockfile + min-interval + max-generation.

    Args:
        enabled: Defensive gate. When False, return ``disabled``
            without touching disk. The wiring layer should also avoid
            registering the trigger in this case; this is belt+suspenders.
        min_interval_minutes: Floor between successful firings (see
            :class:`SchedulerConfig.min_interval_minutes`).
        max_generation: PR-MAX-GEN (2026-05-26) — hard cap on total
            ``fired`` rows in the history log. When non-zero and the
            current count is at or above the cap, return
            ``max_generation_reached`` without firing. ``0`` (default)
            disables the cap — legacy unbounded behaviour preserved.
        runner_factory: Zero-arg callable returning an object with
            ``run_once() -> Mutation`` method. Defaults to
            :class:`SelfImprovingLoopRunner` constructed with no args.
            Tests inject mocks; production wires the real runner.
        lock_path: Lockfile path override (tests).
        timestamp_path: Timestamp path override (tests).
        history_path: JSONL audit log path override (tests).
        hooks: :class:`HookSystem` instance. When provided, every
            terminal state (except ``disabled``) emits a
            ``SELF_IMPROVING_AUTO_TRIGGER_*`` event. None → no telemetry
            (graceful for unit tests / manual CLI use).
        now: Wall-clock override (tests).

    Returns:
        :class:`AutoTriggerStatus` describing the terminal state. Never
        raises — exceptions inside ``run_once`` are caught and packed
        into the ``runner_error`` / ``parse_error`` states.
    """
    ts_now = now if now is not None else time.time()
    if not enabled:
        # ``disabled`` is the only state that skips telemetry + history
        # (see STATE_TO_HOOK_EVENT docstring for rationale).
        return AutoTriggerStatus(state="disabled")

    # PR-MAX-GEN (2026-05-26) — generation cap. Evaluated BEFORE the
    # interval gate so a misconfigured cron with min_interval=0 still
    # hits the cap, and BEFORE the lock so a saturated history doesn't
    # consume the lock for a no-op fire. ``0`` means unlimited.
    if max_generation > 0:
        fired_count = count_fired_generations(history_path=history_path)
        if fired_count >= max_generation:
            return _finalize_status(
                "max_generation_reached",
                f"{fired_count}/{max_generation}",
                hooks=hooks,
                history_path=history_path,
                ts=ts_now,
            )

    if not is_min_interval_satisfied(
        min_interval_minutes=min_interval_minutes,
        now=now,
        timestamp_path=timestamp_path,
    ):
        return _finalize_status(
            "interval_blocked",
            f"min_interval_minutes={min_interval_minutes}",
            hooks=hooks,
            history_path=history_path,
            ts=ts_now,
        )

    fd = acquire_auto_trigger_lock(lock_path)
    if fd is None:
        return _finalize_status(
            "lock_busy",
            "",
            hooks=hooks,
            history_path=history_path,
            ts=ts_now,
        )

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
            return _finalize_status(
                "interval_blocked",
                f"min_interval_minutes={min_interval_minutes} (post-lock re-check)",
                hooks=hooks,
                history_path=history_path,
                ts=ts_now,
            )

        # PR-MAX-GEN (2026-05-26) Codex MCP must-fix #2 — re-check the
        # generation cap AFTER acquiring the lock for the same reason
        # the interval check does: two parallel callers can both read
        # the pre-lock count as N-1, both proceed to fire, and overshoot
        # the cap by 1. The post-lock recheck reads the freshly-written
        # history (the previous holder appends + releases atomically) so
        # the second caller sees count=N and blocks cleanly.
        if max_generation > 0:
            fired_count = count_fired_generations(history_path=history_path)
            if fired_count >= max_generation:
                return _finalize_status(
                    "max_generation_reached",
                    f"{fired_count}/{max_generation} (post-lock re-check)",
                    hooks=hooks,
                    history_path=history_path,
                    ts=ts_now,
                )

        # Codex MCP catch (PR-OL-A1 fix-up): runner construction itself
        # can raise (lazy import failure, runner __init__ side-effects).
        try:
            runner = _resolve_runner(runner_factory)
        except Exception as exc:
            log.exception("auto_trigger: runner factory raised")
            return _finalize_status(
                "runner_error",
                repr(exc),
                hooks=hooks,
                history_path=history_path,
                ts=ts_now,
            )

        try:
            mutation = runner.run_once()
        except ValueError as exc:
            log.warning("auto_trigger: mutator parse/validation failure: %s", exc)
            return _finalize_status(
                "parse_error",
                str(exc),
                hooks=hooks,
                history_path=history_path,
                ts=ts_now,
            )
        except Exception as exc:
            log.exception("auto_trigger: runner.run_once raised")
            return _finalize_status(
                "runner_error",
                repr(exc),
                hooks=hooks,
                history_path=history_path,
                ts=ts_now,
            )

        write_last_run_timestamp(ts_now, timestamp_path)
        target_section = getattr(mutation, "target_section", "<unknown>")
        return _finalize_status(
            "fired",
            f"target_section={target_section}",
            hooks=hooks,
            history_path=history_path,
            ts=ts_now,
        )
    finally:
        release_auto_trigger_lock(fd)


def _resolve_runner(factory: Callable[[], Any] | None) -> Any:
    """Build the runner. Lazy-imports :class:`SelfImprovingLoopRunner`
    so module import doesn't drag the runner's deps in at startup
    (cold-start budget — runner pulls anthropic adapter etc.)."""
    if factory is not None:
        return factory()
    from core.self_improving.loop.runner import SelfImprovingLoopRunner

    return SelfImprovingLoopRunner()


def register_auto_trigger(
    trigger_manager: Any,
    *,
    enabled: bool,
    cron: str,
    min_interval_minutes: int,
    max_generation: int = 0,
    runner_factory: Callable[[], Any] | None = None,
    hooks: Any = None,
) -> bool:
    """Register the auto-trigger with the scheduler. No-op when disabled.

    Wiring contract: this is the *only* function `core/wiring/automation.py`
    needs to call. Returns True when the trigger was registered, False
    when ``enabled=False`` (so the wiring layer can log the skip).

    The callback closes over ``min_interval_minutes`` +
    ``max_generation`` + ``runner_factory`` + ``hooks`` so the
    scheduler's bare ``callback(data)`` invocation forwards into
    :func:`auto_trigger_mutator` with the right config and telemetry
    sink. The callback swallows every exception (logs at WARNING) —
    `TriggerManager`'s own error isolation is the second layer of
    defense.

    PR-MAX-GEN (2026-05-26) — added ``max_generation`` so the wiring
    layer can pass the scheduler config knob through to the mutator
    cap gate. Default ``0`` preserves legacy unbounded behaviour.
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
                max_generation=max_generation,
                runner_factory=runner_factory,
                hooks=hooks,
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
