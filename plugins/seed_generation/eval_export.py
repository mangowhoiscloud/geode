"""Convert seed-generation run artifacts into inspect_ai ``.eval`` files.

PR-SEEDS-EVAL-EXPORT (2026-05-25). The self-improving loop's
seed-generation pipeline produces JSON artefacts under
``state/seed_generation/<run_id>/`` and mirrors a publishable subset
into ``docs/self-improving/petri-bundle/seeds/<run_id>/`` (handled by
:mod:`plugins.seed_generation.bundle_sync`). An inspect_ai SPA viewer
only recognises ``.eval`` log archives, so the JSON-only seed runs never
appeared in a viewer's task list. This module bridges that gap.

PR-SEEDGEN-BUNDLE-SPLIT (2026-05-29). These ``.eval`` files publish to
the seed-generation's own inspect bundle
(``docs/self-improving/seed-generation/bundle/``), not the audit
petri-bundle.

PR-SEEDGEN-EVAL-ALIGN (2026-05-29). Each per-sample datum lives in exactly
ONE viewer tab — the earlier enrich pass triplicated the same content across
MESSAGES, the TRANSCRIPT ``ModelEvent``, and the TRANSCRIPT ``InfoEvent`` (and
the score scalars showed in both the Score's metadata and the sample's
metadata). The clean 3-axis split:
  - TRANSCRIPT ← a single ``InfoEvent`` carrying the phase's full structured
    output (the critic reflection / pilot dim_means+stderr / ranker Elo /
    evolver rewrite / meta-review). One record, one place.
  - SCORING    ← ``EvalSample.scores``: the headline numeric value + a plain
    ``explanation`` of what the metric means (no "(No Explanation)"); the
    output scalars are NOT re-copied here.
  - METADATA   ← ``EvalSample.metadata``: provenance only (iteration, task
    id) — never the output scalars or the score.
  - MESSAGES   ← removed: a seed-generation phase is a structured output, not
    a chat, so the synthetic user/assistant turns added nothing the Info
    event did not already say. The generator's seed ``.md`` body stays in
    ``EvalSample.output`` (and its dedicated candidate viewer page).
The EvalLog aggregate ``results.scores`` summary is kept (additive).

The conversion strategy is **one phase per ``.eval`` file**. Each of the
8 seed-generation pipeline phases (``supervisor`` / ``generator`` /
``proximity`` / ``critic`` / ``pilot`` / ``ranker`` / ``evolver`` /
``meta_reviewer``) becomes a separate inspect_ai task. Phases with no
data in the run's ``state.json`` are skipped.

The produced ``.eval`` files must pass ``scripts/validate_petri_bundle.
py`` which enforces ``status='success'`` + non-empty ``results.scores``
with non-empty ``metrics`` on every score, so each phase fabricates a
minimal but meaningful single-metric score derived from the phase's
own semantics (yield ratio, dedupe ratio, coverage breadth, etc.).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.memory.atomic_write import read_json_or_none

log = logging.getLogger(__name__)

__all__ = ["PHASE_TASKS", "export_run_to_evals"]


# Phase task name → human-readable description. Used for the inspect_ai
# task field, which the SPA viewer surfaces as the task card title.
PHASE_TASKS: dict[str, str] = {
    "supervisor": "seed-generation/supervisor",
    "generator": "seed-generation/generator",
    "proximity": "seed-generation/proximity",
    "critic": "seed-generation/critic",
    "pilot": "seed-generation/pilot",
    "ranker": "seed-generation/ranker",
    "evolver": "seed-generation/evolver",
    "meta_reviewer": "seed-generation/meta_reviewer",
}


def _new_id(prefix: str = "") -> str:
    """Generate an inspect_ai-style 22-char id (base62-ish, uuid4-backed)."""
    return f"{prefix}{uuid4().hex[:22]}"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _coerce_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _coerce_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def _read_json(path: Path) -> dict[str, Any] | None:
    # Shared silent reader (core.memory.atomic_write) + this module's warning:
    # a present-but-unparseable artefact is worth surfacing here.
    data = read_json_or_none(path)
    if data is None and path.exists():
        log.warning("eval_export: failed to read %s", path)
    return data


def _drop_empty(d: dict[str, Any]) -> dict[str, Any]:
    """Drop None / empty-container values — keeps a tab's data block tight
    (no ``null`` rows) while preserving falsy-but-real values like ``0``."""
    return {k: v for k, v in d.items() if v is not None and v not in ("", [], {})}


def export_run_to_evals(
    run_dir: Path | str,
    dest_dir: Path | str,
    *,
    mutator_model: str = "claude-cli/claude-opus-4-7",
) -> list[Path]:
    """Convert a seed-generation run's JSON artefacts into per-phase
    ``.eval`` files inside ``dest_dir``.

    Returns the list of ``.eval`` paths written. Phases with no usable
    data are skipped silently. The caller is responsible for adding
    the produced files to ``logs/listing.json`` (typically through
    :func:`plugins.petri_audit.bundle_sync.sync_eval_to_bundle`).

    ``mutator_model`` is the GEODE-style model id recorded as the
    ``execute`` model role for phases that drive an LLM call. Defaults
    to the operator's typical mutator binding.
    """
    from inspect_ai.event import InfoEvent
    from inspect_ai.log import EvalLog, EvalSample, write_eval_log
    from inspect_ai.log._log import (
        EvalConfig,
        EvalDataset,
        EvalMetric,
        EvalResults,
        EvalScore,
        EvalSpec,
        EvalStats,
    )
    from inspect_ai.model import ModelOutput
    from inspect_ai.scorer import Score

    def text_output(text: str) -> ModelOutput:
        """Wrap a string into a minimal ModelOutput. Empty/falsy text
        yields a content of ``""`` (the default factory is *not* used
        because the validator-required ``choices[0].message.content``
        must exist)."""
        return ModelOutput.from_content(model=mutator_model, content=text or "")

    run_dir_path = Path(run_dir)
    dest_dir_path = Path(dest_dir)
    dest_dir_path.mkdir(parents=True, exist_ok=True)

    def phase_events(payload: Any, info_source: str) -> list[Any]:
        """One ``InfoEvent`` per sample — the TRANSCRIPT tab's single source.

        PR-SEEDGEN-EVAL-ALIGN (2026-05-29) — drops the ``messages`` +
        ``ModelEvent`` that triplicated this same content. A dict payload
        becomes the event's ``data`` (the full structured output). A string
        payload (the generator seed body) returns ``[]`` — that body lives in
        ``EvalSample.output``, not an escaped-JSON string blob. Empty → ``[]``.
        """
        if not isinstance(payload, dict):
            return []
        info_fields = _drop_empty(payload)
        return [InfoEvent(data=info_fields, source=info_source)] if info_fields else []

    state = _read_json(run_dir_path / "state.json")
    if state is None:
        log.warning("eval_export: state.json missing under %s, skipping", run_dir_path)
        return []
    # survivors.json + meta_review.json are best-effort. The state.json
    # already carries the same data nested; the side files exist so that
    # the bundle viewer can read them without parsing the full state.
    _read_json(run_dir_path / "survivors.json")
    meta_doc = _read_json(run_dir_path / "meta_review.json") or {}

    run_id = str(state.get("run_id") or run_dir_path.name)
    gen_tag = str(state.get("gen_tag") or "")
    target_dim = str(state.get("target_dim") or "")
    started_at = state.get("started_at") or _now()
    iteration = state.get("current_iteration")
    max_iterations = state.get("max_iterations")
    iter_ctx = {"iteration": iteration, "max_iterations": max_iterations}

    candidates = _coerce_list(state.get("candidates"))
    reflections = _coerce_dict(state.get("reflections"))
    pilot_scores = _coerce_dict(state.get("pilot_scores"))
    similarity_clusters = _coerce_list(state.get("similarity_clusters"))
    removed_duplicates = _coerce_list(state.get("removed_duplicates"))
    elo_ratings = _coerce_dict(state.get("elo_ratings"))
    survivor_ids = _coerce_list(state.get("survivors"))
    evolved_candidates = _coerce_list(state.get("evolved_candidates"))
    supervisor_guidance = _coerce_dict(state.get("supervisor_guidance"))
    meta = meta_doc or _coerce_dict(state.get("meta_review"))

    def build_log(
        phase: str,
        samples: list[EvalSample],
        score_value: float,
        score_meta: dict[str, Any] | None = None,
    ) -> Path | None:
        """Common EvalLog construction + write. Returns the path or
        ``None`` when there are no samples (caller signals nothing to
        publish for this phase).
        """
        if not samples:
            return None
        task_name = PHASE_TASKS[phase]
        task_id = _new_id()
        eval_id = _new_id()
        run_id_inner = _new_id()
        spec = EvalSpec(
            created=started_at,
            task=task_name,
            dataset=EvalDataset(
                name=f"{run_id}/{phase}",
                samples=len(samples),
                sample_ids=[str(s.id) for s in samples][:10],
                shuffled=False,
            ),
            model=mutator_model,
            config=EvalConfig(
                limit=len(samples),
                epochs=1,
                fail_on_error=False,
                log_samples=True,
            ),
            task_id=task_id,
            eval_id=eval_id,
            run_id=run_id_inner,
            tags=[gen_tag, target_dim, "seed-generation"],
            metadata={
                "seed_run_id": run_id,
                "gen_tag": gen_tag,
                "target_dim": target_dim,
                "phase": phase,
                **(score_meta or {}),
            },
        )
        # Validator demands non-empty results.scores with non-empty
        # metrics on each score. The single-metric ``mean`` shape is
        # what inspect_petri also emits for its judge dims, so the
        # viewer renders it consistently with the audit cards.
        results = EvalResults(
            total_samples=len(samples),
            completed_samples=len(samples),
            scores=[
                EvalScore(
                    name=phase,
                    scorer=f"seed-generation/{phase}",
                    metrics={"mean": EvalMetric(name="mean", value=float(score_value))},
                )
            ],
        )
        log_obj = EvalLog(
            version=2,
            status="success",
            eval=spec,
            results=results,
            stats=EvalStats(started_at=started_at, completed_at=_now()),
            samples=samples,
        )
        ts_safe = started_at.replace(":", "-").replace("+", "-")
        dest_path = dest_dir_path / f"{ts_safe}_seedgen-{phase}_{run_id}.eval"
        write_eval_log(log_obj, str(dest_path))
        # Register into the bundle's logs/listing.json so the inspect_ai
        # SPA viewer shows the phase as a task card. Re-uses the
        # audit-side helpers (same listing contract); per-call try /
        # except keeps a listing failure from blocking the rest of the
        # phase loop.
        try:
            from plugins.petri_audit.bundle_sync import (
                _extract_listing_entry,
                _merge_listing,
            )

            entry = _extract_listing_entry(dest_path)
            _merge_listing(dest_dir_path / "listing.json", dest_path.name, entry)
        except Exception:
            log.warning(
                "eval_export: listing.json merge failed for %s",
                dest_path,
                exc_info=True,
            )
        log.info("eval_export: wrote %s (samples=%d)", dest_path.name, len(samples))
        return dest_path

    def candidate_md_text(candidate: dict[str, Any]) -> str:
        # Prefer the published bundle copy: ``candidate["path"]`` is an
        # absolute LOCAL state path (state/seed_generation/...) that does not
        # exist in a fresh checkout / CI, which would silently empty the
        # generator MESSAGES tab. The bundle ships ``candidates/<cid>.md``
        # (+ evolved / survivors copies) under run_dir.
        cid = str(candidate.get("id") or "").strip()
        if cid:
            for sub in ("candidates", "candidates_evolved", "survivors"):
                p = run_dir_path / sub / f"{cid}.md"
                if p.is_file():
                    try:
                        return p.read_text(encoding="utf-8")[:20000]
                    except OSError:
                        pass
        cpath = candidate.get("path")
        if isinstance(cpath, str):
            p = Path(cpath)
            if p.exists():
                try:
                    return p.read_text(encoding="utf-8")[:20000]
                except OSError:
                    pass
        return ""

    def make_score(value: Any, *, answer: str = "", explanation: str = "") -> Score:
        """Coerce a value into a per-sample Score (graceful on non-numeric).

        ``explanation`` is always supplied by callers so the SCORING tab never
        shows "(No Explanation)". The output scalars are NOT copied into the
        score metadata — they live once, in the InfoEvent record (TRANSCRIPT).
        """
        try:
            v: Any = float(value)
        except (TypeError, ValueError):
            v = str(value)
        return Score(value=v, answer=answer or None, explanation=explanation or None)

    written: list[Path] = []

    # --- supervisor ---------------------------------------------------
    if supervisor_guidance:
        sup_samples = [
            EvalSample(
                id="supervisor-guidance",
                epoch=1,
                input=f"Guide next-gen for target_dim={target_dim}",
                target="",
                output=text_output(json.dumps(supervisor_guidance, ensure_ascii=False)[:4000]),
                events=phase_events(supervisor_guidance, "seed-generation/supervisor"),
                scores={
                    "supervisor": make_score(
                        1.0,
                        answer="emitted",
                        explanation="strategy guidance produced for the next generation",
                    )
                },
                metadata=_drop_empty(dict(iter_ctx)),
            )
        ]
        result = build_log("supervisor", sup_samples, score_value=1.0)
        if result is not None:
            written.append(result)

    # --- generator ----------------------------------------------------
    if candidates:
        gen_samples = []
        for c in candidates:
            cd = _coerce_dict(c)
            cid = str(cd.get("id") or _new_id())
            body = candidate_md_text(cd)
            gen_samples.append(
                EvalSample(
                    id=cid,
                    epoch=1,
                    input=f"Draft a seed for target_dim={cd.get('target_dim', target_dim)}",
                    target="",
                    output=text_output(body),
                    events=phase_events(body, "seed-generation/generator"),
                    scores={
                        "generator": make_score(
                            cd.get("duration_ms") or 0.0,
                            answer="latency (ms)",
                            explanation="seed draft latency in milliseconds",
                        )
                    },
                    metadata=_drop_empty({"task_id": cd.get("task_id"), **iter_ctx}),
                )
            )
        requested = int(state.get("candidates_requested") or len(gen_samples) or 1)
        yield_ratio = len(gen_samples) / max(requested, 1)
        result = build_log(
            "generator",
            gen_samples,
            score_value=yield_ratio,
            score_meta={
                "candidates_requested": requested,
                "candidates_drafted": len(gen_samples),
            },
        )
        if result is not None:
            written.append(result)

    # --- proximity ----------------------------------------------------
    if similarity_clusters:
        prox_samples = []
        for cluster in similarity_clusters:
            cl = _coerce_dict(cluster)
            cluster_id = str(cl.get("cluster_id") or _new_id("cluster-"))
            similar = _coerce_list(cl.get("similar_hypotheses"))
            prox_samples.append(
                EvalSample(
                    id=cluster_id,
                    epoch=1,
                    input=cl.get("topic", "") or "",
                    target="",
                    output=text_output(json.dumps(similar, ensure_ascii=False)),
                    events=phase_events(
                        {
                            "topic": cl.get("topic"),
                            "similar_hypotheses": similar,
                            "removed_duplicates": removed_duplicates,
                        },
                        "seed-generation/proximity",
                    ),
                    scores={
                        "proximity": make_score(
                            float(len(similar)),
                            answer="cluster size",
                            explanation="number of near-duplicate hypotheses in this cluster",
                        )
                    },
                    metadata=_drop_empty(dict(iter_ctx)),
                )
            )
        unique = len(candidates) - len(removed_duplicates)
        ratio = (unique / len(candidates)) if candidates else 1.0
        result = build_log(
            "proximity",
            prox_samples,
            score_value=ratio,
            score_meta={
                "clusters": len(prox_samples),
                "removed_duplicates": len(removed_duplicates),
            },
        )
        if result is not None:
            written.append(result)

    # --- critic -------------------------------------------------------
    if reflections:
        crit_samples = []
        for cid, refl in reflections.items():
            rd = _coerce_dict(refl)
            disc = rd.get("discrimination_estimate")
            crit_samples.append(
                EvalSample(
                    id=str(cid),
                    epoch=1,
                    input=f"Critique candidate {cid}",
                    target="",
                    output=text_output(str(rd.get("rewrite_section") or "")),
                    events=phase_events(
                        {
                            "strengths": rd.get("strengths", []),
                            "weaknesses": rd.get("weaknesses", []),
                            "rewrite_section": rd.get("rewrite_section", ""),
                            "judge_risk": rd.get("judge_risk"),
                            "discrimination_estimate": disc,
                            "intended_dim_match": rd.get("intended_dim_match"),
                        },
                        "seed-generation/critic",
                    ),
                    scores={
                        "critic": make_score(
                            disc,
                            answer="discrimination",
                            explanation=(
                                "discrimination estimate (0–1): how cleanly the seed "
                                "separates strong vs weak agents; judge_risk + "
                                "intended_dim_match in transcript"
                            ),
                        )
                    },
                    metadata=_drop_empty(dict(iter_ctx)),
                )
            )
        d_values = [
            float(_coerce_dict(r).get("discrimination_estimate") or 0.0)
            for r in reflections.values()
        ]
        d_avg = sum(d_values) / len(d_values) if d_values else 0.0
        result = build_log(
            "critic",
            crit_samples,
            score_value=d_avg,
            score_meta={"avg_discrimination_estimate": d_avg},
        )
        if result is not None:
            written.append(result)

    # --- pilot --------------------------------------------------------
    if pilot_scores:
        pilot_samples = []
        for cid, pscore in pilot_scores.items():
            pd = _coerce_dict(pscore)
            dim_means = _coerce_dict(pd.get("dim_means"))
            target_val = dim_means.get(target_dim)
            pilot_samples.append(
                EvalSample(
                    id=str(cid),
                    epoch=1,
                    input=f"Pilot-evaluate candidate {cid}",
                    target="",
                    output=text_output(f"{target_dim} mean = {target_val}"),
                    events=phase_events(
                        {
                            "status": pd.get("status"),
                            "dim_means": dim_means,
                            "dim_stderr": pd.get("dim_stderr", {}),
                        },
                        "seed-generation/pilot",
                    ),
                    scores={
                        "pilot": make_score(
                            target_val,
                            answer=target_dim,
                            explanation=(
                                f"pilot mean for '{target_dim}' on the Petri 1–10 scale; "
                                "full dim_means + stderr in transcript"
                            ),
                        )
                    },
                    metadata=_drop_empty(dict(iter_ctx)),
                )
            )
        target_dim_means = [
            float(_coerce_dict(p).get("dim_means", {}).get(target_dim) or 0.0)
            for p in pilot_scores.values()
        ]
        target_mean = sum(target_dim_means) / len(target_dim_means) if target_dim_means else 0.0
        result = build_log(
            "pilot",
            pilot_samples,
            score_value=target_mean,
            score_meta={
                "target_dim": target_dim,
                "target_dim_mean": target_mean,
                "n_candidates_piloted": len(pilot_samples),
            },
        )
        if result is not None:
            written.append(result)

    # --- ranker -------------------------------------------------------
    # Voters are per-MATCH (``vote-m<NN>-v<NN>``), not per-candidate, so a
    # candidate sample carries its Elo as a Score + an InfoEvent rather than
    # a single agent dialogue.
    if elo_ratings:
        rank_samples = []
        survivor_set = {str(s) for s in survivor_ids}
        for cid, rating in elo_ratings.items():
            survived = str(cid) in survivor_set
            rank_samples.append(
                EvalSample(
                    id=str(cid),
                    epoch=1,
                    input=f"Rank candidate {cid}",
                    target="",
                    output=text_output("survived" if survived else "eliminated"),
                    events=phase_events(
                        {"elo_rating": rating, "survived": survived},
                        "seed-generation/ranker",
                    ),
                    scores={
                        "ranker": make_score(
                            rating,
                            answer="Elo",
                            explanation="post-tournament Elo rating; survival flag in transcript",
                        )
                    },
                    metadata=_drop_empty(dict(iter_ctx)),
                )
            )
        survivors_count = len(survivor_ids)
        total = len(rank_samples)
        survival_ratio = (survivors_count / total) if total else 0.0
        result = build_log(
            "ranker",
            rank_samples,
            score_value=survival_ratio,
            score_meta={
                "n_ranked": total,
                "n_survived": survivors_count,
                "elo_distribution": _coerce_dict(meta.get("elo_distribution")),
            },
        )
        if result is not None:
            written.append(result)

    # --- evolver ------------------------------------------------------
    if evolved_candidates:
        evo_samples = []
        for ev in evolved_candidates:
            ed = _coerce_dict(ev)
            evo_samples.append(
                EvalSample(
                    id=str(ed.get("id") or _new_id()),
                    epoch=1,
                    input=f"Evolve from parent {ed.get('parent_id')}",
                    target="",
                    output=text_output(str(ed.get("notes") or "")),
                    events=phase_events(
                        {
                            "parent_id": ed.get("parent_id"),
                            "rewrite_section": ed.get("rewrite_section"),
                            "notes": ed.get("notes"),
                        },
                        "seed-generation/evolver",
                    ),
                    scores={
                        "evolver": make_score(
                            ed.get("duration_ms") or 0.0,
                            answer="latency (ms)",
                            explanation="evolution latency in milliseconds",
                        )
                    },
                    metadata=_drop_empty(dict(iter_ctx)),
                )
            )
        ey = _coerce_dict(meta.get("evolution_yield"))
        attempted = int(ey.get("attempted") or len(evo_samples) or 1)
        successful = int(ey.get("successful") or len(evo_samples))
        ratio = (successful / attempted) if attempted else 0.0
        result = build_log(
            "evolver",
            evo_samples,
            score_value=ratio,
            score_meta={"attempted": attempted, "successful": successful},
        )
        if result is not None:
            written.append(result)

    # --- meta_reviewer ------------------------------------------------
    if meta:
        coverage = _coerce_dict(meta.get("coverage"))
        underrepresented = _coerce_list(meta.get("underrepresented_dims"))
        overrepresented = _coerce_list(meta.get("overrepresented_dims"))
        priors = _coerce_list(meta.get("next_gen_priors"))
        covered_dims = sum(1 for v in coverage.values() if isinstance(v, int) and v > 0)
        total_dims = len(coverage) or 1
        breadth = covered_dims / total_dims
        meta_samples = [
            EvalSample(
                id="meta-review",
                epoch=1,
                input=f"Review run {run_id}",
                target="",
                output=text_output(str(meta.get("session_summary") or "")[:4000]),
                events=phase_events(
                    {
                        "session_summary": meta.get("session_summary"),
                        "coverage": coverage,
                        "next_gen_priors": priors,
                        "underrepresented_dims": underrepresented,
                        "overrepresented_dims": overrepresented,
                        "evolution_yield": _coerce_dict(meta.get("evolution_yield")),
                        "elo_distribution": _coerce_dict(meta.get("elo_distribution")),
                    },
                    "seed-generation/meta_reviewer",
                ),
                scores={
                    "meta_reviewer": make_score(
                        breadth,
                        answer=f"{covered_dims}/{total_dims} dims",
                        explanation="dimension coverage breadth = covered_dims / total_dims",
                    )
                },
                metadata=_drop_empty(dict(iter_ctx)),
            )
        ]
        result = build_log(
            "meta_reviewer",
            meta_samples,
            score_value=breadth,
            score_meta={
                "covered_dims": covered_dims,
                "total_dims": total_dims,
                "n_priors": len(priors),
            },
        )
        if result is not None:
            written.append(result)

    log.info(
        "eval_export: %d phase(s) written for run_id=%s into %s",
        len(written),
        run_id,
        dest_dir_path,
    )
    return written
