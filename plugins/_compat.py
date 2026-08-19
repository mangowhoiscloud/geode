"""Small helpers for the temporary ``plugins.*`` compatibility surface."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType


def canonical_module(legacy_name: str, canonical_name: str) -> ModuleType:
    """Make one verified legacy module name resolve to its canonical module."""
    module = importlib.import_module(canonical_name)
    sys.modules[legacy_name] = module
    return module


def export_package(namespace: dict[str, object], canonical_name: str) -> None:
    """Re-export a package while keeping curated deep aliases reachable."""
    package = importlib.import_module(canonical_name)
    raw_paths = namespace.get("__path__")
    legacy_paths = list(raw_paths) if isinstance(raw_paths, (list, tuple)) else []
    names = tuple(getattr(package, "__all__", ()))
    namespace.update({name: getattr(package, name) for name in names})
    namespace["__all__"] = list(names)
    # Keep legacy discovery closed to the curated physical facades.  Adding the
    # canonical path here made every unlisted deep module importable under a
    # second name, producing duplicate classes and registries.
    namespace["__path__"] = legacy_paths
    namespace["__spec__"] = package.__spec__
    namespace["__file__"] = package.__file__
    namespace["__loader__"] = package.__loader__
