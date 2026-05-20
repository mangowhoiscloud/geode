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
    # ALIVE/DEAD/DEPRECATED count — S0a/S0b/S0c/S0d 머지 (2026-05-21) 후.
    # 현재 상태: 4 ALIVE (prompt + tool_policy + decomposition + reflection) /
    # 0 DEAD / 1 DEPRECATED (retrieval). 5축 → 4축 명시 축소.
    assert text.count("**ALIVE**") == 4, (
        f"S0a-d 후 ALIVE slot 은 정확히 4 개여야 함. count={text.count('**ALIVE**')}"
    )
    assert text.count("**DEAD**") == 0, (
        f"S0a-d 후 DEAD slot 은 0 개여야 함. count={text.count('**DEAD**')}"
    )
    assert text.count("**DEPRECATED**") >= 1, (
        f"S0d 후 retrieval 이 DEPRECATED 로 명시되어야 함. count={text.count('**DEPRECATED**')}"
    )


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
    인프라를 재사용한다는 결정 명시 + 인용된 파일의 실제 content 검증."""
    text = _read_adr()
    assert "ranker.py" in text
    assert "ELO" in text
    assert "3-voter" in text
    # Codex MCP 검증 catch 반영 — 문자열 매칭만으론 부족, 실제 파일이
    # ELO + voter panel 형태인지 content 검증.
    ranker_src = (REPO_ROOT / "plugins/seed_generation/agents/ranker.py").read_text(
        encoding="utf-8"
    )
    assert "Elo" in ranker_src or "ELO" in ranker_src, (
        "ranker.py 에 Elo/ELO 식별자가 없음 — ADR 의 재사용 claim 검증 실패."
    )
    assert "voter" in ranker_src.lower(), (
        "ranker.py 에 voter 식별자가 없음 — ADR 의 3-voter panel 재사용 claim 검증 실패."
    )


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


def test_decision_gates_have_measurable_thresholds() -> None:
    """Codex MCP catch — G2/G4/G5 가 "정체" / "안정화" 같은 측정 불가
    표현이 아니라 데이터-기반 측정 임계값을 명시해야 함 (Socratic Q3:
    cannot measure → defer 원칙). 적어도 측정 window (주 단위) + 비교 기준
    (stderr / 상관계수 / 편향 %) 가 본문에 등장해야 함."""
    text = _read_adr()
    # 측정 window 단위
    assert "주 측정" in text, "게이트 트리거 조건에 측정 window (주 단위) 명시 필요."
    # 측정 기준 — 적어도 stderr 또는 상관계수가 등장
    assert "stderr" in text or "상관계수" in text, (
        "게이트 트리거 조건에 데이터-기반 비교 기준 (stderr / 상관계수) 필요."
    )


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
    """ADR 이 1/5 누수의 출처 (`policies.py:29-37` docstring) 를 명시 인용 +
    인용된 라인에 실제 자백이 존재하는지 content 검증."""
    text = _read_adr()
    assert "policies.py:29-37" in text
    # Codex MCP catch 반영 — 인용 라인의 실제 content 검증
    policies_src = (REPO_ROOT / "core/self_improving_loop/policies.py").read_text(encoding="utf-8")
    assert "PR-6 stops at the *file format + dispatcher*" in policies_src, (
        "policies.py 의 PR-6 자백 docstring 이 실제로 존재해야 함 — ADR 의 인용 근거."
    )


def test_adr_cites_train_py_dim_weights_location() -> None:
    """ADR 이 1/17 누수의 출처 (`train.py:220-250` dim weights) 를 명시 인용 +
    train.py 의 실제 17-dim weights 존재 검증."""
    text = _read_adr()
    assert "autoresearch/train.py:220-250" in text
    # Codex MCP catch 반영 — 실제로 17-dim 가중치 정의가 있는지 content 검증
    train_src = (REPO_ROOT / "autoresearch/train.py").read_text(encoding="utf-8")
    # 17-dim 의 핵심 alignment dim 들이 weights 매핑에 등장해야 함
    for dim in (
        "broken_tool_use",
        "prefill_susceptibility",
        "manipulated_by_developer",
    ):
        assert dim in train_src, f"train.py 에 17-dim 의 {dim} 가 없음 — ADR 인용 stale 가능."


# ---------------------------------------------------------------------------
# 7. 4축 mutation target 정의 — S0d 이후 retrieval deprecate
# ---------------------------------------------------------------------------


def test_active_4_slots_registered_as_mutation_targets() -> None:
    """S0d (2026-05-21) 머지 후 retrieval 은 TARGET_KINDS 에서 제거.
    나머지 4 slot 만 mutation 대상."""
    import importlib

    mod = importlib.import_module("core.self_improving_loop.policies")
    target_kinds = set(getattr(mod, "TARGET_KINDS", ()))
    expected = {"prompt", "tool_policy", "decomposition", "reflection"}
    assert target_kinds == expected, (
        f"S0d 후 TARGET_KINDS 는 정확히 4 slot 이어야 함 (retrieval 제외). "
        f"got={target_kinds}, expected={expected}"
    )


def test_retrieval_deprecated_but_path_constant_preserved() -> None:
    """S0d 가 retrieval 을 deprecate 하면서도 path constant + dict 매핑은
    보존해서 미래 RAG 인프라 신설 시 별도 ADR 로 복원 가능."""
    src = (REPO_ROOT / "core/self_improving_loop/policies.py").read_text(encoding="utf-8")
    # TARGET_KINDS 에서 제거 (== 4 slot 만)
    assert '"retrieval",' not in src.split("TARGET_KINDS")[1].split(")")[0], (
        "retrieval 은 TARGET_KINDS 에서 제거되어야 함"
    )
    # 단 path constant 매핑은 보존
    assert '"retrieval": GLOBAL_RETRIEVAL_POLICY_PATH' in src, (
        "GLOBAL_RETRIEVAL_POLICY_PATH 매핑은 보존되어야 함 (미래 복원 가능)"
    )
    # core/paths.py 의 path constant 도 보존
    paths_src = (REPO_ROOT / "core/paths.py").read_text(encoding="utf-8")
    assert "GLOBAL_RETRIEVAL_POLICY_PATH" in paths_src
