"""Tests for Hugging Face release bundle preparation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from scripts.prepare_hf_release_bundle import is_distribution_artifact, prepare_bundle


def test_distribution_artifact_filter(tmp_path: Path) -> None:
    wheel = tmp_path / "geode_agent-0.99.11-py3-none-any.whl"
    sdist = tmp_path / "geode_agent-0.99.11.tar.gz"
    dotfile = tmp_path / ".gitignore"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    dotfile.write_text("*\n", encoding="utf-8")

    assert is_distribution_artifact(wheel)
    assert is_distribution_artifact(sdist)
    assert not is_distribution_artifact(dotfile)


def test_prepare_bundle_creates_versioned_dataset_layout(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "geode_agent-0.99.11-py3-none-any.whl"
    sdist = dist / "geode_agent-0.99.11.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    (dist / ".gitignore").write_text("*\n", encoding="utf-8")

    notes = tmp_path / "release-notes.md"
    notes.write_text("release notes\n", encoding="utf-8")
    checksums = tmp_path / "SHA256SUMS"
    checksums.write_text(
        "\n".join(
            [
                f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  dist/{wheel.name}",
                f"{hashlib.sha256(sdist.read_bytes()).hexdigest()}  dist/{sdist.name}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    out = tmp_path / "hf-release"
    prepare_bundle(
        version="0.99.11",
        repo_id="example/geode-release-artifacts",
        dist_dir=dist,
        release_notes=notes,
        checksums=checksums,
        output_dir=out,
        source_sha="abc123",
    )

    release_root = out / "releases" / "v0.99.11"
    assert (out / "README.md").exists()
    assert (out / "latest.json").exists()
    assert (release_root / "dist" / wheel.name).read_bytes() == b"wheel"
    assert (release_root / "dist" / sdist.name).read_bytes() == b"sdist"
    assert not (release_root / "dist" / ".gitignore").exists()
    assert (release_root / "release-notes.md").read_text(encoding="utf-8") == "release notes\n"
    assert (release_root / "SHA256SUMS").read_text(encoding="utf-8") == checksums.read_text(
        encoding="utf-8"
    )

    manifest = json.loads((release_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["project"] == "geode"
    assert manifest["version"] == "0.99.11"
    assert manifest["source_sha"] == "abc123"
    assert {item["name"] for item in manifest["artifacts"]} == {wheel.name, sdist.name}
    assert all(item["sha256"] for item in manifest["artifacts"])

    latest = json.loads((out / "latest.json").read_text(encoding="utf-8"))
    assert latest["manifest"] == "releases/v0.99.11/manifest.json"


def test_prepare_bundle_rejects_mismatched_checksums(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "geode_agent-0.99.11-py3-none-any.whl"
    sdist = dist / "geode_agent-0.99.11.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")

    notes = tmp_path / "release-notes.md"
    notes.write_text("release notes\n", encoding="utf-8")
    checksums = tmp_path / "SHA256SUMS"
    checksums.write_text(
        "\n".join(
            [
                f"{'0' * 64}  dist/{wheel.name}",
                f"{hashlib.sha256(sdist.read_bytes()).hexdigest()}  dist/{sdist.name}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="checksum file does not match"):
        prepare_bundle(
            version="0.99.11",
            repo_id="example/geode-release-artifacts",
            dist_dir=dist,
            release_notes=notes,
            checksums=checksums,
            output_dir=tmp_path / "hf-release",
            source_sha="abc123",
        )
