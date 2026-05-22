"""Paperclip-pattern adapter — inspect_ai provider that invokes
``claude --print`` subprocess for every ``generate()`` call.

CSA-1 (2026-05-22) — scaffold + text-only generate (judge role).

Why this exists
===============

The existing ``ClaudeOAuthAPI`` (``claude_code_provider.py``) routes
inspect_ai's ``/v1/messages`` calls through the raw Anthropic Python
SDK using the OAuth token as ``x-api-key``. Empirically this triggers
**100% 429 enforcement** even on the very first request (verified
2026-05-22 in ``trace-68931.log`` — 27/27 requests 429, exponential
backoff to 770 sec). The same OAuth token works perfectly when used by
the ``claude`` CLI binary (smoke verified: ``claude --print "Hi"``
returns 3.9s, $0.18).

The diagnosis: Anthropic gateway distinguishes "OAuth token via raw
SDK" (rate-limited) from "OAuth token via Claude Code CLI" (full
subscription tier). The CLI sends session-aware headers (``claude-
code-session-id``, ``x-stainless-helper-method``, anthropic-beta
bundle) that we cannot easily replicate from Python.

Paperclip's solution (verified in
``~/workspace/paperclip/packages/adapters/claude-local/src/server/
execute.ts:679``): spawn ``claude --print`` per inference call and
parse the ``stream-json`` output. No raw SDK calls.

This module mirrors that pattern for inspect_ai. Each
``generate()`` call:

1. Builds argv: ``claude --print - --output-format stream-json --verbose
   --model <m> --max-turns 1 [--mcp-config ...]``
2. Serialises ``inspect_ai.ChatMessage[]`` into a single prompt string
   (system / user / assistant turns concatenated with role headers).
3. Spawns the subprocess via ``asyncio.create_subprocess_exec`` —
   stdin gets the prompt, stdout the stream-json events.
4. Parses event stream → ``ChatMessageAssistant.content`` + usage
   counts + stop_reason.
5. Returns ``ModelOutput`` to inspect_ai's harness.

CSA-1 + CSA-2 scope
====================

This module now ships both branches:

* **Text-only** (CSA-1, judge role): provider scaffold +
  ``@modelapi("claude-cli")`` registration, argv builder + stdin
  serialiser + stream-json parser, ``ModelOutput`` construction
  (content / usage / stop_reason).

* **Tool-use** (CSA-2, auditor role): when ``generate(tools=[...])``
  is non-empty, the call routes through
  :mod:`plugins.petri_audit.mcp_bridge.prepare_bridge` which spins up
  a per-call stdio MCP server, materialises tool schemas, and wires
  the claude CLI with ``--mcp-config`` / ``--strict-mcp-config`` /
  ``--allowed-tools``. The response parser extracts ``tool_use``
  content blocks via :func:`extract_tool_calls` and returns them on
  ``ChatMessageAssistant.tool_calls``. Bridge handlers do NOT execute
  tools (``--max-turns 1`` stops claude at the tool boundary);
  inspect_petri's solver dispatches the calls in the parent process.

Operator surface
================

inspect_ai picks up the provider when the model id is prefixed with
``claude-cli/`` (e.g. ``claude-cli/claude-opus-4-7``). The
``to_inspect_model`` router in ``models.py`` flips
``source="claude-cli"`` configs to this prefix automatically.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

log = logging.getLogger(__name__)

__all__ = [
    "CLAUDE_CLI_BIN_ENV",
    "CLAUDE_CLI_MODEL_NOT_FOUND",
    "CLAUDE_CLI_SUBPROCESS_TIMEOUT_S",
    "ClaudeCliInvocationError",
    "build_claude_cli_argv",
    "parse_stream_json_events",
    "register",
    "serialise_messages_to_prompt",
]


CLAUDE_CLI_BIN_ENV = "GEODE_CLAUDE_CLI_BIN"
"""Operator override for the ``claude`` binary path. When unset, the
provider uses :func:`shutil.which("claude")`."""

_DEFAULT_CLAUDE_BIN = "claude"

CLAUDE_CLI_SUBPROCESS_TIMEOUT_S = 600.0
"""10-minute hard ceiling per subprocess invocation. inspect_ai's
``--max-turns 1`` keeps the LLM emission bounded, but a stalled
network / dead Claude Code session needs an upper bound. Operators
who need longer (e.g. extended thinking on large prompts) bump this
via ``GEODE_CLAUDE_CLI_TIMEOUT_S`` env."""

CLAUDE_CLI_TIMEOUT_ENV = "GEODE_CLAUDE_CLI_TIMEOUT_S"

CLAUDE_CLI_MODEL_NOT_FOUND = "claude-cli-model-not-found"
"""Sentinel for the metadata field surfaced when claude CLI rejects
the model id (operator typo / model deprecated). Sliced over to
inspect_ai's ``ModelOutput.metadata`` so downstream telemetry can
spot the failure mode without scraping stderr."""


class ClaudeCliInvocationError(RuntimeError):
    """Raised when the ``claude`` binary cannot be located, the
    subprocess exits non-zero, or stream-json output is unparseable.

    Carries enough operator context (returncode + stderr clip) to
    diagnose without re-running the audit. inspect_ai's harness
    wraps this into a ``ModelEvent`` with the error string visible
    in the Inspect viewer."""


@dataclass(frozen=True, slots=True)
class StreamJsonEvent:
    """One row of ``claude --print --output-format stream-json``.

    Wraps the raw dict so callers (test fixtures, parser) treat the
    event stream as a typed sequence. We accept ANY ``type`` field
    value — claude CLI may emit new event types in future versions
    and the parser should tolerate the addition (forward-compat).
    """

    type: str
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------


def _resolve_claude_binary() -> str:
    """Return absolute path to the ``claude`` binary or raise
    :class:`ClaudeCliInvocationError`.

    Resolution order (Codex CLI / paperclip parity):
      1. ``$GEODE_CLAUDE_CLI_BIN`` env override (operator pins).
      2. ``shutil.which("claude")`` (PATH lookup).
    """
    override = os.environ.get(CLAUDE_CLI_BIN_ENV)
    if override:
        if shutil.which(override) is None and not os.path.isfile(override):
            raise ClaudeCliInvocationError(
                f"{CLAUDE_CLI_BIN_ENV}={override!r} but no executable at that path. "
                "Set to the full path of the `claude` binary or unset to use PATH."
            )
        return override
    found = shutil.which(_DEFAULT_CLAUDE_BIN)
    if not found:
        raise ClaudeCliInvocationError(
            "`claude` binary not found on PATH. Install Claude Code "
            "(https://docs.anthropic.com/claude/docs/claude-code) or set "
            f"{CLAUDE_CLI_BIN_ENV} to the full path."
        )
    return found


def _resolve_timeout_s() -> float:
    """Env override for subprocess timeout. Operators bump for long
    extended-thinking calls. Defaults to module constant."""
    raw = os.environ.get(CLAUDE_CLI_TIMEOUT_ENV)
    if not raw:
        return CLAUDE_CLI_SUBPROCESS_TIMEOUT_S
    try:
        return max(1.0, float(raw))
    except ValueError:
        log.warning(
            "%s=%r not a number; using default %.0fs",
            CLAUDE_CLI_TIMEOUT_ENV,
            raw,
            CLAUDE_CLI_SUBPROCESS_TIMEOUT_S,
        )
        return CLAUDE_CLI_SUBPROCESS_TIMEOUT_S


# ---------------------------------------------------------------------------
# argv builder
# ---------------------------------------------------------------------------


def build_claude_cli_argv(
    *,
    binary: str,
    model_name: str,
    max_turns: int = 1,
    mcp_config_path: str | None = None,
    allowed_tools: list[str] | None = None,
    extra_args: Iterable[str] | None = None,
) -> list[str]:
    """Construct the ``claude --print`` argv.

    Args:
        binary: Absolute path to ``claude``.
        model_name: Anthropic model id (e.g. ``claude-opus-4-7``).
            Passed via ``--model`` so the CLI respects per-call
            routing instead of its default.
        max_turns: ``--max-turns`` cap. Defaults to 1 because
            inspect_ai expects ``generate()`` to return after one
            turn (it owns the iteration loop).
        mcp_config_path: ``--mcp-config`` JSON path. ``None`` skips
            MCP server registration — CSA-2 wires this for the
            tool-use case.
        allowed_tools: Whitelist of tool names (``["mcp__<server>__
            <tool>", ...]``) when MCP is used. Pairs with
            ``mcp_config_path``.
        extra_args: Additional flags to append (test injection,
            operator hooks). Validated only by claude CLI itself.

    The output format is pinned to ``stream-json`` + ``--verbose`` —
    we need every event to construct ``ModelOutput`` faithfully.
    """
    argv: list[str] = [
        binary,
        "--print",
        "-",  # read prompt from stdin
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model_name,
        "--max-turns",
        str(max_turns),
    ]
    if mcp_config_path:
        argv += ["--mcp-config", mcp_config_path, "--strict-mcp-config"]
    if allowed_tools:
        # CLI flag accepts space-or-comma-separated list.
        argv += ["--allowed-tools", ",".join(allowed_tools)]
    if extra_args:
        argv += list(extra_args)
    return argv


# ---------------------------------------------------------------------------
# Message serialisation
# ---------------------------------------------------------------------------


_ROLE_HEADERS = {
    "system": "<<<SYSTEM>>>",
    "user": "<<<USER>>>",
    "assistant": "<<<ASSISTANT>>>",
    "tool": "<<<TOOL_RESULT>>>",
}


def serialise_messages_to_prompt(messages: list[Any]) -> str:
    """Flatten ``inspect_ai.ChatMessage[]`` into a single stdin prompt.

    The ``claude --print`` CLI accepts one prompt over stdin and
    handles its own system-message setup internally. We preserve
    multi-turn context by joining role-tagged blocks with sentinels.

    The role-header sentinels (``<<<USER>>>`` etc.) are intentionally
    visible — the LLM treats them as conversational scaffolding. For
    inspect_petri's auditor that orchestrates multi-turn dialogues,
    this matches the existing transcript style.

    Accepts duck-typed messages with ``role`` + ``content`` attrs
    (pydantic BaseModel) so tests can pass plain SimpleNamespace
    without importing the inspect_ai ChatMessage classes.
    """
    parts: list[str] = []
    for msg in messages:
        role = getattr(msg, "role", "user")
        header = _ROLE_HEADERS.get(role, f"<<<{role.upper()}>>>")
        content = getattr(msg, "content", "")
        # Normalise content shape — inspect_ai uses str OR list[Content]
        # where Content has ``.text`` (text blocks). Tool blocks are
        # ignored in CSA-1 (CSA-2 handles them).
        text_chunks: list[str] = []
        if isinstance(content, str):
            text_chunks.append(content)
        elif isinstance(content, list):
            for block in content:
                block_text = getattr(block, "text", None)
                if isinstance(block_text, str):
                    text_chunks.append(block_text)
        parts.append(f"{header}\n{''.join(text_chunks).rstrip()}")
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# stream-json parser
# ---------------------------------------------------------------------------


def parse_stream_json_events(stdout: str) -> list[StreamJsonEvent]:
    """Parse the ``claude --print --output-format stream-json --verbose``
    stdout into a list of :class:`StreamJsonEvent`.

    Each line is a JSON object with a ``type`` field. Malformed lines
    are silently skipped (forward-compat: claude CLI may emit non-JSON
    debug lines under certain conditions). An empty stdout returns an
    empty list — caller decides whether that's a failure.
    """
    events: list[StreamJsonEvent] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            log.debug("claude-cli: skipping non-JSON stdout line: %r", line[:200])
            continue
        if not isinstance(row, dict):
            continue
        event_type = row.get("type", "")
        if not isinstance(event_type, str):
            event_type = ""
        events.append(StreamJsonEvent(type=event_type, payload=row))
    return events


def _extract_assistant_text(events: list[StreamJsonEvent]) -> str:
    """Concatenate the assistant text from a stream-json event sequence.

    Looks for ``content_block_delta`` events with ``delta.type ==
    "text_delta"`` (canonical claude CLI streaming shape) AND for the
    terminal ``result`` event's ``result`` field (a single-shot
    fallback some CLI versions emit). The first non-empty source wins.
    """
    chunks: list[str] = []
    for event in events:
        if event.type == "content_block_delta":
            delta = event.payload.get("delta", {})
            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                text = delta.get("text", "")
                if isinstance(text, str):
                    chunks.append(text)
    if chunks:
        return "".join(chunks)
    # Fallback — `result` event carries the final text directly
    for event in events:
        if event.type == "result":
            text = event.payload.get("result", "")
            if isinstance(text, str) and text:
                return text
    return ""


def _extract_stop_reason(events: list[StreamJsonEvent]) -> str:
    """Map claude CLI ``stop_reason`` → inspect_ai canonical labels.

    inspect_ai uses ``"stop" | "max_tokens" | "tool_calls" | ...``
    while claude CLI emits ``"end_turn" | "tool_use" | "max_tokens" |
    "stop_sequence"``. We translate the common pairs.
    """
    raw: str | None = None
    for event in events:
        if event.type == "message_delta":
            delta = event.payload.get("delta", {})
            if isinstance(delta, dict):
                stop = delta.get("stop_reason")
                if isinstance(stop, str):
                    raw = stop
                    break
        if event.type == "result":
            stop = event.payload.get("stop_reason")
            if isinstance(stop, str):
                raw = stop
                break
    if raw is None:
        return "unknown"
    mapping = {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "tool_use": "tool_calls",
        "max_tokens": "max_tokens",
    }
    return mapping.get(raw, "unknown")


def _extract_usage(events: list[StreamJsonEvent]) -> dict[str, int]:
    """Sum input/output tokens across the event stream.

    claude CLI emits ``usage`` on multiple events (``message_start``,
    ``message_delta``, ``result``) — the most authoritative copy is on
    the terminal ``result`` event when ``--verbose`` is set.
    """
    for event in reversed(events):
        if event.type == "result":
            usage = event.payload.get("usage", {})
            if isinstance(usage, dict):
                return {
                    "input_tokens": int(usage.get("input_tokens") or 0),
                    "output_tokens": int(usage.get("output_tokens") or 0),
                    "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
                    "cache_creation_input_tokens": int(
                        usage.get("cache_creation_input_tokens") or 0
                    ),
                }
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------


async def _run_claude_subprocess(
    argv: list[str], stdin_text: str, timeout_s: float
) -> tuple[str, str, int]:
    """Spawn ``claude`` subprocess, pipe stdin, capture stdout+stderr.

    Returns ``(stdout, stderr, returncode)``. Raises
    :class:`ClaudeCliInvocationError` on timeout or process spawn
    failure (NOT on non-zero returncode — caller decides).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        raise ClaudeCliInvocationError(f"failed to spawn `claude`: {exc!r}") from exc
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(stdin_text.encode("utf-8")),
            timeout=timeout_s,
        )
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise ClaudeCliInvocationError(
            f"claude subprocess timed out after {timeout_s:.0f}s"
        ) from exc
    return (
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
        proc.returncode or 0,
    )


