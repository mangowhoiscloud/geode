"""Tests for ``core/config/self_improving_loop.py`` — single SoT loader for the
``~/.geode/config.toml`` ``[self_improving_loop.*]`` section.

Covers schema defaults, sub-config defaults, missing-file fallback,
empty-section fallback, env override (``GEODE_CONFIG_TOML``), explicit
path argument, ``extra='forbid'`` typo guard, threshold validation
(abort > warn), and per-role binding deserialisation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.config.self_improving_loop import (
    AutoresearchConfig,
    PetriRoleConfig,
    SeedGenerationConfig,
    SelfImprovingLoopBindings,
    SelfImprovingLoopConfig,
    load_self_improving_loop_config,
)


def _write_toml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_default_config_has_safe_defaults() -> None:
    """SelfImprovingLoopConfig() with no input yields strict-mode safe defaults."""
    cfg = SelfImprovingLoopConfig()
    assert cfg.fallback_to_payg is False  # strict default
    assert cfg.warn_threshold == pytest.approx(0.5)
    assert cfg.abort_threshold == pytest.approx(0.9)
    assert isinstance(cfg.autoresearch, AutoresearchConfig)
    assert isinstance(cfg.seed_generation, SeedGenerationConfig)
    # Step J-b.1 — audit role bindings moved into autoresearch namespace.
    # Defaults are now PetriRoleConfig() instances (model="", source="claude-cli"),
    # not entries in a top-level petri dict.
    assert cfg.autoresearch.target.model == ""
    assert cfg.autoresearch.judge.model == ""
    assert cfg.autoresearch.auditor.model == ""


def test_autoresearch_defaults_match_train_module() -> None:
    """Defaults mirror the existing core/self_improving/train.py module constants.

    PR-MINIMAL-2 (2026-05-21):
    - ``target_model`` / ``judge_model`` defaults flipped to ``None``
      (G1a: inherit ``Settings.model`` when unset).
    - ``use_oauth: bool = True`` → ``source: Source = "auto"`` (B1).
    - ``fallback_to_payg`` per-component override removed (C2).
    PR-SIL-5THEME C6 (2026-05-23):
    - ``source`` default ``"auto"`` → ``"claude-cli"`` (operator decision
      ``project_payg_exclusion_decision.md``).
    """
    a = AutoresearchConfig()
    assert a.budget_minutes == 5
    assert a.target_model is None  # G1a inherit
    assert a.judge_model is None  # G1a inherit
    assert a.source == "claude-cli"  # PR-SIL-5THEME C6 — subscription-first
    assert a.seed_limit == 10
    assert a.seed_select == "plugins/petri_audit/seeds"
    assert a.dim_set == "subset"
    assert a.max_turns == 10
    # PR-MINIMAL-2: per-component fallback_to_payg removed
    assert not hasattr(a, "fallback_to_payg")


def test_load_returns_defaults_when_file_missing(tmp_path: Path) -> None:
    """Missing file → fully-defaulted SelfImprovingLoopConfig, no error."""
    cfg = load_self_improving_loop_config(tmp_path / "nonexistent.toml")
    assert cfg == SelfImprovingLoopConfig()


def test_load_returns_defaults_when_section_missing(tmp_path: Path) -> None:
    """Existing file without [self_improving_loop] section → defaults."""
    path = tmp_path / "config.toml"
    _write_toml(path, "[settings]\nfoo = 'bar'\n")
    cfg = load_self_improving_loop_config(path)
    assert cfg == SelfImprovingLoopConfig()


def test_load_reads_self_improving_loop_section(tmp_path: Path) -> None:
    """[self_improving_loop] section keys override defaults."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop]
fallback_to_payg = true
warn_threshold = 0.6
abort_threshold = 0.95
""",
    )
    cfg = load_self_improving_loop_config(path)
    assert cfg.fallback_to_payg is True
    assert cfg.warn_threshold == pytest.approx(0.6)
    assert cfg.abort_threshold == pytest.approx(0.95)


def test_load_reads_autoresearch_subsection(tmp_path: Path) -> None:
    """[self_improving_loop.autoresearch] section deserialises into AutoresearchConfig."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop.autoresearch]
