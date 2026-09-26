#!/usr/bin/env python3
"""Public trajectory projection and exact-merge read-back for Harbor evidence.

``project`` turns the retained digest-policy ``agent/geode-trajectory.json`` of
closed Harbor trials into reviewed public copies and stages them behind the
existing ``stage_trajectory_release`` gate. The public copy changes only
``privacy`` (review state), ``provenance`` (the transform and source revision)
and ``artifact_digests`` (source bytes it was derived from). Events and outcome
bytes stay exactly those of the digest export, which must equal the projection
of the private full export. Replay completeness is not claimed: digested
bodies make these copies scope-complete but content-replay-incomplete.
Trials whose canonical scope is incomplete are excluded with a reason and
never silently dropped from the receipt.

``readback`` verifies a merged geode-eval-artifacts PR at its exact merge
commit: ordered parents, identical reviewed tree, append-only changed paths
inside declared destinations, publication-manifest bytes and trajectory
releases recomputed from the commit's own blobs, and optionally the reviewed
local bytes and GitHub raw-content anchors. Both commands write a new receipt
and never overwrite one.

Usage:
    python scripts/eval/harbor_publication.py project <phase-dir> --all \\
        --privacy-review review.json --destination <stage-root> --source geode-jev \\
        --published-at 2026-09-26T00:00:00Z --receipt projection-receipt.json
    python scripts/eval/harbor_publication.py scan <public-report-dir>
    python scripts/eval/harbor_publication.py readback --repo <artifact-clone> \\
        --base <sha> --head <sha> --merge <sha> --prefix reports/e2e-validation/<run> \\
        --release trajectories/<release-dir>=<manifest-sha256> \\
        [--manifest <path/publication-manifest.json>] [--local-root <reviewed-tree>] \\
        [--allow-modified README.md] [--expect-remote-main] \\
        [--github-repo owner/name --api-anchor <path>] --output remote-readback.json
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.observability.trajectory import (
    TRAJECTORY_SCHEMA_ID,
    _digest_private_event_payload,
    verify_trajectory_integrity,
)
from core.observability.trajectory_release import (
    _PUBLIC_SCAN_PATTERNS,
    _add_scan_counts,
    stage_trajectory_release,
    verify_trajectory_release,
)
from scripts.eval.contract import _load_json_object, validate_publication, validate_run_spec

_SHA1 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CHANGED_FIELDS = ("artifact_digests", "privacy", "provenance")
TRANSFORM = "scripts/eval/harbor_publication.py project"


class ProjectionExcludedError(ValueError):
    """A trial whose retained export cannot enter a public release."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_receipt(path: Path, value: Mapping[str, Any]) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)
    return _sha256(path.read_bytes())


