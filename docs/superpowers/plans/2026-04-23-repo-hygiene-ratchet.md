# Repo Hygiene Ratchet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CI-enforced repo hygiene ratchet (dangling/absolute symlink + orphan `.claude/worktrees/` detection) and clean up an accidentally-tracked root `.owner` file so the worktree ownership convention in CLAUDE.md §0 no longer pollutes feature branches. Release as PATCH v0.48.1.

**Architecture:** Single stdlib-only Python script `scripts/check_repo_hygiene.py` mirroring the existing `scripts/check_legacy_imports.py` pattern. Wired into the CI `lint` job as one additional step. Tests use subprocess invocation with `tmp_path` fixtures for isolation. Cleanup is a three-file change (`git rm .owner` + `.gitignore` add + CLAUDE.md one-line note). Version bump follows the 4-location sync rule from CLAUDE.md §5.

**Tech Stack:** Python 3.12 stdlib only (`pathlib`, `os`, `sys`), pytest, GitHub Actions, uv.

**Worktree context:** Already allocated at `.claude/worktrees/repo-hygiene-ratchet/` on branch `feature/repo-hygiene-ratchet` (from `origin/develop`). Design spec committed in `docs/superpowers/specs/2026-04-23-repo-hygiene-ratchet-design.md`.

---

## File Structure

| File | Status | Responsibility |
|------|--------|----------------|
| `scripts/check_repo_hygiene.py` | Create | Ratchet logic: scan, classify, report, exit |
| `tests/test_check_repo_hygiene.py` | Create | Unit tests via subprocess with tmp_path |
| `.github/workflows/ci.yml` | Modify | Add step in `lint` job |
| `.owner` | Delete | Stale tracked file from commit 6d07637 |
| `.gitignore` | Modify | Add `/.owner` pattern |
| `CLAUDE.md` | Modify | Version line + §0 one-line note |
| `pyproject.toml` | Modify | Version `0.48.0` → `0.48.1` |
| `README.md` | Modify | Version in header |
| `CHANGELOG.md` | Modify | New `[0.48.1]` section |

### Script module layout (`scripts/check_repo_hygiene.py`)

```
EXCLUDED_DIRS = frozenset({".git", ".venv", "node_modules", ".claude/worktrees"})

def is_excluded_for_symlink_scan(rel: Path) -> bool   # prefix match
def find_dangling_symlinks(root: Path) -> list[tuple[Path, str]]
def find_absolute_symlinks(root: Path) -> list[tuple[Path, str]]
def find_orphan_worktrees(root: Path) -> list[Path]
def format_report(...) -> str
def main() -> int                                      # cwd-rooted
```

All functions are pure (take paths, return data). Only `main()` does I/O (stdout/stderr, exit code).

---

## Task 1: Scaffold the test file and script stub

**Files:**
- Create: `scripts/check_repo_hygiene.py`
- Create: `tests/test_check_repo_hygiene.py`

- [ ] **Step 1: Write the failing test for clean-repo passes**

Create `tests/test_check_repo_hygiene.py`:

```python
"""Unit tests for scripts/check_repo_hygiene.py ratchet."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_repo_hygiene.py"


def run_check(cwd: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the ratchet script with the given working directory."""
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_clean_repo_passes(tmp_path: Path) -> None:
    result = run_check(tmp_path)
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run the test — expect FAIL because script doesn't exist yet**

Run:
```bash
uv run pytest tests/test_check_repo_hygiene.py::test_clean_repo_passes -v
```
Expected: FAIL (FileNotFoundError or non-zero exit from missing script).

- [ ] **Step 3: Write the minimal script stub that exits 0**

Create `scripts/check_repo_hygiene.py`:

```python
#!/usr/bin/env python3
"""CI ratchet: reject repo-shape regressions (dangling/absolute symlinks, orphan worktrees).

Usage:
    python scripts/check_repo_hygiene.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test — expect PASS**

Run:
```bash
uv run pytest tests/test_check_repo_hygiene.py::test_clean_repo_passes -v
```
Expected: PASS.

No commit yet — Task 9 commits the whole script + tests together.

---

## Task 2: Dangling symlink detection

**Files:**
- Modify: `scripts/check_repo_hygiene.py`
- Modify: `tests/test_check_repo_hygiene.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_check_repo_hygiene.py`:

```python
def test_dangling_symlink_fails(tmp_path: Path) -> None:
    # Relative-path symlink to a nonexistent target → dangling only, not absolute
    (tmp_path / "broken").symlink_to("nonexistent-target")
    result = run_check(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "dangling symlink" in result.stderr
    assert "broken" in result.stderr
```

- [ ] **Step 2: Run the test — expect FAIL**

Run:
```bash
uv run pytest tests/test_check_repo_hygiene.py::test_dangling_symlink_fails -v
```
Expected: FAIL (script currently always exits 0).

- [ ] **Step 3: Implement dangling detection + report**

Replace the body of `scripts/check_repo_hygiene.py` with:

```python
#!/usr/bin/env python3
"""CI ratchet: reject repo-shape regressions (dangling/absolute symlinks, orphan worktrees).

Usage:
    python scripts/check_repo_hygiene.py

Exits 0 if clean, 1 on violations (details on stderr).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

EXCLUDED_DIRS: frozenset[tuple[str, ...]] = frozenset({
    (".git",),
    (".venv",),
    ("node_modules",),
    (".claude", "worktrees"),
})


def is_excluded_for_symlink_scan(rel: Path) -> bool:
    """True if `rel` lives under any excluded directory."""
    parts = rel.parts
    for prefix in EXCLUDED_DIRS:
        if len(parts) >= len(prefix) and parts[: len(prefix)] == prefix:
            return True
    return False


