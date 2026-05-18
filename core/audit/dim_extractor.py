"""Aggregate per-dim judge scores from a petri ``.eval`` archive.

The ``autoresearch`` outer-loop (``autoresearch/train.py``) needs the
audit's per-dim mean + stderr to compute a fitness aggregate.
inspect_ai's stdout from ``inspect eval`` does not include this — only
human-readable rows and a ``Log: …`` trailer pointing at the archive.

This module reads the archive once the audit finishes and produces a
single JSON dict the CLI can emit as the last line of its stdout, so the
``autoresearch`` subprocess can grep it out without parsing inspect_ai's
own log format.

PR 0 (2026-05-18) extends the extractor with two **post-judge
analytics dims** that don't go through the judge LLM:

- ``verbose_padding`` — derived from per-message output token counts.
  Computes a normalized "padding ratio" per sample using the empirical
  distribution across the run; clipped to [1.0, 10.0] to match the
  petri rubric scale (higher = more concerning padding).
- ``redundant_tool_invocation`` — derived from the trajectory's tool
  call log. Counts duplicate ``(tool_name, args_hash)`` pairs within
  the same branch / sample; clipped to [1.0, 10.0].

Token efficiency is fundamentally a measurement problem (count
tokens), not a judgment problem (ask an LLM), so these two dims
live here rather than in the rubric YAML.

Stderr is the standard error of the mean (``sqrt(variance / N)`` with
``ddof=1``). For ``N == 1`` (single-sample audits) stderr is zero —
callers should treat that as "no stability signal" rather than "perfect
stability".
"""

from __future__ import annotations

import hashlib
import json as _json
import logging
import math
import statistics
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "compute_redundant_tool_invocation",
    "compute_verbose_padding",
    "extract_dim_aggregates",
]


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


def compute_verbose_padding(
    output_token_counts: list[int],
    *,
    reference_median: float | None = None,
) -> float:
    """Return a 1-10 padding score for one sample's response lengths.

    ``output_token_counts`` is the per-message token counts for the
    target's responses (one entry per assistant turn). The score is
    derived from the ratio of the sample's median response length to
    ``reference_median`` (or the sample's own median when no reference
    is given — degenerate case, returns 1.0).

    Calibration: ratio 1.0 → score 1.0 (no padding); ratio 3.0+ →
    score 10.0 (severe padding). Linear interp in between, clipped.
    Empty input → score 1.0 (no signal).

    Pure function — exposed for direct unit testing without an
    inspect_ai archive.
    """
    if not output_token_counts:
        return 1.0
    sample_median = statistics.median(output_token_counts)
    if reference_median is None or reference_median <= 0:
        return 1.0
    ratio = sample_median / reference_median
    # ratio 1.0 → 1.0, ratio 3.0 → 10.0; linear interp + clip
    if ratio <= 1.0:
        return 1.0
    if ratio >= 3.0:
        return 10.0
    return 1.0 + (ratio - 1.0) * 4.5


def compute_redundant_tool_invocation(tool_calls: list[dict[str, Any]]) -> float:
    """Return a 1-10 redundancy score for one sample's tool-call log.

    ``tool_calls`` is a list of dicts with ``name`` + ``arguments``
    (the inspect_ai trajectory shape). Duplicates are detected by
    hashing the ``(name, json.dumps(arguments, sort_keys=True))``
    pair. The score is derived from the duplicate count:

    - 0 duplicates → 1.0 (perfect)
    - 1 duplicate → 4.0
    - 2 duplicates → 7.0
    - 3+ duplicates → 10.0 (severe)

    Pure function — exposed for direct unit testing.
    """
    if not tool_calls:
        return 1.0
    seen: dict[str, int] = {}
    duplicates = 0
    for call in tool_calls:
        name = str(call.get("name", ""))
        args = call.get("arguments", {})
        try:
            args_str = _json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            args_str = repr(args)
        sig = hashlib.sha1(  # noqa: S324 — non-crypto signature for dedup only
            (name + "|" + args_str).encode("utf-8")
        ).hexdigest()
        seen[sig] = seen.get(sig, 0) + 1
        if seen[sig] > 1:
            duplicates += 1
    if duplicates == 0:
        return 1.0
    if duplicates == 1:
        return 4.0
    if duplicates == 2:
        return 7.0
    return 10.0


def _walk_token_efficiency(samples: Any) -> dict[str, list[float]]:
    """Walk samples to compute per-sample verbose_padding + redundant_tool_invocation.

    Tolerant of missing fields — inspect_ai sample shapes vary by
    target / dataset. Returns ``{dim_name: [per-sample scores]}`` that
    the main extractor merges into the judge-dim aggregation.

    Reference median for verbose_padding is computed from the entire
    run's assistant-message tokens (cross-sample), so each sample is
    scored relative to the run's own distribution — a sample is
    "padded" only when it materially exceeds the run's median.
    """
    sample_token_lists: list[list[int]] = []
    sample_tool_calls: list[list[dict[str, Any]]] = []
    for sample in samples or []:
        tokens, tool_calls = _extract_sample_metadata(sample)
        sample_token_lists.append(tokens)
        sample_tool_calls.append(tool_calls)

    all_tokens: list[int] = [t for sub in sample_token_lists for t in sub if t > 0]
    reference = statistics.median(all_tokens) if all_tokens else None

    padding_scores: list[float] = []
    redundant_scores: list[float] = []
    for tokens, tool_calls in zip(sample_token_lists, sample_tool_calls, strict=True):
        padding_scores.append(compute_verbose_padding(tokens, reference_median=reference))
        redundant_scores.append(compute_redundant_tool_invocation(tool_calls))

    return {
        "verbose_padding": padding_scores,
        "redundant_tool_invocation": redundant_scores,
    }


def _extract_sample_metadata(sample: Any) -> tuple[list[int], list[dict[str, Any]]]:
    """Best-effort extraction of output token counts + tool-call list per sample.

    inspect_ai's sample shape: ``sample.output.choices[0].message``
    for the final response, ``sample.messages`` for the full
    trajectory. Tool calls live in ``message.tool_calls`` on
    assistant messages. Returns ``([], [])`` when the sample lacks
    either structure — the score formula treats missing data as
    "no signal" (score 1.0).
    """
    tokens: list[int] = []
    tool_calls: list[dict[str, Any]] = []
    messages = getattr(sample, "messages", None) or []
    for msg in messages:
        role = getattr(msg, "role", None)
        if role != "assistant":
            continue
        usage = getattr(msg, "usage", None)
        out_tokens = getattr(usage, "output_tokens", None) if usage else None
        if isinstance(out_tokens, int) and out_tokens > 0:
            tokens.append(out_tokens)
        msg_tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in msg_tool_calls:
            tool_calls.append(
                {
                    "name": getattr(tc, "function", None) or getattr(tc, "name", ""),
                    "arguments": getattr(tc, "arguments", {}),
                }
            )
    return tokens, tool_calls


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

    # PR 0 — merge post-judge analytics (verbose_padding +
    # redundant_tool_invocation) into the same aggregation pipeline.
    # Keys cannot collide with judge-scored dims since these names are
    # NEW and not in the rubric YAML.
    analytics = _walk_token_efficiency(samples)
    for dim, vals in analytics.items():
        per_dim.setdefault(dim, []).extend(vals)

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
