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

const mcpmarkGithubBlocked: BenchmarkMeasurement = {
  id: "mcpmark-github-blocked-20260703",
  group: "mcpmark",
  title: "github blocked prerequisite record",
  measuredAt: "2026-07-03 KST",
  suite: "github/easy",
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
    "No GitHub MCPMark score was produced in this cycle.",
    "The harness requires GITHUB_TOKENS and an evaluation organization.",
  ],
  command: `GEODE_REPO_ROOT=<geode-worktree> \\
OPENAI_API_KEY=dummy \\
.venv/bin/python pipeline.py \\
  --mcp github \\
  --task-suite easy \\
  --models geode-gpt-5.5 \\
  --agent geode \\
  --reasoning-effort xhigh`,
  notes: [
    "Blocked before live execution because the local harness environment has no .mcp_env credentials.",
    "Record a measured score only after the GitHub evaluation org and token set are provisioned.",
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

const mcpmarkPostgresBlocked: BenchmarkMeasurement = {
  id: "mcpmark-postgres-blocked-20260703",
  group: "mcpmark",
  title: "postgres blocked prerequisite record",
  measuredAt: "2026-07-03 KST",
  suite: "postgres/easy",
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
    "No Postgres MCPMark score was produced in this cycle.",
    "Docker-dependent Postgres restore and service setup were not available.",
  ],
  command: `GEODE_REPO_ROOT=<geode-worktree> \\
OPENAI_API_KEY=dummy \\
.venv/bin/python pipeline.py \\
  --mcp postgres \\
  --task-suite easy \\
  --models geode-gpt-5.5 \\
  --agent geode \\
  --reasoning-effort xhigh`,
  notes: [
    "Blocked before live execution because Docker service discovery did not complete in the local benchmark environment.",
    "Record a measured score only after the Postgres container, backup restore, and verifier setup pass health checks.",
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
        value: "100.0%",
        measurementId: mcpmarkFilesystemEasyParallel.id,
        note: "filesystem/easy, 10 tasks, category-parallel rerun",
      },
      {
        label: "GitHub",
        value: "blocked",
        measurementId: mcpmarkGithubBlocked.id,
        note: "GITHUB_TOKENS and eval org required",
      },
      {
        label: "Notion",
        value: "blocked",
        measurementId: mcpmarkNotionBlocked.id,
        note: "source/eval Notion workspace credentials required",
      },
      {
        label: "Playwright",
        value: "blocked",
        measurementId: mcpmarkPlaywrightBlocked.id,
        note: "browser/WebArena service setup required",
      },
      {
        label: "Postgres",
        value: "blocked",
        measurementId: mcpmarkPostgresBlocked.id,
        note: "Docker Postgres and backup restore required",
      },
      { label: "Avg.", value: "100.0%", note: "Measured surfaces only: File" },
    ],
    measurements: [
      mcpmarkFilesystemEasyParallel,
      mcpmarkFilesystemEasy,
      mcpmarkGithubBlocked,
      mcpmarkNotionBlocked,
      mcpmarkPlaywrightBlocked,
      mcpmarkPostgresBlocked,
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
      { label: "Retail", value: "planned", note: "Full domain run pending" },
      { label: "Telecom", value: "planned", note: "Next small run target" },
      { label: "Airline", value: "planned", note: "Later HAL/tau-bench comparator path" },
      { label: "Avg.", value: "1.000", note: "Measured surfaces only: Mock" },
    ],
    measurements: [tau2MockSmoke],
  },
];
