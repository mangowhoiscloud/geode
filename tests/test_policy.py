"""Tests for Policy Chain — 6-layer tool access control."""

from __future__ import annotations

import pytest
from core.tools.policy import (
    OrgPolicy,
    PolicyChain,
    ProfilePolicy,
    ToolPolicy,
    build_6layer_chain,
    load_org_policy,
    load_profile_policy,
)


class TestToolPolicy:
    def test_no_restrictions_allows_all(self):
        p = ToolPolicy(name="open", mode="*")
        assert p.is_allowed("any_tool") is True

    def test_allowed_tools_whitelist(self):
        p = ToolPolicy(name="whitelist", mode="scoring", allowed_tools={"psm_calculate"})
        assert p.is_allowed("psm_calculate") is True
        assert p.is_allowed("run_analyst") is False

    def test_denied_tools_blacklist(self):
        p = ToolPolicy(
            name="blacklist", mode="dry_run", denied_tools={"run_analyst", "run_evaluator"}
        )
        assert p.is_allowed("psm_calculate") is True
        assert p.is_allowed("run_analyst") is False
        assert p.is_allowed("run_evaluator") is False

    def test_allowed_takes_precedence_over_denied(self):
        p = ToolPolicy(
            name="mixed",
            mode="*",
            allowed_tools={"psm_calculate"},
            denied_tools={"psm_calculate"},
        )
        # allowed_tools takes precedence (whitelist mode)
        assert p.is_allowed("psm_calculate") is True


class TestPolicyChain:
    def test_empty_chain_allows_all(self):
        chain = PolicyChain()
        result = chain.filter_tools(["a", "b", "c"], mode="any")
        assert result == ["a", "b", "c"]

    def test_single_policy_filters(self):
        chain = PolicyChain()
        chain.add_policy(
            ToolPolicy(
                name="block_llm",
                mode="dry_run",
                denied_tools={"run_analyst", "run_evaluator"},
            )
        )
        result = chain.filter_tools(
            ["run_analyst", "run_evaluator", "psm_calculate"],
            mode="dry_run",
        )
        assert result == ["psm_calculate"]

    def test_policy_mode_matching(self):
        chain = PolicyChain()
        chain.add_policy(
            ToolPolicy(
                name="dry_run_only",
                mode="dry_run",
                denied_tools={"run_analyst"},
            )
        )
        # In full_pipeline mode, policy doesn't apply
        result = chain.filter_tools(["run_analyst"], mode="full_pipeline")
        assert result == ["run_analyst"]

        # In dry_run mode, policy applies
        result = chain.filter_tools(["run_analyst"], mode="dry_run")
        assert result == []

    def test_wildcard_mode_applies_always(self):
        chain = PolicyChain()
        chain.add_policy(
            ToolPolicy(
                name="global_deny",
                mode="*",
                denied_tools={"dangerous_tool"},
            )
        )
        assert chain.filter_tools(["dangerous_tool"], mode="full_pipeline") == []
        assert chain.filter_tools(["dangerous_tool"], mode="dry_run") == []
        assert chain.filter_tools(["dangerous_tool"], mode="scoring") == []

    def test_multiple_policies_all_must_pass(self):
        chain = PolicyChain()
        chain.add_policy(
            ToolPolicy(
                name="policy_a",
                mode="*",
                denied_tools={"tool_x"},
            )
        )
        chain.add_policy(
            ToolPolicy(
                name="policy_b",
                mode="*",
                denied_tools={"tool_y"},
            )
        )
        result = chain.filter_tools(["tool_x", "tool_y", "tool_z"], mode="any")
        assert result == ["tool_z"]

    def test_is_allowed_single_check(self):
        chain = PolicyChain()
        chain.add_policy(ToolPolicy(name="block", mode="*", denied_tools={"blocked"}))
        assert chain.is_allowed("ok_tool", mode="any") is True
        assert chain.is_allowed("blocked", mode="any") is False

    def test_remove_policy(self):
        chain = PolicyChain()
        chain.add_policy(ToolPolicy(name="removable", mode="*", denied_tools={"x"}))
        assert chain.is_allowed("x", mode="any") is False

        assert chain.remove_policy("removable") is True
        assert chain.is_allowed("x", mode="any") is True

    def test_remove_nonexistent_returns_false(self):
        chain = PolicyChain()
        assert chain.remove_policy("nope") is False

    def test_list_policies(self):
        chain = PolicyChain()
        chain.add_policy(ToolPolicy(name="b", mode="*", priority=200))
        chain.add_policy(ToolPolicy(name="a", mode="*", priority=100))
        assert chain.list_policies() == ["a", "b"]  # sorted by priority

    def test_clear(self):
        chain = PolicyChain()
        chain.add_policy(ToolPolicy(name="x", mode="*", denied_tools={"a"}))
        chain.clear()
        assert chain.filter_tools(["a"], mode="any") == ["a"]


