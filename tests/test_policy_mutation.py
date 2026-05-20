"""PR-6 C-5 — policy mutation expansion invariants.

Pins the new ``target_kind`` field on :class:`Mutation`, the
``core.self_improving_loop.policies`` SoT helpers, and
``apply_mutation``'s dispatcher routing to the right policy file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.self_improving_loop.policies import (
    TARGET_KINDS,
    is_valid_target_kind,
    load_policy,
    policy_path,
    write_policy,
)
from core.self_improving_loop.runner import (
    Mutation,
    apply_mutation,
    parse_mutation,
)

from core.self_improving_loop import policies as _policies_mod

# ---------------------------------------------------------------------------
# TARGET_KINDS + is_valid_target_kind
# ---------------------------------------------------------------------------


def test_target_kinds_contains_all_five() -> None:
    """Plan Q3 — exactly five enum values; pin the set."""
    assert set(TARGET_KINDS) == {
        "prompt",
        "tool_policy",
        "decomposition",
        "retrieval",
        "reflection",
    }


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
    """Distinct SoT per kind so policies evolve independently."""
    paths = {kind: policy_path(kind) for kind in TARGET_KINDS}
    # All 5 paths are unique
    assert len(set(paths.values())) == 5


def test_policy_path_prompt_points_to_wrapper_sections() -> None:
    from core.paths import GLOBAL_WRAPPER_SECTIONS_SOT

    assert policy_path("prompt") == GLOBAL_WRAPPER_SECTIONS_SOT


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


def test_apply_mutation_retrieval_writes_to_retrieval_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "retrieval.json"
    _redirect_kind(monkeypatch, "retrieval", target)
    m = Mutation(
        target_section="top_k",
        new_value="3",
        rationale="r",
        target_kind="retrieval",
    )
    apply_mutation(m, current_sections={})
    assert target.exists()


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
    ``autoresearch.train.write_wrapper_prompt_sections`` so the
    schema enforcement (single paragraph / 600-char cap) survives
    the PR-6 dispatcher rewrite."""
    from autoresearch import train as _train

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


def test_global_policy_paths_under_self_improving_loop_dir() -> None:
    """All 5 SoT paths live under the same dir as wrapper-sections —
    operators expect them co-located."""
    from core.paths import (
        GLOBAL_DECOMPOSITION_POLICY_SOT,
        GLOBAL_REFLECTION_POLICY_SOT,
        GLOBAL_RETRIEVAL_POLICY_SOT,
        GLOBAL_SELF_IMPROVING_LOOP_DIR,
        GLOBAL_TOOL_POLICY_SOT,
        GLOBAL_WRAPPER_SECTIONS_SOT,
    )

    for path in (
        GLOBAL_WRAPPER_SECTIONS_SOT,
        GLOBAL_TOOL_POLICY_SOT,
        GLOBAL_DECOMPOSITION_POLICY_SOT,
        GLOBAL_RETRIEVAL_POLICY_SOT,
        GLOBAL_REFLECTION_POLICY_SOT,
    ):
        assert path.parent == GLOBAL_SELF_IMPROVING_LOOP_DIR
