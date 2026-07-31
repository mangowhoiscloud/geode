"""Immutable publication boundary for ``geode.trajectory@1`` artifacts.

The evaluation artifact repository is append-only. A release contains only
schema-validated trajectories and one content-bound manifest; SQLite, JSONL,
hidden reasoning, checkpoints, and benchmark scratch remain outside it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from core.memory.atomic_write import atomic_write_json
from core.observability.record_schema import validate_record
from core.observability.trajectory import TRAJECTORY_SCHEMA_ID, verify_trajectory_integrity

TRAJECTORY_RELEASE_SCHEMA_ID = "geode.trajectory-release@1"
TRAJECTORY_RELEASE_SCHEMA_VERSION = 1

_PUBLIC_SCAN_PATTERNS = {
    "absolute_home": re.compile(
        r"(?:/Users/(?!REDACTED(?:/|$))[^/\s]+"
        r"|/home/(?!REDACTED(?:/|$))[^/\s]+"
        r"|[A-Za-z]:\\Users\\(?!REDACTED(?:\\|$))[^\\\s]+)"
    ),
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "github_token": re.compile(r"\bgh[opsu]_[A-Za-z0-9_]{20,}\b"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "bearer": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b", re.I),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "url_query_secret": re.compile(
        r"[?&](?:api[_-]?key|access[_-]?token|token|secret)=[^&\s]{8,}",
        re.I,
    ),
}


def stage_trajectory_release(
    destination_root: Path | str,
    *,
    release_source: str,
    release_scope: str,
    trajectories: Mapping[str, Mapping[str, Any]],
    published_at: str | None = None,
    supersedes: str | None = None,
    require_complete: bool = True,
    privacy_review: Mapping[str, Any] | None = None,
    source_artifacts: Mapping[str, Path | bytes] | None = None,
) -> Path:
    """Validate, scan, and atomically stage one append-only public release."""
    if not trajectories:
        raise ValueError("trajectory release requires at least one artifact")
    published = _publication_time(published_at)
    normalized_source = _release_component(release_source, "release_source", 128)
    normalized_scope = _release_component(release_scope, "release_scope", 256)
    normalized_review = _normalize_privacy_review(
        privacy_review,
        release_scope=normalized_scope,
    )
    destination = Path(destination_root)
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".trajectory-release-", dir=destination) as raw_tmp:
        staging = Path(raw_tmp)
        files: list[dict[str, Any]] = []
        scan_counts = {**dict.fromkeys(_PUBLIC_SCAN_PATTERNS, 0), "known_secret": 0}
        privacy_reviewed = True
        scope_complete_count = 0
        replay_complete_count = 0
        source_digest_refs = 0
        source_digests_verified = 0
        evidence_refs = 0
        runtime_event_refs = 0
        event_count = 0
        trajectory_ids: set[str] = set()
        release_paths: set[str] = set()
        metadata_scan_text = json.dumps(
            {
                "release_source": normalized_source,
                "release_scope": normalized_scope,
                "supersedes": supersedes,
                "paths": sorted(trajectories),
                "privacy_review": normalized_review,
            },
            ensure_ascii=False,
        )
        _add_scan_counts(scan_counts, metadata_scan_text)
        for relative, raw_trajectory in sorted(trajectories.items()):
            path = _release_file(staging, relative)
            normalized_relative = path.relative_to(staging).as_posix()
            if normalized_relative in release_paths:
                raise ValueError(f"duplicate trajectory release path: {normalized_relative}")
            release_paths.add(normalized_relative)
            trajectory = dict(raw_trajectory)
            quality = verify_trajectory_integrity(trajectory)
            integrity = trajectory.get("integrity")
            privacy = trajectory.get("privacy")
            trajectory_id = str(trajectory.get("trajectory_id") or "")
            if trajectory_id in trajectory_ids:
                raise ValueError(f"duplicate trajectory_id in release: {trajectory_id}")
            trajectory_ids.add(trajectory_id)
            scope_complete = bool(
                isinstance(integrity, Mapping) and integrity.get("scope_complete")
            )
            replay_complete = bool(
                isinstance(integrity, Mapping) and integrity.get("replay_complete")
            )
            reviewed = bool(
                isinstance(privacy, Mapping) and privacy.get("review_state") == "reviewed"
            )
            if not scope_complete:
                raise ValueError(f"public trajectory is not scope-complete: {relative}")
            if require_complete and not replay_complete:
                raise ValueError(f"public trajectory is not replay-complete: {relative}")
            if not reviewed:
                raise ValueError(f"public trajectory lacks privacy review: {relative}")
            privacy_reviewed = privacy_reviewed and reviewed
            scope_complete_count += int(scope_complete)
            replay_complete_count += int(replay_complete)
            digests = trajectory.get("artifact_digests")
            if isinstance(digests, list):
                source_digest_refs += len(digests)
                for digest_ref in digests:
                    if not isinstance(digest_ref, Mapping):
                        raise ValueError("trajectory artifact digest must be an object")
                    source_digests_verified += _verify_source_artifact_digest(
                        digest_ref,
                        source_artifacts=source_artifacts,
                    )
            evidence_refs += quality["evidence_ref_count"]
            runtime_event_refs += quality["runtime_event_ref_count"]
            event_count += quality["record_count"]
            atomic_write_json(path, trajectory, indent=2)
            text = path.read_text(encoding="utf-8")
            _add_scan_counts(scan_counts, text)
            files.append(
                {
                    "path": relative,
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                    "records": int(integrity.get("record_count", 0))
                    if isinstance(integrity, Mapping)
                    else 0,
                    "trajectory_id": trajectory_id,
                    "scope_complete": scope_complete,
                    "replay_complete": replay_complete,
                    "complete": replay_complete,
                }
            )
        if any(scan_counts.values()):
            findings = ", ".join(f"{name}={count}" for name, count in scan_counts.items() if count)
            raise ValueError(f"public trajectory secret scan failed: {findings}")
        manifest = {
            "schema_id": TRAJECTORY_RELEASE_SCHEMA_ID,
            "schema_version": TRAJECTORY_RELEASE_SCHEMA_VERSION,
            "producer_schema_id": TRAJECTORY_SCHEMA_ID,
            "release_source": normalized_source,
            "release_scope": normalized_scope,
            "published_at": published,
            "supersedes": supersedes,
            "admission": {
                "scope_complete_required": True,
                "replay_complete_required": require_complete,
                "privacy_review_required": True,
            },
            "privacy_review": normalized_review,
            "files": files,
            "quality": {
                "schema_valid": True,
                "integrity_recomputed": True,
                "trajectory_ids_unique": True,
                "privacy_reviewed": privacy_reviewed,
                "scope_complete_trajectories": scope_complete_count,
                "scope_incomplete_trajectories": len(files) - scope_complete_count,
                "replay_complete_trajectories": replay_complete_count,
                "replay_incomplete_trajectories": len(files) - replay_complete_count,
                "complete_trajectories": replay_complete_count,
                "incomplete_trajectories": len(files) - replay_complete_count,
                "trajectory_events": event_count,
                "evidence_refs": evidence_refs,
                "runtime_event_refs": runtime_event_refs,
                "secret_scan": scan_counts,
                "source_digest_refs": source_digest_refs,
                "source_digests_verified": source_digests_verified,
                "remote_readback_required": True,
            },
        }
        validate_record(manifest, schema_id=TRAJECTORY_RELEASE_SCHEMA_ID)
        manifest_path = staging / "manifest.json"
        atomic_write_json(manifest_path, manifest, indent=2)
        release_id = (
            f"{_path_component(normalized_source)}-{_path_component(normalized_scope)}-"
            f"{published.replace(':', '').replace('-', '')}-{_sha256(manifest_path)[:12]}"
        )
        manifest_sha256 = _sha256(manifest_path)
        release_dir = destination / release_id
        if release_dir.exists():
            raise FileExistsError(f"refusing to overwrite trajectory release: {release_dir}")
        verify_trajectory_release(
            staging,
            expected_manifest_sha256=manifest_sha256,
            require_directory_binding=False,
        )
        os.rename(staging, release_dir)
        try:
            verify_trajectory_release(
                release_dir,
                expected_manifest_sha256=manifest_sha256,
            )
        except Exception:
            # Restore the temp path so TemporaryDirectory removes the failed
            # staging tree; no declared append-only release survives failure.
            os.rename(release_dir, staging)
            raise
    return release_dir


def verify_trajectory_release(
    release_dir: Path | str,
    *,
    expected_manifest_sha256: str | None = None,
    require_directory_binding: bool = True,
) -> dict[str, Any]:
    """Read a staged release back and verify every manifest-bound byte."""
    root = Path(release_dir).resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("trajectory release manifest must be an object")
    validate_record(manifest, schema_id=TRAJECTORY_RELEASE_SCHEMA_ID)
    manifest_sha256 = _sha256(manifest_path)
    if expected_manifest_sha256 is not None and manifest_sha256 != expected_manifest_sha256:
        raise ValueError("trajectory release manifest digest does not match expected anchor")
    if require_directory_binding and not root.name.endswith(f"-{manifest_sha256[:12]}"):
        raise ValueError("trajectory release directory is not bound to manifest digest")
    declared = {"manifest.json"}
    observed_ids: set[str] = set()
    scan_counts = {**dict.fromkeys(_PUBLIC_SCAN_PATTERNS, 0), "known_secret": 0}
    scope_complete_count = 0
    replay_complete_count = 0
    privacy_reviewed = True
    event_count = 0
    evidence_refs = 0
    runtime_event_refs = 0
    source_digest_refs = 0
    declared_paths: set[str] = set()
    _add_scan_counts(
        scan_counts,
        json.dumps(
            {
                "release_source": manifest["release_source"],
                "release_scope": manifest["release_scope"],
                "supersedes": manifest["supersedes"],
                "paths": [row["path"] for row in manifest["files"]],
                "privacy_review": manifest["privacy_review"],
            },
            ensure_ascii=False,
        ),
    )
    for row in manifest["files"]:
        path = _release_file(root, str(row["path"]))
        relative = path.relative_to(root).as_posix()
        if relative in declared_paths:
            raise ValueError(f"duplicate trajectory release path: {relative}")
        declared_paths.add(relative)
        declared.add(relative)
        if path.stat().st_size != row["bytes"] or _sha256(path) != row["sha256"]:
            raise ValueError(f"trajectory release digest mismatch: {row['path']}")
        text = path.read_text(encoding="utf-8")
        _add_scan_counts(scan_counts, text)
        trajectory = json.loads(text)
        if not isinstance(trajectory, dict):
            raise ValueError(f"trajectory release file is not an object: {row['path']}")
        quality = verify_trajectory_integrity(trajectory)
        trajectory_id = str(trajectory.get("trajectory_id") or "")
        if trajectory_id != row["trajectory_id"]:
            raise ValueError(f"trajectory release identity mismatch: {row['path']}")
        if trajectory_id in observed_ids:
            raise ValueError(f"duplicate trajectory_id in release: {trajectory_id}")
        observed_ids.add(trajectory_id)
        scope_complete = quality["scope_complete"]
        replay_complete = quality["replay_complete"]
        if (
            row["scope_complete"] != scope_complete
            or row["replay_complete"] != replay_complete
            or row["complete"] != replay_complete
            or row["records"] != quality["record_count"]
        ):
            raise ValueError(f"trajectory release aggregate mismatch: {row['path']}")
        scope_complete_count += int(scope_complete)
        replay_complete_count += int(replay_complete)
        privacy = trajectory.get("privacy")
        privacy_reviewed = privacy_reviewed and bool(
            isinstance(privacy, Mapping) and privacy.get("review_state") == "reviewed"
        )
        event_count += quality["record_count"]
        evidence_refs += quality["evidence_ref_count"]
        runtime_event_refs += quality["runtime_event_ref_count"]
        source_digest_refs += quality["source_digest_ref_count"]
    observed = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if observed != declared:
        raise ValueError("trajectory release contains undeclared files")
    recomputed_quality = {
        "schema_valid": True,
        "integrity_recomputed": True,
        "trajectory_ids_unique": True,
        "privacy_reviewed": privacy_reviewed,
        "scope_complete_trajectories": scope_complete_count,
        "scope_incomplete_trajectories": len(declared_paths) - scope_complete_count,
        "replay_complete_trajectories": replay_complete_count,
        "replay_incomplete_trajectories": len(declared_paths) - replay_complete_count,
        "complete_trajectories": replay_complete_count,
        "incomplete_trajectories": len(declared_paths) - replay_complete_count,
        "trajectory_events": event_count,
        "evidence_refs": evidence_refs,
        "runtime_event_refs": runtime_event_refs,
        "secret_scan": scan_counts,
        "source_digest_refs": source_digest_refs,
        "source_digests_verified": source_digest_refs,
        "remote_readback_required": True,
    }
    if manifest["quality"] != recomputed_quality:
        raise ValueError("trajectory release quality does not match recomputed artifacts")
    if any(scan_counts.values()):
        raise ValueError("trajectory release secret scan failed during readback")
    if scope_complete_count != len(declared_paths):
        raise ValueError("trajectory release admission requires scope-complete artifacts")
    if not privacy_reviewed:
        raise ValueError("trajectory release admission requires reviewed artifacts")
    admission = manifest["admission"]
    if admission["replay_complete_required"] and replay_complete_count != len(declared_paths):
        raise ValueError("trajectory release admission requires replay-complete artifacts")
    _verify_privacy_review(
        manifest["privacy_review"],
        release_scope=str(manifest["release_scope"]),
    )
    return manifest


def _release_file(root: Path, relative: str) -> Path:
    candidate = PurePosixPath(relative)
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.suffix != ".json"
        or candidate.name == "manifest.json"
    ):
        raise ValueError(f"invalid trajectory release path: {relative!r}")
    path = (root / Path(*candidate.parts)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"trajectory release path escapes root: {relative!r}")
    return path


def _publication_time(value: str | None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("published_at must be an ISO-8601 date-time") from exc
    if parsed.tzinfo is None:
        raise ValueError("published_at must include a timezone")
    return parsed.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _release_component(value: str, field: str, limit: int) -> str:
    text = str(value).strip()
    if not text or len(text) > limit:
        raise ValueError(f"{field} must contain 1..{limit} characters")
    return text


def _normalize_privacy_review(
    review: Mapping[str, Any] | None,
    *,
    release_scope: str,
) -> dict[str, str]:
    if review is None:
        raise ValueError("public trajectory release requires a privacy review record")
    fields = {
        "reviewer": _release_component(str(review.get("reviewer") or ""), "reviewer", 128),
        "reviewed_at": _publication_time(str(review.get("reviewed_at") or "")),
        "method": _release_component(str(review.get("method") or ""), "method", 256),
        "scope": _release_component(str(review.get("scope") or ""), "scope", 256),
        "attestation": _release_component(
            str(review.get("attestation") or ""),
            "attestation",
            2_048,
        ),
    }
    if fields["scope"] != release_scope:
        raise ValueError("privacy review scope must equal release_scope")
    return {**fields, "record_sha256": _mapping_sha256(fields)}


def _verify_privacy_review(review: Mapping[str, Any], *, release_scope: str) -> None:
    normalized = _normalize_privacy_review(review, release_scope=release_scope)
    if dict(review) != normalized:
        raise ValueError("trajectory release privacy review record is not canonical")


def _mapping_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _path_component(value: str, *, max_length: int = 64) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value).strip()).strip("-")
    if not normalized:
        raise ValueError("release source and scope must contain a path-safe character")
    if len(normalized) > max_length:
        suffix = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
        normalized = f"{normalized[: max_length - len(suffix) - 1]}-{suffix}"
    return normalized


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_source_artifact_digest(
    digest_ref: Mapping[str, Any],
    *,
    source_artifacts: Mapping[str, Path | bytes] | None,
) -> int:
    reference = str(digest_ref.get("path") or "")
    expected = str(digest_ref.get("sha256") or "")
    if source_artifacts is None or reference not in source_artifacts:
        raise ValueError(
            f"source artifact bytes are required to verify digest reference: {reference!r}"
        )
    source = source_artifacts[reference]
    observed = (
        hashlib.sha256(source).hexdigest() if isinstance(source, bytes) else _sha256(Path(source))
    )
    if observed != expected:
        raise ValueError(f"source artifact digest mismatch: {reference}")
    return 1


def _add_scan_counts(counts: dict[str, int], text: str) -> None:
    for name, pattern in _PUBLIC_SCAN_PATTERNS.items():
        counts[name] += len(pattern.findall(text))
    from core.observability.redaction import redact_secrets

    if redact_secrets(text) != text:
        counts["known_secret"] += 1


__all__ = [
    "TRAJECTORY_RELEASE_SCHEMA_ID",
    "TRAJECTORY_RELEASE_SCHEMA_VERSION",
    "stage_trajectory_release",
    "verify_trajectory_release",
]
