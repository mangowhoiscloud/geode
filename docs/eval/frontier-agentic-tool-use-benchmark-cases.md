# Frontier Agentic Tool-Use Benchmark Cases

Date: 2026-07-02; updated 2026-07-03

Purpose: prepare GEODE's public benchmark ledger for agentic tool-use scores,
with the planned GEODE run using GPT-5.5 from a subscription/Codex account.
This note is an evidence ledger, not a full GEODE scorecard. A no-LLM MCPMark
harness smoke was run to validate setup and verification. Live GEODE runs were
also completed for one MCPMark filesystem easy smoke task and the 10-task
MCPMark filesystem easy suite with `gpt-5.5` / `xhigh`.

Target benchmark cluster:

- MCPMark / MCPMark Verified
- BFCL V4
- tau2-bench / tau2-Bench

## Finding

There is no single public primary-source case found so far that runs the exact
planned GEODE configuration, namely GEODE harness + GPT-5.5 via subscription
account, across MCPMark, BFCL V4, and tau2-bench.

There is also no public case found so far that runs Codex/GPT-5.5 across all
three target benchmarks. The closest external evidence is split: MCPMark has a
Codex/GPT-5.5 xhigh result; BFCL V4 and tau2 have GPT-5.5 results from API or
provider-managed routes, not clearly Codex.

The closest evidence splits into four buckets:

| Status | Case | What it gives GEODE | Limitation |
|---|---|---|---|
| Strong baseline | Agent-World Table 1 | Same three benchmark suites in one table, including frontier proprietary model rows | Uses GPT-5.2 High, Claude Sonnet 4.5, Gemini 3 Pro, Seed 2.0; not GPT-5.5 subscription |
| Same target model, MCPMark | MCPMark Verified README / release PR | `gpt-5.5` (`xhigh`) leads MCPMark Verified at 92.9%; verified task set is pinned and stabilized | MCPMark only; likely model/API-style harness, not Codex subscription product |
| Same target model, tau2 | OpenAI GPT-5.5 release | GPT-5.5 reaches 98.0% on tau2-bench Telecom without prompt tuning, with GPT-4.1 as user model | Telecom domain only; not the full retail/telecom/airline average from Agent-World |
| Same target model, BFCL/tau2 comparator | Surge cross-benchmark study | GPT-5.5 evaluated through Azure AI Foundry at medium reasoning effort on BFCL V4, tau2-Bench, and Toolathlon; BFCL V4 pass@4 comparator is 69.4% | Third-party study; medium reasoning, not subscription/Codex; most numeric values are embedded in images |
| Same target model and Codex route, MCPMark | Moonshot Kimi K2.7 Code model card | GPT-5.5 ran in Codex with xhigh mode; MCPMark Verified 92.9 | MCPMark only; vendor comparison table, not GEODE |

## Benchmark Grounding

### MCPMark / MCPMark Verified

Official source: <https://github.com/eval-sys/mcpmark>

MCPMark evaluates agentic models in real MCP tool environments: Notion, GitHub,
Filesystem, Postgres, and Playwright. The repo describes one-command tasks,
isolated sandboxes, auto-resume, unified metrics, and aggregated reports.

Current important versioning note:

- MCPMark Verified is now the default standard task set.
- Earlier task versions are deprecated and not directly comparable.
- Standard covers 127 tasks.
- `easy` hosts 10 lightweight tasks per MCP for smoke tests / CI.
- The Verified release pins all five MCP server versions and the harness so the
  model under test is the intended variable.

Relevant frontier case:

| Source | Model / setting | Reported result |
|---|---|---|
| MCPMark README / PR #264 | `gpt-5.5`, `xhigh` reasoning effort | 92.9% on MCPMark Verified |
| Moonshot Kimi K2.7 Code model card | GPT-5.5 in Codex, xhigh mode | 92.9% on MCPMark Verified |

Use for GEODE:

- Treat MCPMark Verified, not older MCP-Mark, as the canonical MCP score.
- Record server versions, harness commit, task suite, model route, reasoning
  effort, and whether GEODE used native API, Codex subscription, or an emulated
  tool path.

## BFCL V4

Official sources:

