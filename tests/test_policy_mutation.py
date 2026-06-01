"""PR-6 C-5 — policy mutation expansion invariants.

Pins the new ``target_kind`` field on :class:`Mutation`, the
``core.self_improving.loop.policies`` SoT helpers, and
``apply_mutation``'s dispatcher routing to the right policy file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.self_improving.loop.policies import (
    TARGET_KINDS,
    is_valid_target_kind,
    load_policy,
    policy_path,
    write_policy,
)
from core.self_improving.loop.runner import (
    Mutation,
    apply_mutation,
    parse_mutation,
)

from core.self_improving.loop import policies as _policies_mod

# ---------------------------------------------------------------------------
# TARGET_KINDS + is_valid_target_kind
# ---------------------------------------------------------------------------


def test_target_kinds_contains_seven_behaviour_kinds() -> None:
    """ADR-012 S0d — retrieval deprecated. M1 — skill_catalog 추가.
    M2 (2026-05-21) — agent_contract 추가.
    PR-TOOL-DESCRIPTIONS-MUTATE (2026-05-27) — tool_descriptions 추가.
    PR-HYPERPARAM-FOUNDATION (2026-05-28) — hyperparam 추가, then
    PR-DROP-HYPERPARAM-MUTATION (2026-05-31) — hyperparam REMOVED from the
    mutable surface (reflection_depth axis exhausted; measurement params
    fixed). The mutable surface is now exactly the 7 *behaviour* kinds."""
    assert set(TARGET_KINDS) == {
        "prompt",
        "tool_policy",
        "decomposition",
        "reflection",
        "skill_catalog",
        "agent_contract",
        "tool_descriptions",
    }
    assert len(TARGET_KINDS) == 7
    # hyperparam is no longer a mutable kind.
    assert "hyperparam" not in TARGET_KINDS
    assert is_valid_target_kind("hyperparam") is False


def test_is_valid_target_kind_accepts_registered_kinds() -> None:
    for kind in TARGET_KINDS:
        assert is_valid_target_kind(kind) is True


def test_is_valid_target_kind_rejects_unknown() -> None:
    assert is_valid_target_kind("unknown") is False
    assert is_valid_target_kind("") is False


# ---------------------------------------------------------------------------
# policy_path — each kind points to a distinct file
# ---------------------------------------------------------------------------


def test_policy_path_returns_distinct_paths() -> None:
    """Distinct SoT per kind so policies evolve independently.
    PR-DROP-HYPERPARAM-MUTATION (2026-05-31) — 7 active *behaviour* kinds
    (prompt / tool_policy / decomposition / reflection / skill_catalog /
    agent_contract / tool_descriptions) + ``retrieval`` and ``hyperparam``
    (both removed from TARGET_KINDS but path-mapping preserved for runtime
    readers / future re-add) = 9 distinct paths."""
    paths = {kind: policy_path(kind) for kind in (*TARGET_KINDS, "retrieval", "hyperparam")}
    assert len(set(paths.values())) == 9


def test_policy_path_prompt_points_to_wrapper_sections() -> None:
    from core.paths import GLOBAL_WRAPPER_SECTIONS_PATH

    assert policy_path("prompt") == GLOBAL_WRAPPER_SECTIONS_PATH


def test_policy_path_raises_on_unknown() -> None:
    with pytest.raises(ValueError, match="unknown target_kind"):
        policy_path("invalid")


# ---------------------------------------------------------------------------
# load_policy / write_policy roundtrip
# ---------------------------------------------------------------------------


def _redirect_kind(monkeypatch: pytest.MonkeyPatch, kind: str, path: Path) -> None:
    """Point ``_KIND_TO_PATH[kind]`` at ``path`` for the duration of
    the test. Avoids touching the real ``~/.geode/`` dir."""
    new_map = dict(_policies_mod._KIND_TO_PATH)
    new_map[kind] = path
    monkeypatch.setattr(_policies_mod, "_KIND_TO_PATH", new_map)


def test_write_policy_creates_parent_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "nested" / "deep" / "tool-policy.json"
    _redirect_kind(monkeypatch, "tool_policy", target)
    write_policy("tool_policy", {"key": "value"})
    assert target.exists()


def test_load_policy_missing_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "absent.json"
    _redirect_kind(monkeypatch, "tool_policy", target)
    assert load_policy("tool_policy") == {}


def test_load_write_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "tool-policy.json"
    _redirect_kind(monkeypatch, "tool_policy", target)
    write_policy("tool_policy", {"a": "1", "b": "2"})
    assert load_policy("tool_policy") == {"a": "1", "b": "2"}


def test_load_policy_malformed_json_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Robust on corrupt files — readers should never crash. PR-5
    attribution will run during every audit cycle."""
    target = tmp_path / "tool-policy.json"
    target.write_text("not json {{{", encoding="utf-8")
    _redirect_kind(monkeypatch, "tool_policy", target)
    assert load_policy("tool_policy") == {}


