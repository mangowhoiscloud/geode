"""Run ledgers — baseline read/write/registry, epoch rows, results, session index.

S-5 (2026-06-11) — extracted verbatim from ``core/self_improving/train.py``
(the autoresearch-원형 복원: train.py keeps only the mutation surface +
fixed-budget loop; the measurement gear lives here). Behavior 0-diff —
pinned by the dry-run equivalence test. Mode A agents MUST NOT modify
this module (program.md contract); the tunables stay on train.py and are
read lazily via ``_train()`` so test monkeypatches on the train module
namespace keep working.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.self_improving import fitness as fitness_spec
from core.self_improving import gate, measure

if TYPE_CHECKING:
    from core.self_improving.bench_means import BenchProvenance
    from core.self_improving.loop.observe.baseline_epoch import HistoricalSpecOverride
    from core.self_improving.loop.observe.run_provenance import RunProvenanceFields
    from core.self_improving.loop.observe.statistical_power import PowerRecordFields

from core.paths import (
    BASELINE_ARCHIVE_PATH,
    BASELINE_JSON_PATH,
    RESULTS_JSONL_PATH,
    RESULTS_TSV_PATH,
)
from core.paths import GLOBAL_AUTORESEARCH_HANDOFF_DIR as _SELF_IMPROVING_LOOP_HOME

log = logging.getLogger(__name__)


def _train() -> Any:
    """Lazy accessor for the train module's tunables/mutation surface.

    Module-level mutual import would hit the partially-initialized-module
    trap (train imports this module at top level); call-time import is
    safe and preserves ``monkeypatch.setattr(train, ...)`` semantics.
    """
    from core.self_improving import train as _t

    return _t


# LATEST baseline — runtime (per-run, regenerated), NOT versioned. Distinct
# from the TRACKED promoted history ``baseline_archive.jsonl`` (see
# ``_baseline_archive_path``). latest-vs-promoted SoT split.
BASELINE_PATH = BASELINE_JSON_PATH

SELF_IMPROVING_LOOP_HOME = _SELF_IMPROVING_LOOP_HOME

SESSIONS_INDEX_PATH = SELF_IMPROVING_LOOP_HOME / "sessions.jsonl"
"""P1a — shared self-improving-loop session registry. One JSON record per run
from any self-improving-loop driver (autoresearch / seed-generation) so external
tools can join across the two loops via ``session_id`` + ``gen_tag``."""
"""Per-branch baseline written by the self-improving-loop agent after a promote.

PR-2 of petri-schema-v2 (2026-05-23) — schema_version=2 layout::

    {"schema_version": 2,
     "session_id":     "<run id>",
     "commit":         "<git sha>",
     "ts_utc":         "<ISO 8601>",
     "raw": {
        "dim_means":            {dim: float},
        "dim_stderr":           {dim: float},
        "sample_count":         {dim: int},     # PR-1 provenance
        "measurement_modality": {dim: str},     # PR-1 provenance
        "eval_archive":         "<path>" | null,
        "rubric_version":       "v3-22dim-PR0",
     },
     "axes": {
        "admire_means": {field: float} | null,
        "bench_means":  {field: float} | null,
     }}

