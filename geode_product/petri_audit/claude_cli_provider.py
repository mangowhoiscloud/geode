"""Inspect provider registration for the kernel-owned Claude CLI runtime."""

from __future__ import annotations

from typing import Any

from core.llm.adapters.claude_cli_runtime import (
    CLAUDE_CLI_BIN_ENV,
    CLAUDE_CLI_MODEL_NOT_FOUND,
    CLAUDE_CLI_SUBPROCESS_TIMEOUT_S,
    CLAUDE_TRANSIENT_UPSTREAM_RE,
    ClaudeCliInvocationError,
    ClaudeCliTransientUpstreamError,
    TransientSignal,
    build_claude_cli_argv,
    classify_transient_signal,
    extract_assistant_text,
    extract_session_id_from_events,
    extract_stop_reason,
    extract_usage_from_events,
    is_claude_transient_upstream_error,
    is_expected_tool_use_boundary,
    parse_stream_json_events,
    resolve_claude_binary,
    resolve_timeout_s,
    run_claude_subprocess,
)

_ROLE_HEADERS = {
    "system": "<<<SYSTEM>>>",
    "user": "<<<USER>>>",
    "assistant": "<<<ASSISTANT>>>",
    "tool": "<<<TOOL_RESULT>>>",
}


def serialise_messages_to_prompt(messages: list[Any]) -> str:
    """Flatten ``inspect_ai.ChatMessage[]`` into one role-tagged prompt."""
    parts: list[str] = []
    for msg in messages:
        role = getattr(msg, "role", "user")
        header = _ROLE_HEADERS.get(role, f"<<<{role.upper()}>>>")
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            chunks = [getattr(block, "text", None) for block in content]
            text = "".join(chunk for chunk in chunks if isinstance(chunk, str))
        else:
            text = ""
        parts.append(f"{header}\n{text.rstrip()}")
    return "\n\n".join(parts) + "\n"


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
            self._binary = resolve_claude_binary()
            self._timeout_s = resolve_timeout_s()
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
            # mutator path so the host OAuth bucket (and now the host
            # *RAM*) sees at most ``DEFAULT_CLAUDE_CLI_LANE_MAX`` (3
            # after PR-LANE-CAP-TIGHTER v0.99.76, 2026-05-27)
            # concurrent ``claude --print`` subprocesses. The lane runs
            # the blocking semaphore wait in a worker thread so the
            # event loop is not pinned while queued.
            from core.orchestration.claude_cli_lane import acquire_claude_cli_lane_async

            async with acquire_claude_cli_lane_async(key=f"petri.claude_cli.{self.model_name}"):
                stdout, stderr, returncode = await run_claude_subprocess(
                    argv, prompt, self._timeout_s
                )
            if returncode != 0:
                raise ClaudeCliInvocationError(f"claude exited {returncode}: {stderr[:400]!r}")
            events = parse_stream_json_events(stdout)
            if not events:
                raise ClaudeCliInvocationError(
                    f"claude stdout had no stream-json events. stderr: {stderr[:400]!r}"
                )
            text = extract_assistant_text(events)
            stop_reason = extract_stop_reason(events)
            usage = _build_usage(extract_usage_from_events(events))
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
            # Lazy-import so plain ``import geode_product.petri_audit.
            # claude_cli_provider`` does not pay the mcp library +
            # bridge package cold-start cost when tools aren't used.
            from geode_product.petri_audit.mcp_bridge import (
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
                stdout, stderr, returncode = await run_claude_subprocess(
                    argv, prompt, self._timeout_s
                )
                events = parse_stream_json_events(stdout)
                # Order matters here: when the subprocess truly fails
                # (no events at all), surface the exit code first;
                # ``is_expected_tool_use_boundary`` requires a terminal
                # ``result`` event so its check is meaningless when
                # ``events`` is empty.
                if returncode != 0 and (not events or not is_expected_tool_use_boundary(events)):
                    raise ClaudeCliInvocationError(f"claude exited {returncode}: {stderr[:400]!r}")
                if not events:
                    raise ClaudeCliInvocationError(
                        f"claude stdout had no stream-json events. stderr: {stderr[:400]!r}"
                    )
                text = extract_assistant_text(events)
                tool_calls = extract_tool_calls(events, server_name=BRIDGE_SERVER_NAME)
                # ``stop_reason="tool_calls"`` when claude emitted any
                # tool_use blocks. Otherwise fall back to CSA-1's
                # end_turn / stop_sequence mapping. Tool_calls is the
                # inspect_ai-blessed sentinel for the solver's
                # tool-dispatch path.
                stop_reason = "tool_calls" if tool_calls else extract_stop_reason(events)
                usage = _build_usage(extract_usage_from_events(events))
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
