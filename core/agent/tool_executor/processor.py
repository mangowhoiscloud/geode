"""ToolCallProcessor — orchestrate parallel/sequential tool_use execution."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.agent.error_recovery import ErrorRecoveryStrategy
    from core.hooks import HookResult, HookSystem, InterceptResult
    from core.ui.agentic_ui import OperationLogger

from core.agent.safety import (
    AUTO_APPROVED_MCP_SERVERS,
    DANGEROUS_TOOLS,
    EXPENSIVE_TOOLS,
    SAFE_TOOLS,
    WRITE_TOOLS,
)
from core.hooks.system import HookEvent

from ._helpers import _compute_model_tool_limit, _guard_tool_result
from .executor import ToolExecutor

log = logging.getLogger(__name__)


class ToolCallProcessor:
    """Orchestrate parallel/sequential execution of tool_use blocks.

    Extracted from AgenticLoop to separate tool call processing
    (dispatch, tracking, tiering, parallel execution) from the
    conversational loop logic.

    The processor holds per-run mutable state (consecutive failures,
    tool log, clarification count) that is reset via ``reset()``
    at the start of each agentic run.
    """

    MAX_CONSECUTIVE_FAILURES = 2
    MAX_CLARIFICATION_ROUNDS = 3

    def __init__(
        self,
        *,
        executor: ToolExecutor,
        op_logger: OperationLogger,
        error_recovery: ErrorRecoveryStrategy,
        hooks: HookSystem | None = None,
        mcp_manager: Any | None = None,
        transcript: Any | None = None,
        model: str = "",
    ) -> None:
        self._executor = executor
        self._op_logger = op_logger
        self._error_recovery = error_recovery
        self._hooks = hooks
        self._mcp_manager = mcp_manager
        self._transcript = transcript
        self._model = model

        # Per-run mutable state — reset via reset()
        self._consecutive_failures: dict[str, int] = {}
        # Breadcrumb: skip recovery chain for non-recoverable errors (e.g. permission)
        self._last_error_recoverable: dict[str, bool] = {}
        self._tool_log: list[dict[str, Any]] = []
        self._clarification_count: int = 0

    def reset(self) -> None:
        """Reset per-run tracking state. Call at the start of each agentic run."""
        self._consecutive_failures.clear()
        self._last_error_recoverable.clear()
        self._tool_log.clear()
        self._clarification_count = 0

    @property
    def tool_log(self) -> list[dict[str, Any]]:
        """Read-only access to the tool execution log."""
        return self._tool_log

    async def process(self, response: Any) -> list[dict[str, Any]]:
        """Execute tool_use blocks — parallel when multiple, sequential when single.

        When the LLM returns 2+ tool_use blocks in one response, executes them
        concurrently via ``asyncio.gather``.  Single tool_use falls through to
        the sequential path for zero-overhead backward compatibility.

        Tracks consecutive failures per tool name.  After MAX_CONSECUTIVE_FAILURES
        for the same tool, triggers the adaptive error recovery chain.
        """
        tool_blocks = [b for b in response.content if b.type == "tool_use"]

        if len(tool_blocks) <= 1:
            return await self._execute_sequential(tool_blocks)

        return await self._execute_parallel(tool_blocks)

    def _record_tool_activity(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        result: Any,
        visible: bool,
    ) -> None:
        """Log result, record transcript events, and append to tool_log."""
        # Progressive log: show tool result summary (skip if already logged)
        if isinstance(result, dict):
            skip_log = result.get("skipped") or result.get("recovery_attempted")
            if not skip_log:
                self._op_logger.log_tool_result(tool_name, result, visible=visible)

        # Transcript: tool_call + tool_result events
        if self._transcript is not None:
            self._transcript.record_tool_call(tool_name, tool_input)
            status = "error" if isinstance(result, dict) and result.get("error") else "ok"
            summary = ""
            if isinstance(result, dict):
                summary = str(result.get("summary", result.get("error", "")))
            self._transcript.record_tool_result(tool_name, status, summary)

        self._tool_log.append(
            {
                "tool": tool_name,
                "input": tool_input,
                "result": result,
            }
        )

    async def _serialize_tool_result(self, result: Any, block_id: str) -> dict[str, Any]:
        """Apply token guard, offload large results, and serialize for LLM."""
        # Token guard: truncate oversized results to prevent context explosion
        # For small-context models (e.g. GLM-5), apply model-aware limit
        if isinstance(result, dict):
            model_limit = _compute_model_tool_limit(self._model) if self._model else 0
            result = _guard_tool_result(result, max_tokens=model_limit or None)

        # Serialize result as JSON for LLM (not Python repr)
        try:
            serialized = json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            serialized = str(result)

        # P0: Offload large results to filesystem, inject compact summary
        estimated_tokens = len(serialized) // 4
        from core.orchestration.tool_offload import get_offload_store

        offload_store = get_offload_store()
        if (
            offload_store
            and offload_store.threshold > 0
            and estimated_tokens > offload_store.threshold
        ):
            from core.orchestration.tool_offload import extract_result_summary

            ref_id = offload_store.offload(block_id, result)
            summary = extract_result_summary(result, max_chars=400)
            content = json.dumps(
                {
                    "_offloaded": True,
                    "_ref_id": ref_id,
                    "_original_tokens": estimated_tokens,
                    "summary": summary,
                    "hint": "Use recall_tool_result(ref_id) to retrieve the full output.",
                },
                ensure_ascii=False,
            )
            # Fire hook for observability
            if self._hooks:
                from core.hooks import HookEvent

                await self._hooks.trigger_async(
                    HookEvent.TOOL_RESULT_OFFLOADED,
                    {
                        "ref_id": ref_id,
                        "original_tokens": estimated_tokens,
                        "block_id": block_id,
                    },
                )
        else:
            content = serialized

        return {
            "type": "tool_result",
            "tool_use_id": block_id,
            "content": content,
        }

    async def _execute_single(self, block: Any) -> dict[str, Any]:
        """Execute a single tool_use block and return its processed result dict.

        Handles consecutive failure tracking, recovery, clarification guards,
        logging, tool_log bookkeeping, and token guard.

        Returns a dict ready to be used as a tool_result content block
        (with ``type``, ``tool_use_id``, ``content`` keys).
        """
        tool_name = block.name
        tool_input: dict[str, Any] = block.input

        log.info("ToolCallProcessor: tool_use %s(%s)", tool_name, tool_input)

        # Check consecutive failure count
        fail_count = self._consecutive_failures.get(tool_name, 0)

        last_recoverable = self._last_error_recoverable.get(tool_name, True)
        if fail_count >= self.MAX_CONSECUTIVE_FAILURES and last_recoverable:
            # Adaptive recovery: try recovery chain instead of auto-skip
            result = await self._attempt_recovery(tool_name, tool_input, fail_count)
            visible = self._op_logger.log_tool_call(tool_name, tool_input)
            self._op_logger.log_tool_result(tool_name, result, visible=visible)
        else:
            # Progressive log: show tool call before execution
            visible = self._op_logger.log_tool_call(tool_name, tool_input)

            # Hook: TOOL_EXEC_START (interceptor — can block or modify input)
            intercept = await self._fire_interceptor(
                HookEvent.TOOL_EXEC_STARTED, {"tool_name": tool_name, "tool_input": tool_input}
            )
            if intercept is not None and intercept.blocked:
                log.info("Tool %s blocked by TOOL_EXEC_START hook: %s", tool_name, intercept.reason)
                result = {"error": intercept.reason, "blocked_by_hook": True}
                self._op_logger.log_tool_result(tool_name, result, visible=visible)
                self._record_tool_activity(tool_name, tool_input, result, visible)
                return await self._serialize_tool_result(result, block.id)

            # Apply input modifications from interceptor hook
            if intercept is not None:
                modified_input = intercept.data.get("tool_input")
                if isinstance(modified_input, dict):
                    tool_input = modified_input

            # Execute via ToolExecutor async path. Legacy sync handlers are
            # adapted inside the executor instead of wrapping the whole
            # executor call in a worker thread.
            _t0 = time.monotonic()
            result = await self._executor.aexecute(tool_name, tool_input)
            _elapsed_ms = (time.monotonic() - _t0) * 1000

            # Hook: TOOL_EXEC_END (feedback — fires for all completions)
            _has_error = isinstance(result, dict) and bool(result.get("error"))
            _post_data = {
                "tool_name": tool_name,
                "tool_input": tool_input,
                "duration_ms": _elapsed_ms,
                "has_error": _has_error,
                "result": result,
            }
            post_results = await self._fire_with_result(HookEvent.TOOL_EXEC_ENDED, _post_data)
            # Apply result modifications from PostToolUse-style handlers
            for hr in post_results:
                if hr.success and isinstance(hr.data, dict):
                    updated = hr.data.get("updated_result")
                    if isinstance(updated, dict):
                        result = updated
                    extra_ctx = hr.data.get("additional_context")
                    if extra_ctx and isinstance(result, dict):
                        prev = result.get("additional_context", "")
                        result["additional_context"] = f"{prev}\n{extra_ctx}" if prev else extra_ctx

            # Hook: TOOL_EXEC_FAILED (observer — fires only on error)
            if _has_error:
                await self._fire_hook(
                    HookEvent.TOOL_EXEC_FAILED,
                    {
                        "tool_name": tool_name,
                        "tool_input": tool_input,
                        "duration_ms": _elapsed_ms,
                        "error": result.get("error") if isinstance(result, dict) else str(result),
                        "error_type": result.get("error_type", "unknown")
                        if isinstance(result, dict)
                        else "unknown",
                        "recoverable": result.get("recoverable", True)
                        if isinstance(result, dict)
                        else False,
                    },
                )

            # Hook: TOOL_RESULT_TRANSFORM (feedback — result rewriting, post-observation)
            transform_results = await self._fire_with_result(
                HookEvent.TOOL_RESULT_TRANSFORM,
                {
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "result": result,
                    "has_error": _has_error,
                },
            )
            for hr in transform_results:
                if hr.success and isinstance(hr.data, dict):
                    transformed = hr.data.get("transformed_result")
                    if isinstance(transformed, dict):
                        result = transformed

        # Track consecutive failures + recoverability breadcrumb
        if isinstance(result, dict) and result.get("error"):
            if not result.get("recovery_attempted"):
                self._consecutive_failures[tool_name] = fail_count + 1
                self._last_error_recoverable[tool_name] = result.get("recoverable", True)
        else:
            self._consecutive_failures[tool_name] = 0
            self._last_error_recoverable.pop(tool_name, None)

        # Track clarification rounds to prevent infinite loops
        if isinstance(result, dict) and result.get("clarification_needed"):
            self._clarification_count += 1
            if self._clarification_count > self.MAX_CLARIFICATION_ROUNDS:
                result = {
                    "error": (
                        "Too many clarification attempts. Please provide all required parameters."
                    ),
                    "max_clarifications_exceeded": True,
                }

        self._record_tool_activity(tool_name, tool_input, result, visible)
        return await self._serialize_tool_result(result, block.id)

    async def _execute_sequential(self, tool_blocks: list[Any]) -> list[dict[str, Any]]:
        """Execute tool blocks one by one (single-tool fast path)."""
        tool_results: list[dict[str, Any]] = []
        for block in tool_blocks:
            tool_result = await self._execute_single(block)
            tool_results.append(tool_result)
        return tool_results

    # -- Tier classification for parallel execution --------------------------

    @staticmethod
    def _classify_tier(tool_name: str, mcp_manager: Any | None = None) -> int:
        """Classify a tool into a safety tier for parallel execution.

        TIER 0: SAFE tools — auto-execute, no gate
        TIER 1: MCP auto-approved — auto-execute, logged
        TIER 2: EXPENSIVE tools — batch cost confirmation, then parallel
        TIER 3: WRITE tools — individual approval, sequential
        TIER 4: DANGEROUS tools — individual approval, sequential
        Unclassified (STANDARD) tools default to TIER 0 (parallel-safe).
        """
        if tool_name in DANGEROUS_TOOLS:
            return 4
        if tool_name in WRITE_TOOLS:
            return 3
        if tool_name in EXPENSIVE_TOOLS:
            return 2
        if mcp_manager is not None:
            server = mcp_manager.find_server_for_tool(tool_name)
            if server is not None:
                if server in AUTO_APPROVED_MCP_SERVERS:
                    return 1
                return 3
        if tool_name in SAFE_TOOLS:
            return 0
        return 0

    async def _execute_parallel(self, tool_blocks: list[Any]) -> list[dict[str, Any]]:
        """Execute 2+ tool blocks with tiered batch approval.

        Tier classification:
          TIER 0-1 (SAFE/MCP auto-approved): start immediately in parallel
          TIER 2 (EXPENSIVE): batch cost confirmation -> parallel execution
          TIER 3-4 (WRITE/DANGEROUS): individual approval -> sequential

        Results are returned in the same order as the input tool_use blocks
        to satisfy the Anthropic API ordering requirement.
        """
        log.info(
            "ToolCallProcessor: parallel execution of %d tools: %s",
            len(tool_blocks),
            [b.name for b in tool_blocks],
        )

        # Step 1: Classify blocks into tiers
        tiered: dict[int, list[tuple[int, Any]]] = {0: [], 1: [], 2: [], 3: [], 4: []}
        for idx, block in enumerate(tool_blocks):
            tier = self._classify_tier(block.name, self._mcp_manager)
            tiered[tier].append((idx, block))
            log.debug("Tool %s -> tier %d", block.name, tier)

        # Pre-allocate result slots in original order
        results: list[dict[str, Any] | None] = [None] * len(tool_blocks)

        # Step 2: Batch cost approval for TIER 2 (EXPENSIVE) tools
        tier2_approved = True
        if tiered[2]:
            tier2_approved = await self._batch_cost_approval([block for _, block in tiered[2]])

        # Step 3: Build parallel tasks for TIER 0 + TIER 1 + approved TIER 2
        parallel_items: list[tuple[int, Any]] = []
        parallel_items.extend(tiered[0])
        parallel_items.extend(tiered[1])

        if tier2_approved:
            parallel_items.extend(tiered[2])
        else:
            for idx, block in tiered[2]:
                results[idx] = self._make_denial_result(block, "User denied batch cost approval")

        # Step 4: Execute parallel pool
        if parallel_items:
            old_auto_approve = self._executor._auto_approve
            if tier2_approved and tiered[2]:
                self._executor._auto_approve = True

            try:
                gathered = await asyncio.gather(
                    *[self._safe_execute_single(block) for _, block in parallel_items]
                )
            finally:
                if tier2_approved and tiered[2]:
                    self._executor._auto_approve = old_auto_approve

            for (idx, _block), result in zip(parallel_items, gathered, strict=True):
                results[idx] = result

        # Step 5: Execute TIER 3-4 (WRITE/DANGEROUS) sequentially
        sequential_items = list(tiered[3]) + list(tiered[4])
        for idx, block in sequential_items:
            results[idx] = await self._execute_single(block)

        return [r for r in results if r is not None]

    async def _safe_execute_single(self, block: Any) -> dict[str, Any]:
        """Wrapper that catches unexpected exceptions per tool."""
        try:
            return await self._execute_single(block)
        except Exception as exc:
            log.error(
                "Parallel tool %s raised unexpected error: %s",
                block.name,
                exc,
                exc_info=True,
            )
            return self._make_error_result(block, exc)

    async def _batch_cost_approval(self, blocks: list[Any]) -> bool:
        """Delegates to ApprovalWorkflow."""
        return await self._executor._approval.batch_cost_approval(blocks)

    async def _attempt_recovery(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        fail_count: int,
    ) -> dict[str, Any]:
        """Attempt adaptive error recovery for a repeatedly failing tool.

        Runs the recovery chain through the async executor path and emits hook
        events for observability.
        """
        await self._fire_hook(
            HookEvent.TOOL_RECOVERY_ATTEMPTED,
            {
                "tool_name": tool_name,
                "fail_count": fail_count,
                "source": "tool_call_processor",
            },
        )

        recovery_result = await self._error_recovery.arecover(tool_name, tool_input, fail_count)

        if recovery_result.recovered:
            self._consecutive_failures[tool_name] = 0
            await self._fire_hook(
                HookEvent.TOOL_RECOVERY_SUCCEEDED,
                {
                    "tool_name": tool_name,
                    "strategy": recovery_result.strategy_used.value
                    if recovery_result.strategy_used
                    else "unknown",
                    "attempts": len(recovery_result.attempts),
                    "source": "tool_call_processor",
                },
            )
            result = dict(recovery_result.final_result)
            result["recovery_summary"] = recovery_result.to_summary()
            result["recovery_attempted"] = True
            return result

        await self._fire_hook(
            HookEvent.TOOL_RECOVERY_FAILED,
            {
                "tool_name": tool_name,
                "attempts": len(recovery_result.attempts),
                "strategies_tried": [a.strategy.value for a in recovery_result.attempts],
                "source": "tool_call_processor",
            },
        )
        result = dict(recovery_result.final_result)
        result["recovery_summary"] = recovery_result.to_summary()
        result["recovery_attempted"] = True
        result["skipped"] = True
        return result

    async def _fire_hook(self, event: HookEvent, data: dict[str, Any]) -> None:
        """Emit a hook event if HookSystem is configured."""
        if self._hooks is None:
            return
        try:
            await self._hooks.trigger_async(event, data)
        except Exception:
            log.debug("Hook trigger failed for %s", event, exc_info=True)

    async def _fire_interceptor(
        self, event: HookEvent, data: dict[str, Any]
    ) -> InterceptResult | None:
        """Emit a hook event as interceptor (block/modify semantics).

        Returns InterceptResult if hooks are configured, None otherwise.
        """
        if self._hooks is None:
            return None
        try:
            return await self._hooks.trigger_interceptor_async(event, data)
        except Exception:
            log.debug("Interceptor trigger failed for %s", event, exc_info=True)
            return None

    async def _fire_with_result(self, event: HookEvent, data: dict[str, Any]) -> list[HookResult]:
        """Emit a hook event capturing handler return values.

        Returns list of HookResult with handler-returned data.
        """
        if self._hooks is None:
            return []
        try:
            return await self._hooks.trigger_with_result_async(event, data)
        except Exception:
            log.debug("Hook trigger_with_result failed for %s", event, exc_info=True)
            return []

    @staticmethod
    def _make_denial_result(block: Any, reason: str) -> dict[str, Any]:
        """Build a tool_result for a denied tool execution."""
        error_result = {"error": reason, "denied": True}
        try:
            content = json.dumps(error_result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            content = str(error_result)
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": content,
        }

    @staticmethod
    def _make_error_result(block: Any, exc: Exception) -> dict[str, Any]:
        """Build a tool_result for an unexpected exception."""
        error_result = {"error": str(exc)}
        try:
            content = json.dumps(error_result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            content = str(error_result)
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": content,
        }
