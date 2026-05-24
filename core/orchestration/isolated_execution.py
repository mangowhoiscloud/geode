"""Isolated Execution — run callables in isolated contexts with PostToMain delivery.

Inspired by OpenClaw's isolated session pattern, this module provides:
- Isolated execution with timeout and error isolation
- PostToMain: structured result delivery via HookSystem
- PostToMainMode: summary (brief) or full (complete, truncated) output
- Concurrency control with configurable max parallel executions
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.hooks import HookEvent, HookSystem

log = logging.getLogger(__name__)


class PostToMainMode(Enum):
    """How results are posted back to the main session."""

    SUMMARY = "summary"  # Brief summary of execution result
    FULL = "full"  # Full output text, truncated at maxChars


@dataclass
class IsolationConfig:
    """Configuration for an isolated execution."""

    session_id: str = ""  # Auto-generated if empty
    timeout_s: float = 300.0  # Max execution time (5 min default)
    post_to_main: bool = True  # Whether to post result back
    post_mode: PostToMainMode = PostToMainMode.SUMMARY
    max_chars: int = 8000  # Max chars for full mode
    prefix: str = "Isolated"  # Prefix for posted messages
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IsolationResult:
    """Result from an isolated execution."""

    session_id: str
    success: bool
    output: str = ""  # Full output text
    summary: str = ""  # Brief summary
    error: str | None = None
    duration_ms: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, omitting None-valued fields."""
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}


