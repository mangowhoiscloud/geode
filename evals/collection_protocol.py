"""Collection protocol for trajectories that may later become learning data.

The 2026-11-26 RL-readiness audit found evaluation evidence that could not be
reused for training: one run per task, harness diagnostics scored as agent
failures, and no variance next to reported differences. This module owns the
rules that close those gaps at collection time:

* repeat minimums per purpose, and A/A-bounded materiality;
* label hygiene: a versioned contamination detector and invalid flags written
  onto native receipts;
* reward-group and preference-pair construction from same-config repeats;
* variance reporting (Wilson intervals, within-task disagreement, pass@k,
  pass^k, A/A width beside a bootstrap interval).

Run-spec and learning-view validators read these rules instead of redefining
them. Agent outputs are not reproducible on the subscription routes, so every
estimate here is over repeated samples, never over one trajectory.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from core.llm.errors import parse_model_action_message

DETECTOR_VERSION = "geode.contamination-detector@1"

# Minimum same-config repetitions per collection purpose.
REPEAT_MINIMUMS: dict[str, int] = {
    "diagnostic": 1,
    # Same-config baseline runs per campaign; materiality must exceed their width.
    "aa-baseline": 2,
    # Per task. The exact k comes from the campaign's power admission.
    "evaluation-gate": 3,
    # Same-config runs before success/failure pairs are formed.
    "preference": 4,
    # Group size for group-relative RL; all-same-reward groups are dropped.
    "rl-group": 16,
}

# Flags that make an episode's reward a harness fact, not an agent label.
INVALIDATING_FLAGS = frozenset({"harness_error_text", "provider_error_text"})
_PROVIDER_ERROR = re.compile(
    r"rate_limit_exceeded|rate_limit_error|insufficient_quota|Too Many Requests"
    r"|Error code: 429|HTTP 429"
)
_Z95 = 1.959963984540054


def check_repetitions(purpose: str, k: int) -> None:
    """Refuse a plan with fewer same-config repetitions than ``purpose`` needs."""
    if purpose not in REPEAT_MINIMUMS:
        raise ValueError(f"unknown repetition purpose: {purpose}")
    if k < REPEAT_MINIMUMS[purpose]:
        raise ValueError(f"{purpose} needs k >= {REPEAT_MINIMUMS[purpose]}, got {k}")


# --- label hygiene -----------------------------------------------------------


def detect_contamination(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Flag transcript turns written by the harness or provider, not a policy.

    Scans agent and user-simulator turns (the simulator may itself run on
    GEODE). ``harness_error_text`` is a relayed model-action diagnostic and
    ``provider_error_text`` a raw provider throttle/quota error; both
    invalidate the episode. ``empty_response`` is recorded for review only:
    an empty turn can be the policy's own failure.
    """
    flags: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        role = str(message.get("role") or "")
        if role not in {"assistant", "user"}:
            continue
        content = message.get("content")
        text = content if isinstance(content, str) else ""
        if error_type := parse_model_action_message(text):
            flags.append(
                {
                    "kind": "harness_error_text",
                    "message_index": index,
                    "role": role,
                    "error_type": error_type,
                }
            )
        elif _PROVIDER_ERROR.search(text):
            flags.append({"kind": "provider_error_text", "message_index": index, "role": role})
        elif not text.strip() and not message.get("tool_calls"):
            flags.append({"kind": "empty_response", "message_index": index, "role": role})
    return flags


