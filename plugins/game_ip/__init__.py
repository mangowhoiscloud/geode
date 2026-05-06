"""Game IP domain adapter — undervalued game IP evaluation.

Self-registers with ``core.domains.loader`` on import (Step 1 of the
domain-free-core refactor). The loader's convention-fallback can now
discover this plugin by importing ``plugins.game_ip`` without needing
a hard-coded registry seed in core.
"""

from core.domains.loader import register_domain

register_domain("game_ip", "plugins.game_ip.adapter:GameIPDomain")

from plugins.game_ip.adapter import GameIPDomain  # noqa: E402

__all__ = ["GameIPDomain"]
