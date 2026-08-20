"""Smoke-test GEODE from an installed wheel, outside the source tree."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tempfile
from importlib import metadata, resources
from pathlib import Path


def _help_output(target: str | Path) -> str:
    command = [sys.executable, "-I"]
    if isinstance(target, Path):
        command.append(str(target))
    else:
        command.extend(("-m", target))
    command.append("--help")
    with tempfile.TemporaryDirectory() as geode_home:
        result = subprocess.run(  # noqa: S603 -- executable and targets are repository constants
            command,
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "GEODE_HOME": geode_home},
        )
    return result.stdout


def main() -> None:
    scripts = {entry.name: entry for entry in metadata.entry_points(group="console_scripts")}
    assert scripts["geode"].value == "geode_product.cli:app"
    assert scripts["geode-mcp"].value == "geode_product.mcp_server:main"
    scripts["geode-mcp"].load()
    importlib.import_module("geode_product.wiring")
    importlib.import_module("geode_product.worker")

    for leaf in ("train", "campaign", "prepare", "watch_campaign"):
        legacy = f"core.self_improving.{leaf}"
        canonical = f"geode_product.self_improving.{leaf}"
        assert _help_output(legacy) == _help_output(canonical)
        legacy_path = Path(str(resources.files("core").joinpath(f"self_improving/{leaf}.py")))
        canonical_path = Path(
            str(resources.files("geode_product.self_improving").joinpath(f"{leaf}.py"))
        )
        assert _help_output(legacy_path) == _help_output(canonical_path)

    for legacy, canonical in (
        (
            "plugins.benchmark_harness.mcpmark_geode_agent",
            "geode_product.benchmark_harness.mcpmark_geode_agent",
        ),
        ("plugins.petri_audit.runner", "geode_product.petri_audit.runner"),
        (
            "plugins.seed_generation.tools.seed_pool_search",
            "geode_product.seed_generation.tools.seed_pool_search",
        ),
        ("core.self_improving.train", "geode_product.self_improving.train"),
        ("core.self_improving.campaign", "geode_product.self_improving.campaign"),
        ("core.self_improving.prepare", "geode_product.self_improving.prepare"),
        (
            "core.self_improving.watch_campaign",
            "geode_product.self_improving.watch_campaign",
        ),
    ):
        assert importlib.import_module(legacy) is importlib.import_module(canonical)

    try:
        importlib.import_module("core.self_improving.loop")
    except ModuleNotFoundError:
        pass
    else:
        raise AssertionError("unlisted legacy self-improving module is importable")

    assert resources.files("plugins.petri_audit").joinpath("petri.plugin.toml").is_file()
    assert resources.files("geode_product.self_improving").joinpath("program.md").is_file()
    assert resources.files("core").joinpath("self_improving/state/results.tsv").is_file()

    print("installed package OK")


if __name__ == "__main__":
    main()
