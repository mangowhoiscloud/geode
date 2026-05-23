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
    if req.system_prompt:
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
