"""Shared helpers for subprocess-backed adapters (claude-cli / codex-cli).

Both ``ClaudeCliAdapter`` and ``CodexCliAdapter`` flatten the adapter call
into a single stdin prompt fed to a local CLI binary (``claude --print`` /
``codex exec``). The flatten shape is provider-agnostic, so the helper lives
here rather than being copy-pasted across the two adapters (Codex MCP review
2026-05-23 MEDIUM finding — cross-adapter helper import).
"""

from __future__ import annotations

from core.llm.adapters.base import AdapterCallRequest


def build_subprocess_stdin(req: AdapterCallRequest) -> str:
    """Flatten the adapter call into a single stdin prompt.

    System prompt prepended as a marker; user/assistant turns concatenated.
    Tool turns are skipped — the subprocess text-only path doesn't support
    them (callers pin ``supports_tools=False`` in their ``list_models``
    output).
    """
    parts: list[str] = []
    # PR-V (2026-05-24, Codex MCP review of #1588) — paperclip
    # ``execute.ts:694-698`` parity. When resuming a prior claude-cli
    # session the system prompt is already in the backend's session
    # cache; re-injecting it via stdin wastes 5-10K tokens per turn
    # (the exact saving PR-V's CHANGELOG claims). Skip the [SYSTEM]
    # block when ``resume_session_id`` is set so the quota cache hit
    # actually materialises. First-turn callers (empty
    # ``resume_session_id``) keep the legacy behaviour — the prompt
    # must be sent so claude-cli can cache it for the next turn.
    if req.system_prompt and not req.resume_session_id:
        parts.append("[SYSTEM]")
        parts.append(req.system_prompt)
        parts.append("")
    for m in req.messages:
        if m.role == "tool":
            continue
        label = m.role.upper()
        parts.append(f"[{label}]")
        if isinstance(m.content, str):
            parts.append(m.content)
        else:
            parts.append(str(m.content))
        parts.append("")
    return "\n".join(parts).strip() + "\n"


__all__ = ["build_subprocess_stdin"]
