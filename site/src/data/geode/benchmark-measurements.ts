export type BenchmarkGroupId = "mcpmark" | "tau2";

export type BenchmarkMeasurement = {
  id: string;
  group: BenchmarkGroupId;
  title: string;
  measuredAt: string;
  suite: string;
  status: "complete" | "blocked" | "planned";
  model: string;
  provider: string;
  source: string;
  effort: string;
  route: string;
  harness: string;
  artifact: string;
  scoreLabel: string;
  scoreValue: string;
  secondary: string[];
  command: string;
  notes: string[];
};

export type BenchmarkMatrixCell = {
  label: string;
  value: string;
  measurementId?: string;
  note?: string;
};

export type BenchmarkGroup = {
  id: BenchmarkGroupId;
  title: string;
  titleKo: string;
  summary: string;
  summaryKo: string;
  matrix: BenchmarkMatrixCell[];
  measurements: BenchmarkMeasurement[];
};

const mcpmarkFilesystemEasy: BenchmarkMeasurement = {
  id: "mcpmark-filesystem-easy-20260703-gpt55-xhigh",
  group: "mcpmark",
  title: "filesystem/easy full slice",
  measuredAt: "2026-07-03 KST",
  suite: "filesystem/easy",
  status: "complete",
  model: "gpt-5.5",
  provider: "openai-codex",
  source: "subscription",
  effort: "xhigh",
  route: "GEODE local MCPMark adapter",
  harness: "eval-sys/mcpmark@cd45b7f",
  artifact:
    "artifacts/eval/harnesses/mcpmark/results-geode-live/geode-gpt55-xhigh-20260703-filesystem-easy/geode-gpt-5-5-xhigh__filesystem-easy/run-1",
  scoreLabel: "Accuracy",
  scoreValue: "100.0% (10 / 10)",
  secondary: [
    "Total task execution time 1706.044s",
    "Average task execution time 170.604s",
    "40 GEODE rounds total / 4.0 average",
    "266,779 total tokens",
  ],
  command: `cd artifacts/eval/harnesses/mcpmark
GEODE_REPO_ROOT=<geode-worktree> \\
OPENAI_API_KEY=dummy \\
.venv/bin/python pipeline.py \\
  --mcp filesystem \\
  --task-suite easy \\
  --models geode-gpt-5.5 \\
  --agent geode \\
  --reasoning-effort xhigh \\
  --k 1 \\
  --timeout 900 \\
  --exp-name geode-gpt55-xhigh-20260703-filesystem-easy \\
  --output-dir ./results-geode-live`,
  notes: [
    "MCPMark filesystem/easy is directly comparable only to the same subset.",
    "This is not the MCPMark Verified aggregate used by frontier leaderboards.",
    "OPENAI_API_KEY=dummy satisfied the harness environment check; model calls used the GEODE subscription route.",
  ],
};

const mcpmarkFilesystemEasyGpt56: BenchmarkMeasurement = {
  id: "mcpmark-filesystem-easy-20260731-gpt56-high",
  group: "mcpmark",
  title: "filesystem/easy GPT-5.6 subscription rerun",
  measuredAt: "2026-07-31 KST",
  suite: "filesystem/easy",
  status: "complete",
  model: "gpt-5.6-sol",
  provider: "openai-codex",
  source: "subscription",
  effort: "high",
  route: "GEODE local MCPMark adapter",
  harness: "eval-sys/mcpmark@cd45b7f, GEODE@edb74602b",
  artifact:
    "geode-eval-artifacts@9c00ecf/mcpmark/results-geode-agentworld/geode-gpt56-sol-high-edb74602b-20260731-mcpmark-filesystem-easy",
  scoreLabel: "Accuracy",
  scoreValue: "90.0% (9 / 10)",
  secondary: [
    "Total task execution time 799.435s / average 79.943s",
    "54 GEODE turns total / 5.4 average",
    "799,679 input / 10,976 output / 97,792 cache-read tokens",
    "Recorded estimate $3.887611; not subscription billing",
    "Failure: file_context/uppercase left file_01.txt incompletely uppercased",
  ],
  command: `cd artifacts/eval/harnesses/mcpmark
GEODE_HOME=<isolated-runtime-home> \\
PYTHONPATH=<geode-edb74602b-worktree> \\
OPENAI_API_KEY=dummy \\
.venv/bin/python -m plugins.benchmark_harness.run_mcpmark \\
  --mcp filesystem \\
  --task-suite easy \\
  --models geode-gpt-5.6-sol \\
  --agent geode \\
  --reasoning-effort high \\
  --k 1 \\
  --timeout 1200 \\
  --exp-name geode-gpt56-sol-high-edb74602b-20260731-mcpmark-filesystem-easy \\
  --output-dir ./results-geode-edb74602b`,
  notes: [
    "This is directly comparable to filesystem/easy only, not to the MCPMark Verified standard aggregate.",
    "The upstream total_tokens and total_reasoning_tokens summary fields were zero despite populated input/output fields; they are not used.",
    "One response stream disconnected after the first task had already produced its files; that task passed every official integrity check and no 429 occurred.",
    "Raw receipts and ten normalized tool trajectories are pinned to geode-eval-artifacts commit 9c00ecf.",
  ],
};

const mcpmarkFilesystemEasyGpt56V1011: BenchmarkMeasurement = {
  id: "mcpmark-filesystem-easy-20260731-gpt56-high-v1011",
  group: "mcpmark",
  title: "filesystem/easy GPT-5.6 v1.0.11 release regression",
  measuredAt: "2026-07-31 KST",
  suite: "filesystem/easy",
  status: "complete",
  model: "gpt-5.6-sol",
  provider: "openai",
  source: "subscription",
  effort: "high",
  route: "GEODE AgenticLoop MCPMark adapter",
  harness: "eval-sys/mcpmark@cd45b7f, GEODE v1.0.11@686ff372",
  artifact:
    "geode-eval-artifacts@16a54f08450db771c02e30c73bdc3867f6282f83/mcpmark/results-geode-agentworld/geode-gpt56-sol-high-v1011-686ff372-20260731-mcpmark-filesystem-easy",
  scoreLabel: "Accuracy",
  scoreValue: "100.0% (10 / 10)",
  secondary: [
    "Total task execution time 596.580s / average 59.658s",
    "56 GEODE turns total / 5.6 average",
    "700,719 input / 12,164 output / 206,848 cache-read tokens",
    "Recorded estimate $2.937699; not subscription billing",
    "226 canonical events / 78 exactly paired tool calls and results / 0 missing required turn IDs",
  ],
  command: `cd artifacts/eval/harnesses/mcpmark
GEODE_HOME=<isolated-v1011-runtime-home> \\
PYTHONPATH=<geode-v1.0.11-release-tree> \\
.venv/bin/python -m plugins.benchmark_harness.run_mcpmark \\
  --mcp filesystem \\
  --task-suite easy \\
  --models gpt-5.6-sol \\
  --agent geode \\
  --reasoning-effort high \\
  --k 1 \\
  --timeout 1200 \\
  --exp-name geode-gpt56-sol-high-v1011-686ff372-20260731-mcpmark-filesystem-easy \\
  --output-dir ./results-geode-v1011`,
  notes: [
    "The earlier file_context/uppercase failure now passes; all ten official filesystem/easy verifiers are green.",
    "This remains directly comparable only to filesystem/easy, not to the MCPMark Verified standard aggregate.",
    "The stable geode.trajectory@1 release is scope-complete but intentionally replay-incomplete because dialogue and tool bodies are digested.",
    "Native receipts and stable trajectories are pinned to geode-eval-artifacts commit 16a54f0.",
  ],
};

