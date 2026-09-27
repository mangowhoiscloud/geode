"""Reviewed public trajectory projection and exact-merge read-back."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from core.observability.trajectory_release import verify_trajectory_release
from scripts.eval import harbor_publication

from tests.scripts.handoff_phase_fixture import INVALID_TRIAL, build_phase

PUBLISHED_AT = "2026-09-26T09:00:00Z"
REVIEW = {
    "reviewer": "GEODE data owner (fixture)",
    "reviewed_at": PUBLISHED_AT,
    "method": "digest allowlist review plus secret and identity scan",
    "scope": "geode-jev-noul-natural-20260926-fixture",
    "attestation": "Only digest-projected fixture events are admitted.",
    "license_status": "Authored synthetic fixture",
}
_GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
}


def _project(tmp_path: Path, phase: Path, trials: list[str]) -> dict[str, Any]:
    return harbor_publication.project_phase(
        phase,
        trials,
        privacy_review=REVIEW,
        destination=tmp_path / "stage" / "trajectories",
        release_source="geode-jev",
        published_at=PUBLISHED_AT,
        receipt_path=tmp_path / "projection-receipt.json",
    )


def _trials(phase: Path) -> list[str]:
    return sorted(path.name for path in (phase / "trials").iterdir())


def test_projection_marks_reviewed_digest_copies_and_excludes_with_reason(tmp_path: Path) -> None:
    phase = build_phase(tmp_path / "run")["phase_dir"]
    receipt = _project(tmp_path, phase, _trials(phase))
    assert [row["trial"] for row in receipt["excluded"]] == [INVALID_TRIAL]
    assert receipt["excluded"][0]["reason"] == "digest-policy trajectory export missing"
    assert len(receipt["projected"]) == 3
    release = tmp_path / "stage" / "trajectories" / receipt["release"]
    manifest = verify_trajectory_release(
        release, expected_manifest_sha256=receipt["manifest_sha256"]
    )
    assert manifest["admission"]["replay_complete_required"] is False
    assert manifest["quality"]["scope_complete_trajectories"] == 3
    assert manifest["quality"]["replay_complete_trajectories"] == 0
    digest = json.loads(
        (phase / "trials" / _trials(phase)[0] / "agent/geode-trajectory.json").read_text()
    )
    public = json.loads((release / f"{_trials(phase)[0]}.json").read_text())
    assert public["privacy"]["review_state"] == "reviewed"
    assert public["events"] == digest["events"] and public["outcome"] == digest["outcome"]
    assert public["provenance"]["source_revision"] == "a" * 40
    assert {row["path"].split("/", 1)[1] for row in public["artifact_digests"]} == {
        "agent-geode-trajectory.json",
        "result.json",
        "verifier-receipt.json",
    }
    assert "/Users/" not in (tmp_path / "projection-receipt.json").read_text()


def test_projection_rejects_digest_that_is_not_the_private_projection(tmp_path: Path) -> None:
    phase = build_phase(tmp_path / "run")["phase_dir"]
    trial = _trials(phase)[0]
    path = phase / "trials" / trial / "agent/geode-trajectory.private.json"
    full = json.loads(path.read_text())
    full["events"][2]["payload"]["tool"] = "unexpected_tool"
    path.write_text(json.dumps(full))
    with pytest.raises(ValueError, match="not the projection"):
        _project(tmp_path, phase, [trial])
    assert not (tmp_path / "projection-receipt.json").exists()


def test_projection_requires_a_scoped_privacy_review(tmp_path: Path) -> None:
    phase = build_phase(tmp_path / "run")["phase_dir"]
    with pytest.raises(ValueError, match="scope"):
        harbor_publication.project_phase(
            phase,
            [_trials(phase)[0]],
            privacy_review={**REVIEW, "scope": "another-run"},
            destination=tmp_path / "stage",
            release_source="geode-jev",
            published_at=PUBLISHED_AT,
            receipt_path=tmp_path / "projection-receipt.json",
        )


def _git(repo: Path, *args: str) -> str:
    executable = shutil.which("git")
    assert executable is not None
    return subprocess.run(  # noqa: S603 - resolved git executable with fixture argv
        [executable, *args], cwd=repo, env=_GIT_ENV, check=True, capture_output=True, text=True
    ).stdout.strip()


def _publication(prefix: str, public: Path, base: str) -> dict[str, Any]:
    return {
        "artifact_repository": {
            "base_revision": base,
            "destination_prefix": prefix,
            "url": "https://github.com/mangowhoiscloud/geode-eval-artifacts",
        },
        "entries": [
            {
                "bytes": public.stat().st_size,
                "classification": "public",
                "local_path": public.name,
                "remote_path": f"{prefix}/{public.name}",
                "sha256": hashlib.sha256(public.read_bytes()).hexdigest(),
            }
        ],
        "geode": {
            "repository": "https://github.com/mangowhoiscloud/geode",
            "revision": "a" * 40,
            "run_record": "docs/eval/external-artifact-repository.md",
        },
        "publication": {
            "artifact_merge_revision": None,
            "published_at": None,
            "status": "prepared",
        },
        "run_id": "geode-jev-noul-natural-20260926-fixture",
        "schema": "geode.eval-artifact-publication.v1",
        "verification": {
            "local_identity_scrubbed": True,
            "secret_scan_passed": True,
            "source_hashes_verified": True,
        },
    }


@pytest.fixture
def merged(tmp_path: Path) -> dict[str, Any]:
    if shutil.which("git") is None:
        pytest.skip("git is unavailable")
    phase = build_phase(tmp_path / "run")["phase_dir"]
    repo = tmp_path / "artifacts"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("fixture artifact repository\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "publication")
    receipt = harbor_publication.project_phase(
        phase,
        _trials(phase),
        privacy_review=REVIEW,
        destination=repo / "trajectories",
        release_source="geode-jev",
        published_at=PUBLISHED_AT,
        receipt_path=tmp_path / "projection-receipt.json",
    )
    prefix = "reports/e2e-validation/fixture"
    report = repo / prefix
    report.mkdir(parents=True)
    public = report / "trial-summary.json"
    public.write_text('{"passed": 3}\n')
    (report / "publication-manifest.json").write_text(
        json.dumps(_publication(prefix, public, base), indent=2) + "\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "publication")
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "publication", "-m", "merge publication")
    return {
        "repo": repo,
        "base": base,
        "head": head,
        "merge": _git(repo, "rev-parse", "HEAD"),
        "prefix": prefix,
        "release": f"trajectories/{receipt['release']}",
        "manifest_sha256": receipt["manifest_sha256"],
        "output": tmp_path / "remote-readback.json",
    }


def _readback(case: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "base": case["base"],
        "head": case["head"],
        "merge": case["merge"],
        "prefixes": [case["prefix"]],
        "releases": {case["release"]: case["manifest_sha256"]},
        "manifest": f"{case['prefix']}/publication-manifest.json",
        "output": case["output"],
    }
    arguments.update(overrides)
    return harbor_publication.readback(case["repo"], **arguments)


def test_readback_verifies_exact_merge_bytes(merged: dict[str, Any]) -> None:
    receipt = _readback(merged, local_root=merged["repo"])
    assert receipt["status"] == "passed"
    assert receipt["merge_parents"] == [merged["base"], merged["head"]]
    assert receipt["publication_manifest"]["public_entries"] == 1
    assert receipt["trajectory_releases"][0]["quality"]["scope_complete_trajectories"] == 3
    assert receipt["counts"]["modified_files"] == 0
    with pytest.raises(FileExistsError):
        _readback(merged)


def test_readback_rejects_changes_outside_the_append_only_destinations(
    merged: dict[str, Any],
) -> None:
    repo = merged["repo"]
    _git(repo, "checkout", "-q", "publication")
    (repo / "README.md").write_text("rewritten\n")
    _git(repo, "commit", "-q", "-am", "rewrite readme")
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    # Re-merge the widened branch onto the same reviewed base.
    _git(repo, "reset", "-q", "--hard", merged["base"])
    _git(repo, "merge", "-q", "--no-ff", "publication", "-m", "merge again")
    case = {**merged, "head": head, "merge": _git(repo, "rev-parse", "HEAD")}
    with pytest.raises(ValueError, match="existing path"):
        _readback(case)
    receipt = _readback(case, allow_modified=["README.md"])
    assert receipt["counts"]["modified_files"] == 1


@pytest.mark.parametrize("fault", ["parents", "anchor", "local-bytes"])
def test_readback_rejects_wrong_identity_or_bytes(merged: dict[str, Any], fault: str) -> None:
    if fault == "parents":
        overrides: dict[str, Any] = {"base": merged["head"]}
    elif fault == "anchor":
        overrides = {"releases": {merged["release"]: "0" * 64}}
    else:
        local = merged["repo"].parent / "reviewed"
        shutil.copytree(merged["repo"], local, ignore=shutil.ignore_patterns(".git"))
        (local / merged["prefix"] / "trial-summary.json").write_text('{"passed": 4}\n')
        overrides = {"local_root": local}
    with pytest.raises(ValueError):
        _readback(merged, **overrides)
    assert not merged["output"].exists()


def test_scan_reports_counts_without_matched_text(tmp_path: Path) -> None:
    clean = tmp_path / "report"
    clean.mkdir()
    (clean / "table.csv").write_text("trial,value\nfixture,1\n")
    assert harbor_publication.scan_public_files([clean])["clean"] is True
    leaked = clean / "notes.txt"
    leaked.write_text("path /Users/somebody/private and contact person@example.com\n")
    report = harbor_publication.scan_public_files([clean])
    assert report["clean"] is False
    assert report["findings"] == {"absolute_home": 1, "email": 1}
    assert "somebody" not in json.dumps(report) and "person@" not in json.dumps(report)
    (clean / "blob.bin").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ValueError, match="manual review"):
        harbor_publication.scan_public_files([clean])
