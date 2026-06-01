"""ADR-012 — Tier 2 (mutation 금지) deny-list invariant.

ADR-012 가 "CI ratchet 가 Tier 2 의 화이트리스트를 보유" 라고 주장하는
근거. PR-AUDIT-5SLOT 의 ``test_ratchet_policies_in_repo`` 는 policy SoT
의 gitignore/migration 만 pin 하므로, 자기수정 재귀 회피를 위한
**별도의 Tier 2 deny-list** 가 필요했다. 이 파일이 그 첫 invariant.

검증 사항: Tier 2 영역의 파일/디렉토리가 self-improving loop 의 mutation
target 또는 dispatcher 의 target 목록에 등장하지 않음. 등장하면 mutator
가 자기 자신/fitness gate/CI ratchet 을 mutate 할 수 있음 → CANNOT 우회.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Tier 2 영역 정의 — ADR-012 §Decision.1 의 Tier 2 표와 동기화 유지.
# ---------------------------------------------------------------------------


# (path, 금지 이유) — ADR-012 §Decision.1 의 Tier 2 표
TIER_2_FILES: tuple[tuple[str, str], ...] = (
    ("core/runtime.py", "Bootstrap"),
    ("core/agent/loop", "Bootstrap — agent loop"),
    ("core/self_improving/loop/runner.py", "Self-improving runner (mutator caller)"),
    ("core/self_improving/train.py", "Fitness gate (compute_fitness)"),
    ("tests/test_ratchet_policies_in_repo.py", "CI ratchet"),
    ("core/hooks/system.py", "HookSystem (policy chain)"),
    ("pyproject.toml", "4-layer 의존성 룰 (importlinter contracts)"),
    ("CLAUDE.md", "Version stamp (CANNOT/CAN 룰 자체)"),
    ("README.md", "Version stamp"),
    ("CHANGELOG.md", "Release discipline"),
)


def _read(path: str) -> str:
    full = REPO_ROOT / path
    assert full.exists(), f"Tier 2 path missing in repo: {full}"
    if full.is_dir():
        return ""
    return full.read_text(encoding="utf-8")


def _self_improving_loop_target_kinds() -> set[str]:
    """``core/self_improving/loop/policies.py`` 의 ``TARGET_KINDS`` 를 import 해서
    실제 mutation target 목록을 가져온다."""
    import importlib

    mod = importlib.import_module("core.self_improving.loop.policies")
    return set(getattr(mod, "TARGET_KINDS", ()))


def _target_kind_to_sot_file() -> dict[str, str]:
    """``TARGET_KIND_TO_SOT_FILE`` (또는 동등 mapping) 의 실제 매핑을 가져온다."""
    import importlib

    mod = importlib.import_module("core.self_improving.loop.policies")
    # PR-6 시점의 이름은 ``TARGET_KIND_TO_SOT_FILE`` — fallback 으로 path mapping 도 시도
    raw = (
        getattr(mod, "TARGET_KIND_TO_SOT_FILE", None)
        or getattr(mod, "TARGET_KIND_TO_SOT_PATH", None)
        or {}
    )
    return {k: str(v) for k, v in raw.items()}


# ---------------------------------------------------------------------------
# 1. Tier 2 path 가 mutation target SoT 와 충돌하지 않음
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tier_2_path,reason", TIER_2_FILES)
def test_tier_2_path_is_not_a_mutation_sot(tier_2_path: str, reason: str) -> None:
    """Tier 2 영역의 path 가 mutation SoT 매핑의 값으로 등장하면 안 됨.

    mutator 가 ``apply_mutation`` 으로 그 path 를 mutate 할 수 있게 되면
    자기수정 재귀 위험. 매핑은 ``TARGET_KIND_TO_SOT_FILE`` (basename only) 와
    구체 경로 (``GLOBAL_*_POLICY_PATH``) 두 곳에서 확인."""
    sot_map = _target_kind_to_sot_file()
    tier_2_basename = Path(tier_2_path).name
    # basename 충돌 — basename 만 일치해도 mutation dispatcher 가 잘못 라우팅 가능
    for kind, sot in sot_map.items():
        assert tier_2_basename not in sot, (
            f"Tier 2 path {tier_2_path!r} (reason: {reason}) basename "
            f"이 mutation SoT 매핑 [{kind!r}]={sot!r} 와 충돌. "
            f"mutator 가 이 영역을 mutate 할 수 있음."
        )
        # 전체 경로 충돌
        assert tier_2_path not in sot, (
            f"Tier 2 path {tier_2_path!r} 가 mutation SoT 매핑 [{kind!r}]={sot!r} "
            f"에 등장. mutator 가 이 영역을 mutate 할 수 있음."
        )


def test_no_tier_2_target_kind_registered() -> None:
    """``TARGET_KINDS`` 에 Tier 2 영역을 가리키는 kind 가 등록되면 안 됨.
    현재 5축 (prompt / tool_policy / decomposition / retrieval / reflection)
    은 모두 Tier 1 (정책 SoT). 새 target_kind 가 Tier 2 영역의 이름과
    유사하면 의심."""
    target_kinds = _self_improving_loop_target_kinds()
    forbidden_kinds = {
        "runner",
        "fitness",
        "compute_fitness",
        "train",
        "ratchet",
        "ci",
        "hook",
        "importlinter",
        "pyproject",
        "changelog",
        "version",
        "bootstrap",
        "agent_loop",
        "runtime",
    }
    overlap = target_kinds & forbidden_kinds
    assert overlap == set(), (
        f"Tier 2 영역의 이름이 TARGET_KINDS 에 등록됨: {overlap}. ADR-012 의 Tier 2 deny-list 위반."
    )


# ---------------------------------------------------------------------------
# 2. Tier 2 path 가 실제로 존재 — ADR 의 인용이 stale 하지 않은지 보장
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tier_2_path,reason", TIER_2_FILES)
def test_tier_2_path_exists_in_repo(tier_2_path: str, reason: str) -> None:
    """ADR-012 가 인용한 Tier 2 path 가 실제 repo 에 존재해야 함.
    stale 인용은 ADR 의 신뢰성 저해."""
    full = REPO_ROOT / tier_2_path
    assert full.exists(), (
        f"Tier 2 path {tier_2_path!r} (reason: {reason}) 가 repo 에 없음. "
        f"ADR-012 §Decision.1 의 인용을 갱신하거나 path 정정 필요."
    )


# ---------------------------------------------------------------------------
# 3. ADR 본문이 정확한 path 를 인용하는지 cross-check
# ---------------------------------------------------------------------------


ADR_DOC = "docs/adr/ADR-012-self-improvement-surface-tiers.md"


def test_adr_cites_correct_hook_system_path() -> None:
    """ADR 본문에 잘못된 HookSystem path (`core/observability/hook_system.py`)
    가 들어있지 않고, 실제 path (`core/hooks/system.py`) 가 들어 있어야 함."""
    text = (REPO_ROOT / ADR_DOC).read_text(encoding="utf-8")
    assert "core/hooks/system.py" in text, (
        "ADR 이 HookSystem 의 실제 path (`core/hooks/system.py`) 를 인용해야 함."
    )
    assert "core/observability/hook_system.py" not in text, (
        "ADR 에 stale HookSystem path (`core/observability/hook_system.py`) "
        "가 남아있음. Codex MCP 검증으로 catch 된 사항."
    )


def test_adr_cites_importlinter_at_pyproject() -> None:
    """ADR 본문이 import-linter 의 정확한 위치 (`pyproject.toml [tool.importlinter]`)
    를 인용해야 함."""
    text = (REPO_ROOT / ADR_DOC).read_text(encoding="utf-8")
    assert "pyproject.toml" in text
    assert "importlinter" in text


def test_pyproject_actually_has_importlinter_section() -> None:
    """ADR 이 인용하는 pyproject.toml 의 [tool.importlinter] 가 실제 존재해야 함."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.importlinter]" in text
