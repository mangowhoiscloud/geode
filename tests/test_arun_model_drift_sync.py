"""PR-D Phase 2b — ``_sync_model_and_rebuild_prompt`` extraction invariants.

Pins the structural extraction of the model-drift sync + system_prompt
rebuild block from ``arun``'s while-loop body into a dedicated helper.
Phase 2b is pure refactor (zero behaviour change); ``arun`` rebinds
``system_prompt`` from the helper's return value, preserving the
exact pre-refactor semantics:

  * ``_sync_model_from_settings_async()`` checks settings drift.
  * OR-chained with ``_prompt_dirty`` so direct
    ``update_model_async`` callers (v0.52.5) still trigger rebuild.
  * On rebuild: ``_build_system_prompt()`` produces a new prompt;
    ``decomposition_hint`` (if present) appended.
  * Side effect: ``_prompt_dirty`` cleared post-rebuild.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest
from core.agent.loop.agent_loop import AgenticLoop

# ---------------------------------------------------------------------------
# Method exists with the right signature
# ---------------------------------------------------------------------------


def test_helper_method_exists() -> None:
    assert hasattr(AgenticLoop, "_sync_model_and_rebuild_prompt")
    method = AgenticLoop._sync_model_and_rebuild_prompt
    sig = inspect.signature(method)
    assert "system_prompt" in sig.parameters
    assert "decomposition_hint" in sig.parameters
    # Returns str — caller rebinds the local.
    assert "str" in str(sig.return_annotation)


def test_helper_is_coroutine() -> None:
    """``_sync_model_from_settings_async`` is async — the helper must
    be too so the await chain in ``arun`` stays consistent."""
    assert inspect.iscoroutinefunction(AgenticLoop._sync_model_and_rebuild_prompt)


# ---------------------------------------------------------------------------
# Behaviour — exact pre-refactor semantics
# ---------------------------------------------------------------------------


class _StubLoop:
    """Minimal AgenticLoop stub — only the fields + methods
    ``_sync_model_and_rebuild_prompt`` reads. Lets tests invoke the
    helper without constructing the full runtime."""

    def __init__(
        self,
        *,
        sync_returns_drifted: bool = False,
        prompt_dirty: bool = False,
        rebuilt_prompt: str = "REBUILT_PROMPT",
    ) -> None:
        self._sync_returns_drifted = sync_returns_drifted
        self._prompt_dirty = prompt_dirty
        self._rebuilt_prompt = rebuilt_prompt
        self.build_calls = 0
        self.sync_calls = 0

    async def _sync_model_from_settings_async(self) -> bool:
        self.sync_calls += 1
        return self._sync_returns_drifted

    def _build_system_prompt(self) -> str:
        self.build_calls += 1
        return self._rebuilt_prompt


def _call_helper(stub: _StubLoop, system_prompt: str, hint: str | None) -> str:
    bound = AgenticLoop._sync_model_and_rebuild_prompt.__get__(stub, _StubLoop)
    return asyncio.run(bound(system_prompt, hint))


def test_no_drift_no_dirty_returns_input_unchanged() -> None:
    """Common case: neither the settings drift nor _prompt_dirty
    triggers. Helper returns the input system_prompt unchanged and
    does NOT call _build_system_prompt."""
    stub = _StubLoop(sync_returns_drifted=False, prompt_dirty=False)
    result = _call_helper(stub, "ORIGINAL", None)
    assert result == "ORIGINAL"
    assert stub.build_calls == 0
    assert stub.sync_calls == 1


def test_drift_triggers_rebuild() -> None:
    """Settings.model changed → drift sync returns True → rebuild."""
    stub = _StubLoop(sync_returns_drifted=True, prompt_dirty=False)
    result = _call_helper(stub, "ORIGINAL", None)
    assert result == "REBUILT_PROMPT"
    assert stub.build_calls == 1


def test_prompt_dirty_triggers_rebuild_even_without_drift() -> None:
    """v0.52.5 — direct update_model_async callers bypass the drift
    sync, but set _prompt_dirty. OR-chain catches them."""
    stub = _StubLoop(sync_returns_drifted=False, prompt_dirty=True)
    result = _call_helper(stub, "ORIGINAL", None)
    assert result == "REBUILT_PROMPT"
    assert stub.build_calls == 1


def test_both_drift_and_dirty_still_rebuild_exactly_once() -> None:
    """Both flags set: OR-chain short-circuits on the first True.
    Rebuild path still runs exactly once (not twice). Pin against a
    future refactor that accidentally double-rebuilds."""
    stub = _StubLoop(sync_returns_drifted=True, prompt_dirty=True)
    result = _call_helper(stub, "ORIGINAL", None)
    assert result == "REBUILT_PROMPT"
    assert stub.build_calls == 1
    # drift sync runs unconditionally (left operand of OR); dirty
    # flag is consulted only if drift returns False (short-circuit).
    # Here drift=True so the OR short-circuits — dirty is not
    # *evaluated for branching*, but the post-rebuild reset still
    # clears it.
    assert stub.sync_calls == 1
    assert stub._prompt_dirty is False


def test_rebuild_clears_prompt_dirty_flag() -> None:
    """After rebuild ``_prompt_dirty`` must be False so subsequent
    rounds don't loop-rebuild."""
    stub = _StubLoop(sync_returns_drifted=False, prompt_dirty=True)
    _call_helper(stub, "ORIGINAL", None)
    assert stub._prompt_dirty is False


