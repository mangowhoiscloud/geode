"""Loader for ``core/llm/model_pricing.toml`` — pricing + context windows.

P3-A (2026-05-17) introduces this loader. P3-B migrates
:mod:`core.llm.token_tracker`'s ``MODEL_PRICING`` and
``MODEL_CONTEXT_WINDOW`` dicts to consume it. Until then the loader is
dormant — no production call site reads from this module.

Schema (matches the TOML, provider-prefixed):

- ``[pricing.anthropic.<model>]`` — ``input_per_mtok`` + ``output_per_mtok``.
  Loader applies the Anthropic derive: ``cache_write = input × 1.25``,
  ``cache_read = input × 0.1``, ``thinking = output``.
- ``[pricing.openai.<model>]`` — same two keys plus optional
  ``cached_per_mtok`` and ``reasoning`` (bool). Loader applies:
  ``cache_read = cached_per_mtok`` (explicit), ``thinking = output if
  reasoning else 0.0``. GLM models live under ``[pricing.openai.*]``
  by manifest convention (OpenAI-compatible API, openai derive formula).
- ``[context_windows]`` — model id → int (tokens).

Output: a single :class:`PricingCatalogue` dataclass with both maps
already in the ``ModelPrice`` form that ``token_tracker`` consumes.

Refresh cadence: quarterly per the upstream pricing pages. Tests verify
the loader's parity with the legacy hardcoded dicts so a stale file is
caught immediately during P3-B's migration.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
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
    consumer (`token_tracker.ModelPrice`, `plugins.petri_audit.runner`,
    tests that monkeypatch the pricing dict) keeps working unchanged.
    """

    input: float
    output: float
    cache_write: float = 0.0
    cache_read: float = 0.0
    thinking: float = 0.0


def _derive_anthropic(input_mtok: float, output_mtok: float) -> ModelPrice:
    """Anthropic derive: cache_write = input × 1.25, cache_read = input × 0.1,
    thinking = output (Extended Thinking billed as output)."""
    inp = input_mtok / 1_000_000
    out = output_mtok / 1_000_000
    return ModelPrice(
        input=inp,
        output=out,
        cache_write=inp * 1.25,
        cache_read=inp * 0.1,
        thinking=out,
    )


def _derive_openai(
    input_mtok: float,
    output_mtok: float,
    cached_mtok: float = 0.0,
    reasoning: bool = False,
) -> ModelPrice:
    """OpenAI derive: explicit cache_read price, thinking = output for
    reasoning models (o3 / o4-mini billed at output rate for reasoning
    tokens)."""
    out = output_mtok / 1_000_000
    return ModelPrice(
        input=input_mtok / 1_000_000,
        output=out,
        cache_read=cached_mtok / 1_000_000 if cached_mtok else 0.0,
        thinking=out if reasoning else 0.0,
    )


@dataclass(frozen=True)
class PricingCatalogue:
    """Parsed view of ``model_pricing.toml`` — pricing + context windows."""

    pricing: dict[str, ModelPrice]
    context_windows: dict[str, int]


def _parse_provider(provider: str, entries: dict[str, Any]) -> dict[str, ModelPrice]:
    """Build a {model: ModelPrice} dict for a single provider section."""
    out: dict[str, ModelPrice] = {}
    for model, fields in entries.items():
        if not isinstance(fields, dict):
            continue
        try:
            input_mtok = float(fields["input_per_mtok"])
            output_mtok = float(fields["output_per_mtok"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"[pricing.{provider}.{model!r}]: missing or non-numeric "
                f"input_per_mtok / output_per_mtok"
            ) from exc
        if provider == "anthropic":
            out[model] = _derive_anthropic(input_mtok, output_mtok)
        elif provider == "openai":
            out[model] = _derive_openai(
                input_mtok,
                output_mtok,
                cached_mtok=float(fields.get("cached_per_mtok", 0.0)),
                reasoning=bool(fields.get("reasoning", False)),
            )
        else:
            raise ValueError(
                f"[pricing.{provider}.{model!r}]: unknown provider — supported "
                f"providers are 'anthropic' and 'openai' (GLM models route "
                f"through 'openai' by manifest convention)"
            )
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
            continue
        pricing.update(_parse_provider(provider, entries))

    context_raw = data.get("context_windows", {})
    if not isinstance(context_raw, dict):
        raise ValueError(f"{path}: [context_windows] is not a table")
    context_windows: dict[str, int] = {}
    for model, value in context_raw.items():
        try:
            context_windows[model] = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"[context_windows] {model!r}: not an integer ({value!r})") from exc

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
