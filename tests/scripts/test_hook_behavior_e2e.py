import asyncio

from scripts.eval.run_hook_behavior_e2e import (
    _middleware_counts_are_valid,
    _run_action_matrix,
)


def test_middleware_count_invariants_allow_extra_llm_rounds() -> None:
    assert _middleware_counts_are_valid(
        {"tool_request": 1, "tool_execution": 1, "llm_request": 3, "llm_execution": 3}
    )
    assert _middleware_counts_are_valid(
        {"tool_request": 1, "tool_execution": 1, "llm_request": 4, "llm_execution": 4}
    )
    assert not _middleware_counts_are_valid(
        {"tool_request": 1, "tool_execution": 1, "llm_request": 4, "llm_execution": 3}
    )


def test_action_matrix() -> None:
    outcomes = asyncio.run(_run_action_matrix())

    assert outcomes == {
        "cancel_before_start": {"side_effect_calls": 0, "status": "pass"},
        "handler_error": {"side_effect_calls": 1, "status": "pass"},
        "middleware_double_next": {"side_effect_calls": 1, "status": "pass"},
        "middleware_short_circuit": {"side_effect_calls": 0, "status": "pass"},
        "permission_deny": {"side_effect_calls": 0, "status": "pass"},
        "pre_tool_block": {"side_effect_calls": 0, "status": "pass"},
        "subagent_timeout": {
            "side_effect_calls": 1,
            "status": "pass",
            "thread_finished": True,
        },
    }
