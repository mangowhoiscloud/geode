"""Manifest loader for pinned upstream benchmark coordinates."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = Path(__file__).with_name("benchmark_harness.plugin.toml")


@dataclass(frozen=True)
class BenchmarkSpec:
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


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, BenchmarkSpec]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    root = data.get("benchmark_harness", {})
    raw_benchmarks = root.get("benchmark", root.get("harness", {}))
    if not isinstance(raw_benchmarks, dict):
        raise ValueError("benchmark_harness.benchmark must be a table")

    specs: dict[str, BenchmarkSpec] = {}
    for name, raw_spec in raw_benchmarks.items():
        if not isinstance(raw_spec, dict):
            raise ValueError(f"benchmark {name!r} must be a table")
        specs[name] = BenchmarkSpec(
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


BENCHMARKS = load_manifest()


def get_benchmark(name: str) -> BenchmarkSpec:
    try:
        return BENCHMARKS[name]
    except KeyError as exc:
        known = ", ".join(sorted(BENCHMARKS))
        raise KeyError(f"unknown benchmark {name!r}; known: {known}") from exc


HarnessSpec = BenchmarkSpec  # v1.0.x compatibility
BENCHMARK_HARNESSES = BENCHMARKS
get_harness = get_benchmark
