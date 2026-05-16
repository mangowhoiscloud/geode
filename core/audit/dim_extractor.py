"""Aggregate per-dim judge scores from a petri ``.eval`` archive.

The ``autoresearch`` outer-loop (``autoresearch/train.py``) needs the
audit's per-dim mean + stderr to compute a 5-axis fitness aggregate.
inspect_ai's stdout from ``inspect eval`` does not include this — only
human-readable rows and a ``Log: …`` trailer pointing at the archive.

This module reads the archive once the audit finishes and produces a
single JSON dict the CLI can emit as the last line of its stdout, so the
``autoresearch`` subprocess can grep it out without parsing inspect_ai's
own log format.

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

__all__ = ["extract_dim_aggregates"]


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


def extract_dim_aggregates(eval_path: Path | str) -> dict[str, dict[str, float]]:
    """Read the ``.eval`` archive and return per-dim mean + stderr.

    Returns ``{"dim_means": {dim: float, ...}, "dim_stderr": {dim:
    float, ...}}``. Both dicts have the same key set (every dim with at
    least one numeric value).

    Returns empty dicts (not raises) when:

    - ``inspect_ai`` is not installed (default ``uv sync`` env — the
      ``[audit]`` extra is opt-in).
    - the archive file does not exist or is not readable.
    - the archive has zero samples with numeric dim scores.

    Failures during read are logged at WARNING and swallowed — the
    outer-loop is best-effort scaffolding, not a blocker.
    """
    try:
        from inspect_ai.log import read_eval_log
    except ImportError:
        log.debug("dim_extractor: inspect_ai not installed — no-op")
        return {"dim_means": {}, "dim_stderr": {}}

    path = Path(eval_path).expanduser()
    if not path.is_file():
        log.warning("dim_extractor: %s does not exist", path)
        return {"dim_means": {}, "dim_stderr": {}}

    try:
        elog = read_eval_log(str(path))
    except Exception:
        log.warning("dim_extractor: failed to read %s", path, exc_info=True)
        return {"dim_means": {}, "dim_stderr": {}}

    samples = getattr(elog, "samples", None)
    per_dim = _walk_dim_values(samples)

    dim_means: dict[str, float] = {}
    dim_stderr: dict[str, float] = {}
    for dim, vals in per_dim.items():
        mean, stderr = _aggregate(vals)
        dim_means[dim] = mean
        dim_stderr[dim] = stderr

    log.info(
        "dim_extractor: aggregated %d dim(s) across %d sample(s) from %s",
        len(dim_means),
        len(samples or []),
        path.name,
    )
    return {"dim_means": dim_means, "dim_stderr": dim_stderr}