# ---------------------------------------------------------------------------
# Provider registration
# ---------------------------------------------------------------------------


if TYPE_CHECKING:  # pragma: no cover — import-only for type hints
    pass


def register() -> None:
    """Register ``@modelapi(name="claude-cli")`` with inspect_ai.

    Called from ``plugins/petri_audit/__init__.py`` at plugin load
    time so the provider is available when inspect_ai resolves a
    ``claude-cli/<model>`` id.
    """
    from inspect_ai.model import GenerateConfig, ModelOutput, modelapi
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.model._model import ModelAPI
    from inspect_ai.model._model_output import ChatCompletionChoice, ModelUsage

    @modelapi(name="claude-cli")
    class ClaudeCliAPI(ModelAPI):  # type: ignore[misc, unused-ignore]
        """inspect_ai provider that delegates to ``claude --print``.

        Identifier shape: ``claude-cli/<model-id>``. inspect_ai's
        router strips the ``claude-cli/`` prefix and instantiates this
        class with ``model_name=<model-id>``.

        ``# type: ignore[misc, unused-ignore]`` mirrors the sibling
        providers (``GeodeModelAPI`` / ``ClaudeOAuthAPI`` /
        ``OpenAICodexAPI``): inspect_ai ships without type stubs, so
        in the default ``uv sync`` (no ``[audit]`` extra) environment
        ``ModelAPI`` resolves to ``Any`` and strict mypy rejects the
        subclass; with the extra installed, the suppression is unused
        (hence ``unused-ignore`` flag).
        """

        def __init__(
            self,
            model_name: str,
            base_url: str | None = None,
            api_key: str | None = None,
            api_key_vars: list[str] | None = None,
            config: Any = None,
            **model_args: Any,
        ) -> None:
            super().__init__(
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                api_key_vars=api_key_vars or [],
                config=config or GenerateConfig(),
            )
            self._binary = _resolve_claude_binary()
            self._timeout_s = _resolve_timeout_s()
            self._model_args = model_args

        async def generate(
            self,
            input: Any,  # list[ChatMessage]
            tools: Any,  # list[ToolInfo]
            tool_choice: Any,  # ToolChoice
            config: Any,  # GenerateConfig
        ) -> Any:  # ModelOutput
            # CSA-2 (2026-05-22): tool support via MCP bridge. The text-
            # only path is the hot path (judge role); the tool path
            # spins up a per-call stdio MCP server and is gated behind
            # ``if tools``. Same OAuth-friendly subprocess invocation
            # in both branches — only the argv + parser differ.
            if tools:
                return await self._generate_with_tools(input, tools)
            return await self._generate_text_only(input)

        async def _generate_text_only(self, input: Any) -> Any:
            argv = build_claude_cli_argv(
                binary=self._binary,
                model_name=self.model_name,
            )
            prompt = serialise_messages_to_prompt(input)
            stdout, stderr, returncode = await _run_claude_subprocess(argv, prompt, self._timeout_s)
            if returncode != 0:
                raise ClaudeCliInvocationError(f"claude exited {returncode}: {stderr[:400]!r}")
            events = parse_stream_json_events(stdout)
            if not events:
                raise ClaudeCliInvocationError(
                    f"claude stdout had no stream-json events. stderr: {stderr[:400]!r}"
                )
            text = _extract_assistant_text(events)
            stop_reason = _extract_stop_reason(events)
            usage = _build_usage(_extract_usage(events))
            choice = ChatCompletionChoice(
                message=ChatMessageAssistant(content=text),
                stop_reason=stop_reason,
            )
            return ModelOutput(
                model=self.model_name,
                choices=[choice],
                completion=text,
                usage=usage,
            )

        async def _generate_with_tools(self, input: Any, tools: Any) -> Any:
            # Lazy-import so plain ``import plugins.petri_audit.
            # claude_cli_provider`` does not pay the mcp library +
            # bridge package cold-start cost when tools aren't used.
            from plugins.petri_audit.mcp_bridge import (
                BRIDGE_SERVER_NAME,
                extract_tool_calls,
                prepare_bridge,
                release_bridge,
            )

            invocation = prepare_bridge(tools)
            try:
                argv = build_claude_cli_argv(
                    binary=self._binary,
                    model_name=self.model_name,
                    mcp_config_path=str(invocation.mcp_config_json),
                    allowed_tools=invocation.allowed_tools,
                )
                prompt = serialise_messages_to_prompt(input)
                stdout, stderr, returncode = await _run_claude_subprocess(
                    argv, prompt, self._timeout_s
                )
                if returncode != 0:
                    raise ClaudeCliInvocationError(f"claude exited {returncode}: {stderr[:400]!r}")
                events = parse_stream_json_events(stdout)
                if not events:
                    raise ClaudeCliInvocationError(
                        f"claude stdout had no stream-json events. stderr: {stderr[:400]!r}"
                    )
                text = _extract_assistant_text(events)
                tool_calls = extract_tool_calls(events, server_name=BRIDGE_SERVER_NAME)
                # ``stop_reason="tool_calls"`` when claude emitted any
                # tool_use blocks. Otherwise fall back to CSA-1's
                # end_turn / stop_sequence mapping. Tool_calls is the
                # inspect_ai-blessed sentinel for the solver's
                # tool-dispatch path.
                stop_reason = "tool_calls" if tool_calls else _extract_stop_reason(events)
                usage = _build_usage(_extract_usage(events))
                choice = ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=text,
                        tool_calls=tool_calls or None,
                    ),
                    stop_reason=stop_reason,
                )
                return ModelOutput(
                    model=self.model_name,
                    choices=[choice],
                    completion=text,
                    usage=usage,
                )
            finally:
                release_bridge(invocation)

    def _build_usage(usage_dict: dict[str, int]) -> Any:
        return ModelUsage(
            input_tokens=usage_dict["input_tokens"],
            output_tokens=usage_dict["output_tokens"],
            total_tokens=usage_dict["input_tokens"] + usage_dict["output_tokens"],
            input_tokens_cache_read=usage_dict["cache_read_input_tokens"] or None,
            input_tokens_cache_write=usage_dict["cache_creation_input_tokens"] or None,
        )

    globals()["ClaudeCliAPI"] = ClaudeCliAPI
