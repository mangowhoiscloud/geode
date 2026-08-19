"""Compatibility exports for neutral seed-pool metadata validation."""

from __future__ import annotations

from core.self_improving.seed_pool_metadata import (
    seed_target_dims as _seed_target_dims,
)
from core.self_improving.seed_pool_metadata import validate_pool_target_dims

__all__ = ["_seed_target_dims", "validate_pool_target_dims"]
