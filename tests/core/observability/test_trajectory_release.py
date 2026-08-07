"""Public trajectory release staging is immutable and content-bound."""

import json
from hashlib import sha256

import pytest
from core.observability.trajectory import build_trajectory
from core.observability.trajectory_release import (
    stage_trajectory_release,
    verify_trajectory_release,
)


def _trajectory(*, review_state: str = "reviewed", content: str = "done"):
    return build_trajectory(
        trajectory_id="release-trajectory",
        captured_at="2026-07-31T00:00:00Z",
        source={"harness": "test", "session": "s-release"},
        events=[
            {
                "kind": "message.assistant",
                "actor": "assistant",
                "turn_id": "t-release",
                "payload": {"content": content},
            }
        ],
        outcome={"result": "pass"},
        provenance={"revision": "fixture"},
        privacy={"review_state": review_state},
        trajectory_class=("dialogue",),
    )


def _privacy_review(scope: str) -> dict[str, str]:
    return {
        "reviewer": "GEODE release test",
        "reviewed_at": "2026-07-31T01:00:00Z",
        "method": "fixture allowlist and secret scan",
        "scope": scope,
        "attestation": "Only the normalized fixture trajectory is approved.",
    }


def _rebind_release_directory(release, manifest: dict):
    manifest_path = release / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    digest = sha256(manifest_path.read_bytes()).hexdigest()
    rebound = release.with_name(f"{release.name.rsplit('-', 1)[0]}-{digest[:12]}")
    release.rename(rebound)
    return rebound


def test_stage_release_validates_scans_and_reads_back(tmp_path):
    release = stage_trajectory_release(
        tmp_path,
        release_source="geode-agenticloop",
        release_scope="behavior-e2e",
        trajectories={"trajectory.json": _trajectory()},
        published_at="2026-07-31T01:02:03Z",
        privacy_review=_privacy_review("behavior-e2e"),
    )

    manifest = verify_trajectory_release(release)
    assert manifest["schema_id"] == "geode.trajectory-release@1"
    assert manifest["producer_schema_id"] == "geode.trajectory@1"
    assert manifest["quality"]["schema_valid"] is True
    assert manifest["quality"]["integrity_recomputed"] is True
    assert manifest["quality"]["trajectory_ids_unique"] is True
    assert manifest["quality"]["trajectory_events"] == 1
    assert manifest["quality"]["evidence_refs"] == 0
    assert manifest["quality"]["runtime_event_refs"] == 0
    assert manifest["admission"]["scope_complete_required"] is True
    assert manifest["privacy_review"]["reviewer"] == "GEODE release test"
    assert len(manifest["privacy_review"]["record_sha256"]) == 64
    assert manifest["quality"]["secret_scan"] == {
        "absolute_home": 0,
        "email": 0,
        "github_token": 0,
        "openai_key": 0,
        "bearer": 0,
        "aws_access_key": 0,
        "url_query_secret": 0,
        "known_secret": 0,
    }
    assert {path.name for path in release.iterdir()} == {"manifest.json", "trajectory.json"}


def test_stage_release_rejects_unreviewed_or_sensitive_payload(tmp_path):
    with pytest.raises(ValueError, match="lacks privacy review"):
        stage_trajectory_release(
            tmp_path,
            release_source="test",
            release_scope="unreviewed",
            trajectories={"trajectory.json": _trajectory(review_state="local")},
            privacy_review=_privacy_review("unreviewed"),
        )
    with pytest.raises(ValueError, match="secret scan failed"):
        stage_trajectory_release(
            tmp_path,
            release_source="test",
            release_scope="secret",
            trajectories={"trajectory.json": _trajectory(content="owner@example.com")},
            privacy_review=_privacy_review("secret"),
        )


def test_release_readback_rejects_tampering(tmp_path):
    release = stage_trajectory_release(
        tmp_path,
        release_source="test",
        release_scope="tamper",
        trajectories={"trajectory.json": _trajectory()},
        privacy_review=_privacy_review("tamper"),
    )
    path = release / "trajectory.json"
    payload = json.loads(path.read_text())
    payload["outcome"] = {"result": "changed"}
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="digest mismatch"):
        verify_trajectory_release(release)


def test_release_readback_requires_expected_manifest_anchor(tmp_path):
    release = stage_trajectory_release(
        tmp_path,
        release_source="test",
        release_scope="anchor",
        trajectories={"trajectory.json": _trajectory()},
        privacy_review=_privacy_review("anchor"),
    )

    with pytest.raises(ValueError, match="expected anchor"):
        verify_trajectory_release(
            release,
            expected_manifest_sha256="0" * 64,
        )


