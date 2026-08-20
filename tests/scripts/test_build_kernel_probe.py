from __future__ import annotations

import base64
import csv
import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from scripts import build_kernel_probe as probe

DIST_INFO = "geode_agent-1.0.0.dist-info"


def _wheel(path: Path, *, include_metadata: bool = True) -> None:
    files = {
        "core/__init__.py": b"",
        "core/agent/runtime.py": b"KERNEL = True\n",
        "core/self_improving/__init__.py": b"FEATURE = True\n",
        "geode_product/__init__.py": b"",
        "plugins/__init__.py": b"",
        f"{DIST_INFO}/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{DIST_INFO}/entry_points.txt": b"[console_scripts]\ngeode = geode_product.cli:app\n",
        f"{DIST_INFO}/licenses/LICENSE": b"license\n",
        f"{DIST_INFO}/direct_url.json": b"{}",
        f"{DIST_INFO}/RECORD": b"stale,sha256=stale,5\n",
    }
    if include_metadata:
        files[f"{DIST_INFO}/METADATA"] = (
            b"Metadata-Version: 2.4\nName: geode-agent\nVersion: 1.0.0\n"
        )
    with zipfile.ZipFile(path, "w") as wheel:
        for name, data in files.items():
            wheel.writestr(name, data)


def test_build_kernel_probe_keeps_only_kernel_and_minimal_metadata(tmp_path: Path) -> None:
    source = tmp_path / "base" / "geode_agent-1.0.0-py3-none-any.whl"
    source.parent.mkdir()
    _wheel(source)
    output = tmp_path / "probe" / source.name

    probe.build_kernel_probe(source, output)

    with zipfile.ZipFile(output) as wheel:
        names = set(wheel.namelist())
        assert names == {
            "core/__init__.py",
            "core/agent/runtime.py",
            f"{DIST_INFO}/METADATA",
            f"{DIST_INFO}/WHEEL",
            f"{DIST_INFO}/licenses/LICENSE",
            f"{DIST_INFO}/RECORD",
        }
        rows = list(csv.reader(io.TextIOWrapper(wheel.open(f"{DIST_INFO}/RECORD"))))
        by_path = {row[0]: row[1:] for row in rows}
        for name in names - {f"{DIST_INFO}/RECORD"}:
            data = wheel.read(name)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
            assert by_path[name] == [f"sha256={digest.decode('ascii')}", str(len(data))]
        assert by_path[f"{DIST_INFO}/RECORD"] == ["", ""]


def test_build_kernel_probe_requires_wheel_metadata(tmp_path: Path) -> None:
    source = tmp_path / "geode_agent-1.0.0-py3-none-any.whl"
    _wheel(source, include_metadata=False)

    with pytest.raises(ValueError, match="METADATA"):
        probe.build_kernel_probe(source, tmp_path / "probe" / source.name)


def test_build_kernel_probe_rejects_public_dist_output(tmp_path: Path) -> None:
    source = tmp_path / "geode_agent-1.0.0-py3-none-any.whl"
    _wheel(source)

    with pytest.raises(ValueError, match="must not be written"):
        probe.build_kernel_probe(source, probe.REPO_ROOT / "dist" / source.name)
