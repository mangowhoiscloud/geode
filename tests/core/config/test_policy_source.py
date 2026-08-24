"""Neutral policy-source selection and reader injection contracts."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import cast

import pytest
from core.agent.agent_contracts_policy import _load_agent_contracts_override
from core.agent.decomposition_policy import _load_decomposition_policy_override
from core.agent.heuristics_policy import _load_heuristics_override
from core.agent.policy_injection.in_context_slots import (
    _load_in_context_slots_override,
)
from core.agent.reflection_policy import _load_reflection_policy_override
from core.agent.style_guide_policy import _load_style_guide_override
from core.agent.tool_descriptions_policy import _load_tool_descriptions_override
from core.agent.tool_policy import _load_tool_policy_override
from core.config.policy_source import (
    EMPTY_POLICY_SOURCES,
    PolicySourcePaths,
    PolicySourceSelection,
    decode_policy_sources,
    encode_policy_sources,
    select_policy_source,
)
from core.llm.cache_policy import _load_cache_policy_override
from core.llm.few_shot_pool import _load_few_shot_pool_override
from core.llm.strategies.provider_routing_policy import _load_provider_routing_override
from core.skills.skill_catalog_policy import _load_skill_catalog_override

_OVERRIDE_ENV = "GEODE_TEST_POLICY_SOURCE_OVERRIDE"
_STRICT_ENV = "GEODE_TEST_POLICY_SOURCE_STRICT"


def _sources(tmp_path: Path) -> PolicySourcePaths:
    return PolicySourcePaths(
        override_env=_OVERRIDE_ENV,
        operator_local=tmp_path / "operator.json",
        packaged_default=tmp_path / "default.json",
    )


def _required(path: Path | None) -> Path:
    assert path is not None
    return path


def test_source_paths_are_frozen(tmp_path: Path) -> None:
    sources = _sources(tmp_path)

    with pytest.raises(FrozenInstanceError):
        sources.__setattr__("override_env", "GEODE_OTHER_OVERRIDE")


def test_selects_operator_before_packaged_default(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    operator_local = _required(sources.operator_local)
    packaged_default = _required(sources.packaged_default)
    operator_local.write_text("{}", encoding="utf-8")
    packaged_default.write_text("{}", encoding="utf-8")

    assert select_policy_source(sources, environ={}) == PolicySourceSelection(
        operator_local,
        strict=False,
    )


def test_environment_override_is_authoritative_and_strict_is_exact(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    _required(sources.operator_local).write_text("{}", encoding="utf-8")
    missing_override = tmp_path / "missing.json"

    selected = select_policy_source(
        sources,
        environ={
            _OVERRIDE_ENV: str(missing_override),
            _STRICT_ENV: "1",
        },
    )

    assert selected == PolicySourceSelection(missing_override, strict=True)


def test_environment_mapping_is_explicit_and_does_not_require_process_mutation(
    tmp_path: Path,
) -> None:
    sources = _sources(tmp_path)
    _required(sources.packaged_default).write_text("{}", encoding="utf-8")

    selected = select_policy_source(
        sources,
        environ={_OVERRIDE_ENV: str(tmp_path / "env.json"), _STRICT_ENV: "true"},
    )

    assert selected == PolicySourceSelection(tmp_path / "env.json", strict=False)


Reader = Callable[..., object | None]

_NEUTRAL_POLICY_READERS: tuple[Reader, ...] = (
    _load_agent_contracts_override,
    _load_decomposition_policy_override,
    _load_heuristics_override,
    _load_reflection_policy_override,
    _load_style_guide_override,
    _load_tool_descriptions_override,
    _load_tool_policy_override,
    _load_cache_policy_override,
    _load_provider_routing_override,
    _load_few_shot_pool_override,
    _load_skill_catalog_override,
)

_POLICY_READERS: tuple[Reader, ...] = (
    *_NEUTRAL_POLICY_READERS,
    _load_in_context_slots_override,
)


@pytest.mark.parametrize("reader", _NEUTRAL_POLICY_READERS)
def test_all_policy_readers_are_neutral_without_product_sources(reader: Reader) -> None:
    assert reader() is None


@pytest.mark.parametrize("reader", _POLICY_READERS)
def test_all_policy_readers_accept_explicit_source_paths(
    reader: Reader,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_OVERRIDE_ENV, raising=False)

    assert reader(sources=_sources(tmp_path)) is None


@pytest.mark.parametrize("reader", _POLICY_READERS)
def test_all_policy_readers_honor_explicit_strict_override_name(
    reader: Reader,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = tmp_path / "missing.json"
    monkeypatch.setenv(_OVERRIDE_ENV, str(missing))
    monkeypatch.setenv(_STRICT_ENV, "1")

    with pytest.raises(RuntimeError, match=_OVERRIDE_ENV):
        reader(sources=_sources(tmp_path))


def test_worker_codec_captures_parent_override_and_strict_mode(tmp_path: Path) -> None:
    override = tmp_path / "worker-policy.json"
    sources = {"test": _sources(tmp_path)}

    encoded = encode_policy_sources(
        sources,
        environ={_OVERRIDE_ENV: str(override), _STRICT_ENV: "1"},
    )
    decoded = decode_policy_sources(encoded)

    assert select_policy_source(decoded["test"], environ={}) == PolicySourceSelection(
        override,
        strict=True,
    )
    with pytest.raises(TypeError):
        cast(MutableMapping[str, PolicySourcePaths], decoded)["other"] = _sources(tmp_path)


def test_worker_request_preserves_none_vs_explicit_empty_policy_sources() -> None:
    from core.agent.worker import WorkerRequest

    inherited = WorkerRequest.from_dict({"task_id": "inherit"})
    explicit_empty = WorkerRequest.from_dict(
        {"task_id": "empty", "policy_sources": encode_policy_sources(EMPTY_POLICY_SOURCES)}
    )

    assert inherited.policy_sources is None
    assert explicit_empty.policy_sources == {}


def test_legacy_policy_loader_signature_delegates_to_neutral_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.agent.policy_sot import load_policy_sot

    packaged = tmp_path / "policy.json"
    packaged.write_text('{"value": 3}', encoding="utf-8")
    monkeypatch.delenv(_OVERRIDE_ENV, raising=False)

    result = load_policy_sot(
        env_var=_OVERRIDE_ENV,
        operator_local=tmp_path / "operator.json",
        in_repo=packaged,
        label="test",
        validate_strict=lambda _data, _path: None,
        validate_graceful=lambda _data, _path: None,
        coerce=lambda data: data["value"],
    )

    assert result == 3
