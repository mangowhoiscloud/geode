"""Installation-origin guards for ``geode update``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from core.cli.update_provenance import (
    UpdateKind,
    detect_update_target,
    patch_requirement,
)


def _make_geode_checkout(path: Path) -> Path:
    path.mkdir()
    (path / ".git").mkdir()
    (path / "pyproject.toml").write_text(
        '[project]\nname = "geode-agent"\nversion = "0.99.333"\n',
        encoding="utf-8",
    )
    return path


def _entrypoints_toml(bin_dir: Path) -> str:
    executable = (bin_dir / "geode").as_posix()
    return (
        "entrypoints = ["
        f'{{ name = "geode", install-path = "{executable}", from = "geode-agent" }}'
        "]\n"
    )


def test_patch_requirement_locks_major_minor() -> None:
    assert patch_requirement("0.99.333") == "geode-agent~=0.99.333"
    assert patch_requirement("1.2.3") == "geode-agent~=1.2.3"


@pytest.mark.parametrize("version", ["0.99", "0.99.333rc1", "latest", ""])
def test_patch_requirement_rejects_non_final_versions(version: str) -> None:
    with pytest.raises(ValueError, match=r"final X\.Y\.Z"):
        patch_requirement(version)


def test_editable_direct_url_selects_recorded_source(tmp_path: Path) -> None:
    checkout = _make_geode_checkout(tmp_path / "GEODE source")

    with patch(
        "core.cli.update_provenance._read_direct_url",
        return_value={"url": checkout.as_uri(), "dir_info": {"editable": True}},
    ):
        target = detect_update_target(prefix=tmp_path / "not-a-tool")

    assert target.kind is UpdateKind.SOURCE
    assert target.source_root == checkout.resolve()


def test_plain_editable_uv_receipt_selects_source(tmp_path: Path) -> None:
    checkout = _make_geode_checkout(tmp_path / "geode")
    prefix = tmp_path / "tool"
    bin_dir = tmp_path / "bin"
    prefix.mkdir()
    (prefix / "uv-receipt.toml").write_text(
        "[tool]\n"
        f'requirements = [{{ name = "geode-agent", editable = "{checkout.as_posix()}" }}]\n'
        + _entrypoints_toml(bin_dir),
        encoding="utf-8",
    )

    with patch(
        "core.cli.update_provenance._read_direct_url",
        return_value={"url": checkout.as_uri(), "dir_info": {"editable": True}},
    ):
        target = detect_update_target(prefix=prefix)

    assert target.kind is UpdateKind.SOURCE
    assert target.source_root == checkout.resolve()
    assert target.uv_tool_dir == tmp_path.resolve()
    assert target.uv_tool_bin_dir == bin_dir.resolve()


def test_custom_editable_uv_receipt_is_rejected_before_source_update(tmp_path: Path) -> None:
    checkout = _make_geode_checkout(tmp_path / "geode")
    prefix = tmp_path / "tool"
    prefix.mkdir()
    (prefix / "uv-receipt.toml").write_text(
        "[tool]\n"
        "requirements = ["
        f'{{ name = "geode-agent", extras = ["audit"], editable = "{checkout.as_posix()}" }}'
        "]\n"
        'python = "3.12"\n'
        "entrypoints = []\n",
        encoding="utf-8",
    )

    with patch(
        "core.cli.update_provenance._read_direct_url",
        return_value={"url": checkout.as_uri(), "dir_info": {"editable": True}},
    ):
        target = detect_update_target(prefix=prefix)

    assert target.kind is UpdateKind.UNSUPPORTED
    assert checkout.as_posix() in target.reason
    assert str(prefix / "uv-receipt.toml") in target.reason
    assert "registry requirement" in target.reason
    assert "geode-agent~=" not in target.reason


def test_noneditable_local_direct_url_is_not_treated_as_source(tmp_path: Path) -> None:
    checkout = _make_geode_checkout(tmp_path / "geode")
    prefix = tmp_path / "tool"
    prefix.mkdir()
    (prefix / "uv-receipt.toml").write_text(
        "[tool]\n"
        f'requirements = [{{ name = "geode-agent", directory = "{checkout.as_posix()}" }}]\n'
        "entrypoints = []\n",
        encoding="utf-8",
    )

    with patch(
        "core.cli.update_provenance._read_direct_url",
        return_value={"url": checkout.as_uri(), "dir_info": {}},
    ):
        target = detect_update_target(prefix=prefix)

    assert target.kind is UpdateKind.UNSUPPORTED
    assert target.source_root is None
    assert checkout.as_posix() in target.reason
    assert str(prefix / "uv-receipt.toml") in target.reason
    assert "geode-agent~=" not in target.reason


def test_noneditable_direct_url_without_receipt_requires_reinstall(tmp_path: Path) -> None:
    checkout = _make_geode_checkout(tmp_path / "geode")

    with patch(
        "core.cli.update_provenance._read_direct_url",
        return_value={"url": checkout.as_uri(), "dir_info": {"editable": False}},
    ):
        target = detect_update_target(prefix=tmp_path / "not-a-tool")

    assert target.kind is UpdateKind.UNSUPPORTED
    assert target.source_root is None
    assert "direct file, URL, or VCS" in target.reason


def test_registered_uv_tool_receipt_selects_package_update(tmp_path: Path) -> None:
    prefix = tmp_path / "tool"
    bin_dir = tmp_path / "custom-bin"
    prefix.mkdir()
    (prefix / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "geode-agent", specifier = "==0.99.331" }]\n'
        + _entrypoints_toml(bin_dir),
        encoding="utf-8",
    )

    with patch("core.cli.update_provenance._read_direct_url", return_value=None):
        target = detect_update_target(prefix=prefix)

    assert target.kind is UpdateKind.UV_TOOL
    assert target.source_root is None
    assert target.uv_tool_dir == tmp_path.resolve()
    assert target.uv_tool_bin_dir == bin_dir.resolve()


def test_entrypoint_symlink_preserves_declared_bin_directory(tmp_path: Path) -> None:
    prefix = tmp_path / "tools" / "geode-agent"
    target_bin = prefix / "bin"
    target_bin.mkdir(parents=True)
    target = target_bin / "geode"
    target.write_text("", encoding="utf-8")
    declared_bin = tmp_path / "custom-bin"
    declared_bin.mkdir()
    (declared_bin / "geode").symlink_to(target)
    (prefix / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "geode-agent" }]\n' + _entrypoints_toml(declared_bin),
        encoding="utf-8",
    )

    with patch("core.cli.update_provenance._read_direct_url", return_value=None):
        update_target = detect_update_target(prefix=prefix)

    assert update_target.kind is UpdateKind.UV_TOOL
    assert update_target.uv_tool_bin_dir == declared_bin.resolve()
    assert update_target.uv_tool_bin_dir != target_bin.resolve()


def test_standard_uv_receipt_requires_entrypoint_directory(tmp_path: Path) -> None:
    prefix = tmp_path / "tool"
    prefix.mkdir()
    (prefix / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "geode-agent" }]\nentrypoints = []\n',
        encoding="utf-8",
    )

    with patch("core.cli.update_provenance._read_direct_url", return_value=None):
        target = detect_update_target(prefix=prefix)

    assert target.kind is UpdateKind.UNSUPPORTED
    assert "no installed entrypoints" in target.reason


def test_standard_uv_receipt_requires_geode_entrypoint(tmp_path: Path) -> None:
    prefix = tmp_path / "tool"
    prefix.mkdir()
    (prefix / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "geode-agent" }]\n'
        "entrypoints = ["
        f'{{ name = "other", install-path = "{tmp_path / "bin" / "other"}" }}'
        "]\n",
        encoding="utf-8",
    )

    with patch("core.cli.update_provenance._read_direct_url", return_value=None):
        target = detect_update_target(prefix=prefix)

    assert target.kind is UpdateKind.UNSUPPORTED
    assert "no valid geode entrypoint" in target.reason


def test_unrelated_uv_receipt_is_not_accepted(tmp_path: Path) -> None:
    prefix = tmp_path / "tool"
    prefix.mkdir()
    (prefix / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "ruff", specifier = ">=0.6" }]\n',
        encoding="utf-8",
    )

    with patch("core.cli.update_provenance._read_direct_url", return_value=None):
        target = detect_update_target(prefix=prefix)

    assert target.kind is UpdateKind.UNSUPPORTED
    assert "additional dependency of another tool" in target.reason


@pytest.mark.parametrize(
    "custom_receipt",
    [
        """[tool]
