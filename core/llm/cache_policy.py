"""Cache breakpoint policy SoT reader — ADR-013 T5, JSON mutation surface.

Mutator picks how many trailing-message ``cache_control`` breakpoints to
apply on Anthropic API calls (the ``n_breakpoints`` argument to
:func:`core.llm.providers.anthropic.apply_messages_cache_control`).

**Trade-off**:

- Higher ``n_breakpoints`` (up to 3) — more turns of the rolling history
  window are cached → higher cache-hit rate on long multi-turn loops.
  But each breakpoint carries a ``$0.10/MTok`` overhead on the cached
  block whether the call hits or misses the cache.
- Lower (0-1) — fewer breakpoints, lower per-call overhead, lower cache
  hit rate. Right choice for short tasks where the history doesn't
  amortize the overhead.

Cache hits reduce per-call cost and latency. This used to target the
``ux_means`` fitness axis (``token_cost_norm`` + ``latency_norm``); that
axis was removed in PR-MARGIN-FITNESS-SCALE (2026-05-30) — fitness is now
pure Petri dim aggregate, so this remains a cost/latency knob with no
dedicated fitness lever.

**SoT schema** (모든 field optional):

.. code-block:: json

    {
      "messages_breakpoints": 3        // 0 <= int <= 3 (Anthropic cap)
    }

빈 정책 / 누락 / out-of-range 값 → no-op (default 3 유지).

Candidate paths are supplied by product composition. Selection is explicit
override → operator-local → packaged default → no-op; an explicit override is
authoritative and may request strict loading.

**Frontier**: Anthropic prompt caching docs — ``cache_control`` count is
the canonical knob the user tunes; Anthropic recommends putting it on
*stable prefix* + *recent turns* and letting the workload guide which
turns deserve the breakpoint budget.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.config.policy_source import PolicySourcePaths, load_policy_source

log = logging.getLogger(__name__)

_FIELD_MESSAGES_BREAKPOINTS = "messages_breakpoints"

# Anthropic의 4-breakpoint hard cap minus 1 for the system block — agentic
# adapter spends 1-2 on the static system prefix (STATIC + DYNAMIC split).
_MAX_BREAKPOINTS = 3
_MIN_BREAKPOINTS = 0


def _load_cache_policy_override(
    *,
    sources: PolicySourcePaths | None = None,
) -> dict[str, int] | None:
    """Return the active cache-policy dict, or ``None`` if no SoT applies.

    Uses the shared neutral loader while this module retains schema validation
    and coercion."""
    return load_policy_source(
        sources=sources,
        label="cache-policy",
        validate_strict=_validate_schema,
        validate_graceful=_validate_schema,
        coerce=_coerce,
    )


def _validate_schema(data: Any, path: Path) -> None:
    """Top-level shape: ``dict``. ``messages_breakpoints`` must be int.

    Range validation 은 `_coerce` 에서 per-axis graceful drop — 다른
    field 가 추가되더라도 forward-compat."""
    if not isinstance(data, dict):
        raise RuntimeError(f"cache-policy at {path} must be a dict")
    if _FIELD_MESSAGES_BREAKPOINTS in data:
        value = data[_FIELD_MESSAGES_BREAKPOINTS]
        if not isinstance(value, int) or isinstance(value, bool):
            type_name = type(value).__name__
            raise RuntimeError(
                f"cache-policy at {path}[{_FIELD_MESSAGES_BREAKPOINTS!r}] "
                f"must be int (not {type_name})"
            )


def _coerce(data: dict[str, Any]) -> dict[str, int]:
    """Extract known fields + range-check. Out-of-range 값 은 graceful drop."""
    result: dict[str, int] = {}
    if _FIELD_MESSAGES_BREAKPOINTS in data:
        value = data[_FIELD_MESSAGES_BREAKPOINTS]
        if isinstance(value, int) and not isinstance(value, bool):
            if _MIN_BREAKPOINTS <= value <= _MAX_BREAKPOINTS:
                result[_FIELD_MESSAGES_BREAKPOINTS] = value
            else:
                log.warning(
                    "cache-policy field %r out of range (%d <= n <= %d), got %d; dropping",
                    _FIELD_MESSAGES_BREAKPOINTS,
                    _MIN_BREAKPOINTS,
                    _MAX_BREAKPOINTS,
                    value,
                )
    return result


def apply_cache_policy_breakpoints(
    default_n: int,
    policy: dict[str, int] | None,
) -> int:
    """Return effective ``n_breakpoints`` from ``policy``, else ``default_n``.

    Policy field absence → ``default_n`` (no behavior change). The reader's
    range validation guarantees the returned value is in
    ``[_MIN_BREAKPOINTS, _MAX_BREAKPOINTS]`` whenever it comes from policy.
    """
    if policy is None:
        return default_n
    return policy.get(_FIELD_MESSAGES_BREAKPOINTS, default_n)


__all__ = ["apply_cache_policy_breakpoints"]
