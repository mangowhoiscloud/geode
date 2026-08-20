"""geode_product.self_improving — GEODE self-improving loop umbrella package.

Consolidates the previously scattered self-improving-loop CODE under one
package (PR-SELF-IMPROVING-UMBRELLA, 2026-05-31):

* :mod:`geode_product.self_improving.loop` — the loop runtime (runner, mutator,
  policies, baseline_epoch, run_provenance, statistical_power, …; formerly
  ``geode_product.self_improving_loop``).
* :mod:`geode_product.self_improving.train` — the single-experiment audit runner
  (fitness aggregation + promote gate + baseline; formerly
  ``autoresearch/train.py``). Spawned per cycle via
  ``python -m geode_product.self_improving.train``.
* :mod:`geode_product.self_improving.campaign` — the committed campaign driver
  (formerly ``scripts/run_campaign.py``). CLI: ``python -m
  geode_product.self_improving.campaign``.
* :mod:`geode_product.self_improving.prepare` / :mod:`geode_product.self_improving.admire_means`
  / :mod:`geode_product.self_improving.bench_means` — the ground-truth preparation +
  positive-pressure / capability axis helpers (formerly ``autoresearch/*``).

petri (``geode_product.petri_audit``) owns the measurement layer (rubric + dim
scoring); this package owns the aggregation + selection layer (tier weights
+ fitness + auto-promote). PR-STATE-SOT-RUNTIME-SPLIT (2026-06-14) splits the
mutation-loop *DATA* into two roots: the TRACKED ledgers + policies are the
in-repo SoT at ``core.paths.AUTORESEARCH_STATE_DIR`` (``geode_product/self_improving/
state/``, retained as the compatibility data root), while the RUNTIME scratch (baseline.json,
run.log, per-run dirs) lives under ``core.paths.STATE_ROOT``
(``~/.geode/self-improving/``, env-overridable via ``GEODE_STATE_ROOT``). The
program SoT is ``geode_product/self_improving/program.md``. History: the tracked dir was
the interim repo-root ``state/autoresearch/`` — PR-STATE-AUTORESEARCH-RENAME
(2026-06-01) had renamed it from ``state/self_improving`` of #1955 to kill the
underscore/hyphen twin; the SOT-RUNTIME-SPLIT then folded it under the package.

``train`` lazy-imports ``loop`` submodules inside function bodies and
``loop.rollback_condition`` module-level-imports ``train.CRITICAL_DIMS``;
this ``__init__`` is deliberately side-effect-free so importing the package
never forces that mutually-coupled pair to load eagerly.

Reference: ``docs/self-improving/loop-overview.md`` +
``geode_product/self_improving/program.md`` +
``docs/self-improving/campaign-procedure.md``.
"""