requirements = [
    { name = "geode-agent", specifier = "==0.99.331" },
    { name = "ipython", specifier = ">=9" },
]
entrypoints = []
""",
        """[tool]
requirements = [{ name = "geode-agent", extras = ["audit"] }]
entrypoints = []
""",
        """[tool]
requirements = [{ name = "geode-agent" }]
python = "3.12"
entrypoints = []
""",
        """[tool]
requirements = [{ name = "geode-agent" }]
entrypoints = []
[tool.options]
prerelease = "allow"
""",
    ],
)
def test_custom_uv_install_is_rejected_instead_of_losing_metadata(
    tmp_path: Path,
    custom_receipt: str,
) -> None:
    prefix = tmp_path / "tool"
    prefix.mkdir()
    (prefix / "uv-receipt.toml").write_text(custom_receipt, encoding="utf-8")

    with patch("core.cli.update_provenance._read_direct_url", return_value=None):
        target = detect_update_target(prefix=prefix)

    assert target.kind is UpdateKind.UNSUPPORTED
    assert str(prefix / "uv-receipt.toml") in target.reason
    assert "reapply every" in target.reason
    assert "~=" in target.reason
    assert "X.Y.Z" not in target.reason


def test_invalid_uv_receipt_is_rejected_without_falling_back_to_cwd(tmp_path: Path) -> None:
    prefix = tmp_path / "tool"
    prefix.mkdir()
    (prefix / "uv-receipt.toml").write_text("[tool\n", encoding="utf-8")
    with patch("core.cli.update_provenance._read_direct_url", return_value=None):
        target = detect_update_target(prefix=prefix)

    assert target.kind is UpdateKind.UNSUPPORTED
    assert "unreadable or invalid" in target.reason


def test_vcs_install_does_not_silently_switch_to_pypi(tmp_path: Path) -> None:
    prefix = tmp_path / "tool"
    prefix.mkdir()
    (prefix / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "geode-agent" }]\n' + _entrypoints_toml(tmp_path / "bin"),
        encoding="utf-8",
    )

    with patch(
        "core.cli.update_provenance._read_direct_url",
        return_value={
            "url": "https://github.com/mangowhoiscloud/geode.git",
            "vcs_info": {"vcs": "git"},
        },
    ):
        target = detect_update_target(prefix=prefix)

    assert target.kind is UpdateKind.UNSUPPORTED
    assert "direct file, URL, or VCS" in target.reason


def test_metadata_free_install_does_not_fall_back_to_geode_cwd(tmp_path: Path) -> None:
    checkout = _make_geode_checkout(tmp_path / "geode")
    with patch("core.cli.update_provenance._read_direct_url", return_value=None):
        target = detect_update_target(prefix=tmp_path / "not-a-tool")

    assert checkout.is_dir()
    assert target.kind is UpdateKind.UNSUPPORTED
    assert "editable PEP 610 metadata" in target.reason


def test_arbitrary_git_checkout_is_rejected(tmp_path: Path) -> None:
    checkout = tmp_path / "other-project"
    checkout.mkdir()
    (checkout / ".git").mkdir()
    (checkout / "pyproject.toml").write_text(
        '[project]\nname = "not-geode"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )

    with patch("core.cli.update_provenance._read_direct_url", return_value=None):
        target = detect_update_target(prefix=tmp_path / "not-a-tool")

    assert target.kind is UpdateKind.UNSUPPORTED
    assert "editable PEP 610 metadata" in target.reason
