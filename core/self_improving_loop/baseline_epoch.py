"""Content-addressed baseline-archive epoch discriminator.

PR-BASELINE-EPOCH (2026-05-30). Baselines produced under different production
logic are not comparable, so the registry partitions them into **epochs** keyed
by a hash of the baseline-production+measurement *spec*. When the spec changes,
the hash changes → a new epoch begins on its own — deterministic, drift-proof,
no manual bump. See ``.claude/skills/baseline-epoch-partition/SKILL.md``.

Hash the **surface** (how a baseline is made), never the **instance** (its
measured values): the spec is logic-version tags + config + per-role model/source
+ seed-pool identity. Instance fields (dim_means / fitness / fitness_stderr /
seeds / ts / commit) are NEVER hashed — including them would make every run its
own epoch.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Version of the spec field-set ITSELF. Bump when the enumerated fields below
#: change. Because it is part of the hashed spec, a bump puts pre-change and
#: post-change baselines in different epochs (correct — the *definition* of a
#: baseline changed) without retroactively recomputing any stored hash.
#:
#: "1" → "2" (E3, 2026-05-30): added ``promote_policy`` to the spec. The promote
#: policy (gate / random / never) is production logic — the gate arm SELECTS on
#: fitness, the random arm coin-flips, the never arm freezes the baseline — so
#: the three arms produce baselines under genuinely different production logic
#: and must not be averaged into one epoch. Old schema-1 rows fall into a prior
#: epoch (correct — no retroactive recompute; the gate arm under schema 2 simply
#: opens a new epoch alongside the legacy gate-only rows).
SPEC_SCHEMA_VERSION = "2"

#: Roles whose (model, source) bind the production+measurement surface. ``lane``
#: is DERIVED from ``source`` (see role_provenance) so it is not hashed.
_SPEC_ROLES = ("auditor", "target", "judge", "mutator")

_HASH_PREFIX_LEN = 12


@dataclass(frozen=True)
class HistoricalSpecOverride:
    """Optional spec fields for backfilling a baseline measured under PRE-current
    production logic, so it hashes to its OWN epoch instead of today's.

    The live promote path never sets these — each ``None`` field falls back to
    the live constant at the call site, so omitting the override reproduces the
    current spec byte-for-byte. The backfill path (a historical baseline whose
    logic differs from today's) supplies the true historical values, e.g. the
    pre-margin-fix vanilla baseline carries ``fitness_formula_version="0"`` /
    ``margin_logic_version="0"`` so it lands in a distinct genesis epoch rather
    than being mis-stamped with the current logic version. ``promote_policy`` is
    a separate first-class param of the registry writer (not bundled here) since
    the live path already threads it.

    ``fitness`` is the historical baseline's MEASURED fitness — when set, the
    registry writer records it verbatim instead of RE-COMPUTING via today's
    ``compute_fitness`` (a historical baseline was scored under its own formula,
    so recomputing would overwrite its measured value with a current-formula
    number). ``None`` → the live behaviour (recompute), so the live promote path
    is unaffected.
    """

    fitness_formula_version: str | None = None
    margin_logic_version: str | None = None
    rubric_version: str | None = None
    dim_set: str | None = None
    fitness: float | None = None


def build_baseline_spec(
    *,
    margin_rule: str,
    margin_logic_version: str,
    fitness_formula_version: str,
    rubric_version: str,
    dim_set: str,
    bench: bool,
    role_provenance: Mapping[str, Mapping[str, str]],
    seed_pool_id: str | None,
    promote_policy: str = "gate",
) -> dict[str, Any]:
    """Assemble the canonical baseline spec (the surface that is hashed).

    ``role_provenance`` is the ``{role: {model, source, lane}}`` block from
    :mod:`core.self_improving_loop.role_provenance`; only ``model`` + ``source``
    enter the spec (``lane`` is derived from ``source``, so hashing it would be
    redundant). ``seed_pool_id`` is the seed pool's *identity* (content hash),
    not its bodies — ``None``/`""` when no pool is pinned (the pool axis then
    contributes a stable empty value rather than fragmenting epochs).

    ``promote_policy`` (E3, 2026-05-30; schema 2) — the control-arm promote
    policy: ``"gate"`` (selection arm, the fitness gate), ``"random"``
    (random-accept control), or ``"never"`` (no-mutation floor). It is part of
    the hashed surface because the three arms produce baselines under different
    production logic, so a gate spec and a random spec hash to DIFFERENT epochs
    (the 3-arm comparison happens via the per-cycle held-out records tagged by
    arm, NOT by averaging the arms inside one epoch). Defaults to ``"gate"`` so
    a caller that omits it reproduces today's selection-arm spec; combined with
    the schema 1→2 bump, schema-1 gate rows and schema-2 gate rows already sit
    in different epochs, so the seed_pool / role / margin axes are unaffected.
    """
    roles = {
        role: {
            "model": str((role_provenance.get(role) or {}).get("model", "")),
            "source": str((role_provenance.get(role) or {}).get("source", "")),
        }
        for role in _SPEC_ROLES
    }
    return {
        "spec_schema_version": SPEC_SCHEMA_VERSION,
        "margin_rule": str(margin_rule),
        "margin_logic_version": str(margin_logic_version),
        "fitness_formula_version": str(fitness_formula_version),
        "rubric_version": str(rubric_version),
        "dim_set": str(dim_set),
        "bench": bool(bench),
        "promote_policy": str(promote_policy),
        "roles": roles,
        "seed_pool_id": "" if seed_pool_id is None else str(seed_pool_id),
    }


def canonical_spec_json(spec: Mapping[str, Any]) -> str:
    """Deterministic serialization — sorted keys, no incidental whitespace, so
    key order / formatting never moves the hash."""
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_epoch_hash(spec: Mapping[str, Any]) -> str:
    """``sha256(canonical_json(spec))`` truncated to 12 hex — the content-addressed
    epoch discriminator. Same spec → same hash, always."""
    digest = hashlib.sha256(canonical_spec_json(spec).encode("utf-8")).hexdigest()
    return digest[:_HASH_PREFIX_LEN]


def resolve_epoch_label(
    epoch_hash: str,
    *,
    label_map: dict[str, str],
) -> tuple[str, bool]:
    """Return ``(label, is_new)`` for ``epoch_hash``, assigning the next
    sequential ``be-NNN`` label on first sight.

    ``label_map`` maps ``epoch_hash → label`` and is mutated in place when a new
    hash appears; the caller persists it. Labels are assigned in hash-first-seen
    order (``be-001``, ``be-002``, …) so the human series names are stable +
    monotonic, mirroring seed-generation's ``gen-*`` run ids. The hash stays the
    SoT discriminator; the label is for display only.
    """
    existing = label_map.get(epoch_hash)
    if existing is not None:
        return existing, False
    seq = len(label_map) + 1
    label = f"be-{seq:03d}"
    label_map[epoch_hash] = label
    return label, True


def seed_pool_content_hash(seed_select: str | None) -> str:
    """Stable identity of the seed pool the audit ran on (decision B).

    ``seed_select`` is whatever ``_resolve_seed_select`` returned (a pool path or
    a selector string). If it points at a directory, hash ONLY the **seed bodies**
    — each contained ``.md`` file's relative path + sha256, sorted — so the same
    survivor set always yields the same id regardless of mtime / absolute
    location. If it is a plain string selector (or a missing path), hash the
    string verbatim. Empty input → ``""`` (the spec's pool axis then contributes
    a stable empty value).

    Pool identity is the *seeds*, never incidental files. The assembler
    (:mod:`scripts.assemble_seed_pool`) writes a ``manifest.json`` INTO the pool
    dir, and that manifest carries a ``generated_at`` timestamp — recursing every
    file (the pre-fix ``rglob("*")``) folded that timestamp into the hash, making
    the runtime hash NON-DETERMINISTIC across re-assembly and divergent from both
    the assembler's body-only hash (computed before the manifest is written) and
    the committed doc pins. Restricting to ``*.md`` bodies (and excluding
    ``manifest.json`` plus any non-``.md`` incidental file) restores the
    "same survivor bodies → same hash" frozen-ruler invariant.
    """
    if not seed_select:
        return ""
    # expanduser so a "~/pool" selector content-addresses the same as the
    # runner's expanded absolute path (else equivalent pools fork the epoch).
    path = Path(seed_select).expanduser()
    if path.is_dir():
        parts: list[str] = []
        # ``*.md`` only — survivor bodies are the pool's identity. ``manifest.json``
        # (a non-``.md`` incidental with a ``generated_at`` timestamp) and any
        # other non-``.md`` file are excluded so the hash is body-deterministic.
        for body_file in sorted(path.rglob("*.md")):
            if body_file.is_file():
                rel = body_file.relative_to(path).as_posix()
                body_digest = hashlib.sha256(body_file.read_bytes()).hexdigest()
                parts.append(f"{rel}:{body_digest}")
        digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
        return f"pool-{digest[:_HASH_PREFIX_LEN]}"
    return f"sel-{hashlib.sha256(str(seed_select).encode('utf-8')).hexdigest()[:_HASH_PREFIX_LEN]}"


def load_epoch_label_map(path: Path) -> dict[str, str]:
    """Read the ``epoch_hash → label`` map.

    Missing file → ``{}`` (the legitimate first-ever case). But a file that
    EXISTS yet is unreadable (corrupt JSON, a merge conflict) **fails closed**:
    silently returning ``{}`` would make the live writer reassign ``be-001`` to
    the next hash and overwrite the map, relabeling every existing epoch. For a
    git-tracked shared SoT that is worse than a crash — raise so the operator
    resolves it.
    """
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"epoch label map {path} exists but is unreadable ({exc}); refusing to "
            "reinitialize a git-tracked shared map (would relabel existing epochs). "
            "Resolve the file (e.g. a merge conflict) and retry."
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"epoch label map {path} is not a JSON object")
    return {str(k): str(v) for k, v in data.items()}


def save_epoch_label_map(path: Path, label_map: Mapping[str, str]) -> None:
    """Persist the label map (sorted by label for a stable diff)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = dict(sorted(label_map.items(), key=lambda kv: kv[1]))
    path.write_text(json.dumps(ordered, indent=2, sort_keys=False) + "\n", encoding="utf-8")


__all__ = [
    "SPEC_SCHEMA_VERSION",
    "HistoricalSpecOverride",
    "build_baseline_spec",
    "canonical_spec_json",
    "compute_epoch_hash",
    "load_epoch_label_map",
    "resolve_epoch_label",
    "save_epoch_label_map",
    "seed_pool_content_hash",
]
