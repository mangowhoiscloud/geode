"""Built-in sub-agent role registry + typed result validation.

PR-SUBAGENT-ROLES (2026-07-02) — a live run surfaced two ``delegate_task``
calls whose sub-agent output failed JSON parsing; the parent loop had no
contract for what a delegated result should look like, and no explicit
mapping of which sub-agent role gets which tools. This module is the
single declarative home for both:

- **Role → tool allowlist** — enforced through the EXISTING
  ``ToolExecutor.denied_tools`` rail (denied = all tools − allowed);
  ``SubAgentManager._build_worker_request`` computes the denied set via
  :func:`role_denied_tools` and the worker passes it into the child
  executor. No second enforcement path.
- **Role → output schema** — a pydantic model the parent validates the
  sub-agent's raw text against at the parse site
  (``SubAgentManager._to_sub_result``). Validation NEVER raises into the
  loop: failure produces an observable ``{"validated": False, ...}``
  structured error + ``log.warning`` (fail-loud, no silent garbage).

Relation to existing registries (ONE schema / one loader / one call
surface): :class:`core.skills.agents.AgentRegistry` loads *user-defined*
AgentDefinitions from ``.claude/agents/*.md`` (prompt + toolkit); the
toolkit registry (``core/tools/toolkits.toml``) names tool bundles.
Neither carries an output contract. This registry is the built-in,
code-declared role set whose distinguishing feature IS the pydantic
output model — it is opt-in via ``SubTask.role`` / the ``delegate_task``
``role`` parameter, and an unknown/empty role leaves the legacy
behaviour untouched.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

__all__ = [
    "SUBAGENT_ROLES",
    "PatchSet",
    "ResearchFindings",
    "ReviewFindings",
    "SubAgentRole",
    "VerificationResult",
    "get_role",
    "output_schema_line",
    "role_denied_tools",
    "validate_role_output",
]

# Cap on the raw-text excerpt carried in a failed-validation result so a
# runaway sub-agent transcript cannot blow up the parent's tool_result.
_RAW_EXCERPT_LIMIT = 2000

# First fenced ```json``` block (optional lang tag). Sister anchors:
# ``core/agent/sub_agent.py:_JSON_CODEBLOCK_RE`` (producer-side strip)
# and ``plugins/seed_generation/agents/base.py`` (consumer-side strip).
# Kept local so this module stays a leaf (stdlib + pydantic only) —
# importing sub_agent here would invert the dependency direction.
_FENCED_JSON_RE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


# ---------------------------------------------------------------------------
# Output models — one per built-in role
# ---------------------------------------------------------------------------


class ResearchFinding(BaseModel):
    """One evidence-backed claim from a repo_researcher sub-agent."""

    claim: str
    evidence_path: str
    confidence: float


class ResearchFindings(BaseModel):
    """repo_researcher output contract."""

    findings: list[ResearchFinding]


class Patch(BaseModel):
    """One file-level change a patcher sub-agent performed."""

    path: str
    action: str
    summary: str


class PatchSet(BaseModel):
    """patcher output contract."""

    patches: list[Patch]


class VerificationCheck(BaseModel):
    """One named check a verifier sub-agent ran."""

    name: str
    passed: bool
    detail: str = ""


class VerificationResult(BaseModel):
    """verifier output contract."""

    passed: bool
    checks: list[VerificationCheck]


class ReviewFinding(BaseModel):
    """One located issue from a reviewer sub-agent."""

    file: str
    line: int
    severity: str
    summary: str


class ReviewFindings(BaseModel):
    """reviewer output contract."""

    findings: list[ReviewFinding]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubAgentRole:
    """Declarative capability record for one built-in sub-agent role.

    ``tools`` is an ALLOWLIST of ``core/tools/definitions.json`` names;
    enforcement inverts it into the denied set (:func:`role_denied_tools`)
    so the existing ``ToolExecutor.denied_tools`` rail applies — that rail
    is the only one that also stops ``run_bash`` / ``delegate_task``,
    which are special-cased ahead of handler lookup (PR-EXEC-HARDENING).
    """

    role: str
    tools: tuple[str, ...]
    output_model: type[BaseModel] | None
    description: str


SUBAGENT_ROLES: dict[str, SubAgentRole] = {
    "repo_researcher": SubAgentRole(
        role="repo_researcher",
        tools=("glob_files", "grep_files", "read_document", "session_search"),
        output_model=ResearchFindings,
        description=(
            "Read-only codebase researcher — locates evidence and returns "
            "claims with file-path citations and a confidence score."
        ),
    ),
    "patcher": SubAgentRole(
        role="patcher",
        tools=("edit_file", "write_file", "read_document", "grep_files", "glob_files"),
        output_model=PatchSet,
        description=(
            "Applies focused file edits and reports every touched path "
            "with the action taken and a one-line summary."
        ),
    ),
    "verifier": SubAgentRole(
        role="verifier",
        tools=("run_bash",),
        output_model=VerificationResult,
        description=(
            "Runs shell checks (tests / lint / smoke) and reports an "
            "overall pass flag plus per-check outcomes."
        ),
    ),
    "reviewer": SubAgentRole(
        role="reviewer",
        tools=("grep_files", "read_document"),
        output_model=ReviewFindings,
        description=(
            "Read-only code reviewer — reports file/line-located findings "
            "with a severity and a one-line summary."
        ),
    ),
}


def get_role(name: str) -> SubAgentRole | None:
    """Return the built-in role for ``name`` or None (unknown = legacy path)."""
    return SUBAGENT_ROLES.get(name)


# Provider-native tools injected OUTSIDE definitions.json (Anthropic/OpenAI
# computer-use). The inversion universe must include them or a restricted
# role could still execute hosted desktop control (Codex MCP catch).
PROVIDER_NATIVE_TOOLS: frozenset[str] = frozenset({"computer", "computer_use"})


def role_denied_tools(role: SubAgentRole, all_tools: Any) -> set[str]:
    """Invert the role's allowlist into the denied set for the existing rail.

    ``denied = (all_tools ∪ PROVIDER_NATIVE_TOOLS) − role.tools``. The result
    feeds ``WorkerRequest.denied_tools`` → the child ``ToolExecutor``'s
    ``denied_tools`` frozenset — handler-dict filtering alone cannot stop
    ``run_bash`` / ``delegate_task`` / provider-injected ``computer`` (the
    executor special-cases them before handler lookup), so the denylist is
    the enforcement point.
    """
    allowed = set(role.tools)
    universe = set(all_tools) | PROVIDER_NATIVE_TOOLS
    return {name for name in universe if name not in allowed}


def output_schema_line(role: SubAgentRole) -> str:
    """One-line prompt instruction carrying the role's output JSON schema.

    Appended to the sub-agent prompt so generation-side pressure exists in
    addition to the parent-side validation. Empty string when the role has
    no output model.
    """
    if role.output_model is None:
        return ""
    schema = json.dumps(
        role.output_model.model_json_schema(), ensure_ascii=False, separators=(",", ":")
    )
    return (
        "Your FINAL message must be ONLY a JSON object matching this schema "
        f"(no prose, no markdown fences): {schema}"
    )


def validate_role_output(role: SubAgentRole, raw_text: str) -> dict[str, Any] | None:
    """Validate a sub-agent's raw text against the role's output model.

    Returns ``None`` when the role has no ``output_model`` (caller keeps
    the legacy parse). Otherwise ALWAYS returns a dict and never raises:

    - success → ``{"validated": True, "data": <model.model_dump()>}``
    - failure → ``{"validated": False, "error": "<class>: <msg>",
      "raw": <first 2000 chars>}`` + ``log.warning`` (observable degraded
      result — never a JSONDecodeError into the loop, never silent garbage).

    Recovery order: (a) parse the raw text as JSON directly; (b) if that
    fails, extract the FIRST fenced ```json``` block and retry.
    """
    model = role.output_model
    if model is None:
        return None

    text = (raw_text or "").strip()
    candidates: list[str] = []
    if text:
        candidates.append(text)
        fence = _FENCED_JSON_RE.search(text)
        if fence is not None:
            fenced_body = fence.group(1).strip()
            if fenced_body and fenced_body != text:
                candidates.append(fenced_body)

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            last_error = exc
            continue
        try:
            validated = model.model_validate(parsed)
        except ValidationError as exc:
            last_error = exc
            continue
        return {"validated": True, "data": validated.model_dump()}

    if last_error is not None:
        error_text = f"{type(last_error).__name__}: {last_error}"
    else:
        error_text = "EmptyOutput: sub-agent returned no text"
    log.warning(
        "Sub-agent role %r output failed %s validation — %s",
        role.role,
        model.__name__,
        error_text,
    )
    return {"validated": False, "error": error_text, "raw": text[:_RAW_EXCERPT_LIMIT]}
