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
      tau2NativeAggregate,
      tau2NativeTelecomBase,
      tau2NativeRetailBase,
      tau2NativeAirlineBase,
      tau2MockSmoke,
    ],
  },
];
