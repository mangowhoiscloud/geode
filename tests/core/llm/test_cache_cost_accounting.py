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

from pathlib import Path
from types import SimpleNamespace

import pytest
from core.llm.pricing_loader import ModelPrice
from core.llm.token_tracker import TokenTracker


def _tracker(price: ModelPrice) -> TokenTracker:
    return TokenTracker(pricing={"m": price})


@pytest.mark.parametrize("category", ["cached", "cache_write"])
def test_explicit_free_cache_differs_from_missing_price(tmp_path: Path, category: str) -> None:
    from core.llm.pricing_loader import load_pricing_catalogue

    tariff = tmp_path / "prices.toml"
    tariff.write_text(
        '[pricing.openai."m"]\ninput_per_mtok = 2\noutput_per_mtok = 10\n'
        f"{category}_per_mtok = 0\n",
        encoding="utf-8",
    )
    tracker = _tracker(load_pricing_catalogue(tariff).pricing["m"])
    counters = (
        {"cache_read_tokens": 1_000_000}
        if category == "cached"
        else {"cache_creation_tokens": 1_000_000}
    )
    assert tracker.calculate_cost("m", 1_000_000, 0, **counters) == 0
    unknown = _tracker(ModelPrice(input=2e-6, output=10e-6, cache_inclusive_input=True))
    assert unknown.calculate_cost("m", 1_000_000, 0, **counters) == 2


@pytest.mark.parametrize("input_tokens,multiplier", [(272_000, 1.0), (272_001, 2.0)])
def test_long_context_tier_uses_full_inclusive_prompt(input_tokens: int, multiplier: float) -> None:
    from core.llm.pricing_loader import load_pricing_catalogue

    price = load_pricing_catalogue().pricing["gpt-6-sol"]
    tracker = _tracker(price)
    actual = tracker.calculate_cost(
        "m", input_tokens, 1000, cache_read_tokens=200_000, cache_creation_tokens=50_000
    )
    output_multiplier = 1.5 if multiplier == 2 else 1.0
    expected = (
        ((input_tokens - 250_000) * 2 + 200_000 * 0.2 + 50_000 * 2.5) * multiplier
        + 1000 * 10 * output_multiplier
    ) / 1_000_000
    assert actual == pytest.approx(expected)
    assert price.input == pytest.approx(2e-6), "Tier selection must not mutate shared prices"


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

    @pytest.mark.parametrize(
        ("read_rate", "write_rate", "expected"),
        [(0.1, 1.25, 505.0), (0.0, 1.25, 1045.0), (0.1, 0.0, 480.0), (0.0, 0.0, 1020.0)],
    )
    def test_cache_reads_and_writes_billed_once_with_known_rate_fallback(
        self, read_rate: float, write_rate: float, expected: float
    ) -> None:
        price = ModelPrice(
            input=1.0,
            output=2.0,
            cache_read=read_rate,
            cache_write=write_rate,
            cache_inclusive_input=True,
        )
        cost = _tracker(price).calculate_cost(
            "m", 1000, 10, cache_read_tokens=600, cache_creation_tokens=100
        )
        # The 1,000 input tokens include 600 reads, 100 writes and 300 ordinary
        # tokens. A missing cache rate leaves that category at the input rate.
        assert cost == pytest.approx(expected)

    def test_all_cache_writes_billed_once_at_write_rate(self) -> None:
        price = ModelPrice(input=1.0, output=2.0, cache_write=1.25, cache_inclusive_input=True)
        cost = _tracker(price).calculate_cost("m", 1000, 0, cache_creation_tokens=1000)
        assert cost == 1250.0


class TestDisjointProviderUnchanged:
    """Anthropic: input_tokens DISJOINT from cache → no subtraction (the cost
    must NOT regress from its pre-fix value)."""

    def test_anthropic_semantics_add_not_subtract(self):
        # input_tokens already excludes cache; bill both fully.
        price = ModelPrice(input=1.0, output=2.0, cache_read=0.1, cache_inclusive_input=False)
        cost = _tracker(price).calculate_cost("m", 200, 0, cache_read_tokens=800)
        # 200 * 1.0 + 800 * 0.1 = 280 (no subtraction)
        assert cost == 280.0

    def test_anthropic_reads_and_writes_remain_disjoint(self) -> None:
        price = ModelPrice(input=1.0, output=2.0, cache_read=0.1, cache_write=1.25)
        cost = _tracker(price).calculate_cost(
            "m", 300, 10, cache_read_tokens=600, cache_creation_tokens=100
        )
        assert cost == 505.0


