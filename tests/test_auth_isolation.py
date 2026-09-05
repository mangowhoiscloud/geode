"""Exercise the real pytest bootstrap without borrowing operator credentials."""

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


def test_auth_paths_are_owned_by_each_test_worker_and_run(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    sentinel = tmp_path / "operator-auth.toml"
    sentinel.write_text('[operator]\nnote = "must survive"\n', encoding="utf-8")
    sentinel.chmod(0o640)
    original = sentinel.read_bytes(), stat.S_IMODE(sentinel.stat().st_mode)
    receipts = []
    for run in range(2):
        sandbox = tmp_path / str(run)
        sandbox.mkdir()
        shutil.copyfile(repo / "tests/conftest.py", sandbox / "conftest.py")
        (sandbox / "test_probe.py").write_text(
            """import json
import os
from pathlib import Path

import pytest
from core.auth.auth_toml import auth_toml_path
from core.llm.strategies import plan_registry
from core.wiring import container

collection_path = auth_toml_path()
assert collection_path != Path(os.environ["AUTH_SENTINEL"])
assert "OPENROUTER_API_KEY" not in os.environ

@pytest.mark.parametrize("case", range(8))
def test_private_auth(case, tmp_path, monkeypatch):
    path = auth_toml_path()
    assert path != collection_path
    assert not path.exists()
    assert container._profile_store is None
    assert container._profile_rotator is None
    assert plan_registry._plan_registry is None
    path.write_text(f"case = {case}\\n", encoding="utf-8")
    container._profile_store = object()
    container._profile_rotator = object()
    plan_registry._plan_registry = object()
    with monkeypatch.context() as patch:
        override = tmp_path / "explicit.toml"
        patch.setenv("GEODE_AUTH_TOML", str(override))
        assert auth_toml_path() == override
    assert auth_toml_path() == path
    Path(f"receipt-{case}.json").write_text(json.dumps({
        "auth": str(path), "collection": str(collection_path),
        "worker": os.environ.get("PYTEST_XDIST_WORKER", "serial"),
    }), encoding="utf-8")
""",
            encoding="utf-8",
        )
        completed = subprocess.run(  # noqa: S603 - fixed, synthetic pytest child
            [sys.executable, "-m", "pytest", "-q", "-n", "2", "test_probe.py"],
            cwd=sandbox,
            env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(sandbox),
                "GEODE_HOME": str(sandbox / ".geode"),
                "CODEX_HOME": str(sandbox / ".codex"),
                "PYTHONPATH": str(repo),
                "GEODE_AUTH_TOML": str(sentinel),
                "OPENROUTER_API_KEY": "synthetic-not-a-real-key",
                "AUTH_SENTINEL": str(sentinel),
            },
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert (sentinel.read_bytes(), stat.S_IMODE(sentinel.stat().st_mode)) == original
        assert completed.returncode == 0, completed.stdout + completed.stderr
        batch = [json.loads(path.read_text()) for path in sandbox.glob("receipt-*.json")]
        assert len(batch) == 8
        assert {row["worker"] for row in batch} == {"gw0", "gw1"}
        assert len({row["collection"] for row in batch}) == 2
        receipts.extend(batch)
    assert len({row["auth"] for row in receipts}) == 16
    assert len({row["collection"] for row in receipts}) == 4
