"""E2 (2026-05-30) — version-frozen held-out bench, separate from the
co-evolving selection seeds.

The co-evolving ``seed_select`` pool applies SELECTION PRESSURE and mutates every
generation, so the fitness it produces is a moving ruler (not comparable across
generations). The held-out bench is a VERSION-FROZEN seed set used ONLY to MEASURE
fitness on a fixed ruler, so its curve IS the cross-generation evidence.

Pins four contracts:
  1. ``_resolve_held_out_bench`` precedence (env GEODE_/AUTORESEARCH_ → config →
     None) and that it NEVER consults the co-evolving latest_pointer.
  2. ``score_held_out_bench`` records ``held_out_fitness`` (the same 0-1
     compute_fitness the gate uses) + a content-hash-stable ``held_out_bench_id``,
     and restores the seed-select env it overrides.
  3. The baseline registry row stays backward-compatible when no held-out bench is
     configured (held-out keys omitted — no new required key), and gains exactly
     the two additive keys when a bench is scored.
  4. (E2-wire, 2026-05-30) ``main`` ACTUALLY dispatches ``score_held_out_bench``
     in the live cycle path — gated on a configured bench + non-dry-run — and
     feeds the result into BOTH the per-cycle attribution row and the on-promote
     baseline provenance. Guards against "defined but never invoked" mis-wiring.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from core.self_improving import train as auto_train

# --- _resolve_held_out_bench precedence --------------------------------------


def _stub_config(monkeypatch: pytest.MonkeyPatch, *, held_out_bench: str | None) -> None:
    monkeypatch.setattr(
        auto_train,
        "_get_autoresearch_config",
        lambda: SimpleNamespace(held_out_bench=held_out_bench),
    )


def test_resolve_held_out_bench_none_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env + config None → None (fixed-ruler measurement off, the default)."""
    monkeypatch.delenv("GEODE_HELD_OUT_BENCH", raising=False)
    monkeypatch.delenv("AUTORESEARCH_HELD_OUT_BENCH", raising=False)
    _stub_config(monkeypatch, held_out_bench=None)
    assert auto_train._resolve_held_out_bench() is None


def test_resolve_held_out_bench_reads_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEODE_HELD_OUT_BENCH", raising=False)
    monkeypatch.delenv("AUTORESEARCH_HELD_OUT_BENCH", raising=False)
    _stub_config(monkeypatch, held_out_bench="plugins/petri_audit/frozen_bench")
    assert auto_train._resolve_held_out_bench() == "plugins/petri_audit/frozen_bench"


def test_resolve_held_out_bench_geode_env_wins_over_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEODE_HELD_OUT_BENCH", "env/frozen")
    monkeypatch.delenv("AUTORESEARCH_HELD_OUT_BENCH", raising=False)
    _stub_config(monkeypatch, held_out_bench="config/frozen")
    assert auto_train._resolve_held_out_bench() == "env/frozen"


def test_resolve_held_out_bench_autoresearch_env_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The AUTORESEARCH_-prefixed alias is honoured (mirrors AUTORESEARCH_SEED_SELECT)."""
    monkeypatch.delenv("GEODE_HELD_OUT_BENCH", raising=False)
    monkeypatch.setenv("AUTORESEARCH_HELD_OUT_BENCH", "env/alias-frozen")
    _stub_config(monkeypatch, held_out_bench="config/frozen")
    assert auto_train._resolve_held_out_bench() == "env/alias-frozen"


def test_resolve_held_out_bench_geode_env_wins_over_autoresearch_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEODE_HELD_OUT_BENCH", "geode/frozen")
    monkeypatch.setenv("AUTORESEARCH_HELD_OUT_BENCH", "autoresearch/frozen")
    _stub_config(monkeypatch, held_out_bench=None)
    assert auto_train._resolve_held_out_bench() == "geode/frozen"


def test_resolve_held_out_bench_whitespace_env_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A whitespace-only env value must not produce an empty-string bench path."""
    monkeypatch.setenv("GEODE_HELD_OUT_BENCH", "   ")
    monkeypatch.delenv("AUTORESEARCH_HELD_OUT_BENCH", raising=False)
    _stub_config(monkeypatch, held_out_bench="config/frozen")
    assert auto_train._resolve_held_out_bench() == "config/frozen"


def test_resolve_held_out_bench_blank_config_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEODE_HELD_OUT_BENCH", raising=False)
    monkeypatch.delenv("AUTORESEARCH_HELD_OUT_BENCH", raising=False)
    _stub_config(monkeypatch, held_out_bench="   ")
    assert auto_train._resolve_held_out_bench() is None