def project_trajectory(
    trial_dir: Path,
    *,
    source_revision: str,
    review: Mapping[str, Any],
    require_private: bool = True,
) -> tuple[dict[str, Any], dict[str, Path], dict[str, Any]]:
    """Return one reviewed public copy, its source artifacts and a projection record."""
    trial = trial_dir.name
    agent = trial_dir / "agent"
    digest_path = agent / "geode-trajectory.json"
    private_path = agent / "geode-trajectory.private.json"
    if digest_path.is_symlink() or not digest_path.is_file():
        raise ProjectionExcludedError("digest-policy trajectory export missing")
    digest_raw = digest_path.read_bytes()
    digest = _load_json_object(digest_path)
    if digest.get("schema_id") != TRAJECTORY_SCHEMA_ID:
        raise ValueError(f"{trial}: unsupported trajectory schema")
    quality = verify_trajectory_integrity(digest)
    if not quality["scope_complete"]:
        raise ProjectionExcludedError("canonical scope incomplete")
    record: dict[str, Any] = {"trial": trial, "digest_sha256": _sha256(digest_raw)}
    if private_path.is_file() and not private_path.is_symlink():
        full = _load_json_object(private_path)
        verify_trajectory_integrity(full)
        for key in ("source", "trajectory_id", "runtime_event_refs", "outcome"):
            if full.get(key) != digest.get(key):
                raise ValueError(f"{trial}: private/digest {key} differs")
        projected = [
            {**event, "payload": _digest_private_event_payload(event["kind"], event["payload"])}
            for event in full["events"]
        ]
        if projected != digest["events"]:
            raise ValueError(f"{trial}: digest events are not the projection of the private export")
        record["private_sha256"] = _sha256(private_path.read_bytes())
    elif require_private:
        raise ValueError(f"{trial}: private export missing; cannot prove the digest projection")
    else:
        record["private_sha256"] = None
    public = dict(digest)
    privacy: dict[str, Any] = {
        "review_state": "reviewed",
        "payloads": "Digest projection; non-allowlisted bodies remain withheld",
        "review_method": str(review["method"]),
    }
    if isinstance(review.get("license_status"), str) and review["license_status"]:
        privacy["license_status"] = review["license_status"]
    public["privacy"] = privacy
    public["provenance"] = {
        **dict(digest.get("provenance") or {}),
        "public_transform": TRANSFORM,
        "source_revision": source_revision,
    }
    sources = {
        f"{trial}/agent-geode-trajectory.json": digest_path,
        f"{trial}/result.json": trial_dir / "result.json",
        f"{trial}/verifier-receipt.json": trial_dir / "verifier" / "verifier-receipt.json",
    }
    sources = {
        ref: path for ref, path in sources.items() if path.is_file() and not path.is_symlink()
    }
    public["artifact_digests"] = [
        {"path": ref, "sha256": _sha256(path.read_bytes())} for ref, path in sources.items()
    ]
    public_quality = verify_trajectory_integrity(public)
    record.update(
        changed_fields=list(_CHANGED_FIELDS),
        scope_complete=public_quality["scope_complete"],
        replay_complete=public_quality["replay_complete"],
        source_artifacts=[row["path"] for row in public["artifact_digests"]],
    )
    return public, sources, record


def project_phase(
    phase_dir: Path,
    trials: Sequence[str],
    *,
    privacy_review: Mapping[str, Any],
    destination: Path,
    release_source: str,
    published_at: str,
    receipt_path: Path,
    release_scope: str | None = None,
    require_private: bool = True,
) -> dict[str, Any]:
    """Project selected trials, stage one release and write a projection receipt."""
    if receipt_path.exists():
        raise FileExistsError(f"refusing to overwrite projection receipt: {receipt_path.name}")
    run_spec = validate_run_spec(phase_dir / "run-spec.json")
    revision = str(run_spec["reproduction"]["geode"]["revision"])
    scope = release_scope or str(run_spec["run_id"])
    values: dict[str, dict[str, Any]] = {}
    originals: dict[str, Path] = {}
    projected: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for trial in trials:
        trial_dir = phase_dir / "trials" / trial
        if trial_dir.is_symlink() or not trial_dir.is_dir():
            excluded.append({"trial": trial, "reason": "trial directory missing"})
            continue
        try:
            public, sources, record = project_trajectory(
                trial_dir,
                source_revision=revision,
                review=privacy_review,
                require_private=require_private,
            )
        except ProjectionExcludedError as reason:
            excluded.append({"trial": trial, "reason": str(reason)})
            continue
        values[f"{trial}.json"] = public
        originals.update(sources)
        projected.append({**record, "public_path": f"{trial}.json"})
    if not values:
        raise ValueError("no trial produced an admissible public trajectory")
    release = stage_trajectory_release(
        destination,
        release_source=release_source,
        release_scope=scope,
        trajectories=values,
        published_at=published_at,
        require_complete=False,
        privacy_review=privacy_review,
        source_artifacts=originals,
    )
    manifest_sha256 = _sha256((release / "manifest.json").read_bytes())
    verified = verify_trajectory_release(release, expected_manifest_sha256=manifest_sha256)
    for record in projected:
        record["public_sha256"] = _sha256((release / record["public_path"]).read_bytes())
    receipt = {
        "kind": "harbor-public-trajectory-projection",
        "generator": TRANSFORM,
        "run_id": run_spec["run_id"],
        "source_revision": revision,
        "release_source": release_source,
        "release_scope": scope,
        "release": release.name,
        "manifest_sha256": manifest_sha256,
        "projected": projected,
        "excluded": excluded,
        "quality": verified["quality"],
        "limitations": [
            "Digest projections are scope-complete, not content-replay-complete.",
            "Local staging does not replace the artifact PR and exact-merge read-back.",
            "Pattern scans supplement exact-byte privacy review; they do not replace it.",
        ],
    }
    receipt["receipt_sha256"] = _write_receipt(receipt_path, receipt)
    return receipt