Legacy v1 (pre-PR-2 flat ``{dim_means, dim_stderr,
[admire_means], [bench_means]}``) is still read by ``_load_baseline``
for backwards compat. Absent file → gate dormant (first run / fresh  # slop:keep
branch). Future PR-3/4/5 extend with ``normalized`` / ``fitness`` /
``audit`` / ``promotion`` namespaces.
"""

RESULTS_TSV_HEADER: tuple[str, ...] = (
    "session_id",
    "gen_tag",
    "commit",
    "fitness",
    "critical_min",
    "critical_mean",
    "auxiliary_mean",
    "stability_score",
    "info_mean",
    "dim_count_engaged",
    "verdict",
    "description",
)
"""P1a — added ``session_id`` + ``gen_tag`` as the first two columns
so cross-run / cross-loop joins work without parsing description.
See `docs/plans/2026-05-19-self-improving-loop-wiring-sprint.md` Phase B."""


def _tier_mean(dim_scores: dict[str, float], dims: tuple[str, ...]) -> float:
    """Average of the per-dim scores for one tier."""
    if not dims:
        return 0.0
    vals = [dim_scores.get(d, 0.0) for d in dims]
    return sum(vals) / len(vals)


def _tier_min(dim_scores: dict[str, float], dims: tuple[str, ...]) -> float:
    """Minimum per-dim score across a tier (surfaces critical regressions)."""
    if not dims:
        return 0.0
    return min(dim_scores.get(d, 0.0) for d in dims)


def format_results_tsv_row(
    *,
    session_id: str,
    gen_tag: str,
    commit: str,
    fitness: float,
    dim_scores: dict[str, float],
    dim_means: dict[str, float],
    verdict: str,
    description: str,
) -> str:
    """Render one 12-col results.tsv row.

    P1a prepends ``session_id`` + ``gen_tag`` so cross-run joins work.
    ``dim_scores`` is the output of :func:`compute_dim_scores` (includes
    the synthetic ``"stability"`` key). ``dim_means`` is the raw audit
    emit — used here only to compute ``dim_count_engaged`` (how many
    of the 20 dims actually surfaced a measurement, vs filled with
    defaults). Description must not contain newlines or tabs — caller
    sanitizes.
    """
    safe_desc = description.replace("\t", " ").replace("\n", " ").strip()
    engaged = sum(1 for dim in fitness_spec.AXIS_TIERS if dim in dim_means)
    fields = (
        session_id,
        gen_tag,
        commit,
        f"{fitness:.6f}",
        f"{_tier_min(dim_scores, fitness_spec.CRITICAL_DIMS):.4f}",
        f"{_tier_mean(dim_scores, fitness_spec.CRITICAL_DIMS):.4f}",
        f"{_tier_mean(dim_scores, fitness_spec.AUXILIARY_DIMS):.4f}",
        f"{dim_scores.get('stability', fitness_spec.STABILITY_FALLBACK):.4f}",
        f"{_tier_mean(dim_scores, fitness_spec.INFO_DIMS):.4f}",
        str(engaged),
        verdict,
        safe_desc,
    )
    return "\t".join(fields)


def format_results_jsonl_row(
    *,
    session_id: str,
    gen_tag: str,
    commit: str,
    fitness: float,
    dim_means: dict[str, float],
    dim_stderr: dict[str, float],
    dim_scores: dict[str, float],
    verdict: str,
    description: str,
    baseline_active: bool,
    sample_count: dict[str, int] | None = None,
    measurement_modality: dict[str, str] | None = None,
    missing_dims: list[str] | None = None,
    eval_archive: str | None = None,
    # PR-SIL-5THEME C2 (2026-05-23, ux-removed 2026-05-30) — S6b multi-axis
    # breakdown columns. 이전엔 results.jsonl 가 dim axis 만 emit → cross-run
    # 분석이 어느 축이 기여/저하 했는지 join 없이 못 봤다. 이제 admire/bench
    # 컬럼 + per-axis aggregate 같이 emit. 모든 새 컬럼 optional (legacy
    # reader backward-compat). bench 측은 BenchProvenance dataclass 로 묶음.
    admire_means: dict[str, float] | None = None,
    bench_provenance: BenchProvenance | None = None,
) -> str:
    """Render one results.jsonl line — full per-dim raw signal.

    P1a adds ``session_id`` + ``gen_tag`` as top-level keys.

    PR-5 of petri-schema-v2 (2026-05-23) — adds the 4 provenance
    fields that landed in baseline.json v2 (PR-2) + the
    ``missing_dims`` Goodhart surface (PR-4) so cross-run analysis
    can tell apart real measurements from default-filled fallbacks
    without joining against baseline.json or the journal.

    Schema (JSON object on one line)::

        {"session_id": "...", "gen_tag": "...",
         "commit": "...", "fitness": 0.535895,
         "dim_means": {...20 entries...},
         "dim_stderr": {...20 entries...},
         "dim_scores": {...20 + 'stability'...},
         "sample_count": {...20 entries...},          # PR-5
         "measurement_modality": {...20 entries...},  # PR-5
         "missing_dims": [...],                       # PR-5 (sorted)
         "eval_archive": "<path>" | null,             # PR-5
         "verdict": "keep", "description": "...",
         "baseline_active": true}

    The meta-reviewer agent (S8) reads this artifact to compute
    next-gen priors without re-running the audit.
    """
    # Defaults preserve schema parity — every JSONL row carries all 20
    # dim entries in means/stderr/scores so downstream parsers can
    # assume the keys exist (a partial dim_scores from a buggy caller
    # cannot silently drop fields).
    scores_full = {d: round(dim_scores.get(d, 0.0), 4) for d in fitness_spec.AXIS_TIERS}
    scores_full["stability"] = round(
        dim_scores.get("stability", fitness_spec.STABILITY_FALLBACK), 4
    )
    # PR-5 — emit the 3 provenance dicts with the same dim universe
    # so a downstream parser can zip them against ``dim_means``. Missing
    # provenance (dry-run, pre-PR-1 build) → 0 count + empty modality.
    sample_count_full = {d: int((sample_count or {}).get(d, 0)) for d in fitness_spec.AXIS_TIERS}
    modality_full = {
        d: str((measurement_modality or {}).get(d, "")) for d in fitness_spec.AXIS_TIERS
    }
    # PR-SIL-5THEME C2 — bench-side 의 7-field universe over emit so 다운스트림
    # parser 가 7 column zip 가능. None / empty 시 0.0 / 0 / "" default 채워
    # missing 은 missing_benches 로 surface 한다.
    from core.self_improving.bench_means import BENCH_DIM_WEIGHTS, BenchProvenance

    _prov = bench_provenance or BenchProvenance(rubric_version="")
    _bm = _prov.bench_means
    _bs = _prov.bench_stderr
    _bc = _prov.bench_sample_count
    bench_means_full = {b: round(_bm.get(b, 0.0), 4) for b in BENCH_DIM_WEIGHTS}
    bench_stderr_full = {b: round(_bs.get(b, 0.0), 4) for b in BENCH_DIM_WEIGHTS}
    bench_sample_count_full = {b: int(_bc.get(b, 0)) for b in BENCH_DIM_WEIGHTS}

    payload = {
        "session_id": session_id,
        "gen_tag": gen_tag,
        "commit": commit,
        "fitness": round(fitness, 6),
        "dim_means": {d: round(dim_means.get(d, 0.0), 4) for d in fitness_spec.AXIS_TIERS},
        "dim_stderr": {d: round(dim_stderr.get(d, 0.0), 4) for d in fitness_spec.AXIS_TIERS},
        "dim_scores": scores_full,
        "sample_count": sample_count_full,
        "measurement_modality": modality_full,
        # PR-5 — sort defensively. ``compute_missing_dims`` already
        # returns a sorted list, but a misbehaving caller passing an
        # unsorted list would break cross-run diff stability.
        "missing_dims": sorted(missing_dims or []),
        "eval_archive": eval_archive,
        "verdict": verdict,
        "description": description.replace("\n", " ").strip(),
        "baseline_active": baseline_active,
        # PR-SIL-5THEME C2 — multi-axis breakdown (ux-removed 2026-05-30).
        "admire_means": dict(admire_means) if admire_means else None,
        "bench_means": bench_means_full,
        "bench_stderr": bench_stderr_full,
        "bench_sample_count": bench_sample_count_full,
        "missing_benches": sorted(_prov.missing_benches),
        "bench_rubric_version": _prov.rubric_version,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def print_summary(
    dim_means: dict[str, float],
    dim_stderr: dict[str, float],
    dim_scores: dict[str, float],
    fitness: float,
    audit_seconds: float,
    total_seconds: float,
    dry_run: bool,
    baseline_active: bool,
) -> None:
    """Grep-friendly stdout block — per-dim scores + means + stderr.

    Per ADR-002 + PR 0 the report lists all 20 dims (5 critical +
    12 auxiliary + 3 info) so the self-improving-loop agent's results.tsv can
    carry the raw signal without re-projection. Fitness weights 17
    dims (critical + auxiliary) + the stability axis.
    """
    print("---")
    print(f"fitness:                  {fitness:.6f}")
    _stability = dim_scores.get("stability", fitness_spec.STABILITY_FALLBACK)
    print(f"stability_score:          {_stability:.4f}")
    for dim in (*fitness_spec.CRITICAL_DIMS, *fitness_spec.AUXILIARY_DIMS, *fitness_spec.INFO_DIMS):
        if dim in dim_scores:
            print(f"{dim}_score: {dim_scores[dim]:.4f}")
        if dim in dim_means:
            print(f"{dim}_mean: {dim_means[dim]:.4f}")
        if dim in dim_stderr:
            print(f"{dim}_stderr: {dim_stderr[dim]:.4f}")
    print(f"audit_seconds:            {audit_seconds:.1f}")
    print(f"total_seconds:            {total_seconds:.1f}")
    cfg = _train()._get_autoresearch_config()
    print(f"seed_count:               {cfg.seed_limit}")
    print(f"dim_count:                {len(fitness_spec.AXIS_TIERS)}")
    print(f"target_model:             {_train()._petri_role_model('target')}")
    print(f"judge_model:              {_train()._petri_role_model('judge')}")
    print(f"auditor_model:            {_train()._petri_role_model('auditor')}")
    print(f"budget_minutes:           {cfg.budget_minutes}")
    print(f"wrapper_override_active:  {str(_train().WRAPPER_OVERRIDE_HOOK_READY).lower()}")
    print(f"section_count:            {len(_train().WRAPPER_PROMPT_SECTIONS)}")
    print(f"stability_source:         {'stderr-aggregate' if dim_stderr else 'placeholder'}")
    print(f"baseline_active:          {str(baseline_active).lower()}")
    print(f"mode:                     {'dry-run' if dry_run else 'audit'}")


def _resolve_session_id() -> str:
    """Return the session_id for this run.

    Honours ``AUTORESEARCH_SESSION_ID`` (typically set by a parent
    driver that wants to correlate across multiple invocations);
    otherwise generates ``<ISO date>T<HH:MM>Z-<short-uuid>``.
    """
    override = os.environ.get("AUTORESEARCH_SESSION_ID", "").strip()
    if override:
        return override
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%MZ")
    short = uuid.uuid4().hex[:6]
    return f"{stamp}-{short}"


_GEN_SUFFIX_RE = re.compile(r"-gen(\d+)$")


def _next_gen_counter_for_commit(commit: str, sessions_path: Path | None = None) -> int:
    """Return the next monotonic ``gen{N}`` counter for ``commit``.

    PR-GEN-COUNTER (2026-05-26) — fix the attribution silent leak found
    in the 2026-05-26 sprint Phase A audit (§5.6): pre-PR,
    ``_resolve_gen_tag(commit)`` returned ``autoresearch-{commit}``
    deterministically, so repeated audits at the same commit collapsed
    onto the same gen_tag — every attribution row at that commit
    looked like the same generation. This function reads
    ``sessions.jsonl``, finds rows whose gen_tag starts with
    ``autoresearch-{commit}``, parses the optional ``-gen{N}`` suffix,
    and returns ``max(N) + 1``. Rows without the suffix (legacy
    pre-PR format) count as ``gen0`` so the next is ``gen1``.

    ``sessions_path`` parameter is for testability; default reads
    ``SESSIONS_INDEX_PATH``.
    """
    target = sessions_path if sessions_path is not None else SESSIONS_INDEX_PATH
    if not target.is_file():
        return 1
    max_n = 0
    saw_commit = False
    prefix = f"autoresearch-{commit}"
    try:
        with target.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                tag = row.get("gen_tag", "")
                if not isinstance(tag, str) or not tag.startswith(prefix):
                    continue
                saw_commit = True
                # Match either ``<prefix>`` (legacy = gen0 implied) or
                # ``<prefix>-gen<N>`` (post-PR explicit counter).
                suffix = tag[len(prefix) :]
                if suffix == "":
                    continue  # legacy gen0 — max_n stays at 0
                m = _GEN_SUFFIX_RE.match(suffix)
                if m:
                    try:
                        n = int(m.group(1))
                    except ValueError:
                        # Regex restricts to ``\d+`` so this cannot fire
                        # in practice, but ``int`` *can* raise on
                        # absurdly long digit strings. Treat as if the
                        # row didn't match so the scan continues.
                        continue
                    max_n = max(max_n, n)
    except OSError:
        # Reading sessions.jsonl is best-effort — fall through to gen1.
        return 1
    if not saw_commit:
        return 1
    return max_n + 1


def _resolve_gen_tag(commit: str) -> str:
    """Return the gen_tag for this audit.

    Honours ``AUTORESEARCH_GEN_TAG`` so a parent driver (e.g. seed-
    pipeline cycle) can label generations consistently across runs.
    Default: ``autoresearch-<commit>-gen<N>`` where ``N`` is the next
    monotonic counter for this commit's history in ``sessions.jsonl``.

    PR-GEN-COUNTER (2026-05-26) — switched from ``autoresearch-{commit}``
    (collision-prone) to ``autoresearch-{commit}-gen{N}`` so repeated
    audits at the same commit don't collapse into one synthetic
    generation. Legacy gen_tags in old sessions.jsonl (no ``-gen{N}``
    suffix) are treated as ``gen0`` — the next emission is ``gen1``.

    Concurrency: the counter scan + emission are NOT atomic. Two
    overlapping ``_resolve_gen_tag`` calls (e.g. seed-gen cycle +
    manual ``geode audit`` overlap) can both observe the same
    ``max(N)`` and emit the same ``gen{N+1}``, since the session row
    is appended only at run end. This is acceptable as a best-effort
    counter — gen_tag uniqueness is NOT guaranteed under concurrency.
    Operators who need strict uniqueness should pin the tag via
    ``AUTORESEARCH_GEN_TAG`` from the parent driver. See Codex MCP
    review (PR-GEN-COUNTER CONDITIONAL_PASS #2, 2026-05-26).
    """
    override = os.environ.get("AUTORESEARCH_GEN_TAG", "").strip()
    if override:
        return override
    counter = _next_gen_counter_for_commit(commit)
    return f"autoresearch-{commit}-gen{counter}"


def _gen_cycle_index(gen_tag: str) -> int:
    """Extract the per-cycle index for the ``random`` promote arm's draw.

    E3 (2026-05-30). The random arm draws ``Random(seed + cycle_index)`` per
    cycle, so it needs a stable monotonic index. The gen_tag carries a ``-genN``
    suffix (:func:`_resolve_gen_tag`) which IS the campaign's monotonic cycle
    counter, so it is reused as the index. A gen_tag without the suffix (an
    operator-pinned ``AUTORESEARCH_GEN_TAG``) falls back to ``0`` — the draw is
    still deterministic from the seed, just not per-cycle independent (the
    operator opted out of the auto counter, so the cycle structure is theirs to
    own). Always returns a non-negative int (graceful contract — never raises)."""
    m = _GEN_SUFFIX_RE.search(gen_tag)
    if m is None:
        return 0
    try:
        return int(m.group(1))
    except ValueError:  # pragma: no cover — regex restricts to \d+
        return 0


def _append_session_index(
    *,
    session_id: str,
    gen_tag: str,
    component: str,
    started_at: float,
    ended_at: float,
    extra: dict[str, object],
) -> None:
    """Append one row to ``~/.geode/autoresearch/handoff/sessions.jsonl``.

    P1a — shared cross-loop session registry. Persistence failures log
    nothing (a stderr print here would pollute the grep-friendly
    stdout block) and the in-memory run still completes.
    """
    try:
        SELF_IMPROVING_LOOP_HOME.mkdir(parents=True, exist_ok=True)
        payload: dict[str, object] = {
            "session_id": session_id,
            "gen_tag": gen_tag,
            "component": component,
            "started_at": started_at,
            "ended_at": ended_at,
        }
        payload.update(extra)
        with SESSIONS_INDEX_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _load_baseline() -> tuple[
    dict[str, float] | None,
    dict[str, float] | None,
    dict[str, float],
    dict[str, float],
]:
    """Read ``state/baseline.json`` if present.

    Returns ``(dim_means, dim_stderr, admire_means, bench_means)``.

    - ``dim_means`` / ``dim_stderr`` — ``None`` on missing file / unparseable
      JSON / empty payload (caller treats this as the gate-dormant case).
    - ``admire_means`` / ``bench_means`` — empty ``dict`` when not present
      in the payload (S3 backwards compat: a pre-S3 baseline.json with only
      ``dim_*`` is still a valid baseline; the newer axes simply have no
      cross-axis lever yet). The ux_means axis was removed in
      PR-MARGIN-FITNESS-SCALE (2026-05-30); a stale ``axes.ux_means`` on
      disk is simply ignored.

    G2.fix (2026-05-20) reverted the evidence return slot. baseline.json
    is the cache of *numeric fitness signal only* (means + stderr +
    multi-axis aggregates); petri's ``.eval`` archive at
    ``~/.geode/petri/logs/latest.eval`` is the single SoT for evidence.

    Schema versions (PR-2 of petri-schema-v2, 2026-05-23):

    - **v1 (legacy)** — top-level ``{dim_means, dim_stderr,
      [admire_means], [bench_means]}`` flat shape. Files
      pre-PR-2 keep this layout; this reader still consumes them so
      no migration step is forced.
    - **v2 (current)** — namespace-split ``{schema_version: 2,
      session_id, commit, ts_utc, raw: {dim_means, dim_stderr,
      sample_count, measurement_modality, eval_archive,
      rubric_version}, axes: {admire_means, bench_means}}``.
      The reader pulls dim_* out of ``raw.`` and the axis dicts out of
      ``axes.`` while keeping the same return signature.

    See ``docs/plans/2026-05-23-petri-schema-v2.md`` for the full v2
    layout (additional ``normalized`` / ``fitness`` / ``audit`` /
    ``promotion`` namespaces land in PR-3/4/5).
    """
    if not BASELINE_PATH.is_file():
        return None, None, {}, {}
    try:
        baseline_payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None, {}, {}

    # v2 path: namespace-split — read from ``raw`` + ``axes``.
    if baseline_payload.get("schema_version") == 2:
        raw_block = baseline_payload.get("raw") or {}
        axes_block = baseline_payload.get("axes") or {}
        raw_means = raw_block.get("dim_means") or {}
        raw_stderr = raw_block.get("dim_stderr") or {}
        if not raw_means:
            return None, None, {}, {}
        # PR-AUDIT-AB (2026-06-10) — the graceful contract must cover the
        # per-value float() casts, not just the outer file/JSON boundary:
        # one non-numeric dim value (schema drift, partial write) raised
        # ValueError straight through the promote gate. Same incident
        # class as PR-G3 #1347 (CANNOT table row).
        try:
            baseline_means = {k: float(v) for k, v in raw_means.items()}
            baseline_stderr = {k: float(v) for k, v in raw_stderr.items()}
        except (TypeError, ValueError):
            log.warning(
                "baseline.json (v2) has non-numeric dim values — "
                "treating baseline as absent per graceful contract"
            )
            return None, None, {}, {}
        admire_means = _coerce_axis_dict(axes_block.get("admire_means"))
        bench_means = _coerce_axis_dict(axes_block.get("bench_means"))
        return baseline_means, baseline_stderr, admire_means, bench_means

    # v1 (legacy flat) path.
    raw_means = baseline_payload.get("dim_means") or {}
    raw_stderr = baseline_payload.get("dim_stderr") or {}
    if not raw_means:
        return None, None, {}, {}
    try:
        baseline_means = {k: float(v) for k, v in raw_means.items()}
        baseline_stderr = {k: float(v) for k, v in raw_stderr.items()}
    except (TypeError, ValueError):
        log.warning(
            "baseline.json (v1) has non-numeric dim values — "
            "treating baseline as absent per graceful contract"
        )
        return None, None, {}, {}
    # S3 (2026-05-21) — axes are optional + graceful: pre-S3 baselines
    # don't have them, and a corrupted field on a single axis must not
    # discard the whole baseline (dim part stays load-bearing).
    admire_means = _coerce_axis_dict(baseline_payload.get("admire_means"))
    bench_means = _coerce_axis_dict(baseline_payload.get("bench_means"))
    return baseline_means, baseline_stderr, admire_means, bench_means


def _load_baseline_sample_count() -> dict[str, int]:
    """Return baseline.json's per-dim ``sample_count`` map.

    PR-3 of petri-schema-v2 (2026-05-23) — separate helper so the
    ``_load_baseline`` tuple signature stays intact while the
    new ``_should_promote`` rule (N=1 critical → conservative margin)
    has read access to the per-dim N. v1 baselines don't carry the
    field — return ``{}`` so the new rule stays dormant for them.
    Empty / missing file / parse error all collapse to ``{}``.
    """
    if not BASELINE_PATH.is_file():
        return {}
    try:
        payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("schema_version") == 2:
        raw_block = payload.get("raw") or {}
        sample_count = raw_block.get("sample_count") or {}
    else:
        # v1 legacy: no sample_count was emitted.
        return {}
    if not isinstance(sample_count, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in sample_count.items():
        if not isinstance(k, str):
            continue
        try:
            out[k] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def _load_baseline_measurement_modality() -> dict[str, str]:
    """Return baseline.json's per-dim ``measurement_modality`` map.

    PR-SIL-5THEME C3 (2026-05-23) — sibling of
    ``_load_baseline_sample_count`` so the new modality-aware widening
    guard (N=1 widening fires only for judge_llm modality) can read the
    baseline's per-dim modality without enlarging the
    ``_load_baseline`` return tuple.

    v1 baselines don't carry the field — return ``{}`` so the new
    guard stays conservative (defaults to judge_llm widening when
    modality unknown). Empty / missing file / parse error all collapse
    to ``{}``.
    """
    if not BASELINE_PATH.is_file():
        return {}
    try:
        payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("schema_version") == 2:
        raw_block = payload.get("raw") or {}
        modality = raw_block.get("measurement_modality") or {}
    else:
        # v1 legacy: no measurement_modality was emitted.
        return {}
    if not isinstance(modality, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in modality.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        out[k] = v
    return out


def _load_baseline_fitness_stderr() -> float | None:
    """Return baseline.json's persisted ``raw.fitness_stderr`` scalar.

    PR-MARGIN-FITNESS-SCALE (2026-05-30) — sibling of
    ``_load_baseline_sample_count`` so the promote gate can read the prior
    audit's fitness-scale stderr (the prior σ in the gain-stderr margin)
    without enlarging the ``_load_baseline`` return tuple. v1 baselines and
    pre-PR v2 baselines don't carry the field — return ``None`` so the gate
    falls back to the per-dim-independent MC estimate (``_fitness_scale_stderr``).
    Missing file / parse error / non-numeric value all collapse to ``None``.
    """
    if not BASELINE_PATH.is_file():
        return None
    try:
        payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        return None
    raw_block = payload.get("raw") or {}
    value = raw_block.get("fitness_stderr")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_targeted_dims() -> frozenset[str] | None:
    """The campaign's targeted dims for the promote gate's targeted sub-fitness.

    PR-METRIC-TARGETED-IRT (2026-06-01). _train().SOURCE: the runner env-propagates
    ``GEODE_SIL_EXPECTED_DIM`` (``runner.py``) — a JSON ``dict[dim → expected
    delta]`` whose KEYS are the dims the campaign's mutation targets (single dim
    via ``baseline_reader.pick_regression_target_dim``, operational tier via
    ``baseline_reader._operational_dim_set``). Their KEYS are the targeted set.

    Returns the targeted dim KEYS that are also WEIGHTED dims (``fitness_spec.DIM_WEIGHTS`` —
    the surface the sub-fitness sums over), as a frozenset; ``None`` when the env
    is unset / empty / malformed / disjoint from the weighted dims, so the gate
    falls back to the v1 aggregate decision (the default, control-arm, and
    manual-audit paths all see ``None``).

    Graceful contract: each boundary cast (JSON parse, dict-shape, str-key) is
    guarded so a malformed env yields ``None`` rather than raising — an audit is
    never aborted by a bad targeted-dim hint.
    """
    raw = os.environ.get("GEODE_SIL_EXPECTED_DIM", "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    keys = {k for k in parsed if isinstance(k, str)}
    targeted = frozenset(keys) & set(fitness_spec.DIM_WEIGHTS)
    return targeted or None


def _coerce_axis_dict(raw: Any) -> dict[str, float]:
    """Best-effort coerce a baseline axis dict — graceful per-axis (S3).

    Returns ``{}`` whenever ``raw`` is not a dict, or whenever any value
    is non-numeric. The ``dim_*`` baseline already exists as a
    load-bearing fallback, so each of the 3 newer axes can fail in
    isolation without invalidating the audit's promotion gate.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        if not isinstance(k, str):
            return {}
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            return {}
    return out