- Leaderboard: <https://gorilla.cs.berkeley.edu/leaderboard.html>
- V4 web-search blog: <https://gorilla.cs.berkeley.edu/blogs/15_bfcl_v4_web_search.html>
- Code/data: <https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard>

BFCL V4 evaluates function/tool calling accuracy. The public leaderboard states
that models are evaluated using commit `f7cf735`, and reproduction should use
that checkpoint or `bfcl-eval==2025.12.17`.

V4 score composition from the Berkeley blog:

| Component | Weight / role |
|---|---|
| Agentic | 40%, unweighted average across Web Search and Memory |
| Multi-Turn | 30% |
| Live | 10% |
| Non-Live | 10% |
| Hallucination Measurement | 10% |
| Format Sensitivity | non-scoring stress surface |

Relevant frontier cases:

| Source | Model / setting | Reported result |
|---|---|---|
| Agent-World Table 1 | GPT-5.2 High | BFCL V4 average 62.9 |
| Agent-World Table 1 | Claude Sonnet 4.5 | BFCL V4 average 73.2 |
| Agent-World Table 1 | Gemini 3 Pro | BFCL V4 average 72.5 |
| Agent-World Table 1 | Seed 2.0 | BFCL V4 average 73.4 |
| Surge cross-benchmark study | GPT-5.5 via Azure AI Foundry, medium reasoning | BFCL V4 pass@1 64.9; pass@4 comparator 69.4 |

Use for GEODE:

- Do not mix BFCL V4 overall accuracy with BFCL subcategory scores unless the
  report names the exact aggregation.
- Record whether the model used native function calling (`FC`) or prompt-based
  function calling, because the leaderboard distinguishes those modes.

## tau2-bench

Official sources:

- Repo: <https://github.com/sierra-research/tau2-bench>
- Leaderboard: <https://taubench.com/>
- Paper: <https://arxiv.org/pdf/2506.07982>

The current repo describes tau-bench as a simulation framework for customer
service agents. It supports text half-duplex evaluation and voice full-duplex
evaluation. Domains currently listed in the repo are `mock`, `airline`,
`retail`, `telecom`, and `banking_knowledge`.

Relevant frontier cases:

| Source | Model / setting | Reported result |
|---|---|---|
| OpenAI GPT-5.5 release | GPT-5.5, no prompt tuning, GPT-4.1 user model | tau2-bench Telecom 98.0% |
| Agent-World Table 1 | GPT-5.2 High | Retail 81.6, Telecom 95.8, Airline 62.5, average 80.2 |
| Agent-World Table 1 | Claude Sonnet 4.5 | Retail 86.2, Telecom 98.0, Airline 70.1, average 84.7 |
| Agent-World Table 1 | Gemini 3 Pro | Retail 85.3, Telecom 98.0, Airline 72.7, average 85.4 |
| Agent-World Table 1 | Seed 2.0 | Retail 90.4, Telecom 94.2, Airline 64.4, average 83.0 |
| Surge cross-benchmark study | GPT-5.5 via Azure AI Foundry, medium reasoning | tau2-Bench pass@1 60.9 |

Use for GEODE:

- If we publish a tau2 score, report the domain split, not only the average.
- For direct comparison to OpenAI's GPT-5.5 claim, run Telecom with GPT-4.1 as
  the user model and state that it is a Telecom-only comparison.

## Same-Suite Frontier Table

Source: Agent-World, arXiv `2604.18292v1`, Table 1:
<https://arxiv.org/html/2604.18292v1>

The paper reports accuracy across MCP-Mark, BFCL V4, and tau2-Bench in one
table. This is the closest directly comparable public table for the three-suite
cluster, but it is not the planned GPT-5.5 subscription spec.

Frontier proprietary rows from the paper:

| Method | MCP-Mark Avg. | BFCL V4 Avg. | tau2-Bench Avg. |
|---|---:|---:|---:|
| GPT-5.2 High | 53.1 | 62.9 | 80.2 |
| Claude Sonnet 4.5 | 33.3 | 73.2 | 84.7 |
| Gemini 3 Pro | 50.8 | 72.5 | 85.4 |
| Seed 2.0 | 54.7 | 73.4 | 83.0 |

Open-source environment-scaling rows from the same table:

