"""IP name registry — canonical names from fixtures.

Extracted from ``nl_router.py`` so that IP name resolution is available
without importing the NL Router.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _load_ip_names() -> dict[str, str]:
    """Load canonical IP names from fixtures.

    Returns a mapping of lowercased canonical name -> fixture key.
    Example: {"ghost in the shell": "ghost in shell", "berserk": "berserk"}
    """
    from core.domains.game_ip.fixtures import FIXTURE_MAP, load_fixture

    name_to_key: dict[str, str] = {}
    for fk in FIXTURE_MAP:
        try:
            fixture = load_fixture(fk)
            canonical = fixture["ip_info"]["ip_name"]
            name_to_key[canonical.lower()] = fk
        except Exception:
            # Fixture without ip_info -- use key as-is
            name_to_key[fk] = fk
    return name_to_key


# Lazy-loaded cache
_ip_name_cache: dict[str, str] | None = None


def get_ip_name_map() -> dict[str, str]:
    """Get the canonical name -> fixture key map (cached)."""
    global _ip_name_cache
    if _ip_name_cache is None:
        _ip_name_cache = _load_ip_names()
    return _ip_name_cache
