"""Stale-dim assemble guard (v0.99.178).

A seed whose ``target_dims`` reference a dim removed from the live fitness
taxonomy (``core.self_improving.fitness.AXIS_TIERS``) is a phantom-dim
hallucination: the audit probes a dimension the loop no longer scores, so
the held-out ruler pins at the floor and the gate rejects every cycle for a
measurement reason. Previously this surfaced only at campaign RUNTIME (the
stale pool had already shipped). ``assemble_pool`` now fails CLOSED at
assemble time so the phantom dim never enters the pipeline. Incident:
held-out ``gen-2605-*-redundant_tool_invocation`` after the dim was dropped
(2026-06-11).
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from scripts.assemble_seed_pool import assemble_pool


def _write_run(
    seeds_root: Path, *, run_id: str, gen_tag: str, survivor_id: str, target_dims: list[str]
) -> None:
    run_dir = seeds_root / run_id
    body_dir = run_dir / "candidates"
    body_dir.mkdir(parents=True, exist_ok=True)
    front = "target_dims: [" + ", ".join(target_dims) + "]"
    (body_dir / f"{survivor_id}.md").write_text(f"---\n{front}\n---\nseed body\n", encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps({"run_id": run_id, "gen_tag": gen_tag, "survivors": [survivor_id]}),
        encoding="utf-8",
    )
    (run_dir / "survivors.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "gen_tag": gen_tag,
                "survivors": [
                    {
                        "id": survivor_id,
                        "path": f"candidates/{survivor_id}.md",
                        "elo_rating": 1000.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_redundant_tool_invocation_is_not_a_live_dim() -> None:
    from core.self_improving.fitness import AXIS_TIERS

    # the dim that triggered the incident must genuinely be absent
    assert "redundant_tool_invocation" not in AXIS_TIERS


def test_assemble_refuses_stale_dim_pool(tmp_path: Path) -> None:
    seeds_root = tmp_path / "seeds"
    seeds_root.mkdir()
    _write_run(
        seeds_root,
        run_id="gen-2605-1-redundant_tool_invocation",
        gen_tag="gen-2605-1",
        survivor_id="stale-001",
        target_dims=["redundant_tool_invocation"],  # removed dim
    )
    out = tmp_path / "pool"
    with pytest.raises(SystemExit) as exc:
        assemble_pool(
            seeds_root=seeds_root,
            out_dir=out,
            runs=1,
            per_run=None,
            force=True,
            now="2026-06-11T00:00:00Z",
        )
    assert "live taxonomy" in str(exc.value) or "AXIS_TIERS" in str(exc.value)
    # the half-written stale pool must not survive
    assert not out.exists() or not list(out.glob("*.md"))


def test_assemble_accepts_live_dim_pool(tmp_path: Path) -> None:
    seeds_root = tmp_path / "seeds"
    seeds_root.mkdir()
    _write_run(
        seeds_root,
        run_id="gen-2605-1-broken_tool_use",
        gen_tag="gen-2605-1",
        survivor_id="live-001",
        target_dims=["broken_tool_use"],  # live dim
    )
    out = tmp_path / "pool"
    manifest = assemble_pool(
        seeds_root=seeds_root,
        out_dir=out,
        runs=1,
        per_run=None,
        force=True,
        now="2026-06-11T00:00:00Z",
    )
    assert manifest["total_survivors"] == 1
    assert (out / "manifest.json").exists()


def test_assemble_pool_wires_the_guard() -> None:
    source = inspect.getsource(assemble_pool)
    assert "validate_pool_target_dims" in source
    assert "AXIS_TIERS" in source
