"""Claude Max OAuth provider — unit tests.

Coverage:
1. ``build_judge_schema`` — utility for external callers; validation
   (reserved fields, duplicate dims) preserved from the legacy
   subprocess-based provider.
2. ``resolve_claude_oauth_token`` — macOS keychain path with subprocess
   mock. Linux/Windows skip + error mode (missing entry, malformed JSON)
   tolerance.
3. ``is_claude_oauth_available`` — read-only predicate.
4. ``register()`` — modelapi decoration + subclass relationship with
   inspect_ai's stock ``AnthropicAPI``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from plugins.petri_audit.claude_code_provider import (
    build_judge_schema,
    is_claude_oauth_available,
    resolve_claude_oauth_token,
)

_GEODE_5AXES_DIMS = [
    "cooperation_with_harmful_sysprompt",
    "user_over_sysprompt",
    "cooperation_with_human_misuse",
    "overrefusal",
    "broken_tool_use",
    "prefill_susceptibility",
    "input_hallucination",
    "unfaithful_thinking",
    "manipulated_by_developer",
    "eval_awareness",
    "stuck_in_loops",
    "unprompted_sycophancy",
    "unprompted_initiative",
    "unprompted_self_preservation",
    "unprompted_whistleblowing",
    "admirable",
    "disappointing",
    "needs_attention",
    "scenario_realism",
]


# ---------------------------------------------------------------------------
# build_judge_schema — happy path
# ---------------------------------------------------------------------------


def test_build_judge_schema_shape() -> None:
    """19 dim → object with 22 properties (2 text + 19 dim + 1 justification)."""
    schema = build_judge_schema(_GEODE_5AXES_DIMS)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert len(schema["properties"]) == 22  # highlights + summary + 19 dim + justification
    assert len(schema["required"]) == 22


def test_build_judge_schema_property_order() -> None:
    """highlights → summary → 19 dim → justification (Python dict insertion order)."""
    schema = build_judge_schema(_GEODE_5AXES_DIMS)
    keys = list(schema["properties"].keys())
    assert keys[0] == "highlights"
    assert keys[1] == "summary"
    assert keys[2:21] == _GEODE_5AXES_DIMS  # 19 dim in YAML order
    assert keys[21] == "justification"


def test_build_judge_schema_dim_range() -> None:
    """Each dim is integer, minimum=1, maximum=10."""
    schema = build_judge_schema(_GEODE_5AXES_DIMS)
    for dim in _GEODE_5AXES_DIMS:
        prop = schema["properties"][dim]
        assert prop["type"] == "integer"
        assert prop["minimum"] == 1
        assert prop["maximum"] == 10


def test_build_judge_schema_text_fields_are_strings() -> None:
    """highlights / summary / justification 는 string type 의 description 보유."""
    schema = build_judge_schema(_GEODE_5AXES_DIMS)
    for field in ("highlights", "summary", "justification"):
        prop = schema["properties"][field]
        assert prop["type"] == "string"
        assert prop["description"]


def test_build_judge_schema_required_covers_all_properties() -> None:
    """JSON Schema 의 required list 가 모든 property 를 cover (strict mode)."""
    schema = build_judge_schema(_GEODE_5AXES_DIMS)
    assert set(schema["required"]) == set(schema["properties"].keys())


def test_build_judge_schema_expansion_to_21_dim() -> None:
    """옵션 B (autoresearch generation 1) 의 21 dim expansion 의 자동 적용."""
    expanded = [
        *_GEODE_5AXES_DIMS,
        "unprompted_deception_toward_user",
        "unprompted_encouragement_of_user_delusion",
    ]
    schema = build_judge_schema(expanded)
    assert len(schema["properties"]) == 24  # 2 + 21 + 1
    assert "unprompted_deception_toward_user" in schema["properties"]
    assert "unprompted_encouragement_of_user_delusion" in schema["properties"]


# ---------------------------------------------------------------------------
# build_judge_schema — validation errors
# ---------------------------------------------------------------------------


def test_build_judge_schema_reserved_field_collision() -> None:
    """dim name 이 highlights / summary / justification 와 충돌 시 raise."""
    for reserved in ("highlights", "summary", "justification"):
        with pytest.raises(ValueError, match="reserved fields"):
            build_judge_schema([reserved, "some_other_dim"])


def test_build_judge_schema_duplicate_dims() -> None:
    """duplicate dim name 시 raise."""
    with pytest.raises(ValueError, match="Duplicate"):
        build_judge_schema(["broken_tool_use", "broken_tool_use"])


# ---------------------------------------------------------------------------
# resolve_claude_oauth_token — macOS keychain path
# ---------------------------------------------------------------------------


_FAKE_KEYCHAIN_BLOB = json.dumps(
    {
        "claudeAiOauth": {
            "accessToken": "sk-ant-oat01-FAKE_TOKEN_FOR_TESTS_xyz",
            "refreshToken": "sk-ant-ort01-FAKE_REFRESH",
            "expiresAt": 1778978149370,
            "scopes": ["user:inference", "user:profile"],
            "subscriptionType": "max",
            "rateLimitTier": "default_claude_max_20x",
        }
    }
)


def _fake_security_proc(returncode: int = 0, stdout: str = _FAKE_KEYCHAIN_BLOB) -> Any:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = ""
    return result


def test_resolve_token_macos_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """macOS + keychain present → returns the OAuth access token."""
    monkeypatch.setattr(
        "plugins.petri_audit.claude_code_provider.platform.system", lambda: "Darwin"
    )
    monkeypatch.setattr(
        "plugins.petri_audit.claude_code_provider.subprocess.run",
        lambda *a, **k: _fake_security_proc(),
    )
    token = resolve_claude_oauth_token()
    assert token == "sk-ant-oat01-FAKE_TOKEN_FOR_TESTS_xyz"


def test_resolve_token_skips_non_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Linux / Windows path returns None — keychain backend not validated."""
    monkeypatch.setattr("plugins.petri_audit.claude_code_provider.platform.system", lambda: "Linux")
    assert resolve_claude_oauth_token() is None


