"""Verify one GEODE release across GitHub and the public PyPI index.

The verifier is intentionally standard-library only so the release workflow can
run it in a small read-only job.  Public package indexes and release-asset CDNs
can converge a few seconds apart, so the command retries a complete snapshot
before declaring the immutable channels inconsistent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from typing import Any, cast
from urllib.parse import urlsplit

DEFAULT_REPOSITORY = "mangowhoiscloud/geode"
PACKAGE_NAME = "geode-agent"
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[A-Za-z0-9.-]+)?$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_HOSTS = frozenset({"api.github.com", "github.com", "pypi.org"})


class DistributionVerificationError(RuntimeError):
    """Raised when public release channels disagree."""


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise DistributionVerificationError(message)


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DistributionVerificationError(f"{label} must be a JSON object")
    return cast(dict[str, Any], value)


def _items(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise DistributionVerificationError(f"{label} must be a JSON array")
    return cast(list[object], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise DistributionVerificationError(f"{label} must be a string")
    return value


def parse_checksum_manifest(payload: bytes | str) -> dict[str, str]:
    """Parse a sha256sum manifest without retaining line terminators."""

    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    checksums: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise DistributionVerificationError(
                f"SHA256SUMS line {line_number} must contain a digest and filename"
            )
        digest, filename = parts
        filename = filename.removeprefix("*")
        if not _SHA256_RE.fullmatch(digest):
            raise DistributionVerificationError(
                f"SHA256SUMS line {line_number} has an invalid SHA-256"
            )
        if not filename or filename in checksums:
            raise DistributionVerificationError(
                f"SHA256SUMS line {line_number} has an empty or duplicate filename"
            )
        checksums[filename] = digest
    if not checksums:
        raise DistributionVerificationError("SHA256SUMS is empty")
    return checksums


def verify_metadata(
    *,
    version: str,
    source_sha: str,
    pypi: dict[str, Any],
    release: dict[str, Any],
    tag_ref: dict[str, Any],
    tag: dict[str, Any],
    checksums: dict[str, str],
) -> None:
    """Verify an already-fetched public release snapshot."""

    wheel = f"geode_agent-{version}-py3-none-any.whl"
    sdist = f"geode_agent-{version}.tar.gz"
    package_files = {wheel, sdist}

    info = _object(pypi.get("info"), "PyPI info")
    _expect(
        info.get("version") == version,
        f"PyPI release version is {info.get('version')!r}, expected {version!r}",
    )
    pypi_urls = [_object(item, "PyPI file") for item in _items(pypi.get("urls"), "PyPI urls")]
    pypi_files = {_string(item.get("filename"), "PyPI filename") for item in pypi_urls}
    _expect(
        pypi_files == package_files and len(pypi_urls) == len(package_files),
        f"PyPI files are {sorted(pypi_files)}, expected {sorted(package_files)}",
    )

    _expect(release.get("tag_name") == f"v{version}", "GitHub release tag is incorrect")
    _expect(release.get("draft") is False, "GitHub release is still a draft")
    _expect(release.get("prerelease") is False, "GitHub release is a prerelease")
    release_asset_items = [
        _object(item, "GitHub release asset")
        for item in _items(release.get("assets"), "GitHub release assets")
    ]
    release_assets = {
        _string(item.get("name"), "GitHub release asset name") for item in release_asset_items
    }
    expected_assets = package_files | {"SHA256SUMS"}
    _expect(
        release_assets == expected_assets and len(release_asset_items) == len(expected_assets),
        f"GitHub release assets are {sorted(release_assets)}, expected {sorted(expected_assets)}",
    )

    tag_ref_object = _object(tag_ref.get("object"), "annotated tag ref object")
    _expect(tag_ref_object.get("type") == "tag", "release ref is not an annotated tag")
    tag_object = _object(tag.get("object"), "annotated tag target")
    _expect(tag_object.get("type") == "commit", "annotated tag does not target a commit")
    _expect(
        tag_object.get("sha") == source_sha,
        f"annotated tag targets {tag_object.get('sha')!r}, expected {source_sha!r}",
    )

    _expect(
        set(checksums) == package_files,
        f"SHA256SUMS files are {sorted(checksums)}, expected {sorted(package_files)}",
    )
    for item in pypi_urls:
        filename = _string(item.get("filename"), "PyPI filename")
        digests = _object(item.get("digests"), f"PyPI digests for {filename}")
        _expect(
            digests.get("sha256") == checksums[filename],
            f"PyPI and GitHub SHA-256 differ for {filename}",
        )


def _request(url: str, *, token: str | None = None, accept: str) -> bytes:
    parsed = urlsplit(url)
    _expect(
        parsed.scheme == "https"
        and parsed.hostname in _ALLOWED_HOSTS
        and parsed.username is None
        and parsed.password is None,
        f"refusing non-public distribution URL: {url!r}",
    )
    headers = {
        "Accept": accept,
        "User-Agent": "geode-public-distribution-verifier/1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        payload = response.read()
    if not isinstance(payload, bytes):
        raise DistributionVerificationError(f"{url} returned a non-byte response")
    return payload


def _json(url: str, *, token: str | None = None) -> dict[str, Any]:
    payload = _request(url, token=token, accept="application/vnd.github+json")
    parsed = json.loads(payload)
    return _object(parsed, url)


def verify_public_distribution(
    *,
    version: str,
    repository: str,
    source_sha: str,
    token: str | None,
) -> None:
    """Fetch and verify one complete public distribution snapshot."""

    pypi = _json(f"https://pypi.org/pypi/{PACKAGE_NAME}/{version}/json")
    release = _json(
        f"https://api.github.com/repos/{repository}/releases/tags/v{version}",
        token=token,
    )
    tag_ref = _json(
        f"https://api.github.com/repos/{repository}/git/ref/tags/v{version}",
        token=token,
    )
    tag_ref_object = _object(tag_ref.get("object"), "annotated tag ref object")
    tag_sha = tag_ref_object.get("sha")
    _expect(isinstance(tag_sha, str), "annotated tag object SHA is missing")
    tag = _json(
        f"https://api.github.com/repos/{repository}/git/tags/{tag_sha}",
        token=token,
    )
    manifest = _request(
        f"https://github.com/{repository}/releases/download/v{version}/SHA256SUMS",
        accept="application/octet-stream",
    )
    verify_metadata(
        version=version,
        source_sha=source_sha,
        pypi=pypi,
        release=release,
        tag_ref=tag_ref,
        tag=tag,
        checksums=parse_checksum_manifest(manifest),
    )


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--attempts", type=_positive_int, default=12)
    parser.add_argument("--retry-delay", type=_non_negative_float, default=5.0)
    args = parser.parse_args()

    if not _VERSION_RE.fullmatch(args.version):
        parser.error(f"invalid version: {args.version!r}")
    if not _SHA_RE.fullmatch(args.source_sha):
        parser.error("source SHA must be a lowercase 40-character commit SHA")
    if args.repository.count("/") != 1:
        parser.error("repository must use the owner/name form")

    token = os.environ.get("GH_TOKEN")
    last_error: Exception | None = None
    for attempt in range(1, args.attempts + 1):
        try:
            verify_public_distribution(
                version=args.version,
                repository=args.repository,
                source_sha=args.source_sha,
                token=token,
            )
        except (DistributionVerificationError, OSError, ValueError) as error:
            last_error = error
            if attempt == args.attempts:
                break
            print(
                f"public distribution snapshot {attempt}/{args.attempts} failed: {error}; "
                f"retrying in {args.retry_delay:g}s",
                file=sys.stderr,
            )
            time.sleep(args.retry_delay)
        else:
            print(
                f"verified {PACKAGE_NAME} {args.version}: annotated tag, GitHub assets, "
                "PyPI files, and SHA-256 digests agree"
            )
            return
    raise SystemExit(
        f"public distribution verification failed after {args.attempts} attempts: {last_error}"
    )


if __name__ == "__main__":
    main()
