"""Backward-compatible import surface for Unicode boundary helpers."""

from __future__ import annotations

from core.unicode_safety import replace_lone_surrogates, sanitize_jsonable

__all__ = ["replace_lone_surrogates", "sanitize_jsonable"]
