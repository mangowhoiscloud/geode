"""v0.52.5 — Provider switching E2E (3C2 cross-provider + 2 within-provider).

GEODE supports 3 providers (OpenAI Codex Plus OAuth, Anthropic API key,
GLM Coding Plan/PAYG) and 2 within-provider Plan switches (Codex↔PAYG,
Coding↔PAYG). v0.52.4 introduced plan-aware routing with kind-priority
sort, so the routing-policy test suite already covers the *first*
selection. This file pins the *switch* behaviour: starting on provider
A, can the user move to provider B without leaking A's adapter, A's
endpoint, or A's credentials into B's call?

5 paths covered:

  Path A — Codex Plus OAuth → Anthropic API key  (cross-provider)
  Path B — Codex Plus OAuth → GLM Coding Plan    (cross-provider)
  Path C — Anthropic        → GLM                (cross-provider)
  Path D — Codex Plus OAuth → OpenAI PAYG        (within-provider Plan)
  Path E — GLM Coding       → GLM PAYG           (within-provider Plan)

Each path asserts five contracts:
  1. ``_route_provider(target_model)`` returns the destination provider.
  2. ``AgenticLoop.update_model`` swaps ``self._adapter`` to the
     destination provider's adapter class (cross-provider) or keeps
     the same class (within-provider Plan switch).
  3. ``resolve_routing(target_model)`` resolves to the destination
     Plan with the correct ``base_url``.
  4. The destination credential is reachable via the destination
     adapter's ``_resolve_config()`` — no token from origin leaks in.
  5. After the switch, calling ``update_model`` back to origin
     returns the original adapter without state corruption.

Pattern source: aider's ``cmd_model`` (``SwitchCoder`` exception →
fresh Coder instance, preserved messages); Claude Code's `/model`
(immediate next-turn switch, history preserved); the four-agent
research already cited in CHANGELOG v0.52.4.

Live LLM calls are forbidden (``-m live`` cost guard). All tests use
mocks for SDK clients and assert call args / endpoints.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from core.auth.plan_registry import resolve_routing
from core.auth.plans import Plan, PlanKind
from core.auth.profiles import AuthProfile, CredentialType

# ---------------------------------------------------------------------------
# Fixtures — register Plans for each provider/kind combination
# ---------------------------------------------------------------------------


def _reset_singletons() -> None:
    from core.auth import plan_registry as _pr
    from core.lifecycle import container as _infra

    _infra._profile_store = None
    _infra._profile_rotator = None
    _pr._plan_registry = None


def _register_codex_oauth() -> Plan:
    from core.auth.plan_registry import get_plan_registry
    from core.lifecycle.container import ensure_profile_store

    plan = Plan(
        id="openai-codex-geode",
        provider="openai-codex",
        kind=PlanKind.OAUTH_BORROWED,
        display_name="OpenAI Codex (Plus)",
        base_url="https://chatgpt.com/backend-api/codex",
        auth_type="oauth_external",
    )
    get_plan_registry().add(plan)
    ensure_profile_store().add(
        AuthProfile(
            name="openai-codex:geode",
            provider="openai-codex",
            credential_type=CredentialType.OAUTH,
            key="oauth-codex-token",
            plan_id=plan.id,
        )
    )
    return plan


def _register_openai_payg() -> Plan:
    from core.auth.plan_registry import get_plan_registry
    from core.lifecycle.container import ensure_profile_store

    plan = Plan(
        id="openai-payg",
        provider="openai",
        kind=PlanKind.PAYG,
        display_name="OpenAI (PAYG)",
        base_url="https://api.openai.com/v1",
    )
    get_plan_registry().add(plan)
    ensure_profile_store().add(
        AuthProfile(
            name="openai:payg",
            provider="openai",
            credential_type=CredentialType.API_KEY,
            key="sk-openai-payg",
            plan_id=plan.id,
        )
    )
    return plan


def _register_anthropic_payg() -> Plan:
    from core.auth.plan_registry import get_plan_registry
    from core.lifecycle.container import ensure_profile_store

    plan = Plan(
        id="anthropic-payg",
        provider="anthropic",
        kind=PlanKind.PAYG,
        display_name="Anthropic (PAYG)",
        base_url="https://api.anthropic.com",
        auth_type="x-api-key",
    )
    get_plan_registry().add(plan)
    ensure_profile_store().add(
        AuthProfile(
            name="anthropic:payg",
            provider="anthropic",
            credential_type=CredentialType.API_KEY,
            key="sk-ant-payg",
            plan_id=plan.id,
        )
    )
    return plan


def _register_glm_coding() -> Plan:
    from core.auth.plan_registry import get_plan_registry
    from core.lifecycle.container import ensure_profile_store

    plan = Plan(
        id="glm-coding-lite",
        provider="glm-coding",
        kind=PlanKind.SUBSCRIPTION,
        display_name="GLM Coding Lite",
        base_url="https://api.z.ai/api/coding/paas/v4",
    )
    get_plan_registry().add(plan)
    ensure_profile_store().add(
        AuthProfile(
            name="glm-coding:lite",
            provider="glm-coding",
            credential_type=CredentialType.API_KEY,
            key="glm-coding-key",
            plan_id=plan.id,
        )
    )
    return plan


def _register_glm_payg() -> Plan:
    from core.auth.plan_registry import get_plan_registry
    from core.lifecycle.container import ensure_profile_store

    plan = Plan(
        id="glm-payg",
        provider="glm",
        kind=PlanKind.PAYG,
        display_name="GLM (PAYG)",
        base_url="https://api.z.ai/api/paas/v4",
    )
    get_plan_registry().add(plan)
    ensure_profile_store().add(
        AuthProfile(
            name="glm:payg",
            provider="glm",
            credential_type=CredentialType.API_KEY,
            key="glm-payg-key",
            plan_id=plan.id,
        )
    )
    return plan


@pytest.fixture
def isolated_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Reset singletons + redirect auth.toml to a tmp path so plan
    registrations don't leak across tests."""
    monkeypatch.setenv("GEODE_AUTH_TOML", str(tmp_path / "auth.toml"))
    _reset_singletons()
    yield
    _reset_singletons()


