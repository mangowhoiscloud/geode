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
from core.tools.computer_observation import sanitize_computer_payload

from .executor import ToolExecutor
from .result_token_guard import _compute_model_tool_limit, _guard_tool_result

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
    MAX_TOOL_LOG_ENTRIES = 1_000

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
        provider: str = "",
        source: str = "",
        adapter_name: str = "",
    ) -> None:
        self._executor = executor
        self._op_logger = op_logger
        self._error_recovery = error_recovery
        self._hooks = hooks
        self._mcp_manager = mcp_manager
        self._transcript = transcript
        self._model = model
        # PR-TOOL-EXEC-CONTEXT (2026-05-28) — loop's LLM-identity carried
        # forward into every tool dispatch as a ``ToolContext`` so LLM-
        # touching tools (web_search, future web_extract / summarise)
        # prefer the same (provider, source) the loop main path resolved
        # instead of re-running ``infer_source`` from scratch.
        self._provider = provider
        self._source = source
        self._adapter_name = adapter_name

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
        tool_use_id: str = "",
    ) -> None:
        """Log result, record transcript events, and append to tool_log."""
        # Progressive log: show tool result summary (skip if already logged)
        if isinstance(result, dict):
            skip_log = result.get("skipped")
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
            if tool_name in {"computer", "computer_use"} and isinstance(result, dict):
                payload = self._computer_gui_payload(tool_input, result, tool_use_id)
                if payload:
                    self._transcript.record_lifecycle_event(
                        event="gui_step",
                        component="computer_use",
                        level="info" if status == "ok" else "warning",
                        payload=payload,
                        action="computer.step",
                        entity_type="tool_call",
                        entity_id=tool_use_id or "computer",
                    )

        stored_result = (
            sanitize_computer_payload(result)
            if tool_name in {"computer", "computer_use"} and isinstance(result, dict)
            else result
        )
        self._tool_log.append(
            {
                "tool": tool_name,
                "input": tool_input,
                "result": stored_result,
                "tool_use_id": tool_use_id,
            }
        )
        if len(self._tool_log) > self.MAX_TOOL_LOG_ENTRIES:
            del self._tool_log[: len(self._tool_log) - self.MAX_TOOL_LOG_ENTRIES]

    @staticmethod
    def _computer_gui_payload(
        tool_input: dict[str, Any],
        result: dict[str, Any],
        tool_use_id: str,
    ) -> dict[str, Any]:
        """Return transcript-safe GUI metadata; never include screenshot base64."""
        payload: dict[str, Any] = {
            "schema_version": 1,
            "tool_use_id": tool_use_id,
            "input_action": tool_input.get("action"),
        }
        actions = tool_input.get("actions")
        if isinstance(actions, list):
            payload["input_action_count"] = len(actions)
        if isinstance(result.get("observation"), dict):
            payload["observation"] = result["observation"]
        if isinstance(result.get("trajectory"), dict):
            payload["trajectory"] = result["trajectory"]
        if isinstance(result.get("error_kind"), str):
            payload["error_kind"] = result["error_kind"]
        if isinstance(result.get("recovery"), dict):
            payload["recovery"] = result["recovery"]
        return (
            payload
            if any(k in payload for k in ("observation", "trajectory", "error_kind"))
            else {}
        )

    @staticmethod
    def _serialize_computer_result(result: dict[str, Any], block_id: str) -> dict[str, Any]:
        """Computer-use ``tool_result`` carrying the screenshot as an IMAGE block.

        The screenshot must reach the model as a viewable image, not base64
        text: (1) the model cannot "see" a base64 string, and (2) a JPEG
        screenshot is ~10K+ tokens of base64 that the token guard / offload
        store below would truncate or offload — blinding the agent on the very
        next turn. Anthropic ``tool_result.content`` accepts a content-block
        list, and the loop forwards it natively
        (``messages.append({"role": "user", "content": tool_results})`` →
        ``_anthropic_common.build_messages`` passes user content through), so
        the image block reaches the wire unchanged. The non-image fields stay
        as a compact text block.
        """
        meta = {k: v for k, v in result.items() if k != "screenshot"}
        content: list[dict[str, Any]] = [
            {"type": "text", "text": json.dumps(meta, ensure_ascii=False, default=str)},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",  # harness encodes JPEG (computer_use.screenshot)
                    "data": result["screenshot"],
                },
            },
        ]
        return {"type": "tool_result", "tool_use_id": block_id, "content": content}

    async def _serialize_tool_result(
        self, result: Any, block_id: str, tool_name: str = ""
    ) -> dict[str, Any]:
        """Apply token guard, offload large results, and serialize for LLM."""
        # Computer-use screenshots return as an image block (see above) —
        # before the token guard / offload that would otherwise corrupt them.
        if tool_name == "computer" and isinstance(result, dict) and result.get("screenshot"):
            return self._serialize_computer_result(result, block_id)

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

        # Every accepted tool attempt has one start and one terminal end,
        # including interceptor blocks, adaptive recovery, and exceptions.
        fail_count = self._consecutive_failures.get(tool_name, 0)
        visible = self._op_logger.log_tool_call(tool_name, tool_input)
        started_at = time.monotonic()
        intercept = await self._fire_interceptor(
            HookEvent.TOOL_EXEC_STARTED,
            {"tool_name": tool_name, "tool_input": tool_input},
        )
        if intercept is not None:
            modified_input = intercept.data.get("tool_input")
            if isinstance(modified_input, dict):
                tool_input = modified_input

        last_recoverable = self._last_error_recoverable.get(tool_name, True)
        if intercept is not None and intercept.blocked:
            log.info("Tool %s blocked by TOOL_EXEC_START hook: %s", tool_name, intercept.reason)
            result: Any = {
                "error": intercept.reason,
                "error_type": "hook_blocked",
                "blocked_by_hook": True,
                "recoverable": False,
            }
        elif fail_count >= self.MAX_CONSECUTIVE_FAILURES and last_recoverable:
            try:
                result = await self._attempt_recovery(tool_name, tool_input, fail_count)
            except Exception as exc:
                log.exception("Tool recovery raised for %s", tool_name)
                result = {
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "recoverable": False,
                    "recovery_attempted": True,
                }
        else:
            # Execute via ToolExecutor async path. Legacy sync handlers are
            # adapted inside the executor instead of wrapping the whole
            # executor call in a worker thread.
            #
            # PR-TOOL-EXEC-CONTEXT (2026-05-28) — build a fresh
            # ``ToolContext`` per tool call carrying the loop's LLM identity
            # (provider / source / model / adapter_name) so LLM-touching
            # tools route through the same adapter the orchestration loop is
            # using instead of independently re-resolving via
            # ``infer_source``. Tools that do not consume the context absorb
            # the ``_tool_context`` kwarg through their ``**kwargs`` splat.
            from core.tools.base import ToolContext

            tool_ctx = ToolContext(
                provider=self._provider,
                source=self._source,
                model=self._model,
                adapter_name=self._adapter_name,
            )
            try:
                result = await self._executor.aexecute(tool_name, tool_input, context=tool_ctx)
            except Exception as exc:
                log.exception("Tool execution raised for %s", tool_name)
                result = {
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "recoverable": False,
                }

        # One feedback stage owns result rewriting. Legacy ``updated_result``
        # and ``additional_context`` keys are accepted here during migration;
        # TOOL_EXEC_ENDED is now a terminal observer, not a second transformer.
        preliminary_error = isinstance(result, dict) and bool(result.get("error"))
        transform_results = await self._fire_with_result(
            HookEvent.TOOL_RESULT_TRANSFORM,
            {
                "tool_name": tool_name,
                "tool_input": tool_input,
                "result": result,
                "has_error": preliminary_error,
            },
        )
        for hook_result in transform_results:
            if not hook_result.success or not isinstance(hook_result.data, dict):
                continue
            transformed = hook_result.data.get("transformed_result")
            if not isinstance(transformed, dict):
                transformed = hook_result.data.get("updated_result")
            if isinstance(transformed, dict):
                result = transformed
            extra_ctx = hook_result.data.get("additional_context")
            if extra_ctx and isinstance(result, dict):
                previous = result.get("additional_context", "")
                result["additional_context"] = f"{previous}\n{extra_ctx}" if previous else extra_ctx

        # Apply clarification guard before the terminal event so persisted
        # status always reflects the value returned to the model.
        if isinstance(result, dict) and result.get("clarification_needed"):
            self._clarification_count += 1
            if self._clarification_count > self.MAX_CLARIFICATION_ROUNDS:
                result = {
                    "error": (
                        "Too many clarification attempts. Please provide all required parameters."
                    ),
                    "error_type": "max_clarifications_exceeded",
                    "max_clarifications_exceeded": True,
                    "recoverable": False,
                }

        elapsed_ms = (time.monotonic() - started_at) * 1_000
        has_error = isinstance(result, dict) and bool(result.get("error"))
        await self._fire_hook(
            HookEvent.TOOL_EXEC_ENDED,
            {
                "tool_name": tool_name,
                "tool_input": tool_input,
                "duration_ms": elapsed_ms,
                "has_error": has_error,
                "result": result,
            },
        )
        if has_error:
            await self._fire_hook(
                HookEvent.TOOL_EXEC_FAILED,
                {
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "duration_ms": elapsed_ms,
                    "error": result.get("error") if isinstance(result, dict) else str(result),
                    "error_type": result.get("error_type", "unknown")
                    if isinstance(result, dict)
                    else "unknown",
                    "recoverable": result.get("recoverable", True)
                    if isinstance(result, dict)
                    else False,
                },
            )

        # Track consecutive failures + recoverability breadcrumb
        if isinstance(result, dict) and result.get("error"):
            if not result.get("recovery_attempted"):
                self._consecutive_failures[tool_name] = fail_count + 1
                self._last_error_recoverable[tool_name] = result.get("recoverable", True)
        else:
            self._consecutive_failures[tool_name] = 0
            self._last_error_recoverable.pop(tool_name, None)

        self._record_tool_activity(tool_name, tool_input, result, visible, block.id)
        return await self._serialize_tool_result(result, block.id, tool_name)

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
