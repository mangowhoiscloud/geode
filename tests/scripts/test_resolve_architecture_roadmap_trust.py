"""Executable Git-graph tests for architecture-roadmap trust resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from scripts import resolve_architecture_roadmap_trust as resolver
from scripts.git_command import run_git


@dataclass(frozen=True)
class Graph:
    root: str
    develop: str
    main: str
    sync: str
    tree: str


def _git(repo: Path, *args: str) -> str:
    process = run_git(args, cwd=repo)
    assert process.returncode == 0, process.stderr
    return process.stdout.strip()


def _commit(repo: Path, tree: str, message: str, *parents: str) -> str:
    args = ["commit-tree", tree]
    for parent in parents:
        args.extend(("-p", parent))
    args.extend(("-m", message))
    return _git(repo, *args)


@pytest.fixture
def graph(tmp_path: Path) -> Graph:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "GEODE CI")
    _git(tmp_path, "config", "user.email", "ci@example.invalid")
    (tmp_path / "fixture.txt").write_text("roadmap trust fixture\n", encoding="utf-8")
    _git(tmp_path, "add", "fixture.txt")
    tree = _git(tmp_path, "write-tree")
    root = _commit(tmp_path, tree, "root")
    develop = _commit(tmp_path, tree, "develop", root)
    main = _commit(tmp_path, tree, "main", root)
    sync = _commit(tmp_path, tree, "sync", develop, main)
    _git(tmp_path, "update-ref", resolver.REMOTE_DEVELOP_REF, develop)
    _git(tmp_path, "update-ref", resolver.REMOTE_MAIN_REF, main)
    return Graph(root=root, develop=develop, main=main, sync=sync, tree=tree)


def _resolve_sync(repo: Path, head_sha: str, **overrides: str) -> str | None:
    values = {
        "event_mode": "pull_request",
        "target_branch": "develop",
        "head_ref": "sync/main-into-develop-test",
        "head_repo": "mangowhoiscloud/geode",
        "repository": "mangowhoiscloud/geode",
        "head_sha": head_sha,
    }
    values.update(overrides)
    return resolver.resolve_trusted_ref(repo_root=repo, **values)


def test_exact_two_parent_sync_uses_fully_qualified_refs(
    tmp_path: Path,
    graph: Graph,
) -> None:
    forged_main = _commit(tmp_path, graph.tree, "forged main", graph.root)
    _git(tmp_path, "update-ref", "refs/tags/origin/main", forged_main)

    assert _git(tmp_path, "rev-parse", "origin/main") == forged_main
    assert _resolve_sync(tmp_path, graph.sync) == resolver.REMOTE_MAIN_REF


@pytest.mark.parametrize("shape", ["stale", "swapped", "extra", "single"])
def test_sync_rejects_every_non_exact_parent_shape(
    tmp_path: Path,
    graph: Graph,
    shape: str,
) -> None:
    candidates = {
        "stale": _commit(tmp_path, graph.tree, "stale", graph.develop, graph.root),
        "swapped": _commit(tmp_path, graph.tree, "swapped", graph.main, graph.develop),
        "extra": _commit(
            tmp_path,
            graph.tree,
            "extra",
            graph.develop,
            graph.main,
            graph.root,
        ),
        "single": _commit(tmp_path, graph.tree, "single", graph.develop),
    }

    with pytest.raises(resolver.RoadmapTrustError, match="exact current"):
        _resolve_sync(tmp_path, candidates[shape])


def test_fork_and_non_sync_branches_receive_no_trust(tmp_path: Path, graph: Graph) -> None:
    assert (
        _resolve_sync(
            tmp_path,
            graph.sync,
            head_repo="untrusted/geode",
        )
        is None
    )
    assert (
        _resolve_sync(
            tmp_path,
            graph.sync,
            head_ref="feature/not-a-sync",
        )
        is None
    )


def test_direct_canonical_branches_must_match_current_remote_tips(
    tmp_path: Path,
    graph: Graph,
) -> None:
    common = {
        "event_mode": "pull_request",
        "head_repo": "mangowhoiscloud/geode",
        "repository": "mangowhoiscloud/geode",
        "repo_root": tmp_path,
    }

    assert (
        resolver.resolve_trusted_ref(
            target_branch="develop",
            head_ref="main",
            head_sha=graph.main,
            **common,
        )
        == resolver.REMOTE_MAIN_REF
    )
    assert (
        resolver.resolve_trusted_ref(
            target_branch="main",
            head_ref="develop",
            head_sha=graph.develop,
            **common,
        )
        == resolver.REMOTE_DEVELOP_REF
    )
    with pytest.raises(resolver.RoadmapTrustError, match="is stale"):
        resolver.resolve_trusted_ref(
            target_branch="develop",
            head_ref="main",
            head_sha=graph.root,
            **common,
        )


def test_push_trust_is_target_specific_and_uses_full_refs(tmp_path: Path, graph: Graph) -> None:
    del graph
    assert (
        resolver.resolve_trusted_ref(
            event_mode="push",
            target_branch="develop",
            repo_root=tmp_path,
        )
        == resolver.REMOTE_MAIN_REF
    )
    assert (
        resolver.resolve_trusted_ref(
            event_mode="push",
            target_branch="main",
            repo_root=tmp_path,
        )
        == resolver.REMOTE_DEVELOP_REF
    )
