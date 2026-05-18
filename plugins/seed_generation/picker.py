"""Seed-pipeline picker — 7-role × 4-path auth resolver + ToS notice.

For each enabled role in the seed-generation manifest, the picker resolves
the concrete ``(model, family, source)`` binding the role will use at
runtime, factoring in:

1. The role's ``default_model`` from
   ``plugins/seed_generation/seed_generation.plugin.toml``.
2. The model's provider family, inferred from a prefix table (claude-*
   → anthropic, gpt-* / text-embedding-* → openai, glm-* → zhipuai).
3. The Petri source table's ``default`` (typically ``auto``) for that
   family.
4. The OAuth probe (``is_claude_oauth_available`` /
   ``is_codex_oauth_available``) when the source is ``auto``.
5. The user override at ``~/.geode/seed-generation.toml`` (per-role
   ``source = "<concrete>"`` lines), which wins over the auto-resolve.

The 4 paths spanned by the picker are:

============== ====================== ===================
family         OAuth source           PAYG source
============== ====================== ===================
anthropic      ``claude-cli``         ``api_key``
openai         ``openai-codex``       ``api_key``
============== ====================== ===================

ToS notice
==========

Subscription-backed OAuth paths (``claude-cli``, ``openai-codex``) drive
LLM calls through the user's Claude.ai / ChatGPT Plus quota. Anthropic
and OpenAI's Terms of Service permit individual programmatic use but
discourage automation at scale, so the picker surfaces a one-time
warning when any role resolves to a subscription path. The notice is
emitted once per process via :func:`print_tos_notice` (idempotent under
a module-level flag); CLI front-ends can suppress with ``quiet=True``.

Diversity validator
===================

The :class:`JudgePanelSpec` already enforces ``required_diversity_families``
at manifest load. The picker adds a *runtime* check
(:func:`validate_runtime_diversity`) that the *resolved* voter sources
remain on ≥ N distinct ``(family, source)`` pairs after OAuth probing
and user overrides — a user override that collapses all 3 judges onto
``anthropic.claude-cli`` would defeat the bias guarantee even though the
manifest-time families check still passes (all voters claim
``family=anthropic`` but two of them now share an identical source).

P1-P7 prevention checklist application:

- **P4 Environment Anchor**: ``GLOBAL_SEED_PIPELINE_TOML`` is the single
  filesystem anchor (``core/paths.py``), NOT a cwd-relative or
  module-relative path. Mirrors :data:`core.paths.GLOBAL_PETRI_TOML`.
- **P7 Caller-Callee Contract**: every :class:`RoleBinding` carries the
  ``kind`` discriminator (``completion`` / ``embedding``), so the S6
  Ranker / S5 Pilot dispatchers don't need to guess by model-name
  string.
"""

from __future__ import annotations

import logging
import sys
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Literal

from core.paths import GLOBAL_SEED_PIPELINE_TOML

from plugins.seed_generation.manifest import (
    SeedGenerationManifest,
    SeedRoleSpec,
    VoterSpec,
    load_manifest,
)

log = logging.getLogger(__name__)

__all__ = [
    "SUBSCRIPTION_SOURCES",
    "PickerResult",
    "RoleBinding",
    "VoterBinding",
    "infer_family",
    "load_user_overrides",
    "pick_bindings",
    "print_tos_notice",
    "reset_tos_notice",
    "validate_runtime_diversity",
]


SUBSCRIPTION_SOURCES = frozenset({"claude-cli", "openai-codex"})


_FAMILY_PREFIX_MAP: tuple[tuple[str, str], ...] = (
    ("claude-", "anthropic"),
    ("text-embedding-", "openai"),
    ("gpt-", "openai"),
    ("o1-", "openai"),
    ("o3-", "openai"),
    ("glm-", "zhipuai"),
)


_FAMILY_DEFAULT_OAUTH: dict[str, str] = {
    "anthropic": "claude-cli",
    "openai": "openai-codex",
}

_FAMILY_DEFAULT_PAYG: dict[str, str] = {
    "anthropic": "api_key",
    "openai": "api_key",
    "zhipuai": "api_key",
}


# Module-level flag so :func:`print_tos_notice` is idempotent across
# repeated picker calls in the same process (e.g. CLI smoke + CLI run).
_TOS_NOTICE_SHOWN = False


@dataclass(frozen=True)
class RoleBinding:
    """Resolved auth binding for one seed-generation role.

    All fields are concrete after :func:`pick_bindings` returns — no
    ``auto`` sentinel, no ``None`` source. The ``kind`` discriminator
    mirrors :attr:`SeedRoleSpec.kind` so callers don't have to re-import
    the manifest schema.
    """

    role: str
    model: str
    family: str
    source: str
    kind: Literal["completion", "embedding"]


