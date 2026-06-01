"""E3 (2026-05-30) — ``--promote-policy`` control arms (gate / random / never).

Enables a MATCHED 3-arm comparison on the frozen held-out bench so a fitness gain
can be attributed to SELECTION rather than drift / judge-noise:

  - ``gate``   — today's behaviour, the ``_should_promote`` fitness gate (selection arm).
  - ``random`` — random-accept control: the mutation is still applied + audited as
                 normal, but the PROMOTE decision is a SEEDED coin-flip (reproducible),
                 NOT the gate.
  - ``never``  — no-mutation floor: never promote (baseline frozen across the
                 campaign); the held-out is still scored every cycle → pure drift /
                 judge-noise curve, the floor the other arms must beat.

Pins:
  1. ``_resolve_promote_policy`` / ``_resolve_promote_policy_seed`` precedence
     (env → CLI → config → constant) + the unknown-value guard.
  2. ``_random_accept_draw`` is a SEEDED, deterministic, per-cycle draw —
     reproducible with a fixed seed, independent across cycles, and a different
     seed gives a different campaign (no bare nondeterminism).
  3. The live ``main`` cycle ACTUALLY branches on the policy (gate uses the gate;
     never never promotes + freezes the baseline; random promotes per the draw),
     and the default gate path is unchanged in shape.
  4. ``promote_policy`` / ``promote_policy_seed`` are RECORDED on BOTH the per-cycle
     held-out attribution row AND the baseline registry row.
  5. A gate spec and a random spec hash to DIFFERENT epochs (schema 2), while the
     held-out bench id is left untouched (the shared ruler does not move).
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.self_improving import train as auto_train

# --- _resolve_promote_policy precedence --------------------------------------


def _stub_config(
    monkeypatch: pytest.MonkeyPatch,
    *,
    promote_policy: str | None = "gate",
    promote_policy_seed: int | None = 0,
) -> None:
    monkeypatch.setattr(
        auto_train,
        "_get_autoresearch_config",
        lambda: SimpleNamespace(
            promote_policy=promote_policy,
            promote_policy_seed=promote_policy_seed,
        ),
    )


def _clear_policy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GEODE_PROMOTE_POLICY",
        "AUTORESEARCH_PROMOTE_POLICY",
        "GEODE_PROMOTE_POLICY_SEED",
        "AUTORESEARCH_PROMOTE_POLICY_SEED",
    ):
        monkeypatch.delenv(name, raising=False)


def test_resolve_promote_policy_default_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env, no CLI, config gate → gate (today's selection arm, the default)."""
    _clear_policy_env(monkeypatch)
    _stub_config(monkeypatch, promote_policy="gate")
    assert auto_train._resolve_promote_policy(None) == "gate"


def test_resolve_promote_policy_reads_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_policy_env(monkeypatch)
    _stub_config(monkeypatch, promote_policy="random")
    assert auto_train._resolve_promote_policy(None) == "random"


def test_resolve_promote_policy_cli_wins_over_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_policy_env(monkeypatch)
    _stub_config(monkeypatch, promote_policy="gate")
    assert auto_train._resolve_promote_policy("never") == "never"


def test_resolve_promote_policy_geode_env_wins_over_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_PROMOTE_POLICY", "random")
    monkeypatch.delenv("AUTORESEARCH_PROMOTE_POLICY", raising=False)
    _stub_config(monkeypatch, promote_policy="gate")
    # env beats even an explicit CLI value (env is the per-run override tier).
    assert auto_train._resolve_promote_policy("gate") == "random"


def test_resolve_promote_policy_autoresearch_env_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEODE_PROMOTE_POLICY", raising=False)
    monkeypatch.setenv("AUTORESEARCH_PROMOTE_POLICY", "never")
    _stub_config(monkeypatch, promote_policy="gate")
    assert auto_train._resolve_promote_policy(None) == "never"


