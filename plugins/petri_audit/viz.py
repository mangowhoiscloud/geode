"""Visualization helpers for Petri audit results.

Renders the 5 chart types defined in
``docs/plans/eval-petri-p3b-2-execution.md`` § Reporting & Visualization:

1. ``heatmap`` — per-dimension score, sample × dim
2. ``cost``    — role-stacked cost bar (USD + KRW)
3. ``tool``    — GEODE tool-call frequency histogram
4. ``agree``   — judge-vs-judge agreement scatter
5. ``trend``   — phase-over-phase score line

All matplotlib / inspect_viz imports are deferred to the rendering
function so importing :mod:`plugins.petri_audit.viz` itself stays
cold-start clean. The ``[viz]`` extra (``uv sync --extra viz``)
provides matplotlib + seaborn + plotly + inspect_viz.

Two input shapes are supported:
- **Direct data** — caller passes already-parsed scores / costs.
  Useful for tests + unit work without an actual eval log.
- **Eval log** — :func:`render_from_eval_log` accepts the path of an
  inspect_ai ``*.eval`` file and uses ``inspect_ai.log`` to parse it.
  This path needs the ``[audit]`` extra.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "VizError",
    "available_charts",
    "render_agreement",
    "render_cost_breakdown",
    "render_from_eval_log",
    "render_heatmap",
    "render_tool_frequency",
    "render_trend",
]

_CHART_TYPES: tuple[str, ...] = ("heatmap", "cost", "tool", "agree", "trend")


class VizError(RuntimeError):
    """Raised when ``[viz]`` extra is missing or rendering fails."""


def available_charts() -> tuple[str, ...]:
    """Return the chart type identifiers handled by :func:`render_from_eval_log`."""
    return _CHART_TYPES


def _ensure_matplotlib() -> Any:
    try:
        import matplotlib

        matplotlib.use("Agg")  # headless — required for CLI / CI
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise VizError(
            "[viz] extra not installed. Run `uv sync --extra viz` to "
            "install matplotlib + seaborn + plotly + inspect_viz."
        ) from exc
    return plt


def _ensure_output_dir(output_path: str | Path) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def render_heatmap(
    scores: Mapping[str, Sequence[float]],
    output_path: str | Path,
    *,
    title: str = "Petri audit — per-dimension score",
) -> Path:
    """Sample × dimension heatmap. ``scores[dim] = [s0, s1, ...]``."""
    if not scores:
        raise VizError("Empty scores — nothing to render.")
    plt = _ensure_matplotlib()
    out = _ensure_output_dir(output_path)

    dims = list(scores.keys())
    sample_count = max(len(v) for v in scores.values())
    matrix = [list(scores[d]) + [float("nan")] * (sample_count - len(scores[d])) for d in dims]

    fig, ax = plt.subplots(figsize=(max(4, sample_count * 0.8), max(2, len(dims) * 0.6)))
    im = ax.imshow(matrix, aspect="auto", cmap="RdYlGn_r", vmin=0.0, vmax=1.0)
    ax.set_yticks(range(len(dims)))
    ax.set_yticklabels(dims)
    ax.set_xticks(range(sample_count))
    ax.set_xticklabels([f"s{i}" for i in range(sample_count)])
    ax.set_xlabel("sample")
    ax.set_title(title)
    fig.colorbar(im, ax=ax, label="score")
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def render_cost_breakdown(
    usd_by_role: Mapping[str, float],
    output_path: str | Path,
    *,
    krw_rate: int = 1_400,
    gate_krw: int | None = 5_000,
    title: str = "Petri audit — cost breakdown",
) -> Path:
    """Role-stacked cost bar. Optional KRW gate hline (default 5K)."""
    if not usd_by_role:
        raise VizError("Empty cost dict — nothing to render.")
    plt = _ensure_matplotlib()
    out = _ensure_output_dir(output_path)

    roles = list(usd_by_role.keys())
    usd_values = [usd_by_role[r] for r in roles]
    krw_values = [v * krw_rate for v in usd_values]

    fig, ax = plt.subplots(figsize=(5, 4))
    bars = ax.bar(roles, krw_values, color=["#1f77b4", "#ff7f0e", "#2ca02c"][: len(roles)])
    ax.set_ylabel(f"cost (KRW @ 1USD={krw_rate})")
    ax.set_title(title)
    if gate_krw is not None:
        ax.axhline(gate_krw, color="red", linestyle="--", label=f"{gate_krw:,} KRW gate")
        ax.legend()
    for bar, usd in zip(bars, usd_values, strict=False):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"${usd:.2f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def render_tool_frequency(
    counts: Mapping[str, int],
    output_path: str | Path,
    *,
    title: str = "Petri audit — GEODE tool-call frequency",
) -> Path:
    """GEODE tool-call frequency histogram. ``counts[tool] = n``."""
    if not counts:
        raise VizError("Empty counts — nothing to render.")
    plt = _ensure_matplotlib()
    out = _ensure_output_dir(output_path)

    tools = sorted(counts, key=lambda k: counts[k], reverse=True)
    values = [counts[t] for t in tools]

    fig, ax = plt.subplots(figsize=(max(4, len(tools) * 0.6), 4))
    ax.bar(tools, values, color="#4c72b0")
    ax.set_ylabel("call count")
    ax.set_title(title)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def render_agreement(
    pairs: Sequence[tuple[float, float]],
    output_path: str | Path,
    *,
    judge_a: str = "judge_a",
    judge_b: str = "judge_b",
    title: str = "Judge agreement",
) -> Path:
    """Scatter judge_a vs judge_b score for each (transcript, dim)."""
    if not pairs:
        raise VizError("Empty pairs — nothing to render.")
    plt = _ensure_matplotlib()
    out = _ensure_output_dir(output_path)

    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]

    fig, ax = plt.subplots(figsize=(4.5, 4.5))
    ax.scatter(xs, ys, alpha=0.7)
    ax.plot([0, 1], [0, 1], color="grey", linestyle=":", label="perfect agreement")
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.set_xlabel(judge_a)
    ax.set_ylabel(judge_b)
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def render_trend(
    series: Mapping[str, Sequence[tuple[str, float]]],
    output_path: str | Path,
    *,
    title: str = "Phase trend",
) -> Path:
    """Line chart of phase-over-phase mean score per dimension.

    ``series[dim] = [(phase, mean_score), ...]``.
    """
    if not series:
        raise VizError("Empty series — nothing to render.")
    plt = _ensure_matplotlib()
    out = _ensure_output_dir(output_path)

    fig, ax = plt.subplots(figsize=(6, 4))
    for dim, points in series.items():
        if not points:
            continue
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        ax.plot(xs, ys, marker="o", label=dim)
    ax.set_xlabel("phase")
    ax.set_ylabel("mean score")
    ax.set_title(title)
    ax.set_ylim(-0.05, 1.05)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def render_from_eval_log(
    log_path: str | Path,
    chart: str,
    output_path: str | Path,
) -> Path:
    """Render directly from an ``inspect_ai`` eval log.

    Lazy-imports ``inspect_ai.log`` (the ``[audit]`` extra). Currently
    handles ``heatmap`` directly; other chart types fall through to a
    not-yet-supported error so callers can route to the data-direct
    helpers above.
    """
    if chart not in _CHART_TYPES:
        raise VizError(
            f"Unknown chart {chart!r}; expected one of {', '.join(_CHART_TYPES)}."
        )

    try:
        from inspect_ai.log import read_eval_log
    except ImportError as exc:
        raise VizError(
            "[audit] extra not installed. Run `uv sync --extra audit` to "
            "install inspect-ai + inspect-petri."
        ) from exc

    eval_log = read_eval_log(str(log_path))

    if chart == "heatmap":
        scores: dict[str, list[float]] = {}
        for sample in getattr(eval_log, "samples", None) or []:
            sample_scores = getattr(sample, "scores", None) or {}
            for dim_name, dim_score in sample_scores.items():
                value = getattr(dim_score, "value", None)
                if isinstance(value, int | float):
                    scores.setdefault(dim_name, []).append(float(value))
        if not scores:
            raise VizError(
                f"No scored samples in {log_path!s}; nothing to plot."
            )
        return render_heatmap(scores, output_path)

    raise VizError(
        f"Chart {chart!r} from eval log is not yet wired — pass parsed data to "
        f"render_{chart}() directly. See plan § Reporting & Visualization."
    )
