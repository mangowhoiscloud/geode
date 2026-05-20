"""ADR-013 — Mutation Surface Expansion via JSON Schema Pattern invariants.

ADR 본문의 핵심 section anchor + 6 T-series 표면 명세 + AlphaEvolve
명시적 배제 + frontier reference 정합성 검증.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADR_DOC = "docs/adr/ADR-013-mutation-surface-expansion-via-json-schema.md"


def _read_adr() -> str:
    path = REPO_ROOT / ADR_DOC
    assert path.is_file(), f"ADR-013 missing: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Status + 핵심 sections
# ---------------------------------------------------------------------------


def test_adr_013_exists_with_status_proposed() -> None:
    text = _read_adr()
    assert text.startswith("# ADR-013: Mutation Surface Expansion via JSON Schema Pattern")
    assert "Proposed (2026-05-21)" in text


def test_adr_013_has_required_top_sections() -> None:
    text = _read_adr()
    for header in ("## Status", "## Context", "## Decision", "## Consequences", "## Reference"):
        assert header in text, f"missing top section: {header}"


# ---------------------------------------------------------------------------
# 2. 6 T-series 표면 명세
# ---------------------------------------------------------------------------


def test_adr_013_lists_all_6_t_surfaces() -> None:
    text = _read_adr()
    for t in ("T1", "T2", "T3", "T4", "T5", "T6"):
        assert f"#### {t} — " in text, f"missing T-surface section: {t}"


def test_adr_013_names_all_6_sot_files() -> None:
    text = _read_adr()
    for sot in (
        "tool-descriptions.json",
        "skill-catalog.json",
        "style-guide.json",
        "provider-routing.json",
        "cache-policy.json",
        "heuristics.json",
    ):
        assert sot in text, f"SoT not mentioned: {sot}"


def test_adr_013_each_t_has_inference_entry_point() -> None:
    """각 T 표면이 inference 진입점 + 영향 fitness 축 명시."""
    text = _read_adr()
    for entry in (
        "load_all_tool_definitions",  # T1
        "SkillRegistry",  # T2
        "build_system_prompt",  # T3
        "core/llm/router/calls/_route.py",  # T4 (post-Codex fix — package not single module)
        "apply_messages_cache_control",  # T5
        "_is_clearly_simple",  # T6
    ):
        assert entry in text, f"inference entry point not cited: {entry}"


def test_adr_013_inference_entry_points_actually_exist_in_repo() -> None:
    """Codex MCP catch — source-backed verification. ADR 의 inference
    진입점이 실제 repo 에 존재."""
    # T1
    assert (REPO_ROOT / "core/tools/base.py").is_file()
    # T2 — core/skills/skills.py 의 SkillRegistry
    skills_src = (REPO_ROOT / "core/skills/skills.py").read_text(encoding="utf-8")
    assert "SkillRegistry" in skills_src or "Registry" in skills_src
    # T3
    sp_src = (REPO_ROOT / "core/agent/system_prompt.py").read_text(encoding="utf-8")
    assert "build_system_prompt" in sp_src
    # T4 — core/llm/router 가 package
    assert (REPO_ROOT / "core/llm/router").is_dir()
    # T5
    anth_src = (REPO_ROOT / "core/llm/providers/anthropic.py").read_text(encoding="utf-8")
    assert "apply_messages_cache_control" in anth_src
    # T6
    gd_src = (REPO_ROOT / "core/orchestration/goal_decomposer.py").read_text(encoding="utf-8")
    assert "_is_clearly_simple" in gd_src


# ---------------------------------------------------------------------------
# 3. JSON SoT 패턴 - 5-element 구조
# ---------------------------------------------------------------------------


def test_pattern_5_element_structure() -> None:
    """S0a 검증된 5-element 패턴 (SoT + path constant + reader + entry + env)."""
    text = _read_adr()
    for element in (
        "SoT 파일",
        "Path constant",
        "Reader 모듈",
        "Inference 진입점",
        "Env var override",
    ):
        assert element in text, f"5-element pattern missing: {element}"


def test_lifecycle_4_step() -> None:
    """동작 원리 4-step lifecycle 명시."""
    text = _read_adr()
    for step in ("1. operator", "2. 다음 에이전트", "3. apply_", "4. 에이전트 응답"):
        assert step in text, f"lifecycle step missing: {step}"


# ---------------------------------------------------------------------------
# 4. AlphaEvolve 명시적 배제
# ---------------------------------------------------------------------------


def test_alphaevolve_explicitly_excluded() -> None:
    text = _read_adr()
    assert "AlphaEvolve" in text
    assert "명시적" in text and "배제" in text
    # 배제 사유 4 종 명시
    for risk in (
        "자기수정 재귀",
        "Silent breakage",
        "Goodhart on benchmark",
        "Dependency chain",
    ):
        assert risk in text, f"AlphaEvolve exclusion risk missing: {risk}"


def test_json_mutation_only_principle() -> None:
    """ADR-013 의 핵심 원칙 — JSON mutation only, 코드 변경 0."""
    text = _read_adr()
    assert "JSON mutation only" in text or "JSON mutation 만" in text or "코드 변경 0" in text


# ---------------------------------------------------------------------------
# 5. Frontier reference 정합성
# ---------------------------------------------------------------------------


def test_frontier_references_per_surface() -> None:
    """각 T 표면의 frontier 사례 인용."""
    text = _read_adr()
    references = {
        "T1": "OpenAI function calling",
        "T2": "Voyager",
        "T3": "Anthropic Claude personality",
        "T4": "OpenRouter",
        "T5": "Anthropic prompt caching",
        "T6": "Promptbreeder",
    }
    for surface, ref in references.items():
        assert ref in text, f"{surface} frontier reference missing: {ref}"


def test_cross_reference_to_adr_012() -> None:
    """ADR-013 이 ADR-012 의 S0a 패턴 + Tier 2 정책을 참조."""
    text = _read_adr()
    assert "ADR-012" in text
    assert "S0a" in text
    assert "Tier 2" in text


# ---------------------------------------------------------------------------
# 6. 우선순위 + 후속 PR 시퀀스
# ---------------------------------------------------------------------------


def test_priority_table_with_6_surfaces() -> None:
    text = _read_adr()
    # 우선순위 1-6 모두 명시
    for priority in ("| 1 |", "| 2 |", "| 3 |", "| 4 |", "| 5 |", "| 6 |"):
        assert priority in text, f"priority entry missing: {priority}"


def test_followup_pr_sequence_t1_through_t6() -> None:
    text = _read_adr()
    for sub_pr in (
        "T1 — Tool",
        "T2 — Skill",
        "T3 — Response",
        "T4 — Provider",
        "T5 — Cache",
        "T6 — Heuristic",
    ):
        assert sub_pr in text, f"follow-up PR missing: {sub_pr}"


# ---------------------------------------------------------------------------
# 7. ADR-012 와의 호환성 - 6 표면이 모두 fitness 축에 영향
# ---------------------------------------------------------------------------


def test_each_surface_cites_fitness_axis_impact() -> None:
    """각 표면이 dim_means / ux_means / admire_means / bench_means 중 어디에
    영향 미치는지 명시 — ADR-012 의 fitness 다축화와 호환."""
    text = _read_adr()
    for axis in ("broken_tool_use", "ux_means", "token_cost_norm", "gaia_accuracy"):
        assert axis in text, f"fitness axis impact not cited: {axis}"


# ---------------------------------------------------------------------------
# 8. ADR file 자체의 존재 + ADR 시퀀스 위치
# ---------------------------------------------------------------------------


def test_adr_013_in_adr_directory() -> None:
    """ADR-013 이 docs/adr/ 디렉토리에 존재 (ADR 시퀀스 부합)."""
    path = REPO_ROOT / "docs/adr/ADR-013-mutation-surface-expansion-via-json-schema.md"
    assert path.is_file()


def test_adr_012_still_exists_as_predecessor() -> None:
    """ADR-013 의 predecessor 인 ADR-012 가 존재 (ADR 시퀀스)."""
    path = REPO_ROOT / "docs/adr/ADR-012-self-improvement-surface-tiers.md"
    assert path.is_file()
