"""``content_block_delta`` accumulator for ``tool_use`` blocks (CSA-2).

Extends CSA-1's text-only stream-json parser. The claude CLI emits
``tool_use`` content blocks as a sequence::

    content_block_start  { index, content_block: {type: "tool_use", id, name, input: {}} }
    content_block_delta  { index, delta: {type: "input_json_delta", partial_json: "..."} }
    ...
    content_block_stop   { index }

We accumulate ``partial_json`` fragments keyed by ``index``, then
``json.loads`` the concatenation at ``content_block_stop`` to build an
inspect_ai :class:`ToolCall`.

Why split from the CSA-1 parser
================================

CSA-1's ``_extract_assistant_text`` was a single-purpose folder over
``text_delta`` events. Adding tool_use accumulation in-place would have
muddled two unrelated concerns and forced the text-only path to pay
the bookkeeping cost. The split keeps each function single-purpose
and lets the tool-aware response builder compose both.

Edge cases
----------

* claude sometimes inlines a complete ``input`` dict directly in the
  ``content_block_start`` event (small inputs, no streaming). Falls
  back to that dict if no deltas were observed.
* Malformed accumulated JSON → ``ToolCall.parse_error`` populated;
  ``arguments={}``. inspect_ai's ToolCall has a dedicated ``parse_error``
  field exactly for this case.
* Multiple tool_use blocks in one response (``parallel_tool_calls=True``)
  are distinguished by ``index`` — we never share state across blocks.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from plugins.petri_audit.mcp_bridge.lifecycle import strip_mcp_prefix

if TYPE_CHECKING:  # pragma: no cover
    from inspect_ai.tool import ToolCall

log = logging.getLogger(__name__)

__all__ = [
    "ToolUseAccumulator",
    "extract_tool_calls",
]


@dataclass(slots=True)
class ToolUseAccumulator:
    """One tool_use content block being built across delta events.

    ``index`` is claude's per-message ``content_block`` index (0-based,
    monotonically increasing per message). It is the only stable key
    across the start / delta* / stop sequence — ``id`` is also stable
    but only appears in the start event, so keying on ``index`` is
    safer for the accumulator's internal book-keeping.
    """

    index: int
    id: str
    name: str
    partial_json_parts: list[str] = field(default_factory=list)
    initial_input: dict[str, Any] | None = None
    done: bool = False

    def assemble_arguments(self) -> tuple[dict[str, Any], str | None]:
        """Return ``(arguments, parse_error)``.

        Priority order:
          1. Concatenated ``partial_json`` parts (the canonical streaming path).
          2. The ``initial_input`` dict from ``content_block_start`` (small-input fallback).
          3. ``{}`` (empty tool call — semantically odd but legal in JSON Schema).
        """
        if self.partial_json_parts:
            blob = "".join(self.partial_json_parts)
            if not blob.strip():
                return {}, None
            try:
                parsed = json.loads(blob)
            except json.JSONDecodeError as exc:
                log.warning(
                    "tool_use partial_json parse failed for tool=%s id=%s: %s",
                    self.name,
                    self.id,
                    exc,
                )
                return {}, f"partial_json parse failed: {exc.msg} at pos {exc.pos}"
            if not isinstance(parsed, dict):
                return {}, f"partial_json decoded to {type(parsed).__name__}, expected object"
            return parsed, None
        if self.initial_input is not None:
            return self.initial_input, None
        return {}, None


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    """Return the inner ``payload`` dict regardless of CSA-1's event wrapper."""
    payload = event.get("payload")
    if isinstance(payload, dict):
        return payload
    return event


def _coerce_event_dict(event: object) -> dict[str, Any] | None:
    """Unwrap CSA-1's ``StreamJsonEvent`` dataclass to a plain dict.

    The parser is permissive: it accepts plain dicts (for tests and
    forward-compat with future emitters) as well as the dataclass shape
    CSA-1's :func:`parse_stream_json_events` actually returns.
    """
    if isinstance(event, dict):
        return event
    event_type = getattr(event, "type", None)
    payload = getattr(event, "payload", None)
    if event_type is None or payload is None:
        return None
    if not isinstance(payload, dict):
        return None
    return {"type": event_type, "payload": payload}


def extract_tool_calls(
    events: Sequence[object],
    *,
    server_name: str | None = None,
) -> list[ToolCall]:
    """Walk a stream-json event list, build accumulators, materialise ToolCalls.

    Args:
        events: Output of :func:`parse_stream_json_events`. Either the
            CSA-1 dataclass list or a list of plain dicts.
        server_name: If given, the MCP server prefix to strip from
            tool names (typically :data:`BRIDGE_SERVER_NAME`).
            ``None`` skips prefix stripping (useful for non-MCP tool
            sources or pure unit tests).

    Returns ``[]`` when no tool_use blocks were emitted (text-only
    response or empty stream). Order matches the order of the
    ``content_block_start`` events — i.e. claude's emission order, which
    inspect_ai's solver also preserves.
    """
    from inspect_ai.tool import ToolCall

    in_flight: dict[int, ToolUseAccumulator] = {}
    completed_order: list[int] = []

    for raw_event in events:
        event = _coerce_event_dict(raw_event)
        if event is None:
            continue
        event_type = event.get("type")
        payload = _event_payload(event)

        if event_type == "content_block_start":
            content_block = payload.get("content_block")
            if not isinstance(content_block, dict):
                continue
            if content_block.get("type") != "tool_use":
                continue
            index = payload.get("index")
            if not isinstance(index, int):
                continue
            initial_input = content_block.get("input")
            in_flight[index] = ToolUseAccumulator(
                index=index,
                id=str(content_block.get("id", "")),
                name=str(content_block.get("name", "")),
                initial_input=initial_input if isinstance(initial_input, dict) else None,
            )
            continue

        if event_type == "content_block_delta":
            delta = payload.get("delta")
            if not isinstance(delta, dict):
                continue
            if delta.get("type") != "input_json_delta":
                continue
            index = payload.get("index")
            acc = in_flight.get(index) if isinstance(index, int) else None
            if acc is None:
                continue
            partial = delta.get("partial_json", "")
            if isinstance(partial, str):
                acc.partial_json_parts.append(partial)
            continue

        if event_type == "content_block_stop":
            index = payload.get("index")
            if not isinstance(index, int):
                continue
            acc = in_flight.get(index)
            if acc is None:
                continue
            acc.done = True
            completed_order.append(index)
            continue

    tool_calls: list[ToolCall] = []
    for index in completed_order:
        acc = in_flight[index]
        if not acc.done:
            continue
        arguments, parse_error = acc.assemble_arguments()
        if server_name:
            function_name = strip_mcp_prefix(acc.name, server_name=server_name)
        else:
            function_name = acc.name
        tool_calls.append(
            ToolCall(
                id=acc.id or f"tool_use_{index}",
                function=function_name,
                arguments=arguments,
                parse_error=parse_error,
                type="function",
            )
        )
    return tool_calls
