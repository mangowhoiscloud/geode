from pathlib import Path

from plugins.benchmark_harness.env import env_status, missing_required, read_dotenv_status
from plugins.benchmark_harness.manifest import BENCHMARK_HARNESSES, get_harness


def test_manifest_lists_public_harnesses() -> None:
    assert set(BENCHMARK_HARNESSES) == {"mcpmark", "tau2-bench"}
    assert get_harness("mcpmark").public_adapter == "plugins.benchmark_harness.mcpmark_geode_agent"
    assert get_harness("tau2-bench").public_adapter == "plugins.benchmark_harness.tau2_geode_agent"


def test_manifest_uses_ignored_artifact_checkout_paths() -> None:
    spec = get_harness("mcpmark")
    assert spec.checkout_path.as_posix().endswith("artifacts/eval/harnesses/mcpmark")
    assert spec.repo == "https://github.com/eval-sys/mcpmark.git"


def test_dotenv_status_is_redacted(tmp_path: Path) -> None:
    env_file = tmp_path / ".mcp_env"
    env_file.write_text("TOKEN=secret\nEMPTY=\n# COMMENT=yes\n", encoding="utf-8")
    assert read_dotenv_status(env_file) == {"TOKEN": True, "EMPTY": False}
    assert env_status(("TOKEN", "EMPTY", "MISSING"), dotenv_path=env_file) == {
        "TOKEN": True,
        "EMPTY": False,
        "MISSING": False,
    }
    assert missing_required(("TOKEN", "EMPTY"), dotenv_path=env_file) == ["EMPTY"]