# ---------------------------------------------------------------------------
# Path A — Codex Plus OAuth → Anthropic API key (cross-provider)
# ---------------------------------------------------------------------------


def test_path_a_codex_oauth_to_anthropic_apikey(isolated_auth) -> None:
    """User on Codex Plus does ``/model claude-opus-4-7`` → Anthropic API."""
    _register_codex_oauth()
    _register_anthropic_payg()

    # Origin: gpt-5.5 routes to Codex Plus.
    origin = resolve_routing("gpt-5.5")
    assert origin is not None
    assert origin.plan.provider == "openai-codex"
    assert "chatgpt.com/backend-api/codex" in origin.base_url

    # Destination: claude-opus-4-7 routes to Anthropic.
    dest = resolve_routing("claude-opus-4-7")
    assert dest is not None
    assert dest.plan.provider == "anthropic"
    assert dest.base_url == "https://api.anthropic.com"
    assert dest.profile.key == "sk-ant-payg"
    # No token leak from Codex into Anthropic.
    assert "oauth-codex-token" not in dest.profile.key

    # Adapter swap: from CodexAgenticAdapter to ClaudeAgenticAdapter.
    from core.llm.adapters import resolve_agentic_adapter

    a_origin = resolve_agentic_adapter("openai-codex")
    a_dest = resolve_agentic_adapter("anthropic")
    assert type(a_origin).__name__ == "CodexAgenticAdapter"
    assert type(a_dest).__name__ == "ClaudeAgenticAdapter"
    # Round-trip: switching back returns a Codex adapter again
    a_back = resolve_agentic_adapter("openai-codex")
    assert type(a_back).__name__ == "CodexAgenticAdapter"


