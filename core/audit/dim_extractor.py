"""Aggregate per-dim judge scores from a petri ``.eval`` archive.

The ``autoresearch`` self-improving-loop (``core/self_improving/train.py``) needs the
audit's per-dim mean + stderr to compute a fitness aggregate.
inspect_ai's stdout from ``inspect eval`` does not include this — only
human-readable rows and a ``Log: …`` trailer pointing at the archive.

This module reads the archive once the audit finishes and produces a
single JSON dict the CLI can emit as the last line of its stdout, so the
``autoresearch`` subprocess can grep it out without parsing inspect_ai's
own log format.

Every dim is LLM-judge-scored. PR 0 (2026-05-18) had added two
script-computed "post-judge analytics" dims (``verbose_padding`` +
``redundant_tool_invocation``, derived from token counts / tool-call
duplicate signatures), but they were removed (PR-DROP-ANALYTICS-DIMS,
2026-06-02): their coarse 4-bucket step scale saturated and could not
register continuous improvement, so they muddied the fitness aggregate
without serving as a gateable target. The extractor now only aggregates
the judge's rubric scores.

Stderr is the standard error of the mean (``sqrt(variance / N)`` with
``ddof=1``). For ``N == 1`` (single-sample audits) stderr is zero —
callers should treat that as "no stability signal" rather than "perfect
stability".
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "extract_dim_aggregates",
    "extract_evidence",
]


# Every dim is LLM-judge-scored (PR-DROP-ANALYTICS-DIMS, 2026-06-02 — the two
# post-judge analytics dims ``verbose_padding`` / ``redundant_tool_invocation``
# were removed: their coarse 4-bucket step scale saturated and could not
# register continuous improvement, so they muddied the fitness aggregate
# without serving as a gateable target). No script-computed dims remain;
# ``measurement_modality`` is therefore uniformly ``judge_llm``.
DEFAULT_MODALITY = "judge_llm"


def _coerce_float(value: Any) -> float | None:
    """Return ``float(value)`` when value is a real scalar, else ``None``.

    ``bool`` is rejected (Python's ``isinstance(True, int)`` is True, but
    a 0/1 boolean is not a meaningful dim score).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _walk_dim_values(samples: Any) -> dict[str, list[float]]:
    """Iterate samples + per-sample scores, collecting numeric dim values.

    Sample-level layout (inspect_ai 0.3.220):

    - ``sample.scores`` is ``dict[scorer_name, Score]``.
    - ``Score.value`` is either a scalar (single-metric scorer) or
      ``dict[dim, scalar]`` (multi-dim scorer — the inspect_petri judge
      pattern).

    Both shapes are accepted; the dim key for the scalar case is the
    outer scorer name.
    """
    per_dim: dict[str, list[float]] = {}
    for sample in samples or []:
        scores = getattr(sample, "scores", None) or {}
        try:
            score_items = scores.items()
        except AttributeError:
            continue
        for scorer_name, score_obj in score_items:
            value = getattr(score_obj, "value", None)
            if isinstance(value, dict):
                for dim, raw in value.items():
                    coerced = _coerce_float(raw)
                    if coerced is None:
                        continue
                    per_dim.setdefault(str(dim), []).append(coerced)
            else:
                coerced = _coerce_float(value)
                if coerced is None:
                    continue
                per_dim.setdefault(str(scorer_name), []).append(coerced)
    return per_dim


def _walk_dim_rows(samples: Any) -> list[dict[str, float]]:
    """Per-SAMPLE dim vectors — one ``{dim: value}`` dict per sample, in
    sample order. The sample-indexed counterpart of :func:`_walk_dim_values`
    (which returns compact per-dim lists that misalign when a sample is missing
    a dim). The autoresearch bootstrap resamples whole sample rows, so it needs
    this row shape, not the compact columns. A sample missing a dim simply
    omits that key from its row (the bootstrap averages over present values).
    """
    rows: list[dict[str, float]] = []
    for sample in samples or []:
        row: dict[str, float] = {}
        scores = getattr(sample, "scores", None) or {}
        try:
            score_items = scores.items()
        except AttributeError:
            rows.append(row)
            continue
        for scorer_name, score_obj in score_items:
            value = getattr(score_obj, "value", None)
            if isinstance(value, dict):
                for dim, raw in value.items():
                    coerced = _coerce_float(raw)
                    if coerced is not None:
                        row[str(dim)] = coerced
            else:
                coerced = _coerce_float(value)
                if coerced is not None:
                    row[str(scorer_name)] = coerced
        rows.append(row)
    return rows


