from __future__ import annotations

import asyncio
import hashlib
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from evals.platforms.harbor_runtime import (
    GeodeRuntimeHarborAgent,
    _run_native,
    _stop_runtime,
    _summarize_usage,
    _verify_bundle,
)


def test_source_bundle_rejects_mismatch_traversal_and_links(tmp_path: Path) -> None:
    path = tmp_path / "source.tar.gz"
    for unsafe in (None, "../escape", "/absolute", "linked"):
        with tarfile.open(path, "w:gz") as archive:
            for name in ("pyproject.toml", "uv.lock", "core/wiring/runtime.py"):
                item = tarfile.TarInfo(name)
                item.size = 1
                archive.addfile(item, io.BytesIO(b"x"))
            if unsafe:
                item = tarfile.TarInfo(unsafe)
                if unsafe == "linked":
                    item.type = tarfile.SYMTYPE
                    item.linkname = "outside"
                archive.addfile(item)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if unsafe:
            with pytest.raises(ValueError, match="unsafe"):
                _verify_bundle(path, digest)
        else:
            _verify_bundle(path, digest)
        with pytest.raises(ValueError, match="mismatch"):
            _verify_bundle(path, "0" * 64)


def test_usage_projects_partial_evidence_without_fabricating_totals() -> None:
    def event(cache: int | None, call: str) -> SimpleNamespace:
        return SimpleNamespace(
            action="llm.call.ended",
            llm_call_id=call,
            llm_attempt_id=call + ":attempt-1",
            payload={
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "cached_input_tokens": cache,
                    "cache_write_tokens": None,
                },
            },
        )

    def paired(*calls: SimpleNamespace) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(action="llm.call.started", llm_attempt_id=c.llm_attempt_id)
            for c in calls
        ] + list(calls)

    result = _summarize_usage(paired(event(0, "a"), event(4, "b")))
    assert result["input_tokens"] == 20
    assert result["cached_input_tokens"] == 4
    assert result["cached_input_tokens_missing_events"] == 0
    assert result["whole_runtime_complete"] is False
    partial = _summarize_usage(paired(event(None, "a"), event(4, "b")))
    assert partial["cached_input_tokens"] is None
    assert partial["cached_input_tokens_observed_sum"] == 4
    assert partial["cached_input_tokens_missing_events"] == 1
    assert partial["cache_write_tokens"] is None
    assert _summarize_usage([])["input_tokens"] is None
    failed = SimpleNamespace(
        action="llm.call.ended",
        llm_attempt_id="c:attempt-1",
        payload={"error_type": "TimeoutError"},
    )
    assert _summarize_usage(paired(event(4, "a"), failed))["input_tokens"] is None
    unclosed = [
        *paired(event(4, "a")),
        SimpleNamespace(action="llm.call.started", llm_attempt_id="open:attempt-1"),
    ]
    assert _summarize_usage(unclosed)["cached_input_tokens"] is None
    assert _summarize_usage(paired(event(4, "a"), event(4, "a")))["input_tokens"] is None


def test_runtime_entry_refuses_host_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_HOME", "/not-a-harbor-runtime")
    with pytest.raises(RuntimeError, match="container-local"):
        asyncio.run(_run_native(SimpleNamespace()))


def test_post_run_context_keeps_missing_cache_and_no_subscription_price(tmp_path: Path) -> None:
    agent = object.__new__(GeodeRuntimeHarborAgent)
    agent.logs_dir = tmp_path
    context = SimpleNamespace(n_cache_tokens="uninitialized")
    agent.populate_context_post_run(context)
    assert context.n_cache_tokens == "uninitialized"
    payload = {
        "usage": {"input_tokens": 10, "output_tokens": 2, "cached_input_tokens": None},
        "metadata": {"termination_reason": "done"},
    }
    (tmp_path / "runtime-result.json").write_text(json.dumps(payload))
    agent.populate_context_post_run(context)
    assert context.n_input_tokens is None
    assert context.n_cache_tokens is None
    assert context.cost_usd is None


def test_stop_runtime_waits_for_shutdown_receipt_and_fails_closed() -> None:
    environment = SimpleNamespace(exec=AsyncMock(return_value=SimpleNamespace(return_code=0)))
    asyncio.run(_stop_runtime(environment))
    command = environment.exec.call_args.kwargs["command"]
    assert "runtime-finalized.json" in command
    assert "SIGTERM" in command
    assert "deadline" in command
    environment.exec.return_value.return_code = 1
    with pytest.raises(RuntimeError, match="shutdown/export incomplete"):
        asyncio.run(_stop_runtime(environment))


def test_runtime_config_pins_role_models_and_absolute_policy(tmp_path: Path) -> None:
    import tomllib

    agent = object.__new__(GeodeRuntimeHarborAgent)
    agent.logs_dir = tmp_path
    agent.model_name = "gpt-5.6-sol"
    agent.effort = "max"
    agent.source = "subscription"
    agent.source_revision = "a" * 40
    agent.source_sha256 = "b" * 64
    agent.agent_timeout_sec = 900
    agent.render_instruction = lambda instruction: instruction
    agent.exec_as_agent = AsyncMock()
    environment = SimpleNamespace(upload_file=AsyncMock())
    asyncio.run(agent.run("Solve the task.", environment, SimpleNamespace()))
    config = tomllib.loads((tmp_path / "runtime-config.toml").read_text())
    assert config["llm"]["model_policy_path"] == "/installed-agent/geode/model-policy.toml"
    assert config["llm"]["primary_model"] == "gpt-5.6-sol"
    assert config["llm"]["openai_credential_source"] == "openai-codex"
    assert config["llm"]["anthropic_credential_source"] == "none"
    policy = tomllib.loads((tmp_path / "model-policy.toml").read_text())
    assert policy == {"policy": {"allowlist": ["gpt-5.6-sol"]}}
    assert config["agentic"]["effort"] == "max"


def test_installed_agent_uses_harbor_lifecycle_and_classifies_timeout(tmp_path: Path) -> None:
    import importlib.metadata

    path = tmp_path / "source.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name in ("pyproject.toml", "uv.lock", "core/wiring/runtime.py"):
            item = tarfile.TarInfo(name)
            archive.addfile(item)
    kwargs = {
        "logs_dir": tmp_path / "logs",
        "model_name": "gpt-5.6-sol",
        "source_bundle": str(path),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_revision": "a" * 40,
        "agent_timeout_sec": 900,
    }
    try:
        harbor_version = importlib.metadata.version("harbor")
    except importlib.metadata.PackageNotFoundError:
        harbor_version = None
    if harbor_version != "0.22.0":
        with pytest.raises(RuntimeError, match=r"harbor==0\.22\.0"):
            GeodeRuntimeHarborAgent(**kwargs)
        return
    from harbor.agents.installed.base import BaseInstalledAgent, NonZeroAgentExitCodeError
    from harbor.trial.errors import AgentTimeoutError

    agent = GeodeRuntimeHarborAgent(**kwargs)
    assert isinstance(agent, BaseInstalledAgent)
    assert GeodeRuntimeHarborAgent.setup is BaseInstalledAgent.setup
    assert agent.SUPPORTS_ATIF
    assert isinstance(
        agent._classify_exec_error(
            "/venv/bin/python -m evals.platforms.harbor_runtime --timeout 900",
            SimpleNamespace(return_code=124),
        ),
        AgentTimeoutError,
    )
    assert isinstance(
        agent._classify_exec_error(
            "python -m other_module", SimpleNamespace(return_code=1, stdout="", stderr="")
        ),
        NonZeroAgentExitCodeError,
    )
