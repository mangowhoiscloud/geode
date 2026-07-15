"""Installation provenance and version bounds for ``geode update``.

The update command has two supported origins:

* a GEODE git checkout installed in editable mode; and
* the ``geode-agent`` package registered as a persistent uv tool.

PEP 610 metadata identifies direct/editable installs, while uv's receipt
identifies a persistent tool without relying on the caller's current working
directory.  This prevents ``geode update`` from treating an unrelated git
project as the GEODE source checkout.
"""

from __future__ import annotations

import importlib.metadata
import json
import re
import shlex
import sys
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import url2pathname

PACKAGE_NAME = "geode-agent"
_NORMALIZED_PACKAGE_NAME = "geode-agent"
_FINAL_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_STANDARD_TOOL_KEYS = {"requirements", "entrypoints"}
_STANDARD_REQUIREMENT_KEYS = {"name", "specifier"}
_STANDARD_EDITABLE_REQUIREMENT_KEYS = {"name", "editable"}
_SOURCE_REQUIREMENT_KEYS = ("editable", "directory", "git", "url", "path")


class UpdateKind(StrEnum):
    """Supported update origin."""

    SOURCE = "source"
    UV_TOOL = "uv-tool"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class UpdateTarget:
    """Detected installation origin and its source root, when applicable."""

    kind: UpdateKind
    source_root: Path | None = None
    reason: str = ""
    uv_tool_dir: Path | None = None
    uv_tool_bin_dir: Path | None = None


def patch_requirement(version: str) -> str:
    """Return the PEP 440 compatible-release bound for one patch series."""
    if not _FINAL_VERSION.fullmatch(version):
        raise ValueError(f"patch updates require a final X.Y.Z version, got {version!r}")
    return f"{PACKAGE_NAME}~={version}"


def _normalize_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _read_direct_url() -> dict[str, Any] | None:
    """Read the installed distribution's PEP 610 origin, when present."""
    try:
        raw = importlib.metadata.distribution(PACKAGE_NAME).read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        return None
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"invalid": True}
    return value if isinstance(value, dict) else {"invalid": True}


def _file_url_path(url: str) -> Path | None:
    parsed = urlsplit(url)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        return None
    return Path(url2pathname(parsed.path)).expanduser().resolve()


def _is_geode_source_root(path: Path) -> bool:
    """Require both GEODE package metadata and a real git checkout."""
    pyproject = path / "pyproject.toml"
    if not pyproject.is_file() or not (path / ".git").exists():
        return False
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    project = data.get("project")
    if not isinstance(project, dict):
        return False
    name = str(project.get("name", ""))
    return _normalize_distribution_name(name) == _NORMALIZED_PACKAGE_NAME


def _unsupported_uv_receipt(reason: str) -> UpdateTarget:
    return UpdateTarget(
        UpdateKind.UNSUPPORTED,
        reason=f"Cannot update this uv tool automatically: {reason}",
    )


