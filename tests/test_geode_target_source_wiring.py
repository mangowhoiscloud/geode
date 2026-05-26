"""Regression pin for ``geode_target._default_geode_runner``'s source
wiring into ``AgenticLoop``.

The audit subprocess invokes the GEODE target through
``plugins/petri_audit/targets/geode_target.py:_default_geode_runner``.
Until 2026-05-27 the runner passed only ``provider=...`` to
``AgenticLoop`` and silently inherited the default ``source="payg"``,
so the operator's ``[self_improving_loop.petri.target] source`` /
``[petri.target] source`` setting was ignored. On Pattern B
(subscription-only, ``fallback_to_payg=false``) this surfaced as
``OpenAIPaygAdapter: OPENAI_API_KEY not set`` for every target call —
indistinguishable from a real adapter-missing error in the trace.

The fix routes the (provider, source) pair through
``plugins/petri_audit/registry.get_binding("target", model=...)``, the
same resolver the manual ``geode audit`` CLI uses, so the three
source categories (PAYG / subscription / local-cli) all reach
``AgenticLoop`` exactly as the operator configured them.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_default_geode_runner_passes_source_argument() -> None:
    """Source-level pin: AgenticLoop is constructed with a ``source=`` kwarg.

    Greps ``plugins/petri_audit/targets/geode_target.py`` for the
    ``source=`` keyword inside the ``AgenticLoop(...)`` construction
    so a future refactor that drops the argument fails this test
    before the audit-subprocess fake-success path re-emerges.
    """
    target_module = (
        Path(__file__).resolve().parents[1]
        / "plugins"
        / "petri_audit"
        / "targets"
        / "geode_target.py"
    )
    source = target_module.read_text(encoding="utf-8")
    # The construction site we care about is `loop = AgenticLoop(`.
    # The source kwarg must appear before the closing paren.
    construct_idx = source.index("loop = AgenticLoop(")
    paren_open = source.index("(", construct_idx)
    # Find the matching close paren — paren-balanced scan, since the
    # ctor body contains nested calls/conditionals.
    depth = 1
    cursor = paren_open + 1
    while depth > 0 and cursor < len(source):
        ch = source[cursor]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        cursor += 1
    ctor_body = source[paren_open:cursor]
    assert "source=" in ctor_body, (
        "AgenticLoop(...) is constructed without a `source=` argument; "
        "the audit subprocess will silently fall back to "
        "AgenticLoop's default source='payg' and the operator's "
        "[petri.target] source config will be ignored. Pass the "
        "binding's source explicitly — see get_binding('target', ...)."
    )


def test_default_geode_runner_uses_get_binding() -> None:
    """Behavioural pin: the runner consults the binding registry.

    ``get_binding`` is the single resolver shared with the manual
    ``geode audit`` CLI; using it guarantees the audit subprocess
    resolves the same source the operator gets at the command line.
    """
    target_module = (
        Path(__file__).resolve().parents[1]
        / "plugins"
        / "petri_audit"
        / "targets"
        / "geode_target.py"
    )
    source = target_module.read_text(encoding="utf-8")
    assert "get_binding(" in source, (
        "geode_target.py no longer calls get_binding(...). The audit "
        "subprocess will diverge from the manual `geode audit` CLI's "
        "source resolution. Use plugins.petri_audit.registry.get_binding."
    )


@pytest.mark.parametrize(
    "category,source_value",
    [
        # PAYG — API-key path. OpenAIPaygAdapter / AnthropicPaygAdapter /
        # GlmPaygAdapter. Operator sets ``[petri.target] source = "payg"``
        # to force per-token billing.
        ("PAYG", "anthropic-payg"),
        ("PAYG", "openai-payg"),
        # Subscription OAuth — claude-cli (Anthropic Max), codex-oauth
        # (ChatGPT Plus). These ride the operator's interactive
        # subscription quota.
        ("subscription", "claude-cli"),
        ("subscription", "codex-oauth"),
        ("subscription", "anthropic-oauth"),
        # Local CLI subprocess — codex-cli wraps a local Codex
        # binary. Lower-latency option when an OAuth subscription is
        # unavailable.
        ("local-cli", "codex-cli"),
    ],
)
def test_bootstrap_registers_all_three_source_categories(category: str, source_value: str) -> None:
    """Each source the operator may configure resolves to a registered adapter.

    The full set of three categories (PAYG / subscription / local-cli)
    must be present after ``bootstrap_builtins()`` so
    ``AgenticLoop._new_adapter = resolve_for(provider, source)`` does
    not raise ``AdapterNotFoundError`` regardless of which credential
    path the operator selects. A regression that drops one of the
    eight builtin adapter imports surfaces here per-source rather
    than as a remote audit-subprocess failure.
    """
    from core.llm.adapters.registry import (
        _reset_for_test,
        bootstrap_builtins,
        list_adapters,
    )

    try:
        _reset_for_test()
        bootstrap_builtins()
        names = {a.name for a in list_adapters()}
        assert source_value in names, (
            f"{category} source {source_value!r} not registered after "
            f"bootstrap. Registered: {sorted(names)!r}. The audit "
            f"subprocess will fail when operator configures this source."
        )
    finally:
        _reset_for_test()
        bootstrap_builtins()