def scan_public_files(paths: Sequence[Path]) -> dict[str, Any]:
    """Apply the release gate's secret and identity patterns to other public files.

    Only counts and relative file names are returned, never matched text. A clean
    pattern scan supplements exact-byte review; it is not a privacy approval.
    """
    files: list[Path] = []
    for path in paths:
        if path.is_symlink():
            raise ValueError(f"symlinked public candidate rejected: {path.name}")
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_symlink():
                    raise ValueError(f"symlinked public candidate rejected: {child.name}")
                if child.is_file():
                    files.append(child)
        elif path.is_file():
            files.append(path)
        else:
            raise ValueError(f"public candidate does not exist: {path.name}")
    totals = {**dict.fromkeys(_PUBLIC_SCAN_PATTERNS, 0), "known_secret": 0}
    flagged = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(
                f"non-text public candidate needs manual review: {path.name}"
            ) from error
        counts = {**dict.fromkeys(_PUBLIC_SCAN_PATTERNS, 0), "known_secret": 0}
        _add_scan_counts(counts, text)
        findings = {name: count for name, count in counts.items() if count}
        if findings:
            flagged.append({"file": path.name, "findings": findings})
        for name, count in counts.items():
            totals[name] += count
    return {
        "files_scanned": len(files),
        "clean": not any(totals.values()),
        "findings": {name: count for name, count in totals.items() if count},
        "flagged_files": flagged,
    }


def _command(argv: Sequence[str], *, cwd: Path | None = None) -> bytes:
    """Run one fixed tool as argv (never a shell) and return its raw stdout bytes."""
    executable = shutil.which(argv[0])
    if executable is None:
        raise ValueError(f"required command is unavailable: {argv[0]}")
    return subprocess.run(  # noqa: S603 - resolved executable; argv is not shell-expanded
        [executable, *argv[1:]], cwd=cwd, capture_output=True, check=True
    ).stdout


def _git(repo: Path, *args: str) -> bytes:
    return _command(["git", *args], cwd=repo)


