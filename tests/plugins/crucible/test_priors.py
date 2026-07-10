import json
import shutil
import subprocess
from pathlib import Path

import pytest
from plugins.crucible.calibration import MutationClassPrior
from plugins.crucible.cli import main as crucible_main
from plugins.crucible.contract import ContractError
from plugins.crucible.priors import (
    PRIORS_DIR,
    load_prior,
    save_prior,
    update_prior_from_campaign,
)

PACK_SHA = "f" * 64


def _prior() -> MutationClassPrior:
    return MutationClassPrior.from_replay_counts(
        class_name="guard",
        supported=24,
        targeted=27,
        false_blocks=4,
        controls=87,
        task_pack_sha256=PACK_SHA,
        source="g1-trace-replay-2026-07-06",
    )


def _ledger_record(
    *,
    attempt: str,
    outcome: str,
    flips: int | None,
    task_count: int | None,
    pack_sha: str = PACK_SHA,
) -> dict:
    return {
        "schema": "crucible.record.v2",
        "kind": "train_attempt",
        "campaign_id": "campaign-x",
        "attempt_id": attempt,
        "outcome": outcome,
        "task_count": task_count,
        "task_pack_sha256": pack_sha,
        "target_flips": flips,
        "target_regressions": 0,
    }


def _campaign_dir(tmp_path: Path, records: list[dict]) -> Path:
    state_dir = tmp_path / "campaign-state"
    state_dir.mkdir()
    ledger = state_dir / "ledger.jsonl"
    ledger.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return state_dir


def test_prior_round_trip_preserves_posteriors(tmp_path: Path) -> None:
    prior_path = tmp_path / "guard.json"
    save_prior(_prior(), prior_path)
    loaded = load_prior(prior_path)
    assert loaded == _prior()


def test_campaign_fold_updates_fix_posterior_and_history(tmp_path: Path) -> None:
    prior_path = tmp_path / "guard.json"
    save_prior(_prior(), prior_path)
    state_dir = _campaign_dir(
        tmp_path,
        [
            _ledger_record(attempt="a1", outcome="REJECT", flips=3, task_count=20),
            _ledger_record(attempt="a2", outcome="KEEP", flips=8, task_count=20),
            _ledger_record(attempt="a3", outcome="INVALID", flips=None, task_count=None),
        ],
    )
    updated = update_prior_from_campaign(prior_path, state_dir)
    assert updated.fix_alpha == pytest.approx(_prior().fix_alpha + 11)
    assert updated.fix_beta == pytest.approx(_prior().fix_beta + 29)
    # Regression posterior deliberately untouched by train folding.
    assert updated.regression_alpha == _prior().regression_alpha
    stored = json.loads(prior_path.read_text(encoding="utf-8"))
    assert stored["history"][-1]["folded_attempts"] == 2
    assert "campaign-x" in updated.source


def test_campaign_fold_refuses_foreign_task_pack(tmp_path: Path) -> None:
    prior_path = tmp_path / "guard.json"
    save_prior(_prior(), prior_path)
    state_dir = _campaign_dir(
        tmp_path,
        [_ledger_record(attempt="a1", outcome="KEEP", flips=2, task_count=20, pack_sha="e" * 64)],
    )
    with pytest.raises(ContractError, match="refit instead of folding"):
        update_prior_from_campaign(prior_path, state_dir)


def test_campaign_fold_requires_measured_attempts(tmp_path: Path) -> None:
    prior_path = tmp_path / "guard.json"
    save_prior(_prior(), prior_path)
    state_dir = _campaign_dir(
        tmp_path,
        [_ledger_record(attempt="a1", outcome="INVALID", flips=None, task_count=None)],
    )
    with pytest.raises(ContractError, match="no measured attempts"):
        update_prior_from_campaign(prior_path, state_dir)


def test_priors_update_cli_round_trip(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    prior_path = tmp_path / "guard.json"
    save_prior(_prior(), prior_path)
    state_dir = _campaign_dir(
        tmp_path,
        [_ledger_record(attempt="a1", outcome="KEEP", flips=5, task_count=20)],
    )
    assert crucible_main(["priors-update", str(prior_path), "--state-dir", str(state_dir)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["fix_alpha"] == pytest.approx(_prior().fix_alpha + 5)


def test_priors_store_is_not_gitignored() -> None:
    """An ignored prior path would silently break the writer (PR-G5b pattern)."""
    git_bin = shutil.which("git")
    if git_bin is None:
        pytest.skip("git executable not in PATH")
    probe = PRIORS_DIR / "guard.json"
    result = subprocess.run(  # noqa: S603 - fixed git executable and argv
        [git_bin, "check-ignore", "--quiet", str(probe)],
        cwd=PRIORS_DIR.parents[2],
        check=False,
        capture_output=True,
    )
    assert result.returncode != 0, f"{probe} is gitignored — the prior writer would lose history"