class TestRegistryWithPolicy:
    def test_registry_list_tools_with_policy(self):
        from core.tools.registry import ToolRegistry

        class FakeTool:
            @property
            def name(self):
                return "test_tool"

            @property
            def description(self):
                return "desc"

            @property
            def parameters(self):
                return {}

            def execute(self, **kw):
                return {}

        reg = ToolRegistry()
        reg.register(FakeTool())

        chain = PolicyChain()
        chain.add_policy(ToolPolicy(name="block", mode="dry_run", denied_tools={"test_tool"}))

        assert reg.list_tools() == ["test_tool"]
        assert reg.list_tools(policy=chain, mode="dry_run") == []
        assert reg.list_tools(policy=chain, mode="full_pipeline") == ["test_tool"]

    def test_registry_execute_blocked_raises(self):
        from core.tools.registry import ToolRegistry

        class FakeTool:
            @property
            def name(self):
                return "blocked_tool"

            @property
            def description(self):
                return "desc"

            @property
            def parameters(self):
                return {}

            def execute(self, **kw):
                return {}

        reg = ToolRegistry()
        reg.register(FakeTool())

        chain = PolicyChain()
        chain.add_policy(ToolPolicy(name="block", mode="*", denied_tools={"blocked_tool"}))

        with pytest.raises(PermissionError, match="blocked by policy"):
            reg.execute("blocked_tool", policy=chain, mode="full_pipeline")


# ---------------------------------------------------------------------------
# Layer 1: ProfilePolicy
# ---------------------------------------------------------------------------


class TestProfilePolicy:
    def test_default_profile_allows_all(self):
        profile = ProfilePolicy()
        policies = profile.to_policies()
        # Default: allow_expensive=True, allow_write=True, allow_dangerous=False
        # Only no_dangerous should be generated
        assert len(policies) == 1
        assert "no_dangerous" in policies[0].name

    def test_no_expensive_blocks_analysis(self):
        profile = ProfilePolicy(user_id="alice", allow_expensive=False)
        policies = profile.to_policies()
        names = [p.name for p in policies]
        assert any("no_expensive" in n for n in names)
        chain = PolicyChain()
        for p in policies:
            chain.add_policy(p)
        assert chain.is_allowed("analyze_ip", mode="any") is False
        assert chain.is_allowed("list_ips", mode="any") is True

    def test_no_write_blocks_memory(self):
        profile = ProfilePolicy(user_id="bob", allow_write=False)
        policies = profile.to_policies()
        chain = PolicyChain()
        for p in policies:
            chain.add_policy(p)
        assert chain.is_allowed("memory_save", mode="any") is False
        assert chain.is_allowed("memory_search", mode="any") is True

    def test_allow_dangerous_flag(self):
        # Default: dangerous blocked
        profile = ProfilePolicy(user_id="carol")
        policies = profile.to_policies()
        chain = PolicyChain()
        for p in policies:
            chain.add_policy(p)
        assert chain.is_allowed("run_bash", mode="any") is False

        # Explicit allow
        profile2 = ProfilePolicy(user_id="dave", allow_dangerous=True)
        policies2 = profile2.to_policies()
        assert not any("no_dangerous" in p.name for p in policies2)

    def test_custom_denied_tools(self):
        profile = ProfilePolicy(
            user_id="eve",
            denied_tools={"send_notification", "batch_analyze"},
        )
        policies = profile.to_policies()
        chain = PolicyChain()
        for p in policies:
            chain.add_policy(p)
        assert chain.is_allowed("send_notification", mode="any") is False
        assert chain.is_allowed("batch_analyze", mode="any") is False
        assert chain.is_allowed("list_ips", mode="any") is True

    def test_load_profile_nonexistent_returns_default(self):
        profile = load_profile_policy("/nonexistent/dir")
        assert profile.allow_expensive is True
        assert profile.allow_write is True

    def test_load_profile_from_toml(self, tmp_path):
        pref = tmp_path / "preferences.toml"
        pref.write_text(
            "[policy]\n"
            "allow_expensive = false\n"
            "allow_write = false\n"
            "allow_dangerous = true\n"
            'denied_tools = ["send_notification"]\n'
        )
        profile = load_profile_policy(str(tmp_path))
        assert profile.allow_expensive is False
        assert profile.allow_write is False
        assert profile.allow_dangerous is True
        assert "send_notification" in profile.denied_tools


