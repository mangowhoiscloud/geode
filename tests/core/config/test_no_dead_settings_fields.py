"""Guard: every ``Settings`` field must have a consumer (no dead knobs).

Incident: PR-CONFIG-SLOP-SWEEP (v0.99.218) — ``agentic_loop_time_budget``,
``max_total_subagents``, ``subagent_max_tokens``, ``checkpoint_db`` were each
declared on ``Settings`` *and* mapped in the ``config.toml`` cascade, but no
runtime code ever read them. So an operator setting e.g. ``[subagent] max_total``
got silently ignored — the same "setting surface with no wired consumer" slop
class as the ``.env.example`` empty-placeholder footgun (PR-HERMES-ENV-ALIGN).

This pins that every non-allowlisted field is actually consumed somewhere in
``core/`` or ``plugins/`` outside the config declaration + tests, so a future
dead knob fails CI instead of shipping.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.config._settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]

# Fields intentionally not consumed by runtime code (none today). Add a field
# here ONLY with a comment explaining why it has no reader — the default
# expectation is that every knob is wired.
_ALLOWLIST: set[str] = set()


def _consumer_texts() -> list[str]:
    """Read every core/plugins .py file except the config declaration + tests."""
    skip_suffixes = ("core/config/_settings.py", "core/config/__init__.py")
    texts: list[str] = []
    for pkg in ("core", "plugins"):
        for path in (REPO_ROOT / pkg).rglob("*.py"):
            as_str = path.as_posix()
            if as_str.endswith(skip_suffixes) or "test" in as_str:
                continue
            texts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return texts


def test_no_dead_settings_fields() -> None:
    texts = _consumer_texts()
    dead: list[str] = []
    for field in Settings.model_fields:
        if field in _ALLOWLIST:
            continue
        pattern = re.compile(r"\b" + re.escape(field) + r"\b")
        if not any(pattern.search(text) for text in texts):
            dead.append(field)
    assert not dead, (
        "Settings fields with no consumer outside config/tests "
        f"(dead knobs — wire them to a reader or remove field + TOML map): {sorted(dead)}"
    )
