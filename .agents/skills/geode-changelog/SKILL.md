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

**Post-1.0 default: every authorized routine release is a PATCH — features included.**
Ordinary changes stay under `[Unreleased]`; a code landing does not itself
request a release or version bump.
The 0.99.x patch-train (~330 releases where features, fixes, and refactors
all bumped PATCH) continues unchanged as 1.0.x. Textbook SemVer's
"feature = MINOR" does NOT apply here.

```
MAJOR.MINOR.PATCH

PATCH: default for every release — features, fixes, refactors, docs+code
MINOR: operator-declared milestone ONLY (never chosen unilaterally)
MAJOR: operator-declared ONLY (breaking pipeline/State schema)
```

### Before choosing ANY non-patch version

1. `rg -n "removed in v" core/ evals/ evolve/` — minors may be pledged in advance to
   deprecation removals (v1.1.0 is pledged to the legacy
   `[self_improving_loop.petri.*]` / `[self_improving_loop.mutator]`
   removals in `evals/config.py`). A pledged number is
   RESERVED; landing unrelated work under it breaks the pledge.
2. Ask the operator. A minor is a product statement, not a diff size.

### Incident: the v1.1.0 mis-stamp (2026-07-17, corrected as v1.0.1)

The Slack Socket Mode landing was stamped v1.1.0 by mechanically applying
"New feature = MINOR" from this skill's old text + CLAUDE.md §5. Three
gaps compounded:

1. **Rule/practice divergence** — the written rule said feature=MINOR
   while actual practice was patch-train; the written rule won because it
   was the only thing in context.
2. **Pledge invisibility** — v1.1.0's reservation existed only inside
   runtime deprecation strings, which no release step consults. The grep
   step above is the guard.
3. **Compaction lock-in** — once "restamp 1.1.0" entered a session
   summary, later steps treated the number as settled instead of a
   decision still needing operator sign-off.

### Mis-stamp correction procedure

A wrong version may be RECLAIMED (renamed in place) only while it exists
purely as file stamps. Verify against the REMOTE, not a possibly-stale
checkout: `git ls-remote --tags origin "vX.Y.Z*"` (empty), `gh release
view vX.Y.Z` (errors with not-found), and the exact-version PyPI JSON
`https://pypi.org/pypi/geode-agent/X.Y.Z/json` (404). Once any tag/release/artifact exists, the number is
burned — correct forward with the next free number instead. To reclaim:
rename the CHANGELOG heading in place with a retraction blurb, restamp the
5 locations + site SoT (`sync-stats.mjs` + `check_llms_version.py --fix`)
+ `uv.lock`, and land through the
normal PR chain.

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
2. Regenerate architecture inventory when its inputs change; do not hand-count modules/tests
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

#### On Release

Only an authorized release promotes entries and stamps a version. Follow
[versioning conventions](../../../docs/architecture/naming-conventions.md#9-versioning-and-compatibility)
for source stamps, generated mirrors, and immutable artifacts, and
[GitFlow](../geode-gitflow/SKILL.md#release-flow) for branch/CI/integration steps.

1. Promote `[Unreleased]` to the chosen version and date; leave a fresh empty
   `[Unreleased]` heading above it.
2. Regenerate inventory with `scripts/architecture_baseline.py --update` when
   its inputs change. File inventory and collected pytest cases are different
   measurements; neither is a manually maintained CLAUDE.md counter.
3. Regenerate version and public-doc mirrors through their owning commands;
   verify the diff contains only intended source and generated changes.

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

Choose an affected current package or user-facing capability; examples:
- Runtime and CLI (`core`)
- Evaluation (`evals`)
- Experimental Loop (`evolve`)
- Tools, memory, and provider integrations

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