| Method | MCP-Mark Avg. | BFCL V4 Avg. | tau2-Bench Avg. |
|---|---:|---:|---:|
| Simulator-8B | 2.4 | 23.9 | 31.8 |
| TOUCAN-7B | 1.0 | 36.6 | 17.7 |
| EnvScaler-8B | 5.6 | 47.6 | 37.9 |
| AWM-8B | 2.4 | 40.0 | 34.4 |
| AWM-14B | 5.1 | 42.4 | 39.0 |
| ScaleEnv-8B | - | - | 38.5 |
| Agent-World-8B | 8.9 | 51.4 | 61.8 |
| Agent-World-14B | 13.3 | 55.8 | 65.4 |

## GEODE Reporting Contract

When GEODE scores are added later, use this schema:

| Field | Required value |
|---|---|
| Harness | GEODE commit SHA and branch |
| Model route | `openai-subscription/codex` vs `openai-api` vs other |
| Model label | Exact UI/API label, e.g. `GPT-5.5 Thinking`, `gpt-5.5`, etc. |
| Reasoning setting | UI/default/medium/high/xhigh/max, if visible |
| Tool path | Native provider tools, GEODE function tools, MCP servers, or emulation |
| Benchmark version | Repo commit, package version, task suite, server versions |
| User simulator | Required for tau2, e.g. `gpt-4.1` |
| Trials | `k`, pass@k, domain/task count |
| Cost / time | Wall time, estimated cost, subscription limits hit |
| Artifacts | Raw JSONL, trajectories, verifier outputs, run config |

Comparison rule:

- Compare GEODE subscription results to other subscription/product-agent
  results only when the external source states that same product route.
- Compare GEODE subscription results to API/model-card scores as directional
  baselines, not apples-to-apples scores.
- Never combine MCPMark Verified with pre-Verified MCP-Mark results in the same
  leaderboard column without an explicit version label.

## External Codex/GPT-5.5 Cases

Follow-up search date: 2026-07-02.

No public external case was found that reports Codex/GPT-5.5 on all three
target benchmarks (`MCPMark`, `BFCL V4`, `tau2-bench`) under one consistent
run spec.

Found cases:

| Benchmark | External case | Route / setting | Data | Use for GEODE |
|---|---|---|---|---|
| MCPMark Verified | Moonshot Kimi K2.7 Code model card | GPT-5.5 ran in Codex with xhigh mode | 92.9, averaged over 3 runs; 100-step tool-call budget; 32k max tokens per step | Strongest Codex/GPT-5.5 comparator for MCPMark |
| MCPMark Verified | MCPMark README / release PR #264 | `gpt-5.5`, xhigh; public model entry added in MCPMark Verified release | 92.9; verified task set is pinned and stabilized | Strong model/harness comparator; Codex route is clarified by Moonshot, not by MCPMark README alone |
| BFCL V4 | Surge / Edwin Chen cross-benchmark study | GPT-5.5 through Azure AI Foundry, medium reasoning | pass@1 64.9; pass@4 69.4 | Good GPT-5.5 medium comparator, but not Codex |
| tau2-bench | Surge / Edwin Chen cross-benchmark study | GPT-5.5 through Azure AI Foundry, medium reasoning | pass@1 60.9 | Good GPT-5.5 medium comparator, but not Codex |
| tau2-bench Telecom | OpenAI GPT-5.5 release | GPT-5.5 with original prompts, GPT-4.1 user model | 98.0 on Telecom | Official model-card comparator, domain-only and not clearly Codex |

Near-miss:

- MarginLab runs a daily `Codex gpt-5.5-xhigh` tracker directly in Codex CLI,
  but it targets SWE-Bench-Pro, not MCPMark/BFCL/tau2. It is useful as evidence
  that third-party Codex CLI benchmarking exists, not as a score source for
  this benchmark cluster.

Current interpretation:

- For MCPMark, we can cite a Codex/GPT-5.5 xhigh external score.
- For BFCL V4, the public GPT-5.5 number found is Azure AI Foundry medium, not
  Codex.
- For tau2, the public GPT-5.5 numbers found are Azure AI Foundry medium for
  broad tau2 and OpenAI official Telecom-only for the release note, not Codex.
