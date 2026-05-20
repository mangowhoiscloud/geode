"""Program.md-driven self-improving loop runner.

PR-G5b (2026-05-20). The runner is intentionally thin — every
component it composes already has its own PR + tests:

* ``baseline_reader.load_baseline()`` (G3) — typed BaselineSnapshot.
* ``baseline_reader.load_latest_meta_review()`` (G4) — MetaReviewSnapshot.
* ``autoresearch.train.load_wrapper_prompt_sections()`` (G5a) — SoT load.
* ``autoresearch.train.write_wrapper_prompt_sections()`` (G5a) — SoT write.

What the runner adds:

1. **Context bundling** — fetch the three snapshots into a single
   :class:`RunnerContext` dataclass.
2. **Prompt rendering** — pack the context into the program.md system
   prompt + a structured user message asking for ONE mutation.
3. **LLM dispatch** — call the injected ``llm_call`` callable; the
   default binding reads ``[self_improving_loop.mutator]`` from
   ``~/.geode/config.toml`` and dispatches through
   ``core.llm.router.call_with_failover``.
4. **Response parsing** — extract a :class:`Mutation` from the LLM's
   JSON, validate against the SoT schema.
5. **Apply + audit log** — call ``write_wrapper_prompt_sections`` and
   append the mutation to the git-tracked audit jsonl
   (``autoresearch/state/mutations.jsonl``).
6. **Optional re-run** — when ``rerun=True`` (default ``False`` to
   keep dry-runs cheap), spawn ``autoresearch/train.py`` so the next
   baseline reflects the new wrapper.

Test strategy:

* Unit tests inject a mock ``llm_call`` returning a canned JSON dict.
* No test touches real ``~/.geode/`` — all paths are monkeypatched.
* The autoresearch re-run is wrapped in ``_run_autoresearch_subprocess``
  so tests can monkeypatch the subprocess entirely.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.paths import GLOBAL_SELF_IMPROVING_LOOP_DIR
from core.paths import (
    MUTATION_AUDIT_LOG_PATH as MUTATION_AUDIT_LOG_PATH,
)

log = logging.getLogger(__name__)

__all__ = [
    "MUTATION_AUDIT_LOG_PATH",
    "Mutation",
    "Proposal",
    "RunnerContext",
    "SelfImprovingLoopRunner",
    "apply_mutation",
    "build_runner_context",
    "parse_mutation",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Mutation:
    """One LLM-proposed wrapper-section edit.

    Schema mirrors the LLM response contract (see :func:`_build_user_prompt`).
    ``target_section`` may be new (insert) or existing (rewrite); the
    runner enforces non-empty strings at apply time.

    PR-5 C-4 (2026-05-21) — added ``mutation_id`` / ``expected_dim`` /
    ``rollback_condition`` so the runner can pair each apply row with
    a follow-up attribution row keyed by ``mutation_id``. Existing
    callers that don't populate the new fields get safe defaults
    (uuid auto-generated, empty dict, empty string) so the older
    audit history stays parseable.
    """

    target_section: str
    new_value: str
    rationale: str
    target_dim: str = ""
    """The regression dim the mutation is aimed at — informational, may
    be empty when the LLM declines to commit to one."""
    target_kind: str = "prompt"
    """PR-6 C-5 — which policy SoT this mutation edits. One of:
    ``prompt`` (legacy wrapper-sections, default) / ``tool_policy`` /
    ``decomposition`` / ``retrieval`` / ``reflection``. Unknown kinds
    are rejected by :func:`apply_mutation` so the loop fails closed."""
    mutation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    """Stable identifier paired with the attribution row written after
    the next audit. Auto-generated when the LLM doesn't supply one."""
    expected_dim: dict[str, float] = field(default_factory=dict)
    """Per-dim expected delta the LLM commits to (e.g.
    ``{"safety": +0.3, "helpfulness": -0.05}``). PR-5 attribution
    computes ``observed - expected`` after the next audit so a wrong-
    direction mutation can be flagged."""
    rollback_condition: str = ""
    """Free-text condition under which the mutation should be reverted
    (e.g. ``"any dim drops more than 0.5"``). Recorded for auditability;
    enforcement is a follow-up."""

    def to_audit_row(
        self,
        *,
        previous_value: str,
        timestamp: float | None = None,
        baseline_fitness: float | None = None,
    ) -> dict[str, Any]:
        """Render the mutation as one audit-log row."""
        return {
            "ts": timestamp if timestamp is not None else time.time(),
            "kind": "applied",
            "mutation_id": self.mutation_id,
            "target_kind": self.target_kind,
            "target_section": self.target_section,
            "previous_value": previous_value,
            "new_value": self.new_value,
            "rationale": self.rationale,
            "target_dim": self.target_dim,
            "expected_dim": dict(self.expected_dim),
            "rollback_condition": self.rollback_condition,
            "baseline_fitness": baseline_fitness,
        }


