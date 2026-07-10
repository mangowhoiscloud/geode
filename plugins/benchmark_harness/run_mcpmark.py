"""Run the upstream MCPMark pipeline with the GEODE agent registered.

The upstream ``pipeline.py`` builds its ``--agent`` argparse choices from
``src.agents.AGENT_REGISTRY`` inside ``main()``. Registering the GEODE agent
before calling ``main()`` is therefore sufficient; no upstream file is patched.

Usage (from the MCPMark checkout root, its venv active or via .venv/bin/python):

    .venv/bin/python -m plugins.benchmark_harness.run_mcpmark \
        --mcp notion --task-suite standard \
        --models geode-gpt-5.5 --agent geode --reasoning-effort xhigh \
        --k 1 --timeout 1200 --exp-name <run-id> --output-dir ./results-geode-agentworld
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    mcpmark_root = os.environ.get("MCPMARK_ROOT", os.getcwd())
    if mcpmark_root not in sys.path:
        sys.path.insert(0, mcpmark_root)

    from src.agents import AGENT_REGISTRY

    from plugins.benchmark_harness.mcpmark_geode_agent import register_mcpmark_agent

    register_mcpmark_agent(AGENT_REGISTRY)

    import pipeline

    pipeline.main()


if __name__ == "__main__":
    main()