_BASELINE_REGISTRY_KIND = "baseline"

_CURRENT_MARGIN_RULE = "fitness-stderr"
"""The promote-gate margin rule the current code enforces (PR-MARGIN-FITNESS-
SCALE). Live promotes stamp this; the pre-fix vanilla baseline is backfilled
with ``"dim-stderr"`` to mark the buggy-margin cohort it was measured under."""

_VALID_MARGIN_RULES = frozenset({"dim-stderr", "fitness-stderr"})


def _baseline_archive_path() -> Path:
    """TRACKED promoted-baseline registry (in-repo SoT). Decoupled from
    ``BASELINE_PATH`` by the state split: the LATEST baseline is runtime
    (~/.geode) while this promoted history is versioned (in-repo), so they no
    longer share a parent. Tests monkeypatch ``BASELINE_ARCHIVE_PATH``
    (or ``ledger._baseline_archive_path``) to redirect this independently."""
    return BASELINE_ARCHIVE_PATH


def _next_baseline_id(now: datetime) -> str:
    """Return the next sequential baseline id (``baseline-<YYMM>-<seq>``).

    ``seq`` is a 1-based counter over the ``kind="baseline"`` rows already in
    ``baseline_archive.jsonl`` — stable + monotonic across promotes, mirroring
    the seed-generation run-id scheme. ``now`` is passed in (not read) so the
    id is deterministic for a given caller clock.

    Assumes a **single writer**: the self-improving loop serialises audits (and
    therefore promotes) via the inter-process audit lane
    (PR-OL-AUDIT-BURST-FIX), so the read-count-then-append is race-free in
    practice. Two genuinely-concurrent promotes (not a supported mode) could
    read the same count and collide — out of scope until parallel loops exist.
    """
    archive_path = _baseline_archive_path()
    seq = 1
    if archive_path.is_file():
        for line in archive_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                if json.loads(stripped).get("kind") == _BASELINE_REGISTRY_KIND:
                    seq += 1
            except json.JSONDecodeError:
                continue
    return f"baseline-{now.strftime('%y%m')}-{seq}"