@dataclass
class Proposal:
    """One propose-only result — `propose()` returns this, the caller
    decides whether to call `apply_proposal()` afterwards.

    PR-OPS-2a (2026-05-21) — splits ``run_once`` into propose/apply
    halves so the ``/self-improving run`` slash can show the operator
    the LLM's mutation candidate, wait for ``y/N`` confirmation, then
    either apply or record a ``kind=rejected`` audit row. Pre-split
    the only entry was ``run_once`` which built context, called the
    LLM, AND wrote the SoT in one shot — no confirmation seam.
    """

    mutation: Mutation
    """The LLM-proposed mutation."""

    target_sections: dict[str, str] = field(default_factory=dict)
    """Current SoT contents for ``mutation.target_kind`` — what
    ``apply_mutation`` mutates. Distinct from ``original_sections``
    only in identity; both carry the same key/value pairs at propose
    time, and ``apply_mutation`` mutates ``target_sections`` in place."""

    original_sections: dict[str, str] = field(default_factory=dict)
    """Frozen pre-apply snapshot for the rollback path. Captured at
    propose time so a subsequent ``apply_proposal`` failure can
    restore exactly the pre-mutation state."""

    baseline_fitness: float | None = None
    """The current baseline.json fitness scalar (if any), surfaced as
    a convenience for UI rendering — operator wants to see what they
    are comparing against before approving the mutation."""


@dataclass
class RunnerContext:
    """Inputs gathered from G2-G4 readers + autoresearch state.

    Held as a plain dataclass (not frozen) so the runner can carry
    additional debug fields without breaking the call site contract.

    PR-MINIMAL-2 (2026-05-21) — B2 fix-up: ``current_policies`` carries
    the *current state* of ALL 5 mutation targets
    (prompt / tool_policy / decomposition / retrieval / reflection)
    so the mutator LLM sees the full policy surface, not just the
    wrapper prompt. Pre-PR ``current_sections`` was wrapper-only —
    the LLM could "blind mutate" tool_policy / decomposition /
    retrieval / reflection without ever seeing their current values.
    ``current_sections`` is kept as an alias of
    ``current_policies["prompt"]`` for backwards compat with the
    existing readers (``_build_user_prompt``).
    """

    baseline_snapshot: Any = None
    meta_review_snapshot: Any = None
    current_sections: dict[str, str] = field(default_factory=dict)
    current_policies: dict[str, dict[str, str]] = field(default_factory=dict)
    """Map of ``target_kind`` → current policy dict. Filled by
    :func:`build_runner_context` from all 5 policy SoT files. The
    legacy ``current_sections`` field stays as a shortcut to
    ``current_policies["prompt"]``."""
    target_dim: str = ""
    """The dim the runner will focus the mutation on. Picked from
    baseline via ``pick_regression_target_dim`` when present."""


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
#
# PR-MINIMAL-2 (2026-05-21) — canonical definition for
# ``MUTATION_AUDIT_LOG_PATH`` moved to ``core/paths.py`` alongside
# the other path constants. The top-of-file re-export keeps this
# module's existing 5+ callers (tests + production) importing the
# name unchanged.


# ---------------------------------------------------------------------------
# Context gathering
# ---------------------------------------------------------------------------


def build_runner_context() -> RunnerContext:
    """Gather baseline + meta-review + ALL 5 current policy SoTs.

    All lookups are best-effort — a missing baseline / meta-review /
    SoT file just means the runner has less context to work with;
    the LLM call can still propose a mutation based on the policies
    that DID load. The auto target_dim picker fires only when the
    baseline is present.

    PR-MINIMAL-2 (2026-05-21) — B2 fix-up: loads all 5 policy SoT
    files (prompt / tool_policy / decomposition / retrieval /
    reflection) so the mutator LLM sees the full policy surface in
    its prompt. Pre-PR only ``prompt`` (wrapper-sections) was loaded;
    mutating the other 4 kinds was blind. The wrapper-only
    ``current_sections`` field stays populated for backwards compat.
    """
    from autoresearch.train import load_wrapper_prompt_sections
    from plugins.seed_generation.baseline_reader import (
        load_baseline,
        load_latest_meta_review,
        pick_regression_target_dim,
    )

    from core.self_improving_loop.policies import TARGET_KINDS, load_policy

    baseline_snapshot = load_baseline()
    meta_review_snapshot = load_latest_meta_review()
    current_sections = load_wrapper_prompt_sections()
    current_policies: dict[str, dict[str, str]] = {}
    for kind in TARGET_KINDS:
        if kind == "prompt":
            current_policies[kind] = dict(current_sections)
        else:
            current_policies[kind] = load_policy(kind)
    target_dim = ""
    if baseline_snapshot is not None:
        target_dim = pick_regression_target_dim(baseline_snapshot) or ""
    return RunnerContext(
        baseline_snapshot=baseline_snapshot,
        meta_review_snapshot=meta_review_snapshot,
        current_sections=current_sections,
        current_policies=current_policies,
        target_dim=target_dim,
    )


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