def _iter_symlinks(root: Path) -> list[Path]:
    """Yield every symlink under `root`, pruning excluded subtrees."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        rel_current = current.relative_to(root)
        # Prune excluded directories in-place
        dirnames[:] = [
            d for d in dirnames
            if not is_excluded_for_symlink_scan(rel_current / d)
        ]
        # Check both filenames AND dirnames for symlinks
        # (os.walk with followlinks=False yields symlink-dirs as dirnames)
        for name in filenames + dirnames:
            candidate = current / name
            if candidate.is_symlink():
                found.append(candidate)
    return found


def find_dangling_symlinks(root: Path) -> list[tuple[Path, str]]:
    """Return (path, target) for each symlink whose target does not exist."""
    result: list[tuple[Path, str]] = []
    for link in _iter_symlinks(root):
        target = os.readlink(link)
        if not link.exists():
            result.append((link, target))
    return result


def format_report(
    root: Path,
    dangling: list[tuple[Path, str]],
) -> str:
    total = len(dangling)
    if total == 0:
        return ""
    lines = [f"Repo hygiene check: {total} issues", ""]
    if dangling:
        lines.append("[dangling symlink]")
        for path, target in dangling:
            lines.append(f"  {path.relative_to(root)} -> {target}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    root = Path.cwd()
    dangling = find_dangling_symlinks(root)
    report = format_report(root, dangling)
    if report:
        print(report, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run both tests — expect PASS**

Run:
```bash
uv run pytest tests/test_check_repo_hygiene.py -v
```
Expected: 2 PASS.

---

## Task 3: Absolute symlink detection

**Files:**
- Modify: `scripts/check_repo_hygiene.py`
- Modify: `tests/test_check_repo_hygiene.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_check_repo_hygiene.py`:

```python
def test_absolute_symlink_fails(tmp_path: Path) -> None:
    # Symlink to an existing absolute path → absolute only, not dangling
    real = tmp_path / "real_file"
    real.write_text("ok")
    (tmp_path / "abslink").symlink_to(str(real))  # str of absolute path
    result = run_check(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "absolute symlink" in result.stderr
    assert "abslink" in result.stderr
    assert "ln -sr" in result.stderr  # hint
```

- [ ] **Step 2: Run the test — expect FAIL**

Run:
```bash
uv run pytest tests/test_check_repo_hygiene.py::test_absolute_symlink_fails -v
```
Expected: FAIL.

- [ ] **Step 3: Add absolute check to the script**

Modify `scripts/check_repo_hygiene.py`:

1. Add the `find_absolute_symlinks` function below `find_dangling_symlinks`:

```python
def find_absolute_symlinks(root: Path) -> list[tuple[Path, str]]:
    """Return (path, target) for each symlink whose target is an absolute path."""
    result: list[tuple[Path, str]] = []
    for link in _iter_symlinks(root):
        target = os.readlink(link)
        if target.startswith("/"):
            result.append((link, target))
    return result
```

2. Update `format_report` signature + body:

```python
def format_report(
    root: Path,
    dangling: list[tuple[Path, str]],
    absolute: list[tuple[Path, str]],
) -> str:
    total = len(dangling) + len(absolute)
    if total == 0:
        return ""
    lines = [f"Repo hygiene check: {total} issues", ""]
    if dangling:
        lines.append("[dangling symlink]")
        for path, target in dangling:
            lines.append(f"  {path.relative_to(root)} -> {target}")
        lines.append("")
    if absolute:
        lines.append("[absolute symlink]")
        for path, target in absolute:
            lines.append(f"  {path.relative_to(root)} -> {target}")
            lines.append("    hint: use relative path (ln -sr)")
        lines.append("")
    return "\n".join(lines)
```

3. Update `main()`:

```python
def main() -> int:
    root = Path.cwd()
    dangling = find_dangling_symlinks(root)
    absolute = find_absolute_symlinks(root)
    report = format_report(root, dangling, absolute)
    if report:
        print(report, file=sys.stderr)
        return 1
    return 0
```

- [ ] **Step 4: Run all tests — expect PASS**

Run:
```bash
uv run pytest tests/test_check_repo_hygiene.py -v
```
Expected: 3 PASS.

---

## Task 4: Orphan worktree detection

**Files:**
- Modify: `scripts/check_repo_hygiene.py`
- Modify: `tests/test_check_repo_hygiene.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_check_repo_hygiene.py`:

```python
def test_orphan_worktree_fails(tmp_path: Path) -> None:
    (tmp_path / ".claude" / "worktrees" / "abandoned").mkdir(parents=True)
    # no .owner file
    result = run_check(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "orphan worktree" in result.stderr
    assert "abandoned" in result.stderr
    assert "missing .owner" in result.stderr
```

- [ ] **Step 2: Run the test — expect FAIL**

Run:
```bash
uv run pytest tests/test_check_repo_hygiene.py::test_orphan_worktree_fails -v
```
Expected: FAIL.

- [ ] **Step 3: Implement orphan worktree detection**

Add the function below `find_absolute_symlinks`:

```python
def find_orphan_worktrees(root: Path) -> list[Path]:
    """Return each .claude/worktrees/<name>/ directory missing an `.owner` file."""
    worktrees_dir = root / ".claude" / "worktrees"
    if not worktrees_dir.is_dir():
        return []
    orphans: list[Path] = []
    for entry in sorted(worktrees_dir.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / ".owner").is_file():
            orphans.append(entry)
    return orphans
```

Update `format_report` signature + body:

```python
def format_report(
    root: Path,
    dangling: list[tuple[Path, str]],
    absolute: list[tuple[Path, str]],
    orphans: list[Path],
) -> str:
    total = len(dangling) + len(absolute) + len(orphans)
    if total == 0:
        return ""
    lines = [f"Repo hygiene check: {total} issues", ""]
    if dangling:
        lines.append("[dangling symlink]")
        for path, target in dangling:
            lines.append(f"  {path.relative_to(root)} -> {target}")
        lines.append("")
    if absolute:
        lines.append("[absolute symlink]")
        for path, target in absolute:
            lines.append(f"  {path.relative_to(root)} -> {target}")
            lines.append("    hint: use relative path (ln -sr)")
        lines.append("")
    if orphans:
        lines.append("[orphan worktree]")
        for path in orphans:
            lines.append(f"  {path.relative_to(root)}/")
            lines.append("    hint: missing .owner file; remove worktree or add .owner")
        lines.append("")
    return "\n".join(lines)
```

Update `main()`:

```python
def main() -> int:
    root = Path.cwd()
    dangling = find_dangling_symlinks(root)
    absolute = find_absolute_symlinks(root)
    orphans = find_orphan_worktrees(root)
    report = format_report(root, dangling, absolute, orphans)
    if report:
        print(report, file=sys.stderr)
        return 1
    return 0
```

- [ ] **Step 4: Run all tests — expect PASS**

Run:
```bash
uv run pytest tests/test_check_repo_hygiene.py -v
```
Expected: 4 PASS.

---

## Task 5: Valid worktree and exclusion negative tests

**Files:**
- Modify: `tests/test_check_repo_hygiene.py`

- [ ] **Step 1: Write the two negative-case tests**

Append to `tests/test_check_repo_hygiene.py`:

```python
def test_valid_worktree_passes(tmp_path: Path) -> None:
    worktree = tmp_path / ".claude" / "worktrees" / "valid"
    worktree.mkdir(parents=True)
    (worktree / ".owner").write_text("session=x task_id=y\n")
    result = run_check(tmp_path)
    assert result.returncode == 0, result.stderr


def test_excluded_paths_ignored(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    # A dangling symlink inside .git/ must be ignored
    (git_dir / "broken").symlink_to("nonexistent")
    result = run_check(tmp_path)
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run all tests — expect PASS (no implementation change needed)**

Run:
```bash
uv run pytest tests/test_check_repo_hygiene.py -v
```
Expected: 6 PASS.

These tests verify the existing logic without requiring new code — if they fail, the exclusion list or orphan-presence logic needs a bug fix before proceeding.

---

## Task 6: Manual verification on the real repo + commit A

**Files:**
- No code changes. Verifies script behavior against the actual repo state.

- [ ] **Step 1: Run ratchet against the real repo**

Run from worktree root:
```bash
uv run python scripts/check_repo_hygiene.py
echo "exit=$?"
```
Expected: `exit=0` — repo currently has zero dangling/absolute symlinks, `.claude/worktrees/` is gitignored so the CI view has no orphans.

- [ ] **Step 2: Create a temporary dangling symlink and verify the ratchet catches it**

```bash
ln -s /nonexistent/path /tmp/repo-hygiene-probe-$$ 2>/dev/null || true
ln -s /tmp/repo-hygiene-probe-$$ ./probe-link
uv run python scripts/check_repo_hygiene.py
echo "exit=$?"
rm -f ./probe-link
```
Expected: `exit=1`, stderr lists `probe-link` under `[absolute symlink]` (target is `/tmp/...`).

- [ ] **Step 3: Run quality gates on changed files only**

```bash
uv run ruff check scripts/check_repo_hygiene.py tests/test_check_repo_hygiene.py
uv run ruff format --check scripts/check_repo_hygiene.py tests/test_check_repo_hygiene.py
```
Expected: 0 errors. If formatter flags issues, run `uv run ruff format` on those two files and re-check.

- [ ] **Step 4: Commit A — script + tests**

```bash
git add scripts/check_repo_hygiene.py tests/test_check_repo_hygiene.py
git commit -m "$(cat <<'EOF'
feat(ratchet): add repo hygiene checker script

Detects dangling symlinks, absolute-path symlinks, and orphan
.claude/worktrees/ entries missing .owner metadata. Pure stdlib,
follows scripts/check_legacy_imports.py pattern.

6 unit tests via subprocess + tmp_path fixture.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Verify commit**

```bash
git log --oneline -3
git show --stat HEAD
```
Expected: new commit shows only the two new files.

---

## Task 7: CI integration + commit B

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Inspect current lint job**

```bash
grep -n "Legacy import ratchet" .github/workflows/ci.yml
```
Expected: matches around line 22–25 — that's the insertion point.

- [ ] **Step 2: Add the step after "Legacy import ratchet"**

Open `.github/workflows/ci.yml` and add immediately after the `Legacy import ratchet` step in the `lint` job:

```yaml
      - name: Repo hygiene ratchet
        run: uv run python scripts/check_repo_hygiene.py
```

- [ ] **Step 3: Validate YAML structure**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "yaml ok"
```
Expected: `yaml ok` (no exception).

- [ ] **Step 4: Simulate the step locally**

```bash
uv run python scripts/check_repo_hygiene.py
echo "exit=$?"
```
Expected: `exit=0`.

- [ ] **Step 5: Commit B — CI wiring**

```bash
git add .github/workflows/ci.yml
git commit -m "$(cat <<'EOF'
ci: wire repo hygiene ratchet into lint job

Adds one step running scripts/check_repo_hygiene.py inside the
existing lint job — same runner as the legacy-import ratchet,
no extra uv sync.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Remove stale root `.owner` + gitignore hardening + CLAUDE.md note + commit C

**Files:**
- Delete: `.owner`
- Modify: `.gitignore`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Verify the stale file exists and show its content**

```bash
git ls-files .owner
cat .owner
```
Expected: `.owner` listed, content is `session=2026-04-08T04:33:31+09:00 task_id=layer-violation-fix`.

- [ ] **Step 2: Remove it from the index**

```bash
git rm .owner
```
Expected: `rm '.owner'`.

- [ ] **Step 3: Add `/.owner` to `.gitignore`**

Open `.gitignore`. Find the section:

```
# Scaffold harness — local-only
.claude/commands/
.claude/hooks/
.claude/skills/
.claude/workflow-state.json
.claude/worktrees/
.claude/MEMORY.md
```

Append after this block:

```

# Worktree ownership metadata (CLAUDE.md §0 convention writes to worktree checkout root)
/.owner
```

- [ ] **Step 4: Add a one-line note to CLAUDE.md §0**

Open `CLAUDE.md`. Find the line in §0 Board + Worktree Alloc:

```
echo "session=$(date -Iseconds) task_id=<task-name>" > .claude/worktrees/<task-name>/.owner
```

Replace the surrounding block so it reads:

```
# 2) Allocate Worktree
git fetch origin
# Verify main/develop sync (pull if out of sync)
git worktree add .claude/worktrees/<task-name> -b feature/<branch-name> develop
# Note: the target path IS the worktree checkout root; `.owner` is gitignored
# (see /.owner in .gitignore) so the convention does not pollute feature branches.
echo "session=$(date -Iseconds) task_id=<task-name>" > .claude/worktrees/<task-name>/.owner
```

- [ ] **Step 5: Verify the ratchet still passes on the cleaned-up repo**

```bash
uv run python scripts/check_repo_hygiene.py
echo "exit=$?"
```
Expected: `exit=0`.

- [ ] **Step 6: Verify git sees the three changes correctly**

```bash
git status --short
```
Expected:
```
D  .owner
M  .gitignore
M  CLAUDE.md
```

- [ ] **Step 7: Commit C — cleanup**

```bash
git add .gitignore CLAUDE.md
git commit -m "$(cat <<'EOF'
chore: remove stale tracked .owner + gitignore worktree metadata

The root .owner file was committed accidentally in 6d07637 during a
docs reorganization. Because CLAUDE.md §0 instructs each worktree
allocation to write session metadata to .claude/worktrees/<name>/.owner
— which is literally the worktree checkout root — every allocation
silently modified the tracked file and every worktree trivially
satisfied any "owner presence" check.

- git rm .owner (stale, no consumer)
- /.owner added to .gitignore (CLAUDE.md convention is now safe)
- CLAUDE.md §0: one-line note explaining the gitignore interaction

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 8: Verify commit**

```bash
git show --stat HEAD
```
Expected: 3 files changed — `.owner` deleted, `.gitignore` and `CLAUDE.md` modified.

---

## Task 9: Version bump to 0.48.1 across 4 locations + CHANGELOG + commit D

**Files:**
- Modify: `pyproject.toml`
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Bump `pyproject.toml`**

Edit line 3 of `pyproject.toml`:

```toml
version = "0.48.1"
```

- [ ] **Step 2: Bump `CLAUDE.md` version line**

Edit line 11 of `CLAUDE.md`:

```markdown
- **Version**: 0.48.1
```

- [ ] **Step 3: Bump `README.md` header**

Edit line 21 of `README.md`. Find:

```markdown
# GEODE v0.48.0 — Long-running Autonomous Execution Harness
```

Change to:

```markdown
# GEODE v0.48.1 — Long-running Autonomous Execution Harness
```

- [ ] **Step 4: Add `[0.48.1]` section to `CHANGELOG.md`**

Open `CHANGELOG.md`. Find:

```markdown
## [Unreleased]

## [0.48.0] — 2026-04-11
```

Insert between them:

```markdown
## [Unreleased]

## [0.48.1] — 2026-04-23

### Infrastructure
- Added repo hygiene ratchet — CI blocks PRs introducing dangling symlinks, absolute-path symlinks, or orphan `.claude/worktrees/` entries missing `.owner` metadata (`scripts/check_repo_hygiene.py`, wired into the `lint` job).
- Removed stale tracked `.owner` at repo root (accidentally committed via 6d07637) and added `/.owner` to `.gitignore` so the worktree ownership convention in CLAUDE.md §0 no longer pollutes feature branches.

## [0.48.0] — 2026-04-11
```

- [ ] **Step 5: Cross-check all 4 locations**

```bash
grep -rn "0.48.1" pyproject.toml CLAUDE.md README.md CHANGELOG.md | sort
```
Expected: exactly 4 matches — one per file.

```bash
grep -rn "0.48.0" pyproject.toml CLAUDE.md README.md | grep -v CHANGELOG
```
Expected: empty (only CHANGELOG still mentions 0.48.0 as the previous release).

- [ ] **Step 6: Commit D — version bump**

```bash
git add pyproject.toml CLAUDE.md README.md CHANGELOG.md
git commit -m "$(cat <<'EOF'
chore: bump version to 0.48.1

Release notes in CHANGELOG: repo hygiene ratchet + .owner cleanup.
4-location version sync (pyproject.toml, CLAUDE.md, README.md, CHANGELOG.md).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Full verification before PR

**Files:**
- No changes. Final quality gate sweep.

- [ ] **Step 1: Lint**

```bash
uv run ruff check core/ tests/ scripts/
uv run ruff format --check core/ tests/ scripts/
```
Expected: 0 errors each. Fix and re-run if flagged.

- [ ] **Step 2: Type check**

```bash
uv run mypy core/
```
Expected: 0 errors. (`scripts/` is not in CI mypy scope; new script is type-annotated for hygiene but not gated.)

- [ ] **Step 3: Full test suite (excluding live)**

```bash
uv run pytest tests/ -m "not live" -q
```
Expected: previous count + 6 new tests pass. Record the exact pass count — will be cited in the PR body.

- [ ] **Step 4: Ratchet self-invocation**

```bash
uv run python scripts/check_repo_hygiene.py
echo "exit=$?"
```
Expected: `exit=0`.

- [ ] **Step 5: E2E dry-run**

```bash
uv run geode analyze "Cowboy Bebop" --dry-run
```
Expected: final tier `A (68.4)` — unchanged from baseline in CLAUDE.md §Expected Test Results.

- [ ] **Step 6: Confirm `.owner` is absent + gitignored**

```bash
git ls-files .owner          # expect empty output
grep -E '^/?\.owner$' .gitignore   # expect match
```

- [ ] **Step 7: Snapshot git log for PR body**

```bash
git log --oneline origin/develop..HEAD
```
Expected: 4 feature commits (A/B/C/D) + 1 spec commit on top of `origin/develop`.

Record this output — it informs the PR body `## Changes` section.

---

## Task 11: Push + PR feature → develop + CI watch + merge

**Files:**
- No local file changes.

- [ ] **Step 1: Push the feature branch**

```bash
git push -u origin feature/repo-hygiene-ratchet
```

- [ ] **Step 2: Create the PR to develop using HEREDOC body**

```bash
gh pr create --base develop --head feature/repo-hygiene-ratchet \
  --title "feat(ratchet): repo hygiene + .owner cleanup (v0.48.1)" \
  --body "$(cat <<'EOF'
## Summary
- Adds `scripts/check_repo_hygiene.py` CI ratchet detecting dangling symlinks, absolute-path symlinks, and orphan `.claude/worktrees/` entries.
- Removes a stale tracked root `.owner` file (accidentally committed in 6d07637) and gitignores `/.owner` so the CLAUDE.md §0 worktree-ownership convention no longer pollutes feature branches.
- Bumps version to 0.48.1 (PATCH, Infrastructure).

## Why
While allocating a worktree per CLAUDE.md §0, discovered that `echo ... > .claude/worktrees/<name>/.owner` writes to the worktree's checkout root and overwrites a tracked `.owner` file left over from `6d07637`. Every worktree allocation silently modified a tracked file, and any "owner presence" check trivially passed because the tracked file was always present. The ratchet part is preventive (converts zero-symlink state into an enforced invariant, matching the existing test-count / legacy-import / prompt-integrity ratchets); the cleanup part fixes the latent bug in one PR.

## Changes
| File | Change |
|------|--------|
| `scripts/check_repo_hygiene.py` | New: stdlib-only ratchet logic (dangling / absolute / orphan) |
| `tests/test_check_repo_hygiene.py` | New: 6 unit tests via subprocess + tmp_path |
| `.github/workflows/ci.yml` | Added `Repo hygiene ratchet` step under the `lint` job |
| `.owner` | Deleted (stale, no consumer) |
| `.gitignore` | Added `/.owner` + explanatory comment |
| `CLAUDE.md` | §0: one-line note that `.owner` is gitignored; version line → 0.48.1 |
| `pyproject.toml` | version → 0.48.1 |
| `README.md` | header version → 0.48.1 |
| `CHANGELOG.md` | New `## [0.48.1] — 2026-04-23` section |
| `docs/superpowers/specs/2026-04-23-repo-hygiene-ratchet-design.md` | New: design spec |
| `docs/superpowers/plans/2026-04-23-repo-hygiene-ratchet.md` | New: implementation plan |

## GAP Audit
| Item | Status | Notes |
|------|--------|-------|
| Dangling symlink check | Implemented | Task 2 |
| Absolute-path symlink check | Implemented | Task 3 |
| Orphan worktree check | Implemented | Task 4 (defensive — gitignore normally hides contents from CI) |
| Allowlist for intentional symlinks | Dropped (YAGNI) | Zero symlinks today; follow-up if needed |
| Pre-commit hook | Dropped (out of scope) | CI-only per spec |
| Root `.owner` cleanup | Implemented | Task 8 |
| Gitignore hardening | Implemented | Task 8 |

## Verification
- [x] ruff check clean (`core/ tests/ scripts/`)
- [x] ruff format --check clean
- [x] mypy clean (`core/`)
- [x] pytest pass (count: <FILL>)
- [x] ratchet self-run: exit 0
- [x] E2E unchanged: `geode analyze "Cowboy Bebop" --dry-run` → A (68.4)
- [x] `git ls-files .owner` empty; `/.owner` present in `.gitignore`

## Reference
- Spec: `docs/superpowers/specs/2026-04-23-repo-hygiene-ratchet-design.md`
- Plan: `docs/superpowers/plans/2026-04-23-repo-hygiene-ratchet.md`
- Pattern source: `scripts/check_legacy_imports.py` (existing ratchet)
EOF
)"
```

Fill `<FILL>` in the pytest count from Task 10 Step 3 before submitting.

- [ ] **Step 3: Watch CI**

```bash
gh pr checks --watch
```
Expected: all 5 jobs (lint / typecheck / test / security / gate) pass green.

- [ ] **Step 4: Merge (squash)**

```bash
gh pr merge --squash --delete-branch
```

- [ ] **Step 5: Confirm develop now contains the commits**

```bash
git fetch origin
git log --oneline -3 origin/develop
```

---

## Task 12: PR develop → main + merge

**Files:**
- No local file changes.

- [ ] **Step 1: Create the develop → main PR**

```bash
gh pr create --base main --head develop \
  --title "chore: release v0.48.1 (repo hygiene ratchet)" \
  --body "$(cat <<'EOF'
## Summary
- Release v0.48.1 — repo hygiene ratchet (dangling/absolute symlink + orphan `.claude/worktrees/` detection) and one-time cleanup of stale tracked `.owner`.

## Verification
- [x] CI 5/5 green on feature → develop
- [x] CHANGELOG `[0.48.1]` section present; 4-location version sync complete
EOF
)"
```

- [ ] **Step 2: Watch CI**

```bash
gh pr checks --watch
```
Expected: 5/5 green.

- [ ] **Step 3: Merge (merge commit, not squash, to preserve history)**

```bash
gh pr merge --merge
```

- [ ] **Step 4: Fetch and verify main is up to date**

```bash
git fetch origin
git log --oneline -3 origin/main
```
Expected: develop → main merge commit at tip.

---

## Task 13: Worktree cleanup + rebuild

**Files:**
- No repo changes. Local environment only.

- [ ] **Step 1: Leave the worktree directory**

```bash
cd /Users/pinxbot9/workspace/geode
```

- [ ] **Step 2: Remove the worktree**

```bash
git worktree remove .claude/worktrees/repo-hygiene-ratchet
git worktree list
```
Expected: only the main worktree remains.

- [ ] **Step 3: Sync local main/develop to remote**

```bash
git checkout main
git pull origin main
git fetch origin develop:develop
```

- [ ] **Step 4: Rebuild the CLI**

```bash
uv tool install -e . --force
uv sync
```

- [ ] **Step 5: Verify installed version matches**

```bash
geode version
```
Expected: `0.48.1` (or `geode, version 0.48.1` depending on typer output).

- [ ] **Step 6: Restart `geode serve` (if it was running)**

```bash
ps aux | grep "geode serve" | grep -v grep
```

If a PID is listed:
```bash
kill $(ps aux | grep "geode serve" | grep -v grep | awk '{print $2}')
geode serve &
```

Otherwise skip (the thin CLI auto-starts the daemon on next invocation).

- [ ] **Step 7: Smoke-test**

```bash
uv run python scripts/check_repo_hygiene.py
echo "exit=$?"
```
Expected: `exit=0` from the main checkout.

---

## Self-Review Notes

**Spec coverage:**
- Part 1 checks #1/#2/#3 → Tasks 2/3/4 ✓
- Exclusions (`.git/`, `.venv/`, `node_modules/`, `.claude/worktrees/`) → Task 2 script (EXCLUDED_DIRS) + Task 5 test ✓
- Part 2 cleanup (git rm .owner, .gitignore, CLAUDE.md note) → Task 8 ✓
- Version bump (4 locations) + CHANGELOG → Task 9 ✓
- CI integration → Task 7 ✓
- Verification checklist → Task 10 ✓
- Gitflow commits A/B/C/D → Tasks 6/7/8/9 ✓
- PRs → Tasks 11/12 ✓
- Rebuild → Task 13 ✓

**Type consistency:**
- `find_dangling_symlinks`, `find_absolute_symlinks` both return `list[tuple[Path, str]]` — consistent across Tasks 2/3
- `find_orphan_worktrees` returns `list[Path]` — consistent with Task 4 usage
- `format_report` signature grows across tasks; final signature in Task 4 is the one wired in `main()` ✓
- `EXCLUDED_DIRS` is `frozenset[tuple[str, ...]]` — matches the prefix-matching logic in `is_excluded_for_symlink_scan`

**Placeholder scan:** one `<FILL>` is intentional (pytest count in Task 11 PR body, recorded live in Task 10).
