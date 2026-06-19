"""Petri role × model × source binding resolver.

Top layer of the manifest stack — combines :mod:`plugins.petri_audit.manifest`
(role / source / adapter declarations) with :mod:`plugins.petri_audit.
credential_source` (per-provider resolve / suppress) into a single
:class:`PetriBinding` that callers (/petri picker, to_inspect_model
router, runner) consume.

Layers below:

- :class:`PetriBinding` — frozen dataclass: (role, model, source, provider,
  adapter_module, inspect_prefix, inspect_id).
- :func:`get_binding` — manifest defaults + caller overrides + credential
  resolution. Cheap; no caching (each call re-checks suppressions).
- :func:`infer_provider` — model prefix → provider (claude- / gpt- / glm-).

Target role specialisation: when ``role == "target"``, the inspect id is
``geode/<model>`` regardless of the provider adapter's prefix — the audit
always routes the target through ``GeodeModelAPI`` so the full GEODE
stack is what gets evaluated. See ``plugins.petri_audit.
geode_target`` for the inspect_ai registration.
"""

from __future__ import annotations

from dataclasses import dataclass

from plugins.petri_audit.credential_source import resolve_credential_source
from plugins.petri_audit.manifest import load_manifest
from plugins.petri_audit.user_overrides import read_role_override

__all__ = [
    "FamilyInferenceError",
    "PetriBinding",
    "get_binding",
    "infer_provider",
]


_TARGET_INSPECT_PREFIX = "geode"


class FamilyInferenceError(ValueError):
    """Raised when a model id does not match any known provider prefix."""


@dataclass(frozen=True)
class PetriBinding:
    """Resolved (role, model, source) → adapter binding.

    Fields:

    - ``role``: 'auditor' | 'target' | 'judge' (from manifest enabled_roles)
    - ``model``: concrete model id (e.g. 'claude-sonnet-4-6')
    - ``source``: concrete credential source (never 'auto') — e.g.
      'api_key' / 'claude-cli' / 'openai-codex'
    - ``provider``: inferred from model prefix — 'anthropic' / 'openai' /
      'zhipuai'
    - ``adapter_module``: dotted import path to the adapter module
    - ``inspect_prefix``: prefix used by inspect_ai (e.g. 'anthropic',
      'claude-code', 'openai-codex', 'geode'). For the target role this
      is always 'geode' regardless of provider.
    - ``inspect_id``: ``f"{inspect_prefix}/{model}"`` — ready to pass to
      inspect_ai's ``--model`` / ``--model-role`` flags.
    """

    role: str
    model: str
    source: str
    provider: str
    adapter_module: str
    inspect_prefix: str
    inspect_id: str


def infer_provider(model: str) -> str:
    """Return the provider for a model id.

    Mirrors :func:`plugins.petri_audit.models.provider_of` but raises on
    unknown ids (the legacy helper returned 'unknown'). The strict
    behaviour keeps :func:`get_binding` from silently producing a
    nonsensical inspect id. P1-G consolidates these two helpers.
    """
    if not model:
        raise FamilyInferenceError(f"empty model id {model!r}")
    base = model.rsplit("/", 1)[-1]  # accept 'anthropic/claude-...' too
    if base.startswith("claude-"):
        return "anthropic"
    if base.startswith("gpt-") or base in ("o3", "o4-mini"):
        return "openai"
    if base.startswith("glm-"):
        return "zhipuai"
    # Provider-prefixed fallthrough — same logic as provider_of's tail.
    if model.startswith("anthropic/"):
        return "anthropic"
    if model.startswith("openai/") or model.startswith("openai-api/"):
        return "openai"
    raise FamilyInferenceError(
        f"cannot infer provider for model {model!r}; expected "
        f"claude-/gpt-/glm- or provider-prefixed id"
    )


def get_binding(
    role: str,
    *,
    model: str | None = None,
    source: str | None = None,
) -> PetriBinding:
    """Resolve the effective binding for a Petri role.

    Resolution order (per axis):

    1. ``model`` / ``source`` argument (caller override) — wins outright.
    2. ``~/.geode/petri.toml`` ``[petri.<role>]`` (per-user override
       written by the ``/petri`` slash command).
    3. Manifest default for the model axis; the credential_source
       cascade (settings → manifest default → 'auto' expansion) for the
       source axis.

    Model overrides validate against the role's ``allowed_models`` —
    :class:`ValueError` if not allowed. Source overrides flow through
    :func:`plugins.petri_audit.credential_source.resolve_credential_source`
    so suppressions still apply even when petri.toml pins a source.
    """
    manifest = load_manifest()
    role_spec = manifest.get_role(role)

    user_override = read_role_override(role)
    chosen_model = model or user_override.get("model") or role_spec.default_model
    if chosen_model not in role_spec.allowed_models:
        raise ValueError(
            f"role={role}: model {chosen_model!r} not in allowed_models {role_spec.allowed_models}"
        )

    provider = infer_provider(chosen_model)
    # Source priority — caller arg → petri.toml → resolve_credential_source
    # cascade ('auto' expansion happens inside).
    source_override = source or user_override.get("source")
    # PR-β1 — honour [self_improving_loop] fallback_to_payg. Default True preserves
    # pre-2026-05-19 behaviour for callers that haven't migrated yet.
    from plugins.petri_audit.credential_source import self_improving_loop_fallback_policy

    resolved_source = resolve_credential_source(
        provider,
        override=source_override,
        fallback_to_payg=self_improving_loop_fallback_policy(),
    )
    adapter_spec = manifest.get_adapter(provider, resolved_source)

    # Target role is always routed through GeodeModelAPI — the audit
    # evaluates the full GEODE stack, not the bare LLM. Family adapter
    # is still recorded so the picker can show the underlying source,
    # but the inspect id uses the 'geode' prefix.
    inspect_prefix = _TARGET_INSPECT_PREFIX if role == "target" else adapter_spec.inspect_prefix
    inspect_id = f"{inspect_prefix}/{chosen_model}"

    return PetriBinding(
        role=role,
        model=chosen_model,
        source=resolved_source,
        provider=provider,
        adapter_module=adapter_spec.module,
        inspect_prefix=inspect_prefix,
        inspect_id=inspect_id,
    )