def readback(
    repo: Path,
    *,
    base: str,
    head: str,
    merge: str,
    prefixes: Sequence[str],
    releases: Mapping[str, str],
    output: Path,
    manifest: str | None = None,
    local_root: Path | None = None,
    allow_modified: Sequence[str] = (),
    expect_remote_main: bool = False,
    github_repo: str | None = None,
    api_anchors: Sequence[str] = (),
) -> dict[str, Any]:
    """Verify merged public bytes at one exact merge commit and write a receipt."""
    if output.exists():
        raise FileExistsError(f"refusing to overwrite read-back receipt: {output.name}")
    for label, value in (("base", base), ("head", head), ("merge", merge)):
        if not _SHA1.fullmatch(value):
            raise ValueError(f"{label} must be a full 40-character commit SHA")
    for release, digest in releases.items():
        if not _SHA256.fullmatch(digest):
            raise ValueError(f"release manifest anchor is not a SHA-256: {release}")
    roots = [root.strip("/") for root in (*prefixes, *releases)]
    if not roots or any(not root or ".." in Path(root).parts for root in roots):
        raise ValueError("declared destinations must be non-empty relative paths")
    identity = _git(repo, "show", "--no-patch", "--format=%H%n%P%n%T", merge).decode().splitlines()
    commit, parents, tree = identity[0], identity[1].split(), identity[2]
    if commit != merge or parents != [base, head]:
        raise ValueError("merge commit parents are not the reviewed base and head")
    if tree != _git(repo, "rev-parse", f"{head}^{{tree}}").decode().strip():
        raise ValueError("merge tree differs from the reviewed head tree")
    remote_main = None
    if expect_remote_main:
        remote_main = _git(repo, "rev-parse", "origin/main").decode().strip()
        if remote_main != merge:
            raise ValueError("fetched origin/main is not the verified merge commit")
    changes: dict[str, str] = {}
    for line in (
        _git(repo, "diff", "--name-status", "--no-renames", base, merge).decode().splitlines()
    ):
        status, path = line.split("\t", 1)
        changes[path] = status
    for path, status in changes.items():
        if path in allow_modified:
            if status not in ("A", "M"):
                raise ValueError(f"allowed file was not added or modified: {path}")
            continue
        if status != "A":
            raise ValueError(f"append-only publication changed an existing path: {path}")
        if not any(path.startswith(root + "/") for root in roots):
            raise ValueError(f"changed path is outside the declared destinations: {path}")
    blobs = {path: _git(repo, "show", f"{merge}:{path}") for path in sorted(changes)}
    files = []
    for path, data in blobs.items():
        entry: dict[str, Any] = {
            "path": path,
            "change": changes[path],
            "bytes": len(data),
            "sha256": _sha256(data),
        }
        if local_root is not None:
            local = local_root / path
            if local.is_symlink() or not local.is_file() or local.read_bytes() != data:
                raise ValueError(f"reviewed local bytes differ from the merge commit: {path}")
            entry["local_bytes_match"] = True
        files.append(entry)
    manifest_check = None
    release_checks = []
    with tempfile.TemporaryDirectory(prefix="geode-readback-") as raw_tmp:
        tree_root = Path(raw_tmp)
        archive = _git(repo, "archive", "--format=tar", merge, "--", *roots)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(tree_root, filter="data")
        if manifest is not None:
            if manifest not in blobs:
                raise ValueError("publication manifest is not part of the merged change")
            payload = validate_publication(tree_root / manifest)
            public = [row for row in payload["entries"] if row["classification"] == "public"]
            for row in public:
                blob = blobs.get(str(row["remote_path"]))
                if blob is None or len(blob) != row["bytes"] or _sha256(blob) != row["sha256"]:
                    raise ValueError(
                        f"manifest entry differs at the merge commit: {row['remote_path']}"
                    )
            manifest_check = {
                "path": manifest,
                "sha256": _sha256(blobs[manifest]),
                "status": payload["publication"]["status"],
                "public_entries": len(public),
                "public_bytes": sum(int(row["bytes"]) for row in public),
            }
        for release, digest in sorted(releases.items()):
            verified = verify_trajectory_release(
                tree_root / release, expected_manifest_sha256=digest
            )
            declared = [path for path in blobs if path.startswith(release.strip("/") + "/")]
            release_checks.append(
                {
                    "path": release,
                    "manifest_sha256": digest,
                    "files_including_manifest": len(declared),
                    "quality": verified["quality"],
                }
            )
    api = []
    for path in api_anchors:
        if not github_repo:
            raise ValueError("GitHub raw-content anchors require --github-repo")
        if path not in blobs:
            raise ValueError(f"API anchor is not part of the merged change: {path}")
        data = _command(
            [
                "gh",
                "api",
                f"repos/{github_repo}/contents/{path}?ref={merge}",
                "-H",
                "Accept: application/vnd.github.raw",
            ]
        )
        if data != blobs[path]:
            raise ValueError(f"GitHub raw content differs from the merge commit: {path}")
        api.append({"path": path, "bytes": len(data), "sha256": _sha256(data)})
    receipt = {
        "kind": "artifact-merge-readback",
        "generator": "scripts/eval/harbor_publication.py readback",
        "status": "passed",
        "verified_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "base_revision": base,
        "head_revision": head,
        "merge_revision": merge,
        "merge_parents": parents,
        "merge_tree": tree,
        "feature_and_merge_tree_identical": True,
        "fetched_origin_main": remote_main,
        "counts": {
            "changed_files_verified": len(files),
            "added_files": sum(changes[path] == "A" for path in changes),
            "modified_files": sum(changes[path] == "M" for path in changes),
            "changed_bytes_verified": sum(entry["bytes"] for entry in files),
            "trajectory_releases": len(release_checks),
            "github_raw_api_files": len(api),
        },
        "files": files,
        "publication_manifest": manifest_check,
        "trajectory_releases": release_checks,
        "github_raw_api_readback": api,
        "limitations": [
            "Read-back verifies exact public bytes, not a new experiment or model rerun.",
            "Private source logs are neither downloaded nor modified.",
            "A prepared manifest stays prepared; post-merge facts live in this receipt.",
            "No remote CI claim is made unless the artifact repository reports one.",
        ],
    }
    receipt["receipt_sha256"] = _write_receipt(output, receipt)
    return receipt