target_model = "geode/claude-opus-4-7"
judge_model = "claude-code/sonnet"
budget_minutes = 10
seed_limit = 25
""",
    )
    cfg = load_self_improving_loop_config(path)
    assert cfg.autoresearch.target_model == "geode/claude-opus-4-7"
    assert cfg.autoresearch.judge_model == "claude-code/sonnet"
    assert cfg.autoresearch.budget_minutes == 10
    assert cfg.autoresearch.seed_limit == 25
    # PR-MINIMAL-2 — untouched ``source`` field keeps its default
    # (was ``use_oauth: bool = True``; now ``source: Source``).
    # PR-SIL-5THEME C6 (2026-05-23) — default ``"auto" → "claude-cli"``.
    assert cfg.autoresearch.source == "claude-cli"


# ---------------------------------------------------------------------------
# PR-C-P1 (2026-05-23) — seed_limit lower bound ≥ 5
# ---------------------------------------------------------------------------


def test_autoresearch_seed_limit_lower_bound_is_5() -> None:
    """PR-C-P1 bumps ``seed_limit`` from ``ge=1`` to ``ge=5``.
    ``dim_extractor._aggregate`` forces ``stderr=0.0`` only at N=1
    (ddof=1 variance undefined); N=2-4 produces a sample stderr but
    the CV is too unstable to drive ``_should_promote``. Either way
    the gate ends up flooring at the default 0.05, so a 0.05+ Δ
    promotes against a measurement with no confidence signal.
    Pydantic must reject any config that sets it lower."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        AutoresearchConfig(seed_limit=2)
    msg = str(exc_info.value)
    assert "seed_limit" in msg
    assert "greater than or equal to 5" in msg or "ge=5" in msg


def test_autoresearch_seed_limit_boundary_n5_accepted() -> None:
    """Boundary pin — N=5 (the threshold) must be accepted. A future
    typo bumping to ``gt=5`` would silently exclude the boundary."""
    cfg = AutoresearchConfig(seed_limit=5)
    assert cfg.seed_limit == 5


def test_autoresearch_seed_limit_default_remains_10() -> None:
    """The default (already healthy at 10) stays unchanged so operators
    who never set ``seed_limit`` see no behaviour shift."""
    cfg = AutoresearchConfig()
    assert cfg.seed_limit == 10


def test_get_autoresearch_config_propagates_validation_error_to_operator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR-C-P1 Codex MCP catch — ``core.self_improving.train._get_autoresearch_config``
    used to ``except Exception:`` and silently fall back to the module
    defaults, so an operator config with ``seed_limit = 2`` (< new
    ``ge=5`` floor) produced no error. The narrowed catch now lets
    ``pydantic.ValidationError`` surface to the operator with the
    actionable Pydantic message. Same silent-drift pattern as
    PR-MINIMAL-2 #1398."""
    from pydantic import ValidationError

    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop.autoresearch]
seed_limit = 2
""",
    )
    import core.self_improving.train as auto_train
    from core.config import self_improving_loop as sil_config

    # Capture the unpatched loader, then monkeypatch the import target
    # to force the tmp_path. ``_get_autoresearch_config`` imports the
    # loader from ``core.config.self_improving_loop`` so the patch
    # needs to land on that module attribute.
    original_loader = sil_config.load_self_improving_loop_config

    def _load_with_tmp_path(*_args: object, **_kwargs: object) -> object:
        return original_loader(path)

    monkeypatch.setattr(sil_config, "load_self_improving_loop_config", _load_with_tmp_path)

    with pytest.raises(ValidationError):
        auto_train._get_autoresearch_config()


def test_load_reads_petri_role_bindings(tmp_path: Path) -> None:
    """[self_improving_loop.autoresearch.<role>] keys hydrate PetriRoleConfig sub-fields.

    Step J-b.1 — namespace relocated from ``petri`` (executor layer) to
    ``autoresearch`` (control layer) so role-binding ownership matches
    the self-improving pipeline's control flow.
    """
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop.autoresearch.auditor]
model = "claude-sonnet-4-6"
source = "claude-cli"

[self_improving_loop.autoresearch.target]
model = "geode/gpt-5.5"
source = "openai-codex"

[self_improving_loop.autoresearch.judge]
model = "claude-opus-4-7"
source = "claude-cli"
""",
    )
    cfg = load_self_improving_loop_config(path)
    # Step J-b.1 — role bindings live under autoresearch namespace (control SoT).
    assert cfg.autoresearch.auditor.model == "claude-sonnet-4-6"
    assert cfg.autoresearch.auditor.source == "claude-cli"
    assert cfg.autoresearch.target.source == "openai-codex"
    assert cfg.autoresearch.judge.model == "claude-opus-4-7"


