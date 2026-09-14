"""Tests for the official docs generation gate."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from scripts import check_docs_links, check_official_docs


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
        "check generated architecture baseline",
        "check generated evaluation catalog",
        "sync site SOT, changelog, and llms index",
        "check docs links",
        "lint render-gated markdown",
        "build static docs site",
        "export docs markdown and llms-full index",
        "verify generated docs are committed",
    ]
    assert commands[0].argv[1:] == ("scripts/architecture_baseline.py", "--check")
    assert commands[1].argv[1:] == ("scripts/eval/contract.py", "catalog", "--check")
    assert commands[2].argv == ("/usr/bin/npm", "run", "sync-stats")
    assert commands[3].argv[1:] == ("scripts/check_docs_links.py", "--quiet")
    assert commands[4].argv == ("/bin/bash", "scripts/lint_pages_markdown.sh")
    assert commands[5].argv == ("/usr/bin/npm", "run", "build")
    assert commands[6].argv == ("/usr/bin/npm", "run", "export-md")
    assert commands[7].argv == (
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
        "check generated architecture baseline",
        "check generated evaluation catalog",
        "sync site SOT, changelog, and llms index",
        "check docs links",
        "lint render-gated markdown",
        "verify generated docs are committed",
    ]
    assert commands[5].argv == (
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


def test_declared_owner_map_resolves() -> None:
    check_official_docs.check_owner_map()


@pytest.mark.parametrize("missing", ["code.py", "docs/guide.md", "test.py"])
@pytest.mark.parametrize("indent", ["", " "])
def test_owner_map_rejects_missing_code_guidance_or_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str, indent: str
) -> None:
    monkeypatch.setattr(check_official_docs, "REPO_ROOT", tmp_path)
    document = tmp_path / check_official_docs.OWNER_MAP
    document.parent.mkdir(parents=True)
    for name in ("code.py", "docs/guide.md", "test.py"):
        if name != missing:
            (tmp_path / name).touch()
    document.write_text(
        "## Code and documentation owners\n\n"
        "| Surface | Code | Guide | Test |\n|---|---|---|---|\n"
        f"{indent}| Fixture | [code](../../code.py) | [guide](../guide.md) | [test](../../test.py) |\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="missing or non-repository owner path"):
        check_official_docs.check_owner_map()


@pytest.mark.parametrize(
    "table",
    [
        "",
        "| Surface | Code | Guide | Test |\n| broken separator |\n"
        "| Fixture | [code](../../code.py) | [guide](../guide.md) | [test](../../test.py) |\n",
        "| Surface | Code | Guide | Test |\n|---|---|---|---|\n"
        "| Fixture | no link | no link | no link |\n",
        "| Surface | Code | Guide | Test |\n|---|---|---|---|\n"
        "| Fixture | [outside](/etc/passwd) | [outside](/etc/passwd) | [outside](/etc/passwd) |\n",
    ],
)
def test_owner_map_rejects_absent_or_unlinked_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table: str
) -> None:
    monkeypatch.setattr(check_official_docs, "REPO_ROOT", tmp_path)
    document = tmp_path / check_official_docs.OWNER_MAP
    document.parent.mkdir(parents=True)
    document.write_text("## Code and documentation owners\n\n" + table, encoding="utf-8")
    with pytest.raises(SystemExit):
        check_official_docs.check_owner_map()


def test_http_audit_missing_dependency_cannot_write_success_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    page = tmp_path / "site/src/app/page.tsx"
    page.parent.mkdir(parents=True)
    page.write_text('<a href="https://unqueried.invalid/">fixture</a>', encoding="utf-8")
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_docs_links.py",
            "--base",
            str(tmp_path / "site"),
            "--http",
            "--receipt",
            str(receipt),
        ],
    )
    monkeypatch.setitem(sys.modules, "requests", None)
    with pytest.raises(SystemExit, match="no external URLs were checked"):
        check_docs_links.main()
    assert not receipt.exists()
    assert "all external URLs reachable" not in capsys.readouterr().out


def test_check_release_surfaces_rejects_stale_security_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(check_official_docs, "REPO_ROOT", tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "geode-agent"\nversion = "1.2.3"\n',
        encoding="utf-8",
    )
    for rel_path in ("README.md", "README.ko.md"):
        (tmp_path / rel_path).write_text(
            "# GEODE v1.2.3: Autonomous Agent Runtime + Evaluation Substrate\n",
            encoding="utf-8",
        )
    (tmp_path / "SECURITY.md").write_text(
        "| Version | Supported |\n| --- | --- |\n| 0.48.x | :white_check_mark: |\n",
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "## [1.2.3] - 2026-08-07\n\nRelease notes.\n\n"
        "## [1.2.2] - 2026-08-06\n\nEarlier release.\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match=r"SECURITY\.md does not mark 1\.2\.x"):
        check_official_docs.check_release_surfaces()
