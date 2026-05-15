"""Outer-loop runner — CLI entry-point ``geode-research``.

Karpathy autoresearch 의 main loop pattern 의 GEODE 적용:

```
LOOP until termination:
    1. hypothesis = generate_candidates(state, n=1)
    2. ratchet.apply(hypothesis)                  # mutation + quality gate
    3. subprocess(uv run geode audit ...)         # inner-loop harness
    4. fitness = compute(latest_archive)
    5. verdict = ratchet.verdict(fitness, baseline)
    6. ratchet.commit_or_reset(verdict, ...)
    7. baseline_marker.mark(...) if promote
    8. results.tsv.append(generation, hypothesis, fitness, verdict)
```

Full spec: ``docs/architecture/autoresearch.md`` § 4 (동작 프로세스).

Implementation: follow-up PR1 (loop + hypothesis + fitness + ratchet).
"""

from __future__ import annotations

import typer

app = typer.Typer(help="GEODE autoresearch — outer-loop self-improvement runner.")


@app.command()
def init() -> None:
    """Initialize ``autoresearch/state/`` and load ``program.md``.

    Creates:
    - ``autoresearch/state/results.tsv`` with header schema
    - ``autoresearch/state/current_generation.json`` (generation 0 baseline)
    - ``autoresearch/state/audit_logs/`` (per-generation subprocess stdout)
    - ``autoresearch/state/failure_log.jsonl`` (rejected hypothesis trace)
    """
    raise NotImplementedError("autoresearch/loop.py:init — follow-up PR1")


@app.command()
def step(program: str = "autoresearch/program.md") -> None:
    """Run a single generation cycle (1 hypothesis, 1 audit, 1 verdict).

    Implements steps 1-8 of the lifecycle. Useful for debugging — invoke
    once per hypothesis instead of the full ``loop`` command.
    """
    raise NotImplementedError("autoresearch/loop.py:step — follow-up PR1")


@app.command()
def loop(
    program: str = "autoresearch/program.md",
    max_gen: int = 50,
    rejection_threshold: int = 5,
) -> None:
    """Run continuous outer loop until termination.

    Termination conditions (per ``program.md``):
    - ``max_gen`` generation 도달
    - ``rejection_threshold`` consecutive rejection (default 5)
    - fitness monotonic ratchet 위반 (regression post-promote)
    """
    raise NotImplementedError("autoresearch/loop.py:loop — follow-up PR1")


def cli() -> None:
    """Entry-point for ``geode-research`` console script."""
    app()


if __name__ == "__main__":
    cli()