def test_release_readback_accepts_relative_release_path(tmp_path, monkeypatch):
    release = stage_trajectory_release(
        tmp_path / "releases",
        release_source="test",
        release_scope="relative-path",
        trajectories={"trajectory.json": _trajectory()},
        privacy_review=_privacy_review("relative-path"),
    )
    manifest_sha256 = sha256((release / "manifest.json").read_bytes()).hexdigest()
    monkeypatch.chdir(tmp_path)

    manifest = verify_trajectory_release(
        release.relative_to(tmp_path),
        expected_manifest_sha256=manifest_sha256,
    )

    assert manifest["quality"]["scope_complete_trajectories"] == 1


def test_stage_release_accepts_symlinked_destination_root(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    release = stage_trajectory_release(
        alias / "releases",
        release_source="test",
        release_scope="symlink-root",
        trajectories={"trajectory.json": _trajectory()},
        privacy_review=_privacy_review("symlink-root"),
    )

    assert release.is_relative_to(real.resolve())


def test_release_readback_recomputes_manifest_quality(tmp_path):
    release = stage_trajectory_release(
        tmp_path,
        release_source="test",
        release_scope="quality",
        trajectories={"trajectory.json": _trajectory()},
        privacy_review=_privacy_review("quality"),
    )
    manifest_path = release / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["quality"]["trajectory_events"] = 99
    rebound = _rebind_release_directory(release, manifest)

    with pytest.raises(ValueError, match="quality does not match"):
        verify_trajectory_release(rebound)


def test_readback_rejects_self_consistent_unreviewed_release(tmp_path):
    release = stage_trajectory_release(
        tmp_path,
        release_source="test",
        release_scope="readback-privacy",
        trajectories={"trajectory.json": _trajectory()},
        privacy_review=_privacy_review("readback-privacy"),
    )
    trajectory_path = release / "trajectory.json"
    trajectory = json.loads(trajectory_path.read_text())
    trajectory["privacy"]["review_state"] = "local"
    trajectory_path.write_text(json.dumps(trajectory, sort_keys=True))
    manifest = json.loads((release / "manifest.json").read_text())
    row = manifest["files"][0]
    row["bytes"] = trajectory_path.stat().st_size
    row["sha256"] = sha256(trajectory_path.read_bytes()).hexdigest()
    manifest["quality"]["privacy_reviewed"] = False
    rebound = _rebind_release_directory(release, manifest)

    with pytest.raises(ValueError, match="requires reviewed artifacts"):
        verify_trajectory_release(rebound)


def test_readback_rejects_self_consistent_scope_incomplete_release(tmp_path):
    release = stage_trajectory_release(
        tmp_path,
        release_source="test",
        release_scope="readback-scope",
        trajectories={"trajectory.json": _trajectory()},
        privacy_review=_privacy_review("readback-scope"),
    )
    incomplete = build_trajectory(
        trajectory_id="release-trajectory",
        captured_at="2026-07-31T00:00:00Z",
        source={"harness": "test", "session": "s-release"},
        events=[
            {
                "kind": "tool.called",
                "actor": "assistant",
                "turn_id": "t-release",
                "call_id": "c-orphan",
                "payload": {"tool": "read"},
            }
        ],
        outcome={"result": "pass"},
        provenance={"revision": "fixture"},
        privacy={"review_state": "reviewed"},
    )
    trajectory_path = release / "trajectory.json"
    trajectory_path.write_text(json.dumps(incomplete, sort_keys=True))
    manifest = json.loads((release / "manifest.json").read_text())
    row = manifest["files"][0]
    row.update(
        {
            "bytes": trajectory_path.stat().st_size,
            "sha256": sha256(trajectory_path.read_bytes()).hexdigest(),
            "records": 1,
            "scope_complete": False,
            "replay_complete": False,
            "complete": False,
        }
    )
    manifest["quality"].update(
        {
            "scope_complete_trajectories": 0,
            "scope_incomplete_trajectories": 1,
            "replay_complete_trajectories": 0,
            "replay_incomplete_trajectories": 1,
            "complete_trajectories": 0,
            "incomplete_trajectories": 1,
        }
    )
    rebound = _rebind_release_directory(release, manifest)

    with pytest.raises(ValueError, match="requires scope-complete"):
        verify_trajectory_release(rebound)


def test_stage_release_scans_linux_home_in_metadata(tmp_path):
    with pytest.raises(ValueError, match="absolute_home=1"):
        stage_trajectory_release(
            tmp_path,
            release_source="/home/alice/geode",
            release_scope="metadata",
            trajectories={"trajectory.json": _trajectory()},
            privacy_review=_privacy_review("metadata"),
        )


def test_stage_release_recomputes_integrity_and_rejects_duplicate_identity(tmp_path):
    invalid = _trajectory()
    invalid["integrity"]["record_count"] = 99
    with pytest.raises(ValueError, match="record_count"):
        stage_trajectory_release(
            tmp_path,
            release_source="test",
            release_scope="false-integrity",
            trajectories={"trajectory.json": invalid},
            privacy_review=_privacy_review("false-integrity"),
        )

    first = _trajectory()
    second = _trajectory(content="another")
    with pytest.raises(ValueError, match="duplicate trajectory_id"):
        stage_trajectory_release(
            tmp_path,
            release_source="test",
            release_scope="duplicate-id",
            trajectories={"first.json": first, "second.json": second},
            privacy_review=_privacy_review("duplicate-id"),
        )


def test_stage_release_requires_scope_bound_privacy_review(tmp_path):
    with pytest.raises(ValueError, match="requires a privacy review record"):
        stage_trajectory_release(
            tmp_path,
            release_source="test",
            release_scope="missing-review",
            trajectories={"trajectory.json": _trajectory()},
        )
    with pytest.raises(ValueError, match="scope must equal"):
        stage_trajectory_release(
            tmp_path,
            release_source="test",
            release_scope="expected-scope",
            trajectories={"trajectory.json": _trajectory()},
            privacy_review=_privacy_review("other-scope"),
        )


def test_stage_release_verifies_every_source_artifact_digest(tmp_path):
    source = tmp_path / "run.eval"
    source.write_bytes(b"inspect-eval-native-receipt")
    digest = sha256(source.read_bytes()).hexdigest()
    trajectory = _trajectory()
    trajectory["artifact_digests"] = [{"path": "run.eval", "sha256": digest}]

    release = stage_trajectory_release(
        tmp_path / "releases",
        release_source="sil",
        release_scope="digest-join",
        trajectories={"trajectory.json": trajectory},
        privacy_review=_privacy_review("digest-join"),
        source_artifacts={"run.eval": source},
    )
    manifest = verify_trajectory_release(release)
    assert manifest["quality"]["source_digest_refs"] == 1
    assert manifest["quality"]["source_digests_verified"] == 1

    with pytest.raises(ValueError, match="source artifact bytes are required"):
        stage_trajectory_release(
            tmp_path / "missing-source",
            release_source="sil",
            release_scope="digest-missing",
            trajectories={"trajectory.json": trajectory},
            privacy_review=_privacy_review("digest-missing"),
        )
    with pytest.raises(ValueError, match="source artifact digest mismatch"):
        stage_trajectory_release(
            tmp_path / "wrong-source",
            release_source="sil",
            release_scope="digest-wrong",
            trajectories={"trajectory.json": trajectory},
            privacy_review=_privacy_review("digest-wrong"),
            source_artifacts={"run.eval": b"different bytes"},
        )


def test_release_readback_rejects_undeclared_files(tmp_path):
    release = stage_trajectory_release(
        tmp_path,
        release_source="test",
        release_scope="undeclared",
        trajectories={"trajectory.json": _trajectory()},
        privacy_review=_privacy_review("undeclared"),
    )
    (release / "unexpected.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="undeclared files"):
        verify_trajectory_release(release)


def test_replay_incomplete_release_requires_explicit_admission(tmp_path):
    trajectory = build_trajectory(
        trajectory_id="digest-only-trajectory",
        captured_at="2026-07-31T00:00:00Z",
        source={"harness": "test", "session": "s-digest-only"},
        events=[
            {
                "kind": "message.assistant",
                "actor": "assistant",
                "turn_id": "t-digest-only",
                "payload": {"content_sha256": "a" * 64, "content_omitted": True},
            }
        ],
        outcome={"result": "pass"},
        provenance={"revision": "fixture"},
        privacy={"review_state": "reviewed"},
        integrity={
            "scope_complete": True,
            "replay_complete": False,
            "replay_incompleteness": ["private content was replaced by a digest"],
        },
    )
    with pytest.raises(ValueError, match="not replay-complete"):
        stage_trajectory_release(
            tmp_path / "strict",
            release_source="test",
            release_scope="strict-replay",
            trajectories={"trajectory.json": trajectory},
            privacy_review=_privacy_review("strict-replay"),
        )

    release = stage_trajectory_release(
        tmp_path / "digest-admitted",
        release_source="test",
        release_scope="digest-admitted",
        trajectories={"trajectory.json": trajectory},
        privacy_review=_privacy_review("digest-admitted"),
        require_complete=False,
    )
    manifest = verify_trajectory_release(release)
    assert manifest["admission"]["replay_complete_required"] is False
    assert manifest["quality"]["scope_complete_trajectories"] == 1
    assert manifest["quality"]["replay_incomplete_trajectories"] == 1
