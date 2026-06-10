"""Abstract base for the 7 seed-generation agent roles.

Each concrete role (Generation / Reflection / Proximity / Pilot / Ranker
/ Evolver / Meta-review) is a subclass of :class:`BaseSeedAgent` and
returns a :class:`SeedAgentResult`. The orchestrator
(``plugins.seed_generation.orchestrator.Pipeline``) registers role
instances via :class:`PipelineRegistry` and awaits
:meth:`BaseSeedAgent.aexecute` once per phase, passing the current
:class:`PipelineState`.

Why a class hierarchy
=====================

Each role has a distinct contract (input schema, output schema, side
effects). The paper (arXiv:2502.18864 Figure 1) defines 6 agent types
with explicit symmetry — Generation / Reflection / Ranking / Evolution
/ Proximity / Meta-review. GEODE adds Pilot to replace the
scientist-in-the-loop human validator with an automated Petri inner-
loop subset. The 7-way symmetry is structural, not premature
abstraction — see ``docs/audits/2026-05-18-plan-a-fidelity-amendment.md``
for the explicit waiver.

Lifecycle
=========

1. ``__init__(role_name, model, source, manifest_role)`` — bind to a
   ``[seed_generation.role.<name>]`` manifest entry. The manifest carries
   ``default_model`` + ``allowed_models`` + ``role_contract`` (S2.5).
2. ``execute(state)`` — synchronous entry point. The orchestrator
   provides sub-agent isolation and cost rollup.
3. Returns ``SeedAgentResult`` with ``status``, ``output`` payload,
   token usage, optional ``error_message``.

Sub-agent integration
=====================

Every role dispatches through ``SubAgentManager.delegate`` (S2+).
There is no per-role embedding branch — pre-CSP-8 Proximity called
``text_embed`` directly outside the delegate path; CSP-8 reverted
that to the paper's §3 LLM-clustering, and CSP-10 dropped the
remaining ``kind`` plumbing from the manifest / picker / pre-flight.
"""

from __future__ import annotations

import abc
import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

log = logging.getLogger(__name__)

# Single anchor for every agent role's default model (hardcoding sweep,
# 2026-06-11) — was independently hardcoded in 10 agent modules. Per-role
# overrides still flow through [self_improving_loop.seed_generation.roles.*].
DEFAULT_AGENT_MODEL = "claude-opus-4-8"

__all__ = [
    "BaseSeedAgent",
    "SeedAgentResult",
    "parse_structured_output",
    "sum_sub_result_tokens",
]


# Matches a fenced code block containing JSON. The optional language tag
# (`json` / `JSON`) and surrounding whitespace/newlines are stripped; the
# captured group is the inner JSON body. Smoke 6 surfaced critic /
# proximity / meta_reviewer responses wrapped in ```json``` fences that
# json.loads() rejects — this helper unwraps them before parsing.
_JSON_CODEBLOCK_RE = re.compile(
    r"```(?:json|JSON)?\s*\n?(.*?)\n?\s*```",
    re.DOTALL,
)


def _strip_json_codeblock(text: str) -> str:
    """Strip a leading/trailing ```json``` fence from an LLM response.

    Returns the inner body if a fenced block is found, otherwise the
    original string unchanged. The body itself is whitespace-stripped so
    json.loads() sees `{...}` without leading/trailing newlines.
    """
    match = _JSON_CODEBLOCK_RE.search(text)
    if match is None:
        return text
    return match.group(1).strip()


def parse_structured_output(
    raw_output: Any,
    *,
    required_fields: Sequence[str],
    pin_field: str | None = None,
    pin_value: Any = None,
) -> dict[str, Any] | None:
    """Extract a structured JSON dict from a sub-agent's SubResult.output.

    Shared parser used by Critic (S3), Pilot (S5), and Ranker voters
    (S6) — all of which dispatch one sub-agent per work item and
    expect a JSON response. Hoisted to base.py to avoid duplicating the
    JSON-as-text fallback + required-field validation across 3+ agents
    (see post-merge audit recommendation, 2026-05-18).

    Accepts either:
    - ``raw_output`` already a dict (most adapters serialize JSON →
      dict in ``SubResult.output`` directly).
    - ``raw_output`` a dict with a ``"text"`` key holding a JSON string
      (fallback for adapters that pass through raw text).

    Returns ``None`` (so the caller drops the result) when:
    - ``raw_output`` is not a dict and has no parseable ``text`` field.
    - The parsed dict is missing ANY of ``required_fields``.

    When ``pin_field`` is provided, the function overrides that key
    with ``pin_value`` after validation — used to pin candidate_id /
    match_id from the task args so a wrong LLM echo can't reroute a
    result to the wrong slot.
    """
    if not isinstance(raw_output, dict):
        return None
    parsed: dict[str, Any] | None = None
    # Prefer the dict-as-structured-output shape when any required field
    # is present (or when there are no required fields and no "text" key,
    # in which case the dict itself is the payload).
    has_required = any(f in raw_output for f in required_fields)
    has_text = isinstance(raw_output.get("text"), str)
    if has_required or (not required_fields and not has_text):
        parsed = dict(raw_output)
    elif has_text:
        candidate_text = _strip_json_codeblock(raw_output["text"])
        try:
            candidate = json.loads(candidate_text)
        except json.JSONDecodeError:
            return None
        if isinstance(candidate, dict):
            parsed = candidate
    if parsed is None:
        return None
    missing = [f for f in required_fields if f not in parsed]
    if missing:
        log.warning(
            "seed-generation parse_structured_output: missing required fields %s",
            missing,
        )
        return None
    if pin_field is not None:
        parsed[pin_field] = pin_value
    return parsed