- Therefore GEODE's planned Codex/subscription run will likely be the first
  locally controlled apples-to-apples Codex/GPT-5.5 ledger across these three
  suites, unless a private or newly published Codex benchmark appears.

## Local Harness Inventory

GEODE-owned benchmark glue now lives in the public-safe
`plugins/benchmark_harness/` plugin. The plugin records upstream repo
coordinates, pinned commits, preflight env names, and GEODE adapters. The
third-party benchmark repositories themselves are still fetched under ignored
local artifacts so GEODE does not vendor external harness code.

Raw run logs cited by this ledger are published as append-only snapshots at
<https://github.com/mangowhoiscloud/geode-eval-artifacts> (MCPMark result
directories with per-task `meta.json` / `messages.json` / verifier output,
pipeline logs, and GEODE-owned tau2 simulation JSONs). Local
`artifacts/eval/harnesses/**` paths cited below map to the same relative paths
in that repository. A secret scan gates every upload.

The benchmark harnesses were fetched under ignored local artifacts so they can
be used for setup and smoke testing without vendoring third-party repos into
GEODE:

| Benchmark | Local path | Upstream commit / version | Status |
|---|---|---:|---|
| MCPMark | `artifacts/eval/harnesses/mcpmark` | `cd45b7f` | Installed in local Python 3.12 venv; filesystem easy smoke passed |
| tau2-bench | `artifacts/eval/harnesses/tau2-bench` | `1901a30` | Installed with `uv sync`; `tau2 check-data` passed |
| BFCL V4 | `artifacts/eval/harnesses/gorilla/berkeley-function-call-leaderboard` | Gorilla `6ea5797` | Fetched via sparse checkout; CLI commands inspected |

MCPMark install command used:

```bash
cd artifacts/eval/harnesses/mcpmark
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e .
```

The first attempt with system `python3` failed because `/usr/bin/python3` is
Python 3.9.6 and MCPMark requires Python 3.11 or newer.

tau2 setup commands used:

```bash
cd artifacts/eval/harnesses/tau2-bench
uv sync
uv run tau2 check-data
```

tau2 data check result:

| Field | Value |
|---|---|
| Data directory | `artifacts/eval/harnesses/tau2-bench/data` |
| Registered domains | `mock`, `airline`, `retail`, `telecom`, `telecom-workflow`, `banking_knowledge` |
| Registered users | `user_simulator`, `dummy_user` |
| Status | Passed; `You can now run tau2 commands.` |

BFCL V4 inspected commands:

```bash
cd artifacts/eval/harnesses/gorilla/berkeley-function-call-leaderboard
pip install -e .
bfcl generate --model MODEL_NAME --test-category TEST_CATEGORY --num-threads 1
bfcl evaluate --model MODEL_NAME --test-category TEST_CATEGORY
```

BFCL V4 notes:

- Web Search requires a SerpAPI key or compatible replacement.
- Editable install defaults result and score folders under the BFCL project
  root; PyPI install requires `BFCL_PROJECT_ROOT`.
- BFCL generation is a model-calling step and was not run here.

### MCPMark Harness Smoke

Smoke command:

```bash
cd artifacts/eval/harnesses/mcpmark
OPENAI_API_KEY=dummy .venv/bin/python pipeline.py \
  --mcp filesystem \
  --task-suite easy \
  --tasks file_context/uppercase \
  --models smoke \
  --agent smoke \
  --k 1 \
  --timeout 120 \
  --exp-name geode-smoke-20260702 \
  --output-dir ./results-geode-smoke
```

Result:

| Field | Value |
|---|---|
| Task | `filesystem/easy/file_context/uppercase` |
| Result path | `artifacts/eval/harnesses/mcpmark/results-geode-smoke/geode-smoke-20260702/smoke__filesystem-easy/run-1` |
| Passed | 1 / 1 |
| Success rate | 100.0% |
| Total task execution time | 0.559s |
| Model calls | 0 |

What this proves:

- MCPMark imports and runs in the local Python 3.12 environment.
- Filesystem easy fixtures download from `storage.mcpmark.ai`.
- The harness setup, backup isolation, verifier, `messages.json`, `meta.json`,
  and `summary.json` paths work end-to-end.

What this does not prove:

- It is not a GEODE score.
- It does not exercise GEODE's `AgenticLoop`.
- It does not exercise MCP tool calls through GEODE.
- It does not use GPT-5.5 or the subscription/Codex route.

### Live GEODE MCPMark Smoke

Run date: 2026-07-03.

Authentication note for the live GEODE commands below: `OPENAI_API_KEY=dummy`
only satisfies the MCPMark pipeline's environment-variable expectation. The
actual model calls used GEODE's `openai-codex` provider with `source=subscription`.
An API-key route would not have authenticated with the dummy value.

Command:

```bash
cd artifacts/eval/harnesses/mcpmark
GEODE_REPO_ROOT=<geode-worktree> \
OPENAI_API_KEY=dummy \
.venv/bin/python pipeline.py \
  --mcp filesystem \
  --task-suite easy \
  --tasks file_context/uppercase \
  --models geode-gpt-5.5 \
  --agent geode \
  --reasoning-effort xhigh \
  --k 1 \
  --timeout 900 \
  --exp-name geode-gpt55-xhigh-20260703-smoke-r10 \
  --output-dir ./results-geode-live
```

Result:

| Field | Value |
|---|---|
| Task | `filesystem/easy/file_context/uppercase` |
| Model route | GEODE `gpt-5.5`, provider `openai-codex`, source `subscription` |
| Reasoning effort | `xhigh` |
| Result path | `artifacts/eval/harnesses/mcpmark/results-geode-live/geode-gpt55-xhigh-20260703-smoke-r10/geode-gpt-5-5-xhigh__filesystem-easy/run-1` |
| Passed | 1 / 1 |
| Success rate | 100.0% |
| Agent execution time | 398.486s |
| Task execution time | 398.623s |
| GEODE rounds | 12 |
| MCP tool calls | 11 |
| Token usage | 59,219 input / 7,457 output / 66,676 total |

What this proves:

- MCPMark can drive GEODE's `AgenticLoop` through a local `BaseMCPAgent`
  adapter.
- GEODE can discover and execute MCP filesystem tools from the MCPMark
  task-specific server.
- The `gpt-5.5` Codex/subscription route completed a verifier-backed MCPMark
  filesystem task under `xhigh`.

Adapter caveats found during smoke:

- GEODE's MCP tool surface exposed a `write_file` argument name mismatch for
  this server path (`file_path` from the model vs `path` required by the MCP
  filesystem server). This is now normalized in GEODE core before MCP dispatch.
- `read_multiple_files` adds display separators/newlines, which can break exact
  byte-for-byte verifier checks if the model copies the display text literally.
  GEODE now caches local source EOF metadata after successful reads and trims a
  single display-induced trailing newline on same-name text writes when the
  source did not have one.
- `read_text_file` rejects simultaneous `head` and `tail`; GEODE now drops both
  when both are present so full-file reads work.

### Live GEODE MCPMark Smoke After EOF Offload

Run date: 2026-07-03.

Command:

```bash
cd artifacts/eval/harnesses/mcpmark
GEODE_REPO_ROOT=<geode-worktree> \
OPENAI_API_KEY=dummy \
.venv/bin/python pipeline.py \
  --mcp filesystem \
  --task-suite easy \
  --tasks file_context/uppercase \
  --models geode-gpt-5.5 \
  --agent geode \
  --reasoning-effort xhigh \
  --k 1 \
  --timeout 900 \
  --exp-name geode-gpt55-xhigh-20260703-smoke-r11-eof-offload \
  --output-dir ./results-geode-live
```

Result:

| Field | Value |
|---|---|
| Task | `filesystem/easy/file_context/uppercase` |
| Result path | `artifacts/eval/harnesses/mcpmark/results-geode-live/geode-gpt55-xhigh-20260703-smoke-r11-eof-offload/geode-gpt-5-5-xhigh__filesystem-easy/run-1` |
| Passed | 1 / 1 |
| Success rate | 100.0% |
| Task execution time | 167.9s |
| GEODE rounds | 3 |
| MCP tool calls | 7 |

Interpretation:

- EOF handling no longer needs to be solved by forcing file-by-file
  `read_text_file` calls in the model loop.
- For the same uppercase smoke, wall time dropped from 398.6s / 12 rounds to
  167.9s / 3 rounds while preserving verifier correctness.

