"""Cross-module symbol liveness for the low-level provider layer.

2026-07-29 incident: a legacy-prune pass deleted
``providers.anthropic._async_response_hook`` as an apparent orphan. It is in
fact consumed by ``adapters._anthropic_common.build_async_anthropic_client``
through a **lazy in-function import**, which neither ruff nor mypy resolves —
every Anthropic subscription call would have died with ImportError at runtime,
and no unit test touched the path. These pins exercise the real builders.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_ADAPTERS = _REPO / "core" / "llm" / "adapters"


def test_anthropic_async_client_builder_constructs() -> None:
    """The live async client builder must import + run end to end."""
    from core.llm.adapters._anthropic_common import build_async_anthropic_client

    client = build_async_anthropic_client("sk-ant-api-test")
    assert type(client).__name__ == "AsyncAnthropic"


def test_lazy_provider_imports_in_adapters_all_resolve() -> None:
    """Every ``from core.llm.providers.X import Y`` inside adapters — including
    the in-function (lazy) ones — must resolve. This is the check that would
    have caught the prune incident."""
    import importlib

    missing: list[str] = []
    for path in sorted(_ADAPTERS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("core.llm.providers"):
                continue
            module = importlib.import_module(node.module)
            for alias in node.names:
                if not hasattr(module, alias.name):
                    missing.append(f"{path.name}: {node.module}.{alias.name}")
    assert not missing, f"adapters import provider symbols that no longer exist: {missing}"


@pytest.mark.parametrize(
    "symbol",
    ["_feed_banner_from_anthropic_response", "_build_httpx_limits", "_build_httpx_timeout"],
)
def test_provider_helpers_consumed_by_adapters_exist(symbol: str) -> None:
    import core.llm.providers.anthropic as anthropic_provider

    assert hasattr(anthropic_provider, symbol)
