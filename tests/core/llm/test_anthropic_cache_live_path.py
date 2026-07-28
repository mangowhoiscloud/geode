"""Prompt-cache wiring on the LIVE Anthropic adapter path (2026-07-29).

The whole cache apparatus previously lived only inside the never-registered
``ClaudeAgenticAdapter`` — these tests pin it to ``build_create_kwargs`` /
``build_stream_kwargs`` so it can never silently strand again.
"""

from __future__ import annotations

from core.agent.system_injection import _REMINDER_TAG
from core.agent.system_prompt import PROMPT_CACHE_BOUNDARY
from core.llm.adapters._anthropic_common import build_create_kwargs, build_stream_kwargs
from core.llm.adapters.base import AdapterCallRequest, Message
from core.llm.providers.anthropic import (
    _SYSTEM_REMINDER_OPEN,
    _select_breakpoint_targets,
)


def _req(
    system: str, messages: tuple = (Message(role="user", content="hi"),)
) -> AdapterCallRequest:
    return AdapterCallRequest(
        model="claude-sonnet-5", system_prompt=system, messages=messages, max_tokens=64
    )


def test_boundary_split_marks_static_block_with_ttl() -> None:
    system = "STATIC RULES\n\n" + PROMPT_CACHE_BOUNDARY + "\n\nvolatile\n\n</dynamic_context>"
    kwargs = build_create_kwargs(_req(system))
    blocks = kwargs["system"]
    assert isinstance(blocks, list) and len(blocks) == 2
    assert blocks[0]["text"] == "STATIC RULES"
    assert blocks[0]["cache_control"]["type"] == "ephemeral"
    assert blocks[0]["cache_control"].get("ttl") == "1h", "static prefix must carry the 1h TTL"
    # dynamic block keeps the envelope BALANCED (open tag retained)
    assert blocks[1]["text"].startswith(PROMPT_CACHE_BOUNDARY)
    assert "cache_control" not in blocks[1]


def test_no_boundary_passthrough_str() -> None:
    kwargs = build_create_kwargs(_req("plain system"))
    assert kwargs["system"] == "plain system"


def test_empty_static_half_marks_dynamic_ephemeral() -> None:
    system = PROMPT_CACHE_BOUNDARY + "\n\nvolatile only\n\n</dynamic_context>"
    kwargs = build_create_kwargs(_req(system))
    blocks = kwargs["system"]
    assert len(blocks) == 1
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_stream_kwargs_share_cache_shaping() -> None:
    system = "S\n\n" + PROMPT_CACHE_BOUNDARY + "\n\nd\n\n</dynamic_context>"
    kwargs = build_stream_kwargs(_req(system))
    assert isinstance(kwargs["system"], list)


def test_messages_get_breakpoints_on_live_path() -> None:
    msgs = tuple(Message(role="user", content=f"turn {i}") for i in range(6))
    kwargs = build_create_kwargs(_req("s", messages=msgs))
    marked = [
        m
        for m in kwargs["messages"]
        if any(isinstance(b, dict) and "cache_control" in b for b in m.get("content", []))
    ]
    assert marked, "live path must attach message breakpoints"


def test_reminder_tag_constant_drift() -> None:
    # dual-SoT pin: providers-side literal must equal the system_injection tag
    assert f"<{_REMINDER_TAG}>" == _SYSTEM_REMINDER_OPEN


def test_volatile_reminder_excluded_from_breakpoints() -> None:
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "real turn"}]},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"<{_REMINDER_TAG}>\nCurrent round: 3\n</{_REMINDER_TAG}>"}
            ],
        },
    ]
    targets = _select_breakpoint_targets(messages, 3)
    assert 1 not in targets, "byte-volatile reminder must never hold a breakpoint slot"
    assert 0 in targets
