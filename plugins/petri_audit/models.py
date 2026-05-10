"""Model identifier mapping for Petri audit (P3-b-2 prep).

Bridges between GEODE's internal model IDs (``MODEL_PRICING`` keys in
``core/llm/token_tracker.py``) and ``inspect_ai``'s ``provider/model``
identifier convention. Used by ``runner.run_audit`` to translate user
input (``--judge sonnet-4-6``) into the form ``inspect eval`` expects
(``--model-role judge=anthropic/claude-sonnet-4-6``).

Mapping policy:

- Raw passthrough — input contains ``/`` → returned untouched.
  Escape hatch for ``openai-api/...``, ``anthropic/...:tier`` etc.
- ``claude-*``                → ``anthropic/<model>``      (inspect_ai native)
- ``gpt-*``, ``o3``, ``o4-mini`` → ``openai/<model>``       (inspect_ai native)
- ``glm-*``                  → ``geode/<model>``           (routed through our
  registered ``GeodeModelAPI`` because inspect_ai has no native GLM provider).
- target role                → ``geode/<model>`` regardless of family. The
  whole point of the audit is GEODE-as-a-system, so the target is always
  routed through ``GeodeModelAPI``; the user only chooses the *base* LLM.
"""

from __future__ import annotations

from core.llm.token_tracker import MODEL_PRICING

__all__ = [
    "AuditModelMappingError",
    "family_of",
    "list_audit_models",
    "same_family",
    "to_inspect_model",
    "to_inspect_target",
]


def family_of(model_id: str) -> str:
    """Return the LLM family ('anthropic' / 'openai' / 'zhipuai' / 'unknown').

    Used by :mod:`plugins.petri_audit.optimize` to enforce **M1 — Judge
    must not share a family with the generator** (mitigation against
    in-context reward hacking + self-preference bias). See plan
    § "D 단계 도입 전 위험 카탈로그" R1/R3.

    Raw provider-prefixed ids ("anthropic/...", "openai-api/...") are
    parsed by stripping the trailing segment and re-classifying the
    bare model id; "geode/<base>" routes through us so the family is
    that of the base model.
    """
    if not model_id:
        return "unknown"
    base = model_id.rsplit("/", 1)[-1]
    if base.startswith("claude-"):
        return "anthropic"
    if base.startswith("gpt-") or base in ("o3", "o4-mini"):
        return "openai"
    if base.startswith("glm-"):
        return "zhipuai"
    # Provider prefix fallback for raw inspect_ai identifiers.
    if model_id.startswith("anthropic/"):
        return "anthropic"
    if model_id.startswith("openai/") or model_id.startswith("openai-api/"):
        return "openai"
    return "unknown"


def same_family(model_a: str, model_b: str) -> bool:
    """True when ``family_of(a) == family_of(b)`` and family is known.

    Two ``unknown`` ids are NOT treated as same-family — caller decides
    whether to fail-fast or accept the lower-confidence pair.
    """
    fam_a = family_of(model_a)
    fam_b = family_of(model_b)
    if fam_a == "unknown" or fam_b == "unknown":
        return False
    return fam_a == fam_b


class AuditModelMappingError(ValueError):
    """Raised when a model id cannot be mapped to an ``inspect_ai`` identifier."""


def to_inspect_model(geode_id: str) -> str:
    """Map a GEODE model id to an ``inspect_ai`` ``provider/model`` identifier.

    Used for the ``auditor`` and ``judge`` Petri model-roles. The ``target``
    role uses :func:`to_inspect_target` instead because target is always
    routed through ``geode/...``.

    Raw passthrough: any string containing ``/`` is returned untouched —
    callers can pass ``anthropic/claude-haiku-4-5-20251001`` or
    ``openai-api/glm/glm-5.1`` directly when the alias rules don't fit.
    """
    if not geode_id:
        raise AuditModelMappingError("Empty model id")
    if "/" in geode_id:
        return geode_id
    if geode_id.startswith("claude-"):
        return f"anthropic/{geode_id}"
    if geode_id.startswith("gpt-") or geode_id in ("o3", "o4-mini"):
        return f"openai/{geode_id}"
    if geode_id.startswith("glm-"):
        return f"geode/{geode_id}"
    raise AuditModelMappingError(
        f"Unknown model id {geode_id!r}. Use a MODEL_PRICING key (claude-*, "
        f"gpt-*, o3, o4-mini, glm-*) or a raw 'provider/model' string."
    )


def to_inspect_target(geode_id: str | None) -> str:
    """Map a GEODE model id to a ``geode/<model>`` target identifier.

    Auto-prefixes ``geode/`` unless the input already contains ``/`` (raw
    passthrough). The Petri audit always routes the target through our
    registered ``GeodeModelAPI`` so the *whole* GEODE stack — agentic loop,
    tools, hooks, memory — is what gets evaluated; the user only picks the
    base LLM that GEODE will use internally for the run.

    **N6-followup**: ``None`` / empty string returns the
    ``geode/default`` sentinel, which ``GeodeModelAPI.generate`` reads
    as "caller did not pin a base — let GEODE's regular drift sync
    pick ``settings.model``". Pinned ids stay sticky for the audit's
    lifetime.
    """
    if not geode_id:
        return "geode/default"
    if "/" in geode_id:
        return geode_id
    return f"geode/{geode_id}"


def list_audit_models() -> list[tuple[str, str]]:
    """Return ``(geode_id, inspect_id)`` pairs for every catalog model.

    Powers ``--help`` output and the tool description. Catalog source is
    ``MODEL_PRICING`` so adding a model in ``token_tracker.py`` auto-flows
    here. Skips models whose family the mapping rules don't recognise
    (defensive — should be empty in practice).
    """
    pairs: list[tuple[str, str]] = []
    for geode_id in MODEL_PRICING:
        try:
            pairs.append((geode_id, to_inspect_model(geode_id)))
        except AuditModelMappingError:
            continue
    return pairs
