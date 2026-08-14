"""Compatibility facade for the neutral policy-source selector.

New production code imports :mod:`core.config.policy_source`. This module
keeps the historical names and call signature available while delegating to
the single canonical implementation.
"""

from __future__ import annotations

from pathlib import Path

from core.config.policy_source import (
    PolicySourcePaths,
    PolicySourceSelection,
    select_policy_source,
)

SoTSelection = PolicySourceSelection


def resolve_sot(
    *,
    env_var: str,
    operator_local: Path,
    in_repo: Path,
) -> SoTSelection | None:
    """Delegate the historical three-keyword API to the neutral selector."""
    return select_policy_source(
        PolicySourcePaths(
            override_env=env_var,
            operator_local=operator_local,
            packaged_default=in_repo,
        )
    )


__all__ = ["SoTSelection", "resolve_sot"]