def test_resolve_held_out_bench_ignores_co_evolving_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The held-out resolver must NOT auto-pick the latest survivor pool — that
    is the co-evolving pool's behaviour; the held-out ruler is frozen by
    definition. If ``_resolve_held_out_bench`` ever consulted the pointer this
    would fail loudly (read_latest_pointer is not in its precedence chain)."""

    def _boom() -> object:  # pragma: no cover - only fails if wrongly called
        raise AssertionError("held-out resolver must not read the latest pointer")

    monkeypatch.delenv("GEODE_HELD_OUT_BENCH", raising=False)
    monkeypatch.delenv("AUTORESEARCH_HELD_OUT_BENCH", raising=False)
    _stub_config(monkeypatch, held_out_bench=None)
    monkeypatch.setattr("core.paths.read_latest_pointer", _boom, raising=False)
    assert auto_train._resolve_held_out_bench() is None


# --- score_held_out_bench ----------------------------------------------------


def test_score_held_out_bench_returns_fitness_dims_and_stable_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The scorer returns (fitness, dim_means, bench_id). The id is the content
    hash of the frozen bench dir — stable across calls for the same content."""
    bench = tmp_path / "frozen_bench"
    bench.mkdir()
    # Seed bodies are ``.md`` — the only extension the audit's pool loader reads
    # (``directory.glob("*.md")``) and the only one ``seed_pool_content_hash``
    # fingerprints (incidental non-.md files are excluded).
    (bench / "seed_a.md").write_text("id: a\n", encoding="utf-8")
    (bench / "seed_b.md").write_text("id: b\n", encoding="utf-8")

    fitness, dim_means, bench_id = auto_train.score_held_out_bench(str(bench), dry_run=True)

    assert isinstance(fitness, float)
    # 0-1 compute_fitness scale (E1 reconciled ledger) — the gate's ruler.
    assert 0.0 <= fitness <= 1.0
    # dry-run synthesises the baseline-flavoured dim set on the Petri 1-10 scale.
    assert dim_means["broken_tool_use"] == pytest.approx(3.4)
    # content-addressed id of the frozen dir
    assert bench_id.startswith("pool-")
    # same content → same id (the frozen ruler keeps its fingerprint)
    _f2, _d2, bench_id_again = auto_train.score_held_out_bench(str(bench), dry_run=True)
    assert bench_id_again == bench_id


def test_score_held_out_bench_id_changes_when_frozen_set_edited(
    tmp_path: Path,
) -> None:
    """If the 'frozen' set is silently edited, the content-address changes — the
    drift is detectable, not hidden."""
    bench = tmp_path / "frozen_bench"
    bench.mkdir()
    (bench / "seed_a.md").write_text("id: a\n", encoding="utf-8")
    _f, _d, id_before = auto_train.score_held_out_bench(str(bench), dry_run=True)
    (bench / "seed_a.md").write_text("id: a-EDITED\n", encoding="utf-8")
    _f2, _d2, id_after = auto_train.score_held_out_bench(str(bench), dry_run=True)
    assert id_before != id_after


