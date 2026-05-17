"""ContextVar-backed local storage with ``threading.local``-style access."""

from __future__ import annotations

import threading
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any, cast


class ContextLocal:
    """Small ``threading.local``-compatible facade for async task isolation.

    Attribute access first reads task-local state from a ``ContextVar``. If the
    current context has not written any values, it falls back to a per-thread
    dictionary. Mutations copy the current mapping before setting it back on
    the context, so concurrently-created asyncio tasks do not share the same
    mutable dictionary.
    """

    def __init__(self, name: str) -> None:
        object.__setattr__(self, "_ctx", ContextVar[dict[str, Any] | None](name, default=None))
        object.__setattr__(self, "_thread", threading.local())
        object.__setattr__(self, "_dict_proxy", _ContextLocalDict(self))

    def __getattribute__(self, name: str) -> Any:
        if name == "__dict__":
            return object.__getattribute__(self, "_dict_proxy")
        if name.startswith("_"):
            return object.__getattribute__(self, name)
        data = self._read()
        if name in data:
            return data[name]
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        data = self._copy_current()
        data[name] = value
        self._write(data)

    def __delattr__(self, name: str) -> None:
        if name.startswith("_"):
            object.__delattr__(self, name)
            return
        data = self._copy_current()
        if name not in data:
            raise AttributeError(name)
        del data[name]
        self._write(data)

    def _read(self) -> dict[str, Any]:
        ctx_data = self._ctx.get()
        if ctx_data is not None:
            return cast(dict[str, Any], ctx_data)
        return cast(dict[str, Any], self._thread.__dict__)

    def _copy_current(self) -> dict[str, Any]:
        return dict(self._read())

    def _write(self, data: dict[str, Any]) -> None:
        self._ctx.set(data)

    def _clear_key(self, key: str) -> None:
        data = self._copy_current()
        data.pop(key, None)
        self._write(data)


class _ContextLocalDict(MutableMapping[str, Any]):
    """Minimal mapping proxy for legacy ``local.__dict__`` call sites."""

    def __init__(self, local: ContextLocal) -> None:
        self._local = local

    def __getitem__(self, key: str) -> Any:
        return self._local._read()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        data = self._local._copy_current()
        data[key] = value
        self._local._write(data)

    def __delitem__(self, key: str) -> None:
        data = self._local._copy_current()
        del data[key]
        self._local._write(data)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._local._read())

    def __len__(self) -> int:
        return len(self._local._read())

    def pop(self, key: str, default: Any = None) -> Any:
        data = self._local._copy_current()
        value = data.pop(key, default)
        self._local._write(data)
        return value
