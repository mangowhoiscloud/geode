#!/usr/bin/env python3
"""Resolve the only repository refs trusted by the roadmap CI gate.

The resolver keeps GitHub event authorization and Git graph validation in one
executable boundary.  It prints one fully qualified remote-tracking ref, or an
empty line when the event receives no cross-branch trust.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from scripts.git_command import GitExecutableNotFoundError, run_git

REPO_ROOT = Path(__file__).resolve().parents[1]
REMOTE_MAIN_REF = "refs/remotes/origin/main"
REMOTE_DEVELOP_REF = "refs/remotes/origin/develop"
SYNC_BRANCH_PREFIX = "sync/main-into-develop-"
FULL_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class RoadmapTrustError(ValueError):
    """Raised when a trust-eligible event has an invalid or stale Git graph."""


def _commit_sha(ref: str, *, repo_root: Path) -> str:
    process = run_git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=repo_root)
    sha = process.stdout.strip()
    if process.returncode != 0 or FULL_SHA_PATTERN.fullmatch(sha) is None:
        detail = process.stderr.strip() or f"git rev-parse exited {process.returncode}"
        raise RoadmapTrustError(f"cannot resolve canonical ref {ref}: {detail}")
    return sha


def _commit_parents(head_sha: str, *, repo_root: Path) -> tuple[str, ...]:
    if FULL_SHA_PATTERN.fullmatch(head_sha) is None:
        raise RoadmapTrustError("pull-request head SHA must be exactly 40 lowercase hex characters")
    process = run_git(
        ["show", "-s", "--format=%P", f"{head_sha}^{{commit}}"],
        cwd=repo_root,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or f"git show exited {process.returncode}"
        raise RoadmapTrustError(f"cannot inspect pull-request head {head_sha}: {detail}")
    return tuple(process.stdout.strip().split())


def _require_direct_head(
    head_sha: str,
    canonical_ref: str,
    *,
    repo_root: Path,
) -> None:
    if FULL_SHA_PATTERN.fullmatch(head_sha) is None:
        raise RoadmapTrustError("pull-request head SHA must be exactly 40 lowercase hex characters")
    expected = _commit_sha(canonical_ref, repo_root=repo_root)
    if head_sha != expected:
        raise RoadmapTrustError(
            f"direct branch head {head_sha} is stale; current {canonical_ref} is {expected}"
        )


def _require_exact_sync_head(head_sha: str, *, repo_root: Path) -> None:
    expected = (
        _commit_sha(REMOTE_DEVELOP_REF, repo_root=repo_root),
        _commit_sha(REMOTE_MAIN_REF, repo_root=repo_root),
    )
    actual = _commit_parents(head_sha, repo_root=repo_root)
    if actual != expected:
        raise RoadmapTrustError(
            "trusted sync HEAD must merge exact current "
            f"{REMOTE_DEVELOP_REF} + {REMOTE_MAIN_REF} parents; "
            f"expected={' '.join(expected)} actual={' '.join(actual) or '<none>'}"
        )


def resolve_trusted_ref(
    *,
    event_mode: str,
    target_branch: str,
    head_ref: str = "",
    head_repo: str = "",
    repository: str = "",
    head_sha: str = "",
    repo_root: Path = REPO_ROOT,
) -> str | None:
    """Return the authorized fully qualified ref, validating eligible heads."""
    if event_mode not in {"pull_request", "push"}:
        raise RoadmapTrustError(f"unknown event mode {event_mode!r}")
    if target_branch not in {"develop", "main"}:
        raise RoadmapTrustError(f"unknown target branch {target_branch!r}")

    if event_mode == "push":
        return REMOTE_MAIN_REF if target_branch == "develop" else REMOTE_DEVELOP_REF

    if not repository or head_repo != repository:
        return None

    if target_branch == "develop" and head_ref == "main":
        _require_direct_head(head_sha, REMOTE_MAIN_REF, repo_root=repo_root)
        return REMOTE_MAIN_REF
    if target_branch == "develop" and head_ref.startswith(SYNC_BRANCH_PREFIX):
        _require_exact_sync_head(head_sha, repo_root=repo_root)
        return REMOTE_MAIN_REF
    if target_branch == "main" and head_ref == "develop":
        _require_direct_head(head_sha, REMOTE_DEVELOP_REF, repo_root=repo_root)
        return REMOTE_DEVELOP_REF
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-mode", choices=("pull_request", "push"), required=True)
    parser.add_argument("--target-branch", choices=("develop", "main"), required=True)
    parser.add_argument("--head-ref", default="")
    parser.add_argument("--head-repo", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--head-sha", default="")
    parser.add_argument(
        "--require-trust",
        choices=("main", "develop"),
        help="fail unless the event resolves to the requested canonical branch",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        trusted_ref = resolve_trusted_ref(
            event_mode=args.event_mode,
            target_branch=args.target_branch,
            head_ref=args.head_ref,
            head_repo=args.head_repo,
            repository=args.repository,
            head_sha=args.head_sha,
        )
        required_ref = {
            "main": REMOTE_MAIN_REF,
            "develop": REMOTE_DEVELOP_REF,
            None: None,
        }[args.require_trust]
        if required_ref is not None and trusted_ref != required_ref:
            raise RoadmapTrustError(f"event does not qualify for required {required_ref} trust")
    except (GitExecutableNotFoundError, RoadmapTrustError) as error:
        print(f"architecture roadmap trust: {error}", file=sys.stderr)
        return 2

    print(trusted_ref or "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
