"""Guard: hub build self-heals the seeds listing (v0.99.x).

The publish chain is sync_run_to_bundle → build_seeds_listing → hub build.
Pre-fix, ``geode hub build`` only READ ``listing.json``; a run synced to
the bundle was silently absent from the hub until someone re-ran the
separate listing step (frontier-2612-bt, 2026-06-12). ``load_seedgen`` now
rebuilds the listing from the seeds dir first, so a synced run always
renders.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from scripts.build_self_improving_hub import load_seedgen


def test_load_seedgen_rebuilds_listing_in_source() -> None:
    src = inspect.getsource(load_seedgen)
    assert "write_listing" in src
    assert "build_seeds_listing" in src


def test_load_seedgen_self_heals_missing_listing(tmp_path: Path) -> None:
    bundle = tmp_path / "docs" / "self-improving" / "petri-bundle"
    run = bundle / "seeds" / "gen-x-broken_tool_use"
    run.mkdir(parents=True)
    (run / "state.json").write_text(
        json.dumps(
            {
                "run_id": "gen-x-broken_tool_use",
                "gen_tag": "gen-x",
                "target_dim": "broken_tool_use",
                "survivors": ["s1", "s2"],
            }
        ),
        encoding="utf-8",
    )
    listing = bundle / "seeds" / "listing.json"
    assert not listing.exists()  # no listing yet — the stale-listing scenario

    rows = load_seedgen(bundle)

    # listing was rebuilt from the seeds dir, and the synced run is present
    assert listing.exists()
    assert any(r.run_id == "gen-x-broken_tool_use" for r in rows)
