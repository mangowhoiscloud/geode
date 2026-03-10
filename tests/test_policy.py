"""Tests for Policy Chain — mode-based tool access control."""

from __future__ import annotations

import pytest
from core.tools.policy import PolicyChain, ToolPolicy


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