def _mapping(values: Sequence[str], *, label: str) -> dict[str, str]:
    result = {}
    for value in values:
        key, separator, item = value.partition("=")
        if not separator or not key or not item:
            raise ValueError(f"{label} must use KEY=VALUE")
        if key in result:
            raise ValueError(f"duplicate {label}: {key}")
        result[key] = item
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    project = commands.add_parser("project", help="stage reviewed public trajectory copies")
    project.add_argument("phase_dir", type=Path)
    selection = project.add_mutually_exclusive_group(required=True)
    selection.add_argument("--trial", action="append", default=[])
    selection.add_argument("--all", action="store_true")
    project.add_argument("--privacy-review", type=Path, required=True)
    project.add_argument("--destination", type=Path, required=True)
    project.add_argument("--source", required=True)
    project.add_argument("--scope")
    project.add_argument("--published-at", required=True)
    project.add_argument("--receipt", type=Path, required=True)
    back = commands.add_parser("readback", help="verify merged bytes at one exact commit")
    back.add_argument("--repo", type=Path, required=True)
    back.add_argument("--base", required=True)
    back.add_argument("--head", required=True)
    back.add_argument("--merge", required=True)
    back.add_argument("--prefix", action="append", default=[])
    back.add_argument("--release", action="append", default=[])
    back.add_argument("--manifest")
    back.add_argument("--local-root", type=Path)
    back.add_argument("--allow-modified", action="append", default=[])
    back.add_argument("--expect-remote-main", action="store_true")
    back.add_argument("--github-repo")
    back.add_argument("--api-anchor", action="append", default=[])
    back.add_argument("--output", type=Path, required=True)
    scan = commands.add_parser("scan", help="pattern-scan other public candidate files")
    scan.add_argument("paths", type=Path, nargs="+")
    args = parser.parse_args(argv)
    try:
        if args.command == "scan":
            report = scan_public_files(args.paths)
            print(json.dumps({"ok": report["clean"], **report}, sort_keys=True))
            return 0 if report["clean"] else 1
        if args.command == "project":
            review = _load_json_object(args.privacy_review)
            trials = args.trial or sorted(
                path.name for path in (args.phase_dir / "trials").iterdir() if path.is_dir()
            )
            receipt = project_phase(
                args.phase_dir,
                trials,
                privacy_review=review,
                destination=args.destination,
                release_source=args.source,
                published_at=args.published_at,
                receipt_path=args.receipt,
                release_scope=args.scope,
            )
            summary = {
                "projected": len(receipt["projected"]),
                "excluded": len(receipt["excluded"]),
                "release": receipt["release"],
                "manifest_sha256": receipt["manifest_sha256"],
            }
        else:
            receipt = readback(
                args.repo,
                base=args.base,
                head=args.head,
                merge=args.merge,
                prefixes=args.prefix,
                releases=_mapping(args.release, label="--release"),
                output=args.output,
                manifest=args.manifest,
                local_root=args.local_root,
                allow_modified=args.allow_modified,
                expect_remote_main=args.expect_remote_main,
                github_repo=args.github_repo,
                api_anchors=args.api_anchor,
            )
            summary = {"status": receipt["status"], **receipt["counts"]}
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(json.dumps({"ok": False, "error_type": type(error).__name__, "error": str(error)}))
        return 1
    print(json.dumps({"ok": True, **summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
