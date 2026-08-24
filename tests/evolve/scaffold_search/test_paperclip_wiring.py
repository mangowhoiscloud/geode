"""Mutator source dispatch and TOML wiring invariants.

Pins:
- ``_default_llm_call`` dispatches API-key and OpenAI OAuth sources.
- ``splice_toml_section`` (``core.config.toml_edit``) updates an existing
  TOML section in place, appends a fresh section when missing, and replaces
  a single key while preserving the rest of the section.
- ``_cmd_source_set`` rejects invalid sources / unknown keys without
  touching the config file.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# runner dispatch -----------------------------------------------------------


def _stub_adapter_call_result(
    text: str, *, input_tokens: int = 1, output_tokens: int = 1
) -> object:
    """Build a minimal :class:`AdapterCallResult` for the mutator runner tests.

    Step J-b.2 — the runner now consumes
    :class:`core.llm.adapters.base.AdapterCallResult` directly (no
    intermediate AgenticResponse), so dispatch tests build the typed
    dataclass instead of a generic ``MagicMock`` with ``.content`` /
    ``.text`` blocks.
    """
    from core.llm.adapters.base import AdapterCallResult, UsageSummary

    return AdapterCallResult(
        text=text,
        usage=UsageSummary(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason="end_turn",
    )


def test_default_llm_call_rejects_retired_claude_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    from evolve.scaffold_search.loop.mutate import runner

    cfg_mock = MagicMock()
    cfg_mock.autoresearch.mutator.default_model = "claude-opus-4-7"
    cfg_mock.autoresearch.mutator.source = "claude-cli"
    cfg_mock.autoresearch.mutator.max_tokens = 1024
    monkeypatch.setattr(
        "evals.config.load_self_improving_loop_config",
        lambda: cfg_mock,
    )
    monkeypatch.setattr("core.config._resolve_provider", lambda m: "anthropic")

    with pytest.raises(RuntimeError, match="integration is retired"):
        runner._default_llm_call("SYS", "USR")


@pytest.mark.parametrize(
    ("configured_source", "expected_source", "adapter_name"),
    [
        ("api_key", "payg", "openai-payg"),
        ("openai-codex", "subscription", "codex-oauth"),
    ],
)
def test_default_llm_call_routes_openai_sources(
    monkeypatch: pytest.MonkeyPatch,
    configured_source: str,
    expected_source: str,
    adapter_name: str,
) -> None:
    """OpenAI uses one provider family with explicit PAYG/subscription sources.

    ``_resolve_provider("gpt-5.x")`` returns the legacy
    ``"openai-codex"`` provider key, but the Path-B registry only
    knows ``"openai"``. ``_normalize_provider_for_registry`` collapses
    the legacy key so the API path resolves to ``openai-payg`` instead
    of erroring with ``AdapterNotFoundError``.
    """
    from evolve.scaffold_search.loop.mutate import runner

    cfg_mock = MagicMock()
    cfg_mock.autoresearch.mutator.default_model = "gpt-5.5"
    cfg_mock.autoresearch.mutator.source = configured_source
    cfg_mock.autoresearch.mutator.max_tokens = 1024
    monkeypatch.setattr(
        "evals.config.load_self_improving_loop_config",
        lambda: cfg_mock,
    )
    monkeypatch.setattr("core.config._resolve_provider", lambda m: "openai-codex")
    # PR-SOURCE-ROUTING (2026-05-28) — runner now consults
    # :func:`core.llm.adapters._source_inference.infer_source` instead of
    # hard-coding ``"payg"``. Pin the test to the historical API-path
    # default by stubbing the inference helper; the live behaviour
    # (settings + ProfileStore promotion) is covered by
    # ``tests/core/llm/test_source_routing_regression.py``.
    monkeypatch.setattr("core.llm.adapters._source_inference.infer_source", lambda _p: "payg")

    captured: dict[str, object] = {"provider": None, "source": None}

    def _capture_resolve(provider: str, source: str) -> MagicMock:
        captured["provider"] = provider
        captured["source"] = source
        stub = MagicMock()
        stub.name = adapter_name

        async def _acomplete(req: object) -> object:
            return _stub_adapter_call_result(f"from {adapter_name}")

        stub.acomplete = _acomplete
        return stub

    monkeypatch.setattr("core.llm.adapters.resolve_for", _capture_resolve)

    async def _fake_failover(
        models: list[str], do_call: Callable[[str], Awaitable[object]], **kwargs: object
    ) -> tuple[object, str]:
        result_obj = await do_call(models[0])
        return (result_obj, models[0])

    monkeypatch.setattr("core.llm.router.call_with_failover", _fake_failover)

    result = runner._default_llm_call("SYS", "USR")
    assert result == f"from {adapter_name}"
    # Provider normalisation: ``openai-codex`` (legacy key) → ``openai``
    # (Path-B registry key). Source resolved via stubbed ``infer_source``
    # returning the API-path default.
    assert captured == {"provider": "openai", "source": expected_source}


def test_normalize_provider_for_registry_passes_through_known_keys() -> None:
    """Non-codex provider keys pass through ``normalize_registry_provider``
    unchanged so the helper is conservative. PR-DRIFT-ANCHORS — the
    runner's local copy was replaced by the shared anchor."""
    from core.llm.adapters.registry import normalize_registry_provider

    assert normalize_registry_provider("anthropic") == "anthropic"
    assert normalize_registry_provider("openai") == "openai"
    assert normalize_registry_provider("glm") == "glm"
    # Legacy Codex provider key collapses to the Path-B registry key.
    assert normalize_registry_provider("openai-codex") == "openai"


