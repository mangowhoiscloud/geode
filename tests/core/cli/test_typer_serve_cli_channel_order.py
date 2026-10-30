from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import psutil
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_COMMAND = [sys.executable, "-P", "-c", "from core.cli import app; app()"]


@pytest.fixture
def isolated_cli() -> Iterator[tuple[Path, dict[str, str]]]:
    """Own temporary homes and daemon identities without inheriting credentials."""
    with tempfile.TemporaryDirectory(prefix="g-cli-", dir="/tmp") as temp_dir:
        root = Path(temp_dir).resolve()
        home = root / "home"
        home.mkdir()
        geode_home = root / "geode"
        geode_home.mkdir()
        # Exercise an already-onboarded, credential-free CLI. Otherwise the
        # first-run credential wizard consumes the scripted slash commands.
        (geode_home / ".dry-run-opt-in").touch(mode=0o600)
        # The real CLI and its children must never reach a provider during these
        # model-free tests. AF_UNIX remains available for the real IPC transport.
        (root / "sitecustomize.py").write_text(
            "import socket, sys\n"
            "def reject_network(event, args):\n"
            "    if event == 'socket.connect' and args[0].family != socket.AF_UNIX:\n"
            "        raise OSError('Network disabled in CLI startup E2E')\n"
            "sys.addaudithook(reject_network)\n",
            encoding="utf-8",
        )
        env = {
            "HOME": str(home),
            "PATH": os.defpath,
            "PYTHONPATH": os.pathsep.join((str(root), str(REPO_ROOT))),
            "PYTHONUNBUFFERED": "1",
            "GEODE_HOME": str(geode_home),
            "GEODE_STATE_ROOT": str(root / "state"),
            "GEODE_GATEWAY_ENABLED": "false",
            "GEODE_WEBHOOK_ENABLED": "false",
            "GEODE_CLI_FULLSCREEN": "0",
            "NO_COLOR": "1",
            "TERM": "dumb",
        }
        try:
            yield root, env
        finally:
            # Detached children are discovered only through this fixture's own
            # records, with creation-time and cwd checks before any signal.
            for owner_path in root.rglob("*.serve.lock"):
                try:
                    record = json.loads(owner_path.read_text(encoding="utf-8"))
                    process = psutil.Process(record["pid"])
                    if process.create_time() != record["create_time"]:
                        continue
                    if not Path(process.cwd()).resolve().is_relative_to(root):
                        continue
                    children = process.children(recursive=True)
                    process.terminate()
                    _, alive = psutil.wait_procs([process, *children], timeout=10)
                    for child in alive:
                        child.kill()
                    _, alive = psutil.wait_procs(alive, timeout=5)
                    assert not alive, "Owned E2E daemon failed to stop"
                except (OSError, ValueError, KeyError, psutil.NoSuchProcess):
                    continue


def _socket_path(workspace: Path, env: dict[str, str]) -> Path:
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-P",
            "-c",
            "from core.paths import CLI_SOCKET_PATH; print(CLI_SOCKET_PATH)",
        ],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return Path(result.stdout.strip())


def _listening(path: Path) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(1)
            probe.connect(str(path))
        return True
    except OSError:
        return False