_FALLBACK_SYSTEM_PROMPT = (
    "You are the self-improving-loop mutator for GEODE, an autonomous "
    "execution agent. Your job: read the audit baseline, meta-review "
    "priors, and the current WRAPPER_PROMPT_SECTIONS dict, then propose "
    "ONE single-section mutation that should drive the next audit's "
    "fitness up.\n"
    "\n"
    "Constraints:\n"
    "- Change exactly ONE section. Adding a new section counts; "
    "deleting does not.\n"
    "- New value must be a non-empty single-paragraph string under 600 "
    "characters.\n"
    "- Rationale must cite the specific regression evidence or prior "
    "the mutation responds to.\n"
    "- Respond with a single JSON object — NO prose, NO code fences.\n"
    "\n"
    "Response schema:\n"
    "{\n"
    '  "target_section": "<section key>",\n'
    '  "new_value": "<replacement text>",\n'
    '  "rationale": "<= 200 chars, citing the evidence>",\n'
    '  "target_dim": "<dim name the mutation aims at, or empty>"\n'
    "}\n"
)
"""Inline fallback prompt used when ``autoresearch/program.md`` is unreadable.

Kept as a complete, self-contained string so a `program.md` outage (missing
file, OSError) doesn't take the runner offline. Tests that don't need the
program.md content monkeypatch :func:`_load_program_md` to skip the disk read.
"""


_MUTATION_CONTRACT_SUFFIX = (
    "\n\n"
    "## Mutation Contract (runner-specific, on top of program.md)\n"
    "\n"
    "For THIS invocation, ignore the broader autoresearch loop instructions "
    "in program.md and act as a single-shot mutator with these constraints:\n"
    "\n"
    "- Change exactly ONE section of the chosen policy SoT (the dict "
    "selected by ``target_kind`` — defaults to WRAPPER_PROMPT_SECTIONS "
    "when omitted). Adding a new section key counts as a change; "
    "deleting does NOT (the runner ignores deletions).\n"
    '- Default to ``target_kind = "prompt"`` unless the regression '
    "evidence specifically points at tool / decomposition / retrieval / "
    "reflection policy. The current user message only shows wrapper-"
    "prompt sections; non-prompt SoTs start empty until populated, so "
    "explicit operator signal should drive non-prompt mutations.\n"
    "- ``new_value`` must be a non-empty single-paragraph string under 600 "
    "characters.\n"
    "- ``rationale`` must cite the specific regression evidence or "
    "meta-review prior that motivates the change.\n"
    "- ``expected_dim`` is a small dict mapping dim name → expected delta "
    "(float in [-1, 1]); commit to which dims should move and by how much "
    "so PR-5 attribution can compute ``observed - expected`` after the "
    "next audit.\n"
    "- ``rollback_condition`` is a one-line predicate describing when this "
    'mutation should be reverted (e.g. ``"helpfulness drops below 0.4"``).\n'
    "- ``target_kind`` selects the policy SoT to mutate. One of "
    "``prompt`` (default, wrapper-sections.json), ``tool_policy`` "
    "(tool-policy.json), ``decomposition`` (decomposition.json), "
    "``retrieval`` (retrieval.json), ``reflection`` (reflection.json). "
    "Omit for prompt-level mutations.\n"
    "- Respond with a single JSON object — NO surrounding prose, NO code fences.\n"
    "\n"
    "Response schema:\n"
    "{\n"
    '  "target_section": "<section key>",\n'
    '  "new_value": "<replacement text>",\n'
    '  "rationale": "<= 200 chars, citing the evidence>",\n'
    '  "target_dim": "<dim name the mutation aims at, or empty>",\n'
    '  "target_kind": "<prompt|tool_policy|decomposition|retrieval|reflection>",\n'
    '  "expected_dim": {"<dim>": 0.0, ...},\n'
    '  "rollback_condition": "<one-line predicate, or empty>"\n'
    "}\n"
)
"""Appended to program.md so the runner can scope it to a single mutation step.

program.md (Karpathy P7 — the agent instruction document) describes the
*overall* self-improving loop: branch creation, multi-iteration ratchet,
fitness measurement etc. This runner is a single-shot step inside that loop
that proposes ONE mutation per invocation. The suffix narrows the broader
contract to the JSON output the parser expects.
"""


