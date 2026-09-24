"""Validated provider tariffs and context limits consumed by the runtime.

The TOML is the only price-data owner. Provider sections identify accounting
semantics, independent of their wire protocol: Anthropic input is disjoint
from cache; OpenAI and GLM report inclusive prompt totals. Explicit cache
rates override defaults, including zero. TypeSafe has no cache tariff.
Provider-reported cost takes precedence over these standard API estimates.
"""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_PRICING_PATH",
    "ModelPrice",
    "PricingCatalogue",
    "clear_pricing_cache",
    "load_pricing_catalogue",
]

DEFAULT_PRICING_PATH = Path(__file__).parent / "model_pricing.toml"


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """Per-token pricing for a single model.

    P3-B (2026-05-17): canonical definition lives here.
    ``core.llm.token_tracker`` re-exports the class so every existing
    consumer (`token_tracker.ModelPrice`, `evals.petri.runner`,
    tests that monkeypatch the pricing dict) keeps working unchanged.
    """

    input: float
    output: float
    cache_write: float = 0.0
    cache_read: float = 0.0
    # Whether the provider's reported ``input_tokens`` INCLUDES the cached
    # tokens (OpenAI / GLM: ``prompt_tokens`` is the total, ``cached_tokens`` a
    # subset) or is DISJOINT from them (Anthropic: ``input_tokens`` is the
    # uncached remainder, ``cache_read_input_tokens`` separate). The cost math
    # must subtract cached from input ONLY for the inclusive case, else cached
    # tokens are billed at both the full input rate and the cache-read rate.
    cache_inclusive_input: bool = False
    cache_read_known: bool = False
    cache_write_known: bool = False
    long_context_threshold: int | None = None
    long_context_input_multiplier: float = 1.0
    long_context_output_multiplier: float = 1.0
    cache_write_1h: float | None = None

    def for_input_tokens(self, input_tokens: int) -> ModelPrice:
        """Apply the published full-request tier above its strict threshold."""
        if self.long_context_threshold is None or input_tokens <= self.long_context_threshold:
            return self
        return replace(
            self,
            input=self.input * self.long_context_input_multiplier,
            output=self.output * self.long_context_output_multiplier,
            cache_read=self.cache_read * self.long_context_input_multiplier,
            cache_write=self.cache_write * self.long_context_input_multiplier,
            cache_write_1h=(
                self.cache_write_1h * self.long_context_input_multiplier
                if self.cache_write_1h is not None
                else None
            ),
            long_context_threshold=None,
        )


def _derive_anthropic(
    input_mtok: float,
    output_mtok: float,
    cached_mtok: float | None = None,
    cache_write_mtok: float | None = None,
) -> ModelPrice:
    """Anthropic derive: cache_write = input × 1.25, cache_read = input × 0.1."""
    inp = input_mtok / 1_000_000
    out = output_mtok / 1_000_000
    return ModelPrice(
        input=inp,
        output=out,
        cache_write=inp * 1.25 if cache_write_mtok is None else cache_write_mtok / 1_000_000,
        cache_read=inp * 0.1 if cached_mtok is None else cached_mtok / 1_000_000,
        cache_read_known=True,
        cache_write_known=True,
        cache_write_1h=inp * 2,
    )


def _derive_openai(
    input_mtok: float,
    output_mtok: float,
    cached_mtok: float = 0.0,
    cache_write_mtok: float = 0.0,
) -> ModelPrice:
    """OpenAI derive: explicit cache-read and optional cache-write prices."""
    out = output_mtok / 1_000_000
    return ModelPrice(
        input=input_mtok / 1_000_000,
        output=out,
        cache_write=cache_write_mtok / 1_000_000 if cache_write_mtok else 0.0,
        cache_read=cached_mtok / 1_000_000 if cached_mtok else 0.0,
        # OpenAI / GLM report ``prompt_tokens`` inclusive of cached tokens.
        cache_inclusive_input=True,
    )


@dataclass(frozen=True)
class PricingCatalogue:
    """Parsed view of ``model_pricing.toml`` — pricing + context windows."""

    pricing: dict[str, ModelPrice]
    context_windows: dict[str, int]


def _rate(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field}: expected a finite non-negative number")
    try:
        rate = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}: missing or non-numeric rate") from exc
    if not math.isfinite(rate) or rate < 0:
        raise ValueError(f"{field}: expected a finite non-negative number")
    return rate


