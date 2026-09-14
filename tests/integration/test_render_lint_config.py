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

import fnmatch
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

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


def test_pages_build_runs_site_lint_after_install() -> None:
    data = yaml.safe_load(PAGES_WORKFLOW.read_text(encoding="utf-8"))
    build = data["jobs"]["build"]
    assert build["defaults"]["run"]["working-directory"] == "site"
    steps = build["steps"]
    commands = [step.get("run") for step in steps]
    assert (
        commands.index("npm ci") < commands.index("npm run lint") < commands.index("npm run build")
    )
    lint = steps[commands.index("npm run lint")]
    assert not lint.get("continue-on-error", False)
    assert "if" not in lint


@pytest.mark.parametrize(
    "path",
    [
        "docs/audits/2026-05-12-petri-geode-audit-v3.md",
        "docs/audits/2026-05-12-petri-insights.md",
        "docs/audits/2026-05-12-petri-multi-model-partial.md",
        "docs/self-improving/petri-bundle/README.md",
    ],
)
def test_caveat_files_exist(path: str) -> None:
    """The 4 caveat-bearing markdown files the lint gate protects must exist.

    If any of these are renamed or moved, the README cross-links in
    docs/self-improving/petri-bundle/README.md (which Pages serves verbatim) start
    404-ing — fix the README at the same time as the rename.
    """

    assert (REPO_ROOT / path).is_file(), f"missing {path}"


@pytest.mark.parametrize("missing_readme", [False, True])
def test_markdown_lint_invokes_public_targets_or_fails_before_lint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_readme: bool
) -> None:
    source = (REPO_ROOT / "scripts/lint_pages_markdown.sh").read_text(encoding="utf-8")
    targets = re.findall(r'^\s*"(docs/[^\"]+)"', source, re.M)
    readme = "docs/self-improving/petri-bundle/README.md"
    assert readme in targets
    for name in targets:
        if missing_readme and name == readme:
            continue
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    script = tmp_path / "scripts/lint_pages_markdown.sh"
    script.parent.mkdir()
    script.write_text(source, encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    linter = fake_bin / "pymarkdown"
    linter.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n', encoding="utf-8")
    linter.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:/usr/bin:/bin")
    # The script and linter are test-owned fixtures, never caller-supplied commands.
    result = subprocess.run(  # noqa: S603
        ["/bin/bash", str(script)], capture_output=True, text=True, check=False
    )
    if missing_readme:
        assert result.returncode == 1
        assert f"missing render-gated markdown: {readme}" in result.stderr
        assert not result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ["--config", ".pymarkdown.json", "scan", *targets]


def test_docs_only_owner_checks_do_not_enable_full_runtime_tests() -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    changes = jobs["changes"]
    filter_step = next(step for step in changes["steps"] if step.get("id") == "filter")
    filters = yaml.safe_load(filter_step["with"]["filters"])
    for path in (
        "CLAUDE.md",
        "docs/workflow.md",
        "docs/scaffold-skills.md",
        "docs/architecture/official-docs-generation.md",
    ):
        assert any(fnmatch.fnmatchcase(path, pattern) for pattern in filters["docs"])
        assert not any(fnmatch.fnmatchcase(path, pattern) for pattern in filters["code"])
    docs_step = next(
        step
        for step in jobs["lint"]["steps"]
        if step.get("name") == "Documentation owner paths and scaffold contracts"
    )
    assert docs_step["if"] == "needs.changes.outputs.docs == 'true'"
    assert "scripts/check_official_docs.py --check-map" in docs_step["run"]
    assert "tests/test_workflow_scaffold.py" in docs_step["run"]
    full_test = next(step for step in jobs["test"]["steps"] if "--cov=core" in step.get("run", ""))
    assert full_test["if"] == "needs.changes.outputs.code == 'true'"


def test_petri_bundle_json_parses() -> None:
    """listing.json is the entry point inspect_ai's viewer reads first."""

    listing = REPO_ROOT / "docs" / "self-improving/petri-bundle" / "logs" / "listing.json"
    assert listing.is_file(), f"missing {listing}"
    data = json.loads(listing.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data, "listing.json is empty — the petri-bundle viewer shows nothing"


def test_judge_dims_yaml_parses() -> None:
    """The judge_dim YAML loads via PyYAML (= the path plugin code uses)."""

    yaml_path = REPO_ROOT / "evals" / "petri" / "judge_dims" / "geode_judge_subset.yaml"
    assert yaml_path.is_file()
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert isinstance(data, list), "geode_judge_subset.yaml must parse as a list of dims"
    assert "broken_tool_use" in data, "broken_tool_use must be among the dims"
    assert "input_hallucination" in data, (
        "input_hallucination must be among the dims (caveat docs reference it)"
    )
