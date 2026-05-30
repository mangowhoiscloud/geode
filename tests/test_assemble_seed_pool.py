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
from core.self_improving_loop.baseline_epoch import seed_pool_content_hash
from scripts.assemble_seed_pool import (
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


def test_parse_gen_tag_key_non_numeric_segment_is_graceful() -> None:
    # A non-numeric trailing segment never raises; the numeric prefix still orders.
    assert parse_gen_tag_key("gen-2605-4-unfaithful") == (2605, 4)
    assert parse_gen_tag_key("gen-weird") == ()


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

    # Manifest content_hash matches a fresh hash of the out dir. The manifest.json
    # itself is part of the dir; the recorded hash was computed before it was
    # written, so re-hash a sibling copy holding only the .md bodies.
    bodies_only = tmp_path / "bodies_only"
    bodies_only.mkdir()
    for md in out_dir.glob("*.md"):
        (bodies_only / md.name).write_text(md.read_text(encoding="utf-8"), encoding="utf-8")
    assert manifest["content_hash"] == seed_pool_content_hash(str(bodies_only))
    assert manifest["content_hash"].startswith("pool-")


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
