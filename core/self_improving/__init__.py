"""core.self_improving — GEODE self-improving loop umbrella package.

Consolidates the previously scattered self-improving-loop CODE under one
package (PR-SELF-IMPROVING-UMBRELLA, 2026-05-31):

* :mod:`core.self_improving.loop` — the loop runtime (runner, mutator,
  policies, baseline_epoch, run_provenance, statistical_power, …; formerly
  ``core.self_improving_loop``).
* :mod:`core.self_improving.train` — the single-experiment audit runner
  (fitness aggregation + promote gate + baseline; formerly
  ``autoresearch/train.py``). Spawned per cycle via
  ``python -m core.self_improving.train``.
* :mod:`core.self_improving.campaign` — the committed campaign driver
  (formerly ``scripts/run_campaign.py``). CLI: ``python -m
  core.self_improving.campaign``.
* :mod:`core.self_improving.prepare` / :mod:`core.self_improving.admire_means`
  / :mod:`core.self_improving.bench_means` — the ground-truth preparation +
  positive-pressure / capability axis helpers (formerly ``autoresearch/*``).

petri (``plugins.petri_audit``) owns the measurement layer (rubric + dim
scoring); this package owns the aggregation + selection layer (tier weights
+ fitness + auto-promote). The mutation-loop *DATA* lives under the single
canonical ``core.paths.AUTORESEARCH_STATE_DIR`` (``state/autoresearch/``
under ``STATE_ROOT``, env-overridable via ``GEODE_STATE_ROOT``); the program
SoT is ``core/self_improving/program.md``. The CODE package keeps the
``self_improving`` name; only the STATE dir is ``autoresearch`` (the engine's
name) — PR-STATE-AUTORESEARCH-RENAME (2026-06-01, Scheme A) renamed it from
``state/self_improving`` of #1955 to kill the underscore/hyphen twin with
``self-improving-loop/`` (now folded in as ``state/autoresearch/handoff/``).

``train`` lazy-imports ``loop`` submodules inside function bodies and
``loop.rollback_condition`` module-level-imports ``train.CRITICAL_DIMS``;
this ``__init__`` is deliberately side-effect-free so importing the package
never forces that mutually-coupled pair to load eagerly.

Reference: ``docs/self-improving/loop-overview.md`` +
``core/self_improving/program.md`` +
``docs/self-improving/campaign-procedure.md``.
"""
