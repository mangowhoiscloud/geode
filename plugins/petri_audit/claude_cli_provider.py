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
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

log = logging.getLogger(__name__)

__all__ = [
    "CLAUDE_CLI_BIN_ENV",
    "CLAUDE_CLI_MODEL_NOT_FOUND",
    "CLAUDE_CLI_SUBPROCESS_TIMEOUT_S",
    "CLAUDE_TRANSIENT_UPSTREAM_RE",
    "ClaudeCliInvocationError",
    "ClaudeCliTransientUpstreamError",
    "TransientSignal",
    "build_claude_cli_argv",
    "classify_transient_signal",
    "extract_session_id_from_events",
    "is_claude_transient_upstream_error",
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


class ClaudeCliTransientUpstreamError(ClaudeCliInvocationError):
    """Raised when claude-cli's stdout/stderr matches an upstream
    rate-limit / overload / quota-reset signature.

    Subclass of :class:`ClaudeCliInvocationError` so existing
    ``except ClaudeCliInvocationError`` blocks still catch it; callers
    that want retry-with-backoff can dispatch on the subclass.

    Why it has its own class: the pre-classifier path was returning
    claude-cli's *error text* (``! Unexpected error. Auto-retrying.``)
    as the LLM's assistant message — the worker then terminated
    "successfully" with no tool calls and the caller recorded a
    ghost candidate. Failing loud here is the only way the parent
    sees an actual error to react to.

    ``signal`` (added 2026-05-24) carries the *matched* classifier hit
    so log readers can tell *which* upstream signature fired. The
    pre-signal path emitted only ``stderr_tail`` — invariably ``<empty>``
    because claude-cli writes its errors to stdout, not stderr — and
    log readers had to guess between rate_limit / overloaded / quota.

    ``dump_path`` is the optional full ``(stdout, stderr, parsed events,
    classifier signal, rc)`` post-mortem JSON that the adapter writes to
    ``~/.geode/diagnostics/`` on every transient hit. Reading the dump
    recovers the upstream error message claude-cli emitted in its
    ``result`` event (which is otherwise discarded after classification).
    """

    def __init__(
        self,
        message: str,
        *,
        signal: TransientSignal | None = None,
        dump_path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.signal = signal
        self.dump_path = dump_path


@dataclass(frozen=True, slots=True)
class TransientSignal:
    """One classifier hit on the transient-upstream regex.

    Returned by :func:`classify_transient_signal`. Pre-PR-T the
    classifier returned ``bool`` so callers could not distinguish
    *rate_limit* from *overloaded* from *quota-reset* — the diagnostic
    that drives the operator's next action (wait vs retry vs swap
    account) was lost. This dataclass carries the matched substring
    + the *source field* (stdout / stderr / which event type) so
    post-mortem operators can act on the actual upstream signature.
    """

    matched_text: str
    """The exact substring that matched ``CLAUDE_TRANSIENT_UPSTREAM_RE``,
    bounded to the first 200 chars to keep log lines tractable."""

    source: str
    """One of ``"stdout"`` / ``"stderr"`` / ``"event"`` — which raw
    field the regex hit."""

    event_type: str | None = None
    """When ``source == "event"`` this is the ``type`` of the
    :class:`StreamJsonEvent` carrying the matched text
    (``"result"`` / ``"assistant"`` / etc.). ``None`` for raw
    stdout/stderr hits."""

    event_field: str | None = None
    """When ``source == "event"`` and ``event_type == "result"`` this
    is the inner field key that carried the matched text
    (``"result"`` / ``"error"`` / ``"message"`` / ``"stderr"``).
    ``None`` for assistant events (those always carry the text in
    ``message.content[].text``)."""


# Ported from paperclip ``packages/adapters/claude-local/src/server/
# parse.ts:12`` ``CLAUDE_TRANSIENT_UPSTREAM_RE``. The set of phrases
# claude-cli (or the upstream Anthropic gateway it talks to) prints
# when a request was throttled, rejected by an overload guard, or
# bumped against the OAuth subscription's hourly / weekly quota.
# Matching is case-insensitive over the union of stdout, stderr, and
# the parsed ``result`` event's free-text fields.
# PR-PRT-STATUS (2026-05-25) — the first alternative was previously
# ``rate[-\s]?limit(?:ed)?`` with ``IGNORECASE``: the ``?`` made the
# separator optional, so a camelCase token like ``rateLimitType``
# (which appears inside claude-cli's INFORMATIONAL
# ``rate_limit_event`` payload — ``status="allowed"``) was matched
# as if it were a rejection signal. The v0.99.53 smoke surfaced this:
# every generator candidate produced a 12-turn successful claude-cli
# run (rc=0 + ``is_error=false`` + ``subtype="success"``) writing
# the seed markdown, but the classifier still flagged the stdout's
# embedded ``rateLimitType`` and the adapter raised
# ``ClaudeCliTransientUpstreamError`` — empty candidates downstream.
# The new ``[-_\s]`` (no ``?``) requires an actual separator, so
# ``rateLimit`` no longer matches while real "rate limited" / "rate
# limit error" / "rate-limit" / "rate_limit" messages still do.
CLAUDE_TRANSIENT_UPSTREAM_RE = re.compile(
    r"(?:rate[-_\s]limit(?:ed\b|_error\b|(?![_a-zA-Z]))"
    r"|too\s+many\s+requests"
    r"|\b429\b"
    r"|overloaded(?:_error)?"
    r"|server\s+overloaded"
    r"|service\s+unavailable"
    r"|\b503\b"
    r"|\b529\b"
    r"|high\s+demand"
    r"|try\s+again\s+later"
    r"|temporarily\s+unavailable"
    r"|throttl(?:ed|ing)"
    r"|throttlingexception"
    r"|servicequotaexceededexception"
    r"|out\s+of\s+extra\s+usage"
    r"|extra\s+usage\b"
    r"|claude\s+usage\s+limit\s+reached"
    r"|5[-\s]?hour\s+limit\s+reached"
    r"|weekly\s+limit\s+reached"
    r"|usage\s+limit\s+reached"
    r"|usage\s+cap\s+reached"
    r"|unexpected\s+error.*auto[-\s]?retrying"
    r")",
    re.IGNORECASE,
)


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
    disable_builtin_tools: bool = False,
    extra_args: Iterable[str] | None = None,
    resume_session_id: str | None = None,
    skip_permissions: bool = False,
    disable_session_persistence: bool = False,
    json_schema: dict[str, Any] | None = None,
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
        resume_session_id: PR-V (2026-05-24) paperclip parity. When
            non-empty/non-None claude-cli resumes the named session —
            the backend reuses the cached system prompt + prior
            conversation context so input billing drops to the
            cached-marker tier (paperclip ``execute.ts:680``: 5-10K
            tokens saved per heartbeat). When supplied alongside
            ``mcp_config_path`` the system prompt is NOT re-injected;
            claude-cli pulls the cached one (paperclip
            ``execute.ts:697`` "instructions are already in the
            session cache").
        skip_permissions: When True append the
            ``--dangerously-skip-permissions`` flag. Required for
            headless sub-agent execution (operator can't approve
            file-system permission prompts in a background spawn).
            GEODE's AgenticLoop adapter call passes True; inspect_ai
            / petri_audit interactive paths leave it False so the
            CLI's permission prompts still gate writes.

            Note: ``claude --help`` lists two related flags. The
            ``--allow-dangerously-skip-permissions`` variant only
            *enables the option*; ``--dangerously-skip-permissions``
            (no ``--allow-`` prefix) actually performs the bypass.
            PR-PERMS-FLAG-FIX (2026-05-25) corrected from the former
            to the latter after the v0.99.53 smoke surfaced the
            difference (1st sub-agent passed, 2nd hit Write denial
            because the meta-flag didn't actually bypass).
        disable_session_persistence: When True append
            ``--no-session-persistence``. claude-cli's own
            ``~/.claude/projects/<cwd-hash>/sessions/`` cache is keyed
            on cwd, NOT on GEODE's per-agent task_id, so successive
            smoke runs sharing the same cwd would read each other's
            cached conversation context — surfaced as "the excerpt
            mentions a scenario from a different smoke" in the v0.99.53
            smoke. Setting True turns off the persistence side-channel
            entirely, restoring strict per-spawn isolation at the cost
            of giving up PR-V's cross-turn cached-marker billing
            optimization. GEODE's AgenticLoop adapter call passes True
            because the sub-agent execution model is "one task_id, one
            spawn" — there is no cross-turn resume to optimize.
        json_schema: JSON Schema dict that constrains the model's
            final response shape. When set, appends
            ``--json-schema <json>`` (inline). Mirrors the Anthropic
            SDK's ``messages.parse(output_format=PydanticModel)`` →
            ``JSONOutputFormatParam(schema=..., type="json_schema")``
            structured-output API. Eliminates the "LLM returns natural
            language + code block instead of pure JSON" failure that
            clipped proximity / critic / pilot / meta_reviewer in the
            v0.99.53 smoke. Callers pass the dict; this helper handles
            serialisation.

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
    ]
    if resume_session_id:
        # PR-V — paperclip ``execute.ts:680`` argv parity. ``--resume``
        # must precede ``--model`` because claude-cli pulls the cached
        # model when the session is resumed.
        argv += ["--resume", resume_session_id]
    argv += [
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
    if disable_builtin_tools:
        # CSA-2 (2026-05-22) — when wrapping a real ``claude`` binary
        # (e.g. the cmux.app variant) the CLI auto-injects Claude
        # Code's built-in tools (Bash / Edit / ToolSearch / …) which
        # poison the auditor's tool choice (the LLM picks ToolSearch
        # over mcp__bridge__send_message). ``--tools ""`` disables
        # the built-in set so only MCP tools remain.
        argv += ["--tools", ""]
    if skip_permissions:
        # PR-SKIP-PERMS (2026-05-24) — operator directive: GEODE's
        # AgenticLoop adapter spawns claude-cli as a headless
        # subprocess, so any tool that requires interactive permission
        # approval (Write outside cwd, Bash dangerous commands, etc.)
        # would hang the subprocess on a prompt no one can answer.
        # PR-PERMS-FLAG-FIX (2026-05-25): the original
        # ``--allow-dangerously-skip-permissions`` is only the meta
        # ENABLE flag; ``--dangerously-skip-permissions`` (no
        # ``--allow-`` prefix) is the one that ACTUALLY bypasses.
        # v0.99.53 smoke caught this — 1st sub-agent passed (Bash
        # tools bypassed under a lighter check) while 2nd hit Write
        # denial because the meta-flag never enabled the bypass.
        # ``claude --help`` documents both: this flag is recommended
        # only for sandboxes; GEODE's sub-agent dispatch IS such a
        # sandbox (denied_tools set + working_dirs whitelist +
        # isolated subprocess).
        argv += ["--dangerously-skip-permissions"]
    if disable_session_persistence:
        # PR-PERMS-FLAG-FIX (2026-05-25) — claude-cli's own session
        # cache (``~/.claude/projects/<cwd-hash>/sessions/``) is keyed
        # on cwd, NOT on GEODE's per-agent ``task_id``. v0.99.53
        # smoke surfaced this as cross-smoke conversation leakage —
        # the proximity sub-agent in smoke 5 responded with "the
        # excerpt mentions a scenario from a different smoke" because
        # claude-cli auto-resumed a cached session from smoke 3 / 4
        # that happened to share the same cwd. Disabling persistence
        # restores strict per-spawn isolation at the cost of PR-V's
        # cross-turn cached-marker billing — acceptable for sub-agent
        # spawns which run once and exit. ``--no-session-persistence``
        # is documented in ``claude --help``: "Disable session
        # persistence ... only works with --print".
        argv += ["--no-session-persistence"]
    if json_schema is not None:
        # PR-PERMS-FLAG-FIX (2026-05-25, JSON-forcing bundle) — pass
        # the schema inline so claude-cli's structured-output
        # validator constrains the model's final response. Mirrors
        # paperclip / Anthropic SDK
        # ``messages.parse(output_format=...)`` → JSONOutputFormat.
        argv += ["--json-schema", json.dumps(json_schema, separators=(",", ":"))]
    if extra_args:
        argv += list(extra_args)
    return argv


def extract_session_id_from_events(events: list[StreamJsonEvent]) -> str:
    """Pull the ``session_id`` claude-cli emits in its ``system.init``
    event. Mirrors paperclip ``parse.ts:30-33`` — the first event
    claude-cli emits is always ``{type:"system", subtype:"init", session_id:"..."}``
    carrying the freshly-allocated session_id for this turn. Callers
    persist this so the next turn can resume via ``--resume <id>``.

    PR-V (2026-05-24). Returns empty string when no system.init event
    was seen (e.g. claude-cli crashed before init) so caller can
    distinguish "session unknown" from "session zero"."""
    for event in events:
        if event.type != "system":
            continue
        if event.payload.get("subtype") != "init":
            continue
        session_id = event.payload.get("session_id")
        if isinstance(session_id, str) and session_id:
            return session_id
    return ""


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

    Three sources are tried in order, and the first non-empty wins:

    1. ``content_block_delta`` with ``delta.type == "text_delta"`` —
       the Anthropic SSE shape that ``--output-format stream-json``
       passes through verbatim.
    2. ``assistant`` event with ``message.content[].text`` — claude-cli's
       aggregated shape (one event per finished assistant message).
       Mirrors paperclip ``parse.ts:36-49`` which is the only shape
       that path ever sees.
    3. Terminal ``result`` event's ``result`` field — single-shot
       fallback some CLI versions emit when the stream is empty.
    """
    delta_chunks: list[str] = []
    assistant_chunks: list[str] = []
    for event in events:
        if event.type == "content_block_delta":
            delta = event.payload.get("delta", {})
            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                text = delta.get("text", "")
                if isinstance(text, str):
                    delta_chunks.append(text)
        elif event.type == "assistant":
            message = event.payload.get("message", {})
            if not isinstance(message, dict):
                continue
            content = message.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "text":
                    continue
                text = block.get("text", "")
                if isinstance(text, str) and text:
                    assistant_chunks.append(text)
    if delta_chunks:
        return "".join(delta_chunks)
    if assistant_chunks:
        return "".join(assistant_chunks)
    for event in events:
        if event.type == "result":
            text = event.payload.get("result", "")
            if isinstance(text, str) and text:
                return text
    return ""


def classify_transient_signal(
    *,
    stdout: str,
    stderr: str,
    events: list[StreamJsonEvent] | None = None,
) -> TransientSignal | None:
    """Return the first :class:`TransientSignal` hit on the union of
    raw stdout, raw stderr, every parsed ``result`` event's free-text
    fields, and every ``assistant`` text block's ``text``. ``None``
    when nothing matches.

    Pre-PR-T this was :func:`is_claude_transient_upstream_error`
    returning ``bool`` — callers couldn't tell which signal fired so
    the post-mortem could not act on the actual upstream signature
    (rate_limit vs overloaded vs quota-reset). The dataclass-returning
    form preserves the matched substring + source field so
    log readers and operators get an actionable diagnostic.

    Search order matches paperclip's ``buildClaudeTransientHaystack``:
    raw stdout / stderr first, then events in arrival order.
    """
    if stdout:
        match = CLAUDE_TRANSIENT_UPSTREAM_RE.search(stdout)
        if match:
            return TransientSignal(
                matched_text=_signal_excerpt(stdout, match),
                source="stdout",
            )
    if stderr:
        match = CLAUDE_TRANSIENT_UPSTREAM_RE.search(stderr)
        if match:
            return TransientSignal(
                matched_text=_signal_excerpt(stderr, match),
                source="stderr",
            )
    if not events:
        return None
    for event in events:
        if event.type == "result":
            for key in ("result", "error", "message", "stderr"):
                value = event.payload.get(key)
                if not isinstance(value, str):
                    continue
                match = CLAUDE_TRANSIENT_UPSTREAM_RE.search(value)
                if match:
                    return TransientSignal(
                        matched_text=_signal_excerpt(value, match),
                        source="event",
                        event_type="result",
                        event_field=key,
                    )
        elif event.type == "assistant":
            message = event.payload.get("message", {})
            if not isinstance(message, dict):
                continue
            content = message.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "text":
                    continue
                text = block.get("text", "")
                if not isinstance(text, str):
                    continue
                match = CLAUDE_TRANSIENT_UPSTREAM_RE.search(text)
                if match:
                    return TransientSignal(
                        matched_text=_signal_excerpt(text, match),
                        source="event",
                        event_type="assistant",
                    )
    return None


def is_claude_transient_upstream_error(
    *,
    stdout: str,
    stderr: str,
    events: list[StreamJsonEvent] | None = None,
) -> bool:
    """Backwards-compatible ``bool`` wrapper around
    :func:`classify_transient_signal`. New callers should use the
    classifier directly so they keep the diagnostic context (matched
    text, source field, event type) instead of throwing it away.
    """
    return classify_transient_signal(stdout=stdout, stderr=stderr, events=events) is not None


def _signal_excerpt(haystack: str, match: re.Match[str], radius: int = 80) -> str:
    """Slice ``[match.start()-radius : match.end()+radius]`` from
    ``haystack`` so the log line carries the surrounding error sentence
    without flooding when claude-cli emits a multi-KB result event.

    Args:
        haystack: The full text the classifier ran the regex against
            (stdout / stderr / one event field). Named ``haystack``
            instead of ``text`` because the same name appears in event
            payloads (``content[].text``) and the alias keeps the two
            distinct at the call site.
        match: The ``re.Match`` object the classifier obtained.
        radius: Characters of pre/post context to include around the
            matched span. ``80`` is empirically enough to capture one
            sentence on either side of common Anthropic upstream
            errors (``rate_limit_error: ...``, ``overloaded_error: ...``).

    Returns:
        Whitespace-normalised excerpt bounded to 200 chars so the
        eventual log line stays a single row.
    """
    excerpt_start = max(0, match.start() - radius)
    excerpt_end = min(len(haystack), match.end() + radius)
    raw_excerpt = haystack[excerpt_start:excerpt_end]
    # Collapse whitespace runs so the log line is one row.
    collapsed = " ".join(raw_excerpt.split())
    return collapsed[:200]


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


def _is_expected_tool_use_boundary(events: list[StreamJsonEvent]) -> bool:
    """True when the terminal ``result`` event indicates a clean
    ``--max-turns 1`` stop at the tool_use boundary.

    The claude CLI exits with returncode 1 + ``is_error=true`` +
    ``errors=["Reached maximum number of turns (1)"]`` whenever the
    model would have continued (i.e. the assistant message ends with
    ``stop_reason=tool_use``). That is the **expected** behaviour for
    inspect_ai — the harness owns the iteration loop and just wants
    the tool_use blocks. CSA-2 detects this case so the provider
    doesn't surface it as ``ClaudeCliInvocationError``.

    Verified live 2026-05-22 against claude CLI 2.1.140.
    """
    for event in reversed(events):
        if event.type != "result":
            continue
        payload = event.payload
        terminal = payload.get("terminal_reason")
        stop = payload.get("stop_reason")
        return terminal == "max_turns" and stop == "tool_use"
    return False


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
            # PR-LQ-Phase2 (2026-05-22) — share the
            # claude-cli-subagent lane with the self-improving-loop
            # mutator path so the host OAuth bucket sees at most
            # ``DEFAULT_CLAUDE_CLI_LANE_MAX`` (=2) concurrent
            # ``claude --print`` subprocesses. The lane runs the
            # blocking semaphore wait in a worker thread so the
            # event loop is not pinned while queued.
            from core.orchestration.claude_cli_lane import acquire_claude_cli_lane_async

            async with acquire_claude_cli_lane_async(key=f"petri.claude_cli.{self.model_name}"):
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
                    disable_builtin_tools=True,
                )
                prompt = serialise_messages_to_prompt(input)
                stdout, stderr, returncode = await _run_claude_subprocess(
                    argv, prompt, self._timeout_s
                )
                events = parse_stream_json_events(stdout)
                # Order matters here: when the subprocess truly fails
                # (no events at all), surface the exit code first;
                # ``_is_expected_tool_use_boundary`` requires a terminal
                # ``result`` event so its check is meaningless when
                # ``events`` is empty.
                if returncode != 0 and (not events or not _is_expected_tool_use_boundary(events)):
                    raise ClaudeCliInvocationError(f"claude exited {returncode}: {stderr[:400]!r}")
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