def test_score_held_out_bench_restores_seed_select_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The scorer overrides AUTORESEARCH_SEED_SELECT for the audit duration only;
    a prior value must be restored (and an unset var stays unset)."""
    bench = tmp_path / "frozen_bench"
    bench.mkdir()
    (bench / "s.md").write_text("id: s\n", encoding="utf-8")

    # Case 1: a prior co-evolving override is restored exactly.
    monkeypatch.setenv("AUTORESEARCH_SEED_SELECT", "co-evolving/survivors")
    auto_train.score_held_out_bench(str(bench), dry_run=True)
    import os

    assert os.environ["AUTORESEARCH_SEED_SELECT"] == "co-evolving/survivors"

    # Case 2: an unset var stays unset after the call.
    monkeypatch.delenv("AUTORESEARCH_SEED_SELECT", raising=False)
    auto_train.score_held_out_bench(str(bench), dry_run=True)
    assert "AUTORESEARCH_SEED_SELECT" not in os.environ


def test_score_held_out_bench_uses_same_fitness_formula_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The held-out fitness MUST be computed on the same formula path the gate's
    ``current_raw`` uses — same compute_fitness arguments — so the curve is not on
    a subtly different fitness DEFINITION than the baselines it is compared
    against.

    Pins that ``score_held_out_bench`` threads the shared ``anchor_confidence_mode``
    flag into compute_fitness WITH the held-out's own ``ANCHOR_DIMS`` subset as
    ``anchor_means`` (the gate extracts the same subset from its current dims —
    passing the flag without the subset would silently no-op the multiplier), with
    ``baseline_means=None`` (fresh-anchor intrinsic) and ``admire_means=None`` (the
    held-out audit emits no admire signal).
    """
    bench = tmp_path / "frozen_bench"
    bench.mkdir()
    (bench / "s.md").write_text("id: s\n", encoding="utf-8")

    # Stub the audit to return dims that INCLUDE the anchor dims (a real audit's
    # dim_extractor collects them; the dry-run synthetic set omits them), so the
    # anchor-subset extraction is observable.
    held_dims = {
        "broken_tool_use": 3.0,
        "admirable": 2.0,
        "disappointing": 4.0,
        "needs_attention": 5.0,
    }

    def _fake_audit(
        _dry_run: bool, *, session_id: str = "", gen_tag: str = ""
    ) -> tuple[
        dict[str, float],
        dict[str, float],
        float,
        float,
        dict[str, int],
        dict[str, str],
        list[dict[str, float]],
        list[dict[str, object]],
    ]:
        # PR-CONTRACT-EVAL (2026-06-03) — 8th element is the contract ledger.
        return dict(held_dims), {}, 0.0, 0.0, {}, {}, [], []

    monkeypatch.setattr(auto_train, "run_audit", _fake_audit)

    captured: dict[str, object] = {}

    def _spy(
        dim_means: dict[str, float],
        dim_stderr: dict[str, float] | None = None,
        **kwargs: object,
    ) -> float:
        # Capture the keyword formula-path arguments; return a fixed in-range
        # value (the test asserts on the captured args, not the fitness scalar).
        captured.update(kwargs)
        return 0.5

    monkeypatch.setattr(auto_train, "compute_fitness", _spy)

    # mode ON must be threaded through verbatim, WITH a real anchor subset so the
    # multiplier actually applies (not a silent no-op).
    auto_train.score_held_out_bench(str(bench), dry_run=True, anchor_confidence_mode=True)
    assert captured["anchor_confidence_mode"] is True
    assert captured["baseline_means"] is None
    assert captured["admire_means"] is None
    anchor_means = captured["anchor_means"]
    assert isinstance(anchor_means, dict) and anchor_means
    # the anchor subset is exactly the held-out dims restricted to ANCHOR_DIMS —
    # the SAME extraction the gate's current_raw does on its current dims.
    assert anchor_means == {dim: held_dims[dim] for dim in auto_train.ANCHOR_DIMS}

    captured.clear()
    # mode OFF (default) is likewise honoured — the curve does not silently flip on.
    auto_train.score_held_out_bench(str(bench), dry_run=True)
    assert captured["anchor_confidence_mode"] is False


def test_score_held_out_bench_signature_has_anchor_flag() -> None:
    """The scorer exposes the ``anchor_confidence_mode`` keyword so the live
    dispatch can thread the gate's flag (formula-parity wiring)."""
    sig = inspect.signature(auto_train.score_held_out_bench)
    assert "anchor_confidence_mode" in sig.parameters


def test_main_threads_anchor_confidence_mode_into_held_out() -> None:
    """The live cycle must pass the SAME ``_anchor_confidence_mode`` it gives the
    promote gate into ``score_held_out_bench`` — a static guard against a
    half-wired flag that would leave the held-out curve on the mode-off formula."""
    source = inspect.getsource(auto_train.main)
    assert "anchor_confidence_mode=_anchor_confidence_mode" in source, (
        "main must thread _anchor_confidence_mode into score_held_out_bench so the "
        "held-out curve shares the gate's fitness formula path"
    )


