"""Contract checks for .github/workflows/publication-bundle.yml."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/publication-bundle.yml"


def _workflow() -> dict[Any, Any]:
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _publish_script() -> str:
    steps = _workflow()["jobs"]["publish"]["steps"]
    scripts = [step["run"] for step in steps if "run" in step]
    assert len(scripts) == 1
    return scripts[0]


def test_triggers_are_main_pushes_and_manual_dispatch_only() -> None:
    # PyYAML reads the bare ``on`` key as boolean True.
    assert _workflow()[True] == {"push": {"branches": ["main"]}, "workflow_dispatch": None}


def test_only_the_publish_job_can_write_and_runs_serialize() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]

    assert workflow["permissions"] == {"contents": "read"}
    assert "permissions" not in jobs["build"]
    assert jobs["publish"]["permissions"] == {"contents": "write"}
    assert workflow["concurrency"] == {"group": "publication-bundle", "cancel-in-progress": False}
    publish_uses = [step["uses"] for step in jobs["publish"]["steps"] if "uses" in step]
    assert [use.split("@")[0] for use in publish_uses] == ["actions/download-artifact"]


def test_build_uses_full_history_without_persisted_credentials() -> None:
    checkout = _workflow()["jobs"]["build"]["steps"][0]

    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"] == {"fetch-depth": 0, "persist-credentials": False}


def test_release_stays_out_of_the_version_and_latest_namespaces() -> None:
    workflow = _workflow()
    script = _publish_script()

    assert workflow["env"]["RELEASE_TAG"] == "publication"
    assert "--prerelease" in script
    assert "--latest=false" in script
    assert 'test "$(gh release view "$RELEASE_TAG"' in script


def test_archive_is_public_before_the_pointer_moves_and_unchanged_trees_skip() -> None:
    script = _publish_script()

    skip = script.index('if [ "$current_tree" = "$tree" ]')
    upload = script.index('gh release upload "$RELEASE_TAG" "$file"')
    verify = script.index('test "$downloaded" = "$sha"')
    swap = script.index("-f name=manifest.json >/dev/null")
    prune = script.index("KEEP_BUNDLES + 1")
    assert skip < upload < verify < swap < prune


def test_run_blocks_parse_as_bash() -> None:
    for job in _workflow()["jobs"].values():
        for step in job["steps"]:
            if "run" not in step:
                continue
            result = subprocess.run(
                ["/bin/bash", "-n"], input=step["run"], text=True, capture_output=True, check=False
            )
            assert result.returncode == 0, result.stderr