class IsolatedRunner:
    """Execute callables in isolated contexts with PostToMain delivery.

    Supports two execution modes:
    - **Thread mode** (default): Run a callable in-process via daemon thread.
      Used for simple callbacks and tests.
    - **Subprocess mode**: Run a WorkerRequest in a child process via
      ``python -m core.agent.worker``. Used for sub-agent and scheduler
      workloads. Provides crash isolation and clean timeout via SIGKILL.

    Usage::

        runner = IsolatedRunner(hooks=hook_system)
        config = IsolationConfig(timeout_s=60, post_mode=PostToMainMode.FULL)
        result = await runner.arun(my_callable, args=("hello",), config=config)

        # Subprocess mode (pass WorkerRequest instead of callable)
        from core.agent.worker import WorkerRequest
        req = WorkerRequest(task_id="t-1", description="hello")
        result = await runner.arun(req, config=config)
    """

    MAX_RESULTS_CACHE = 200  # Evict oldest results beyond this limit
    SLOT_WAIT_S = 30.0  # Wait up to 30s for a lane slot
    KILL_WAIT_S = 5.0  # Wait for process death after SIGKILL

    # Subprocess env whitelist — only these vars are forwarded to child processes.
    # Prevents accidental leakage of secrets or shell-specific vars.
    _SUBPROCESS_ENV_WHITELIST: set[str] = {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "TERM",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "ZHIPUAI_API_KEY",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "GEODE_CONFIG_PATH",
        "GEODE_DATA_DIR",
    }

    def __init__(
        self,
        hooks: HookSystem | None = None,
        lane: Any | None = None,
    ) -> None:
        self._hooks = hooks
        self._lane = lane  # Lane("global") from unified LaneQueue
        self._results: dict[str, IsolationResult] = {}
        # Only async subprocess workers register here — thread-mode runs
        # via ``asyncio.to_thread`` and is not externally cancellable.
        self._active: dict[str, asyncio.subprocess.Process] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def arun(
        self,
        fn_or_request: Callable[..., Any] | Any,
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        config: IsolationConfig | None = None,
    ) -> IsolationResult:
        """Run *fn_or_request* asynchronously in an isolated context.

        Accepts either a callable (thread mode) or a WorkerRequest (subprocess mode).

        PR-Async-Phase-C step 3 (2026-05-22) — subprocess path now uses
        :meth:`_aexecute_subprocess` (native ``asyncio.create_subprocess_exec``)
        so the parent event loop is not pinned. Thread path stays via
        :func:`asyncio.to_thread`.
        """
        cfg = self._resolve_config(config)
        return await self._adispatch(fn_or_request, args, kwargs or {}, cfg)

    def list_active(self) -> list[str]:
        """Return session IDs of currently running executions."""
        with self._lock:
            return list(self._active.keys())

    def cancel(self, session_id: str) -> bool:
        """Cancel a running async subprocess session via SIGKILL.

        Returns True if the worker process was found alive and killed.
        Thread-mode runs (``arun(callable)``) are not externally
        cancellable in CPython and return False.

        PR-Async-Phase-C step 4b fix-up (2026-05-22) — after the sync
        ``run_async`` / ``_execute_subprocess`` paths were deleted,
        ``_active`` only holds ``asyncio.subprocess.Process`` instances
        (registered by :meth:`_aexecute_subprocess`). The cooperative
        ``_cancel_flags`` indirection is gone — async tasks should be
        cancelled via ``task.cancel()`` instead, which surfaces as
        ``asyncio.CancelledError`` inside ``_aexecute_subprocess`` and
        triggers the same kill+release path.
        """
        with self._lock:
            active = self._active.get(session_id)

        if active is None or active.returncode is not None:
            return False
        active.kill()
        log.info("Cancel requested for session %s", session_id)
        if self._hooks:
            self._hooks.trigger(
                HookEvent.EXECUTION_CANCELLED,
                {"session_id": session_id},
            )
        return True

    @property
    def active_count(self) -> int:
        """Number of currently running isolated executions."""
        with self._lock:
            return len(self._active)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_config(self, config: IsolationConfig | None) -> IsolationConfig:
        """Return config with a guaranteed session_id."""
        cfg = config or IsolationConfig()
        if not cfg.session_id:
            cfg = IsolationConfig(
                session_id=uuid.uuid4().hex[:12],
                timeout_s=cfg.timeout_s,
                post_to_main=cfg.post_to_main,
                post_mode=cfg.post_mode,
                max_chars=cfg.max_chars,
                prefix=cfg.prefix,
                metadata=dict(cfg.metadata),
            )
        return cfg

    def _acquire_slot(self, config: IsolationConfig) -> IsolationResult | None:
        """Acquire a lane slot. Returns an error result if timed out.

        Uses the ``global`` Lane from the unified LaneQueue when available.
        If no lane was injected, runs without concurrency gating (tests).
        """
        if self._lane is None:
            return None  # No gating (backward compat for tests)
        key = config.session_id
        acquired = self._lane.acquire_timeout(key, self.SLOT_WAIT_S)
        if not acquired:
            return IsolationResult(
                session_id=config.session_id,
                success=False,
                error=(
                    f"Lane '{self._lane.name}' full "
                    f"(max {self._lane.max_concurrent}) "
                    f"after {self.SLOT_WAIT_S}s wait"
                ),
                started_at=time.time(),
                completed_at=time.time(),
                metadata=dict(config.metadata),
            )
        return None

    def _release_slot(self, config: IsolationConfig) -> None:
        """Release a lane slot acquired by :meth:`_acquire_slot`."""
        if self._lane is not None:
            self._lane.manual_release(config.session_id)

    # ------------------------------------------------------------------
    # Thread mode (existing behavior, for callables and tests)
    # ------------------------------------------------------------------

    def _execute_thread(
        self,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        config: IsolationConfig,
    ) -> IsolationResult:
        """Execute *fn* in a daemon thread with timeout and error isolation."""
        slot_error = self._acquire_slot(config)
        if slot_error is not None:
            return slot_error
        acquired = True

        started = time.time()
        result_holder: list[IsolationResult] = []
        error_holder: list[str] = []

        def _target() -> None:
            try:
                raw = fn(*args, **kwargs)
                output = str(raw) if raw is not None else ""
                result_holder.append(
                    IsolationResult(
                        session_id=config.session_id,
                        success=True,
                        output=output,
                        started_at=started,
                        metadata=dict(config.metadata),
                    )
                )
            except Exception as exc:
                error_holder.append(str(exc))

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout=config.timeout_s)

        completed = time.time()
        duration_ms = (completed - started) * 1000

        try:
            if thread.is_alive():
                # Timeout — thread still running (zombie thread, known
                # limitation). The thread itself cannot be killed in
                # CPython; ``_active`` does not track threads after the
                # step-4b cleanup, so there is nothing to evict.
                log.warning(
                    "Zombie thread: session %s still running after timeout",
                    config.session_id,
                )
                result = IsolationResult(
                    session_id=config.session_id,
                    success=False,
                    error=f"Timeout after {config.timeout_s}s",
                    duration_ms=duration_ms,
                    started_at=started,
                    completed_at=completed,
                    metadata=dict(config.metadata),
                )
            elif error_holder:
                result = IsolationResult(
                    session_id=config.session_id,
                    success=False,
                    error=error_holder[0],
                    duration_ms=duration_ms,
                    started_at=started,
                    completed_at=completed,
                    metadata=dict(config.metadata),
                )
            elif result_holder:
                result = result_holder[0]
                result.completed_at = completed
                result.duration_ms = duration_ms
                result.summary = self._make_summary(result)
            else:
                # Shouldn't happen, but handle gracefully
                result = IsolationResult(
                    session_id=config.session_id,
                    success=True,
                    output="",
                    duration_ms=duration_ms,
                    started_at=started,
                    completed_at=completed,
                    metadata=dict(config.metadata),
                )

            if config.post_to_main:
                self._post_to_main(result, config)

            return result
        finally:
            if acquired:
                self._release_slot(config)

    # ------------------------------------------------------------------
    # Subprocess mode (WorkerRequest → python -m core.agent.worker)
    # async-native via ``asyncio.create_subprocess_exec``.
    # ------------------------------------------------------------------

    async def _aexecute_subprocess(
        self,
        request: Any,  # WorkerRequest
        config: IsolationConfig,
    ) -> IsolationResult:
        """Async subprocess execution via ``asyncio.create_subprocess_exec``.

        Uses :func:`asyncio.create_subprocess_exec` so the parent
        process's event loop is not pinned waiting for the worker
        subprocess to finish.

        * Lane-slot acquisition gates concurrency via the shared
          ``Lane`` semaphore. The blocking acquire is wrapped in
          :func:`asyncio.shield` so that a mid-await ``CancelledError``
          cannot drop the slot mid-acquisition — the underlying
          ``to_thread`` is drained in the ``finally`` block and the
          slot is released if it ended up acquired.
        * Timeout via ``asyncio.wait_for(proc.communicate(input), ...)``;
          on timeout, ``proc.kill()`` + ``await proc.wait()`` guarantee
          process death before the slot is released.
        * stderr persisted to ``~/.geode/workers/<sid>.stderr.log``.
        """
        # PR-Async-Phase-C step 4b fix-up — Codex MCP CRITICAL catch
        # (2026-05-22). Previously the slot acquire was a bare
        # ``await asyncio.to_thread(...)``; cancelling the coroutine
        # while the underlying thread was still blocked on the lane
        # semaphore left an orphan slot (the thread eventually woke
        # and claimed the slot, but the cancelled coroutine never
        # reached the ``finally`` release). Shielding the acquire +
        # draining the task on cancel closes that hole.
        acquired = False
        started = time.time()
        proc: asyncio.subprocess.Process | None = None
        acquire_task: asyncio.Task[IsolationResult | None] = asyncio.create_task(
            asyncio.to_thread(self._acquire_slot, config),
            name=f"isolated-acquire:{config.session_id}",
        )

        try:
            slot_error: IsolationResult | None = await asyncio.shield(acquire_task)
            if slot_error is not None:
                return slot_error
            acquired = True
            safe_env = {k: v for k, v in os.environ.items() if k in self._SUBPROCESS_ENV_WHITELIST}
            # PR-Q (2026-05-24) — forward the parent's active run_dir
            # binding to the subprocess so its observability writers
            # (``_save_result_backup``, ``SessionTranscript``) land
            # output under ``<run_dir>/sub_agents/<task_id>/`` instead
            # of the legacy ``~/.geode/workers/`` + ``~/.geode/transcripts/``
            # global pools. Empty when no orchestrator opened a
            # ``run_dir_scope`` — child falls back to legacy paths.
            from core.observability.run_dir import RUN_DIR_ENV, get_active_run_dir

            active_run_dir = get_active_run_dir()
            if active_run_dir is not None:
                safe_env[RUN_DIR_ENV] = str(active_run_dir)
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "core.agent.worker",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=safe_env,
            )

            with self._lock:
                self._active[config.session_id] = proc

            request_bytes = json.dumps(request.to_dict()).encode("utf-8") + b"\n"
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=request_bytes),
                    timeout=config.timeout_s,
                )
            except TimeoutError:
                # Clean timeout: kill + await death before releasing slot.
                proc.kill()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=self.KILL_WAIT_S)
                except TimeoutError:
                    log.warning(
                        "Async subprocess %s did not die within %.1fs after kill",
                        config.session_id,
                        self.KILL_WAIT_S,
                    )
                completed = time.time()
                duration_ms = (completed - started) * 1000
                log.warning(
                    "Async subprocess session %s killed after %.1fs timeout",
                    config.session_id,
                    config.timeout_s,
                )
                return IsolationResult(
                    session_id=config.session_id,
                    success=False,
                    error=f"Timeout after {config.timeout_s}s (process killed)",
                    duration_ms=duration_ms,
                    started_at=started,
                    completed_at=completed,
                    metadata=dict(config.metadata),
                )

            completed = time.time()
            duration_ms = (completed - started) * 1000

            if stderr_bytes:
                await asyncio.to_thread(self._save_stderr, config.session_id, stderr_bytes)

            stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
            if not stdout_text:
                return IsolationResult(
                    session_id=config.session_id,
                    success=False,
                    error="Worker produced no output on stdout",
                    duration_ms=duration_ms,
                    started_at=started,
                    completed_at=completed,
                    metadata=dict(config.metadata),
                )

            result_data = json.loads(stdout_text)
            result = IsolationResult(
                session_id=config.session_id,
                success=result_data.get("success", False),
                output=result_data.get("output", ""),
                summary=result_data.get("summary", ""),
                error=result_data.get("error"),
                duration_ms=duration_ms,
                started_at=started,
                completed_at=completed,
                metadata=dict(config.metadata),
            )

            if config.post_to_main:
                self._post_to_main(result, config)

            return result

        except asyncio.CancelledError:
            # CancelledError is BaseException (not Exception) on 3.8+, so
            # the broader handler below would miss it. Kill the worker
            # before re-raising so cancellation never orphans a child.
            if proc is not None and proc.returncode is None:
                proc.kill()
                import contextlib as _cl

                with _cl.suppress(TimeoutError):
                    await asyncio.wait_for(proc.wait(), timeout=self.KILL_WAIT_S)
            raise
        except Exception as exc:
            if proc is not None and proc.returncode is None:
                proc.kill()
                import contextlib as _cl

                with _cl.suppress(TimeoutError):
                    await asyncio.wait_for(proc.wait(), timeout=self.KILL_WAIT_S)
            completed = time.time()
            duration_ms = (completed - started) * 1000
            return IsolationResult(
                session_id=config.session_id,
                success=False,
                error=f"Subprocess error: {type(exc).__name__}: {exc}",
                duration_ms=duration_ms,
                started_at=started,
                completed_at=completed,
                metadata=dict(config.metadata),
            )
        finally:
            # Hard guarantee: even if a path above missed it, kill any
            # still-live child before releasing the lane slot.
            if proc is not None and proc.returncode is None:
                proc.kill()
            with self._lock:
                self._active.pop(config.session_id, None)
            # Drain the (possibly still-running) acquire_task so a
            # mid-await cancel cannot leak a lane slot — see the
            # CRITICAL note at the top of this method.
            if not acquire_task.done():
                import contextlib as _cl

                with _cl.suppress(asyncio.CancelledError, Exception):
                    slot_error_late = await acquire_task
                    if slot_error_late is None:
                        acquired = True
            elif not acquired and acquire_task.cancelled() is False:
                # acquire_task completed before cancel arrived but
                # we never reached ``acquired = True``. Inspect.
                import contextlib as _cl

                with _cl.suppress(Exception):
                    if acquire_task.result() is None:
                        acquired = True
            if acquired:
                await asyncio.to_thread(self._release_slot, config)

    async def _adispatch(
        self,
        fn_or_request: Callable[..., Any] | Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        config: IsolationConfig,
    ) -> IsolationResult:
        """Async router — WorkerRequest → :meth:`_aexecute_subprocess`,
        callable → thread (via :func:`asyncio.to_thread`)."""
        from core.agent.worker import WorkerRequest

        if isinstance(fn_or_request, WorkerRequest):
            return await self._aexecute_subprocess(fn_or_request, config)
        return await asyncio.to_thread(self._execute_thread, fn_or_request, args, kwargs, config)

    @staticmethod
    def _save_stderr(session_id: str, stderr_bytes: bytes) -> None:
        """Persist subprocess stderr for debugging.

        PR-Q (2026-05-24) — when an active run_dir is bound, the stderr
        log lands under ``<run_dir>/sub_agents/<session_id>/stderr.log``
        so it's co-located with the sub-agent's ``result.json`` +
        ``dialogue.jsonl`` for that cycle. Otherwise falls back to the
        legacy global ``~/.geode/workers/<session_id>.stderr.log`` pool.
        """
        from core.observability.run_dir import resolve_sub_agent_path
        from core.paths import GLOBAL_WORKERS_DIR

        try:
            stderr_path = resolve_sub_agent_path(session_id, "stderr.log")
            if stderr_path is None:
                GLOBAL_WORKERS_DIR.mkdir(parents=True, exist_ok=True)
                stderr_path = GLOBAL_WORKERS_DIR / f"{session_id}.stderr.log"
            stderr_path.write_bytes(stderr_bytes)
        except Exception:
            log.debug("Failed to save stderr for %s", session_id, exc_info=True)

    def _post_to_main(self, result: IsolationResult, config: IsolationConfig) -> None:
        """Deliver the execution result via HookSystem."""
        if self._hooks is None:
            log.debug("No hook system configured — skipping PostToMain for %s", result.session_id)
            return

        if config.post_mode is PostToMainMode.SUMMARY:
            message = result.summary or self._make_summary(result)
        else:
            message = self._truncate(result.output, config.max_chars)

        data: dict[str, Any] = {
            "source": "isolated_execution",
            "session_id": result.session_id,
            "prefix": config.prefix,
            "mode": config.post_mode.value,
            "message": message,
            "success": result.success,
            "duration_ms": result.duration_ms,
        }

        try:
            self._hooks.trigger(HookEvent.SUBAGENT_COMPLETED, data)
            log.debug(
                "PostToMain delivered for session %s (mode=%s)",
                result.session_id,
                config.post_mode.value,
            )
        except Exception:
            log.exception("PostToMain failed for session %s", result.session_id)

    def _truncate(self, text: str, max_chars: int) -> str:
        """Truncate text to *max_chars*, appending an indicator if trimmed."""
        if len(text) <= max_chars:
            return text
        suffix = f"... [truncated at {max_chars} chars]"
        return text[: max_chars - len(suffix)] + suffix

    def _make_summary(self, result: IsolationResult) -> str:
        """Generate a brief summary line for an IsolationResult."""
        status = "OK" if result.success else "FAIL"
        chars = len(result.output)
        ms = result.duration_ms
        parts = [f"[{status}]", f"{ms:.0f}ms"]
        if result.error:
            parts.append(f"error={result.error}")
        else:
            parts.append(f"{chars} chars")
        return " | ".join(parts)
