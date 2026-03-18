"""Tests for 6-layer Policy Chain — ProfilePolicy, OrgPolicy, build_6layer_chain."""

from __future__ import annotations

from core.tools.policy import (
    OrgPolicy,
    PolicyChain,
    ProfilePolicy,
    ToolPolicy,
    build_6layer_chain,
    load_org_policy,
    load_profile_policy,
)

# ---------------------------------------------------------------------------
# ProfilePolicy
# ---------------------------------------------------------------------------


class TestProfilePolicy:
    def test_default_permissive(self):
        p = ProfilePolicy()
        assert p.allow_expensive
        assert p.allow_write
        assert not p.allow_dangerous
        policies = p.to_policies()
        # Default: only deny dangerous
        assert len(policies) == 1
        assert "no_dangerous" in policies[0].name

    def test_deny_expensive(self):
        p = ProfilePolicy(user_id="test", allow_expensive=False)
        policies = p.to_policies()
        names = [pol.name for pol in policies]
        assert any("no_expensive" in n for n in names)
        # Check denied tools
        expensive_pol = next(pol for pol in policies if "no_expensive" in pol.name)
        assert "analyze_ip" in expensive_pol.denied_tools

    def test_deny_write(self):
        p = ProfilePolicy(user_id="test", allow_write=False)
        policies = p.to_policies()
        write_pol = next(pol for pol in policies if "no_write" in pol.name)
        assert "memory_save" in write_pol.denied_tools

    def test_custom_denied_tools(self):
        p = ProfilePolicy(
            user_id="test",
            denied_tools={"special_tool", "another_tool"},
        )
        policies = p.to_policies()
        custom = [pol for pol in policies if "custom_deny" in pol.name]
        assert len(custom) == 1
        assert "special_tool" in custom[0].denied_tools

    def test_all_restrictions(self):
        p = ProfilePolicy(
            user_id="strict",
            allow_expensive=False,
            allow_write=False,
            allow_dangerous=False,
            denied_tools={"custom_tool"},
        )
        policies = p.to_policies()
        assert len(policies) == 4  # expensive + write + dangerous + custom

    def test_priority_is_10(self):
        p = ProfilePolicy(user_id="test", allow_expensive=False)
        for pol in p.to_policies():
            assert pol.priority == 10


# ---------------------------------------------------------------------------
# OrgPolicy
# ---------------------------------------------------------------------------


class TestOrgPolicy:
    def test_default_no_restrictions(self):
        o = OrgPolicy()
        assert len(o.to_policies()) == 0

    def test_org_denied_tools(self):
        o = OrgPolicy(org_id="nexon", denied_tools={"run_bash", "set_api_key"})
        policies = o.to_policies()
        assert len(policies) == 1
        assert policies[0].priority == 5
        assert "run_bash" in policies[0].denied_tools

    def test_org_mode_wildcard(self):
        o = OrgPolicy(org_id="test", denied_tools={"foo"})
        pol = o.to_policies()[0]
        assert pol.mode == "*"


# ---------------------------------------------------------------------------
# build_6layer_chain
# ---------------------------------------------------------------------------


class TestBuild6LayerChain:
    def test_empty_chain(self):
        chain = build_6layer_chain()
        assert isinstance(chain, PolicyChain)

    def test_with_profile(self):
        profile = ProfilePolicy(user_id="dev", allow_expensive=False)
        chain = build_6layer_chain(profile=profile)
        assert len(chain._policies) > 0

    def test_with_org(self):
        org = OrgPolicy(org_id="team", denied_tools={"run_bash"})
        chain = build_6layer_chain(org=org)
        assert len(chain._policies) == 1

    def test_with_mode_policies(self):
        mode_pol = ToolPolicy(
            name="mode:dry_run",
            mode="dry_run",
            priority=100,
            denied_tools={"analyze_ip"},
        )
        chain = build_6layer_chain(mode_policies=[mode_pol])
        assert len(chain._policies) == 1

    def test_full_6layer(self):
        profile = ProfilePolicy(user_id="dev", allow_dangerous=False)
        org = OrgPolicy(org_id="team", denied_tools={"run_bash"})
        mode_pol = ToolPolicy(
            name="mode:dry_run",
            mode="dry_run",
            priority=100,
            denied_tools={"analyze_ip"},
        )
        chain = build_6layer_chain(
            profile=profile,
            org=org,
            mode_policies=[mode_pol],
        )
        # 1 profile (no_dangerous) + 1 org + 1 mode = 3
        assert len(chain._policies) == 3

    def test_priority_ordering(self):
        """Org (5) > Profile (10) > Mode (100) — lower number = higher priority."""
        profile = ProfilePolicy(user_id="dev", allow_expensive=False)
        org = OrgPolicy(org_id="team", denied_tools={"run_bash"})
        chain = build_6layer_chain(profile=profile, org=org)
        priorities = sorted(p.priority for p in chain._policies)
        assert priorities[0] == 5  # org first
        assert priorities[1] == 10  # profile second


# ---------------------------------------------------------------------------
# File-based loading (integration)
# ---------------------------------------------------------------------------


class TestLoadProfilePolicy:
    def test_no_file_returns_default(self, tmp_path):
        p = load_profile_policy(str(tmp_path / "nonexistent"))
        assert p.allow_expensive
        assert p.allow_write

    def test_valid_toml(self, tmp_path):
        pref = tmp_path / "preferences.toml"
        pref.write_text(
            "[policy]\n"
            "allow_expensive = false\n"
            "allow_write = true\n"
            "allow_dangerous = false\n"
            'denied_tools = ["custom_tool"]\n'
        )
        p = load_profile_policy(str(tmp_path))
        assert not p.allow_expensive
        assert p.allow_write
        assert "custom_tool" in p.denied_tools

    def test_malformed_toml(self, tmp_path):
        pref = tmp_path / "preferences.toml"
        pref.write_text("not valid toml {{{}}")
        p = load_profile_policy(str(tmp_path))
        assert p.allow_expensive  # default fallback


class TestLoadOrgPolicy:
    def test_no_file_returns_default(self, tmp_path):
        o = load_org_policy(str(tmp_path / "nonexistent.toml"))
        assert len(o.denied_tools) == 0

    def test_valid_toml(self, tmp_path):
        config = tmp_path / "config.toml"
        config.write_text('[policy.org]\norg_id = "nexon"\ndenied_tools = ["run_bash"]\n')
        o = load_org_policy(str(config))
        assert o.org_id == "nexon"
        assert "run_bash" in o.denied_tools
