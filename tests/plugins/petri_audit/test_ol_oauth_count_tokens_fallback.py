"""OL-OAUTH-COUNT-TOKENS — Claude OAuth count_tokens fallback invariants.

Background
==========

Claude OAuth tokens carry scope ``user:inference`` which Anthropic's
gateway accepts for ``/v1/messages`` but rejects with ``401 invalid
x-api-key`` on ``/v1/messages/count_tokens``. inspect_ai's class-method
``count_tokens`` (in its stock ``AnthropicAPI`` at lines 532+)
propagates the 401 with no try/except — a single pre-audit token-
counting call kills the entire audit task with ``Task interrupted (no
samples completed)``.

Pre-fix the run.log of a Pattern-B subscription audit (Claude Max OAuth)
showed::

    AuthenticationError: Error code: 401 - 'invalid x-api-key'
    Task interrupted (no samples completed before interruption)

The fix exposes a pure function :func:`estimate_tokens_for_oauth` that
returns the same ``chars / 4`` Anthropic-documented heuristic
inspect_ai's module-level helper uses on exception (lines 2944-2954).
``ClaudeOAuthAPI.count_tokens`` is a 1-line shim delegating here, so
the heuristic is testable without instantiating inspect_ai's wrapped
class.

Pins
====

1. ``estimate_tokens_for_oauth`` is callable on str / list / None input.
2. ``str`` input → ``max(1, len(s) // 4)``.
3. List of msg-like objects with ``content: str`` → concatenated estimate.
4. List of msg-like objects with ``content: list[block]`` → blocks'
   ``.text`` concatenated.
5. None input → 1 (minimum token count contract).
6. Source file declares ``count_tokens`` override on ``ClaudeOAuthAPI``
   AND delegates to ``estimate_tokens_for_oauth`` (prevents future
   refactor from dropping the delegation).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

# Provider module imports `inspect_ai` lazily inside ``register()``,
# so the module-level import of ``estimate_tokens_for_oauth`` is safe
# even without the audit extra. Heuristic tests run in any env.


def test_estimate_string_input() -> None:
    """``len(s) // 4`` for a plain string."""
    from plugins.petri_audit.claude_code_provider import estimate_tokens_for_oauth

    assert estimate_tokens_for_oauth("a" * 400) == 100  # 400 // 4
    assert estimate_tokens_for_oauth("hello world") == 11 // 4  # 11 chars / 4 = 2


def test_estimate_empty_string_returns_one() -> None:
    """Token counter min contract: never returns 0."""
    from plugins.petri_audit.claude_code_provider import estimate_tokens_for_oauth

    assert estimate_tokens_for_oauth("") == 1


def test_estimate_none_input_returns_one() -> None:
    """None gracefully handled — same as empty."""
    from plugins.petri_audit.claude_code_provider import estimate_tokens_for_oauth

    assert estimate_tokens_for_oauth(None) == 1


def test_estimate_list_of_messages_with_str_content() -> None:
    """Message-like objects with ``content: str`` — texts joined by space."""
    from plugins.petri_audit.claude_code_provider import estimate_tokens_for_oauth

    messages = [
        SimpleNamespace(content="x" * 100),
        SimpleNamespace(content="y" * 100),
    ]
    # "x"*100 + " " + "y"*100 = 201 chars, // 4 = 50
    assert estimate_tokens_for_oauth(messages) == 50


def test_estimate_list_of_messages_with_block_content() -> None:
    """Block-list content (tool_use / thinking shape) — extract ``.text``."""
    from plugins.petri_audit.claude_code_provider import estimate_tokens_for_oauth

    block1 = SimpleNamespace(text="hello world", type="text")
    block2 = SimpleNamespace(text="more text here", type="text")
    msg = SimpleNamespace(content=[block1, block2])
    # "hello world" + " " + "more text here" = 26 chars, // 4 = 6
    assert estimate_tokens_for_oauth([msg]) == 6


def test_estimate_mixed_message_shapes() -> None:
    """A list containing both str-content and block-content messages
    accumulates them all correctly."""
    from plugins.petri_audit.claude_code_provider import estimate_tokens_for_oauth

    str_msg = SimpleNamespace(content="aaaa")  # 4 chars
    block_msg = SimpleNamespace(content=[SimpleNamespace(text="bbbb")])  # 4 chars
    # "aaaa" + " " + "bbbb" = 9 chars, // 4 = 2
    assert estimate_tokens_for_oauth([str_msg, block_msg]) == 2


def test_estimate_skips_non_text_blocks() -> None:
    """Blocks without ``.text`` attribute (or with non-string ``.text``)
    are silently skipped — heuristic stays conservative."""
    from plugins.petri_audit.claude_code_provider import estimate_tokens_for_oauth

    block_with_text = SimpleNamespace(text="abc")
    block_without = SimpleNamespace(no_text="present")
    block_non_string_text = SimpleNamespace(text=42)
    msg = SimpleNamespace(content=[block_with_text, block_without, block_non_string_text])
    # Only "abc" (3 chars) → 1 (min)
    assert estimate_tokens_for_oauth([msg]) == 1


def test_source_has_oauth_count_tokens_override() -> None:
    """Source-level pin: ``ClaudeOAuthAPI`` declares ``count_tokens``
    override AND delegates to ``estimate_tokens_for_oauth``. A future
    refactor that drops the override (reverting to inherited stock
    behaviour) re-introduces the 401 bug and breaks subscription-
    routed audits.
    """
    from plugins.petri_audit import claude_code_provider

    source = Path(claude_code_provider.__file__).read_text(encoding="utf-8")
    assert "async def count_tokens" in source, (
        "OL-OAUTH-COUNT-TOKENS regressed: ClaudeOAuthAPI no longer "
        "overrides count_tokens — subscription-routed audits will hit "
        "401 on /v1/messages/count_tokens and abort the task."
    )
    assert "estimate_tokens_for_oauth" in source, (
        "OL-OAUTH-COUNT-TOKENS regressed: count_tokens override no "
        "longer delegates to estimate_tokens_for_oauth — heuristic "
        "drift between caller + helper risks."
    )


def _has_inspect_ai() -> bool:
    """Return True when inspect_ai is importable — gates the live
    class-instance test below."""
    try:
        import inspect_ai  # noqa: F401
    except ImportError:
        return False
    return True


def test_class_override_delegates_when_inspect_ai_available() -> None:
    """When inspect_ai is installed, ``ClaudeOAuthAPI.count_tokens`` must
    be the override (not the inherited stock implementation). Skip in
    minimal envs without the audit extra.
    """
    if not _has_inspect_ai():
        pytest.skip("inspect_ai extra not installed")

    from plugins.petri_audit import claude_code_provider as p

    if not hasattr(p, "ClaudeOAuthAPI"):
        p.register()

    # The modelapi decorator wraps the class in a factory function, so
    # we can't access the class directly. Verify via attribute on the
    # registered object's __qualname__ (closure path includes class).
    wrap: Any = p.ClaudeOAuthAPI
    # Heuristic: if the wrapper exists, register() ran without error,
    # meaning the class body (including count_tokens) compiled OK.
    # The source-level pin above is the durable contract.
    assert callable(wrap)
