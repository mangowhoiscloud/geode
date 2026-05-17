"""Prepare a Hugging Face dataset-repo release bundle for GEODE.

The bundle is intentionally not a model repository. GEODE publishes Python
package artifacts and release metadata to a Hub dataset repo so downstream
agents can discover, download, and verify immutable CLI release files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path


def is_distribution_artifact(path: Path) -> bool:
    """Return True for Python release files that should be published."""
    return path.is_file() and (path.name.endswith(".whl") or path.name.endswith(".tar.gz"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _read_checksums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise SystemExit(f"invalid checksum row in {path}:{line_no}")
        digest, artifact_path = parts
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise SystemExit(f"invalid sha256 digest in {path}:{line_no}")
        name = Path(artifact_path.removeprefix("*")).name
        if name in checksums:
            raise SystemExit(f"duplicate checksum artifact in {path}:{line_no}: {name}")
        checksums[name] = digest
    return checksums


def _repo_card(repo_id: str, version: str) -> str:
    return f"""---
license: apache-2.0
tags:
- geode
- release-artifacts
- autonomous-agents
- cli
- python
pretty_name: GEODE Release Artifacts
---

# GEODE Release Artifacts

This dataset repository stores GEODE CLI release artifacts and verification
metadata. It does not contain model weights.

## Layout

- `releases/v{version}/dist/` - wheel and source distribution files.
- `releases/v{version}/SHA256SUMS` - SHA-256 checksums for `dist/`.
- `releases/v{version}/release-notes.md` - release notes copied from
  `CHANGELOG.md`.
- `releases/v{version}/manifest.json` - machine-readable artifact manifest.
- `latest.json` - pointer to the latest uploaded GEODE release.

Install GEODE from PyPI as `geode-agent` or from the GitHub release. Use this
Hub repo as a mirrored artifact index for agent workflows and reproducibility
checks.

Repository: `{repo_id}`
"""


def prepare_bundle(
    *,
    version: str,
    repo_id: str,
    dist_dir: Path,
    release_notes: Path,
    checksums: Path,
    output_dir: Path,
    source_sha: str,
) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    release_root = output_dir / "releases" / f"v{version}"
    release_dist = release_root / "dist"
    release_dist.mkdir(parents=True)

    artifacts: list[dict[str, str | int]] = []
    for src in sorted(dist_dir.iterdir()):
        if not is_distribution_artifact(src):
            continue
        dst = release_dist / src.name
        _copy_file(src, dst)
        digest = _sha256(src)
        artifacts.append(
            {
                "name": src.name,
                "path": dst.relative_to(output_dir).as_posix(),
                "size": src.stat().st_size,
                "sha256": digest,
            }
        )

    if not artifacts:
        raise SystemExit(f"no release artifacts found in {dist_dir}")

    checksum_rows = _read_checksums(checksums)
    expected_checksums = {str(artifact["name"]): str(artifact["sha256"]) for artifact in artifacts}
    if checksum_rows != expected_checksums:
        raise SystemExit(
            "checksum file does not match dist artifacts: "
            f"expected {sorted(expected_checksums)}, got {sorted(checksum_rows)}"
        )

    _copy_file(release_notes, release_root / "release-notes.md")
    _copy_file(checksums, release_root / "SHA256SUMS")

    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    manifest = {
        "project": "geode",
        "version": version,
        "source_sha": source_sha,
        "repo_id": repo_id,
        "generated_at": generated_at,
        "artifacts": artifacts,
        "release_notes": f"releases/v{version}/release-notes.md",
        "checksums": f"releases/v{version}/SHA256SUMS",
    }
    (release_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "latest.json").write_text(
        json.dumps(
            {
                "project": "geode",
                "version": version,
                "manifest": f"releases/v{version}/manifest.json",
                "source_sha": source_sha,
                "generated_at": generated_at,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "README.md").write_text(_repo_card(repo_id, version), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--release-notes", type=Path, required=True)
    parser.add_argument("--checksums", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()

    prepare_bundle(
        version=args.version,
        repo_id=args.repo_id,
        dist_dir=args.dist_dir,
        release_notes=args.release_notes,
        checksums=args.checksums,
        output_dir=args.output_dir,
        source_sha=args.source_sha,
    )


if __name__ == "__main__":
    main()
