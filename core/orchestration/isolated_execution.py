"""Isolated Execution — run callables in isolated contexts with PostToMain delivery.

Inspired by OpenClaw's isolated session pattern, this module provides:
- Isolated execution with timeout and error isolation
- PostToMain: structured result delivery via HookSystem
- PostToMainMode: summary (brief) or full (complete, truncated) output
- Concurrency control with configurable max parallel executions
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
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
        result = runner.run(my_callable, args=("hello",), config=config)

        # Subprocess mode (pass WorkerRequest instead of callable)
        from core.agent.worker import WorkerRequest
        req = WorkerRequest(task_id="t-1", description="hello")
        result = runner.run(req, config=config)
    """

    MAX_CONCURRENT = 5  # Max parallel isolated executions
    MAX_RESULTS_CACHE = 200  # Evict oldest results beyond this limit
    SEMAPHORE_WAIT_S = 30.0  # Wait up to 30s for a slot (was 0 = immediate reject)
    KILL_WAIT_S = 5.0  # Wait for process death after SIGKILL

    # Subprocess env whitelist — only these vars are forwarded to child processes.
    # Prevents accidental leakage of secrets or shell-specific vars.
    _SUBPROCESS_ENV_WHITELIST: set[str] = {
        "PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM",
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ZHIPUAI_API_KEY",
        "PYTHONPATH", "VIRTUAL_ENV",
    }

    def __init__(self, hooks: HookSystem | None = None) -> None:
        self._hooks = hooks
        self._results: dict[str, IsolationResult] = {}
        self._active: dict[str, threading.Thread | subprocess.Popen[bytes]] = {}
        self._cancel_flags: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(self.MAX_CONCURRENT)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        fn_or_request: Callable[..., Any] | Any,
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        config: IsolationConfig | None = None,
    ) -> IsolationResult:
        """Run *fn_or_request* synchronously in an isolated context.

        Accepts either a callable (thread mode) or a WorkerRequest (subprocess mode).
        """
        cfg = self._resolve_config(config)
        return self._dispatch(fn_or_request, args, kwargs or {}, cfg)

    def run_async(
        self,
        fn_or_request: Callable[..., Any] | Any,
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        config: IsolationConfig | None = None,
    ) -> str:
        """Run *fn_or_request* in background. Returns session_id for later retrieval.

        Accepts either a callable (thread mode) or a WorkerRequest (subprocess mode).
        """
        cfg = self._resolve_config(config)
        session_id = cfg.session_id

        cancel_flag = threading.Event()
        with self._lock:
            self._cancel_flags[session_id] = cancel_flag

        def _worker() -> None:
            result = self._dispatch(fn_or_request, args, kwargs or {}, cfg)
            with self._lock:
                self._results[session_id] = result
                self._active.pop(session_id, None)
                self._cancel_flags.pop(session_id, None)
                # Evict oldest results to prevent unbounded growth
                if len(self._results) > self.MAX_RESULTS_CACHE:
                    oldest = next(iter(self._results))
                    self._results.pop(oldest, None)

        thread = threading.Thread(target=_worker, name=f"isolated-{session_id}", daemon=True)
        with self._lock:
            self._active[session_id] = thread
        thread.start()
        return session_id

    def get_result(self, session_id: str) -> IsolationResult | None:
        """Retrieve the result for a completed async execution."""
        with self._lock:
            return self._results.get(session_id)

    def list_active(self) -> list[str]:
        """Return session IDs of currently running executions."""
        with self._lock:
            return list(self._active.keys())

    def cancel(self, session_id: str) -> bool:
        """Cancel a running session. Returns True if found.

        For thread mode: sets the cooperative cancel flag.
        For subprocess mode: kills the child process (SIGKILL).
        """
        with self._lock:
            flag = self._cancel_flags.get(session_id)
            active = self._active.get(session_id)

        cancelled = False
        # Cooperative cancel for threads
        if flag is not None:
            flag.set()
            cancelled = True
        # Forceful kill for subprocesses
        if isinstance(active, subprocess.Popen) and active.poll() is None:
            active.kill()
            cancelled = True

        if cancelled:
            log.info("Cancel requested for session %s", session_id)
        return cancelled

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

    def _dispatch(
        self,
        fn_or_request: Callable[..., Any] | Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        config: IsolationConfig,
    ) -> IsolationResult:
        """Route to thread or subprocess execution based on input type."""
        # Import here to avoid circular import at module level
        from core.agent.worker import WorkerRequest

        if isinstance(fn_or_request, WorkerRequest):
            return self._execute_subprocess(fn_or_request, config)
        return self._execute_thread(fn_or_request, args, kwargs, config)

    def _acquire_slot(self, config: IsolationConfig) -> IsolationResult | None:
        """Acquire a semaphore slot. Returns an error result if timed out."""
        acquired = self._semaphore.acquire(timeout=self.SEMAPHORE_WAIT_S)
        if not acquired:
            return IsolationResult(
                session_id=config.session_id,
                success=False,
                error=(
                    f"Concurrency limit reached (max {self.MAX_CONCURRENT}) "
                    f"after {self.SEMAPHORE_WAIT_S}s wait"
                ),
                started_at=time.time(),
                completed_at=time.time(),
                metadata=dict(config.metadata),
            )
        return None

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

        # Capture cancel event before thread creation to avoid
        # a race condition on self._cancel_flags inside the thread.
        with self._lock:
            cancel_event = self._cancel_flags.get(config.session_id)

        def _target() -> None:
            try:
                # Check cancel flag before execution (uses captured value)
                if cancel_event and cancel_event.is_set():
                    error_holder.append("Cancelled before execution")
                    return
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
                # Timeout — thread still running (zombie thread, known limitation).
                # Clean up tracking state so the zombie doesn't hold a slot
                # in _active / _cancel_flags.  The thread itself cannot be
                # killed in CPython, but at least we stop tracking it.
                with self._lock:
                    self._active.pop(config.session_id, None)
                    self._cancel_flags.pop(config.session_id, None)
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
                self._semaphore.release()

    # ------------------------------------------------------------------
    # Subprocess mode (WorkerRequest → python -m core.agent.worker)
    # ------------------------------------------------------------------

    def _execute_subprocess(
        self,
        request: Any,  # WorkerRequest (typed as Any to avoid circular import at annotation level)
        config: IsolationConfig,
    ) -> IsolationResult:
        """Execute a WorkerRequest in a child process with clean timeout via SIGKILL.

        Eliminates zombie thread problem: process.kill() guarantees termination,
        so the semaphore is only released after confirmed process death.
        """
        slot_error = self._acquire_slot(config)
        if slot_error is not None:
            return slot_error
        acquired = True

        started = time.time()
        proc: subprocess.Popen[bytes] | None = None

        try:
            safe_env = {
                k: v for k, v in os.environ.items()
                if k in self._SUBPROCESS_ENV_WHITELIST
            }
            proc = subprocess.Popen(  # noqa: S603 — fixed args, no untrusted input
                [sys.executable, "-m", "core.agent.worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=safe_env,
            )

            # Track process for cancel()
            with self._lock:
                self._active[config.session_id] = proc

            # Send request and wait for result
            request_bytes = json.dumps(request.to_dict()).encode("utf-8") + b"\n"
            stdout_bytes, stderr_bytes = proc.communicate(
                input=request_bytes,
                timeout=config.timeout_s,
            )

            completed = time.time()
            duration_ms = (completed - started) * 1000

            # Save stderr for debugging
            if stderr_bytes:
                self._save_stderr(config.session_id, stderr_bytes)

            # Parse result
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

        except subprocess.TimeoutExpired:
            # Clean timeout: kill process, wait for confirmed death
            if proc is not None:
                proc.kill()
                proc.wait(timeout=self.KILL_WAIT_S)
            completed = time.time()
            duration_ms = (completed - started) * 1000
            log.warning(
                "Subprocess session %s killed after %.1fs timeout",
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
        except Exception as exc:
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=self.KILL_WAIT_S)
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
            with self._lock:
                self._active.pop(config.session_id, None)
            if acquired:
                self._semaphore.release()

    @staticmethod
    def _save_stderr(session_id: str, stderr_bytes: bytes) -> None:
        """Save subprocess stderr to ~/.geode/workers/ for debugging."""
        try:
            worker_dir = Path.home() / ".geode" / "workers"
            worker_dir.mkdir(parents=True, exist_ok=True)
            path = worker_dir / f"{session_id}.stderr.log"
            path.write_bytes(stderr_bytes)
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
            self._hooks.trigger(HookEvent.PIPELINE_END, data)
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