def test_resolve_promote_policy_unknown_value_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo'd arm must fail loudly, not silently run the selection arm under the
    wrong label and contaminate the comparison."""
    _clear_policy_env(monkeypatch)
    _stub_config(monkeypatch, promote_policy="gate")
    with pytest.raises(ValueError, match="gate / random / never"):
        auto_train._resolve_promote_policy("gae")


# --- _resolve_promote_policy_seed precedence ---------------------------------


def test_resolve_seed_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_policy_env(monkeypatch)
    _stub_config(monkeypatch, promote_policy_seed=0)
    assert auto_train._resolve_promote_policy_seed(None) == 0


def test_resolve_seed_reads_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_policy_env(monkeypatch)
    _stub_config(monkeypatch, promote_policy_seed=4242)
    assert auto_train._resolve_promote_policy_seed(None) == 4242


def test_resolve_seed_cli_wins_over_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_policy_env(monkeypatch)
    _stub_config(monkeypatch, promote_policy_seed=1)
    assert auto_train._resolve_promote_policy_seed(99) == 99


def test_resolve_seed_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_PROMOTE_POLICY_SEED", "777")
    _stub_config(monkeypatch, promote_policy_seed=1)
    assert auto_train._resolve_promote_policy_seed(99) == 777


def test_resolve_seed_malformed_env_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-integer seed ENV must not crash the cycle (graceful contract) — the
    resolver parses the raw env string itself, so it warns + degrades to the next
    tier and the campaign still runs."""
    monkeypatch.setenv("GEODE_PROMOTE_POLICY_SEED", "not-an-int")
    monkeypatch.delenv("AUTORESEARCH_PROMOTE_POLICY_SEED", raising=False)
    _stub_config(monkeypatch, promote_policy_seed=5)
    assert auto_train._resolve_promote_policy_seed(None) == 5


def test_malformed_config_seed_fails_loudly_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """HONEST contract (Codex MCP, E3): unlike the ENV string (parsed by the
    resolver), a malformed TOML ``promote_policy_seed`` is rejected by the Pydantic
    loader BEFORE the resolver runs — the loader is deliberately loud (the same
    ``ValidationError`` path as ``seed_limit`` / ``budget_minutes``), so the
    operator sees the actionable message rather than a silent fallback. The
    resolver's config-tier ``int()`` guard only defends the test-stub
    ``SimpleNamespace`` path. This pins the loud-at-load behaviour so it is not
    mistaken for a bug."""
    from core.config.self_improving_loop import SelfImprovingLoopConfig
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SelfImprovingLoopConfig.model_validate({"autoresearch": {"promote_policy_seed": "x"}})


# --- _random_accept_draw: seeded, deterministic, per-cycle -------------------


def test_random_draw_reproducible_with_fixed_seed() -> None:
    """Same (seed, cycle_index) → same decision, ALWAYS. The random campaign is
    reproducible from the recorded seed (no bare nondeterminism)."""
    for cycle in range(20):
        assert auto_train._random_accept_draw(1234, cycle) == auto_train._random_accept_draw(
            1234, cycle
        )


def test_random_draw_independent_across_cycles() -> None:
    """Successive cycles draw INDEPENDENT flips (not all sharing one draw) — so a
    fixed-seed campaign is a genuine random-accept sequence, not one repeated coin."""
    draws = [auto_train._random_accept_draw(1234, c) for c in range(40)]
    # both outcomes appear over 40 cycles (overwhelmingly likely for a fair coin;
    # this also proves the cycle index actually varies the draw)
    assert any(draws) and not all(draws)


def test_random_draw_different_seed_different_campaign() -> None:
    """A different seed yields an independent campaign — the two seeds disagree on
    at least one cycle (so the seed is load-bearing, not ignored)."""
    a = [auto_train._random_accept_draw(1, c) for c in range(40)]
    b = [auto_train._random_accept_draw(2, c) for c in range(40)]
    assert a != b


def test_gen_cycle_index_parses_gen_suffix() -> None:
    """The per-cycle index is the gen counter parsed from gen_tag (monotonic
    within a campaign)."""
    assert auto_train._gen_cycle_index("autoresearch-abc123-gen7") == 7
    # operator-pinned tag with no -genN suffix → 0 (deterministic, not per-cycle)
    assert auto_train._gen_cycle_index("my-pinned-campaign") == 0


# --- live main() dispatch: the policy is WIRED, not just defined -------------


