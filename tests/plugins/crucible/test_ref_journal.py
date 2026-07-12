from __future__ import annotations

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import plugins.crucible.ref_journal as journal_module
import pytest
from plugins.crucible.ref_journal import (
    RefIntent,
    RefJournalError,
    RefReceipt,
    commit_ref_update,
    load_intent,
    load_receipt,
    persist_intent,
    reconcile_ref_update,
    verify_ref_update,
)

SUBJECT_ID = "a" * 64
ZERO_SHA = "0" * 40
GIT = shutil.which("git")
assert GIT is not None


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed Git executable and test-owned argv
        [GIT, *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(path: Path) -> tuple[str, str, str]:
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.name", "crucible-test")
    _git(path, "config", "user.email", "crucible-test@localhost")
    commits: list[str] = []
    tracked = path / "tracked.txt"
    for index in range(3):
        tracked.write_text(f"revision {index}\n", encoding="utf-8")
        _git(path, "add", "tracked.txt")
        _git(path, "commit", "-qm", f"revision {index}")
        commits.append(_git(path, "rev-parse", "HEAD"))
    return commits[0], commits[1], commits[2]


def _intent(ref: str, old: str, new: str, *, subject_id: str = SUBJECT_ID) -> RefIntent:
    witness_ref = None
    if ref.startswith("refs/crucible/search/"):
        campaign = ref.removeprefix("refs/crucible/search/")
        witness_ref = f"refs/crucible/applied/{campaign}/{subject_id}"
    return RefIntent(
        ref=ref,
        expected_old_sha=old,
        new_sha=new,
        subject_id=subject_id,
        witness_ref=witness_ref,
    )


def test_intent_and_receipt_ids_are_canonical_and_strict() -> None:
    intent = _intent("refs/crucible/search/campaign", "1" * 40, "2" * 40)
    assert RefIntent.from_mapping(intent.to_dict()) == intent
    assert len(intent.intent_id) == 64

    tampered = deepcopy(intent.to_dict())
    tampered["subject_id"] = "b" * 64
    tampered["witness_ref"] = f"refs/crucible/applied/campaign/{'b' * 64}"
    with pytest.raises(RefJournalError, match="intent_id"):
        RefIntent.from_mapping(tampered)

    unknown = {**intent.to_dict(), "extra": True}
    with pytest.raises(RefJournalError, match="unknown fields"):
        RefIntent.from_mapping(unknown)

    receipt = RefReceipt.from_intent(intent)
    assert RefReceipt.from_mapping(receipt.to_dict()) == receipt
    assert len(receipt.receipt_id) == 64

    tampered_receipt = deepcopy(receipt.to_dict())
    tampered_receipt["new_sha"] = "3" * 40
    with pytest.raises(RefJournalError, match=r"intent_id|receipt_id"):
        RefReceipt.from_mapping(tampered_receipt)


def test_search_intent_requires_exact_subject_bound_witness() -> None:
    ref = "refs/crucible/search/campaign"
    with pytest.raises(RefJournalError, match="record-bound applied witness"):
        RefIntent(
            ref=ref,
            expected_old_sha="1" * 40,
            new_sha="2" * 40,
            subject_id=SUBJECT_ID,
        )
    with pytest.raises(RefJournalError, match="record-bound applied witness"):
        RefIntent(
            ref=ref,
            expected_old_sha="1" * 40,
            new_sha="2" * 40,
            subject_id=SUBJECT_ID,
            witness_ref=f"refs/crucible/applied/campaign/{'b' * 64}",
        )


def test_eligible_intent_forbids_applied_witness() -> None:
    with pytest.raises(RefJournalError, match="eligible-ref intent"):
        RefIntent(
            ref="refs/crucible/eligible/campaign",
            expected_old_sha="1" * 40,
            new_sha="2" * 40,
            subject_id=SUBJECT_ID,
            witness_ref=f"refs/crucible/applied/campaign/{SUBJECT_ID}",
        )


@pytest.mark.parametrize(
    "ref",
    [
        "refs/heads/main",
        "refs/tags/v1",
        "refs/crucible/candidates/campaign/a",
        "refs/crucible/search",
        "refs/crucible/search/../heads/main",
        "refs/crucible/eligible/bad.lock",
        "refs/crucible/eligible/bad name",
    ],
)
def test_intent_rejects_every_ref_outside_private_search_or_eligible(ref: str) -> None:
    with pytest.raises(RefJournalError, match="ref"):
        _intent(ref, "1" * 40, "2" * 40)


def test_commit_persists_and_fsyncs_intent_before_git_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    old, new, _third = _repository(repository)
    ref = "refs/crucible/search/campaign"
    _git(repository, "update-ref", ref, old, ZERO_SHA)
    state = tmp_path / "journal"
    intent_path = state / "intent.json"
    receipt_path = state / "receipt.json"
    intent = _intent(ref, old, new)
    events: list[str] = []

    real_fsync = journal_module._fsync_directory
    real_git = journal_module._git

    def traced_fsync(path: Path) -> None:
        real_fsync(path)
        if path == state:
            events.append("fsync")

    def traced_git(
        repo: Path,
        *args: str,
        check: bool = True,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if args and args[0] == "update-ref":
            assert intent_path.exists()
            assert events == ["fsync"]
            events.append("cas")
        return real_git(repo, *args, check=check, input_text=input_text)

    monkeypatch.setattr(journal_module, "_fsync_directory", traced_fsync)
    monkeypatch.setattr(journal_module, "_git", traced_git)

    receipt = commit_ref_update(
        repository,
        intent,
        intent_path=intent_path,
        receipt_path=receipt_path,
    )

    assert events == ["fsync", "cas", "fsync"]
    assert _git(repository, "rev-parse", ref) == new
    assert intent.witness_ref is not None
    assert _git(repository, "rev-parse", intent.witness_ref) == new
    assert load_intent(intent_path) == intent
    assert load_receipt(receipt_path) == receipt == RefReceipt.from_intent(intent)


def test_verify_accepts_only_a_persisted_receipt_at_the_current_ref(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    old, new, _third = _repository(repository)
    ref = "refs/crucible/search/verified"
    _git(repository, "update-ref", ref, old, ZERO_SHA)
    state = tmp_path / "journal"
    intent_path = state / "intent.json"
    receipt_path = state / "receipt.json"
    intent = _intent(ref, old, new)
    receipt = commit_ref_update(
        repository,
        intent,
        intent_path=intent_path,
        receipt_path=receipt_path,
    )

    assert (
        verify_ref_update(
            repository,
            intent_path=intent_path,
            receipt_path=receipt_path,
        )
        == receipt
    )
    assert intent.witness_ref is not None
    assert _git(repository, "rev-parse", intent.witness_ref) == new


def test_verify_rejects_fabricated_receipt_without_applied_cas(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    old, new, _third = _repository(repository)
    ref = "refs/crucible/search/fabricated"
    _git(repository, "update-ref", ref, old, ZERO_SHA)
    state = tmp_path / "journal"
    intent_path = state / "intent.json"
    receipt_path = state / "receipt.json"
    intent = _intent(ref, old, new)
    persist_intent(intent_path, intent)
    receipt_path.write_text(
        json.dumps(RefReceipt.from_intent(intent).to_dict()),
        encoding="utf-8",
    )
    _git(repository, "update-ref", ref, new, old)

    with pytest.raises(RefJournalError, match="applied witness is stale"):
        verify_ref_update(
            repository,
            intent_path=intent_path,
            receipt_path=receipt_path,
        )

    assert _git(repository, "rev-parse", ref) == new
    assert intent.witness_ref is not None
    assert _git(repository, "for-each-ref", "--format=%(objectname)", intent.witness_ref) == ""


def test_verify_rejects_missing_witness_after_a_valid_atomic_commit(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    old, new, _third = _repository(repository)
    ref = "refs/crucible/search/missing-witness"
    _git(repository, "update-ref", ref, old, ZERO_SHA)
    state = tmp_path / "journal"
    intent_path = state / "intent.json"
    receipt_path = state / "receipt.json"
    intent = _intent(ref, old, new)
    commit_ref_update(
        repository,
        intent,
        intent_path=intent_path,
        receipt_path=receipt_path,
    )
    assert intent.witness_ref is not None
    _git(repository, "update-ref", "-d", intent.witness_ref, new)

    with pytest.raises(RefJournalError, match="applied witness is stale"):
        verify_ref_update(
            repository,
            intent_path=intent_path,
            receipt_path=receipt_path,
        )


def test_verify_rejects_drifted_witness_after_a_valid_atomic_commit(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    old, new, third = _repository(repository)
    ref = "refs/crucible/search/drifted-witness"
    _git(repository, "update-ref", ref, old, ZERO_SHA)
    state = tmp_path / "journal"
    intent_path = state / "intent.json"
    receipt_path = state / "receipt.json"
    intent = _intent(ref, old, new)
    commit_ref_update(
        repository,
        intent,
        intent_path=intent_path,
        receipt_path=receipt_path,
    )
    assert intent.witness_ref is not None
    _git(repository, "update-ref", intent.witness_ref, third, new)

    with pytest.raises(RefJournalError, match="applied witness is stale"):
        verify_ref_update(
            repository,
            intent_path=intent_path,
            receipt_path=receipt_path,
        )


def test_verify_rejects_current_ref_drift_after_a_valid_receipt(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    old, new, third = _repository(repository)
    ref = "refs/crucible/eligible/drifted"
    _git(repository, "update-ref", ref, old, ZERO_SHA)
    state = tmp_path / "journal"
    intent_path = state / "intent.json"
    receipt_path = state / "receipt.json"
    intent = _intent(ref, old, new)
    commit_ref_update(
        repository,
        intent,
        intent_path=intent_path,
        receipt_path=receipt_path,
    )
    _git(repository, "update-ref", ref, third, new)

    with pytest.raises(RefJournalError, match=r"receipt is stale|observed"):
        verify_ref_update(
            repository,
            intent_path=intent_path,
            receipt_path=receipt_path,
        )

    assert _git(repository, "rev-parse", ref) == third


def test_reconcile_recovers_both_pre_cas_and_post_cas_crashes(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    old, new, third = _repository(repository)
    state = tmp_path / "journal"

    first_ref = "refs/crucible/search/pre-cas"
    _git(repository, "update-ref", first_ref, old, ZERO_SHA)
    first = _intent(first_ref, old, new)
    first_intent = state / "first-intent.json"
    first_receipt = state / "first-receipt.json"
    persist_intent(first_intent, first)

    recovered_before = reconcile_ref_update(
        repository,
        intent_path=first_intent,
        receipt_path=first_receipt,
    )
    assert _git(repository, "rev-parse", first_ref) == new
    assert first.witness_ref is not None
    assert _git(repository, "rev-parse", first.witness_ref) == new
    assert recovered_before == RefReceipt.from_intent(first)

    second_ref = "refs/crucible/eligible/post-cas"
    _git(repository, "update-ref", second_ref, old, ZERO_SHA)
    second = _intent(second_ref, old, third, subject_id="b" * 64)
    second_intent = state / "second-intent.json"
    second_receipt = state / "second-receipt.json"
    persist_intent(second_intent, second)
    _git(repository, "update-ref", second_ref, third, old)

    recovered_after = reconcile_ref_update(
        repository,
        intent_path=second_intent,
        receipt_path=second_receipt,
    )
    assert recovered_after == RefReceipt.from_intent(second)
    assert load_receipt(second_receipt) == recovered_after


def test_reconcile_rejects_third_sha_without_writing_receipt(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    old, new, third = _repository(repository)
    ref = "refs/crucible/eligible/conflict"
    _git(repository, "update-ref", ref, old, ZERO_SHA)
    state = tmp_path / "journal"
    intent_path = state / "intent.json"
    receipt_path = state / "receipt.json"
    persist_intent(intent_path, _intent(ref, old, new))
    _git(repository, "update-ref", ref, third, old)

    with pytest.raises(RefJournalError, match="CAS conflict"):
        reconcile_ref_update(
            repository,
            intent_path=intent_path,
            receipt_path=receipt_path,
        )

    assert not receipt_path.exists()
    assert _git(repository, "rev-parse", ref) == third


def test_existing_receipt_is_idempotent_but_cannot_be_replaced(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    old, new, _third = _repository(repository)
    ref = "refs/crucible/eligible/idempotent"
    _git(repository, "update-ref", ref, old, ZERO_SHA)
    state = tmp_path / "journal"
    intent_path = state / "intent.json"
    receipt_path = state / "receipt.json"
    intent = _intent(ref, old, new)
    receipt = commit_ref_update(
        repository,
        intent,
        intent_path=intent_path,
        receipt_path=receipt_path,
    )

    assert (
        reconcile_ref_update(
            repository,
            intent_path=intent_path,
            receipt_path=receipt_path,
        )
        == receipt
    )
    with pytest.raises(RefJournalError, match="overwrite immutable artifact"):
        persist_intent(intent_path, intent)

    mismatched = RefReceipt.from_intent(_intent(ref, old, new, subject_id="c" * 64)).to_dict()
    receipt_path.write_text(json.dumps(mismatched), encoding="utf-8")
    with pytest.raises(RefJournalError, match="does not match"):
        reconcile_ref_update(
            repository,
            intent_path=intent_path,
            receipt_path=receipt_path,
        )


def test_missing_ref_uses_zero_sha_compare_and_swap(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    _old, new, _third = _repository(repository)
    ref = "refs/crucible/eligible/new-campaign"
    state = tmp_path / "journal"
    intent = _intent(ref, ZERO_SHA, new)

    receipt = commit_ref_update(
        repository,
        intent,
        intent_path=state / "intent.json",
        receipt_path=state / "receipt.json",
    )

    assert receipt == RefReceipt.from_intent(intent)
    assert _git(repository, "rev-parse", ref) == new


def test_symbolic_private_ref_cannot_reach_a_head(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    _old, new, head = _repository(repository)
    branch = _git(repository, "symbolic-ref", "HEAD")
    ref = "refs/crucible/search/symbolic"
    _git(repository, "symbolic-ref", ref, branch)
    state = tmp_path / "journal"
    intent_path = state / "intent.json"
    receipt_path = state / "receipt.json"
    persist_intent(intent_path, _intent(ref, head, new))

    with pytest.raises(RefJournalError, match="symbolic"):
        reconcile_ref_update(
            repository,
            intent_path=intent_path,
            receipt_path=receipt_path,
        )

    assert _git(repository, "rev-parse", branch) == head
    assert _git(repository, "symbolic-ref", ref) == branch
    assert not receipt_path.exists()