def label_hygiene(messages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return the ``label_hygiene`` record a rollout or native receipt carries."""
    flags = detect_contamination(messages)
    invalid = any(flag["kind"] in INVALIDATING_FLAGS for flag in flags)
    return {
        "detector": DETECTOR_VERSION,
        "validity": "invalid" if invalid else "valid",
        "flags": flags,
    }


def annotate_tau2_results(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a tau2 ``results.json`` with a hygiene record on every simulation.

    The original reward stays untouched; consumers read
    ``geode_label_hygiene.validity`` before admitting it as a label.
    """
    simulations = raw.get("simulations")
    if not isinstance(simulations, list):
        raise ValueError("tau2 results simulations must be a list")
    annotated = []
    for sim in simulations:
        messages = sim.get("messages") or []
        annotated.append({**sim, "geode_label_hygiene": label_hygiene(messages)})
    return {**raw, "simulations": annotated}


# --- repeats: A/A, RL groups, preference pairs ------------------------------


def aa_variation(baselines: Sequence[Mapping[str, float]]) -> dict[str, Any]:
    """Measure same-config baseline spread: pass-rate width and flipped tasks.

    Each baseline maps task ID to a 0/1 (or bounded) reward over one task set.
    """
    check_repetitions("aa-baseline", len(baselines))
    tasks = set(baselines[0])
    if not tasks or any(set(run) != tasks for run in baselines):
        raise ValueError("A/A baselines must cover the same non-empty task set")
    ordered = sorted(tasks)
    rates = [statistics.fmean(run[task] for task in ordered) for run in baselines]
    flipped = [task for task in ordered if len({run[task] for run in baselines}) > 1]
    return {
        "runs": len(baselines),
        "tasks": len(ordered),
        "pass_rates": rates,
        "width": max(rates) - min(rates),
        "flipped_tasks": flipped,
    }


def check_materiality(materiality: float, aa: Mapping[str, Any]) -> None:
    """A promotion threshold at or below the measured A/A width admits noise."""
    if materiality <= float(aa["width"]):
        raise ValueError(
            f"materiality {materiality:g} does not exceed measured A/A width {aa['width']:g}"
        )


def informative_groups(
    rows: Sequence[Mapping[str, Any]], *, k: int = REPEAT_MINIMUMS["rl-group"]
) -> dict[str, Any]:
    """Group same-config rollouts per example; keep groups with reward variance.

    A group whose rewards are all equal has zero group-relative advantage, so
    it is dropped and should be resampled. Groups smaller than ``k`` are
    reported as undersampled rather than silently used.
    """
    check_repetitions("rl-group", k)
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["example_id"])].append(row)
    kept: dict[str, list[Mapping[str, Any]]] = {}
    uniform: list[str] = []
    undersampled: list[str] = []
    for example_id, members in sorted(groups.items()):
        if len(members) < k:
            undersampled.append(example_id)
        elif len({member["reward"] for member in members}) == 1:
            uniform.append(example_id)
        else:
            kept[example_id] = members
    return {"kept": kept, "dropped_uniform": uniform, "undersampled": undersampled}


