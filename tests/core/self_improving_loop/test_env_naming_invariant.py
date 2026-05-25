"""F3 (Codex MCP review Dedup) — env naming invariant between runner.py
_SIBLING_SOT_ENV_MAP and autoresearch/train.py W3 env literal block.

Two SOT sources for sibling SoT path propagation env vars:
- ``core/self_improving_loop/runner.py:_SIBLING_SOT_ENV_MAP`` (5 kinds —
  Mutation.target_kind)
- ``autoresearch/train.py:809-873`` literal env assignment block (12
  kinds — all GLOBAL_*_PATH)

The 5-kind subset MUST be identical between the two SOTs — drift means
sibling audit subprocess receives a different env name than what GEODE
runtime's strict-mode reader expects → silent disconnection ([[feedback-
changelog-implementation-parity]]).

This test pins the 5-kind subset by reading the literal env block from
train.py and grepping for each Mutation.target_kind's expected env name.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.self_improving_loop.policies import TARGET_KINDS
from core.self_improving_loop.runner import _SIBLING_SOT_ENV_MAP


def _read_train_py_source() -> str:
    """Read autoresearch/train.py source text."""
    here = Path(__file__).resolve()
    # tests/core/self_improving_loop/ → ../../../autoresearch/train.py
    repo_root = here.parents[3]
    train_py = repo_root / "autoresearch" / "train.py"
    return train_py.read_text(encoding="utf-8")


def test_sibling_env_map_covers_all_target_kinds() -> None:
    """F3.1: _SIBLING_SOT_ENV_MAP 가 TARGET_KINDS 의 모든 kind 를 cover."""
    missing = set(TARGET_KINDS) - set(_SIBLING_SOT_ENV_MAP)
    assert not missing, (
        f"_SIBLING_SOT_ENV_MAP missing kinds: {missing}. "
        f"sibling sampling 안 됨 — TARGET_KINDS 와 동기 필수."
    )


def test_sibling_env_names_match_train_py() -> None:
    """F3.2: runner.py 의 _SIBLING_SOT_ENV_MAP 의 env 명명이 train.py 의
    W3 env literal block 과 정확히 일치 — drift 시 sibling audit 가
    잘못된 env 로 launched → silent SoT-not-loaded.
    """
    train_src = _read_train_py_source()
    for kind, env_name in _SIBLING_SOT_ENV_MAP.items():
        # train.py 가 env[<env_name>] = ... 로 set 하는지 (literal 검색)
        # 또는 env literal "GEODE_<KIND>_OVERRIDE" 가 등장하는지
        pattern = re.compile(rf'env\[\s*["\']({re.escape(env_name)})["\']\s*\]')
        assert pattern.search(train_src), (
            f"train.py 가 env[{env_name!r}] 을 set 안 함. runner.py 의 "
            f"_SIBLING_SOT_ENV_MAP[{kind!r}]={env_name!r} 와 drift. "
            f"sibling audit 가 SoT 못 받음."
        )


def test_geode_override_naming_pattern() -> None:
    """F3.3: env 명명이 ``GEODE_<KIND>_OVERRIDE`` pattern 따름 — naming
    convention 일관성."""
    pattern = re.compile(r"^GEODE_[A-Z_]+_OVERRIDE$")
    for kind, env_name in _SIBLING_SOT_ENV_MAP.items():
        assert pattern.match(env_name), (
            f"_SIBLING_SOT_ENV_MAP[{kind!r}]={env_name!r} does not match "
            f"GEODE_<KIND>_OVERRIDE pattern"
        )


def test_sibling_env_value_unique() -> None:
    """F3.4: env 명명이 unique (한 env 가 여러 kind 에 묶이지 않음)."""
    env_values = list(_SIBLING_SOT_ENV_MAP.values())
    assert len(env_values) == len(set(env_values)), (
        f"_SIBLING_SOT_ENV_MAP has duplicate env names: {env_values}"
    )