def _load_program_md() -> str | None:
    """Read ``autoresearch/program.md`` from disk; return ``None`` on failure.

    Resolves the path relative to the runner module so the lookup works in
    worktrees / installs where ``cwd`` doesn't match the repo root.
    Returns ``None`` (not a raised exception) on missing file / OSError so
    the runner can fall back to the inline prompt without breaking the loop.
    Tests monkeypatch this function to inject canned content.
    """
    program_md_path = Path(__file__).resolve().parents[2] / "autoresearch" / "program.md"
    try:
        return program_md_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning(
            "self-improving-loop runner: could not read %s (%s); using fallback prompt",
            program_md_path,
            exc,
        )
        return None


def _build_system_prompt() -> str:
    """Compose the system prompt: program.md body + single-mutation contract.

    G5b.fix1.b (2026-05-20) — closes the second of the Codex MCP findings on
    PR-G5b: the runner is now genuinely "program.md-driven" because the
    document is loaded and used at every invocation. When program.md is
    unreadable, the runner falls back to :data:`_FALLBACK_SYSTEM_PROMPT`
    (the previous hardcoded prompt) so the loop never goes offline due to
    a missing/corrupt instruction file.
    """
    program_md = _load_program_md()
    if program_md is None:
        return _FALLBACK_SYSTEM_PROMPT
    return program_md.rstrip() + _MUTATION_CONTRACT_SUFFIX


def _build_user_prompt(ctx: RunnerContext) -> str:
    """Render the per-iteration context as the LLM's user message."""
    from plugins.seed_generation.baseline_reader import (
        format_evidence_block,
        format_priors_block,
    )

    blocks: list[str] = []
    if ctx.baseline_snapshot is not None and ctx.target_dim:
        evidence = format_evidence_block(ctx.baseline_snapshot, ctx.target_dim)
        if evidence:
            blocks.append(evidence)
    if ctx.meta_review_snapshot is not None:
        priors = format_priors_block(ctx.meta_review_snapshot, target_dim=ctx.target_dim)
        if priors:
            blocks.append(priors)
    # PR-MINIMAL-2 (2026-05-21) — surface ALL 5 current policy SoTs
    # so the mutator LLM sees the full surface before proposing a
    # mutation. Falls back to wrapper-only (the legacy shape) when
    # ``current_policies`` is empty (older callers that built the
    # RunnerContext by hand without filling the new field).
    if ctx.current_policies:
        policies_block = "Current policy SoT (5 kinds):\n" + json.dumps(
            ctx.current_policies, indent=2, ensure_ascii=False, sort_keys=True
        )
    else:
        policies_block = "Current WRAPPER_PROMPT_SECTIONS:\n" + json.dumps(
            ctx.current_sections, indent=2, ensure_ascii=False
        )
    blocks.append(policies_block)
    if ctx.target_dim:
        blocks.append(f"Focus your mutation on improving dim: {ctx.target_dim!r}.")
    blocks.append("Return the JSON mutation object now.")
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# LLM call default + response parsing
# ---------------------------------------------------------------------------


LLMCallable = Callable[[str, str], str]
"""Signature: ``llm_call(system_prompt, user_prompt) -> raw response``."""


