"""core.hooks — Cross-cutting hook system accessible by all layers.

Exposes HookSystem and HookEvent at the package root so any layer can import
without depending on core.orchestration:

    from core.hooks import HookSystem, HookEvent
"""

from core.hooks.system import HookEvent, HookResult, HookSystem

__all__ = ["HookEvent", "HookResult", "HookSystem"]
