"""Behavioral contract for the curated ``plugins.*`` compatibility surface."""

from __future__ import annotations

import importlib
from importlib import resources
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGINS_ROOT = _REPO_ROOT / "plugins"

_DEEP_ALIASES = (
    ("plugins.benchmark_harness.cli", "geode_product.benchmark_harness.cli"),
    (
        "plugins.benchmark_harness.mcpmark_geode_agent",
        "geode_product.benchmark_harness.mcpmark_geode_agent",
    ),
    (
        "plugins.benchmark_harness.run_mcpmark",
        "geode_product.benchmark_harness.run_mcpmark",
    ),
    (
        "plugins.benchmark_harness.run_mcpmark_pair",
        "geode_product.benchmark_harness.run_mcpmark_pair",
    ),
    (
        "plugins.benchmark_harness.tau2_geode_agent",
        "geode_product.benchmark_harness.tau2_geode_agent",
    ),
    (
        "plugins.benchmark_harness.tau2_turn_supervisor",
        "geode_product.benchmark_harness.tau2_turn_supervisor",
    ),
    ("plugins.crucible.cli", "geode_product.crucible.cli"),
    ("plugins.crucible.prepare", "geode_product.crucible.prepare"),
    (
        "plugins.crucible.producers.replay",
        "geode_product.crucible.producers.replay",
    ),
    ("plugins.crucible.tau2_live", "geode_product.crucible.tau2_live"),
    ("plugins.petri_audit.cli", "geode_product.petri_audit.cli"),
    (
        "plugins.petri_audit.cli_agreement",
        "geode_product.petri_audit.cli_agreement",
    ),
    ("plugins.petri_audit.cli_audit", "geode_product.petri_audit.cli_audit"),
    (
        "plugins.petri_audit.geode_target",
        "geode_product.petri_audit.geode_target",
    ),
    ("plugins.petri_audit.runner", "geode_product.petri_audit.runner"),
    (
        "plugins.seed_generation.baseline_reader",
        "geode_product.seed_generation.baseline_reader",
    ),
    ("plugins.seed_generation.cli", "geode_product.seed_generation.cli"),
    (
        "plugins.seed_generation.tools.literature_snapshot",
        "geode_product.seed_generation.tools.literature_snapshot",
    ),
    (
        "plugins.seed_generation.tools.seed_debate",
        "geode_product.seed_generation.tools.seed_debate",
    ),
    (
        "plugins.seed_generation.tools.seed_pool_search",
        "geode_product.seed_generation.tools.seed_pool_search",
    ),
)

_IMPORT_ONLY_FACADES = frozenset(
    {
        "plugins",
        "plugins._compat",
        "plugins.benchmark_harness",
        "plugins.crucible",
        "plugins.crucible.producers",
        "plugins.petri_audit",
        "plugins.seed_generation",
        "plugins.seed_generation.tools",
    }
)
# Importing an ``__main__`` module correctly executes and exits its CLI, so it
# participates in the physical census but not the ordinary importability set.
_LAUNCH_ONLY_FACADES = frozenset({"plugins.crucible.__main__"})
_IMPORTABLE_FACADES = _IMPORT_ONLY_FACADES | {legacy for legacy, _ in _DEEP_ALIASES}
_PHYSICAL_FACADES = _IMPORTABLE_FACADES | _LAUNCH_ONLY_FACADES


def _physical_facade_modules() -> set[str]:
    modules: set[str] = set()
    for source_path in _PLUGINS_ROOT.rglob("*.py"):
        relative = source_path.relative_to(_REPO_ROOT).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules.add(".".join(parts))
    return modules


def test_curated_physical_facade_census_is_complete() -> None:
    assert len(_PHYSICAL_FACADES) == 29
    assert _physical_facade_modules() == _PHYSICAL_FACADES


@pytest.mark.parametrize("module_name", sorted(_IMPORTABLE_FACADES))
def test_curated_facade_is_importable(module_name: str) -> None:
    assert isinstance(importlib.import_module(module_name), ModuleType)


@pytest.mark.parametrize(("legacy", "canonical"), _DEEP_ALIASES)
def test_deep_alias_is_the_canonical_module(legacy: str, canonical: str) -> None:
    assert importlib.import_module(legacy) is importlib.import_module(canonical)


@pytest.mark.parametrize(
    ("package", "data_path"),
    (
        ("plugins.benchmark_harness", "tau2_agent_policy.md"),
        ("plugins.petri_audit", "petri.plugin.toml"),
        ("plugins.seed_generation", "seed_generation.plugin.toml"),
    ),
)
def test_legacy_package_resolves_canonical_data(package: str, data_path: str) -> None:
    assert resources.files(package).joinpath(data_path).is_file()


def test_unlisted_deep_module_is_not_an_implicit_facade() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("plugins.crucible.evidence")
