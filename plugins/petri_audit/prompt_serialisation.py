"""Shared CLI-provider prompt serialisation (PR-CLEANUP-D2, 2026-06-10).

The role-header sentinel dict and ``serialise_messages_to_prompt`` used to
be byte-near-identical copies in ``claude_cli_provider`` and
``codex_cli_provider`` (the codex docstring admitted "Identical strategy to
CSA-1's claude provider"). A sentinel change on one side would have forked
the transcript wire format between the two subscription-CLI backends —
this module is the single SoT both import.

The role-header sentinels (``<<<USER>>>`` etc.) are intentionally visible —
the LLM treats them as conversational scaffolding, matching inspect_petri's
multi-turn transcript style.
"""

from __future__ import annotations

from typing import Any

ROLE_HEADERS = {
    "system": "<<<SYSTEM>>>",
    "user": "<<<USER>>>",
    "assistant": "<<<ASSISTANT>>>",
    "tool": "<<<TOOL_RESULT>>>",
}


def serialise_messages_to_prompt(messages: list[Any]) -> str:
    """Flatten ``inspect_ai.ChatMessage[]`` into a single stdin prompt.

    Both subscription CLIs (``claude --print`` / ``codex exec``) accept one
    prompt blob over stdin; multi-turn context is preserved by joining
    role-tagged blocks with sentinels.

    Accepts duck-typed messages with ``role`` + ``content`` attrs
    (pydantic BaseModel) so tests can pass plain SimpleNamespace without
    importing the inspect_ai ChatMessage classes. Content is ``str`` OR
    ``list[Content]`` where Content has ``.text``; tool blocks are ignored
    in CSA-1 (CSA-2 handles them).
    """
    parts: list[str] = []
    for msg in messages:
        role = getattr(msg, "role", "user")
        header = ROLE_HEADERS.get(role, f"<<<{role.upper()}>>>")
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