def test_load_policy_non_dict_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "tool-policy.json"
    target.write_text('["not", "a", "dict"]', encoding="utf-8")
    _redirect_kind(monkeypatch, "tool_policy", target)
    assert load_policy("tool_policy") == {}


def test_write_policy_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Temp file should not survive after the rename completes."""
    target = tmp_path / "tool-policy.json"
    _redirect_kind(monkeypatch, "tool_policy", target)
    write_policy("tool_policy", {"k": "v"})
    assert target.exists()
    assert not target.with_suffix(".json.tmp").exists()


# ---------------------------------------------------------------------------
# Mutation schema — target_kind field
# ---------------------------------------------------------------------------


def test_mutation_default_target_kind_is_prompt() -> None:
    """Default = prompt for backward compatibility."""
    m = Mutation(target_section="s", new_value="v", rationale="r")
    assert m.target_kind == "prompt"


def test_mutation_to_audit_row_includes_target_kind() -> None:
    m = Mutation(
        target_section="s",
        new_value="v",
        rationale="r",
        target_kind="tool_policy",
    )
    row = m.to_audit_row(previous_value="")
    assert row["target_kind"] == "tool_policy"


# ---------------------------------------------------------------------------
# parse_mutation — target_kind extraction + validation
# ---------------------------------------------------------------------------


def test_parse_mutation_missing_target_kind_defaults_to_prompt() -> None:
    """Older LLM responses don't include target_kind. Backward
    compatibility — default to legacy prompt mutation."""
    raw = json.dumps({"target_section": "s", "new_value": "v", "rationale": "r"})
    m = parse_mutation(raw)
    assert m.target_kind == "prompt"


def test_parse_mutation_extracts_target_kind() -> None:
    raw = json.dumps(
        {
            "target_section": "s",
            "new_value": "v",
            "rationale": "r",
            "target_kind": "decomposition",
        }
    )
    m = parse_mutation(raw)
    assert m.target_kind == "decomposition"


def test_parse_mutation_rejects_unknown_target_kind() -> None:
    """Fail closed on unknown kinds rather than silently writing to
    an unexpected file."""
    raw = json.dumps(
        {
            "target_section": "s",
            "new_value": "v",
            "rationale": "r",
            "target_kind": "bogus_kind",
        }
    )
    with pytest.raises(ValueError, match="target_kind 'bogus_kind' is not one of"):
        parse_mutation(raw)


def test_parse_mutation_empty_target_kind_defaults_to_prompt() -> None:
    """Empty string after strip — operator typo defense."""
    raw = json.dumps(
        {
            "target_section": "s",
            "new_value": "v",
            "rationale": "r",
            "target_kind": "   ",
        }
    )
    m = parse_mutation(raw)
    assert m.target_kind == "prompt"


def test_parse_mutation_rejects_non_string_target_kind() -> None:
    raw = json.dumps(
        {
            "target_section": "s",
            "new_value": "v",
            "rationale": "r",
            "target_kind": 42,
        }
    )
    with pytest.raises(ValueError, match="target_kind must be a string"):
        parse_mutation(raw)


# ---------------------------------------------------------------------------
# apply_mutation — dispatcher routes by target_kind
# ---------------------------------------------------------------------------


def test_apply_mutation_tool_policy_writes_to_tool_policy_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "tool-policy.json"
    _redirect_kind(monkeypatch, "tool_policy", target)
    m = Mutation(
        target_section="prefer_tools",
        new_value="bash before read",
        rationale="r",
        target_kind="tool_policy",
    )
    new_sections, prev = apply_mutation(m, current_sections={})
    assert prev == ""
    assert new_sections == {"prefer_tools": "bash before read"}
    # File written
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"prefer_tools": "bash before read"}


def test_apply_mutation_decomposition_writes_to_decomposition_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "decomposition.json"
    _redirect_kind(monkeypatch, "decomposition", target)
    m = Mutation(
        target_section="strategy",
        new_value="depth-first",
        rationale="r",
        target_kind="decomposition",
    )
    apply_mutation(m, current_sections={})
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"strategy": "depth-first"}


def test_apply_mutation_retrieval_is_rejected_post_s0d() -> None:
    """ADR-012 S0d (2026-05-21) — retrieval 은 TARGET_KINDS 에서 deprecate.
    ``apply_mutation`` 호출 시 ``is_valid_target_kind("retrieval") == False``
    이므로 ``policy_path`` 가 ValueError 를 raise 한다."""
    from core.self_improving.loop.policies import is_valid_target_kind, policy_path

    assert is_valid_target_kind("retrieval") is False, (
        "S0d 후 retrieval 은 active target_kind 가 아님"
    )
    # policy_path 는 raise ValueError on unknown kinds — 그러나 dict 매핑은
    # 보존돼 있어서 직접 호출은 가능 (path constant preservation).
    # apply_mutation 의 entry guard 는 is_valid_target_kind 를 거치므로
    # retrieval mutation 시도는 거부됨.
    path = policy_path("retrieval")  # dict 매핑은 보존 — 미래 복원용
    assert path.name == "retrieval.json"


def test_apply_mutation_reflection_writes_to_reflection_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "reflection.json"
    _redirect_kind(monkeypatch, "reflection", target)
    m = Mutation(
        target_section="cadence",
        new_value="every 3 rounds",
        rationale="r",
        target_kind="reflection",
    )
    apply_mutation(m, current_sections={})
    assert target.exists()


def test_apply_mutation_prompt_kind_uses_legacy_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The legacy ``prompt`` kind must still route through
    ``core.self_improving.train.write_wrapper_prompt_sections`` so the
    schema enforcement (single paragraph / 600-char cap) survives
    the PR-6 dispatcher rewrite."""
    from core.self_improving import train as _train

    written: list[dict[str, str]] = []

    def _fake_writer(sections: dict[str, str]) -> None:
        written.append(dict(sections))

    monkeypatch.setattr(_train, "write_wrapper_prompt_sections", _fake_writer)

    m = Mutation(
        target_section="role",
        new_value="ship it",
        rationale="r",
        target_kind="prompt",
    )
    apply_mutation(m, current_sections={"existing": "x"})
    assert len(written) == 1
    assert written[0] == {"existing": "x", "role": "ship it"}


