# GPT-5.4 GEODE × Codex MCPMark filesystem/easy paired diagnostic

## Identity

| Field | Value |
|---|---|
| Run ID | `paired-full-20260812` |
| Date | 2026-08-12 |
| GEODE version | 1.0.21 plus feature-worktree adapter changes |
| Execution base | `549875803fbb94ac8fd4339a12bbfcc880112265` |
| Branch | `codex/tau2-gpt54-official-alignment` |
| Worktree state | Dirty by design; the adapter implementation under test was not yet committed |

The eventual feature commit must be recorded before external artifact
publication. The raw run remains diagnostic until that commit and the artifact
repository commit are both pinned.

## Frozen comparison surface

| Field | Value |
|---|---|
| Benchmark | MCPMark upstream `filesystem/easy`; not the MCPMark Verified standard suite |
| Harness revision | `eval-sys/mcpmark@cd45b7f57923b9b3985467f5139927575f83141c` |
| Tasks / trials | 10 / `k=1` |
| Agent model | GPT-5.4 subscription, `high` effort |
| Timeout | 1,200 seconds per task |
| Codex | `codex-cli 0.145.0`, ephemeral, strict isolated config |
| MCP server | `@modelcontextprotocol/server-filesystem@2025.12.18` |
| State and verifier | Same upstream setup, fixture restore, and task verifier |
| Order | Alternating GEODE-first and Codex-first by task |

The Codex sandbox was read-only. Its task-local MCP server was the only mutation
surface; shell, direct file edits, web, apps, skills, collaboration, goals, and
other optional tool features were disabled. The GEODE arm exposed the same MCP
tool schemas through its `AgenticLoop` and auto-approved only those tools.

## Result

| Metric | GEODE | Codex CLI |
|---|---:|---:|
| Passed | 9 | 9 |
| Failed | 1 | 1 |
| Accuracy | 90.0% | 90.0% |
| Total agent time | 747.2s | 745.5s |
| Mean task time | 74.7s | 74.5s |
| Median task time | 57.0s | 45.8s |
| MCP calls | 50 | 116 |
| Input tokens | 447,376 | 1,518,869 |
| Cached input tokens | 195,584 | 1,366,400 |
| Output tokens | 25,157 | 25,477 |
| Reasoning tokens exposed separately | n/a | 10,144 |

| Task | GEODE | Time / calls | Codex | Time / calls |
|---|---|---:|---|---:|
| `file_context/file_splitting` | PASS | 267.5s / 9 | PASS | 132.2s / 9 |
| `file_context/pattern_matching` | PASS | 79.1s / 5 | PASS | 61.6s / 4 |
| `file_context/uppercase` | FAIL | 66.8s / 9 | FAIL | 70.2s / 11 |
| `file_property/largest_rename` | PASS | 24.5s / 3 | PASS | 35.7s / 5 |
| `file_property/txt_merging` | PASS | 72.6s / 4 | PASS | 46.6s / 5 |
| `folder_structure/structure_analysis` | PASS | 39.1s / 4 | PASS | 245.8s / 55 |
| `legal_document/file_reorganize` | PASS | 59.8s / 5 | PASS | 44.9s / 12 |
| `papers/papers_counting` | PASS | 45.9s / 3 | PASS | 44.7s / 4 |
| `student_database/duplicate_name` | PASS | 37.7s / 3 | PASS | 25.3s / 3 |
| `student_database/recommender_name` | PASS | 54.2s / 5 | PASS | 38.6s / 8 |

The sole failure is exactly paired. Both agents uppercased the requested files
but appended an LF that was absent from each source file. The pinned easy
verifier compares exact strings, so the output is correctly scored as failure.
No retry was used to erase it.

Codex's `structure_analysis` trajectory is the largest efficiency outlier: 53
of its 55 MCP calls were `list_directory`, producing 763,210 input tokens and a
245.8-second task. GEODE used the available tree operation and four MCP calls.
GEODE's slowest task was instead `file_splitting` at 267.5 seconds. The nearly
identical total time is therefore not evidence of identical scheduling quality.

## Trajectory and protocol audit

| Quality | GEODE | Codex CLI |
|---|---:|---:|
| Sidecars | 10 | 10 |
| Scope-complete | 10 | 10 |
| Replay-complete | 0 | 0 |
| Canonical events | 180 | 306 |
| Tool call/result pairs | 50/50 | 116/116 |
| Orphan calls/results | 0/0 | 0/0 |
| Forbidden mutation events | 0 | 0 |

Native logs remain authoritative for tool bodies and verifier evidence. Public
sidecars store digests, explicitly mark content omission, and retain unique
`<task>/execution.log` digest references. A schema validator recomputed all 20
integrity envelopes after the run.

Local raw paths:

```text
artifacts/eval/harnesses/mcpmark/results-paired/paired-full-20260812/
  geode-gpt-5-4-high__filesystem-easy/run-1/
  codex-gpt-5-4-high__filesystem-easy/run-1/
```

These paths are ignored evidence, not public URLs. Raw JSONL, tool bodies,
temporary fixture paths, and stderr must not be copied wholesale to the public
artifact repository.

## Interpretation and next gate

- Direct claim allowed: on the same ten easy tasks, model, effort, state,
  verifier, and trial, GEODE and Codex had identical pass/fail outcomes.
- Claim not allowed: GEODE equals Codex generally, or either score is a current
  MCPMark Verified leaderboard result.
- The sample has no discordant pass/fail pair and only one trial. Repetition is
  not justified for a score delta that is currently zero.
- The next useful cross-harness lane is Terminal-Bench 2.1 only after GEODE has
  a faithful terminal adapter. Until then its public same-model Codex/Terminus
  result is directional context, not a GEODE score.

## Verification executed

```text
15 MCPMark adapter unit tests passed
ruff check and format check passed for touched adapter/trajectory tests
mypy passed for touched benchmark modules
10,411 non-live tests passed in the full repository gate
20/20 trajectory schemas and integrity envelopes recomputed successfully
10/10 sidecars per arm; zero orphan tool pairs; zero Codex protocol violations
post-fix Codex subscription-environment gate passed 1/1 with ChatGPT login
```

External artifact promotion remains pending. It requires a committed GEODE
implementation, reviewed replay-incomplete trajectory releases for each arm,
an append-only `geode-eval-artifacts` PR, and exact remote digest read-back.
