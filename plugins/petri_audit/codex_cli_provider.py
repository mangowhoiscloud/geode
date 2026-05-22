"""Paperclip-pattern adapter — inspect_ai provider that invokes
``codex exec`` subprocess for every ``generate()`` call.

CSA-1b (2026-05-22) — scaffold + text-only generate (judge role).

Why this exists
===============

Sibling of CSA-1's ``claude_cli_provider``. Same architectural
motivation: avoid raw OpenAI / Anthropic SDK calls on OAuth-routed
sessions (where rate-limit enforcement is harsh) by delegating to
the local CLI binary which knows how to talk to its own
authentication backend.

Pattern source (verified): ``~/workspace/paperclip/packages/adapters/
codex-local/src/server/codex-args.ts:53`` — paperclip invokes
``codex exec --json [-c key=val ...] -`` with stdin prompt and
parses the per-line JSON event stream.

Differences from CSA-1 (claude-cli)
====================================

* **Subcommand**: ``codex exec`` (non-interactive) instead of
  ``claude --print``.
* **Output flag**: ``--json`` (single flag — codex emits per-line
  JSON natively; no separate ``--verbose`` needed).
* **Model override**: ``--model <m>`` directly OR ``-c model=<m>``
  config override. We use ``--model`` for parity with ``claude``.
* **Event shapes**: ``thread.started`` / ``item.completed`` /
  ``turn.completed`` / ``turn.failed`` (NOT claude's
  ``message_start`` / ``content_block_delta`` / ``message_stop``).
* **Stdin marker**: ``-`` (same as claude).
* **Resume**: ``codex exec resume <session_id> -`` (subcommand
  form, not flag).

CSA-1b scope
============

* Provider scaffold + ``@modelapi("codex-cli")`` registration.
* argv builder + stdin serialiser + per-line JSON parser.
* ``ModelOutput`` construction (content / usage / stop_reason).
* No tool support — ``generate()`` with non-empty ``tools`` raises
  ``NotImplementedError("tool_use deferred to CSA-2b MCP bridge")``.

CSA-2b will add MCP bridge for auditor tool-use. Codex has first-class
MCP support (``codex mcp`` subcommand for management + ``codex
mcp-server`` for codex AS MCP server) so the bridge work is lower-risk
than the claude side.

Operator surface
================

inspect_ai picks up the provider when the model id is prefixed with
``codex-cli/`` (e.g. ``codex-cli/gpt-5.5``). The ``to_inspect_model``
router in ``models.py`` flips ``source="openai-codex"`` configs to
this prefix once the manifest is updated in CSA-3.
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
    "CODEX_CLI_BIN_ENV",
    "CODEX_CLI_SUBPROCESS_TIMEOUT_S",
    "CODEX_CLI_TIMEOUT_ENV",
    "CodexCliInvocationError",
    "build_codex_cli_argv",
    "parse_codex_jsonl_events",
    "register",
    "serialise_messages_to_prompt",
]


CODEX_CLI_BIN_ENV = "GEODE_CODEX_CLI_BIN"
"""Operator override for the ``codex`` binary path. When unset, the
provider uses :func:`shutil.which("codex")`."""

_DEFAULT_CODEX_BIN = "codex"

CODEX_CLI_SUBPROCESS_TIMEOUT_S = 600.0
"""10-minute hard ceiling per subprocess invocation — mirrors
CSA-1 (claude-cli) for consistency. Operators override via
``GEODE_CODEX_CLI_TIMEOUT_S``."""

CODEX_CLI_TIMEOUT_ENV = "GEODE_CODEX_CLI_TIMEOUT_S"


class CodexCliInvocationError(RuntimeError):
    """Raised when the ``codex`` binary cannot be located, the
    subprocess exits non-zero, or the JSONL event stream is
    unparseable. Mirrors :class:`ClaudeCliInvocationError` shape so
    callers can ``except`` on either with the same handler logic."""


@dataclass(frozen=True, slots=True)
class CodexJsonlEvent:
    """One row of ``codex exec --json``.

    Forward-compatible — accepts ANY ``type`` value so codex CLI can
    add new event types without breaking the parser."""

    type: str
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------


def _resolve_codex_binary() -> str:
    """Return absolute path to ``codex`` binary or raise.

    Resolution order:
      1. ``$GEODE_CODEX_CLI_BIN`` env override.
      2. ``shutil.which("codex")``.
    """
    override = os.environ.get(CODEX_CLI_BIN_ENV)
    if override:
        if shutil.which(override) is None and not os.path.isfile(override):
            raise CodexCliInvocationError(
                f"{CODEX_CLI_BIN_ENV}={override!r} but no executable at that path. "
                "Set to the full path of the `codex` binary or unset to use PATH."
            )
        return override
    found = shutil.which(_DEFAULT_CODEX_BIN)
    if not found:
        raise CodexCliInvocationError(
            "`codex` binary not found on PATH. Install Codex CLI "
            "(https://github.com/openai/codex) or set "
            f"{CODEX_CLI_BIN_ENV} to the full path."
        )
    return found


def _resolve_timeout_s() -> float:
    """Env override for subprocess timeout. Mirrors CSA-1 helper."""
    raw = os.environ.get(CODEX_CLI_TIMEOUT_ENV)
    if not raw:
        return CODEX_CLI_SUBPROCESS_TIMEOUT_S
    try:
        return max(1.0, float(raw))
    except ValueError:
        log.warning(
            "%s=%r not a number; using default %.0fs",
            CODEX_CLI_TIMEOUT_ENV,
            raw,
            CODEX_CLI_SUBPROCESS_TIMEOUT_S,
        )
        return CODEX_CLI_SUBPROCESS_TIMEOUT_S


# ---------------------------------------------------------------------------
# argv builder
# ---------------------------------------------------------------------------


def build_codex_cli_argv(
    *,
    binary: str,
    model_name: str,
    skip_git_repo_check: bool = True,
    bypass_sandbox: bool = False,
    resume_session_id: str | None = None,
    reasoning_effort: str | None = None,
    mcp_overrides: Iterable[str] | None = None,
    extra_args: Iterable[str] | None = None,
) -> list[str]:
    """Construct the ``codex exec --json`` argv.

    Args:
        binary: Absolute path to ``codex``.
        model_name: OpenAI model id (e.g. ``gpt-5.5``).
        skip_git_repo_check: ``--skip-git-repo-check`` flag. Default
            True — inspect_ai eval runs may execute outside a git
            repo; codex defaults to refusing those.
        bypass_sandbox: ``--dangerously-bypass-approvals-and-sandbox``.
            Default False. Operators opt in via config for headless
            audit runs that can't answer approval prompts.
        resume_session_id: When set, uses ``codex exec resume <id> -``
            subcommand form for multi-turn continuation. CSA-2b will
            wire this for the auditor's turn loop.
        reasoning_effort: ``-c model_reasoning_effort=<value>`` config
            override. ``"low" / "medium" / "high"``.
        extra_args: Additional flags to append (test injection).

    The output format is pinned to ``--json`` — we need every event
    to construct ``ModelOutput`` faithfully (text + usage).
    """
    argv: list[str] = [binary]
    if resume_session_id:
        argv += ["exec", "--json", "resume", resume_session_id]
    else:
        argv += ["exec", "--json"]
    if skip_git_repo_check:
        argv.append("--skip-git-repo-check")
    if bypass_sandbox:
        argv.append("--dangerously-bypass-approvals-and-sandbox")
    if model_name:
        argv += ["--model", model_name]
    if reasoning_effort:
        argv += ["-c", f"model_reasoning_effort={json.dumps(reasoning_effort)}"]
    if mcp_overrides:
        # CSA-2c (2026-05-22) — MCP bridge wiring goes here as a flat
        # sequence of ``-c key=value`` tokens emitted by
        # :func:`plugins.petri_audit.mcp_bridge.codex_overrides.build_codex_cli_mcp_overrides`.
        # Codex parses TOML values, so the bridge module already
        # JSON-quotes strings for parser parity.
        argv += list(mcp_overrides)
    if extra_args:
        argv += list(extra_args)
    # stdin marker — must come last (codex parses positional after
    # subcommand). When resume is used the marker is already after
    # the session id so we skip duplicate insertion.
    if "-" not in argv:
        argv.append("-")
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

    Identical strategy to CSA-1's claude provider — role-tagged
    sentinels preserve multi-turn context in a single prompt blob.
    codex exec accepts arbitrary prompt text via stdin.
    """
    parts: list[str] = []
    for msg in messages:
        role = getattr(msg, "role", "user")
        header = _ROLE_HEADERS.get(role, f"<<<{role.upper()}>>>")
        content = getattr(msg, "content", "")
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
# JSONL parser (codex format)
# ---------------------------------------------------------------------------


