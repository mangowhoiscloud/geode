"""Tests for Codex provider (core/llm/providers/codex.py)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from core.config import CODEX_BASE_URL, CODEX_FALLBACK_CHAIN, CODEX_PRIMARY


class TestCodexConfig:
    def test_codex_primary(self):
        # v0.52.4 — Codex's new default per developers.openai.com/codex/models
        # (gpt-5.5 is OAuth-only, can't even be called with API-key auth).
        assert CODEX_PRIMARY == "gpt-5.5"

    def test_codex_base_url(self):
        assert "chatgpt.com/backend-api" in CODEX_BASE_URL

    def test_codex_fallback_chain_default_empty(self):
        """v0.99.19 — silent same-provider fallback removed. Shipped
        default for the chain is an empty list (opt-in knob). The
        constant must still be a list so user-tuned chains from
        ``~/.geode/routing.toml`` propagate as before."""
        assert isinstance(CODEX_FALLBACK_CHAIN, list)
        assert CODEX_FALLBACK_CHAIN == [], (
            "Shipped default for CODEX_FALLBACK_CHAIN must be empty. "
            "Users opt in via ~/.geode/routing.toml [model.fallbacks]."
        )

    def test_resolve_provider_codex_models(self):
        from core.config import _resolve_provider

        # v0.50.0: Codex OAuth is a distinct provider variant ("openai-codex")
        # so its credentials never leak into general OpenAI calls.
        assert _resolve_provider("gpt-5.3-codex") == "openai-codex"
        assert _resolve_provider("gpt-5.2-codex") == "openai-codex"
        assert _resolve_provider("gpt-5.1-codex-max") == "openai-codex"
        assert _resolve_provider("gpt-5.1-codex-mini") == "openai-codex"

    def test_resolve_provider_non_codex(self):
        from core.config import _resolve_provider

        assert _resolve_provider("gpt-5.4") == "openai"
        assert _resolve_provider("gpt-5.4-mini") == "openai"  # detected by gpt- prefix


class TestCodexPricing:
    def test_codex_models_have_pricing(self):
        from core.llm.token_tracker import MODEL_PRICING

        # v0.52.4 — refreshed against developers.openai.com/codex/models 2026-04-26.
        # gpt-5.5 added (Codex's new default, OAuth-only). gpt-5.2-codex,
        # gpt-5.1-codex-max/mini removed (no longer in current Codex models page).
        for model in ["gpt-5.5", "gpt-5.4-mini", "gpt-5.3-codex"]:
            price = MODEL_PRICING.get(model)
            assert price is not None, f"{model} missing from MODEL_PRICING"
            assert price.input > 0, f"{model} should have non-zero pricing"
            assert price.output > 0

    def test_codex_context_windows(self):
        from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

        for model in ["gpt-5.5", "gpt-5.4-mini", "gpt-5.3-codex"]:
            ctx = MODEL_CONTEXT_WINDOW.get(model)
            assert ctx is not None, f"{model} missing from MODEL_CONTEXT_WINDOW"
            assert ctx >= 200_000


class TestAccountIdExtraction:
    def test_extract_valid_jwt(self):
        # Build a minimal JWT with the expected claim
        import base64

        from core.llm.providers.codex import _extract_account_id

        header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
        payload_data = {
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "test-account-123",
            }
        }
        payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
        token = f"{header}.{payload}.signature"

        assert _extract_account_id(token) == "test-account-123"

    def test_extract_missing_claim(self):
        import base64

        from core.llm.providers.codex import _extract_account_id

        header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(b'{"sub":"user"}').rstrip(b"=").decode()
        token = f"{header}.{payload}.sig"

        assert _extract_account_id(token) == ""

    def test_extract_invalid_token(self):
        from core.llm.providers.codex import _extract_account_id

        assert _extract_account_id("not-a-jwt") == ""
        assert _extract_account_id("") == ""


class TestCodexOAuthHeaders:
    """``build_codex_oauth_headers`` is the single SoT for the
    ``originator`` + ``ChatGPT-Account-ID`` pair that the Codex backend
    requires. Four call sites (``_get_codex_client``,
    ``_get_async_codex_client``, ``build_async_codex_client`` adapter
    builder, ``OpenAICodexAPI`` inspect_ai subclass) all go through it."""

    def _build_token(self, account_id: str | None) -> str:
        import base64

        header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
        payload_data: dict = {}
        if account_id is not None:
            payload_data["https://api.openai.com/auth"] = {
                "chatgpt_account_id": account_id,
            }
        payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
        return f"{header}.{payload}.signature"

    def test_header_includes_account_id_when_jwt_carries_claim(self):
        from core.llm.providers.codex import build_codex_oauth_headers

        token = self._build_token("acct-77")
        headers = build_codex_oauth_headers(token)

        assert headers == {
            "originator": "codex_cli_rs",
            "ChatGPT-Account-ID": "acct-77",
        }

    def test_header_omits_account_id_when_jwt_lacks_claim(self):
        from core.llm.providers.codex import build_codex_oauth_headers

        token = self._build_token(None)
        headers = build_codex_oauth_headers(token)

        assert headers == {"originator": "codex_cli_rs"}
        assert "ChatGPT-Account-ID" not in headers

    def test_header_safe_on_malformed_token(self):
        """``_extract_account_id`` swallows ``ValueError`` /
        ``json.JSONDecodeError`` / ``UnicodeDecodeError`` from bad base64
        decoding and returns ``""`` — so the helper must still ship a
        valid ``originator``-only dict rather than crashing."""
        from core.llm.providers.codex import build_codex_oauth_headers

        # Early-return: token has fewer than 2 dotted parts.
        assert build_codex_oauth_headers("not-a-jwt") == {"originator": "codex_cli_rs"}
        assert build_codex_oauth_headers("") == {"originator": "codex_cli_rs"}
        # Dotted but the middle segment is not valid base64 — exercises the
        # ``except (json.JSONDecodeError, ValueError, UnicodeDecodeError)``
        # branch of ``_extract_account_id``.
        assert build_codex_oauth_headers("h.%%%.s") == {"originator": "codex_cli_rs"}
        # Dotted but the middle segment decodes to non-JSON bytes.
        assert build_codex_oauth_headers("h.bm9wZQ.s") == {"originator": "codex_cli_rs"}

    def test_returns_fresh_dict_per_call(self):
        """Caller may mutate the returned dict — the helper must not hand
        out a cached reference shared across threads."""
        from core.llm.providers.codex import build_codex_oauth_headers

        token = self._build_token("acct-77")
        first = build_codex_oauth_headers(token)
        first["X-Test-Mutation"] = "y"
        second = build_codex_oauth_headers(token)

        assert "X-Test-Mutation" not in second


class TestCodexAdapterProperties:
    def test_provider_name(self):
        from core.llm.providers.codex import CodexAgenticAdapter

        adapter = CodexAgenticAdapter()
        assert adapter.provider_name == "openai-codex"

    def test_fallback_chain(self):
        from core.llm.providers.codex import CodexAgenticAdapter

        adapter = CodexAgenticAdapter()
        assert adapter.fallback_chain == list(CODEX_FALLBACK_CHAIN)

    def test_resolve_config(self):
        from core.llm.providers.codex import CodexAgenticAdapter

        adapter = CodexAgenticAdapter()
        _key, base_url = adapter._resolve_config("gpt-5.4-mini")
        assert base_url == CODEX_BASE_URL


class TestNormalizeResponsesApi:
    """v0.53.1 — Codex adapter now uses the SHARED normalize_openai_responses
    (returns AgenticResponse dataclass) instead of a local dict-returning
    helper. Pre-fix the dict path crashed AgenticLoop._track_usage with
    `'dict' object has no attribute 'usage'` (production incident
    2026-04-27, immediately after v0.53.0). See test_codex_normalize_parity
    for the full invariant cohort."""

    def test_text_output(self):
        from core.llm.agentic_response import AgenticResponse, normalize_openai_responses

        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.type = "output_text"
        mock_content.text = "Hello!"
        mock_block = MagicMock()
        mock_block.content = [mock_content]
        mock_block.type = "message"
        mock_response.output = [mock_block]
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5

        result = normalize_openai_responses(mock_response)
        assert isinstance(result, AgenticResponse)
        assert result.stop_reason == "end_turn"
        assert result.usage.input_tokens == 10
        assert any(b.type == "text" and b.text == "Hello!" for b in result.content)

    def test_tool_call_output(self):
        from core.llm.agentic_response import AgenticResponse, normalize_openai_responses

        mock_response = MagicMock()
        mock_tool_block = MagicMock()
        mock_tool_block.type = "function_call"
        mock_tool_block.name = "web_search"
        mock_tool_block.arguments = '{"query": "test"}'
        mock_tool_block.call_id = "call_123"
        mock_response.output = [mock_tool_block]
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 15
        mock_response.usage.output_tokens = 8

        result = normalize_openai_responses(mock_response)
        assert isinstance(result, AgenticResponse)
        assert result.stop_reason == "tool_use"
        tool_blocks = [b for b in result.content if b.type == "tool_use"]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].name == "web_search"
        assert tool_blocks[0].input == {"query": "test"}


class TestAdapterRegistry:
    def test_codex_oauth_in_path_b_registry(self):
        """PR-MAINPATH-67 (2026-05-24) — the legacy ``_ADAPTER_MAP``
        was deleted; Codex routing now lives in the Path-B registry
        under ``(provider="openai", source="subscription")``."""
        from core.llm.adapters.registry import (
            _reset_for_test,
            bootstrap_builtins,
            list_adapters,
        )

        _reset_for_test()
        bootstrap_builtins()
        entries = {(a.provider, a.source): a for a in list_adapters()}
        assert ("openai", "subscription") in entries
        codex = entries[("openai", "subscription")]
        assert codex.__class__.__name__ == "CodexOAuthAdapter"

    def test_no_cross_provider_fallback_shim(self):
        """v0.99.19 — the empty-dict ``CROSS_PROVIDER_FALLBACK`` shim is
        deleted. The v0.50.0 invariant ("openai-codex must not silently
        jump to another provider") is preserved by absence of the chain
        code itself, not by an empty-dict sentinel."""
        from core.llm import adapters as _adapters_mod

        assert not hasattr(_adapters_mod, "CROSS_PROVIDER_FALLBACK"), (
            "CROSS_PROVIDER_FALLBACK resurfaced — cross-provider silent "
            "fallback elimination requires the symbol to stay deleted."
        )


class TestModelSelector:
    def test_codex_in_model_profiles(self):
        from core.cli.commands import MODEL_PROFILES

        # v0.53.0 — provider labels are CANONICAL provider IDs ("openai-codex"),
        # NOT marketing names ("Codex (Plus)"). Pre-fix label/ID mismatch
        # confused users about which auth-mode would be consumed.
        codex_profiles = [p for p in MODEL_PROFILES if p.provider == "openai-codex"]
        assert len(codex_profiles) >= 1, (
            "at least one model must be tagged with the canonical provider "
            "ID 'openai-codex' so the picker matches the /login dashboard"
        )
        assert any(p.id.endswith("-codex") for p in codex_profiles)
