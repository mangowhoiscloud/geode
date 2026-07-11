"""Deterministically replay one preregistered candidate after invalid measurement."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from .codex_kg import (
    ProducerError,
    _load_object,
    _text,
    _validate_policy_grammar,
    _write_exclusive,
)

_REQUEST_SCHEMA = "crucible.proposal-request.v3"
_CANDIDATE_SCHEMA = "crucible.candidate.v2"
_FULL_SHA = re.compile(r"[0-9a-f]{40}")
_DEFAULT_HYPOTHESIS = (
    "Replay the preregistered candidate after an infrastructure-only invalidation."
)


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


def replay_candidate(
    *,
    request_path: Path,
    output_path: Path,
    source_repository: Path,
    source_candidate: str,
    hypothesis: str = _DEFAULT_HYPOTHESIS,
) -> None:
    """Reapply an attested source diff only when its baseline blob still matches."""

    started = time.monotonic()
    request = _load_object(request_path, "proposal request")
    if request.get("schema") != _REQUEST_SCHEMA:
        raise ProducerError(f"proposal request must use {_REQUEST_SCHEMA}")
    surface = _surface(request)
    parent_sha = _sha(request.get("parent_sha"), "request parent_sha")
    source_candidate = _sha(source_candidate, "source candidate")
    hypothesis = _text(hypothesis, "hypothesis")
    source_repository = source_repository.resolve()
    if not source_repository.is_dir():
        raise ProducerError("source repository must exist")
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise ProducerError("candidate checkout must start clean")
    if _git("rev-parse", "HEAD") != parent_sha:
        raise ProducerError("candidate checkout HEAD must match request parent_sha")

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

    _git(
        "restore",
        f"--source={source_candidate}",
        "--staged",
        "--worktree",
        "--",
        surface,
    )
    changed = tuple(
        path for path in _git("diff", "--cached", "--name-only", "--").splitlines() if path.strip()
    )
    if changed != (surface,):
        raise ProducerError(f"replay must change exactly {(surface,)!r}; observed {changed!r}")
    surface_path = Path(surface)
    if surface_path.is_symlink() or not surface_path.is_file():
        raise ProducerError("candidate surface must remain a regular file")
    if surface_path.stat().st_size > 16 * 1024:
        raise ProducerError("candidate surface exceeds 16384 bytes")
    _validate_policy_grammar(surface_path.read_text(encoding="utf-8"))
    _git("commit", "-qm", f"crucible: replay candidate {request['iteration']}")
    candidate_sha = _git("rev-parse", "HEAD")
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
    parser.add_argument("--source-candidate", required=True)
    parser.add_argument("--hypothesis", default=_DEFAULT_HYPOTHESIS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    replay_candidate(
        request_path=Path(os.environ["CRUCIBLE_PROPOSAL_REQUEST"]),
        output_path=Path(os.environ["CRUCIBLE_CANDIDATE_OUTPUT"]),
        source_repository=args.source_repository,
        source_candidate=args.source_candidate,
        hypothesis=args.hypothesis,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
