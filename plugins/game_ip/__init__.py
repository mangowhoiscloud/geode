"""Game IP domain adapter — undervalued game IP evaluation.

Self-registers with ``core.domains.loader`` on import (Step 1 of the
domain-free-core refactor). The loader's convention-fallback can now
discover this plugin by importing ``plugins.game_ip`` without needing
a hard-coded registry seed in core.

Step 4 also merges the plugin's slash commands into ``core.cli.commands.COMMAND_MAP``
at import time so static-import paths (tests, REPL bootstrap, the legacy
``COMMAND_REGISTRY`` parity check) see the full slash registry without
needing the bootstrap helper to have been called.
"""

from core.domains.loader import register_domain

register_domain("game_ip", "plugins.game_ip.adapter:GameIPDomain")

from plugins.game_ip.adapter import GameIPDomain  # noqa: E402

# Eagerly merge slash entries into COMMAND_MAP. The bootstrap helper
# (``core/cli/bootstrap.py:install_domain_commands``) is the canonical
# wiring path; this import-time merge is a static fallback so that
# ``COMMAND_MAP`` is populated whenever the plugin is importable, even
# in test contexts that never call ``bootstrap_geode``.
try:  # pragma: no cover - thin import-time guard
    import logging as _logging

    from core.cli.commands import COMMAND_MAP as _COMMAND_MAP

    from plugins.game_ip.cli.commands import GAME_IP_SLASHES as _GAME_IP_SLASHES

    _COMMAND_MAP.update(_GAME_IP_SLASHES)
except Exception:
    # Avoid hard-failing plugin import if commands module is partway
    # initialized (circular-import edge cases during test collection).
    _logging.getLogger(__name__).debug(
        "Game-IP slash registration deferred to bootstrap", exc_info=True
    )

__all__ = ["GameIPDomain"]
