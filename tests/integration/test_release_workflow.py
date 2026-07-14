from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/release.yml"
PORTFOLIO_PATH = REPO_ROOT / "site/src/app/portfolio/page.tsx"


def _workflow() -> dict[str, object]:
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_release_actions_are_pinned_to_immutable_commits() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)

    uses: list[str] = []
    for job in jobs.values():
        assert isinstance(job, dict)
        for step in job.get("steps", []):
            if isinstance(step, dict) and isinstance(step.get("uses"), str):
                uses.append(step["uses"])

    assert uses
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", value) for value in uses)


def test_release_run_blocks_parse_as_bash() -> None:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)

    for job_name, job in jobs.items():
        assert isinstance(job, dict)
        for index, step in enumerate(job.get("steps", [])):
            if not isinstance(step, dict) or not isinstance(step.get("run"), str):
                continue
            result = subprocess.run(
                ["/bin/bash", "-n"],
                input=step["run"],
                text=True,
                capture_output=True,
                check=False,
            )
            label = step.get("name", f"step {index}")
            assert result.returncode == 0, (
                f"{job_name} / {label} is not valid Bash:\n{result.stderr}"
            )


def test_pypi_oidc_is_isolated_from_public_verification() -> None:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)
    publish = jobs["publish-pypi"]
    verify = jobs["verify-pypi"]
    assert isinstance(publish, dict)
    assert isinstance(verify, dict)

    assert publish["permissions"] == {"contents": "read", "id-token": "write"}
    assert verify["permissions"] == {"contents": "read"}
    assert all(
        "setup-uv" not in str(step.get("uses", ""))
        for step in publish["steps"]
        if isinstance(step, dict)
    )


def test_homebrew_publish_uses_scoped_key_and_retry_guards() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "HOMEBREW_TAP_TOKEN" not in text
    assert "HOMEBREW_TAP_DEPLOY_KEY" in text
    assert "--ignore-main-package-cooldown" in text
    assert text.count("--template geode/packaging/homebrew/geode.rb.in") == 3
    assert "git pull --rebase" not in text
    assert "steps.tap-base.outputs.sha" in text
    assert "skip-existing: true" in text


def test_release_retry_preserves_release_body_bytes() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "SOURCE_DATE_EPOCH=$(git show -s --format=%ct HEAD)" in text
    assert "--json body > published-release/release.json" in text
    assert 'payload["body"]' in text
    assert "--jq .body > published-release/release-notes.md" not in text


def test_public_uv_commands_use_the_stable_pypi_channel() -> None:
    text = PORTFOLIO_PATH.read_text(encoding="utf-8")

    assert 'copy: "uv tool install geode-agent"' in text
    assert 'copy: "uvx --from geode-agent geode"' in text
    assert "GEODE_GIT_SOURCE" not in text


def test_published_metadata_has_no_direct_dependencies() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]

    dependencies = list(project["dependencies"])
    for extra in project["optional-dependencies"].values():
        dependencies.extend(extra)
    assert not [dependency for dependency in dependencies if " @ " in dependency]
