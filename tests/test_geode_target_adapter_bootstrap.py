"""Regression pin for ``plugins/petri_audit/targets/geode_target.py``'s
adapter-registry bootstrap.

The inspect-ai audit subprocess (``uv run inspect eval inspect_petri/audit``)
does not go through ``core.runtime.GeodeRuntime._build_core``, the
parent's wiring bootstrap path. Without an explicit ``bootstrap_builtins()``
call before constructing ``AgenticLoop`` inside ``_default_geode_runner``,
the audit subprocess's adapter registry stays empty and every target
``generate(messages, ...)`` call inside the runner fails with
``AdapterNotFoundError: provider='openai' source='payg'. Known pairs: []``.

Latent until 2026-05-27 because no test exercised the audit subprocess
end-to-end with a real target invocation. Surfaced when
``SelfImprovingLoopRunner.run_once(rerun_enabled=True, rerun_dry_run=False)``
was driven for the first real closed-loop validation cycle: target
inference happened 0 times across 8 seeds × 5 max_turns × 5 samples;
all dim_means returned ``inspect_petri`` default values, making the
fitness signal that drives the autoresearch promote/revert gate a
fake-success surface.

Mirrors the equivalent fix at ``core/agent/worker.py:817-823`` for the
sub-agent worker subprocess, which has the identical wiring gap.
"""

from __future__ import annotations

from pathlib import Path


def test_default_geode_runner_calls_bootstrap_builtins() -> None:
    """Source-level pin: the runner module references ``bootstrap_builtins``.

    Greps ``plugins/petri_audit/targets/geode_target.py`` for the
    ``bootstrap_builtins`` symbol so a future refactor that drops the
    call (e.g. import rearrangement, function extraction) fails the
    test before the audit subprocess fake-success regression re-lands.
    """
    target_module = (
        Path(__file__).resolve().parents[1]
        / "plugins"
        / "petri_audit"
        / "targets"
        / "geode_target.py"
    )
    source = target_module.read_text(encoding="utf-8")
    assert "bootstrap_builtins" in source, (
        "geode_target.py no longer references bootstrap_builtins(); the "
        "audit subprocess will revert to AdapterNotFoundError on the next "
        "live audit. Re-add the call before AgenticLoop construction in "
        "_default_geode_runner — see worker.py:817 for the pattern."
    )
    assert "bootstrap_builtins()" in source, (
        "bootstrap_builtins must be CALLED (not merely imported) inside "
        "_default_geode_runner. The audit subprocess's wiring container "
        "is the parent's, not this one's — registry stays empty without "
        "an explicit call."
    )


def test_bootstrap_builtins_is_idempotent_so_double_call_is_safe() -> None:
    """``bootstrap_builtins`` is safe to call when the registry is populated.

    The fix in ``_default_geode_runner`` calls ``bootstrap_builtins()``
    unconditionally on every runner entry, on the assumption the call is
    cheap and idempotent. This test pins that assumption so a future
    refactor that makes the call expensive (e.g. by changing it from
    "skip-if-registered" to "fail-if-registered") doesn't silently
    introduce a hot-path crash.
    """
    from core.llm.adapters.registry import (
        _REGISTRY,
        _reset_for_test,
        bootstrap_builtins,
        list_adapters,
    )

    try:
        _reset_for_test()
        assert len(_REGISTRY) == 0, "registry not cleared by _reset_for_test"

        bootstrap_builtins()
        first_pass = list_adapters()
        assert len(first_pass) > 0, (
            "bootstrap_builtins did not register any adapters; the audit "
            "subprocess will still see Known pairs=[]."
        )

        bootstrap_builtins()  # idempotent — no raise
        second_pass = list_adapters()
        assert second_pass == first_pass, (
            "second bootstrap_builtins() call changed the registry. The "
            "runner expects calling the function on a populated registry "
            "to be a no-op."
        )
    finally:
        _reset_for_test()
        bootstrap_builtins()  # restore for any downstream tests


def test_bootstrap_registers_codex_oauth_for_petri_target() -> None:
    """The ``codex-oauth`` adapter (backs Petri ``target`` source) must be registered.

    ``config.toml`` pins ``[self_improving_loop.petri.target] source =
    "openai-codex"`` — a Petri-surface alias that
    ``plugins/petri_audit/models.py`` routes to the canonical
    ``codex-oauth`` adapter inside the GEODE registry.
    ``_default_geode_runner`` resolves the source via
    ``resolve_for(provider, source)`` inside ``AgenticLoop``. If the
    canonical adapter is not registered after ``bootstrap_builtins()``,
    the lookup falls back to ``source='payg'`` and triggers
    ``AdapterNotFoundError`` (the fake-success path that motivated this
    PR). Pin the registration so a future ``bootstrap_builtins``
    refactor that drops the codex-oauth import is caught here.
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
        # Canonical adapter name (registered by CodexOAuthAdapter) — the
        # Petri-surface ``openai-codex`` alias resolves through this.
        assert "codex-oauth" in names, (
            f"codex-oauth adapter missing after bootstrap. Registered: "
            f"{sorted(names)!r}. The Petri target inference will fail."
        )
        # Also pin claude-cli (auditor + judge source) so a regression
        # that drops either bootstrap surfaces in a single test rather
        # than as a remote AdapterNotFoundError during a live audit.
        assert "claude-cli" in names, (
            f"claude-cli adapter missing after bootstrap. Registered: "
            f"{sorted(names)!r}. The Petri auditor + judge will fail."
        )
    finally:
        _reset_for_test()
        bootstrap_builtins()
