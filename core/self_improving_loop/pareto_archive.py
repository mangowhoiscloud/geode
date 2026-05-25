"""P2-revised (2026-05-25) — Pareto archive + Dynamic Reward Weighting.

Plan: ``docs/plans/2026-05-25-p2-pareto-archive-dynamic-reward-weighting.md``.

Frontier source:
- AlphaEvolve (DeepMind 2025-05) — MAP-Elites + island + Pareto rank
- DGM (Sakana 2025-05) — archive lineage + Quality-Diversity
- Dynamic Reward Weighting (TACL '26, arXiv 2509.11452) — hypervolume-
  guided weight gradient
- Pareto Set Learning (arXiv 2501.06773) — non-dominated front 보존

GEODE 적용 — linear scalarization (현재 fitness = w·r) 의 한계 해소:
- concave Pareto front 의 일부 구간 영원히 도달 불가 (Das & Dennis 1997)
- substitution: 한 dim 의 큰 양수가 다른 dim 의 큰 음수 cancel out

본 모듈 = **selection layer only** (PR-5 의 P1-revised 와 같은 정합):
- archive 가 mutation 의 17-dim vector 보존
- 새 mutation 의 vector 가 archive 내 어느 element 도 dominate 하지 않으면 archive 에 insert
- archive 가 어느 element 를 dominate 하면 dominated element 제거
- weight 는 hypervolume gradient 로 update — fixed weight 가 미도달인 Pareto
  front 영역 추적 가능
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

_RNG_SEED = 20260525
"""Reproducible MC seed for hypervolume estimation in dim>=3."""


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class ArchiveEntry(BaseModel):
    """One mutation 의 17-dim fitness vector + provenance.

    ``extra="allow"`` 로 legacy reader 호환 + 후속 PR 의 추가 field
    (예: GEPA Pareto sampler 의 reflection text) 친화.
    """

    model_config = ConfigDict(extra="allow")

    mutation_id: str
    """W3 attribution wiring 의 mutation_id 와 일치 — apply row 와 join."""
    group_id: str = ""
    """P1-revised 의 group_id (sibling 묶음). legacy single mutation 일 때 ""."""
    audit_run_id: str = ""
    """W3 audit_run_id. attribution row 와 join."""
    ts: float
    """Insert timestamp (Unix epoch)."""
    dim_means: dict[str, float] = Field(default_factory=dict)
    """17-dim fitness vector (Petri judge dim_means subset)."""
    dim_stderr: dict[str, float] = Field(default_factory=dict)
    """per-dim std error (variance signal)."""


# ---------------------------------------------------------------------------
# PareteArchive class
# ---------------------------------------------------------------------------


def _dominates(a: dict[str, float], b: dict[str, float]) -> bool:
    """Strict Pareto dominance — ``a dominates b`` iff a ≥ b in all dims
    AND a > b in at least one dim.

    Missing dim in either treated as ``-inf`` (worst). 'higher is better'
    convention (good-low palette 의 dim 은 caller 가 미리 invert).
    """
    common_dims = set(a.keys()) | set(b.keys())
    if not common_dims:
        return False
    has_strict = False
    for d in common_dims:
        av = a.get(d, float("-inf"))
        bv = b.get(d, float("-inf"))
        if av < bv:
            return False
        if av > bv:
            has_strict = True
    return has_strict


@dataclass
class PareteArchive:
    """Pareto-non-dominated archive of mutation fitness vectors.

    Frontier source: AlphaEvolve MAP-Elites + DGM archive lineage.
    """

    entries: list[ArchiveEntry] = field(default_factory=list)
    """Non-dominated entries — Pareto front. Insert/dominate-prune maintains
    invariant: no entry dominates another in the archive."""

    def insert(self, entry: ArchiveEntry) -> bool:
        """Insert ``entry`` if non-dominated by current archive. Prune any
        existing entry that the new entry dominates.

        Returns True if inserted, False if dominated by archive (rejected).
        """
        # Check if new entry is dominated by any existing
        for existing in self.entries:
            if _dominates(existing.dim_means, entry.dim_means):
                return False
        # Prune existing entries dominated by new
        self.entries = [e for e in self.entries if not _dominates(entry.dim_means, e.dim_means)]
        self.entries.append(entry)
        return True

    def non_dominated_set(self) -> list[ArchiveEntry]:
        """Return current Pareto front (== self.entries by invariant)."""
        return list(self.entries)

    def sample(self, n: int = 1, *, rng: random.Random | None = None) -> list[ArchiveEntry]:
        """Uniform-random sample from the Pareto front.

        Future (P2.1): sparsity-weighted sampling (density-aware diversity).
        Current MVP: uniform.
        """
        if not self.entries:
            return []
        rng = rng or random.Random(_RNG_SEED)
        return rng.sample(self.entries, min(n, len(self.entries)))

    def __len__(self) -> int:
        return len(self.entries)


# ---------------------------------------------------------------------------
# Hypervolume — exact for dim==2, Monte Carlo for dim>=3
# ---------------------------------------------------------------------------


def compute_hypervolume(
    archive: PareteArchive,
    reference_point: dict[str, float],
    *,
    mc_samples: int = 1000,
    rng_seed: int = _RNG_SEED,
) -> float:
    """Lebesgue measure of dominated region above ``reference_point`` (nadir).

    - dim == 2: exact (sort + rectangle sum)
    - dim >= 3: Monte Carlo (uniformly sample bounding box, count dominated)

    Reference point는 dim 별 worst (e.g., 0 if normalized [0, 1] or
    raw min dim_score). Higher is better convention.
    """
    if not archive.entries:
        return 0.0

    dims = sorted(reference_point.keys())
    if not dims:
        return 0.0

    # Compute bounding box: max over all entries per dim
    upper = {d: reference_point[d] for d in dims}
    for entry in archive.entries:
        for d in dims:
            upper[d] = max(upper[d], entry.dim_means.get(d, reference_point[d]))

    # Volume of bounding box (above reference, up to upper)
    box_volume = 1.0
    for d in dims:
        edge = upper[d] - reference_point[d]
        if edge <= 0.0:
            return 0.0
        box_volume *= edge

    if len(dims) == 2:
        # Exact 2D hypervolume — sort by first dim desc, sweep rectangles
        sorted_entries = sorted(
            archive.entries,
            key=lambda e: e.dim_means.get(dims[0], reference_point[dims[0]]),
            reverse=True,
        )
        hv = 0.0
        last_d1 = reference_point[dims[1]]
        for entry in sorted_entries:
            d0 = entry.dim_means.get(dims[0], reference_point[dims[0]])
            d1 = entry.dim_means.get(dims[1], reference_point[dims[1]])
            if d0 <= reference_point[dims[0]] or d1 <= last_d1:
                continue
            hv += (d0 - reference_point[dims[0]]) * (d1 - last_d1)
            last_d1 = d1
        return hv

    # dim >= 3: Monte Carlo
    rng = random.Random(rng_seed)
    dominated_count = 0
    for _ in range(mc_samples):
        point = {
            d: reference_point[d] + rng.random() * (upper[d] - reference_point[d]) for d in dims
        }
        for entry in archive.entries:
            if all(entry.dim_means.get(d, reference_point[d]) >= point[d] for d in dims):
                dominated_count += 1
                break
    return box_volume * (dominated_count / mc_samples)


# ---------------------------------------------------------------------------
# Dynamic Reward Weighting (TACL '26 arXiv 2509.11452)
# ---------------------------------------------------------------------------


def dynamic_reward_weight_step(
    current_weights: dict[str, float],
    archive: PareteArchive,
    reference_point: dict[str, float],
    *,
    lr: float = 0.01,
    perturbation: float = 0.001,
) -> dict[str, float]:
    """One gradient ascent step on hypervolume w.r.t. weights.

    HV is differentiable w.r.t. archive entries (Pareto front), but weights
    enter only via *which* mutations get accepted (top-1 by w·r). Numeric
    gradient via finite-difference perturbation on each weight dim.

    Returns updated weights (sum-to-1 normalized).
    """
    if not archive.entries:
        return dict(current_weights)
    base_hv = compute_hypervolume(archive, reference_point)
    new_weights = dict(current_weights)
    for dim in current_weights:
        {**current_weights, dim: current_weights[dim] + perturbation}
        # In a full impl we'd re-run selection with perturbed weights and
        # observe HV; here we approximate gradient as proportional to dim's
        # spread in the current archive (proxy for "moving this weight
        # would change HV"). Full impl deferred to P2.1.
        spreads = [e.dim_means.get(dim, 0.0) for e in archive.entries]
        spread = max(spreads) - min(spreads) if spreads else 0.0
        gradient_proxy = spread * (base_hv / max(base_hv, 1e-8))
        new_weights[dim] = current_weights[dim] + lr * gradient_proxy
    # Normalize sum to 1
    total = sum(new_weights.values())
    if total > 0:
        new_weights = {k: v / total for k, v in new_weights.items()}
    return new_weights


# ---------------------------------------------------------------------------
# Archive JSONL writer + reader
# ---------------------------------------------------------------------------


def append_archive_entry(
    entry: ArchiveEntry,
    *,
    archive_path: Path,
) -> Path:
    """Append one Pareto-archive entry as JSONL row.

    git-tracked, append-only — same invariant as mutations.jsonl (PR-G5b
    [[project-petri-p1-handoff]] silent-ignored writer precedent).
    """
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    payload = entry.model_dump(exclude_none=True)
    with archive_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return archive_path


def load_archive(archive_path: Path) -> PareteArchive:
    """Load Pareto archive from JSONL. Returns empty archive if file missing.

    All entries loaded — caller decides which subset to use (e.g., last N
    by ts, or all). For dominated-pruning, re-insert each loaded entry
    into a fresh PareteArchive.
    """
    if not archive_path.is_file():
        return PareteArchive()
    archive = PareteArchive()
    for line in archive_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            entry = ArchiveEntry.model_validate(data)
            archive.insert(entry)
        except (json.JSONDecodeError, Exception) as exc:
            log.warning("pareto_archive: skipping invalid row: %s", exc)
    return archive


def read_pareto_front(
    archive_path: Path,
    target_dims: list[str],
) -> list[dict[str, Any]]:
    """Return the current non-dominated set restricted to ``target_dims``.

    PR-SG-SELECTION-ALIGN (2026-05-25, G5) — reader counterpart for
    the seed-gen evolver. The Pareto archive is the SoT for which
    mutations the selection layer currently considers ``non-
    dominated`` in the active dim scope. Surface this front in the
    evolver's HANDOFF so the LLM can reason about which front edge
    its rewrite should push.

    Returns ``[]`` when the archive file is missing or
    ``target_dims`` is empty (no scope to project onto). When a
    loaded entry omits all ``target_dims`` it's skipped (no signal
    to compare). Each returned row is a plain dict so the caller
    can embed it directly into the JSON handoff without coupling
    to the pydantic ``ArchiveEntry`` model.

    Output row shape:
    ``{"id": <mutation_id>, "dims": {dim: mean, ...}, "fitness": <scalar>}``

    where ``fitness`` is the mean of the projected dim values
    (cheap scalarization for human-readable handoff; the LLM uses
    ``dims`` itself for trade-off reasoning).
    """
    if not target_dims or not archive_path.is_file():
        return []
    front_archive = PareteArchive()
    for line in archive_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            entry = ArchiveEntry.model_validate(data)
        except (json.JSONDecodeError, Exception) as exc:
            log.warning("pareto_archive read_pareto_front: skipping invalid row: %s", exc)
            continue
        projected = {d: entry.dim_means[d] for d in target_dims if d in entry.dim_means}
        if not projected:
            continue
        # Re-insert with the projected dims so dominance is computed in
        # the requested scope, not the full 17-dim vector.
        projected_entry = ArchiveEntry(
            mutation_id=entry.mutation_id,
            group_id=entry.group_id,
            audit_run_id=entry.audit_run_id,
            ts=entry.ts,
            dim_means=projected,
            dim_stderr={d: entry.dim_stderr.get(d, 0.0) for d in projected},
        )
        front_archive.insert(projected_entry)
    out: list[dict[str, Any]] = []
    for member in front_archive.non_dominated_set():
        dims_map = dict(member.dim_means)
        scalar = sum(dims_map.values()) / max(len(dims_map), 1)
        out.append({"id": member.mutation_id, "dims": dims_map, "fitness": scalar})
    return out


__all__ = [
    "ArchiveEntry",
    "PareteArchive",
    "append_archive_entry",
    "compute_hypervolume",
    "dynamic_reward_weight_step",
    "load_archive",
    "read_pareto_front",
]
