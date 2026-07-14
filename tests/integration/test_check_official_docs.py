"""Tests for the official docs generation gate."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import check_official_docs


def test_build_docs_commands_orders_generation_before_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        check_official_docs,
        "_resolve_executable",
        lambda name: f"/usr/bin/{name}",
    )

    commands = check_official_docs.build_docs_commands()

    assert [command.label for command in commands] == [
        "sync site SOT, changelog, and llms index",
        "check docs links",
        "lint render-gated markdown",
        "build static docs site",
        "export docs markdown and llms-full index",
        "verify generated docs are committed",
    ]
    assert commands[0].argv == ("/usr/bin/npm", "run", "sync-stats")
    assert commands[1].argv[1:] == ("scripts/check_docs_links.py", "--quiet")
    assert commands[2].argv == ("/bin/bash", "scripts/lint_pages_markdown.sh")
    assert commands[3].argv == ("/usr/bin/npm", "run", "build")
    assert commands[4].argv == ("/usr/bin/npm", "run", "export-md")
    assert commands[5].argv == (
        "/usr/bin/git",
        "diff",
        "--exit-code",
        "--",
        *check_official_docs.GENERATED_DOCS,
    )


def test_build_docs_commands_can_skip_site_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        check_official_docs,
        "_resolve_executable",
        lambda name: f"/usr/bin/{name}",
    )

    commands = check_official_docs.build_docs_commands(skip_build=True)

    assert [command.label for command in commands] == [
        "sync site SOT, changelog, and llms index",
        "check docs links",
        "lint render-gated markdown",
        "verify generated docs are committed",
    ]
    assert commands[3].argv == (
        "/usr/bin/git",
        "diff",
        "--exit-code",
        "--",
        *check_official_docs.GENERATED_DOCS[:-1],
    )


def test_run_docs_gate_uses_repo_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[tuple[str, ...], Path, dict[str, str]]] = []
    venv_bin = tmp_path / "bin"
    venv_bin.mkdir()
    monkeypatch.setattr(check_official_docs, "VENV_BIN", venv_bin)
    monkeypatch.setattr(check_official_docs, "check_release_surfaces", lambda: None)
    monkeypatch.setenv("PATH", "/bin")

    def fake_run(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        check: bool,
    ) -> None:
        assert check is True
        calls.append((argv, cwd, env))

    monkeypatch.setattr("scripts.check_official_docs.subprocess.run", fake_run)

    command = check_official_docs.DocsCommand(
        "demo",
        ("demo",),
        check_official_docs.REPO_ROOT,
    )
    check_official_docs.run_docs_gate([command])

    assert calls == [(("demo",), check_official_docs.REPO_ROOT, calls[0][2])]
    assert calls[0][2]["GEODE_REPO"] == str(check_official_docs.REPO_ROOT)
    assert calls[0][2]["PATH"].startswith(f"{venv_bin}:")


def test_check_release_surfaces_accepts_current_release() -> None:
    check_official_docs.check_release_surfaces()
