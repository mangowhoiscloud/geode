"""Validate the immutable GEODE product distribution contents.

The wheel contains product code and read-only package data. The sdist contains
source plus a small release-facing documentation set, not mutable experiment
state or the full docs/site/archive tree.
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

SELF_IMPROVING_RUNTIME_PATHS = {
    "evals/config.py",
    "evals/run_timeline.py",
    "evolve/scaffold_search/__init__.py",
    "evolve/scaffold_search/campaign.py",
    "evolve/scaffold_search/cli_commands.py",
    "evolve/scaffold_search/loop/mutate/runner.py",
    "evolve/scaffold_search/mcp.py",
    "evolve/scaffold_search/mcp_tools.json",
    "evolve/scaffold_search/outer_bundle.py",
    "evolve/scaffold_search/program.md",
    "evolve/scaffold_search/train.py",
}

SELF_IMPROVING_STATIC_PATHS = {
    "evolve/scaffold_search/state/README.md",
    "evolve/scaffold_search/state/policies/hyperparam.json",
}

MUTABLE_STATE_PATHS = {
    "evolve/scaffold_search/state/baseline_archive.jsonl",
    "evolve/scaffold_search/state/baseline_epochs.json",
    "evolve/scaffold_search/state/mutations.jsonl",
    "evolve/scaffold_search/state/results.jsonl",
    "evolve/scaffold_search/state/results.tsv",
}

BUNDLED_SKILL_PATHS = {
    ".geode/skills/arxiv-digest/SKILL.md",
    ".geode/skills/deep-researcher/SKILL.md",
    ".geode/skills/frontier-ui-ux-catalog/SKILL.md",
    ".geode/skills/frontier-ui-ux-catalog/reference.md",
    ".geode/skills/geo/SKILL.md",
    ".geode/skills/geode-context/SKILL.md",
    ".geode/skills/grilling/SKILL.md",
    ".geode/skills/long-task-watcher/SKILL.md",
    ".geode/skills/pdf/LICENSE.txt",
    ".geode/skills/pdf/SKILL.md",
    ".geode/skills/pdf/forms.md",
    ".geode/skills/pdf/reference.md",
    ".geode/skills/pdf/scripts/check_bounding_boxes.py",
    ".geode/skills/pdf/scripts/check_bounding_boxes_test.py",
    ".geode/skills/pdf/scripts/check_fillable_fields.py",
    ".geode/skills/pdf/scripts/convert_pdf_to_images.py",
    ".geode/skills/pdf/scripts/create_validation_image.py",
    ".geode/skills/pdf/scripts/extract_form_field_info.py",
    ".geode/skills/pdf/scripts/fill_fillable_fields.py",
    ".geode/skills/pdf/scripts/fill_pdf_form_with_annotations.py",
}

REQUIRED_WHEEL_PATHS = (
    {
        "core/GEODE.md",
        "core/worker.py",
        "core/tools/definitions.json",
        "core/tools/mcp_tools.json",
        "core/config/routing.toml",
        "core/llm/model_pricing.toml",
        "core/llm/prompts/router.md",
        "core/llm/prompts/reviewer.md",
        "evals/__init__.py",
        "evals/cli.py",
        "evals/worker.py",
        "evals/benchmarks/benchmark_harness.plugin.toml",
        "evals/benchmarks/tau2/agent_policy.md",
        "evals/benchmarks/mcpmark/patches/mcpmark-cd45b7f-filesystem-standard-verifier-missing-output.patch",
        "evals/petri/petri.plugin.toml",
        "evals/petri/roles/auditor.md",
        "evals/petri/roles/target.md",
        "evals/petri/roles/judge.md",
        "evals/petri/judge_dims/geode_judge_subset.yaml",
        "evals/petri/seeds/auxiliary/overrefusal/01_base.md",
        "evals/seed_generation/seed_generation.plugin.toml",
        "evals/seed_generation/agents/generator.md",
        "evals/seed_generation/agents/critic.md",
        "evals/seed_generation/agents/proximity.md",
        "evals/seed_generation/agents/ranker.md",
        "evals/seed_generation/agents/evolver.md",
        "evals/seed_generation/agents/meta_reviewer.md",
        "evals/seed_generation/agents/supervisor.md",
        "evals/seed_generation/agents/literature_review.md",
        "evolve/__init__.py",
        "evolve/cli.py",
    }
    | SELF_IMPROVING_RUNTIME_PATHS
    | SELF_IMPROVING_STATIC_PATHS
    | BUNDLED_SKILL_PATHS
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
        "core/worker.py",
        "evals/__init__.py",
        "evals/worker.py",
        "evolve/__init__.py",
    }
    | SELF_IMPROVING_RUNTIME_PATHS
    | SELF_IMPROVING_STATIC_PATHS
    | BUNDLED_SKILL_PATHS
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


def _check_mutable_state(label: str, paths: set[str]) -> list[str]:
    return [
        f"{label}: mutable experiment state is packaged: {path}"
        for path in sorted(paths & MUTABLE_STATE_PATHS)
    ]


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
        if (
            path.startswith(prefixes)
            and not path.startswith(ALLOWED_PREFIXES)
            and path not in BUNDLED_SKILL_PATHS
        ):
            problems.append(f"{label}: banned path {path}")
    return problems


def _check_removed_compatibility_layout(label: str, paths: set[str]) -> list[str]:
    removed_paths = {
        path
        for path in paths
        if path.startswith(
            ("geode_product/", "plugins/", "core/self_improving/")  # slop:keep
        )
    }
    problems = [
        f"{label}: removed compatibility path is packaged: {path}" for path in sorted(removed_paths)
    ]
    return problems


def validate(dist_dir: Path) -> None:
    wheel_path, sdist_path = _find_artifacts(dist_dir, _project_version())
    wheel_paths, wheel_symlinks = _read_wheel(wheel_path)
    sdist_paths, sdist_symlinks = _read_sdist(sdist_path)

    problems: list[str] = []
    problems.extend(_check_required("wheel", wheel_paths, REQUIRED_WHEEL_PATHS))
    problems.extend(_check_required("sdist", sdist_paths, REQUIRED_SDIST_PATHS))
    problems.extend(_check_mutable_state("wheel", wheel_paths))
    problems.extend(_check_mutable_state("sdist", sdist_paths))
    problems.extend(_check_banned("wheel", wheel_paths, BANNED_WHEEL_PREFIXES))
    problems.extend(_check_banned("sdist", sdist_paths, BANNED_SDIST_PREFIXES))
    problems.extend(_check_removed_compatibility_layout("wheel", wheel_paths))
    problems.extend(_check_removed_compatibility_layout("sdist", sdist_paths))
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
