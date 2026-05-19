"""autoresearch — Petri-signal fork of Karpathy/autoresearch (MIT, 2026-03).

A GEODE-side port of Karpathy's 3-file pattern (``prepare.py`` /
``train.py`` / ``program.md``) into the alignment-audit domain.
The original ML pre-train + ``val_bpb`` slot is replaced by a Petri
seed pool + AlphaEval tiered fitness. This ``__init__`` is
deliberately empty — the self-improving-loop agent never imports the package,
it just invokes ``uv run python autoresearch/train.py`` in keeping
with the upstream's single-script constraint.

Reference: ``autoresearch/README.md`` + ``autoresearch/program.md``.
"""