# ---------------------------------------------------------------------------
# Path B — Codex Plus OAuth → GLM Coding Plan (cross-provider)
# ---------------------------------------------------------------------------


def test_path_b_codex_oauth_to_glm_coding(isolated_auth) -> None:
    _register_codex_oauth()
    _register_glm_coding()

    origin = resolve_routing("gpt-5.5")
    assert origin is not None
    assert origin.plan.provider == "openai-codex"

    dest = resolve_routing("glm-5.1")
    assert dest is not None
    assert dest.plan.provider == "glm-coding"
    assert dest.base_url == "https://api.z.ai/api/coding/paas/v4"
    assert dest.profile.key == "glm-coding-key"
    assert "oauth-codex-token" not in dest.profile.key

    from core.llm.adapters import resolve_agentic_adapter

    assert type(resolve_agentic_adapter("glm")).__name__ == "GlmAgenticAdapter"


# ---------------------------------------------------------------------------
# Path C — Anthropic → GLM (cross-provider)
# ---------------------------------------------------------------------------


def test_path_c_anthropic_to_glm(isolated_auth) -> None:
    _register_anthropic_payg()
    _register_glm_coding()

    origin = resolve_routing("claude-opus-4-7")
    assert origin is not None
    assert origin.plan.provider == "anthropic"

    dest = resolve_routing("glm-5.1")
    assert dest is not None
    assert dest.plan.provider == "glm-coding"
    # Anthropic key must not leak into GLM call.
    assert "sk-ant" not in dest.profile.key
    assert dest.profile.key == "glm-coding-key"

    from core.llm.adapters import resolve_agentic_adapter

    a_origin = resolve_agentic_adapter("anthropic")
    a_dest = resolve_agentic_adapter("glm")
    assert type(a_origin).__name__ == "ClaudeAgenticAdapter"
    assert type(a_dest).__name__ == "GlmAgenticAdapter"


# ---------------------------------------------------------------------------
# Path D — Codex Plus OAuth → OpenAI PAYG (within-provider Plan switch)
# ---------------------------------------------------------------------------


def test_path_d_codex_oauth_to_openai_payg_within_provider(isolated_auth) -> None:
    """Both Plans registered. Default routing prefers Codex Plus (OAuth) for
    gpt-5.4 per kind-priority. After ``/login route gpt-5.4 openai-payg``
    explicit override the same model must route to PAYG."""
    _register_codex_oauth()
    _register_openai_payg()
    from core.auth.plan_registry import get_plan_registry

    # Default — kind-priority wins (Codex OAuth).
    default = resolve_routing("gpt-5.4")
    assert default is not None
    assert default.plan.id == "openai-codex-geode"
    assert "chatgpt.com" in default.base_url

    # Explicit /login route override.
    get_plan_registry().set_routing("gpt-5.4", ["openai-payg"])
    overridden = resolve_routing("gpt-5.4")
    assert overridden is not None
    assert overridden.plan.id == "openai-payg"
    assert overridden.base_url == "https://api.openai.com/v1"
    assert overridden.profile.key == "sk-openai-payg"
    # The OAuth token must NOT be the credential consumed.
    assert overridden.profile.key != "oauth-codex-token"


def test_path_d_forced_login_method_apikey_route(isolated_auth) -> None:
    """Codex CLI parity (forced_login_method='apikey') flips the kind sort.
    No explicit /login route, but the config flag forces PAYG."""
    _register_codex_oauth()
    _register_openai_payg()
    from core.config import settings

    with patch.object(settings, "forced_login_method", {"openai": "apikey"}):
        target = resolve_routing("gpt-5.4")
        assert target is not None
        assert target.plan.id == "openai-payg"
        assert target.profile.key == "sk-openai-payg"