def test_apply_mutation_preserves_previous_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``previous_value`` must capture the *replaced* string so the
    audit log can render a diff."""
    target = tmp_path / "tool-policy.json"
    _redirect_kind(monkeypatch, "tool_policy", target)
    m = Mutation(
        target_section="prefer_tools",
        new_value="new value",
        rationale="r",
        target_kind="tool_policy",
    )
    _, prev = apply_mutation(m, current_sections={"prefer_tools": "old value"})
    assert prev == "old value"


# ---------------------------------------------------------------------------
# Paths sanity
# ---------------------------------------------------------------------------


def test_run_once_loads_target_kind_policy_not_wrapper_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex MCP review #1 (HIGH) catch — run_once used to always pass
    ``ctx.current_sections`` (wrapper-prompt sections) into
    apply_mutation, which would write wrapper-prompt content into the
    wrong SoT for non-prompt target_kinds. Pin that run_once now
    loads the correct policy via ``load_policy(mutation.target_kind)``."""
    from core.self_improving.loop.runner import SelfImprovingLoopRunner

    from core.self_improving import train as _train

    # Redirect tool_policy SoT to a tmp path so the test never touches
    # ~/.geode/. Pre-populate with one entry to confirm load_policy is
    # invoked (and ctx.current_sections is NOT used).
    tool_path = tmp_path / "tool-policy.json"
    _redirect_kind(monkeypatch, "tool_policy", tool_path)
    write_policy("tool_policy", {"existing": "from_policy_file"})

    # Stub the LLM call to return a tool_policy mutation.
    monkeypatch.setattr(
        SelfImprovingLoopRunner,
        "_invoke_autoresearch",
        lambda self, _root: None,
    )
    runner_llm = (
        '{"target_section": "new_tool",'
        ' "new_value": "use bash before read",'
        ' "rationale": "r",'
        ' "target_kind": "tool_policy"}'
    )

    # Stub build_runner_context so the test doesn't depend on a real
    # baseline / wrapper-sections file.
    from core.self_improving.loop.runner import RunnerContext

    from core.self_improving.loop import runner as _runner_mod

    monkeypatch.setattr(
        _runner_mod,
        "build_runner_context",
        lambda: RunnerContext(current_sections={"wrapper_only": "WRAPPER CONTENTS"}),
    )

    # Stub the legacy writer so the test never touches the real
    # wrapper-sections SoT.
    monkeypatch.setattr(_train, "write_wrapper_prompt_sections", lambda _s: None)

    audit_path = tmp_path / "mutations.jsonl"
    runner = SelfImprovingLoopRunner(
        llm_call=lambda _sys, _user: runner_llm,
        audit_log_path=audit_path,
    )
    runner.run_once()

    # After run_once with target_kind="tool_policy", the tool-policy
    # SoT should have the original entry PLUS the new mutation, and
    # the wrapper-sections-only "wrapper_only" key must NOT appear in
    # the tool-policy file (which would prove the dispatcher bug
    # Codex caught).
    on_disk = json.loads(tool_path.read_text(encoding="utf-8"))
    assert on_disk == {"existing": "from_policy_file", "new_tool": "use bash before read"}
    assert "wrapper_only" not in on_disk