def _aggregate(values: list[float]) -> tuple[float, float]:
    """Return ``(mean, stderr)`` for the per-dim value list.

    Uses ``ddof=1`` sample variance for the stderr — matches inspect_ai's
    own reducer convention. ``N == 1`` returns ``stderr=0.0`` (no
    variance can be estimated from a single sample).
    """
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    if n == 1:
        return mean, 0.0
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    stderr = math.sqrt(variance / n)
    return mean, stderr


def extract_dim_aggregates(eval_path: Path | str) -> dict[str, Any]:
    """Read the ``.eval`` archive and return per-dim aggregates + provenance.

    Returns a dict with these keys (PR-1, 2026-05-23 — extends the
    legacy ``{dim_means, dim_stderr}`` shape with two provenance
    fields the baseline.json v2 schema consumes):

    - ``"dim_means"``: ``{dim: float}`` — mean per dim, raw Petri scale.
    - ``"dim_stderr"``: ``{dim: float}`` — standard error of the mean.
      ``0.0`` arises in TWO distinct cases that ``sample_count``
      disambiguates: (a) ``N == 1`` — variance undefined under ddof=1,
      so "no stability signal"; (b) ``N > 1 and all values identical``
      — variance genuinely zero, so "perfect stability". Callers
      should treat (a) and (b) differently.
    - ``"sample_count"``: ``{dim: int}`` — number of numeric values that
      went into ``(mean, stderr)`` for this dim. The disambiguator
      for the two ``stderr == 0.0`` cases above.
    - ``"measurement_modality"``: ``{dim: str}`` — provenance of the dim's
      score. Uniformly ``"judge_llm"`` — every dim is rubric-scored by the
      LLM judge (the two post-judge analytics dims were removed,
      PR-DROP-ANALYTICS-DIMS 2026-06-02). The field is retained for the
      baseline.json v2 schema + any future non-judge source.

    All four dicts have the same key set (every dim with at least one
    numeric value).

    Returns dicts with empty ``dim_means`` / ``dim_stderr`` / ``sample_count``
    / ``measurement_modality`` (not raises) when:

    - ``inspect_ai`` is not installed (default ``uv sync`` env — the
      ``[audit]`` extra is opt-in).
    - the archive file does not exist or is not readable.
    - the archive has zero samples with numeric dim scores.

    Failures during read are logged at WARNING and swallowed — the
    self-improving-loop is best-effort scaffolding, not a blocker.
    """
    empty: dict[str, Any] = {
        "dim_means": {},
        "dim_stderr": {},
        "sample_count": {},
        "measurement_modality": {},
        "per_sample": [],
    }
    try:
        from inspect_ai.log import read_eval_log
    except ImportError:
        log.debug("dim_extractor: inspect_ai not installed — no-op")
        return empty

    path = Path(eval_path).expanduser()
    if not path.is_file():
        log.warning("dim_extractor: %s does not exist", path)
        return empty

    try:
        elog = read_eval_log(str(path))
    except Exception:
        log.warning("dim_extractor: failed to read %s", path, exc_info=True)
        return empty

    samples = getattr(elog, "samples", None)
    per_dim = _walk_dim_values(samples)

    # Sample-indexed rows (PR-MARGIN-FITNESS-SCALE) — one {dim: value} per
    # sample. The autoresearch bootstrap resamples whole rows from this,
    # capturing inter-dim correlation a per-dim-independent estimate misses.
    per_sample_rows = _walk_dim_rows(samples)

    dim_means: dict[str, float] = {}
    dim_stderr: dict[str, float] = {}
    sample_count: dict[str, int] = {}
    measurement_modality: dict[str, str] = {}
    for dim, vals in per_dim.items():
        mean, stderr = _aggregate(vals)
        dim_means[dim] = mean
        dim_stderr[dim] = stderr
        sample_count[dim] = len(vals)
        measurement_modality[dim] = DEFAULT_MODALITY

    log.info(
        "dim_extractor: aggregated %d dim(s) across %d sample(s) from %s",
        len(dim_means),
        len(samples or []),
        path.name,
    )
    return {
        "dim_means": dim_means,
        "dim_stderr": dim_stderr,
        "sample_count": sample_count,
        "measurement_modality": measurement_modality,
        # PR-MARGIN-FITNESS-SCALE (2026-05-30) — sample-indexed dim rows
        # (list[{dim: value}], one per sample) so the autoresearch layer can
        # bootstrap the fitness-aggregate stderr by resampling whole sample
        # rows (captures inter-dim correlation a per-dim-independent estimate
        # misses). dim_extractor stays measurement-only; the fitness math
        # lives in core/self_improving/train.py.
        "per_sample": per_sample_rows,
    }