const mcpmarkFilesystemEasyGpt54V1012: BenchmarkMeasurement = {
  id: "mcpmark-filesystem-easy-20260803-gpt54-high-v1012",
  group: "mcpmark",
  title: "filesystem/easy GPT-5.4 v1.0.12 post-release regression",
  measuredAt: "2026-08-03 KST",
  suite: "filesystem/easy",
  status: "complete",
  model: "gpt-5.4",
  provider: "openai",
  source: "subscription",
  effort: "high",
  route: "GEODE AgenticLoop MCPMark adapter",
  harness: "eval-sys/mcpmark@cd45b7f, GEODE v1.0.12@f99cea63",
  artifact:
    "geode-eval-artifacts@04ff1c4a1fee0cd1a3d837ad3a5f5239f1fd9acd/mcpmark/results-geode-agentworld/geode-gpt54-high-v1.0.12-f99cea63-20260803-mcpmark-filesystem-easy",
  scoreLabel: "Accuracy",
  scoreValue: "90.0% (9 / 10)",
  secondary: [
    "Total task execution time 802.182s / average 80.218s",
    "53 GEODE turns total / 5.3 average",
    "302,984 input / 30,238 output tokens",
    "182 canonical events / 56 exactly paired tool calls and results",
    "Failure: file_context/uppercase left file_01.txt incompletely uppercased",
  ],
  command: `cd artifacts/eval/harnesses/mcpmark
PYTHONPATH=<geode-v1.0.12-release-tree> \
.venv/bin/python -m plugins.benchmark_harness.run_mcpmark \
  --mcp filesystem \
  --task-suite easy \
  --models geode-gpt-5.4 \
  --agent geode \
  --reasoning-effort high \
  --k 1 \
  --timeout 1200 \
  --exp-name geode-gpt54-high-v1.0.12-f99cea63-20260803-mcpmark-filesystem-easy \
  --output-dir ./results-geode-v1012`,
  notes: [
    "The official verifier found all five output files, but file_01.txt was not fully uppercased; the failure is retained without retry.",
    "No authentication, quota, provider-adapter, MCP transport, or harness exception occurred.",
    "The v1.0.11 GPT-5.6 10/10 comparison is model-confounded and cannot be attributed to the runtime release alone.",
    "All ten trajectories are scope-complete and intentionally replay-incomplete; manifest and native receipts are pinned to artifact commit 04ff1c4.",
  ],
};

const mcpmarkFilesystemEasyGpt54TokenEfficiency: BenchmarkMeasurement = {
  id: "mcpmark-filesystem-easy-20260812-gpt54-high-token-efficiency",
  group: "mcpmark",
  title: "filesystem/easy GPT-5.4 token-efficiency rerun",
  measuredAt: "2026-08-12 KST",
  suite: "filesystem/easy",
  status: "complete",
  model: "gpt-5.4",
  provider: "openai",
  source: "subscription",
  effort: "high",
  route: "GEODE AgenticLoop MCPMark adapter",
  harness: "eval-sys/mcpmark@cd45b7f, GEODE feature@149024e6e",
  artifact:
    "geode-eval-artifacts@2c2d1f0621f64ff7ceeff8c05d8ebd3449501aaf/trajectories/mcpmark-geode-gpt54-high-token-efficiency-rerun-filesystem-easy-20260812T090254Z-35db8b275a36",
  scoreLabel: "Accuracy",
  scoreValue: "90.0% (9 / 10)",
  secondary: [
    "Matched input tokens 447,376 → 314,219 (-29.8%)",
    "Matched output tokens 25,157 → 20,385 (-19.0%)",
    "Native reasoning tokens 14,174, included within output tokens",
    "188 canonical events / 54 exactly paired tool calls and results",
    "Failure unchanged: file_context/uppercase exact-string mismatch",
  ],
  command: `cd artifacts/eval/harnesses/mcpmark
PYTHONPATH=<geode-feature-tree> \
.venv/bin/python -m plugins.benchmark_harness.run_mcpmark \
  --mcp filesystem \
  --task-suite easy \
  --models geode-gpt-5.4 \
  --agent geode \
  --reasoning-effort high \
  --k 1 \
  --timeout 1200 \
  --exp-name geode-gpt54-high-token-efficiency-20260812-rerun \
  --output-dir ./results-token-efficiency`,
  notes: [
    "The score matched the pre-repair GEODE baseline at 9/10 while input and output tokens fell materially.",
    "Eight of ten tasks used fewer input tokens; the four tasks with identical round counts fell 12.5%.",
    "This is one matched diagnostic trial, not MCPMark Verified, a confidence interval, or a subscription billing claim.",
    "All ten public trajectories are scope-complete and intentionally replay-incomplete; the immutable release was read back from artifact main.",
  ],
};

const mcpmarkFilesystemEasyParallel: BenchmarkMeasurement = {
  id: "mcpmark-filesystem-easy-parallel-20260703-gpt55-xhigh",
  group: "mcpmark",
  title: "filesystem/easy category-parallel rerun",
  measuredAt: "2026-07-03 05:11 KST",
  suite: "filesystem/easy",
  status: "complete",
  model: "gpt-5.5",
  provider: "openai-codex",
  source: "subscription",
  effort: "xhigh",
  route: "GEODE local MCPMark adapter, category-parallel execution",
  harness: "eval-sys/mcpmark@cd45b7f",
  artifact:
    "artifacts/eval/harnesses/mcpmark/results-geode-live/geode-gpt55-xhigh-20260703-ledger-*",
  scoreLabel: "Accuracy",
  scoreValue: "100.0% (10 / 10)",
  secondary: [
    "Total task execution time 1360.129s",
    "Average task execution time 136.013s",
    "40 GEODE rounds total / 4.0 average",
    "429,324 total tokens",
    "Category rows: file_context 3/3, file_property 2/2, folder_structure 1/1, legal_document 1/1, papers 1/1, student_database 2/2",
  ],
  command: `cd artifacts/eval/harnesses/mcpmark
for category in file_context file_property folder_structure legal_document papers student_database; do
  GEODE_REPO_ROOT=<geode-worktree> \\
  OPENAI_API_KEY=dummy \\
  FILESYSTEM_TEST_ROOT=./test_environments \\
  .venv/bin/python pipeline.py \\
    --mcp filesystem \\
    --task-suite easy \\
    --tasks "$category" \\
    --models geode-gpt-5.5 \\
    --agent geode \\
    --reasoning-effort xhigh \\
    --k 1 \\
    --timeout 900 \\
    --exp-name "geode-gpt55-xhigh-20260703-ledger-$category" \\
    --output-dir ./results-geode-live &
done
wait`,
  notes: [
    "This rerun split filesystem/easy by category and executed the six categories in parallel.",
    "Only filesystem was runnable in the current local environment without additional credentials or Docker services.",
    "GitHub, Notion, Playwright, and Postgres MCPMark columns remain blocked until their service prerequisites are provisioned.",
  ],
};