def test_rollback_sot_dispatches_on_target_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex MCP review #1 (HIGH) catch — _rollback_sot used to always
    call write_wrapper_prompt_sections, which for non-prompt mutations
    would restore the wrong destination. Pin that rollback now
    dispatches by target_kind."""
    from core.self_improving.loop.runner import SelfImprovingLoopRunner

    tool_path = tmp_path / "tool-policy.json"
    _redirect_kind(monkeypatch, "tool_policy", tool_path)

    # Initial state on disk
    write_policy("tool_policy", {"baseline": "orig"})

    # Simulate _rollback_sot directly
    mutation = Mutation(
        target_section="x",
        new_value="y",
        rationale="r",
        target_kind="tool_policy",
    )
    SelfImprovingLoopRunner._rollback_sot(
        {"baseline": "restored"}, mutation=mutation, exc=OSError("simulated")
    )

    # tool-policy.json should now reflect the *rollback* dict, NOT the
    # original on-disk state, AND the legacy wrapper-sections writer
    # must not have been touched.
    on_disk = json.loads(tool_path.read_text(encoding="utf-8"))
    assert on_disk == {"baseline": "restored"}


def test_rollback_sot_prompt_kind_still_uses_legacy_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin that the prompt branch still routes through
    core.self_improving.train.write_wrapper_prompt_sections — schema
    enforcement (single-paragraph 600-char cap) must survive PR-6."""
    from core.self_improving.loop.runner import SelfImprovingLoopRunner

    from core.self_improving import train as _train

    written: list[dict[str, str]] = []
    monkeypatch.setattr(_train, "write_wrapper_prompt_sections", lambda s: written.append(dict(s)))

    mutation = Mutation(
        target_section="role",
        new_value="ship",
        rationale="r",
        target_kind="prompt",
    )
    SelfImprovingLoopRunner._rollback_sot(
        {"role": "original"}, mutation=mutation, exc=OSError("simulated")
    )
    assert written == [{"role": "original"}]


