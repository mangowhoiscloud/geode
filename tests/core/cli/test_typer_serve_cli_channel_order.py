from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_cli_channel_starts_before_gateway_pollers() -> None:
    """Source pin: gateway pollers may block in start(), so CLI opens first."""
    src = (REPO_ROOT / "core" / "cli" / "typer_serve.py").read_text(encoding="utf-8")
    cli_start = src.index("_cli_poller.start()")
    gateway_start = src.index("gateway.start()")
    assert cli_start < gateway_start