const mcpmarkVerifiedAvailable: BenchmarkMeasurement = {
  id: "mcpmark-verified-available-20260704-gpt55-xhigh",
  group: "mcpmark",
  title: "Verified available-services aggregate",
  measuredAt: "2026-07-04 KST",
  suite: "filesystem + postgres + github / standard",
  status: "complete",
  model: "gpt-5.5",
  provider: "openai-codex",
  source: "subscription",
  effort: "xhigh",
  route: "GEODE local MCPMark adapter",
  harness: "eval-sys/mcpmark@cd45b7f, GEODE feature/mcpmark-agentworld-run",
  artifact:
    "artifacts/eval/harnesses/mcpmark/results-geode-agentworld/geode-gpt55-xhigh-20260704-mcpmark-verified-*",
  scoreLabel: "Accuracy",
  scoreValue: "86.5% (64 / 74)",
  secondary: [
    "Filesystem standard: 25 / 30, 83.3%",
    "Postgres standard: 20 / 21, 95.2%",
    "GitHub standard: 19 / 23, 82.6%",
    "Recorded task execution time: filesystem 13580.6s over 29 recorded tasks, postgres 8765.7s, github 16476.3s",
    "Notion was not included: no notion_state.json in the local harness environment.",
    "Playwright/WebArena was not included: required Docker images/service stack were absent.",
  ],
  command: `cd artifacts/eval/harnesses/mcpmark
# Run each available MCP service through the GEODE adapter.
GEODE_REPO_ROOT=<geode-worktree> \\
PYTHONPATH=<geode-worktree>:<geode-site-packages> \\
GITHUB_EVAL_ORG=mangowhoiscloud \\
GEODE_MCPMARK_GITHUB_REPO_VISIBILITY=public \\
.venv/bin/python pipeline.py \\
  --mcp <filesystem|postgres|github> \\
  --task-suite standard \\
  --models geode-gpt-5.5 \\
  --agent geode \\
  --reasoning-effort xhigh \\
  --k 1 \\
  --timeout 1500 \\
  --exp-name geode-gpt55-xhigh-20260704-mcpmark-verified-<service> \\
  --output-dir ./results-geode-agentworld`,
  notes: [
    "This is not the full MCPMark Verified leaderboard aggregate. It covers only services that were runnable in the local environment: filesystem, postgres, and github.",
    "The OpenAI model route was the GEODE Codex subscription route, not MCPMark's native LiteLLM OpenAI API route.",
    "GitHub fixture repositories were made public during execution so the Docker GitHub MCP server could use normal public-repo semantics; all transient repos were deleted by cleanup.",
    "The filesystem score counts papers/author_folders as a failed no-result transport run after two attempts without meta output.",
  ],
};

const mcpmarkVerifiedFilesystem: BenchmarkMeasurement = {
  id: "mcpmark-verified-filesystem-20260704-gpt55-xhigh",
  group: "mcpmark",
  title: "Verified filesystem standard slice",
  measuredAt: "2026-07-04 KST",
  suite: "filesystem/standard",
  status: "complete",
  model: "gpt-5.5",
  provider: "openai-codex",
  source: "subscription",
  effort: "xhigh",
  route: "GEODE local MCPMark adapter",
  harness: "eval-sys/mcpmark@cd45b7f",
  artifact:
    "artifacts/eval/harnesses/mcpmark/results-geode-agentworld/geode-gpt55-xhigh-20260704-mcpmark-verified-filesystem-*",
  scoreLabel: "Accuracy",
  scoreValue: "83.3% (25 / 30)",
  secondary: [
    "Recorded task execution time 13580.6s over 29 recorded tasks",
    "Average recorded task execution time 468.3s",
    "Failures: desktop_template/budget_computation, papers/author_folders, papers/find_math_paper, student_database/english_talent, threestudio/output_analysis",
  ],
  command: mcpmarkVerifiedAvailable.command.replace(
    "<filesystem|postgres|github>",
    "filesystem",
  ),
  notes: [
    "filesystem/standard is a materially harder slice than filesystem/easy.",
    "papers/author_folders is counted as a failed no-result transport run because both attempts hung before meta output.",
    "The adapter now aliases file_path to path when the MCP schema expects path, which fixed write_file failures seen in the first filesystem pass.",
  ],
};

const mcpmarkVerifiedPostgres: BenchmarkMeasurement = {
  id: "mcpmark-verified-postgres-20260704-gpt55-xhigh",
  group: "mcpmark",
  title: "Verified postgres standard slice",
  measuredAt: "2026-07-04 KST",
  suite: "postgres/standard",
  status: "complete",
  model: "gpt-5.5",
  provider: "openai-codex",
  source: "subscription",
  effort: "xhigh",
  route: "GEODE local MCPMark adapter + postgres-mcp",
  harness: "eval-sys/mcpmark@cd45b7f, postgres-mcp==0.3.0",
  artifact:
    "artifacts/eval/harnesses/mcpmark/results-geode-agentworld/geode-gpt55-xhigh-20260704-mcpmark-verified-postgres",
  scoreLabel: "Accuracy",
  scoreValue: "95.2% (20 / 21)",
  secondary: [
    "Total task execution time 8765.7s",
    "Average task execution time 417.4s",
    "Failure: employees/employee_performance_analysis",
  ],
  command: mcpmarkVerifiedAvailable.command.replace(
    "<filesystem|postgres|github>",
    "postgres",
  ),
  notes: [
    "The GEODE adapter overrides MCPMark's default postgres server with postgres-mcp==0.3.0 in unrestricted mode.",
    "A final NoEventLoopError appeared during async cleanup after result writing; it did not affect the recorded verifier result.",
  ],
};

const mcpmarkVerifiedGithub: BenchmarkMeasurement = {
  id: "mcpmark-verified-github-20260704-gpt55-xhigh",
  group: "mcpmark",
  title: "Verified github standard slice",
  measuredAt: "2026-07-04 KST",
  suite: "github/standard",
  status: "complete",
  model: "gpt-5.5",
  provider: "openai-codex",
  source: "subscription",
  effort: "xhigh",
  route: "GEODE local MCPMark adapter + GitHub MCP Docker server",
  harness: "eval-sys/mcpmark@cd45b7f, ghcr.io/github/github-mcp-server:v0.15.0",
  artifact:
    "artifacts/eval/harnesses/mcpmark/results-geode-agentworld/geode-gpt55-xhigh-20260704-mcpmark-verified-github*",
  scoreLabel: "Accuracy",
  scoreValue: "82.6% (19 / 23)",
  secondary: [
    "Total task execution time 16476.3s",
    "Average task execution time 716.4s",
    "Failures: claude-code/label_color_standardization, mcpmark-cicd/deployment_status_workflow, missing-semester/assign_contributor_labels, missing-semester/find_salient_file",
    "All transient GitHub repositories were deleted by MCPMark cleanup.",
  ],
  command: mcpmarkVerifiedAvailable.command.replace(
    "<filesystem|postgres|github>",
    "github",
  ),
  notes: [
    "The first label_color_standardization record is a fixture setup failure from GitHub state duplication; the retry produced an agent-level verification failure.",
    "The assign_contributor_labels failure used suffixed transient usernames in labels instead of canonical contributor labels.",
    "The find_salient_file failure did not create ANSWER.md on the required master branch.",
  ],
};

const mcpmarkNotionBlocked: BenchmarkMeasurement = {
  id: "mcpmark-notion-blocked-20260703",
  group: "mcpmark",
  title: "notion blocked prerequisite record",
  measuredAt: "2026-07-03 KST",
  suite: "notion/easy",
  status: "blocked",
  model: "gpt-5.5",
  provider: "openai-codex",
  source: "subscription",
  effort: "xhigh",
  route: "GEODE local MCPMark adapter",
  harness: "eval-sys/mcpmark@cd45b7f",
  artifact: "not created",
  scoreLabel: "Accuracy",
  scoreValue: "blocked",
  secondary: [
    "No Notion MCPMark score was produced in this cycle.",
    "The harness requires source and evaluation Notion workspace credentials.",
  ],
  command: `GEODE_REPO_ROOT=<geode-worktree> \\
OPENAI_API_KEY=dummy \\
.venv/bin/python pipeline.py \\
  --mcp notion \\
  --task-suite easy \\
  --models geode-gpt-5.5 \\
  --agent geode \\
  --reasoning-effort xhigh`,
  notes: [
    "Blocked before live execution because the local harness environment has no .mcp_env credentials.",
    "Record a measured score only after the Notion integration and paired workspaces are provisioned.",
  ],
};