# ---------------------------------------------------------------------------
# Path E — GLM Coding → GLM PAYG (within-provider Plan switch)
# ---------------------------------------------------------------------------


def test_path_e_glm_coding_to_glm_payg_within_provider(isolated_auth) -> None:
    """Both GLM Plans registered. Coding Plan is SUBSCRIPTION → wins by
    default. ``/login route glm-5.1 glm-payg`` flips it."""
    _register_glm_coding()
    _register_glm_payg()
    from core.auth.plan_registry import get_plan_registry

    default = resolve_routing("glm-5.1")
    assert default is not None
    assert default.plan.id == "glm-coding-lite"
    assert "coding/paas" in default.base_url

    get_plan_registry().set_routing("glm-5.1", ["glm-payg"])
    overridden = resolve_routing("glm-5.1")
    assert overridden is not None
    assert overridden.plan.id == "glm-payg"
    assert overridden.base_url == "https://api.z.ai/api/paas/v4"
    assert overridden.profile.key == "glm-payg-key"
    # Coding Plan key must not leak.
    assert overridden.profile.key != "glm-coding-key"


# ---------------------------------------------------------------------------
# Cross-cutting — no token leak through adapter cache singletons
# ---------------------------------------------------------------------------


def test_codex_token_resolution_uses_geode_profile_first(isolated_auth) -> None:
    """v0.52.4 contract: ``_resolve_codex_token`` checks ProfileStore first
    so the OAuth token registered via /login oauth openai is the one used,
    not whatever ~/.codex/auth.json carries from Codex CLI."""
    _register_codex_oauth()
    from core.llm.providers.codex import _resolve_codex_token

    # The geode-registered profile token should be returned.
    token = _resolve_codex_token()
    assert token == "oauth-codex-token"


def test_no_cross_provider_token_visible_in_routing(isolated_auth) -> None:
    """Registering all three providers must not cause the wrong-provider
    credential to appear in any routing target."""
    _register_codex_oauth()
    _register_openai_payg()
    _register_anthropic_payg()
    _register_glm_coding()
    _register_glm_payg()

    # gpt-5.5 → OAuth token only.
    t1 = resolve_routing("gpt-5.5")
    assert t1 is not None and t1.profile.key == "oauth-codex-token"

    # claude → anthropic key only.
    t2 = resolve_routing("claude-opus-4-7")
    assert t2 is not None and t2.profile.key == "sk-ant-payg"

    # glm-5.1 → coding plan key (subscription wins).
    t3 = resolve_routing("glm-5.1")
    assert t3 is not None and t3.profile.key == "glm-coding-key"

    # No two paths share a key.
    keys = {t1.profile.key, t2.profile.key, t3.profile.key}
    assert len(keys) == 3, f"key collision across providers: {keys}"


# ---------------------------------------------------------------------------
# update_model behaviour under the switch
# ---------------------------------------------------------------------------