def _run_cli(workspace: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(  # noqa: S603
        CLI_COMMAND,
        input="/model\n/quit\n",
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "connected" in output, output
    assert "Models" in output, output
    assert "different workspace" not in output, output
    return result


def _owner(path: Path, workspace: Path) -> dict[str, object]:
    record: dict[str, object] = json.loads(
        path.with_suffix(".serve.lock").read_text(encoding="utf-8")
    )
    assert record["workspace"] == str(workspace.resolve())
    assert type(record["pid"]) is int
    process = psutil.Process(record["pid"])
    assert process.create_time() == record["create_time"]
    assert Path(process.cwd()).resolve() == workspace.resolve()
    return record


def test_cli_channel_starts_before_gateway_pollers() -> None:
    """Source pin: gateway pollers may block in start(), so CLI opens first."""
    src = (REPO_ROOT / "core" / "cli" / "typer_serve.py").read_text(encoding="utf-8")
    cli_start = src.index("_cli_poller.start()")
    gateway_start = src.index("gateway.start()")
    assert cli_start < gateway_start


def test_serve_starts_cli_socket_with_external_gateway_disabled(
    isolated_cli: tuple[Path, dict[str, str]],
) -> None:
    """The daemon's local IPC channel does not depend on external gateways."""
    root, env = isolated_cli
    project_dir = root / "project"
    project_dir.mkdir()
    env.update(GEODE_WEBHOOK_ENABLED="true", GEODE_WEBHOOK_PORT="0")
    socket_path = _socket_path(project_dir, env)
    proc = subprocess.Popen(  # noqa: S603
        [*CLI_COMMAND, "serve", "--poll", "0.05"],
        cwd=project_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    started = False
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and proc.poll() is None:
            if _listening(socket_path):
                started = True
                break
            time.sleep(0.05)
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            output, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            output, _ = proc.communicate(timeout=5)
    assert started, output
    assert "Webhook endpoint started" not in output


def test_local_only_serve_exits_when_cli_socket_cannot_start(
    isolated_cli: tuple[Path, dict[str, str]],
) -> None:
    """A local-only daemon must not report success without a usable socket."""
    root, env = isolated_cli
    project_dir = root / "project"
    project_dir.mkdir()
    env["GEODE_HOME"] = str(root / ("x" * 120))
    proc = subprocess.run(  # noqa: S603
        [*CLI_COMMAND, "serve", "--poll", "0.05"],
        cwd=project_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert proc.returncode != 0
    assert "CLI channel failed to start." in proc.stdout


@pytest.mark.parametrize(
    "relative_dir",
    [
        "arbitrary",
        "nested/project",
        "공백 있는 프로젝트",
        "shadows-core",
        "deep/" + "x" * 80 + "/" + "y" * 40,
    ],
)
def test_cli_starts_from_caller_directory_without_using_path_binary(
    isolated_cli: tuple[Path, dict[str, str]], relative_dir: str
) -> None:
    root, env = isolated_cli
    workspace = root / relative_dir
    workspace.mkdir(parents=True)
    if relative_dir.startswith("nested/"):
        (workspace / ".git").mkdir()
    shadow_marker = root / "wrong-core-imported"
    if relative_dir == "shadows-core":
        package = workspace / "core"
        package.mkdir()
        (package / "__init__.py").write_text(
            f"from pathlib import Path; Path({str(shadow_marker)!r}).touch(); "
            "raise RuntimeError('Loaded workspace code instead of GEODE')\n"
        )
    wrong_project = root / "unrelated"
    wrong_project.mkdir()
    bin_dir = root / "bin"
    bin_dir.mkdir()
    poison_called = root / "wrong-install-called"
    poison = bin_dir / "geode"
    poison.write_text(f"#!/bin/sh\n: > {shlex.quote(str(poison_called))}\nexit 97\n")
    poison.chmod(0o700)
    env.update(
        PATH=os.pathsep.join((str(bin_dir), os.defpath)),
        GEODE_PROJECT_DIR=str(wrong_project),
        GEODE_GATEWAY_ENABLED="true",
        GEODE_WEBHOOK_ENABLED="true",
        GEODE_WEBHOOK_PORT="0",
    )

    _run_cli(workspace, env)
    endpoint = _socket_path(workspace, env)
    owner = _owner(endpoint, workspace)
    assert _listening(endpoint)
    assert not poison_called.exists()
    assert not shadow_marker.exists()
    assert not _socket_path(wrong_project, env).exists()
    assert psutil.Process(owner["pid"]).environ()["GEODE_GATEWAY_ENABLED"] == "false"


def test_workspace_daemons_coexist_reuse_and_stop_independently(
    isolated_cli: tuple[Path, dict[str, str]],
) -> None:
    root, env = isolated_cli
    workspace_a, workspace_b = root / "project", root / "project" / "nested"
    workspace_b.mkdir(parents=True)
    (workspace_b / ".git").mkdir()
    _run_cli(workspace_a, env)
    _run_cli(workspace_b, env)
    endpoint_a, endpoint_b = _socket_path(workspace_a, env), _socket_path(workspace_b, env)
    owner_a, owner_b = _owner(endpoint_a, workspace_a), _owner(endpoint_b, workspace_b)
    assert owner_a["pid"] != owner_b["pid"]
    assert endpoint_a != endpoint_b

    _run_cli(workspace_a, env)
    assert _owner(endpoint_a, workspace_a) == owner_a
    alias = root / "project-alias"
    alias.symlink_to(workspace_a, target_is_directory=True)
    _run_cli(alias, env)
    assert _socket_path(alias, env) == endpoint_a
    assert _owner(endpoint_a, workspace_a) == owner_a

    duplicate = subprocess.run(  # noqa: S603
        [*CLI_COMMAND, "serve"],
        cwd=workspace_a,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert duplicate.returncode != 0
    assert "already serving this workspace" in duplicate.stdout
    assert _listening(endpoint_a) and _listening(endpoint_b)
    assert _owner(endpoint_a, workspace_a) == owner_a

    # Exercise the lifecycle owner from a fresh process for workspace A;
    # the CLI currently has no standalone Typer stop subcommand.
    stopped = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-c",
            "from core.cli.commands.lifecycle import stop_serve; "
            "raise SystemExit(0 if stop_serve(timeout=10) else 1)",
        ],
        cwd=workspace_a,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    assert not _listening(endpoint_a)
    assert _listening(endpoint_b)
    _run_cli(workspace_b, env)
    assert _owner(endpoint_b, workspace_b) == owner_b


def test_concurrent_clients_share_one_owner_and_preserve_legacy_socket(
    isolated_cli: tuple[Path, dict[str, str]],
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    root, env = isolated_cli
    workspace = root / "concurrent"
    workspace.mkdir()
    legacy_path = Path(env["GEODE_HOME"]) / "cli.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as legacy:
        legacy.bind(str(legacy_path))
        legacy.listen(5)
        legacy_inode = legacy_path.stat().st_ino
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_run_cli, workspace, env) for _ in range(2)]
            for future in futures:
                future.result(timeout=50)
        endpoint = _socket_path(workspace, env)
        owner = _owner(endpoint, workspace)
        assert endpoint != legacy_path
        assert legacy_path.stat().st_ino == legacy_inode
        assert _listening(legacy_path)
        records = [path for path in root.rglob("*.serve.lock") if path.read_text().strip()]
        assert records == [endpoint.with_suffix(".serve.lock")]
        _run_cli(workspace, env)
        assert _owner(endpoint, workspace) == owner


def test_custom_endpoint_keeps_canonical_owner_and_transport_exclusion(
    isolated_cli: tuple[Path, dict[str, str]],
) -> None:
    from core.cli.commands.lifecycle import _all_runtimes_stopped
    from core.paths import encode_project_id

    root, env = isolated_cli
    workspace = root / "custom-owner"
    workspace.mkdir()
    endpoint = root / "external-transport" / "different-name.sock"
    env["GEODE_CLI_SOCKET"] = str(endpoint)
    _run_cli(workspace, env)
    home = Path(env["GEODE_HOME"])
    owner_path = home / "run" / encode_project_id(workspace) / "cli.serve.lock"
    record = json.loads(owner_path.read_text())
    assert record["workspace"] == str(workspace.resolve())
    assert record["socket_path"] == str(endpoint)
    assert not _all_runtimes_stopped(home)
    inode = endpoint.stat().st_ino
    other = root / "other-owner"
    other.mkdir()
    rejected = subprocess.run(  # noqa: S603 - fixed CLI argv in an owned temporary workspace
        [*CLI_COMMAND, "serve"],
        cwd=other,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert rejected.returncode != 0
    assert endpoint.stat().st_ino == inode and _listening(endpoint)
    stopped = subprocess.run(  # noqa: S603 - fixed lifecycle probe in an owned temporary workspace
        [
            sys.executable,
            "-P",
            "-c",
            "from core.cli.commands.lifecycle import stop_serve; "
            "raise SystemExit(0 if stop_serve(timeout=10) else 1)",
        ],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    assert not _listening(endpoint) and _all_runtimes_stopped(home)
