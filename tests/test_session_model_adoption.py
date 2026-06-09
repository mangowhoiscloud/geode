"""Daemon adopts the thin CLI's project-resolved model (2026-06-09 fix).

The serve daemon creates each session with its OWN launch-cwd default
(``settings.model``); the thin CLI resolves the model at the *caller's*
project cwd and ships it in the ``client_capability`` message. The poller must
adopt it so the executed model matches the caller's project (and the banner),
instead of the daemon's launch-cwd model. The ``client_capability`` branch of
``CLIPoller._process_message_async`` is self-stateless, so we exercise it
directly on a bare instance with a mock loop.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from core.server.ipc_server.poller import CLIPoller


def _bare_poller() -> CLIPoller:
    # client_capability handling touches no instance state — skip __init__.
    return object.__new__(CLIPoller)


def _capability_msg(**extra: object) -> dict[str, object]:
    return {"type": "client_capability", "is_tty": True, "width": 120, "_client": None, **extra}


def test_client_capability_adopts_cli_project_model() -> None:
    poller = _bare_poller()
    loop = MagicMock()
    loop.model = "claude-opus-4-6"  # daemon launch-cwd default
    loop.update_model_async = AsyncMock()

    result = asyncio.run(
        poller._process_message_async(
            _capability_msg(model="claude-opus-4-8"), loop, MagicMock(), "cli-test"
        )
    )

    assert result == {"type": "ack"}
    loop.update_model_async.assert_awaited_once()
    assert loop.update_model_async.call_args.args[0] == "claude-opus-4-8"


def test_client_capability_no_model_keeps_daemon_default() -> None:
    poller = _bare_poller()
    loop = MagicMock()
    loop.model = "claude-opus-4-6"
    loop.update_model_async = AsyncMock()

    # Old client (no model field) — daemon must not swap.
    asyncio.run(poller._process_message_async(_capability_msg(), loop, MagicMock(), "cli-test"))
    loop.update_model_async.assert_not_awaited()


def test_client_capability_same_model_no_swap() -> None:
    poller = _bare_poller()
    loop = MagicMock()
    loop.model = "claude-opus-4-8"
    loop.update_model_async = AsyncMock()

    asyncio.run(
        poller._process_message_async(
            _capability_msg(model="claude-opus-4-8"), loop, MagicMock(), "cli-test"
        )
    )
    loop.update_model_async.assert_not_awaited()