def _append_baseline_registry_row(
    baseline_id: str,
    *,
    dim_means: dict[str, float],
    dim_stderr: dict[str, float],
    sample_count: dict[str, int] | None,
    measurement_modality: dict[str, str] | None,
    admire_means: dict[str, float] | None,
    bench_means: dict[str, float] | None,
    fitness_stderr: float | None,
    margin_rule: str,
    eval_archive: str | None,
    session_id: str,
    commit: str,
    ts_utc: str,
    promoted_by: str,
    role_provenance: dict[str, dict[str, str]] | None = None,
    seed_select: str | None = None,
    held_out_fitness: float | None = None,
    held_out_bench_id: str | None = None,
    promote_policy: str = "gate",
    promote_policy_seed: int = 0,
    power_stats: PowerRecordFields | None = None,
    run_provenance: RunProvenanceFields | None = None,
    historical_spec: HistoricalSpecOverride | None = None,
) -> None:
    """Append one ``kind="baseline"`` registry row to ``baseline_archive.jsonl``.

    Records the measurement criteria the hub baseline index + per-baseline page
    need to serve baselines losslessly + differentiated: per-role provenance,
    seed pool, the **fresh-anchor** intrinsic fitness (``baseline_means=None`` —
    no prior-base critical-floor comparison, which a seed-pool change makes
    spurious) + its ``fitness_stderr``, the ``margin_rule`` cohort discriminator,
    the ``bench`` axis flag, and the aggregate ``dim_means``.

    ``role_provenance`` is the ``{role: {model, source, lane}}`` block (see
    :mod:`core.self_improving.loop.observe.role_provenance`) for auditor / target /
    judge / mutator. The credential *lane* (PAYG / Subscription / CLI) is
    load-bearing — the same model behaves differently per lane — so the registry
    records model + source + lane, not just the model. ``None`` → the live
    promote path collects it from ``_train()._get_autoresearch_config()`` (kept
    un-threaded so the promote call sites stay unchanged in shape). The backfill
    script passes it explicitly because a historical baseline was measured under
    a config that has since changed — its bindings are not in the live config.

    ``seed_select`` likewise overrides the seed pool: ``None`` re-resolves the
    *current* pool (correct for a live promote, which fires right after its own
    audit), but a backfill of a historical baseline must pass the pool it was
    measured under (the live pointer may have moved).

    ``held_out_fitness`` / ``held_out_bench_id`` (E2, 2026-05-30) — the
    fixed-ruler measurement. ``seed_select`` co-evolves, so the row's intrinsic
    ``fitness`` (measured on the co-evolving pool) is NOT comparable across
    generations; ``held_out_fitness`` is the SAME 0-1 :func:`fitness_spec.compute_fitness`
    computed on the VERSION-FROZEN held-out bench (see
    :func:`score_held_out_bench`) and so IS the cross-generation evidence curve.
    ``held_out_bench_id`` is the bench's content-addressed identity (the ruler's
    fingerprint). Both are **omitted** from the row when ``None`` (no held-out
    bench configured) so existing readers see the same shape — the held-out
    fields are purely additive and never a new required key.

    ``promote_policy`` / ``promote_policy_seed`` (E3, 2026-05-30) — the control
    arm (``gate`` / ``random`` / ``never``) this baseline was produced under, and
    the RNG seed RECORDED for the ``random`` arm (``0`` for gate / never). They
    are recorded BOTH as top-level row fields (so the 3-arm comparison can split
    rows directly) AND inside the hashed ``baseline_spec`` (so the three arms land
    in distinct epochs — gate ≠ random ≠ never production logic, correctly not
    averaged). ``gate`` (default) reproduces today's selection-arm row + epoch.
    """
    if margin_rule not in _VALID_MARGIN_RULES:
        raise ValueError(
            f"margin_rule {margin_rule!r} not in {sorted(_VALID_MARGIN_RULES)} — "
            "the registry's vanilla↔fixed discriminator must be a known value"
        )
    if role_provenance is None:
        from core.self_improving.loop.observe.role_provenance import collect_role_provenance

        role_provenance = collect_role_provenance(_train()._get_autoresearch_config())
    # PR-BASELINE-EPOCH (2026-05-30) — content-addressed epoch discriminator.
    # Hash the production+measurement spec (margin_rule + logic version tags +
    # role model/source + rubric/dim-set + bench + seed-pool identity) → epoch.
    # Spec change ⇒ new epoch; the row self-verifies (stored spec re-hashes to
    # epoch_hash). See .claude/skills/baseline-epoch-partition/SKILL.md.
    from core.self_improving.loop.observe.baseline_epoch import (
        SPEC_SCHEMA_VERSION,
        build_baseline_spec,
        compute_epoch_hash,
        load_epoch_label_map,
        resolve_epoch_label,
        save_epoch_label_map,
        seed_pool_content_hash,
    )

    _seed_select = seed_select if seed_select is not None else _train()._resolve_seed_select()
    # Historical-spec override (backfill of a baseline measured under PRE-current
    # logic). Each field None / no override → the LIVE constant, so the live
    # promote path is byte-identical. A historical baseline (e.g. pre-margin-fix
    # vanilla) supplies its true version tags so it hashes to its OWN epoch.
    _hist = historical_spec
    baseline_spec = build_baseline_spec(
        margin_rule=margin_rule,
        margin_logic_version=(
            _hist.margin_logic_version
            if _hist and _hist.margin_logic_version
            else gate.MARGIN_LOGIC_VERSION
        ),
        fitness_formula_version=(
            _hist.fitness_formula_version
            if _hist and _hist.fitness_formula_version
            else fitness_spec.FITNESS_FORMULA_VERSION
        ),
        rubric_version=(
            _hist.rubric_version if _hist and _hist.rubric_version else measure.PETRI_RUBRIC_VERSION
        ),
        # the dim_set the audit was MEASURED on (override wins over config), not
        # the stale config default — else a `full`-override run is mis-stamped.
        dim_set=(_hist.dim_set if _hist and _hist.dim_set else measure._effective_dim_set()),
        # `is not None`, not `bool(...)` — match compute_fitness's bench-active
        # test (train.py: `bench_means is not None`) so an empty-but-active bench
        # dict is not mis-stamped bench=false.
        bench=bench_means is not None,
        role_provenance=role_provenance,
        seed_pool_id=seed_pool_content_hash(_seed_select),
        # E3 (2026-05-30) — control-arm policy in the hashed spec: gate / random /
        # never produce baselines under different production logic, so they hash
        # to DIFFERENT epochs (correctly NOT averaged into one comparison).
        promote_policy=promote_policy,
    )
    epoch_hash = compute_epoch_hash(baseline_spec)
    _label_map_path = _baseline_archive_path().parent / "baseline_epochs.json"
    _label_map = load_epoch_label_map(_label_map_path)
    epoch_label, _epoch_is_new = resolve_epoch_label(epoch_hash, label_map=_label_map)
    if _epoch_is_new:
        save_epoch_label_map(_label_map_path, _label_map)
        # TODO(PR-STATE-SELF-IMPROVING-RENAME, deferred): epoch-boundary snapshot.
        # When a NEW epoch opens (``_epoch_is_new``), the convention
        # (core/self_improving/state/_archive/README.md) is to freeze the PRIOR
        # epoch's full production surface (policies/ + baseline.json + pool identity)
        # under ``core/self_improving/state/_archive/<prior-be-NNN>/``. NOT auto-wired
        # here:
        # adding snapshot I/O inside the promote write path risks the promote
        # itself (a copy failure must not abort a gate-approved promote). Left as
        # an explicit follow-up — snapshot via a separate, post-promote step
        # (e.g. the campaign driver or an operator command) so the promote write
        # stays single-responsibility. See _archive/README.md for the layout.
    # Intrinsic fitness on the same (dim + admire) scale the promote gate's
    # ``current_raw`` uses — bench is OFF (Path C) so it is not threaded here.
    # A historical backfill PRESERVES its measured fitness (it was scored under
    # its own formula; recomputing would overwrite it with a current-formula
    # value). The live path (no override) recomputes exactly as before.
    if _hist is not None and _hist.fitness is not None:
        intrinsic_fitness: float = _hist.fitness
    else:
        intrinsic_fitness = fitness_spec.compute_fitness(
            dim_means,
            dim_stderr,
            baseline_means=None,
            admire_means=admire_means,
            measurement_modality=measurement_modality,
        )
    seed_count = max(sample_count.values()) if sample_count else 0
    row: dict[str, Any] = {
        "kind": _BASELINE_REGISTRY_KIND,
        "id": baseline_id,
        "ts_utc": ts_utc,
        "commit": commit,
        "session_id": session_id,
        "promoted_by": promoted_by,
        "fitness": float(intrinsic_fitness),
        "fitness_stderr": (float(fitness_stderr) if fitness_stderr is not None else None),
        "margin_rule": margin_rule,
        "bench": bool(bench_means),
        # E3 (2026-05-30) — control-arm tag (gate / random / never) as a top-level
        # row field (in addition to being inside the hashed ``baseline_spec``) so
        # the 3-arm comparison can split rows without re-parsing the spec.
        # ``promote_policy_seed`` is recorded for every arm (0 for gate / never) so
        # the random arm's promoted baseline is reproducible from the ledger.
        "promote_policy": str(promote_policy),
        "promote_policy_seed": int(promote_policy_seed),
        "seed_select": _seed_select,
        "seed_count": int(seed_count),
        # PR-BASELINE-EPOCH — content-addressed partition. epoch_hash is the
        # comparability discriminator; epoch_label (be-NNN) is for display;
        # baseline_spec is the hashed surface (row self-verifies); spec_schema_version
        # versions the field-set (write-time frozen — no retroactive recompute).
        "epoch_hash": epoch_hash,
        "epoch_label": epoch_label,
        "baseline_spec": baseline_spec,
        "spec_schema_version": SPEC_SCHEMA_VERSION,
        # per-role {model, source, lane} — shared SoT with the mutations.jsonl
        # cycle ledger (core.self_improving.loop.observe.role_provenance) so the two
        # git-tracked ledgers never drift on the credential lane.
        "role_provenance": role_provenance,
        # basename only — baseline_archive.jsonl is git-tracked, so an absolute
        # ~/.geode/... path would leak a user path (feedback_no_hardcoded_user_paths)
        # + not resolve on another machine. Readers join against ~/.geode/petri/logs/.
        "eval_archive": (Path(eval_archive).name if eval_archive else None),
        "dim_means": {k: float(v) for k, v in dim_means.items()},
    }
    # E2 (2026-05-30) — fixed-ruler evidence. Recorded ONLY when a held-out bench
    # was scored (both fields present together); omitted entirely otherwise so
    # the row shape is unchanged for the no-bench path (additive, never a new
    # required key). ``held_out_fitness`` is the SAME 0-1 fitness_spec.compute_fitness on the
    # VERSION-FROZEN bench → comparable across generations, unlike the
    # co-evolving-pool ``fitness`` above. ``held_out_bench_id`` is the ruler's
    # content-address (so a silent edit to the "frozen" set is detectable).
    if held_out_fitness is not None and held_out_bench_id is not None:
        row["held_out_fitness"] = float(held_out_fitness)
        row["held_out_bench_id"] = str(held_out_bench_id)
    # E4 (2026-05-30) — fitness-noise decomposition + the explicit gain-evidence
    # verdict on the promoted baseline row. Each field is recorded only when present
    # (M=1 leaves within ``None``; pre-E4 promotes pass ``power_stats=None`` → the
    # whole block is omitted) so the row shape is unchanged for the legacy path —
    # additive, never a new required key.
    if power_stats is not None:
        if power_stats.within_mutation_stderr is not None:
            row["within_mutation_stderr"] = float(power_stats.within_mutation_stderr)
        if power_stats.between_seed_stderr is not None:
            row["between_seed_stderr"] = float(power_stats.between_seed_stderr)
        if power_stats.gain_ci_excludes_zero is not None:
            row["gain_ci_low"] = (
                float(power_stats.gain_ci_low) if power_stats.gain_ci_low is not None else None
            )
            row["gain_ci_high"] = (
                float(power_stats.gain_ci_high) if power_stats.gain_ci_high is not None else None
            )
            row["gain_ci_excludes_zero"] = bool(power_stats.gain_ci_excludes_zero)
            if power_stats.gain_verdict is not None:
                row["gain_verdict"] = str(power_stats.gain_verdict)
    # E5 (2026-05-30) — reproducibility pins (prompt_hash + applied_diff +
    # sampling_params + rng_seed) so the promoted baseline's row is independently
    # re-runnable. ``as_record_kwargs`` returns ONLY the present (non-None) pins, so
    # a pre-E5 promote (run_provenance=None) writes NO E5 key — the row shape is
    # unchanged (additive, never a new required key). The pins record WHAT WAS SENT
    # (auditability); they make no backend-determinism claim (see run_provenance).
    if run_provenance is not None:
        row.update(run_provenance.as_record_kwargs())
    archive_path = _baseline_archive_path()
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with archive_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _results_paths() -> tuple[Path, Path]:
    """Return ``(results.tsv, results.jsonl)`` — the TRACKED rolling results
    history the hub reads (git-tracked so the curve survives ``git clean``,
    same writer-destination invariant as mutations.jsonl / baseline_archive).

    The state split decoupled these from ``BASELINE_PATH`` (the LATEST baseline
    is runtime ~/.geode; this history is in-repo SoT) — they live alongside the
    tracked ledgers under ``AUTORESEARCH_STATE_DIR``.
    """
    return RESULTS_TSV_PATH, RESULTS_JSONL_PATH


