"""Assembled-prompt dump guards (PR-PROMPT-DUMP, prompt-refactor P0).

Content-independent pins: machine state (memory files, user profile)
varies, so these assert STRUCTURE — placeholder collapse, suffix
presence, single cache boundary, ordering — not bytes.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from core.agent.prompt_dump import (
    DUMP_SURFACES,
    SKILL_EMPTY_MARKER,
    analyze_prompt,
    assemble_full_prompt,
    dump_matrix,
    measure_tokens_anthropic,
)
from core.llm.prompts import AGENTIC_SUFFIX


def test_assembled_prompt_matches_loop_composition_contract() -> None:
    prompt = assemble_full_prompt("claude-opus-4-8", "cli")
    assert "{skill_context}" not in prompt, "placeholder must collapse to the empty marker"
    assert SKILL_EMPTY_MARKER in prompt
    assert prompt.count(AGENTIC_SUFFIX) == 1, "suffix exactly once (no loop double-append)"
    assert prompt.count("<dynamic_context>") == 1, "exactly one cache boundary"
    assert prompt.count("</dynamic_context>") == 1, "B1: the envelope must CLOSE"
    boundary_at = prompt.index("<dynamic_context>")
    # PR-PROMPT-P2A zone rule — authored static (markdown, incl. the
    # agentic suffix) precedes the boundary; injected XML follows it.
    assert prompt.index("## Math formatting") < boundary_at
    assert prompt.index(AGENTIC_SUFFIX) < boundary_at, "suffix is cache-stable static"
    assert prompt.index("<current_date>") > boundary_at
    assert prompt.rstrip().endswith("</dynamic_context>")


def test_assembled_prompt_binds_configured_profile_when_missing(monkeypatch) -> None:
    profile = MagicMock()
    profile.get_context_summary.return_value = "User: Project Operator"
    profile.get_career_summary.return_value = "ML Engineer"
    monkeypatch.setattr("core.memory.user_profile.FileBasedUserProfile", lambda **_kwargs: profile)
    prompt = assemble_full_prompt("claude-opus-4-8", "cli")

    assert "User: Project Operator" in prompt
    assert "Career: ML Engineer" in prompt


def test_surface_pin_reaches_platform_hint() -> None:
    cli_prompt = assemble_full_prompt("claude-opus-4-8", "cli")
    slack_prompt = assemble_full_prompt("claude-opus-4-8", "slack")
    assert "surface='cli'" in cli_prompt
    assert "surface='slack'" in slack_prompt


def test_dump_preserves_literal_context_data(monkeypatch) -> None:
    from core.agent import system_prompt

    monkeypatch.setenv("GEODE_AUDIT_UNRESTRICTED", "0")
    monkeypatch.setattr(system_prompt, "_generic_static_prefix", lambda: "Skills: {skill_context}")
    monkeypatch.setattr(
        system_prompt, "_build_user_context", lambda _profile: "User literal: {skill_context}"
    )

    prompt = assemble_full_prompt("claude-opus-4-8", "cli")

    assert f"Skills: {SKILL_EMPTY_MARKER}" in prompt
    assert "User literal: {skill_context}" in prompt


def test_surface_env_is_restored() -> None:
    import os

    sentinel = os.environ.get("GEODE_SURFACE_TYPE")
    assemble_full_prompt("claude-opus-4-8", "worktree")
    assert os.environ.get("GEODE_SURFACE_TYPE") == sentinel


def test_analyze_prompt_flags_duplicate_sections() -> None:
    tags, duplicates = analyze_prompt("<alpha>\nx\n</alpha>\n<beta>\n<alpha>\ny\n</alpha>")
    assert tags == ("alpha", "beta", "alpha")
    assert duplicates == ("alpha",)


def test_dump_matrix_writes_cells(tmp_path) -> None:
    dump_dir = tmp_path / "cells"
    rows = dump_matrix(("claude-opus-4-8",), ("cli",), out_dir=dump_dir, measure=False)
    assert len(rows) == 1
    cell = rows[0]
    assert cell.path.is_file()
    assert cell.chars == len(cell.path.read_text(encoding="utf-8"))
    assert cell.est_tokens == cell.chars // 4, "without --measure the figure is the estimate"
    assert cell.surface in DUMP_SURFACES


@pytest.mark.parametrize("custom_endpoint", [False, True])
@pytest.mark.parametrize("status", [200, 503])
def test_measure_uses_file_key_and_matching_endpoint_then_closes_client(
    tmp_path, monkeypatch, custom_endpoint: bool, status: int
) -> None:
    import json

    import anthropic
    import httpx
    from core.auth.auth_toml import auth_file_transaction, save_api_key
    from core.auth.profiles import ProfileStore
    from core.config import ANTHROPIC_PRIMARY, settings
    from core.llm.strategies import plan_registry
    from core.wiring import container

    monkeypatch.setenv("GEODE_AUTH_TOML", str(tmp_path / "auth.toml"))
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setattr(container, "_profile_store", ProfileStore())
    monkeypatch.setattr(plan_registry, "_plan_registry", plan_registry.PlanRegistry())
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "anthropic_credential_source", "auto")
    monkeypatch.setattr(settings, "forced_login_method", {})
    plan = save_api_key("synthetic-file-key", provider="anthropic")
    endpoint = "https://api.anthropic.com"
    if custom_endpoint:
        endpoint = "https://anthropic.example.invalid"
        with auth_file_transaction() as (plans, _profiles):
            plans.get(plan.id).base_url = endpoint
            plans.set_routing(ANTHROPIC_PRIMARY, [plan.id])
    requests = []
    clients = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert str(request.url) == f"{endpoint}/v1/messages/count_tokens"
        assert request.headers["x-api-key"] == "synthetic-file-key"
        assert json.loads(request.content)["system"] == "Measured prompt"
        return httpx.Response(status, json={"input_tokens": 123})

    original = anthropic.Anthropic

    def build(**kwargs):
        client = original(
            http_client=httpx.Client(transport=httpx.MockTransport(transport)), **kwargs
        )
        clients.append(client)
        return client

    monkeypatch.setattr(anthropic, "Anthropic", build)
    assert measure_tokens_anthropic("Measured prompt") == (123 if status == 200 else None)
    assert len(requests) == 1
    assert len(clients) == 1 and clients[0].is_closed()
    assert settings.anthropic_api_key == ""
    monkeypatch.setattr(settings, "anthropic_credential_source", "none")
    assert measure_tokens_anthropic("Disabled route") is None
    assert len(requests) == 1
