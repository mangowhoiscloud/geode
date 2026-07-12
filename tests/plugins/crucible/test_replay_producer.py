from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from plugins.crucible.contract import content_sha256
from plugins.crucible.producers.codex_kg import ProducerError
from plugins.crucible.producers.replay import _attested_object, replay_candidate

POLICY = """\
Mode: executable assay.
Behavior:
- CAN use tools for environment state.
- CANNOT invent tool results.
"""
IMPROVED_POLICY = """\
Mode: executable assay.
Behavior:
- CAN use tools for environment state.
- CAN batch causally ready tool calls.
- CANNOT invent tool results.
"""


def _git(repository: Path, *args: str) -> str:
    executable = shutil.which("git")
    assert executable is not None
    result = subprocess.run(  # noqa: S603 - fixed git executable, fixture-owned argv
        [executable, *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init(repository: Path) -> None:
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "fixture")
    _git(repository, "config", "user.email", "fixture@example.invalid")
    _git(repository, "config", "commit.gpgsign", "false")


def _write_policy(repository: Path, content: str) -> Path:
    path = repository / "plugins/benchmark_harness/tau2_agent_policy.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", message)
    return _git(repository, "rev-parse", "HEAD")


def _source(repository: Path, *, extra_change: bool = False) -> tuple[str, str]:
    _init(repository)
    _write_policy(repository, POLICY)
    (repository / "runtime.py").write_text("VERSION = 1\n", encoding="utf-8")
    baseline = _commit(repository, "baseline")
    _write_policy(repository, IMPROVED_POLICY)
    if extra_change:
        (repository / "extra.txt").write_text("unexpected\n", encoding="utf-8")
    candidate = _commit(repository, "candidate")
    return baseline, candidate


def _target(
    repository: Path,
    *,
    policy: str = POLICY,
    runtime_version: int = 2,
) -> str:
    _init(repository)
    _write_policy(repository, policy)
    (repository / "runtime.py").write_text(
        f"VERSION = {runtime_version}\n",
        encoding="utf-8",
    )
    return _commit(repository, "new runtime baseline")


def _target_at_source_parent(
    repository: Path,
    *,
    source: Path,
    source_parent: str,
) -> None:
    _git(source, "branch", "invalid-retry-baseline", source_parent)
    executable = shutil.which("git")
    assert executable is not None
    subprocess.run(  # noqa: S603 - fixed git executable, fixture-owned argv
        [
            executable,
            "clone",
            "-q",
            "--branch",
            "invalid-retry-baseline",
            str(source),
            str(repository),
        ],
        check=True,
    )
    _git(repository, "config", "user.name", "fixture")
    _git(repository, "config", "user.email", "fixture@example.invalid")
    _git(repository, "config", "commit.gpgsign", "false")


def _request(path: Path, parent_sha: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "crucible.proposal-request.v3",
                "attempt_id": "0001-fixture",
                "request_id": "request-id",
                "iteration": 1,
                "parent_sha": parent_sha,
                "allowed_surfaces": ["plugins/benchmark_harness/tau2_agent_policy.md"],
            }
        ),
        encoding="utf-8",
    )