def test_no_rebuild_leaves_prompt_dirty_flag_untouched() -> None:
    """If no rebuild happens, ``_prompt_dirty`` keeps its value
    (which is already False in the no-rebuild path — this just
    pins that the helper doesn't accidentally set it to True)."""
    stub = _StubLoop(sync_returns_drifted=False, prompt_dirty=False)
    _call_helper(stub, "ORIGINAL", None)
    assert stub._prompt_dirty is False


def test_decomposition_hint_appended_when_rebuilding() -> None:
    """If a decomposition hint exists, it's appended to the rebuilt
    prompt with two newline separator (matches pre-refactor)."""
    stub = _StubLoop(sync_returns_drifted=True)
    result = _call_helper(stub, "ORIGINAL", "HINT_TEXT")
    assert result == "REBUILT_PROMPT\n\nHINT_TEXT"


def test_decomposition_hint_none_not_appended() -> None:
    """No hint = no append (no ``None`` string concatenation
    accident)."""
    stub = _StubLoop(sync_returns_drifted=True)
    result = _call_helper(stub, "ORIGINAL", None)
    assert result == "REBUILT_PROMPT"
    assert "None" not in result


def test_decomposition_hint_ignored_when_not_rebuilding() -> None:
    """If no rebuild happens, the hint doesn't matter — original
    prompt returned unchanged."""
    stub = _StubLoop(sync_returns_drifted=False, prompt_dirty=False)
    result = _call_helper(stub, "ORIGINAL", "HINT_THAT_IS_IGNORED")
    assert result == "ORIGINAL"


# ---------------------------------------------------------------------------
# arun delegates to the helper
# ---------------------------------------------------------------------------


def test_arun_calls_sync_and_rebuild_helper() -> None:
    """``arun``'s while-loop must call the helper and rebind
    ``system_prompt`` from its return value."""
    src = inspect.getsource(AgenticLoop.arun)
    assert "system_prompt = await self._sync_model_and_rebuild_prompt(" in src


def test_arun_no_longer_inlines_drift_sync() -> None:
    """Anti-residue guard — the pre-refactor inline block must NOT
    remain in ``arun`` (would double-call sync + double-build prompt)."""
    src = inspect.getsource(AgenticLoop.arun)
    # The exact pre-refactor lines that should be gone:
    assert "if await self._sync_model_from_settings_async() or self._prompt_dirty:" not in src
    # The inline "self._prompt_dirty = False" line is now ONLY inside
    # the helper. arun should have zero direct writes to _prompt_dirty.
    assert "self._prompt_dirty = False" not in src


# ---------------------------------------------------------------------------
# Cross-phase regression guard
# ---------------------------------------------------------------------------


def test_phase1_and_phase2a_helpers_still_exist() -> None:
    """Phase 1 (_emit_session_start_signals) and Phase 2a
    (_check_round_guards) must remain intact. Phase 2b is additive."""
    assert hasattr(AgenticLoop, "_emit_session_start_signals")
    assert hasattr(AgenticLoop, "_check_round_guards")


@pytest.fixture(autouse=True)
def _no_shared_state() -> None:
    """Stub-based tests are self-contained; fixture present so a
    future per-test setup hook has a place to live."""
    yield
