"""Subprocess worker for isolated sub-agent execution.

Spawned by IsolatedRunner._execute_subprocess() as:
    python -m core.agent.worker

Protocol:
    stdin  → single JSON line (WorkerRequest)
    stdout → single JSON line (WorkerResult)
    stderr → log output (captured by parent for debugging)

The worker bootstraps a minimal GEODE runtime, runs an AgenticLoop
with the given prompt, and writes the result to stdout. It never
spawns child sub-agents (depth=1 enforced, matching Claude Code).
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

WORKER_DIR = Path.home() / ".geode" / "workers"


@dataclass
class WorkerRequest:
    """Serializable request from parent process to worker subprocess."""

    task_id: str
    task_type: str = ""
    description: str = ""  # Prompt text
    args: dict[str, Any] = field(default_factory=dict)
    denied_tools: list[str] = field(default_factory=list)
    model: str = "claude-opus-4-6"
    provider: str = "anthropic"
    timeout_s: float = 120.0
    time_budget_s: float = 0.0  # 0 = inherit parent's budget
    thinking_budget: int = 0  # 0 = disabled; >0 = thinking tokens per call
    domain: str = ""  # Domain adapter name (e.g. "game_ip") or ""
    isolation: str = ""  # Reserved for Phase 3: "worktree" etc.

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkerRequest:
        return cls(
            task_id=data["task_id"],
            task_type=data.get("task_type", ""),
            description=data.get("description", ""),
            args=data.get("args", {}),
            denied_tools=data.get("denied_tools", []),
            model=data.get("model", "claude-opus-4-6"),
            provider=data.get("provider", "anthropic"),
            timeout_s=data.get("timeout_s", 120.0),
            domain=data.get("domain", ""),
            isolation=data.get("isolation", ""),
        )


@dataclass
class WorkerResult:
    """Serializable result from worker subprocess to parent process."""

    task_id: str
    success: bool
    output: str = ""  # Full AgenticLoop response text
    summary: str = ""  # Truncated summary (max 500 chars)
    error: str | None = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkerResult:
        return cls(
            task_id=data["task_id"],
            success=data["success"],
            output=data.get("output", ""),
            summary=data.get("summary", ""),
            error=data.get("error"),
            duration_ms=data.get("duration_ms", 0.0),
        )


# ---------------------------------------------------------------------------
# Worker bootstrap and execution
# ---------------------------------------------------------------------------


def _save_result_backup(result: WorkerResult) -> None:
    """Save result JSON to ~/.geode/workers/ for crash debugging."""
    try:
        WORKER_DIR.mkdir(parents=True, exist_ok=True)
        path = WORKER_DIR / f"{result.task_id}.result.json"
        path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        log.debug("Failed to save result backup for %s", result.task_id, exc_info=True)


def _run_agentic(request: WorkerRequest) -> WorkerResult:
    """Bootstrap minimal GEODE runtime and run AgenticLoop."""
    started = time.time()

    # 1. Domain context (optional)
    if request.domain:
        try:
            from core.domains.port import set_domain
            from core.domains.registry import load_domain_adapter  # type: ignore[import-untyped]

            domain = load_domain_adapter(request.domain)
            set_domain(domain)
        except Exception as exc:
            log.warning("Domain '%s' load failed: %s", request.domain, exc)

    # 2. Build tool handlers (same factory as CLI)
    from core.cli.tool_handlers import _build_tool_handlers

    handlers = _build_tool_handlers(verbose=False)

    # 3. Filter denied tools
    denied = set(request.denied_tools)
    # Always deny delegate_task in worker (depth=1 enforcement)
    denied.add("delegate_task")
    if denied:
        handlers = {k: v for k, v in handlers.items() if k not in denied}

    # 4. Build ToolExecutor (auto_approve=True for sub-agents)
    from core.agent.tool_executor import ToolExecutor

    executor = ToolExecutor(
        action_handlers=handlers,
        auto_approve=True,  # Sub-agents skip HITL prompts
    )

    # 5. Build ConversationContext
    from core.agent.conversation import ConversationContext

    conversation = ConversationContext(max_turns=200)

    # 6. Build AgenticLoop
    from core.agent.agentic_loop import AgenticLoop

    loop = AgenticLoop(
        conversation,
        executor,
        max_rounds=0,  # unlimited — controlled by timeout_s from parent
        max_tokens=32768,
        model=request.model,
        provider=request.provider,
        quiet=True,  # Suppress spinner — parent handles UI
    )

    # 7. Build prompt
    prompt = request.description
    if request.args:
        prompt += f"\n\nParameters: {json.dumps(request.args, ensure_ascii=False)}"

    # 8. Run
    agentic_result = loop.run(prompt)

    elapsed_ms = (time.time() - started) * 1000
    text = agentic_result.text if agentic_result else ""

    return WorkerResult(
        task_id=request.task_id,
        success=bool(text),
        output=text,
        summary=text[:500] if text else "No response from sub-agent",
        duration_ms=elapsed_ms,
    )


def main() -> None:
    """Worker entry point. Reads request from stdin, writes result to stdout."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,  # Logs go to stderr; stdout reserved for result JSON
    )

    result: WorkerResult | None = None
    try:
        # Read request from stdin (single JSON line)
        raw = sys.stdin.readline()
        if not raw.strip():
            result = WorkerResult(
                task_id="unknown",
                success=False,
                error="Empty stdin — no request received",
            )
        else:
            request = WorkerRequest.from_dict(json.loads(raw))
            result = _run_agentic(request)
    except json.JSONDecodeError as exc:
        result = WorkerResult(
            task_id="unknown",
            success=False,
            error=f"Invalid JSON on stdin: {exc}",
        )
    except Exception as exc:
        task_id = "unknown"
        with contextlib.suppress(Exception):
            task_id = json.loads(raw).get("task_id", "unknown")
        result = WorkerResult(
            task_id=task_id,
            success=False,
            error=f"Worker crash: {type(exc).__name__}: {exc}",
        )

    # Write result to stdout (single JSON line)
    sys.stdout.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")
    sys.stdout.flush()

    # Backup for crash debugging
    _save_result_backup(result)


if __name__ == "__main__":
    main()
