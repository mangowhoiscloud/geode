"""Self-improving loop runner — program.md-driven wrapper-prompt mutation.

PR-G5b (2026-05-20) — closes the final gap in the 2026-05-20
self-improving-loop wiring sprint. Composes the upstream PRs:

* PR-G1: ``latest_seed_pool`` symlink → autoresearch picks freshest pool.
* PR-G2: Petri evidence in ``baseline.json`` → top-K per dim.
* PR-G3: seed-gen reads ``baseline.json`` evidence + auto target dim.
* PR-G4: ``next_gen_priors`` persist + next-run reader.
* PR-G5a: wrapper sections file SoT + env-less daily-run fallback.

PR-G5b ties the loop closed: the runner reads the most-recent audit's
baseline + evidence + meta-review priors, asks an LLM to propose a
single-section ``WRAPPER_PROMPT_SECTIONS`` mutation, applies it to the
SoT, appends the mutation to a git-tracked audit log, and (optionally)
re-runs autoresearch so the next baseline reflects the change.

Public API:

* :class:`SelfImprovingLoopRunner` — top-level orchestrator.
* :func:`build_runner_context` — gather baseline + evidence + priors.
* :func:`apply_mutation` — write the SoT after schema validation.

The LLM call is injected as a callable so tests can supply a mock
without touching real provider quota. The default callable reads
``[self_improving_loop.mutator]`` from ``~/.geode/config.toml``
(:class:`core.config.self_improving.MutatorConfig`) and
dispatches through ``core.llm.router.call_with_failover`` so the
mutator shares the same credential rotator + retry path the rest of
GEODE's agentic callers use; see :func:`_default_llm_call` for the
binding.
"""

from __future__ import annotations

from core.self_improving.loop.mutate.runner import (
    Mutation,
    RunnerContext,
    SelfImprovingLoopRunner,
    apply_mutation,
    build_runner_context,
)

__all__ = [
    "Mutation",
    "RunnerContext",
    "SelfImprovingLoopRunner",
    "apply_mutation",
    "build_runner_context",
]
