"""PR-BASELINE-EPOCH (2026-05-30) — content-addressed epoch discriminator.

Pins the pure spec→hash→label module (``core.self_improving.loop.observe.baseline_epoch``):
determinism, surface-sensitivity (every spec field moves the hash), instance-blindness
(measured values are not in the spec), canonical serialization, sequential labels, and
the seed-pool content-hash. The registry-integration guards (row self-verifies, distinct
epochs per margin_rule) live in tests/autoresearch/test_baseline_registry.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.self_improving.loop.observe.baseline_epoch import (
    SPEC_SCHEMA_VERSION,
    build_baseline_spec,
    canonical_spec_json,
    compute_epoch_hash,
    load_epoch_label_map,
    resolve_epoch_label,
    save_epoch_label_map,
    seed_pool_content_hash,
)

_ROLE_PROV = {
    "auditor": {"model": "opus-4-8", "source": "claude-cli", "lane": "CLI"},
    "target": {"model": "gpt-5.5", "source": "openai-codex", "lane": "Subscription"},
    "judge": {"model": "opus-4-8", "source": "api_key", "lane": "PAYG"},
    "mutator": {"model": "gpt-5.5", "source": "openai-codex", "lane": "Subscription"},
}


def _base_spec(**over: object) -> dict:
    kwargs: dict = {
        "margin_rule": "fitness-stderr",
        "margin_logic_version": "1",
        "fitness_formula_version": "1",
        "rubric_version": "v3-22dim-PR0",
        "dim_set": "subset",
        "bench": False,
        "role_provenance": _ROLE_PROV,
        "seed_pool_id": "pool-deadbeef0001",
    }
    kwargs.update(over)
    return build_baseline_spec(**kwargs)  # type: ignore[arg-type]


# --- determinism + canonical -------------------------------------------------


def test_epoch_hash_deterministic() -> None:
    spec = _base_spec()
    assert compute_epoch_hash(spec) == compute_epoch_hash(spec)
    # rebuilt-from-scratch spec hashes identically too (no hidden state)
    assert compute_epoch_hash(_base_spec()) == compute_epoch_hash(_base_spec())


def test_canonical_serialization_key_order_invariant() -> None:
    spec = _base_spec()
    shuffled = {k: spec[k] for k in reversed(list(spec))}
    assert canonical_spec_json(spec) == canonical_spec_json(shuffled)
    assert compute_epoch_hash(spec) == compute_epoch_hash(shuffled)


def test_hash_is_twelve_hex() -> None:
    h = compute_epoch_hash(_base_spec())
    assert len(h) == 12 and all(c in "0123456789abcdef" for c in h)


# --- surface-sensitivity (every spec field moves the hash) -------------------


def test_each_surface_field_moves_the_hash() -> None:
    base = compute_epoch_hash(_base_spec())
    variants = {
        "margin_rule": _base_spec(margin_rule="dim-stderr"),
        "margin_logic_version": _base_spec(margin_logic_version="2"),
        "fitness_formula_version": _base_spec(fitness_formula_version="2"),
        "rubric_version": _base_spec(rubric_version="v4"),
        "dim_set": _base_spec(dim_set="full"),
        "bench": _base_spec(bench=True),
        "promote_policy": _base_spec(promote_policy="random"),  # E3 — control arm
        "seed_pool_id": _base_spec(seed_pool_id="pool-deadbeef0002"),
        "role_model": _base_spec(
            role_provenance={**_ROLE_PROV, "target": {**_ROLE_PROV["target"], "model": "gpt-6"}}
        ),
        "role_source": _base_spec(
            role_provenance={**_ROLE_PROV, "judge": {**_ROLE_PROV["judge"], "source": "claude-cli"}}
        ),
    }
    for field, spec in variants.items():
        assert compute_epoch_hash(spec) != base, f"flipping {field} did not move the epoch hash"


def test_derived_lane_does_not_move_the_hash() -> None:
    """lane is derived from source, so a (contradictory) lane edit with source
    unchanged must NOT change the epoch — only model+source are hashed."""
    base = compute_epoch_hash(_base_spec())
    lane_only = _base_spec(
        role_provenance={**_ROLE_PROV, "judge": {**_ROLE_PROV["judge"], "lane": "WRONG"}}
    )
    assert compute_epoch_hash(lane_only) == base


def test_spec_excludes_instance_fields() -> None:
    """The spec is the surface, never the measured instance — no dim_means /
    fitness / fitness_stderr / seed_count / ts / commit keys leak in."""
    spec = _base_spec()
    forbidden = {"dim_means", "fitness", "fitness_stderr", "seed_count", "ts_utc", "commit", "id"}
    assert forbidden.isdisjoint(spec)
    assert spec["spec_schema_version"] == SPEC_SCHEMA_VERSION


# --- E3: promote_policy control arm in the spec (schema 2) -------------------


def test_schema_is_version_2() -> None:
    """E3 bumped the spec field-set version 1 → 2 (promote_policy added). Old
    schema-1 rows fall into a prior epoch (correct — no retroactive recompute)."""
    assert SPEC_SCHEMA_VERSION == "2"
    assert _base_spec()["spec_schema_version"] == "2"


def test_gate_vs_random_spec_distinct_epoch() -> None:
    """A gate spec and a random spec hash to DIFFERENT epochs — the selection arm
    and the random-accept control are different production logic and must never be
    averaged into one comparison."""
    h_gate = compute_epoch_hash(_base_spec(promote_policy="gate"))
    h_random = compute_epoch_hash(_base_spec(promote_policy="random"))
    h_never = compute_epoch_hash(_base_spec(promote_policy="never"))
    assert len({h_gate, h_random, h_never}) == 3


def test_promote_policy_in_spec_seed_is_not() -> None:
    """``promote_policy`` is a production-logic axis (in the hashed spec), but the
    RNG SEED is an instance/reproducibility field — two random campaigns with
    different seeds are the same logic, so the seed must NOT fragment the epoch."""
    spec = _base_spec(promote_policy="random")
    assert spec["promote_policy"] == "random"
    assert "promote_policy_seed" not in spec


# --- label resolution --------------------------------------------------------


def test_resolve_label_sequential_and_idempotent() -> None:
    label_map: dict[str, str] = {}
    l1, new1 = resolve_epoch_label("aaaaaaaaaaaa", label_map=label_map)
    l2, new2 = resolve_epoch_label("bbbbbbbbbbbb", label_map=label_map)
    l1_again, new1_again = resolve_epoch_label("aaaaaaaaaaaa", label_map=label_map)
    assert (l1, l2) == ("be-001", "be-002")
    assert (new1, new2) == (True, True)
    assert (l1_again, new1_again) == ("be-001", False)  # re-seen hash keeps its label


def test_label_map_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "baseline_epochs.json"
    original = {"aaaaaaaaaaaa": "be-001", "bbbbbbbbbbbb": "be-002"}
    save_epoch_label_map(path, original)
    assert load_epoch_label_map(path) == original


def test_load_label_map_missing_returns_empty(tmp_path: Path) -> None:
    # missing file is the legitimate first-ever case → {}
    assert load_epoch_label_map(tmp_path / "absent.json") == {}


def test_load_label_map_corrupt_fails_closed(tmp_path: Path) -> None:
    # an EXISTING but unreadable map (corrupt / merge-conflicted) must raise, not
    # silently return {} — else the writer would relabel every existing epoch.
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unreadable"):
        load_epoch_label_map(bad)
    not_obj = tmp_path / "list.json"
    not_obj.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not a JSON object"):
        load_epoch_label_map(not_obj)


# --- seed-pool content hash (decision B) -------------------------------------


def test_seed_pool_content_hash_string_vs_empty() -> None:
    assert seed_pool_content_hash("") == ""
    assert seed_pool_content_hash(None) == ""
    sel = seed_pool_content_hash("petri_17dim")
    assert sel.startswith("sel-")
    assert seed_pool_content_hash("petri_17dim") == sel  # deterministic
    assert seed_pool_content_hash("other") != sel


def test_seed_pool_content_hash_dir_is_content_addressed(tmp_path: Path) -> None:
    """A pool DIR hashes its survivor bodies (path+sha), so the SAME set yields
    the SAME id regardless of absolute location; a body change moves it."""
    a = tmp_path / "poolA"
    a.mkdir()
    (a / "x.md").write_text("alpha", encoding="utf-8")
    (a / "y.md").write_text("beta", encoding="utf-8")
    h_a = seed_pool_content_hash(str(a))
    assert h_a.startswith("pool-")

    # identical content at a different location → identical id
    b = tmp_path / "elsewhere" / "poolB"
    b.mkdir(parents=True)
    (b / "x.md").write_text("alpha", encoding="utf-8")
    (b / "y.md").write_text("beta", encoding="utf-8")
    assert seed_pool_content_hash(str(b)) == h_a

    # mutate one body → different id
    (b / "x.md").write_text("ALPHA", encoding="utf-8")
    assert seed_pool_content_hash(str(b)) != h_a


def test_seed_pool_content_hash_expands_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `~/pool` selector must content-address the same as its expanded absolute
    path — the runner expands ~, so without expanduser the two would fork the epoch."""
    home = tmp_path / "home"
    pool = home / "pool"
    pool.mkdir(parents=True)
    (pool / "s.md").write_text("seed", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    assert seed_pool_content_hash("~/pool") == seed_pool_content_hash(str(pool))
    assert seed_pool_content_hash("~/pool").startswith("pool-")


def test_seed_pool_content_hash_ignores_manifest_json(tmp_path: Path) -> None:
    """A pool dir's hash is its ``.md`` BODIES only — the assembler's
    ``manifest.json`` (and its ``generated_at`` timestamp) must NOT move it.

    Regression for the masked bug: the pre-fix ``rglob("*")`` folded
    ``manifest.json`` into the hash, so the runtime hash on the live pool dir
    (manifest present) diverged from the assembler's body-only hash AND changed
    whenever the manifest timestamp changed — fragmenting identical survivor
    bodies into different epochs. The masking earlier test re-hashed a
    bodies-only COPY; this one keeps the manifest IN the dir and asserts (a) the
    hash equals the bodies-only hash and (b) it is invariant when the manifest's
    timestamp changes.
    """
    pool = tmp_path / "pool"
    pool.mkdir()
    (pool / "a.md").write_text("body-a", encoding="utf-8")
    (pool / "b.md").write_text("body-b", encoding="utf-8")

    # Reference: bodies only (no manifest in the dir).
    bodies_only = seed_pool_content_hash(str(pool))
    assert bodies_only.startswith("pool-")

    # (a) Adding manifest.json with a timestamp must not move the hash.
    (pool / "manifest.json").write_text(
        '{"generated_at": "2026-05-30T00:00:00+00:00", "x": 1}', encoding="utf-8"
    )
    with_manifest = seed_pool_content_hash(str(pool))
    assert with_manifest == bodies_only

    # (b) Mutating ONLY the manifest's timestamp must not move the hash.
    (pool / "manifest.json").write_text(
        '{"generated_at": "2099-12-31T23:59:59+00:00", "x": 2}', encoding="utf-8"
    )
    assert seed_pool_content_hash(str(pool)) == bodies_only

    # An UNRELATED non-.md incidental file is likewise excluded.
    (pool / "notes.txt").write_text("scratch", encoding="utf-8")
    assert seed_pool_content_hash(str(pool)) == bodies_only

    # But a real .md body edit STILL moves the hash (the fix did not over-narrow).
    (pool / "a.md").write_text("body-a-EDITED", encoding="utf-8")
    assert seed_pool_content_hash(str(pool)) != bodies_only
