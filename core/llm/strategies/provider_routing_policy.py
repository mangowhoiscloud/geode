"""Provider routing SoT reader — ADR-013 T4, JSON mutation surface.

The optional policy supplies a preferred plan chain for each model. The shared
``core.llm.routing`` owner combines it with explicit source constraints and the
stored ``PlanRegistry`` order. A different plan need not have the same model
support, endpoint, quota, or price; account availability does not authorize a
cross-source fallback.

**SoT schema** (모든 entry optional):

.. code-block:: json

    {
      "claude-opus-4-7": ["plan-anthropic-paid", "plan-anthropic-free"],
      "gpt-5": ["plan-openai-tier4"]
    }

빈 entry / 누락 model / 부적합 schema → no-op (registry's set_routing
chain 그대로 사용). Unknown plan_id는 runtime admission에서 명시적으로 거절한다.
선택한 source의 계정이 불가능해도 다른 과금 source로 전환하지 않는다.

Candidate paths are supplied by product composition. Selection is explicit
override → operator-local → packaged default → no-op; an explicit override is
authoritative and may request strict loading.

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