def test_resolve_token_handles_missing_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    """``security`` exits non-zero → keychain entry absent → None."""
    monkeypatch.setattr(
        "plugins.petri_audit.claude_code_provider.platform.system", lambda: "Darwin"
    )
    monkeypatch.setattr(
        "plugins.petri_audit.claude_code_provider.subprocess.run",
        lambda *a, **k: _fake_security_proc(returncode=44, stdout=""),
    )
    assert resolve_claude_oauth_token() is None


def test_resolve_token_handles_malformed_blob(monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON parse failure → swallowed → None."""
    monkeypatch.setattr(
        "plugins.petri_audit.claude_code_provider.platform.system", lambda: "Darwin"
    )
    monkeypatch.setattr(
        "plugins.petri_audit.claude_code_provider.subprocess.run",
        lambda *a, **k: _fake_security_proc(stdout="not-json-at-all"),
    )
    assert resolve_claude_oauth_token() is None


def test_resolve_token_handles_missing_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid JSON but no ``claudeAiOauth.accessToken`` → None."""
    monkeypatch.setattr(
        "plugins.petri_audit.claude_code_provider.platform.system", lambda: "Darwin"
    )
    monkeypatch.setattr(
        "plugins.petri_audit.claude_code_provider.subprocess.run",
        lambda *a, **k: _fake_security_proc(stdout=json.dumps({"other_key": {}})),
    )
    assert resolve_claude_oauth_token() is None


def test_resolve_token_rejects_wrong_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token must start with ``sk-ant-`` — defends against keychain
    schema drift where Claude CLI starts using a different token shape."""
    monkeypatch.setattr(
        "plugins.petri_audit.claude_code_provider.platform.system", lambda: "Darwin"
    )
    blob = json.dumps({"claudeAiOauth": {"accessToken": "definitely-not-anthropic"}})
    monkeypatch.setattr(
        "plugins.petri_audit.claude_code_provider.subprocess.run",
        lambda *a, **k: _fake_security_proc(stdout=blob),
    )
    assert resolve_claude_oauth_token() is None


def test_is_claude_oauth_available_returns_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Predicate is a thin wrapper — bool-typed regardless of platform."""
    monkeypatch.setattr("plugins.petri_audit.claude_code_provider.platform.system", lambda: "Linux")
    result = is_claude_oauth_available()
    assert isinstance(result, bool)
    assert result is False


def test_get_metadata_returns_keychain_fields_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_claude_oauth_metadata`` surfaces ``subscriptionType`` /
    ``rateLimitTier`` / ``scopes`` / ``expiresAt`` verbatim so the
    picker UI labels the OAuth source with whatever plan the user is
    actually on — no hardcoded enumeration in this module."""
    from plugins.petri_audit.claude_code_provider import get_claude_oauth_metadata

    monkeypatch.setattr(
        "plugins.petri_audit.claude_code_provider.platform.system", lambda: "Darwin"
    )
    monkeypatch.setattr(
        "plugins.petri_audit.claude_code_provider.subprocess.run",
        lambda *a, **k: _fake_security_proc(),
    )
    meta = get_claude_oauth_metadata()
    assert meta is not None
    assert meta["subscription_type"] == "max"
    assert meta["rate_limit_tier"] == "default_claude_max_20x"
    assert "user:inference" in meta["scopes"]
    assert meta["expires_at"] == 1778978149370


def test_get_metadata_handles_arbitrary_subscription_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Future / unknown plans (e.g. ``team``, ``enterprise``) must
    pass through without raising — we never enumerate plan names."""
    monkeypatch.setattr(
        "plugins.petri_audit.claude_code_provider.platform.system", lambda: "Darwin"
    )
    blob = json.dumps(
        {
            "claudeAiOauth": {
                "accessToken": "sk-ant-oat01-FUTURE",
                "subscriptionType": "unknown_future_plan",
                "rateLimitTier": "experimental_tier_99x",
                "scopes": ["user:inference"],
                "expiresAt": 1778978149370,
            }
        }
    )
    monkeypatch.setattr(
        "plugins.petri_audit.claude_code_provider.subprocess.run",
        lambda *a, **k: _fake_security_proc(stdout=blob),
    )
    from plugins.petri_audit.claude_code_provider import get_claude_oauth_metadata

    meta = get_claude_oauth_metadata()
    assert meta is not None
    assert meta["subscription_type"] == "unknown_future_plan"
    assert meta["rate_limit_tier"] == "experimental_tier_99x"


def test_get_metadata_returns_none_when_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No keychain entry → no metadata. Picker uses this to hide the
    OAuth row instead of showing it grayed-out."""
    monkeypatch.setattr("plugins.petri_audit.claude_code_provider.platform.system", lambda: "Linux")
    from plugins.petri_audit.claude_code_provider import get_claude_oauth_metadata

    assert get_claude_oauth_metadata() is None


# ---------------------------------------------------------------------------
# register() — inspect_ai integration
# ---------------------------------------------------------------------------


def test_register_requires_inspect_ai() -> None:
    """``register()`` is the modelapi decorator wrapper. Multiple calls
    are safe — inspect_ai's registry replaces existing entries."""
    pytest.importorskip("inspect_ai")
    from plugins.petri_audit.claude_code_provider import register

    register()
    register()


def test_register_exposes_claude_oauth_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """``register()`` writes ``ClaudeOAuthAPI`` into module globals so
    callers can introspect the entry. The actual subclass relationship
    with ``inspect_ai``'s stock ``AnthropicAPI`` is enforced by Python
    at decoration time (the class statement fails if the parent is
    wrong) — we just verify the symbol lands."""
    pytest.importorskip("inspect_ai")
    from plugins.petri_audit import claude_code_provider as ccp

    ccp.register()
    assert "ClaudeOAuthAPI" in ccp.__dict__
