"""Fail-closed composition tests for CLI tool handlers."""

from __future__ import annotations

from typing import Any, cast

import pytest
from core.cli.tool_handlers import _build_tool_handler_catalog, _HandlerRegistrar
from core.cli.tool_handlers.registration import UniqueEntries


def _handler(**_: Any) -> dict[str, object]:
    return {"ok": True}


def test_handler_registrar_preserves_every_registration_origin() -> None:
    registrar = _HandlerRegistrar()
    registrar.add("memory", UniqueEntries((("memory_search", _handler),)))
    registrar.add("calendar", UniqueEntries((("calendar_list", _handler),)))

    catalog = registrar.snapshot()

    assert list(catalog.handlers) == ["memory_search", "calendar_list"]
    assert catalog.origins == {
        "memory_search": "memory",
        "calendar_list": "calendar",
    }


def test_handler_registrar_rejects_cross_group_name_collisions() -> None:
    registrar = _HandlerRegistrar()
    registrar.add("memory", UniqueEntries((("shared_name", _handler),)))

    with pytest.raises(
        ValueError,
        match=r"duplicate tool handler registration: 'shared_name' \(memory vs calendar\)",
    ):
        registrar.add("calendar", UniqueEntries((("shared_name", _handler),)))


def test_registration_group_rejects_duplicates_before_mapping_fold() -> None:
    with pytest.raises(
        ValueError,
        match="duplicate entries in one registration group: 'shared_name'",
    ):
        UniqueEntries(
            (
                ("shared_name", _handler),
                ("shared_name", lambda: {"ok": False}),
            )
        )


def test_registrar_rejects_lossy_plain_mappings() -> None:
    registrar = _HandlerRegistrar()

    with pytest.raises(TypeError, match="must return lossless UniqueEntries"):
        registrar.add(
            "memory",
            cast(UniqueEntries[str, Any], {"shared_name": _handler}),
        )


def test_runtime_catalog_has_one_origin_for_every_handler() -> None:
    catalog = _build_tool_handler_catalog()

    assert catalog.handlers
    assert set(catalog.handlers) == set(catalog.origins)