def parse_codex_jsonl_events(stdout: str) -> list[CodexJsonlEvent]:
    """Parse ``codex exec --json`` stdout into a list of events.

    Codex JSONL is one JSON object per line. Each event carries:

    * ``type`` — e.g. ``thread.started`` / ``item.completed`` /
      ``turn.completed`` / ``turn.failed`` / ``error``.
    * Type-specific payload fields.

    Malformed lines are silently skipped (forward-compat — codex CLI
    can emit non-JSON debug rows under certain conditions). Empty
    stdout returns an empty list.
    """
    events: list[CodexJsonlEvent] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            log.debug("codex-cli: skipping non-JSON stdout line: %r", line[:200])
            continue
        if not isinstance(row, dict):
            continue
        event_type = row.get("type", "")
        if not isinstance(event_type, str):
            event_type = ""
        events.append(CodexJsonlEvent(type=event_type, payload=row))
    return events


def _extract_agent_message(events: list[CodexJsonlEvent]) -> str:
    """Pull the final agent message text from the event stream.

    Pattern from paperclip's parser (``parse.ts:42-49``):

    * ``item.completed`` events carry ``item.{type, text}``.
    * The ``agent_message`` typed items hold the model's reply.
    * Multiple completions per turn are possible (codex can emit
      progressive item.completed events); we concatenate them in
      order.
    """
    chunks: list[str] = []
    for event in events:
        if event.type == "item.completed":
            item = event.payload.get("item", {})
            if not isinstance(item, dict):
                continue
            if item.get("type") == "agent_message":
                text = item.get("text", "")
                if isinstance(text, str) and text:
                    chunks.append(text)
    return "\n".join(chunks)