@dataclass
class SeedAgentResult:
    """Standardized result of one phase-agent invocation.

    Why not reuse ``core.agent.sub_agent.SubAgentResult``? S2-fix
    (2026-05-18) explicit rationale — both dataclasses share ~80% of
    fields (status / duration / token counts / error category), but
    their *aggregation semantics* differ:

    - ``SubAgentResult`` is per-TASK (one spawn → one result), with
      ``task_id`` + ``announced`` flag for the parent loop's announce
      queue. It is N-many per phase when Generator/Ranker fan out.
    - ``SeedAgentResult`` is per-ROLE (one phase → one result),
      consumed by the orchestrator's state merge. Carries ``output``
      dict whose keys (``candidates``, ``reflections``, ``elo_ratings``,
      …) map directly onto ``PipelineState`` fields.

    Wrapping SubAgentResult would force every role to construct a
    fake ``task_id`` and force the orchestrator to know about
    sub-task-vs-phase polymorphism. Keeping them sibling types lets
    each evolve in its own domain. Roles that spawn sub-agents
    (Generator, Ranker, Pilot) translate ``list[SubResult]`` →
    ``SeedAgentResult.output`` inside ``execute()``.
    """

    role: str
    status: Literal["ok", "error", "skipped"] = "ok"
    output: dict[str, Any] = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usd_spent: float = 0.0
    duration_ms: float = 0.0
    error_category: str | None = None
    error_message: str | None = None

    @property
    def success(self) -> bool:
        return self.status == "ok"


def sum_sub_result_tokens(
    results: Iterable[Any],
) -> tuple[int, int, float]:
    """Sum ``(prompt_tokens, completion_tokens, usd_spent)`` over sub-results.

    PR-SEEDGEN-TOKENS (2026-05-30) — fan-out roles (generator / ranker /
    pilot) and single-shot roles delegate via ``SubAgentManager`` and get
    back a ``list[SubResult]``. Each ``SubResult`` now carries the worker
    subprocess's LLM usage (forwarded through ``IsolationResult``). Roles
    call this to fold every spawned sub-agent's usage into the single
    ``SeedAgentResult`` they return; the orchestrator's run-level rollup
    (``orchestrator.py``) then sums those into ``PipelineState``.

    HARD LIMITATION: subscription / CLI-routed calls (claude-cli,
    codex-cli) return an empty ``UsageSummary()`` — the subscription path
    does not expose token usage — so their contribution is honestly 0.
    Only API-key / payg sub-agents (e.g. payg ranker voters) add non-zero
    numbers. Counts are never fabricated.

    Accepts any iterable of objects exposing the three attributes so it
    works on real ``SubResult`` instances and lightweight test stubs.
    """
    prompt_tokens = 0
    completion_tokens = 0
    usd_spent = 0.0
    for result in results:
        prompt_tokens += int(getattr(result, "prompt_tokens", 0) or 0)
        completion_tokens += int(getattr(result, "completion_tokens", 0) or 0)
        usd_spent += float(getattr(result, "usd_spent", 0.0) or 0.0)
    return prompt_tokens, completion_tokens, usd_spent


class BaseSeedAgent(abc.ABC):
    """Abstract contract for a single seed-generation phase role.

    Subclasses MUST override :meth:`aexecute`. Per the fidelity
    amendment, the role concrete implementations (S2-S8) must perform
    substantive work — no ``pass`` / ``return None`` stubs are
    permitted.
    """

    def __init__(
        self,
        *,
        role: str,
        model: str,
        source: str = "auto",
        manifest_role: dict[str, Any] | None = None,
    ) -> None:
        self.role = role
        self.model = model
        self.source = source
        self.manifest_role = manifest_role or {}

    @property
    def adapter_source(self) -> str:
        """Picker-source → adapter-source translation for ``SubTask.source``.

        v0.99.40 Follow-up B: the picker emits historical source names
        (``api_key`` / ``claude-cli`` / ``openai-codex`` / ``auto``). The
        v0.99.39 :class:`LLMAdapter` registry uses the paperclip-aligned
        names (``payg`` / ``subscription`` / ``adapter``). This property
        bridges the two so each agent's ``SubTask(source=...)`` call
        produces a value the spawned worker's ``AgenticLoop`` can pass
        directly into :func:`core.llm.adapters.resolve_for`.

        Returns the empty string for ``"auto"`` so unresolved picker output
        falls back to legacy routing rather than hard-failing.
        """
        return picker_source_to_adapter_source(self.source)

    @abc.abstractmethod
    async def aexecute(self, state: Any) -> SeedAgentResult:
        """Run one phase of the pipeline against ``state`` (async).

        ``state`` is the ``PipelineState`` instance (forward type to
        avoid circular import). The agent reads input fields, performs
        its work (typically via ``await self._manager.adelegate(...)``),
        and returns a ``SeedAgentResult`` whose ``output`` the
        orchestrator merges back into the state.
        """

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(role={self.role!r}, "
            f"model={self.model!r}, source={self.source!r})"
        )


def picker_source_to_adapter_source(picker_source: str) -> str:
    """Free-function variant of :attr:`BaseSeedAgent.adapter_source`.

    Used by agents that build per-voter ``SubTask`` instances (e.g.
    :class:`RankerAgent`) where each voter carries its own picker source
    name and the role-level ``self.source`` is not the right input.
    """
    if not picker_source or picker_source == "auto":
        return ""
    from plugins.seed_generation.picker import binding_to_adapter_source

    try:
        return binding_to_adapter_source(picker_source)
    except ValueError:
        return ""
