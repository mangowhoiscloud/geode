from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from scripts.probes.probe_effort_surface import (
    _acomplete_with_runtime_retry,
    _wire_effort,
    visible_effort_surface,
)


@pytest.mark.parametrize("source", ["subscription", "payg"])
def test_visible_effort_surface_matches_picker(
    monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    from core.cli.commands._state import get_model_profiles
    from core.cli.effort_picker import supported_efforts

    monkeypatch.setattr("core.cli.commands._state._selected_openai_source", lambda model="": source)
    surface = visible_effort_surface()

    assert surface
    assert len(surface) == len(set(surface))
    assert surface == tuple(
        (profile.id, profile.provider, effort)
        for profile in get_model_profiles(openai_source=source)
        for effort in supported_efforts(profile.id, profile.provider)
    )
    retired_subscription_ids = {"gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex"}
    surface_models = {model for model, _, _ in surface}
    if source == "subscription":
        assert retired_subscription_ids.isdisjoint(surface_models)
    else:
        assert retired_subscription_ids <= surface_models
    assert ("gpt-6-astra", "openai", "low") in surface
    assert ("gpt-6-astra", "openai", "max") in surface
    assert ("gpt-5.6-sol", "openai", "max") in surface
    assert ("claude-fable-5", "anthropic", "xhigh") in surface


def test_visible_effort_surface_honors_explicit_model_order() -> None:
    surface = visible_effort_surface(("gpt-5.6-luna", "gpt-5.6-sol"))

    assert len(surface) == 12
    assert [model for model, _, _ in surface[:6]] == ["gpt-5.6-luna"] * 6
    assert [model for model, _, _ in surface[6:]] == ["gpt-5.6-sol"] * 6


def test_measurement_retries_pre_response_transient_once() -> None:
    class FlakyAdapter:
        calls = 0

        async def acomplete(self, request: object) -> object:
            del request
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("servers are currently overloaded")
            return SimpleNamespace(text="EFFORT_OK")

    adapter = FlakyAdapter()
    history: list[dict[str, object]] = []
    with patch("core.llm.fallback.asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            _acomplete_with_runtime_retry(
                adapter,
                SimpleNamespace(model="gpt-5.6-sol"),
                timeout_s=1,
                retry_history=history,
            )
        )

    assert result.text == "EFFORT_OK"
    assert adapter.calls == 2
    assert history[0]["error_category"] == "unknown"


@pytest.mark.parametrize(("model", "effort"), [("glm-5.3", "high"), ("glm-5.2", "none")])
def test_glm_probe_uses_native_reasoning_contract(model: str, effort: str) -> None:
    from core.llm.adapters.base import AdapterCallRequest

    request = AdapterCallRequest(model=model, messages=(), effort=effort)
    assert _wire_effort(request, "glm", "payg") == effort


@pytest.mark.parametrize("configured", [False, True])
def test_visible_effort_surface_includes_selected_openrouter(
    monkeypatch: pytest.MonkeyPatch, configured: bool
) -> None:
    monkeypatch.setattr("core.cli.commands._state._selected_openai_source", lambda model="": "payg")
    model = "openrouter/openai/gpt-6-sol"
    surface = (
        visible_effort_surface(configured_model_ids=(model,))
        if configured
        else visible_effort_surface((model,))
    )
    assert (model, "openrouter", "low") in surface
    assert (model, "openrouter", "max") in surface
    if not configured:
        assert all(row[0] == model for row in surface)


def test_visible_effort_surface_does_not_invent_unknown_support() -> None:
    with pytest.raises(ValueError, match="no exposed effort surface"):
        visible_effort_surface(("openrouter/openai/unknown-model",))


@pytest.mark.parametrize(
    "field",
    [
        "provider",
        "adapter",
        "adapter_source",
        "model",
        "requested_effort",
        "producer_revision",
    ],
)
def test_resume_identity_includes_route_source_and_revision(tmp_path: Path, field: str) -> None:
    import json

    from scripts.probes.probe_effort_surface import (
        SCHEMA,
        _measurement_key,
        _passed_keys,
    )

    row = {
        "schema": SCHEMA,
        "provider": "openai",
        "adapter": "codex-oauth",
        "adapter_source": "subscription",
        "adapter_base_url": "https://chatgpt.com/backend-api/codex",
        "model": "gpt-6-sol",
        "requested_effort": "low",
        "wire_effort": "low",
        "producer_revision": "a" * 40,
        "status": "pass",
    }
    output = tmp_path / "measurements.jsonl"
    original = json.dumps(row) + "\n"
    output.write_text(original)
    assert _measurement_key(row) in _passed_keys(output)
    assert _measurement_key({**row, field: "different"}) not in _passed_keys(output)
    assert output.read_text() == original


