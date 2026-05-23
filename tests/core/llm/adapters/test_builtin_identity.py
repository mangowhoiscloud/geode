"""Identity invariants for each of the 6 built-in adapters.

These tests pin the (name, provider, source, billing_type) tuple for each
shipped adapter. They DO NOT exercise the actual SDK / subprocess call path —
that requires live credentials and is out of scope for the unit suite. The
acomplete path is covered by integration tests in the adapter migration
follow-up PRs.

The invariants here guard against accidental rename (e.g. ``claude-cli`` →
``anthropic-cli``) which would silently break operator overrides and the UI's
adapter list.
"""

from __future__ import annotations

import pytest
from core.llm.adapters.anthropic_oauth import AnthropicOAuthAdapter
from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter
from core.llm.adapters.base import AdapterBillingType
from core.llm.adapters.claude_cli import ClaudeCliAdapter
from core.llm.adapters.codex_cli import CodexCliAdapter
from core.llm.adapters.codex_oauth import CodexOAuthAdapter
from core.llm.adapters.openai_payg import OpenAIPaygAdapter


@pytest.mark.parametrize(
    ("cls", "expected_name", "expected_provider", "expected_source", "expected_billing"),
    [
        (AnthropicPaygAdapter, "anthropic-payg", "anthropic", "payg", AdapterBillingType.API),
        (
            AnthropicOAuthAdapter,
            "anthropic-oauth",
            "anthropic",
            "subscription",
            AdapterBillingType.SUBSCRIPTION,
        ),
        (
            ClaudeCliAdapter,
            "claude-cli",
            "anthropic",
            "adapter",
            AdapterBillingType.SUBSCRIPTION_INCLUDED,
        ),
        (OpenAIPaygAdapter, "openai-payg", "openai", "payg", AdapterBillingType.API),
        (
            CodexOAuthAdapter,
            "codex-oauth",
            "openai",
            "subscription",
            AdapterBillingType.SUBSCRIPTION,
        ),
        (
            CodexCliAdapter,
            "codex-cli",
            "openai",
            "adapter",
            AdapterBillingType.SUBSCRIPTION_INCLUDED,
        ),
    ],
)
def test_adapter_identity(
    cls: type,
    expected_name: str,
    expected_provider: str,
    expected_source: str,
    expected_billing: AdapterBillingType,
) -> None:
    instance = cls()
    assert instance.name == expected_name
    assert instance.provider == expected_provider
    assert instance.source == expected_source
    assert instance.billing_type is expected_billing


def test_test_environment_returns_report() -> None:
    """Every adapter's test_environment returns an EnvironmentReport (no raise).

    Adapters may report ok=False when credentials are missing — that's a valid
    outcome. We just confirm the surface doesn't raise on a fresh process.
    """
    for cls in (
        AnthropicPaygAdapter,
        AnthropicOAuthAdapter,
        ClaudeCliAdapter,
        OpenAIPaygAdapter,
        CodexOAuthAdapter,
        CodexCliAdapter,
    ):
        report = cls().test_environment()
        # Either ok=True with credentials available, or ok=False with hints.
        if not report.ok:
            assert report.hints, f"{cls.__name__}: ok=False but no hints"


def test_list_models_returns_specs() -> None:
    for cls in (
        AnthropicPaygAdapter,
        AnthropicOAuthAdapter,
        ClaudeCliAdapter,
        OpenAIPaygAdapter,
        CodexOAuthAdapter,
        CodexCliAdapter,
    ):
        models = cls().list_models()
        assert models, f"{cls.__name__}: list_models returned empty list"
        for m in models:
            assert m.id
            assert m.context_tokens > 0
