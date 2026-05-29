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
2. ``~/.geode/self-improving-loop/provider-routing.json`` — operator-local, graceful.
3. ``autoresearch/state/policies/provider-routing.json`` — in-repo, graceful.
4. ``None`` — no-op.

**Frontier**: OpenRouter's explicit per-model plan ordering — same model,
different providers, different prices. Anthropic / OpenAI both surface
multiple credential tiers (subscription / PAYG / batch); routing across
them is a measurable cost lever.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.paths import GLOBAL_PROVIDER_ROUTING_PATH, OPERATOR_LOCAL_PROVIDER_ROUTING_PATH
from core.self_improving_loop.sot_resolution import resolve_sot

log = logging.getLogger(__name__)

_PROVIDER_ROUTING_OVERRIDE_ENV = "GEODE_PROVIDER_ROUTING_OVERRIDE"

_PROVIDER_ROUTING_SOT_PATH = GLOBAL_PROVIDER_ROUTING_PATH
"""Cross-process in-repo SoT path (T4, 2026-05-21). Module-local alias."""

_OPERATOR_LOCAL_PROVIDER_ROUTING_PATH = OPERATOR_LOCAL_PROVIDER_ROUTING_PATH
"""Operator-local SoT path. Module-local alias for monkey-patch."""


def _load_provider_routing_override() -> dict[str, list[str]] | None:
    """Return the active provider-routing dict, or ``None`` if no SoT applies."""
    selection = resolve_sot(
        env_var=_PROVIDER_ROUTING_OVERRIDE_ENV,
        operator_local=_OPERATOR_LOCAL_PROVIDER_ROUTING_PATH,
        in_repo=_PROVIDER_ROUTING_SOT_PATH,
    )
    if selection is None:
        return None
    if selection.strict:
        return _strict_load(selection.path)
    return _graceful_load(selection.path)


def _strict_load(path: Path) -> dict[str, list[str]]:
    if not path.is_file():
        raise RuntimeError(f"{_PROVIDER_ROUTING_OVERRIDE_ENV}={path} file not found")
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{_PROVIDER_ROUTING_OVERRIDE_ENV}={path} load failed: {exc}") from exc
    _validate_schema(data, path)
    return _coerce(data)


def _graceful_load(path: Path) -> dict[str, list[str]] | None:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        log.warning("provider-routing SoT at %s is unreadable; ignoring", path)
        return None
    try:
        _validate_schema(data, path)
    except RuntimeError as exc:
        log.warning("provider-routing SoT at %s schema invalid: %s; ignoring", path, exc)
        return None
    return _coerce(data)


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
