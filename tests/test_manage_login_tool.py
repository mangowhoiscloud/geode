"""Phase v0.50.1 — manage_login agentic tool tests.

Verifies the tool definition is registered, the handler is wired, and
calling it produces a structured snapshot the LLM can reason over.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from core.cli.tool_handlers import _build_system_handlers


def _handler():
    handlers = _build_system_handlers(force_dry=True, readiness=MagicMock(), mcp_manager=None)
    return handlers["manage_login"]


class TestToolDefinition:
    def test_manage_login_in_definitions_json(self) -> None:
        path = Path(__file__).resolve().parents[1] / "core" / "tools" / "definitions.json"
        data = json.loads(path.read_text())
        names = [t["name"] for t in data]
        assert "manage_login" in names, "manage_login missing from definitions.json"

        entry = next(t for t in data if t["name"] == "manage_login")
        assert entry["category"] == "model"
        # Subcommand enum must include the user-facing actions
        sub_enum = entry["input_schema"]["properties"]["subcommand"]["enum"]
        for required in ("status", "add", "oauth", "set-key", "use", "route", "remove", "quota"):
            assert required in sub_enum, required


class TestHandlerWired:
    def test_handler_is_registered(self) -> None:
        handlers = _build_system_handlers(force_dry=True, readiness=MagicMock(), mcp_manager=None)
        assert "manage_login" in handlers

    def test_status_returns_structured_snapshot(self) -> None:
        result = _handler()(subcommand="status")
        assert result["status"] == "ok"
        assert result["action"] == "login"
        # Snapshot fields — never None, always lists/dicts
        assert isinstance(result["plans"], list)
        assert isinstance(result["profiles"], list)
        assert isinstance(result["routing"], dict)

    def test_help_subcommand_runs_without_mutation(self) -> None:
        result = _handler()(subcommand="help")
        assert result["status"] == "ok"
        assert result["subcommand"] == "help"

    def test_quota_subcommand_returns_payload(self) -> None:
        result = _handler()(subcommand="quota")
        assert result["status"] == "ok"
        assert result["subcommand"] == "quota"


class TestSafetyRegistration:
    def test_manage_login_in_write_tools(self) -> None:
        from core.agent.safety import WRITE_TOOLS

        assert "manage_login" in WRITE_TOOLS

    def test_manage_login_blocked_for_subagents(self) -> None:
        from core.agent.sub_agent import SUBAGENT_DENIED_TOOLS

        assert "manage_login" in SUBAGENT_DENIED_TOOLS

    def test_manage_login_excluded_from_auto_recovery(self) -> None:
        from core.agent.error_recovery import _EXCLUDED_TOOLS

        assert "manage_login" in _EXCLUDED_TOOLS

    def test_approval_message_points_at_login(self) -> None:
        from core.agent.approval import _write_denial_with_fallback

        out = _write_denial_with_fallback("manage_login")
        assert "/login" in out["error"] or "/login" in out.get("fallback_hint", "")


class TestRouting:
    def test_set_key_via_tool_persists(self, tmp_path: Path, monkeypatch) -> None:
        # Redirect auth.toml to tmp so the test never touches ~/.geode
        monkeypatch.setenv("GEODE_AUTH_TOML", str(tmp_path / "auth.toml"))

        # Pre-register a plan via the registry so set-key has a target
        from core.auth.plan_registry import get_plan_registry
        from core.auth.plans import GLM_CODING_TIERS

        registry = get_plan_registry()
        registry.add(GLM_CODING_TIERS["lite"])

        result = _handler()(subcommand="set-key", args="glm-coding-lite zai-xx-1234567890")
        assert result["status"] == "ok"

        bound = [p for p in result["profiles"] if p["plan_id"] == "glm-coding-lite"]
        assert bound, "set-key did not bind a profile to the plan"


class TestVerdictPerOwnProvider:
    """Regression — every profile must surface the verdict against its OWN
    provider, not a stale ``provider_mismatch`` from a sibling-provider
    iteration. Pre-fix the ``verdict_index`` dict-key collided across
    providers and the last-iterated provider's mismatch verdict overwrote
    the real one, so a healthy PAYG profile showed as ``eligible=False /
    provider_mismatch`` to the LLM and the dashboard.
    """

    def test_multi_provider_profiles_keep_real_verdicts(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("GEODE_AUTH_TOML", str(tmp_path / "auth.toml"))

        from core.auth.profiles import AuthProfile, CredentialType
        from core.wiring.container import ensure_profile_store

        store = ensure_profile_store()
        # Three healthy profiles, one per provider — none should be reported
        # as ``provider_mismatch`` because each is being evaluated against
        # its own provider.
        for name, provider in (
            ("openai-codex:user", "openai-codex"),
            ("openai:work", "openai"),
            ("anthropic:work", "anthropic"),
        ):
            store.add(
                AuthProfile(
                    name=name,
                    provider=provider,
                    credential_type=CredentialType.API_KEY,
                    key="sk-xx",
                )
            )
        try:
            result = _handler()(subcommand="status")
            assert result["status"] == "ok"
            for p in result["profiles"]:
                if p["name"] in {"openai-codex:user", "openai:work", "anthropic:work"}:
                    assert p["eligible"] is True, (
                        f"{p['name']} should be eligible against its own provider — "
                        f"got reason={p['reason']!r} detail={p['reason_detail']!r}"
                    )
                    assert p["reason"] != "provider_mismatch"
        finally:
            for name in ("openai-codex:user", "openai:work", "anthropic:work"):
                store.remove(name)
