import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = "scripts/eval/crucible_window_preflight.py"


def _config(tmp_path: Path, *, max_tokens: int = 14_500_000) -> Path:
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps({"limits": {"max_tokens": max_tokens}}), encoding="utf-8")
    return path


def _history(tmp_path: Path, token_totals: list[int]) -> Path:
    root = tmp_path / "campaigns"
    for index, tokens in enumerate(token_totals):
        state = root / f"run-{index}" / "state"
        state.mkdir(parents=True)
        (state / "summary.json").write_text(
            json.dumps({"usage": {"tokens": tokens}}), encoding="utf-8"
        )
    # An interrupted campaign (no summary) must not count as history.
    (root / "run-crashed" / "state").mkdir(parents=True)
    return root


def _run(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [sys.executable, SCRIPT, *argv],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_cap_fit_when_remaining_covers_the_hard_cap(tmp_path: Path) -> None:
    completed = _run(
        str(_config(tmp_path)),
        "--history",
        str(_history(tmp_path, [4_584_651, 5_103_000])),
        "--remaining-tokens",
        "20000000",
    )
    verdict = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert verdict["schema"] == "crucible.window-preflight.v2"
    assert verdict["fit"] == "cap_fit"
    assert verdict["history_completed_runs"] == 2


def test_history_fit_when_remaining_covers_only_the_measured_worst(tmp_path: Path) -> None:
    completed = _run(
        str(_config(tmp_path)),
        "--history",
        str(_history(tmp_path, [4_584_651, 5_103_000])),
        "--remaining-tokens",
        "6000000",
    )
    verdict = json.loads(completed.stdout)
    assert completed.returncode == 1
    assert verdict["fit"] == "history_fit"
    assert verdict["history_worst_tokens"] == 5_103_000


def test_defer_reproduces_the_r23_launch_shape(tmp_path: Path) -> None:
    # r23: ~5.1M-token run launched into a window that held roughly 4M.
    completed = _run(
        str(_config(tmp_path)),
        "--history",
        str(_history(tmp_path, [4_584_651, 5_103_000])),
        "--remaining-tokens",
        "4000000",
    )
    verdict = json.loads(completed.stdout)
    assert completed.returncode == 3
    assert verdict["fit"] == "defer"


def test_defer_without_history_when_hard_cap_does_not_fit(tmp_path: Path) -> None:
    completed = _run(str(_config(tmp_path)), "--remaining-tokens", "1000000")
    verdict = json.loads(completed.stdout)
    assert completed.returncode == 3
    assert verdict["history_completed_runs"] == 0