def test_load_reads_seed_generation_subsection(tmp_path: Path) -> None:
    """[self_improving_loop.seed_generation] + nested role bindings deserialise."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop.seed_generation]
candidates_default = 20
default_gen_tag = "gen3"

[self_improving_loop.seed_generation.roles.generator]
model = "gpt-5.5"
source = "openai-codex"
""",
    )
    cfg = load_self_improving_loop_config(path)
    assert cfg.seed_generation.candidates_default == 20
    assert cfg.seed_generation.default_gen_tag == "gen3"
    assert cfg.seed_generation.roles["generator"].model == "gpt-5.5"


def test_extra_forbid_rejects_typo(tmp_path: Path) -> None:
    """Unknown field at top level → pydantic ValidationError."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop]
falback_to_payg = true
""",
    )
    with pytest.raises(Exception) as exc_info:
        load_self_improving_loop_config(path)
    assert "falback_to_payg" in str(exc_info.value)


def test_extra_forbid_rejects_typo_in_autoresearch(tmp_path: Path) -> None:
    """Unknown field in [self_improving_loop.autoresearch] → ValidationError."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop.autoresearch]
budget_minute = 5
""",
    )
    with pytest.raises(Exception) as exc_info:
        load_self_improving_loop_config(path)
    assert "budget_minute" in str(exc_info.value)


def test_abort_threshold_must_exceed_warn(tmp_path: Path) -> None:
    """abort_threshold ≤ warn_threshold → ValidationError."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop]
warn_threshold = 0.8
abort_threshold = 0.7
""",
    )
    with pytest.raises(Exception) as exc_info:
        load_self_improving_loop_config(path)
    assert "abort_threshold" in str(exc_info.value)


def test_threshold_range_clamps(tmp_path: Path) -> None:
    """warn / abort thresholds outside [0, 1] are rejected."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop]
warn_threshold = 1.5
""",
    )
    with pytest.raises(Exception):
        load_self_improving_loop_config(path)


def test_env_override_resolves_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GEODE_CONFIG_TOML env var redirects the loader."""
    path = tmp_path / "alt.toml"
    _write_toml(
        path,
        """
[self_improving_loop]
warn_threshold = 0.42
""",
    )
    monkeypatch.setenv("GEODE_CONFIG_TOML", str(path))
    cfg = load_self_improving_loop_config()
    assert cfg.warn_threshold == pytest.approx(0.42)


def test_explicit_path_arg_wins_over_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit path argument trumps GEODE_CONFIG_TOML env var."""
    env_path = tmp_path / "env.toml"
    arg_path = tmp_path / "arg.toml"
    _write_toml(env_path, "[self_improving_loop]\nwarn_threshold = 0.1\n")
    _write_toml(arg_path, "[self_improving_loop]\nwarn_threshold = 0.9\n")
    monkeypatch.setenv("GEODE_CONFIG_TOML", str(env_path))
    # abort_threshold must remain > warn so reduce abort and bump warn:
    # write a valid file at arg_path.
    _write_toml(arg_path, "[self_improving_loop]\nwarn_threshold = 0.5\nabort_threshold = 0.9\n")
    cfg = load_self_improving_loop_config(arg_path)
    assert cfg.warn_threshold == pytest.approx(0.5)


def test_bindings_dataclass_round_trip() -> None:
    """SelfImprovingLoopBindings serialises both ways without loss.

    PR-MINIMAL-2 (2026-05-21) — per-component ``fallback_to_payg``
    override removed (C2). Only the global flag survives at
    ``[self_improving_loop] fallback_to_payg``."""
    b = SelfImprovingLoopBindings(model="x", source="claude-cli")
    assert b.model == "x"
    assert b.source == "claude-cli"
    assert not hasattr(b, "fallback_to_payg")


def test_petri_role_default_source_is_subscription_first() -> None:
    """PetriRoleConfig without explicit source picks ``claude-cli`` default.

    PR-SIL-5THEME C6 (2026-05-23) — operator decision
    (``project_payg_exclusion_decision.md``) 으로 default ``auto`` → ``claude-cli``.
    ``auto`` 는 manifest cascade 가 PAYG 까지 fallback 가능 → 명시
    subscription-first default 로 silent leak 차단.
    """
    p = PetriRoleConfig(model="claude-sonnet-4-6")
    assert p.source == "claude-cli"


def test_load_handles_empty_self_improving_loop_section(tmp_path: Path) -> None:
    """File with `[self_improving_loop]` but no body → defaults (model_validator must
    not reject the default-vs-default threshold pair)."""
    path = tmp_path / "config.toml"
    _write_toml(path, "[self_improving_loop]\n")
    cfg = load_self_improving_loop_config(path)
    assert cfg == SelfImprovingLoopConfig()


