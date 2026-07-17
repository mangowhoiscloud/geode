"""Lossless, immutable registration batches for CLI tool handlers."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType


class UniqueEntries[K, V](Mapping[K, V]):
    """Mapping-compatible entry stream that rejects duplicates before folding.

    A plain ``dict`` has already discarded an earlier value by the time a
    registrar receives it. Builders therefore construct this type from raw
    ``(key, value)`` entries. It validates the stream first, then exposes an
    immutable Mapping for backwards-compatible direct builder consumers.
    """

    def __init__(self, entries: Iterable[tuple[K, V]]) -> None:
        captured = tuple(entries)
        values: dict[K, V] = {}
        duplicates: list[K] = []
        for key, value in captured:
            if key in values:
                duplicates.append(key)
                continue
            values[key] = value
        if duplicates:
            rendered = ", ".join(repr(key) for key in duplicates)
            raise ValueError(f"duplicate entries in one registration group: {rendered}")
        self._entries = captured
        self._values: Mapping[K, V] = MappingProxyType(values)

    @property
    def entries(self) -> tuple[tuple[K, V], ...]:
        return self._entries

    def __getitem__(self, key: K) -> V:
        return self._values[key]

    def __iter__(self) -> Iterator[K]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)
