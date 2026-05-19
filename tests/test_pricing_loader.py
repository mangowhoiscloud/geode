"""Unit tests for core.llm.pricing_loader (P3-A)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from core.llm.pricing_loader import (
    DEFAULT_PRICING_PATH,
    ModelPrice,
    PricingCatalogue,
    clear_pricing_cache,
    load_pricing_catalogue,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    clear_pricing_cache()
    yield
    clear_pricing_cache()


# ── Default file presence + shape ──────────────────────────────────────────


def test_default_file_exists() -> None:
    assert DEFAULT_PRICING_PATH.exists()
    assert DEFAULT_PRICING_PATH.suffix == ".toml"


def test_load_default_catalogue() -> None:
    cat = load_pricing_catalogue()
    assert isinstance(cat, PricingCatalogue)
    assert isinstance(cat.pricing, dict)
    assert isinstance(cat.context_windows, dict)


# ── Parity with legacy MODEL_PRICING ───────────────────────────────────────


def test_parity_with_legacy_pricing() -> None:
    """Loader output must match the legacy ``MODEL_PRICING`` dict P3-B replaces."""
    from core.llm.token_tracker import MODEL_PRICING

    legacy = MODEL_PRICING
    cat = load_pricing_catalogue()
    assert set(cat.pricing) == set(legacy), (
        f"Model id sets differ — loader extras: "
        f"{set(cat.pricing) - set(legacy)}, missing: "
        f"{set(legacy) - set(cat.pricing)}"
    )
    for model, legacy_price in legacy.items():
        loaded = cat.pricing[model]
        assert loaded.input == pytest.approx(legacy_price.input), f"{model}.input"
        assert loaded.output == pytest.approx(legacy_price.output), f"{model}.output"
        assert loaded.cache_write == pytest.approx(legacy_price.cache_write), f"{model}.cache_write"
        assert loaded.cache_read == pytest.approx(legacy_price.cache_read), f"{model}.cache_read"
        assert loaded.thinking == pytest.approx(legacy_price.thinking), f"{model}.thinking"


# ── Parity with legacy MODEL_CONTEXT_WINDOW ────────────────────────────────


def test_parity_with_legacy_context_windows() -> None:
    from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

    legacy = MODEL_CONTEXT_WINDOW
    cat = load_pricing_catalogue()
    assert set(cat.context_windows) == set(legacy), (
        f"Context window id sets differ — loader extras: "
        f"{set(cat.context_windows) - set(legacy)}, missing: "
        f"{set(legacy) - set(cat.context_windows)}"
    )
    for model, legacy_ctx in legacy.items():
        assert cat.context_windows[model] == legacy_ctx, f"{model} context window"


# ── Anthropic derive formula ───────────────────────────────────────────────


def test_anthropic_derive_formula(tmp_path: Path) -> None:
    """Anthropic provider: cache_write = input × 1.25, cache_read = input × 0.1,
    thinking = output."""
    toml = tmp_path / "p.toml"
    toml.write_text(
        """
[pricing.anthropic."m"]
input_per_mtok = 4.0
output_per_mtok = 20.0

[context_windows]
"m" = 100
""",
        encoding="utf-8",
    )
    cat = load_pricing_catalogue(toml)
    p = cat.pricing["m"]
    assert p.input == pytest.approx(4.0 / 1_000_000)
    assert p.output == pytest.approx(20.0 / 1_000_000)
    assert p.cache_write == pytest.approx(4.0 / 1_000_000 * 1.25)
    assert p.cache_read == pytest.approx(4.0 / 1_000_000 * 0.1)
    assert p.thinking == pytest.approx(20.0 / 1_000_000)


# ── OpenAI derive formula ──────────────────────────────────────────────────


def test_openai_derive_with_cached(tmp_path: Path) -> None:
    toml = tmp_path / "p.toml"
    toml.write_text(
        """
[pricing.openai."m"]
input_per_mtok = 5.0
output_per_mtok = 30.0
cached_per_mtok = 0.5

[context_windows]
"m" = 100
""",
        encoding="utf-8",
    )
    cat = load_pricing_catalogue(toml)
    p = cat.pricing["m"]
    assert p.cache_read == pytest.approx(0.5 / 1_000_000)
    assert p.thinking == 0.0  # not reasoning


def test_openai_derive_reasoning(tmp_path: Path) -> None:
    """reasoning = true → thinking = output."""
    toml = tmp_path / "p.toml"
    toml.write_text(
        """
[pricing.openai."m"]
input_per_mtok = 2.0
output_per_mtok = 8.0
reasoning = true

[context_windows]
"m" = 100
""",
        encoding="utf-8",
    )
    cat = load_pricing_catalogue(toml)
    p = cat.pricing["m"]
    assert p.thinking == pytest.approx(8.0 / 1_000_000)
    assert p.cache_read == 0.0


def test_openai_derive_no_cached(tmp_path: Path) -> None:
    toml = tmp_path / "p.toml"
    toml.write_text(
        """
[pricing.openai."m"]
input_per_mtok = 1.4
output_per_mtok = 4.4

[context_windows]
"m" = 100
""",
        encoding="utf-8",
    )
    cat = load_pricing_catalogue(toml)
    p = cat.pricing["m"]
    assert p.cache_read == 0.0
    assert p.thinking == 0.0


# ── Negative validation ────────────────────────────────────────────────────


def test_unknown_provider_raises(tmp_path: Path) -> None:
    toml = tmp_path / "p.toml"
    toml.write_text(
        """
[pricing.mystery."m"]
input_per_mtok = 1.0
output_per_mtok = 2.0

[context_windows]
"m" = 100
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown provider"):
        load_pricing_catalogue(toml)


def test_missing_required_field_raises(tmp_path: Path) -> None:
    toml = tmp_path / "p.toml"
    toml.write_text(
        """
[pricing.anthropic."m"]
output_per_mtok = 20.0

[context_windows]
"m" = 100
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing or non-numeric"):
        load_pricing_catalogue(toml)


def test_non_int_context_window_raises(tmp_path: Path) -> None:
    toml = tmp_path / "p.toml"
    toml.write_text(
        """
[pricing.anthropic."m"]
input_per_mtok = 1.0
output_per_mtok = 2.0

[context_windows]
"m" = "not-an-int"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not an integer"):
        load_pricing_catalogue(toml)


# ── Cache behaviour ────────────────────────────────────────────────────────


def test_load_caches_by_path(tmp_path: Path) -> None:
    a = load_pricing_catalogue()
    b = load_pricing_catalogue()
    assert a is b


def test_clear_cache_forces_reload() -> None:
    a = load_pricing_catalogue()
    clear_pricing_cache()
    b = load_pricing_catalogue()
    assert a is not b


# ── ModelPrice dataclass ───────────────────────────────────────────────────


def test_model_price_defaults() -> None:
    p = ModelPrice(input=1.0, output=2.0)
    assert p.cache_write == 0.0
    assert p.cache_read == 0.0
    assert p.thinking == 0.0
