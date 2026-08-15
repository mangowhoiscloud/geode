"""Prompt-cache wiring on the LIVE Anthropic adapter path (2026-07-29).

The whole cache apparatus previously lived only inside the never-registered
``ClaudeAgenticAdapter`` — these tests pin it to ``build_create_kwargs`` /
``build_stream_kwargs`` so it can never silently strand again.
"""

from __future__ import annotations

import pytest
from core.agent.system_prompt import PROMPT_CACHE_BOUNDARY
from core.llm.adapters._anthropic_common import build_create_kwargs, build_stream_kwargs
from core.llm.adapters.base import AdapterCallRequest, Message


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


def test_context_management_injected_for_supported_model() -> None:
    """Context-management beta (ported + live-verified 2026-07-29) rides the
    live builder for supporting models, with beta tokens MERGED."""
    kwargs = build_create_kwargs(_req("s"))
    if "extra_body" not in kwargs:  # model gate — probe with a supported one
        kwargs = build_create_kwargs(
            AdapterCallRequest(
                model="claude-sonnet-4-6",
                system_prompt="s",
                messages=(Message(role="user", content="hi"),),
                max_tokens=64,
            )
        )
    cm = kwargs["extra_body"]["context_management"]
    kinds = [e["type"] for e in cm["edits"]]
    assert kinds == ["clear_tool_uses_20250919", "compact_20260112"]
    assert cm["edits"][1]["trigger"]["value"] > 0
    beta = kwargs["extra_headers"]["anthropic-beta"]
    assert "context-management-2025-06-27" in beta
    assert "compact-2026-01-12" in beta


def test_context_management_absent_for_unsupported_model() -> None:
    kwargs = build_create_kwargs(
        AdapterCallRequest(
            model="claude-haiku-4-5",
            system_prompt="s",
            messages=(Message(role="user", content="hi"),),
            max_tokens=64,
        )
    )
    assert "context_management" not in (kwargs.get("extra_body") or {})


def test_beta_merge_never_clobbers_existing_tokens() -> None:
    from core.llm.adapters._anthropic_common import _merge_beta

    kwargs = {"extra_headers": {"anthropic-beta": "computer-use-x"}}
    _merge_beta(kwargs, "context-management-2025-06-27", "computer-use-x")
    beta = kwargs["extra_headers"]["anthropic-beta"]
    assert beta.split(",") == ["computer-use-x", "context-management-2025-06-27"]


def _tool_req(model: str = "claude-sonnet-4-6") -> AdapterCallRequest:
    from core.llm.adapters.base import ToolSpec

    return AdapterCallRequest(
        model=model,
        system_prompt="s",
        messages=(Message(role="user", content="hi"),),
        max_tokens=64,
        tools=(ToolSpec(name="my_tool", description="d", input_schema={"type": "object"}),),
    )


def test_native_web_tools_off_by_default() -> None:
    """Provider-side web tools bypass ToolExecutor, so they stay opt-in and
    adapter allowlist-gated (Codex review 2026-07-29)."""
    names = [t.get("name") for t in build_create_kwargs(_tool_req())["tools"]]
    assert "web_search" not in names and "web_fetch" not in names


def test_native_web_tools_injected_when_opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "anthropic_native_web_tools", True, raising=False)
    names = [t.get("name") for t in build_create_kwargs(_tool_req())["tools"]]
    assert "web_search" in names and "web_fetch" in names
    assert names.count("web_search") == 1, "dedup by name"

    # A tool-free completion stays tool-free even when opted in.
    bare = build_create_kwargs(_req("s"))
    assert not any(
        x.get("name") in {"web_search", "web_fetch"} for x in bare.get("tools", []) or []
    )


def test_native_web_tools_respect_explicit_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings
    from core.llm.adapters.base import ToolSpec

    monkeypatch.setattr(settings, "anthropic_native_web_tools", True, raising=False)
    req = AdapterCallRequest(
        model="claude-sonnet-4-6",
        system_prompt="s",
        messages=(Message(role="user", content="hi"),),
        max_tokens=64,
        tools=(ToolSpec(name="my_tool", description="d", input_schema={"type": "object"}),),
        allowed_tool_names=frozenset({"my_tool", "web_fetch"}),
    )
    names = [t.get("name") for t in build_create_kwargs(req)["tools"]]
    assert "web_fetch" in names
    assert "web_search" not in names


def test_native_web_tools_skipped_on_unsupported_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """``web_*_20260209`` 400s on models outside the documented set — the
    budget-lane haiku must never receive it."""
    from core.config import settings

    monkeypatch.setattr(settings, "anthropic_native_web_tools", True, raising=False)
    names = [t.get("name") for t in build_create_kwargs(_tool_req("claude-haiku-4-5"))["tools"]]
    assert "web_search" not in names


def test_dated_model_alias_resolves_capabilities() -> None:
    """A dated snapshot id must resolve to the family's capability gates."""
    from core.llm.adapters._anthropic_common import _base_model

    assert _base_model("claude-sonnet-4-5-20250929") == "claude-sonnet-4-5"
    assert _base_model("claude-sonnet-4-6") == "claude-sonnet-4-6"
    kwargs = build_create_kwargs(
        AdapterCallRequest(
            model="claude-sonnet-4-5-20250929",
            system_prompt="s",
            messages=(Message(role="user", content="hi"),),
            max_tokens=64,
        )
    )
    assert "context_management" in (kwargs.get("extra_body") or {})


def test_merge_beta_dedups_existing_and_strips_space() -> None:
    from core.llm.adapters._anthropic_common import _merge_beta

    kwargs = {"extra_headers": {"anthropic-beta": "first, second,first"}}
    _merge_beta(kwargs, "second", "third")
    assert kwargs["extra_headers"]["anthropic-beta"] == "first,second,third"