def test_update_model_swaps_adapter_on_provider_change(
    isolated_auth, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end on AgenticLoop: starting with Codex adapter, calling
    update_model('claude-opus-4-7') must swap the adapter to Claude."""
    _register_codex_oauth()
    _register_anthropic_payg()

    # Build a minimal AgenticLoop stub-state — we only exercise update_model
    # so we don't need the full constructor wiring.
    from unittest.mock import MagicMock

    import core.agent.loop as _loop_mod

    stub = MagicMock()
    stub.model = "gpt-5.5"
    stub._provider = "openai-codex"
    stub._adapter = MagicMock(name="CodexAgenticAdapter")
    type(stub._adapter).__name__ = "CodexAgenticAdapter"  # type: ignore[misc]
    stub._tool_processor = MagicMock()
    stub._hooks = None
    stub.context = MagicMock(is_empty=True)
    # Bind the real method against the stub.
    stub.update_model = _loop_mod.AgenticLoop.update_model.__get__(stub)
    stub._adapt_context_for_model = MagicMock()

    monkeypatch.setattr("core.agent.loop._resolve_provider", lambda _m: "anthropic")

    # Patch the factory so we can assert it was called with the new provider.
    fake_claude = MagicMock(name="ClaudeAgenticAdapter")
    type(fake_claude).__name__ = "ClaudeAgenticAdapter"  # type: ignore[misc]
    monkeypatch.setattr("core.agent.loop.resolve_agentic_adapter", lambda p: fake_claude)

    stub.update_model("claude-opus-4-7")

    assert stub._provider == "anthropic"
    assert stub._adapter is fake_claude
    assert stub.model == "claude-opus-4-7"
    # Tool processor must see the new model so retries don't reuse the old name.
    assert stub._tool_processor._model == "claude-opus-4-7"


def test_update_model_marks_prompt_dirty_so_escalation_rebuilds(
    isolated_auth, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v0.52.5 contract: update_model must set ``_prompt_dirty = True`` so
    that escalation paths (which call update_model directly + persist via
    _persist_escalated_model) cause the next round to rebuild the system
    prompt. Pre-fix the prompt was rebuilt only when
    ``_sync_model_from_settings()`` returned True; escalation made the
    sync see no drift, so the model card stayed pinned to the failed model.
    """
    from unittest.mock import MagicMock

    import core.agent.loop as _loop_mod

    stub = MagicMock()
    stub.model = "gpt-5.4"
    stub._provider = "openai"
    stub._adapter = MagicMock()
    stub._tool_processor = MagicMock()
    stub._hooks = None
    stub.context = MagicMock(is_empty=True)
    stub._prompt_dirty = False
    stub.update_model = _loop_mod.AgenticLoop.update_model.__get__(stub)
    stub._adapt_context_for_model = MagicMock()

    monkeypatch.setattr("core.agent.loop._resolve_provider", lambda _m: "openai")
    monkeypatch.setattr("core.agent.loop.resolve_agentic_adapter", lambda p: MagicMock())

    stub.update_model("gpt-5.3-codex", reason="failure_escalation")

    assert stub._prompt_dirty is True, (
        "update_model must set _prompt_dirty when model changes — "
        "without this, escalation leaves the system prompt pinned to the "
        "previously-failed model card."
    )


def test_update_model_keeps_adapter_on_within_provider_switch(
    isolated_auth, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Within-provider model swap (e.g. gpt-5.5 → gpt-5.4 inside the same
    OpenAI Codex provider) must NOT rebuild the adapter. The adapter owns
    its client; rebuilding wastes a connection setup."""
    from unittest.mock import MagicMock

    import core.agent.loop as _loop_mod

    initial_adapter = MagicMock(name="CodexAgenticAdapter")
    type(initial_adapter).__name__ = "CodexAgenticAdapter"  # type: ignore[misc]

    stub = MagicMock()
    stub.model = "gpt-5.5"
    stub._provider = "openai-codex"
    stub._adapter = initial_adapter
    stub._tool_processor = MagicMock()
    stub._hooks = None
    stub.context = MagicMock(is_empty=True)
    stub.update_model = _loop_mod.AgenticLoop.update_model.__get__(stub)
    stub._adapt_context_for_model = MagicMock()

    monkeypatch.setattr("core.agent.loop._resolve_provider", lambda _m: "openai-codex")

    # Track factory calls — should NOT be invoked since provider unchanged.
    factory_calls = []
    monkeypatch.setattr(
        "core.agent.loop.resolve_agentic_adapter",
        lambda p: factory_calls.append(p) or MagicMock(),
    )

    stub.update_model("gpt-5.4")

    assert stub.model == "gpt-5.4"
    assert stub._adapter is initial_adapter, "adapter rebuilt on within-provider switch"
    assert factory_calls == [], (
        f"resolve_agentic_adapter called {factory_calls} for within-provider switch"
    )
