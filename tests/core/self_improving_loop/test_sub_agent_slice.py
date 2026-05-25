"""A.8 (2026-05-25) — sub_agent_slice helper invariants (PR-21).

Scope:
- compute_sub_agent_slice: deterministic round-robin / negative idx raises /
  zero total raises / round-robin wrap when total > 5
- derive_slice_prompt_hint: known slices return non-empty / unknown empty
- SLICE_NAMES order matches plan §C4 5-stage spec
"""

from __future__ import annotations

import pytest
from core.self_improving_loop.sub_agent_slice import (
    SLICE_NAMES,
    compute_sub_agent_slice,
    derive_slice_prompt_hint,
)

# ---------------------------------------------------------------------------
# 1. SLICE_NAMES constant
# ---------------------------------------------------------------------------


def test_slice_names_5_stage_order() -> None:
    """Plan §C4 의 5-stage 순서 — role / tools / reflection / decomposition /
    interlocutor."""
    assert SLICE_NAMES == (
        "role",
        "tools",
        "reflection",
        "decomposition",
        "interlocutor",
    )


def test_slice_names_count_matches_config_cap() -> None:
    """sub_agent_count config cap = 5 (Field(ge=1, le=5)). SLICE_NAMES
    길이가 cap 과 일치 — round-robin wrap 안 일어남."""
    assert len(SLICE_NAMES) == 5


# ---------------------------------------------------------------------------
# 2. compute_sub_agent_slice — deterministic round-robin
# ---------------------------------------------------------------------------


def test_compute_slice_idx_0_returns_role() -> None:
    assert compute_sub_agent_slice(0, 5) == "role"


def test_compute_slice_idx_1_returns_tools() -> None:
    assert compute_sub_agent_slice(1, 5) == "tools"


def test_compute_slice_idx_4_returns_interlocutor() -> None:
    assert compute_sub_agent_slice(4, 5) == "interlocutor"


def test_compute_slice_is_deterministic() -> None:
    """Same (idx, total) always yields same slice — pure function."""
    for idx in range(5):
        assert compute_sub_agent_slice(idx, 5) == compute_sub_agent_slice(idx, 5)


def test_compute_slice_total_smaller_than_max() -> None:
    """total=2 sub-agents — idx 0 + 1 모두 유효 slice."""
    assert compute_sub_agent_slice(0, 2) == "role"
    assert compute_sub_agent_slice(1, 2) == "tools"


def test_compute_slice_negative_idx_raises() -> None:
    with pytest.raises(ValueError, match=r"sub_agent_index must be >= 0"):
        compute_sub_agent_slice(-1, 5)


def test_compute_slice_zero_total_raises() -> None:
    with pytest.raises(ValueError, match=r"total sub-agents must be >= 1"):
        compute_sub_agent_slice(0, 0)


def test_compute_slice_negative_total_raises() -> None:
    with pytest.raises(ValueError, match=r"total sub-agents must be >= 1"):
        compute_sub_agent_slice(0, -3)


def test_compute_slice_round_robin_wrap() -> None:
    """idx > len(SLICE_NAMES) (방어적 — config cap 으로 정상 안 도달).
    idx=5 → 5 % 5 = 0 → 'role'."""
    assert compute_sub_agent_slice(5, 10) == "role"
    assert compute_sub_agent_slice(6, 10) == "tools"


# ---------------------------------------------------------------------------
# 3. derive_slice_prompt_hint
# ---------------------------------------------------------------------------


def test_derive_hint_known_slices_non_empty() -> None:
    for slice_name in SLICE_NAMES:
        hint = derive_slice_prompt_hint(slice_name)
        assert hint != "", f"slice {slice_name!r} has empty hint"


def test_derive_hint_unknown_slice_returns_empty() -> None:
    """Unknown slice → empty (graceful, caller falls back)."""
    assert derive_slice_prompt_hint("nonexistent_slice") == ""


def test_derive_hint_role_mentions_role() -> None:
    assert "role" in derive_slice_prompt_hint("role").lower()


def test_derive_hint_tools_mentions_tool() -> None:
    assert "tool" in derive_slice_prompt_hint("tools").lower()


# ---------------------------------------------------------------------------
# 4. Integration — pipeline pattern
# ---------------------------------------------------------------------------


def test_full_pipeline_idx_to_hint() -> None:
    """compute_sub_agent_slice → derive_slice_prompt_hint pipeline."""
    slice_name = compute_sub_agent_slice(2, 5)
    hint = derive_slice_prompt_hint(slice_name)
    assert slice_name == "reflection"
    assert "reflection" in hint.lower()
