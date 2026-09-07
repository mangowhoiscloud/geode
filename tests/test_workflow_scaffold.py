import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HYGIENE_SCRIPT = ROOT / "scripts" / "check_repo_hygiene.py"


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def test_evidence_first_workflow_has_required_scaffold_sections() -> None:
    workflow = _read("docs/workflow.md")

    required_sections = [
        "# GEODE Evidence-First Development Workflow",
        "## Core Loop",
        "## Progressive Disclosure Map",
        "## Worktree And GitFlow",
        "## Minimum Verification",
        ".claude/skills/geode-workflow/SKILL.md",
    ]

    for section in required_sections:
        assert section in workflow


def test_geode_workflow_skill_uses_progressive_disclosure() -> None:
    skill = _read(".claude/skills/geode-workflow/SKILL.md")

    required_references = [
        "references/phase-checklist.md",
        "references/provider-grounding.md",
        "references/observability-contract.md",
        "references/codex-geode-paired-coding.md",
        "references/verification-gates.md",
        "references/gitflow.md",
    ]

    assert "name: geode-workflow" in skill
    assert "description:" in skill
    assert "## Reference Routing" in skill
    for reference in required_references:
        assert reference in skill
        assert (ROOT / ".claude/skills/geode-workflow" / reference).exists()


def test_paired_coding_reference_preserves_runtime_and_verification_boundaries() -> None:
    reference_path = ".claude/skills/geode-workflow/references/codex-geode-paired-coding.md"
    reference = _read(reference_path)
    workflow = _read("docs/workflow.md")

    for required in (
        "## Production Workflow",
        "## Verification Workflow",
        "base_sha",
        "brief_sha256",
        "allowed_paths",
        "protected_paths",
        "acceptance_commands",
        "geode-mcp run_agent",
        "CodexOAuthAdapter",
        "inside GEODE's AgenticLoop",
        "launches native `codex exec`",
        "`codex` and `codex-reply`",
        "must not auto-merge or auto-promote",
    ):
        assert required in reference

    for stale_tool in ("mcp__codex__exec", "mcp__codex__review", "mcp__codex__apply"):
        assert stale_tool not in reference

    assert reference_path in workflow


def test_agent_entrypoints_reference_canonical_workflow() -> None:
    for path in ("CLAUDE.md", "AGENTS.md"):
        text = _read(path)

        assert "docs/workflow.md" in text
        assert ".claude/skills/geode-workflow/" in text
        assert "evidence-first" in text.lower()


def test_worktree_free_contract_is_shared_by_every_entrypoint() -> None:
    command = "scripts/check_repo_hygiene.py free-merged-worktree"
    paths = (
        "AGENTS.md",
        "CLAUDE.md",
        "docs/workflow.md",
        ".claude/skills/geode-gitflow/SKILL.md",
    )

    for path in paths:
        assert command in _read(path), path

    gitflow = _read(".claude/skills/geode-gitflow/SKILL.md")
    workflow_reference = _read(".claude/skills/geode-workflow/references/gitflow.md")
    assert "git branch -d feature/<branch-name>" not in gitflow
    assert "git checkout develop &&" not in gitflow
    assert "gh pr merge <PR#> --squash --delete-branch" not in gitflow
    canonical_link = "../../geode-gitflow/SKILL.md"
    assert canonical_link in workflow_reference
    reference_dir = ROOT / ".claude/skills/geode-workflow/references"
    assert (reference_dir / canonical_link).resolve() == (
        ROOT / ".agents/skills/geode-gitflow/SKILL.md"
    ).resolve()
    assert "gh pr merge --delete-branch" in gitflow
    assert "gh api --method PUT repos/mangowhoiscloud/geode/pulls/" in gitflow