const mcpmarkNotionUnblockSmoke: BenchmarkMeasurement = {
  id: "mcpmark-notion-unblock-smoke-20260710",
  group: "mcpmark",
  title: "notion unblock smoke (easy, single task)",
  measuredAt: "2026-07-10 KST",
  suite: "notion/easy",
  status: "complete",
  model: "gpt-5.5",
  provider: "openai-codex",
  source: "subscription",
  effort: "xhigh",
  route: "GEODE local MCPMark adapter",
  harness: "eval-sys/mcpmark@cd45b7f",
  artifact:
    "artifacts/eval/harnesses/mcpmark/results-geode-agentworld/geode-gpt55-xhigh-20260710-notion-smoke-unblock-r2/geode-gpt-5-5-xhigh__notion-easy/run-1",
  scoreLabel: "Accuracy",
  scoreValue: "1 / 1",
  secondary: [
    "State duplication 58.9s; agent 216.8s over 8 rounds; 62.8k input / 8.0k output tokens.",
    "The 2026-07-04 stall was an expired browser session: duplication page.goto to app.notion.com timed out at 120s per retry.",
    "Re-login used a real-Chrome-channel persistent context (Google OAuth rejects automation-flagged browsers); the session cookie lives on .app.notion.com.",
  ],
  command: `set -a; source .mcp_env; set +a
OPENAI_API_KEY=dummy \\
.venv/bin/python -m plugins.benchmark_harness.run_mcpmark \\
  --mcp notion \\
  --task-suite easy \\
  --tasks toronto_guide/simple__change_color \\
  --models geode-gpt-5.5 \\
  --agent geode \\
  --reasoning-effort xhigh`,
  notes: [
    "Verifier-backed single-task smoke proving the notion service is runnable end to end; not a notion standard score.",
    "The task embeds a Notion API trap: updating a select option color returns validation_error; the agent passed by redefining options via a database schema update.",
  ],
};

const mcpmarkPlaywrightBlocked: BenchmarkMeasurement = {
  id: "mcpmark-playwright-blocked-20260703",
  group: "mcpmark",
  title: "playwright blocked prerequisite record",
  measuredAt: "2026-07-03 KST",
  suite: "playwright/easy",
  status: "blocked",
  model: "gpt-5.5",
  provider: "openai-codex",
  source: "subscription",
  effort: "xhigh",
  route: "GEODE local MCPMark adapter",
  harness: "eval-sys/mcpmark@cd45b7f",
  artifact: "not created",
  scoreLabel: "Accuracy",
  scoreValue: "blocked",
  secondary: [
    "No Playwright MCPMark score was produced in this cycle.",
    "Browser/WebArena service setup was not available in the local benchmark environment.",
  ],
  command: `GEODE_REPO_ROOT=<geode-worktree> \\
OPENAI_API_KEY=dummy \\
.venv/bin/python pipeline.py \\
  --mcp playwright \\
  --task-suite easy \\
  --models geode-gpt-5.5 \\
  --agent geode \\
  --reasoning-effort xhigh`,
  notes: [
    "Blocked before live execution because the browser-backed service stack was not running.",
    "Record a measured score only after the browser environment is provisioned and health checked.",
  ],
};

const tau2MockSmoke: BenchmarkMeasurement = {
  id: "tau2-mock-smoke-20260703-gpt55-xhigh",
  group: "tau2",
  title: "mock/create_task_1 smoke",
  measuredAt: "2026-07-03 KST",
  suite: "mock / create_task_1",
  status: "complete",
  model: "gpt-5.5",
  provider: "openai",
  source: "subscription",
  effort: "agent xhigh / user high",
  route: "geode_agent + geode_user",
  harness: "sierra-research/tau2-bench@1901a30, tau2==1.0.0",
  artifact:
    "artifacts/eval/harnesses/tau2-bench/data/simulations/geode-gpt-5-5-xhigh-geode-user-mock-smoke-20260703-r5/results.json",
  scoreLabel: "Reward / pass^1",
  scoreValue: "1.0 / 1.000 (1 / 1)",
  secondary: [
    "DB check 1.0",
    "create_task action check 1.0",
    "Termination user_stop",
    "Duration 54.90s",
  ],
  command: `uv run python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain mock \\
  --num-tasks 1 \\
  --num-trials 1 \\
  --max-concurrency 1 \\
  --max-steps 8 \\
  --timeout 900 \\
  --model gpt-5.5 \\
  --provider openai \\
  --source subscription \\
  --effort xhigh \\
  --time-budget-s 180 \\
  --user geode_user \\
  --user-llm gpt-5.5 \\
  --user-provider openai \\
  --user-source subscription \\
  --user-effort high \\
  --user-time-budget-s 120 \\
  --save-to geode-gpt-5-5-xhigh-geode-user-mock-smoke-20260703-r5 \\
  --log-level INFO \\
  --verbose-logs`,
  notes: [
    "This is a tau2 wiring/regression smoke, not a tau2 leaderboard score.",
    "Do not average it with native tau2 user_simulator runs using gpt-4.1 or gpt-5.2.",
    "Both assistant and simulated user used the GEODE subscription route.",
  ],
};

const tau2MockGpt54: BenchmarkMeasurement = {
  id: "tau2-mock-20260802-gpt54-high-geode-user",
  group: "tau2",
  title: "mock/create_task_1 GPT-5.4 subscription diagnostic",
  measuredAt: "2026-08-02 KST",
  suite: "mock / create_task_1",
  status: "complete",
  model: "gpt-5.4",
  provider: "openai",
  source: "subscription",
  effort: "agent high / user high",
  route: "geode_agent + geode_user",
  harness: "sierra-research/tau2-bench@1901a30, tau2==1.0.0, GEODE@afaab52b",
  artifact:
    "geode-eval-artifacts@f588ce9fd23b9123732b45c4dbe202136691d3fe/tau2/simulations/geode-gpt54-high-afaab52b-geode-user-mock-smoke-20260802/results.json",
  scoreLabel: "Reward / pass^1",
  scoreValue: "0.0 / 0.000 (0 / 1)",
  secondary: [
    "Communication check 1.0 / DB check 0.0",
    "create_task action check 0.0",
    "Termination user_stop",
    "Duration 25.33s",
    "31 canonical events / 2 exact tool pairs",
  ],
  command: `python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain mock \\
  --task-ids create_task_1 \\
  --num-tasks 1 \\
  --num-trials 1 \\
  --max-concurrency 1 \\
  --max-steps 8 \\
  --timeout 900 \\
  --model gpt-5.4 \\
  --provider openai \\
  --source subscription \\
  --effort high \\
  --time-budget-s 180 \\
  --user geode_user \\
  --user-llm gpt-5.4 \\
  --user-provider openai \\
  --user-source subscription \\
  --user-effort high \\
  --user-time-budget-s 120 \\
  --save-to geode-gpt54-high-afaab52b-geode-user-mock-smoke-20260802`,
  notes: [
    "The model supplied unrequested description=\"\"; Tau2's exact action and DB comparators rejected it.",
    "No route, provider, adapter, quota, agent, or simulated-user exception occurred.",
    "This fixed GEODE-user diagnostic is not a native user_simulator headline row.",
    "The immutable source snapshot retains the runner-default train stage with promotion_authority=none; future benchmark commands should set --trajectory-stage benchmark explicitly.",
  ],
};