def test_legacy_or_incomplete_pass_is_preserved_but_not_reused(tmp_path: Path) -> None:
    import json

    from scripts.probes.probe_effort_surface import SCHEMA, _passed_keys

    rows = [
        {"model": "gpt-6-sol", "requested_effort": "low", "status": "pass"},
        {
            "schema": SCHEMA,
            "provider": "openai",
            "adapter": "openai-payg",
            "adapter_source": "payg",
            "model": "gpt-6-sol",
            "requested_effort": "low",
            "wire_effort": "high",
            "producer_revision": "a" * 40,
            "status": "pass",
        },
    ]
    output = tmp_path / "measurements.jsonl"
    original = "".join(json.dumps(row) + "\n" for row in rows)
    output.write_text(original)
    assert not _passed_keys(output)
    assert output.read_text() == original


@pytest.mark.parametrize(("source", "revision"), [("payg", "a" * 40), ("subscription", "b" * 40)])
@pytest.mark.parametrize(
    ("tokens", "present", "expected"), [(0, False, None), (0, True, 0), (7, True, 7)]
)
def test_measure_does_not_skip_another_source_or_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    revision: str,
    tokens: int,
    present: bool,
    expected: int | None,
) -> None:
    import json

    from core.llm.adapters.base import UsageSummary
    from scripts.probes import probe_effort_surface as probe

    adapter = SimpleNamespace(
        name="codex-oauth" if source == "subscription" else "openai-payg", source=source
    )
    result = SimpleNamespace(
        text="EFFORT_OK",
        tool_uses=[],
        stop_reason="end_turn",
        usage=UsageSummary(
            input_tokens=1,
            output_tokens=1,
            reasoning_tokens=tokens,
            reasoning_tokens_present=present,
        ),
        raw_response=None,
        reasoning_items=(),
        reasoning_summaries=(),
    )
    call = AsyncMock(return_value=result)
    monkeypatch.setattr(probe, "_require_producer_revision", lambda revision: None)
    monkeypatch.setattr(
        probe,
        "visible_effort_surface",
        lambda *a, **k: (("gpt-6-sol", "openai", "low"),),
    )
    monkeypatch.setattr(probe, "_wire_effort", lambda *a: "low")
    monkeypatch.setattr(
        probe, "_adapter_base_url", lambda *a: "https://chatgpt.com/backend-api/codex"
    )
    monkeypatch.setattr(probe, "_acomplete_with_runtime_retry", call)
    monkeypatch.setattr("core.cli.commands.model._current_model_for_role", lambda role: "")
    monkeypatch.setattr("core.llm.adapters.registry.bootstrap_builtins", lambda: None)
    monkeypatch.setattr("core.llm.adapters.registry.resolve_for", lambda *a: adapter)
    monkeypatch.setattr("core.llm.routing.infer_source", lambda provider, **kwargs: source)
    output = tmp_path / "measurements.jsonl"
    prior = {
        "schema": probe.SCHEMA,
        "provider": "openai",
        "adapter": "codex-oauth",
        "adapter_source": "subscription",
        "adapter_base_url": "https://chatgpt.com/backend-api/codex",
        "model": "gpt-6-sol",
        "requested_effort": "low",
        "wire_effort": "low",
        "producer_revision": "a" * 40,
        "status": "pass",
    }
    original = json.dumps(prior) + "\n"
    output.write_text(original)
    assert asyncio.run(probe.measure(output, timeout_s=1, producer_revision=revision)) == 0
    call.assert_awaited_once()
    assert output.read_text().startswith(original)
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 2
    assert rows[1]["adapter_source"] == source
    assert rows[1]["producer_revision"] == revision
    assert rows[1]["reasoning_tokens"] == expected
    assert asyncio.run(probe.measure(output, timeout_s=1, producer_revision=revision)) == 0
    call.assert_awaited_once()
    assert len(output.read_text().splitlines()) == 2