def test_threshold_inversion_caught_when_only_warn_set(tmp_path: Path) -> None:
    """If user raises warn_threshold past the default abort_threshold without
    moving abort, model_validator must catch the inversion. ``field_validator``
    misses this case because it only fires when abort is explicitly set."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop]
warn_threshold = 0.95
""",
    )
    with pytest.raises(Exception) as exc_info:
        load_self_improving_loop_config(path)
    assert "abort_threshold" in str(exc_info.value)


def test_default_path_resolves_to_global_config_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without explicit path or env override, the loader resolves to
    ``core.paths.GLOBAL_CONFIG_TOML``."""
    import core.config.self_improving_loop as mod

    monkeypatch.delenv("GEODE_CONFIG_TOML", raising=False)
    fake = tmp_path / "global.toml"
    _write_toml(fake, "[self_improving_loop]\nwarn_threshold = 0.33\n")
    monkeypatch.setattr(mod, "GLOBAL_CONFIG_TOML", fake)
    cfg = load_self_improving_loop_config()
    assert cfg.warn_threshold == pytest.approx(0.33)


# ── PR-P2 — defaults-applied RunTranscript notice ──


def _make_journal(tmp_path: Path):
    """Construct a RunTranscript pointing at a temp file."""
    from core.self_improving.loop.run_transcript import RunTranscript

    return RunTranscript(
        session_id="p2-test",
        gen_tag="test",
        component="config-test",
        path=tmp_path / "transcript.jsonl",
    )


def _read_journal(journal_path: Path) -> list[dict]:
    import json

    lines = journal_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_load_emits_file_missing_notice_into_session_journal(tmp_path: Path) -> None:
    """When config file is absent and a RunTranscript scope is active,
    the loader emits a ``self_improving_loop_config_defaults_applied``
    event with ``reason='file_missing'``."""
    from core.self_improving.loop.run_transcript import run_transcript_scope

    journal = _make_journal(tmp_path)
    missing = tmp_path / "nope.toml"
    with run_transcript_scope(journal):
        cfg = load_self_improving_loop_config(missing)
    assert cfg == SelfImprovingLoopConfig()
    rows = _read_journal(journal.path)
    assert len(rows) == 1
    assert rows[0]["event"] == "self_improving_loop_config_defaults_applied"
    assert rows[0]["payload"]["reason"] == "file_missing"
    assert rows[0]["payload"]["path"] == str(missing)
    assert rows[0]["level"] == "info"


def test_load_emits_section_missing_notice_into_session_journal(tmp_path: Path) -> None:
    """File exists but the ``[self_improving_loop]`` section is absent →
    notice with ``reason='section_missing'``."""
    from core.self_improving.loop.run_transcript import run_transcript_scope

    journal = _make_journal(tmp_path)
    path = tmp_path / "config.toml"
    _write_toml(path, "[settings]\nfoo = 'bar'\n")
    with run_transcript_scope(journal):
        cfg = load_self_improving_loop_config(path)
    assert cfg == SelfImprovingLoopConfig()
    rows = _read_journal(journal.path)
    assert len(rows) == 1
    assert rows[0]["event"] == "self_improving_loop_config_defaults_applied"
    assert rows[0]["payload"]["reason"] == "section_missing"
    assert rows[0]["level"] == "info"


def test_load_emits_read_error_notice_as_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OSError on read → notice with ``reason='read_error'`` at level ``warn``."""
    from core.self_improving.loop.run_transcript import run_transcript_scope

    journal = _make_journal(tmp_path)
    path = tmp_path / "config.toml"
    _write_toml(path, "[self_improving_loop]\n")

    real_open = Path.open

    def _boom(self: Path, *args: object, **kwargs: object):
        if self == path:
            raise OSError("simulated permission denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _boom)

    with run_transcript_scope(journal):
        cfg = load_self_improving_loop_config(path)
    assert cfg == SelfImprovingLoopConfig()
    rows = _read_journal(journal.path)
    assert len(rows) == 1
    assert rows[0]["payload"]["reason"] == "read_error"
    assert rows[0]["level"] == "warn"


def test_load_silent_when_no_run_transcript_scope(tmp_path: Path) -> None:
    """Outside an active scope the defaults-notice helper must be a
    no-op (no exception). The loader still returns the defaults."""
    cfg = load_self_improving_loop_config(tmp_path / "nope.toml")
    assert cfg == SelfImprovingLoopConfig()


def test_load_does_not_emit_notice_when_section_present(tmp_path: Path) -> None:
    """When the [self_improving_loop] section is populated, no
    defaults-applied event fires — the loader is using user values."""
    from core.self_improving.loop.run_transcript import run_transcript_scope

    journal = _make_journal(tmp_path)
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop]
warn_threshold = 0.4
""",
    )
    with run_transcript_scope(journal):
        cfg = load_self_improving_loop_config(path)
    assert cfg.warn_threshold == pytest.approx(0.4)
    assert not journal.path.exists() or _read_journal(journal.path) == []


# ── Step J-b.1 — control-layer SoT migration semantics ──────────────────


def test_step_j_b1_petri_namespace_migrates_to_autoresearch() -> None:
    """Legacy ``[self_improving_loop.petri.<role>]`` raw input is moved
    under ``autoresearch`` by the before-validator and the migration
    fires a ``DeprecationWarning``. The Python field
    ``SelfImprovingLoopConfig.petri`` no longer exists — readers must
    use ``cfg.autoresearch.target`` etc.
    """
    import warnings

    raw = {
        "petri": {
            "target": {"model": "legacy-target", "source": "claude-cli"},
            "judge": {"model": "legacy-judge"},
            "auditor": {"model": "legacy-auditor"},
        },
    }
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        cfg = SelfImprovingLoopConfig.model_validate(raw)
    deprecations = [w for w in recorded if issubclass(w.category, DeprecationWarning)]
    petri_warnings = [w for w in deprecations if "[self_improving_loop.petri.*]" in str(w.message)]
    assert len(petri_warnings) == 1, (
        "Step J-b.1 invariant: legacy [petri.*] input must emit exactly one "
        "DeprecationWarning per load so operators see the migration once."
    )

    assert cfg.autoresearch.target.model == "legacy-target"
    assert cfg.autoresearch.judge.model == "legacy-judge"
    assert cfg.autoresearch.auditor.model == "legacy-auditor"
    assert not hasattr(cfg, "petri"), (
        "Step J-b.1 regressed: SelfImprovingLoopConfig.petri must be removed; "
        "readers route through cfg.autoresearch.<role>."
    )


def test_step_j_b1_mutator_namespace_migrates_to_autoresearch() -> None:
    """Legacy ``[self_improving_loop.mutator]`` raw input is moved
    under ``autoresearch.mutator`` by the before-validator with a
    ``DeprecationWarning``. The top-level ``mutator`` field is removed.
    """
    import warnings

    raw = {
        "mutator": {"default_model": "legacy-mutator", "source": "claude-cli"},
    }
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        cfg = SelfImprovingLoopConfig.model_validate(raw)
    mutator_warnings = [
        w
        for w in recorded
        if issubclass(w.category, DeprecationWarning)
        and "[self_improving_loop.mutator]" in str(w.message)
    ]
    assert len(mutator_warnings) == 1

    assert cfg.autoresearch.mutator.default_model == "legacy-mutator"
    assert cfg.autoresearch.mutator.source == "claude-cli"
    assert not hasattr(cfg, "mutator"), (
        "Step J-b.1 regressed: SelfImprovingLoopConfig.mutator must be removed; "
        "readers route through cfg.autoresearch.mutator."
    )


def test_step_j_b1_new_namespace_wins_when_both_layouts_present() -> None:
    """When both ``[autoresearch.target]`` and the legacy
    ``[petri.target]`` are present, the new (control-layer) value wins.
    Mirrors PR #1496's "new wins" semantics in the opposite direction.
    """
    raw = {
        "autoresearch": {"target": {"model": "NEW-WINS"}},
        "petri": {"target": {"model": "OLD-LOSES"}},
    }
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        cfg = SelfImprovingLoopConfig.model_validate(raw)
    assert cfg.autoresearch.target.model == "NEW-WINS"


def test_step_j_b1_clean_input_emits_no_deprecation() -> None:
    """Pure ``autoresearch.*`` input (no legacy keys) must not emit any
    DeprecationWarning — the migration warning is a deprecation signal,
    not noise on every load."""
    import warnings

    raw = {
        "autoresearch": {
            "target": {"model": "new-target"},
            "judge": {"model": "new-judge"},
            "mutator": {"default_model": "new-mutator"},
        },
    }
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        SelfImprovingLoopConfig.model_validate(raw)
    deprecations = [
        w
        for w in recorded
        if issubclass(w.category, DeprecationWarning)
        and (
            "[self_improving_loop.petri.*]" in str(w.message)
            or "[self_improving_loop.mutator]" in str(w.message)
        )
    ]
    assert deprecations == [], (
        "Step J-b.1 regressed: clean (new-style) input should not emit any "
        "petri/mutator DeprecationWarning."
    )
