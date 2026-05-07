"""Computer-use handler (desktop automation).

Only active when ``GEODE_COMPUTER_USE_ENABLED=true`` and ``pyautogui`` is
installed. Returns an empty handler dict otherwise.
"""

from __future__ import annotations

from typing import Any


def _build_computer_use_handler() -> dict[str, Any]:
    """Build computer-use handler (screenshot + mouse + keyboard)."""
    from core.llm.providers.anthropic import is_computer_use_enabled

    if not is_computer_use_enabled():
        return {}

    from core.tools.computer_use import ComputerUseHarness

    harness = ComputerUseHarness()

    def handle_computer(**kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action", "screenshot")
        return harness.execute(action, **kwargs)

    return {"computer": handle_computer}
