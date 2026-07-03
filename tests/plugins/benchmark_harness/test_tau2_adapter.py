from plugins.benchmark_harness.tau2_geode_agent import _agent_system_prompt


def test_tau2_agent_prompt_blocks_inferred_optional_tool_args() -> None:
    prompt = _agent_system_prompt("Policy body")

    assert "leave optional arguments unset" in prompt
    assert "unless the user, the policy, or a prior tool result explicitly supplied" in prompt
    assert "Do not add inferred descriptions" in prompt
    assert "Policy body" in prompt
