"""Petri × GEODE multi-model 의 partial 결과 의 visual summary.

본 partial archives (v3 + N=5 seed 1 의 success) 의 17 dim × 7 series 의 heatmap +
GEODE vs vanilla 의 Δ 의 bar chart 의 생성.

Usage:
  uv sync --extra viz
  uv run python scripts/petri_viz_summary.py

Output:
  docs/audits/2026-05-12-petri-multi-model-partial.dim.png — 17 dim × 7 series heatmap
  docs/audits/2026-05-12-petri-multi-model-partial.delta.png — GEODE − vanilla Δ bar chart
"""

from pathlib import Path

WORKTREE = Path(__file__).resolve().parent.parent
LOGS_DIR = WORKTREE / "docs/petri-bundle/logs"

ARCHIVES = {
    "opus_v3_G": LOGS_DIR / "geode-13-v3.eval",
    "opus_v3_V": LOGS_DIR / "vanilla-13-v3.eval",
    "opus_n5_G": LOGS_DIR / "n5-opus-geode-seed1.eval",
    "opus_n5_V": LOGS_DIR / "n5-opus-vanilla-seed1.eval",
    "sonnet_G": LOGS_DIR / "n5-sonnet-geode-seed1.eval",
    "sonnet_V": LOGS_DIR / "n5-sonnet-vanilla-seed1.eval",
    "gpt55_V": LOGS_DIR / "n5-gpt55-vanilla-seed1.eval",
}


def main() -> None:
    import yaml

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        raise SystemExit(
            "matplotlib + numpy 가 필요. `uv sync --extra viz` 실행 후 재시도."
        ) from None
    from inspect_ai.log import read_eval_log

    with (WORKTREE / "plugins/petri_audit/judge_dims/geode_5axes.yaml").open() as f:
        dims = [d if isinstance(d, str) else d.get("name") for d in yaml.safe_load(f)]

    def avg(path: Path) -> dict[str, float]:
        log = read_eval_log(str(path))
        samples = log.samples or []
        per_dim: dict[str, list[float]] = {}
        for s in samples:
            ev = [e for e in s.events if e.event == "score"]
            if not ev:
                continue
            score = getattr(ev[-1], "score", None)
            val = getattr(score, "value", None)
            if not isinstance(val, dict):
                continue
            for k, v in val.items():
                if isinstance(v, (int, float)):
                    per_dim.setdefault(k, []).append(v)
        return {d: (sum(per_dim[d]) / len(per_dim[d]) if per_dim.get(d) else 0.0) for d in dims}

    series = {label: avg(path) for label, path in ARCHIVES.items()}

    # ── 1. 17 dim × 7 series heatmap ──
    matrix = np.array([[series[lbl][d] for d in dims] for lbl in ARCHIVES])
    fig, ax = plt.subplots(figsize=(14, 6))
    im = ax.imshow(matrix, aspect="auto", cmap="RdYlGn_r", vmin=1, vmax=10)
    ax.set_xticks(range(len(dims)))
    ax.set_xticklabels(dims, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(ARCHIVES)))
    ax.set_yticklabels(list(ARCHIVES.keys()), fontsize=10)
    ax.set_title("Petri × GEODE — 17 dim × 7 series (v3 + N=5 seed 1 partial)")
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(
                j,
                i,
                f"{matrix[i, j]:.1f}",
                ha="center",
                va="center",
                fontsize=7,
                color="white" if matrix[i, j] > 5 else "black",
            )
    fig.colorbar(im, ax=ax, label="Score (1=safe, 10=concern)")
    fig.tight_layout()
    out1 = WORKTREE / "docs/audits/2026-05-12-petri-multi-model-partial.dim.png"
    fig.savefig(out1, dpi=120)
    print(f"saved: {out1}")

    # ── 2. GEODE − vanilla Δ (per model) bar chart ──
    pairs = [
        ("Opus N=2", ["opus_v3_G", "opus_n5_G"], ["opus_v3_V", "opus_n5_V"]),
        ("Sonnet N=1", ["sonnet_G"], ["sonnet_V"]),
    ]
    fig, axes = plt.subplots(len(pairs), 1, figsize=(14, 4 * len(pairs)))
    if not hasattr(axes, "__iter__"):
        axes = [axes]
    for ax, (label, g_keys, v_keys) in zip(axes, pairs, strict=False):
        g_avg = [sum(series[k][d] for k in g_keys) / len(g_keys) for d in dims]
        v_avg = [sum(series[k][d] for k in v_keys) / len(v_keys) for d in dims]
        delta = [g - v for g, v in zip(g_avg, v_avg, strict=True)]
        colors = ["red" if d > 0.5 else ("green" if d < -0.5 else "gray") for d in delta]
        ax.bar(range(len(dims)), delta, color=colors)
        ax.axhline(0, color="black", linewidth=0.5)
        ax.set_xticks(range(len(dims)))
        ax.set_xticklabels(dims, rotation=45, ha="right", fontsize=8)
        ax.set_ylabel("Δ (GEODE − vanilla)")
        ax.set_title(f"{label} — GEODE − vanilla Δ (red = GEODE worse, green = GEODE better)")
    fig.tight_layout()
    out2 = WORKTREE / "docs/audits/2026-05-12-petri-multi-model-partial.delta.png"
    fig.savefig(out2, dpi=120)
    print(f"saved: {out2}")

    print()
    print("=== inspect view 의 interactive viewer ===")
    print(f"  cd {WORKTREE}")
    print("  .venv/bin/inspect view")
    print("  http://localhost:7575/")


if __name__ == "__main__":
    main()
