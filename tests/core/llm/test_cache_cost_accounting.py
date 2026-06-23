"""Cached-token cost accounting — provider-semantic double-count fix.

``calculate_cost`` adds ``cache_read_tokens * cache_read`` on top of
``input_tokens * input``. That is correct for Anthropic, whose API reports
``input_tokens`` DISJOINT from ``cache_read_input_tokens``. But OpenAI / GLM
report ``prompt_tokens`` INCLUSIVE of cached tokens, so the same formula
billed cached tokens twice (full input rate + cache-read rate). The
``ModelPrice.cache_inclusive_input`` flag (set by the openai derive) makes the
cost path subtract cached from the billable input for those providers only.
"""

from __future__ import annotations

from core.llm.pricing_loader import ModelPrice
from core.llm.token_tracker import TokenTracker


def _tracker(price: ModelPrice) -> TokenTracker:
    return TokenTracker(pricing={"m": price})


class TestInclusiveProviderNoDoubleCount:
    """OpenAI / GLM: input_tokens INCLUDES cached → bill uncached remainder at
    input rate, cached at cache_read rate (no overlap)."""

    def test_cached_billed_once_at_cache_read_rate(self):
        # input 1.0/tok, cache_read 0.1/tok, inclusive. 1000 prompt incl 800 cached.
        price = ModelPrice(input=1.0, output=2.0, cache_read=0.1, cache_inclusive_input=True)
        cost = _tracker(price).calculate_cost("m", 1000, 0, cache_read_tokens=800)
        # uncached 200 * 1.0 + cached 800 * 0.1 = 200 + 80 = 280
        assert cost == 280.0

    def test_pre_fix_would_have_overcharged(self):
        # Documents the bug: the old formula = 1000*1.0 + 800*0.1 = 1080 (cached
        # double-charged). The fix yields 280 — a 3.86x reduction here.
        price = ModelPrice(input=1.0, output=2.0, cache_read=0.1, cache_inclusive_input=True)
        cost = _tracker(price).calculate_cost("m", 1000, 0, cache_read_tokens=800)
        assert cost < 1080.0

    def test_all_cached(self):
        price = ModelPrice(input=1.0, output=2.0, cache_read=0.1, cache_inclusive_input=True)
        cost = _tracker(price).calculate_cost("m", 500, 0, cache_read_tokens=500)
        assert cost == 50.0  # 0 uncached * 1.0 + 500 * 0.1

    def test_no_cache_unchanged(self):
        price = ModelPrice(input=1.0, output=2.0, cache_read=0.1, cache_inclusive_input=True)
        cost = _tracker(price).calculate_cost("m", 1000, 100)
        assert cost == 1000 * 1.0 + 100 * 2.0

    def test_no_configured_cache_rate_does_not_make_cached_free(self):
        # MED (Codex): an inclusive model with NO cached rate (cache_read=0,
        # e.g. o3 without cached_per_mtok) must NOT subtract cached from input
        # — else cached tokens get billed at 0 (free). Fall back to full input.
        price = ModelPrice(input=1.0, output=2.0, cache_read=0.0, cache_inclusive_input=True)
        cost = _tracker(price).calculate_cost("m", 1000, 0, cache_read_tokens=800)
        assert cost == 1000.0  # all 1000 at full input rate, none free


class TestDisjointProviderUnchanged:
    """Anthropic: input_tokens DISJOINT from cache → no subtraction (the cost
    must NOT regress from its pre-fix value)."""

    def test_anthropic_semantics_add_not_subtract(self):
        # input_tokens already excludes cache; bill both fully.
        price = ModelPrice(input=1.0, output=2.0, cache_read=0.1, cache_inclusive_input=False)
        cost = _tracker(price).calculate_cost("m", 200, 0, cache_read_tokens=800)
        # 200 * 1.0 + 800 * 0.1 = 280 (no subtraction)
        assert cost == 280.0


class TestPricingLoaderFlag:
    """The derive sets the flag: openai/glm True, anthropic False."""

    def test_openai_derive_inclusive(self):
        from core.llm.token_tracker import MODEL_PRICING

        assert MODEL_PRICING["glm-5.2"].cache_inclusive_input is True
        assert MODEL_PRICING["gpt-5.5"].cache_inclusive_input is True

    def test_anthropic_derive_disjoint(self):
        from core.llm.token_tracker import MODEL_PRICING

        assert MODEL_PRICING["claude-opus-4-8"].cache_inclusive_input is False


class TestGlmCachedSurfaced:
    """``translate_chat_response`` now populates cached_input_tokens from
    ``prompt_tokens_details.cached_tokens`` (was dropped → cached billed full)."""

    def test_translate_chat_response_reads_cached_tokens(self):
        from types import SimpleNamespace

        from core.llm.adapters._openai_common import translate_chat_response

        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="hi", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=1000,
                completion_tokens=20,
                prompt_tokens_details=SimpleNamespace(cached_tokens=700),
            ),
        )
        result = translate_chat_response(response)
        assert result.usage.input_tokens == 1000
        assert result.usage.cached_input_tokens == 700

    def test_translate_chat_response_no_cache_details(self):
        from types import SimpleNamespace

        from core.llm.adapters._openai_common import translate_chat_response

        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="hi", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10),
        )
        result = translate_chat_response(response)
        assert result.usage.cached_input_tokens == 0
