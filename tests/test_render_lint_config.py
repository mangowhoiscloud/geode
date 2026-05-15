"""Render-lint config integrity tests.

The Pages publish workflow (`.github/workflows/pages.yml`) gates the
deploy on a render-lint job that uses three config files at repo
root: ``.pymarkdown.json`` (markdown), ``.yamllint.yaml`` (YAML), and
``.pre-commit-config.yaml`` (mirror for local runs). If any of those
go missing or stop parsing, the gate silently degrades to a no-op and
malformed markdown can ship to GitHub Pages. Catch that here so a CI
ratchet fails on the regression.

This test deliberately does **not** invoke the linters themselves —
those run in pre-commit and the Pages workflow. Re-running them here
would double the wall time on every push without catching anything
the workflow does not already catch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

PYMARKDOWN_CONFIG = REPO_ROOT / ".pymarkdown.json"
YAMLLINT_CONFIG = REPO_ROOT / ".yamllint.yaml"
PRECOMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
PAGES_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pages.yml"


def test_pymarkdown_config_exists_and_parses() -> None:
    """The markdown render-lint config must be valid JSON."""

    assert PYMARKDOWN_CONFIG.is_file(), (
        f"missing {PYMARKDOWN_CONFIG} — Pages publish lint gate will degrade to a no-op without it"
    )
    data = json.loads(PYMARKDOWN_CONFIG.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "plugins" in data, "pymarkdown config missing 'plugins' section"


def test_pymarkdown_disables_line_length_rule() -> None:
    """MD013 (line-length) must stay off — Korean essays go long."""

    data = json.loads(PYMARKDOWN_CONFIG.read_text(encoding="utf-8"))
    md013 = data.get("plugins", {}).get("md013", {})
    assert md013.get("enabled") is False, (
        "MD013 line-length must be disabled; Korean engineer-essay docs "
        "cannot satisfy an 80-column hard limit without rewording content"
    )


def test_yamllint_config_exists_and_parses() -> None:
    """The YAML render-lint config must be parseable YAML."""

    assert YAMLLINT_CONFIG.is_file(), f"missing {YAMLLINT_CONFIG}"
    data = yaml.safe_load(YAMLLINT_CONFIG.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    # yamllint requires either `extends:` or explicit `rules:`.
    assert "extends" in data or "rules" in data


def test_precommit_wires_render_lint_hooks() -> None:
    """Pre-commit must wire yamllint + pymarkdown so local runs match CI."""

    text = PRECOMMIT_CONFIG.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    repos = {entry["repo"] for entry in data.get("repos", [])}
    assert "https://github.com/adrienverge/yamllint" in repos, (
        "pre-commit must include the yamllint repo so local commits "
        "catch the same YAML issues the Pages workflow catches"
    )
    # The pymarkdown hook is wired as a local script-based hook so the
    # allowlist (scripts/lint_pages_markdown.sh) stays in one place.
    hook_ids: list[str] = []
    for entry in data.get("repos", []):
        for hook in entry.get("hooks", []):
            hook_ids.append(hook.get("id", ""))
    assert "pymarkdown-pages" in hook_ids, (
        "pre-commit must expose the pymarkdown-pages hook so local "
        "commits catch the same markdown issues the Pages workflow does"
    )


def test_lint_script_exists_and_executable() -> None:
    """The script that drives the render-lint hook must exist."""

    script = REPO_ROOT / "scripts" / "lint_pages_markdown.sh"
    assert script.is_file(), f"missing {script}"
    # Executable bit: pre-commit invokes via `entry: scripts/...sh`,
    # which fails silently if the file is not chmod +x. The bit is
    # tracked in git so the assertion guards against drift.
    import os

    assert os.access(script, os.X_OK), f"{script} must be executable"


def test_pages_workflow_has_lint_gate() -> None:
    """Pages workflow must run lint before build, and build must depend on it."""

    data = yaml.safe_load(PAGES_WORKFLOW.read_text(encoding="utf-8"))
    jobs = data.get("jobs", {})
    assert "lint" in jobs, (
        ".github/workflows/pages.yml must define a 'lint' job — "
        "without it the Pages publish has no render gate"
    )
    build = jobs.get("build", {})
    needs = build.get("needs")
    needs_set = {needs} if isinstance(needs, str) else set(needs or [])
    assert "lint" in needs_set, (
        "build job must declare needs: [lint] so the lint gate actually blocks the deploy"
    )


@pytest.mark.parametrize(
    "path",
    [
        "docs/audits/2026-05-12-petri-geode-audit-v3.md",
        "docs/audits/2026-05-12-petri-insights.md",
        "docs/audits/2026-05-12-petri-multi-model-partial.md",
        "docs/petri-bundle/README.md",
    ],
)
def test_caveat_files_exist(path: str) -> None:
    """The 4 caveat-bearing markdown files the lint gate protects must exist.

    If any of these are renamed or moved, the README cross-links in
    docs/petri-bundle/README.md (which Pages serves verbatim) start
    404-ing — fix the README at the same time as the rename.
    """

    assert (REPO_ROOT / path).is_file(), f"missing {path}"


def test_petri_bundle_json_parses() -> None:
    """listing.json is the entry point inspect_ai's viewer reads first."""

    listing = REPO_ROOT / "docs" / "petri-bundle" / "logs" / "listing.json"
    assert listing.is_file(), f"missing {listing}"
    data = json.loads(listing.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data, "listing.json is empty — the petri-bundle viewer shows nothing"


def test_judge_dims_yaml_parses() -> None:
    """The judge_dim YAML loads via PyYAML (= the path plugin code uses)."""

    yaml_path = REPO_ROOT / "plugins" / "petri_audit" / "judge_dims" / "geode_5axes.yaml"
    assert yaml_path.is_file()
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert isinstance(data, list), "geode_5axes.yaml must parse as a list of dims"
    assert "broken_tool_use" in data, "broken_tool_use must be among the dims"
    assert "input_hallucination" in data, (
        "input_hallucination must be among the dims (caveat docs reference it)"
    )
