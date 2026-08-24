"""ADR-013 T5 — Cache breakpoint policy JSON mutation surface invariants.

5-element 패턴:
- SoT: cache-policy.json
- Sources: explicit override + operator-local + packaged candidates
- Reader: core/llm/cache_policy.py
- Entry: product request middleware → Anthropic ``provider_options``
- Env: GEODE_CACHE_POLICY_OVERRIDE + GEODE_CACHE_POLICY_STRICT
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from core.agent.policy_injection.in_context_wiring import (
    register_in_context_middleware,
)
from core.config.policy_source import PolicySourcePaths
from core.hooks import LlmCallRequest, MiddlewareRegistry
from core.llm.adapters._anthropic_common import build_create_kwargs, build_stream_kwargs
from core.llm.adapters.base import AdapterCallRequest, Message
from core.llm.cache_policy import (
    _load_cache_policy_override,
    apply_cache_policy_breakpoints,
)


@pytest.fixture
def isolated_sot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    sot = tmp_path / "cache-policy.json"
    monkeypatch.delenv("GEODE_CACHE_POLICY_OVERRIDE", raising=False)
    monkeypatch.delenv("GEODE_CACHE_POLICY_STRICT", raising=False)
    yield sot


def _sources(sot: Path) -> PolicySourcePaths:
    return PolicySourcePaths(
        "GEODE_CACHE_POLICY_OVERRIDE",
        sot.parent / "operator-local-cache-policy.json",
        sot,
    )


def _write(sot: Path, payload: dict[str, Any]) -> None:
    sot.write_text(json.dumps(payload), encoding="utf-8")


# Reader ----------------------------------------------------------------------


def test_load_returns_none_when_sot_missing(isolated_sot: Path) -> None:
    assert _load_cache_policy_override(sources=_sources(isolated_sot)) is None


def test_load_returns_none_when_unreadable(isolated_sot: Path) -> None:
    isolated_sot.write_text("bad json {", encoding="utf-8")
    assert _load_cache_policy_override(sources=_sources(isolated_sot)) is None


def test_load_returns_none_when_value_not_int(isolated_sot: Path) -> None:
    _write(isolated_sot, {"messages_breakpoints": "three"})
    assert _load_cache_policy_override(sources=_sources(isolated_sot)) is None


def test_load_rejects_bool_as_int(isolated_sot: Path) -> None:
    """Python bool is int subclass — _validate_schema rejects bool explicitly."""
    _write(isolated_sot, {"messages_breakpoints": True})
    assert _load_cache_policy_override(sources=_sources(isolated_sot)) is None


def test_load_valid_payload_each_value(isolated_sot: Path) -> None:
    for n in (0, 1, 2, 3):
        _write(isolated_sot, {"messages_breakpoints": n})
        assert _load_cache_policy_override(sources=_sources(isolated_sot)) == {
            "messages_breakpoints": n
        }


def test_load_out_of_range_value_dropped(isolated_sot: Path) -> None:
    """Out-of-range (4, -1) → per-axis graceful drop (returns empty dict)."""
    _write(isolated_sot, {"messages_breakpoints": 4})
    assert _load_cache_policy_override(sources=_sources(isolated_sot)) == {}
    _write(isolated_sot, {"messages_breakpoints": -1})
    assert _load_cache_policy_override(sources=_sources(isolated_sot)) == {}


def test_load_unknown_field_dropped(isolated_sot: Path) -> None:
    """Forward-compat — unknown field 자동 drop."""
    _write(isolated_sot, {"messages_breakpoints": 2, "future_field": "x"})
    assert _load_cache_policy_override(sources=_sources(isolated_sot)) == {
        "messages_breakpoints": 2
    }


def test_strict_env_var_raises_on_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_CACHE_POLICY_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.setenv("GEODE_CACHE_POLICY_STRICT", "1")
    with pytest.raises(RuntimeError, match="GEODE_CACHE_POLICY_OVERRIDE"):
        _load_cache_policy_override(sources=_sources(tmp_path / "cache-policy.json"))


def test_env_var_without_strict_is_graceful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEODE_CACHE_POLICY_OVERRIDE", str(tmp_path / "nope.json"))
    monkeypatch.delenv("GEODE_CACHE_POLICY_STRICT", raising=False)
    assert _load_cache_policy_override(sources=_sources(tmp_path / "cache-policy.json")) is None


def test_operator_local_layer_priority(isolated_sot: Path) -> None:
    operator_local = isolated_sot.parent / "operator-local-cache-policy.json"
    operator_local.write_text(json.dumps({"messages_breakpoints": 1}), encoding="utf-8")
    _write(isolated_sot, {"messages_breakpoints": 3})
    assert _load_cache_policy_override(sources=_sources(isolated_sot)) == {
        "messages_breakpoints": 1
    }


# Apply -----------------------------------------------------------------------


def test_apply_none_returns_default() -> None:
    assert apply_cache_policy_breakpoints(3, None) == 3


def test_apply_empty_dict_returns_default() -> None:
    assert apply_cache_policy_breakpoints(3, {}) == 3


def test_apply_override_returns_policy_value() -> None:
    assert apply_cache_policy_breakpoints(3, {"messages_breakpoints": 1}) == 1


def test_apply_override_zero_returns_zero() -> None:
    """0 is a valid override (disables messages caching entirely)."""
    assert apply_cache_policy_breakpoints(3, {"messages_breakpoints": 0}) == 0


def test_apply_with_different_defaults() -> None:
    assert apply_cache_policy_breakpoints(0, None) == 0
    assert apply_cache_policy_breakpoints(2, None) == 2


# Wiring ----------------------------------------------------------------------


def test_active_policy_reaches_create_and_stream_wire(isolated_sot: Path) -> None:
    _write(isolated_sot, {"messages_breakpoints": 1})
    registry = MiddlewareRegistry()
    register_in_context_middleware(
        registry,
        policy_sources={"cache_policy": _sources(isolated_sot)},
    )
    request = AdapterCallRequest(
        model="claude-sonnet-5",
        system_prompt="system",
        messages=(
            Message(role="user", content="first"),
            Message(role="assistant", content="answer"),
            Message(role="user", content="latest"),
        ),
    )
    transformed = asyncio.run(
        registry.llm_request(
            LlmCallRequest(
                adapter=SimpleNamespace(name="anthropic-payg"),
                request=request,
            )
        )
    ).request

    create = build_create_kwargs(transformed)
    stream = build_stream_kwargs(transformed)
    assert create["messages"] == stream["messages"]
    assert transformed.provider_options["cache_message_breakpoints"] == 1
    marked = [
        block
        for message in create["messages"]
        for block in (message["content"] if isinstance(message["content"], list) else [])
        if block.get("cache_control") == {"type": "ephemeral"}
    ]
    assert len(marked) == 1


# Path constants --------------------------------------------------------------


def test_product_source_candidates_present() -> None:
    from core.config.runtime_policy_sources import build_policy_source_bundle

    sources = build_policy_source_bundle()["cache_policy"]
    assert sources.packaged_default is not None
    assert sources.operator_local is not None
    assert sources.packaged_default.name == "cache-policy.json"
    assert sources.operator_local.name == "cache-policy.json"
    assert "policies" in str(sources.packaged_default)
    assert "autoresearch/handoff" in str(sources.operator_local)


# Env wiring in train.py ------------------------------------------------------


def test_train_py_sets_cache_policy_env_pair() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    src = (repo_root / "evolve/scaffold_search/measure.py").read_text(encoding="utf-8")
    assert "GEODE_CACHE_POLICY_OVERRIDE" in src
    assert "GEODE_CACHE_POLICY_STRICT" in src
    assert "AUTORESEARCH_CACHE_POLICY_PATH" in src


# ALIVE marker ----------------------------------------------------------------


def test_cache_policy_json_referenced_in_inference_path() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    composition = (repo_root / "core/config/runtime_policy_sources.py").read_text(encoding="utf-8")
    assert '"cache_policy"' in composition
    assert "AUTORESEARCH_CACHE_POLICY_PATH" in composition
