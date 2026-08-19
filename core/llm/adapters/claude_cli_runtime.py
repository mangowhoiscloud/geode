"""Public subprocess contract shared by Claude CLI adapters."""

from core.llm.adapters._claude_cli_runtime import (
    CLAUDE_CLI_BIN_ENV,
    CLAUDE_CLI_MODEL_NOT_FOUND,
    CLAUDE_CLI_SUBPROCESS_TIMEOUT_S,
    CLAUDE_TRANSIENT_UPSTREAM_RE,
    ClaudeCliInvocationError,
    ClaudeCliTransientUpstreamError,
    TransientSignal,
    build_claude_cli_argv,
    classify_transient_signal,
    extract_session_id_from_events,
    extract_usage_from_events,
    is_claude_transient_upstream_error,
    parse_stream_json_events,
)
from core.llm.adapters._claude_cli_runtime import (
    _extract_assistant_text as extract_assistant_text,
)
from core.llm.adapters._claude_cli_runtime import (
    _extract_stop_reason as extract_stop_reason,
)
from core.llm.adapters._claude_cli_runtime import (
    _is_expected_tool_use_boundary as is_expected_tool_use_boundary,
)
from core.llm.adapters._claude_cli_runtime import (
    _resolve_claude_binary as resolve_claude_binary,
)
from core.llm.adapters._claude_cli_runtime import (
    _resolve_timeout_s as resolve_timeout_s,
)
from core.llm.adapters._claude_cli_runtime import (
    _run_claude_subprocess as run_claude_subprocess,
)

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
    "extract_assistant_text",
    "extract_session_id_from_events",
    "extract_stop_reason",
    "extract_usage_from_events",
    "is_claude_transient_upstream_error",
    "is_expected_tool_use_boundary",
    "parse_stream_json_events",
    "resolve_claude_binary",
    "resolve_timeout_s",
    "run_claude_subprocess",
]
