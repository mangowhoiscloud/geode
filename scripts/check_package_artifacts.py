"""Validate GEODE packaging artifact contents.

The wheel should contain only runtime code and runtime package data. The sdist
should contain source plus a small release-facing documentation set, not the
full docs/site/archive tree.
"""

from __future__ import annotations

import argparse
import re
import stat
import sys
import tarfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_WHEEL_PATHS = {
    "core/tools/definitions.json",
    "core/tools/mcp_tools.json",
    "core/config/routing.toml",
    "core/llm/model_pricing.toml",
    "core/llm/prompts/router.md",
    "core/llm/prompts/decomposer.md",
    "plugins/petri_audit/petri.plugin.toml",
    "plugins/petri_audit/roles/auditor.md",
    "plugins/petri_audit/roles/target.md",
    "plugins/petri_audit/roles/judge.md",
    "plugins/petri_audit/judge_dims/geode_judge_subset.yaml",
    "plugins/petri_audit/seeds/calibration_false_refusal_drift.md",
}

REQUIRED_SDIST_PATHS = {
    "pyproject.toml",
    "README.md",
    "README.ko.md",
    "CHANGELOG.md",
    "LICENSE",
    "NOTICE",
    "core/__init__.py",
    "plugins/__init__.py",
    "plugins/petri_audit/__init__.py",
}

BANNED_COMMON_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".import_linter_cache",
    ".DS_Store",
}

BANNED_WHEEL_PREFIXES = (
    ".claude/",
    ".geode/",
    ".github/",
    "docs/",
    "site/",
    "tests/",
    "experimental/",
    "autoresearch/",
    "scripts/",
)

BANNED_SDIST_PREFIXES = (
    ".claude/",
    ".geode/",
    ".github/",
    "dist/",
    "docs/",
    "site/",
    "tests/",
    "experimental/",
    "autoresearch/",
    "scripts/",
    "docs/audits/",
    "docs/blog/",
    "docs/diagrams/",
    "docs/e2e/",
    "docs/eval/",
    "docs/petri-bundle/",
    "docs/plans/",
    "docs/research/",
    "docs/superpowers/",
)


def _project_version() -> str:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    if not match:
        raise SystemExit("pyproject.toml project.version is missing")
    return match.group(1)


def _strip_sdist_root(path: str) -> str:
    parts = path.split("/", 1)
    if len(parts) == 1:
        return ""
    return parts[1]


def _read_wheel(path: Path) -> tuple[set[str], list[str]]:
    symlinks: list[str] = []
    with zipfile.ZipFile(path) as zf:
        paths = {name for name in zf.namelist() if name and not name.endswith("/")}
        for info in zf.infolist():
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_IFMT(mode) == stat.S_IFLNK:
                symlinks.append(info.filename)
    return paths, symlinks


def _read_sdist(path: Path) -> tuple[set[str], list[str]]:
    symlinks: list[str] = []
    with tarfile.open(path, "r:gz") as tf:
        paths: set[str] = set()
        for member in tf.getmembers():
            stripped = _strip_sdist_root(member.name)
            if not stripped:
                continue
            if member.issym() or member.islnk():
                symlinks.append(stripped)
            if member.isfile():
                paths.add(stripped)
    return paths, symlinks


def _find_artifacts(dist_dir: Path, version: str) -> tuple[Path, Path]:
    normalized = version.replace("-", "_")
    wheel = dist_dir / f"geode_agent-{normalized}-py3-none-any.whl"
    sdist = dist_dir / f"geode_agent-{version}.tar.gz"
    missing = [str(path) for path in (wheel, sdist) if not path.exists()]
    if missing:
        raise SystemExit("missing package artifact(s): " + ", ".join(missing))
    return wheel, sdist


def _has_banned_common(path: str) -> bool:
    parts = set(path.split("/"))
    return bool(parts & BANNED_COMMON_PARTS) or path.endswith((".pyc", ".pyo"))


def _check_required(label: str, paths: set[str], required: set[str]) -> list[str]:
    return [f"{label}: missing required path {path}" for path in sorted(required - paths)]


def _check_banned(label: str, paths: set[str], prefixes: tuple[str, ...]) -> list[str]:
    problems: list[str] = []
    for path in sorted(paths):
        if _has_banned_common(path):
            problems.append(f"{label}: banned cache/generated path {path}")
            continue
        if path.startswith(prefixes):
            problems.append(f"{label}: banned path {path}")
    return problems


def validate(dist_dir: Path) -> None:
    wheel_path, sdist_path = _find_artifacts(dist_dir, _project_version())
    wheel_paths, wheel_symlinks = _read_wheel(wheel_path)
    sdist_paths, sdist_symlinks = _read_sdist(sdist_path)

    problems: list[str] = []
    problems.extend(_check_required("wheel", wheel_paths, REQUIRED_WHEEL_PATHS))
    problems.extend(_check_required("sdist", sdist_paths, REQUIRED_SDIST_PATHS))
    problems.extend(_check_banned("wheel", wheel_paths, BANNED_WHEEL_PREFIXES))
    problems.extend(_check_banned("sdist", sdist_paths, BANNED_SDIST_PREFIXES))
    problems.extend(f"wheel: symlink is not allowed: {path}" for path in wheel_symlinks)
    problems.extend(f"sdist: symlink is not allowed: {path}" for path in sdist_symlinks)

    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        raise SystemExit(1)

    print(f"wheel OK: {wheel_path.name} ({len(wheel_paths)} files)")
    print(f"sdist OK: {sdist_path.name} ({len(sdist_paths)} files)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=REPO_ROOT / "dist",
        help="Directory containing geode_agent wheel and sdist artifacts.",
    )
    args = parser.parse_args()
    validate(args.dist_dir)


if __name__ == "__main__":
    main()