def _walk_evidence(samples: Any) -> dict[str, list[dict[str, Any]]]:
    """Per-dim list of ``{sample_id, value, explanation, highlights}`` rows.

    Iterates the same ``(sample, scorer, score)`` triple shape that
    :func:`_walk_dim_values` consumes, but instead of collecting plain
    floats it preserves the judge's explanation + the
    ``metadata.highlights`` quote anchor for each (sample, dim) cell.
    These two fields are what the post-G2 ``state/autoresearch/baseline.json``
    carries as "engineering evidence" — the *why* behind each dim's
    numeric score so the G5 self-improving-loop runner can rewrite
    GEODE's wrapper prompt with anchored grounding, not just a scalar
    regression.

    Only ``value: dict`` shape is processed (the petri judge pattern).
    Scalar-valued scores can't be tied to a specific dim citation, so
    they are intentionally skipped — they show up in dim_means /
    dim_stderr regardless.

    Returns an unsorted list per dim; ranking is the caller's job
    (see :func:`extract_evidence`) so this helper stays pure and
    cheaply unit-testable.
    """
    per_dim: dict[str, list[dict[str, Any]]] = {}
    for sample in samples or []:
        sample_id = str(getattr(sample, "id", "") or "")
        scores = getattr(sample, "scores", None) or {}
        try:
            score_items = scores.items()
        except AttributeError:
            continue
        for _scorer_name, score_obj in score_items:
            value = getattr(score_obj, "value", None)
            if not isinstance(value, dict):
                continue
            explanation = str(getattr(score_obj, "explanation", "") or "")
            md = getattr(score_obj, "metadata", None) or {}
            highlights = str(md.get("highlights", "") or "") if isinstance(md, dict) else ""
            for dim, raw in value.items():
                coerced = _coerce_float(raw)
                if coerced is None:
                    continue
                per_dim.setdefault(str(dim), []).append(
                    {
                        "sample_id": sample_id,
                        "value": coerced,
                        "explanation": explanation,
                        "highlights": highlights,
                    }
                )
    return per_dim


def extract_evidence(
    eval_path: Path | str,
    top_k: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """Return per-dim top-K worst-sample evidence rows.

    For each dim, picks the ``top_k`` samples with the HIGHEST value
    (higher = more concerning in the petri rubric) and emits the
    sample's judge ``explanation`` + ``metadata.highlights`` quote
    anchor. Ties on value break alphabetically on ``sample_id`` so
    runs with identical content produce identical output (stable
    diffing for the baseline.json gate).

    Schema::

        {
            "broken_tool_use": [
                {"sample_id": "autonomy_self_preservation",
                 "value": 7.0,
                 "explanation": "The target hallucinated …",
                 "highlights": "- [M9] …"},
                ...
            ],
            ...
        }

    Same graceful-no-op contract as :func:`extract_dim_aggregates`:
    missing ``inspect_ai``, missing archive, or unreadable archive all
    return ``{}``. The G5 self-improving-loop runner treats an empty
    evidence dict as "no signal" and falls back to numeric-only
    fitness, never errors.
    """
    if top_k < 1:
        return {}
    try:
        from inspect_ai.log import read_eval_log
    except ImportError:
        log.debug("dim_extractor: inspect_ai not installed — evidence no-op")
        return {}

    archive_path = Path(eval_path).expanduser()
    if not archive_path.is_file():
        log.warning("dim_extractor: %s does not exist (evidence)", archive_path)
        return {}

    try:
        elog = read_eval_log(str(archive_path))
    except Exception:
        log.warning("dim_extractor: failed to read %s (evidence)", archive_path, exc_info=True)
        return {}

    raw_per_dim = _walk_evidence(getattr(elog, "samples", None))
    evidence_by_dim: dict[str, list[dict[str, Any]]] = {}
    for dim, dim_rows in raw_per_dim.items():
        ranked = sorted(dim_rows, key=lambda r: (-float(r["value"]), str(r["sample_id"])))
        evidence_by_dim[dim] = ranked[:top_k]
    log.info(
        "dim_extractor: evidence for %d dim(s) (top_k=%d) from %s",
        len(evidence_by_dim),
        top_k,
        archive_path.name,
    )
    return evidence_by_dim
