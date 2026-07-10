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
      tau2NativeAggregate,
      tau2NativeTelecomBase,
      tau2NativeRetailBase,
      tau2NativeAirlineBase,
      tau2MockSmoke,
    ],
  },
];