def _parse_provider(provider: str, entries: dict[str, Any]) -> dict[str, ModelPrice]:
    """Build prices without conflating provider identity with wire format."""
    if provider not in {"anthropic", "openai", "glm", "typesafe"}:
        raise ValueError(
            f"unknown provider {provider!r}; expected anthropic, openai, glm or typesafe"
        )
    out: dict[str, ModelPrice] = {}
    for model, fields in entries.items():
        prefix = f"pricing.{provider}.{model}"
        if not isinstance(fields, dict):
            raise ValueError(f"{prefix}: expected a table")
        try:
            inp = _rate(fields["input_per_mtok"], field=f"{prefix}.input_per_mtok")
            output = _rate(fields["output_per_mtok"], field=f"{prefix}.output_per_mtok")
        except KeyError as exc:
            raise ValueError(f"{prefix}: missing or non-numeric required rate") from exc
        cached = (
            _rate(fields["cached_per_mtok"], field=f"{prefix}.cached_per_mtok")
            if "cached_per_mtok" in fields
            else None
        )
        write = (
            _rate(fields["cache_write_per_mtok"], field=f"{prefix}.cache_write_per_mtok")
            if "cache_write_per_mtok" in fields
            else None
        )
        if provider == "typesafe":
            price = ModelPrice(input=inp / 1_000_000, output=output / 1_000_000)
        elif provider == "anthropic":
            price = _derive_anthropic(inp, output, cached, write)
        else:
            price = _derive_openai(inp, output, cached or 0.0, write or 0.0)
        if provider != "anthropic":
            price = replace(
                price, cache_read_known=cached is not None, cache_write_known=write is not None
            )
        threshold = fields.get("long_context_threshold")
        if threshold is not None:
            if type(threshold) is not int or threshold <= 0:
                raise ValueError(f"{prefix}.long_context_threshold: expected positive integer")
            price = replace(
                price,
                long_context_threshold=threshold,
                long_context_input_multiplier=_rate(
                    fields.get("long_context_input_multiplier", 1.0),
                    field=f"{prefix}.input_multiplier",
                ),
                long_context_output_multiplier=_rate(
                    fields.get("long_context_output_multiplier", 1.0),
                    field=f"{prefix}.output_multiplier",
                ),
            )
        out[model] = price
    return out


@lru_cache(maxsize=4)
def _load_cached(path_str: str) -> PricingCatalogue:
    path = Path(path_str)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    pricing_section = data.get("pricing", {})
    if not isinstance(pricing_section, dict):
        raise ValueError(f"{path}: [pricing] is not a table")

    pricing: dict[str, ModelPrice] = {}
    for provider, entries in pricing_section.items():
        if not isinstance(entries, dict):
            raise ValueError(f"pricing.{provider}: expected a table")
        parsed = _parse_provider(provider, entries)
        duplicates = pricing.keys() & parsed.keys()
        if duplicates:
            raise ValueError(f"Duplicate model prices across providers: {sorted(duplicates)}")
        pricing.update(parsed)

    context_raw = data.get("context_windows", {})
    if not isinstance(context_raw, dict):
        raise ValueError(f"{path}: [context_windows] is not a table")
    context_windows: dict[str, int] = {}
    for model, value in context_raw.items():
        if type(value) is not int or value <= 0:
            raise ValueError(f"[context_windows] {model!r}: not an integer above zero ({value!r})")
        context_windows[model] = value

    aliases = data.get("aliases", {})
    if not isinstance(aliases, dict):
        raise ValueError(f"{path}: [aliases] is not a table")
    for alias, target in aliases.items():
        if alias in pricing or alias in context_windows:
            raise ValueError(f"Alias {alias!r} duplicates a model row")
        if not isinstance(target, str) or target not in pricing or target not in context_windows:
            raise ValueError(f"Alias {alias!r} has unknown target {target!r}")
        pricing[alias] = pricing[target]
        context_windows[alias] = context_windows[target]

    return PricingCatalogue(pricing=pricing, context_windows=context_windows)


def load_pricing_catalogue(path: Path | str | None = None) -> PricingCatalogue:
    """Load and validate the model pricing catalogue.

    Defaults to :data:`DEFAULT_PRICING_PATH`. Result cached per absolute
    path so repeat calls share the parsed catalogue. Tests that fixture
    custom TOML files call :func:`clear_pricing_cache` first.
    """
    target = Path(path) if path is not None else DEFAULT_PRICING_PATH
    return _load_cached(str(target.resolve()))


def clear_pricing_cache() -> None:
    """Drop the lru_cache — used by tests."""
    _load_cached.cache_clear()
