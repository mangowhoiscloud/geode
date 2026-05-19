"""autoresearch — GEODE self-improving loop driver.

Runs the wrapper-prompt mutation loop on top of petri's per-dim
baseline. petri owns the measurement layer (rubric + dim scoring);
this package owns the aggregation + selection layer (tier weights +
fitness + auto-promote). This ``__init__`` is deliberately empty —
the self-improving-loop agent never imports the package, it just
invokes ``uv run python autoresearch/train.py`` (the single-script
invocation idiom borrowed from Karpathy autoresearch, MIT 2026-03).

Reference: ``autoresearch/README.md`` + ``autoresearch/program.md``.
"""