def test_main_resolves_promote_policy_in_live_path() -> None:
    """``main`` must resolve the policy + seed from args (the CLI override) and the
    per-cycle index — a static pin against a defined-but-never-resolved knob."""
    source = inspect.getsource(auto_train.main)
    assert "promote_policy = _resolve_promote_policy(args.promote_policy)" in source
    assert "promote_policy_seed = _resolve_promote_policy_seed(args.promote_policy_seed)" in source
    assert "_cycle_index = _gen_cycle_index(gen_tag)" in source


def test_main_branches_on_policy() -> None:
    """The live promote decision must DISPATCH on the policy: a ``never`` branch
    that never writes the baseline + a ``random`` branch that draws the seeded
    coin. Static guard against "policy resolved but the decision still always uses
    the gate"."""
    source = inspect.getsource(auto_train.main)
    assert 'elif promote_policy == "never":' in source
    assert 'elif promote_policy == "random":' in source
    # the random branch actually invokes the seeded draw
    assert "_random_accept_draw(promote_policy_seed, _cycle_index)" in source


def test_main_gate_path_unchanged_in_shape() -> None:
    """The gate arm (the ``else`` branch) still runs ``_should_promote`` + the
    rollback gate + ``_write_baseline`` — the default path is unchanged."""
    source = inspect.getsource(auto_train.main)
    assert "ok, reason = _should_promote(" in source
    assert "_apply_rollback_condition_gate(" in source
    # gate is the fall-through else (not a new elif that could be skipped)
    assert source.index('elif promote_policy == "random":') < source.index(
        "ok, reason = _should_promote("
    ), "the gate must remain the final else branch (today's default behaviour)"


def test_never_branch_never_calls_should_promote() -> None:
    """``never`` must NOT consult the fitness gate at all — the baseline is frozen
    regardless of fitness. Pin that the never branch's body has no _should_promote
    call (it would otherwise be a gate-in-disguise)."""
    source = inspect.getsource(auto_train.main)
    never_start = source.index('elif promote_policy == "never":')
    random_start = source.index('elif promote_policy == "random":')
    never_body = source[never_start:random_start]
    assert "_should_promote" not in never_body, (
        "the never arm must never call the promote gate — the baseline is frozen"
    )
    assert "_write_baseline" not in never_body, (
        "the never arm must never write the baseline — it is the no-mutation floor"
    )


def test_main_forwards_policy_into_attribution_and_provenance() -> None:
    """The control-arm tag must flow into BOTH sinks: the per-cycle attribution row
    (the curve SoT) and the on-promote baseline provenance."""
    source = inspect.getsource(auto_train.main)
    # attribution row (write_attribution kwargs)
    assert "promote_policy=promote_policy" in source
    assert "promote_policy_seed=promote_policy_seed" in source
    # baseline provenance dict
    assert '"promote_policy": promote_policy' in source
    assert '"promote_policy_seed": promote_policy_seed' in source


# --- baseline registry row: control-arm fields -------------------------------


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(auto_train, "BASELINE_PATH", tmp_path / "baseline.json")
    fake_cfg = SimpleNamespace(
        auditor=SimpleNamespace(model="aud-m", source="claude-cli"),
        target=SimpleNamespace(model="tgt-m", source="openai-codex"),
        judge=SimpleNamespace(model="jdg-m", source="claude-cli"),
        mutator=SimpleNamespace(default_model="mut-m", source="openai-codex"),
        seed_select="petri_17dim",
        held_out_bench=None,
        promote_policy="gate",
        promote_policy_seed=0,
    )
    monkeypatch.setattr(auto_train, "_get_autoresearch_config", lambda: fake_cfg)
    return tmp_path


def _rows(archive: Path) -> list[dict]:
    return [json.loads(line) for line in archive.read_text(encoding="utf-8").splitlines() if line]


def test_row_records_default_gate_policy(isolated: Path) -> None:
    """The default ``_write_baseline`` (no policy override) records the gate arm —
    backward-compatible default."""
    auto_train._write_baseline({"broken_tool_use": 3.0}, {"broken_tool_use": 0.2})
    row = _rows(isolated / "baseline_archive.jsonl")[0]
    assert row["promote_policy"] == "gate"
    assert row["promote_policy_seed"] == 0


