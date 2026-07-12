"""Replay one preregistered candidate after invalid measurement or evaluator repair."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from plugins.crucible.contract import ContractError, content_sha256

from .codex_kg import (
    ProducerError,
    _load_object,
    _text,
    _validate_policy_grammar,
    _write_error_sidecar,
    _write_exclusive,
)

_REQUEST_SCHEMA = "crucible.proposal-request.v3"
_CANDIDATE_SCHEMA = "crucible.candidate.v2"
_VERDICT_SCHEMA = "crucible.verdict.v3"
_RECORD_SCHEMA = "crucible.loop-record.v2"
_FULL_SHA = re.compile(r"[0-9a-f]{40}")
_FULL_SHA256 = re.compile(r"[0-9a-f]{64}")


def _git(*args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise ProducerError("git executable is required")
    result = subprocess.run(  # noqa: S603 - fixed git executable, wrapper-owned argv
        [executable, *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ProducerError(result.stderr.strip() or "git operation failed")
    return result.stdout.strip()


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _FULL_SHA.fullmatch(value) is None:
        raise ProducerError(f"{field} must be a full git commit sha")
    return value


def _surface(request: dict[str, Any]) -> str:
    raw = request.get("allowed_surfaces")
    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], str):
        raise ProducerError("replay producer requires exactly one allowed surface")
    surface = raw[0].strip()
    candidate = PurePosixPath(surface)
    if not surface or candidate.is_absolute() or ".." in candidate.parts:
        raise ProducerError("allowed surface must be repository-relative")
    return surface


def _attested_object(path: Path, expected_sha256: str, field: str) -> dict[str, Any]:
    if _FULL_SHA256.fullmatch(expected_sha256) is None:
        raise ProducerError(f"{field} sha256 must be a full digest")
    info = path.lstat()
    if path.is_symlink() or not path.is_file() or info.st_size > 1024 * 1024:
        raise ProducerError(f"{field} must be a bounded regular file")
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ProducerError(f"{field} sha256 does not match")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ProducerError(f"{field} must be an object")
    return value


def _source_attempt(
    path: Path,
    *,
    candidate_sha256: str,
    verdict_sha256: str,
    record_sha256: str,
    source_contract_sha256: str | None,
) -> tuple[str, str, str, str, str | None, tuple[str, ...]]:
    """Return an attested replay source and any evaluator-revision boundary."""

    candidate = _attested_object(path / "candidate.json", candidate_sha256, "source candidate")
    verdict = _attested_object(path / "verdict.json", verdict_sha256, "source verdict")
    record = _attested_object(path / "record.json", record_sha256, "source record")
    if candidate.get("schema") != _CANDIDATE_SCHEMA:
        raise ProducerError(f"source candidate must use {_CANDIDATE_SCHEMA}")
    if verdict.get("schema") != _VERDICT_SCHEMA:
        raise ProducerError(f"source verdict must use {_VERDICT_SCHEMA}")
    if record.get("schema") != _RECORD_SCHEMA:
        raise ProducerError(f"source record must use {_RECORD_SCHEMA}")
    reasons = verdict.get("reasons")
    record_reasons = record.get("reasons")
    metric = verdict.get("metric")
    paired_rows = metric.get("paired_rows") if isinstance(metric, dict) else None
    linked = (
        record.get("search_head_before") == record.get("search_head_after")
        and record.get("proposal_id") == candidate.get("proposal_id")
        and record.get("verdict_id") == verdict.get("verdict_id")
        and candidate.get("parent_sha") == record.get("search_head_before")
    )
    mutation = candidate.get("mutation")
    if not isinstance(mutation, dict):
        raise ProducerError("source candidate mutation must be an object")
    candidate_sha = _sha(candidate.get("candidate_sha"), "source candidate_sha")
    parent_sha = _sha(candidate.get("parent_sha"), "source parent_sha")
    surface = _text(mutation.get("surface"), "source mutation surface")
    hypothesis = _text(mutation.get("hypothesis"), "source mutation hypothesis")
    invalid_retry = (
        linked
        and verdict.get("verdict") == "INVALID"
        and record.get("outcome") == "INVALID"
        and isinstance(reasons, list)
        and "infrastructure_contamination" in reasons
        and isinstance(record_reasons, list)
        and "infrastructure_contamination" in record_reasons
        and isinstance(paired_rows, int)
        and not isinstance(paired_rows, bool)
        and paired_rows == 0
    )
    if invalid_retry:
        return candidate_sha, parent_sha, surface, hypothesis, None, ()
    if source_contract_sha256 is None:
        raise ProducerError(
            "source attempt is not a scoreless infrastructure INVALID; "
            "evaluator-revision replay requires an attested source contract"
        )

    contract = _attested_object(
        path / "contract.json",
        source_contract_sha256,
        "source contract",
    )
    contract_id = contract.get("contract_id")
    canonical_contract_id = hashlib.sha256(
        json.dumps(
            {key: value for key, value in contract.items() if key != "contract_id"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    evaluator_sha = contract.get("evaluator_sha256")
    evaluator_paths_raw = contract.get("evaluator_paths")
    mutations = contract.get("mutations")
    correction_eligible = (
        linked
        and verdict.get("verdict") == "REJECT"
        and record.get("outcome") == "REJECT"
        and verdict.get("promotion_authority") == "none"
        and isinstance(reasons, list)
        and bool(reasons)
        and isinstance(record_reasons, list)
        and record_reasons == reasons
        and isinstance(paired_rows, int)
        and not isinstance(paired_rows, bool)
        and paired_rows > 0
        and contract.get("schema") == "crucible.experiment.v3"
        and contract.get("stage") == "train"
        and isinstance(contract_id, str)
        and _FULL_SHA256.fullmatch(contract_id) is not None
        and contract_id == canonical_contract_id
        and verdict.get("contract_id") == contract_id
        and record.get("contract_id") == contract_id
        and contract.get("baseline_sha") == parent_sha
        and contract.get("candidate_sha") == candidate_sha
        and isinstance(evaluator_sha, str)
        and _FULL_SHA256.fullmatch(evaluator_sha) is not None
        and isinstance(mutations, list)
        and len(mutations) == 1
        and isinstance(mutations[0], dict)
        and mutations[0].get("surface") == surface
    )
    if not correction_eligible:
        raise ProducerError("source attempt is not eligible for evaluator-revision replay")
    if not isinstance(evaluator_paths_raw, list) or not evaluator_paths_raw:
        raise ProducerError("source contract evaluator_paths must be a non-empty list")
    evaluator_paths: list[str] = []
    for value in evaluator_paths_raw:
        if not isinstance(value, str) or not value.strip():
            raise ProducerError("source contract evaluator_paths must contain strings")
        path_value = PurePosixPath(value)
        if path_value.is_absolute() or ".." in path_value.parts:
            raise ProducerError("source contract evaluator_paths must be repository-relative")
        evaluator_paths.append(value)
    return candidate_sha, parent_sha, surface, hypothesis, evaluator_sha, tuple(evaluator_paths)


def replay_candidate(
    *,
    request_path: Path,
    output_path: Path,
    source_repository: Path,
    source_attempt_dir: Path,
    candidate_sha256: str,
    verdict_sha256: str,
    record_sha256: str,
    source_contract_sha256: str | None = None,
) -> None:
    """Reapply an attested source diff only when its baseline blob still matches."""

    started = time.monotonic()
    request = _load_object(request_path, "proposal request")
    if request.get("schema") != _REQUEST_SCHEMA:
        raise ProducerError(f"proposal request must use {_REQUEST_SCHEMA}")
    surface = _surface(request)
    parent_sha = _sha(request.get("parent_sha"), "request parent_sha")
    (
        source_candidate,
        claimed_source_parent,
        source_surface,
        hypothesis,
        source_evaluator_sha,
        source_evaluator_paths,
    ) = _source_attempt(
        source_attempt_dir.resolve(),
        candidate_sha256=candidate_sha256,
        verdict_sha256=verdict_sha256,
        record_sha256=record_sha256,
        source_contract_sha256=source_contract_sha256,
    )
    if source_surface != surface:
        raise ProducerError("source mutation surface does not match the allowed surface")
    source_repository = source_repository.resolve()
    if not source_repository.is_dir():
        raise ProducerError("source repository must exist")
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise ProducerError("candidate checkout must start clean")
    if _git("rev-parse", "HEAD") != parent_sha:
        raise ProducerError("candidate checkout HEAD must match request parent_sha")
    if source_evaluator_sha is not None:
        try:
            current_evaluator_sha = content_sha256(Path.cwd(), source_evaluator_paths)
        except ContractError as exc:
            raise ProducerError(f"cannot attest current evaluator: {exc}") from exc
        if current_evaluator_sha == source_evaluator_sha:
            raise ProducerError("evaluator-revision replay requires a changed evaluator digest")

    _git(
        "fetch",
        "--quiet",
        "--no-tags",
        "--depth=2",
        str(source_repository),
        source_candidate,
    )
    fetched = _git("rev-parse", "FETCH_HEAD^{commit}")
    if fetched != source_candidate:
        raise ProducerError("source candidate did not resolve exactly")
    ancestry = _git(
        "--no-replace-objects",
        "rev-list",
        "--parents",
        "-n",
        "1",
        source_candidate,
    ).split()
    if len(ancestry) != 2 or ancestry[0] != source_candidate:
        raise ProducerError("source candidate must be one single-parent commit")
    source_parent = ancestry[1]
    if source_parent != claimed_source_parent:
        raise ProducerError("source candidate parent does not match its proposal")
    source_paths = tuple(
        path
        for path in _git(
            "diff",
            "--name-only",
            source_parent,
            source_candidate,
            "--",
        ).splitlines()
        if path.strip()
    )
    if source_paths != (surface,):
        raise ProducerError(
            f"source candidate must change exactly {(surface,)!r}; observed {source_paths!r}"
        )
    if _git("rev-parse", f"{parent_sha}:{surface}") != _git(
        "rev-parse", f"{source_parent}:{surface}"
    ):
        raise ProducerError("current surface baseline differs from the source candidate baseline")

    exact_revision_retry = source_evaluator_sha is None and parent_sha == source_parent
    if exact_revision_retry:
        # A scoreless infrastructure INVALID may retry the identical treatment.
        # Fast-forwarding the disposable producer checkout preserves the exact
        # candidate revision, which is part of the row-cache identity. Reapplying
        # and recommitting the same patch would create a new SHA and strand every
        # completed candidate row harvested from the interrupted attempt.
        _git("merge", "--ff-only", source_candidate)
        candidate_sha = source_candidate
    else:
        # A corrected-evaluator replay can have a newer parent. Its source
        # surface blob is still attested above, but the candidate must become a
        # fresh child of the current measurement world.
        _git(
            "restore",
            f"--source={source_candidate}",
            "--staged",
            "--worktree",
            "--",
            surface,
        )
        changed = tuple(
            path
            for path in _git("diff", "--cached", "--name-only", "--").splitlines()
            if path.strip()
        )
        if changed != (surface,):
            raise ProducerError(f"replay must change exactly {(surface,)!r}; observed {changed!r}")
        _git("commit", "-qm", f"crucible: replay candidate {request['iteration']}")
        candidate_sha = _git("rev-parse", "HEAD")
    surface_path = Path(surface)
    if surface_path.is_symlink() or not surface_path.is_file():
        raise ProducerError("candidate surface must remain a regular file")
    if surface_path.stat().st_size > 16 * 1024:
        raise ProducerError("candidate surface exceeds 16384 bytes")
    _validate_policy_grammar(surface_path.read_text(encoding="utf-8"))
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise ProducerError("replayed candidate checkout must finish clean")
    payload = {
        "schema": _CANDIDATE_SCHEMA,
        "attempt_id": request["attempt_id"],
        "request_id": request["request_id"],
        "parent_sha": parent_sha,
        "candidate_sha": candidate_sha,
        "mutation": {
            "surface": surface,
            "hypothesis": hypothesis[:500],
        },
        "usage": {
            "wall_seconds": time.monotonic() - started,
            "calls": 0,
            "tokens": 0,
            "cost_usd": 0.0,
        },
    }
    _write_exclusive(output_path, payload)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", type=Path, required=True)
    parser.add_argument("--source-attempt-dir", type=Path, required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--verdict-sha256", required=True)
    parser.add_argument("--record-sha256", required=True)
    parser.add_argument("--source-contract-sha256")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        replay_candidate(
            request_path=Path(os.environ["CRUCIBLE_PROPOSAL_REQUEST"]),
            output_path=Path(os.environ["CRUCIBLE_CANDIDATE_OUTPUT"]),
            source_repository=args.source_repository,
            source_attempt_dir=args.source_attempt_dir,
            candidate_sha256=args.candidate_sha256,
            verdict_sha256=args.verdict_sha256,
            record_sha256=args.record_sha256,
            source_contract_sha256=args.source_contract_sha256,
        )
    except (
        ContractError,
        KeyError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        ProducerError,
    ) as exc:
        _write_error_sidecar(exc)
        print(f"crucible replay producer failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