@pytest.mark.parametrize("drop_effort", [False, True])
def test_openrouter_probe_observes_adapter_sdk_body(
    monkeypatch: pytest.MonkeyPatch, drop_effort: bool
) -> None:
    from core.llm.adapters.base import AdapterCallRequest, Message
    from core.llm.adapters.openrouter_payg import OpenRouterPaygAdapter
    from scripts.probes.probe_effort_surface import _openrouter_wire_effort

    adapter = OpenRouterPaygAdapter()
    request = AdapterCallRequest(
        model="openrouter/openai/gpt-6-sol",
        messages=(Message(role="user", content="fixture"),),
        effort="low",
    )
    if drop_effort:
        monkeypatch.setattr("core.llm.adapters.openrouter_payg.openai_effort_kwargs", lambda *a: {})
    with patch.object(
        adapter, "_get_client", side_effect=AssertionError("credential lookup")
    ) as getter:
        with patch(
            "core.llm.adapters._openai_common.build_responses_kwargs",
            side_effect=AssertionError("wrong Responses serializer"),
        ):
            assert asyncio.run(_openrouter_wire_effort(request, adapter)) == (
                None if drop_effort else "low"
            )
        assert adapter._get_client is getter
        getter.assert_not_called()


@pytest.mark.parametrize(
    ("provider", "source"),
    [
        ("unknown", "payg"),
        ("anthropic", "subscription"),
        ("openai", "adapter"),
        ("openrouter", "payg"),
    ],
)
def test_unknown_wire_oracle_fails_closed(provider: str, source: str) -> None:
    with pytest.raises(ValueError, match="no wire effort oracle"):
        _wire_effort(SimpleNamespace(effort="low"), provider, source)


def test_producer_revision_requires_matching_clean_checkout() -> None:
    import subprocess

    from scripts.probes.probe_effort_surface import _require_producer_revision

    with (
        patch(
            "scripts.probes.probe_effort_surface.subprocess.check_output",
            return_value="a" * 40,
        ),
        patch("scripts.probes.probe_effort_surface.subprocess.run") as check,
    ):
        _require_producer_revision("a" * 40)
        check.assert_called_once()
        with pytest.raises(ValueError, match="does not match"):
            _require_producer_revision("b" * 40)
        with pytest.raises(ValueError, match="full commit SHA"):
            _require_producer_revision("HEAD")
        check.side_effect = subprocess.CalledProcessError(1, "git diff")
        with pytest.raises(subprocess.CalledProcessError):
            _require_producer_revision("a" * 40)


@pytest.mark.parametrize(
    "endpoint",
    ["https://one.invalid/v1", "https://two.invalid/v1", "https://one.invalid/other"],
)
def test_endpoint_override_changes_resume_identity(monkeypatch, endpoint: str) -> None:
    from scripts.probes.probe_effort_surface import _adapter_base_url

    monkeypatch.setenv("OPENAI_BASE_URL", endpoint + "/")
    adapter = SimpleNamespace(name="openai-payg")
    assert _adapter_base_url(adapter) == endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:password@host.invalid/v1",
        "https://host.invalid/v1?key=secret",
        "https://host.invalid/v1#fragment",
        "file:///tmp/file",
    ],
)
def test_sensitive_or_unknown_endpoint_is_not_recorded(monkeypatch, endpoint: str) -> None:
    from scripts.probes.probe_effort_surface import _adapter_base_url

    monkeypatch.setenv("OPENAI_BASE_URL", endpoint)
    with pytest.raises(ValueError, match="without credentials/query/fragment") as exc:
        _adapter_base_url(SimpleNamespace(name="openai-payg"))
    assert endpoint not in str(exc.value)
    with pytest.raises(ValueError, match="no endpoint oracle"):
        _adapter_base_url(SimpleNamespace(name="custom-adapter"))


def test_profile_owned_endpoint_cannot_resume_without_credential_read() -> None:
    from scripts.probes.probe_effort_surface import (
        SCHEMA,
        _adapter_base_url,
        _measurement_key,
    )

    with patch(
        "core.llm.adapters.glm_coding_plan._resolve_coding_plan_endpoint",
        side_effect=AssertionError("profile read"),
    ) as resolve:
        assert _adapter_base_url(SimpleNamespace(name="glm-coding-plan")) is None
        resolve.assert_not_called()
    assert (
        _measurement_key(
            {
                "schema": SCHEMA,
                "provider": "glm",
                "adapter": "glm-coding-plan",
                "adapter_source": "subscription",
                "adapter_base_url": None,
                "model": "glm-5.3",
                "requested_effort": "low",
                "producer_revision": "a" * 40,
            }
        )
        is None
    )


@pytest.mark.parametrize("adapter", ["openai-payg", "anthropic-payg", "openrouter-payg"])
def test_missing_provider_contract_fails_before_endpoint_read(monkeypatch, adapter: str) -> None:
    from scripts.probes.probe_effort_surface import _adapter_base_url

    monkeypatch.setattr("core.llm.registry.get_provider_spec", lambda provider: None)
    with pytest.raises(ValueError, match="provider contract is missing"):
        _adapter_base_url(SimpleNamespace(name=adapter))