def test_row_records_random_arm_with_seed(isolated: Path) -> None:
    """The random arm's baseline row records the policy + the RECORDED seed so the
    campaign is reproducible from the ledger."""
    auto_train._write_baseline(
        {"broken_tool_use": 3.0},
        {"broken_tool_use": 0.2},
        promote_policy="random",
        promote_policy_seed=4242,
    )
    row = _rows(isolated / "baseline_archive.jsonl")[0]
    assert row["promote_policy"] == "random"
    assert row["promote_policy_seed"] == 4242
    # also inside the hashed spec (the epoch discriminator)
    assert row["baseline_spec"]["promote_policy"] == "random"


def test_row_self_verifies_under_schema_2(isolated: Path) -> None:
    """The stored row recomputes to its own epoch_hash under schema 2."""
    from core.self_improving.loop.baseline_epoch import compute_epoch_hash

    auto_train._write_baseline({"broken_tool_use": 3.0}, {"broken_tool_use": 0.2})
    row = _rows(isolated / "baseline_archive.jsonl")[0]
    assert row["spec_schema_version"] == "2"
    assert compute_epoch_hash(row["baseline_spec"]) == row["epoch_hash"]


# --- epoch distinctness: gate / random / never hash differently --------------


def test_gate_random_never_are_distinct_epochs() -> None:
    """A gate spec, a random spec, and a never spec hash to THREE different epochs
    (different production logic, correctly NOT averaged into one comparison)."""
    from core.self_improving.loop.baseline_epoch import build_baseline_spec, compute_epoch_hash

    role_prov = {
        "auditor": {"model": "m", "source": "s"},
        "target": {"model": "m", "source": "s"},
        "judge": {"model": "m", "source": "s"},
        "mutator": {"model": "m", "source": "s"},
    }
    common = {
        "margin_rule": "fitness-stderr",
        "margin_logic_version": "1",
        "fitness_formula_version": "1",
        "rubric_version": "v3",
        "dim_set": "subset",
        "bench": False,
        "role_provenance": role_prov,
        "seed_pool_id": "pool-x",
    }
    h_gate = compute_epoch_hash(build_baseline_spec(**common, promote_policy="gate"))  # type: ignore[arg-type]
    h_random = compute_epoch_hash(build_baseline_spec(**common, promote_policy="random"))  # type: ignore[arg-type]
    h_never = compute_epoch_hash(build_baseline_spec(**common, promote_policy="never"))  # type: ignore[arg-type]
    assert len({h_gate, h_random, h_never}) == 3


def test_promote_policy_seed_not_in_epoch_spec() -> None:
    """The SEED is an instance/reproducibility field, NOT a production-logic axis —
    two random campaigns with different seeds are the SAME logic (random-accept), so
    they must share an epoch. The seed is recorded on the ROW + held-out record, not
    folded into the epoch hash (else every random seed would fragment the epoch)."""
    from core.self_improving.loop.baseline_epoch import build_baseline_spec

    spec = build_baseline_spec(
        margin_rule="fitness-stderr",
        margin_logic_version="1",
        fitness_formula_version="1",
        rubric_version="v3",
        dim_set="subset",
        bench=False,
        role_provenance={
            r: {"model": "m", "source": "s"} for r in ("auditor", "target", "judge", "mutator")
        },
        seed_pool_id="pool-x",
        promote_policy="random",
    )
    assert "promote_policy_seed" not in spec
    assert spec["promote_policy"] == "random"


# --- attribution record: control-arm tag -------------------------------------


def test_attribution_records_policy_tag() -> None:
    """The per-cycle held-out attribution row carries the control-arm tag so the
    three arms' fixed-ruler curves are splittable + comparable."""
    from core.self_improving.loop.attribution import compute_attribution

    payload = compute_attribution(
        mutation_id="m1",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
        promote_policy="random",
        promote_policy_seed=4242,
    )
    assert payload["promote_policy"] == "random"
    assert payload["promote_policy_seed"] == 4242


def test_attribution_omits_policy_when_none() -> None:
    """Legacy / unspecified rows omit the policy fields (backward-compatible shape)."""
    from core.self_improving.loop.attribution import compute_attribution

    payload = compute_attribution(
        mutation_id="m1",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
    )
    assert "promote_policy" not in payload
    assert "promote_policy_seed" not in payload
