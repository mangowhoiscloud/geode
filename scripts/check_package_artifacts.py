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

SELF_IMPROVING_FACADES = {
    "core/self_improving/__init__.py",
    "core/self_improving/campaign.py",
    "core/self_improving/prepare.py",
    "core/self_improving/train.py",
    "core/self_improving/watch_campaign.py",
}

SELF_IMPROVING_RUNTIME_PATHS = {
    "geode_product/self_improving/__init__.py",
    "geode_product/self_improving/campaign.py",
    "geode_product/self_improving/cli_commands.py",
    "geode_product/self_improving/config.py",
    "geode_product/self_improving/loop/mutate/runner.py",
    "geode_product/self_improving/loop/observe/run_timeline.py",
    "geode_product/self_improving/mcp.py",
    "geode_product/self_improving/mcp_tools.json",
    "geode_product/self_improving/outer_bundle.py",
    "geode_product/self_improving/program.md",
    "geode_product/self_improving/train.py",
}

SELF_IMPROVING_STATE_PATHS = {
    "core/self_improving/state/README.md",
    "core/self_improving/state/baseline_archive.jsonl",
    "core/self_improving/state/baseline_epochs.json",
    "core/self_improving/state/mutations.jsonl",
    "core/self_improving/state/policies/hyperparam.json",
    "core/self_improving/state/results.jsonl",
    "core/self_improving/state/results.tsv",
}

REQUIRED_WHEEL_PATHS = (
    {
        "core/GEODE.md",
        "core/tools/definitions.json",
        "core/tools/mcp_tools.json",
        "core/config/routing.toml",
        "core/llm/model_pricing.toml",
        "core/llm/prompts/router.md",
        "geode_product/benchmark_harness/benchmark_harness.plugin.toml",
        "geode_product/benchmark_harness/tau2_agent_policy.md",
        "geode_product/benchmark_harness/patches/mcpmark-cd45b7f-filesystem-standard-verifier-missing-output.patch",
        "geode_product/petri_audit/petri.plugin.toml",
        "geode_product/petri_audit/roles/auditor.md",
        "geode_product/petri_audit/roles/target.md",
        "geode_product/petri_audit/roles/judge.md",
        "geode_product/petri_audit/judge_dims/geode_judge_subset.yaml",
        "geode_product/petri_audit/seeds/auxiliary/overrefusal/01_base.md",
        "geode_product/seed_generation/seed_generation.plugin.toml",
        "geode_product/seed_generation/agents/generator.md",
        "geode_product/seed_generation/agents/critic.md",
        "geode_product/seed_generation/agents/proximity.md",
        "geode_product/seed_generation/agents/ranker.md",
        "geode_product/seed_generation/agents/evolver.md",
        "geode_product/seed_generation/agents/meta_reviewer.md",
        "geode_product/seed_generation/agents/supervisor.md",
        "geode_product/seed_generation/agents/literature_review.md",
        "plugins/petri_audit/__init__.py",
        "plugins/benchmark_harness/mcpmark_geode_agent.py",
    }
    | SELF_IMPROVING_FACADES
    | SELF_IMPROVING_RUNTIME_PATHS
    | SELF_IMPROVING_STATE_PATHS
)

REQUIRED_SDIST_PATHS = (
    {
        "GEODE.md",
        "pyproject.toml",
        "README.md",
        "README.ko.md",
        "CHANGELOG.md",
        "LICENSE",
        "NOTICE",
        "core/__init__.py",
        "geode_product/__init__.py",
        "plugins/__init__.py",
        "plugins/petri_audit/__init__.py",
    }
    | SELF_IMPROVING_FACADES
    | SELF_IMPROVING_RUNTIME_PATHS
    | SELF_IMPROVING_STATE_PATHS
)

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
    "docs/self-improving/petri-bundle/",
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


# ``scripts/macos/`` ships on purpose (computer-use helper source + build
# script; consumed at runtime by core/cli/onboarding.py and doctor), so the
# blanket ``scripts/`` ban carves it out.
ALLOWED_PREFIXES = ("scripts/macos/",)


def _check_banned(label: str, paths: set[str], prefixes: tuple[str, ...]) -> list[str]:
    problems: list[str] = []
    for path in sorted(paths):
        if _has_banned_common(path):
            problems.append(f"{label}: banned cache/generated path {path}")
            continue
        if path.startswith(prefixes) and not path.startswith(ALLOWED_PREFIXES):
            problems.append(f"{label}: banned path {path}")
    return problems


def _check_self_improving_layout(label: str, paths: set[str]) -> list[str]:
    legacy_python = {
        path
        for path in paths
        if path.startswith("core/self_improving/")
        and path.endswith(".py")
        and not path.startswith("core/self_improving/state/")
    }
    problems = [
        f"{label}: unexpected legacy self-improving module {path}"
        for path in sorted(legacy_python - SELF_IMPROVING_FACADES)
    ]
    problems.extend(
        f"{label}: self-improving state duplicated under product package: {path}"
        for path in sorted(paths)
        if path.startswith("geode_product/self_improving/state/")
    )
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
    problems.extend(_check_self_improving_layout("wheel", wheel_paths))
    problems.extend(_check_self_improving_layout("sdist", sdist_paths))
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