const tau2TelecomSmallGpt54: BenchmarkMeasurement = {
  id: "tau2-telecom-small-20260802-gpt54-high-geode-user",
  group: "tau2",
  title: "Telecom small first-task GPT-5.4 subscription diagnostic",
  measuredAt: "2026-08-02 KST",
  suite:
    "telecom / small / [mobile_data_issue]user_abroad_roaming_enabled_off[PERSONA:None]",
  status: "complete",
  model: "gpt-5.4",
  provider: "openai",
  source: "subscription",
  effort: "agent high / user high",
  route: "geode_agent + geode_user",
  harness: "sierra-research/tau2-bench@1901a30, tau2==1.0.0, GEODE@afaab52b",
  artifact:
    "geode-eval-artifacts@f588ce9fd23b9123732b45c4dbe202136691d3fe/tau2/simulations/geode-gpt54-high-afaab52b-geode-user-telecom-small-01-20260802/results.json",
  scoreLabel: "Reward / pass^1",
  scoreValue: "1.0 / 1.000 (1 / 1)",
  secondary: [
    "DB check 1.0",
    "toggle_roaming write action 1.0",
    "Mobile-data and excellent-speed assertions 1.0",
    "Termination user_stop",
    "Duration 119.83s / 127 canonical events / 8 exact tool pairs",
  ],
  command: `python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain telecom \\
  --task-split-name small \\
  --task-ids '[mobile_data_issue]user_abroad_roaming_enabled_off[PERSONA:None]' \\
  --num-tasks 1 \\
  --num-trials 1 \\
  --max-concurrency 1 \\
  --max-steps 50 \\
  --timeout 1800 \\
  --model gpt-5.4 \\
  --provider openai \\
  --source subscription \\
  --effort high \\
  --time-budget-s 300 \\
  --user geode_user \\
  --user-llm gpt-5.4 \\
  --user-provider openai \\
  --user-source subscription \\
  --user-effort high \\
  --user-time-budget-s 180 \\
  --save-to geode-gpt54-high-afaab52b-geode-user-telecom-small-01-20260802`,
  notes: [
    "The DB, toggle_roaming, mobile-data, and excellent-speed checks all passed.",
    "No route, provider, adapter, quota, agent, or simulated-user exception occurred.",
    "Tau2 results.json is the score authority; the 127-event trajectory is a digest-joined correlation and replay sidecar.",
    "The immutable source snapshot retains the runner-default train stage with promotion_authority=none; future benchmark commands should set --trajectory-stage benchmark explicitly.",
  ],
};

const tau2BaseFullGpt54: BenchmarkMeasurement = {
  id: "tau2-base-full-20260803-gpt54-high-geode-user",
  group: "tau2",
  title: "Airline + Retail + Telecom base full-cycle GPT-5.4 diagnostic",
  measuredAt: "2026-08-03 KST",
  suite: "airline + retail + telecom / base / 278 tasks",
  status: "complete",
  model: "gpt-5.4",
  provider: "openai",
  source: "subscription",
  effort: "agent high / user high",
  route: "geode_agent + geode_user",
  harness:
    "sierra-research/tau2-bench@1901a30, tau2==1.0.0, GEODE@22789ee2",
  artifact:
    "geode-eval-artifacts@86dcbba3d15f1979b71a501780bf66fea4b450b5/reports/e2e-validation/2026-08-03-gpt54-tau2-full-cycle.json",
  scoreLabel: "Weighted reward / pass^1",
  scoreValue: "0.7194 / 0.719 (200 / 278)",
  secondary: [
    "Airline 0.8400 (42 / 50)",
    "Retail 0.6930 (79 / 114)",
    "Telecom 0.6930 (79 / 114)",
    "51,985 canonical events / 3,964 exact tool pairs / zero orphans",
    "Telecom p95 957.65s / 14 max-step terminations / MMS 21 of 49",
  ],
  command: `# Run once per domain with num-tasks 50 (airline) or 114 (retail/telecom).
python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain <airline|retail|telecom> \\
  --task-split-name base \\
  --num-tasks <50|114> \\
  --num-trials 1 \\
  --max-concurrency 2 \\
  --max-steps 200 \\
  --max-errors 1 \\
  --max-retries <0|1> \\
  --timeout 3600 \\
  --model gpt-5.4 \\
  --provider openai \\
  --source subscription \\
  --effort high \\
  --time-budget-s 600 \\
  --user geode_user \\
  --user-llm gpt-5.4 \\
  --user-provider openai \\
  --user-source subscription \\
  --user-effort high \\
  --user-time-budget-s 180 \\
  --trajectory-stage benchmark \\
  --save-to <domain-specific-run-id>`,
  notes: [
    "This GEODE-user full cycle is not comparable to the native tau2 user_simulator headline matrix.",
    "Tau2 results.json is score authority; the trajectory release is a privacy-reviewed diagnostic and external-loop sidecar.",
    "Seven Telecom transport retries created 14 extra SQLite sessions outside the final trajectory parents; no behavior-score failure was retried.",
    "The released trajectories are scope-complete for final task attempts and replay-incomplete for bounded bodies and retry-attempt lineage.",
    "The isolated Tau2 AgenticLoop records no public hook_events; the separate hook behavior E2E remains hook authority.",
  ],
};

const tau2MockGpt54V1012: BenchmarkMeasurement = {
  id: "tau2-mock-20260803-gpt54-high-geode-user-v1012",
  group: "tau2",
  title: "mock/create_task_1 GPT-5.4 v1.0.12 post-release diagnostic",
  measuredAt: "2026-08-03 KST",
  suite: "mock / create_task_1",
  status: "complete",
  model: "gpt-5.4",
  provider: "openai",
  source: "subscription",
  effort: "agent high / user high",
  route: "geode_agent + geode_user",
  harness:
    "sierra-research/tau2-bench@1901a30, tau2==1.0.0, GEODE v1.0.12@f99cea63",
  artifact:
    "geode-eval-artifacts@04ff1c4a1fee0cd1a3d837ad3a5f5239f1fd9acd/tau2/simulations/geode-gpt54-high-v1.0.12-f99cea63-geode-user-mock-smoke-20260803/results.json",
  scoreLabel: "Reward / pass^1",
  scoreValue: "0.0 / 0.000 (0 / 1)",
  secondary: [
    "Communication check 1.0 / DB check 0.0",
    "create_task action check 0.0",
    "Termination user_stop",
    "Duration 13.75s / 31 canonical events / 2 exact tool pairs",
  ],
  command: `python scripts/eval/tau2_geode_agent.py \
  --harness-dir artifacts/eval/harnesses/tau2-bench \
  --domain mock \
  --task-ids create_task_1 \
  --num-tasks 1 \
  --num-trials 1 \
  --max-concurrency 1 \
  --max-steps 8 \
  --timeout 900 \
  --model gpt-5.4 \
  --provider openai \
  --source subscription \
  --effort high \
  --time-budget-s 180 \
  --user geode_user \
  --user-llm gpt-5.4 \
  --user-provider openai \
  --user-source subscription \
  --user-effort high \
  --user-time-budget-s 120 \
  --trajectory-stage benchmark \
  --save-to geode-gpt54-high-v1.0.12-f99cea63-geode-user-mock-smoke-20260803`,
  notes: [
    "The simulated user stopped before a verifier-compatible state change; DB and action checks are zero while communication is one.",
    "The run has no authentication, quota, provider-adapter, or harness exception and is retained without retry.",
    "This release smoke is not a rerun or replacement of the 278-task full cycle and is not a native user_simulator leaderboard row.",
  ],
};