def test_default_llm_call_api_key_path_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """source=api_key routes to the PAYG adapter via resolve_for.

    Step J-b.2 — the API path is the migrated branch: legacy
    ``resolve_agentic_adapter(provider).agentic_call(...)`` →
    ``resolve_for(provider, "payg").acomplete(req)``.
    """
    from evolve.scaffold_search.loop.mutate import runner

    cfg_mock = MagicMock()
    cfg_mock.autoresearch.mutator.default_model = "claude-opus-4-7"
    cfg_mock.autoresearch.mutator.source = "api_key"
    cfg_mock.autoresearch.mutator.max_tokens = 1024
    monkeypatch.setattr(
        "evals.config.load_self_improving_loop_config",
        lambda: cfg_mock,
    )
    monkeypatch.setattr("core.config._resolve_provider", lambda m: "anthropic")

    captured: dict[str, object] = {"provider": None, "source": None}

    def _capture_resolve(provider: str, source: str) -> MagicMock:
        captured["provider"] = provider
        captured["source"] = source
        stub = MagicMock()
        stub.name = "anthropic-payg"

        async def _acomplete(req: object) -> object:
            return _stub_adapter_call_result("from api")

        stub.acomplete = _acomplete
        return stub

    monkeypatch.setattr("core.llm.adapters.resolve_for", _capture_resolve)

    async def _fake_failover(
        models: list[str], do_call: Callable[[str], Awaitable[object]], **kwargs: object
    ) -> tuple[object, str]:
        result_obj = await do_call(models[0])
        return (result_obj, models[0])

    monkeypatch.setattr("core.llm.router.call_with_failover", _fake_failover)

    result = runner._default_llm_call("SYS", "USR")
    assert result == "from api"
    # ``api_key`` source → registry pair ``(<provider>, payg)``.
    assert captured == {"provider": "anthropic", "source": "payg"}


# TOML splicer --------------------------------------------------------------


def test_splice_section_appends_when_missing() -> None:
    from core.config.toml_edit import splice_toml_section

    out = splice_toml_section(
        "[other]\nfoo = 1\n",
        "self_improving_loop.mutator",
        {"source": "api_key"},
    )
    assert "[self_improving_loop.mutator]" in out
    assert 'source = "api_key"' in out
    assert "[other]" in out  # preserved