def _run(cwd: Path, *argv: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed test commands, no shell expansion
        list(argv),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def _prepare_repo(
    tmp_path: Path,
    *,
    advance_base_before_merge: bool = False,
    advance_after_merge: bool = False,
) -> tuple[Path, Path, dict[str, object]]:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    _run(tmp_path, "git", "init", "--bare", str(remote))
    _run(tmp_path, "git", "init", str(repo))
    _run(repo, "git", "config", "user.email", "test@example.com")
    _run(repo, "git", "config", "user.name", "GEODE Test")
    _run(repo, "git", "remote", "add", "origin", str(remote))

    (repo / ".gitignore").write_text(".owner\n.claude/worktrees/\n", encoding="utf-8")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-m", "base")
    _run(repo, "git", "branch", "-M", "develop")
    _run(repo, "git", "push", "-u", "origin", "develop")

    branch = "feature/demo"
    _run(repo, "git", "switch", "-c", branch)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _run(repo, "git", "add", "feature.txt")
    _run(repo, "git", "commit", "-m", "feature")
    feature_oid = _run(repo, "git", "rev-parse", "HEAD").stdout.strip()
    _run(repo, "git", "push", "-u", "origin", branch)

    _run(repo, "git", "switch", "develop")
    if advance_base_before_merge:
        (repo / "base-advance.txt").write_text("base advanced\n", encoding="utf-8")
        _run(repo, "git", "add", "base-advance.txt")
        _run(repo, "git", "commit", "-m", "advance base")
        _run(repo, "git", "push", "origin", "develop")
    _run(repo, "git", "merge", "--squash", branch)
    _run(repo, "git", "commit", "-m", "squash feature")
    merge_oid = _run(repo, "git", "rev-parse", "HEAD").stdout.strip()
    _run(repo, "git", "push", "origin", "develop")

    target = repo / ".claude" / "worktrees" / "demo"
    target.parent.mkdir(parents=True)
    _run(repo, "git", "worktree", "add", str(target), branch)
    (target / ".owner").write_text("session=test-session task_id=demo\n", encoding="utf-8")

    if advance_after_merge:
        (target / "unmerged.txt").write_text("not merged\n", encoding="utf-8")
        _run(target, "git", "add", "unmerged.txt")
        _run(target, "git", "commit", "-m", "post-merge work")
        feature_oid = _run(target, "git", "rev-parse", "HEAD").stdout.strip()
        _run(target, "git", "push", "origin", branch)

    _run(tmp_path, "git", f"--git-dir={remote}", "update-ref", "refs/pull/7/head", feature_oid)
    return (
        repo,
        target,
        {
            "state": "MERGED",
            "headRefName": branch,
            "headRefOid": feature_oid,
            "mergeCommit": {"oid": merge_oid},
            "url": "https://example.invalid/pull/7",
        },
    )


def _run_cleanup(
    repo: Path, target: Path, details: dict[str, object]
) -> subprocess.CompletedProcess[str]:
    fake_bin = repo.parent / "bin"
    fake_bin.mkdir(exist_ok=True)
    fake_gh = fake_bin / "gh"
    payload = json.dumps(details, separators=(",", ":"))
    fake_gh.write_text(f"#!/bin/sh\nprintf '%s\\n' '{payload}'\n", encoding="utf-8")
    fake_gh.chmod(0o755)
    env = os.environ | {"PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run(  # noqa: S603 - fixed interpreter and audited script path
        [
            sys.executable,
            str(HYGIENE_SCRIPT),
            "free-merged-worktree",
            "--pr",
            "7",
            "--worktree",
            str(target.relative_to(repo)),
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_frees_clean_squash_merged_worktree(tmp_path: Path) -> None:
    repo, target, details = _prepare_repo(tmp_path)

    result = _run_cleanup(repo, target, details)

    assert result.returncode == 0, result.stderr
    assert "freed: verified PR #7" in result.stdout
    assert not target.exists()
    assert not _run(repo, "git", "branch", "--list", "feature/demo").stdout.strip()
    assert not _run(repo, "git", "ls-remote", "--heads", "origin", "feature/demo").stdout.strip()


def test_frees_squash_merge_after_base_advanced(tmp_path: Path) -> None:
    repo, target, details = _prepare_repo(tmp_path, advance_base_before_merge=True)

    result = _run_cleanup(repo, target, details)

    assert result.returncode == 0, result.stderr
    assert not target.exists()


def test_refuses_branch_that_advanced_after_merge(tmp_path: Path) -> None:
    repo, target, details = _prepare_repo(tmp_path, advance_after_merge=True)

    result = _run_cleanup(repo, target, details)

    assert result.returncode == 1
    assert "squash merge tree differs from replaying its final PR head" in result.stderr
    assert target.exists()
    assert _run(repo, "git", "branch", "--list", "feature/demo").stdout.strip()
    assert _run(repo, "git", "ls-remote", "--heads", "origin", "feature/demo").stdout.strip()