const tau2TelecomSmallGpt54V1012: BenchmarkMeasurement = {
  id: "tau2-telecom-small-20260803-gpt54-high-geode-user-v1012",
  group: "tau2",
  title: "Telecom small first-task GPT-5.4 v1.0.12 post-release diagnostic",
  measuredAt: "2026-08-03 KST",
  suite:
    "telecom / small / [mobile_data_issue]user_abroad_roaming_enabled_off[PERSONA:None]",
  status: "complete",
  model: "gpt-5.4",
  provider: "openai",
  source: "subscription",
  effort: "agent high / user high",
  route: "geode_agent + geode_user",
  harness:
    "sierra-research/tau2-bench@1901a30, tau2==1.0.0, GEODE v1.0.12@f99cea63",
  artifact:
    "geode-eval-artifacts@04ff1c4a1fee0cd1a3d837ad3a5f5239f1fd9acd/tau2/simulations/geode-gpt54-high-v1.0.12-f99cea63-geode-user-telecom-small-01-20260803/results.json",
  scoreLabel: "Reward / pass^1",
  scoreValue: "0.0 / 0.000 (0 / 1)",
  secondary: [
    "Termination max_steps before native component scoring",
    "Duration 236.73s",
    "203 canonical events / 14 exact tool pairs",
    "Repeated customer, line, network, usage, restriction, and VPN diagnostics",
  ],
  command: `python scripts/eval/tau2_geode_agent.py \
  --harness-dir artifacts/eval/harnesses/tau2-bench \
  --domain telecom \
  --task-split-name small \
  --task-ids '[mobile_data_issue]user_abroad_roaming_enabled_off[PERSONA:None]' \
  --num-tasks 1 \
  --num-trials 1 \
  --max-concurrency 1 \
  --max-steps 50 \
  --timeout 1800 \
  --model gpt-5.4 \
  --provider openai \
  --source subscription \
  --effort high \
  --time-budget-s 300 \
  --user geode_user \
  --user-llm gpt-5.4 \
  --user-provider openai \
  --user-source subscription \
  --user-effort high \
  --user-time-budget-s 180 \
  --trajectory-stage benchmark \
  --save-to geode-gpt54-high-v1.0.12-f99cea63-geode-user-telecom-small-01-20260803`,
  notes: [
    "The run reached 50 steps before native DB/action scoring; repeated diagnostics are preserved as behavior evidence.",
    "All fourteen tool calls have exactly one result, with no route, authentication, quota, or adapter failure.",
    "This two-task release smoke does not invalidate or replace the 200/278 full-cycle diagnostic.",
  ],
};

const tau2MockGpt56: BenchmarkMeasurement = {
  id: "tau2-mock-20260731-gpt56-high-geode-user",
  group: "tau2",
  title: "mock/create_task_1 GPT-5.6 subscription diagnostic",
  measuredAt: "2026-07-31 KST",
  suite: "mock / create_task_1",
  status: "complete",
  model: "gpt-5.6-sol",
  provider: "openai",
  source: "subscription",
  effort: "agent high / user high",
  route: "geode_agent + geode_user",
  harness: "sierra-research/tau2-bench@1901a30, tau2==1.0.0, GEODE@edb74602b",
  artifact:
    "geode-eval-artifacts@9c00ecf/tau2/simulations/geode-gpt56-sol-high-edb74602b-geode-user-mock-smoke-20260731/results.json",
  scoreLabel: "Reward / pass^1",
  scoreValue: "0.0 / 0.000 (0 / 1)",
  secondary: [
    "Communication check 1.0 / DB check 0.0",
    "create_task action check 0.0",
    "Termination user_stop",
    "Duration 14.58s",
  ],
  command: `python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain mock \\
  --num-tasks 1 \\
  --num-trials 1 \\
  --max-concurrency 1 \\
  --max-steps 8 \\
  --timeout 900 \\
  --model gpt-5.6-sol \\
  --provider openai \\
  --source subscription \\
  --effort high \\
  --user geode_user \\
  --user-llm gpt-5.6-sol \\
  --user-source subscription \\
  --user-effort high \\
  --save-to geode-gpt56-sol-high-edb74602b-geode-user-mock-smoke-20260731`,
  notes: [
    "The create_task tool executed, but the model supplied an unrequested optional description=\"\".",
    "Tau2's exact action and DB comparators rejected the extra argument; this is retained as a behavioral failure.",
    "This GEODE-owned user route is not comparable to the native tau2 user_simulator headline.",
  ],
};

const tau2TelecomSmallGpt56: BenchmarkMeasurement = {
  id: "tau2-telecom-small-20260731-gpt56-high-geode-user",
  group: "tau2",
  title: "Telecom small first-task GPT-5.6 subscription diagnostic",
  measuredAt: "2026-07-31 KST",
  suite:
    "telecom / small / [mobile_data_issue]user_abroad_roaming_enabled_off[PERSONA:None]",
  status: "complete",
  model: "gpt-5.6-sol",
  provider: "openai",
  source: "subscription",
  effort: "agent high / user high",
  route: "geode_agent + geode_user",
  harness: "sierra-research/tau2-bench@1901a30, tau2==1.0.0, GEODE@edb74602b",
  artifact:
    "geode-eval-artifacts@9c00ecf/tau2/simulations/geode-gpt56-sol-high-edb74602b-geode-user-telecom-small-01-20260731/results.json",
  scoreLabel: "Reward / pass^1",
  scoreValue: "0.0 / 0.000 (0 / 1)",
  secondary: [
    "Required user toggle_roaming action 0.0",
    "Mobile-data and excellent-speed assertions 0.0",
    "Termination user_stop after human transfer",
    "Duration 51.91s",
  ],
  command: `python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain telecom \\
  --task-split-name small \\
  --task-ids '[mobile_data_issue]user_abroad_roaming_enabled_off[PERSONA:None]' \\
  --num-tasks 1 \\
  --num-trials 1 \\
  --max-concurrency 1 \\
  --max-steps 50 \\
  --timeout 1800 \\
  --model gpt-5.6-sol \\
  --provider openai \\
  --source subscription \\
  --effort high \\
  --user geode_user \\
  --user-llm gpt-5.6-sol \\
  --user-source subscription \\
  --user-effort high \\
  --save-to geode-gpt56-sol-high-edb74602b-geode-user-telecom-small-01-20260731`,
  notes: [
    "The agent correctly identified the customer, line, roaming state, and data usage.",
    "It then declared device tools unavailable and transferred to a human instead of guiding the user-side roaming/device workflow.",
    "No provider, quota, or adapter exception occurred; the failure is retained as behavior evidence.",
  ],
};

const tau2MockGpt56V1011: BenchmarkMeasurement = {
  id: "tau2-mock-20260731-gpt56-high-geode-user-v1011",
  group: "tau2",
  title: "mock/create_task_1 GPT-5.6 v1.0.11 diagnostic",
  measuredAt: "2026-07-31 KST",
  suite: "mock / create_task_1",
  status: "complete",
  model: "gpt-5.6-sol",
  provider: "openai",
  source: "subscription",
  effort: "agent high / user high",
  route: "geode_agent + geode_user",
  harness: "sierra-research/tau2-bench@1901a30, tau2==1.0.0, GEODE v1.0.11@686ff372",
  artifact:
    "geode-eval-artifacts@16a54f08450db771c02e30c73bdc3867f6282f83/tau2/simulations/geode-gpt56-sol-high-v1011-686ff372-geode-user-mock-smoke-20260731/results.json",
  scoreLabel: "Reward / pass^1",
  scoreValue: "0.0 / 0.000 (0 / 1)",
  secondary: [
    "Communication check 1.0 / DB check 0.0",
    "create_task action check 0.0",
    "Termination user_stop",
    "Duration 9.03s",
    "25 canonical events / 1 exactly paired tool call and result",
  ],
  command: `python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain mock \\
  --num-tasks 1 \\
  --num-trials 1 \\
  --max-concurrency 1 \\
  --max-steps 8 \\
  --timeout 900 \\
  --model gpt-5.6-sol \\
  --provider openai \\
  --source subscription \\
  --effort high \\
  --time-budget-s 180 \\
  --user geode_user \\
  --user-llm gpt-5.6-sol \\
  --user-source subscription \\
  --user-effort high \\
  --user-time-budget-s 120 \\
  --save-to geode-gpt56-sol-high-v1011-686ff372-geode-user-mock-smoke-20260731`,
  notes: [
    "The failure reproduces the earlier behavior: create_task includes unrequested description=\"\" and the native exact comparator rejects it.",
    "The run completed normally and is retained without retry or relabeling.",
    "This diagnostic has promotion_authority=none and is not a native user_simulator leaderboard row.",
  ],
};

