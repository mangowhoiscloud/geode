from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_cli_channel_starts_before_gateway_pollers() -> None:
    """Source pin: gateway pollers may block in start(), so CLI opens first."""
    src = (REPO_ROOT / "core" / "cli" / "typer_serve.py").read_text(encoding="utf-8")
    cli_start = src.index("_cli_poller.start()")
    gateway_start = src.index("gateway.start()")
    assert cli_start < gateway_start


def test_serve_starts_cli_socket_with_external_gateway_disabled() -> None:
    """The daemon's local IPC channel does not depend on external gateways."""
    with tempfile.TemporaryDirectory(prefix="geode-serve-", dir="/tmp") as temp_dir:
        root = Path(temp_dir)
        geode_home = root / "home"
        project_dir = root / "project"
        project_dir.mkdir()
        env = {
            **os.environ,
            "ANTHROPIC_API_KEY": "",
            "GEODE_GATEWAY_ENABLED": "false",
            "GEODE_HOME": str(geode_home),
            "GEODE_PROJECT_DIR": str(project_dir),
            "GEODE_STATE_ROOT": str(root / "state"),
            "GEODE_WEBHOOK_ENABLED": "true",
            "GEODE_WEBHOOK_PORT": "0",
            "OPENAI_API_KEY": "",
            "ZAI_API_KEY": "",
        }
        proc = subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                "-c",
                "from core.cli import app; app()",
                "serve",
                "--poll",
                "0.05",
            ],
            cwd=project_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        socket_path = geode_home / "cli.sock"
        started = False
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and proc.poll() is None:
                if socket_path.exists():
                    started = True
                    break
                time.sleep(0.05)
        finally:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        output = proc.stdout.read() if proc.stdout else ""
        assert started, output
        assert "Webhook endpoint started" not in output


def test_local_only_serve_exits_when_cli_socket_cannot_start() -> None:
    """A local-only daemon must not report success without a usable socket."""
    with tempfile.TemporaryDirectory(prefix="geode-serve-", dir="/tmp") as temp_dir:
        root = Path(temp_dir)
        geode_home = root / ("x" * 120)
        project_dir = root / "project"
        project_dir.mkdir()
        env = {
            **os.environ,
            "ANTHROPIC_API_KEY": "",
            "GEODE_GATEWAY_ENABLED": "false",
            "GEODE_HOME": str(geode_home),
            "GEODE_PROJECT_DIR": str(project_dir),
            "GEODE_STATE_ROOT": str(root / "state"),
            "GEODE_WEBHOOK_ENABLED": "false",
            "OPENAI_API_KEY": "",
            "ZAI_API_KEY": "",
        }
        proc = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-c",
                "from core.cli import app; app()",
                "serve",
                "--poll",
                "0.05",
            ],
            cwd=project_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
    assert proc.returncode != 0
    assert "CLI channel failed to start; daemon stopped." in proc.stdout
