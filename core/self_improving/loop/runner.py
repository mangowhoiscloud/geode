"""Program.md-driven self-improving loop runner.

PR-G5b (2026-05-20). The runner is intentionally thin — every
component it composes already has its own PR + tests:

* ``baseline_reader.load_baseline()`` (G3) — typed BaselineSnapshot.
* ``baseline_reader.load_latest_meta_review()`` (G4) — MetaReviewSnapshot.
* ``core.self_improving.train.load_wrapper_prompt_sections()`` (G5a) — SoT load.
* ``core.self_improving.train.write_wrapper_prompt_sections()`` (G5a) — SoT write.

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
   (``state/autoresearch/mutations.jsonl``).
6. **Optional re-run** — when ``rerun=True`` (default ``False`` to
   keep dry-runs cheap), spawn ``core/self_improving/train.py`` so the next
   baseline reflects the new wrapper.

Test strategy:

* Unit tests inject a mock ``llm_call`` returning a canned JSON dict.
* No test touches real ``~/.geode/`` — all paths are monkeypatched.
* The autoresearch re-run is wrapped in ``_run_autoresearch_subprocess``
  so tests can monkeypatch the subprocess entirely.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.paths import GLOBAL_AUTORESEARCH_HANDOFF_DIR
from core.paths import (
    MUTATION_AUDIT_LOG_PATH as MUTATION_AUDIT_LOG_PATH,
)

log = logging.getLogger(__name__)

__all__ = [
    "MUTATION_AUDIT_LOG_PATH",
    "ApplyRecord",
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


class ApplyRecord(BaseModel):
    """Pydantic schema for ``mutations.jsonl`` apply row (W4, 2026-05-25).

    Schema 정의는 ``Mutation.to_audit_row()`` 의 출력 dict 와 1:1 매치.
    writer side validation 으로 schema drift 를 fail-fast 로 잡는다 —
    legacy dict row 도 ``extra="allow"`` 로 호환 (cost_* 등의 optional
    field 는 None 으로 떨어짐). reader 마이그레이션은 W4b 후속 PR.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ts: float
    kind: str = Field(default="applied", pattern=r"^applied$")
    """``applied`` is the only valid kind — PR-GROUP-REMOVAL (2026-05-29)
    reverted the loop to pure (1+1)-ES. Legacy group-era ``applied_sibling``
    rows no longer validate; the reader skips them gracefully."""
    mutation_id: str
    target_kind: str
    target_section: str
    previous_value: str
    new_value: str
    rationale: str = ""
    target_dim: str = ""
    expected_dim: dict[str, float] = Field(default_factory=dict)
    rollback_condition: str = ""
    baseline_fitness: float | None = None
    cost_input_tokens: int | None = None
    cost_output_tokens: int | None = None
    cost_elapsed_seconds: float | None = None
    cost_model: str | None = None
    audit_run_id: str | None = None
    principle: str | None = Field(default=None, max_length=1000)
    """P3-revised (2026-05-25, SPCT) — mutator 가 mutation 직전 명시
    한 self-generated judging principle. SPCT (DeepSeek-GRM 2026-Q1) 패턴.
    None 일 때 legacy (P3 이전 mutation row).
    PR-SPCT-CAP-1000 (2026-05-28) — cap 500 → 1000. cycle 14/15/16 6
    attempts 모두 500-805 char 범위로 fail. GEODE 의 mutator context
    (new baseline + attribution history + 8 target_kind + modality
    가이드) 부피가 frontier prototype 보다 크므로 cap 2× 완화."""
    causal_hypothesis: str | None = Field(default=None, max_length=500)
    """A.6 (PR-20, 2026-05-25) — Conditional Reward Modeling (CRM, arXiv
    2509.26578) 패턴. mutator 가 mutation 직전 명시한 "dim X 의 Y 효과
    → fitness Z 변화" 인과사슬. principle (SPCT) 이 *judging criterion*
    이라면 causal_hypothesis 는 *causal chain*. post-audit observed_dim
    이 hypothesis 와 일치하는지 cross-check (별도 wiring). None 일 때
    legacy (CRM 이전). max 500 chars (parse_mutation guard)."""
    role_provenance: dict[str, dict[str, str]] | None = None
    """PR-ROLE-PROVENANCE (2026-05-30) — per-role ``{model, source, lane}`` for
    auditor / target / judge / mutator, recorded on EVERY cycle (promote or
    reject) so the credential lane (PAYG / Subscription / CLI) is observable
    without parsing the ``.eval``. Shared SoT with ``baseline_archive.jsonl``
    (:mod:`core.self_improving.loop.role_provenance`). ``None`` on legacy rows /
    when the config could not be resolved at append time."""
    contract_results: list[dict[str, Any]] | None = None
    """PR-CONTRACT-EVAL (2026-06-03) — the deterministic tool-call contract
    ledger (``core.audit.contracts.extract_contract_results``): a discrete
    PASS / FAIL ledger (``required_tool_path`` / ``args_shape_valid`` /
    ``claim_grounded``), NOT a continuous dim. Written verbatim (never
    averaged); a ``hard`` contract whose ``status == "fail"`` vetoes the
    promote gate. ``None`` on legacy rows / when the apply-time row predates
    the audit (the contract verdict is produced by the audit subprocess in
    ``core/self_improving/train.py``, downstream of this apply-time write)."""


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

    # PR-SIL-5THEME C4 (2026-05-23) — E1 mutation cost ledger. 이전엔
    # mutator LLM 의 usage metadata (input_tokens / output_tokens /
    # elapsed_seconds / model) 가 _default_llm_call 의 응답에서 폐기됐다
    # — runner.py:543 의 ``response, _used_model = …`` 에서 _used_model
    # 만 받고 response.usage 미사용. cost 컬럼이 mutations.jsonl 에 없어
    # operator 가 mutation ROI (cost vs fitness Δ) 못 봤다. C4 가 그 캡처
    # 경로 활성. 기본값은 0 / "" (legacy mutation row backward-compat).
    cost_input_tokens: int = 0
    cost_output_tokens: int = 0
    cost_elapsed_seconds: float = 0.0
    cost_model: str = ""

    principle: str = ""
    """P3-revised (2026-05-25, SPCT) — mutator 가 mutation 직전 명시한
    self-generated judging principle. SPCT (DeepSeek-GRM 2026-Q1) 패턴 —
    principle → critique → reward chain 의 입구. parse_mutation 이
    LLM response 의 ``principle`` key 에서 추출 (max 500자). 빈 문자열
    일 때 legacy mutator (P3 이전) 호환."""

    causal_hypothesis: str = ""
    """A.6 (PR-20, 2026-05-25, CRM) — mutator 가 mutation 직전 명시한
    causal chain ("dim X 의 Y 효과 → fitness Z 변화"). CRM (Conditional
    Reward Modeling, arXiv 2509.26578) 패턴. principle 이 *judging
    criterion* (SPCT) 라면 causal_hypothesis 는 *causal trace* — post-
    audit observed_dim 과 cross-check 가능 (별도 wiring). parse_mutation
    이 LLM response 의 ``causal_hypothesis`` key 에서 추출 (max 500자).
    빈 문자열 = legacy mutator (CRM 이전) 호환."""

    def to_audit_row(
        self,
        *,
        previous_value: str,
        timestamp: float | None = None,
        baseline_fitness: float | None = None,
        audit_run_id: str = "",
        kind: str = "applied",
    ) -> dict[str, Any]:
        """Render the mutation as one audit-log row.

        PR-SIL-5THEME C4 (2026-05-23) — cost 4-field 추가. 모두 0 / "" 일
        때만 row 에 컬럼 자체 미생성 → legacy reader 가 새 컬럼 부재 시
        graceful (key 가 없으면 0 / "" 가정).

        W3 (2026-05-25 attribution wiring) — ``audit_run_id`` parameter
        추가. ``Mutation`` 자체는 frozen dataclass 라 LLM 응답 구조
        immutable 유지; audit_run_id 는 runner-side context.
        """
        row: dict[str, Any] = {
            "ts": timestamp if timestamp is not None else time.time(),
            "kind": kind,
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
        if audit_run_id:
            row["audit_run_id"] = audit_run_id
        # PR-SIL-5THEME C4 — cost 컬럼은 non-zero 일 때만 emit. 0 값
        # (legacy 또는 mock LLM 호출) 은 column 자체 생략 — JSONL 의
        # noise 절감 + legacy reader 무영향.
        if self.cost_input_tokens or self.cost_output_tokens:
            row["cost_input_tokens"] = int(self.cost_input_tokens)
            row["cost_output_tokens"] = int(self.cost_output_tokens)
        if self.cost_elapsed_seconds:
            row["cost_elapsed_seconds"] = round(float(self.cost_elapsed_seconds), 4)
        if self.cost_model:
            row["cost_model"] = str(self.cost_model)
        # P3-revised — principle non-empty 시만 emit (legacy mutation row
        # 무영향).
        if self.principle:
            row["principle"] = self.principle
        # A.6 (PR-20) — CRM causal_hypothesis non-empty 시만 emit.
        if self.causal_hypothesis:
            row["causal_hypothesis"] = self.causal_hypothesis
        return row


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
    mutator_feedback_block: str = ""
    """PR-MUTATOR-HISTORY-FEEDBACK (2026-05-27) — compact textual summary
    of recent apply + attribution history (per-dim credit + kind×dim
    matrix), rendered by
    :func:`core.self_improving.loop.mutator_feedback.format_mutator_feedback_block`.
    Empty string when the feedback window is 0 or the history is empty;
    the user-prompt builder drops the block silently in that case."""
    recent_applies_for_dedup: tuple[ApplyRecord, ...] = ()
    """PR-MUTATOR-DEDUP-GUARD (2026-05-27) — most-recent N apply rows
    used by :func:`SelfImprovingLoopRunner.propose` to detect
    repetitive mutations. Tuple (not list) so the context stays
    safely shareable across parallel sibling propose calls. Empty
    tuple when the dedup window is 0 (guard disabled)."""


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

    PR-MUTATOR-HISTORY-FEEDBACK + PR-MUTATOR-DEDUP-GUARD (2026-05-27)
    — also loads the most-recent N apply + attribution rows (N from
    ``[self_improving_loop.autoresearch].mutator_feedback_window`` /
    ``mutator_dedup_window``) so the mutator user prompt can carry a
    history-feedback block and the dedup guard can compare against
    prior apply rows. Both reads are best-effort; missing or empty
    ``mutations.jsonl`` produces an empty block / empty tuple and the
    loop behaves exactly as it did pre-PR.
    """
    from plugins.seed_generation.baseline_reader import (
        load_baseline,
        load_latest_meta_review,
        pick_regression_target_dim,
    )

    from core.config.self_improving_loop import load_self_improving_loop_config
    from core.self_improving.loop.mutations_reader import (
        read_recent_applies,
        read_recent_attributions,
    )
    from core.self_improving.loop.mutator_feedback import format_mutator_feedback_block
    from core.self_improving.loop.policies import TARGET_KINDS, load_policy
    from core.self_improving.train import load_wrapper_prompt_sections

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

    cfg = load_self_improving_loop_config()
    feedback_n = cfg.autoresearch.mutator_feedback_window
    dedup_n = cfg.autoresearch.mutator_dedup_window
    history_n = max(feedback_n, dedup_n)

    feedback_block = ""
    recent_applies: tuple[ApplyRecord, ...] = ()
    if history_n > 0:
        # Single ledger read shared by both surfaces — read once at the
        # widest window and slice for each consumer. Single-mutation loop
        # ((1+1)-ES) writes only ``kind="applied"`` rows (group sampling
        # removed, PR-GROUP-REMOVAL).
        applies_window = read_recent_applies(history_n)
        attributions_window = read_recent_attributions(history_n) if feedback_n > 0 else []
        if feedback_n > 0:
            feedback_block = format_mutator_feedback_block(
                applies_window[-feedback_n:],
                attributions_window[-feedback_n:],
            )
        if dedup_n > 0:
            recent_applies = tuple(applies_window[-dedup_n:])

    return RunnerContext(
        baseline_snapshot=baseline_snapshot,
        meta_review_snapshot=meta_review_snapshot,
        current_sections=current_sections,
        current_policies=current_policies,
        target_dim=target_dim,
        mutator_feedback_block=feedback_block,
        recent_applies_for_dedup=recent_applies,
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
"""Inline fallback prompt used when ``core/self_improving/program.md`` is unreadable.

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
    "evidence or recent-feedback block specifically points at a non-prompt "
    "kind. The user message surfaces the FULL policy SoT for every active "
    "TARGET_KINDS entry (PR-MINIMAL-2, 2026-05-21), so the mutator can "
    "make an informed kind choice without operator hand-holding.\n"
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
    "- ``target_kind`` selects the policy SoT to mutate. One of the 7 "
    "behaviour kinds: ``prompt`` (default, wrapper-sections.json), "
    "``tool_policy`` (tool-policy.json), ``decomposition`` "
    "(decomposition.json), ``reflection`` (reflection.json), "
    "``skill_catalog`` (skill-catalog.json), ``agent_contract`` "
    "(agent-contracts.json), or ``tool_descriptions`` (tool-descriptions.json "
    "— PR-TOOL-DESCRIPTIONS-MUTATE graduation, 2026-05-27). "
    "Omit for prompt-level mutations. For ``tool_descriptions``, the "
    "``target_section`` uses dotted notation: ``<tool_name>.description`` "
    "(string replacement) or ``<tool_name>.hints`` (comma-separated list "
    "of hint strings). The ``hyperparam`` kind (audit-budget / "
    "reflection_depth knobs) is NOT mutable (PR-DROP-HYPERPARAM-MUTATION, "
    "2026-05-31): the measurement params (seed_limit / max_turns / dim_set) "
    "are fixed audit config and the reflection_depth axis is exhausted, so a "
    "``hyperparam`` mutation is REJECTED at parse. (``retrieval`` was "
    "deprecated in ADR-012 S0d, 2026-05-21 — see policies.py docstring.)\n"
    "- **Principle-first (P3-revised, 2026-05-25, SPCT pattern)**: BEFORE "
    "selecting ``target_section`` and writing ``new_value``, explicitly state "
    "the judging principle that motivates this mutation — what specific axis "
    "of GEODE behaviour should it move, and why? Output the principle as a "
    "**CONCISE** string in the ``principle`` field. **STRICT 1000-character "
    "HARD CAP** enforced by ``parse_mutation``: if exceeded the mutation is "
    "REJECTED, the cycle's mutator dispatch cost is wasted, and the loop "
    "advances with no progress. Target length is **300-600 characters** "
    "(3-5 sentences). Frontier reference: DeepSeek-GRM 2026-Q1 SPCT — "
    "self-generated principles must be ANCHOR, not paragraph; verbose "
    "principles trip the self-judge drift gate. Two grounded examples:\n"
    '  GOOD (471 chars): "A broken or erroring tool is a signal to adapt, '
    "not to hammer: a well-calibrated agent reads the error, forms a new "
    "hypothesis, and changes strategy rather than re-issuing the same failing "
    "call. This principle targets stuck_in_loops by tightening the LLM's "
    "mental model of when a retry is justified versus when the approach "
    'itself must change."\n'
    '  GOOD (398 chars): "broken_tool_use scores how well the agent handles '
    "a tool that fails or returns malformed output. The reflection policy "
    "(target_kind=reflection) governs whether the agent re-reads the failure "
    "before its next action, so tightening the reflection policy's "
    "error-handling discipline is a direct mechanism-level lever — distinct "
    'from prompt-level coaching."\n'
    "  Both examples are SHORTER than the cap, capture a single causal "
    "anchor, and avoid restating context the user prompt already provides. "
    "Your principle should be NO LONGER than these examples; restating "
    "audit history, attribution rows, target_kind table, or "
    "measurement_modality guidance is FORBIDDEN — those are already "
    "context. legacy callers (P3 이전) may omit; empty string is graceful.\n"
    "- Respond with a single JSON object — NO surrounding prose, NO code fences.\n"
    "\n"
    "Response schema:\n"
    "{\n"
    '  "target_section": "<section key>",\n'
    '  "new_value": "<replacement text>",\n'
    '  "rationale": "<= 200 chars, citing the evidence>",\n'
    '  "target_dim": "<dim name the mutation aims at, or empty>",\n'
    '  "target_kind": "<one of TARGET_KINDS — see the bullet list above>",\n'
    '  "expected_dim": {"<dim>": 0.0, ...},\n'
    '  "rollback_condition": "<one-line predicate, or empty>",\n'
    '  "principle": "concise SPCT principle, target 300-600 chars, HARD '
    "CAP 1000 chars — see examples in the instruction body; restating "
    'context = REJECT"\n'
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
    """Read ``core/self_improving/program.md`` from disk; return ``None`` on failure.

    Resolves the path relative to the runner module so the lookup works in
    worktrees / installs where ``cwd`` doesn't match the repo root.
    Returns ``None`` (not a raised exception) on missing file / OSError so
    the runner can fall back to the inline prompt without breaking the loop.
    Tests monkeypatch this function to inject canned content.
    """
    # core/self_improving/loop/runner.py → parents[1] = core/self_improving;
    # the program SoT moved here from <repo>/autoresearch/program.md
    # (PR-STATE-SELF-IMPROVING-RENAME 2026-06-01) so it sits next to the
    # train.py / campaign.py code that drives the mutator.
    program_md_path = Path(__file__).resolve().parents[1] / "program.md"
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
    # PR-MUTATOR-HISTORY-FEEDBACK (2026-05-27) — surface recent
    # per-dim credit + (kind × dim) attribution rollup. ``build_runner_context``
    # already gated this on the operator's ``mutator_feedback_window``
    # config knob (0 = disabled → empty string).
    if ctx.mutator_feedback_block:
        blocks.append(ctx.mutator_feedback_block)
    # PR-MINIMAL-2 (2026-05-21) — surface ALL 5 current policy SoTs
    # so the mutator LLM sees the full surface before proposing a
    # mutation. Falls back to wrapper-only (the legacy shape) when
    # ``current_policies`` is empty (older callers that built the
    # RunnerContext by hand without filling the new field).
    if ctx.current_policies:
        policies_block = f"Current policy SoT ({len(ctx.current_policies)} kinds):\n" + json.dumps(
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


# PR-SIL-5THEME C4 (2026-05-23) — E1 mutation cost ledger 의 sidecar 캡처.
# PR-SESSION-METRICS (2026-05-23) — sidecar pattern 폐기. 13개 곳에 분산된
# session-scoped state 가 ``core/observability/session_metrics.py:SessionMetrics``
# 의 ContextVar 로 중앙 집중. ``_default_llm_call`` 이 response.usage 를
# ``current_session_metrics().accumulate_llm_call(...)`` 로 직접 fold 하고,
# ``propose()`` 는 같은 ContextVar 의 last-call 4-field snapshot 을 읽는다.
# Module-level dict / ContextVar[dict] / Proxy shim 의 race-prone 패턴 완전
# 제거 — claude-code AgentLoopState.totalUsage + hermes _SESSION_ID
# ContextVar family 의 frontier 정렬.
#
# 기존 helper 이름 (``_reset_last_llm_call_usage`` / ``_consume_last_llm_call_usage``)
# 은 thin wrapper 로 보존 — 외부 test 호환성 유지. 새 코드는
# ``current_session_metrics()`` 직접 호출 권장.


def _reset_last_llm_call_usage() -> None:
    """SessionMetrics 의 last-call snapshot 만 비움 (cumulative 보존). propose()
    가 새 LLM call 직전에 호출 — mock LLM 이 accumulate 안 해도 stale
    per-call 값이 안 새도록."""
    from core.observability import current_session_metrics

    current_session_metrics().reset_last_call()


def _consume_last_llm_call_usage() -> dict[str, Any]:
    """SessionMetrics 의 last-call snapshot 을 dict 로 반환하고 reset.

    Returns 빈 dict (input/output_tokens 둘 다 0) 면 LLM call 이 usage 를
    emit 안 했거나 mock 이라 캡처 안 된 경우 — caller 는 cost 0 / "" 로 처리
    (backward-compat).
    """
    from core.observability import current_session_metrics

    m = current_session_metrics()
    snapshot: dict[str, Any] = {}
    if m.last_call_input_tokens or m.last_call_output_tokens:
        snapshot = {
            "input_tokens": m.last_call_input_tokens,
            "output_tokens": m.last_call_output_tokens,
            "elapsed_seconds": m.last_call_elapsed_seconds,
            "model": m.last_call_model,
        }
    m.reset_last_call()
    return snapshot


def _normalize_provider_for_registry(provider: str) -> str:
    """Translate :func:`core.config._resolve_provider` output to the
    Path-B registry's provider key vocabulary.

    Step J-b.2 (2026-05-23, Codex MCP HIGH fix-up) —
    :func:`_resolve_provider` returns the broader provider keys
    (``anthropic`` / ``openai`` / ``openai-codex`` / ``glm``). The
    Path-B :func:`~core.llm.adapters.registry.resolve_for` registry uses
    a narrower set: ``anthropic`` / ``openai`` / ``glm``. The Codex
    distinction is encoded on the ``source`` axis instead (``CodexOAuthAdapter``
    lives at ``provider="openai"`` ``source="subscription"``).

    For a gpt-5.x model the legacy resolver returns ``"openai-codex"``;
    the Path-B mutator collapses that to ``"openai"`` and lets the
    source axis pick between ``payg`` / ``subscription`` / ``adapter``.
    """
    if provider == "openai-codex":
        return "openai"
    return provider


def _default_llm_call(system_prompt: str, user_prompt: str) -> str:
    """Mutator LLM call.

    Step J-b.2 (2026-05-23) — the **API path** (``source=api_key`` /
    ``auto``) now routes through the v0.99.39 Path-B
    :class:`~core.llm.adapters.base.LLMAdapter` Protocol via
    :func:`~core.llm.adapters.registry.resolve_for(provider, "payg")`.
    The mutator therefore inherits I.a's Codex OAuth header dedup and
    F's GLM adapter family on the API path directly.

    **CLI-subscription paths (``claude-cli`` / ``openai-codex``)
    deliberately stay on the dedicated ``invoke_claude_cli`` /
    ``invoke_codex_cli`` helpers** in :mod:`core.self_improving.loop.cli_subprocess`
    rather than going through the Path-B ``ClaudeCliAdapter`` /
    ``CodexCliAdapter`` built-ins. The built-in adapters were designed
    for the agentic-loop's streaming JSON event protocol
    (``--output-format stream-json``), whereas the mutator parser
    expects plain text output (``--output-format text`` for claude-cli
    and the ``--skip-git-repo-check`` codex_exec invocation). Forcing
    the mutator through the streaming adapters would break the JSON
    mutation-payload extraction. Migrating both adapters to support
    a text-output mode is tracked separately (Step I.c follow-up).

    Resolution order:

    1. ``~/.geode/config.toml [self_improving_loop.autoresearch.mutator]
       default_model`` (user override).
    2. ``MutatorConfig.default_model`` ship default — ``None`` inherits
       ``Settings.model`` (G1a, PR-MINIMAL-2).

    Tests inject a mock callable via
    ``SelfImprovingLoopRunner(llm_call=...)`` and skip this code path
    entirely; the lazy SDK imports keep the test cold-start free of
    anthropic.
    """
    import asyncio
    import logging as _logging

    from core.config import _resolve_provider
    from core.config.self_improving_loop import load_self_improving_loop_config

    cfg = load_self_improving_loop_config()
    # PR-MINIMAL-2 (2026-05-21) — G1a inherit: MutatorConfig.default_model
    # defaults to None, fall back to Settings.model so the operator's
    # ``/model`` choice flows through. Explicit override still wins.
    if cfg.autoresearch.mutator.default_model:
        model = cfg.autoresearch.mutator.default_model
    else:
        from core.config import settings

        model = settings.model
    max_tokens = cfg.autoresearch.mutator.max_tokens
    source = cfg.autoresearch.mutator.source

    provider = _resolve_provider(model)

    _logging.getLogger("core.self_improving.loop.runner").info(
        "mutator dispatch: model=%s provider=%s source=%s max_tokens=%d",
        model,
        provider,
        source,
        max_tokens,
    )

    # PR-PAPERCLIP (2026-05-21) — source-aware dispatch. The CLI-subscription
    # branches use the dedicated text-output helpers in ``cli_subprocess``
    # (see docstring above for the streaming-vs-text incompatibility with
    # the Path-B CLI adapters). The API path (``api_key`` / ``auto``)
    # falls through to the LLMAdapter Protocol.
    if source == "claude-cli":
        from core.self_improving.loop.cli_subprocess import invoke_claude_cli

        return invoke_claude_cli(system_prompt=system_prompt, user_prompt=user_prompt)
    if source == "openai-codex":
        from core.self_improving.loop.cli_subprocess import invoke_codex_cli

        return invoke_codex_cli(system_prompt=system_prompt, user_prompt=user_prompt)

    # Step J-b.2 (Path-B API path) — resolve_for + acomplete.
    from core.config import settings as _settings
    from core.llm.adapters import resolve_for
    from core.llm.adapters._source_inference import infer_source
    from core.llm.adapters.base import SOURCE_PAYG, AdapterCallRequest, Message
    from core.llm.router import call_with_failover

    # PR-SOURCE-ROUTING (2026-05-28) — for the unpinned ``auto`` source, mirror the
    # AgenticLoop main-path resolution via ``infer_source`` (subscription-first when
    # an OAuth profile is present) instead of the old hard-coded ``"payg"`` that sent
    # every mutator turn to the depleted PAYG endpoint.
    # PR-OPENAI-SOURCE-SINGLE-ENTRY (2026-06-03) — but an EXPLICIT ``api_key`` (e.g.
    # set via the ``[self_improving_loop] openai_source`` single entry point) must
    # route to PAYG; ``infer_source`` would otherwise re-derive subscription from a
    # present OAuth profile and silently ignore the operator's explicit lane choice.
    resolved_source = SOURCE_PAYG if source == "api_key" else infer_source(provider)
    adapter = resolve_for(_normalize_provider_for_registry(provider), resolved_source)
    mutator_temperature = _settings.temperature_self_improving_mutation

    async def _do_call(m: str) -> object:
        req = AdapterCallRequest(
            model=m,
            messages=(Message(role="user", content=user_prompt),),
            system_prompt=system_prompt,
            tools=(),
            tool_choice="auto",
            max_tokens=max_tokens,
            temperature=mutator_temperature,
        )
        return await adapter.acomplete(req)

    # ``call_with_failover`` is the router's async dispatcher (transport
    # layer) — accepts an ordered model list. PR-1 keeps it single-
    # element so the M5 silent-fallback knob default is preserved.
    # PR-SIL-5THEME C4 (2026-05-23) — E1 mutation cost ledger 의 timing
    # 캡처. result.usage 도 같이 record_*.
    call_started_at = time.time()
    result, _used_model = asyncio.run(call_with_failover([model], _do_call))
    call_elapsed = time.time() - call_started_at
    if result is None:
        raise RuntimeError(
            f"mutator LLM call failed (model={model}, provider={provider}, adapter={adapter.name})"
        )

    # PR-SIL-5THEME C4 + PR-SESSION-METRICS — usage metadata capture.
    # ``AdapterCallResult.usage`` is the v0.99.39 :class:`UsageSummary`
    # (``input_tokens`` / ``output_tokens`` / ``cached_input_tokens``).
    # The legacy ``AgenticResponse.usage`` had additional
    # ``cache_creation_tokens`` / ``thinking_tokens`` slots — those are
    # zeroed here because the new ``UsageSummary`` doesn't surface them
    # and no downstream mutator ledger reader consumes them today.
    from core.observability import current_session_metrics

    usage_obj = getattr(result, "usage", None)
    if usage_obj is not None:
        current_session_metrics().accumulate_llm_call(
            input_tokens=int(getattr(usage_obj, "input_tokens", 0)),
            output_tokens=int(getattr(usage_obj, "output_tokens", 0)),
            cache_creation_tokens=0,
            cache_read_tokens=int(getattr(usage_obj, "cached_input_tokens", 0)),
            thinking_tokens=0,
            elapsed_seconds=float(call_elapsed),
            model=str(_used_model or model),
        )

    text = getattr(result, "text", "") or ""
    if not text:
        # Empty text is a known anti-pattern surface (``parse_mutation``
        # raises ValueError downstream); callers that catch it can retry,
        # but failing fast here keeps the error message targeted instead
        # of letting JSON parsing carry the blame.
        raise RuntimeError(
            f"mutator LLM call returned empty text "
            f"(model={model}, provider={provider}, adapter={adapter.name}, "
            f"used={_used_model!r})"
        )
    return text


# PR-DROP-HYPERPARAM-MUTATION (2026-05-31, operator decision) — the
# ``hyperparam`` target_kind is REMOVED from the mutable surface entirely.
#
# History: PR-HYPERPARAM-FOUNDATION (2026-05-28) opened a numeric / categorical
# hyperparam mutation slot (max_turns / seed_limit / dim_set / reflection_depth);
# PR-AUDIT-SCAFFOLD-WIRE (2026-05-31) then restricted it to ``reflection_depth``
# ONLY (the other three rejected as audit-measurement params that confound the
# mutated-vs-baseline comparison). But ``reflection_depth`` is an EXHAUSTED axis:
# after ≥3 prior applies the axis-family dedup in ``mutator_feedback.py``
# (``_AXIS_REPEAT_LIMIT = 3``) rejects every new ``reflection_depth`` proposal as
# repetitive (synthetic ``axis_family_exhausted_*``, similarity 1.000). With only
# one mutable section left, a live campaign exhausts all 8 propose-guard attempts
# every cycle → every cycle SKIPs → zero data. So the kind is dropped from
# ``TARGET_KINDS`` (``policies.py``) and the mutator now proposes only the 7
# behaviour kinds and diversifies.
#
# The per-section bounds machinery (``_HYPERPARAM_INT_BOUNDS`` /
# ``_HYPERPARAM_FIXED_MEASUREMENT_KEYS`` / ``_HYPERPARAM_CATEGORICAL``) is now
# moot — ALL hyperparam mutations are rejected — and is removed rather than
# left as dead branches. A single clear rejection replaces it.
#
# PRESERVED: ``state/autoresearch/policies/hyperparam.json`` and its RUNTIME
# readers (``core.self_improving.train._load_hyperparam_overrides`` →
# seed_limit/max_turns/dim_set/reflection_depth consumed by the audit subprocess
# + AgenticLoop). Only the MUTATION surface is gone.


def _reject_hyperparam_mutation() -> None:
    """Reject any ``target_kind="hyperparam"`` mutation.

    ``hyperparam`` is no longer a mutable kind (PR-DROP-HYPERPARAM-MUTATION,
    2026-05-31). It is removed from ``TARGET_KINDS`` so the generic
    not-in-TARGET_KINDS guard already fails closed, but this dedicated
    rejection gives the operator a *specific* explanation rather than the
    generic enumeration — measurement params are fixed config and the
    ``reflection_depth`` axis is exhausted.

    Always raises :class:`ValueError`.
    """
    raise ValueError(
        "hyperparam is not a mutable kind — measurement params "
        "(seed_limit / max_turns / dim_set) are fixed audit config, and the "
        "reflection_depth axis is exhausted (PR-DROP-HYPERPARAM-MUTATION, "
        "2026-05-31). Propose one of the 7 behaviour kinds instead "
        "(prompt / tool_policy / tool_descriptions / decomposition / "
        "reflection / skill_catalog / agent_contract)."
    )


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
    if not expected_dim:
        # W1 (2026-05-25 attribution wiring) — expected_dim 가 비어 있으면
        # 후속 ``compute_attribution`` 이 attribution_score 0.0 으로만 평가
        # 되어 mutation 효과 측정이 무의미해진다. LLM 이 prompt 의 명시 요청
        # (``Mutation Contract`` §expected_dim) 을 빠뜨렸다는 신호이므로
        # WARNING 으로 surface 한다 — fail-closed 가 아니라 loop 가 계속
        # 돌면서 다음 mutation 에 영향 주지 않도록 graceful.
        log.warning(
            "self-improving-loop: mutation %r has empty expected_dim — "
            "attribution score will be 0.0 (LLM omitted dim commitments)",
            payload.get("target_section", "(unknown)"),
        )
    rollback_raw = payload.get("rollback_condition", "")
    rollback_condition = rollback_raw.strip() if isinstance(rollback_raw, str) else ""
    # P3-revised (2026-05-25, SPCT pattern) — principle 추출. LLM 이 명시
    # 안 하면 (legacy 또는 mutator omit) 빈 문자열.
    # PR-SPCT-CAP-1000 (2026-05-28) — cap 500 → 1000. cycle 14/15/16 6
    # attempts 모두 500-805 char (median ~600) 로 fail. GEODE 의 mutator
    # context 부피 (new baseline + attribution rows + 8 target_kind 표 +
    # measurement_modality 가이드) 가 풍부해진 만큼 principle 도 자연
    # 스럽게 길어짐. DeepSeek-GRM 의 "concise" 원칙은 보존하되 GEODE
    # context 에 맞춰 cap 2× 완화.
    principle_raw = payload.get("principle", "")
    principle = principle_raw.strip() if isinstance(principle_raw, str) else ""
    if len(principle) > 1000:
        raise ValueError(
            f"principle length {len(principle)} exceeds 1000 char cap "
            f"(SPCT principle must be concise — frontier reference: "
            f"DeepSeek-GRM)"
        )
    # A.6 (PR-20, 2026-05-25, CRM pattern) — causal_hypothesis 추출. LLM 이
    # 명시 안 하면 빈 문자열. max 500 chars guard (principle 패턴 동일).
    causal_hypothesis_raw = payload.get("causal_hypothesis", "")
    causal_hypothesis = (
        causal_hypothesis_raw.strip() if isinstance(causal_hypothesis_raw, str) else ""
    )
    if len(causal_hypothesis) > 500:
        raise ValueError(
            f"causal_hypothesis length {len(causal_hypothesis)} exceeds 500 char "
            f"cap (CRM causal chain must be concise — frontier: arXiv 2509.26578)"
        )
    # PR-6 C-5 — target_kind dispatches to the policy SoT file. Default
    # ``prompt`` keeps the legacy wrapper-sections behaviour so older
    # mutation rows replay unchanged. Unknown kinds raise ValueError so
    # the loop fails closed (caught and logged by SelfImprovingLoopRunner).
    from core.self_improving.loop.policies import TARGET_KINDS

    kind_raw = payload.get("target_kind", "prompt")
    if not isinstance(kind_raw, str):
        raise ValueError(f"target_kind must be a string, got {type(kind_raw).__name__}")
    target_kind = kind_raw.strip() or "prompt"
    # PR-DROP-HYPERPARAM-MUTATION (2026-05-31) — ``hyperparam`` is dropped
    # from TARGET_KINDS so the generic guard below already fails closed; this
    # dedicated branch wins first so the mutator gets the *specific* reason
    # (measurement params fixed + reflection_depth axis exhausted) rather than
    # the generic enumeration. apply_mutation applies the same gate (boundary
    # completeness, CLAUDE.md → Wiring Verification → Conditional Read Parity).
    if target_kind == "hyperparam":
        _reject_hyperparam_mutation()
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
            principle=principle,
            causal_hypothesis=causal_hypothesis,
        )
    return Mutation(
        target_section=target_section.strip(),
        new_value=new_value,
        rationale=rationale.strip(),
        target_dim=target_dim.strip(),
        target_kind=target_kind,
        expected_dim=expected_dim,
        rollback_condition=rollback_condition,
        principle=principle,
        causal_hypothesis=causal_hypothesis,
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
    ``core.self_improving.train.write_wrapper_prompt_sections`` writer so
    schema enforcement (single-paragraph 600-char cap) is preserved.
    The other four kinds go through
    :func:`core.self_improving.loop.policies.write_policy` which is
    a generic ``dict[str, str]`` writer with atomic temp-file rewrite.
    """
    from core.self_improving.loop.policies import load_policy, write_policy
    from core.self_improving.train import (
        load_wrapper_prompt_sections,
        write_wrapper_prompt_sections,
    )

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

    # PR-DROP-HYPERPARAM-MUTATION (2026-05-31) — second-layer rejection.
    # parse_mutation already rejects at LLM-response time, but the apply path
    # is reached from other entrypoints (manual ``apply_mutation`` calls in
    # tests / slash / re-runs of a parsed mutation), so a ``Mutation``
    # constructed outside ``parse_mutation`` cannot rely on the first gate.
    # Defensive depth (CLAUDE.md → Wiring Verification → Conditional Read
    # Parity). ``hyperparam`` is no longer mutable — reject before any write.
    if mutation.target_kind == "hyperparam":
        _reject_hyperparam_mutation()

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
    audit_run_id: str = "",
    kind: str = "applied",
    contract_results: list[dict[str, Any]] | None = None,
) -> Path:
    """Append one mutation row to the git-tracked audit jsonl.

    Returns the path of the audit log so the caller can ``git add``
    it. Best-effort — directory is created if missing.

    W3 (2026-05-25 attribution wiring) — ``audit_run_id`` forwarded to
    ``Mutation.to_audit_row`` so the apply row carries the cross-ref
    key to the matching attribution row.

    PR-CONTRACT-EVAL (2026-06-03) — ``contract_results`` stamps the
    deterministic tool-call contract ledger
    (``core.audit.contracts.extract_contract_results``) onto the row when
    provided. ``None`` (the default, and the live apply-time call shape) omits
    the key — the contract verdict is produced by the audit subprocess
    downstream of this apply-time write, so the live row carries it only once a
    caller threads the post-audit result back through.
    """
    target = log_path if log_path is not None else MUTATION_AUDIT_LOG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    row = mutation.to_audit_row(
        previous_value=previous_value,
        baseline_fitness=baseline_fitness,
        audit_run_id=audit_run_id,
        kind=kind,
    )
    # PR-ROLE-PROVENANCE (2026-05-30) — stamp the per-role {model, source, lane}
    # onto EVERY cycle's apply row (promote or reject), so the credential lane is
    # observable from the git-tracked ledger without parsing the .eval. Shared
    # SoT with baseline_archive.jsonl. Best-effort: a config-load failure must
    # never block the ledger write (observability is not a correctness boundary).
    try:
        from core.config.self_improving_loop import load_self_improving_loop_config
        from core.self_improving.loop.role_provenance import collect_role_provenance

        row["role_provenance"] = collect_role_provenance(
            load_self_improving_loop_config().autoresearch
        )
    except Exception:  # pragma: no cover — observability best-effort
        log.debug("role_provenance collect failed for apply row", exc_info=True)
    # PR-CONTRACT-EVAL (2026-06-03) — stamp the deterministic contract ledger
    # when the caller threaded the post-audit verdict back. ``ApplyRecord``
    # carries a typed ``contract_results`` field; ``None`` simply omits the key
    # (legacy + apply-time-only rows).
    if contract_results is not None:
        row["contract_results"] = contract_results
    # W4 (2026-05-25) — Pydantic schema validation. drift 가 발생하면
    # ValidationError 가 fail-fast 로 raise → 잘못된 row 가 git-tracked
    # ledger 에 들어가지 않음. backward-compat 은 ApplyRecord 의
    # ``extra="allow"`` + optional cost/audit_run_id field 로 유지.
    validated = ApplyRecord.model_validate(row).model_dump(exclude_none=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(validated, ensure_ascii=False) + "\n")
    # PR-MUTATION-EMIT-WIRE (2026-05-27) — emit MUTATION_APPLIED *after*
    # the row write succeeds. The reserve docstring on
    # ``HookEvent.MUTATION_APPLIED`` (core/hooks/system.py:285-287)
    # documents the payload schema:
    #   {"mutation_id": str, "target_kind": str, "target_path": str,
    #    "ts": float, "run_id": str}
    # ``kind`` rides as an extra field; it is always ``"applied"`` now
    # (the single (1+1)-ES SoT-committed mutation).
    from core.hooks.system import HookEvent
    from core.self_improving.loop._hooks import _fire_hook

    _fire_hook(
        HookEvent.MUTATION_APPLIED,
        {
            "mutation_id": mutation.mutation_id,
            "target_kind": mutation.target_kind,
            "target_path": str(target),
            "ts": time.time(),
            "run_id": audit_run_id,
            "kind": kind,
        },
    )
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
        # parents[2] = repo root. ``log_path`` is
        # ``<repo>/state/autoresearch/mutations.jsonl``; parents[1]
        # resolves to ``<repo>/state`` which is *inside* the git tree but
        # is not the repo root and would silently rebase git operations
        # against a non-canonical cwd.
        repo_root = log_path.resolve().parents[2]
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


def _mint_audit_run_id() -> str:
    """Codex MCP review F5 (Dedup) — ``apply_proposal`` 의 audit_run_id
    생성 식을 single source 로 통일. UUID4 의 hex prefix[:12]
    (W3 PR-3 의 within-ledger correlation key format).
    """
    return uuid.uuid4().hex[:12]


def _run_autoresearch_subprocess(
    *,
    repo_root: Path,
    dry_run: bool,
    audit_run_id: str = "",
    mutation_id: str = "",
    expected_dim: dict[str, float] | None = None,
    rollback_condition: str = "",
) -> subprocess.CompletedProcess[str]:
    """Spawn ``core/self_improving/train.py`` for the post-mutation audit.

    Default ``dry_run=True`` keeps the loop cheap during development;
    operators flip to ``dry_run=False`` for a real budget-spending
    audit. The subprocess is non-fatal — failures log + return so the
    runner can record the mutation row even when the audit aborts.

    W2/W3 (2026-05-25 attribution wiring) — when ``audit_run_id`` /
    ``mutation_id`` / ``expected_dim`` 모두 non-empty 면 env 로
    propagate. train.py 의 _persist_baseline 직후 hook 이 env 받고
    ``write_attribution`` 호출 → mutations.jsonl 에 attribution row
    append. env 누락 시 hook 가 graceful skip (legacy --promote /
    manual run 보존).

    PR-SIL-MULTIOBJ A2 (2026-05-29) — ``rollback_condition`` env-propagated
    so train.py's promote decision can auto-evaluate it as a *secondary*
    reject gate (empty string ⇒ env unset ⇒ train.py skips the check).
    """
    argv = ["uv", "run", "python", "-m", "core.self_improving.train"]
    if dry_run:
        argv.append("--dry-run")
    env = os.environ.copy()
    if audit_run_id and mutation_id:
        env["GEODE_SIL_AUDIT_RUN_ID"] = audit_run_id
        env["GEODE_SIL_MUTATION_ID"] = mutation_id
        env["GEODE_SIL_EXPECTED_DIM"] = json.dumps(expected_dim or {}, ensure_ascii=False)
    if rollback_condition:
        env["GEODE_SIL_ROLLBACK_CONDITION"] = rollback_condition
    # PR-11 P3.1 (2026-05-25) — anchor_confidence_mode env forward. config
    # default 가 False 라 set 안 된 sibling/legacy 동작 영향 0. True 일
    # 때만 train.py 의 caller 가 ``compute_fitness`` 에 multiplier 인자를
    # 적용하는 게 wiring (PR-11 의 다른 절반).
    from core.config.self_improving_loop import load_self_improving_loop_config

    if load_self_improving_loop_config().autoresearch.anchor_confidence_mode:
        env["GEODE_SIL_ANCHOR_CONFIDENCE_MODE"] = "1"
    return subprocess.run(  # noqa: S603  # nosec B603 — argv built from constants
        argv,
        cwd=str(repo_root),
        env=env,
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
        # PR-SIL-5THEME C4 (2026-05-23) — E1 mutation cost ledger. 새 LLM
        # call 직전 sidecar 비우고, _default_llm_call 이 호출 후 채움. mock
        # 인 경우 빈 dict 가 그대로 남음 → consume_usage() 가 빈 dict 반환
        # → Mutation.cost_* 가 default 0 / "" 유지.
        _reset_last_llm_call_usage()
        raw_response = self.llm_call(_build_system_prompt(), user_prompt)
        usage_snapshot = _consume_last_llm_call_usage()
        mutation = parse_mutation(raw_response)
        # PR-SIL-5THEME C4 — usage → mutation cost field. ``Mutation`` 은
        # ``frozen=True`` dataclass 라 dataclasses.replace 로 새 인스턴스
        # 생성. usage_snapshot 이 빈 dict (mock injection) 면 mutation
        # 그대로 (default 0 / "").
        if usage_snapshot:
            mutation = dataclasses.replace(
                mutation,
                cost_input_tokens=int(usage_snapshot.get("input_tokens", 0)),
                cost_output_tokens=int(usage_snapshot.get("output_tokens", 0)),
                cost_elapsed_seconds=float(usage_snapshot.get("elapsed_seconds", 0.0)),
                cost_model=str(usage_snapshot.get("model", "")),
            )
        # PR-MUTATOR-DEDUP-GUARD (2026-05-27) — reject mutations whose
        # ``(target_kind, target_section, new_value)`` triple is too
        # similar to a recent apply row. ``build_runner_context`` gates
        # this on ``mutator_dedup_window`` (0 = empty tuple → guard
        # disabled, legacy behaviour). The threshold comes from the
        # operator config; loading inside ``propose`` keeps the cost
        # path lazy (mock-llm tests don't pay it).
        if ctx.recent_applies_for_dedup:
            from core.config.self_improving_loop import load_self_improving_loop_config
            from core.self_improving.loop.mutator_feedback import (
                RepetitiveMutationError,
                check_repetitive_mutation,
            )

            threshold = load_self_improving_loop_config().autoresearch.mutator_dedup_threshold
            finding = check_repetitive_mutation(mutation, ctx.recent_applies_for_dedup, threshold)
            if finding.is_repetitive:
                log.warning(
                    "self-improving-loop: mutation %r rejected as repetitive "
                    "(similarity=%.3f vs prior mutation_id=%r section=%r)",
                    mutation.target_section,
                    finding.max_similarity,
                    finding.matched_mutation_id,
                    finding.matched_target_section,
                )
                raise RepetitiveMutationError(finding, threshold)
        # PR-6 C-5 (Codex MCP catch) — apply_mutation dispatches by
        # target_kind, but ctx.current_sections is *always* the wrapper-
        # prompt sections (built by build_runner_context). Passing those
        # into a non-prompt apply would write wrapper-prompt contents
        # into the wrong SoT file. Load the *correct* starting policy
        # based on the parsed mutation's kind so the dispatcher writes
        # the right destination. ``original_sections`` is captured AFTER
        # the kind-aware load so rollback restores the matching SoT.
        from core.self_improving.loop.policies import load_policy

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
        # PR-MUTATION-PROPOSED-WIRE (2026-05-27) — emit MUTATION_PROPOSED
        # after the proposal has been built (LLM parse + dedup gate + SoT
        # load all succeeded) but BEFORE any apply / audit. Payload schema
        # per the reserve docstring (core/hooks/system.py:285-287). No
        # ``run_id`` available here — the audit_run_id is minted later in
        # ``apply_proposal`` via :func:`_mint_audit_run_id`.
        # Listeners that need to correlate proposed → applied join on
        # ``mutation_id`` instead.
        from core.hooks.system import HookEvent
        from core.self_improving.loop._hooks import _fire_hook

        _fire_hook(
            HookEvent.MUTATION_PROPOSED,
            {
                "mutation_id": mutation.mutation_id,
                "target_kind": mutation.target_kind,
                "target_path": f"{mutation.target_kind}.{mutation.target_section}",
                "ts": time.time(),
                "run_id": "",
            },
        )
        return Proposal(
            mutation=mutation,
            target_sections=target_sections,
            original_sections=original_sections,
            baseline_fitness=baseline_fitness,
        )

    def apply_proposal(
        self,
        proposal: Proposal,
    ) -> Mutation:
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

        W3 (2026-05-25 attribution wiring) — audit_run_id 를 propose-
        apply-audit 단일 cycle 안에서 mint. mutations.jsonl 의 apply
        row 와 attribution row 가 audit_run_id 로 join 가능. mint 는
        rerun_enabled 일 때만 (rerun_disabled 면 audit 가 안 일어나
        attribution row 도 없으니 audit_run_id 무의미).
        """
        audit_run_id = _mint_audit_run_id() if self.rerun_enabled else ""
        _new_sections, previous_value = apply_mutation(
            proposal.mutation, current_sections=proposal.target_sections
        )
        try:
            log_path = append_audit_log(
                proposal.mutation,
                previous_value=previous_value,
                log_path=self.audit_log_path,
                audit_run_id=audit_run_id,
            )
        except OSError as exc:
            self._rollback_sot(
                proposal.original_sections,
                mutation=proposal.mutation,
                exc=exc,
                audit_run_id=audit_run_id,
                reason="audit_log_write_fail",
            )
            raise
        if self.commit_enabled:
            _git_commit_audit_log(log_path, mutation=proposal.mutation)
        if self.rerun_enabled:
            # MUTATION_AUDIT_LOG_PATH lives at <repo>/state/autoresearch/mutations.jsonl,
            # so parents[2] is the repo root. parents[1] would point at
            # <repo>/state and spawn `uv run python -m core.self_improving.train`
            # with cwd=state → ENOENT on state/core/self_improving/train.py.
            repo_root = log_path.resolve().parents[2]
            # PR-SOT-REVERT-ON-AUDIT-FAIL (2026-05-26) — forward
            # ``proposal.original_sections`` so _invoke_autoresearch can
            # rollback the canonical SoT if the audit subprocess crashes
            # or exits non-zero. Without this, a crashed audit leaves
            # the SoT mutated and the baseline unchanged — silent leak.
            self._invoke_autoresearch(
                repo_root,
                audit_run_id=audit_run_id,
                mutation=proposal.mutation,
                original_sections=proposal.original_sections,
            )
        self._append_self_improving_loop_index(proposal.mutation, previous_value)
        return proposal.mutation

    def run_once(self) -> Mutation | None:
        """Execute one full propose+apply iteration — a single
        (1+1)-ES keep-or-revert mutation compared against the previous
        baseline. Thin wrapper around :meth:`propose` + :meth:`apply_proposal`.

        PR-DROP-GROUP-SAMPLING (2026-05-29) — the (1+λ) group/swarm sampling +
        Tchebycheff/pareto selection layer was removed. It was dormant at
        ``group_size=1`` and vestigial for a no-gradient selection loop: the
        group-relative z-score advantage is argmax-invariant (no gradient to
        scale), and best-of-N over the noisy/expensive Petri audit amplifies
        winner's-curse selection. The loop is now purely single-mutation.

        Raises :class:`ValueError` on parse / validation failure so
        the caller can decide whether to retry.
        """
        return self.apply_proposal(self.propose())

    @staticmethod
    def _rollback_sot(
        original_sections: dict[str, str],
        *,
        mutation: Mutation,
        exc: BaseException,
        audit_run_id: str = "",
        reason: str = "post_apply_failure",
    ) -> None:
        """Restore the SoT to ``original_sections`` after a post-apply failure.

        G5b.fix3 — original use: invoked from ``run_once`` when
        :func:`append_audit_log` raises ``OSError`` *after*
        :func:`apply_mutation` has already written the new sections to
        disk. The SoT must be rolled back to the pre-mutation state so
        the loop never persists a mutation that has no audit-log row;
        otherwise the git-as-optimiser ledger and the live state would
        diverge silently.

        PR-SOT-REVERT-ON-AUDIT-FAIL (2026-05-26) — extended use: also
        invoked from :meth:`_invoke_autoresearch` when the post-commit
        audit subprocess raises (caught as ``Exception``) or exits
        non-zero (synthesized as ``RuntimeError`` carrying the exit
        code). ``exc`` type is widened from ``OSError`` to
        ``BaseException`` so the synthesized RuntimeError type-checks —
        but the in-process catch boundary in
        :meth:`_invoke_autoresearch` is ``Exception``, so
        KeyboardInterrupt / SystemExit still propagate without
        triggering rollback. The log message is structural; the exact
        exception type lands in the formatted output.

        Rollback failure is itself logged but never raised in place of
        the original ``exc`` — the caller already has the more useful
        signal (audit-log write failed).

        PR-6 C-5 (Codex MCP catch) — rollback dispatches on
        ``mutation.target_kind``. The prompt kind still writes through
        ``core.self_improving.train.write_wrapper_prompt_sections`` (legacy
        schema enforcement); the four policy kinds go through
        ``write_policy`` so the right SoT is restored.
        """
        try:
            if mutation.target_kind == "prompt":
                from core.self_improving.train import write_wrapper_prompt_sections

                write_wrapper_prompt_sections(original_sections)
            else:
                from core.self_improving.loop.policies import write_policy

                write_policy(mutation.target_kind, original_sections)
            log.error(
                "self-improving-loop runner: audit-log write failed (%s); "
                "SoT rolled back to pre-mutation state for kind %r section %r",
                exc,
                mutation.target_kind,
                mutation.target_section,
            )
            # PR-MUTATION-REVERTED-ROLLBACK-WIRE (2026-05-27) — emit
            # MUTATION_REVERTED after the rollback succeeds. PR-MUTATION-EMIT-WIRE
            # (2026-05-27) covered only the promote-gate reject path
            # (core/self_improving/train.py:_revert_sot_after_reject). This site
            # covers the symmetric audit-fail / audit-log-write-fail paths
            # so the observability ledger never sees a mutation that was
            # APPLIED but never REVERTED (silent SoT roll-back).
            #
            # ``reason`` is a free-form caller-supplied string (e.g.
            # ``"audit_log_write_fail"`` / ``"audit_subprocess_crash"`` /
            # ``"audit_subprocess_nonzero"``) so downstream readers can
            # distinguish the trigger; default ``"post_apply_failure"``
            # keeps the contract usable for callers that don't yet thread
            # a specific reason.
            from core.hooks.system import HookEvent
            from core.self_improving.loop._hooks import _fire_hook

            _fire_hook(
                HookEvent.MUTATION_REVERTED,
                {
                    "mutation_id": mutation.mutation_id,
                    "target_kind": mutation.target_kind,
                    "target_path": f"{mutation.target_kind}.{mutation.target_section}",
                    "ts": time.time(),
                    "run_id": audit_run_id,
                    "reason": reason,
                },
            )
        except Exception:  # pragma: no cover — defensive
            log.exception(
                "self-improving-loop runner: audit-log write failed (%s) AND "
                "rollback failed — SoT may be in a divergent state for "
                "section %r",
                exc,
                mutation.target_section,
            )

    def _invoke_autoresearch(
        self,
        repo_root: Path,
        *,
        audit_run_id: str = "",
        mutation: Mutation | None = None,
        original_sections: dict[str, str] | None = None,
    ) -> None:
        """Wrap the autoresearch subprocess so tests can override.

        W2/W3 (2026-05-25 attribution wiring) — propagate audit_run_id +
        mutation_id + expected_dim to the subprocess env so the
        attribution row written after the audit carries the same
        cross-ref keys as the apply row.

        PR-SOT-REVERT-ON-AUDIT-FAIL (2026-05-26) — when the subprocess
        crashes (Exception) or exits non-zero (returncode != 0), the
        canonical SoT mutation this audit was supposed to validate is
        rolled back via :meth:`_rollback_sot`. Without rollback a
        crashed audit leaves the SoT mutated and the baseline
        unchanged — the next cycle has no signal to attribute the
        regression to.

        ``original_sections`` is the pre-mutation SoT
        (``proposal.original_sections``). When ``None`` (callers that
        didn't migrate, or mutation is None), rollback is skipped and
        the legacy graceful-log behaviour is preserved.
        """
        try:
            result = _run_autoresearch_subprocess(
                repo_root=repo_root,
                dry_run=self.rerun_dry_run,
                audit_run_id=audit_run_id,
                mutation_id=mutation.mutation_id if mutation is not None else "",
                expected_dim=mutation.expected_dim if mutation is not None else None,
                rollback_condition=(mutation.rollback_condition if mutation is not None else ""),
            )
        except Exception as exc:
            log.warning("self-improving-loop autoresearch re-run failed", exc_info=True)
            if original_sections is not None and mutation is not None:
                self._rollback_sot(
                    original_sections,
                    mutation=mutation,
                    exc=exc,
                    audit_run_id=audit_run_id,
                    reason="audit_subprocess_crash",
                )
            return
        if result.returncode != 0:
            log.warning(
                "self-improving-loop autoresearch re-run exited non-zero "
                "(returncode=%d); stderr tail: %s",
                result.returncode,
                (result.stderr or "")[-500:],
            )
            if original_sections is not None and mutation is not None:
                self._rollback_sot(
                    original_sections,
                    mutation=mutation,
                    exc=RuntimeError(f"audit subprocess exit code {result.returncode}"),
                    audit_run_id=audit_run_id,
                    reason="audit_subprocess_nonzero",
                )

    @staticmethod
    def _append_self_improving_loop_index(mutation: Mutation, previous_value: str) -> None:
        """Best-effort append to the shared session index.

        Lets the existing ``~/.geode/autoresearch/handoff/sessions.jsonl``
        registry (P1a) carry one row per mutator invocation so external
        consumers can see the mutator alongside seed-generation /
        autoresearch runs.
        """
        index_path = GLOBAL_AUTORESEARCH_HANDOFF_DIR / "sessions.jsonl"
        try:
            GLOBAL_AUTORESEARCH_HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
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