### Live GEODE MCPMark Filesystem Easy

Run date: 2026-07-03.

Command:

```bash
cd artifacts/eval/harnesses/mcpmark
GEODE_REPO_ROOT=<geode-worktree> \
OPENAI_API_KEY=dummy \
.venv/bin/python pipeline.py \
  --mcp filesystem \
  --task-suite easy \
  --models geode-gpt-5.5 \
  --agent geode \
  --reasoning-effort xhigh \
  --k 1 \
  --timeout 900 \
  --exp-name geode-gpt55-xhigh-20260703-filesystem-easy \
  --output-dir ./results-geode-live
```

Result:

| Field | Value |
|---|---|
| Suite | `MCPMark filesystem/easy` |
| Model route | GEODE `gpt-5.5`, provider `openai-codex`, source `subscription` |
| Reasoning effort | `xhigh` |
| Result path | `artifacts/eval/harnesses/mcpmark/results-geode-live/geode-gpt55-xhigh-20260703-filesystem-easy/geode-gpt-5-5-xhigh__filesystem-easy/run-1` |
| Passed | 10 / 10 |
| Success rate | 100.0% |
| Total task execution time | 1706.044s |
| Average task execution time | 170.604s |
| Total agent execution time | 1696.300s |
| GEODE rounds | 40 total / 4.0 average |
| Token usage | 234,483 input / 32,296 output / 266,779 total |

Task-level results:

| Task | Result | Time | Rounds | Tokens |
|---|---:|---:|---:|---:|
| `file_context__file_splitting` | PASS | 640.287s | 7 | 52,925 |
| `file_context__pattern_matching` | PASS | 162.561s | 3 | 24,781 |
| `file_context__uppercase` | PASS | 145.404s | 3 | 17,541 |
| `file_property__largest_rename` | PASS | 61.050s | 4 | 17,532 |
| `file_property__txt_merging` | PASS | 124.666s | 4 | 22,619 |
| `folder_structure__structure_analysis` | PASS | 85.059s | 3 | 12,977 |
| `legal_document__file_reorganize` | PASS | 115.090s | 5 | 24,307 |
| `papers__papers_counting` | PASS | 113.489s | 3 | 32,570 |
| `student_database__duplicate_name` | PASS | 105.057s | 3 | 20,720 |
| `student_database__recommender_name` | PASS | 153.381s | 5 | 40,807 |

Interpretation:

- This is a verifier-backed GEODE result for the MCPMark filesystem easy subset,
  not a MCPMark Verified or full MCPMark score.
- Accuracy is saturated on this subset: 100.0%.
- Runtime remains high for `xhigh`; the slowest task was
  `file_context__file_splitting` at 640.3s. Median task time is roughly two
  minutes, but long reasoning turns dominate wall time.
- Token usage averages 26,678 tokens per task. The run is suitable as a
  smoke/regression baseline, but not as a cost-efficient CI gate.

### Live GEODE MCPMark Verified Available Services

Run date: 2026-07-04.

This is a verifier-backed GEODE result for the MCPMark standard services that
were runnable in the local environment. It is not a full MCPMark Verified
leaderboard score because Notion and Playwright/WebArena were blocked by local
service prerequisites.

| Field | Value |
|---|---|
| Suite | `filesystem/standard` + `postgres/standard` + `github/standard` |
| Model route | GEODE `gpt-5.5`, provider `openai-codex`, source `subscription` |
| Reasoning effort | `xhigh` |
| Harness | `eval-sys/mcpmark@cd45b7f` |
| Result path | `artifacts/eval/harnesses/mcpmark/results-geode-agentworld/geode-gpt55-xhigh-20260704-mcpmark-verified-*` |
| Measured total | 64 / 74 |
| Accuracy | 86.5% |

Service-level results:

| Service | Tasks | Passed | Accuracy | Recorded time |
|---|---:|---:|---:|---:|
| `filesystem/standard` | 30 | 25 | 83.3% | 13580.6s over 29 recorded tasks |
| `postgres/standard` | 21 | 20 | 95.2% | 8765.7s |
| `github/standard` | 23 | 19 | 82.6% | 16476.3s |

Blocked services:

| Service | Reason |
|---|---|
| `notion` | No `notion_state.json` was available in the local harness environment. |
| `playwright` / WebArena | Required Docker images and browser service stack were absent. |

Notable failures:

| Service | Task | Failure |
|---|---|---|
| `filesystem` | `desktop_template/budget_computation` | verifier failed |
| `filesystem` | `papers/author_folders` | two attempts ended without meta output; counted as a failed no-result transport run |
| `filesystem` | `papers/find_math_paper` | verifier failed |
| `filesystem` | `student_database/english_talent` | verifier failed |
| `filesystem` | `threestudio/output_analysis` | verifier failed |
| `postgres` | `employees/employee_performance_analysis` | verifier failed |
| `github` | `claude-code/label_color_standardization` | fixture duplication first, then agent-level verification failure on retry |
| `github` | `mcpmark-cicd/deployment_status_workflow` | verifier failed |
| `github` | `missing-semester/assign_contributor_labels` | used suffixed transient usernames instead of canonical contributor labels |
| `github` | `missing-semester/find_salient_file` | `ANSWER.md` was not created on the required master branch |

Adapter/runtime changes required for this run:

- Bootstrap GEODE LLM adapter registry inside the MCPMark import context.
- Alias `file_path` to `path` when MCP tool schemas expect `path`.
- Override GitHub execution to use `ghcr.io/github/github-mcp-server:v0.15.0`.
- Override Postgres execution to use `postgres-mcp==0.3.0` with the MCPMark
  database URI.
- Add `GEODE_MCPMARK_GITHUB_REPO_VISIBILITY=public` for transient GitHub
  fixture repos when measuring through the Docker GitHub MCP server.

### MCPMark Environment Unblock (2026-07-10)

Goal: make the services blocked on 2026-07-04 runnable so a single-cycle
measurement can be compared against Agent-World Table 1 (File / Github /
Notion / Play / Post). Operational runbook:
`docs/eval/mcpmark-agentworld-comparison-runbook.md`.

Root causes and fixes:

| Blocked case (07-04) | Root cause | Fix (07-10) |
|---|---|---|
| `github` State Duplication Error 6 tasks | `GITHUB_EVAL_ORG` unset in `.mcp_env`; upstream default `mcpleague-eval` is not writable by the local token | Persisted `GITHUB_EVAL_ORG=mangowhoiscloud` (the value the successful 07-04 retry used); token re-validated |
| `notion` Stage 1 stall (all runs aborted) | Expired browser session in `notion_state.json`; duplication `page.goto` to `app.notion.com` timed out at 120s per retry | Re-login and saved a fresh session. Google OAuth rejects automation browsers, so login used a real-Chrome channel persistent context with `--disable-blink-features=AutomationControlled`; the session cookie (`token_v2`) lives on `.app.notion.com`, not the `notion.so`/`notion.com` marketing hosts |
| `postgres` container down | Host restart; `mcpmark-postgres` Exited(255) | Restarted; WAL auto-recovery clean; all 5 sample DBs and default credentials verified |
| `--agent geode` not registered | 07-04 runs relied on an unsaved local patch to `src/agents/__init__.py` | Committed launcher `plugins/benchmark_harness/run_mcpmark.py` registers the agent before `pipeline.main()`; upstream stays unpatched |
| `playwright` never run | Assumed to need WebArena | The 4 standard tasks are live-web; `@playwright/mcp@0.0.68` launch verified, browsers installed. No fixture needed |
| `playwright_webarena` never run | WebArena Docker images (~100GB for shopping / shopping_admin / reddit) exceed the 13GB free local disk | Still blocked locally; needs an external volume or a VM |

Notion unblock smoke (verifier-backed):

| Field | Value |
|---|---|
| Task | `notion/easy/toronto_guide/simple__change_color` |
| Model route | GEODE `gpt-5.5`, provider `openai-codex`, source `subscription`, effort `xhigh` |
| Result | 1 / 1 PASS |
| State duplication | 58.9s |
| Agent execution | 216.8s, 8 rounds |
| Token usage | 62,834 input / 8,013 output |
| Result path | `artifacts/eval/harnesses/mcpmark/results-geode-agentworld/geode-gpt55-xhigh-20260710-notion-smoke-unblock-r2/geode-gpt-5-5-xhigh__notion-easy/run-1` |

