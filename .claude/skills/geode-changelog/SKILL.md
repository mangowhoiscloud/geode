---
name: geode-changelog
description: GEODE CHANGELOG.md management rules. Version releases, change logging, scope determination, format standards. Triggers on "changelog", "release", "version", "릴리스", "변경사항", "버전".
---

# GEODE Changelog Convention

## File Location

`/CHANGELOG.md` (project root)

## Format

[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) + [SemVer 2.0.0](https://semver.org/)

```markdown
## [X.Y.Z] — YYYY-MM-DD

### Added       ← New features
### Changed     ← Changes to existing features (including breaking)
### Fixed       ← Bug fixes
### Removed     ← Removed features
### Architecture ← Structural decisions (GEODE extension)
### Infrastructure ← CI, build, dependencies (GEODE extension)
```

## Versioning Policy

```
MAJOR.MINOR.PATCH

MAJOR: Breaking changes (pipeline structure, State schema changes)
MINOR: New feature additions (new nodes, new evaluators, new tools)
PATCH: Bug fixes, performance improvements
```

Current: `0.x.y` — pre-release phase. MINOR = feature milestones.

## Scope Rules — What to Record / What Not to Record

### What to Record (Feature-level aggregation)
| Type | Example |
|------|---------|
| New module/class | `AgenticLoop`, `BashTool`, `SubAgentManager` |
| New pipeline node | `evaluator: prospect_judge` |
| New tool/command | `/batch`, `run_bash` tool |
| Behavior change | NLRouter → AgenticLoop transition |
| Formula/threshold change | Scoring weights, Tier criteria |
| Bug fix | Confidence calculation edge case |
| Dependency add/remove | LangGraph 2.0 upgrade |
| CI change | New verification job added |

### What Not to Record
| Type | Reason |
|------|--------|
| Internal refactor (behavior unchanged) | No user/developer impact |
| Code quality passes (R1→R8) | Summarize in one line |
| Merge commits | Noise |
| README/blog edits | Outside changelog scope |
| Per-commit records | Aggregate at feature level |

## Writing Procedure

### On Code Change Commits (mandatory every time)

**Include CHANGELOG entries in the same commit as the code change.** Do not defer to a separate commit after the PR.

```
1. Determine change type → Add 1-line entry to appropriate [Unreleased] category
2. Sync CLAUDE.md metrics when changed (Tests, Modules)
3. Sync README.md metrics + description + Mermaid visualization when changed
4. Bundle code + CHANGELOG + docs in a single commit
```

**Exception**: CHANGELOG entry not required for docs/refactor-only changes.

### Consistency Verification Checklist (mandatory before PR)

After writing the CHANGELOG, check the following:

```
□ Do [Unreleased] entries accurately reflect actual code changes?
□ Do Infrastructure section Test/Module counts match measured values?
□ Are all feature/fix items from merged PR bodies included in [Unreleased]?
□ Do README.md Features table and Mermaid diagrams match code behavior?
□ If .claude/mcp_servers.json changed, was the README MCP section also updated?
```

### On Release
1. Convert `[Unreleased]` → `[X.Y.Z] — YYYY-MM-DD`
2. Regenerate empty `[Unreleased]` section
3. Update Version History table
4. Update footer links
5. Sync `pyproject.toml` + `core/__init__.py` version

### Release Checklist
```bash
# 1. Version bump
# pyproject.toml: version = "X.Y.Z"
# core/__init__.py: __version__ = "X.Y.Z"

# 2. Update CHANGELOG.md
# [Unreleased] → [X.Y.Z] — YYYY-MM-DD

# 3. Verify
uv run ruff check core/ tests/
uv run mypy core/
uv run pytest tests/ -q

# 4. Tag
git tag -a vX.Y.Z -m "Release vX.Y.Z"
```

## Subsection Guide (within Added)

For large releases, organize Added into functional areas:

```markdown
### Added

#### Core Pipeline
- ...

#### CLI
- ...

#### Memory System
- ...
```

Area list (GEODE standard):
- Core Pipeline (LangGraph)
- Analysis Engine (Analysts + Evaluators)
- Verification Layer
- CLI (REPL + Commands)
- Agentic Loop
- Memory System
- Infrastructure (Ports/Adapters)
- Orchestration (Hooks/Tasks/Runner)
- Tools & Policies
- Automation (L4.5)

## Example

```markdown
## [Unreleased]

### Added
- `AgenticLoop` — while(tool_use) multi-round execution loop
- `BashTool` — HITL shell command execution with 9 blocked patterns

### Fixed
- Scoring confidence edge case with empty analyst array
```

## Git History → Changelog Conversion

When extracting changelog entries from commit logs:

```bash
# Extract only feat/fix commits since last release
git log v0.6.0..HEAD --oneline --grep="^feat\|^fix"
```

1. `feat` → Added
2. `fix` → Fixed
3. `refactor` (with behavior change) → Changed
4. Commits in the same functional area → Aggregate into one
5. Merge/docs/ci/chore → Skip (record ci under Infrastructure when applicable)
