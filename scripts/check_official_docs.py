"""Run the official GEODE documentation generation gate.

This is the release-facing composition layer for the docs site. It regenerates
the site SOT/Changelog/llms indexes, validates repo-local docs links and
render-gated Markdown, then builds the static Next.js export.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = REPO_ROOT / "site"
VENV_BIN = REPO_ROOT / ".venv" / "bin"


@dataclass(frozen=True)
class DocsCommand:
    label: str
    argv: tuple[str, ...]
    cwd: Path


def _resolve_executable(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise SystemExit(f"missing required executable on PATH: {name}")
    return found


def build_docs_commands(*, skip_build: bool = False) -> list[DocsCommand]:
    npm = _resolve_executable("npm")
    commands = [
        DocsCommand(
            "sync site SOT, changelog, and llms indexes",
            (npm, "run", "sync-stats"),
            SITE_DIR,
        ),
        DocsCommand(
            "check docs links",
            (sys.executable, "scripts/check_docs_links.py", "--quiet"),
            REPO_ROOT,
        ),
        DocsCommand(
            "lint render-gated markdown",
            ("/bin/bash", "scripts/lint_pages_markdown.sh"),
            REPO_ROOT,
        ),
    ]
    if not skip_build:
        commands.append(DocsCommand("build static docs site", (npm, "run", "build"), SITE_DIR))
    return commands


def _project_version() -> str:
    with (REPO_ROOT / "pyproject.toml").open("rb") as f:
        data = tomllib.load(f)
    version = data["project"]["version"]
    if not isinstance(version, str):
        raise SystemExit("pyproject.toml project.version must be a string")
    return version


def check_bilingual_release_surfaces() -> None:
    """Ensure public Korean and English release surfaces point at this version."""
    version = _project_version()
    expected_heading = f"# GEODE v{version}"

    for rel_path in ("README.md", "README.ko.md"):
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        if expected_heading not in text:
            raise SystemExit(f"{rel_path} is not aligned to GEODE v{version}")

    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\].*?\n(?P<body>.*?)(?=^## \[)",
        re.M | re.S,
    )
    match = pattern.search(changelog)
    if not match:
        raise SystemExit(f"CHANGELOG.md is missing release section {version}")
    body = match.group("body")
    if not re.search(r"[가-힣]", body):
        raise SystemExit(f"CHANGELOG.md {version} section is missing Korean release notes")
    if not re.search(r"[A-Za-z]", body):
        raise SystemExit(f"CHANGELOG.md {version} section is missing English release notes")


def _command_env() -> dict[str, str]:
    env = os.environ.copy()
    if VENV_BIN.exists():
        env["PATH"] = f"{VENV_BIN}{os.pathsep}{env.get('PATH', '')}"
    env.setdefault("GEODE_REPO", str(REPO_ROOT))
    return env


def run_docs_gate(commands: Sequence[DocsCommand]) -> None:
    env = _command_env()
    print("==> check bilingual release surfaces")
    check_bilingual_release_surfaces()
    for command in commands:
        print(f"==> {command.label}")
        subprocess.run(command.argv, cwd=command.cwd, env=env, check=True)  # noqa: S603


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Regenerate and validate docs without running the Next.js production build.",
    )
    args = parser.parse_args()

    run_docs_gate(build_docs_commands(skip_build=args.skip_build))


if __name__ == "__main__":
    main()