const tau2TelecomSmallGpt56V1011: BenchmarkMeasurement = {
  id: "tau2-telecom-small-20260731-gpt56-high-geode-user-v1011",
  group: "tau2",
  title: "Telecom small first-task GPT-5.6 v1.0.11 diagnostic",
  measuredAt: "2026-07-31 KST",
  suite:
    "telecom / small / [mobile_data_issue]user_abroad_roaming_enabled_off[PERSONA:None]",
  status: "complete",
  model: "gpt-5.6-sol",
  provider: "openai",
  source: "subscription",
  effort: "agent high / user high",
  route: "geode_agent + geode_user",
  harness: "sierra-research/tau2-bench@1901a30, tau2==1.0.0, GEODE v1.0.11@686ff372",
  artifact:
    "geode-eval-artifacts@16a54f08450db771c02e30c73bdc3867f6282f83/tau2/simulations/geode-gpt56-sol-high-v1011-686ff372-geode-user-telecom-small-01-20260731/results.json",
  scoreLabel: "Reward / pass^1",
  scoreValue: "1.0 / 1.000 (1 / 1)",
  secondary: [
    "DB check 1.0",
    "toggle_roaming write action 1.0",
    "Mobile-data and excellent-speed assertions 1.0",
    "Termination user_stop",
    "Duration 78.52s / 117 canonical events / 8 exact tool pairs",
  ],
  command: `python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain telecom \\
  --task-split-name small \\
  --task-ids '[mobile_data_issue]user_abroad_roaming_enabled_off[PERSONA:None]' \\
  --num-tasks 1 \\
  --num-trials 1 \\
  --max-concurrency 1 \\
  --max-steps 50 \\
  --timeout 1800 \\
  --model gpt-5.6-sol \\
  --provider openai \\
  --source subscription \\
  --effort high \\
  --time-budget-s 300 \\
  --user geode_user \\
  --user-llm gpt-5.6-sol \\
  --user-source subscription \\
  --user-effort high \\
  --user-time-budget-s 180 \\
  --save-to geode-gpt56-sol-high-v1011-686ff372-geode-user-telecom-small-01-20260731`,
  notes: [
    "The earlier premature human-transfer failure is closed for this fixed case.",
    "Tau2 native DB/action/assertion checks remain the score authority; the GEODE trajectory is a digest-joined replay sidecar.",
    "The Crucible v3 snapshot remains diagnostic with promotion_authority=none because no frozen experiment contract was supplied.",
  ],
};

const tau2NativeAirlineBase: BenchmarkMeasurement = {
  id: "tau2-airline-base-20260703-geode-099269-gpt52-high-payg",
  group: "tau2",
  title: "airline/base native user_simulator",
  measuredAt: "2026-07-03 KST",
  suite: "airline / base",
  status: "complete",
  model: "gpt-5.2",
  provider: "openai",
  source: "payg",
  effort: "agent high / user medium",
  route: "geode_agent + native tau2 user_simulator",
  harness: "sierra-research/tau2-bench@1901a30, tau2==1.0.0, GEODE v0.99.269",
  artifact:
    "artifacts/eval/harnesses/tau2-bench/data/simulations/geode-gpt-5-2-high-native-user-airline-base-20260703/results.json",
  scoreLabel: "Reward / pass^1",
  scoreValue: "0.8200 / 0.820 (41 / 50)",
  secondary: [
    "DB match 42 / 50",
    "Read actions 81 / 91",
    "Write actions 33 / 49",
    "Termination user_stop 50 / 50",
    "Duration total 14205.02s / avg 284.10s / max 979.65s",
  ],
  command: `uv run python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain airline \\
  --task-split-name base \\
  --num-tasks 50 \\
  --num-trials 1 \\
  --max-concurrency 2 \\
  --max-steps 200 \\
  --timeout 3600 \\
  --model gpt-5.2 \\
  --provider openai \\
  --source payg \\
  --effort high \\
  --time-budget-s 600 \\
  --user user_simulator \\
  --user-llm gpt-4.1-2025-04-14 \\
  --user-provider openai \\
  --user-source payg \\
  --user-effort medium \\
  --user-time-budget-s 120 \\
  --save-to geode-gpt-5-2-high-native-user-airline-base-20260703 \\
  --log-level INFO \\
  --auto-resume`,
  notes: [
    "GEODE version at measurement: v0.99.269.",
    "This is the native tau2 user_simulator comparator track, not the GEODE geode_user smoke track.",
    "Airline is retained for internal trend comparison; OpenAI's GPT-5.2 announcement excludes Airline from its Tau2 headline due to lower-quality ground truth grading.",
  ],
};

const tau2NativeRetailBase: BenchmarkMeasurement = {
  id: "tau2-retail-base-20260703-geode-099269-gpt52-high-payg",
  group: "tau2",
  title: "retail/base native user_simulator",
  measuredAt: "2026-07-03 KST",
  suite: "retail / base",
  status: "complete",
  model: "gpt-5.2",
  provider: "openai",
  source: "payg",
  effort: "agent high / user medium",
  route: "geode_agent + native tau2 user_simulator",
  harness: "sierra-research/tau2-bench@1901a30, tau2==1.0.0, GEODE v0.99.269",
  artifact:
    "artifacts/eval/harnesses/tau2-bench/data/simulations/geode-gpt-5-2-high-native-user-retail-base-20260703/results.json",
  scoreLabel: "Reward / pass^1",
  scoreValue: "0.7632 / 0.763 (87 / 114)",
  secondary: [
    "DB match 88 / 113",
    "Read actions 320 / 354",
    "Write actions 140 / 174",
    "Termination user_stop 113 / 114, too_many_errors 1 / 114",
    "Duration total 23543.64s / avg 206.52s / max 873.92s",
  ],
  command: `uv run python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain retail \\
  --task-split-name base \\
  --num-tasks 114 \\
  --num-trials 1 \\
  --max-concurrency 2 \\
  --max-steps 200 \\
  --timeout 3600 \\
  --model gpt-5.2 \\
  --provider openai \\
  --source payg \\
  --effort high \\
  --time-budget-s 600 \\
  --user user_simulator \\
  --user-llm gpt-4.1-2025-04-14 \\
  --user-provider openai \\
  --user-source payg \\
  --user-effort medium \\
  --user-time-budget-s 120 \\
  --save-to geode-gpt-5-2-high-native-user-retail-base-20260703 \\
  --log-level INFO \\
  --auto-resume`,
  notes: [
    "GEODE version at measurement: v0.99.269.",
    "The main failure mode was missing required side-effect actions even when the natural-language response looked plausible.",
    "One task terminated with too_many_errors; the remaining failures ended with user_stop but failed verifier assertions.",
  ],
};

