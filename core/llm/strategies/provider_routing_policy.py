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

**Resolution order** (PR-BACKFILL-SOT 2026-05-21 shared chain):

1. ``GEODE_PROVIDER_ROUTING_OVERRIDE`` env var — explicit override.
   - With ``GEODE_PROVIDER_ROUTING_STRICT=1`` (audit subprocess): strict.
   - Without strict flag (operator daily): graceful (no fall-through).
2. ``~/.geode/autoresearch/handoff/provider-routing.json`` — operator-local, graceful.
3. ``core/self_improving/state/policies/provider-routing.json`` — in-repo, graceful.
4. ``None`` — no-op.

**Frontier**: OpenRouter's explicit per-model plan ordering — same model,
different providers, different prices. Anthropic / OpenAI both surface
multiple credential tiers (subscription / PAYG / batch); routing across
them is a measurable cost lever.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.agent.policy_sot import load_policy_sot
from core.paths import AUTORESEARCH_PROVIDER_ROUTING_PATH, OPERATOR_LOCAL_PROVIDER_ROUTING_PATH

_PROVIDER_ROUTING_OVERRIDE_ENV = "GEODE_PROVIDER_ROUTING_OVERRIDE"

_PROVIDER_ROUTING_SOT_PATH = AUTORESEARCH_PROVIDER_ROUTING_PATH
"""Cross-process in-repo SoT path (T4, 2026-05-21). Module-local alias."""

_OPERATOR_LOCAL_PROVIDER_ROUTING_PATH = OPERATOR_LOCAL_PROVIDER_ROUTING_PATH
"""Operator-local SoT path. Module-local alias for monkey-patch."""


def _load_provider_routing_override() -> dict[str, list[str]] | None:
    """Return the active provider-routing dict, or ``None`` if no SoT applies.

    Uses the shared :func:`load_policy_sot` loader (PR-LOWRISK-SLOP — this
    module + cache_policy were the two policy loaders the v0.99.196 7-to-1
    dedup missed). Behaviour preserved: same RuntimeError shapes + log
    wording (via ``label``)."""
    return load_policy_sot(
        env_var=_PROVIDER_ROUTING_OVERRIDE_ENV,
        operator_local=_OPERATOR_LOCAL_PROVIDER_ROUTING_PATH,
        in_repo=_PROVIDER_ROUTING_SOT_PATH,
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
