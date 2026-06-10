"""Tests for model-first provider inference (Feature 7).

Feature 7: Make _resolve_provider handle more model prefixes.
  - gpt-* → openai
  - o3-*/o4-* → openai
  - gemini-* → google
  - deepseek-* → deepseek
  - llama-* → meta
  - qwen-*/qwen3* → alibaba
  - claude-* → anthropic
  - glm-* → glm
  - unknown → openai (fallback)
"""

from __future__ import annotations

from core.config import _resolve_provider


class TestResolveProvider:
    """Test _resolve_provider prefix-based inference."""

    # Anthropic
    def test_claude_primary(self) -> None:
        assert _resolve_provider("claude-opus-4-6") == "anthropic"

    def test_claude_sonnet(self) -> None:
        assert _resolve_provider("claude-sonnet-4-6") == "anthropic"

    def test_claude_haiku(self) -> None:
        assert _resolve_provider("claude-haiku-4-5-20251001") == "anthropic"

    # GLM
    def test_glm_primary(self) -> None:
        assert _resolve_provider("glm-5") == "glm"

    def test_glm_turbo(self) -> None:
        assert _resolve_provider("glm-5-turbo") == "glm"

    def test_glm_flash(self) -> None:
        assert _resolve_provider("glm-4.7-flash") == "glm"

    # OpenAI — gpt-*
    def test_gpt_5_4(self) -> None:
        assert _resolve_provider("gpt-5.4") == "openai"

    def test_gpt_5_2(self) -> None:
        assert _resolve_provider("gpt-5.2") == "openai"

    def test_gpt_4_1(self) -> None:
        assert _resolve_provider("gpt-4.1") == "openai"

    def test_gpt_4_1_mini(self) -> None:
        assert _resolve_provider("gpt-4.1-mini") == "openai"

    # OpenAI — o3-*/o4-*
    def test_o3_mini(self) -> None:
        assert _resolve_provider("o3-mini") == "openai"

    def test_o4_mini(self) -> None:
        assert _resolve_provider("o4-mini") == "openai"

    def test_o3_pro(self) -> None:
        assert _resolve_provider("o3-pro") == "openai"

    # Google — gemini-*
    def test_gemini_pro(self) -> None:
        assert _resolve_provider("gemini-pro") == "google"

    def test_gemini_2_5_flash(self) -> None:
        assert _resolve_provider("gemini-2.5-flash") == "google"

    def test_gemini_ultra(self) -> None:
        assert _resolve_provider("gemini-ultra") == "google"

    # DeepSeek — deepseek-*
    def test_deepseek_v3(self) -> None:
        assert _resolve_provider("deepseek-v3") == "deepseek"

    def test_deepseek_coder(self) -> None:
        assert _resolve_provider("deepseek-coder") == "deepseek"

    def test_deepseek_r1(self) -> None:
        assert _resolve_provider("deepseek-r1") == "deepseek"

    # Meta — llama-*
    def test_llama_3_1(self) -> None:
        assert _resolve_provider("llama-3.1") == "meta"

    def test_llama_guard(self) -> None:
        assert _resolve_provider("llama-guard-3") == "meta"

    # Alibaba — qwen-*/qwen3*
    def test_qwen_72b(self) -> None:
        assert _resolve_provider("qwen-72b") == "alibaba"

    def test_qwen3_235b(self) -> None:
        assert _resolve_provider("qwen3-235b-a22b") == "alibaba"

    def test_qwen_turbo(self) -> None:
        assert _resolve_provider("qwen-turbo") == "alibaba"

    # Fallback — unknown models default to openai
    def test_unknown_model_fallback(self) -> None:
        assert _resolve_provider("some-random-model") == "openai"

    def test_empty_string_fallback(self) -> None:
        assert _resolve_provider("") == "openai"

    def test_mistral_fallback(self) -> None:
        """Mistral is not explicitly mapped — falls back to openai."""
        assert _resolve_provider("mistral-large") == "openai"

    # Backward compatibility
    def test_existing_openai_models_still_work(self) -> None:
        """Pre-existing gpt models still resolve correctly."""
        assert _resolve_provider("gpt-5.4") == "openai"
        assert _resolve_provider("gpt-4.1-mini") == "openai"

    def test_existing_anthropic_models_still_work(self) -> None:
        """Pre-existing claude models still resolve correctly."""
        assert _resolve_provider("claude-opus-4-6") == "anthropic"

    def test_existing_glm_models_still_work(self) -> None:
        """Pre-existing glm models still resolve correctly."""
        assert _resolve_provider("glm-5") == "glm"
