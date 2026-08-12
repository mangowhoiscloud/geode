# MCPMark filesystem/easy: GEODE × Codex paired comparison

Date: 2026-08-12. Status: diagnostic complete.

## Decision

Use the current MCPMark repository's `filesystem/easy` suite as the first direct GEODE–Codex
comparison. Both arms use the same pinned upstream checkout, task fixture,
MCP server, task order, timeout, GPT-5.4 subscription route, `high` effort,
and official verifier. Only the agent harness changes.

This is not the 127-task MCPMark Verified standard suite and is not eligible
for its public leaderboard. “Official verifier” below means the verifier shipped
with each pinned easy task, not a Verified leaderboard submission.

Terminal-Bench 2.1 remains the stronger public scaffold leaderboard, but it is
not this experiment: GEODE has no Terminal-Bench adapter and a full verified
Codex run is materially more expensive. Tau2 remains the stateful-dialogue
lane; no public Codex Tau2 configuration is available to reproduce directly.

## Comparison contract

| Axis | GEODE arm | Codex arm |
|---|---|---|
| Harness | MCPMark `cd45b7f` | same |
| Suite | `filesystem/easy`, 10 tasks | same |
| Model | GPT-5.4 subscription | same |
| Effort | `high` | `high` |
| State + verifier | upstream MCPMark | same |
| MCP server | pinned upstream filesystem server | same |
| Agent loop | GEODE `AgenticLoop` | `codex exec` 0.145.0 |
| Native mutation path | MCP tools | MCP tools only; read-only Codex sandbox |
| Repetition | `k=1` diagnostic | same |

The result is a direct **harness comparison**, not a model leaderboard result.
The Codex arm intentionally ignores the operator's Codex config and exec-policy
rules, uses an empty temporary working directory, disables session persistence,
and injects only the per-task MCP server. The isolated server's tools are
pre-approved because non-interactive Codex otherwise cancels mutating MCP calls;
the sandbox remains read-only and non-MCP tool features are disabled. Automatic
skill/app/collaboration instructions are also disabled. This removes global
connectors, project rules, writable shell access, and unrelated tool schemas
from the model-facing comparison surface.

`turn_count` is not a cross-harness metric: MCPMark receives GEODE loop rounds,
whereas `codex exec` exposes one outer turn for the whole task. Compare verifier
pass, MCP calls, aggregate tokens, wall time, and failure class instead.

## Gates

1. Unit gate: command construction, JSONL parsing, model label, registration.
2. Config gate: `codex exec --strict-config` accepts the isolated MCP config.
3. One-task gate: run the same fixed easy task once in both arms.
4. Stop conditions: quota/auth failure, state setup failure, non-MCP mutation,
   malformed JSONL, missing official verifier receipt, or unequal task identity.
5. Full diagnostic: only after gate 3 passes, run all 10 easy tasks once per arm.

The 10-task run is diagnostic, not publication-grade. Task execution order was
counterbalanced by alternating which arm ran first. Repeated trials are deferred
because the first trial produced no pass/fail discordance.

## Result

Both arms scored **9/10 (90%)** and failed the same task. There is therefore no
observed pass-rate advantage for either harness in this sample.

| Metric | GEODE | Codex CLI |
|---|---:|---:|
| Passed | 9/10 | 9/10 |
| Agent wall time | 747.2s | 745.5s |
| Median task time | 57.0s | 45.8s |
| MCP calls | 50 | 116 |
| Input tokens, native counter | 447,376 | 1,518,869 |
| Cached input tokens | 195,584 | 1,366,400 |
| Output tokens | 25,157 | 25,477 |
| Canonical events | 180 | 306 |
| Exact tool pairs | 50/50 | 116/116 |
| Protocol violations | 0 | 0 |

The input counters are native adapter measurements and do not have proven
cross-product billing equivalence. GEODE rounds and Codex outer turns are also
not comparable. Wall time is comparable at the task boundary.

The shared failure was `file_context/uppercase`. Both agents wrote all five
uppercase files with one extra trailing LF; the source files ended in `.` and
the pinned easy verifier requires exact content equality. This is shared action
behavior, not evidence of a GEODE-only regression.

The aggregate wall-time tie hides different tails. GEODE spent 267.5s on
`file_splitting`; Codex spent 245.8s and 55 MCP calls on `structure_analysis`,
including 53 `list_directory` calls, where GEODE used four calls and completed
in 39.1s. A larger repeated study should report tail behavior and call economy,
not only pass rate.

All 20 normalized trajectories are schema-valid and scope-complete. They are
deliberately replay-incomplete because private prompt, reasoning, and tool bodies
are represented by digests. The artifact audit caught and corrected two
publication-contract defects before promotion: digested Codex bodies now count
as reduced replay fidelity, and per-task native receipt references are unique.

## Reproduction

Run from the pinned MCPMark checkout with GEODE on `PYTHONPATH`. MCPMark's model
loader requires an `OPENAI_API_KEY` value even though both adapters use ChatGPT
subscription auth; `dummy` satisfies only that upstream preflight and is never
sent to a model provider.

```bash
cd artifacts/eval/harnesses/mcpmark
export PYTHONPATH=/absolute/path/to/geode

OPENAI_API_KEY=dummy .venv/bin/python \
  -m plugins.benchmark_harness.run_mcpmark \
  --mcp filesystem --task-suite easy --tasks file_context/uppercase \
  --models geode-gpt-5.4 --agent geode --reasoning-effort high \
  --k 1 --timeout 1200 --exp-name paired-smoke-geode \
  --output-dir ./results-paired

OPENAI_API_KEY=dummy .venv/bin/python \
  -m plugins.benchmark_harness.run_mcpmark \
  --mcp filesystem --task-suite easy --tasks file_context/uppercase \
  --models codex-gpt-5.4 --agent codex --reasoning-effort high \
  --k 1 --timeout 1200 --exp-name paired-smoke-codex \
  --output-dir ./results-paired
```

For the 10-task diagnostic, change `--tasks` to `all` while retaining every
other field. The detailed run record is
[`docs/eval/2026-08-12-mcpmark-geode-codex-gpt54-paired.md`](../eval/2026-08-12-mcpmark-geode-codex-gpt54-paired.md).

## External context, not merged into the score

- Terminal-Bench 2.1 reports GPT-5.4 at 77.3% with Codex CLI and 54.8% with
  Terminus 2 under the same task suite, showing that scaffold choice can move
  results materially: <https://www.tbench.ai/news/terminal-bench-2-1>
- MCPMark Verified defines the current isolated, verifier-backed task contract:
  <https://github.com/eval-sys/mcpmark>
- Codex non-interactive JSONL and subscription authentication are documented in
  the Codex CLI manual: <https://developers.openai.com/codex/noninteractive>