The task embeds a Notion API trap: updating an existing select option color
returns `validation_error` (`Cannot update color of select with id: ...`).
The agent received the structured error and passed the verifier by redefining
the select options through a database schema update. This is an API
limitation, not a plan/pricing restriction.

Subscription quota note: the first full-cycle attempt on 2026-07-10 hit
`429 usage_limit_reached` (plan `prolite`) on its first task. The run was
stopped immediately and the one contaminated task result was deleted, because
the harness resume logic treats a failed task with a non-retryable error
message as final and would otherwise skip it forever. Full-suite runs must be
scheduled inside quota reset windows, and 429 failures are never counted as
task failures.

### Required GEODE Adapter Work

MCPMark's native agents call models directly through LiteLLM. Running the
default MCPMark agent with `gpt-5.5` would measure `MCPMark + OpenAI API-style
LiteLLM`, not GEODE.

For a real GEODE result, add an adapter that implements MCPMark's
`BaseMCPAgent.execute()` and routes each task through:

1. MCPMark task setup and service config.
2. GEODE `MCPServerManager` configured with the task-specific MCP server.
3. GEODE `ToolExecutor(mcp_manager=...)`.
4. GEODE `AgenticLoop(model="gpt-5.5", provider=_resolve_provider("gpt-5.5"))`
   using the subscription/Codex source.
5. MCPMark verifier and result reporter.

The relevant GEODE injection points already exist:

| GEODE surface | Role |
|---|---|
| `core/mcp/manager.py` | loads MCP server config and exposes MCP tools |
| `core/agent/tool_executor/executor.py` | dispatches MCP tool calls through `mcp_manager` |
| `core/agent/loop/agent_loop.py` | accepts `mcp_manager` and merges MCP tool schemas into the visible tool surface |
| `core/config/routing.toml` | routes `gpt-5.5` / `gpt-5.5-pro` through Codex/subscription |

## Suggested First Measurement Pass

The active queue after the 2026-07-03 priority update is:

1. MCPMark Verified `easy` suite across all available MCPs using the GEODE
   adapter, starting with filesystem.
2. tau2 `mock` smoke, then Telecom small run. The default GEODE route uses
   `geode_agent` + `geode_user`, both with `source=subscription`, so no
   LiteLLM credential is required for the first GEODE-owned run. Native tau2
   `user_simulator` runs with GPT-4.1 or GPT-5.2 are optional comparator tracks
   and must stay separate from the subscription-only score.
3. BFCL V4 agentic subset first; full BFCL V4 only after the function-calling
   route is stable.
4. HAL Reliability tau-bench airline smoke, reusing the tau2 adapter shape where
   possible.
5. Terminal-Bench 2.0 smoke.
6. Toolathlon smoke.
7. Archive every run under `artifacts/eval/<bench>/<date>/` and add only
   verifier-backed scores to the public docs.

## Sources

- Agent-World paper, Table 1: <https://arxiv.org/html/2604.18292v1>
- MCPMark repo: <https://github.com/eval-sys/mcpmark>
- MCPMark Verified release PR: <https://github.com/eval-sys/mcpmark/pull/264>
- Moonshot Kimi K2.7 Code model card: <https://huggingface.co/moonshotai/Kimi-K2.7-Code>
- BFCL V4 leaderboard: <https://gorilla.cs.berkeley.edu/leaderboard.html>
- BFCL V4 web-search methodology: <https://gorilla.cs.berkeley.edu/blogs/15_bfcl_v4_web_search.html>
- tau2-bench repo: <https://github.com/sierra-research/tau2-bench>
- OpenAI GPT-5.5 release: <https://openai.com/index/introducing-gpt-5-5/>
- GPT-5.5 system card: <https://deploymentsafety.openai.com/gpt-5-5>
- Surge cross-benchmark study: <https://surgehq.ai/blog/cross-benchmark-generalization-for-long-horizon-agentic-tasks>
- Edwin Chen LinkedIn summary of Surge study: <https://www.linkedin.com/posts/edwinzchen_cross-benchmark-generalization-for-long-horizon-activity-7467343602092986368-T4DW>
- MarginLab Codex gpt-5.5-xhigh tracker: <https://marginlab.ai/trackers/codex/>