def _extract_session_id(events: list[CodexJsonlEvent]) -> str | None:
    """Pull the ``thread.started`` event's ``thread_id`` — codex's
    session identifier. Used by CSA-2b for multi-turn ``resume``."""
    for event in events:
        if event.type == "thread.started":
            tid = event.payload.get("thread_id")
            if isinstance(tid, str):
                return tid
    return None


def _extract_stop_reason(events: list[CodexJsonlEvent]) -> str:
    """Map codex event sequence → inspect_ai canonical stop_reason.

    * ``turn.completed`` → ``"stop"`` (normal end)
    * ``turn.failed`` / ``error`` → ``"stop"`` (with error in
      ModelOutput.error — codex doesn't distinguish "ran out of
      budget" cleanly).
    * Neither present → ``"unknown"``.
    """
    saw_complete = False
    for event in events:
        if event.type == "turn.completed":
            saw_complete = True
        if event.type in {"turn.failed", "error"}:
            return "stop"
    if saw_complete:
        return "stop"
    return "unknown"


def _extract_usage(events: list[CodexJsonlEvent]) -> dict[str, int]:
    """Sum token counts from the terminal ``turn.completed`` event."""
    for event in reversed(events):
        if event.type == "turn.completed":
            usage = event.payload.get("usage", {})
            if isinstance(usage, dict):
                return {
                    "input_tokens": int(usage.get("input_tokens") or 0),
                    "output_tokens": int(usage.get("output_tokens") or 0),
                    "cached_input_tokens": int(usage.get("cached_input_tokens") or 0),
                }
    return {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}


