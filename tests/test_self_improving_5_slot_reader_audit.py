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


# Inference reader 가 들어갈 수 있는 모든 코드 디렉토리. ``core/agent``
# 외에도 ``core/orchestration`` (e.g. GoalDecomposer), ``core/skills``,
# ``plugins/``, ``autoresearch/`` 까지 포함 — DEAD anchor 가 다른
# 디렉토리에 reader 가 신설되는 경우도 catch 하도록.
_READER_SEARCH_DIRS: tuple[str, ...] = (
    "core/agent",
    "core/orchestration",
    "core/skills",
    "core/llm",
    "core/self_improving_loop",
    "plugins",
    "autoresearch",
)


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


def _grep_inference_dirs(needle: str) -> list[str]:
    """Aggregate ``_grep_py_in_dir`` over the full inference reader search
    surface (all 7 dirs). Skips matches inside ``self_improving_loop``
    mutation infra (policies.py / runner.py) because those define / dispatch
    the SoT files, not consume them — that's exactly the bug audit pins."""
    hits: list[str] = []
    for sub in _READER_SEARCH_DIRS:
        for line in _grep_py_in_dir(needle, sub):
            # ``policies.py`` 와 ``runner.py`` 는 SoT 정의/디스패처. inference reader 아님.
            if "self_improving_loop/policies.py" in line:
                continue
            if "self_improving_loop/runner.py" in line:
                continue
            hits.append(line)
    return hits


# ---------------------------------------------------------------------------
# Audit doc presence + core anchors
# ---------------------------------------------------------------------------


AUDIT_DOC = "docs/audits/2026-05-21-self-improving-loop-5-slot-reader-audit.md"


def test_audit_doc_exists() -> None:
    text = _read(AUDIT_DOC)
    assert "5 Slot Reader-Wiring Audit" in text


def test_audit_doc_pins_1_alive_4_dead() -> None:
    """결론 한 줄 anchor. S0a-d 4단계 후속 갱신 섹션 모두 존재."""
    text = _read(AUDIT_DOC)
    assert "1/5 ALIVE, 4/5 DEAD" in text  # 원본 audit 시점 사실
    assert "Post-S0a" in text
    assert "Post-S0b" in text
    assert "Post-S0c" in text
    assert "Post-S0d" in text  # retrieval deprecate
    assert "4/4 ALIVE" in text  # 현재 상태 (S0d 후 deprecate 한 retrieval 제외)


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
    """``build_system_prompt`` 가 실제로 호출되는 경로가 살아있어야 한다.
    실제 chain (Codex MCP 검증): system_prompt.py → core/agent/loop/_context.py
    → core/agent/loop/agent_loop.py."""
    hits = _grep_inference_dirs("build_system_prompt")
    # 최소 2개 hit (정의 + 호출자 1개 이상).
    assert len(hits) >= 2, f"build_system_prompt should have a caller; got {hits}"


# ---------------------------------------------------------------------------
# DEAD slot — reader 부재 marker
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sot_filename",
    [
        # ADR-012 S0a/S0b/S0c/S0d (2026-05-21) 머지 후:
        # - tool-policy.json (S0a) / reflection.json (S0b) / decomposition.json
        #   (S0c) 는 ALIVE — 각각의 reader 가 core/agent/*_policy.py 에 존재
        # - retrieval.json (S0d) 는 DEPRECATED — TARGET_KINDS 에서 제거됨.
        #   reader 부재 검증 자체는 의미 없음 (mutation dispatch 안 함). 이
        #   parametrize 에서 제거되어 빈 list.
        # parametrize 가 비어있으면 test 가 실행되지 않으므로, 명시적
        # historical anchor 1개 유지 — placeholder file 명으로 0 hits 보장.
        "DEPRECATED_no_active_dead_slot.json",
    ],
)
def test_dead_slot_has_no_inference_reader(sot_filename: str) -> None:
    """S0a-d 머지 후 active dead slot 없음. parametrize 의 placeholder 는
    "현재 dead slot 0개" 라는 anchor 의 historical marker. 미래에 dead slot
    이 다시 생기면 (예: retrieval RAG 신설 후 reader 미완) 이 list 에 추가."""
    hits = _grep_inference_dirs(sot_filename)
    # 0 hits 가 정상 — placeholder file 명이라 항상 0.
    assert hits == [], f"placeholder {sot_filename!r} 에서 hit 가 발견됨 — 비정상. hits={hits}"