def _source_attempt(
    path: Path,
    *,
    source_repository: Path,
    parent_sha: str,
    candidate_sha: str,
    outcome: str = "INVALID",
    evaluator_revision: bool = False,
) -> dict[str, str]:
    path.mkdir()
    proposal_id = "a" * 64
    verdict_id = "b" * 64
    contract_payload: dict[str, object] | None = None
    contract_id = "c" * 64
    if evaluator_revision:
        contract_payload = {
            "schema": "crucible.experiment.v3",
            "stage": "train",
            "baseline_sha": parent_sha,
            "candidate_sha": candidate_sha,
            "evaluator_sha256": content_sha256(source_repository, ("runtime.py",)),
            "evaluator_paths": ["runtime.py"],
            "mutations": [{"surface": "plugins/benchmark_harness/tau2_agent_policy.md"}],
        }
        contract_id = hashlib.sha256(
            json.dumps(
                contract_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        contract_payload["contract_id"] = contract_id
    reasons = (
        ["improvement_below_materiality"]
        if evaluator_revision
        else ["infrastructure_contamination"]
    )
    paired_rows = 2 if evaluator_revision else 0
    payloads: dict[str, dict[str, object]] = {
        "candidate": {
            "schema": "crucible.candidate.v2",
            "attempt_id": "source-attempt",
            "request_id": "source-request",
            "parent_sha": parent_sha,
            "candidate_sha": candidate_sha,
            "proposal_id": proposal_id,
            "mutation": {
                "surface": "plugins/benchmark_harness/tau2_agent_policy.md",
                "hypothesis": "Batch causally ready tool calls.",
            },
            "usage": {"wall_seconds": 1.0, "calls": 1, "tokens": 10, "cost_usd": 0.0},
        },
        "verdict": {
            "schema": "crucible.verdict.v3",
            "verdict": outcome,
            "verdict_id": verdict_id,
            "contract_id": contract_id,
            "promotion_authority": "none",
            "reasons": reasons,
            "metric": {"paired_rows": paired_rows},
        },
        "record": {
            "schema": "crucible.loop-record.v2",
            "outcome": outcome,
            "contract_id": contract_id,
            "reasons": reasons,
            "proposal_id": proposal_id,
            "verdict_id": verdict_id,
            "search_head_before": parent_sha,
            "search_head_after": parent_sha,
        },
    }
    if contract_payload is not None:
        payloads["contract"] = contract_payload
    digests: dict[str, str] = {}
    for name, payload in payloads.items():
        artifact = path / f"{name}.json"
        artifact.write_text(json.dumps(payload), encoding="utf-8")
        key = "source_contract_sha256" if name == "contract" else f"{name}_sha256"
        digests[key] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return digests


def _replay(
    *,
    request: Path,
    output: Path,
    source: Path,
    source_candidate: str,
    source_parent: str,
    outcome: str = "INVALID",
    evaluator_revision: bool = False,
) -> None:
    attempt = source.parent / f"attempt-{outcome.lower()}"
    digests = _source_attempt(
        attempt,
        source_repository=source,
        parent_sha=source_parent,
        candidate_sha=source_candidate,
        outcome=outcome,
        evaluator_revision=evaluator_revision,
    )
    replay_candidate(
        request_path=request,
        output_path=output,
        source_repository=source,
        source_attempt_dir=attempt,
        **digests,
    )


def test_replay_candidate_reapplies_only_the_preregistered_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source_parent, source_candidate = _source(source)
    target = tmp_path / "target"
    parent = _target(target)
    request = tmp_path / "request.json"
    output = tmp_path / "candidate.json"
    _request(request, parent)
    monkeypatch.chdir(target)

    _replay(
        request=request,
        output=output,
        source=source,
        source_candidate=source_candidate,
        source_parent=source_parent,
    )

    proposal = json.loads(output.read_text(encoding="utf-8"))
    assert proposal["parent_sha"] == parent
    assert proposal["candidate_sha"] == _git(target, "rev-parse", "HEAD")
    assert proposal["usage"]["calls"] == 0
    assert _git(target, "rev-list", "--parents", "-n", "1", "HEAD").split() == [
        proposal["candidate_sha"],
        parent,
    ]
    assert _git(target, "diff", "--name-only", f"{parent}..HEAD") == (
        "plugins/benchmark_harness/tau2_agent_policy.md"
    )
    assert (target / "plugins/benchmark_harness/tau2_agent_policy.md").read_text(
        encoding="utf-8"
    ) == IMPROVED_POLICY


def test_invalid_replay_preserves_exact_candidate_revision_for_row_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source_parent, source_candidate = _source(source)
    target = tmp_path / "target"
    _target_at_source_parent(target, source=source, source_parent=source_parent)
    request = tmp_path / "request.json"
    output = tmp_path / "candidate.json"
    _request(request, source_parent)
    monkeypatch.chdir(target)

    _replay(
        request=request,
        output=output,
        source=source,
        source_candidate=source_candidate,
        source_parent=source_parent,
    )

    proposal = json.loads(output.read_text(encoding="utf-8"))
    assert proposal["parent_sha"] == source_parent
    assert proposal["candidate_sha"] == source_candidate
    assert _git(target, "rev-parse", "HEAD") == source_candidate
    assert _git(target, "status", "--porcelain", "--untracked-files=all") == ""


def test_replay_candidate_rejects_a_source_with_extra_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source_parent, source_candidate = _source(source, extra_change=True)
    target = tmp_path / "target"
    parent = _target(target)
    request = tmp_path / "request.json"
    _request(request, parent)
    monkeypatch.chdir(target)

    with pytest.raises(ProducerError, match="must change exactly"):
        _replay(
            request=request,
            output=tmp_path / "candidate.json",
            source=source,
            source_candidate=source_candidate,
            source_parent=source_parent,
        )


def test_replay_candidate_rejects_current_surface_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source_parent, source_candidate = _source(source)
    target = tmp_path / "target"
    parent = _target(target, policy=POLICY.replace("use tools", "use trusted tools"))
    request = tmp_path / "request.json"
    _request(request, parent)
    monkeypatch.chdir(target)

    with pytest.raises(ProducerError, match="baseline differs"):
        _replay(
            request=request,
            output=tmp_path / "candidate.json",
            source=source,
            source_candidate=source_candidate,
            source_parent=source_parent,
        )


def test_replay_candidate_rejects_a_scored_source_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source_parent, source_candidate = _source(source)
    target = tmp_path / "target"
    parent = _target(target)
    request = tmp_path / "request.json"
    _request(request, parent)
    monkeypatch.chdir(target)

    with pytest.raises(ProducerError, match="scoreless infrastructure INVALID"):
        _replay(
            request=request,
            output=tmp_path / "candidate.json",
            source=source,
            source_candidate=source_candidate,
            source_parent=source_parent,
            outcome="REJECT",
        )


def test_replay_candidate_allows_reject_only_after_evaluator_digest_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source_parent, source_candidate = _source(source)
    target = tmp_path / "target"
    parent = _target(target, runtime_version=2)
    request = tmp_path / "request.json"
    output = tmp_path / "candidate.json"
    _request(request, parent)
    monkeypatch.chdir(target)

    _replay(
        request=request,
        output=output,
        source=source,
        source_candidate=source_candidate,
        source_parent=source_parent,
        outcome="REJECT",
        evaluator_revision=True,
    )

    proposal = json.loads(output.read_text(encoding="utf-8"))
    assert proposal["usage"]["calls"] == 0
    assert (target / "plugins/benchmark_harness/tau2_agent_policy.md").read_text(
        encoding="utf-8"
    ) == IMPROVED_POLICY


def test_replay_candidate_rejects_reject_when_evaluator_digest_is_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source_parent, source_candidate = _source(source)
    target = tmp_path / "target"
    parent = _target(target, runtime_version=1)
    request = tmp_path / "request.json"
    _request(request, parent)
    monkeypatch.chdir(target)

    with pytest.raises(ProducerError, match="requires a changed evaluator digest"):
        _replay(
            request=request,
            output=tmp_path / "candidate.json",
            source=source,
            source_candidate=source_candidate,
            source_parent=source_parent,
            outcome="REJECT",
            evaluator_revision=True,
        )


def test_replay_candidate_rejects_a_source_artifact_hash_mismatch(tmp_path: Path) -> None:
    artifact = tmp_path / "candidate.json"
    artifact.write_text("{}", encoding="utf-8")

    with pytest.raises(ProducerError, match="sha256 does not match"):
        _attested_object(artifact, "0" * 64, "source candidate")
