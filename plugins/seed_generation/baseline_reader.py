"""Read autoresearch's ``baseline.json`` for seed-generation agents.

G3 — closes the 2026-05-20 self-improving-loop wiring sprint's third
gap: seed-generation's generator / critic / evolver previously
generated seeds without any knowledge of which dims the *most-recent*
audit was regressing on. The runner-friendly fix is a thin reader that
exposes three contracts:

* :func:`load_baseline` — return a typed snapshot of
  ``autoresearch/state/baseline.json`` (post-G2 schema:
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

The dim tier list mirrors :mod:`autoresearch.train`'s ``AXIS_TIERS`` —
imported lazily so the module stays cheap when only the reader contracts
(``format_evidence_block`` on a hand-built snapshot) are needed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "BaselineSnapshot",
    "MetaReviewSnapshot",
    "format_evidence_block",
    "format_priors_block",
    "load_baseline",
    "load_latest_meta_review",
    "pick_regression_target_dim",
]


@dataclass(frozen=True)
class BaselineSnapshot:
    """Frozen view of one ``autoresearch/state/baseline.json``.

    All three fields are always present (empty dict / list when the
    underlying JSON omits the key). Frozen so the snapshot is safe to
    pass through sub-agent prompt builders without aliasing risk.
    """

    dim_means: dict[str, float] = field(default_factory=dict)
    dim_stderr: dict[str, float] = field(default_factory=dict)
    evidence: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _default_baseline_path() -> Path | None:
    """Resolve autoresearch's ``BASELINE_PATH`` lazily.

    Lazy because importing :mod:`autoresearch.train` at module load
    drags every fitness helper + datetime + uuid into the seed-gen
    cold start. Importing only when the reader is actually called
    keeps ``plugins/seed_generation`` lightweight for the tests that
    hand-construct a :class:`BaselineSnapshot`.

    Returns ``None`` on import failure — the seed-gen runner treats
    this as "no autoresearch installed" and falls through to operator-
    supplied ``--target-dim``.
    """
    try:
        from autoresearch.train import BASELINE_PATH

        return Path(BASELINE_PATH)
    except Exception:  # pragma: no cover — defensive
        log.debug("baseline_reader: autoresearch.train unavailable", exc_info=True)
        return None


def load_baseline(path: Path | str | None = None) -> BaselineSnapshot | None:
    """Read ``autoresearch/state/baseline.json`` into a :class:`BaselineSnapshot`.

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
    raw_means = baseline_payload.get("dim_means") or {}
    if not raw_means:
        return None
    raw_stderr = baseline_payload.get("dim_stderr") or {}
    raw_evidence = baseline_payload.get("evidence") or {}

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
    evidence: dict[str, list[dict[str, Any]]] = {}
    if isinstance(raw_evidence, dict):
        for dim, dim_rows in raw_evidence.items():
            if not isinstance(dim_rows, list):
                continue
            evidence[str(dim)] = [r for r in dim_rows if isinstance(r, dict)]
    return BaselineSnapshot(dim_means=dim_means, dim_stderr=dim_stderr, evidence=evidence)


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
        from autoresearch.train import AUXILIARY_DIMS, CRITICAL_DIMS

        return frozenset(CRITICAL_DIMS) | frozenset(AUXILIARY_DIMS)
    except Exception:  # pragma: no cover
        return frozenset()


def pick_regression_target_dim(
    snapshot: BaselineSnapshot,
    *,
    prefer_critical: bool = True,
) -> str | None:
    """Return the worst-regressed dim worth targeting in the next generation.

    "Worst" = highest baseline mean among the *operational* dim tier
    (``critical | auxiliary`` from :mod:`autoresearch.train`). The petri
    rubric maps higher value → more concerning, so the dim with the
    largest mean is the one the next round of seed-generation should
    attack hardest. Ties on value break alphabetically for stable
    selection across reruns.

    ``prefer_critical=True`` (default) prioritises a critical-tier dim
    when one exists with a mean above the highest auxiliary mean,
    matching the gate semantics in :func:`autoresearch.train.compute_fitness`
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
            from autoresearch.train import CRITICAL_DIMS

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


def format_evidence_block(
    snapshot: BaselineSnapshot,
    dim: str,
    *,
    max_rows: int = 3,
    header: str = "Recent audit baseline (regression evidence)",
) -> str:
    """Render ``snapshot.evidence[dim]`` as a prompt-ready string.

    Layout::

        Recent audit baseline (regression evidence)
        - dim: broken_tool_use
        - dim_mean: 7.2 (stderr 0.4)
        - top-3 worst samples:
          1. seed-foo (value=9.0) — The target hallucinated …
             highlights: - [M9] worst
          2. ...

    Returns an empty string when:

    - ``dim`` is empty / missing from ``snapshot.dim_means``, or
    - ``snapshot.evidence[dim]`` is empty / absent (legacy baseline
      with no G2 evidence rows), in which case the caller's prompt
      falls through to its existing non-baseline message.

    ``max_rows`` caps the rendered rows independently of how many the
    snapshot carries — the runner can tighten this for token-bounded
    prompts.
    """
    if not dim or dim not in snapshot.dim_means:
        return ""
    rows = snapshot.evidence.get(dim) or []
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


def _default_latest_meta_review_path() -> Path:
    """``~/.geode/self-improving-loop/latest_meta_review.json`` symlink.

    The orchestrator's ``_persist_meta_review`` stamps this on every
    run; the reader treats a missing / dead symlink as "bootstrap"
    (no priors).
    """
    return Path.home() / ".geode" / "self-improving-loop" / "latest_meta_review.json"


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
    if not review_path.exists():
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
