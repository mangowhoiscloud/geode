"""Manifest loader for public benchmark harness coordinates."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = Path(__file__).with_name("benchmark_harness.plugin.toml")


@dataclass(frozen=True)
class HarnessSpec:
    name: str
    repo: str
    commit: str
    local_dir: str
    python: str
    install: tuple[str, ...]
    healthcheck: tuple[str, ...]
    public_adapter: str
    required_env: tuple[str, ...]
    optional_env: tuple[str, ...]

    @property
    def checkout_path(self) -> Path:
        return REPO_ROOT / "artifacts" / "eval" / "harnesses" / self.local_dir


def _string_tuple(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError("manifest list value must contain only strings")
    return tuple(raw)


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, HarnessSpec]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    root = data.get("benchmark_harness", {})
    raw_harnesses = root.get("harness", {})
    if not isinstance(raw_harnesses, dict):
        raise ValueError("benchmark_harness.harness must be a table")

    specs: dict[str, HarnessSpec] = {}
    for name, raw_spec in raw_harnesses.items():
        if not isinstance(raw_spec, dict):
            raise ValueError(f"harness {name!r} must be a table")
        specs[name] = HarnessSpec(
            name=name,
            repo=str(raw_spec["repo"]),
            commit=str(raw_spec["commit"]),
            local_dir=str(raw_spec["local_dir"]),
            python=str(raw_spec.get("python", "python3.12")),
            install=_string_tuple(raw_spec.get("install")),
            healthcheck=_string_tuple(raw_spec.get("healthcheck")),
            public_adapter=str(raw_spec["public_adapter"]),
            required_env=_string_tuple(raw_spec.get("required_env")),
            optional_env=_string_tuple(raw_spec.get("optional_env")),
        )
    return specs


BENCHMARK_HARNESSES = load_manifest()


def get_harness(name: str) -> HarnessSpec:
    try:
        return BENCHMARK_HARNESSES[name]
    except KeyError as exc:
        known = ", ".join(sorted(BENCHMARK_HARNESSES))
        raise KeyError(f"unknown benchmark harness {name!r}; known: {known}") from exc
