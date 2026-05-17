"""Domain adapter loader — discovers and instantiates domain adapters.

Discovery is two-pass:

1. Direct registry lookup. Plugins typically pre-register themselves at
   import time via ``register_domain(...)`` from their package
   ``__init__.py``.
2. Convention fallback. If the requested name is not in the registry, we
   try to import ``plugins.<name>`` so its ``__init__.py`` runs and
   self-registers, then re-check the registry.

This keeps ``core/`` free of plugin import paths: the registry seeds itself
at runtime when a plugin is imported, and consumers (CLI bootstrap, tests)
can call ``load_domain_adapter(name)`` without first importing the plugin.

Usage:
    adapter = load_domain_adapter("research")
    set_domain(adapter)
"""

from __future__ import annotations

import importlib
import logging

from core.domains.port import DomainPort

log = logging.getLogger(__name__)

# Registry of domain adapters. Populated at runtime by ``register_domain``,
# typically from ``plugins/<name>/__init__.py`` at import time.
_BUILTIN_DOMAINS: dict[str, str] = {}


def load_domain_adapter(name: str) -> DomainPort:
    """Load a domain adapter by name.

    Args:
        name: Domain identifier (e.g. "research").

    Returns:
        Instantiated DomainPort implementation.

    Raises:
        ValueError: If domain name is not found after both registry and
            convention-fallback lookup.
        ImportError: If adapter module cannot be imported.
    """
    if name not in _BUILTIN_DOMAINS:
        # Convention fallback: importing plugins.<name> triggers the plugin's
        # __init__.py, which is expected to call register_domain(...).
        try:
            importlib.import_module(f"plugins.{name}")
        except ImportError:
            log.debug("plugins.%s not importable for self-registration", name)

    if name not in _BUILTIN_DOMAINS:
        available = ", ".join(sorted(_BUILTIN_DOMAINS.keys())) or "<none registered>"
        raise ValueError(f"Unknown domain: {name!r}. Available: {available}")

    module_path = _BUILTIN_DOMAINS[name]
    module_name, class_name = module_path.rsplit(":", 1)

    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    adapter: DomainPort = cls()
    log.info("Loaded domain adapter: %s v%s", adapter.name, adapter.version)
    return adapter


def list_domains() -> list[str]:
    """Return list of currently registered domain names."""
    return sorted(_BUILTIN_DOMAINS.keys())


def register_domain(name: str, adapter_path: str) -> None:
    """Register a domain adapter at runtime.

    Args:
        name: Domain identifier.
        adapter_path: Import path in "module:ClassName" format.
    """
    _BUILTIN_DOMAINS[name] = adapter_path
    log.info("Registered domain: %s -> %s", name, adapter_path)