def _default_llm_call(system_prompt: str, user_prompt: str) -> str:
    """Mutator LLM call routed through ``core.llm.router`` (PR-1 G-A).

    Pre-PR-1 (v0.99.22) this body instantiated ``anthropic.Anthropic()``
    directly and pinned ``model="claude-opus-4-7"`` as a literal —
    paperclip-style abstraction goal: route through the same
    ``call_with_failover`` path every other provider-aware caller uses,
    and read the model id from ``[self_improving_loop.mutator]`` so the
    operator can flip provider/model without editing this file.

    Resolution order:

    1. ``~/.geode/config.toml [self_improving_loop.mutator] default_model``
       (user override).
    2. ``MutatorConfig.default_model`` ship default (``claude-opus-4-7``).

    The model id is routed through ``core.llm.router.call_with_failover``
    so the same credential / provider rotator the agentic loop uses
    also serves the mutator — no second SDK client, no second key
    store.

    Tests inject a mock callable via
    ``SelfImprovingLoopRunner(llm_call=...)`` and skip this code path
    entirely; the lazy SDK imports keep the test cold-start free of
    anthropic.
    """
    import asyncio
    import logging as _logging

    from core.config import _resolve_provider
    from core.config.self_improving_loop import load_self_improving_loop_config
    from core.llm.adapters import resolve_agentic_adapter
    from core.llm.router import call_with_failover

    cfg = load_self_improving_loop_config()
    # PR-MINIMAL-2 (2026-05-21) — G1a inherit: MutatorConfig.default_model
    # defaults to None, fall back to Settings.model so the operator's
    # ``/model`` choice flows through. Explicit override still wins.
    if cfg.mutator.default_model:
        model = cfg.mutator.default_model
    else:
        from core.config import settings

        model = settings.model
    max_tokens = cfg.mutator.max_tokens
    source = cfg.mutator.source

    # PR-MINIMAL-2 — MutatorConfig.allowed_models removed (C1). The
    # router's provider routing already guards model existence per
    # provider; the dedicated allow-list added more config surface
    # than it caught. The (formerly logged-only) contract path field
    # was also removed (A1) since the dispatch log line below already
    # carries the configured model + provider + source for telemetry
    # grouping — operator-facing contract docs at
    # ``.claude/agents/self_improving_loop_mutator.md`` remain on
    # disk as reference.

    provider = _resolve_provider(model)
    adapter = resolve_agentic_adapter(provider)

    # Mutator dispatch telemetry (one line per call) so downstream
    # Petri / Inspect viewers can group runs by operator intent.
    _logging.getLogger("core.self_improving_loop.runner").info(
        "mutator dispatch: model=%s provider=%s source=%s max_tokens=%d",
        model,
        provider,
        source,
        max_tokens,
    )

    async def _do_call(m: str) -> object:
        return await adapter.agentic_call(
            model=m,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[],
            tool_choice={"type": "auto"},
            max_tokens=max_tokens,
            temperature=0.3,
        )

    # ``call_with_failover`` is the router's async dispatcher (transport
    # layer) — accepts an ordered model list. PR-1 keeps it single-
    # element so the M5 silent-fallback knob default is preserved; an
    # operator who wants the mutator to fall through to alternate models
    # populates ``MutatorConfig.allowed_models`` and the dispatcher's
    # ``models`` list is expanded in a follow-up PR.
    response, _used_model = asyncio.run(call_with_failover([model], _do_call))
    if response is None:
        last_err = getattr(adapter, "last_error", None)
        raise RuntimeError(
            f"mutator LLM call failed (model={model}, provider={provider}): {last_err!r}"
        )

    # Adapter normalises to AgenticResponse — concatenate text blocks.
    text_chunks: list[str] = []
    for block in getattr(response, "content", []):
        text = getattr(block, "text", "")
        if text:
            text_chunks.append(text)
    text = "".join(text_chunks)
    if not text:
        # Empty text is a known anti-pattern surface (``parse_mutation``
        # raises ValueError downstream); callers that catch it can retry,
        # but failing fast here keeps the error message targeted instead
        # of letting JSON parsing carry the blame.
        raise RuntimeError(
            f"mutator LLM call returned empty text "
            f"(model={model}, provider={provider}, used={_used_model!r})"
        )
    return text


