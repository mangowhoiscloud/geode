"""ADR-012 — Self-Improvement Surface Tiers invariants.

ADR 문서의 필수 section anchor + cross-reference 무결성을 pin 한다.
ADR-011 / PR-AUDIT-5SLOT 패턴 그대로.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADR_DOC = "docs/adr/ADR-012-self-improvement-surface-tiers.md"


def _read_adr() -> str:
    path = REPO_ROOT / ADR_DOC
    assert path.is_file(), f"ADR-012 missing: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. 파일 존재 + status + 핵심 section anchor
# ---------------------------------------------------------------------------


def test_adr_012_exists_with_status_proposed() -> None:
    text = _read_adr()
    assert text.startswith("# ADR-012: Self-Improvement Surface Tiers")
    assert "Proposed (2026-05-21)" in text


def test_adr_012_has_required_top_sections() -> None:
    text = _read_adr()
    for header in ("## Status", "## Context", "## Decision", "## Consequences", "## Reference"):
        assert header in text, f"missing top section: {header}"


def test_adr_012_decision_lists_4_axes() -> None:
    """Decision 의 4 축이 모두 명시되어야 함."""
    text = _read_adr()
    for token in (
        "Tier 1 / Tier 2",
        "Fitness 다축화",
        "Surrogate fine-tune",
        "성장 곡선",
    ):
        assert token in text, f"missing decision axis: {token}"


# ---------------------------------------------------------------------------
# 2. Tier 1 / Tier 2 영역 명시
# ---------------------------------------------------------------------------


def test_tier_1_lists_all_5_slots_with_alive_dead_status() -> None:
    text = _read_adr()
    for slot in ("prompt", "tool_policy", "decomposition", "retrieval", "reflection"):
        assert f"`{slot}`" in text, f"slot missing in Tier 1: {slot}"
    # ALIVE 1개 + DEAD 4개 명시
    assert "**ALIVE**" in text
    assert text.count("**DEAD**") >= 4


def test_tier_2_forbids_mutator_and_fitness_gate() -> None:
    """자기수정 재귀 회피의 핵심 영역들."""
    text = _read_adr()
    for must_be_forbidden in (
        "Self-improving runner",
        "Fitness gate",
        "Mutator agent contract",
        "CI ratchet",
        "HookSystem",
        "Bootstrap",
    ):
        assert must_be_forbidden in text, f"Tier 2 missing forbidden area: {must_be_forbidden}"


# ---------------------------------------------------------------------------
# 3. Fitness 3축 + admire_means / ux_means
# ---------------------------------------------------------------------------


def test_fitness_three_axes_named() -> None:
    text = _read_adr()
    for axis in ("dim_means", "ux_means", "admire_means"):
        assert axis in text, f"fitness axis not named: {axis}"


def test_admire_means_reuses_ranker_panel() -> None:
    """admire_means 가 seed_generation ranker 의 ELO + 3-voter panel
    인프라를 재사용한다는 결정 명시."""
    text = _read_adr()
    assert "ranker.py" in text
    assert "ELO" in text
    assert "3-voter" in text


# ---------------------------------------------------------------------------
# 4. Surrogate fine-tune 4 경로 (RAG drop 명시)
# ---------------------------------------------------------------------------


def test_surrogate_4_paths_named() -> None:
    text = _read_adr()
    # 4 경로 모두 명시
    for path in ("few-shot pool", "mutator candidate reference", "judge calibration", "reflection"):
        assert path in text, f"surrogate path not named: {path}"


def test_rag_path_explicitly_dropped() -> None:
    """경로 ② RAG vector store 가 drop 결정 — `retrieval` reader 부재
    + 외부 인프라 비용 대비 효과 불명확. 미래 reconsider 명시."""
    text = _read_adr()
    assert "RAG vector store 는 drop" in text or "RAG vector store** 는 drop" in text
    assert "reconsider" in text


# ---------------------------------------------------------------------------
# 5. S0/S1-S5/M1-M5 + G1-G6 시퀀스
# ---------------------------------------------------------------------------


def test_s0_dead_slot_remediation_sub_prs_listed() -> None:
    text = _read_adr()
    for sub in ("S0a", "S0b", "S0c", "S0d"):
        assert sub in text, f"S0 sub-PR missing: {sub}"


def test_short_term_s1_through_s5_listed() -> None:
    text = _read_adr()
    for sub in ("S1", "S2", "S3", "S4", "S5"):
        assert sub in text, f"short-term sub-PR missing: {sub}"


def test_mid_term_m1_through_m5_listed() -> None:
    text = _read_adr()
    for sub in ("M1", "M2", "M3", "M4.0", "M4.1", "M4.2", "M5"):
        assert sub in text, f"mid-term sub-PR missing: {sub}"


def test_decision_gates_g1_through_g6_listed() -> None:
    text = _read_adr()
    for gate in ("G1", "G2", "G3", "G4", "G5", "G6"):
        assert f"| {gate} |" in text, f"gate not in decision table: {gate}"


# ---------------------------------------------------------------------------
# 6. Cross-reference 무결성 — audit doc + policies.py 자백
# ---------------------------------------------------------------------------


def test_adr_cites_pr_audit_5slot() -> None:
    """ADR 이 audit doc 을 근거로 참조해야 함."""
    text = _read_adr()
    assert "2026-05-21-self-improving-loop-5-slot-reader-audit.md" in text


def test_adr_cites_audit_doc_actually_exists() -> None:
    """cited audit doc 이 실제 존재해야 함."""
    audit_path = REPO_ROOT / "docs/audits/2026-05-21-self-improving-loop-5-slot-reader-audit.md"
    assert audit_path.is_file(), f"cited audit doc missing: {audit_path}"


def test_adr_cites_policies_self_admission_location() -> None:
    """ADR 이 1/5 누수의 출처 (`policies.py:29-37` docstring) 를 명시 인용."""
    text = _read_adr()
    assert "policies.py:29-37" in text


def test_adr_cites_train_py_dim_weights_location() -> None:
    """ADR 이 1/17 누수의 출처 (`train.py:220-250` dim weights) 를 명시 인용."""
    text = _read_adr()
    assert "autoresearch/train.py:220-250" in text


# ---------------------------------------------------------------------------
# 7. 5축 mutation target 정의는 그대로 유지 — ADR 은 reader 처치만 결정
# ---------------------------------------------------------------------------


def test_all_5_slots_still_registered_as_mutation_targets() -> None:
    """ADR 이 reader 신설을 결정하지만 mutation target 정의 자체는
    손대지 않음 (S0d 의 retrieval deprecate 결정 전까지)."""
    src = (REPO_ROOT / "core/self_improving_loop/policies.py").read_text(encoding="utf-8")
    for slot in ("prompt", "tool_policy", "decomposition", "retrieval", "reflection"):
        assert f'"{slot}"' in src, f"mutation target {slot} should still be registered"
