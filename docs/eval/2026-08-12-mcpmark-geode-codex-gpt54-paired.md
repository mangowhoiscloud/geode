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
| Implementation commit | `85967a498451f493055cb94738410378d6eddbe9` |
| Artifact commit | `9095f7f8b07bd93b41748ef89a32fc2540288d3e` |

The execution used the stated dirty feature worktree; commit `85967a498` pins
the tested adapter content after the run. The reviewed public projection was
merged separately at the artifact commit above. This provenance keeps the run
diagnostic rather than pretending it executed from a clean release tag.

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

## Post-run token diagnosis

The token totals above remain the native counters from the executed run. A
follow-up code audit found two GEODE-side amplification mechanisms; this report
does not retroactively rewrite the measurements or assign a precise causal
share without a matched rerun.

1. MCPMark returned the complete MCP `CallToolResult` as a JSON string inside a
   second `result` envelope. The common tool boundary then serialized that
   string again. Because MCP may repeat the same structured value in both
   `content` and `structuredContent` for compatibility, the model received
   duplicate data plus JSON escaping. The repaired boundary keeps the raw MCP
   envelope in the session timeline/tool log, but chooses
   `structuredContent` (falling back to `content`) for the model. A
   representative duplicate payload fell from 76,604 to 38,258 serialized
   characters, a 50.06% reduction.
2. AgenticLoop appended a synthetic per-round reminder after the growing
   history. It was absent from the stored conversation but still changed the
   next request shape and weakened exact-prefix reuse. Current date and runtime
   rules already have a system-prompt path, so the duplicate reminder layer was
   deleted. A regression test now compares consecutive real
   `AdapterCallRequest.messages` and requires the earlier request to remain an
   exact prefix.

The audit also found that GEODE discarded provider-reported reasoning and
cache-write counts when translating adapter usage. The runtime now maps those
values into the existing `thinking_tokens` and `cache_creation_tokens` fields,
and the per-call lifecycle hook carries the same breakdown. Both OpenAI and
Anthropic define reasoning as a subset of inclusive `output_tokens`, so the
local estimator records it for analysis without billing it a second time. This
improves the next artifact's accounting but cannot recover the omitted
breakdown from this completed run. Verify was not identified as the serializer
or cache-prefix defect, so no verifier stage was removed or weakened.

Primary contracts: [OpenAI Responses usage](https://platform.openai.com/docs/api-reference/responses/object#responses/object-usage)
and [Anthropic extended-thinking usage](https://platform.claude.com/docs/en/build-with-claude/extended-thinking#pricing).

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

Reviewed public releases:

- [GEODE trajectory release](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/9095f7f8b07bd93b41748ef89a32fc2540288d3e/trajectories/mcpmark-geode-gpt54-high-geode-codex-paired-filesystem-easy-20260812T060733Z-3ea7869be85a)
  — manifest SHA-256 `3ea7869be85a2a058c204f7768c40e25b63cb5fcf2f10ae090aa01b701d33d53`
- [Codex trajectory release](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/9095f7f8b07bd93b41748ef89a32fc2540288d3e/trajectories/mcpmark-codex-gpt54-high-geode-codex-paired-filesystem-easy-20260812T060733Z-871a6c2ae92c)
  — manifest SHA-256 `871a6c2ae92cc77c7d195cc1aa669b4afa017bfaadb76bedd1f727c5b96b2ff7`

Both manifests were fetched again from artifact-repository `main` after merge
and verified byte-for-byte against these independently retained anchors.

## Interpretation and next gate

- Direct claim allowed: on the same ten easy tasks, model, effort, state,
  verifier, and trial, GEODE and Codex had identical pass/fail outcomes.
- Claim not allowed: GEODE equals Codex generally, or either score is a current
  MCPMark Verified leaderboard result.
- The historical token row is a pre-repair diagnostic, not the expected cost
  of the repaired runtime. A same-task GPT-5.4 rerun is required before making
  an efficiency claim.
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

External artifact promotion completed through
[`geode-eval-artifacts#20`](https://github.com/mangowhoiscloud/geode-eval-artifacts/pull/20).
Only the two reviewed replay-incomplete trajectory releases and their run
report were published; native logs remain local.
