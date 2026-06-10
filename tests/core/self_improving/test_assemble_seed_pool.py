"""B1 — deterministic seed-pool assembly (``scripts/assemble_seed_pool.py``).

Pins the four invariants the upcoming 10-cycle depends on:

1. Stable time-sort by ``gen_tag`` picks the highest gen tags (NOT mtime), with a
   legacy bare ``gen1`` sorting below ``gen-2605-*``.
2. The valid-survivor filter drops PHANTOM survivors (id in state but body
   missing) and any id not in ``state.json["survivors"]``.
3. Determinism — identical inputs yield an identical pool file set and an
   identical content hash across two independent runs.
4. Flat ``.md`` copy + manifest correctness, including ``candidates_evolved/``
   bodies, with the manifest hash matching ``seed_pool_content_hash(out)``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.self_improving.loop.observe.baseline_epoch import seed_pool_content_hash
from scripts.assemble_seed_pool import (
    _assert_safe_dest_basename,
    _split_run_ids,
    assemble_pool,
    collect_valid_survivors,
    parse_gen_tag_key,
    select_runs,
)


def _write_run(
    seeds_root: Path,
    *,
    run_id: str,
    gen_tag: str,
    survivors_state: list[str],
    bodies: dict[str, str],
    rel_subdir: str = "candidates",
) -> Path:
    """Create one synthetic seed-generation run dir under ``seeds_root``.

    ``survivors_state`` is the canonical ``state.json["survivors"]`` id list.
    ``bodies`` maps survivor_id -> body text for which an actual ``.md`` file is
    written under ``rel_subdir`` (omit an id from ``bodies`` to make it a phantom:
    listed in state, no body on disk). ``survivors.json`` lists every id in
    ``survivors_state`` so the body-existence filter is what drops phantoms.
    """
    run_dir = seeds_root / run_id
    body_dir = run_dir / rel_subdir
    body_dir.mkdir(parents=True, exist_ok=True)

    survivor_entries = []
    for survivor_id in survivors_state:
        rel_path = f"{rel_subdir}/{survivor_id}.md"
        survivor_entries.append({"id": survivor_id, "path": rel_path, "elo_rating": 1000.0})
        body_text = bodies.get(survivor_id)
        if body_text is not None:
            (run_dir / rel_path).write_text(body_text, encoding="utf-8")

    (run_dir / "state.json").write_text(
        json.dumps({"run_id": run_id, "gen_tag": gen_tag, "survivors": survivors_state}),
        encoding="utf-8",
    )
    (run_dir / "survivors.json").write_text(
        json.dumps({"run_id": run_id, "gen_tag": gen_tag, "survivors": survivor_entries}),
        encoding="utf-8",
    )
    return run_dir


@pytest.fixture
def seeds_tree(tmp_path: Path) -> Path:
    """A synthetic seeds root with 5 runs across distinct gen_tags.

    - gen-2605-4 / gen-2605-3 : the two highest tags (should be selected by N=2).
    - gen-2605-2 / gen-2605-1 : lower 2605 tags (should NOT be selected).
    - gen1                    : legacy bare tag (lowest; never selected).

    gen-2605-3 carries a PHANTOM survivor (``...-phantom`` is in state but has no
    body) plus a ``candidates_evolved/`` body to exercise that path.
    """
    seeds_root = tmp_path / "seeds"
    seeds_root.mkdir()

    _write_run(
        seeds_root,
        run_id="gen-2605-4-unfaithful_thinking",
        gen_tag="gen-2605-4",
        survivors_state=["g4-001", "g4-002"],
        bodies={"g4-001": "g4 body one\n", "g4-002": "g4 body two\n"},
    )
    _write_run(
        seeds_root,
        run_id="gen-2605-3-broken_tool_use",
        gen_tag="gen-2605-3",
        survivors_state=["g3-001", "g3-phantom", "g3-evolved"],
        # g3-phantom is in state but gets no body file -> must be dropped.
        bodies={"g3-001": "g3 body one\n"},
    )
    # Add an evolved-path survivor to gen-2605-3 (separate subdir).
    g3_dir = seeds_root / "gen-2605-3-broken_tool_use"
    (g3_dir / "candidates_evolved").mkdir()
    (g3_dir / "candidates_evolved" / "g3-evolved.md").write_text("g3 evolved\n", encoding="utf-8")
    survivors_meta = json.loads((g3_dir / "survivors.json").read_text(encoding="utf-8"))
    for entry in survivors_meta["survivors"]:
        if entry["id"] == "g3-evolved":
            entry["path"] = "candidates_evolved/g3-evolved.md"
    (g3_dir / "survivors.json").write_text(json.dumps(survivors_meta), encoding="utf-8")

    _write_run(
        seeds_root,
        run_id="gen-2605-2-redundant_tool_invocation",
        gen_tag="gen-2605-2",
        survivors_state=["g2-001"],
        bodies={"g2-001": "g2 body\n"},
    )
    _write_run(
        seeds_root,
        run_id="gen-2605-1-redundant_tool_invocation",
        gen_tag="gen-2605-1",
        survivors_state=["g1x-001"],
        bodies={"g1x-001": "g1x body\n"},
    )
    _write_run(
        seeds_root,
        run_id="gen1-broken_tool_use",
        gen_tag="gen1",
        survivors_state=["legacy-001"],
        bodies={"legacy-001": "legacy body\n"},
    )
    return seeds_root


def test_parse_gen_tag_key_orders_2605_above_legacy() -> None:
    assert parse_gen_tag_key("gen-2605-4") == (2605, 4)
    assert parse_gen_tag_key("gen-2605-3") == (2605, 3)
    assert parse_gen_tag_key("gen1") == (1,)
    # Descending sort puts the highest tags first; legacy gen1 sorts last.
    keys = [parse_gen_tag_key(t) for t in ["gen1", "gen-2605-1", "gen-2605-4", "gen-2605-3"]]
    assert sorted(keys, reverse=True) == [(2605, 4), (2605, 3), (2605, 1), (1,)]


def test_parse_gen_tag_key_malformed_returns_none() -> None:
    # FIX 2/3: anything outside the two accepted shapes (gen-<stamp>-<counter>
    # or legacy gen<n>) is malformed -> None, so it sorts lowest at the caller.
    assert parse_gen_tag_key("") is None
    assert parse_gen_tag_key("gen-weird") is None
    assert parse_gen_tag_key("genfoo") is None
    assert parse_gen_tag_key("2605-4") is None  # no gen prefix
    # A non-numeric trailing segment never raises but is malformed (not (2605,4)).
    assert parse_gen_tag_key("gen-2605-4-unfaithful") is None
    # FIX 3: a spurious extra numeric segment must NOT parse above gen-2605-4.
    assert parse_gen_tag_key("gen-2605-4-999") is None


def test_select_runs_picks_two_highest_gen_tags(seeds_tree: Path) -> None:
    seeds_root = seeds_tree
    selected = select_runs(seeds_root, runs=2, per_run=None)
    assert [run.run_id for run in selected] == [
        "gen-2605-4-unfaithful_thinking",
        "gen-2605-3-broken_tool_use",
    ]
    # gen-2605-2 / gen-2605-1 / gen1 are NOT selected.
    assert all("gen-2605-2" not in run.run_id for run in selected)
    assert all(not run.run_id.startswith("gen1-") for run in selected)


def test_phantom_and_non_state_ids_are_dropped(seeds_tree: Path) -> None:
    seeds_root = seeds_tree
    g3_dir = seeds_root / "gen-2605-3-broken_tool_use"
    valid = collect_valid_survivors(g3_dir, per_run=None)
    valid_ids = [survivor_id for survivor_id, _ in valid]
    # g3-phantom is in state but has no body -> dropped. g3-001 + g3-evolved kept.
    assert "g3-phantom" not in valid_ids
    assert valid_ids == ["g3-001", "g3-evolved"]


def test_id_not_in_state_is_dropped(tmp_path: Path) -> None:
    seeds_root = tmp_path / "seeds"
    seeds_root.mkdir()
    run_dir = _write_run(
        seeds_root,
        run_id="gen-2605-9-x",
        gen_tag="gen-2605-9",
        survivors_state=["keep-001"],
        bodies={"keep-001": "kept\n"},
    )
    # Add a survivors.json entry + body for an id that is NOT in state.json.
    (run_dir / "candidates" / "stray-001.md").write_text("stray\n", encoding="utf-8")
    survivors_meta = json.loads((run_dir / "survivors.json").read_text(encoding="utf-8"))
    survivors_meta["survivors"].append(
        {"id": "stray-001", "path": "candidates/stray-001.md", "elo_rating": 999.0}
    )
    (run_dir / "survivors.json").write_text(json.dumps(survivors_meta), encoding="utf-8")

    valid_ids = [survivor_id for survivor_id, _ in collect_valid_survivors(run_dir, per_run=None)]
    assert valid_ids == ["keep-001"]


def test_evolved_path_body_is_copied(seeds_tree: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "pool"
    assemble_pool(
        seeds_root=seeds_tree,
        out_dir=out_dir,
        runs=2,
        per_run=None,
        force=False,
        now="2026-05-30T00:00:00+00:00",
    )
    evolved_pool_body = out_dir / "g3-evolved.md"
    assert evolved_pool_body.is_file()
    assert evolved_pool_body.read_text(encoding="utf-8") == "g3 evolved\n"


def test_flat_copy_and_manifest_correctness(seeds_tree: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "pool"
    manifest = assemble_pool(
        seeds_root=seeds_tree,
        out_dir=out_dir,
        runs=2,
        per_run=None,
        force=False,
        now="2026-05-30T00:00:00+00:00",
    )

    md_files = sorted(p.name for p in out_dir.glob("*.md"))
    # 2 from gen-2605-4 + (g3-001, g3-evolved) from gen-2605-3 (phantom dropped) = 4.
    assert md_files == ["g3-001.md", "g3-evolved.md", "g4-001.md", "g4-002.md"]
    # No tier subdirs — flat pool.
    assert not [p for p in out_dir.iterdir() if p.is_dir()]

    assert manifest["total_survivors"] == 4
    assert manifest["selected_run_ids"] == [
        "gen-2605-4-unfaithful_thinking",
        "gen-2605-3-broken_tool_use",
    ]
    by_run = {run["run_id"]: run for run in manifest["runs"]}
    assert by_run["gen-2605-4-unfaithful_thinking"]["survivor_ids"] == ["g4-001", "g4-002"]
    assert by_run["gen-2605-3-broken_tool_use"]["survivor_ids"] == ["g3-001", "g3-evolved"]
    assert manifest["generated_at"] == "2026-05-30T00:00:00+00:00"

    # Manifest content_hash matches a fresh hash of the ACTUAL out dir — the one
    # that NOW holds manifest.json. ``seed_pool_content_hash`` hashes only the
    # ``.md`` bodies, so the runtime hash on the live dir equals the assembler's
    # body-only hash (recorded before the manifest was written). This is the
    # masked-bug guard: the pre-fix ``rglob("*")`` folded manifest.json's
    # timestamp into the hash, so this equality FAILED on the live dir.
    assert (out_dir / "manifest.json").is_file()
    assert manifest["content_hash"] == seed_pool_content_hash(str(out_dir))
    assert manifest["content_hash"].startswith("pool-")

    # Sanity: it also equals a bodies-only sibling copy (manifest absent), proving
    # the two are one and the same identity regardless of the incidental file.
    bodies_only = tmp_path / "bodies_only"
    bodies_only.mkdir()
    for md in out_dir.glob("*.md"):
        (bodies_only / md.name).write_text(md.read_text(encoding="utf-8"), encoding="utf-8")
    assert manifest["content_hash"] == seed_pool_content_hash(str(bodies_only))


def test_runtime_hash_invariant_to_manifest_timestamp(seeds_tree: Path, tmp_path: Path) -> None:
    """End-to-end: assembling the SAME survivor bodies with DIFFERENT ``--now``
    timestamps yields the SAME runtime ``seed_pool_content_hash`` on the live pool
    dirs (manifest present). Regression for the non-determinism the masked bug
    introduced — a re-assembly with a fresh timestamp must NOT fork the epoch.
    """
    out_a = tmp_path / "pool_a"
    out_b = tmp_path / "pool_b"
    manifest_a = assemble_pool(
        seeds_root=seeds_tree,
        out_dir=out_a,
        runs=2,
        per_run=None,
        force=False,
        now="2026-05-30T00:00:00+00:00",
    )
    manifest_b = assemble_pool(
        seeds_root=seeds_tree,
        out_dir=out_b,
        runs=2,
        per_run=None,
        force=False,
        now="2099-12-31T23:59:59+00:00",  # different timestamp
    )
    # The two manifests carry DIFFERENT generated_at...
    assert manifest_a["generated_at"] != manifest_b["generated_at"]
    # ...yet the runtime hash on each live dir (manifest present) is identical.
    hash_a = seed_pool_content_hash(str(out_a))
    hash_b = seed_pool_content_hash(str(out_b))
    assert hash_a == hash_b == manifest_a["content_hash"] == manifest_b["content_hash"]


def test_determinism_same_inputs_same_pool_and_hash(seeds_tree: Path, tmp_path: Path) -> None:
    out_a = tmp_path / "pool_a"
    out_b = tmp_path / "pool_b"
    manifest_a = assemble_pool(
        seeds_root=seeds_tree,
        out_dir=out_a,
        runs=2,
        per_run=None,
        force=False,
        now="2026-05-30T00:00:00+00:00",
    )
    manifest_b = assemble_pool(
        seeds_root=seeds_tree,
        out_dir=out_b,
        runs=2,
        per_run=None,
        force=False,
        now="2026-05-30T00:00:00+00:00",
    )
    assert sorted(p.name for p in out_a.glob("*.md")) == sorted(p.name for p in out_b.glob("*.md"))
    assert manifest_a["content_hash"] == manifest_b["content_hash"]
    assert manifest_a["runs"] == manifest_b["runs"]


def test_per_run_cap_is_deterministic(seeds_tree: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "pool"
    manifest = assemble_pool(
        seeds_root=seeds_tree,
        out_dir=out_dir,
        runs=2,
        per_run=1,
        force=False,
        now=None,
    )
    # 1 survivor per selected run -> 2 total; capped survivors are the id-sorted first.
    assert manifest["total_survivors"] == 2
    by_run = {run["run_id"]: run for run in manifest["runs"]}
    assert by_run["gen-2605-4-unfaithful_thinking"]["survivor_ids"] == ["g4-001"]
    assert by_run["gen-2605-3-broken_tool_use"]["survivor_ids"] == ["g3-001"]


def test_refuse_nonempty_out_without_force(seeds_tree: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "pool"
    out_dir.mkdir()
    (out_dir / "preexisting.md").write_text("do not clobber\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        assemble_pool(
            seeds_root=seeds_tree,
            out_dir=out_dir,
            runs=2,
            per_run=None,
            force=False,
            now=None,
        )
    # The pre-existing file is untouched.
    assert (out_dir / "preexisting.md").read_text(encoding="utf-8") == "do not clobber\n"


def test_force_overwrites_nonempty_out(seeds_tree: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "pool"
    out_dir.mkdir()
    (out_dir / "stale.md").write_text("stale\n", encoding="utf-8")
    assemble_pool(
        seeds_root=seeds_tree,
        out_dir=out_dir,
        runs=2,
        per_run=None,
        force=True,
        now=None,
    )
    # Stale file is gone; only fresh pool bodies + manifest remain.
    assert not (out_dir / "stale.md").exists()
    assert sorted(p.name for p in out_dir.glob("*.md")) == [
        "g3-001.md",
        "g3-evolved.md",
        "g4-001.md",
        "g4-002.md",
    ]


def test_no_valid_survivors_raises(tmp_path: Path) -> None:
    seeds_root = tmp_path / "seeds"
    seeds_root.mkdir()
    # A run whose only survivor is a phantom (no body) -> zero valid -> error.
    _write_run(
        seeds_root,
        run_id="gen-2605-1-x",
        gen_tag="gen-2605-1",
        survivors_state=["phantom-only"],
        bodies={},
    )
    out_dir = tmp_path / "pool"
    with pytest.raises(SystemExit):
        assemble_pool(
            seeds_root=seeds_root,
            out_dir=out_dir,
            runs=2,
            per_run=None,
            force=False,
            now=None,
        )


def test_missing_seeds_root_raises(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        select_runs(tmp_path / "does-not-exist", runs=2, per_run=None)


# --- FIX 1: duplicate destination basename across selected runs --------------


def test_duplicate_survivor_id_across_runs_fails_closed(tmp_path: Path) -> None:
    # Two selected runs each contain a VALID survivor with the SAME id. The flat
    # pool would write <id>.md twice (silent overwrite + manifest over-count), so
    # assembly must fail closed naming the colliding id.
    seeds_root = tmp_path / "seeds"
    seeds_root.mkdir()
    _write_run(
        seeds_root,
        run_id="gen-2605-4-a",
        gen_tag="gen-2605-4",
        survivors_state=["dup-001"],
        bodies={"dup-001": "from run four\n"},
    )
    _write_run(
        seeds_root,
        run_id="gen-2605-3-b",
        gen_tag="gen-2605-3",
        survivors_state=["dup-001"],
        bodies={"dup-001": "from run three\n"},
    )
    out_dir = tmp_path / "pool"
    with pytest.raises(SystemExit) as excinfo:
        assemble_pool(
            seeds_root=seeds_root,
            out_dir=out_dir,
            runs=2,
            per_run=None,
            force=False,
            now=None,
        )
    message = str(excinfo.value)
    assert "dup-001" in message
    # Both colliding run_ids are surfaced.
    assert "gen-2605-4-a" in message
    assert "gen-2605-3-b" in message
    # Fail-closed BEFORE writing: no pool dir was created.
    assert not out_dir.exists()


# --- survivor_id dest-basename path-escape guard -----------------------------


@pytest.mark.parametrize(
    "bad_id",
    ["evil/../escape", "sub/dir", "..", ".", "/abs", "back\\slash", ""],
)
def test_assert_safe_dest_basename_rejects_escapes(bad_id: str) -> None:
    """An id that is not a single safe path segment fails closed (SystemExit
    naming the bad id), so it can never be copied to a dest outside the pool."""
    with pytest.raises(SystemExit) as excinfo:
        _assert_safe_dest_basename(bad_id, run_id="gen-2605-4-x")
    assert repr(bad_id) in str(excinfo.value)


def test_assert_safe_dest_basename_accepts_normal_ids() -> None:
    """A normal gen_tag-prefixed survivor id is a valid single segment."""
    _assert_safe_dest_basename("gen-2605-4-003-e2b9759a", run_id="gen-2605-4-x")


def test_assemble_pool_fails_closed_on_escaping_survivor_id(tmp_path: Path) -> None:
    """A survivor whose id contains ``/`` (run-local body, so it passes the
    valid-survivor filter) would copy to ``pool_dir / sub/evil.md`` — escaping the
    flat pool. assemble_pool must fail closed BEFORE writing, naming the bad id.
    """
    seeds_root = tmp_path / "seeds"
    run_dir = seeds_root / "gen-2605-4-x"
    body_rel = "candidates/sub/evil.md"  # run-local nested body for a "/"-id
    body_abs = run_dir / body_rel
    body_abs.parent.mkdir(parents=True, exist_ok=True)
    body_abs.write_text("escaping body\n", encoding="utf-8")
    # The id itself carries a ``/`` — its body lives at a run-local nested path, so
    # the valid-survivor filter accepts it. Only the dest-basename guard stops it.
    (run_dir / "state.json").write_text(
        json.dumps({"gen_tag": "gen-2605-4", "survivors": ["sub/evil"]}),
        encoding="utf-8",
    )
    (run_dir / "survivors.json").write_text(
        json.dumps({"survivors": [{"id": "sub/evil", "path": body_rel, "elo_rating": 1000.0}]}),
        encoding="utf-8",
    )
    out_dir = tmp_path / "pool"
    with pytest.raises(SystemExit) as excinfo:
        assemble_pool(
            seeds_root=seeds_root,
            out_dir=out_dir,
            runs=2,
            per_run=None,
            force=False,
            now=None,
        )
    assert "sub/evil" in str(excinfo.value)
    # No stray escaped file was written outside the pool.
    assert not (out_dir / "sub").exists()


# --- FIX 2: missing/empty gen_tag sorts lowest, never selected ---------------


def test_missing_gen_tag_sorts_lowest_not_selected(tmp_path: Path) -> None:
    # A run with an empty gen_tag must sort LOWEST (never beat a well-formed run
    # via its directory name) — even when its dir name looks like a high tag.
    seeds_root = tmp_path / "seeds"
    seeds_root.mkdir()
    _write_run(
        seeds_root,
        run_id="gen-2605-2-clean",
        gen_tag="gen-2605-2",
        survivors_state=["clean-001"],
        bodies={"clean-001": "clean body\n"},
    )
    # Directory name LOOKS like the newest run, but its gen_tag is empty.
    _write_run(
        seeds_root,
        run_id="gen-9999-x-malformed",
        gen_tag="",
        survivors_state=["bad-001"],
        bodies={"bad-001": "malformed body\n"},
    )
    selected = select_runs(seeds_root, runs=1, per_run=None)
    assert [run.run_id for run in selected] == ["gen-2605-2-clean"]


# --- FIX 3: spurious extra numeric segment does not outrank a clean tag -------


def test_extra_numeric_segment_does_not_outrank_clean_tag(tmp_path: Path) -> None:
    # gen-2605-4-999 must NOT tuple-compare above gen-2605-4; the malformed run
    # sorts lowest, so the clean gen-2605-4 run is selected.
    seeds_root = tmp_path / "seeds"
    seeds_root.mkdir()
    _write_run(
        seeds_root,
        run_id="gen-2605-4-clean",
        gen_tag="gen-2605-4",
        survivors_state=["clean-001"],
        bodies={"clean-001": "clean body\n"},
    )
    _write_run(
        seeds_root,
        run_id="gen-2605-4-999-spurious",
        gen_tag="gen-2605-4-999",
        survivors_state=["spurious-001"],
        bodies={"spurious-001": "spurious body\n"},
    )
    selected = select_runs(seeds_root, runs=1, per_run=None)
    assert [run.run_id for run in selected] == ["gen-2605-4-clean"]


# --- Tie-break determinism: same gen_tag -> stable order by run_id ------------


def test_same_gen_tag_tie_breaks_by_run_id(tmp_path: Path) -> None:
    # Two runs share gen_tag; descending (sort_key, run_id) is the deterministic
    # tie-break, so the higher run_id sorts first regardless of fs iteration.
    seeds_root = tmp_path / "seeds"
    seeds_root.mkdir()
    _write_run(
        seeds_root,
        run_id="gen-2605-4-alpha",
        gen_tag="gen-2605-4",
        survivors_state=["a-001"],
        bodies={"a-001": "alpha\n"},
    )
    _write_run(
        seeds_root,
        run_id="gen-2605-4-beta",
        gen_tag="gen-2605-4",
        survivors_state=["b-001"],
        bodies={"b-001": "beta\n"},
    )
    selected = select_runs(seeds_root, runs=2, per_run=None)
    # Descending run_id tie-break: "...beta" > "...alpha".
    assert [run.run_id for run in selected] == [
        "gen-2605-4-beta",
        "gen-2605-4-alpha",
    ]


# --- FIX 4: absolute / escaping survivor body paths are dropped --------------


def test_absolute_and_escaping_paths_are_dropped(tmp_path: Path) -> None:
    seeds_root = tmp_path / "seeds"
    seeds_root.mkdir()
    run_dir = _write_run(
        seeds_root,
        run_id="gen-2605-5-paths",
        gen_tag="gen-2605-5",
        survivors_state=["local-001"],
        bodies={"local-001": "run-local body\n"},
    )

    # A body that physically EXISTS outside the run dir (would be accepted if the
    # path were trusted blindly).
    outside_body = tmp_path / "outside.md"
    outside_body.write_text("absolute escape\n", encoding="utf-8")
    # A sibling run holding a body reachable via ``../``.
    other_run = seeds_root / "gen-2605-9-other"
    (other_run / "candidates").mkdir(parents=True)
    (other_run / "candidates" / "escape.md").write_text("relative escape\n", encoding="utf-8")

    survivors_meta = json.loads((run_dir / "survivors.json").read_text(encoding="utf-8"))
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    state["survivors"].extend(["abs-001", "rel-001"])
    survivors_meta["survivors"].append(
        {"id": "abs-001", "path": str(outside_body), "elo_rating": 1.0}
    )
    survivors_meta["survivors"].append(
        {
            "id": "rel-001",
            "path": "../gen-2605-9-other/candidates/escape.md",
            "elo_rating": 1.0,
        }
    )
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (run_dir / "survivors.json").write_text(json.dumps(survivors_meta), encoding="utf-8")

    valid_ids = [survivor_id for survivor_id, _ in collect_valid_survivors(run_dir, per_run=None)]
    # Only the run-local survivor survives; both escapes are dropped as invalid.
    assert valid_ids == ["local-001"]
    assert "abs-001" not in valid_ids
    assert "rel-001" not in valid_ids


# --------------------------------------------------------------------------- #
# E2 — explicit run selection for the version-frozen held-out bench           #
# --------------------------------------------------------------------------- #
def test_split_run_ids_strips_dedupes_and_drops_blanks() -> None:
    # Whitespace stripped, empties dropped (trailing comma / blank value), dups
    # de-duped while first-seen order is preserved.
    assert _split_run_ids("") == ()
    assert _split_run_ids("  ") == ()
    assert _split_run_ids("a, b ,c,") == ("a", "b", "c")
    assert _split_run_ids("a,a,b,a") == ("a", "b")


def test_select_runs_explicit_pins_exact_disjoint_set(seeds_tree: Path) -> None:
    """E2: --select-runs pins EXACTLY the named runs (ignoring --runs) and the
    set is DISJOINT from the default top-N selection pool."""
    held_out_ids = (
        "gen-2605-1-redundant_tool_invocation",
        "gen-2605-2-redundant_tool_invocation",
        "gen1-broken_tool_use",
    )
    selected = select_runs(
        seeds_tree,
        runs=2,  # ignored in explicit mode
        per_run=None,
        select_run_ids=held_out_ids,
    )
    selected_ids = {run.run_id for run in selected}
    assert selected_ids == set(held_out_ids)
    # The default top-N pool is gen-2605-4 + gen-2605-3 — DISJOINT from held-out.
    top_n = {run.run_id for run in select_runs(seeds_tree, runs=2, per_run=None)}
    assert top_n == {"gen-2605-4-unfaithful_thinking", "gen-2605-3-broken_tool_use"}
    assert selected_ids.isdisjoint(top_n), "held-out bench must not overlap the selection pool"


def test_select_runs_explicit_missing_id_is_fatal(seeds_tree: Path) -> None:
    """A --select-runs id matching no run dir is fatal (a typo must not silently
    shrink a frozen held-out bench)."""
    with pytest.raises(SystemExit, match="not found"):
        select_runs(
            seeds_tree,
            runs=2,
            per_run=None,
            select_run_ids=("gen-2605-1-redundant_tool_invocation", "gen-9999-typo"),
        )


def test_select_runs_exclude_drops_from_top_n(seeds_tree: Path) -> None:
    """--exclude-runs drops a run from top-N so the freed slot is filled by the
    next-highest remaining run."""
    selected = select_runs(
        seeds_tree,
        runs=2,
        per_run=None,
        exclude_run_ids=("gen-2605-4-unfaithful_thinking",),
    )
    # Without gen-2605-4, the top 2 become gen-2605-3 then gen-2605-2.
    assert [run.run_id for run in selected] == [
        "gen-2605-3-broken_tool_use",
        "gen-2605-2-redundant_tool_invocation",
    ]


def test_select_runs_select_and_exclude_contradiction_is_fatal(seeds_tree: Path) -> None:
    """A run id in BOTH --select-runs and --exclude-runs is a fatal contradiction."""
    with pytest.raises(SystemExit, match="BOTH"):
        select_runs(
            seeds_tree,
            runs=2,
            per_run=None,
            select_run_ids=("gen-2605-1-redundant_tool_invocation",),
            exclude_run_ids=("gen-2605-1-redundant_tool_invocation",),
        )


def test_assemble_held_out_is_deterministic_and_disjoint(seeds_tree: Path, tmp_path: Path) -> None:
    """The explicitly-selected held-out bench is content-hash stable across two
    independent assembles AND shares no survivor body with the selection pool."""
    held_out_ids = (
        "gen-2605-1-redundant_tool_invocation",
        "gen-2605-2-redundant_tool_invocation",
        "gen1-broken_tool_use",
    )
    held_out_a = tmp_path / "held_out_a"
    held_out_b = tmp_path / "held_out_b"
    manifest_a = assemble_pool(
        seeds_root=seeds_tree,
        out_dir=held_out_a,
        runs=2,
        per_run=None,
        force=False,
        now="2026-05-30T00:00:00+00:00",
        select_run_ids=held_out_ids,
    )
    manifest_b = assemble_pool(
        seeds_root=seeds_tree,
        out_dir=held_out_b,
        runs=2,
        per_run=None,
        force=False,
        now="2026-05-30T00:00:00+00:00",
        select_run_ids=held_out_ids,
    )
    # Deterministic — identical content hash + manifest provenance.
    assert manifest_a["content_hash"] == manifest_b["content_hash"]
    assert manifest_a["content_hash"].startswith("pool-")
    assert manifest_a["selection_mode"] == "explicit"
    assert manifest_a["select_run_ids"] == sorted(held_out_ids)
    assert set(manifest_a["selected_run_ids"]) == set(held_out_ids)
    # Stable identity re-verified directly against seed_pool_content_hash on a
    # bodies-only sibling (manifest.json is excluded — it is written after the
    # hash is computed and the .md set is what defines identity).
    bodies_only = tmp_path / "bodies_only"
    bodies_only.mkdir()
    for md in held_out_a.glob("*.md"):
        (bodies_only / md.name).write_text(md.read_text(encoding="utf-8"), encoding="utf-8")
    assert manifest_a["content_hash"] == seed_pool_content_hash(str(bodies_only))

    # Disjoint from the default selection pool (gen-2605-4 + gen-2605-3).
    selection_pool = tmp_path / "selection_pool"
    assemble_pool(
        seeds_root=seeds_tree,
        out_dir=selection_pool,
        runs=2,
        per_run=None,
        force=False,
        now="2026-05-30T00:00:00+00:00",
    )
    held_out_bodies = {p.name for p in held_out_a.glob("*.md")}
    selection_bodies = {p.name for p in selection_pool.glob("*.md")}
    assert held_out_bodies.isdisjoint(selection_bodies), (
        "held-out bench bodies must be disjoint from the selection pool"
    )
