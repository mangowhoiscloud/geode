import subprocess
import sys
from pathlib import Path


def test_contract_cli_reports_invalid_input_without_traceback(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    contract = tmp_path / "invalid.json"
    contract.write_text("{}\n", encoding="utf-8")

    completed = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [sys.executable, "scripts/eval/crucible_contract.py", str(contract)],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "invalid Crucible contract" in completed.stderr
    assert "Traceback" not in completed.stderr
