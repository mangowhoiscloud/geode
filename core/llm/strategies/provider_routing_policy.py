"""Provider routing SoT reader — ADR-013 T4, JSON mutation surface.

Mutator picks the **preferred plan-chain** for each model (plan_id ordered
list). `resolve_routing(model)` consults this override before falling back
to the user-set `PlanRegistry.set_routing(model, ...)` chain. Choosing a
cheaper plan (PAYG vs SUBSCRIPTION) for the same model reduces per-call
cost without changing behavior. This used to target the ``ux_means``
fitness axis (``token_cost_norm``); that axis was removed in
PR-MARGIN-FITNESS-SCALE (2026-05-30) — fitness is now pure Petri dim
aggregate, so this remains a cost knob with no dedicated fitness lever.

**SoT schema** (모든 entry optional):

.. code-block:: json

    {
      "claude-opus-4-7": ["plan-anthropic-paid", "plan-anthropic-free"],
      "gpt-5": ["plan-openai-tier4"]
    }

빈 entry / 누락 model / 부적합 schema → no-op (registry's set_routing
chain 그대로 사용). Unknown plan_id 는 정책에 있어도 `resolve_routing`
이 등록된 plan 만 시도하므로 silently ignored.

Candidate paths are supplied by product composition. Selection is explicit
override → operator-local → packaged default → no-op; an explicit override is
authoritative and may request strict loading.

**Frontier**: OpenRouter's explicit per-model plan ordering — same model,
different providers, different prices. Anthropic / OpenAI both surface
multiple credential tiers (subscription / PAYG / batch); routing across
them is a measurable cost lever.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.config.policy_source import PolicySourcePaths, load_policy_source


def _load_provider_routing_override(
    *,
    sources: PolicySourcePaths | None = None,
) -> dict[str, list[str]] | None:
    """Return the active provider-routing dict, or ``None`` if no SoT applies.

    Uses the shared neutral loader while this module retains schema validation
    and coercion."""
    return load_policy_source(
        sources=sources,
        label="provider-routing",
        validate_strict=_validate_schema,
        validate_graceful=_validate_schema,
        coerce=_coerce,
    )


def _validate_schema(data: Any, path: Path) -> None:
    """``data`` 는 ``dict[str, list[str]]`` 모양 — model_name → plan_id chain."""
    if not isinstance(data, dict):
        raise RuntimeError(f"provider-routing at {path} must be a dict")
    for model, chain in data.items():
        if not isinstance(model, str):
            type_name = type(model).__name__
            raise RuntimeError(f"provider-routing at {path} key must be str, got {type_name}")
        if not isinstance(chain, list):
            type_name = type(chain).__name__
            raise RuntimeError(
                f"provider-routing at {path}[{model!r}] must be list, got {type_name}"
            )
        if not all(isinstance(p, str) for p in chain):
            raise RuntimeError(f"provider-routing at {path}[{model!r}] must be list[str]")


def _coerce(data: dict[str, Any]) -> dict[str, list[str]]:
    """Normalize — drop empty chains (no policy effect)."""
    result: dict[str, list[str]] = {}
    for model, chain in data.items():
        if not isinstance(chain, list):
            continue
        normalized = [p for p in chain if isinstance(p, str) and p]
        if normalized:
            result[model] = normalized
    return result


def apply_provider_routing_policy(
    model: str,
    default_chain: list[str],
    policy: dict[str, list[str]] | None,
) -> list[str]:
    """Return the effective plan-chain for ``model``.

    Resolution: ``policy[model]`` if present and non-empty → that chain
    (authoritative — overrides registry's set_routing). Otherwise
    ``default_chain`` (i.e. what ``registry.get_routing(model)`` returned).

    ``policy is None`` or model absent → ``default_chain`` unchanged
    (no behavior change).
    """
    if policy is None:
        return default_chain
    override_chain = policy.get(model)
    if not override_chain:
        return default_chain
    return list(override_chain)


__all__ = ["apply_provider_routing_policy"]
