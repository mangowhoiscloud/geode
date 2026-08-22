"""Regression tests for sub_agent's producer-side ```json``` codeblock strip.

Smoke 7 (v0.99.53, post-PR-JSON-CODEBLOCK-STRIP) surfaced both
proximity and critic still failing because the LLM wrapped its
otherwise-valid JSON in a ```json``` markdown fence. The pre-fix
`SubAgentManager._protocol.to_sub_result` called
`json.loads(isolation.output)` directly, which raises JSONDecodeError
on the fence and falls back to `{"raw": <wrapped-text>}` —
downstream parsers (proximity uses a non-`text`-key consumer) can't
recover from that shape.

The fix applies `_strip_json_codeblock()` *before* `json.loads()`, so a fenced
JSON body parses to a proper dict and propagates as `SubResult.output`.
"""

from __future__ import annotations

from core.agent.sub_agent import SubAgentManager, SubTask
from core.orchestration.isolated_execution import IsolatedRunner, IsolationResult


def _make_manager() -> SubAgentManager:
    return SubAgentManager(runner=IsolatedRunner())


def _make_task(task_id: str = "t1", task_type: str = "analyze") -> SubTask:
    return SubTask(task_id=task_id, description="desc", task_type=task_type)


def _make_isolation(output: str) -> IsolationResult:
    return IsolationResult(session_id="s1", success=True, output=output)


def test_to_sub_result_unwraps_json_codeblock_fence() -> None:
    manager = _make_manager()
    task = _make_task()
    isolation = _make_isolation('```json\n{"similarity_clusters": [], "k": 1}\n```')

    result = manager._protocol.to_sub_result(task, isolation)

    assert result.success is True
    assert result.output == {"similarity_clusters": [], "k": 1}
    # No "raw" fallback when the fence unwraps to valid JSON.
    assert "raw" not in result.output


def test_to_sub_result_unwraps_fence_with_leading_prose() -> None:
    """Smoke 7 proximity case — LLM narrates its tool-call attempts
    before emitting the structured payload."""
    manager = _make_manager()
    task = _make_task()
    text = (
        "New IDs — searching for these files on disk. "
        "The excerpts are detailed enough to assess similarity.\n\n"
        '```json\n{"similarity_clusters": [{"cluster_id": "c0"}]}\n```'
    )
    isolation = _make_isolation(text)

    result = manager._protocol.to_sub_result(task, isolation)

    assert result.success is True
    assert result.output == {"similarity_clusters": [{"cluster_id": "c0"}]}


def test_to_sub_result_plain_json_still_works() -> None:
    """Regression — un-fenced JSON must still parse correctly."""
    manager = _make_manager()
    task = _make_task()
    isolation = _make_isolation('{"a": 1, "b": 2}')

    result = manager._protocol.to_sub_result(task, isolation)

    assert result.output == {"a": 1, "b": 2}


def test_to_sub_result_non_json_text_falls_back_to_raw() -> None:
    """Regression — text that contains no JSON and no fence still
    falls into the `{"raw": <text>}` wrapper (unchanged behaviour)."""
    manager = _make_manager()
    task = _make_task()
    isolation = _make_isolation("just plain prose, no JSON here")

    result = manager._protocol.to_sub_result(task, isolation)

    assert result.output == {"raw": "just plain prose, no JSON here"}


def test_to_sub_result_empty_output_yields_empty_dict() -> None:
    """Empty isolation.output yields an empty dict — no fence-strip
    side effect on this path."""
    manager = _make_manager()
    task = _make_task()
    isolation = _make_isolation("")

    result = manager._protocol.to_sub_result(task, isolation)

    assert result.output == {}


def test_to_sub_result_bare_fence_no_lang_tag() -> None:
    """Some LLMs omit the `json` lang tag — bare ``` fence must
    also unwrap."""
    manager = _make_manager()
    task = _make_task()
    isolation = _make_isolation('```\n{"x": 42}\n```')

    result = manager._protocol.to_sub_result(task, isolation)

    assert result.output == {"x": 42}
