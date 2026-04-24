"""Tests for Codex provider (core/llm/providers/codex.py)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from core.config import CODEX_BASE_URL, CODEX_FALLBACK_CHAIN, CODEX_PRIMARY


class TestCodexConfig:
    def test_codex_primary(self):
        assert CODEX_PRIMARY == "gpt-5.4-mini"

    def test_codex_base_url(self):
        assert "chatgpt.com/backend-api" in CODEX_BASE_URL

    def test_codex_fallback_chain(self):
        assert CODEX_PRIMARY in CODEX_FALLBACK_CHAIN
        assert len(CODEX_FALLBACK_CHAIN) >= 2

    def test_resolve_provider_codex_models(self):
        from core.config import _resolve_provider

        assert _resolve_provider("gpt-5.3-codex") == "codex"
        assert _resolve_provider("gpt-5.2-codex") == "codex"
        assert _resolve_provider("gpt-5.1-codex-max") == "codex"
        assert _resolve_provider("gpt-5.1-codex-mini") == "codex"

    def test_resolve_provider_non_codex(self):
        from core.config import _resolve_provider

        assert _resolve_provider("gpt-5.4") == "openai"
        assert _resolve_provider("gpt-5.4-mini") == "openai"  # detected by gpt- prefix


class TestCodexPricing:
    def test_codex_models_have_pricing(self):
        from core.llm.token_tracker import MODEL_PRICING

        for model in ["gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.1-codex-max"]:
            price = MODEL_PRICING.get(model)
            assert price is not None, f"{model} missing from MODEL_PRICING"
            assert price.input > 0, f"{model} should have non-zero pricing"
            assert price.output > 0

    def test_codex_context_windows(self):
        from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

        for model in ["gpt-5.3-codex", "gpt-5.2-codex"]:
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


class TestCodexAdapterProperties:
    def test_provider_name(self):
        from core.llm.providers.codex import CodexAgenticAdapter

        adapter = CodexAgenticAdapter()
        assert adapter.provider_name == "codex"

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
    def test_text_output(self):
        from core.llm.providers.codex import _normalize_responses_api

        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "Hello!"
        mock_block = MagicMock()
        mock_block.content = [mock_content]
        mock_block.type = "message"
        mock_response.output = [mock_block]
        mock_response.model = "gpt-5.4-mini"
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5

        result = _normalize_responses_api(mock_response)
        assert result["content"] == "Hello!"
        assert result["role"] == "assistant"
        assert result["stop_reason"] == "end_turn"
        assert result["usage"]["input_tokens"] == 10

    def test_tool_call_output(self):
        from core.llm.providers.codex import _normalize_responses_api

        mock_response = MagicMock()
        mock_tool_block = MagicMock()
        mock_tool_block.type = "function_call"
        mock_tool_block.name = "web_search"
        mock_tool_block.arguments = '{"query": "test"}'
        mock_tool_block.call_id = "call_123"
        mock_tool_block.content = []
        mock_response.output = [mock_tool_block]
        mock_response.model = "gpt-5.4-mini"
        mock_response.usage.input_tokens = 15
        mock_response.usage.output_tokens = 8

        result = _normalize_responses_api(mock_response)
        assert result["stop_reason"] == "tool_use"
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["function"]["name"] == "web_search"


class TestAdapterMap:
    def test_codex_in_adapter_map(self):
        from core.llm.adapters import _ADAPTER_MAP

        assert "codex" in _ADAPTER_MAP
        assert "CodexAgenticAdapter" in _ADAPTER_MAP["codex"]

    def test_codex_cross_provider_fallback(self):
        from core.llm.adapters import CROSS_PROVIDER_FALLBACK

        assert "codex" in CROSS_PROVIDER_FALLBACK
        providers = [p for p, _ in CROSS_PROVIDER_FALLBACK["codex"]]
        assert "openai" in providers


class TestModelSelector:
    def test_codex_in_model_profiles(self):
        from core.cli.commands import MODEL_PROFILES

        codex_profiles = [p for p in MODEL_PROFILES if "Codex" in p.provider]
        assert len(codex_profiles) >= 2
        assert any("Codex" in p.provider for p in codex_profiles)
