"""Pin the survivor-path SoT invariant on both writers.

Two producers stamp ``survivors.json`` / ``survivors/`` for a seed run:

1. ``Pipeline._persist_survivors`` (live runs) — must write a path RELATIVE
   to ``run_dir`` so a clone / GitHub-Pages mirror resolves bodies without a
   broken absolute path into the gitignored generation scratch tree.
2. ``scripts/reconcile_seed_bundle.reconcile_run`` (one-shot reconciliation
   of the served bundle) — must (a) write relative paths, (b) make
   ``survivors/`` match the valid survivor set exactly, and (c) drop a
   survivor whose body ``<id>.md`` is absent from both body subdirs.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any

from plugins.seed_generation.agents.base import BaseSeedAgent, SeedAgentResult
from plugins.seed_generation.orchestrator import (
    Pipeline,
    PipelineRegistry,
    PipelineState,
)

# Repo root = tests/plugins/seed_generation/<this file>.parents[3].
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_reconcile_module() -> Any:
    """Import scripts/reconcile_seed_bundle.py by path (scripts/ isn't a pkg)."""
    script_path = _REPO_ROOT / "scripts" / "reconcile_seed_bundle.py"
    spec = importlib.util.spec_from_file_location("reconcile_seed_bundle", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Writer 1 — Pipeline._persist_survivors (live run)
# ---------------------------------------------------------------------------


class _NoopAgent(BaseSeedAgent):
    """Concrete agent that returns success without touching state."""

    def __init__(self, role: str) -> None:
        super().__init__(role=role, model="dummy")

    async def aexecute(self, state: Any) -> SeedAgentResult:
        return SeedAgentResult(role=self.role)


def _registry_with_noop_agents() -> PipelineRegistry:
    reg = PipelineRegistry()
    for role in (
        "generator",
        "proximity",
        "critic",
        "pilot",
        "ranker",
        "evolver",
        "meta_reviewer",
    ):
        reg.register(_NoopAgent(role))
    return reg


def _seed_candidate_md(run_dir: Path, subdir: str, cid: str) -> Path:
    body_dir = run_dir / subdir
    body_dir.mkdir(parents=True, exist_ok=True)
    path = body_dir / f"{cid}.md"
    path.write_text(f"# {cid}\n\nbody for {cid}\n", encoding="utf-8")
    return path


def test_persist_survivors_writes_relative_path(tmp_path: Path) -> None:
    """survivors.json ``path`` is run-dir-relative, never absolute."""
    state = PipelineState(
        run_id="t-rel",
        target_dim="broken_tool_use",
        gen_tag="gen2",
        candidates_requested=2,
        run_dir=tmp_path,
    )
    cand_a = _seed_candidate_md(tmp_path, "candidates", "c-00")
    cand_b = _seed_candidate_md(tmp_path, "candidates_evolved", "c-01-ev")
    state.candidates = [
        {"id": "c-00", "path": str(cand_a), "target_dim": "broken_tool_use"},
        {"id": "c-01-ev", "path": str(cand_b), "target_dim": "broken_tool_use"},
    ]
    state.survivors = ["c-00", "c-01-ev"]
    state.elo_ratings = {"c-00": 1010.0, "c-01-ev": 1020.0}

    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    asyncio.run(pipeline.arun())

    blob = json.loads((tmp_path / "survivors.json").read_text(encoding="utf-8"))
    paths = {row["id"]: row["path"] for row in blob["survivors"]}
    assert paths == {
        "c-00": "candidates/c-00.md",
        "c-01-ev": "candidates_evolved/c-01-ev.md",
    }
    for path in paths.values():
        assert not path.startswith("/")
        assert not Path(path).is_absolute()


def test_persist_survivors_dir_matches_survivor_set(tmp_path: Path) -> None:
    """survivors/ contains EXACTLY the survivor bodies (no stale extras)."""
    state = PipelineState(
        run_id="t-set",
        target_dim="broken_tool_use",
        gen_tag="gen2",
        candidates_requested=2,
        run_dir=tmp_path,
    )
    cand_a = _seed_candidate_md(tmp_path, "candidates", "c-00")
    _seed_candidate_md(tmp_path, "candidates", "c-99")  # non-survivor body
    state.candidates = [
        {"id": "c-00", "path": str(cand_a), "target_dim": "broken_tool_use"},
    ]
    state.survivors = ["c-00"]

    # Pre-seed a stale file in survivors/ to prove pruning.
    stale_dir = tmp_path / "survivors"
    stale_dir.mkdir(parents=True, exist_ok=True)
    (stale_dir / "c-stale.md").write_text("stale\n", encoding="utf-8")

    pipeline = Pipeline(state=state, registry=_registry_with_noop_agents())
    asyncio.run(pipeline.arun())

    names = sorted(p.name for p in (tmp_path / "survivors").iterdir())
    assert names == ["c-00.md"]


# ---------------------------------------------------------------------------
# Writer 2 — scripts/reconcile_seed_bundle.reconcile_run
# ---------------------------------------------------------------------------


def _make_run(run_dir: Path, *, survivors: list[str], bodies: dict[str, str]) -> None:
    """Build a minimal run dir. ``bodies`` maps id -> subdir for present bodies."""
    run_dir.mkdir(parents=True, exist_ok=True)
    for cid, subdir in bodies.items():
        body_dir = run_dir / subdir
        body_dir.mkdir(parents=True, exist_ok=True)
        (body_dir / f"{cid}.md").write_text(f"# {cid}\n", encoding="utf-8")
    state = {
        "run_id": run_dir.name,
        "gen_tag": "gen1",
        "target_dim": "broken_tool_use",
        "survivors": survivors,
        "elo_ratings": dict.fromkeys(survivors, 1000.0),
        "pilot_scores": {cid: {"status": "ok"} for cid in survivors},
    }
    (run_dir / "state.json").write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def test_reconcile_run_drops_bodyless_and_writes_relative(tmp_path: Path) -> None:
    """reconcile_run drops a body-less id, writes relative paths, and makes
    survivors/ match the valid set."""
    reconcile = _load_reconcile_module()
    run_dir = tmp_path / "seeds" / "gen1-broken_tool_use"
    # s-keep present in candidates, s-evo present in candidates_evolved,
    # s-phantom has NO body anywhere -> must be dropped.
    _make_run(
        run_dir,
        survivors=["s-keep", "s-phantom", "s-evo"],
        bodies={"s-keep": "candidates", "s-evo": "candidates_evolved"},
    )
    # Pre-seed a stale survivors/ file to prove pruning.
    sd = run_dir / "survivors"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "old.md").write_text("old\n", encoding="utf-8")

    summary = reconcile.reconcile_run(run_dir)
    assert "s-phantom" in summary

    # state.json["survivors"] has the phantom pruned, order preserved.
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["survivors"] == ["s-keep", "s-evo"]

    # survivors.json paths are relative + match the valid set.
    blob = json.loads((run_dir / "survivors.json").read_text(encoding="utf-8"))
    paths = {row["id"]: row["path"] for row in blob["survivors"]}
    assert paths == {
        "s-keep": "candidates/s-keep.md",
        "s-evo": "candidates_evolved/s-evo.md",
    }
    for path in paths.values():
        assert not Path(path).is_absolute()

    # survivors/ matches state.json["survivors"] exactly (stale pruned).
    names = sorted(p.name for p in (run_dir / "survivors").iterdir())
    assert names == ["s-evo.md", "s-keep.md"]


def test_reconcile_run_is_idempotent(tmp_path: Path) -> None:
    """A second reconcile reports no drops and a stable survivors/ count."""
    reconcile = _load_reconcile_module()
    run_dir = tmp_path / "seeds" / "gen1-redundant_tool_invocation"
    _make_run(
        run_dir,
        survivors=["a", "b"],
        bodies={"a": "candidates", "b": "candidates"},
    )
    reconcile.reconcile_run(run_dir)
    second = reconcile.reconcile_run(run_dir)
    assert "dropped: []" in second
    assert "2->2" in second
