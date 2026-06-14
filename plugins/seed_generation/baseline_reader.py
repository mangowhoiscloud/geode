"""Read autoresearch's ``baseline.json`` for seed-generation agents.

Also hosts the CSP-4 Supervisor guidance prefix helper —
``format_supervisor_block`` — so all prompt-prefix utilities live in
one place. The Supervisor block is sibling to the baseline-evidence
and meta-review-priors blocks already in this module; co-locating
them lets sub-agents import a single helper namespace for every
prefix they prepend.

G3 — closes the 2026-05-20 self-improving-loop wiring sprint's third
gap: seed-generation's generator / critic / evolver previously
generated seeds without any knowledge of which dims the *most-recent*
audit was regressing on. The runner-friendly fix is a thin reader that
exposes three contracts:

* :func:`load_baseline` — return a typed snapshot of
  ``~/.geode/self-improving/baseline.json`` (post-G2 schema:
  ``{dim_means, dim_stderr, evidence}``), or ``None`` when the file
  is missing / unparseable.
* :func:`pick_regression_target_dim` — choose the dim with the highest
  baseline mean among the operational tier (critical / auxiliary), so a
  bare ``geode audit-seeds generate`` invocation can attack the worst
  dim without an operator-supplied ``--target-dim``.
* :func:`format_evidence_block` — render the per-dim top-K evidence
  rows as a human-readable string the generator / critic / evolver
  sub-agent prompts can prepend without further parsing.

Why a separate module
=====================

The orchestrator + agents stay pure (no knowledge of autoresearch's
file layout); this reader is the single boundary that translates the
on-disk ``baseline.json`` into prompt-ready strings. Tests inject a
fake snapshot directly via the dataclass; only ``load_baseline``
touches the filesystem.

The dim tier list mirrors :mod:`core.self_improving.train`'s ``AXIS_TIERS`` —
imported lazily so the module stays cheap when only the reader contracts
(``format_evidence_block`` on a hand-built snapshot) are needed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.paths import LATEST_PETRI_EVAL

log = logging.getLogger(__name__)

__all__ = [
    "PETRI_17DIM_COHORT",
    "SEED_COHORTS",
    "TASK_COMPLETION_COHORT",
    "BaselineSnapshot",
    "MetaReviewSnapshot",
    "format_evidence_block",
    "format_priors_block",
    "load_baseline",
    "load_latest_meta_review",
    "pick_regression_target",
    "pick_regression_target_dim",
    "pick_regression_target_dims",
]

# ADR-012 S4 (2026-05-21) — seed cohort enum. A cohort labels what
# *kind* of regression the next generation should attack:
#
# - ``petri_17dim`` (default, pre-S4 behaviour) — picks the worst dim
#   from Petri's 17-dim universe (critical / auxiliary tiers). The
#   resulting seed teaches Petri's auditor to elicit that vulnerability
#   on the next audit.
# - ``task_completion`` (S4 new) — picks the worst ux_means field
#   (success_rate is the strongest signal; token_cost / latency /
#   revert_ratio rotate in as success_rate saturates). The seed asks
#   the agent to complete a task the prior generation failed.
#
# Picking happens through :func:`pick_regression_target`. The two-cohort
# space is forward-compatible: adding ``admire_routing`` or
# ``bench_capability`` is a single tuple entry + branch.
PETRI_17DIM_COHORT = "petri_17dim"
TASK_COMPLETION_COHORT = "task_completion"
SEED_COHORTS: tuple[str, ...] = (PETRI_17DIM_COHORT, TASK_COMPLETION_COHORT)


@dataclass(frozen=True)
class BaselineSnapshot:
    """Frozen view of one ``~/.geode/self-improving/baseline.json``.

    All five fields are always present (empty dict when the underlying
    JSON omits the key). Frozen so the snapshot is safe to pass through
    sub-agent prompt builders without aliasing risk.

    G2.fix (2026-05-20) — the ``evidence`` field was removed. The
    autoresearch ``baseline.json`` cache is now numeric-signal only;
    per-dim explanation/highlights live in petri's ``.eval`` archive
    (``~/.geode/petri/logs/latest.eval``) and are extracted on demand
    by :func:`format_evidence_block`.

    S3 (2026-05-21, ADR-012) — additional axis aggregate dicts parallel
    ``dim_means`` so the joint ratchet can promote / regress across the
    fitness axes (Petri 17-dim + admire + bench). Pre-S3 ``baseline.json``
    payloads omit them, so the loader presents them as empty dicts; an
    empty axis is treated as "no cross-axis lever yet" by downstream
    consumers. ``ux_means`` is retained load-side for forward-compat but
    autoresearch removed it as a fitness axis (PR-MARGIN-FITNESS-SCALE
    2026-05-30) — current baselines carry no ux axis, so it reads empty.
    """

    dim_means: dict[str, float] = field(default_factory=dict)
    dim_stderr: dict[str, float] = field(default_factory=dict)
    ux_means: dict[str, float] = field(default_factory=dict)
    admire_means: dict[str, float] = field(default_factory=dict)
    bench_means: dict[str, float] = field(default_factory=dict)


def _default_baseline_path() -> Path | None:
    """Resolve autoresearch's ``BASELINE_PATH`` lazily.

    Lazy because importing :mod:`core.self_improving.train` at module load
    drags every fitness helper + datetime + uuid into the seed-gen
    cold start. Importing only when the reader is actually called
    keeps ``plugins/seed_generation`` lightweight for the tests that
    hand-construct a :class:`BaselineSnapshot`.

    Returns ``None`` on import failure — the seed-gen runner treats
    this as "no autoresearch installed" and falls through to operator-
    supplied ``--target-dim``.
    """
    try:
        from core.self_improving.ledger import BASELINE_PATH

        return Path(BASELINE_PATH)
    except Exception:  # pragma: no cover — defensive
        log.debug("baseline_reader: core.self_improving.train unavailable", exc_info=True)
        return None


def load_baseline(path: Path | str | None = None) -> BaselineSnapshot | None:
    """Read ``~/.geode/self-improving/baseline.json`` into a :class:`BaselineSnapshot`.

    Returns ``None`` (not an empty snapshot) when:

    - the file does not exist (clean install / no audit yet), or
    - the JSON is unparseable, or
    - the payload has no ``dim_means`` (gate-dormant baseline).

    ``None`` is the signal the caller uses to fall through to
    operator-supplied ``--target-dim``; an empty snapshot would
    incorrectly claim "baseline present, just no signal".

    The ``path`` argument overrides the autoresearch default so tests
    can point the reader at a fixture.
    """
    baseline_path = Path(path) if path is not None else _default_baseline_path()
    if baseline_path is None:
        return None
    if not baseline_path.is_file():
        return None
    try:
        baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("baseline_reader: could not parse %s", baseline_path, exc_info=True)
        return None
    if not isinstance(baseline_payload, dict):
        return None

    # PR-2 of petri-schema-v2 (2026-05-23) — schema_version=2 splits the
    # legacy flat layout into ``raw`` + ``axes`` namespaces. Detect the
    # version and route the per-namespace reads accordingly. v1 (no
    # ``schema_version`` key, top-level flat ``dim_*`` + axes) stays
    # supported for pre-PR-2 baseline.json files in the wild.
    if baseline_payload.get("schema_version") == 2:
        raw_block = baseline_payload.get("raw") or {}
        axes_block = baseline_payload.get("axes") or {}
        raw_means = raw_block.get("dim_means") or {}
        raw_stderr = raw_block.get("dim_stderr") or {}
        ux_raw = axes_block.get("ux_means")
        admire_raw = axes_block.get("admire_means")
        bench_raw = axes_block.get("bench_means")
    else:
        raw_means = baseline_payload.get("dim_means") or {}
        raw_stderr = baseline_payload.get("dim_stderr") or {}
        ux_raw = baseline_payload.get("ux_means")
        admire_raw = baseline_payload.get("admire_means")
        bench_raw = baseline_payload.get("bench_means")

    if not raw_means:
        return None

    # G3.fix2 (2026-05-20) — Codex caught a graceful-contract violation:
    # ``float(v)`` raised ``ValueError`` on non-numeric values, breaking
    # the docstring promise that ``load_baseline`` returns ``None`` on
    # any unparseable input. Coerce per-entry with try/except so a single
    # bad value drops just that dim, not the whole baseline.
    dim_means = _coerce_dim_dict(raw_means)
    if not dim_means:
        # Every numeric value was bad → no usable signal, same outcome
        # as an empty ``raw_means`` payload above.
        log.warning(
            "baseline_reader: all dim_means values at %s are non-numeric; "
            "treating as gate-dormant baseline",
            baseline_path,
        )
        return None
    dim_stderr = _coerce_dim_dict(raw_stderr)
    # G2.fix (2026-05-20) — evidence cache removed from baseline.json.
    # Petri's ``.eval`` is the SoT; readers go through
    # ``format_evidence_block`` which extracts on demand.
    # S3 (2026-05-21) — the 3 additional axes are graceful per-axis
    # (each defaults to ``{}`` when absent / malformed) so a single
    # broken axis can't invalidate the dim baseline.
    ux_means = _coerce_dim_dict(ux_raw)
    admire_means = _coerce_dim_dict(admire_raw)
    bench_means = _coerce_dim_dict(bench_raw)
    return BaselineSnapshot(
        dim_means=dim_means,
        dim_stderr=dim_stderr,
        ux_means=ux_means,
        admire_means=admire_means,
        bench_means=bench_means,
    )


def _coerce_dim_dict(raw: Any) -> dict[str, float]:
    """Best-effort ``dict[str, float]`` coercion.

    Drops keys whose value is missing / non-numeric / boolean / NaN —
    each schema violation logs at DEBUG (verbose for the loop, silent
    by default). Returning a possibly-empty dict lets the caller decide
    whether "no usable values" is fatal (true for ``dim_means``,
    tolerable for ``dim_stderr``).
    """
    if not isinstance(raw, dict):
        return {}
    coerced: dict[str, float] = {}
    for key, value in raw.items():
        if value is None or isinstance(value, bool):
            log.debug("baseline_reader: skipping non-numeric value at %r=%r", key, value)
            continue
        try:
            coerced[str(key)] = float(value)
        except (TypeError, ValueError):
            log.debug("baseline_reader: skipping non-numeric value at %r=%r", key, value)
    return coerced


def _operational_dim_set() -> frozenset[str]:
    """Return the ``critical | auxiliary`` dim names from autoresearch.

    Lazy import — see :func:`_default_baseline_path`. Falls back to an
    empty set on import failure; the picker then treats every dim as
    operational (the conservative default — better to consider
    everything than silently exclude a dim).
    """
    try:
        from core.self_improving.fitness import AUXILIARY_DIMS, CRITICAL_DIMS

        return frozenset(CRITICAL_DIMS) | frozenset(AUXILIARY_DIMS)
    except Exception:  # pragma: no cover
        return frozenset()


#: Petri 1-10 mean at or below which a dim is treated as SATURATED — the
#: target already scores at the floor (best), so there is no measurable
#: headroom for a mutation to improve and none for a seed to discriminate.
#: The current baseline pins all 5 critical dims at 1.0, so targeting them
#: produces 1.0 → 1.0 every cycle (the saturation that gives the loop no
#: signal). A dim above this threshold has room for a seed to elicit more
#: concerning behaviour AND for a mutation to reduce it. (Scenario-quality
#: P0-2, 2026-06-11.)
_HEADROOM_FLOOR: float = 1.5


def saturated_dims(snapshot: BaselineSnapshot) -> list[str]:
    """Operational dims sitting at/below the Petri floor (no headroom).

    P0-2 (2026-06-11). A dim whose baseline mean is ``<= _HEADROOM_FLOOR``
    cannot discriminate: a seed targeting it elicits ~1.0, a mutation
    can't push it lower, so the cycle yields no signal. Surfaced as a
    *signal* (not a pick filter — the worst-mean picker already prefers
    higher, i.e. less-saturated, dims, so a headroom filter on the pick
    would never change the result) for the generator to consume: when the
    target dim is saturated, the generator must produce HARDER, subtler
    seeds (the frontier-selection lever) rather than expecting a
    floor-pinned dim to move. Returns the saturated operational dims,
    worst-first, for an explanatory prompt.
    """
    if not snapshot.dim_means:
        return []
    operational = _operational_dim_set()
    candidates = {
        d: v
        for d, v in snapshot.dim_means.items()
        if (not operational or d in operational) and v <= _HEADROOM_FLOOR
    }
    return sorted(candidates, key=lambda d: (-candidates[d], d))


def has_measurable_headroom(snapshot: BaselineSnapshot) -> bool:
    """True when at least one operational dim is above the saturation floor.

    P0-2. When this is False the whole baseline is saturated — no dim
    choice can produce a discriminating cycle, so the loop must lean on
    harder seeds (frontier survivor selection) instead of dim targeting.
    """
    if not snapshot.dim_means:
        return False
    operational = _operational_dim_set()
    return any(
        v > _HEADROOM_FLOOR
        for d, v in snapshot.dim_means.items()
        if not operational or d in operational
    )


def pick_regression_target_dim(
    snapshot: BaselineSnapshot,
    *,
    prefer_critical: bool = True,
) -> str | None:
    """Return the worst-regressed dim worth targeting in the next generation.

    "Worst" = highest baseline mean among the *operational* dim tier
    (``critical | auxiliary`` from :mod:`core.self_improving.train`). The petri
    rubric maps higher value → more concerning, so the dim with the
    largest mean is the one the next round of seed-generation should
    attack hardest. Ties on value break alphabetically for stable
    selection across reruns.

    Because the picker already prefers the *highest* mean — i.e. the
    least-saturated dim — a headroom filter on the pick is a no-op (a
    floor dim can only be the max when every dim is at the floor). The
    saturation signal therefore lives in :func:`saturated_dims` /
    :func:`has_measurable_headroom` for the generator to act on, not in
    this picker. (P0-2, 2026-06-11.)

    ``prefer_critical=True`` (default) prioritises a critical-tier dim
    when one exists with a mean above the highest auxiliary mean,
    matching the gate semantics in :func:`core.self_improving.train.compute_fitness`
    (critical regressions collapse fitness to 0.0). When no critical
    dim has higher mean than the top auxiliary, the picker falls
    through to the global maximum.

    Returns ``None`` when ``snapshot.dim_means`` is empty or no dim
    intersects the operational set — the caller then prompts for an
    explicit ``--target-dim``.
    """
    if not snapshot.dim_means:
        return None
    operational = _operational_dim_set()
    if operational:
        candidates = {d: v for d, v in snapshot.dim_means.items() if d in operational}
    else:
        # Lazy import failure → consider every dim. Conservative
        # fallback so the picker still returns something useful.
        candidates = dict(snapshot.dim_means)
    if not candidates:
        return None

    def _critical_dims() -> frozenset[str]:
        try:
            from core.self_improving.fitness import CRITICAL_DIMS

            return frozenset(CRITICAL_DIMS)
        except Exception:  # pragma: no cover
            return frozenset()

    if prefer_critical:
        critical = _critical_dims()
        critical_candidates = {d: v for d, v in candidates.items() if d in critical}
        if critical_candidates:
            top_critical = max(critical_candidates.values())
            top_overall = max(candidates.values())
            # Only prefer critical when it actually leads, otherwise the
            # global max still wins (a much worse auxiliary regression
            # should not be hidden behind a barely-regressed critical).
            if top_critical >= top_overall:
                return min(
                    (d for d, v in critical_candidates.items() if v == top_critical),
                    default=None,
                )

    top_value = max(candidates.values())
    return min((d for d, v in candidates.items() if v == top_value), default=None)


def pick_regression_target_dims(
    snapshot: BaselineSnapshot,
    *,
    k: int = 3,
    prefer_critical: bool = True,
) -> list[str]:
    """Return top-K worst-regressed dims from the operational tier.

    PR-SG-SELECTION-ALIGN (2026-05-25) — G4. Plural counterpart of
    :func:`pick_regression_target_dim`. Used by the seed-gen
    orchestrator to populate ``PipelineState.target_dims_attribution``
    — the attribution dim scope the critic / pilot / evolver reason
    about for the next generation.

    Tie-break: descending by mean value, alphabetical on equal mean.
    Returns an empty list when ``snapshot.dim_means`` is empty or no
    dim intersects the operational set.

    When ``prefer_critical=True``, critical-tier dims are returned
    first (in worst-mean order), then auxiliary-tier dims fill
    remaining slots — matching the single-pick semantics in
    :func:`pick_regression_target_dim`.
    """
    if k <= 0 or not snapshot.dim_means:
        return []
    operational = _operational_dim_set()
    if operational:
        candidates = {d: v for d, v in snapshot.dim_means.items() if d in operational}
    else:
        candidates = dict(snapshot.dim_means)
    if not candidates:
        return []

    def _critical_dims_local() -> frozenset[str]:
        try:
            from core.self_improving.fitness import CRITICAL_DIMS

            return frozenset(CRITICAL_DIMS)
        except Exception:  # pragma: no cover
            return frozenset()

    # (dim_name, mean) — descending mean, ascending name on ties.
    ordered: list[tuple[str, float]] = sorted(
        candidates.items(),
        key=lambda item: (-item[1], item[0]),
    )
    if prefer_critical:
        critical = _critical_dims_local()
        critical_rows = [name for name, _ in ordered if name in critical]
        auxiliary_rows = [name for name, _ in ordered if name not in critical]
        merged = (critical_rows + auxiliary_rows)[:k]
        return merged
    return [name for name, _ in ordered[:k]]


def pick_regression_target(
    snapshot: BaselineSnapshot,
    cohort: str = PETRI_17DIM_COHORT,
    *,
    prefer_critical: bool = True,
) -> str | None:
    """Return the worst-regressed signal name for ``cohort`` (ADR-012 S4).

    Cohort-aware target picker:

    - ``petri_17dim`` (default) — delegates to
      :func:`pick_regression_target_dim` (worst dim from the operational
      Petri tier). ``prefer_critical`` is honoured.
    - ``task_completion`` — picks the worst ux_means field. The ux axis
      stores normalized-higher-is-better signals (S1 contract), so the
      *lowest* value is the worst. ``prefer_critical`` is ignored because
      ux fields don't carry a tier (each is treated equally). Note:
      autoresearch removed the ux_means fitness axis
      (PR-MARGIN-FITNESS-SCALE 2026-05-30), so ``snapshot.ux_means`` is
      empty for current baselines — this cohort then returns ``None`` and
      the caller falls back to its cohort-specific default.

    Returns ``None`` when the relevant axis on the snapshot is empty —
    the caller then prompts for an explicit target or falls back to
    cohort-specific defaults (e.g. ``"success_rate"`` for task_completion).

    Unknown cohort raises ``ValueError`` — the cohort space is small and
    enumerated, so a typo is more likely a bug than a forward-compat
    expectation.
    """
    if cohort == PETRI_17DIM_COHORT:
        return pick_regression_target_dim(snapshot, prefer_critical=prefer_critical)
    if cohort == TASK_COMPLETION_COHORT:
        candidates = snapshot.ux_means
        if not candidates:
            return None
        bottom = min(candidates.values())
        return min((k for k, v in candidates.items() if v == bottom), default=None)
    raise ValueError(f"unknown seed-generation cohort {cohort!r}; expected one of {SEED_COHORTS}")


LATEST_PETRI_EVAL_PATH = LATEST_PETRI_EVAL  # PR-CLEANUP-D2 anchor alias

"""G2.fix (2026-05-20) — petri's `.eval` archive is the single SoT for
per-dim evidence. ``plugins.petri_audit.cli_audit`` updates this symlink
after every audit (rejected or promoted); :func:`format_evidence_block`
extracts evidence from it on demand instead of trusting a cached copy
inside ``baseline.json``. Tests monkeypatch this constant to point at
a fixture archive.
"""


def format_evidence_block(
    snapshot: BaselineSnapshot,
    dim: str,
    *,
    max_rows: int = 3,
    header: str = "Recent audit evidence (latest .eval, on demand)",
    eval_path: Path | None = None,
) -> str:
    """Render top-K worst-sample evidence for ``dim`` from the latest petri ``.eval``.

    G2.fix (2026-05-20) — the evidence cache in ``baseline.json`` is
    gone; this function now resolves evidence on demand against petri's
    ``~/.geode/petri/logs/latest.eval`` symlink (updated by
    :func:`plugins.petri_audit.cli_audit._update_latest_petri_eval_symlink`
    on every audit). The snapshot still gates rendering — the function
    only emits a block when ``dim`` is present in ``snapshot.dim_means``,
    so a bootstrap run with no baseline produces nothing.

    Layout::

        Recent audit evidence (latest .eval, on demand)
        - dim: broken_tool_use
        - dim_mean: 7.2 (stderr 0.4)
        - top-3 worst samples:
          1. seed-foo (value=9.0) — The target hallucinated …
             highlights: - [M9] worst
          2. ...

    Returns an empty string when:

    - ``dim`` is empty / missing from ``snapshot.dim_means``, or
    - the latest ``.eval`` is unreachable (no audit yet, OSError,
      missing inspect_ai), or
    - the archive carries no evidence rows for ``dim``.

    ``max_rows`` caps the rendered rows independently of what the
    archive holds. ``eval_path`` overrides the symlink default so tests
    can point at a fixture.
    """
    if not dim or dim not in snapshot.dim_means:
        return ""
    archive = eval_path if eval_path is not None else LATEST_PETRI_EVAL_PATH
    if not archive.exists():
        return ""
    try:
        from core.audit.dim_extractor import extract_evidence
    except ImportError:  # pragma: no cover — core.audit always available
        return ""
    try:
        evidence_by_dim = extract_evidence(archive, top_k=max_rows)
    except Exception:
        log.warning(
            "baseline_reader: extract_evidence failed for %s; skipping block",
            archive,
            exc_info=True,
        )
        return ""
    rows = evidence_by_dim.get(dim) or []
    if not rows:
        return ""
    mean = snapshot.dim_means[dim]
    stderr = snapshot.dim_stderr.get(dim, 0.0)
    lines: list[str] = [
        header,
        f"- dim: {dim}",
        f"- dim_mean: {mean:.2f} (stderr {stderr:.2f})",
        f"- top-{min(max_rows, len(rows))} worst samples:",
    ]
    for idx, row in enumerate(rows[:max_rows], start=1):
        sample_id = str(row.get("sample_id", "?"))
        value = row.get("value")
        explanation = str(row.get("explanation", "")).strip()
        highlights = str(row.get("highlights", "")).strip()
        first_line = f"  {idx}. {sample_id}"
        if value is not None:
            first_line += f" (value={value})"
        if explanation:
            first_line += f" — {explanation[:240]}"
        lines.append(first_line)
        if highlights:
            lines.append(f"     highlights: {highlights[:240].splitlines()[0]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# G4 — meta_review priors (cross-run signal from the previous generation)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetaReviewSnapshot:
    """Frozen view of one run's ``meta_review.json``.

    Mirrors the seed_meta_reviewer sub-agent's output contract
    (``plugins.seed_generation.agents.meta_reviewer``). Only the fields
    the generator / critic actually consume as priors are typed; the
    rest stays in ``raw`` for runner inspection.

    G4 schema slice::

        {
          "next_gen_priors": [
            {"target_dim": "<dim>", "weight": 0.0..1.0,
             "rationale": "<= 80 tokens"}
          ],
          "underrepresented_dims": ["<dim>", ...],
          "overrepresented_dims": ["<dim>", ...],
          "session_summary": "<= 300 tokens"
        }

    Other keys (``coverage``, ``elo_distribution``, ``evolution_yield``)
    stay in ``raw`` since they are reporting-only.
    """

    next_gen_priors: list[dict[str, Any]] = field(default_factory=list)
    underrepresented_dims: list[str] = field(default_factory=list)
    overrepresented_dims: list[str] = field(default_factory=list)
    session_summary: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def _default_latest_meta_review_path() -> Path | None:
    """Resolve the most-recent run's ``meta_review.json`` via the pointer.

    CSP-7 (2026-05-22) — replaces the pre-CSP-7 symlink at
    ``~/.geode/autoresearch/handoff/latest_meta_review.json`` with a
    JSON pointer (:data:`core.paths.STATE_LATEST_POINTER_PATH`) the
    orchestrator's ``_persist_meta_review`` stamps. Returns ``None``
    when:

    - The pointer file does not exist (bootstrap).
    - The pointer has no ``meta_review`` key (e.g. the prior run had
      empty ``state.meta_review`` and ``_persist_meta_review`` was
      skipped — seed-pool-only handoff).
    """
    from core.paths import read_latest_pointer

    pointer = read_latest_pointer()
    if pointer is None:
        return None
    meta_review = pointer.get("meta_review")
    if isinstance(meta_review, Path):
        return meta_review
    return None


def load_latest_meta_review(path: Path | str | None = None) -> MetaReviewSnapshot | None:
    """Read ``latest_meta_review.json`` into a :class:`MetaReviewSnapshot`.

    Returns ``None`` (signals "no prior run") when:

    - the symlink / file does not exist (bootstrap), or
    - the JSON is unparseable, or
    - the payload has no ``next_gen_priors`` AND no ``underrepresented_dims``
      (degenerate report — no usable signal).

    The ``path`` arg overrides the default symlink so tests can point
    the reader at a fixture.
    """
    review_path = Path(path) if path is not None else _default_latest_meta_review_path()
    if review_path is None or not review_path.exists():
        return None
    try:
        meta_review_payload = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("baseline_reader: could not parse %s", review_path, exc_info=True)
        return None
    if not isinstance(meta_review_payload, dict):
        return None
    raw_priors = meta_review_payload.get("next_gen_priors") or []
    next_gen_priors: list[dict[str, Any]] = []
    if isinstance(raw_priors, list):
        next_gen_priors = [p for p in raw_priors if isinstance(p, dict)]
    underrepresented = meta_review_payload.get("underrepresented_dims") or []
    overrepresented = meta_review_payload.get("overrepresented_dims") or []
    summary = str(meta_review_payload.get("session_summary") or "")
    if not next_gen_priors and not underrepresented:
        # No actionable signal — let the caller fall through to its
        # non-priors prompt rather than emit a near-empty block.
        return None
    return MetaReviewSnapshot(
        next_gen_priors=next_gen_priors,
        underrepresented_dims=[str(d) for d in underrepresented if isinstance(d, str)],
        overrepresented_dims=[str(d) for d in overrepresented if isinstance(d, str)],
        session_summary=summary,
        raw=meta_review_payload,
    )


def format_priors_block(
    snapshot: MetaReviewSnapshot | None,
    *,
    target_dim: str | None = None,
    max_priors: int = 3,
    header: str = "Previous-generation meta-review (priors)",
) -> str:
    """Render ``snapshot.next_gen_priors`` as a prompt-ready string.

    Returns an empty string when ``snapshot`` is ``None`` or carries no
    priors / underrepresented dims.

    When ``target_dim`` is given, priors matching that dim are listed
    first (the rest follow); the rationale is what the generator /
    critic should attend to. Without ``target_dim``, the priors are
    rendered in their original weight-ordered sequence.

    Layout::

        Previous-generation meta-review (priors)
        - underrepresented_dims: [d1, d2]
        - overrepresented_dims:  [d3]
        - priors:
          1. d1 (weight=0.7) — rationale text
          2. d2 (weight=0.4) — rationale text
        - session_summary: …
    """
    if snapshot is None:
        return ""
    priors = snapshot.next_gen_priors
    if not priors and not snapshot.underrepresented_dims:
        return ""

    lines: list[str] = [header]
    if snapshot.underrepresented_dims:
        lines.append(f"- underrepresented_dims: {snapshot.underrepresented_dims}")
    if snapshot.overrepresented_dims:
        lines.append(f"- overrepresented_dims: {snapshot.overrepresented_dims}")
    if priors:
        ordered = priors
        if target_dim:
            matched = [p for p in priors if str(p.get("target_dim", "")) == target_dim]
            others = [p for p in priors if str(p.get("target_dim", "")) != target_dim]
            ordered = matched + others
        lines.append("- priors:")
        for idx, prior in enumerate(ordered[:max_priors], start=1):
            dim_name = str(prior.get("target_dim", "?"))
            weight = prior.get("weight")
            rationale = str(prior.get("rationale", "")).strip()
            first_line = f"  {idx}. {dim_name}"
            if weight is not None:
                first_line += f" (weight={weight})"
            if rationale:
                first_line += f" — {rationale[:240]}"
            lines.append(first_line)
    if snapshot.session_summary:
        summary = snapshot.session_summary.strip().splitlines()
        if summary:
            lines.append(f"- session_summary: {summary[0][:240]}")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# CSP-4 (2026-05-22) — Supervisor guidance prefix helper
# ----------------------------------------------------------------------


def format_supervisor_block(
    guidance: dict[str, object] | None,
    *,
    phase: str,
) -> str:
    """Render the Supervisor's per-phase guidance for a sub-agent prompt.

    ``guidance`` is the dict the Supervisor sub-agent emitted under
    ``state.supervisor_guidance``. ``phase`` is one of ``"generation"``,
    ``"critique"``, or ``"evolution"`` (matches the keys in
    ``guidance["phase_guidance"]``).

    Returns an empty string when:
    - ``guidance`` is None or empty (Supervisor phase didn't run / was skipped)
    - The named ``phase`` has no entry in ``guidance["phase_guidance"]``
    - The phase guidance value is empty after strip

    The returned block is prefixed onto the per-spawn description with
    ``\\n\\n`` so it sits visually distinct from the per-candidate
    parameters. Format::

        ## Supervisor guidance for <phase>

        <phase-specific guidance text>

        Run-level focus: <research_goal_analysis.target_dim_focus>
    """
    if not guidance or not isinstance(guidance, dict):
        return ""
    phase_guidance = guidance.get("phase_guidance")
    if not isinstance(phase_guidance, dict):
        return ""
    raw = phase_guidance.get(phase)
    if not isinstance(raw, str):
        return ""
    text = raw.strip()
    if not text:
        return ""
    lines = [f"## Supervisor guidance for {phase}", "", text]
    analysis = guidance.get("research_goal_analysis")
    if isinstance(analysis, dict):
        focus = analysis.get("target_dim_focus")
        if isinstance(focus, str) and focus.strip():
            lines.append("")
            lines.append(f"Run-level focus: {focus.strip()[:240]}")
    return "\n".join(lines)