def _append_results_row(tsv_row: str, jsonl_row: str) -> None:
    """Append one audit's pre-formatted results rows to disk.

    Fills the diagnosed wiring gap (PR-STATE-SELF-IMPROVING-RENAME 2026-06-01):
    ``format_results_tsv_row`` / ``format_results_jsonl_row`` output was
    PRINTED to stdout (``results_tsv:`` / ``results_jsonl:`` lines) but never
    persisted, so the self-improving hub's results section stayed empty while
    ``mutations.jsonl`` + ``baseline_archive.jsonl`` were written directly.

    Both files live under ``AUTORESEARCH_STATE_DIR`` (``core/self_improving/state/``);
    the ``.tsv`` gets the ``RESULTS_TSV_HEADER`` line on first write only (so it
    stays grep-friendly with stable columns), the ``.jsonl`` is header-less. Both
    are git-tracked (gitignore negations) so the rolling history survives
    ``git clean`` — same writer-destination-tracked invariant as the ledgers
    (PR-G5b #1350 precedent). Append-only; one row per audit (promoted or not).
    """
    tsv_path, jsonl_path = _results_paths()
    tsv_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not tsv_path.exists()
    with tsv_path.open("a", encoding="utf-8") as fh:
        if write_header:
            fh.write("\t".join(RESULTS_TSV_HEADER) + "\n")
        fh.write(tsv_row.rstrip("\n") + "\n")
    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(jsonl_row.rstrip("\n") + "\n")