def test_splice_section_replaces_existing_key() -> None:
    from core.config.toml_edit import splice_toml_section

    src = '[self_improving_loop.mutator]\nsource = "api_key"\nmax_tokens = 1024\n'
    out = splice_toml_section(src, "self_improving_loop.mutator", {"source": "openai-codex"})
    assert 'source = "openai-codex"' in out
    assert "max_tokens = 1024" in out  # untouched neighbor preserved


def test_splice_section_inserts_new_key_in_existing_section() -> None:
    from core.config.toml_edit import splice_toml_section

    src = "[self_improving_loop.mutator]\nmax_tokens = 1024\n"
    out = splice_toml_section(
        src, "self_improving_loop.mutator", {"default_model": "claude-opus-4-7"}
    )
    assert 'default_model = "claude-opus-4-7"' in out
    assert "max_tokens = 1024" in out


def test_splice_section_does_not_clobber_sibling_section() -> None:
    """Updating mutator must not touch ``[self_improving_loop.petri.auditor]``."""
    from core.config.toml_edit import splice_toml_section

    src = (
        "[self_improving_loop.mutator]\n"
        'source = "api_key"\n'
        "\n"
        "[self_improving_loop.petri.auditor]\n"
        'source = "api_key"\n'
        'model = "claude-opus-4-7"\n'
    )
    out = splice_toml_section(src, "self_improving_loop.mutator", {"source": "openai-codex"})
    assert 'source = "openai-codex"' in out
    # Petri section untouched:
    assert "[self_improving_loop.petri.auditor]" in out
    assert out.count('source = "api_key"') == 1
    assert 'model = "claude-opus-4-7"' in out


def test_splice_section_escapes_special_chars() -> None:
    from core.config.toml_edit import splice_toml_section

    out = splice_toml_section("", "x", {"k": 'has " quote and \\ backslash'})
    assert 'k = "has \\" quote and \\\\ backslash"' in out


# source set --------------------------------------------------------------


def test_cmd_source_set_rejects_invalid_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bad source value → no file written."""
    from evolve.scaffold_search import cli_commands as self_improving

    fake_toml = tmp_path / "config.toml"
    monkeypatch.setattr("core.paths.GLOBAL_CONFIG_TOML", fake_toml)
    # PR-DEDUP-CONFIG-TOML — writer + loader both resolve through
    # ``core.config.toml_edit.resolve_config_toml_path``, which reads the
    # module-local ``GLOBAL_CONFIG_TOML`` binding; patch that symbol so the
    # test honors fake_toml regardless of which side calls in first.
    monkeypatch.setattr("core.config.toml_edit.GLOBAL_CONFIG_TOML", fake_toml)
    with patch.object(self_improving, "console") as cmock:
        self_improving._cmd_source_set(["source=bogus"])
    assert not fake_toml.exists()
    # Warning emitted, no success line
    printed = " ".join(str(call) for call in cmock.print.call_args_list)
    assert "invalid source" in printed


def test_cmd_source_set_persists_valid_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A supported source writes the line to ~/.geode/config.toml."""
    from evolve.scaffold_search import cli_commands as self_improving

    fake_toml = tmp_path / "config.toml"
    monkeypatch.setattr("core.paths.GLOBAL_CONFIG_TOML", fake_toml)
    # See sibling test for rationale on patching both symbols.
    monkeypatch.setattr("core.config.toml_edit.GLOBAL_CONFIG_TOML", fake_toml)
    self_improving._cmd_source_set(["source=openai-codex"])
    text = fake_toml.read_text(encoding="utf-8")
    # Step J-b.1 — writer target moved to autoresearch.mutator.
    assert "[self_improving_loop.autoresearch.mutator]" in text
    assert 'source = "openai-codex"' in text


def test_valid_sources_constant_matches_config_enum() -> None:
    """``_VALID_SOURCES`` must stay in sync with ``MutatorConfig.source`` Literal."""
    from evolve.scaffold_search.cli_commands import _VALID_SOURCES

    assert set(_VALID_SOURCES) == {"auto", "api_key", "openai-codex"}


