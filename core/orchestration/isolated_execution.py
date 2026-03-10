"""Isolated Execution — run callables in isolated contexts with PostToMain delivery.

Inspired by OpenClaw's isolated session pattern, this module provides:
- Isolated execution with timeout and error isolation
- PostToMain: structured result delivery via HookSystem
- PostToMainMode: summary (brief) or full (complete, truncated) output
- Concurrency control with configurable max parallel executions
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.infrastructure.ports.hook_port import HookSystemPort
from core.orchestration.hooks import HookEvent

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


class IsolatedRunner:
    """Execute callables in isolated contexts with PostToMain delivery.

    Usage::

        runner = IsolatedRunner(hooks=hook_system)
        config = IsolationConfig(timeout_s=60, post_mode=PostToMainMode.FULL)
        result = runner.run(my_callable, args=("hello",), config=config)
    """

    MAX_CONCURRENT = 5  # Max parallel isolated executions

    def __init__(self, hooks: HookSystemPort | None = None) -> None:
        self._hooks = hooks
        self._results: dict[str, IsolationResult] = {}
        self._active: dict[str, threading.Thread] = {}
        self._cancel_flags: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(self.MAX_CONCURRENT)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        fn: Callable[..., Any],
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        config: IsolationConfig | None = None,
    ) -> IsolationResult:
        """Run *fn* synchronously in an isolated context."""
        cfg = self._resolve_config(config)
        return self._execute(fn, args, kwargs or {}, cfg)

    def run_async(
        self,
        fn: Callable[..., Any],
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        config: IsolationConfig | None = None,
    ) -> str:
        """Run *fn* in a background thread. Returns session_id for later retrieval."""
        cfg = self._resolve_config(config)
        session_id = cfg.session_id

        cancel_flag = threading.Event()
        with self._lock:
            self._cancel_flags[session_id] = cancel_flag

        def _worker() -> None:
            result = self._execute(fn, args, kwargs or {}, cfg)
            with self._lock:
                self._results[session_id] = result
                self._active.pop(session_id, None)
                self._cancel_flags.pop(session_id, None)

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
        """Set the cancel flag for a running session. Returns True if found."""
        with self._lock:
            flag = self._cancel_flags.get(session_id)
        if flag is not None:
            flag.set()
            log.info("Cancel requested for session %s", session_id)
            return True
        return False

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

    def _execute(
        self,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        config: IsolationConfig,
    ) -> IsolationResult:
        """Execute *fn* with timeout and error isolation."""
        acquired = self._semaphore.acquire(timeout=0)
        if not acquired:
            return IsolationResult(
                session_id=config.session_id,
                success=False,
                error=f"Concurrency limit reached (max {self.MAX_CONCURRENT})",
                started_at=time.time(),
                completed_at=time.time(),
                metadata=dict(config.metadata),
            )

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
                # Timeout
                result = IsolationResult(
                    session_id=config.session_id,
                    success=False,
                    error=f"Timeout after {config.timeout_s}s",
                    duration_ms=duration_ms,
                    started_at=started,
                    completed_at=completed,
                    metadata=dict(config.metadata),
                )
                log.warning(
                    "Isolated session %s timed out after %.1fs",
                    config.session_id,
                    config.timeout_s,
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
            self._semaphore.release()

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