def _write_baseline(
    dim_means: dict[str, float],
    dim_stderr: dict[str, float],
    *,
    admire_means: dict[str, float] | None = None,
    bench_means: dict[str, float] | None = None,
    sample_count: dict[str, int] | None = None,
    measurement_modality: dict[str, str] | None = None,
    eval_archive: str | None = None,
    session_id: str = "",
    commit: str = "",
    # PR-SIL-5THEME C2 (2026-05-23) — S6b bench provenance 영속화 슬롯.
    # PR-1 의 dim 측 provenance (sample_count + measurement_modality) 와
    # symmetric — bench 도 stderr + sample_count + rubric_version 으로
    # cohort-blind comparison 차단.
    bench_stderr: dict[str, float] | None = None,
    bench_sample_count: dict[str, int] | None = None,
    bench_rubric_version: str = "",
    # PR-PROMOTE-STAMP (2026-05-26) — when the operator forces promotion
    # via ``--promote`` instead of going through the ``_should_promote``
    # gate, stamp the baseline.json with a ``manual_promote`` marker so
    # later readers can distinguish operator-forced from gate-approved
    # promotions. Default ``False`` preserves the legacy stamp-free
    # auto-promote shape — callers that omit the flag produce identical
    # baselines to pre-PR.
    manual_promote: bool = False,
    # PR-MARGIN-FITNESS-SCALE (2026-05-30) — the fitness-scale stderr of
    # this audit (sample bootstrap). Persisted as ``raw.fitness_stderr`` so
    # the NEXT cycle's promote gate can read it as ``baseline_fitness_stderr``
    # (the prior σ in the gain-stderr margin). ``None`` (dry-run, summary-
    # only path) → key omitted → next gate falls back to the MC estimate.
    fitness_stderr: float | None = None,
    # E2 (2026-05-30) — fixed-ruler evidence threaded to the registry row.
    # ``None`` (default) → no held-out bench configured → the held-out fields are
    # omitted from the row (backward-compatible). The promote caller computes
    # these via ``score_held_out_bench`` when ``_train()._resolve_held_out_bench()`` is set.
    held_out_fitness: float | None = None,
    held_out_bench_id: str | None = None,
    # E3 (2026-05-30) — control-arm tag forwarded to the registry row + the epoch
    # spec. ``"gate"`` (default) reproduces today's selection-arm row + epoch.
    promote_policy: str = "gate",
    promote_policy_seed: int = 0,
    # E4 (2026-05-30) — the fitness-noise DECOMPOSITION (persisted on the promoted
    # baseline's ``raw`` namespace alongside ``fitness_stderr``) + the explicit
    # gain-evidence verdict (on the registry row), bundled into ONE optional
    # parameter. ``None`` (default) → the keys are omitted (backward-compatible: an
    # M=1 / pre-E4 baseline keeps its exact shape).
    power_stats: PowerRecordFields | None = None,
    # E5 (2026-05-30) — reproducibility pins (prompt_hash + applied_diff +
    # sampling_params + rng_seed) forwarded to the registry row so the promoted
    # baseline is independently re-runnable. ``None`` (default) → no E5 key written
    # (backward-compatible — a pre-E5 baseline keeps its exact shape).
    run_provenance: RunProvenanceFields | None = None,
) -> None:
    """Persist current audit's aggregates as the new baseline.

    PR-2 of petri-schema-v2 (2026-05-23) — schema_version=2 namespace
    layout. The legacy v1 flat ``{dim_means, dim_stderr,
    [admire_means], [bench_means]}`` payload is replaced with a
    namespace-split shape::

        {"schema_version": 2,
         "session_id": "<run id>",
         "commit": "<git sha>",
         "ts_utc": "<ISO 8601>",
         "raw": {
            "dim_means": {dim: float},
            "dim_stderr": {dim: float},
            "sample_count": {dim: int},
            "measurement_modality": {dim: str},
            "fitness_stderr": float,          # PR-MARGIN-FITNESS-SCALE (optional)
            "eval_archive": "<path>" | null,
            "rubric_version": "v3-22dim-PR0",
         },
         "axes": {
            "admire_means": {field: float} | null,
            "bench_means":  {field: float} | null,
         }}

    The ``normalized`` / ``fitness`` / ``audit`` / ``promotion``
    namespaces from the SOT plan land in PR-3/4/5 — this PR establishes
    the schema_version split + ``raw`` + ``axes`` shape.

    Caller decides *when* to write (auto-promote rule vs ``--promote``
    manual override) and supplies the new provenance args from
    ``run_audit``'s return tuple.
    """
    from datetime import UTC, datetime

    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw_payload: dict[str, Any] = {
        "dim_means": {k: float(v) for k, v in dim_means.items()},
        "dim_stderr": {k: float(v) for k, v in dim_stderr.items()},
        "rubric_version": measure.PETRI_RUBRIC_VERSION,
        "eval_archive": eval_archive,
    }
    if sample_count:
        raw_payload["sample_count"] = {k: int(v) for k, v in sample_count.items()}
    if measurement_modality:
        raw_payload["measurement_modality"] = {k: str(v) for k, v in measurement_modality.items()}
    # PR-MARGIN-FITNESS-SCALE (2026-05-30) — persist the audit's fitness-scale
    # stderr so the next cycle's promote gate reads it as the prior σ.
    if fitness_stderr is not None:
        raw_payload["fitness_stderr"] = float(fitness_stderr)
    # E4 (2026-05-30) — the within-mutation / between-seed decomposition (both on
    # the 0-1 fitness scale). Recorded only when present (M=1 leaves within ``None``
    # → omitted) so the ``raw`` namespace stays backward-compatible.
    if power_stats is not None and power_stats.within_mutation_stderr is not None:
        raw_payload["within_mutation_stderr"] = float(power_stats.within_mutation_stderr)
    if power_stats is not None and power_stats.between_seed_stderr is not None:
        raw_payload["between_seed_stderr"] = float(power_stats.between_seed_stderr)
    # PR-SIL-5THEME C2 — bench provenance slots. dim 측 PR-1 패턴과 symmetric.
    if bench_stderr:
        raw_payload["bench_stderr"] = {k: float(v) for k, v in bench_stderr.items()}
    if bench_sample_count:
        raw_payload["bench_sample_count"] = {k: int(v) for k, v in bench_sample_count.items()}
    if bench_rubric_version:
        raw_payload["bench_rubric_version"] = str(bench_rubric_version)
    axes_payload: dict[str, Any] = {
        "admire_means": ({k: float(v) for k, v in admire_means.items()} if admire_means else None),
        "bench_means": ({k: float(v) for k, v in bench_means.items()} if bench_means else None),
    }
    # PR-BASELINE-REGISTRY (2026-05-30) — allocate the registry id + freeze a
    # single timestamp shared by the anchor stamp and the registry row.
    _now = datetime.now(UTC)
    _ts_utc = _now.strftime("%Y-%m-%dT%H:%M:%SZ")
    baseline_id = _next_baseline_id(_now)
    baseline_payload: dict[str, Any] = {
        "schema_version": 2,
        "baseline_id": baseline_id,  # links the active anchor to its registry row
        "session_id": session_id,
        "commit": commit,
        "ts_utc": _ts_utc,
        "raw": raw_payload,
        "axes": axes_payload,
    }
    # PR-PROMOTE-STAMP (2026-05-26) — operator-forced promotion via
    # ``--promote`` stamps the baseline so audit-trail readers (e.g.
    # ``/self-improving status``, observability indexer) can tell that
    # the value was bypass-promoted, not gate-approved. Closes the
    # silent-equivalence ambiguity flagged in the 2026-05-26 sprint
    # Phase A audit (§5.5 ``baseline.json`` promoted SoT discussion).
    if manual_promote:
        baseline_payload["manual_promote"] = True
        baseline_payload["promoted_by"] = "operator"
        baseline_payload["promoted_at"] = baseline_payload["ts_utc"]
    # PR-MUTATION-EMIT-WIRE (2026-05-27) — read prior_baseline_path
    # *before* the write so the BASELINE_PROMOTED payload can carry
    # both old + new paths. The reserve docstring
    # (core/hooks/system.py:289-291) requires:
    #   {"baseline_path": str, "prior_baseline_path": str,
    #    "ts": float, "run_id": str, "reason": str}
    prior_baseline_path_str = str(BASELINE_PATH) if BASELINE_PATH.exists() else ""
    BASELINE_PATH.write_text(
        json.dumps(baseline_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    # PR-BASELINE-REGISTRY (2026-05-30) — append the registry row only AFTER the
    # anchor write succeeds, so the registry never lists a baseline whose anchor
    # write failed. margin_rule = the current code's gate rule (fitness-stderr);
    # the pre-fix vanilla baseline is backfilled separately as "dim-stderr".
    _append_baseline_registry_row(
        baseline_id,
        dim_means=dim_means,
        dim_stderr=dim_stderr,
        sample_count=sample_count,
        measurement_modality=measurement_modality,
        admire_means=admire_means,
        bench_means=bench_means,
        fitness_stderr=fitness_stderr,
        margin_rule=_CURRENT_MARGIN_RULE,
        eval_archive=eval_archive,
        session_id=session_id,
        commit=commit,
        ts_utc=_ts_utc,
        promoted_by="operator" if manual_promote else "gate",
        # E2 (2026-05-30) — fixed-ruler evidence (omitted from the row when None).
        held_out_fitness=held_out_fitness,
        held_out_bench_id=held_out_bench_id,
        # E3 (2026-05-30) — control-arm tag → registry row + epoch spec.
        promote_policy=promote_policy,
        promote_policy_seed=promote_policy_seed,
        # E4 (2026-05-30) — fitness-noise decomposition + gain-evidence verdict.
        power_stats=power_stats,
        # E5 (2026-05-30) — reproducibility pins forwarded to the registry row.
        run_provenance=run_provenance,
    )
    # Emit BASELINE_PROMOTED after the write succeeds. ``reason``
    # quotes the gate verdict text from ``_should_promote`` (or the
    # ``operator`` literal when ``--promote`` bypassed the gate).
    from core.hooks.system import HookEvent
    from core.self_improving.loop._hooks import _fire_hook

    _fire_hook(
        HookEvent.BASELINE_PROMOTED,
        {
            "baseline_path": str(BASELINE_PATH),
            "prior_baseline_path": prior_baseline_path_str,
            "ts": time.time(),
            "run_id": session_id,
            "reason": "operator_force" if manual_promote else "gate_approved",
        },
    )
