from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/release.yml"
PORTFOLIO_PATH = REPO_ROOT / "site/src/app/portfolio/page.tsx"
DISTRIBUTION_SKILL_PATH = REPO_ROOT / ".claude/skills/geode-distribution/SKILL.md"
RELEASE_DOC_PATH = REPO_ROOT / "site/src/app/docs/ops/release-pypi-lifecycle/page.tsx"
HOMEBREW_GUIDE_PATH = REPO_ROOT / "packaging/homebrew/README.md"


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


def test_stable_release_has_no_custom_homebrew_tap_channel() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert "publish-homebrew" not in jobs

    verify = jobs["verify-stable-distribution"]
    assert isinstance(verify, dict)
    assert verify["needs"] == ["validate-build", "publish-github-release", "verify-pypi"]

    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "HOMEBREW_TAP_DEPLOY_KEY" not in text
    assert "homebrew-tap" not in text
    assert "mangowhoiscloud/tap" not in text


def test_public_distribution_uses_the_reusable_exact_version_verifier() -> None:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)
    verify_pypi = jobs["verify-pypi"]
    verify = jobs["verify-stable-distribution"]
    assert isinstance(verify_pypi, dict)
    assert isinstance(verify, dict)
    pypi_steps = verify_pypi["steps"]
    steps = verify["steps"]
    assert isinstance(pypi_steps, list)
    assert isinstance(steps, list)

    pypi_step_text = "\n".join(
        str(step.get("run", "")) for step in pypi_steps if isinstance(step, dict)
    )
    assert "for attempt in $(seq 1 12)" in pypi_step_text
    assert "pypi.org/pypi" not in pypi_step_text
    assert not any(
        isinstance(step, dict) and "download-artifact" in str(step.get("uses", ""))
        for step in pypi_steps
    )
    assert any(
        isinstance(step, dict)
        and "setup-uv" in str(step.get("uses", ""))
        and step.get("with") == {"enable-cache": False}
        for step in pypi_steps
    )
    assert any(
        isinstance(step, dict) and str(step.get("uses", "")).startswith("actions/checkout@")
        for step in steps
    )
    assert any(
        isinstance(step, dict)
        and "python scripts/verify_public_distribution.py" in str(step.get("run", ""))
        for step in steps
    )
    assert "line.decode().split(maxsplit=1)" not in WORKFLOW_PATH.read_text(encoding="utf-8")


def test_current_distribution_surfaces_do_not_restore_the_deleted_tap() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            WORKFLOW_PATH,
            PORTFOLIO_PATH,
            DISTRIBUTION_SKILL_PATH,
            RELEASE_DOC_PATH,
            HOMEBREW_GUIDE_PATH,
        )
    )

    assert "mangowhoiscloud/homebrew-tap" not in text
    assert "mangowhoiscloud/tap" not in text
    assert "HOMEBREW_TAP_DEPLOY_KEY" not in text
    assert "publish-homebrew" not in text


def test_release_retry_preserves_release_body_bytes() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "SOURCE_DATE_EPOCH=$(git show -s --format=%ct HEAD)" in text
    assert "--json body > published-release/release.json" in text
    assert 'payload["body"]' in text
    assert "--jq .body > published-release/release-notes.md" not in text


def test_public_install_commands_use_the_stable_pypi_channel() -> None:
    text = PORTFOLIO_PATH.read_text(encoding="utf-8")
    release_doc = RELEASE_DOC_PATH.read_text(encoding="utf-8")

    assert "brew install" not in text
    assert "brew install geode-agent" not in release_doc
    assert "mangowhoiscloud/tap" not in text
    assert 'useState("uv-tool")' in text
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
