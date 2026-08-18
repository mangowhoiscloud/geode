"""Compatibility facade for the neutral JSON policy loader."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.config.policy_source import PolicySourcePaths, load_policy_source


def load_policy_sot(
    *,
    env_var: str,
    operator_local: Path,
    in_repo: Path,
    label: str,
    validate_strict: Callable[[Any, Path], None],
    validate_graceful: Callable[[Any, Path], None],
    coerce: Callable[[Any], Any],
) -> Any | None:
    """Preserve the historical call shape while delegating selection."""
    return load_policy_source(
        sources=PolicySourcePaths(env_var, operator_local, in_repo),
        label=label,
        validate_strict=validate_strict,
        validate_graceful=validate_graceful,
        coerce=coerce,
    )


__all__ = ["load_policy_sot"]
