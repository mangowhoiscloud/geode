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
GENERATED_DOCS = (
    "site/src/data/geode/sot.ts",
    "site/src/data/geode/changelog.ts",
    "site/public/llms.txt",
    "site/public/llms-full.txt",
)
PUBLIC_IDENTITY = "Autonomous Agent Runtime + Evaluation Substrate"
OWNER_MAP = Path("docs/architecture/official-docs-generation.md")


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
    git = _resolve_executable("git")
    commands = [
        DocsCommand(
            "check generated architecture baseline",
            (sys.executable, "scripts/architecture_baseline.py", "--check"),
            REPO_ROOT,
        ),
        DocsCommand(
            "check generated evaluation catalog",
            (sys.executable, "scripts/eval/contract.py", "catalog", "--check"),
            REPO_ROOT,
        ),
        DocsCommand(
            "sync site SOT, changelog, and llms index",
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
        commands.append(
            DocsCommand(
                "export docs markdown and llms-full index",
                (npm, "run", "export-md"),
                SITE_DIR,
            )
        )
    checked_files = GENERATED_DOCS[:-1] if skip_build else GENERATED_DOCS
    commands.append(
        DocsCommand(
            "verify generated docs are committed",
            (git, "diff", "--exit-code", "--", *checked_files),
            REPO_ROOT,
        )
    )
    return commands


def _project_version() -> str:
    with (REPO_ROOT / "pyproject.toml").open("rb") as f:
        data = tomllib.load(f)
    version = data["project"]["version"]
    if not isinstance(version, str):
        raise SystemExit("pyproject.toml project.version must be a string")
    return version


def check_owner_map() -> None:
    """Check the small declared owner table, not prose or whole-codebase coverage."""
    document = REPO_ROOT / OWNER_MAP
    _, heading, section = document.read_text(encoding="utf-8").partition(
        "## Code and documentation owners\n"
    )
    rows = [
        line.strip()
        for line in section.split("\n## ", 1)[0].splitlines()
        if line.lstrip().startswith("|")
    ]
    if not heading or len(rows) < 3 or not re.fullmatch(r"\|(?:\s*:?-+:?\s*\|){4}", rows[1]):
        raise SystemExit(f"{OWNER_MAP}: missing code/documentation owner table")
    for row in rows[2:]:
        cells = row.strip("|").split("|")
        if len(cells) != 4:
            raise SystemExit(f"{OWNER_MAP}: owner row must have four columns: {row}")
        for cell in cells[1:]:
            links = re.findall(r"\]\(([^)\s]+)\)", cell)
            if not links:
                raise SystemExit(
                    f"{OWNER_MAP}: missing code, guidance, or verification link: {row}"
                )
            for link in links:
                target = (document.parent / link.split("#", 1)[0]).resolve()
                if not target.is_relative_to(REPO_ROOT.resolve()) or not target.is_file():
                    raise SystemExit(f"{OWNER_MAP}: missing or non-repository owner path: {link}")
    print(f"owner map OK: {len(rows) - 2} declared surfaces (paths only)")


def check_release_surfaces() -> None:
    """Ensure public release surfaces point at this version."""
    version = _project_version()
    expected_heading = f"# GEODE v{version}"

    for rel_path in ("README.md", "README.ko.md"):
        text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        if expected_heading not in text:
            raise SystemExit(f"{rel_path} is not aligned to GEODE v{version}")
        if PUBLIC_IDENTITY not in text:
            raise SystemExit(f"{rel_path} is missing the canonical public identity")

    version_parts = version.split(".")
    if len(version_parts) < 2 or not all(part.isdigit() for part in version_parts[:2]):
        raise SystemExit(f"cannot derive supported release series from {version!r}")
    supported_series = f"{version_parts[0]}.{version_parts[1]}.x"
    security = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    supported_row = re.compile(
        rf"^\|\s*{re.escape(supported_series)}\s*\|\s*:white_check_mark:\s*\|\s*$",
        re.M,
    )
    if not supported_row.search(security):
        raise SystemExit(f"SECURITY.md does not mark {supported_series} as supported")

    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\].*?\n(?P<body>.*?)(?=^## \[)",
        re.M | re.S,
    )
    match = pattern.search(changelog)
    if not match:
        raise SystemExit(f"CHANGELOG.md is missing release section {version}")
    body = match.group("body")
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
    print("==> check code/documentation owner paths")
    check_owner_map()
    print("==> check release surfaces")
    check_release_surfaces()
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
    parser.add_argument(
        "--check-map",
        action="store_true",
        help="Only check declared code, documentation owner, and verification file links.",
    )
    args = parser.parse_args()
    if args.check_map:
        check_owner_map()
    else:
        run_docs_gate(build_docs_commands(skip_build=args.skip_build))


if __name__ == "__main__":
    main()
