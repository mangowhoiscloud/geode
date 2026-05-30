"""Per-role (auditor / target / judge / mutator) model + credential-lane provenance.

PR-ROLE-PROVENANCE (2026-05-30). The self-improving loop routes four LLM roles,
each through a credential *lane* that changes cost + behaviour even for the same
model id:

- ``api_key``    → **PAYG**          (metered ANTHROPIC_API_KEY / OPENAI_API_KEY)
- ``openai-codex`` → **Subscription** (ChatGPT subscription OAuth via Codex)
- ``claude-cli`` → **CLI**           (Claude Code CLI subscription OAuth)
- ``auto``       → **Auto**          (manifest cascade)

Recording only the model id loses that lane — so a cycle audited under PAYG
Opus is indistinguishable from one under subscription Opus. This module is the
**single source of truth** for the per-role ``{model, source, lane}`` block so
the two git-tracked ledgers that record it — ``baseline_archive.jsonl`` (on
promote) and ``mutations.jsonl`` (every cycle) — never drift. The canonical
display id is ``GEODE/{model}/{lane}`` (e.g. ``GEODE/gpt-5.5/Subscription``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.config.credential_source import CredentialSource

# Operator-facing lane label per concrete credential source. Mirrors the
# operator's own taxonomy (PAYG / Subscription / CLI): ``claude-cli`` is the
# Claude Code CLI subscription lane, kept distinct from the OpenAI Codex
# subscription lane.
_SOURCE_TO_LANE: dict[str, str] = {
    CredentialSource.API_KEY.value: "PAYG",
    CredentialSource.OPENAI_CODEX.value: "Subscription",
    CredentialSource.CLAUDE_CLI.value: "CLI",
    CredentialSource.AUTO.value: "Auto",
}

ROLES: tuple[str, ...] = ("auditor", "target", "judge", "mutator")


def source_to_lane(source: str | CredentialSource | None) -> str:
    """Map a credential source to the operator-facing lane.

    ``"api_key"`` → ``"PAYG"``, ``"openai-codex"`` → ``"Subscription"``,
    ``"claude-cli"`` → ``"CLI"``, ``"auto"`` → ``"Auto"``. Anything else
    (or ``None``) → ``"Unknown"`` — never raises, so a logging path can't be
    broken by an unexpected source string.
    """
    if source is None:
        return "Unknown"
    key = source.value if isinstance(source, CredentialSource) else str(source)
    return _SOURCE_TO_LANE.get(key, "Unknown")


def role_display_id(model: str | None, lane: str) -> str:
    """The canonical ``GEODE/{model}/{lane}`` per-role observability id."""
    return f"GEODE/{model or '?'}/{lane}"


def build_role_provenance(
    roles: Mapping[str, tuple[str | None, str | None]],
) -> dict[str, dict[str, str]]:
    """Build the ``{role: {model, source, lane}}`` block from (model, source) pairs.

    Used by both the live path (config-derived) and the backfill path (a
    historical baseline's bindings, passed explicitly because its config has
    since changed). ``lane`` is always derived from ``source`` here so the two
    can never disagree.
    """
    out: dict[str, dict[str, str]] = {}
    for role, (model, source) in roles.items():
        src = "" if source is None else str(source)
        out[role] = {
            "model": "" if model is None else str(model),
            "source": src,
            "lane": source_to_lane(src),
        }
    return out


def collect_role_provenance(cfg: Any) -> dict[str, dict[str, str]]:
    """Per-role provenance from a live ``AutoresearchConfig``.

    ``cfg.auditor`` / ``cfg.target`` / ``cfg.judge`` are ``PetriRoleConfig``
    (``.model`` + ``.source``); ``cfg.mutator`` is ``MutatorConfig``
    (``.default_model`` + ``.source``). Read here (not threaded) so the audit /
    promote call sites stay unchanged in shape.
    """
    return build_role_provenance(
        {
            "auditor": (cfg.auditor.model, cfg.auditor.source),
            "target": (cfg.target.model, cfg.target.source),
            "judge": (cfg.judge.model, cfg.judge.source),
            "mutator": (cfg.mutator.default_model, cfg.mutator.source),
        }
    )


__all__ = [
    "ROLES",
    "build_role_provenance",
    "collect_role_provenance",
    "role_display_id",
    "source_to_lane",
]
