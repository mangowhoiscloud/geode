"""Deterministic per-job jitter (claude-code pattern) — thundering-herd prevention."""

from __future__ import annotations

import hashlib

from core.scheduler.scheduler.models import DEFAULT_JITTER_FRACTION, DEFAULT_MAX_JITTER_MS


def _compute_jitter_frac(job_id: str) -> float:
    """Compute a deterministic jitter fraction [0, 1) from job_id.

    Uses SHA-256 to produce a stable, uniformly distributed value.
    Same job_id always produces the same jitter across restarts.
    """
    h = hashlib.sha256(job_id.encode()).digest()
    # Use first 4 bytes as uint32 → normalize to [0, 1)
    val = int.from_bytes(h[:4], "big")
    return val / (2**32)


def _jittered_next_run(
    next_ms: float,
    interval_ms: float,
    job_id: str,
    *,
    max_jitter_ms: float = DEFAULT_MAX_JITTER_MS,
    jitter_fraction: float = DEFAULT_JITTER_FRACTION,
) -> float:
    """Apply deterministic forward jitter to a recurring job's next-run time.

    Jitter = min(frac * interval * jitter_fraction, max_jitter_ms).
    This spreads jobs with the same cron across a window instead of all
    firing at :00.
    """
    frac = _compute_jitter_frac(job_id)
    jitter = min(frac * interval_ms * jitter_fraction, max_jitter_ms)
    return next_ms + jitter