def preference_pairs(runs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Pair higher- and lower-reward runs of one example and one configuration.

    Each run carries ``rollout_id``, ``reward``, ``config_sha256`` and ordered
    ``events`` of ``{"actor", "digest"}``. A pair records the first event
    ordinal where the two runs differ and who acted there, because a user
    simulator or environment turn can decide the outcome instead of the agent.
    """
    check_repetitions("preference", len(runs))
    if len({run["config_sha256"] for run in runs}) != 1:
        raise ValueError("preference pairs need runs from one configuration")
    pairs = []
    for chosen in runs:
        for rejected in runs:
            if chosen["reward"] <= rejected["reward"]:
                continue
            a, b = chosen["events"], rejected["events"]
            ordinal = next(
                (i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y),
                min(len(a), len(b)),
            )
            pairs.append(
                {
                    "chosen": chosen["rollout_id"],
                    "rejected": rejected["rollout_id"],
                    "first_divergence": ordinal,
                    "divergence_actor": {
                        "chosen": a[ordinal]["actor"] if ordinal < len(a) else None,
                        "rejected": b[ordinal]["actor"] if ordinal < len(b) else None,
                    },
                }
            )
    return pairs


# --- variance reporting ------------------------------------------------------


def wilson_interval(passes: int, n: int, z: float = _Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial pass rate."""
    if n <= 0 or not 0 <= passes <= n:
        raise ValueError("need 0 <= passes <= n and n > 0")
    p = passes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that at least one of k draws (without replacement) passes."""
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k: probability that all k draws pass (reliability)."""
    return math.comb(c, k) / math.comb(n, k)


def variance_report(rows: Sequence[Mapping[str, Any]], *, k: int | None = None) -> dict[str, Any]:
    """Summarize repeated 0/1 outcomes per task and across the task set.

    ``rows`` carry ``example_id`` and boolean ``passed``. Within-task
    disagreement is the share of same-task attempt pairs whose outcomes differ.
    """
    outcomes: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        outcomes[str(row["example_id"])].append(bool(row["passed"]))
    if not outcomes:
        raise ValueError("variance report needs at least one row")
    counts = {key: (len(values), sum(values)) for key, values in sorted(outcomes.items())}
    per_task: dict[str, dict[str, Any]] = {}
    for example_id, (n, c) in counts.items():
        lo, hi = wilson_interval(c, n)
        per_task[example_id] = {"passes": c, "k": n, "rate": c / n, "wilson_95": [lo, hi]}
    total_pairs = sum(math.comb(n, 2) for n, _c in counts.values())
    differing = sum(c * (n - c) for n, c in counts.values())
    within = [c * (n - c) / (n * (n - 1)) for n, c in counts.values() if n > 1]
    rates = [c / n for n, c in counts.values()]
    depth = k or min(n for n, _c in counts.values())
    eligible = [(n, c) for n, c in counts.values() if n >= depth]
    return {
        "tasks": len(counts),
        "attempts": sum(n for n, _c in counts.values()),
        "per_task": per_task,
        "mixed_tasks": sum(0 < c < n for n, c in counts.values()),
        "within_task_disagreement": differing / total_pairs if total_pairs else None,
        "variance": {
            "between_task": statistics.pvariance(rates) if len(rates) > 1 else 0.0,
            "within_task": statistics.fmean(within) if within else None,
        },
        "k": depth,
        "pass_at_k": statistics.fmean(pass_at_k(n, c, depth) for n, c in eligible),
        "pass_hat_k": statistics.fmean(pass_hat_k(n, c, depth) for n, c in eligible),
    }


def comparison_report(
    difference: float, interval: Sequence[float], aa: Mapping[str, Any]
) -> dict[str, Any]:
    """Put the same-config A/A width beside a bootstrap difference interval."""
    lo, hi = float(interval[0]), float(interval[1])
    width = float(aa["width"])
    return {
        "difference": difference,
        "bootstrap_interval": [lo, hi],
        "aa_width": width,
        "aa_runs": aa["runs"],
        "exceeds_aa_width": lo > width or hi < -width,
    }


# --- CLI ---------------------------------------------------------------------


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    variance = commands.add_parser("variance", help="variance report from JSONL rows")
    variance.add_argument("rows", type=Path)
    variance.add_argument("--k", type=int)
    annotate = commands.add_parser("annotate-tau2", help="add hygiene flags to results.json")
    annotate.add_argument("results", type=Path)
    annotate.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "variance":
        rows = [json.loads(line) for line in args.rows.read_text().splitlines() if line.strip()]
        print(json.dumps(variance_report(rows, k=args.k), indent=2, sort_keys=True))
        return
    raw = json.loads(args.results.read_text(encoding="utf-8"))
    annotated = annotate_tau2_results(raw)
    args.out.write_text(json.dumps(annotated, ensure_ascii=False, indent=2) + "\n")
    invalid = sum(
        sim["geode_label_hygiene"]["validity"] == "invalid" for sim in annotated["simulations"]
    )
    print(f"annotated {len(annotated['simulations'])} simulations, invalid={invalid}")


if __name__ == "__main__":
    _main()