const tau2NativeTelecomBase: BenchmarkMeasurement = {
  id: "tau2-telecom-base-20260703-geode-099269-gpt52-high-payg",
  group: "tau2",
  title: "telecom/base native user_simulator",
  measuredAt: "2026-07-04 03:45 KST",
  suite: "telecom / base",
  status: "complete",
  model: "gpt-5.2",
  provider: "openai",
  source: "payg",
  effort: "agent high / user medium",
  route: "geode_agent + native tau2 user_simulator",
  harness: "sierra-research/tau2-bench@1901a30, tau2==1.0.0, GEODE v0.99.269",
  artifact:
    "artifacts/eval/harnesses/tau2-bench/data/simulations/geode-gpt-5-2-high-native-user-telecom-base-20260703/results.json",
  scoreLabel: "Reward / pass^1",
  scoreValue: "0.8772 / 0.877 (100 / 114)",
  secondary: [
    "DB match 31 / 114",
    "Write actions 471 / 496",
    "Generic actions 20 / 20",
    "Termination user_stop 114 / 114",
    "Duration total 28827.72s / avg 252.87s / max 818.58s",
  ],
  command: `uv run python scripts/eval/tau2_geode_agent.py \\
  --harness-dir artifacts/eval/harnesses/tau2-bench \\
  --domain telecom \\
  --task-split-name base \\
  --num-tasks 114 \\
  --num-trials 1 \\
  --max-concurrency 4 \\
  --max-steps 200 \\
  --timeout 3600 \\
  --model gpt-5.2 \\
  --provider openai \\
  --source payg \\
  --effort high \\
  --time-budget-s 600 \\
  --user user_simulator \\
  --user-llm gpt-4.1-2025-04-14 \\
  --user-provider openai \\
  --user-source payg \\
  --user-effort medium \\
  --user-time-budget-s 120 \\
  --save-to geode-gpt-5-2-high-native-user-telecom-base-20260703 \\
  --log-level INFO \\
  --auto-resume`,
  notes: [
    "GEODE version at measurement: v0.99.269.",
    "Concurrency was raised from 2 to 4 mid-run and resumed from tau2 checkpoints; no rate-limit, quota, or billing errors were observed.",
    "Failures clustered around multi-issue MMS/mobile-data/service cases where one required APN, permission, roaming, or data-refuel action was omitted.",
  ],
};

const tau2NativeAggregate: BenchmarkMeasurement = {
  id: "tau2-base-aggregate-20260703-geode-099269-gpt52-high-payg",
  group: "tau2",
  title: "base aggregate native user_simulator",
  measuredAt: "2026-07-04 03:45 KST",
  suite: "airline + retail + telecom / base",
  status: "complete",
  model: "gpt-5.2",
  provider: "openai",
  source: "payg",
  effort: "agent high / user medium",
  route: "geode_agent + native tau2 user_simulator",
  harness: "sierra-research/tau2-bench@1901a30, tau2==1.0.0, GEODE v0.99.269",
  artifact:
    "artifacts/eval/harnesses/tau2-bench/data/simulations/geode-gpt-5-2-high-native-user-{airline,retail,telecom}-base-20260703/results.json",
  scoreLabel: "Weighted reward / pass^1",
  scoreValue: "0.8201 / 0.820 (228 / 278)",
  secondary: [
    "Airline 0.8200 (41 / 50)",
    "Retail 0.7632 (87 / 114)",
    "Telecom 0.8772 (100 / 114)",
    "Native user simulator gpt-4.1-2025-04-14",
    "GEODE recorded gpt-5.2 PAYG usage locally; user simulator cost is visible through OpenAI billing, not GEODE's usage ledger.",
  ],
  command: `# Aggregate of the three per-domain native tau2 runs listed above.
# Do not average this with mock smoke or GEODE geode_user rows.`,
  notes: [
    "This weighted aggregate is for internal Agent-World-style comparison only.",
    "The run spec differs from OpenAI's official GPT-5.2 Tau2 headline, which used an internal research setup and excludes Airline.",
    "The run spec differs from the earlier GEODE geode_user smoke matrix.",
  ],
};

export const BENCHMARK_GROUPS: BenchmarkGroup[] = [
  {
    id: "mcpmark",
    title: "MCPMark",
    titleKo: "MCPMark",
    summary:
      "MCP tool-use measurements grouped by MCP surface. The matrix follows the Agent-World style columns but keeps unmeasured or blocked surfaces explicit.",
    summaryKo:
      "MCP tool-use 실측을 MCP surface별로 묶습니다. Agent-World식 column을 따르되, 미측정 또는 준비 차단된 surface를 명시합니다.",
    matrix: [
      {
        label: "File",
        value: "83.3%",
        measurementId: mcpmarkVerifiedFilesystem.id,
        note: "standard, 25 / 30",
      },
      {
        label: "GitHub",
        value: "82.6%",
        measurementId: mcpmarkVerifiedGithub.id,
        note: "standard, 19 / 23",
      },
      {
        label: "Notion",
        value: "unmeasured",
        measurementId: mcpmarkNotionUnblockSmoke.id,
        note: "unblocked 2026-07-10 (easy smoke 1/1); standard 28 tasks not yet measured",
      },
      {
        label: "Playwright",
        value: "unmeasured",
        measurementId: mcpmarkPlaywrightBlocked.id,
        note: "live-web subset runnable since 2026-07-10; WebArena subset needs ~100GB images (local disk exceeded)",
      },
      {
        label: "Postgres",
        value: "95.2%",
        measurementId: mcpmarkVerifiedPostgres.id,
        note: "standard, 20 / 21",
      },
      {
        label: "Avg.",
        value: "86.5%",
        measurementId: mcpmarkVerifiedAvailable.id,
        note: "Measured available services only: filesystem+postgres+github",
      },
    ],
    measurements: [
      mcpmarkVerifiedAvailable,
      mcpmarkFilesystemEasyGpt54TokenEfficiency,
      mcpmarkFilesystemEasyGpt54V1012,
      mcpmarkFilesystemEasyGpt56V1011,
      mcpmarkFilesystemEasyGpt56,
      mcpmarkVerifiedGithub,
      mcpmarkVerifiedPostgres,
      mcpmarkVerifiedFilesystem,
      mcpmarkFilesystemEasyParallel,
      mcpmarkFilesystemEasy,
      mcpmarkNotionUnblockSmoke,
      mcpmarkNotionBlocked,
      mcpmarkPlaywrightBlocked,
    ],
  },
  {
    id: "tau2",
    title: "Tau2",
    titleKo: "Tau2",
    summary:
      "Conversational tool-use measurements grouped by tau2 domain and user route. GEODE-owned runs keep the agent and simulated user routes explicit.",
    summaryKo:
      "tau2 domain과 user route별 conversational tool-use 실측입니다. GEODE 자체 run은 agent와 simulated user route를 분리해 기록합니다.",
    matrix: [
      {
        label: "Mock",
        value: "1.000",
        measurementId: tau2MockSmoke.id,
        note: "reward 1.0, pass^1 1.000",
      },
      {
        label: "Retail",
        value: "0.763",
        measurementId: tau2NativeRetailBase.id,
        note: "base, 114 tasks, native user_simulator",
      },
      {
        label: "Telecom",
        value: "0.877",
        measurementId: tau2NativeTelecomBase.id,
        note: "base, 114 tasks, native user_simulator",
      },
      {
        label: "Airline",
        value: "0.820",
        measurementId: tau2NativeAirlineBase.id,
        note: "base, 50 tasks, native user_simulator",
      },
      {
        label: "Avg.",
        value: "0.820",
        measurementId: tau2NativeAggregate.id,
        note: "weighted across airline+retail+telecom, excludes mock",
      },
    ],
    measurements: [
      tau2BaseFullGpt54,
      tau2TelecomSmallGpt54V1012,
      tau2MockGpt54V1012,
      tau2TelecomSmallGpt54,
      tau2MockGpt54,
      tau2NativeAggregate,
      tau2TelecomSmallGpt56V1011,
      tau2MockGpt56V1011,
      tau2TelecomSmallGpt56,
      tau2MockGpt56,
      tau2NativeTelecomBase,
      tau2NativeRetailBase,
      tau2NativeAirlineBase,
      tau2MockSmoke,
    ],
  },
];
