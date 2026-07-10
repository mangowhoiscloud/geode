"""Versioned assay-adapter registry."""

from __future__ import annotations

from .base import AssayAdapter
from .tau2 import TAU2_ADAPTER, normalize_tau2_results

_ADAPTERS: dict[str, AssayAdapter] = {TAU2_ADAPTER.schema: TAU2_ADAPTER}


def get_assay_adapter(schema: str) -> AssayAdapter:
    try:
        return _ADAPTERS[schema]
    except KeyError as exc:
        raise ValueError(f"unsupported Crucible assay schema: {schema}") from exc


__all__ = ["AssayAdapter", "get_assay_adapter", "normalize_tau2_results"]
