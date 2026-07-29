"""Credential changes must drop the clients that actually serve traffic.

2026-07-29 incident class: ``/key`` and ``/login`` reset the ``providers/``
SYNC singletons, a surface the live path stopped using long before they were
deleted — so a rotated key kept flowing through a stale ADAPTER client until
restart. These pins assert the wiring at both ends: the invalidation function
really empties adapter caches, and every credential-changing CLI path calls it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from core.llm.adapters.registry import (
    bootstrap_builtins,
    invalidate_provider_clients,
)

_REPO = Path(__file__).resolve().parents[3]


def _fill_caches() -> list[object]:
    """Seed every adapter's loop-affine client cache with a sentinel."""
    from core.llm.adapters.registry import _REGISTRY

    bootstrap_builtins()
    seeded = []
    for adapter in _REGISTRY.values():
        cache = getattr(adapter, "_clients", None)
        if cache is not None and hasattr(cache, "get"):
            cache.get(lambda: object())
            seeded.append(adapter)
    return seeded


def test_invalidate_empties_adapter_caches() -> None:
    seeded = _fill_caches()
    assert seeded, "no adapter exposes a client cache — wiring assumption broken"
    dropped = invalidate_provider_clients()
    assert dropped >= len(seeded)


def test_invalidate_scoped_to_one_provider() -> None:
    _fill_caches()
    from core.llm.adapters.registry import _REGISTRY, normalize_registry_provider

    expected = sum(
        1
        for a in _REGISTRY.values()
        if a.provider == normalize_registry_provider("anthropic")
        and getattr(a, "_clients", None) is not None
    )
    assert invalidate_provider_clients("anthropic") == expected


@pytest.mark.parametrize(
    "rel_path",
    ["core/cli/commands/key.py", "core/cli/commands/login.py", "core/llm/fallback.py"],
)
def test_credential_paths_invalidate_adapter_clients(rel_path: str) -> None:
    """Every credential-changing module must reach the adapter invalidation.

    A module that only resets a ``providers/`` singleton is the exact defect
    this guards — those singletons no longer exist, so the check is that the
    live entry point is referenced at all.
    """
    src = (_REPO / rel_path).read_text(encoding="utf-8")
    assert "invalidate_provider_clients" in src, (
        f"{rel_path} changes credentials without dropping adapter clients"
    )


def test_key_command_invalidates_for_every_provider_branch() -> None:
    """``/key`` handles anthropic / openai / glm — each branch must invalidate."""
    src = (_REPO / "core/cli/commands/key.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    invalidated = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_invalidate"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    assert {"anthropic", "openai", "glm"} <= invalidated, (
        f"/key branches missing adapter invalidation: {invalidated}"
    )
