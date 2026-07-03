# GEODE Benchmark Harness Plugin

This plugin keeps GEODE-owned benchmark adapters public while third-party
benchmark repositories remain ignored local checkouts under
`artifacts/eval/harnesses/`.

It covers:

- `mcpmark`: upstream `eval-sys/mcpmark` pinned by commit, with a GEODE
  `BaseMCPAgent` adapter in `mcpmark_geode_agent.py`.
- `tau2-bench`: upstream `sierra-research/tau2-bench` pinned by commit, with
  the GEODE participant adapter in `tau2_geode_agent.py`.

Secrets are never stored here. Put real tokens in ignored `.mcp_env` files and
keep only placeholder variable names in `.env.example` / `.mcp_env.example`.

Common commands:

```bash
python -m plugins.benchmark_harness.cli list
python -m plugins.benchmark_harness.cli ensure mcpmark
python -m plugins.benchmark_harness.cli install mcpmark
python -m plugins.benchmark_harness.cli preflight mcpmark --env-file .mcp_env
python -m plugins.benchmark_harness.cli ensure tau2-bench
python -m plugins.benchmark_harness.cli healthcheck tau2-bench
```

`ensure`, `install`, and `healthcheck` print the reproducible shell commands
instead of executing them. This keeps the public plugin side-effect free; live
benchmark sessions can run the emitted commands explicitly.

For MCPMark, register the GEODE agent inside an upstream checkout before
running `pipeline.py`:

```python
from plugins.benchmark_harness.mcpmark_geode_agent import register_mcpmark_agent
from src.agents import AGENT_REGISTRY

register_mcpmark_agent(AGENT_REGISTRY)
```