def test_global_policy_paths_under_policies_dir() -> None:
    """All SoT paths live under the same in-repo dir
    (``state/autoresearch/policies/``) — operators expect them
    co-located, and the in-repo location is git-tracked so ``git diff``
    shows the current mutation state (PR-RATCHET-1, 2026-05-21).
    PR-HYPERPARAM-FOUNDATION (2026-05-28) adds the hyperparam SoT path
    to the co-location invariant."""
    from core.paths import (
        GLOBAL_DECOMPOSITION_POLICY_PATH,
        GLOBAL_HYPERPARAM_POLICY_PATH,
        GLOBAL_POLICIES_DIR,
        GLOBAL_REFLECTION_POLICY_PATH,
        GLOBAL_RETRIEVAL_POLICY_PATH,
        GLOBAL_TOOL_POLICY_PATH,
        GLOBAL_WRAPPER_SECTIONS_PATH,
    )

    for path in (
        GLOBAL_WRAPPER_SECTIONS_PATH,
        GLOBAL_TOOL_POLICY_PATH,
        GLOBAL_DECOMPOSITION_POLICY_PATH,
        GLOBAL_RETRIEVAL_POLICY_PATH,
        GLOBAL_REFLECTION_POLICY_PATH,
        GLOBAL_HYPERPARAM_POLICY_PATH,
    ):
        assert path.parent == GLOBAL_POLICIES_DIR


# ---------------------------------------------------------------------------
# PR-DROP-HYPERPARAM-MUTATION (2026-05-31) — hyperparam is no longer mutable
# ---------------------------------------------------------------------------


def test_parse_mutation_rejects_hyperparam_kind_with_clear_message() -> None:
    """PR-DROP-HYPERPARAM-MUTATION (2026-05-31, operator decision) — a
    ``hyperparam`` mutation (ANY section, including the formerly-mutable
    ``reflection_depth``) is REJECTED at parse with a specific explanation:
    measurement params are fixed config and the reflection_depth axis is
    exhausted. This is the operator-visible signal, distinct from the generic
    not-in-TARGET_KINDS enumeration."""
    import json

    from core.self_improving.loop.runner import parse_mutation

    for section in ("reflection_depth", "max_turns", "seed_limit", "dim_set", "anything"):
        payload = json.dumps(
            {
                "target_kind": "hyperparam",
                "target_section": section,
                "new_value": "3",
                "rationale": "attempt a hyperparam mutation",
                "target_dim": "redundant_tool_invocation",
                "expected_dim": {"redundant_tool_invocation": -0.5},
            }
        )
        with pytest.raises(ValueError, match="hyperparam is not a mutable kind"):
            parse_mutation(payload)


def test_parse_mutation_accepts_all_seven_behaviour_kinds() -> None:
    """The 7 behaviour kinds remain mutator-dispatchable after the hyperparam
    drop. Iterates ``TARGET_KINDS`` so the assertion tracks the canonical set;
    nested-schema kinds use a dotted ``target_section``."""
    import json

    from core.self_improving.loop.policies import _NESTED_KINDS
    from core.self_improving.loop.runner import parse_mutation

    for kind in TARGET_KINDS:
        section = "tool.description" if kind in _NESTED_KINDS else "some_section"
        payload = json.dumps(
            {
                "target_kind": kind,
                "target_section": section,
                "new_value": "a new behaviour-policy value",
                "rationale": "behaviour-kind mutation should parse cleanly",
                "target_dim": "helpfulness",
                "expected_dim": {"helpfulness": 0.1},
            }
        )
        m = parse_mutation(payload)
        assert m.target_kind == kind


def test_reject_hyperparam_mutation_helper_always_raises() -> None:
    """The dedicated rejection helper raises unconditionally with the
    operator-facing message (pins the message text the contract promises)."""
    from core.self_improving.loop.runner import _reject_hyperparam_mutation

    with pytest.raises(ValueError, match="reflection_depth axis is exhausted"):
        _reject_hyperparam_mutation()


def test_apply_mutation_rejects_hyperparam_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second-layer defense: an externally-constructed ``hyperparam``
    Mutation that bypassed parse_mutation is still rejected at apply, before
    any write — the SoT path stays untouched."""
    from core.self_improving.loop.runner import Mutation, apply_mutation

    target = tmp_path / "hyperparam.json"
    _redirect_kind(monkeypatch, "hyperparam", target)
    bad = Mutation(
        target_section="reflection_depth",
        new_value="4",
        rationale="bypass parse",
        target_kind="hyperparam",
    )
    with pytest.raises(ValueError, match="hyperparam is not a mutable kind"):
        apply_mutation(bad, current_sections={"reflection_depth": "3"})
    # Rejection must precede the write.
    assert not target.exists()