def test_persist_full_config_uses_plural_roles_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seed-generation writes MUST land under ``...seed_generation.roles.<X>`` (plural).

    Pre-fix the writer used singular ``role.<X>`` which falls outside
    ``SeedGenerationConfig`` schema's ``extra="forbid"`` allowlist —
    next config load raises ``ValidationError``. Codex MCP catch on
    PR-PAPERCLIP.
    """
    from evals.config import load_self_improving_loop_config
    from evolve.scaffold_search import cli_commands as self_improving

    fake_toml = tmp_path / "config.toml"
    monkeypatch.setattr("core.paths.GLOBAL_CONFIG_TOML", fake_toml)
    monkeypatch.setattr("core.config.toml_edit.GLOBAL_CONFIG_TOML", fake_toml)
    self_improving._persist_full_config(
        mutator={},
        petri={},
        seed_generation={"miner": {"model": "claude-haiku-4-5", "source": "api_key"}},
    )
    text = fake_toml.read_text(encoding="utf-8")
    assert "[self_improving_loop.seed_generation.roles.miner]" in text
    assert "[self_improving_loop.seed_generation.role.miner]" not in text  # singular forbidden
    # Round-trip: the loader must accept what the writer produced.
    cfg = load_self_improving_loop_config()
    assert "miner" in cfg.seed_generation.roles
    assert cfg.seed_generation.roles["miner"].source == "api_key"


def test_default_llm_call_explicit_api_key_routes_payg_not_inferred_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR-OPENAI-SOURCE-SINGLE-ENTRY (2026-06-03) — an EXPLICIT ``api_key`` mutator
    source must route to PAYG even when ``infer_source`` would re-derive subscription
    from a present OAuth profile. Proves the ``[self_improving_loop] openai_source``
    single entry point actually reaches the mutator (regression guard for the
    half-honored knob: pre-fix the API branch discarded ``source`` and used
    ``infer_source(provider)`` unconditionally)."""
    from evolve.scaffold_search.loop.mutate import runner

    cfg_mock = MagicMock()
    cfg_mock.autoresearch.mutator.default_model = "gpt-5.5"
    cfg_mock.autoresearch.mutator.source = "api_key"
    cfg_mock.autoresearch.mutator.max_tokens = 1024
    monkeypatch.setattr(
        "evals.config.load_self_improving_loop_config",
        lambda: cfg_mock,
    )
    monkeypatch.setattr("core.config._resolve_provider", lambda m: "openai-codex")
    # infer_source WOULD say subscription (OAuth profile present). The fix must NOT
    # consult it for an explicit api_key — otherwise the operator's PAYG choice is
    # silently reverted to the rate-limited subscription lane.
    monkeypatch.setattr(
        "core.llm.adapters._source_inference.infer_source", lambda _p: "openai-codex"
    )

    captured: dict[str, object] = {"provider": None, "source": None}

    def _capture_resolve(provider: str, source: str) -> MagicMock:
        captured["provider"] = provider
        captured["source"] = source
        stub = MagicMock()
        stub.name = "openai-payg"

        async def _acomplete(req: object) -> object:
            return _stub_adapter_call_result("from openai-payg")

        stub.acomplete = _acomplete
        return stub

    monkeypatch.setattr("core.llm.adapters.resolve_for", _capture_resolve)

    async def _fake_failover(
        models: list[str], do_call: Callable[[str], Awaitable[object]], **kwargs: object
    ) -> tuple[object, str]:
        result_obj = await do_call(models[0])
        return (result_obj, models[0])

    monkeypatch.setattr("core.llm.router.call_with_failover", _fake_failover)

    result = runner._default_llm_call("SYS", "USR")
    assert result == "from openai-payg"
    # explicit api_key → SOURCE_PAYG ("payg"), NOT infer_source's "openai-codex"
    assert captured == {"provider": "openai", "source": "payg"}