# ---------------------------------------------------------------------------
# Layer 2: OrgPolicy
# ---------------------------------------------------------------------------


class TestOrgPolicy:
    def test_empty_org_no_policies(self):
        org = OrgPolicy()
        assert org.to_policies() == []

    def test_org_denied_tools(self):
        org = OrgPolicy(org_id="nexon", denied_tools={"run_bash", "send_notification"})
        policies = org.to_policies()
        assert len(policies) == 1
        chain = PolicyChain()
        for p in policies:
            chain.add_policy(p)
        assert chain.is_allowed("run_bash", mode="any") is False
        assert chain.is_allowed("list_ips", mode="any") is True

    def test_org_priority_higher_than_profile(self):
        """Org policies (priority=5) override profile (priority=10)."""
        org = OrgPolicy(org_id="team", denied_tools={"analyze_ip"})
        profile = ProfilePolicy(user_id="alice", allow_expensive=True)

        chain = build_6layer_chain(profile=profile, org=org)
        # Org blocks analyze_ip even though profile allows it
        assert chain.is_allowed("analyze_ip", mode="any") is False

    def test_load_org_nonexistent_returns_default(self):
        org = load_org_policy("/nonexistent/config.toml")
        assert org.denied_tools == set()

    def test_load_org_from_toml(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[policy.org]\norg_id = "analytics"\ndenied_tools = ["run_bash", "send_notification"]\n'
        )
        org = load_org_policy(str(cfg))
        assert org.org_id == "analytics"
        assert "run_bash" in org.denied_tools
        assert "send_notification" in org.denied_tools


# ---------------------------------------------------------------------------
# build_6layer_chain
# ---------------------------------------------------------------------------


class TestBuild6LayerChain:
    def test_empty_chain(self):
        chain = build_6layer_chain()
        assert chain.is_allowed("anything", mode="any") is True

    def test_with_profile_only(self):
        profile = ProfilePolicy(user_id="x", allow_expensive=False)
        chain = build_6layer_chain(profile=profile)
        assert chain.is_allowed("analyze_ip", mode="any") is False
        assert chain.is_allowed("list_ips", mode="any") is True

    def test_with_mode_policies(self):
        mode_policies = [
            ToolPolicy(
                name="dry_run_block",
                mode="dry_run",
                denied_tools={"run_analyst"},
                priority=100,
            )
        ]
        chain = build_6layer_chain(mode_policies=mode_policies)
        assert chain.is_allowed("run_analyst", mode="dry_run") is False
        assert chain.is_allowed("run_analyst", mode="full_pipeline") is True

    def test_all_layers_combined(self):
        org = OrgPolicy(org_id="team", denied_tools={"run_bash"})
        profile = ProfilePolicy(user_id="alice", allow_expensive=False)
        mode_policies = [
            ToolPolicy(
                name="dry_run_block",
                mode="dry_run",
                denied_tools={"send_notification"},
                priority=100,
            )
        ]
        chain = build_6layer_chain(profile=profile, org=org, mode_policies=mode_policies)
        # Org blocks run_bash
        assert chain.is_allowed("run_bash", mode="any") is False
        # Profile blocks analyze_ip
        assert chain.is_allowed("analyze_ip", mode="any") is False
        # Mode blocks send_notification in dry_run only
        assert chain.is_allowed("send_notification", mode="dry_run") is False
        assert chain.is_allowed("send_notification", mode="full_pipeline") is True
        # Other tools pass
        assert chain.is_allowed("list_ips", mode="any") is True
