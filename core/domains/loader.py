"""Domain adapter loader — discovers and instantiates domain adapters.

Usage:
    adapter = load_domain_adapter("game_ip")
    set_domain(adapter)
"""

from __future__ import annotations

import logging

from core.domains.port import DomainPort

log = logging.getLogger(__name__)

# Registry of built-in domain adapters (lazy-loaded)
_BUILTIN_DOMAINS: dict[str, str] = {
    "game_ip": "core.domains.game_ip.adapter:GameIPDomain",
}


def load_domain_adapter(name: str) -> DomainPort:
    """Load a domain adapter by name.

    Args:
        name: Domain identifier (e.g. "game_ip").

    Returns:
        Instantiated DomainPort implementation.

    Raises:
        ValueError: If domain name is not found.
        ImportError: If adapter module cannot be imported.
    """
    if name not in _BUILTIN_DOMAINS:
        available = ", ".join(sorted(_BUILTIN_DOMAINS.keys()))
        raise ValueError(f"Unknown domain: {name!r}. Available: {available}")

    module_path = _BUILTIN_DOMAINS[name]
    module_name, class_name = module_path.rsplit(":", 1)

    import importlib

    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    adapter: DomainPort = cls()
    log.info("Loaded domain adapter: %s v%s", adapter.name, adapter.version)
    return adapter


def list_domains() -> list[str]:
    """Return list of available domain names."""
    return sorted(_BUILTIN_DOMAINS.keys())


def register_domain(name: str, adapter_path: str) -> None:
    """Register a custom domain adapter at runtime.

    Args:
        name: Domain identifier.
        adapter_path: Import path in "module:ClassName" format.
    """
    _BUILTIN_DOMAINS[name] = adapter_path
    log.info("Registered domain: %s -> %s", name, adapter_path)
