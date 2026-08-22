"""Smoke-test GEODE from an installed wheel, outside the source tree."""

from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
import tempfile
from importlib import metadata, resources
from importlib.util import find_spec
from pathlib import Path, PurePosixPath
from unittest.mock import Mock


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


def _check_full_package() -> None:
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
    distribution = metadata.distribution("geode-agent")
    for skill in ("geo", "grilling"):
        skill_path = distribution.locate_file(f".geode/skills/{skill}/SKILL.md")
        assert Path(str(skill_path)).is_file()

    print("installed package OK")


def _kernel_record_paths() -> frozenset[str]:
    matches: list[tuple[metadata.Distribution, frozenset[str]]] = []
    for distribution in metadata.distributions():
        files = distribution.files
        if files is None:
            continue
        paths = frozenset(file.as_posix() for file in files)
        if "core/__init__.py" in paths:
            matches.append((distribution, paths))

    assert len(matches) == 1, f"expected one distribution owning core, found {len(matches)}"
    distribution, paths = matches[0]
    forbidden = ("geode_product/", "plugins/", "core/self_improving/")
    leaked = sorted(path for path in paths if path.startswith(forbidden))
    assert not leaked, f"kernel wheel contains feature files: {leaked}"
    assert not distribution.entry_points, "kernel wheel contains package entry points"
    assert not any(path.endswith(".dist-info/entry_points.txt") for path in paths)
    return paths


def _core_module_names(paths: frozenset[str]) -> tuple[str, ...]:
    modules: set[str] = set()
    for path in paths:
        source = PurePosixPath(path)
        if not source.parts or source.parts[0] != "core" or source.suffix != ".py":
            continue
        parts = list(source.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        assert parts and all(part.isidentifier() for part in parts), f"invalid module path: {path}"
        modules.add(".".join(parts))
    assert modules, "kernel wheel contains no Python modules"
    return tuple(sorted(modules))


def _import_core_modules(modules: tuple[str, ...], *, cwd: Path, geode_home: Path) -> None:
    env = {**os.environ, "GEODE_HOME": str(geode_home)}
    for module in modules:
        result = subprocess.run(  # noqa: S603 -- executable is the current interpreter
            [
                sys.executable,
                "-I",
                "-c",
                f"import importlib; importlib.import_module({module!r})",
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
            timeout=30,
        )
        assert result.returncode == 0, f"isolated import failed for {module}: {result.stderr}"


def _check_kernel_runtime() -> None:
    from core.hooks import HookRegistry, MiddlewareRegistry
    from core.llm.adapters import bootstrap_builtins, list_adapters
    from core.runtime import GeodeRuntime, RuntimeCoreConfig
    from core.tools.policy import PolicyChain
    from core.wiring.container import build_default_registry

    events = Mock()
    hooks = HookRegistry(events=events)
    middleware = MiddlewareRegistry(events=events)
    tools = build_default_registry()
    tool_names = tools.list_tools()
    assert tool_names
    assert all(
        (tool := tools.get(name)) is not None and type(tool).__module__.startswith("core.")
        for name in tool_names
    )
    assert hooks.list_hooks() == {}

    bootstrap_builtins()
    adapters = list_adapters()
    assert adapters
    assert all(type(adapter).__module__.startswith("core.") for adapter in adapters)

    config_watcher = Mock()
    runtime = GeodeRuntime(
        RuntimeCoreConfig(
            hooks=events,
            hook_registry=hooks,
            middleware_registry=middleware,
            session_store=Mock(),
            policy_chain=PolicyChain(),
            tool_registry=tools,
            event_store=Mock(),
            hook_metrics=Mock(),
            config_watcher=config_watcher,
            lane_queue=Mock(),
            project_memory=Mock(),
            session_key="kernel-probe:analysis",
            subject_id="kernel-probe",
        )
    )
    runtime.shutdown()
    runtime.shutdown()
    config_watcher.stop.assert_called_once_with()
    events.close.assert_called_once_with()


def _check_kernel_package() -> None:
    modules = _core_module_names(_kernel_record_paths())
    for feature in ("geode_product", "plugins", "core.self_improving"):
        assert find_spec(feature) is None, f"kernel environment exposes {feature}"
    previous_cwd = Path.cwd()
    previous_geode_home = os.environ.get("GEODE_HOME")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        geode_home = root / "geode-home"
        geode_home.mkdir()
        try:
            os.chdir(root)
            os.environ["GEODE_HOME"] = str(geode_home)
            _import_core_modules(modules, cwd=root, geode_home=geode_home)
            _check_kernel_runtime()
        finally:
            os.chdir(previous_cwd)
            if previous_geode_home is None:
                os.environ.pop("GEODE_HOME", None)
            else:
                os.environ["GEODE_HOME"] = previous_geode_home
    print(f"installed kernel package OK ({len(modules)} modules)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-only", action="store_true")
    args = parser.parse_args(argv)
    if args.kernel_only:
        _check_kernel_package()
    else:
        _check_full_package()


if __name__ == "__main__":
    main()