@dataclass(frozen=True)
class VoterBinding:
    """Resolved auth binding for one judge-panel voter."""

    model: str
    family: str
    source: str


@dataclass(frozen=True)
class PickerResult:
    """Top-level picker output — per-role bindings + voter panel.

    The orchestrator (S6 Ranker, S11 CLI) reads
    :attr:`bindings` to look up each role's binding and :attr:`voters`
    for the 3-judge panel's resolved auth. :attr:`subscription_paths_in_use`
    lists the distinct subscription sources currently routed through so
    :func:`print_tos_notice` can render the right warning lines.
    """

    bindings: dict[str, RoleBinding]
    voters: list[VoterBinding]
    diversity_families: int
    subscription_paths_in_use: frozenset[str]


def infer_family(model: str) -> str:
    """Return the provider family for ``model`` (best-effort by prefix).

    Raises ``ValueError`` for unrecognised prefixes — better to fail
    loudly at picker time than to bind to the wrong adapter.
    """
    for prefix, family in _FAMILY_PREFIX_MAP:
        if model.startswith(prefix):
            return family
    raise ValueError(
        f"infer_family: model {model!r} did not match any known prefix "
        f"({[p for p, _ in _FAMILY_PREFIX_MAP]})"
    )


def load_user_overrides(
    path: Path | str | None = None,
) -> dict[str, dict[str, str]]:
    """Load ``~/.geode/seed-generation.toml`` per-role overrides.

    Schema:

    .. code-block:: toml

       [generator]
       source = "api_key"

       [pilot]
       source = "claude-cli"
       model  = "claude-haiku-4-5"

    Returns ``{role: {key: value, …}}``. Empty dict when the file does
    not exist (the override file is OPTIONAL).
    """
    target = Path(path) if path is not None else GLOBAL_SEED_PIPELINE_TOML
    if not target.is_file():
        return {}
    try:
        raw = tomllib.loads(target.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        log.warning(
            "seed-generation picker: %s is not valid TOML (%s) — ignoring overrides",
            target,
            exc,
        )
        return {}
    out: dict[str, dict[str, str]] = {}
    for role, body in raw.items():
        if not isinstance(body, dict):
            log.warning(
                "seed-generation picker: override entry %r is not a table — ignoring",
                role,
            )
            continue
        out[role] = {k: str(v) for k, v in body.items() if isinstance(v, (str, int, float))}
    return out


def _probe_oauth(family: str) -> bool:
    """Lazy OAuth probe — imports the per-family helper only when needed."""
    if family == "anthropic":
        from plugins.petri_audit.claude_code_provider import is_claude_oauth_available

        return is_claude_oauth_available()
    if family == "openai":
        from plugins.petri_audit.codex_provider import is_codex_oauth_available

        return is_codex_oauth_available()
    return False


def _resolve_source(
    family: str,
    *,
    hint: str | None = None,
    auto_probe: bool = True,
) -> str:
    """Resolve a concrete source for ``family``.

    - ``hint`` may be one of: a concrete source (returned as-is after
      family-allowance check via the caller); ``"auto"`` (probe OAuth →
      fall back to api_key); or ``None`` (equivalent to ``"auto"``).
    - ``auto_probe=False`` skips the OAuth probe (used by tests and by
      pre-flight dry-runs that don't want to touch the keychain).
    """
    if hint and hint != "auto":
        return hint
    if auto_probe and family in _FAMILY_DEFAULT_OAUTH:
        try:
            if _probe_oauth(family):
                return _FAMILY_DEFAULT_OAUTH[family]
        except Exception as exc:  # pragma: no cover - defensive
            log.debug(
                "seed-generation picker: OAuth probe for family=%r raised %s — "
                "falling back to PAYG",
                family,
                exc,
            )
    return _FAMILY_DEFAULT_PAYG.get(family, "api_key")


def pick_bindings(
    manifest: SeedGenerationManifest | None = None,
    *,
    overrides: dict[str, dict[str, str]] | None = None,
    auto_probe: bool = True,
    enforce_diversity: bool = True,
) -> PickerResult:
    """Resolve concrete bindings for every enabled role + judge voter.

    Parameters
    ----------
    manifest
        Loaded :class:`SeedGenerationManifest`. Defaults to
        :func:`load_manifest`'s result (with its lru_cache).
    overrides
        Per-role override map as returned by :func:`load_user_overrides`.
        Defaults to reading :data:`GLOBAL_SEED_PIPELINE_TOML`. Pass
        ``{}`` explicitly to ignore the override file (used by tests).
    auto_probe
        When False, skip the OAuth credential probe and resolve any
        ``auto`` to the PAYG source. Used by pre-flight dry-runs.
    enforce_diversity
        When True (default), call :func:`validate_runtime_diversity`
        on the resolved panel before returning so a user override that
        collapses the judges cannot silently make it to S6. Tests that
        construct deliberately-collapsed fixtures pass ``False``.

    Override validation
    -------------------
    For each role, an override ``model`` field is dropped (with a
    WARNING) when it is not in the role's ``allowed_models`` —
    falling back to ``default_model``. Override ``source`` values are
    cross-checked against Petri's source table and dropped (with a
    WARNING) when they are not in ``petri.source.<family>.allowed``,
    falling back to the resolved auto / PAYG source. This keeps a
    typo or unsupported pairing from producing a bad ``RoleBinding``
    that the S6 Ranker would then dispatch against the wrong adapter.
    """
    if manifest is None:
        manifest = load_manifest()
    if overrides is None:
        overrides = load_user_overrides()
    petri_sources = _load_petri_sources()

    bindings: dict[str, RoleBinding] = {}
    subscription_paths: set[str] = set()
    for role_name in manifest.enabled_roles:
        spec = manifest.get_role(role_name)
        override = overrides.get(role_name, {})
        model = _validate_override_model(role_name, override.get("model"), spec)
        try:
            family = infer_family(model)
        except ValueError:
            log.warning(
                "seed-generation picker: role=%r model=%r — family inference failed, "
                "defaulting to anthropic",
                role_name,
                model,
            )
            family = "anthropic"
        source_hint = _validate_override_source(
            role_name, override.get("source"), family, petri_sources
        )
        source = _resolve_source(family, hint=source_hint, auto_probe=auto_probe)
        bindings[role_name] = RoleBinding(
            role=role_name,
            model=model,
            family=family,
            source=source,
            kind=spec.kind,
        )
        if source in SUBSCRIPTION_SOURCES:
            subscription_paths.add(source)

    voters: list[VoterBinding] = []
    for voter in manifest.judge_panel.voters:
        resolved_source = _resolve_voter_source(voter, auto_probe=auto_probe)
        voters.append(
            VoterBinding(
                model=voter.model,
                family=voter.family,
                source=resolved_source,
            )
        )
        if resolved_source in SUBSCRIPTION_SOURCES:
            subscription_paths.add(resolved_source)

    diversity_families = len({v.family for v in voters})

    result = PickerResult(
        bindings=bindings,
        voters=voters,
        diversity_families=diversity_families,
        subscription_paths_in_use=frozenset(subscription_paths),
    )
    if enforce_diversity:
        validate_runtime_diversity(
            result,
            required_family_count=manifest.judge_panel.required_diversity_families,
        )
    return result


def _validate_override_model(role_name: str, override_model: str | None, spec: SeedRoleSpec) -> str:
    """Return a model name, replacing an out-of-allowlist override with the default."""
    default_model = spec.default_model
    allowed = spec.allowed_models
    if override_model is None:
        return default_model
    if override_model not in allowed:
        log.warning(
            "seed-generation picker: role=%r override model=%r not in allowed_models=%s "
            "— falling back to default %r",
            role_name,
            override_model,
            allowed,
            default_model,
        )
        return default_model
    return override_model


def _load_petri_sources() -> dict[str, set[str]]:
    """Build ``{family: allowed_sources}`` from the Petri manifest.

    Loaded lazily and tolerantly — if the Petri manifest is unavailable
    in a test fixture, override-source validation falls back to a
    permissive mode (logs WARNING but does not block). The seed-generation
    manifest's cross-validator already rejects voter rows with bad
    families/sources at load time, so override validation is the second
    line of defence.
    """
    try:
        from plugins.petri_audit.manifest import load_manifest as load_petri_manifest

        petri = load_petri_manifest()
    except Exception as exc:
        log.debug(
            "seed-generation picker: petri manifest unavailable (%s) — "
            "skipping override-source allowlist check",
            exc,
        )
        return {}
    out: dict[str, set[str]] = {}
    for family, spec in getattr(petri, "sources", {}).items():
        out[family] = set(getattr(spec, "allowed", []))
    return out


def _validate_override_source(
    role_name: str,
    override_source: str | None,
    family: str,
    petri_sources: dict[str, set[str]],
) -> str | None:
    """Return an override source if allowed, else None (caller will auto-resolve).

    Allows ``auto`` because that's an explicit sentinel handled by
    :func:`_resolve_source`. A blank or invalid override falls through
    to None so the OAuth/PAYG resolver picks a safe default.
    """
    if override_source is None:
        return None
    if override_source == "auto":
        return "auto"
    allowed = petri_sources.get(family)
    if allowed and override_source not in allowed:
        log.warning(
            "seed-generation picker: role=%r override source=%r not in "
            "petri.source.%s.allowed=%s — falling back to auto-resolve",
            role_name,
            override_source,
            family,
            sorted(allowed),
        )
        return None
    return override_source


def _resolve_voter_source(voter: VoterSpec, *, auto_probe: bool) -> str:
    """Voter sources are concrete-by-construction (``auto`` is rejected
    at manifest load), but call through :func:`_resolve_source` so a
    future relaxation of that rule transparently picks up OAuth probing.
    """
    return _resolve_source(voter.family, hint=voter.source, auto_probe=auto_probe)


def print_tos_notice(
    result: PickerResult,
    *,
    file: IO[str] | None = None,
    quiet: bool = False,
    force: bool = False,
) -> None:
    """Render the ToS notice when any subscription source is in use.

    Idempotent within a process — call from CLI startup. Pass
    ``force=True`` to override the once-per-process flag (tests).
    """
    global _TOS_NOTICE_SHOWN
    if quiet:
        return
    if not result.subscription_paths_in_use:
        return
    if _TOS_NOTICE_SHOWN and not force:
        return
    out = file if file is not None else sys.stderr
    paths_in_use = ", ".join(sorted(result.subscription_paths_in_use))
    out.write(
        "\n"
        "─── seed-generation ToS notice ─────────────────────────────────────\n"
        f"Subscription-backed auth path(s) in use: {paths_in_use}\n"
        "These paths charge the run against your Claude.ai / ChatGPT Plus\n"
        "quota. The vendors' Terms of Service permit individual programmatic\n"
        "use but discourage automation at scale; review the linked policies\n"
        "before running unattended.\n"
        "  - Anthropic: https://www.anthropic.com/legal/aup\n"
        "  - OpenAI:    https://openai.com/policies/usage-policies\n"
        "Switch a role to PAYG via ~/.geode/seed-generation.toml\n"
        "  e.g.  [ranker]\n"
        '        source = "api_key"\n'
        "──────────────────────────────────────────────────────────────────\n"
    )
    out.flush()
    _TOS_NOTICE_SHOWN = True


def reset_tos_notice() -> None:
    """Reset the once-per-process flag — used by tests."""
    global _TOS_NOTICE_SHOWN
    _TOS_NOTICE_SHOWN = False


def validate_runtime_diversity(
    result: PickerResult,
    *,
    required_family_count: int = 2,
    required_voter_path_count: int = 2,
) -> None:
    """Verify the resolved bindings preserve panel diversity at runtime.

    Two checks:

    1. ``len({v.family for v in result.voters}) >= required_family_count``
       — same gate as the manifest, re-run after override merge so a
       user override that swaps a voter's family is caught.
    2. ``len({(v.family, v.source) for v in result.voters}) >= required_voter_path_count``
       — voters must span at least ``required_voter_path_count`` distinct
       *paths* (family + source pair), not just families. A panel that
       collapsed all 3 judges onto a single ``(anthropic, claude-cli)``
       binding would pass check #1 in some pathological override flows
       but fails this stricter runtime check.

    Raises ``ValueError`` on either failure.
    """
    family_set = {v.family for v in result.voters}
    if len(family_set) < required_family_count:
        raise ValueError(
            f"judge panel runtime diversity violated — resolved voters "
            f"span families {sorted(family_set)} ({len(family_set)} of "
            f"required {required_family_count})"
        )
    path_set = {(v.family, v.source) for v in result.voters}
    if len(path_set) < required_voter_path_count:
        raise ValueError(
            f"judge panel runtime path diversity violated — resolved voters "
            f"collapsed onto {sorted(path_set)} ({len(path_set)} of required "
            f"{required_voter_path_count}). Check user overrides at "
            f"~/.geode/seed-generation.toml."
        )


def list_subscription_roles(result: PickerResult) -> list[str]:
    """Return the list of role names currently bound to a subscription
    source. Used by CLI front-ends to highlight specific roles in the
    ToS notice / pre-flight summary.
    """
    return [
        role for role, binding in result.bindings.items() if binding.source in SUBSCRIPTION_SOURCES
    ]


def iter_distinct_paths(result: PickerResult) -> Iterable[tuple[str, str]]:
    """Iterate distinct ``(family, source)`` pairs across roles + voters."""
    seen: set[tuple[str, str]] = set()
    for binding in result.bindings.values():
        key = (binding.family, binding.source)
        if key not in seen:
            seen.add(key)
            yield key
    for voter in result.voters:
        key = (voter.family, voter.source)
        if key not in seen:
            seen.add(key)
            yield key
