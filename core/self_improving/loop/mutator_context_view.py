"""C.7 (2026-05-25) — unified mutator context view (PR-27).

Memory ``project_autoresearch_fragmentation_audit.md`` F2 — mutator
context 가 5+ source 에 분산 (baseline_snapshot / kind-policy snapshots /
program.md / meta_review / mutations history). PR-12 ``mutations_reader``
이 history 표면화, PR-26 ``cross_run_join`` 이 cross-run key 통합.
C.7 는 그 위 layer — **하나의 view dataclass + composition helper**.

본 module = **read-side composition** (write-side 영향 X):

- :class:`MutatorContextView` — Pydantic snapshot 의 5+ source 합본
- :func:`compose_mutator_context_view(...)` — 5 source 가 각자 추출된
  optional Any 를 받아 dataclass instance 로 packing
- :func:`source_count(view)` — non-None source count (운영자 진단 metric)

caller (runner.py 의 build_runner_context) 가 이 view 를 단일 객체로
들고 다닐 수 있어 5+ field 풀이 사라짐. wiring 후속 PR.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MutatorContextView(BaseModel):
    """5+ source 의 합본 view.

    각 field 가 ``None`` 이면 그 source 가 부재 (bootstrap / pre-feature
    runs). caller 가 None 체크로 graceful 분기.

    ``extra="allow"`` 라 신규 source 추가 시 본 schema 변경 없이 forward-
    compat dict field 로 받음 — but 명시적 field 가 grep-able 이라 우선.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    baseline_snapshot: Any = None
    """BaselineSnapshot — plugins.seed_generation.baseline_reader.
    last successful audit 의 dim_means / dim_stderr / metadata."""

    policy_snapshots: dict[str, Any] = Field(default_factory=dict)
    """5 kind policy snapshots — {kind_name: policy_payload}.
    tool_policy / decomposition / reflection / skill_catalog /
    agent_contract. 5 kind 각각 disk file 또는 fallback."""

    program_md: str = ""
    """core/self_improving/program.md content (raw). mutator 가 frontier
    convention reference 로 사용."""

    meta_review_snapshot: Any = None
    """MetaReviewSnapshot — plugins.seed_generation.baseline_reader.
    cross-run priors. bootstrap 시 None."""

    recent_mutations: list[Any] = Field(default_factory=list)
    """PR-12 mutations_reader 결과 — last N apply rows (history).
    mutator 가 self-repetition 회피용 참조."""

    cross_run_key: Any = None
    """PR-26 CrossRunJoinKey — 현재 cycle 의 run_id + gen_tag.
    cross-run audit join 의 anchor. bootstrap 시 None."""


def compose_mutator_context_view(
    *,
    baseline_snapshot: Any = None,
    policy_snapshots: dict[str, Any] | None = None,
    program_md: str = "",
    meta_review_snapshot: Any = None,
    recent_mutations: list[Any] | None = None,
    cross_run_key: Any = None,
) -> MutatorContextView:
    """Pack 5+ source into a single immutable view.

    Caller does the actual source loading (each source has its own
    reader); this helper just composes the result. Defaults match
    "source absent" semantics so a bootstrap caller can pass only
    what it has.
    """
    return MutatorContextView(
        baseline_snapshot=baseline_snapshot,
        policy_snapshots=policy_snapshots or {},
        program_md=program_md,
        meta_review_snapshot=meta_review_snapshot,
        recent_mutations=recent_mutations or [],
        cross_run_key=cross_run_key,
    )


def source_count(view: MutatorContextView) -> int:
    """Return the count of non-empty source fields — operator metric.

    Counts a source as "present" when:
    - baseline_snapshot / meta_review_snapshot / cross_run_key: non-None
    - policy_snapshots: non-empty dict
    - program_md: non-empty string
    - recent_mutations: non-empty list
    """
    count = 0
    if view.baseline_snapshot is not None:
        count += 1
    if view.policy_snapshots:
        count += 1
    if view.program_md:
        count += 1
    if view.meta_review_snapshot is not None:
        count += 1
    if view.recent_mutations:
        count += 1
    if view.cross_run_key is not None:
        count += 1
    return count


__all__ = [
    "MutatorContextView",
    "compose_mutator_context_view",
    "source_count",
]