def _extract_error(events: list[CodexJsonlEvent]) -> str | None:
    """Surface error message from ``error`` or ``turn.failed`` event."""
    for event in events:
        if event.type == "error":
            msg = event.payload.get("message", "")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
        if event.type == "turn.failed":
            err = event.payload.get("error", {})
            if isinstance(err, dict):
                msg = err.get("message", "")
                if isinstance(msg, str) and msg.strip():
                    return msg.strip()
    return None


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------


async def _run_codex_subprocess(
    argv: list[str], stdin_text: str, timeout_s: float
) -> tuple[str, str, int]:
    """Spawn ``codex`` subprocess. Mirrors CSA-1 runner contract.

    Returns ``(stdout, stderr, returncode)``. Raises
    :class:`CodexCliInvocationError` on spawn failure or timeout.
    Caller decides what to do with non-zero returncode.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        raise CodexCliInvocationError(f"failed to spawn `codex`: {exc!r}") from exc
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(stdin_text.encode("utf-8")),
            timeout=timeout_s,
        )
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise CodexCliInvocationError(f"codex subprocess timed out after {timeout_s:.0f}s") from exc
    return (
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
        proc.returncode or 0,
    )


# ---------------------------------------------------------------------------
# Provider registration
# ---------------------------------------------------------------------------


if TYPE_CHECKING:  # pragma: no cover
    pass


def register() -> None:
    """Register ``@modelapi(name="codex-cli")`` with inspect_ai.

    Called from ``plugins/petri_audit/__init__.py`` at plugin load
    time. Idempotent — re-registration on the same name overwrites.
    """
    from inspect_ai.model import GenerateConfig, ModelOutput, modelapi
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.model._model import ModelAPI
    from inspect_ai.model._model_output import ChatCompletionChoice, ModelUsage

    @modelapi(name="codex-cli")
    class CodexCliAPI(ModelAPI):  # type: ignore[misc, unused-ignore]
        """inspect_ai provider that delegates to ``codex exec --json``.

        Identifier shape: ``codex-cli/<model-id>``. inspect_ai's
        router strips the ``codex-cli/`` prefix and instantiates this
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
            self._binary = _resolve_codex_binary()
            self._timeout_s = _resolve_timeout_s()
            self._model_args = model_args

        async def generate(
            self,
            input: Any,  # list[ChatMessage]
            tools: Any,  # list[ToolInfo]
            tool_choice: Any,  # ToolChoice
            config: Any,  # GenerateConfig
        ) -> Any:  # ModelOutput
            if tools:
                return await self._generate_with_tools(input, tools)
            return await self._generate_text_only(input)

        async def _generate_text_only(self, input: Any) -> Any:
            argv = build_codex_cli_argv(
                binary=self._binary,
                model_name=self.model_name,
            )
            prompt = serialise_messages_to_prompt(input)
            # PR-LQ-Phase3 (2026-05-22) — share the
            # codex-cli-subagent lane with the self-improving-loop
            # mutator path so the host ChatGPT-Plus OAuth bucket
            # sees at most ``DEFAULT_CODEX_CLI_LANE_MAX`` (=2)
            # concurrent ``codex exec`` subprocesses. Parity with the
            # Claude-side wiring in ``ClaudeCliAPI.generate``.
            from core.orchestration.codex_cli_lane import acquire_codex_cli_lane_async

            async with acquire_codex_cli_lane_async(key=f"petri.codex_cli.{self.model_name}"):
                stdout, stderr, returncode = await _run_codex_subprocess(
                    argv, prompt, self._timeout_s
                )
            if returncode != 0:
                raise CodexCliInvocationError(f"codex exited {returncode}: {stderr[:400]!r}")
            events = parse_codex_jsonl_events(stdout)
            if not events:
                raise CodexCliInvocationError(
                    f"codex stdout had no JSONL events. stderr: {stderr[:400]!r}"
                )
            text = _extract_agent_message(events)
            stop_reason = _extract_stop_reason(events)
            usage_dict = _extract_usage(events)
            error_msg = _extract_error(events)
            choice = ChatCompletionChoice(
                message=ChatMessageAssistant(content=text),
                stop_reason=stop_reason,
            )
            usage = ModelUsage(
                input_tokens=usage_dict["input_tokens"],
                output_tokens=usage_dict["output_tokens"],
                total_tokens=usage_dict["input_tokens"] + usage_dict["output_tokens"],
                # codex calls cache `cached_input_tokens`; map to
                # inspect_ai's cache_read field.
                input_tokens_cache_read=usage_dict["cached_input_tokens"] or None,
            )
            return ModelOutput(
                model=self.model_name,
                choices=[choice],
                completion=text,
                usage=usage,
                error=error_msg,
            )

        async def _generate_with_tools(self, input: Any, tools: Any) -> Any:
            # Lazy-import so plain ``import plugins.petri_audit.
            # codex_cli_provider`` does not pay the mcp library +
            # bridge package cold-start cost when tools aren't used.
            from plugins.petri_audit.mcp_bridge import (
                build_codex_cli_mcp_overrides,
                extract_codex_tool_calls,
                prepare_bridge,
                release_bridge,
            )

            invocation = prepare_bridge(tools)
            try:
                argv = build_codex_cli_argv(
                    binary=self._binary,
                    model_name=self.model_name,
                    mcp_overrides=build_codex_cli_mcp_overrides(invocation),
                )
                prompt = serialise_messages_to_prompt(input)
                # PR-LQ-Phase3 (2026-05-22) — share the codex-cli-subagent
                # lane (parity with the text-only path above).
                from core.orchestration.codex_cli_lane import (
                    acquire_codex_cli_lane_async,
                )

                async with acquire_codex_cli_lane_async(key=f"petri.codex_cli.{self.model_name}"):
                    stdout, stderr, returncode = await _run_codex_subprocess(
                        argv, prompt, self._timeout_s
                    )
                if returncode != 0:
                    raise CodexCliInvocationError(f"codex exited {returncode}: {stderr[:400]!r}")
                events = parse_codex_jsonl_events(stdout)
                if not events:
                    raise CodexCliInvocationError(
                        f"codex stdout had no JSONL events. stderr: {stderr[:400]!r}"
                    )
                text = _extract_agent_message(events)
                # extract_codex_tool_calls operates on the raw JSON
                # shape (``{"type": ..., "item": {...}}``); convert
                # the CodexJsonlEvent dataclasses back to that shape
                # at the call boundary.
                event_dicts = [{"type": e.type, **e.payload} for e in events]
                tool_calls = extract_codex_tool_calls(event_dicts)
                # Stop reason: tool_use vs text. inspect_ai's contract
                # is "tool_calls" when any tool call was emitted, else
                # the regular stop_reason.
                stop_reason = "tool_calls" if tool_calls else _extract_stop_reason(events)
                usage_dict = _extract_usage(events)
                error_msg = _extract_error(events)
                choice = ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=text,
                        tool_calls=tool_calls or None,
                    ),
                    stop_reason=stop_reason,
                )
                usage = ModelUsage(
                    input_tokens=usage_dict["input_tokens"],
                    output_tokens=usage_dict["output_tokens"],
                    total_tokens=usage_dict["input_tokens"] + usage_dict["output_tokens"],
                    input_tokens_cache_read=usage_dict["cached_input_tokens"] or None,
                )
                return ModelOutput(
                    model=self.model_name,
                    choices=[choice],
                    completion=text,
                    usage=usage,
                    error=error_msg,
                )
            finally:
                # Release the per-call tempdir + bridge process. Runs
                # even on subprocess failure (boundary-violation safety
                # — matches the claude side's contract).
                release_bridge(invocation)

    globals()["CodexCliAPI"] = CodexCliAPI
