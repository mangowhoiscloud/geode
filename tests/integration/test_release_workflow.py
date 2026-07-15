from __future__ import annotations

import os
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
    assert "brew update-python-resources --help" in text
    assert "--ignore-main-package-cooldown" in text
    assert 'brew trust --formula "$tap_name/geode"' in text
    assert 'cp tap/Formula/geode.rb "$tap_formula"' in text
    assert text.count("--template geode/packaging/homebrew/geode.rb.in") == 3
    assert "git pull --rebase" not in text
    assert "steps.tap-base.outputs.sha" in text
    assert "skip-existing: true" in text


def test_homebrew_resource_refresh_uses_local_tap_and_adapts_cli(
    tmp_path: Path,
) -> None:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)
    publish = jobs["publish-homebrew"]
    assert isinstance(publish, dict)
    steps = publish["steps"]
    assert isinstance(steps, list)
    run = next(
        step["run"]
        for step in steps
        if isinstance(step, dict)
        and step.get("name") == "Refresh pinned Python resources from the published PyPI package"
    )
    assert isinstance(run, str)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    checkout_formula = tmp_path / "tap" / "Formula" / "geode.rb"
    checkout_formula.parent.mkdir(parents=True)
    tap_repo = tmp_path / "homebrew-tap"
    (tap_repo / "Formula").mkdir(parents=True)
    brew = bin_dir / "brew"
    brew.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "tap" ]]; then
  printf '%s\\n' "$@" > "$BREW_TAP_CAPTURE"
  exit 0
fi
if [[ "${1:-}" == "trust" && "${2:-}" == "--help" ]]; then
  exit 0
fi
if [[ "${1:-}" == "trust" ]]; then
  printf '%s\\n' "$@" > "$BREW_TRUST_CAPTURE"
  exit 0
fi
if [[ "${1:-}" == "--repo" ]]; then
  [[ "${2:-}" == "mangowhoiscloud/tap" ]]
  printf '%s\\n' "$BREW_TAP_REPO"
  exit 0
fi
if [[ "${1:-}" == "update-python-resources" && "${2:-}" == "--help" ]]; then
  printf '%s\\n' "${BREW_HELP_TEXT:-}"
  exit 0
fi
printf '%s\\n' "$@" > "$BREW_CAPTURE"
cp "$BREW_TAP_REPO/Formula/geode.rb" "$BREW_SEED_CAPTURE"
printf 'updated formula\\n' > "$BREW_TAP_REPO/Formula/geode.rb"
""",
        encoding="utf-8",
    )
    brew.chmod(0o755)

    cases: tuple[tuple[str, str, list[str]], ...] = (
        (
            "legacy",
            "",
            ["update-python-resources", "mangowhoiscloud/tap/geode"],
        ),
        (
            "cooldown",
            "--ignore-main-package-cooldown",
            [
                "update-python-resources",
                "mangowhoiscloud/tap/geode",
                "--package-name",
                "geode-agent",
                "--version",
                "0.99.330",
                "--ignore-main-package-cooldown",
            ],
        ),
    )
    for label, help_text, expected_args in cases:
        capture = tmp_path / f"{label}.args"
        tap_capture = tmp_path / f"{label}.tap"
        trust_capture = tmp_path / f"{label}.trust"
        seed_capture = tmp_path / f"{label}.seed"
        checkout_formula.write_text("checkout formula\n", encoding="utf-8")
        (tap_repo / "Formula" / "geode.rb").write_text(
            "tapped formula\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.update(
            {
                "BREW_CAPTURE": str(capture),
                "BREW_HELP_TEXT": help_text,
                "BREW_SEED_CAPTURE": str(seed_capture),
                "BREW_TAP_CAPTURE": str(tap_capture),
                "BREW_TAP_REPO": str(tap_repo),
                "BREW_TRUST_CAPTURE": str(trust_capture),
                "GEODE_VERSION": "0.99.330",
                "PATH": f"{bin_dir}:{env['PATH']}",
            }
        )
        result = subprocess.run(
            ["/bin/bash", "-e"],
            input=run,
            text=True,
            capture_output=True,
            check=False,
            cwd=tmp_path,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        assert capture.read_text(encoding="utf-8").splitlines() == expected_args
        assert tap_capture.read_text(encoding="utf-8").splitlines() == [
            "tap",
            "mangowhoiscloud/tap",
            str(tmp_path / "tap"),
        ]
        assert trust_capture.read_text(encoding="utf-8").splitlines() == [
            "trust",
            "--formula",
            "mangowhoiscloud/tap/geode",
        ]
        assert seed_capture.read_text(encoding="utf-8") == "checkout formula\n"
        assert checkout_formula.read_text(encoding="utf-8") == "updated formula\n"


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