def parse_mutation(raw: str) -> Mutation:
    """Extract a :class:`Mutation` from the LLM's raw response.

    The model is instructed to emit a bare JSON object, but defensive
    parsing tolerates leading/trailing whitespace and (rarely) a
    surrounding triple-backtick code fence — strip those before json.loads.

    Raises :class:`ValueError` on missing fields or wrong types so the
    runner can catch + log + skip a malformed iteration without
    crashing the whole loop.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("empty LLM response")
    text = raw.strip()
    if text.startswith("```"):
        # Strip fence: ```json ... ```
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"LLM response must be a JSON object, got {type(payload).__name__}")
    target_section = payload.get("target_section")
    new_value = payload.get("new_value")
    rationale = payload.get("rationale", "")
    target_dim = payload.get("target_dim", "")
    if not isinstance(target_section, str) or not target_section.strip():
        raise ValueError("target_section must be a non-empty string")
    if not isinstance(new_value, str) or not new_value.strip():
        raise ValueError("new_value must be a non-empty string")
    if not isinstance(rationale, str):
        raise ValueError("rationale must be a string")
    if not isinstance(target_dim, str):
        raise ValueError("target_dim must be a string")
    if len(new_value) > 600:
        raise ValueError(f"new_value length {len(new_value)} exceeds 600 char cap")
    # PR-5 C-4 — optional attribution fields. The LLM is *encouraged* to
    # supply them via the system prompt, but missing fields fall through
    # to safe defaults (uuid auto-generated, empty expectation dict,
    # empty rollback condition) so older LLM responses + tests that
    # don't construct the new schema still parse.
    expected_raw = payload.get("expected_dim", {})
    expected_dim: dict[str, float] = {}
    if isinstance(expected_raw, dict):
        for k, v in expected_raw.items():
            # ``bool`` is an ``int`` subclass — exclude it explicitly so
            # ``{"safety": true}`` doesn't silently become ``1.0`` (Codex
            # MCP review #1 catch — "float expected delta" must be a
            # genuine numeric, not a coerced bool).
            if isinstance(k, str) and isinstance(v, int | float) and not isinstance(v, bool):
                expected_dim[k] = float(v)
    rollback_raw = payload.get("rollback_condition", "")
    rollback_condition = rollback_raw.strip() if isinstance(rollback_raw, str) else ""
    # PR-6 C-5 — target_kind dispatches to the policy SoT file. Default
    # ``prompt`` keeps the legacy wrapper-sections behaviour so older
    # mutation rows replay unchanged. Unknown kinds raise ValueError so
    # the loop fails closed (caught and logged by SelfImprovingLoopRunner).
    from core.self_improving_loop.policies import TARGET_KINDS

    kind_raw = payload.get("target_kind", "prompt")
    if not isinstance(kind_raw, str):
        raise ValueError(f"target_kind must be a string, got {type(kind_raw).__name__}")
    target_kind = kind_raw.strip() or "prompt"
    if target_kind not in TARGET_KINDS:
        raise ValueError(f"target_kind {target_kind!r} is not one of {TARGET_KINDS!r}")
    mutation_id_raw = payload.get("mutation_id")
    # Mutation has a default_factory; pass only when the LLM supplied one.
    if isinstance(mutation_id_raw, str) and mutation_id_raw.strip():
        return Mutation(
            target_section=target_section.strip(),
            new_value=new_value,
            rationale=rationale.strip(),
            target_dim=target_dim.strip(),
            target_kind=target_kind,
            mutation_id=mutation_id_raw.strip(),
            expected_dim=expected_dim,
            rollback_condition=rollback_condition,
        )
    return Mutation(
        target_section=target_section.strip(),
        new_value=new_value,
        rationale=rationale.strip(),
        target_dim=target_dim.strip(),
        target_kind=target_kind,
        expected_dim=expected_dim,
        rollback_condition=rollback_condition,
    )


# ---------------------------------------------------------------------------
# Apply + audit log
# ---------------------------------------------------------------------------


def apply_mutation(
    mutation: Mutation,
    *,
    current_sections: dict[str, str] | None = None,
) -> tuple[dict[str, str], str]:
    """Apply a single-section mutation to the SoT.

    Returns ``(new_sections, previous_value)``. ``previous_value`` is
    the string the mutation replaced (empty for insertions) — captured
    so the audit log can record the diff.

    PR-6 C-5 — dispatches on ``mutation.target_kind``. The
    ``prompt`` kind uses the legacy
    ``autoresearch.train.write_wrapper_prompt_sections`` writer so
    schema enforcement (single-paragraph 600-char cap) is preserved.
    The other four kinds go through
    :func:`core.self_improving_loop.policies.write_policy` which is
    a generic ``dict[str, str]`` writer with atomic temp-file rewrite.
    """
    from autoresearch.train import load_wrapper_prompt_sections, write_wrapper_prompt_sections

    from core.self_improving_loop.policies import load_policy, write_policy

    if mutation.target_kind == "prompt":
        sections = (
            dict(current_sections)
            if current_sections is not None
            else load_wrapper_prompt_sections()
        )
        previous_value = sections.get(mutation.target_section, "")
        sections[mutation.target_section] = mutation.new_value
        write_wrapper_prompt_sections(sections)
        return sections, previous_value

    # PR-6 policy kinds — tool_policy / decomposition / retrieval /
    # reflection. ``current_sections`` override is honoured for symmetry
    # with the prompt branch (tests inject pre-populated dicts).
    sections = (
        dict(current_sections)
        if current_sections is not None
        else load_policy(mutation.target_kind)
    )
    previous_value = sections.get(mutation.target_section, "")
    sections[mutation.target_section] = mutation.new_value
    write_policy(mutation.target_kind, sections)
    return sections, previous_value


def append_audit_log(
    mutation: Mutation,
    *,
    previous_value: str,
    baseline_fitness: float | None = None,
    log_path: Path | None = None,
) -> Path:
    """Append one mutation row to the git-tracked audit jsonl.

    Returns the path of the audit log so the caller can ``git add``
    it. Best-effort — directory is created if missing.
    """
    target = log_path if log_path is not None else MUTATION_AUDIT_LOG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    row = mutation.to_audit_row(previous_value=previous_value, baseline_fitness=baseline_fitness)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return target


# ---------------------------------------------------------------------------
# Git commit + autoresearch re-run
# ---------------------------------------------------------------------------


def _git_commit_audit_log(
    log_path: Path,
    *,
    mutation: Mutation,
    runner: subprocess.CompletedProcess[str] | None = None,
) -> bool:
    """Stage + commit the audit log row.

    Returns ``True`` on success, ``False`` when git is unavailable or
    the commit fails. The runner treats commit failure as
    non-blocking: the SoT is already updated in-place, so the loop's
    correctness boundary is the file write, not the git commit.

    ``runner`` is exposed so tests can inject a mock that records the
    argv without running real git.
    """
    try:
        repo_root = log_path.resolve().parents[1]
        subprocess.run(  # noqa: S603  # nosec B603 — argv = audit-log path
            ["git", "add", str(log_path)],  # noqa: S607  # nosec B607 — git in PATH
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
        )
        commit_message = (
            f"self-improving-loop: mutate '{mutation.target_section}'\n\n"
            f"target_dim: {mutation.target_dim or '(unspecified)'}\n"
            f"rationale: {mutation.rationale}\n"
        )
        subprocess.run(  # noqa: S603  # nosec B603 — commit_message from validated Mutation
            ["git", "commit", "-m", commit_message],  # noqa: S607  # nosec B607 — git in PATH
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        log.warning("self-improving-loop git commit failed: %s", exc)
        return False
    return True


def _run_autoresearch_subprocess(
    *,
    repo_root: Path,
    dry_run: bool,
) -> subprocess.CompletedProcess[str]:
    """Spawn ``autoresearch/train.py`` for the post-mutation audit.

    Default ``dry_run=True`` keeps the loop cheap during development;
    operators flip to ``dry_run=False`` for a real budget-spending
    audit. The subprocess is non-fatal — failures log + return so the
    runner can record the mutation row even when the audit aborts.
    """
    argv = ["uv", "run", "python", "autoresearch/train.py"]
    if dry_run:
        argv.append("--dry-run")
    return subprocess.run(  # noqa: S603  # nosec B603 — argv built from constants
        argv,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class SelfImprovingLoopRunner:
    """Top-level runner — composes context + LLM + apply + audit + re-run.

    Construction parameters:

    * ``llm_call`` — injected callable. Defaults to
      :func:`_default_llm_call` (reads ``MutatorConfig`` + dispatches
      through ``core.llm.router.call_with_failover``); tests pass a mock.
    * ``audit_log_path`` — override for the audit jsonl location
      (tests).
    * ``commit_enabled`` — when ``False``, skip the git step
      (useful for dry-runs / detached HEAD).
    * ``rerun_enabled`` — when ``False`` (default), skip the
      autoresearch re-run. The next ``geode audit`` invocation picks
      up the new SoT automatically; the re-run flag is opt-in so
      operators control quota spend.
    * ``rerun_dry_run`` — when re-run is enabled, default to
      ``--dry-run`` to keep the loop cheap.
    """

    llm_call: LLMCallable = field(default=_default_llm_call)
    audit_log_path: Path | None = None
    commit_enabled: bool = True
    rerun_enabled: bool = False
    rerun_dry_run: bool = True

    def propose(self) -> Proposal:
        """Build context, call the mutator LLM, parse one Mutation.

        Stops BEFORE any SoT write. Returns a :class:`Proposal` the
        caller can show the operator for confirmation; calling
        :meth:`apply_proposal` afterwards persists the mutation.

        Raises :class:`ValueError` on parse / validation failure.

        Steps:

        1. Build context (baseline + meta-review + current sections).
        2. Call the LLM with the system + user prompt.
        3. Parse + validate the mutation.
        4. Load the correct SoT for the parsed ``target_kind`` (kind-
           aware so a tool_policy mutation reads tool-policy.json, not
           wrapper-sections.json).

        ``target_sections`` and ``original_sections`` carry identical
        contents at this point; the latter is the rollback snapshot,
        the former is what :func:`apply_mutation` mutates in place.
        """
        ctx = build_runner_context()
        user_prompt = _build_user_prompt(ctx)
        raw_response = self.llm_call(_build_system_prompt(), user_prompt)
        mutation = parse_mutation(raw_response)
        # PR-6 C-5 (Codex MCP catch) — apply_mutation dispatches by
        # target_kind, but ctx.current_sections is *always* the wrapper-
        # prompt sections (built by build_runner_context). Passing those
        # into a non-prompt apply would write wrapper-prompt contents
        # into the wrong SoT file. Load the *correct* starting policy
        # based on the parsed mutation's kind so the dispatcher writes
        # the right destination. ``original_sections`` is captured AFTER
        # the kind-aware load so rollback restores the matching SoT.
        from core.self_improving_loop.policies import load_policy

        if mutation.target_kind == "prompt":
            target_sections = dict(ctx.current_sections)
        else:
            target_sections = load_policy(mutation.target_kind)
        original_sections = dict(target_sections)
        baseline_fitness: float | None = None
        snapshot = ctx.baseline_snapshot
        if snapshot is not None:
            raw_fitness = getattr(snapshot, "fitness", None)
            if isinstance(raw_fitness, int | float):
                baseline_fitness = float(raw_fitness)
        return Proposal(
            mutation=mutation,
            target_sections=target_sections,
            original_sections=original_sections,
            baseline_fitness=baseline_fitness,
        )

    def apply_proposal(self, proposal: Proposal) -> Mutation:
        """Apply a previously-proposed mutation — write SoT, audit
        log, (optional) git commit, (optional) autoresearch rerun.

        Steps 4-6 of the original ``run_once``. The caller (slash
        handler / tool / scheduler) is responsible for showing the
        operator the proposal and gating this method on consent.

        ``proposal.target_sections`` is mutated in place by
        :func:`apply_mutation`. The G5b.fix3 atomicity boundary stays
        intact: if the audit-log write fails after the SoT mutation
        lands, the SoT is rolled back to
        ``proposal.original_sections`` and the original exception
        propagates so the caller can retry.
        """
        _new_sections, previous_value = apply_mutation(
            proposal.mutation, current_sections=proposal.target_sections
        )
        try:
            log_path = append_audit_log(
                proposal.mutation,
                previous_value=previous_value,
                log_path=self.audit_log_path,
            )
        except OSError as exc:
            self._rollback_sot(proposal.original_sections, mutation=proposal.mutation, exc=exc)
            raise
        if self.commit_enabled:
            _git_commit_audit_log(log_path, mutation=proposal.mutation)
        if self.rerun_enabled:
            repo_root = log_path.resolve().parents[1]
            self._invoke_autoresearch(repo_root)
        self._append_self_improving_loop_index(proposal.mutation, previous_value)
        return proposal.mutation

    def run_once(self) -> Mutation:
        """Execute one full propose+apply iteration. Backwards-compat
        wrapper around :meth:`propose` + :meth:`apply_proposal` so
        existing callers (and the autoresearch self-improving loop)
        keep working unchanged.

        Raises :class:`ValueError` on parse / validation failure so
        the caller can decide whether to retry.
        """
        return self.apply_proposal(self.propose())

    @staticmethod
    def _rollback_sot(
        original_sections: dict[str, str],
        *,
        mutation: Mutation,
        exc: OSError,
    ) -> None:
        """Restore the SoT to ``original_sections`` after a post-apply failure.

        G5b.fix3 — invoked from ``run_once`` when
        :func:`append_audit_log` raises ``OSError`` *after*
        :func:`apply_mutation` has already written the new sections to
        disk. The SoT must be rolled back to the pre-mutation state so
        the loop never persists a mutation that has no audit-log row;
        otherwise the git-as-optimiser ledger and the live state would
        diverge silently.

        Rollback failure is itself logged but never raised in place of
        the original ``exc`` — the caller already has the more useful
        signal (audit-log write failed).

        PR-6 C-5 (Codex MCP catch) — rollback dispatches on
        ``mutation.target_kind``. The prompt kind still writes through
        ``autoresearch.train.write_wrapper_prompt_sections`` (legacy
        schema enforcement); the four policy kinds go through
        ``write_policy`` so the right SoT is restored.
        """
        try:
            if mutation.target_kind == "prompt":
                from autoresearch.train import write_wrapper_prompt_sections

                write_wrapper_prompt_sections(original_sections)
            else:
                from core.self_improving_loop.policies import write_policy

                write_policy(mutation.target_kind, original_sections)
            log.error(
                "self-improving-loop runner: audit-log write failed (%s); "
                "SoT rolled back to pre-mutation state for kind %r section %r",
                exc,
                mutation.target_kind,
                mutation.target_section,
            )
        except Exception:  # pragma: no cover — defensive
            log.exception(
                "self-improving-loop runner: audit-log write failed (%s) AND "
                "rollback failed — SoT may be in a divergent state for "
                "section %r",
                exc,
                mutation.target_section,
            )

    def _invoke_autoresearch(self, repo_root: Path) -> None:
        """Wrap the autoresearch subprocess so tests can override."""
        try:
            _run_autoresearch_subprocess(repo_root=repo_root, dry_run=self.rerun_dry_run)
        except Exception:  # pragma: no cover — defensive
            log.warning("self-improving-loop autoresearch re-run failed", exc_info=True)

    @staticmethod
    def _append_self_improving_loop_index(mutation: Mutation, previous_value: str) -> None:
        """Best-effort append to the shared session index.

        Lets the existing ``~/.geode/self-improving-loop/sessions.jsonl``
        registry (P1a) carry one row per mutator invocation so external
        consumers can see the mutator alongside seed-generation /
        autoresearch runs.
        """
        index_path = GLOBAL_SELF_IMPROVING_LOOP_DIR / "sessions.jsonl"
        try:
            GLOBAL_SELF_IMPROVING_LOOP_DIR.mkdir(parents=True, exist_ok=True)
            row = {
                "ts": time.time(),
                "component": "self-improving-loop-mutator",
                "target_section": mutation.target_section,
                "target_dim": mutation.target_dim,
                "rationale": mutation.rationale,
                "previous_value_len": len(previous_value),
                "new_value_len": len(mutation.new_value),
            }
            with index_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            log.debug("self-improving-loop sessions.jsonl append failed", exc_info=True)
