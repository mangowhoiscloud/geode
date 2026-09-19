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


def _resolve_feature(repo: Path, head_sha: str, **overrides: str) -> str | None:
    values = {
        "event_mode": "pull_request",
        "target_branch": "develop",
        "head_ref": "codex/feature",
        "head_repo": "mangowhoiscloud/geode",
        "repository": "mangowhoiscloud/geode",
        "head_sha": head_sha,
    }
    values.update(overrides)
    return resolver.resolve_trusted_ref(repo_root=repo, **values)


def test_feature_main_ancestry_uses_fully_qualified_refs(
    tmp_path: Path,
    graph: Graph,
) -> None:
    forged_main = _commit(tmp_path, graph.tree, "forged main", graph.root)
    _git(tmp_path, "update-ref", "refs/tags/origin/main", forged_main)

    assert _git(tmp_path, "rev-parse", "origin/main") == forged_main
    feature_head = _commit(tmp_path, graph.tree, "feature after sync", graph.sync)
    assert _resolve_feature(tmp_path, feature_head) == resolver.REMOTE_MAIN_REF


@pytest.mark.parametrize("head_ref", ["main", "sync/main-into-develop-test", "sync/other"])
def test_standalone_sync_prs_are_rejected_even_with_valid_ancestry(
    tmp_path: Path,
    graph: Graph,
    head_ref: str,
) -> None:
    with pytest.raises(resolver.RoadmapTrustError, match="standalone"):
        _resolve_feature(tmp_path, graph.sync, head_ref=head_ref)


def test_fork_receives_no_trust(tmp_path: Path, graph: Graph) -> None:
    assert (
        _resolve_feature(
            tmp_path,
            graph.sync,
            head_repo="untrusted/geode",
        )
        is None
    )


@pytest.mark.parametrize("head", ["missing", "stale", "invalid"])
def test_feature_requires_current_main_ancestry(tmp_path: Path, graph: Graph, head: str) -> None:
    head_sha = graph.develop
    if head == "stale":
        head_sha = graph.sync
        new_main = _commit(tmp_path, graph.tree, "new main", graph.main)
        _git(tmp_path, "update-ref", resolver.REMOTE_MAIN_REF, new_main)
    elif head == "invalid":
        head_sha = "not-a-sha"
    with pytest.raises(resolver.RoadmapTrustError):
        _resolve_feature(tmp_path, head_sha)


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

    _git(tmp_path, "update-ref", resolver.REMOTE_DEVELOP_REF, graph.sync)
    assert (
        resolver.resolve_trusted_ref(
            target_branch="main",
            head_ref="develop",
            head_sha=graph.sync,
            **common,
        )
        == resolver.REMOTE_DEVELOP_REF
    )
    with pytest.raises(resolver.RoadmapTrustError, match="is stale"):
        resolver.resolve_trusted_ref(
            target_branch="main",
            head_ref="develop",
            head_sha=graph.develop,
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
