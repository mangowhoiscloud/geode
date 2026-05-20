"""PR-AUDIT-5SLOT — self-improving loop 5 slot reader-wiring audit invariants.

이 테스트는 ``docs/audits/2026-05-21-self-improving-loop-5-slot-reader-audit.md``
의 각 인용을 grep-provable anchor 로 pin 한다. 두 가지 목적:

1. **ALIVE slot (prompt) 의 reader 가 사라지지 않음** 을 보장 — 진화 압력의
   유일한 경로가 회귀되면 즉시 알람.
2. **DEAD slot 4 개 (tool_policy / decomposition / retrieval / reflection)
   의 reader 부재** 를 명시적으로 marker — 미래에 reader 가 신설되면
   해당 test 가 명시적으로 갱신되도록 anchor 가 박혀있다 (S0a/b/c PR
   에서 이 파일을 함께 수정).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read(path: str) -> str:
    full = REPO_ROOT / path
    assert full.is_file(), f"missing file: {full}"
    return full.read_text(encoding="utf-8")


def _grep_py_in_dir(needle: str, subdir: str) -> list[str]:
    """Recursively grep ``needle`` in ``*.py`` under ``REPO_ROOT/subdir``,
    skipping test files and bytecode. Returns ``path:lineno:line`` strings."""
    hits: list[str] = []
    base = REPO_ROOT / subdir
    if not base.is_dir():
        return hits
    for path in base.rglob("*.py"):
        if "test_" in path.name:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for i, line in enumerate(content.splitlines(), 1):
            if needle in line:
                rel = path.relative_to(REPO_ROOT)
                hits.append(f"{rel}:{i}:{line}")
    return hits


# ---------------------------------------------------------------------------
# Audit doc presence + core anchors
# ---------------------------------------------------------------------------


AUDIT_DOC = "docs/audits/2026-05-21-self-improving-loop-5-slot-reader-audit.md"


def test_audit_doc_exists() -> None:
    text = _read(AUDIT_DOC)
    assert "5 Slot Reader-Wiring Audit" in text


def test_audit_doc_pins_1_alive_4_dead() -> None:
    """결론 한 줄 anchor."""
    text = _read(AUDIT_DOC)
    assert "1/5 ALIVE, 4/5 DEAD" in text


def test_audit_doc_names_all_5_slots() -> None:
    text = _read(AUDIT_DOC)
    for slot in ("prompt", "tool_policy", "decomposition", "retrieval", "reflection"):
        assert f"`{slot}`" in text, f"slot not mentioned: {slot}"


def test_audit_doc_cites_policies_py_self_admission() -> None:
    """policies.py docstring 의 PR-6 자백 인용."""
    text = _read(AUDIT_DOC)
    assert "PR-6 stops at the *file format + dispatcher*" in text


# ---------------------------------------------------------------------------
# ALIVE slot — prompt reader 가 살아있어야 함
# ---------------------------------------------------------------------------


def test_prompt_slot_reader_alive_in_system_prompt() -> None:
    """``wrapper-sections.json`` reader 는 ``system_prompt.py`` 에 살아있어야 한다."""
    src = _read("core/agent/system_prompt.py")
    assert "_load_wrapper_override" in src
    assert "wrapper-sections.json" in src
    assert "build_system_prompt" in src


def test_prompt_reader_is_called_in_agentic_loop() -> None:
    """``build_system_prompt`` 가 실제로 호출되는 경로가 살아있어야 한다."""
    # AgenticLoop 또는 그 호출 사이트 어디서든 build_system_prompt 가 호출돼야 함.
    hits = _grep_py_in_dir("build_system_prompt", "core/agent")
    # 최소 2개 hit (정의 + 호출자 1개 이상)
    assert len(hits) >= 2, f"build_system_prompt should have a caller; got {hits}"


# ---------------------------------------------------------------------------
# DEAD slot — reader 부재 marker
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sot_filename",
    [
        "tool-policy.json",
        "decomposition.json",
        "retrieval.json",
        "reflection.json",
    ],
)
def test_dead_slot_has_no_inference_reader(sot_filename: str) -> None:
    """DEAD slot 의 SoT 파일명이 ``core/agent/`` 인퍼런스 경로 어디에서도
    참조되지 않음을 pin. S0a/b/c PR 에서 reader 가 신설되면 이 test 가
    실패해서 함께 갱신해야 한다 (의도된 anchor 회귀)."""
    hits = _grep_py_in_dir(sot_filename, "core/agent")
    # 0 hits 가 정상 (DEAD)
    assert hits == [], (
        f"DEAD slot {sot_filename!r} 의 reader 가 core/agent/ 에서 발견됨. "
        f"S0a/b/c 권고 의 reader 신설이라면 이 test 와 audit doc 의 상태표를 "
        f"ALIVE 로 갱신해야 함. hits={hits}"
    )


def test_decomposition_slot_dead_via_hardcoded_goal_decomposer() -> None:
    """decomposition slot 의 dead 사유 — GoalDecomposer 가 hardcoded."""
    src = _read("core/agent/loop/_decomposition.py")
    assert "GoalDecomposer" in src
    # decomposition.json 을 읽는 reader 없음
    assert "decomposition.json" not in src


def test_reflection_slot_dead_via_hardcoded_tool_schema() -> None:
    """reflection slot 의 dead 사유 — _REFLECTION_TOOL 가 module-level constant."""
    src = _read("core/agent/loop/_reflection.py")
    assert "_REFLECTION_TOOL" in src
    # reflection.json 을 읽는 reader 없음
    assert "reflection.json" not in src


# ---------------------------------------------------------------------------
# Mutation target 등록은 5축 모두 유지 (정의는 그대로 — reader 만 부재)
# ---------------------------------------------------------------------------


def test_all_5_slots_still_registered_as_mutation_targets() -> None:
    """audit 결과로 mutation target 정의 자체를 손대지는 않음. 단지 reader
    부재만 진단. S0d (retrieval deprecate) 결정 전까지는 5축 그대로 유지."""
    src = _read("core/self_improving_loop/policies.py")
    for slot in ("prompt", "tool_policy", "decomposition", "retrieval", "reflection"):
        assert f'"{slot}"' in src, f"mutation target {slot} should still be registered"