# --- baseline registry row: held-out fields ----------------------------------


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect BASELINE_PATH to tmp + stub the config so the registry writer
    resolves role models / seed_select without ~/.geode/config.toml."""
    monkeypatch.setattr(auto_train, "BASELINE_PATH", tmp_path / "baseline.json")
    fake_cfg = SimpleNamespace(
        auditor=SimpleNamespace(model="aud-m", source="claude-cli"),
        target=SimpleNamespace(model="tgt-m", source="openai-codex"),
        judge=SimpleNamespace(model="jdg-m", source="claude-cli"),
        mutator=SimpleNamespace(default_model="mut-m", source="openai-codex"),
        seed_select="petri_17dim",
        held_out_bench=None,
    )
    monkeypatch.setattr(auto_train, "_get_autoresearch_config", lambda: fake_cfg)
    return tmp_path


def _rows(archive: Path) -> list[dict]:
    return [json.loads(line) for line in archive.read_text(encoding="utf-8").splitlines() if line]


def test_row_omits_held_out_keys_when_no_bench(isolated: Path) -> None:
    """Backward-compatible: a promote without a held-out bench produces the
    same row shape as before — no held-out keys, so existing readers are
    unaffected (additive, never a new required key)."""
    auto_train._write_baseline({"broken_tool_use": 3.0}, {"broken_tool_use": 0.2})
    row = _rows(isolated / "baseline_archive.jsonl")[0]
    assert "held_out_fitness" not in row
    assert "held_out_bench_id" not in row


def test_row_records_held_out_fields_when_scored(isolated: Path) -> None:
    """When a held-out bench is scored, the row gains exactly the two additive
    keys: ``held_out_fitness`` (the fixed-ruler evidence) + ``held_out_bench_id``
    (the ruler's content-address)."""
    auto_train._write_baseline(
        {"broken_tool_use": 3.0},
        {"broken_tool_use": 0.2},
        held_out_fitness=0.7321,
        held_out_bench_id="pool-deadbeef0001",
    )
    row = _rows(isolated / "baseline_archive.jsonl")[0]
    assert row["held_out_fitness"] == pytest.approx(0.7321)
    assert row["held_out_bench_id"] == "pool-deadbeef0001"


def test_row_omits_held_out_when_only_one_field_present(isolated: Path) -> None:
    """Both held-out fields must be present together or omitted together — a lone
    fitness without its bench id (or vice versa) would be an ambiguous half-row,
    so the writer drops both rather than recording an un-attributable value."""
    auto_train._append_baseline_registry_row(
        "baseline-2606-1",
        dim_means={"broken_tool_use": 3.0},
        dim_stderr={},
        sample_count=None,
        measurement_modality=None,
        admire_means=None,
        bench_means=None,
        fitness_stderr=None,
        margin_rule="fitness-stderr",
        eval_archive=None,
        session_id="s",
        commit="c",
        ts_utc="2026-06-01T00:00:00Z",
        promoted_by="gate",
        held_out_fitness=0.5,  # bench_id missing → both dropped
    )
    row = _rows(isolated / "baseline_archive.jsonl")[0]
    assert "held_out_fitness" not in row
    assert "held_out_bench_id" not in row


# --- E2-wire: per-cycle live dispatch in main() ------------------------------


def test_main_dispatches_score_held_out_bench_in_live_cycle() -> None:
    """The live cycle path in ``main`` MUST call ``score_held_out_bench`` — not
    merely define it. Static pin against the "defined but never invoked"
    mis-wiring: the call site, the resolver, and the cost guard (configured bench
    + non-dry-run) must all be present in ``main``'s source.

    A full subprocess integration of train.py would spend real audit quota
    (score_held_out_bench runs a SECOND audit), so — mirroring
    test_dry_run_no_attribution's rationale — this pins the wiring at the source
    level, which is the cheap, regression-proof guard."""
    source = inspect.getsource(auto_train.main)
    # Resolver consulted in the live path.
    assert "_held_out_bench = _resolve_held_out_bench()" in source, (
        "main no longer resolves the held-out bench in the live cycle path"
    )
    # Cost guard: only when a bench is configured AND not a dry-run.
    assert "if _held_out_bench and not args.dry_run:" in source, (
        "held-out scoring must be gated on a configured bench + non-dry-run "
        "(None bench → skip, zero cost, backward-compatible)"
    )
    # The scoring function is actually CALLED (not just imported / referenced).
    assert "score_held_out_bench(" in source, (
        "main defines the held-out fields but never invokes score_held_out_bench "
        "— the per-cycle scoring is mis-wired (dead)"
    )


def test_main_feeds_held_out_into_attribution_and_provenance() -> None:
    """The scored values must flow into BOTH sinks: the per-cycle attribution row
    (the curve SoT, EVERY cycle) and the on-promote baseline provenance."""
    source = inspect.getsource(auto_train.main)
    # Attribution row (write_attribution kwargs) — the per-cycle curve SoT.
    assert "held_out_fitness=_held_out_fitness" in source, (
        "main does not forward held_out_fitness into the attribution row"
    )
    assert "held_out_bench_id=_held_out_bench_id" in source, (
        "main does not forward held_out_bench_id into the attribution row"
    )
    # Baseline provenance dict (on-promote registry row).
    assert '"held_out_fitness": _held_out_fitness' in source, (
        "main does not thread held_out_fitness into the baseline provenance"
    )
    assert '"held_out_bench_id": _held_out_bench_id' in source, (
        "main does not thread held_out_bench_id into the baseline provenance"
    )


def test_main_held_out_scoring_failure_is_non_fatal() -> None:
    """A held-out scoring error must NOT sink the primary cycle — the curve skips
    the generation (fields reset to None) and the promote / attribution path
    continues. Pin the defensive guard."""
    source = inspect.getsource(auto_train.main)
    # try/except wrapping the score call, resetting both fields on failure.
    assert "except Exception:" in source
    assert "_held_out_fitness = None" in source and "_held_out_bench_id = None" in source, (
        "held-out scoring failure must reset both fields so the curve skips this "
        "generation without corrupting the row"
    )
