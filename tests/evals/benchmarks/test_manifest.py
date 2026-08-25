from pathlib import Path

import evals.benchmarks as benchmark_api
from evals.benchmarks import manifest
from evals.benchmarks.env import env_status, missing_required, read_dotenv_status
from evals.benchmarks.manifest import BENCHMARKS, get_benchmark


def test_manifest_lists_pinned_benchmarks() -> None:
    assert set(BENCHMARKS) == {"mcpmark", "tau2-bench"}
    assert get_benchmark("mcpmark").public_adapter == "evals.benchmarks.mcpmark_geode_agent"
    assert get_benchmark("tau2-bench").public_adapter == "evolve.crucible.tau2_geode_agent"


def test_legacy_harness_names_alias_benchmark_coordinates(tmp_path: Path) -> None:
    assert benchmark_api.HarnessSpec is benchmark_api.BenchmarkSpec
    assert benchmark_api.BENCHMARK_HARNESSES is benchmark_api.BENCHMARKS
    assert benchmark_api.get_harness is benchmark_api.get_benchmark
    legacy = tmp_path / "legacy.toml"
    legacy.write_text(
        manifest.MANIFEST_PATH.read_text().replace(".benchmark.", ".harness."),
        encoding="utf-8",
    )
    assert set(manifest.load_manifest(legacy)) == set(BENCHMARKS)


def test_mcpmark_install_keeps_dependency_metadata_out_of_the_harness_checkout() -> None:
    spec = get_benchmark("mcpmark")
    assert spec.install[-1] == "uv sync --project ../../../.. --extra audit"
    assert ".venv/bin/pip install -e ../../../.." not in spec.install


def test_tau2_install_uses_the_pinned_lock_without_mutating_it() -> None:
    spec = get_benchmark("tau2-bench")
    assert spec.install == ("uv sync --frozen",)
    assert spec.healthcheck == ("LITELLM_LOCAL_MODEL_COST_MAP=true .venv/bin/tau2 check-data",)


def test_dotenv_status_is_redacted(tmp_path: Path) -> None:
    env_file = tmp_path / ".mcp_env"
    env_file.write_text("TOKEN=secret\nEMPTY=\n# COMMENT=yes\n", encoding="utf-8")
    assert read_dotenv_status(env_file) == {"TOKEN": True, "EMPTY": False}
    status = env_status(("TOKEN", "EMPTY", "MISSING"), dotenv_path=env_file)
    assert status == {"TOKEN": True, "EMPTY": False, "MISSING": False}
    assert missing_required(("TOKEN", "EMPTY"), dotenv_path=env_file) == ["EMPTY"]
