"""GEODE autoresearch — outer-loop self-improvement orchestrator.

Top-level package for the meta-loop that mutates GEODE's wrapper prompt
surface, runs the Petri × GEODE audit harness as inner-loop fitness
oracle, and ratchets promotions via git commit / reject via
``git reset --hard``.

Karpathy autoresearch (2026-03, 26K+ stars) reference pattern, mapped to
GEODE's runtime:

- ``prepare.py`` (harness, frozen)   → ``plugins/petri_audit/``
- ``train.py``   (~630 LOC, mutable) → ``core/agent/system_prompt.py`` + skills + loop prompts
- ``program.md`` (human direction)   → ``autoresearch/program.md``
- ``results.tsv``                    → ``autoresearch/state/results.tsv``

The package is **top-level** rather than a ``plugins/`` member so that
mutation-of-self and lifecycle conflicts are avoided — the outer loop
invokes ``geode audit`` as a subprocess, never via in-process import.

Full spec: ``docs/architecture/autoresearch.md``.
"""

from __future__ import annotations

__version__ = "0.0.1"

__all__ = ["__version__"]
