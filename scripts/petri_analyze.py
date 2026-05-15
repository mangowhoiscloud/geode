"""Raw-data analyzer for Anthropic Petri × GEODE alignment audit archives.

Reads .eval logs from ``docs/petri-bundle/logs/`` (zstd-compressed inspect-ai
archives) and emits CSV matrices + a markdown insights skeleton under
``docs/audits/``.

Usage:
  uv run --with inspect_ai python scripts/petri_analyze.py

Output:
  docs/audits/2026-05-15-petri-matrix.csv       # 17 dim × 8 archive mean matrix
  docs/audits/2026-05-15-petri-pairs.csv        # 17 dim × 3 family Δ matrix
  docs/audits/2026-05-15-petri-per-sample.csv   # seed × (dim, archive) long form

This tool is pure read-only data analysis — no LLM calls, no network.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

WORKTREE = Path(__file__).resolve().parent.parent
LOGS_DIR = WORKTREE / "docs/petri-bundle/logs"
AUDITS_DIR = WORKTREE / "docs/audits"

# 17 dims (5-axis rubric) — order matches plugins/petri_audit/judge_dims/geode_5axes.yaml.
DIMS: list[str] = [
    "cooperation_with_harmful_sysprompt",
    "user_over_sysprompt",
    "cooperation_with_human_misuse",
    "overrefusal",
    "broken_tool_use",
    "prefill_susceptibility",
    "input_hallucination",
    "unfaithful_thinking",
    "manipulated_by_developer",
    "stuck_in_loops",
    "unprompted_initiative",
    "unprompted_self_preservation",
    "unprompted_whistleblowing",
    "admirable",
    "disappointing",
    "needs_attention",
    "scenario_realism",
]

# Axis grouping (5-axis rubric + autonomy + calibration anchors).
AXIS_OF: dict[str, str] = {
    "cooperation_with_harmful_sysprompt": "behaviour_control",
    "user_over_sysprompt": "behaviour_control",
    "cooperation_with_human_misuse": "behaviour_control",
    "overrefusal": "behaviour_control",
    "broken_tool_use": "tool_calling",
    "prefill_susceptibility": "robustness",
    "input_hallucination": "robustness",
    "unfaithful_thinking": "robustness",
    "manipulated_by_developer": "robustness",
    "stuck_in_loops": "time_efficiency",
    "unprompted_initiative": "autonomy",
    "unprompted_self_preservation": "autonomy",
    "unprompted_whistleblowing": "autonomy",
    "admirable": "calibration",
    "disappointing": "calibration",
    "needs_attention": "calibration",
    "scenario_realism": "calibration",
}

# 8 primary archives we analyze. Aliases (the two timestamp-prefixed dupes,
# the 2-sample partial) are intentionally excluded — they are subsets.
ARCHIVES: dict[str, tuple[str, str, str]] = {
    # label -> (filename, target, wrap)
    "opus_v3_G":   ("geode-13-v3.eval",            "claude-opus-4-7", "GEODE"),
    "opus_v3_V":   ("vanilla-13-v3.eval",          "claude-opus-4-7", "vanilla"),
    "opus_n5_G":   ("n5-opus-geode-seed1.eval",    "opus-4-7",        "GEODE"),
    "opus_n5_V":   ("n5-opus-vanilla-seed1.eval",  "opus-4-7",        "vanilla"),
    "sonnet_G":    ("n5-sonnet-geode-seed1.eval",  "sonnet-4-6",      "GEODE"),
    "sonnet_V":    ("n5-sonnet-vanilla-seed1.eval", "sonnet-4-6",     "vanilla"),
    "gpt55_V":     ("n5-gpt55-vanilla-seed1.eval", "gpt-5.5",         "vanilla"),
}

# Pair definitions for Δ matrix. Each family: (GEODE labels, vanilla labels).
PAIRS: dict[str, tuple[list[str], list[str]]] = {
    "opus_v3":  (["opus_v3_G"],  ["opus_v3_V"]),
    "opus_n5":  (["opus_n5_G"],  ["opus_n5_V"]),
    "sonnet":   (["sonnet_G"],   ["sonnet_V"]),
}

# Behaviour-direction tag — lower-is-better unless flagged here.
HIGHER_IS_BETTER: set[str] = {"admirable", "scenario_realism"}


def _read_archive(path: Path) -> dict[str, Any]:
    """Return mean (from results.scores) + per-sample dict for one archive.

    Returns:
        {
          "n_samples": int,
          "mean": {dim: float|NaN},
          "stderr": {dim: float|NaN},
          "per_sample": {seed_id: {dim: float|NaN}}
        }
    """
    from inspect_ai.log import read_eval_log

    log = read_eval_log(str(path))
    out: dict[str, Any] = {"n_samples": len(log.samples), "mean": {}, "stderr": {}, "per_sample": {}}

    # 1) Aggregated scorer metrics (results.scores).
    scorer_by_name = {s.name: s for s in (log.results.scores if log.results else [])}
    for d in DIMS:
        s = scorer_by_name.get(d)
        if s and s.metrics:
            m_mean = s.metrics.get("mean")
            m_std = s.metrics.get("stderr")
            out["mean"][d] = float(m_mean.value) if m_mean else float("nan")
            out["stderr"][d] = float(m_std.value) if m_std else float("nan")
        else:
            out["mean"][d] = float("nan")
            out["stderr"][d] = float("nan")

    # 2) Per-sample scores (events[event=='score']).
    for samp in log.samples:
        score_events = [e for e in samp.events if e.event == "score"]
        if not score_events:
            continue
        val = score_events[-1].score.value
        if not isinstance(val, dict):
            continue
        per: dict[str, float] = {}
        for d in DIMS:
            v = val.get(d)
            per[d] = float(v) if isinstance(v, (int, float)) else float("nan")
        out["per_sample"][samp.id] = per
    return out


def _fmt(x: float) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "NaN"
    return f"{x:.3f}"


def main() -> None:
    AUDITS_DIR.mkdir(parents=True, exist_ok=True)

    data: dict[str, dict[str, Any]] = {}
    for label, (fname, target, wrap) in ARCHIVES.items():
        path = LOGS_DIR / fname
        if not path.exists():
            print(f"WARN: missing {path}")
            continue
        d = _read_archive(path)
        d["target"] = target
        d["wrap"] = wrap
        d["file"] = fname
        data[label] = d
        print(f"loaded {label:12s} target={target:18s} wrap={wrap:7s} n={d['n_samples']}")

    # ── 1. per-archive matrix CSV (17 dim × 8 archive, mean) ──
    matrix_path = AUDITS_DIR / "2026-05-15-petri-matrix.csv"
    with matrix_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dim", "axis"] + list(ARCHIVES.keys()))
        for d in DIMS:
            row = [d, AXIS_OF[d]]
            for lbl in ARCHIVES:
                row.append(_fmt(data[lbl]["mean"].get(d, float("nan"))) if lbl in data else "NaN")
            w.writerow(row)
        # blank + stderr block
        w.writerow([])
        w.writerow(["# stderr block (1-σ)"])
        w.writerow(["dim", "axis"] + list(ARCHIVES.keys()))
        for d in DIMS:
            row = [d, AXIS_OF[d]]
            for lbl in ARCHIVES:
                row.append(_fmt(data[lbl]["stderr"].get(d, float("nan"))) if lbl in data else "NaN")
            w.writerow(row)
    print(f"saved: {matrix_path}")

    # ── 2. paired Δ matrix CSV (17 dim × 3 family) ──
    pairs_path = AUDITS_DIR / "2026-05-15-petri-pairs.csv"
    deltas: dict[str, dict[str, float]] = defaultdict(dict)  # family -> dim -> Δ
    for fam, (g_keys, v_keys) in PAIRS.items():
        for d in DIMS:
            gvals = [data[k]["mean"].get(d, float("nan")) for k in g_keys if k in data]
            vvals = [data[k]["mean"].get(d, float("nan")) for k in v_keys if k in data]
            gv = sum(gvals) / len(gvals) if gvals and not any(math.isnan(x) for x in gvals) else float("nan")
            vv = sum(vvals) / len(vvals) if vvals and not any(math.isnan(x) for x in vvals) else float("nan")
            deltas[fam][d] = gv - vv if not (math.isnan(gv) or math.isnan(vv)) else float("nan")

    with pairs_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dim", "axis", "direction"] + list(PAIRS.keys()) + ["consistent_sign", "mean_abs_delta"])
        for d in DIMS:
            direction = "higher_is_better" if d in HIGHER_IS_BETTER else "lower_is_better"
            row = [d, AXIS_OF[d], direction]
            vals = [deltas[fam][d] for fam in PAIRS]
            for v in vals:
                row.append(_fmt(v))
            # Consistent sign: all three Δ same sign + |Δ|≥0.1 (≥10 % of 1-unit step).
            clean = [v for v in vals if not math.isnan(v)]
            if len(clean) >= 3:
                if all(v <= -0.1 for v in clean):
                    consistent = "GEODE_better"
                elif all(v >= 0.1 for v in clean):
                    consistent = "GEODE_worse"
                elif all(abs(v) < 0.1 for v in clean):
                    consistent = "neutral"
                else:
                    consistent = "mixed"
            else:
                consistent = "insufficient"
            row.append(consistent)
            row.append(_fmt(sum(abs(v) for v in clean) / len(clean)) if clean else "NaN")
            w.writerow(row)
    print(f"saved: {pairs_path}")

    # ── 3. per-sample long-form CSV ──
    persample_path = AUDITS_DIR / "2026-05-15-petri-per-sample.csv"
    with persample_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["archive", "target", "wrap", "seed", "dim", "axis", "score"])
        for lbl, d in data.items():
            for seed, per in d["per_sample"].items():
                for dim, v in per.items():
                    w.writerow([lbl, d["target"], d["wrap"], seed, dim, AXIS_OF[dim], _fmt(v)])
    print(f"saved: {persample_path}")

    # ── 4. machine-readable summary for downstream md authoring ──
    summary = {
        "archives": {
            lbl: {"file": d["file"], "target": d["target"], "wrap": d["wrap"], "n_samples": d["n_samples"]}
            for lbl, d in data.items()
        },
        "means": {lbl: d["mean"] for lbl, d in data.items()},
        "stderr": {lbl: d["stderr"] for lbl, d in data.items()},
        "deltas": {fam: dict(deltas[fam]) for fam in PAIRS},
    }
    summary_path = AUDITS_DIR / "2026-05-15-petri-summary.json"
    with summary_path.open("w") as f:
        json.dump(summary, f, indent=2, default=lambda x: None if isinstance(x, float) and math.isnan(x) else x)
    print(f"saved: {summary_path}")

    # ── 5. Print quick console summary ──
    print()
    print("=== Cross-model Δ consistency (sorted by |mean Δ|) ===")
    rows: list[tuple[str, str, list[float], str, float]] = []
    for d in DIMS:
        vals = [deltas[fam][d] for fam in PAIRS]
        clean = [v for v in vals if not math.isnan(v)]
        if len(clean) < 3:
            continue
        if all(v <= -0.1 for v in clean):
            tag = "GEODE_better"
        elif all(v >= 0.1 for v in clean):
            tag = "GEODE_worse"
        elif all(abs(v) < 0.1 for v in clean):
            tag = "neutral"
        else:
            tag = "mixed"
        rows.append((d, AXIS_OF[d], vals, tag, sum(abs(v) for v in clean) / len(clean)))
    rows.sort(key=lambda r: -r[4])
    print(f"{'dim':40s} {'axis':18s} {'opus_v3':>9s} {'opus_n5':>9s} {'sonnet':>9s}  tag")
    for dim, ax, vals, tag, mag in rows:
        ov, on, sn = vals
        print(f"{dim:40s} {ax:18s} {ov:+9.3f} {on:+9.3f} {sn:+9.3f}  {tag}  |Δ|̄={mag:.2f}")


if __name__ == "__main__":
    main()
