"""Tests for the official docs generation gate."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import check_official_docs


def test_build_docs_commands_check_generated_sources_and_markdown() -> None:
    commands = check_official_docs.build_docs_commands()

    assert [command.label for command in commands] == [
        "check generated architecture baseline",
        "check generated evaluation catalog",
        "lint render-gated markdown",
    ]
    assert commands[0].argv[1:] == ("scripts/architecture_baseline.py", "--check")
    assert commands[1].argv[1:] == ("scripts/eval/contract.py", "catalog", "--check")
    assert commands[2].argv == ("/bin/bash", "scripts/lint_pages_markdown.sh")


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


@pytest.mark.parametrize("column", ["code", "guide", "test"])
def test_public_docs_url_counts_only_as_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, column: str
) -> None:
    monkeypatch.setattr(check_official_docs, "REPO_ROOT", tmp_path)
    document = tmp_path / check_official_docs.OWNER_MAP
    document.parent.mkdir(parents=True)
    for name in ("code.py", "test.py"):
        (tmp_path / name).touch()
    public = f"[page]({check_official_docs.PUBLIC_DOCS_PREFIX}run/providers/)"
    cells = {"code": "[code](../../code.py)", "guide": public, "test": "[test](../../test.py)"}
    cells[column] = public
    document.write_text(
        "## Code and documentation owners\n\n"
        "| Surface | Code | Guide | Test |\n|---|---|---|---|\n"
        f"| Fixture | {cells['code']} | {cells['guide']} | {cells['test']} |\n",
        encoding="utf-8",
    )
    if column == "guide":
        check_official_docs.check_owner_map()
    else:
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
