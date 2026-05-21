"""ADR-012 M1 — Skill mutation slot 개통 invariants.

Pins the dispatcher's 5-kind contract + skill_catalog 의 dotted-key
flat ↔ nested round-trip + T2 reader 호환.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.self_improving_loop import policies as pol


@pytest.fixture
def isolated_skill_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect skill_catalog SoT to tmp_path."""
    target = tmp_path / "skill-catalog.json"
    monkeypatch.setitem(pol._KIND_TO_PATH, "skill_catalog", target)
    return target


# TARGET_KINDS / is_valid_target_kind ----------------------------------------


def test_target_kinds_includes_skill_catalog() -> None:
    assert "skill_catalog" in pol.TARGET_KINDS


def test_target_kinds_count_is_5() -> None:
    """4 prior (prompt / tool_policy / decomposition / reflection) + 1 new (skill_catalog)."""
    assert len(pol.TARGET_KINDS) == 5
    assert pol.TARGET_KINDS == (
        "prompt",
        "tool_policy",
        "decomposition",
        "reflection",
        "skill_catalog",
    )


def test_is_valid_target_kind_accepts_skill_catalog() -> None:
    assert pol.is_valid_target_kind("skill_catalog") is True


def test_is_valid_target_kind_still_rejects_retrieval() -> None:
    """S0d deprecation 유지 — M1 가 추가만 하고 retrieval 복원 안 함."""
    assert pol.is_valid_target_kind("retrieval") is False


# policy_path ----------------------------------------------------------------


def test_policy_path_skill_catalog_maps_to_in_repo() -> None:
    from core.paths import GLOBAL_SKILL_CATALOG_PATH

    assert pol.policy_path("skill_catalog") == GLOBAL_SKILL_CATALOG_PATH


# Flatten / Unflatten round-trip ---------------------------------------------


def test_unflatten_produces_nested_dict_with_bool_coercion() -> None:
    flat = {
        "geode-gitflow.description": "Curated workflow.",
        "geode-gitflow.user_invocable": "true",
        "frontier-research.user_invocable": "false",
    }
    nested = pol._unflatten_nested(flat)
    assert nested == {
        "geode-gitflow": {"description": "Curated workflow.", "user_invocable": True},
        "frontier-research": {"user_invocable": False},
    }


def test_unflatten_drops_keys_without_dot() -> None:
    """Mutation contract requires dotted form for nested kinds."""
    flat = {"loose_key": "value", "geode-gitflow.description": "x"}
    nested = pol._unflatten_nested(flat)
    assert "loose_key" not in nested
    assert nested == {"geode-gitflow": {"description": "x"}}


def test_unflatten_drops_empty_skill_or_field() -> None:
    """Dotted but malformed (`".desc"` / `"skill."`) → drop."""
    flat = {".description": "x", "skill.": "y", "good.desc": "z"}
    nested = pol._unflatten_nested(flat)
    assert nested == {"good": {"desc": "z"}}


def test_flatten_inverts_unflatten_for_typical_payload() -> None:
    flat = {
        "geode-gitflow.description": "Curated workflow.",
        "geode-gitflow.user_invocable": "true",
    }
    nested = pol._unflatten_nested(flat)
    re_flat = pol._flatten_nested(nested)
    assert re_flat == flat


def test_flatten_preserves_lowercase_bool() -> None:
    """bool True/False → 'true'/'false' (T2 reader 가 다시 bool 로 검증)."""
    nested = {"sk": {"user_invocable": False}}
    flat = pol._flatten_nested(nested)
    assert flat == {"sk.user_invocable": "false"}


def test_flatten_skips_non_dict_entry() -> None:
    """Forward-compat — disk payload 에 dict 아닌 entry → skip."""
    nested = {"sk": "not a dict", "good": {"desc": "x"}}
    flat = pol._flatten_nested(nested)
    assert flat == {"good.desc": "x"}


# write_policy → T2 reader 호환 ----------------------------------------------


def test_write_skill_catalog_then_t2_reader_parses(isolated_skill_catalog: Path) -> None:
    """가장 중요한 invariant — M1 write_policy 가 쓴 file 을 T2 reader 가
    그대로 parse 해야 함 (mutator → reader 의 end-to-end consistency)."""
    flat = {
        "geode-gitflow.description": "Curated workflow.",
        "geode-gitflow.user_invocable": "true",
    }
    pol.write_policy("skill_catalog", flat)
    raw = isolated_skill_catalog.read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert payload == {
        "geode-gitflow": {
            "description": "Curated workflow.",
            "user_invocable": True,
        }
    }
    # Independently: invoke T2 reader on the same on-disk path.
    from core.skills.skill_catalog_policy import _coerce, _validate_schema

    _validate_schema(payload, isolated_skill_catalog)
    coerced = _coerce(payload)
    assert coerced == {
        "geode-gitflow": {"description": "Curated workflow.", "user_invocable": True}
    }


# load_policy round-trip -----------------------------------------------------


def test_load_skill_catalog_returns_flat_dotted(isolated_skill_catalog: Path) -> None:
    isolated_skill_catalog.write_text(
        json.dumps(
            {
                "geode-gitflow": {
                    "description": "Curated workflow.",
                    "user_invocable": True,
                }
            }
        ),
        encoding="utf-8",
    )
    flat = pol.load_policy("skill_catalog")
    assert flat == {
        "geode-gitflow.description": "Curated workflow.",
        "geode-gitflow.user_invocable": "true",
    }


def test_write_then_load_skill_catalog_round_trips(isolated_skill_catalog: Path) -> None:
    original = {
        "sk1.description": "desc1",
        "sk1.user_invocable": "false",
        "sk2.description": "desc2",
    }
    pol.write_policy("skill_catalog", original)
    loaded = pol.load_policy("skill_catalog")
    assert loaded == original


def test_load_skill_catalog_missing_file_returns_empty() -> None:
    from core.paths import GLOBAL_SKILL_CATALOG_PATH

    # No isolated_skill_catalog fixture — default path. Test only asserts
    # graceful empty-dict behaviour, not against the operator's file.
    # If the operator has a real file we monkey-patch around it.
    if GLOBAL_SKILL_CATALOG_PATH.is_file():
        pytest.skip("operator-local skill-catalog.json present; skipping")
    assert pol.load_policy("skill_catalog") == {}


# BC — pre-M1 4 kinds unchanged ----------------------------------------------


def test_load_tool_policy_still_returns_flat_string_dict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "tool-policy.json"
    target.write_text(
        json.dumps({"allowed_tools": "bash, read", "forbidden_tools": "write"}),
        encoding="utf-8",
    )
    monkeypatch.setitem(pol._KIND_TO_PATH, "tool_policy", target)
    flat = pol.load_policy("tool_policy")
    assert flat == {"allowed_tools": "bash, read", "forbidden_tools": "write"}


def test_write_tool_policy_keeps_legacy_string_serialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "tool-policy.json"
    monkeypatch.setitem(pol._KIND_TO_PATH, "tool_policy", target)
    pol.write_policy("tool_policy", {"allowed_tools": "bash"})
    payload = json.loads(target.read_text(encoding="utf-8"))
    # Flat string dict, NOT nested — backwards compat preserved.
    assert payload == {"allowed_tools": "bash"}


# Public surface --------------------------------------------------------------


def test_policies_exports_target_kinds() -> None:
    assert "TARGET_KINDS" in pol.__all__
    assert "is_valid_target_kind" in pol.__all__