def test_tool_policy_slot_is_now_alive_post_s0a() -> None:
    """ADR-012 S0a 머지 이후 ``tool-policy.json`` 은 ALIVE — reader 가
    ``core/agent/tool_policy.py`` 에 존재 + ``_helpers.py`` 의 도구 통합
    경로에서 실제로 호출됨. PR-AUDIT-5SLOT 의 의도된 회귀 marker 의
    발화 결과 (Codex MCP catch — cosmetic 검증 → call chain 검증)."""
    hits = _grep_inference_dirs("tool-policy.json")
    # tool_policy.py 의 path constant alias 위치 + _helpers.py 의 호출 위치
    assert any("tool_policy.py" in h for h in hits), (
        f"tool-policy.json 이 core/agent/tool_policy.py 에서 발견되어야 함. hits={hits}"
    )
    # Call chain 검증 — _helpers.get_agentic_tools 가 _load_tool_policy_override 를 호출.
    helpers_src = (REPO_ROOT / "core/agent/loop/_helpers.py").read_text(encoding="utf-8")
    assert "_load_tool_policy_override" in helpers_src, (
        "_helpers.py 가 _load_tool_policy_override 를 import/호출해야 함 — "
        "reader 가 inference 경로에 실제로 wired 됐는지 검증."
    )
    assert "apply_tool_policy" in helpers_src, (
        "_helpers.py 가 apply_tool_policy 를 호출해야 함 — 정책이 도구 목록에 적용되는지."
    )


def test_decomposition_slot_is_now_alive_post_s0c() -> None:
    """ADR-012 S0c 머지 이후 ``decomposition.json`` 은 ALIVE — reader 가
    ``core/agent/decomposition_policy.py`` 에 존재 + ``goal_decomposer.py``
    의 ``_llm_decompose`` 에서 실제로 호출됨."""
    hits = _grep_inference_dirs("decomposition.json")
    assert any("decomposition_policy.py" in h for h in hits), (
        f"decomposition.json 이 core/agent/decomposition_policy.py 에서 발견되어야 함. hits={hits}"
    )
    # Call chain 검증 — goal_decomposer.py 가 reader 를 호출.
    src = _read("core/orchestration/goal_decomposer.py")
    assert "_load_decomposition_policy_override" in src, (
        "goal_decomposer.py 가 _load_decomposition_policy_override 를 호출해야 함."
    )
    assert "apply_decomposition_policy" in src, (
        "goal_decomposer.py 가 apply_decomposition_policy 를 호출해야 함."
    )


def test_reflection_slot_is_now_alive_post_s0b() -> None:
    """ADR-012 S0b 머지 이후 ``reflection.json`` 은 ALIVE — reader 가
    ``core/agent/reflection_policy.py`` 에 존재 + ``_reflection.py`` 의
    reflection LLM 호출 직전에 실제로 호출됨. PR-AUDIT-5SLOT 의 의도된
    회귀 marker 의 발화 결과."""
    hits = _grep_inference_dirs("reflection.json")
    assert any("reflection_policy.py" in h for h in hits), (
        f"reflection.json 이 core/agent/reflection_policy.py 에서 발견되어야 함. hits={hits}"
    )
    # Call chain 검증 — _reflection.py 가 reflection_policy 의 reader 를 호출.
    reflection_src = _read("core/agent/loop/_reflection.py")
    assert "_load_reflection_policy_override" in reflection_src, (
        "_reflection.py 가 _load_reflection_policy_override 를 호출해야 함."
    )
    assert "apply_reflection_policy" in reflection_src, (
        "_reflection.py 가 apply_reflection_policy 를 호출해야 함 — 정책이 reflection LLM 호출에 적용되는지."
    )


# ---------------------------------------------------------------------------
# Mutation target 등록은 S0d 머지 후 4축 명시 축소 (retrieval deprecated)
# ---------------------------------------------------------------------------


def test_active_slots_registered_as_mutation_targets() -> None:
    """S0d (2026-05-21) — retrieval deprecated.
    M1 (2026-05-21) — skill_catalog 추가.
    M2 (2026-05-21) — agent_contract 추가 → 6 active slot.
    retrieval 은 명시적 deprecate 유지; path constant + dict 매핑은
    보존 (별도 ADR 로 RAG 인프라 신설 시 복원 가능)."""
    import importlib

    mod = importlib.import_module("core.self_improving_loop.policies")
    target_kinds = set(getattr(mod, "TARGET_KINDS", ()))
    expected = {
        "prompt",
        "tool_policy",
        "decomposition",
        "reflection",
        "skill_catalog",
        "agent_contract",
    }
    assert target_kinds == expected, (
        f"TARGET_KINDS 는 정확히 {expected} (post-M2). got={target_kinds}"
    )
    assert "retrieval" not in target_kinds, "retrieval 은 S0d 이후 deprecate 유지"
    # path constant 보존 — 미래 복원용
    src = _read("core/self_improving_loop/policies.py")
    assert '"retrieval": GLOBAL_RETRIEVAL_POLICY_PATH' in src, (
        "GLOBAL_RETRIEVAL_POLICY_PATH 매핑은 deprecate 후에도 보존 필요"
    )
