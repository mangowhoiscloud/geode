from __future__ import annotations

import pytest
from scripts.verify_public_distribution import (
    DistributionVerificationError,
    parse_checksum_manifest,
    verify_metadata,
)

VERSION = "0.99.331"
SOURCE_SHA = "a" * 40
WHEEL = f"geode_agent-{VERSION}-py3-none-any.whl"
SDIST = f"geode_agent-{VERSION}.tar.gz"
WHEEL_SHA = "b" * 64
SDIST_SHA = "c" * 64


def _pypi_file(filename: str, digest: str) -> dict[str, object]:
    return {"filename": filename, "digests": {"sha256": digest}}


def test_checksum_manifest_drops_line_terminators() -> None:
    manifest = f"{WHEEL_SHA}  {WHEEL}\n{SDIST_SHA}  {SDIST}\n"

    assert parse_checksum_manifest(manifest) == {
        WHEEL: WHEEL_SHA,
        SDIST: SDIST_SHA,
    }


def test_checksum_manifest_rejects_duplicate_filename() -> None:
    manifest = f"{WHEEL_SHA}  {WHEEL}\n{SDIST_SHA}  {WHEEL}\n"

    with pytest.raises(DistributionVerificationError, match="duplicate filename"):
        parse_checksum_manifest(manifest)


def test_public_distribution_metadata_agrees() -> None:
    verify_metadata(
        version=VERSION,
        source_sha=SOURCE_SHA,
        pypi={
            "info": {"version": VERSION},
            "urls": [
                _pypi_file(WHEEL, WHEEL_SHA),
                _pypi_file(SDIST, SDIST_SHA),
            ],
        },
        release={
            "tag_name": f"v{VERSION}",
            "draft": False,
            "prerelease": False,
            "assets": [{"name": WHEEL}, {"name": SDIST}, {"name": "SHA256SUMS"}],
        },
        tag_ref={"object": {"type": "tag", "sha": "d" * 40}},
        tag={"object": {"type": "commit", "sha": SOURCE_SHA}},
        checksums={WHEEL: WHEEL_SHA, SDIST: SDIST_SHA},
    )


def test_public_distribution_reports_tag_target_mismatch() -> None:
    with pytest.raises(DistributionVerificationError, match="annotated tag targets"):
        verify_metadata(
            version=VERSION,
            source_sha=SOURCE_SHA,
            pypi={
                "info": {"version": VERSION},
                "urls": [
                    _pypi_file(WHEEL, WHEEL_SHA),
                    _pypi_file(SDIST, SDIST_SHA),
                ],
            },
            release={
                "tag_name": f"v{VERSION}",
                "draft": False,
                "prerelease": False,
                "assets": [
                    {"name": WHEEL},
                    {"name": SDIST},
                    {"name": "SHA256SUMS"},
                ],
            },
            tag_ref={"object": {"type": "tag", "sha": "d" * 40}},
            tag={"object": {"type": "commit", "sha": "e" * 40}},
            checksums={WHEEL: WHEEL_SHA, SDIST: SDIST_SHA},
        )
