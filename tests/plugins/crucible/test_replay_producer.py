from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from plugins.crucible.producers.codex_kg import ProducerError
from plugins.crucible.producers.replay import replay_candidate

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
    baseline = _commit(repository, "baseline")
    _write_policy(repository, IMPROVED_POLICY)
    if extra_change:
        (repository / "extra.txt").write_text("unexpected\n", encoding="utf-8")
    candidate = _commit(repository, "candidate")
    return baseline, candidate


def _target(repository: Path, *, policy: str = POLICY) -> str:
    _init(repository)
    _write_policy(repository, policy)
    (repository / "runtime.py").write_text("VERSION = 2\n", encoding="utf-8")
    return _commit(repository, "new runtime baseline")


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


def test_replay_candidate_reapplies_only_the_preregistered_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    _source(source)
    source_candidate = _git(source, "rev-parse", "HEAD")
    target = tmp_path / "target"
    parent = _target(target)
    request = tmp_path / "request.json"
    output = tmp_path / "candidate.json"
    _request(request, parent)
    monkeypatch.chdir(target)

    replay_candidate(
        request_path=request,
        output_path=output,
        source_repository=source,
        source_candidate=source_candidate,
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


def test_replay_candidate_rejects_a_source_with_extra_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    _source(source, extra_change=True)
    target = tmp_path / "target"
    parent = _target(target)
    request = tmp_path / "request.json"
    _request(request, parent)
    monkeypatch.chdir(target)

    with pytest.raises(ProducerError, match="must change exactly"):
        replay_candidate(
            request_path=request,
            output_path=tmp_path / "candidate.json",
            source_repository=source,
            source_candidate=_git(source, "rev-parse", "HEAD"),
        )


def test_replay_candidate_rejects_current_surface_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    _source(source)
    target = tmp_path / "target"
    parent = _target(target, policy=POLICY.replace("use tools", "use trusted tools"))
    request = tmp_path / "request.json"
    _request(request, parent)
    monkeypatch.chdir(target)

    with pytest.raises(ProducerError, match="baseline differs"):
        replay_candidate(
            request_path=request,
            output_path=tmp_path / "candidate.json",
            source_repository=source,
            source_candidate=_git(source, "rev-parse", "HEAD"),
        )
