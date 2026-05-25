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

from core.paths import GLOBAL_SELF_IMPROVING_LOOP_DIR
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
    "_compute_group_advantage",
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
    kind: str = Field(default="applied", pattern=r"^applied(_sibling)?$")
    """P1-revised (2026-05-25) — ``applied`` (group 의 top-1 채택) 또는
    ``applied_sibling`` (group 의 non-best, in-memory only). legacy
    group_size=1 mode 는 항상 ``applied``."""
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
    group_id: str | None = None
    """P1-revised — group sampling cross-ref key. 같은 cycle 의 N sibling
    apply row + attribution row 가 모두 같은 group_id 를 가져 group statistic
    재구성 가능. group_size=1 (legacy) 일 때 None."""
    group_advantage: float | None = None
    """P1-revised — advantage normalization z-score. group_size=1 일 때 None."""
    principle: str | None = Field(default=None, max_length=500)
    """P3-revised (2026-05-25, SPCT) — mutator 가 mutation 직전 명시
    한 self-generated judging principle. SPCT (DeepSeek-GRM 2026-Q1) 패턴.
    None 일 때 legacy (P3 이전 mutation row). max 500 chars (parse_mutation
    guard)."""


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

    def to_audit_row(
        self,
        *,
        previous_value: str,
        timestamp: float | None = None,
        baseline_fitness: float | None = None,
        audit_run_id: str = "",
        kind: str = "applied",
        group_id: str = "",
        group_advantage: float | None = None,
    ) -> dict[str, Any]:
        """Render the mutation as one audit-log row.

        PR-SIL-5THEME C4 (2026-05-23) — cost 4-field 추가. 모두 0 / "" 일
        때만 row 에 컬럼 자체 미생성 → legacy reader 가 새 컬럼 부재 시
        graceful (key 가 없으면 0 / "" 가정).

        W3 (2026-05-25 attribution wiring) — ``audit_run_id`` parameter
        추가. ``Mutation`` 자체는 frozen dataclass 라 LLM 응답 구조
        immutable 유지; audit_run_id 는 runner-side context.

        P1-revised (2026-05-25 baseline RL grounding) — ``kind`` /
        ``group_id`` / ``group_advantage`` parameter 추가. group sampling
        의 sibling row (``kind="applied_sibling"``) + group cross-ref.
        group_size=1 (legacy) 일 때 default 그대로 (``kind="applied"``,
        group_id="" → row 에서 column 생략).
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
        if group_id:
            row["group_id"] = group_id
        if group_advantage is not None:
            row["group_advantage"] = round(float(group_advantage), 6)
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
    "``reflection`` (reflection.json). "
    "Omit for prompt-level mutations. (``retrieval`` was deprecated "
    "in ADR-012 S0d, 2026-05-21 — see policies.py docstring.)\n"
    "- **Principle-first (P3-revised, 2026-05-25, SPCT pattern)**: BEFORE "
    "selecting ``target_section`` and writing ``new_value``, explicitly state "
    "the judging principle that motivates this mutation — what specific axis "
    "of GEODE behaviour should it move, and why? Output the principle as a "
    "short string in the ``principle`` field (<= 500 chars). This is the "
    "SPCT (DeepSeek-GRM 2026-Q1) frontier — self-generated principles "
    "anchor self-judge drift and let downstream attribution (PR-3 W2 hook) "
    "trace causal hypothesis. legacy callers (P3 이전) may omit; empty "
    "string is graceful.\n"
    "- **Group sampling (P1-revised, 2026-05-25)**: when this invocation is "
    "part of a sibling group (``group_size > 1``), each sibling MUST target a "
    "meaningfully different section or strategy. Repeating the same "
    "``target_section`` + ``new_value`` across siblings collapses group "
    "variance to zero, trips the DAPO Dynamic Sampling variance filter, and "
    "the entire cycle's audit cost is discarded (see plan "
    "``docs/plans/2026-05-25-baseline-fitness-rl-grounding.md`` §6).\n"
    "- Respond with a single JSON object — NO surrounding prose, NO code fences.\n"
    "\n"
    "Response schema:\n"
    "{\n"
    '  "target_section": "<section key>",\n'
    '  "new_value": "<replacement text>",\n'
    '  "rationale": "<= 200 chars, citing the evidence>",\n'
    '  "target_dim": "<dim name the mutation aims at, or empty>",\n'
    '  "target_kind": "<prompt|tool_policy|decomposition|reflection>",\n'
    '  "expected_dim": {"<dim>": 0.0, ...},\n'
    '  "rollback_condition": "<one-line predicate, or empty>",\n'
    '  "principle": "<= 500 chars SPCT principle (P3-revised), or empty>"\n'
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
    ``invoke_codex_cli`` helpers** in :mod:`core.self_improving_loop.cli_subprocess`
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

    _logging.getLogger("core.self_improving_loop.runner").info(
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
        from core.self_improving_loop.cli_subprocess import invoke_claude_cli

        return invoke_claude_cli(system_prompt=system_prompt, user_prompt=user_prompt)
    if source == "openai-codex":
        from core.self_improving_loop.cli_subprocess import invoke_codex_cli

        return invoke_codex_cli(system_prompt=system_prompt, user_prompt=user_prompt)

    # Step J-b.2 (Path-B API path) — resolve_for + acomplete.
    from core.config import settings as _settings
    from core.llm.adapters import resolve_for
    from core.llm.adapters.base import AdapterCallRequest, Message
    from core.llm.router import call_with_failover

    adapter = resolve_for(_normalize_provider_for_registry(provider), "payg")
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
    # 안 하면 (legacy 또는 mutator omit) 빈 문자열. max 500 chars guard.
    principle_raw = payload.get("principle", "")
    principle = principle_raw.strip() if isinstance(principle_raw, str) else ""
    if len(principle) > 500:
        raise ValueError(
            f"principle length {len(principle)} exceeds 500 char cap "
            f"(SPCT principle must be concise — frontier reference: "
            f"DeepSeek-GRM)"
        )
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
            principle=principle,
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


def _apply_sibling_in_memory_with_value(
    proposal: Proposal,
) -> tuple[dict[str, str], str, Path]:
    """P1-revised — write sibling SoT to OS temp file, returning the
    new sections + previous_value + temp path.

    Canonical SoT (``autoresearch/state/policies/*.json``) 는 건드리지
    않음. audit subprocess 가 temp path 를 ``GEODE_<KIND>_OVERRIDE`` env
    로 받아 strict mode read (W3 PR-3 인프라).
    """
    from core.self_improving_loop.policies import write_sibling_in_memory

    new_sections = dict(proposal.target_sections)
    previous_value = new_sections.get(proposal.mutation.target_section, "")
    new_sections[proposal.mutation.target_section] = proposal.mutation.new_value
    sibling_path = write_sibling_in_memory(proposal.mutation.target_kind, new_sections)
    return new_sections, previous_value, sibling_path


_FITNESS_RESULT_SENTINEL = "FITNESS_RESULT: "


def _parse_fitness_from_subprocess_stdout(
    stdout: str,
    *,
    audit_run_id: str,
    sibling_idx: int,
) -> float:
    """Parse the ``FITNESS_RESULT: {...}`` sentinel line from
    ``autoresearch/train.py`` stdout end-of-run.

    Sentinel format: ``FITNESS_RESULT: {"fitness": <float>, "audit_run_id": "<id>"}``

    Raises RuntimeError when the sentinel is missing or unparseable —
    fail-fast so group sampling cycle aborts cleanly instead of producing
    silent-zero advantages.
    """
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith(_FITNESS_RESULT_SENTINEL):
            payload_str = line[len(_FITNESS_RESULT_SENTINEL) :].strip()
            try:
                payload = json.loads(payload_str)
                fitness = float(payload.get("fitness"))
                returned_audit_id = str(payload.get("audit_run_id", ""))
                if returned_audit_id and returned_audit_id != audit_run_id:
                    log.warning(
                        "self-improving-loop: sibling[%d] FITNESS_RESULT audit_run_id "
                        "mismatch (expected %s, got %s) — possible env "
                        "propagation drift",
                        sibling_idx,
                        audit_run_id,
                        returned_audit_id,
                    )
                return fitness
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"sibling[{sibling_idx}] FITNESS_RESULT parse failed: {exc} "
                    f"(payload: {payload_str!r})"
                ) from exc
    raise RuntimeError(
        f"sibling[{sibling_idx}] audit subprocess did not emit FITNESS_RESULT "
        f"sentinel — autoresearch/train.py end-of-run print missing or stdout "
        f"truncated. audit_run_id={audit_run_id}"
    )


def _compute_group_advantage(
    fitness_values: list[float],
    threshold: float,
    *,
    mutator_temperature: float,
) -> tuple[list[float] | None, str]:
    """P1-revised (2026-05-25) — DAPO Dynamic Sampling + GRPO advantage normalization.

    Plan: ``docs/plans/2026-05-25-baseline-fitness-rl-grounding.md`` §4.1.

    Frontier source: DAPO (ByteDance/Tsinghua arXiv 2503.14476) 의 Dynamic
    Sampling — group reward variance ≈ 0 batch 폐기. EXAONE 4.5 (LG, arXiv
    2604.08644) 의 zero-variance filter production 검증. GRPO (DeepSeek R1
    arXiv 2402.03300) 의 advantage whitening.

    Returns (advantages, status):
    - status="ok" + advantages = z-score whitening if group std > threshold
    - status="filtered_low_variance" + advantages=None if std < threshold
      → caller cycle skip (audit cost wasted 회피)
    - status="group_too_small" if N < 2 (legacy group_size=1 mode 는 caller
      가 본 helper 호출 안 함, 본 분기는 invariant test 용)

    Raises RuntimeError when ``mutator_temperature`` < 0.1 — deterministic
    mutation 은 N rollout 모두 같음 → group std=0 → variance filter 영구
    trigger → loop 영구 cycle skip 의 silent infinite-loop. plan §6 risk 표.
    """
    if mutator_temperature < 0.1:
        raise RuntimeError(
            f"P1-revised group sampling requires mutator temperature >= 0.1 "
            f"(current: {mutator_temperature}). Deterministic mutation 은 N "
            f"rollout 모두 같음 → group std=0 → variance filter 영구 trigger. "
            f"Settings.temperature_self_improving_mutation (env "
            f"GEODE_TEMPERATURE_SELF_IMPROVING_MUTATION) 을 >= 0.1 로 override."
        )
    n = len(fitness_values)
    if n < 2:
        return None, "group_too_small"
    mean_val = sum(fitness_values) / n
    var_val = sum((r - mean_val) ** 2 for r in fitness_values) / n
    std_val = var_val**0.5
    if std_val < threshold:
        return None, "filtered_low_variance"
    eps = 1e-8
    advantages = [(r - mean_val) / (std_val + eps) for r in fitness_values]
    return advantages, "ok"


def append_audit_log(
    mutation: Mutation,
    *,
    previous_value: str,
    baseline_fitness: float | None = None,
    log_path: Path | None = None,
    audit_run_id: str = "",
    kind: str = "applied",
    group_id: str = "",
    group_advantage: float | None = None,
) -> Path:
    """Append one mutation row to the git-tracked audit jsonl.

    Returns the path of the audit log so the caller can ``git add``
    it. Best-effort — directory is created if missing.

    W3 (2026-05-25 attribution wiring) — ``audit_run_id`` forwarded to
    ``Mutation.to_audit_row`` so the apply row carries the cross-ref
    key to the matching attribution row.

    P1-revised (2026-05-25 baseline RL grounding) — ``kind`` / ``group_id``
    / ``group_advantage`` forwarded. group sampling 의 sibling row
    (``kind="applied_sibling"``) + group cross-ref. group_size=1 (legacy)
    일 때 default 그대로.
    """
    target = log_path if log_path is not None else MUTATION_AUDIT_LOG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    row = mutation.to_audit_row(
        previous_value=previous_value,
        baseline_fitness=baseline_fitness,
        audit_run_id=audit_run_id,
        kind=kind,
        group_id=group_id,
        group_advantage=group_advantage,
    )
    # W4 (2026-05-25) — Pydantic schema validation. drift 가 발생하면
    # ValidationError 가 fail-fast 로 raise → 잘못된 row 가 git-tracked
    # ledger 에 들어가지 않음. backward-compat 은 ApplyRecord 의
    # ``extra="allow"`` + optional cost/audit_run_id field 로 유지.
    validated = ApplyRecord.model_validate(row).model_dump(exclude_none=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(validated, ensure_ascii=False) + "\n")
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


def _mint_audit_run_id() -> str:
    """Codex MCP review F5 (Dedup) — apply_proposal / apply_group_proposals
    의 audit_run_id 생성 식을 single source 로 통일. UUID4 의 hex prefix[:12]
    (W3 PR-3 의 within-ledger correlation key format).
    """
    return uuid.uuid4().hex[:12]


_SIBLING_SOT_ENV_MAP: dict[str, str] = {
    "prompt": "GEODE_WRAPPER_OVERRIDE",
    "tool_policy": "GEODE_TOOL_POLICY_OVERRIDE",
    "decomposition": "GEODE_DECOMPOSITION_POLICY_OVERRIDE",
    "reflection": "GEODE_REFLECTION_POLICY_OVERRIDE",
    "skill_catalog": "GEODE_SKILL_CATALOG_OVERRIDE",
    "agent_contract": "GEODE_AGENT_CONTRACTS_OVERRIDE",
}
"""P1-revised — sibling SoT temp file path 를 propagation 할 env var
mapping (per ``Mutation.target_kind``). W3 인프라 (``autoresearch/train.py:809+``)
의 ``GEODE_*_OVERRIDE`` 와 동일 — sibling audit subprocess 가 strict mode
로 temp SoT 를 read 하도록 강제."""

_SIBLING_SOT_STRICT_ENV_MAP: dict[str, str] = {
    "tool_policy": "GEODE_TOOL_POLICY_STRICT",
    "decomposition": "GEODE_DECOMPOSITION_POLICY_STRICT",
    "reflection": "GEODE_REFLECTION_POLICY_STRICT",
    "skill_catalog": "GEODE_SKILL_CATALOG_STRICT",
    "agent_contract": "GEODE_AGENT_CONTRACTS_STRICT",
}
"""``GEODE_<KIND>_STRICT=1`` mapping — sibling audit 의 strict-load.
``prompt`` kind 는 ``_load_wrapper_override`` 가 env path 가 set 되면
자동 strict (W3 PR-3 패턴) 라 별도 STRICT flag 불필요."""


def _run_autoresearch_subprocess(
    *,
    repo_root: Path,
    dry_run: bool,
    audit_run_id: str = "",
    mutation_id: str = "",
    expected_dim: dict[str, float] | None = None,
    sibling_sot_kind: str = "",
    sibling_sot_path: Path | None = None,
    group_id: str = "",
    no_promote: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Spawn ``autoresearch/train.py`` for the post-mutation audit.

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

    P1-revised (2026-05-25 baseline RL grounding) — ``sibling_sot_kind``
    / ``sibling_sot_path`` / ``group_id`` / ``no_promote`` parameter
    추가. group sampling 의 sibling audit 가 (1) temp SoT path 를
    canonical SoT 대신 read 하도록 env override + STRICT, (2) baseline.json
    promote 차단 (--no-promote argv), (3) attribution row 에 group_id
    propagation.
    """
    argv = ["uv", "run", "python", "autoresearch/train.py"]
    if dry_run:
        argv.append("--dry-run")
    if no_promote:
        argv.append("--no-promote")
    env = os.environ.copy()
    if audit_run_id and mutation_id:
        env["GEODE_SIL_AUDIT_RUN_ID"] = audit_run_id
        env["GEODE_SIL_MUTATION_ID"] = mutation_id
        env["GEODE_SIL_EXPECTED_DIM"] = json.dumps(expected_dim or {}, ensure_ascii=False)
    if group_id:
        env["GEODE_SIL_GROUP_ID"] = group_id
    if sibling_sot_kind and sibling_sot_path is not None:
        env_var = _SIBLING_SOT_ENV_MAP.get(sibling_sot_kind)
        if env_var is None:
            raise ValueError(
                f"sibling_sot_kind {sibling_sot_kind!r} has no env mapping; "
                f"expected one of {list(_SIBLING_SOT_ENV_MAP)!r}"
            )
        env[env_var] = str(sibling_sot_path)
        strict_var = _SIBLING_SOT_STRICT_ENV_MAP.get(sibling_sot_kind)
        if strict_var is not None:
            env[strict_var] = "1"
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

    def propose_group(self, n: int) -> list[Proposal]:
        """P1-revised (2026-05-25) — propose N sibling Mutations in parallel.

        Frontier source: GRPO (DeepSeek R1) 의 group sampling + Promptbreeder
        의 multi-prompt 동시 평가. plan ``docs/plans/2026-05-25-baseline-fitness-rl-grounding.md``
        §4.3 MVP scope.

        Each sibling shares the same baseline state (same system + user
        prompt). Stochasticity comes from ``Settings.temperature_self_improving_mutation``
        (default 1.0, must be >= 0.1 — see _compute_group_advantage guard).
        N parallel calls run in a ThreadPoolExecutor — mutator API endpoint
        is stateless and each call is independent.

        - ``n=1`` → returns ``[self.propose()]`` (legacy fallback)
        - ``n>=2`` → parallel propose, N distinct Proposals (stochastic)

        Audit cost is N × per-cycle audit cost (apply_group_proposals
        spawns N sequential audit subprocesses); mutator LLM cost is N ×
        per-call cost (parallel here).
        """
        if n < 1:
            # Codex MCP review (slop) — n=0/negative 의 silent single propose
            # 는 misleading. config knob 은 ``Field(ge=1, le=8)`` 라 정상
            # path 에서 도달 안 함, 단 direct call 의 type-confusion 방지.
            raise ValueError(f"propose_group: n must be >= 1, got {n}")
        if n == 1:
            return [self.propose()]
        import concurrent.futures
        import contextvars

        # Codex MCP review (slop) — ThreadPoolExecutor 는 ContextVar 를 자동
        # 전파하지 않는다. session metrics / cost ledger ContextVar 가 thread
        # 안에서 unset → parent session aggregate 와 분리될 위험. 각 submit
        # 마다 ``copy_context()`` 로 main thread 의 ctx snapshot 을 fresh copy
        # 해 thread 안에서 run — 같은 Context 객체를 여러 thread 에서 enter
        # 할 수 없는 제약 (RuntimeError "already entered") 회피.

        def _propose_with_fresh_ctx() -> Proposal:
            return contextvars.copy_context().run(self.propose)

        proposals: list[Proposal] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as executor:
            futures = [executor.submit(_propose_with_fresh_ctx) for _ in range(n)]
            for future in concurrent.futures.as_completed(futures):
                proposals.append(future.result())
        return proposals

    def apply_group_proposals(self, proposals: list[Proposal]) -> Mutation | None:
        """P1-revised (2026-05-25) — apply N sibling proposals → audit →
        variance filter → advantage normalization → top-1 commit.

        Frontier source: DAPO Dynamic Sampling (variance filter) + GRPO
        whitening (advantage normalization) + EXAONE 4.5 zero-variance
        filter (production threshold). plan §4.3 + §5 (W3 env propagation
        infra 재활용).

        Steps:

        1. Mint single ``group_id`` for the cycle.
        2. For each sibling: write sibling SoT to OS temp file
           (``write_sibling_in_memory``) — does NOT touch the canonical
           ``autoresearch/state/policies/*.json`` SoT. Production
           AgenticLoop 의 reader 는 이 temp file 을 안 봄.
        3. Spawn N audit subprocesses sequentially (OL-P2 audit_lane=1
           host enforcement preserved). Each subprocess receives the
           sibling temp SoT path via env (``GEODE_<KIND>_OVERRIDE`` —
           W3 STRICT-mode infra) + ``GEODE_SIL_GROUP_ID`` + per-sibling
           ``GEODE_SIL_AUDIT_RUN_ID`` / ``GEODE_SIL_MUTATION_ID`` /
           ``GEODE_SIL_EXPECTED_DIM`` (W2/W3 PR-3 infra).
        4. Parse fitness from subprocess stdout (``FITNESS_RESULT: <json>``
           sentinel printed by ``autoresearch/train.py`` end-of-run).
        5. ``_compute_group_advantage`` — variance filter + whitening.
           ``status="filtered_low_variance"`` → cycle skip, no SoT commit,
           sibling temp files cleaned. Returns ``None``.
        6. ``status="ok"`` → top-1 by advantage. Apply top-1 mutation to
           canonical SoT via ``apply_mutation`` + ``append_audit_log``
           with ``kind="applied"`` + ``group_id`` + ``group_advantage``.
           Sibling rows (N-1) written with ``kind="applied_sibling"``.

        Returns the accepted Mutation, or ``None`` if variance filter
        triggered (cycle skipped).

        Requires ``rerun_enabled=True`` — group advantage 가 real fitness
        에 의존하므로 audit 가 실제로 fire 되어야 함.
        """
        if len(proposals) == 1:
            return self.apply_proposal(proposals[0])
        if not self.rerun_enabled:
            raise RuntimeError(
                "P1-revised group sampling requires rerun_enabled=True "
                "(group advantage needs actual fitness from audit). "
                "Use apply_proposal() with a single proposal for "
                "rerun_disabled mode."
            )
        if self.rerun_dry_run:
            # Codex MCP review #4 (2026-05-25) — dry-run synthetic fitness 는
            # 모든 sibling 에 deterministic 값 (autoresearch/train.py:770+
            # hardcoded dim_means) → group std=0 → variance filter 영구 trigger
            # → group 영구 skip 의 silent dead loop. 또한 train.py 의 W2 hook 가
            # ``if not args.dry_run`` 분기로 attribution row 자체 안 만듦.
            # rerun_dry_run=True 와 group N>=2 는 양립 불가능.
            raise RuntimeError(
                "P1-revised group sampling requires rerun_dry_run=False "
                "for N>=2 (dry-run synthesises deterministic fitness → "
                "group std=0 → variance filter 영구 trigger + attribution "
                "row 미작성). Either set rerun_dry_run=False to spend real "
                "audit budget, or use apply_proposal() with a single proposal."
            )

        from core.config import settings
        from core.config.self_improving_loop import load_self_improving_loop_config

        cfg = load_self_improving_loop_config()
        threshold = cfg.autoresearch.group_variance_threshold
        mutator_temp = settings.temperature_self_improving_mutation

        # Codex MCP review #5 (2026-05-25) — temperature guard 를 N audit 비용
        # 지출 전에 raise 하도록 사전 fire. _compute_group_advantage 도 동일
        # guard 보유 (defense in depth).
        if mutator_temp < 0.1:
            raise RuntimeError(
                f"P1-revised group sampling requires mutator temperature >= 0.1 "
                f"(current: {mutator_temp}). Settings.temperature_self_improving_mutation "
                f"또는 GEODE_TEMPERATURE_SELF_IMPROVING_MUTATION env 를 >= 0.1 로 set."
            )

        group_id = _mint_audit_run_id()
        log.info(
            "self-improving-loop: group %s — N=%d sibling propose+audit start",
            group_id,
            len(proposals),
        )

        fitness_values: list[float] = []
        audit_run_ids: list[str] = []
        sibling_sot_paths: list[Path] = []
        sibling_previous_values: list[str] = []

        try:
            for idx, proposal in enumerate(proposals):
                # In-memory (= OS temp file) sibling SoT
                new_sections, previous_value, sibling_sot_path = (
                    _apply_sibling_in_memory_with_value(proposal)
                )
                sibling_sot_paths.append(sibling_sot_path)
                sibling_previous_values.append(previous_value)

                audit_run_id = _mint_audit_run_id()
                audit_run_ids.append(audit_run_id)

                repo_root = (self.audit_log_path or MUTATION_AUDIT_LOG_PATH).resolve().parents[1]

                proc = _run_autoresearch_subprocess(
                    repo_root=repo_root,
                    dry_run=self.rerun_dry_run,
                    audit_run_id=audit_run_id,
                    mutation_id=proposal.mutation.mutation_id,
                    expected_dim=proposal.mutation.expected_dim,
                    sibling_sot_kind=proposal.mutation.target_kind,
                    sibling_sot_path=sibling_sot_path,
                    group_id=group_id,
                    no_promote=True,
                )
                fitness = _parse_fitness_from_subprocess_stdout(
                    proc.stdout, audit_run_id=audit_run_id, sibling_idx=idx
                )
                fitness_values.append(fitness)

            advantages, status = _compute_group_advantage(
                fitness_values,
                threshold,
                mutator_temperature=mutator_temp,
            )

            if status == "filtered_low_variance":
                log.info(
                    "self-improving-loop: group %s filtered (low variance, "
                    "std < %s). cycle skipped, no SoT commit.",
                    group_id,
                    threshold,
                )
                return None
            if status != "ok" or advantages is None:
                log.warning(
                    "self-improving-loop: group %s status=%s; no advantage computed",
                    group_id,
                    status,
                )
                return None

            # Top-1 by advantage
            best_idx = max(range(len(advantages)), key=lambda i: advantages[i])
            best_proposal = proposals[best_idx]
            log.info(
                "self-improving-loop: group %s — best=sibling[%d] advantage=%.4f fitness=%.4f",
                group_id,
                best_idx,
                advantages[best_idx],
                fitness_values[best_idx],
            )

            # Commit best to canonical SoT + apply row (kind="applied")
            _committed_sections, previous_value = apply_mutation(
                best_proposal.mutation,
                current_sections=best_proposal.target_sections,
            )
            try:
                log_path = append_audit_log(
                    best_proposal.mutation,
                    previous_value=previous_value,
                    log_path=self.audit_log_path,
                    audit_run_id=audit_run_ids[best_idx],
                    kind="applied",
                    group_id=group_id,
                    group_advantage=advantages[best_idx],
                )
            except OSError as exc:
                self._rollback_sot(
                    best_proposal.original_sections,
                    mutation=best_proposal.mutation,
                    exc=exc,
                )
                raise

            # Sibling rows (kind="applied_sibling")
            # Codex MCP review (slop) — previous_value 를 보존 (이전 ""
            # placeholder 였음). sibling 의 in-memory SoT 의 mutation 직전
            # 값 → history audit + dedup detection 에 의미.
            for i, sibling_proposal in enumerate(proposals):
                if i == best_idx:
                    continue
                append_audit_log(
                    sibling_proposal.mutation,
                    previous_value=sibling_previous_values[i],
                    log_path=self.audit_log_path,
                    audit_run_id=audit_run_ids[i],
                    kind="applied_sibling",
                    group_id=group_id,
                    group_advantage=advantages[i],
                )

            if self.commit_enabled:
                _git_commit_audit_log(log_path, mutation=best_proposal.mutation)

            self._append_self_improving_loop_index(best_proposal.mutation, previous_value)
            return best_proposal.mutation
        finally:
            for sibling_path in sibling_sot_paths:
                try:
                    sibling_path.unlink(missing_ok=True)
                except OSError:
                    log.warning(
                        "self-improving-loop: sibling temp file cleanup failed for %s",
                        sibling_path,
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
            self._rollback_sot(proposal.original_sections, mutation=proposal.mutation, exc=exc)
            raise
        if self.commit_enabled:
            _git_commit_audit_log(log_path, mutation=proposal.mutation)
        if self.rerun_enabled:
            repo_root = log_path.resolve().parents[1]
            self._invoke_autoresearch(
                repo_root,
                audit_run_id=audit_run_id,
                mutation=proposal.mutation,
            )
        self._append_self_improving_loop_index(proposal.mutation, previous_value)
        return proposal.mutation

    def run_once(self) -> Mutation | None:
        """Execute one full propose+apply iteration. Backwards-compat
        wrapper around :meth:`propose` + :meth:`apply_proposal` so
        existing callers (and the autoresearch self-improving loop)
        keep working unchanged.

        P1-revised (2026-05-25) — ``AutoresearchConfig.group_size`` knob
        분기:
        - ``group_size=1`` (default, legacy): :meth:`propose` +
          :meth:`apply_proposal` 그대로 (single mutation, REINFORCE-style)
        - ``group_size>=2``: :meth:`propose_group` +
          :meth:`apply_group_proposals` (DAPO Dynamic Sampling + GRPO
          advantage normalization + variance filter top-1 commit)

        Variance filter trigger 시 ``None`` 반환 (cycle skip, no SoT
        commit). legacy mode 는 항상 ``Mutation`` 반환.

        Raises :class:`ValueError` on parse / validation failure so
        the caller can decide whether to retry.
        """
        from core.config.self_improving_loop import load_self_improving_loop_config

        group_size = load_self_improving_loop_config().autoresearch.group_size
        if group_size <= 1:
            return self.apply_proposal(self.propose())
        proposals = self.propose_group(group_size)
        return self.apply_group_proposals(proposals)

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

    def _invoke_autoresearch(
        self,
        repo_root: Path,
        *,
        audit_run_id: str = "",
        mutation: Mutation | None = None,
    ) -> None:
        """Wrap the autoresearch subprocess so tests can override.

        W2/W3 (2026-05-25 attribution wiring) — propagate audit_run_id +
        mutation_id + expected_dim to the subprocess env so the
        attribution row written after the audit carries the same
        cross-ref keys as the apply row.
        """
        try:
            _run_autoresearch_subprocess(
                repo_root=repo_root,
                dry_run=self.rerun_dry_run,
                audit_run_id=audit_run_id,
                mutation_id=mutation.mutation_id if mutation is not None else "",
                expected_dim=mutation.expected_dim if mutation is not None else None,
            )
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
