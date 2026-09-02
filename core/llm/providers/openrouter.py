"""OpenRouter model-identity helpers shared by the adapter and CLI."""

from __future__ import annotations


def to_openrouter_model_id(model: str) -> str:
    """Strip exactly one GEODE ``openrouter/`` namespace and validate the slug."""
    prefix = "openrouter/"
    if not model.startswith(prefix):
        raise ValueError("OpenRouter model must start with 'openrouter/'")
    upstream = model[len(prefix) :]
    publisher, separator, name = upstream.partition("/")
    if (
        not separator
        or upstream.count("/") != 1
        or not publisher
        or not name
        or any(char.isspace() for char in upstream)
    ):
        raise ValueError(
            "OpenRouter model must be 'openrouter/<publisher>/<model>' "
            "(for router-owned models use openrouter/openrouter/<model>)"
        )
    return upstream


__all__ = ["to_openrouter_model_id"]
