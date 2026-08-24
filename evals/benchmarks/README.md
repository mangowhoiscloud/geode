# GEODE Benchmark Harness Plugin

This plugin keeps GEODE-owned benchmark adapters public while third-party
benchmark repositories remain ignored local checkouts under
`artifacts/eval/harnesses/`.

It covers:

- `mcpmark`: upstream `eval-sys/mcpmark` pinned by commit, with GEODE and
  filesystem-only Codex CLI `BaseMCPAgent` adapters in
  `mcpmark_geode_agent.py`.
- `tau2-bench`: upstream `sierra-research/tau2-bench` pinned by commit, with
  the GEODE participant adapter in `tau2_geode_agent.py`.

Secrets are never stored here. Put real tokens in ignored `.mcp_env` files and
keep only placeholder variable names in `.env.example` / `.mcp_env.example`.

Common commands:

```bash
python -m evals.benchmarks.cli list
python -m evals.benchmarks.cli ensure mcpmark
python -m evals.benchmarks.cli install mcpmark
python -m evals.benchmarks.cli preflight mcpmark --env-file .mcp_env
python -m evals.benchmarks.cli ensure tau2-bench
python -m evals.benchmarks.cli healthcheck tau2-bench
```

`ensure`, `install`, and `healthcheck` print the reproducible shell commands
instead of executing them. This keeps the public plugin side-effect free; live
benchmark sessions can run the emitted commands explicitly.

MCPMark and GEODE declare incompatible `openai-agents` package ranges, so do
not install both projects into one environment. `cli install mcpmark` prints
commands for an upstream-only MCPMark `.venv` and a separate dependency-clean
GEODE `.venv`. The filesystem paired runner uses the latter and imports the
pinned harness from its source checkout. Before any model call it checks
`pip check`, the MCPMark/adapter imports, and Node's `npx`; other services keep
using the upstream-only environment.

For MCPMark, register both comparison agents inside an upstream checkout before
running `pipeline.py`:

```python
from evals.benchmarks.mcpmark_geode_agent import register_mcpmark_agent
from src.agents import AGENT_REGISTRY

register_mcpmark_agent(AGENT_REGISTRY)
```

Registration also wraps the pinned evaluator's error path so fixture cleanup is
attempted before an escaped execution error aborts the run.

Use `--agent geode --models geode-gpt-5.4` for GEODE or
`--agent codex --models codex-gpt-5.4` for the isolated Codex CLI arm. The Codex
adapter currently accepts only `--mcp filesystem`; other services remain out of
scope until this paired diagnostic shows a real need.

For the fail-closed Filesystem-30 pair, freeze and validate a run spec first,
then point the public serial runner at a **new** output path:

Run `python -m evals.benchmarks.cli install mcpmark` and execute its
printed setup commands first; the commands prepare both isolated environments.

```bash
<geode-checkout>/.venv/bin/python -m evals.benchmarks.run_mcpmark_pair \
  --run-spec <run-spec.json> --mcpmark-root <pinned-mcpmark> \
  --output-dir <fresh-attempt-root> \
  --python <geode-checkout>/.venv/bin/python
```

The spec's `initial_state_ref` must be
`fixture-semantic-sha256:273477d554250f4f076e69651e29689ed71095ec1b3fe3e054094be82f574fbf`.
It binds file bytes, mtimes, modes, and empty directories. A mismatch stops
before any model call; a retry uses a new attempt root rather than resuming
native output.

Gate 0C starts with one paired task under the same runner and evidence
contract:

```bash
<geode-checkout>/.venv/bin/python -m evals.benchmarks.run_mcpmark_pair \
  --profile filesystem1-geode-codex-smoke --task <filesystem-standard-task> \
  --run-spec <smoke-run-spec.json> --mcpmark-root <pinned-mcpmark> \
  --output-dir <fresh-smoke-attempt-root> \
  --python <geode-checkout>/.venv/bin/python
```

The smoke result records accepted paired-task coverage. The full
`filesystem30-geode-codex` result records the signed GEODE-minus-Codex
verifier-pass-rate delta directly in `runner-result.json`; no second score
receipt is needed. Pair specs bind comparator identity to `codex-cli 0.145.0`
and `openai/codex@dad1db87bb5ad4b92af6b0f58502d12453681f81`; the runner plan
also records the executable digest without publishing a machine-local path.
The GEODE arm is fixed at `GEODE_MAX_TOOL_RESULT_TOKENS=25000`; its native
deadline receipt must match that cap and the preflighted filesystem tool schema.

Gate 0B reuses the same runner for the frozen five-task, two-cap, three-repeat
diagnostic (30 independent GEODE processes):

```bash
<geode-checkout>/.venv/bin/python -m evals.benchmarks.run_mcpmark_pair \
  --profile max-tool-result-tokens \
  --run-spec <gate-0b-run-spec.json> --mcpmark-root <pinned-mcpmark> \
  --output-dir <fresh-attempt-root> \
  --python <geode-checkout>/.venv/bin/python
```

The profile alternates `GEODE_MAX_TOOL_RESULT_TOKENS=25000` and `0`, records
the effective cap and offload-store state in each deadline receipt, and stops
if the current direct MCP `CallToolResult` evidence cannot reconstruct the
model-facing truncation outcome. A completed run writes `runner-result.json`,
which binds the accepted native receipts through `runner-events.jsonl` and
exposes the signed pass-rate numerator and denominator for `analysis.json`.