def _custom_receipt_reason(requirement: dict[str, Any], receipt: Path) -> str:
    """Describe a provenance-preserving manual recovery for a custom receipt."""
    settings = (
        "the install has extras, additional requirements, constraints, a custom Python, "
        "or resolver settings."
    )
    source_key = next((key for key in _SOURCE_REQUIREMENT_KEYS if key in requirement), None)
    source = requirement.get(source_key) if source_key is not None else None
    if source_key is not None and isinstance(source, str) and source:
        return (
            f"{settings} Preserve the recorded {source_key} source {json.dumps(source)}. "
            f"Inspect `{receipt}` and rerun `uv tool install` with that source plus every "
            "recorded option; do not replace it with a registry requirement."
        )

    extras = requirement.get("extras")
    extra_suffix = ""
    if isinstance(extras, list) and all(isinstance(extra, str) for extra in extras):
        extra_suffix = f"[{','.join(extras)}]"
    try:
        version = importlib.metadata.version(PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        version = ""
    if _FINAL_VERSION.fullmatch(version):
        package_requirement = f"{PACKAGE_NAME}{extra_suffix}~={version}"
    else:
        specifier = requirement.get("specifier")
        package_requirement = (
            f"{PACKAGE_NAME}{extra_suffix}{specifier}"
            if isinstance(specifier, str) and specifier
            else f"{PACKAGE_NAME}{extra_suffix}"
        )
    base_command = shlex.join(["uv", "tool", "install", "--force", package_requirement])
    return (
        f"{settings} Inspect `{receipt}`, then start from `{base_command}` and reapply every "
        "recorded option before running it."
    )


def _detect_uv_tool(
    prefix: Path,
    *,
    editable_source: Path | None = None,
) -> UpdateTarget | None:
    """Classify an independently installed ``geode-agent`` uv tool.

    A plain editable receipt may select ``SOURCE`` only when PEP 610 metadata
    independently identifies the same checkout.  Any other receipt settings
    are rejected before source classification so rebuilding cannot discard
    extras, an explicit Python request, or resolver options.
    """
    receipt = prefix / "uv-receipt.toml"
    if not receipt.is_file():
        return None
    try:
        data = tomllib.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return _unsupported_uv_receipt("its uv-receipt.toml is unreadable or invalid.")

    tool = data.get("tool")
    if not isinstance(tool, dict):
        return _unsupported_uv_receipt("its uv-receipt.toml has no valid [tool] table.")
    requirements = tool.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        return _unsupported_uv_receipt("its uv receipt has no target requirement.")

    target_requirement = requirements[0]
    if not isinstance(target_requirement, dict):
        return _unsupported_uv_receipt(
            "its legacy requirement format cannot be updated without losing metadata."
        )
    target_name = _normalize_distribution_name(str(target_requirement.get("name", "")))
    if target_name != _NORMALIZED_PACKAGE_NAME:
        return _unsupported_uv_receipt(
            "GEODE is an additional dependency of another tool, not its target package."
        )

    custom_tool_keys = set(tool) - _STANDARD_TOOL_KEYS
    requirement_keys = set(target_requirement)
    editable_value = target_requirement.get("editable")
    plain_editable = (
        editable_source is not None
        and len(requirements) == 1
        and not custom_tool_keys
        and requirement_keys == _STANDARD_EDITABLE_REQUIREMENT_KEYS
        and isinstance(editable_value, str)
        and Path(editable_value).expanduser().resolve() == editable_source
    )

    custom_requirement_keys = requirement_keys - _STANDARD_REQUIREMENT_KEYS
    standard_registry = (
        len(requirements) == 1 and not custom_tool_keys and not custom_requirement_keys
    )
    if not plain_editable and not standard_registry:
        return _unsupported_uv_receipt(_custom_receipt_reason(target_requirement, receipt))

    entrypoints = tool.get("entrypoints")
    if not isinstance(entrypoints, list) or not entrypoints:
        return _unsupported_uv_receipt("its uv receipt has no installed entrypoints.")
    bin_dirs: set[Path] = set()
    has_geode_entrypoint = False
    for entrypoint in entrypoints:
        if not isinstance(entrypoint, dict):
            return _unsupported_uv_receipt("its uv receipt has an invalid entrypoint.")
        name = entrypoint.get("name")
        install_path = entrypoint.get("install-path")
        if not isinstance(name, str) or not isinstance(install_path, str):
            return _unsupported_uv_receipt("its uv receipt has an invalid entrypoint path.")
        executable = Path(install_path).expanduser()
        if not executable.is_absolute():
            return _unsupported_uv_receipt("its uv receipt has a relative entrypoint path.")
        # Resolve the directory, not the executable: uv entrypoints are often
        # symlinks into the tool environment, while UV_TOOL_BIN_DIR must remain
        # the directory that owns the declared link.
        bin_dirs.add(executable.parent.resolve())
        if name == "geode" and executable.name == "geode":
            has_geode_entrypoint = True
    if not has_geode_entrypoint:
        return _unsupported_uv_receipt("its uv receipt has no valid geode entrypoint.")
    if len(bin_dirs) != 1:
        return _unsupported_uv_receipt("its uv entrypoints use multiple install directories.")

    uv_tool_dir = prefix.parent.resolve()
    uv_tool_bin_dir = bin_dirs.pop()
    if plain_editable:
        return UpdateTarget(
            UpdateKind.SOURCE,
            source_root=editable_source,
            uv_tool_dir=uv_tool_dir,
            uv_tool_bin_dir=uv_tool_bin_dir,
        )
    return UpdateTarget(
        UpdateKind.UV_TOOL,
        uv_tool_dir=uv_tool_dir,
        uv_tool_bin_dir=uv_tool_bin_dir,
    )


def detect_update_target(*, prefix: Path | None = None) -> UpdateTarget:
    """Detect an editable source checkout or persistent uv tool install."""
    direct_url = _read_direct_url()
    editable_source: Path | None = None
    if direct_url is not None:
        source = _file_url_path(str(direct_url.get("url", "")))
        dir_info = direct_url.get("dir_info")
        is_editable = isinstance(dir_info, dict) and dir_info.get("editable") is True
        if source is not None and is_editable and _is_geode_source_root(source):
            editable_source = source

    active_prefix = (prefix or Path(sys.prefix)).expanduser().resolve()
    uv_target = _detect_uv_tool(active_prefix, editable_source=editable_source)
    if uv_target is not None:
        if direct_url is None:
            return uv_target
        if uv_target.kind is not UpdateKind.UV_TOOL:
            return uv_target

    if direct_url is not None:
        if editable_source is not None and uv_target is None:
            return UpdateTarget(UpdateKind.SOURCE, source_root=editable_source)
        return UpdateTarget(
            UpdateKind.UNSUPPORTED,
            reason=(
                "This GEODE install comes from a direct file, URL, or VCS source. "
                "Reinstall that source explicitly instead of switching it to PyPI."
            ),
        )

    return UpdateTarget(
        UpdateKind.UNSUPPORTED,
        reason=(
            "GEODE has neither editable PEP 610 metadata nor a registered uv tool receipt. "
            "Reinstall it with `uv tool install geode-agent` or `uv tool install -e .`."
        ),
    )