def test_reasoning_breakdown_is_observed_without_double_billing() -> None:
    tracker = _tracker(ModelPrice(input=1.0, output=2.0))

    usage = tracker.record("m", 0, 100, thinking_tokens=80)

    assert usage.thinking_tokens == 80
    assert usage.cost_usd == 200.0


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
                prompt_tokens_details=SimpleNamespace(cached_tokens=700, cache_write_tokens=30),
                completion_tokens_details=SimpleNamespace(reasoning_tokens=4),
            ),
        )
        result = translate_chat_response(response)
        assert result.usage.input_tokens == 1000
        assert result.usage.cached_input_tokens == 700
        assert result.usage.cache_write_tokens == 30
        assert result.usage.reasoning_tokens == 4

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


def test_anthropic_usage_carries_cache_write_and_thinking_tokens() -> None:
    from types import SimpleNamespace

    from core.llm.adapters._anthropic_common import translate_response

    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")],
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=20,
            cache_read_input_tokens=60,
            cache_creation_input_tokens=15,
            output_tokens_details=SimpleNamespace(thinking_tokens=3),
        ),
    )
    result = translate_response(response)
    assert result.usage.cached_input_tokens == 60
    assert result.usage.cache_write_tokens == 15
    assert result.usage.reasoning_tokens == 3


@pytest.mark.parametrize("provider", ["chat", "codex", "anthropic"])
@pytest.mark.parametrize("cache_values", [None, (None, None), (0, 0), (7, 3), (None, 0), (0, None)])
def test_provider_cache_presence_preserves_missing_and_zero(
    provider: str, cache_values: tuple[int | None, int | None] | None
) -> None:
    from core.llm.adapters._anthropic_common import translate_response
    from core.llm.adapters._openai_common import translate_chat_response, translate_codex_response

    cache_fields = ("cached_tokens", "cache_write_tokens")
    if provider == "anthropic":
        cache_fields = ("cache_read_input_tokens", "cache_creation_input_tokens")
    detail = SimpleNamespace(
        **dict(zip(cache_fields, cache_values, strict=True)) if cache_values is not None else {}
    )
    usage = SimpleNamespace(input_tokens=100, output_tokens=20)
    response = SimpleNamespace(content=[], choices=[], output=[], usage=usage)
    if provider == "chat":
        usage.prompt_tokens = 100
        usage.completion_tokens = 20
        usage.prompt_tokens_details = detail
        result = translate_chat_response(response)
    elif provider == "codex":
        usage.input_tokens_details = detail
        result = translate_codex_response(response)
    else:
        vars(usage).update(vars(detail))
        result = translate_response(response)

    read, write = cache_values if cache_values is not None else (None, None)
    assert result.usage.cached_input_tokens == (read or 0)
    assert result.usage.cache_write_tokens == (write or 0)
    assert result.usage.cached_input_tokens_present is (read is not None)
    assert result.usage.cache_write_tokens_present is (write is not None)
    assert (result.usage.input_tokens, result.usage.output_tokens) == (100, 20)


@pytest.mark.parametrize("provider", ["chat", "codex", "anthropic"])
@pytest.mark.parametrize(
    "counts", [None, (None, None, None), (0, 0, 0), (100, 20, 3), (100, None, 0)]
)
def test_provider_counter_presence_preserves_missing_and_zero(
    provider: str, counts: tuple[int | None, int | None, int | None] | None
) -> None:
    from core.llm.adapters._anthropic_common import translate_response
    from core.llm.adapters._openai_common import translate_chat_response, translate_codex_response

    input_key, output_key = (
        ("prompt_tokens", "completion_tokens")
        if provider == "chat"
        else ("input_tokens", "output_tokens")
    )
    reasoning_key = "thinking_tokens" if provider == "anthropic" else "reasoning_tokens"
    detail_key = "completion_tokens_details" if provider == "chat" else "output_tokens_details"
    usage = None
    if counts is not None:
        usage = SimpleNamespace(
            **{
                input_key: counts[0],
                output_key: counts[1],
                detail_key: SimpleNamespace(**{reasoning_key: counts[2]}),
            }
        )
    response = SimpleNamespace(content=[], choices=[], output=[], usage=usage)
    translator = {
        "chat": translate_chat_response,
        "codex": translate_codex_response,
        "anthropic": translate_response,
    }[provider]
    result = translator(response)
    for key, value in zip(
        ("input_tokens", "output_tokens", "reasoning_tokens"),
        counts if counts is not None else (None, None, None),
        strict=True,
    ):
        assert getattr(result.usage, key) == (value or 0)
        assert getattr(result.usage, f"{key}_present") is (value is not None)
