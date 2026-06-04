#!/usr/bin/env python3
"""Build `docs/self-improving/index.html` for the GEODE Self-Improving Hub.

Reads live data at build time and renders the static landing page:

- `docs/self-improving/petri-bundle/logs/listing.json`     -> Petri audit table (top-10)
- `docs/self-improving/petri-bundle/seeds/listing.json`    -> Seed-generation table
- `state/autoresearch/baseline.json`      -> Autoresearch baseline row
   (falls back to most recent `baseline.json.outdated-*` with a stale flag
   per design contract §10 of the master DESIGN.md)
- `state/autoresearch/mutations.jsonl`    -> row count for autoresearch row
- `state/autoresearch/results.tsv`        -> row count for autoresearch row
- `state/autoresearch/policies/`          -> file count
- `pyproject.toml`                          -> GEODE version stamp

Page contract:   docs/design/self-improving-hub.md
Master tokens:   docs/design/self-improving-hub-system.md

CLI:
    python scripts/build_self_improving_hub.py
        [--bundle-root docs/self-improving/petri-bundle]
        [--state-dir state/autoresearch]
        [--out docs/self-improving/index.html]

The served section dir + URLs stay `docs/self-improving/autoresearch/` +
`/geode/self-improving/autoresearch/...` (the loop's lineage name) so deep
links + the Inspect-View `#/logs/<file>` routes do not break. Only the
READ path moved (PR-STATE-SELF-IMPROVING-RENAME 2026-06-01).

NOTE: `--bundle-root` defaults to `docs/self-improving/petri-bundle/` (post-Phase 3)
relocation the bundle moves to `docs/self-improving/petri-bundle/`; update the
default (or the CI invocation) accordingly.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import json
import logging
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist
from typing import Any
from urllib.parse import quote

LOG = logging.getLogger("build_self_improving_hub")

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "docs" / "self-improving" / "index.html.template"
DEFAULT_BUNDLE_ROOT = REPO_ROOT / "docs" / "self-improving" / "petri-bundle"
# PR-STATE-AUTORESEARCH-RENAME (2026-06-01, Scheme A) — the self-improving
# state DATA dir is ``state/autoresearch`` (mirrors
# ``core.paths.AUTORESEARCH_STATE_DIR``; this builder is intentionally
# stdlib-only so it cannot import core, hence the literal). Renamed from
# ``state/self_improving`` of #1955 to kill the underscore/hyphen twin. The
# SERVED output dir + URLs below keep the hyphenated lineage name to preserve
# deep links.
DEFAULT_STATE_DIR = REPO_ROOT / "state" / "autoresearch"
DEFAULT_OUT = REPO_ROOT / "docs" / "self-improving" / "index.html"
DEFAULT_SEEDGEN_OUT_DIR = REPO_ROOT / "docs" / "self-improving" / "seed-generation"
SEEDGEN_INDEX_TEMPLATE = (
    REPO_ROOT / "docs" / "self-improving" / "seed-generation" / "index.html.template"
)
SEEDGEN_RUN_TEMPLATE = (
    REPO_ROOT / "docs" / "self-improving" / "seed-generation" / "run.html.template"
)
DEFAULT_AUTORESEARCH_OUT_DIR = REPO_ROOT / "docs" / "self-improving" / "autoresearch"
AUTORESEARCH_LANDING_TEMPLATE = (
    REPO_ROOT / "docs" / "self-improving" / "autoresearch" / "index.html.template"
)
AUTORESEARCH_BASELINE_TEMPLATE = (
    REPO_ROOT / "docs" / "self-improving" / "autoresearch" / "baseline.html.template"
)
AUTORESEARCH_MUTATIONS_TEMPLATE = (
    REPO_ROOT / "docs" / "self-improving" / "autoresearch" / "mutations.html.template"
)
AUTORESEARCH_RESULTS_TEMPLATE = (
    REPO_ROOT / "docs" / "self-improving" / "autoresearch" / "results.html.template"
)
AUTORESEARCH_POLICIES_TEMPLATE = (
    REPO_ROOT / "docs" / "self-improving" / "autoresearch" / "policies.html.template"
)
AUTORESEARCH_EVIDENCE_TEMPLATE = (
    REPO_ROOT / "docs" / "self-improving" / "autoresearch" / "evidence.html.template"
)
AUTORESEARCH_RUNS_INDEX_TEMPLATE = (
    REPO_ROOT / "docs" / "self-improving" / "autoresearch" / "runs-index.html.template"
)
AUTORESEARCH_RUN_REPORT_TEMPLATE = (
    REPO_ROOT / "docs" / "self-improving" / "autoresearch" / "run-report.html.template"
)
# PR-HUB-RUN-REPORT (2026-06-04) — per-run campaign synthesis markdown SoT.
# Each ``docs/self-improving/run-*.md`` auto-registers as a /runs/<slug>/ page
# (slug = filename stem with the leading ``run-`` stripped). The page RENDERS
# the .md client-side via the shared Marked.js loader; the markdown is never
# duplicated into the template (single SoT, shared with the campaign video).
DEFAULT_RUN_REPORTS_DIR = REPO_ROOT / "docs" / "self-improving"
RUN_REPORT_GLOB = "run-*.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"

# E6 (2026-05-30) — the three control arms of the matched held-out comparison.
# Mirrors the writer-side ``_VALID_PROMOTE_POLICIES`` in ``core/self_improving/train.py``
# (kept stdlib-only here, in lockstep by ``test_evidence_arm_map_matches_core``).
# gate = selection arm; random = random-accept control; never = no-mutation floor.
_EVIDENCE_ARMS: tuple[tuple[str, str], ...] = (
    ("gate", "selection (promote gate)"),
    ("random", "random-accept control"),
    ("never", "no-mutation floor"),
)

# PR-HUB-CAMPAIGN-VIZ (2026-06-01) — the live 3-arm campaign per-cycle ledger.
# campaign-progress.log lives next to mutations.jsonl in the autoresearch state
# dir; the gen-0 K-mean snapshot is a SIBLING of the autoresearch root
# (``<repo>/state/campaign/gen-0-snapshot/``), written by the campaign runner.
_CAMPAIGN_PROGRESS_LOG = "campaign-progress.log"
_CAMPAIGN_GEN0_SNAPSHOT = ("state", "campaign", "gen-0-snapshot", "baseline.json")
# The Petri eval-log MANIFEST (one row per audit archive) + the Inspect-View
# deep-link base. The MANIFEST is the only ledger linking a cycle's completed_at
# to its .eval archive filename + the seeds it scored + its per-sample dims.
_AUDIT_MANIFEST = ("docs", "audits", "eval-logs", "MANIFEST.jsonl")
_EVAL_SUMMARY_DIR = ("docs", "audits", "eval-logs")
_PETRI_BUNDLE_DEEPLINK_BASE = "/geode/self-improving/petri-bundle/"
# A cycle's attribution-row ``ts`` is written within a few seconds of the audit
# archive's ``completed_at``; a generous 180s tolerance matches a cycle to its
# audit without ever stitching two distinct audits (they are >10min apart).
_AUDIT_MATCH_TOLERANCE_S = 180.0

# Per-cycle parse of campaign-progress.log. SoT for the line format is the campaign
# driver ``core/self_improving/campaign.py`` (the ``progress.emit(...)`` writers), kept
# in lockstep by ``test_campaign_regex_matches_digest_sot``.
# "... arm 'gate' cycle 3/10: fitness_after=0.67 fitness_delta=-0.13 held_out=0.79 reject ..."
_CAMPAIGN_CYCLE_RE = re.compile(
    r"arm '(?P<arm>\w+)' cycle (?P<n>\d+)/(?P<total>\d+): "
    r"(?:fitness_after=(?P<sel>[\d.]+) fitness_delta=(?P<delta>[-\d.]+) "
    r"held_out=(?P<held>[\d.]+) (?P<verdict>\w+)"
    r"|(?P<skip>SKIP[^\n]*))"
)
_CAMPAIGN_GEN0_RE = re.compile(
    r"gen-0 baseline repeat (?P<n>\d+)/(?P<total>\d+): "
    r"held_out=(?P<held>[\d.]+) fitness=(?P<sel>[\d.]+)"
)
_CAMPAIGN_NOISE_RE = re.compile(
    r"gen-0 noise band: K=(?P<k>\d+) held_out_mean=(?P<mean>[\d.]+) stderr=(?P<stderr>[\d.]+)"
)
_CAMPAIGN_TS_RE = re.compile(r"^(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)")

# E6 (2026-05-30) — the standard two-sample mean-difference power constants,
# MIRRORING the SoT in ``core/self_improving/loop/statistical_power.py`` (this
# builder is intentionally stdlib-only so it cannot import core). The defaults
# below are the same δ / α / power the writer powers for; the formula
# (``n ≈ 2(z_{α/2}+z_β)²σ²/δ²``) is reproduced in ``_required_n_seed`` so the page
# computes N from the RECORDED σ (never a fabricated number). Kept in lockstep by
# ``test_evidence_power_constants_match_core``.
_POWER_DEFAULT_TARGET_EFFECT_SIZE = 0.02
_POWER_DEFAULT_ALPHA = 0.05
_POWER_DEFAULT_POWER = 0.8

# 12-col header from core/self_improving/train.py:1284 RESULTS_TSV_HEADER.
# Verified against actual code (P-Phase-6 baseline 2026-05-26).
AUTORESEARCH_RESULTS_TSV_HEADER: tuple[str, ...] = (
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

# Baseline schema v2 namespaces rendered as 7 blocks on the baseline page.
# Per docs/design/self-improving-autoresearch-baseline.md §4.
AUTORESEARCH_BASELINE_NAMESPACES: tuple[str, ...] = (
    "metadata",
    "raw",
    "normalized",
    "axes",
    "fitness",
    "audit",
    "promotion",
)

# Sparkline characters from low to high.
_SPARKLINE_CHARS: str = "▁▂▃▄▅▆▇█"

DESIGN_SCHEMA_VERSION = 1
PETRI_ROW_LIMIT = 10
PETRI_SIDEBAR_LIMIT = 3
# Default mutator (single LLM per run for now — per DESIGN.md §7).
DEFAULT_MUTATOR_MODEL = "claude-cli/claude-opus-4-7"
# Canonical 20-dim subset displayed on the pilot-score heatmap (the two
# post-judge analytics dims were removed — PR-DROP-ANALYTICS-DIMS 2026-06-02).
PILOT_HEATMAP_DIMS: tuple[str, ...] = (
    "cooperation_with_harmful_sysprompt",
    "user_over_sysprompt",
    "cooperation_with_human_misuse",
    "overrefusal",
    "broken_tool_use",
    "prefill_susceptibility",
    "input_hallucination",
    "unfaithful_thinking",
    "manipulated_by_developer",
    "eval_awareness",
    "stuck_in_loops",
    "unprompted_sycophancy",
    "unprompted_initiative",
    "unprompted_self_preservation",
    "unprompted_whistleblowing",
    "scenario_realism",
    "context_overflow_handling",
    "stale_context_recall",
    "context_attribution",
    "needs_attention",
)

# Map provider prefix (model.split("/")[0]) -> chip class + chip label.
# Per master DESIGN.md §3 — 4 chips only; palette explosion forbidden.
HARNESS_MAP: dict[str, tuple[str, str]] = {
    "anthropic": ("payg", "PAYG"),
    "openai": ("payg", "PAYG"),
    "claude-cli": ("claude", "Claude Code"),
    "codex": ("codex", "Codex"),
    "openai-codex": ("codex", "Codex"),
    "geode": ("geode", "GEODE"),
}


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def html_escape(value: str) -> str:
    """Minimal HTML escape — no external dep."""
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def inspect_log_route(log_file: str) -> str:
    """Deep-link hash for the Inspect View SPA that opens a specific .eval.

    The bundled viewer is a hash router whose only log route is ``/logs/*``;
    it navigates via ``/logs/${encodeURIComponent(file)}`` (see the bundle's
    assets/index.js). There is **no** ``/tasks/`` route — ``#/tasks/<id>``
    silently falls back to the run list, so deep-links must key on the .eval
    *filename* (the logs/listing.json key), not the task_id. See the CANNOT
    rule in CLAUDE.md (PR-HUB-AUDIT-DEEPLINK, 2026-05-30).
    """
    return f"#/logs/{quote(log_file, safe='')}"


def read_pyproject_version(path: Path = PYPROJECT) -> str:
    """Extract `version = "..."` from pyproject.toml (PEP-518 table=project)."""
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError(f"version not found in {path}")
    return match.group(1)


def short_iso(timestamp: str | None) -> str:
    """Reformat an ISO 8601 string to `YYYY-MM-DD HH:MM` UTC (per §9)."""
    if not timestamp:
        return ""
    # Trim to YYYY-MM-DDTHH:MM
    head = timestamp[:16].replace("T", " ")
    return head


def _harness_chip(model: str) -> tuple[str, str]:
    """Resolve a model prefix to its chip CSS class + visible label.

    Centralised helper so hub + seedgen renderers stay in lockstep.
    Unknown prefixes default to PAYG per §3 of the master DESIGN.md
    (palette explosion forbidden — no fifth chip class).
    """
    if not model:
        return ("payg", "PAYG")
    prefix = model.split("/", 1)[0]
    return HARNESS_MAP.get(prefix, ("payg", "PAYG"))


def harness_chip(model: str) -> str:
    """Render a `<span class="chip ...">label</span> <code>model</code>` cell."""
    if not model:
        return '<span class="muted">.</span>'
    cls, label = _harness_chip(model)
    return f'<span class="chip {cls}">{html_escape(label)}</span> <code>{html_escape(model)}</code>'


def fmt_mtime(path: Path) -> str:
    if not path.exists():
        return "—"
    mtime = _dt.datetime.fromtimestamp(path.stat().st_mtime, tz=_dt.UTC)
    return mtime.strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------- #
# Data loading                                                                #
# --------------------------------------------------------------------------- #
@dataclass
class PetriRow:
    task_id: str
    log_file: str
    seeds: str
    auditor: str
    target: str
    judge: str
    started_at: str


@dataclass
class SeedGenRow:
    run_id: str
    gen_tag: str
    target_dim: str
    candidates_drafted: int
    survivors_count: int
    evolved_count: int
    usd_spent: float
    total_tokens: int = 0
    iterations: int = 0
    max_iterations: int = 0


def load_petri(bundle_root: Path) -> list[PetriRow]:
    listing = bundle_root / "logs" / "listing.json"
    if not listing.exists():
        LOG.warning("petri listing missing: %s", listing)
        return []
    raw: dict[str, dict[str, Any]] = json.loads(listing.read_text(encoding="utf-8"))
    rows: list[PetriRow] = []
    # The listing key IS the .eval filename the Inspect View hash router loads
    # via /logs/<encodeURIComponent(file)> — keep it so deep-links resolve.
    for fname, entry in raw.items():
        if entry.get("task") != "inspect_petri/audit":
            continue
        model_roles = entry.get("model_roles") or {}
        # `task_args_passed.limit` per DESIGN.md §5.1 — not present in current
        # listing schema; gracefully fall back to dataset.samples or "—".
        task_args = entry.get("task_args_passed") or {}
        dataset = entry.get("dataset") or {}
        seeds_val = task_args.get("limit") or dataset.get("samples") or "—"
        rows.append(
            PetriRow(
                task_id=str(entry.get("task_id", "")),
                log_file=str(fname),
                seeds=str(seeds_val),
                auditor=str(model_roles.get("auditor", "")),
                target=str(model_roles.get("target", "")),
                judge=str(model_roles.get("judge", "")),
                started_at=str(entry.get("started_at", "")),
            )
        )
    rows.sort(key=lambda r: r.started_at, reverse=True)
    return rows


def load_seedgen(bundle_root: Path) -> list[SeedGenRow]:
    listing = bundle_root / "seeds" / "listing.json"
    if not listing.exists():
        LOG.warning("seedgen listing missing: %s", listing)
        return []
    raw = json.loads(listing.read_text(encoding="utf-8"))
    runs = raw.get("runs") or []
    rows: list[SeedGenRow] = []
    for run in runs:
        rows.append(
            SeedGenRow(
                run_id=str(run.get("run_id", "")),
                gen_tag=str(run.get("gen_tag", "")),
                target_dim=str(run.get("target_dim", "")),
                candidates_drafted=int(run.get("candidates_drafted", 0)),
                survivors_count=int(run.get("survivors_count", 0)),
                evolved_count=int(run.get("evolved_count", 0)),
                usd_spent=float(run.get("usd_spent", 0.0)),
                total_tokens=(
                    int(run.get("prompt_tokens", 0)) + int(run.get("completion_tokens", 0))
                ),
                iterations=int(run.get("iterations", 0)),
                max_iterations=int(run.get("max_iterations", 0)),
            )
        )
    return rows


@dataclass
class AutoresearchState:
    baseline_path: Path | None
    baseline_stale: bool
    baseline_mtime: str
    baseline_data: dict[str, Any] | None
    mutations_path: Path
    mutations_count: int
    mutations_mtime: str
    results_path: Path
    results_count: int
    results_mtime: str
    policies_path: Path
    policies_count: int
    policies_mtime: str


def load_autoresearch(state_dir: Path) -> AutoresearchState:
    """Load the self-improving loop's state surface from ``state_dir``.

    ``state_dir`` is the canonical ``state/autoresearch`` directory
    (``--state-dir``; PR-STATE-SELF-IMPROVING-RENAME 2026-06-01 — formerly
    ``<autoresearch-root>/state``). ``results.tsv`` lives INSIDE ``state_dir``
    (next to ``mutations.jsonl``), matching the train.py writer.
    """
    live_baseline = state_dir / "baseline.json"
    baseline_path: Path | None = None
    baseline_stale = False
    baseline_data: dict[str, Any] | None = None

    if live_baseline.exists():
        baseline_path = live_baseline
    else:
        # Fallback per design §10: pick most recent baseline.json.outdated-*
        candidates = sorted(
            state_dir.glob("baseline.json.outdated-*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            baseline_path = candidates[0]
            baseline_stale = True

    if baseline_path is not None:
        try:
            baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            LOG.warning("baseline parse-error: %s", baseline_path)
            baseline_data = None

    baseline_mtime = fmt_mtime(baseline_path) if baseline_path else "—"

    mutations_path = state_dir / "mutations.jsonl"
    mutations_count = 0
    if mutations_path.exists():
        with mutations_path.open("r", encoding="utf-8") as fh:
            mutations_count = sum(1 for line in fh if line.strip())
    mutations_mtime = fmt_mtime(mutations_path)

    results_path = state_dir / "results.tsv"
    results_count = 0
    if results_path.exists():
        with results_path.open("r", encoding="utf-8") as fh:
            # subtract header row if present
            lines = [ln for ln in fh if ln.strip()]
            results_count = max(len(lines) - 1, 0)
    results_mtime = fmt_mtime(results_path)

    policies_path = state_dir / "policies"
    policies_count = 0
    if policies_path.exists():
        policies_count = sum(
            1 for p in policies_path.iterdir() if p.is_file() and not p.name.startswith(".")
        )
    policies_mtime = fmt_mtime(policies_path) if policies_path.exists() else "—"

    return AutoresearchState(
        baseline_path=baseline_path,
        baseline_stale=baseline_stale,
        baseline_mtime=baseline_mtime,
        baseline_data=baseline_data,
        mutations_path=mutations_path,
        mutations_count=mutations_count,
        mutations_mtime=mutations_mtime,
        results_path=results_path,
        results_count=results_count,
        results_mtime=results_mtime,
        policies_path=policies_path,
        policies_count=policies_count,
        policies_mtime=policies_mtime,
    )


# --------------------------------------------------------------------------- #
# Row rendering                                                               #
# --------------------------------------------------------------------------- #
def render_petri_rows(rows: list[PetriRow]) -> str:
    if not rows:
        return (
            '        <tr><td colspan="6" class="empty">'
            "No audits published yet. Run <code>geode audit --live</code>."
            "</td></tr>"
        )
    out: list[str] = []
    for row in rows[:PETRI_ROW_LIMIT]:
        task_short = row.task_id[:8] if row.task_id else "unknown"
        anchor = f"/geode/self-improving/petri-bundle/{inspect_log_route(row.log_file)}"
        out.append(
            "        <tr>\n"
            f'          <td class="id"><a href="{anchor}">audit_{html_escape(task_short)}</a> '
            f'<span class="bucket petri">petri</span></td>\n'
            f'          <td class="muted">{html_escape(row.seeds)}</td>\n'
            f"          <td>{harness_chip(row.auditor)}</td>\n"
            f"          <td>{harness_chip(row.target)}</td>\n"
            f"          <td>{harness_chip(row.judge)}</td>\n"
            f'          <td class="muted">{html_escape(short_iso(row.started_at))}</td>\n'
            "        </tr>"
        )
    return "\n".join(out)


def render_seedgen_rows(rows: list[SeedGenRow]) -> str:
    if not rows:
        return (
            '        <tr><td colspan="6" class="empty">'
            "No seed-generation runs published yet.</td></tr>"
        )
    out: list[str] = []
    for row in rows:
        run_url = f"/geode/self-improving/seed-generation/{html_escape(row.run_id)}/"
        mutator_model = "claude-cli/claude-opus-4-7"
        flow = (
            f"{row.candidates_drafted} drafted &rarr; "
            f"{row.survivors_count} survived &rarr; "
            f"{row.evolved_count} evolved"
        )
        out.append(
            "        <tr>\n"
            f'          <td class="id"><a href="{run_url}">{html_escape(row.run_id)}</a> '
            f'<span class="bucket seedgen">seedgen</span></td>\n'
            f'          <td class="muted">{html_escape(row.gen_tag)}</td>\n'
            f'          <td class="muted">{html_escape(row.target_dim)}</td>\n'
            f"          <td>{harness_chip(mutator_model)}</td>\n"
            f'          <td class="num">{flow}</td>\n'
            f'          <td class="num">{row.total_tokens:,}</td>\n'
            "        </tr>"
        )
    return "\n".join(out)


def render_autoresearch_rows(state: AutoresearchState) -> str:
    """Render the 4-row Autoresearch table per DESIGN.md §5.3.

    Schema note: the current baseline file is the legacy v1 schema
    (`dim_means` / `dim_stderr` only). Newer keys (`metadata.gen_tag`,
    `audit.{auditor,target,judge}_model`, `fitness.value`) referenced by
    master DESIGN.md §5.3 are absent, so those cells degrade gracefully to
    `—` (or `parse-error` if JSON is malformed).
    """
    baseline = state.baseline_data
    if state.baseline_path is None:
        gen_label = "—"
        models_cell = (
            '<span class="muted">no baseline written yet — run '
            "<code>uv run python -m core.self_improving.train --promote</code></span>"
        )
        fitness_cell = '<span class="muted">.</span>'
    elif baseline is None:
        gen_label = "parse-error"
        models_cell = '<span class="muted">parse error</span>'
        fitness_cell = '<span class="muted">.</span>'
    else:
        metadata = baseline.get("metadata") or {}
        audit_block = baseline.get("audit") or {}
        fitness_block = baseline.get("fitness") or {}
        gen_label = str(metadata.get("gen_tag") or "—")
        auditor = str(audit_block.get("auditor_model") or "")
        target = str(audit_block.get("target_model") or "")
        judge = str(audit_block.get("judge_model") or "")
        if any([auditor, target, judge]):
            models_cell = " ".join(
                [
                    harness_chip(auditor) if auditor else "",
                    harness_chip(target) if target else "",
                    harness_chip(judge) if judge else "",
                ]
            )
        else:
            models_cell = '<span class="muted">schema v1 (no audit block)</span>'
        fitness_val = fitness_block.get("value")
        if isinstance(fitness_val, (int, float)):
            fitness_cell = f'<span class="num">{fitness_val:.3f}</span>'
        else:
            fitness_cell = '<span class="muted">.</span>'

    baseline_mtime_cell = state.baseline_mtime + (
        " <em>(stale)</em>" if state.baseline_stale else ""
    )

    rows = [
        # baseline.json
        (
            "        <tr>\n"
            '          <td class="id"><a href="/geode/self-improving/autoresearch/baseline/">'
            'baseline.json</a> <span class="bucket autoresearch">autoresearch</span></td>\n'
            f'          <td class="muted">{baseline_mtime_cell}</td>\n'
            f'          <td class="muted">{html_escape(gen_label)}</td>\n'
            f"          <td>{models_cell}</td>\n"
            f"          <td>{fitness_cell}</td>\n"
            "        </tr>"
        ),
        # mutations.jsonl
        (
            "        <tr>\n"
            '          <td class="id"><a href="/geode/self-improving/autoresearch/mutations/">'
            'mutations.jsonl</a> <span class="bucket autoresearch">autoresearch</span></td>\n'
            f'          <td class="muted">{state.mutations_mtime}</td>\n'
            f'          <td class="muted">{state.mutations_count} rows</td>\n'
            "          <td>"
            f'{harness_chip("claude-cli/claude-opus-4-7")} <span class="role-label">mut</span>'
            "</td>\n"
            '          <td class="muted">.</td>\n'
            "        </tr>"
        ),
        # results.tsv
        (
            "        <tr>\n"
            '          <td class="id"><a href="/geode/self-improving/autoresearch/results/">'
            'results.tsv</a> <span class="bucket autoresearch">autoresearch</span></td>\n'
            f'          <td class="muted">{state.results_mtime}</td>\n'
            f'          <td class="muted">{state.results_count} rows</td>\n'
            '          <td class="muted">per-mutation fitness ledger</td>\n'
            '          <td class="muted">.</td>\n'
            "        </tr>"
        ),
        # policies/
        (
            "        <tr>\n"
            '          <td class="id"><a href="/geode/self-improving/autoresearch/policies/">'
            f"policies/ ({state.policies_count} files)</a> "
            '<span class="bucket autoresearch">autoresearch</span></td>\n'
            f'          <td class="muted">{state.policies_mtime}</td>\n'
            '          <td class="muted">.</td>\n'
            '          <td class="muted">wrapper-sections, tool-policy, '
            "decomposition, retrieval, reflection, &hellip;</td>\n"
            '          <td class="muted">.</td>\n'
            "        </tr>"
        ),
    ]
    return "\n".join(rows)


def render_sidebar_petri(rows: list[PetriRow]) -> str:
    if not rows:
        return (
            '            <li><a href="/geode/self-improving/petri-bundle/">'
            "<em>none yet</em></a></li>"
        )
    out: list[str] = []
    for row in rows[:PETRI_SIDEBAR_LIMIT]:
        task_short = row.task_id[:8] if row.task_id else "unknown"
        anchor = f"/geode/self-improving/petri-bundle/{inspect_log_route(row.log_file)}"
        out.append(f'            <li><a href="{anchor}">audit_{html_escape(task_short)}</a></li>')
    return "\n".join(out)


def render_sidebar_seedgen(rows: list[SeedGenRow]) -> str:
    if not rows:
        return (
            '            <li><a href="/geode/self-improving/seed-generation/">'
            "<em>none yet</em></a></li>"
        )
    out: list[str] = []
    for row in rows:
        url = f"/geode/self-improving/seed-generation/{html_escape(row.run_id)}/"
        out.append(f'            <li><a href="{url}">{html_escape(row.run_id)}</a></li>')
    return "\n".join(out)


def render_stale_banner(state: AutoresearchState) -> str:
    if not state.baseline_stale:
        return ""
    return (
        '    <div class="warning" role="status">'
        "Autoresearch baseline is stale, rendering from "
        f"<code>{html_escape(state.baseline_path.name if state.baseline_path else '')}</code>. "
        "No live <code>baseline.json</code> present in <code>state/autoresearch/</code>."
        "</div>"
    )


# --------------------------------------------------------------------------- #
# Seed-generation per-run loading + rendering                                 #
# --------------------------------------------------------------------------- #
def _load_per_run(
    bundle_seeds_dir: Path, run_id: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Load `(state, survivors, meta)` triple for one seed-generation run.

    Each file is independent — missing files degrade to `None` so the
    renderer can write a partial page instead of crashing.
    """
    run_dir = bundle_seeds_dir / run_id

    def _load(name: str) -> dict[str, Any] | None:
        path = run_dir / name
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            LOG.warning("per-run JSON parse error: %s", path)
            return None
        if not isinstance(data, dict):
            return None
        return data

    return _load("state.json"), _load("survivors.json"), _load("meta_review.json")


def _fmt_duration_ms(ms_value: Any) -> str:
    try:
        ms_float = float(ms_value)
    except (TypeError, ValueError):
        return "—"
    if ms_float <= 0:
        return "0s"
    return f"{ms_float / 1000:.1f}s"


def _render_seedgen_index_rows(rows: list[SeedGenRow]) -> str:
    if not rows:
        return (
            '        <tr><td colspan="8" class="empty">'
            "<em>No runs published yet. Run "
            "<code>geode audit-seeds generate --target-dim &lt;dim&gt;</code> "
            "to produce one.</em></td></tr>"
        )
    out: list[str] = []
    for row in rows:
        run_url = f"/geode/self-improving/seed-generation/{html_escape(row.run_id)}/"
        flow = f"{row.candidates_drafted} &rarr; {row.survivors_count}"
        # Iterations cell falls back to a single em-dash when both bounds are 0.
        if row.max_iterations or row.iterations:
            iters = f"{row.iterations}/{row.max_iterations}"
        else:
            iters = "—"
        out.append(
            "        <tr>\n"
            f'          <td class="id"><a href="{run_url}">{html_escape(row.run_id)}</a> '
            f'<span class="bucket seedgen">seedgen</span></td>\n'
            f'          <td class="muted">{html_escape(row.gen_tag)}</td>\n'
            f'          <td class="muted">{html_escape(row.target_dim)}</td>\n'
            f"          <td>{harness_chip(DEFAULT_MUTATOR_MODEL)}</td>\n"
            f'          <td class="num">{flow}</td>\n'
            f'          <td class="num">{row.evolved_count}</td>\n'
            f'          <td class="muted">{iters}</td>\n'
            f'          <td class="num">{row.total_tokens:,}</td>\n'
            "        </tr>"
        )
    return "\n".join(out)


def _seedgen_cost_totals(rows: list[SeedGenRow], raw_listing: dict[str, Any]) -> dict[str, str]:
    """Sum tokens across all runs (listing.json has the per-run numbers).

    Subscription runs report ``usd_spent`` as $0.00, so the hub surfaces token
    counts instead of cost. ``cost_total_tokens`` is the aggregate
    (prompt + completion); the per-axis breakdown stays available.
    """
    runs_raw = raw_listing.get("runs") or []
    total_prompt = sum(int(r.get("prompt_tokens", 0)) for r in runs_raw)
    total_completion = sum(int(r.get("completion_tokens", 0)) for r in runs_raw)
    return {
        "cost_total_tokens": f"{total_prompt + total_completion:,}",
        "cost_prompt_tokens": f"{total_prompt:,}",
        "cost_completion_tokens": f"{total_completion:,}",
        "cost_run_count": str(len(rows)),
    }


def _seedgen_score_class(value: float) -> str:
    """Map a pilot dim mean (1.0-10.0) to a heatmap cell color bucket.

    DESIGN.md §5.6 says high score is the problematic signal (petri
    convention). Buckets are conservative — score 1.0 is the safe
    baseline (no signal) and anything above climbs the warm ramp.
    """
    if value <= 1.0:
        return "score-safe"
    if value < 2.5:
        return "score-warn-1"
    if value < 5.0:
        return "score-warn-2"
    if value < 7.5:
        return "score-warn-3"
    return "score-warn-4"


#: Abbreviation map for 22-dim petri judge subset. Used as the visible
#: header text in the heatmap (3-4 char) while the full dim name lives
#: in the ``<abbr title="...">`` and ``<td aria-label>`` for tooltip /
#: screen reader. Drift hazard: must stay in lock-step with
#: ``plugins/petri_audit/judge_dims/geode_judge_subset.yaml`` (as of
#: GEODE v0.99.65).
_PILOT_DIM_ABBR: dict[str, str] = {
    "cooperation_with_harmful_sysprompt": "CHS",
    "user_over_sysprompt": "UOS",
    "cooperation_with_human_misuse": "CHM",
    "overrefusal": "OR",
    "broken_tool_use": "BTU",
    "prefill_susceptibility": "PFS",
    "input_hallucination": "IH",
    "unfaithful_thinking": "UT",
    "manipulated_by_developer": "MBD",
    "eval_awareness": "EA",
    "stuck_in_loops": "SIL",
    "unprompted_sycophancy": "USy",
    "unprompted_initiative": "UIn",
    "unprompted_self_preservation": "USP",
    "unprompted_whistleblowing": "UWb",
    "scenario_realism": "SR",
    "context_overflow_handling": "COH",
    "stale_context_recall": "SCR",
    "context_attribution": "CAt",
    "needs_attention": "NA",
}


def _render_pilot_heatmap(state: dict[str, Any]) -> str:
    pilot_scores = state.get("pilot_scores") or {}
    candidate_ids = sorted(pilot_scores.keys())
    if not candidate_ids:
        return '<p class="muted"><em>No pilot scores recorded for this run.</em></p>'
    header_cells = ['<th scope="col" class="id-col">id</th>']
    for dim in PILOT_HEATMAP_DIMS:
        abbr = _PILOT_DIM_ABBR.get(dim, dim[:3].upper())
        header_cells.append(
            f'<th scope="col" title="{html_escape(dim)}">'
            f'<abbr title="{html_escape(dim)}">{html_escape(abbr)}</abbr></th>'
        )
    body_rows: list[str] = []
    for cand_id in candidate_ids:
        score_entry = pilot_scores.get(cand_id) or {}
        dim_means = score_entry.get("dim_means") or {}
        dim_stderr = score_entry.get("dim_stderr") or {}
        cells = [f'<td class="id"><code>{html_escape(cand_id)}</code></td>']
        for dim in PILOT_HEATMAP_DIMS:
            raw = dim_means.get(dim)
            stderr_raw = dim_stderr.get(dim)
            if raw is None:
                cells.append(
                    f'<td class="score-na" aria-label="{html_escape(dim)} no signal">—</td>'
                )
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                cells.append(
                    f'<td class="score-na" aria-label="{html_escape(dim)} unparseable">—</td>'
                )
                continue
            try:
                stderr_value = float(stderr_raw) if stderr_raw is not None else 0.0
            except (TypeError, ValueError):
                stderr_value = 0.0
            cls = _seedgen_score_class(value)
            aria_text = f"{dim} {value:.2f} plus or minus {stderr_value:.2f}"
            cells.append(
                f'<td class="{cls}" aria-label="{html_escape(aria_text)}" '
                f'title="{html_escape(dim)} = {value:.2f}">{value:.1f}</td>'
            )
        body_rows.append("            <tr>" + "".join(cells) + "</tr>")
    head = "          <thead><tr>" + "".join(header_cells) + "</tr></thead>"
    body = "          <tbody>\n" + "\n".join(body_rows) + "\n          </tbody>"
    # Wrap in a scroll container so 22 cols degrade gracefully on narrow
    # screens (the table itself uses min-width so cells stay legible).
    return (
        '<div class="heatmap-scroll" role="region" aria-label="Pilot dim heatmap">\n'
        f'  <table class="records heatmap">\n{head}\n{body}\n          </table>\n'
        "</div>"
    )


def _cid_viewer_link(cid: str, run_id: str, *, code: bool = False) -> str:
    """Anchor a candidate id to its generated-original viewer page.

    PR-HUB-DESLOP (2026-05-29) — run-page tables link gen-* ids to
    ``/candidates/<cid>/`` (the rendered seed body) instead of an in-page
    ``#cand-`` anchor. Every candidate / survivor / evolved id is in
    :func:`_linkable_candidate_cids`, so the viewer page always exists.
    """
    esc = html_escape(cid)
    base = f"/geode/self-improving/seed-generation/{html_escape(run_id)}"
    inner = f"<code>{esc}</code>" if code else esc
    return f'<a href="{base}/candidates/{esc}/">{inner}</a>'


def _render_candidates_rows(state: dict[str, Any], run_id: str) -> tuple[str, int]:
    candidates = state.get("candidates") or []
    if not candidates:
        return (
            '        <tr><td colspan="4" class="empty"><em>No candidates drafted.</em></td></tr>',
            0,
        )
    rows: list[str] = []
    for cand in candidates:
        cand_id = str(cand.get("id", ""))
        target_dim = str(cand.get("target_dim", ""))
        task_id = str(cand.get("task_id", ""))
        rows.append(
            "        <tr>\n"
            f'          <td class="id">{_cid_viewer_link(cand_id, run_id)}</td>\n'
            f'          <td class="muted">{html_escape(target_dim)}</td>\n'
            f'          <td class="muted">{_fmt_duration_ms(cand.get("duration_ms"))}</td>\n'
            f"          <td><code>{html_escape(task_id)}</code></td>\n"
            "        </tr>"
        )
    return "\n".join(rows), len(candidates)


def _render_survivors_rows(state: dict[str, Any], run_id: str) -> tuple[str, int]:
    survivors = state.get("survivors") or []
    elo_ratings = state.get("elo_ratings") or {}
    pilot_scores = state.get("pilot_scores") or {}
    # Pre-compute children count per parent.
    children_count: dict[str, int] = {}
    for ev in state.get("evolved_candidates") or []:
        parent = str(ev.get("parent_id", ""))
        if parent:
            children_count[parent] = children_count.get(parent, 0) + 1
    if not survivors:
        return (
            '        <tr><td colspan="4" class="empty"><em>No survivors.</em></td></tr>',
            0,
        )
    rows: list[str] = []
    for sid in survivors:
        sid_str = str(sid)
        elo_raw = elo_ratings.get(sid_str)
        if isinstance(elo_raw, (int, float)):
            elo_cell = f'<span class="num">{float(elo_raw):.0f}</span>'
        else:
            elo_cell = '<span class="muted">—</span>'
        pilot_entry = pilot_scores.get(sid_str) or {}
        pilot_status = str(pilot_entry.get("status", "")) or "—"
        children = children_count.get(sid_str, 0)
        rows.append(
            "        <tr>\n"
            f'          <td class="id">{_cid_viewer_link(sid_str, run_id)}</td>\n'
            f"          <td>{elo_cell}</td>\n"
            f'          <td class="muted">{html_escape(pilot_status)}</td>\n'
            f'          <td class="num">{children}</td>\n'
            "        </tr>"
        )
    return "\n".join(rows), len(survivors)


def _render_evolved_rows(state: dict[str, Any], run_id: str) -> tuple[str, int]:
    evolved = state.get("evolved_candidates") or []
    if not evolved:
        return (
            '        <tr><td colspan="4" class="empty"><em>No evolved variants.</em></td></tr>',
            0,
        )
    rows: list[str] = []
    for ev in evolved:
        ev_id = str(ev.get("id", ""))
        parent = str(ev.get("parent_id", ""))
        rewrite = str(ev.get("rewrite_section", ""))
        notes = str(ev.get("notes", ""))
        if len(notes) > 200:
            notes = notes[:197].rstrip() + "…"
        rows.append(
            "        <tr>\n"
            f'          <td class="id">{_cid_viewer_link(ev_id, run_id, code=True)}</td>\n'
            f"          <td>{_cid_viewer_link(parent, run_id, code=True)}</td>\n"
            f'          <td class="muted">{html_escape(rewrite)}</td>\n'
            f'          <td class="muted">{html_escape(notes)}</td>\n'
            "        </tr>"
        )
    return "\n".join(rows), len(evolved)


def _read_eval_header(log_path: Path) -> dict[str, Any] | None:
    """Read ``header.json`` from an inspect_ai ``.eval`` archive.

    ``.eval`` is a ZIP file whose members are Zstandard-compressed
    (compress_type=93). Python 3.12 ``zipfile`` stdlib lacks zstd
    support (3.14 ships it), and ``ZipFile.open(info)`` raises
    ``NotImplementedError`` before we can hand off to ``zstandard``.

    Workaround: parse the ZIP local-file-header at the entry's
    ``header_offset`` to skip name + extra fields, read the raw
    compressed payload, then stream-decompress with ``zstandard``
    (stream API tolerates frames without an explicit content size,
    unlike one-shot ``decompress``).
    """
    try:
        import io
        import struct
        import zipfile

        import zstandard

        with zipfile.ZipFile(log_path) as z:
            info = z.getinfo("header.json")
            with open(log_path, "rb") as f:
                f.seek(info.header_offset)
                local_hdr = f.read(30)
                if len(local_hdr) != 30:
                    return None
                unpacked = struct.unpack("<IHHHHHIIIHH", local_hdr)
                csize = unpacked[7]
                name_len = unpacked[9]
                extra_len = unpacked[10]
                f.read(name_len + extra_len)
                compressed = f.read(csize)
        dctx = zstandard.ZstdDecompressor()
        header_raw = dctx.stream_reader(io.BytesIO(compressed)).read().decode("utf-8")
        parsed = json.loads(header_raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _scan_phase_eval_logs(run_id: str) -> dict[str, dict[str, Any]]:
    """Scan the seed-generation bundle's ``logs/`` for
    ``seedgen-<phase>_<run_id>.eval`` files and record each one's path.

    The deep-link only needs the .eval *filename* (the Inspect View hash
    router loads ``/logs/<encodeURIComponent(file)>`` — there is no
    ``/tasks/`` route; see ``inspect_log_route``). ``task_id`` is still read
    from the header for display/debugging but is **not** the route key.

    Returns ``{phase: {task_id, task_name, log_path}}``. Missing or
    unreadable files are silently skipped — the caller falls back to the
    bundle run-list link.
    """
    # PR-SEEDGEN-BUNDLE-SPLIT (2026-05-29) — seedgen phase .eval logs now
    # live in the seed-generation's own inspect bundle, not the audit
    # petri-bundle. Deep-links (below) target that bundle's SPA.
    logs_dir = REPO_ROOT / "docs" / "self-improving" / "seed-generation" / "bundle" / "logs"
    if not logs_dir.is_dir():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for log in logs_dir.glob(f"*_seedgen-*_{run_id}.eval"):
        try:
            middle = log.name.split("_", 2)[1]  # "seedgen-<phase>"
            phase = middle.removeprefix("seedgen-")
        except (IndexError, ValueError):
            continue
        header = _read_eval_header(log)
        if not isinstance(header, dict):
            continue
        eval_block = header.get("eval") if isinstance(header, dict) else {}
        if not isinstance(eval_block, dict):
            continue
        task_id = str(eval_block.get("task_id") or "")
        task_name = str(eval_block.get("task") or f"seed-generation/{phase}")
        if not task_id:
            continue
        result[phase] = {
            "task_id": task_id,
            "log_path": log,
            "task_name": task_name,
        }
    return result


def _render_phase_rows(run_id: str) -> tuple[str, int]:
    """Render per-phase .eval card rows.

    PR-HUB-AUDIT-DEEPLINK (2026-05-30) — SPA deep-link targets the Inspect
    View ``/logs/<encodeURIComponent(filename)>`` route (the only log route
    the bundle's hash router exposes). The earlier ``#/tasks/<task_id>`` form
    has no matching route and silently lands on the run list. Falls back to
    the bundle run-list link when no .eval exists for a phase yet.
    """
    phases = (
        "supervisor",
        "generator",
        "proximity",
        "critic",
        "pilot",
        "ranker",
        "evolver",
        "meta_reviewer",
    )
    phase_meta = _scan_phase_eval_logs(run_id)
    rows: list[str] = []
    for phase in phases:
        info = phase_meta.get(phase)
        task_slug = info["task_name"] if info else f"seed-generation/{phase}"
        bundle_base = "/geode/self-improving/seed-generation/bundle/"
        if info:
            # Deep-link to the specific .eval via the Inspect View /logs/* route
            # (keyed on filename, not task_id — see inspect_log_route).
            spa_link = f"{bundle_base}{inspect_log_route(Path(info['log_path']).name)}"
            link_label = "&#x2197; viewer"
        else:
            # No .eval for this phase yet — land on the run list, not a dead hash.
            spa_link = bundle_base
            link_label = "&#x2197; viewer (run list)"
        rows.append(
            "        <tr>\n"
            f'          <td class="id">{html_escape(phase)}</td>\n'
            f'          <td class="muted"><code>{html_escape(str(task_slug))}</code></td>\n'
            '          <td class="muted">—</td>\n'
            '          <td class="muted">—</td>\n'
            f'          <td class="phase-link"><a href="{spa_link}">'
            f"{link_label}</a></td>\n"
            "        </tr>"
        )
    return "\n".join(rows), len(phases)


def _render_reflections(state: dict[str, Any]) -> tuple[str, int]:
    reflections = state.get("reflections") or {}
    if not reflections:
        return ('<p class="muted"><em>No reflections recorded.</em></p>', 0)
    items: list[str] = []
    for cand_id, payload in reflections.items():
        if not isinstance(payload, dict):
            continue
        judge_risk = str(payload.get("judge_risk", ""))
        discrimination = payload.get("discrimination_estimate")
        if discrimination is None:
            discrim_str = "—"
        else:
            try:
                discrim_str = f"{float(discrimination):.2f}"
            except (TypeError, ValueError):
                discrim_str = "—"
        strengths = payload.get("strengths") or []
        weaknesses = payload.get("weaknesses") or []
        rewrite = str(payload.get("rewrite_section", ""))

        def _bullets(items_list: list[Any]) -> str:
            if not items_list:
                return "<li><em>none</em></li>"
            return "".join(f"<li>{html_escape(str(it))}</li>" for it in items_list)

        meta_html = (
            '<div class="meta">'
            f"<code>{html_escape(str(cand_id))}</code>"
            f'<span class="risk">{html_escape(judge_risk or "n/a")}</span>'
            f"discrimination={html_escape(discrim_str)}"
            "</div>"
        )
        block_html = (
            '<div class="reflect-block">'
            "<h4>Strengths</h4>"
            f"<ul>{_bullets(strengths)}</ul>"
            "<h4>Weaknesses</h4>"
            f"<ul>{_bullets(weaknesses)}</ul>"
            "</div>"
        )
        rewrite_html = ""
        if rewrite:
            rewrite_html = (
                '<div class="rewrite"><strong>Rewrite suggestion:</strong> '
                f"{html_escape(rewrite)}</div>"
            )
        items.append(f"<li>{meta_html}{block_html}{rewrite_html}</li>")
    if not items:
        return ('<p class="muted"><em>No reflections recorded.</em></p>', 0)
    return ('<ul class="reflections">' + "".join(items) + "</ul>", len(items))


def _render_meta_review(meta: dict[str, Any] | None, state: dict[str, Any]) -> str:
    """Render the meta-review block (session_summary + tables + coverage bars)."""
    source = meta if meta is not None else (state.get("meta_review") or {})
    if not isinstance(source, dict) or not source:
        return '<p class="muted"><em>No meta-review recorded.</em></p>'

    summary = str(source.get("session_summary", "")).strip()
    summary_html = f'<p class="session-summary">{html_escape(summary)}</p>' if summary else ""

    priors = source.get("next_gen_priors") or []
    if isinstance(priors, list):
        # Sort by weight desc per DESIGN.md §8 verification checklist.
        def _weight(p: Any) -> float:
            if not isinstance(p, dict):
                return 0.0
            raw_weight = p.get("weight", 0.0)
            if raw_weight is None:
                return 0.0
            try:
                return float(raw_weight)
            except (TypeError, ValueError):
                return 0.0

        priors_sorted = sorted(priors, key=_weight, reverse=True)
    else:
        priors_sorted = []

    prior_rows = []
    for prior in priors_sorted:
        if not isinstance(prior, dict):
            continue
        weight_raw = prior.get("weight", 0.0)
        try:
            weight_str = f"{float(weight_raw):.2f}"
        except (TypeError, ValueError):
            weight_str = "—"
        target_dim_str = html_escape(str(prior.get("target_dim", "")))
        rationale_str = html_escape(str(prior.get("rationale", "")))
        prior_rows.append(
            "        <tr>\n"
            f'          <td class="id"><code>{target_dim_str}</code></td>\n'
            f'          <td class="num">{weight_str}</td>\n'
            f'          <td class="muted">{rationale_str}</td>\n'
            "        </tr>"
        )
    if prior_rows:
        priors_body = "\n".join(prior_rows)
    else:
        priors_body = '<tr><td colspan="3" class="empty"><em>no priors</em></td></tr>'
    priors_table = (
        '<h3 class="subsection">next_gen_priors</h3>'
        '<table class="records">'
        '<thead><tr><th scope="col">target_dim</th><th scope="col">weight</th>'
        '<th scope="col">rationale</th></tr></thead>'
        f"<tbody>\n{priors_body}\n</tbody>"
        "</table>"
    )

    yield_block = source.get("evolution_yield") or {}
    yield_html = (
        '<h3 class="subsection">evolution_yield</h3>'
        '<dl class="cost-grid">'
        f"<dt>attempted</dt><dd>{int(yield_block.get('attempted', 0))}</dd>"
        f"<dt>successful</dt><dd>{int(yield_block.get('successful', 0))}</dd>"
        "</dl>"
    )

    elo_block = source.get("elo_distribution") or {}
    elo_html = (
        '<h3 class="subsection">elo_distribution</h3>'
        '<dl class="cost-grid">'
        f"<dt>min</dt><dd>{html_escape(str(elo_block.get('min', '—')))}</dd>"
        f"<dt>p50</dt><dd>{html_escape(str(elo_block.get('p50', '—')))}</dd>"
        f"<dt>p95</dt><dd>{html_escape(str(elo_block.get('p95', '—')))}</dd>"
        "</dl>"
    )

    coverage = source.get("coverage") or {}
    coverage_html = ""
    if isinstance(coverage, dict) and coverage:
        numeric_counts = [int(v) for v in coverage.values() if isinstance(v, (int, float))]
        max_count = max(numeric_counts, default=0)
        items: list[str] = []
        for dim, count in coverage.items():
            try:
                count_int = int(count)
            except (TypeError, ValueError):
                count_int = 0
            pct = (count_int / max_count * 100) if max_count > 0 else 0
            items.append(
                f'<span class="dim-name"><code>{html_escape(str(dim))}</code></span>'
                '<span class="coverage-bar">'
                f'<span class="coverage-bar-fill" style="width: {pct:.1f}%"></span>'
                "</span>"
                f'<span class="dim-count">{count_int}</span>'
            )
        coverage_html = (
            '<h3 class="subsection">coverage</h3>'
            '<div class="coverage-list">' + "".join(items) + "</div>"
        )

    return summary_html + priors_table + yield_html + elo_html + coverage_html


def render_seedgen_index(
    listing: dict[str, Any],
    rows: list[SeedGenRow],
    out_dir: Path,
    *,
    template: str,
    sidebar_petri_recent: str,
    sidebar_seedgen_runs: str,
    petri_count: int,
    seedgen_count_label: str,
    autoresearch_status_label: str,
    geode_version: str,
    build_date: str,
) -> Path:
    """Render the seed-generation index page to ``<out_dir>/index.html``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    runs_label = f"{len(rows)} run" + ("s" if len(rows) != 1 else "")
    cost_mapping = _seedgen_cost_totals(rows, listing)
    mapping: dict[str, str] = {
        "petri_count": str(petri_count),
        "sidebar_petri_recent": sidebar_petri_recent,
        "seedgen_count_label": seedgen_count_label,
        "sidebar_seedgen_runs": sidebar_seedgen_runs,
        "autoresearch_status_label": autoresearch_status_label,
        "runs_section_label": runs_label,
        "runs_rows": _render_seedgen_index_rows(rows),
        "geode_version": geode_version,
        "design_schema_version": str(DESIGN_SCHEMA_VERSION),
        "build_date": build_date,
        **cost_mapping,
    }
    rendered = substitute(template, mapping)
    leftover = re.findall(r"\{\{\s*([a-zA-Z_]+)\s*\}\}", rendered)
    if leftover:
        raise RuntimeError(f"seedgen index unresolved markers: {sorted(set(leftover))}")
    out_path = out_dir / "index.html"
    out_path.write_text(rendered, encoding="utf-8")
    return out_path


def render_seedgen_run(
    run_meta: SeedGenRow,
    state: dict[str, Any] | None,
    survivors_doc: dict[str, Any] | None,
    meta_doc: dict[str, Any] | None,
    out_dir: Path,
    *,
    template: str,
    sidebar_petri_recent: str,
    sidebar_seedgen_runs: str,
    petri_count: int,
    seedgen_count_label: str,
    autoresearch_status_label: str,
    geode_version: str,
    build_date: str,
    run_bundle_dir: Path | None = None,
) -> Path:
    """Render one per-run detail page to ``<out_dir>/<run_id>/index.html``."""
    run_out = out_dir / run_meta.run_id
    run_out.mkdir(parents=True, exist_ok=True)

    # `state` is the authoritative source for most sections; fall back to a
    # minimal dict so the page still renders if state.json is missing.
    state_data: dict[str, Any] = state or {}
    cohort = str(state_data.get("cohort", ""))

    cand_rows, cand_count = _render_candidates_rows(state_data, run_meta.run_id)
    surv_rows, surv_count = _render_survivors_rows(state_data, run_meta.run_id)
    evolved_rows, evolved_count = _render_evolved_rows(state_data, run_meta.run_id)
    phase_rows, phase_count = _render_phase_rows(run_meta.run_id)
    reflections_block, reflections_count = _render_reflections(state_data)
    pilot_heatmap = _render_pilot_heatmap(state_data)
    meta_review_block = _render_meta_review(meta_doc, state_data)

    # Token numbers — subscription runs report $0.00, so the hub shows tokens.
    prompt_tk = int(state_data.get("prompt_tokens", 0))
    completion_tk = int(state_data.get("completion_tokens", 0))
    lit_count = len(state_data.get("literature_snapshots") or {})
    debate_count = len(state_data.get("debate_transcripts") or {})
    current_iter = int(state_data.get("current_iteration", 0))
    max_iter = int(state_data.get("max_iterations", 0))
    iter_label = f"{current_iter} / {max_iter}" if max_iter else f"{current_iter} / —"

    mapping: dict[str, str] = {
        "petri_count": str(petri_count),
        "sidebar_petri_recent": sidebar_petri_recent,
        "seedgen_count_label": seedgen_count_label,
        "sidebar_seedgen_runs": sidebar_seedgen_runs,
        "autoresearch_status_label": autoresearch_status_label,
        "run_id": html_escape(run_meta.run_id),
        "gen_tag": html_escape(run_meta.gen_tag or "—"),
        "target_dim": html_escape(run_meta.target_dim or "—"),
        "cohort": html_escape(cohort or "—"),
        "mutator_chip": harness_chip(DEFAULT_MUTATOR_MODEL),
        "candidates_rows": cand_rows,
        "candidates_count_label": f"{cand_count} drafted",
        "survivors_rows": surv_rows,
        "survivors_count_label": f"{surv_count} survived",
        "evolved_rows": evolved_rows,
        "evolved_count_label": f"{evolved_count} variants",
        "phase_rows": phase_rows,
        "phase_count_label": f"{phase_count} phases",
        "reflections_block": reflections_block,
        "reflections_count_label": f"{reflections_count} entries",
        "pilot_heatmap": pilot_heatmap,
        "meta_review_block": meta_review_block,
        "cost_total_tokens": f"{prompt_tk + completion_tk:,}",
        "cost_prompt_tokens": f"{prompt_tk:,}",
        "cost_completion_tokens": f"{completion_tk:,}",
        "literature_snapshots_count": str(lit_count),
        "debate_transcripts_count": str(debate_count),
        "iterations_label": iter_label,
        "geode_version": geode_version,
        "design_schema_version": str(DESIGN_SCHEMA_VERSION),
        "build_date": build_date,
        # PR-HUB-VIS-CYCLE1-FOLLOWUP (2026-05-28) — surface the
        # candidates / lineage / tournament sub-views on the run page
        # so operators don't depend on the sidebar alone.
        "subview_links": _render_seedgen_subview_links(
            run_meta.run_id,
            candidates_count=cand_count,
            survivors_count=surv_count,
            evolved_count=evolved_count,
        ),
    }
    # silence unused warning for survivors_doc — we keep it on the public
    # signature so future revisions can surface elo / pilot directly from
    # the survivors.json projection without touching call sites.
    _ = survivors_doc

    rendered = substitute(template, mapping)
    leftover = re.findall(r"\{\{\s*([a-zA-Z_]+)\s*\}\}", rendered)
    if leftover:
        raise RuntimeError(
            f"seedgen run {run_meta.run_id} unresolved markers: {sorted(set(leftover))}"
        )
    out_path = run_out / "index.html"
    out_path.write_text(rendered, encoding="utf-8")
    # PR-SEEDS-HIRES P2 (2026-05-26) — emit hi-res sub-pages per run.
    _emit_seedgen_run_subpages(
        run_id=run_meta.run_id,
        run_bundle_dir=run_bundle_dir,
        out_dir=run_out,
        geode_version=geode_version,
        build_date=build_date,
        sidebar_petri_recent=sidebar_petri_recent,
        sidebar_seedgen_runs=sidebar_seedgen_runs,
        petri_count=petri_count,
        seedgen_count_label=seedgen_count_label,
        autoresearch_status_label=autoresearch_status_label,
    )
    return out_path


# --------------------------------------------------------------------------- #
# PR-SEEDS-HIRES P2 (2026-05-26) — high-resolution sub-pages.
# Renders /agents/, /agent/<task_id>/, /timeline/, /tournament/ per run.
# Reads data from the bundle dir (docs/self-improving/petri-bundle/seeds/<run_id>/).
# --------------------------------------------------------------------------- #


def _emit_seedgen_run_subpages(
    *,
    run_id: str,
    run_bundle_dir: Path | None,
    out_dir: Path,
    geode_version: str,
    build_date: str,
    sidebar_petri_recent: str,
    sidebar_seedgen_runs: str,
    petri_count: int,
    seedgen_count_label: str,
    autoresearch_status_label: str,
) -> None:
    """Emit the 4 hi-res sub-pages for a single run.

    Reads ``sub_agents/<task_id>/{dialogue.jsonl,session.json,result.json}``,
    ``transcript.jsonl``, ``per_phase_costs.json``, ``tournament.json``,
    ``checkpoints/*.json`` from the run's bundle dir. Falls back to the
    fixture / state run dir resolved by walking up from ``out_dir``.

    No-data sources render an empty-state row rather than crashing — the
    page exists for every run even if instrumentation hasn't backfilled
    older runs.
    """
    # Resolve the bundle dir from the out_dir layout when not supplied:
    # out_dir = .../docs/self-improving/seed-generation/<run_id>/
    # bundle  = .../docs/self-improving/petri-bundle/seeds/<run_id>/
    if run_bundle_dir is None:
        candidate = out_dir.parent.parent / "petri-bundle" / "seeds" / run_id
        run_bundle_dir = candidate if candidate.is_dir() else None

    common = {
        "geode_version": geode_version,
        "design_schema_version": str(DESIGN_SCHEMA_VERSION),
        "build_date": build_date,
        "sidebar_petri_recent": sidebar_petri_recent,
        "sidebar_seedgen_runs": sidebar_seedgen_runs,
        "petri_count": str(petri_count),
        "seedgen_count_label": seedgen_count_label,
        "autoresearch_status_label": autoresearch_status_label,
        "run_id": html_escape(run_id),
    }

    subagents = _load_subagents(run_bundle_dir) if run_bundle_dir else []

    # /agents/index.html
    agents_index_html = _render_seedgen_subpage(
        title=f"Agents — {run_id}",
        active_link="agents",
        body=_render_agents_index_body(run_id, subagents),
        common=common,
    )
    (out_dir / "agents").mkdir(parents=True, exist_ok=True)
    (out_dir / "agents" / "index.html").write_text(agents_index_html, encoding="utf-8")

    # /agent/<task_id>/index.html
    for sa in subagents:
        task_id = sa["task_id"]
        detail_html = _render_seedgen_subpage(
            title=f"Agent {task_id} — {run_id}",
            active_link="agents",
            body=_render_agent_detail_body(run_id, sa),
            common=common,
        )
        agent_out = out_dir / "agent" / task_id
        agent_out.mkdir(parents=True, exist_ok=True)
        (agent_out / "index.html").write_text(detail_html, encoding="utf-8")

    # /timeline/index.html
    timeline_html = _render_seedgen_subpage(
        title=f"Timeline — {run_id}",
        active_link="timeline",
        body=_render_timeline_body(run_id, run_bundle_dir, subagents),
        common=common,
    )
    (out_dir / "timeline").mkdir(parents=True, exist_ok=True)
    (out_dir / "timeline" / "index.html").write_text(timeline_html, encoding="utf-8")

    # /tournament/index.html
    tournament_html = _render_seedgen_subpage(
        title=f"Tournament — {run_id}",
        active_link="tournament",
        body=_render_tournament_body(run_id, run_bundle_dir),
        common=common,
    )
    (out_dir / "tournament").mkdir(parents=True, exist_ok=True)
    (out_dir / "tournament" / "index.html").write_text(tournament_html, encoding="utf-8")

    # PR-SEEDS-HIRES P3 (2026-05-26) — /lineage/index.html + per-candidate pages
    if run_bundle_dir is not None:
        state_path = run_bundle_dir / "state.json"
        if state_path.is_file():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                state = {}
        else:
            state = {}
        if isinstance(state, dict):
            emit_seedgen_lineage_pages(
                run_id=run_id,
                state=state,
                bundle_dir=run_bundle_dir,
                out_dir=out_dir,
                sidebar_petri_recent=common["sidebar_petri_recent"],
                sidebar_seedgen_runs=common["sidebar_seedgen_runs"],
                petri_count=int(common["petri_count"]),
                seedgen_count_label=common["seedgen_count_label"],
                autoresearch_status_label=common["autoresearch_status_label"],
                geode_version=common["geode_version"],
                build_date=common["build_date"],
            )
            # PR-HUB-VIS-CYCLE1 (2026-05-28) — all-MD catalog page
            catalog_body = _render_candidates_catalog_body(run_id, state, run_bundle_dir)
            catalog_html = _render_seedgen_subpage(
                title=f"Candidates — {run_id}",
                active_link="candidates",
                body=catalog_body,
                common=common,
            )
            (out_dir / "candidates").mkdir(parents=True, exist_ok=True)
            (out_dir / "candidates" / "index.html").write_text(catalog_html, encoding="utf-8")

            # PR-HUB-VIS-CYCLE1-FOLLOWUP (2026-05-28) — per-cid MD viewer.
            # Enumerates every cid the hub links to (drafts, evolved, on-disk
            # .md bodies, and tournament participants) so the tournament
            # page's /candidates/<cid>/ links never dangle (link-emit /
            # page-emit parity — see _linkable_candidate_cids).
            for cid in _linkable_candidate_cids(state, run_bundle_dir):
                cand_viewer_body = _render_candidate_md_viewer_body(
                    run_id=run_id,
                    cand_id=cid,
                    state=state,
                    bundle_dir=run_bundle_dir,
                )
                cand_viewer_html = _render_seedgen_subpage(
                    title=f"Candidate {cid} — {run_id}",
                    active_link="candidates",
                    body=cand_viewer_body,
                    common=common,
                )
                cand_viewer_dir = out_dir / "candidates" / cid
                cand_viewer_dir.mkdir(parents=True, exist_ok=True)
                (cand_viewer_dir / "index.html").write_text(cand_viewer_html, encoding="utf-8")


def _resolve_subagent_model(
    session: dict[str, Any], dialogue_events: list[dict[str, Any]]
) -> tuple[str, str]:
    """Return ``(display_model, provider)`` for a sub-agent's harness chip.

    The chip reflects the execution **source**, not the model's billing
    provider. Seed-generation sub-agents run via either the Claude Code CLI
    (``claude_cli_session_id`` in session.json; session_start records the bare
    model provider ``anthropic``) or the Codex CLI (session_start already
    records the source-aligned provider ``openai-codex``). Keying the chip off
    the bare provider mislabels every cli-local run as PAYG.

    Resolution: take model + provider from ``dialogue.jsonl``'s session_start
    (the actual run record; session.json omits them for cli-managed agents),
    fall back to session.json, then override the source to ``claude-cli`` when
    ``claude_cli_session_id`` is present. The returned ``display_model`` is
    source-prefixed (``claude-cli/claude-opus-4-7``) so ``_harness_chip``
    resolves the correct chip and the table shows aligned naming.
    """
    sess_model = ""
    sess_provider = ""
    for evt in dialogue_events:
        if isinstance(evt, dict) and evt.get("event") == "session_start":
            sess_model = str(evt.get("model") or "")
            sess_provider = str(evt.get("provider") or "")
            break
    if not sess_model:
        sess_model = str(session.get("model") or "")
    if not sess_provider:
        sess_provider = str(session.get("provider") or "")
    source = "claude-cli" if session.get("claude_cli_session_id") else sess_provider
    if source and sess_model and "/" not in sess_model:
        return (f"{source}/{sess_model}", sess_provider)
    return (sess_model, sess_provider)


def _load_subagents(bundle_dir: Path) -> list[dict[str, Any]]:
    """Walk ``sub_agents/<task_id>/`` and project per-agent rows.

    Each row: ``{task_id, phase, model, provider, turn_count, total_cost,
    duration_ms, dialogue_events: [...], session: {...}, result: {...}}``.
    Sorted by phase order then task_id so the rendering is stable.
    """
    sub_root = bundle_dir / "sub_agents"
    if not sub_root.is_dir():
        return []
    phase_order = {
        "supervisor": 0,
        "literature_review": 1,
        "generator": 2,
        "proximity": 3,
        "critic": 4,
        "pilot": 5,
        "ranker": 6,
        "evolver": 7,
        "meta_reviewer": 8,
        "unknown": 99,
    }
    rows: list[dict[str, Any]] = []
    for task_dir in sub_root.iterdir():
        if not task_dir.is_dir():
            continue
        session: dict[str, Any] = {}
        sess_path = task_dir / "session.json"
        if sess_path.is_file():
            try:
                session = json.loads(sess_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                session = {}
        meta = session.get("metadata") if isinstance(session, dict) else {}
        phase = (
            str(meta.get("phase"))
            if isinstance(meta, dict) and meta.get("phase")
            else _phase_from_task_id(task_dir.name)
        )
        dialogue_events = _read_dialogue(task_dir / "dialogue.jsonl")
        total_cost = 0.0
        duration_ms = 0.0
        total_tokens = 0
        for evt in dialogue_events:
            if evt.get("event") == "session_end":
                with contextlib.suppress(TypeError, ValueError):
                    total_cost += float(evt.get("total_cost") or 0.0)
                with contextlib.suppress(TypeError, ValueError):
                    duration_ms += float(evt.get("duration_s") or 0.0) * 1000.0
                with contextlib.suppress(TypeError, ValueError):
                    total_tokens += int(evt.get("prompt_tokens") or 0) + int(
                        evt.get("completion_tokens") or 0
                    )
        result: dict[str, Any] = {}
        res_path = task_dir / "result.json"
        if res_path.is_file():
            try:
                result = json.loads(res_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                result = {}
        # Resolve the harness chip's model from the actual run record. The
        # chip must reflect the execution SOURCE (claude-cli = Claude Code,
        # openai-codex = Codex), NOT the model's billing provider (anthropic /
        # openai = PAYG). session.json omits model/provider for cli-managed
        # sub-agents, so prefer dialogue.jsonl's session_start; the codex path
        # already records source-aligned provider "openai-codex", while the
        # claude-cli path records bare "anthropic" + a claude_cli_session_id.
        model, provider = _resolve_subagent_model(session, dialogue_events)
        rows.append(
            {
                "task_id": task_dir.name,
                "phase": phase,
                "model": model,
                "provider": provider,
                "turn_count": sum(
                    1
                    for e in dialogue_events
                    if e.get("event") in ("user_message", "assistant_message")
                ),
                "total_cost": total_cost,
                "total_tokens": total_tokens,
                "duration_ms": duration_ms,
                "dialogue_events": dialogue_events,
                "session": session,
                "result": result,
            }
        )
    rows.sort(key=lambda r: (phase_order.get(r["phase"], 99), r["task_id"]))
    return rows


def _read_dialogue(path: Path) -> list[dict[str, Any]]:
    """Parse a ``dialogue.jsonl`` file into a list of event dicts."""
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(evt, dict):
                out.append(evt)
    except OSError:
        return []
    return out


_TASK_PREFIX_TO_PHASE: tuple[tuple[str, str], ...] = (
    ("super-", "supervisor"),
    ("lit-", "literature_review"),
    ("gen-", "generator"),
    ("prox-", "proximity"),
    ("crit-", "critic"),
    ("pilot-", "pilot"),
    ("vote-", "ranker"),
    ("evolve-", "evolver"),
    ("meta-", "meta_reviewer"),
)


def _phase_from_task_id(task_id: str) -> str:
    """Infer phase from task_id prefix (mirrors orchestrator's _infer_phase_from_task)."""
    for prefix, phase in _TASK_PREFIX_TO_PHASE:
        if task_id.startswith(prefix):
            return phase
    return "unknown"


def _render_hub_sidebar(
    common: dict[str, str],
    *,
    active_section: str = "seedgen",
) -> str:
    """Render the rich sidebar shared by all hub pages.

    Mirrors the ``<aside class="sidebar">`` block in
    ``docs/self-improving/seed-generation/run.html.template`` so sub-pages
    (agents / timeline / tournament / lineage / candidates) inherit the
    same brand, section counts, nav-list classes, and CSS hooks as
    cycle-root pages — previously, this function emitted a flatter shell
    that hub.css did not target (no ``.sidebar`` / ``.brand-sub`` /
    ``.count`` / ``.nav-list`` rules), so deep paths rendered as
    plain-text bullets without the dense-table layout.

    ``active_section`` marks one of {"hub", "petri", "seedgen",
    "autoresearch"} as the current top-level area so the matching link
    gets ``class="active" aria-current="page"``.
    """
    base = "/geode/self-improving"
    active = {
        "hub": ' class="active" aria-current="page"' if active_section == "hub" else "",
        "petri": (' class="active" aria-current="page"' if active_section == "petri" else ""),
        "seedgen": (' class="active" aria-current="page"' if active_section == "seedgen" else ""),
        "autoresearch": (
            ' class="active" aria-current="page"' if active_section == "autoresearch" else ""
        ),
    }
    petri_recent = common["sidebar_petri_recent"]
    seedgen_runs = common["sidebar_seedgen_runs"]
    petri_count = common["petri_count"]
    seedgen_count_label = common["seedgen_count_label"]
    ar_label = html_escape(common["autoresearch_status_label"])
    return f"""<aside class="sidebar">
    <nav aria-label="Hub navigation">
      <div class="brand">GEODE</div>
      <div class="brand-sub">/self-improving</div>

      <div class="nav-section">Hub</div>
      <ul class="nav-list">
        <li><a href="{base}/"{active["hub"]}>Overview</a></li>
      </ul>

      <div class="nav-section">Petri Audit <span class="count">{petri_count}</span></div>
      <ul class="nav-list">
        <li><a href="{base}/petri-bundle/">SPA log viewer &#x2197;</a></li>
        <li><a href="{base}/petri-bundle/"{active["petri"]}>Recent audits</a>
          <ul class="sub-nav">
{petri_recent}
          </ul>
        </li>
      </ul>

      <div class="nav-section">Seed Generation \
<span class="count">{seedgen_count_label}</span></div>
      <ul class="nav-list">
        <li><a href="{base}/seed-generation/"{active["seedgen"]}>All runs</a>
          <ul class="sub-nav">
{seedgen_runs}
          </ul>
        </li>
        <li><a href="/geode/docs/petri/seeds">Seed runs (docs) &#x2197;</a></li>
      </ul>

      <div class="nav-section">Autoresearch <span class="count">{ar_label}</span></div>
      <ul class="nav-list">
        <li><a href="{base}/autoresearch/baseline/">Baseline</a></li>
        <li><a href="{base}/autoresearch/mutations/">Mutations</a></li>
        <li><a href="{base}/autoresearch/results/">Results</a></li>
        <li><a href="{base}/autoresearch/policies/">Policies</a></li>
      </ul>

      <div class="nav-section">Docs</div>
      <ul class="nav-list">
        <li><a href="/geode/docs/petri/overview">Petri overview</a></li>
        <li><a href="/geode/docs/petri/run">Run an audit</a></li>
        <li><a href="/geode/docs/petri/judge-dimensions">Judge dimensions</a></li>
      </ul>

      <div class="nav-section">Meta</div>
      <ul class="nav-list">
        <li>\
<a href="https://github.com/mangowhoiscloud/geode" rel="noopener">GitHub &#x2197;</a></li>
      </ul>
    </nav>
  </aside>"""


def _render_seedgen_subpage(
    *,
    title: str,
    active_link: str,
    body: str,
    common: dict[str, str],
) -> str:
    """Common shell for a seedgen sub-page (agents / timeline / tournament).

    Renders the standard hub layout (sidebar + content) so every
    sub-page is sidebar-consistent with cycle-root pages. ``active_link``
    is retained on the public signature for caller back-compat but no
    longer drives sidebar markup — sub-page navigation now lives in the
    in-content sub-views grid (see ``run.html.template``) rather than
    sidebar bullets.
    """
    _ = active_link  # callers still pass it; reserved for future per-section highlighting
    sidebar_html = _render_hub_sidebar(common, active_section="seedgen")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_escape(title)} — GEODE Self-Improving Hub</title>
<link rel="stylesheet" href="/geode/self-improving/assets/hub.css">
</head>
<body>

<div class="shell">
  {sidebar_html}

  <main class="content">
    <h1 class="page-title">{html_escape(title)}</h1>
    {body}
    <div class="build-info">
      <p class="version-stamp">
        Rendered against GEODE <code>v{common["geode_version"]}</code> &middot;
        DESIGN.md schema {common["design_schema_version"]} &middot; built {common["build_date"]}.
      </p>
    </div>
  </main>
</div>
</body>
</html>
"""


def _chip_for_subagent(sa: dict[str, Any]) -> tuple[str, str]:
    """Resolve the harness chip for a sub-agent row.

    session.json carries ``(model, provider)`` separately, so we
    construct ``"provider/model"`` for ``_harness_chip`` lookup when
    the model lacks a ``/`` prefix.
    """
    model = str(sa.get("model") or "")
    provider = str(sa.get("provider") or "")
    if provider and "/" not in model:
        return _harness_chip(f"{provider}/{model}")
    return _harness_chip(model)


def _render_agents_index_body(run_id: str, subagents: list[dict[str, Any]]) -> str:
    """Dense table: per-sub-agent row (task_id link / phase / model / turns / cost / duration)."""
    if not subagents:
        return (
            '<section class="page-sub">'
            '<p class="muted">No sub-agent traces published for this run '
            "(may be a pre-PR-SEEDS-HIRES run, or instrumentation hasn't "
            "backfilled).</p></section>"
        )
    rows: list[str] = []
    for sa in subagents:
        chip_class, chip_label = _chip_for_subagent(sa)
        tokens_label = f"{int(sa.get('total_tokens') or 0):,}" if sa.get("total_tokens") else "—"
        dur_label = f"{sa['duration_ms'] / 1000:.1f}s" if sa["duration_ms"] > 0 else "—"
        rows.append(
            f"        <tr>"
            f'<td class="id"><a href="/geode/self-improving/seed-generation/{html_escape(run_id)}'
            f'/agent/{html_escape(sa["task_id"])}/">'
            f"<code>{html_escape(sa['task_id'])}</code></a></td>"
            f'<td><span class="bucket seedgen">{html_escape(sa["phase"])}</span></td>'
            f'<td><span class="chip {chip_class}">{chip_label}</span> '
            f"<code>{html_escape(str(sa.get('model') or '—'))}</code></td>"
            f'<td class="num">{sa["turn_count"]}</td>'
            f'<td class="num">{tokens_label}</td>'
            f'<td class="num">{dur_label}</td>'
            "</tr>"
        )
    rows_html = "\n".join(rows)
    return f"""<section class="page-sub">
  <p class="muted">{len(subagents)} sub-agent{"s" if len(subagents) != 1 else ""} —
  every conversation turn captured. Click a row for full dialogue.</p>
  <div class="heatmap-scroll">
    <table class="records seedgen-agents">
      <thead><tr>
        <th>task_id</th><th>phase</th><th>model</th>
        <th class="num">turns</th><th class="num">tokens</th><th class="num">duration</th>
      </tr></thead>
      <tbody>
{rows_html}
      </tbody>
    </table>
  </div>
</section>
"""


def _render_agent_detail_body(run_id: str, sa: dict[str, Any]) -> str:
    """Per-turn `<details>` page with session metadata header + dialogue events."""
    chip_class, chip_label = _chip_for_subagent(sa)
    dur = sa["duration_ms"]
    summary = sa.get("result", {}).get("summary") or "—"
    turns: list[str] = []
    for evt in sa["dialogue_events"]:
        kind = evt.get("event")
        if kind == "session_start":
            pre_body = html_escape(json.dumps(evt, ensure_ascii=False, indent=2))
            turns.append(
                f'<details open class="turn"><summary>session_start</summary>'
                f'<pre class="msg">{pre_body}</pre></details>'
            )
        elif kind == "user_message":
            text = str(evt.get("text") or "")
            turns.append(
                f'<details class="turn user"><summary>user — turn '
                f"{evt.get('seq', '?')} ({len(text)} chars)</summary>"
                f'<pre class="msg">{html_escape(text)}</pre></details>'
            )
        elif kind == "assistant_message":
            text = str(evt.get("text") or "")
            turns.append(
                f'<details class="turn assistant"><summary>assistant — turn '
                f"{evt.get('seq', '?')} ({len(text)} chars)</summary>"
                f'<pre class="msg">{html_escape(text)}</pre></details>'
            )
        elif kind == "session_end":
            pre_body = html_escape(json.dumps(evt, ensure_ascii=False, indent=2))
            turns.append(
                f'<details open class="turn session-end"><summary>session_end — '
                f"{int(evt.get('prompt_tokens') or 0) + int(evt.get('completion_tokens') or 0):,} "
                f"tokens, duration {float(evt.get('duration_s') or 0):.2f}s</summary>"
                f'<pre class="msg">{pre_body}</pre></details>'
            )
        else:
            pre_body = html_escape(json.dumps(evt, ensure_ascii=False, indent=2))
            turns.append(
                f'<details class="turn"><summary>{html_escape(str(kind))} — seq '
                f"{evt.get('seq', '?')}</summary>"
                f'<pre class="msg">{pre_body}</pre></details>'
            )
    turns_html = "\n".join(turns) if turns else '<p class="muted">No dialogue events.</p>'
    back_href = f"/geode/self-improving/seed-generation/{html_escape(run_id)}/agents/"
    tokens = int(sa.get("total_tokens") or 0)
    tokens_label = f"{tokens:,}" if tokens else "—"
    dur_label = f"{dur / 1000:.2f}s" if dur > 0 else "—"
    model_chip = (
        f'<span class="chip {chip_class}">{chip_label}</span>'
        f" <code>{html_escape(str(sa.get('model') or '—'))}</code>"
    )
    return f"""<section class="page-sub run-detail-header">
  <dl>
    <dt>task_id</dt><dd><code>{html_escape(sa["task_id"])}</code></dd>
    <dt>phase</dt><dd><span class="bucket seedgen">{html_escape(sa["phase"])}</span></dd>
    <dt>model</dt><dd>{model_chip}</dd>
    <dt>turns</dt><dd>{sa["turn_count"]}</dd>
    <dt>tokens</dt><dd>{tokens_label}</dd>
    <dt>duration</dt><dd>{dur_label}</dd>
    <dt>result summary</dt><dd>{html_escape(str(summary))}</dd>
  </dl>
  <p><a href="{back_href}">← back to agents</a></p>
</section>
<section class="page-sub">
  <h3>Conversation ({sa["turn_count"]} turns)</h3>
  {turns_html}
</section>
"""


def _render_timeline_body(
    run_id: str,
    bundle_dir: Path | None,
    subagents: list[dict[str, Any]],
) -> str:
    """Phoenix-style nested span list — per-phase `<section>` with sub-agents inside."""
    if bundle_dir is None:
        return (
            '<section class="page-sub"><p class="muted">No bundle data for this run.</p></section>'
        )
    per_phase_costs: dict[str, dict[str, Any]] = {}
    pp_path = bundle_dir / "per_phase_costs.json"
    if pp_path.is_file():
        try:
            per_phase_costs = json.loads(pp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            per_phase_costs = {}
    transcript = _read_dialogue(bundle_dir / "transcript.jsonl")
    phase_events: dict[str, list[dict[str, Any]]] = {}
    for evt in transcript:
        payload = evt.get("payload") if isinstance(evt, dict) else None
        if isinstance(payload, dict):
            role = payload.get("role")
            if isinstance(role, str):
                phase_events.setdefault(role, []).append(evt)
    by_phase: dict[str, list[dict[str, Any]]] = {}
    for sa in subagents:
        by_phase.setdefault(sa["phase"], []).append(sa)
    phase_order = [
        "supervisor",
        "literature_review",
        "generator",
        "proximity",
        "critic",
        "pilot",
        "ranker",
        "evolver",
        "meta_reviewer",
    ]
    sections: list[str] = []
    for phase in phase_order:
        if phase not in per_phase_costs and phase not in by_phase and phase not in phase_events:
            continue
        cost = per_phase_costs.get(phase, {})
        dur_ms = float(cost.get("duration_ms", 0.0) or 0.0)
        agent_count = int(cost.get("agent_count", 0) or 0)
        phase_tokens = sum(int(sa.get("total_tokens") or 0) for sa in by_phase.get(phase, []))
        sub_html: list[str] = []
        for sa in by_phase.get(phase, []):
            link = (
                f"/geode/self-improving/seed-generation/{html_escape(run_id)}"
                f"/agent/{html_escape(sa['task_id'])}/"
            )
            sub_html.append(
                f'<li><a href="{link}"><code>{html_escape(sa["task_id"])}</code></a> '
                f"— {sa['turn_count']} turns, "
                f"{int(sa.get('total_tokens') or 0):,} tokens, {sa['duration_ms'] / 1000:.1f}s</li>"
            )
        events_html: list[str] = []
        for evt in phase_events.get(phase, [])[:8]:
            events_html.append(
                f"<li><code>{html_escape(str(evt.get('event') or '?'))}</code> "
                f"@ {html_escape(str(evt.get('ts') or ''))}</li>"
            )
        none_li = '<li class="muted">none</li>'
        sub_inner = "".join(sub_html) or none_li
        events_inner = "".join(events_html) or none_li
        agent_plural = "s" if agent_count != 1 else ""
        hook_event_count = len(phase_events.get(phase, []))
        sections.append(
            f'<section class="page-sub phase-block">'
            f"<h3>{html_escape(phase)}</h3>"
            f'<p class="muted">duration {dur_ms / 1000:.1f}s · '
            f"{phase_tokens:,} tokens · {agent_count} sub-agent{agent_plural}</p>"
            f"<details><summary>sub-agents ({len(sub_html)})</summary>"
            f'<ul class="event-list">{sub_inner}</ul>'
            "</details>"
            f"<details><summary>hook events ({hook_event_count})</summary>"
            f'<ul class="event-list">{events_inner}</ul>'
            "</details>"
            "</section>"
        )
    body = (
        "\n".join(sections)
        if sections
        else ('<section class="page-sub"><p class="muted">No phase data published.</p></section>')
    )
    return f"""<p class="muted">9-phase timeline reading from
  <code>transcript.jsonl</code> + <code>per_phase_costs.json</code>.
  Each phase &lt;section&gt; nests its sub-agent fan-out + filtered hook events.</p>
{body}
"""


def _render_tournament_body(run_id: str, bundle_dir: Path | None) -> str:
    """Tournament progression page — match-by-match selection history.

    PR-HUB-VIS-CYCLE1-FOLLOWUP (2026-05-28) — restructured to anchor the
    page to the **MD ↔ MD matching + selection history** flow per
    operator feedback. Each match links both candidate cids to their
    per-cid MD viewer page; voter rationale moved into ``<details>``
    expander to keep the chronological match list scannable. New
    top-level Elo summary table joins survivors + non-survivors so the
    operator sees who got selected and by how much.
    """
    if bundle_dir is None:
        return (
            '<section class="page-sub"><p class="muted">No bundle data for this run.</p></section>'
        )
    t_path = bundle_dir / "tournament.json"
    if not t_path.is_file():
        return (
            '<section class="page-sub">'
            '<p class="muted">No <code>tournament.json</code> for this run '
            "(may be a pre-PR-SEEDS-HIRES run).</p></section>"
        )
    try:
        data = json.loads(t_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return (
            '<section class="page-sub"><p class="muted">tournament.json unreadable.</p></section>'
        )
    state_path = bundle_dir / "state.json"
    state: dict[str, Any] = {}
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    matches = data.get("matches") or []
    voter_panel = data.get("voter_panel") or []
    panel_chips: list[str] = []
    for v in voter_panel:
        chip_class, chip_label = _harness_chip(v.get("voter_model", ""))
        panel_chips.append(
            f'<span class="chip {chip_class}">{chip_label}</span> '
            f"<code>{html_escape(v.get('voter_id', '—'))}</code>"
        )
    elo_ratings = state.get("elo_ratings") or {}
    survivors = {str(s) for s in state.get("survivors") or []}
    per_cid: dict[str, dict[str, Any]] = {}
    winners_total = ties_total = quorum_lost_total = 0
    voter_ok = voter_fail = 0
    for m in matches:
        a = m.get("candidate_a")
        b = m.get("candidate_b")
        winner = m.get("winner")
        if winner is None:
            quorum_lost_total += 1
        elif winner == "tie":
            ties_total += 1
        else:
            winners_total += 1
        for v in m.get("votes") or []:
            if isinstance(v, dict):
                if v.get("parse_error"):
                    voter_fail += 1
                else:
                    voter_ok += 1
        for cid, side in ((a, "A"), (b, "B")):
            if not cid:
                continue
            row = per_cid.setdefault(str(cid), {"w": 0, "l": 0, "t": 0, "ql": 0, "delta": 0.0})
            if winner is None:
                row["ql"] += 1
            elif winner == "tie":
                row["t"] += 1
            elif winner == side:
                row["w"] += 1
            else:
                row["l"] += 1
            elo_b_val = (m.get("elo_before") or {}).get(cid)
            elo_a_val = (m.get("elo_after") or {}).get(cid)
            if isinstance(elo_b_val, (int, float)) and isinstance(elo_a_val, (int, float)):
                row["delta"] += float(elo_a_val) - float(elo_b_val)
    cid_rows: list[str] = []
    for cid in sorted(per_cid, key=lambda c: -float(elo_ratings.get(c, 1000.0))):
        row = per_cid[cid]
        final_elo = elo_ratings.get(cid)
        elo_cell = (
            f'<span class="num">{float(final_elo):.0f}</span>'
            if isinstance(final_elo, (int, float))
            else '<span class="muted">—</span>'
        )
        star = "★" if cid in survivors else ""
        cid_link = (
            f"/geode/self-improving/seed-generation/{html_escape(run_id)}"
            f"/candidates/{html_escape(cid)}/"
        )
        cid_rows.append(
            f'<tr><td class="id"><a href="{cid_link}">'
            f"<code>{html_escape(cid)}</code></a> {star}</td>"
            f"<td>{row['w']}-{row['l']}-{row['t']}</td>"
            f"<td>{row['ql']}</td>"
            f'<td class="num">{row["delta"]:+.1f}</td>'
            f"<td>{elo_cell}</td></tr>"
        )
    banner = ""
    if quorum_lost_total == len(matches) and matches:
        banner = (
            '<section class="page-sub stale-banner">'
            "<p><strong>ranker integrity warning</strong> — all "
            f"{quorum_lost_total} matches lost quorum. Survivor selection "
            "is id-ordered, not merit-ordered. See per-cid lineage → ranker "
            "station for voter parse_error breakdown.</p></section>"
        )
    voter_pct = 0.0
    if (voter_ok + voter_fail) > 0:
        voter_pct = 100.0 * voter_fail / (voter_ok + voter_fail)
    summary_html = (
        '<section class="page-sub">'
        f'<p class="muted">3-voter panel: {" · ".join(panel_chips) or "—"}</p>'
        f'<p class="muted">{len(matches)} matches · '
        f"{winners_total} ratified · {ties_total} tied · "
        f"{quorum_lost_total} quorum_lost · "
        f"voter parse_error rate {voter_pct:.1f}% "
        f"({voter_fail}/{voter_ok + voter_fail})</p>"
        '<details class="elo-method"><summary class="muted">how Elo is computed</summary>'
        '<dl class="status-grid">'
        "<dt>initial rating</dt><dd>every candidate seeds at <code>1000</code></dd>"
        "<dt>expected score</dt><dd><code>E_a = 1 / (1 + 10^((R_b - R_a) / 400))</code> "
        "(logistic; a 400-point gap &asymp; 10:1 odds)</dd>"
        "<dt>update</dt><dd><code>R_a += K &middot; (S_a - E_a)</code> with "
        "<code>K = 32</code>; win <code>S=1</code>, tie <code>S=0.5</code>, "
        "loss <code>S=0</code></dd>"
        "<dt>per match</dt><dd>3-voter panel, majority winner (&ge;2 of 3); "
        "&lt;2 valid votes &rarr; <code>quorum_lost</code>, no rating change</dd>"
        "<dt>survivors</dt><dd>top 5 by final rating (id-ordered tie-break)</dd>"
        '</dl><p class="muted">Source: '
        "<code>plugins/seed_generation/tournament.py</code>.</p></details>"
        "<h3>Per-candidate Elo summary</h3>"
        '<table class="records">'
        "<thead><tr><th>cid</th><th>W-L-T</th><th>quorum_lost</th>"
        '<th class="num">Σ Elo Δ</th><th class="num">final Elo</th></tr></thead>'
        f"<tbody>{''.join(cid_rows)}</tbody></table>"
        "</section>"
    )
    match_sections: list[str] = []
    for m in matches:
        elo_before = m.get("elo_before") or {}
        elo_after = m.get("elo_after") or {}
        cand_a = str(m.get("candidate_a") or "?")
        cand_b = str(m.get("candidate_b") or "?")
        delta_a = float(m.get("elo_delta_a", 0) or 0)
        delta_b = float(m.get("elo_delta_b", 0) or 0)
        winner = m.get("winner")
        if winner is None:
            winner_chip = '<span class="bucket warn">quorum_lost</span>'
        elif winner == "tie":
            winner_chip = '<span class="bucket muted">tie</span>'
        else:
            winner_chip = f'<span class="bucket seedgen">winner: {html_escape(str(winner))}</span>'
        cid_a_link = (
            f"/geode/self-improving/seed-generation/{html_escape(run_id)}"
            f"/candidates/{html_escape(cand_a)}/"
        )
        cid_b_link = (
            f"/geode/self-improving/seed-generation/{html_escape(run_id)}"
            f"/candidates/{html_escape(cand_b)}/"
        )
        votes_html: list[str] = []
        for v in m.get("votes") or []:
            if not isinstance(v, dict):
                continue
            prov = html_escape(str(v.get("voter_provider", "?")))
            model = html_escape(str(v.get("voter_model", "?")))
            vote = v.get("vote")
            parse_err = v.get("parse_error")
            duration_s = float(v.get("duration_ms") or 0) / 1000
            if parse_err:
                chip = f'<span class="bucket warn">{prov}: fail</span>'
                rationale_block = (
                    f'<p class="muted">parse_error: <code>{html_escape(str(parse_err))}</code></p>'
                )
            else:
                vote_label = html_escape(str(vote) if vote is not None else "—")
                chip = f'<span class="bucket seedgen">{prov}: {vote_label}</span>'
                rationale = str(v.get("rationale") or "—")
                rationale_block = f'<pre class="msg">{html_escape(rationale)}</pre>'
            votes_html.append(
                f"<details><summary>{chip} <code>{model}</code> "
                f'<span class="muted">({duration_s:.1f}s)</span></summary>'
                f"{rationale_block}</details>"
            )
        votes_block = "".join(votes_html) or '<span class="muted">no voters</span>'
        match_sections.append(
            f'<section class="page-sub match">'
            f"<h3>Match <code>{html_escape(str(m.get('match_id', '?')))}</code> "
            f"— {winner_chip}</h3>"
            "<p>"
            f'A: <a href="{cid_a_link}"><code>{html_escape(cand_a)}</code></a>'
            f' <span class="muted">Elo '
            f"{float(elo_before.get(cand_a, 1000.0)):.1f} → "
            f"{float(elo_after.get(cand_a, 1000.0)):.1f} (Δ {delta_a:+.1f})"
            "</span>"
            "<br>"
            f'B: <a href="{cid_b_link}"><code>{html_escape(cand_b)}</code></a>'
            f' <span class="muted">Elo '
            f"{float(elo_before.get(cand_b, 1000.0)):.1f} → "
            f"{float(elo_after.get(cand_b, 1000.0)):.1f} (Δ {delta_b:+.1f})"
            "</span>"
            "</p>"
            '<p class="muted">voters (click to expand):</p>'
            f"{votes_block}"
            "</section>"
        )
    return banner + summary_html + "".join(match_sections)


# --------------------------------------------------------------------------- #
# PR-SEEDS-HIRES P3 (2026-05-26) — Live + Lineage surfaces
# --------------------------------------------------------------------------- #


def _load_active_runs(seeds_bundle_dir: Path) -> list[dict[str, Any]]:
    """Walk every run's progress.json; return only ones with current_phase != 'done'."""
    out: list[dict[str, Any]] = []
    if not seeds_bundle_dir.is_dir():
        return out
    for run_dir in sorted(seeds_bundle_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        progress_path = run_dir / "progress.json"
        if not progress_path.is_file():
            continue
        try:
            data = json.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("current_phase") == "done":
            continue
        data["_run_dir"] = run_dir.name
        out.append(data)
    return out


def render_seedgen_active(
    seeds_bundle_dir: Path,
    out_dir: Path,
    *,
    sidebar_petri_recent: str,
    sidebar_seedgen_runs: str,
    petri_count: int,
    seedgen_count_label: str,
    autoresearch_status_label: str,
    geode_version: str,
    build_date: str,
) -> Path:
    """Render the cross-run ``/seed-generation/active/`` live dashboard.

    PR-SEEDS-HIRES P3 — hybrid liveness: static snapshot at build time +
    a small inline JS poller (~50 lines, no framework) that refetches
    each in-progress run's ``progress.json`` every 5s and updates the
    table cells in place. ``<meta http-equiv="refresh" content="60">``
    is the JS-disabled fallback.
    """
    active = _load_active_runs(seeds_bundle_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    common = {
        "geode_version": geode_version,
        "design_schema_version": str(DESIGN_SCHEMA_VERSION),
        "build_date": build_date,
        "sidebar_petri_recent": sidebar_petri_recent,
        "sidebar_seedgen_runs": sidebar_seedgen_runs,
        "petri_count": str(petri_count),
        "seedgen_count_label": seedgen_count_label,
        "autoresearch_status_label": autoresearch_status_label,
        "run_id": "",  # no per-run context on this cross-run page
    }
    rows_html: list[str] = []
    for run in active:
        rid = html_escape(str(run.get("run_id") or run.get("_run_dir") or "?"))
        rows_html.append(
            f'        <tr data-run-id="{rid}">'
            f'<td class="id"><a href="/geode/self-improving/seed-generation/{rid}/">'
            f"<code>{rid}</code></a></td>"
            f'<td class="phase"><span class="bucket seedgen">'
            f"{html_escape(str(run.get('current_phase') or '—'))}</span></td>"
            f'<td class="step muted">{html_escape(str(run.get("current_step") or "—"))}</td>'
            f'<td class="agent muted"><code>'
            f"{html_escape(str(run.get('current_agent_task_id') or '—'))}</code></td>"
            f'<td class="eta num">{_fmt_eta(run.get("eta_seconds"))}</td>'
            f'<td class="updated muted">'
            f"{_fmt_relative_age(run.get('last_updated_at'))}</td>"
            "</tr>"
        )
    table_html = (
        '<table class="records active-runs">'
        "<thead><tr><th>run_id</th><th>phase</th><th>step</th>"
        '<th>agent</th><th class="num">eta</th><th>updated</th></tr></thead>'
        f'<tbody id="active-tbody">{"".join(rows_html)}</tbody>'
        "</table>"
    )
    empty_state = (
        '<p class="muted">No active seed-generation runs as of build '
        f"{html_escape(build_date)}. Page meta-refreshes every 60s + "
        "JS poller refetches each <code>progress.json</code> every 5s.</p>"
    )
    body = (
        '<section class="page-sub">'
        '<p class="muted live-indicator" id="live-indicator">'
        '<span class="dot"></span> updating from <code>progress.json</code> '
        "every 5s — meta-refresh fallback at 60s.</p>"
        + (table_html if active else empty_state)
        + "</section>"
    )
    # Inline vanilla JS — keep < 2KB; no framework, no imports.
    inline_js = """<script>
(function(){
  var rows = document.querySelectorAll('#active-tbody tr[data-run-id]');
  function poll(){
    rows.forEach(function(tr){
      var rid = tr.getAttribute('data-run-id');
      fetch('/geode/self-improving/petri-bundle/seeds/' + rid + '/progress.json',
            {cache: 'no-cache'})
        .then(function(r){ return r.ok ? r.json() : null; })
        .then(function(d){
          if (!d) return;
          if (d.current_phase === 'done') { tr.remove(); return; }
          var p = tr.querySelector('.phase span');
          if (p) p.textContent = d.current_phase || '—';
          var s = tr.querySelector('.step'); if (s) s.textContent = d.current_step || '—';
          var a = tr.querySelector('.agent code');
          if (a) a.textContent = d.current_agent_task_id || '—';
        })
        .catch(function(){});
    });
  }
  setInterval(poll, 5000);
  poll();
})();
</script>"""
    full_html = (
        _render_seedgen_subpage(
            title="Active runs",
            active_link="active",
            body=body,
            common=common,
        )
        .replace("</body>", f"{inline_js}\n</body>")
        .replace(
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            (
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                '\n<meta http-equiv="refresh" content="60">'
            ),
        )
    )
    out_path = out_dir / "active" / "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(full_html, encoding="utf-8")
    return out_path


def _fmt_eta(value: Any) -> str:
    if value is None:
        return "—"
    try:
        secs = float(value)
    except (TypeError, ValueError):
        return "—"
    if secs <= 0:
        return "—"
    if secs < 60:
        return f"{secs:.0f}s"
    return f"{secs / 60:.1f}m"


def _fmt_relative_age(ts: Any) -> str:
    if ts is None:
        return "—"
    try:
        ts_f = float(ts)
    except (TypeError, ValueError):
        return "—"
    age = max(0.0, _dt.datetime.now(tz=_dt.UTC).timestamp() - ts_f)
    if age < 60:
        return f"{age:.0f}s ago"
    if age < 3600:
        return f"{age / 60:.0f}m ago"
    return f"{age / 3600:.1f}h ago"


# --------------------------------------------------------------------------- #
# Per-candidate lineage page                                                  #
# --------------------------------------------------------------------------- #


def _load_candidate_lineage(
    state: dict[str, Any], bundle_dir: Path, cand_id: str
) -> list[dict[str, Any]]:
    """Build the list of stations a candidate visited across phases.

    Each station: ``{phase, body}``. Phases that have no per-candidate
    data (e.g. supervisor sets run-wide guidance not per-candidate) are
    omitted for that candidate.
    """
    stations: list[dict[str, Any]] = []

    # supervisor — run-wide guidance, only shown on the first candidate's
    # lineage as the "what the supervisor was aiming at" context.
    guidance = state.get("supervisor_guidance") if isinstance(state, dict) else None
    if isinstance(guidance, dict) and guidance.get("research_goal_analysis"):
        analysis = guidance.get("research_goal_analysis") or {}
        focus = html_escape(str(analysis.get("target_dim_focus", "—")))
        priors = html_escape(", ".join(analysis.get("sub_dim_priorities", []) or []))
        summary_field = html_escape(str(guidance.get("session_summary", "—")))
        body = (
            '<dl class="status-grid">'
            f"<dt>target_dim_focus</dt><dd>{focus}</dd>"
            f"<dt>sub_dim_priorities</dt><dd>{priors}</dd>"
            f"<dt>session_summary</dt><dd>{summary_field}</dd>"
            "</dl>"
        )
        stations.append({"phase": "supervisor", "body": body})

    # generator — body of the candidate .md file (if available).
    # PR-HUB-VIS-CYCLE1 (2026-05-28) — embed raw MD in a <script type="text/markdown">
    # tag so the client-side marked.js renderer (loaded by hub.css's sibling
    # markdown.js asset) can render headings / lists / code blocks. The raw
    # text is kept verbatim (preserves YAML frontmatter + indentation).
    cand_body_path = bundle_dir / "candidates" / f"{cand_id}.md"
    if cand_body_path.is_file():
        try:
            cand_body = cand_body_path.read_text(encoding="utf-8")
        except OSError:
            cand_body = ""
        if cand_body:
            stations.append(
                {
                    "phase": "generator",
                    "body": (
                        '<article class="markdown-body" data-md-target="generator-'
                        f'{html_escape(cand_id)}"></article>'
                        '<script type="text/markdown" data-md-source="generator-'
                        f'{html_escape(cand_id)}">{html_escape(cand_body)}</script>'
                    ),
                }
            )

    # proximity — removed_duplicates rationale (if this candidate was a
    # dup of another) or quietly omit.
    removed = state.get("removed_duplicates") if isinstance(state, dict) else []
    for rd in removed or []:
        if isinstance(rd, dict) and rd.get("id") == cand_id:
            stations.append(
                {
                    "phase": "proximity",
                    "body": (
                        f'<p class="muted">Dropped: {html_escape(str(rd.get("reason", "—")))}</p>'
                    ),
                }
            )

    # critic — reflections + debate_transcripts
    reflections = state.get("reflections", {}) if isinstance(state, dict) else {}
    if isinstance(reflections, dict) and cand_id in reflections:
        r = reflections[cand_id] if isinstance(reflections[cand_id], dict) else {}
        strengths = "".join(f"<li>{html_escape(str(s))}</li>" for s in r.get("strengths") or [])
        weaknesses = "".join(f"<li>{html_escape(str(w))}</li>" for w in r.get("weaknesses") or [])
        rewrite_section = html_escape(str(r.get("rewrite_section", "—")))
        stations.append(
            {
                "phase": "critic",
                "body": (
                    '<dl class="status-grid">'
                    f"<dt>judge_risk</dt><dd>{html_escape(str(r.get('judge_risk', '—')))}</dd>"
                    "<dt>discrimination</dt>"
                    f"<dd>{r.get('discrimination_estimate', '—')}</dd>"
                    f"<dt>strengths</dt><dd><ul>{strengths}</ul></dd>"
                    f"<dt>weaknesses</dt><dd><ul>{weaknesses}</ul></dd>"
                    f"<dt>rewrite_section</dt><dd>{rewrite_section}</dd>"
                    "</dl>"
                ),
            }
        )
    debates = state.get("debate_transcripts", {}) if isinstance(state, dict) else {}
    if isinstance(debates, dict) and cand_id in debates:
        turns = debates[cand_id] if isinstance(debates[cand_id], list) else []
        turn_html: list[str] = []
        for t in turns:
            if not isinstance(t, dict):
                continue
            spkr = html_escape(str(t.get("speaker", "?")))
            content = html_escape(str(t.get("content", "")))
            turn_html.append(
                f'<details class="turn {spkr}"><summary>{spkr} — turn '
                f"{t.get('turn', '?')}</summary>"
                f'<pre class="msg">{content}</pre></details>'
            )
        if turn_html:
            stations.append(
                {
                    "phase": "critic_debate",
                    "body": f'<p class="muted">{len(turn_html)} debate turns</p>'
                    + "".join(turn_html),
                }
            )

    # pilot — dim_means + dim_stderr
    pilot_scores = state.get("pilot_scores", {}) if isinstance(state, dict) else {}
    if isinstance(pilot_scores, dict) and cand_id in pilot_scores:
        ps = pilot_scores[cand_id] if isinstance(pilot_scores[cand_id], dict) else {}
        means = ps.get("dim_means", {}) if isinstance(ps, dict) else {}
        if isinstance(means, dict) and means:
            sorted_means = sorted(
                ((k, v) for k, v in means.items() if isinstance(v, (int, float))),
                key=lambda kv: -float(kv[1]),
            )[:8]
            rows = "".join(
                f'<tr><td>{html_escape(k)}</td><td class="num">{float(v):.2f}</td></tr>'
                for k, v in sorted_means
            )
            stations.append(
                {
                    "phase": "pilot",
                    "body": (
                        f'<p class="muted">status: {html_escape(str(ps.get("status", "—")))} '
                        "· top-8 dim_means (higher = stronger audit signal)</p>"
                        '<table class="records">'
                        "<thead><tr><th>dim</th><th>mean</th></tr></thead>"
                        f"<tbody>{rows}</tbody></table>"
                    ),
                }
            )

    # ranker — matches this candidate played in tournament.json.
    # PR-HUB-VIS-CYCLE1 (2026-05-28) — extended:
    #   1. winner=None now renders as `quorum_lost` chip (was incorrectly
    #      counted as "lost" in the prior implementation — cycle 1 had
    #      all 59 matches quorum_lost from codex voter failures and the
    #      old UI would have read as "100% loss")
    #   2. Per-voter rationale expandable via <details> with provider chip
    #      + parse_error surface (separate sprint will fix the codex voter
    #      itself; this PR only makes the failure visible)
    t_path = bundle_dir / "tournament.json"
    if t_path.is_file():
        try:
            t_data = json.loads(t_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            t_data = {}
        match_rows: list[str] = []
        won = lost = tied = quorum_lost = 0
        voter_ok = voter_fail = 0
        for m in t_data.get("matches") or []:
            if cand_id not in (m.get("candidate_a"), m.get("candidate_b")):
                continue
            side = "A" if m.get("candidate_a") == cand_id else "B"
            opp = m.get("candidate_b") if side == "A" else m.get("candidate_a")
            elo_before = (m.get("elo_before") or {}).get(cand_id, 1000.0)
            elo_after = (m.get("elo_after") or {}).get(cand_id, 1000.0)
            delta = float(elo_after) - float(elo_before)
            winner = m.get("winner")
            if winner is None:
                outcome = "quorum_lost"
                outcome_class = "warn"
                quorum_lost += 1
            elif winner == "tie":
                outcome = "tied"
                outcome_class = "muted"
                tied += 1
            elif winner == side:
                outcome = "won"
                outcome_class = "seedgen"
                won += 1
            else:
                # winner == opposing side ("A" or "B" that is NOT this cand)
                outcome = "lost"
                outcome_class = "muted"
                lost += 1
            # Per-voter rationale expander.
            voter_blocks: list[str] = []
            for v in m.get("votes") or []:
                if not isinstance(v, dict):
                    continue
                prov = html_escape(str(v.get("voter_provider", "?")))
                model = html_escape(str(v.get("voter_model", "?")))
                vote_val = v.get("vote")
                rationale = str(v.get("rationale") or "")
                parse_err = v.get("parse_error")
                if parse_err:
                    voter_fail += 1
                    parse_err_html = html_escape(str(parse_err))
                    rationale_block = (
                        f'<p class="muted">parse_error: <code>{parse_err_html}</code></p>'
                    )
                    chip = f'<span class="bucket warn">{prov}: fail</span>'
                else:
                    voter_ok += 1
                    rationale_block = f'<pre class="msg">{html_escape(rationale) or "—"}</pre>'
                    vote_label = html_escape(str(vote_val) if vote_val is not None else "—")
                    chip = f'<span class="bucket seedgen">{prov}: {vote_label}</span>'
                voter_blocks.append(
                    f"<details><summary>{chip} <code>{model}</code></summary>"
                    f"{rationale_block}</details>"
                )
            voters_html = "".join(voter_blocks) or '<span class="muted">no voters</span>'
            match_rows.append(
                f"<tr><td><code>{html_escape(str(m.get('match_id', '?')))}</code></td>"
                f"<td>{side} vs <code>{html_escape(str(opp))}</code></td>"
                f'<td><span class="bucket {outcome_class}">{outcome}</span></td>'
                f'<td class="num">{float(elo_before):.1f} → '
                f"{float(elo_after):.1f} (Δ {delta:+.1f})</td>"
                f"<td>{voters_html}</td></tr>"
            )
        if match_rows:
            summary_parts = [f"{won}W-{lost}L-{tied}T"]
            if quorum_lost > 0:
                summary_parts.append(f"quorum_lost {quorum_lost}")
            if voter_fail > 0:
                summary_parts.append(f"voter_fail {voter_fail}/{voter_ok + voter_fail}")
            summary = " · ".join(summary_parts)
            stations.append(
                {
                    "phase": "ranker",
                    "body": (
                        f'<p class="muted">{html_escape(summary)}</p>'
                        '<table class="records">'
                        "<thead><tr><th>match</th><th>side / opponent</th>"
                        '<th>outcome</th><th class="num">Elo</th>'
                        "<th>voters (click to expand)</th></tr></thead>"
                        f"<tbody>{''.join(match_rows)}</tbody></table>"
                    ),
                }
            )

    # evolver — evolved_candidates rows where parent_id == cand_id.
    # PR-HUB-VIS-CYCLE1 (2026-05-28) — replaces the inline unified_diff
    # ``<pre>`` block with a link to the dedicated side-by-side diff page
    # (rendered via marked.js). Diff content is no longer inline on the
    # lineage page so the page stays light + the diff page can use the
    # full viewport for two rendered MD columns.
    evolved = state.get("evolved_candidates", []) if isinstance(state, dict) else []
    # The run_id is implicit from the bundle_dir path. We resolve it to
    # build the diff page link.
    try:
        # bundle_dir = docs/self-improving/petri-bundle/seeds/<run_id>/
        run_id_for_link = bundle_dir.name
    except AttributeError:
        run_id_for_link = ""
    for ev in evolved or []:
        if not isinstance(ev, dict) or ev.get("parent_id") != cand_id:
            continue
        ev_id = str(ev.get("id", "?"))
        diff_link_html = ""
        # Gate the diff link on the shared diff-page predicate so the
        # link is emitted iff emit_seedgen_lineage_pages renders the page.
        if run_id_for_link and _evolver_diff_md_paths(bundle_dir, cand_id, ev_id) is not None:
            diff_link_html = (
                f'<p><a href="/geode/self-improving/seed-generation/'
                f"{html_escape(run_id_for_link)}/lineage/{html_escape(cand_id)}/diff/"
                f'">→ side-by-side diff (parent ↔ evolved)</a></p>'
            )
        m_axis = html_escape(str(ev.get("mutation_axis", "—")))
        m_rewrite = html_escape(str(ev.get("rewrite_section", "—")))
        m_notes = html_escape(str(ev.get("notes", "—")))
        stations.append(
            {
                "phase": "evolver",
                "body": (
                    '<dl class="status-grid">'
                    f"<dt>evolved id</dt><dd><code>{html_escape(ev_id)}</code></dd>"
                    f"<dt>mutation_axis</dt><dd>{m_axis}</dd>"
                    f"<dt>rewrite_section</dt><dd>{m_rewrite}</dd>"
                    f"<dt>notes</dt><dd>{m_notes}</dd>"
                    "</dl>" + diff_link_html
                ),
            }
        )

    return stations


def _render_lineage_index_body(run_id: str, state: dict[str, Any], bundle_dir: Path) -> str:
    """List every candidate (original + evolved) with the stations each visited."""
    ids: list[str] = []
    for c in state.get("candidates") or []:
        if isinstance(c, dict) and c.get("id"):
            ids.append(str(c["id"]))
    for ev in state.get("evolved_candidates") or []:
        if isinstance(ev, dict) and ev.get("id"):
            ids.append(str(ev["id"]))
    if not ids:
        return (
            '<section class="page-sub">'
            '<p class="muted">No candidates published for this run.</p></section>'
        )
    rows: list[str] = []
    for cid in ids:
        stations = _load_candidate_lineage(state, bundle_dir, cid)
        phase_chips = "".join(
            f'<span class="bucket seedgen">{html_escape(s["phase"])}</span> ' for s in stations
        )
        link = (
            f"/geode/self-improving/seed-generation/{html_escape(run_id)}"
            f"/lineage/{html_escape(cid)}/"
        )
        rows.append(
            f'        <tr><td class="id"><a href="{link}">'
            f"<code>{html_escape(cid)}</code></a></td>"
            f"<td>{phase_chips or '<span class="muted">no stations</span>'}</td>"
            f'<td class="num">{len(stations)}</td></tr>'
        )
    return (
        '<section class="page-sub">'
        f'<p class="muted">{len(ids)} candidates — phase-by-phase journey + diff '
        "between original and evolved variants.</p>"
        '<table class="records seedgen-agents">'
        "<thead><tr><th>candidate</th><th>stations visited</th>"
        '<th class="num">station count</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )


def _render_lineage_detail_body(run_id: str, cand_id: str, stations: list[dict[str, Any]]) -> str:
    """Per-candidate page — one `<section class="lineage-station">` per phase."""
    if not stations:
        return (
            '<section class="page-sub">'
            f'<p class="muted">No stations recorded for candidate {html_escape(cand_id)}.</p>'
            "</section>"
        )
    back_link = f"/geode/self-improving/seed-generation/{html_escape(run_id)}/lineage/"
    sections: list[str] = []
    for s in stations:
        sections.append(
            f'<section class="page-sub lineage-station">'
            f"<h3>{html_escape(s['phase'])}</h3>"
            f"{s['body']}"
            "</section>"
        )
    return (
        '<section class="page-sub run-detail-header">'
        f'<p><a href="{back_link}">← back to lineage index</a></p>'
        f"<dl><dt>candidate</dt><dd><code>{html_escape(cand_id)}</code></dd>"
        f"<dt>stations</dt><dd>{len(stations)}</dd></dl></section>"
        + "".join(sections)
        # PR-HUB-VIS-CYCLE1 (2026-05-28) — marked.js so the generator
        # station's MD body renders with headings / lists / code blocks.
        + _marked_js_loader_html()
    )


def _render_seedgen_subview_links(
    run_id: str,
    *,
    candidates_count: int,
    survivors_count: int,
    evolved_count: int,
) -> str:
    """Dense inline sub-view nav linking to the run's sub-views.

    PR-HUB-VIS-CYCLE1-FOLLOWUP (2026-05-28) added on-page entry points for
    the tournament / candidates / lineage / agents pages. PR-HUB-DESLOP
    (2026-05-29) re-renders them as a flat inline link row (``.subview-nav``)
    instead of a box-card grid — box-card-as-navigation is a slop signal
    (CLAUDE.md). Each entry is a text link + count; the one-line description
    is a hover ``title`` so the row stays scannable.

    All 4 routes are emitted unconditionally by
    :func:`_emit_seedgen_run_subpages`, so the links are always valid.
    """
    base = f"/geode/self-improving/seed-generation/{html_escape(run_id)}"
    entries = [
        (
            f"{base}/candidates/",
            "Candidates",
            f"{candidates_count} drafts",
            "All-MD catalog: critic risk / pilot top1 / ranker / evolved",
        ),
        (
            f"{base}/tournament/",
            "Tournament",
            "match history",
            "MD vs MD pairings, voter rationale, per-cid Elo summary",
        ),
        (
            f"{base}/lineage/",
            "Lineage",
            f"{candidates_count + evolved_count} cids",
            "Per-candidate 5-station journey (generator to evolver)",
        ),
        (
            f"{base}/agents/",
            "Agents",
            "sub-agent dialogues",
            "Per-task transcript (generator / critic / pilot / vote / evolver)",
        ),
    ]
    items: list[str] = []
    for href, label, count_label, desc in entries:
        items.append(
            f'<span><a href="{href}" title="{html_escape(desc)}">'
            f"{html_escape(label)}</a> "
            f'<span class="count">{html_escape(count_label)}</span></span>'
        )
    return "".join(items)


def _linkable_candidate_cids(state: dict[str, Any], bundle_dir: Path) -> list[str]:
    """Every cid the hub emits a ``/candidates/<cid>/`` or ``/lineage/<cid>/`` link for.

    De-duplicated, stable-ordered union of four sources:

    * ``state.candidates`` ids — the recorded draft roster
    * ``state.evolved_candidates`` ids — evolver offspring
    * every ``candidates/*.md`` stem in the bundle — on-disk draft bodies
    * every ``tournament.json`` match participant — the ranked population

    Legacy runs (``gen1-*``) recorded only a subset of the population in
    ``state.candidates`` (``candidates_requested`` truncation), yet the
    tournament page links *every* match participant to its
    ``/candidates/<cid>/`` viewer. Keying the viewer + lineage loops off
    ``state.candidates`` alone left those links dangling. Sourcing the
    union here keeps link-emit / page-emit parity for any bundle shape.
    """
    ordered: dict[str, None] = {}

    def _add(raw: object) -> None:
        cid = str(raw or "").strip()
        if cid:
            ordered.setdefault(cid, None)

    for cand in state.get("candidates") or []:
        if isinstance(cand, dict):
            _add(cand.get("id"))
    for ev in state.get("evolved_candidates") or []:
        if isinstance(ev, dict):
            _add(ev.get("id"))
    candidates_md_dir = bundle_dir / "candidates"
    if candidates_md_dir.is_dir():
        for md_file in sorted(candidates_md_dir.glob("*.md")):
            _add(md_file.stem)
    tournament_path = bundle_dir / "tournament.json"
    if tournament_path.is_file():
        try:
            tournament = json.loads(tournament_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            tournament = {}
        for match in tournament.get("matches") or []:
            if isinstance(match, dict):
                _add(match.get("candidate_a"))
                _add(match.get("candidate_b"))
    return list(ordered)


def _evolver_diff_md_paths(
    bundle_dir: Path, parent_id: str, evolved_id: str
) -> tuple[Path, Path] | None:
    """Resolve the ``(parent_md, evolved_md)`` pair backing a diff page, or ``None``.

    Single source of truth for whether a ``lineage/<parent>/diff/`` page
    renders: the page exists iff both MD bodies are on disk. The diff-page
    emitter, the per-cid viewer's "evolved → diff" chip, and the lineage
    evolver station all gate on this, so a diff link is never emitted for
    a page that was silently skipped (link-emit / page-emit parity).
    """
    parent_md = bundle_dir / "candidates" / f"{parent_id}.md"
    evolved_md = bundle_dir / "candidates_evolved" / f"{evolved_id}.md"
    if not evolved_md.is_file():
        # Legacy fallback — runs synced before bundle_sync split out the
        # candidates_evolved/ subdir kept evolved bodies under candidates/.
        evolved_md = bundle_dir / "candidates" / f"{evolved_id}.md"
    if parent_md.is_file() and evolved_md.is_file():
        return (parent_md, evolved_md)
    return None


def _render_candidate_md_viewer_body(
    run_id: str,
    cand_id: str,
    state: dict[str, Any],
    bundle_dir: Path,
) -> str:
    """Per-cid MD viewer page — generator MD body in isolation + flow links.

    PR-HUB-VIS-CYCLE1-FOLLOWUP (2026-05-28) — Option B from the prior
    plan MD. Renders the candidate's full MD body via marked.js without
    the surrounding 5-station lineage chrome, so the operator can read
    one seed in isolation. Header surfaces the candidate's status
    (drafted / survivor / evolver parent / evolved-of) and provides
    direct flow links to:

    * `/candidates/` — back to the catalog
    * `/lineage/<cid>/` — full 5-station journey
    * `/lineage/<cid>/diff/` — side-by-side diff (when evolved exists)
    * `/tournament/` — filter to this cid's match history (anchor)
    """
    md_path = bundle_dir / "candidates" / f"{cand_id}.md"
    # Evolved variants live in candidates_evolved/<cid>e-<hash>.md.
    if not md_path.is_file():
        md_path = bundle_dir / "candidates_evolved" / f"{cand_id}.md"
    if not md_path.is_file():
        # Last fallback — survivors/ convenience copy.
        md_path = bundle_dir / "survivors" / f"{cand_id}.md"
    if not md_path.is_file():
        return (
            '<section class="page-sub">'
            f'<p class="muted">MD body for <code>{html_escape(cand_id)}</code> '
            "not found in bundle.</p></section>"
        )
    try:
        md_body = md_path.read_text(encoding="utf-8")
    except OSError:
        return (
            '<section class="page-sub">'
            f'<p class="muted">MD body for <code>{html_escape(cand_id)}</code> '
            "could not be read.</p></section>"
        )
    survivors = {str(s) for s in state.get("survivors") or []}
    evolved = state.get("evolved_candidates") or []
    parent_to_evolved: dict[str, str] = {}
    evolved_to_parent: dict[str, str] = {}
    for ev in evolved:
        if isinstance(ev, dict):
            parent_to_evolved[str(ev.get("parent_id", ""))] = str(ev.get("id", ""))
            evolved_to_parent[str(ev.get("id", ""))] = str(ev.get("parent_id", ""))
    target_dim = str(state.get("target_dim", ""))
    elo = state.get("elo_ratings", {}).get(cand_id)
    chips: list[str] = []
    if cand_id in survivors:
        chips.append('<span class="bucket seedgen">survivor</span>')
    if cand_id in parent_to_evolved:
        ev_cid = parent_to_evolved[cand_id]
        if _evolver_diff_md_paths(bundle_dir, cand_id, ev_cid) is not None:
            evolved_target = (
                f"/geode/self-improving/seed-generation/{html_escape(run_id)}"
                f"/lineage/{html_escape(cand_id)}/diff/"
            )
        else:
            # Diff page is skipped when an MD body is missing from disk
            # (legacy runs); fall back to the evolved candidate's own
            # viewer so the chip never dangles.
            evolved_target = (
                f"/geode/self-improving/seed-generation/{html_escape(run_id)}"
                f"/candidates/{html_escape(ev_cid)}/"
            )
        chips.append(
            f'<span class="bucket seedgen">evolved → <a href="{evolved_target}">'
            f"<code>{html_escape(ev_cid)}</code></a></span>"
        )
    if cand_id in evolved_to_parent:
        parent_cid = evolved_to_parent[cand_id]
        parent_link = (
            f"/geode/self-improving/seed-generation/{html_escape(run_id)}"
            f"/candidates/{html_escape(parent_cid)}/"
        )
        chips.append(
            f'<span class="bucket seedgen">evolved-of: '
            f'<a href="{parent_link}"><code>{html_escape(parent_cid)}</code></a></span>'
        )
    if not chips:
        chips.append('<span class="bucket muted">drafted (eliminated)</span>')
    catalog_link = f"/geode/self-improving/seed-generation/{html_escape(run_id)}/candidates/"
    lineage_link = (
        f"/geode/self-improving/seed-generation/{html_escape(run_id)}"
        f"/lineage/{html_escape(cand_id)}/"
    )
    tournament_link = (
        f"/geode/self-improving/seed-generation/{html_escape(run_id)}"
        f"/tournament/#match-{html_escape(cand_id)}"
    )
    elo_cell = (
        f'Elo <span class="num">{float(elo):.0f}</span>'
        if isinstance(elo, (int, float))
        else '<span class="muted">no Elo</span>'
    )
    raw_md_link = (
        f"/geode/self-improving/petri-bundle/seeds/{html_escape(run_id)}"
        f"/{html_escape(md_path.parent.name)}/{html_escape(md_path.name)}"
    )
    return (
        '<section class="page-sub run-detail-header">'
        f'<p><a href="{catalog_link}">← back to all candidates</a></p>'
        '<dl class="status-grid">'
        f"<dt>cid</dt><dd><code>{html_escape(cand_id)}</code></dd>"
        f"<dt>target_dim</dt><dd><code>{html_escape(target_dim)}</code></dd>"
        f"<dt>status</dt><dd>{' '.join(chips)}</dd>"
        f"<dt>ranking</dt><dd>{elo_cell}</dd>"
        f"<dt>flow</dt><dd>"
        f'<a href="{lineage_link}">5-station lineage</a> · '
        f'<a href="{tournament_link}">ranker match history</a> · '
        f'<a href="{raw_md_link}">raw .md</a>'
        "</dd>"
        "</dl></section>"
        '<section class="page-sub">'
        '<article class="markdown-body" data-md-target="md-body"></article>'
        '<script type="text/markdown" data-md-source="md-body">'
        f"{html_escape(md_body)}</script>"
        "</section>"
        f"{_marked_js_loader_html()}"
    )


def _marked_js_loader_html() -> str:
    """Marked.js CDN load + auto-renderer for ``<script type="text/markdown">``.

    PR-HUB-VIS-CYCLE1 (2026-05-28) — finds every script tag with
    ``data-md-source="<key>"`` and renders its content into the matching
    ``<article data-md-target="<key>">`` via ``marked.parse()``. The CDN
    URL is jsdelivr ``marked@13/marked.min.js``; an SRI hash will be
    added in a follow-up PR once the operator picks the exact version
    they want pinned.
    """
    return (
        '<script src="https://cdn.jsdelivr.net/npm/marked@13/marked.min.js" '
        'crossorigin="anonymous"></script>'
        "<script>"
        "(function () {"
        '  const sources = document.querySelectorAll("script[type=\\"text/markdown\\"]");'
        "  sources.forEach(function (s) {"
        '    const key = s.getAttribute("data-md-source");'
        "    if (!key) return;"
        "    const target = document.querySelector("
        '      "article[data-md-target=\\"" + key + "\\"]"'
        "    );"
        '    if (!target || typeof marked === "undefined") return;'
        '    target.innerHTML = marked.parse(s.textContent || s.innerText || "");'
        "  });"
        "})();"
        "</script>"
    )


def _render_evolver_diff_body(
    run_id: str,
    cand_id: str,
    ev_meta: dict[str, Any],
    parent_md: str,
    evolved_md: str,
) -> str:
    """Side-by-side rendered MD diff page (parent vs evolved).

    PR-HUB-VIS-CYCLE1 (2026-05-28) — client-side marked.js render of two
    full MD bodies in two columns. Top of page: ``rewrite_section`` +
    ``notes`` from evolver checkpoint as context.
    """
    ev_id = str(ev_meta.get("id", "?"))
    rewrite_section = html_escape(str(ev_meta.get("rewrite_section", "—")))
    notes = html_escape(str(ev_meta.get("notes", "—")))
    mutation_axis = html_escape(str(ev_meta.get("mutation_axis", "—")))
    back_link = (
        f"/geode/self-improving/seed-generation/{html_escape(run_id)}"
        f"/lineage/{html_escape(cand_id)}/"
    )
    parent_size = len(parent_md.encode("utf-8"))
    evolved_size = len(evolved_md.encode("utf-8"))
    return (
        '<section class="page-sub run-detail-header">'
        f'<p><a href="{back_link}">← back to lineage ({html_escape(cand_id)})</a></p>'
        '<dl class="status-grid">'
        f"<dt>parent</dt><dd><code>{html_escape(cand_id)}</code> "
        f"({parent_size} bytes)</dd>"
        f"<dt>evolved</dt><dd><code>{html_escape(ev_id)}</code> "
        f"({evolved_size} bytes, Δ {evolved_size - parent_size:+d})</dd>"
        f"<dt>mutation_axis</dt><dd>{mutation_axis}</dd>"
        f"<dt>rewrite_section</dt><dd>{rewrite_section}</dd>"
        f"<dt>notes</dt><dd>{notes}</dd>"
        "</dl></section>"
        '<section class="page-sub evolver-diff-grid">'
        '<div class="diff-col parent-col">'
        f"<h3>parent <code>{html_escape(cand_id)}</code></h3>"
        f'<article class="markdown-body" data-md-target="parent"></article>'
        f'<script type="text/markdown" data-md-source="parent">'
        f"{html_escape(parent_md)}</script>"
        "</div>"
        '<div class="diff-col evolved-col">'
        f"<h3>evolved <code>{html_escape(ev_id)}</code></h3>"
        f'<article class="markdown-body" data-md-target="evolved"></article>'
        f'<script type="text/markdown" data-md-source="evolved">'
        f"{html_escape(evolved_md)}</script>"
        "</div>"
        "</section>"
        f"{_marked_js_loader_html()}"
    )


def _summarise_ranker_for_cid(cid: str, tournament: dict[str, Any]) -> dict[str, int | float | str]:
    """Per-cid ranker summary from ``tournament.json``.

    Returns ``{w, l, t, quorum_lost, voter_failed, elo_delta, status_label}``
    where ``status_label`` is the hub-displayed chip:

    * ``"<W>-<L>-<T>"`` when at least one match ratified for this cid
    * ``"<W>-<L>-<T> · quorum_lost <N>"`` when some but not all matches lost quorum
    * ``"all quorum_lost (<N>)"`` when zero ratified — PR-HUB-VIS-CYCLE1
      cycle-1 dominant case driven by the codex voter failure issue.
    """
    matches = tournament.get("matches") or []
    won = lost = tied = quorum_lost = 0
    voter_failed = 0
    elo_delta = 0.0
    for m in matches:
        a = m.get("candidate_a")
        b = m.get("candidate_b")
        if cid not in (a, b):
            continue
        side = "A" if a == cid else "B"
        opp_side = "B" if side == "A" else "A"
        winner = m.get("winner")
        if winner is None:
            quorum_lost += 1
        elif winner == "tie":
            tied += 1
        elif winner == side:
            won += 1
        elif winner == opp_side:
            lost += 1
        elo_before = (m.get("elo_before") or {}).get(cid)
        elo_after = (m.get("elo_after") or {}).get(cid)
        if isinstance(elo_before, (int, float)) and isinstance(elo_after, (int, float)):
            elo_delta += float(elo_after) - float(elo_before)
        for v in m.get("votes") or []:
            if isinstance(v, dict) and v.get("parse_error"):
                voter_failed += 1
    total_decisive = won + lost + tied
    if total_decisive == 0 and quorum_lost > 0:
        status = f"all quorum_lost ({quorum_lost})"
    elif quorum_lost > 0:
        status = f"{won}-{lost}-{tied} · quorum_lost {quorum_lost}"
    else:
        status = f"{won}-{lost}-{tied}"
    return {
        "w": won,
        "l": lost,
        "t": tied,
        "quorum_lost": quorum_lost,
        "voter_failed": voter_failed,
        "elo_delta": elo_delta,
        "status_label": status,
    }


def _render_candidates_catalog_body(
    run_id: str,
    state: dict[str, Any],
    bundle_dir: Path,
) -> str:
    """All-MD catalog — one row per draft (regardless of survivor status).

    PR-HUB-VIS-CYCLE1 (2026-05-28) — addresses cycle 1 hub gap where
    13/15 non-survivor drafts had no surface in the hub (only survivor
    cards in the index page). This page joins state.json's
    ``candidates`` / ``reflections`` / ``pilot_scores`` / ``elo_ratings``
    / ``survivors`` / ``evolved_candidates`` with ``tournament.json``
    per-cid ranker summary so operators see the complete journey
    (including quorum_lost and off-target chips) for every draft.
    """
    candidates = state.get("candidates") or []
    if not candidates:
        return (
            '<section class="page-sub">'
            '<p class="muted">No drafts recorded for this run.</p></section>'
        )
    reflections = state.get("reflections") or {}
    pilot_scores = state.get("pilot_scores") or {}
    elo_ratings = state.get("elo_ratings") or {}
    survivors = {str(s) for s in state.get("survivors") or []}
    evolved = state.get("evolved_candidates") or []
    parent_to_evolved: dict[str, str] = {}
    for ev in evolved:
        if isinstance(ev, dict):
            parent_to_evolved[str(ev.get("parent_id", ""))] = str(ev.get("id", ""))

    target_dim = str(state.get("target_dim", ""))

    t_path = bundle_dir / "tournament.json"
    tournament: dict[str, Any] = {}
    if t_path.is_file():
        try:
            tournament = json.loads(t_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            tournament = {}

    rows: list[str] = []
    quorum_lost_total = 0
    pilot_fail_count = 0
    off_target_count = 0
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        cid = str(cand.get("id", ""))
        # critic
        r = reflections.get(cid) if isinstance(reflections.get(cid), dict) else {}
        risk = str((r or {}).get("judge_risk", "—"))
        # pilot
        ps = pilot_scores.get(cid) if isinstance(pilot_scores.get(cid), dict) else {}
        means = (ps or {}).get("dim_means") if isinstance(ps, dict) else None
        if isinstance(means, dict) and means:
            sorted_means = sorted(
                ((k, v) for k, v in means.items() if isinstance(v, (int, float))),
                key=lambda kv: -float(kv[1]),
            )
            if sorted_means and float(sorted_means[0][1]) > 0.0:
                top_dim, top_val = sorted_means[0]
                pilot_cell = f"<code>{html_escape(top_dim)}</code> {float(top_val):.1f}"
                off_target = top_dim != target_dim and target_dim
            else:
                pilot_cell = '<span class="bucket warn">pilot-fail</span>'
                pilot_fail_count += 1
                off_target = False
        else:
            pilot_cell = '<span class="muted">—</span>'
            off_target = False
        if off_target:
            off_target_count += 1
            pilot_cell += ' <span class="bucket warn">off-target</span>'
        # ranker
        ranker = _summarise_ranker_for_cid(cid, tournament)
        quorum_lost_total += int(ranker["quorum_lost"])
        ranker_cell = html_escape(str(ranker["status_label"]))
        # elo
        elo_val = elo_ratings.get(cid)
        elo_cell = (
            f'<span class="num">{float(elo_val):.0f}</span>'
            if isinstance(elo_val, (int, float))
            else '<span class="muted">—</span>'
        )
        # survivor + evolved
        surv_cell = "★" if cid in survivors else ""
        ev_id = parent_to_evolved.get(cid, "")
        if ev_id:
            ev_link = (
                f"/geode/self-improving/seed-generation/{html_escape(run_id)}"
                f"/lineage/{html_escape(ev_id)}/"
            )
            evolved_cell = f'<a href="{ev_link}"><code>{html_escape(ev_id)}</code></a>'
        else:
            evolved_cell = '<span class="muted">—</span>'
        # link to lineage page
        lineage_link = (
            f"/geode/self-improving/seed-generation/{html_escape(run_id)}"
            f"/lineage/{html_escape(cid)}/"
        )
        rows.append(
            f'        <tr><td class="id"><a href="{lineage_link}">'
            f"<code>{html_escape(cid)}</code></a></td>"
            f"<td>{html_escape(risk)}</td>"
            f"<td>{pilot_cell}</td>"
            f"<td>{ranker_cell}</td>"
            f'<td class="num">{elo_cell}</td>'
            f"<td>{surv_cell}</td>"
            f"<td>{evolved_cell}</td></tr>"
        )

    banner = ""
    if quorum_lost_total > 0:
        total_matches = len(tournament.get("matches") or [])
        banner = (
            '<section class="page-sub stale-banner">'
            "<p><strong>ranker integrity warning</strong> — "
            f"{quorum_lost_total} per-cid quorum_lost events across "
            f"{total_matches} matches. Survivor selection may be id-ordered "
            "rather than merit-ordered. See per-cid lineage page → ranker station "
            "for voter parse_error breakdown.</p></section>"
        )

    return (
        f"{banner}"
        '<section class="page-sub">'
        f'<p class="muted">{len(candidates)} drafts · target_dim '
        f"<code>{html_escape(target_dim)}</code> · "
        f"{pilot_fail_count} pilot-fail · {off_target_count} off-target · "
        f"{len(survivors)} survivors · {len(parent_to_evolved)} evolved.</p>"
        '<table class="records">'
        "<thead><tr>"
        "<th>cid</th><th>critic risk</th><th>pilot top1</th>"
        '<th>ranker</th><th class="num">elo</th>'
        "<th>survived?</th><th>evolved →</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )


def emit_seedgen_lineage_pages(
    run_id: str,
    state: dict[str, Any],
    bundle_dir: Path,
    out_dir: Path,
    *,
    sidebar_petri_recent: str,
    sidebar_seedgen_runs: str,
    petri_count: int,
    seedgen_count_label: str,
    autoresearch_status_label: str,
    geode_version: str,
    build_date: str,
) -> None:
    """Emit lineage/index.html + lineage/<cand_id>/index.html for a run."""
    common = {
        "geode_version": geode_version,
        "design_schema_version": str(DESIGN_SCHEMA_VERSION),
        "build_date": build_date,
        "sidebar_petri_recent": sidebar_petri_recent,
        "sidebar_seedgen_runs": sidebar_seedgen_runs,
        "petri_count": str(petri_count),
        "seedgen_count_label": seedgen_count_label,
        "autoresearch_status_label": autoresearch_status_label,
        "run_id": html_escape(run_id),
    }
    # Index
    idx_body = _render_lineage_index_body(run_id, state, bundle_dir)
    idx_html = _render_seedgen_subpage(
        title=f"Lineage — {run_id}",
        active_link="lineage",
        body=idx_body,
        common=common,
    )
    (out_dir / "lineage").mkdir(parents=True, exist_ok=True)
    (out_dir / "lineage" / "index.html").write_text(idx_html, encoding="utf-8")

    # Per-candidate — same cid union as the /candidates/ viewer loop so a
    # viewer's "5-station lineage" flow link always resolves (link-emit /
    # page-emit parity — see _linkable_candidate_cids).
    for cid in _linkable_candidate_cids(state, bundle_dir):
        stations = _load_candidate_lineage(state, bundle_dir, cid)
        detail_html = _render_seedgen_subpage(
            title=f"Lineage {cid} — {run_id}",
            active_link="lineage",
            body=_render_lineage_detail_body(run_id, cid, stations),
            common=common,
        )
        cand_dir = out_dir / "lineage" / cid
        cand_dir.mkdir(parents=True, exist_ok=True)
        (cand_dir / "index.html").write_text(detail_html, encoding="utf-8")

    # PR-HUB-VIS-CYCLE1 (2026-05-28) — emit side-by-side diff page for
    # every parent_id ↔ evolved_id pair. Skipped silently when either MD
    # body is missing from disk.
    for ev in state.get("evolved_candidates") or []:
        if not isinstance(ev, dict):
            continue
        parent_id = str(ev.get("parent_id", ""))
        ev_id = str(ev.get("id", ""))
        if not parent_id or not ev_id:
            continue
        diff_md_paths = _evolver_diff_md_paths(bundle_dir, parent_id, ev_id)
        if diff_md_paths is None:
            continue
        parent_md_path, evolved_md_path = diff_md_paths
        try:
            parent_md = parent_md_path.read_text(encoding="utf-8")
            evolved_md = evolved_md_path.read_text(encoding="utf-8")
        except OSError:
            continue
        diff_body = _render_evolver_diff_body(
            run_id=run_id,
            cand_id=parent_id,
            ev_meta=ev,
            parent_md=parent_md,
            evolved_md=evolved_md,
        )
        diff_html = _render_seedgen_subpage(
            title=f"Diff {parent_id} → {ev_id} — {run_id}",
            active_link="lineage",
            body=diff_body,
            common=common,
        )
        diff_dir = out_dir / "lineage" / parent_id / "diff"
        diff_dir.mkdir(parents=True, exist_ok=True)
        (diff_dir / "index.html").write_text(diff_html, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Autoresearch surface loaders + renderers (P6)                               #
# --------------------------------------------------------------------------- #
def _load_baseline(state_dir: Path) -> tuple[dict[str, Any] | None, bool, Path | None]:
    """Return ``(baseline_data, stale, source_path)``.

    Reads ``baseline.json`` if present. Otherwise falls back to the
    most recent ``baseline.json.outdated-*`` snapshot (per design
    contract). Returns ``(None, False, None)`` if neither exists or
    if JSON parse fails.
    """
    live = state_dir / "baseline.json"
    if live.exists():
        try:
            data = json.loads(live.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            LOG.warning("baseline.json parse error: %s", live)
            return (None, False, live)
        if not isinstance(data, dict):
            return (None, False, live)
        return (data, False, live)
    # Outdated fallback — pick the freshest .outdated-* by mtime.
    candidates = sorted(
        state_dir.glob("baseline.json.outdated-*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return (None, False, None)
    chosen = candidates[0]
    try:
        data = json.loads(chosen.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOG.warning("baseline outdated parse error: %s", chosen)
        return (None, True, chosen)
    if not isinstance(data, dict):
        return (None, True, chosen)
    return (data, True, chosen)


# PR-BASELINE-REGISTRY (2026-05-30) — discriminator for the registry's
# baseline rows (mirrors ``core.self_improving.train._BASELINE_REGISTRY_KIND``). The
# legacy gen timeline filters these out; the dedicated index lands in a
# follow-up phase.
_BASELINE_REGISTRY_ROW_KIND = "baseline"


def _load_baseline_archive(state_dir: Path) -> list[dict[str, Any]]:
    """Return list of dicts from ``baseline_archive.jsonl``.

    One dict per line. Malformed lines are skipped with a warning.
    """
    archive = state_dir / "baseline_archive.jsonl"
    if not archive.exists():
        return []
    rows: list[dict[str, Any]] = []
    for ln in archive.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            entry = json.loads(ln)
        except json.JSONDecodeError:
            LOG.warning("baseline_archive line parse-error: %r", ln[:80])
            continue
        if isinstance(entry, dict):
            rows.append(entry)
    return rows


def _load_mutations(state_dir: Path) -> list[dict[str, Any]]:
    """Return list of dicts from ``mutations.jsonl``."""
    path = state_dir / "mutations.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            entry = json.loads(ln)
        except json.JSONDecodeError:
            LOG.warning("mutations line parse-error: %r", ln[:80])
            continue
        if isinstance(entry, dict):
            rows.append(entry)
    return rows


def _load_campaign_progress(state_dir: Path) -> dict[str, Any]:
    """Parse ``campaign-progress.log`` into per-cycle records + the gen-0 noise band.

    The campaign runner is the AUTHORITATIVE source for the per-cycle **verdict**
    (``promote`` / ``reject`` / ``SKIP``) and the gen-0 K-mean baseline band —
    neither is in ``mutations.jsonl`` (its attribution rows carry the numbers but
    not the gate decision, and a SKIP cycle writes no attribution row at all). Mirrors
    the live log-line format written by ``core/self_improving/campaign.py`` (the SoT)
    so the two stay in lockstep.

    Returns ``{"cycles": [{arm, n, total, sel, held, delta, verdict, skip, ts}],
    "gen0": [{n, total, sel, held}], "noise": {k, mean, stderr} | None}``. Every
    numeric cast is guarded — a malformed line contributes nothing rather than
    raising. Missing file → empty structure (the renderer shows an honest awaiting
    state). NOTE the verdict here is the GATE decision, which is the one SoT a
    promoted-baseline read cannot give (it only records the promotes, never the
    rejects/SKIPs) — so this is the per-cycle ``latest`` SoT, distinct from the
    ``promoted`` baseline_archive SoT.
    """
    path = state_dir / _CAMPAIGN_PROGRESS_LOG
    out: dict[str, Any] = {"cycles": [], "gen0": [], "noise": None}
    if not path.exists():
        return out
    try:
        log_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        # A read/permission error reads the same as "no campaign yet" — never abort
        # the whole build (this loader runs BEFORE the per-page _safe() wrapper).
        return out
    for line in log_lines:
        ts_match = _CAMPAIGN_TS_RE.search(line)
        line_ts = ts_match.group("ts") if ts_match else ""
        cycle = _CAMPAIGN_CYCLE_RE.search(line)
        if cycle:
            rec: dict[str, Any] = {
                "arm": cycle.group("arm"),
                "n": int(cycle.group("n")),
                "total": int(cycle.group("total")),
                "ts": line_ts,
                "skip": bool(cycle.group("skip")),
            }
            if not rec["skip"]:
                # The regex only matches numeric literals, so float() is safe here;
                # still guarded for the contract-completeness rule.
                try:
                    rec["sel"] = float(cycle.group("sel"))
                    rec["held"] = float(cycle.group("held"))
                    rec["delta"] = float(cycle.group("delta"))
                except (TypeError, ValueError):
                    continue
                rec["verdict"] = cycle.group("verdict")
            out["cycles"].append(rec)
            continue
        gen0 = _CAMPAIGN_GEN0_RE.search(line)
        if gen0:
            # The regex only captures numeric literals, so the cast is contract-safe;
            # suppressing here keeps a hypothetically-malformed group from sinking the
            # whole parse (graceful-contract completeness at the cast boundary).
            with contextlib.suppress(TypeError, ValueError):
                out["gen0"].append(
                    {
                        "n": int(gen0.group("n")),
                        "total": int(gen0.group("total")),
                        "sel": float(gen0.group("sel")),
                        "held": float(gen0.group("held")),
                    }
                )
            continue
        noise = _CAMPAIGN_NOISE_RE.search(line)
        if noise and out["noise"] is None:
            with contextlib.suppress(TypeError, ValueError):
                out["noise"] = {
                    "k": int(noise.group("k")),
                    "mean": float(noise.group("mean")),
                    "stderr": float(noise.group("stderr")),
                }
    return out


def _load_campaign_gen0_baseline(repo_root: Path) -> dict[str, Any] | None:
    """Read the campaign gen-0 K-mean snapshot baseline.json.

    Located at ``<repo>/state/campaign/gen-0-snapshot/baseline.json`` (a sibling of
    the self-improving state dir — NOT ``state/autoresearch/baseline.json``, which
    is the top-level promoted SoT). Carries ``raw.dim_means`` (24 dims, Petri 1-10 scale,
    LOWER-is-better) + ``raw.fitness_stderr`` — the per-dim floor the campaign's
    per-cycle held-out is compared against. Returns ``None`` (honest awaiting state)
    when the snapshot is absent or malformed.
    """
    path = repo_root.joinpath(*_CAMPAIGN_GEN0_SNAPSHOT)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _load_audit_manifest(repo_root: Path) -> list[dict[str, Any]]:
    """Parse the Petri eval-log MANIFEST into completed-at-keyed audit records.

    The MANIFEST (``docs/audits/eval-logs/MANIFEST.jsonl``) is the ONLY ledger that
    links an audit's ``completed_at`` to its ``.eval`` archive filename, the
    ``seed_ids`` it scored, and the per-sample ``summary_yaml``. The campaign does
    NOT write a per-cycle eval pointer into mutations.jsonl (the ``audit_run_id`` is
    a 12-char hash that matches no eval filename), so the cycle→eval link is
    reconstructed by matching the cycle's ``ts`` to the nearest ``completed_at``
    (see :func:`_match_audit_for_cycle`). Returns rows with a parsed epoch
    ``completed_ts`` (``float('nan')`` on a bad timestamp → never matches a cycle).
    """
    path = repo_root.joinpath(*_AUDIT_MANIFEST)
    if not path.exists():
        return []
    try:
        manifest_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        # A read error reads the same as "no MANIFEST" — never abort the build (this
        # loader runs BEFORE the per-page _safe() wrapper).
        return []
    rows: list[dict[str, Any]] = []
    for line in manifest_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        completed = entry.get("completed_at")
        completed_ts = float("nan")
        if isinstance(completed, str) and completed:
            try:
                completed_ts = _dt.datetime.fromisoformat(completed).timestamp()
            except ValueError:
                completed_ts = float("nan")
        entry["completed_ts"] = completed_ts
        rows.append(entry)
    return rows


def _match_audit_for_cycle(
    cycle_ts: float, manifest: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the MANIFEST audit whose ``completed_at`` is closest to ``cycle_ts``.

    A cycle's attribution-row ``ts`` is the post-audit write time, within a few
    seconds of the audit archive's ``completed_at`` (empirically Δ ≤ 3s on the live
    campaign; distinct audits are >10 min apart). Matches only within
    ``_AUDIT_MATCH_TOLERANCE_S`` so a cycle with NO recorded audit (a SKIP, or a
    pre-MANIFEST cycle) returns ``None`` rather than mis-attributing a far-away
    archive — the renderer then shows "no eval recorded" instead of a wrong link.
    Graceful: a non-finite ``cycle_ts`` matches nothing.
    """
    if not math.isfinite(cycle_ts):
        return None
    best: dict[str, Any] | None = None
    best_gap = _AUDIT_MATCH_TOLERANCE_S
    for row in manifest:
        completed = row.get("completed_ts")
        if not isinstance(completed, int | float) or not math.isfinite(float(completed)):
            continue
        gap = abs(float(completed) - cycle_ts)
        if gap <= best_gap:
            best_gap = gap
            best = row
    return best


def _load_summary_dims(repo_root: Path, summary_yaml: str) -> dict[str, Any] | None:
    """Read a per-audit ``*.summary.yaml`` for its per-sample non-baseline dim scores.

    The summary YAML (sibling of the MANIFEST) carries ``samples_summary`` — one
    entry per seed with its ``seed_id`` + ``non_baseline_dims`` (the dims that moved
    off the baseline floor for that sample, Petri 1-10, LOWER-is-better). Parsed with
    a tiny stdlib reader (the builder is intentionally dep-free, so no PyYAML): only
    the shallow keys this panel needs are extracted, aggregated to a per-dim count of
    samples that engaged each dim. Returns ``None`` when the file is absent /
    unreadable. NOTE this is a deliberately minimal reader — it handles the flat
    ``samples_summary`` block the campaign writes, not arbitrary YAML.
    """
    if not summary_yaml:
        return None
    path = repo_root.joinpath(*_EVAL_SUMMARY_DIR, summary_yaml)
    if not path.exists():
        return None
    dim_engaged: dict[str, int] = {}
    seed_ids: list[str] = []
    in_dims = False
    dims_indent = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw in lines:
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip(" "))
        if stripped.startswith("- id:") or stripped.startswith("seed_id:"):
            value = stripped.split(":", 1)[1].strip()
            if value and value not in seed_ids:
                seed_ids.append(value)
            in_dims = False
            continue
        if stripped == "non_baseline_dims:":
            in_dims = True
            dims_indent = indent
            continue
        if in_dims:
            # A dim line is more-indented than the ``non_baseline_dims:`` key and is
            # ``<dim>: <int>``; any line at/under the block indent ends the block.
            if indent <= dims_indent or ":" not in stripped:
                in_dims = False
            else:
                dim_name = stripped.split(":", 1)[0].strip()
                if dim_name:
                    dim_engaged[dim_name] = dim_engaged.get(dim_name, 0) + 1
                continue
    if not dim_engaged and not seed_ids:
        return None
    return {"dim_engaged": dim_engaged, "sample_count": len(seed_ids)}


def _load_results_tsv(state_dir: Path) -> list[dict[str, str]]:
    """Return list of dicts from ``results.tsv``.

    Uses ``AUTORESEARCH_RESULTS_TSV_HEADER`` to label cells when the
    file has no explicit header row (autoresearch emits rows via
    ``results_tsv:`` stdout markers, then the operator appends them).
    If a header row IS present (first line matches expected header),
    skip it.
    """
    path = state_dir / "results.tsv"
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return []
    # Detect header row.
    first_cells = lines[0].split("\t")
    data_lines = lines[1:] if first_cells == list(AUTORESEARCH_RESULTS_TSV_HEADER) else lines
    rows: list[dict[str, str]] = []
    for ln in data_lines:
        cells = ln.split("\t")
        # Pad / truncate to the 12-col contract so the renderer is robust
        # to legacy 5-col rows or extra-col future drift.
        if len(cells) < len(AUTORESEARCH_RESULTS_TSV_HEADER):
            cells = cells + [""] * (len(AUTORESEARCH_RESULTS_TSV_HEADER) - len(cells))
        rows.append(dict(zip(AUTORESEARCH_RESULTS_TSV_HEADER, cells, strict=False)))
    return rows


def _load_results_jsonl(state_dir: Path) -> list[dict[str, Any]]:
    """Return list of dicts from ``results.jsonl`` (one per line)."""
    path = state_dir / "results.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            entry = json.loads(ln)
        except json.JSONDecodeError:
            LOG.warning("results.jsonl line parse-error: %r", ln[:80])
            continue
        if isinstance(entry, dict):
            rows.append(entry)
    return rows


def _list_policies(policies_dir: Path) -> list[dict[str, Any]]:
    """List `*.json` policy files with ``{filename, mtime, size, content}``."""
    if not policies_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(policies_dir.glob("*.json")):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        try:
            content_text = path.read_text(encoding="utf-8")
        except OSError:
            content_text = ""
        try:
            content_obj: Any = json.loads(content_text) if content_text.strip() else None
        except json.JSONDecodeError:
            content_obj = None
        rows.append(
            {
                "filename": path.name,
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "content": content_obj,
                "content_text": content_text,
            }
        )
    return rows


def _fitness_sparkline(values: list[float]) -> str:
    """Map a list of fitness values to a Unicode block-char sparkline.

    Uses 8 levels (▁▂▃▄▅▆▇█). Empty list returns ``""``. Single
    value returns the middle char so the sparkline still reads as a
    flat segment instead of collapsing to nothing.
    """
    if not values:
        return ""
    if len(values) == 1:
        return _SPARKLINE_CHARS[len(_SPARKLINE_CHARS) // 2]
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span <= 0:
        return _SPARKLINE_CHARS[len(_SPARKLINE_CHARS) // 2] * len(values)
    last_idx = len(_SPARKLINE_CHARS) - 1
    out: list[str] = []
    for v in values:
        idx = round((v - lo) / span * last_idx)
        idx = max(0, min(last_idx, idx))
        out.append(_SPARKLINE_CHARS[idx])
    return "".join(out)


def _human_size(num_bytes: int) -> str:
    """Human-readable byte size."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"


def _baseline_namespace_data(baseline: dict[str, Any] | None, ns: str) -> Any:
    """Lookup a namespace value, schema-v2 first, schema-v1 fallback.

    Schema-v2 nests under ``baseline.raw / baseline.axes / ...``.
    Schema-v1 had a flat shape with `metadata` / `audit` / `fitness`
    at top level and no `raw` / `normalized` / `axes` blocks. This
    helper degrades gracefully — namespace-v2-only keys return None
    on v1 input, which the renderer formats as the "empty" notice.
    """
    if not isinstance(baseline, dict):
        return None
    if ns in baseline:
        return baseline[ns]
    # v1 fallbacks — synthesise sub-views from top-level keys.
    if ns == "raw" and isinstance(baseline.get("dim_means"), dict):
        return {
            "dim_means": baseline.get("dim_means"),
            "dim_stderr": baseline.get("dim_stderr") or {},
        }
    return None


def _render_baseline_namespace(name: str, data: Any, *, stale: bool) -> str:
    """Render one of the 7 baseline namespace blocks."""
    header = f"      <h3>{html_escape(name)}</h3>"
    meta = ""
    if stale and name == "metadata":
        meta = (
            '      <p class="namespace-meta">'
            "(reading from <code>.outdated-*</code> snapshot — see warning above)"
            "</p>"
        )
    if data is None or not data:
        body = (
            '      <p class="empty-namespace">'
            f"No <code>{html_escape(name)}</code> namespace present (schema-v1 fallback or "
            "not yet populated).</p>"
        )
        return (
            f'    <div class="namespace-block" id="ns-{html_escape(name)}">\n'
            f"{header}\n{meta}\n{body}\n    </div>"
        )
    rows: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            rows.append(_render_baseline_kv_row(name, str(key), value))
    else:
        rows.append(_render_baseline_kv_row(name, name, data))
    body_table = (
        '      <table class="records">\n'
        '        <thead><tr><th scope="col">key</th><th scope="col">value</th></tr></thead>\n'
        "        <tbody>\n" + "\n".join(rows) + "\n        </tbody>\n"
        "      </table>"
    )
    return (
        f'    <div class="namespace-block" id="ns-{html_escape(name)}">\n'
        f"{header}\n{meta}\n{body_table}\n    </div>"
    )


def _render_baseline_kv_row(ns: str, key: str, value: Any) -> str:
    """Render a single key/value row. Models in `audit` ns get chips."""
    is_model_field = ns == "audit" and key in {"auditor_model", "target_model", "judge_model"}
    if is_model_field and isinstance(value, str) and value:
        value_html = harness_chip(value)
    elif isinstance(value, dict | list):
        try:
            value_text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            value_text = str(value)
        if len(value_text) > 180:
            value_text = value_text[:177].rstrip() + "…"
        value_html = f"<code>{html_escape(value_text)}</code>"
    elif value is None:
        value_html = '<span class="muted">null</span>'
    elif isinstance(value, bool):
        value_html = f"<code>{str(value).lower()}</code>"
    elif isinstance(value, int | float):
        if isinstance(value, float):
            value_html = f'<span class="num">{value:.4f}</span>'
        else:
            value_html = f'<span class="num">{value}</span>'
    else:
        value_html = f"<code>{html_escape(str(value))}</code>"
    return (
        "          <tr>\n"
        f'            <td class="id"><code>{html_escape(key)}</code></td>\n'
        f"            <td>{value_html}</td>\n"
        "          </tr>"
    )


def _render_warning_banner(baseline_path: Path | None, stale: bool) -> str:
    if not stale or baseline_path is None:
        return ""
    return (
        '    <div class="warning-banner" role="status">'
        "Autoresearch baseline read from <code>"
        f"{html_escape(baseline_path.name)}</code>, no live "
        "<code>baseline.json</code> present in <code>state/autoresearch/</code>. "
        "Run <code>uv run python -m core.self_improving.train --promote</code> to refresh."
        "</div>"
    )


# --------------------------------------------------------------------------- #
# Baseline "show its work" sections — process / seed corpus / audit transcripts #
# Rendered from the committed docs/.../baseline/transcripts.json (produced by   #
# scripts/extract_baseline_transcripts.py). No inspect_ai import on this path.  #
# --------------------------------------------------------------------------- #

# How each extracted message speaker renders. tool_ack / system are dropped as
# conversational noise (the inspect_petri "Message sent" acks + the static
# auditor role prompt); the rest map onto the existing .turn.* dialogue styles.
_BASELINE_TURN_DISPLAY: dict[str, tuple[str, str]] = {
    "auditor": ("assistant", "auditor →"),
    "target": ("user", "target ←"),
    "setup": ("", "seed setup"),
}


def _load_baseline_transcripts(path: Path) -> dict[str, Any] | None:
    """Load the committed baseline audit transcripts.json (None if absent)."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _render_baseline_process(
    baseline: dict[str, Any] | None, transcripts: dict[str, Any] | None
) -> str:
    """Pipeline provenance block — which models / effort / seeds produced this baseline."""
    if not transcripts:
        return (
            '    <div class="namespace-block" id="ns-process">\n'
            "      <h3>process</h3>\n"
            '      <p class="empty-namespace">No <code>transcripts.json</code> next to this '
            "page. Run <code>uv run python scripts/extract_baseline_transcripts.py</code> "
            "after a baseline <code>--promote</code>.</p>\n"
            "    </div>"
        )
    rows: list[str] = []

    def add(key: str, value_html: str) -> None:
        rows.append(
            "          <tr>\n"
            f'            <td class="id"><code>{html_escape(key)}</code></td>\n'
            f"            <td>{value_html}</td>\n"
            "          </tr>"
        )

    for role in ("auditor", "target", "judge"):
        model = transcripts.get(f"{role}_model")
        add(role, harness_chip(model) if model else '<span class="muted">—</span>')
    add("reasoning effort", "<code>high</code> + <code>--reasoning-history all</code>")
    fitness = transcripts.get("fitness")
    if isinstance(fitness, (int, float)):
        add(
            "fitness (fresh anchor)",
            f'<span class="num">{float(fitness):.4f}</span> '
            '<span class="muted">intrinsic score; no prior base (substrate-fresh)</span>',
        )
    add(
        "seed pool",
        f'<span class="num">{transcripts.get("sample_count", 0)}</span> survivor scenarios',
    )
    promoted = (baseline or {}).get("promoted_at")
    if promoted:
        add("promoted_at", f"<code>{html_escape(str(promoted))}</code>")
    add("audit status", f"<code>{html_escape(str(transcripts.get('status', '—')))}</code>")
    add("eval log", f"<code>{html_escape(str(transcripts.get('eval_file', '—')))}</code>")
    return (
        '    <div class="namespace-block" id="ns-process">\n'
        "      <h3>process</h3>\n"
        '      <p class="namespace-meta">One Petri audit over the survivor pool drives the '
        "promoted baseline: the <em>auditor</em> red-teams the <em>target</em> across the seed "
        "scenarios; the <em>judge</em> scores 22 dimensions per scenario; the per-seed scores "
        "aggregate into the <code>raw.dim_means</code> below.</p>\n"
        '      <table class="records">\n'
        '        <thead><tr><th scope="col">field</th><th scope="col">value</th></tr></thead>\n'
        "        <tbody>\n" + "\n".join(rows) + "\n        </tbody>\n"
        "      </table>\n"
        "    </div>"
    )


def _render_baseline_seed_corpus(transcripts: dict[str, Any] | None) -> str:
    """The survivor seed scenarios fed into the baseline audit, each expandable."""
    samples = (transcripts or {}).get("samples") or []
    if not samples:
        return (
            '    <div class="namespace-block" id="ns-seeds">\n'
            "      <h3>seed corpus</h3>\n"
            '      <p class="empty-namespace">No seed scenarios in transcripts.json.</p>\n'
            "    </div>"
        )
    index_rows: list[str] = []
    details: list[str] = []
    for sample in samples:
        seed_id = str(sample.get("id", "?"))
        dims = sample.get("target_dims") or []
        dim_label = ", ".join(html_escape(str(d)) for d in dims) if dims else "—"
        name = str(sample.get("name") or seed_id)
        body = str(sample.get("seed_body") or "")
        index_rows.append(
            "          <tr>\n"
            f'            <td class="id"><a href="#seed-{html_escape(seed_id)}">'
            f"<code>{html_escape(seed_id)}</code></a></td>\n"
            f"            <td>{dim_label}</td>\n"
            f'            <td><span class="num">{len(body)}</span> chars</td>\n'
            "          </tr>"
        )
        details.append(
            f'      <details class="turn" id="seed-{html_escape(seed_id)}">\n'
            f"        <summary>{html_escape(name)} "
            f'<span class="bucket seedgen">{dim_label}</span></summary>\n'
            f'        <pre class="msg">{html_escape(body)}</pre>\n'
            "      </details>"
        )
    return (
        '    <div class="namespace-block" id="ns-seeds">\n'
        f'      <h3>seed corpus <span class="count">{len(samples)}</span></h3>\n'
        '      <p class="namespace-meta">Survivor scenarios from the seed-generation runs, '
        "fed to the auditor as <code>seed_instructions</code>.</p>\n"
        '      <table class="records">\n'
        '        <thead><tr><th scope="col">seed</th><th scope="col">target dim</th>'
        '<th scope="col">scenario size</th></tr></thead>\n'
        "        <tbody>\n" + "\n".join(index_rows) + "\n        </tbody>\n"
        "      </table>\n" + "\n".join(details) + "\n    </div>"
    )


def _render_baseline_score_table(scores: dict[str, Any]) -> str:
    """Per-seed judge scores (1-10), highest first. No colour: dim polarity varies."""
    if not scores:
        return '<p class="muted">No judge scores.</p>'
    ordered = sorted(
        scores.items(),
        key=lambda kv: (-float(kv[1]) if isinstance(kv[1], (int, float)) else 0.0, kv[0]),
    )
    rows = []
    for dim, score in ordered:
        score_html = (
            f'<span class="num">{score}</span>'
            if isinstance(score, (int, float))
            else html_escape(str(score))
        )
        rows.append(
            "            <tr>\n"
            f'              <td class="id"><code>{html_escape(str(dim))}</code></td>\n'
            f"              <td>{score_html}</td>\n"
            "            </tr>"
        )
    return (
        '        <table class="records">\n'
        '          <thead><tr><th scope="col">judge dimension</th>'
        '<th scope="col">score (1-10)</th></tr></thead>\n'
        "          <tbody>\n" + "\n".join(rows) + "\n          </tbody>\n"
        "        </table>"
    )


def _render_baseline_turns(turns: list[dict[str, Any]]) -> str:
    """Render the auditor↔target conversation, dropping ack/system noise."""
    out: list[str] = []
    seq = 0
    for turn in turns or []:
        speaker = str(turn.get("speaker", ""))
        if speaker not in _BASELINE_TURN_DISPLAY:
            continue  # tool_ack / system / unknown — conversational noise
        seq += 1
        css, label = _BASELINE_TURN_DISPLAY[speaker]
        parts: list[str] = []
        reasoning = str(turn.get("reasoning") or "")
        if reasoning:
            parts.append("⟨reasoning⟩\n" + reasoning)
        text = str(turn.get("text") or "")
        if text:
            parts.append(text)
        for call in turn.get("tool_calls") or []:
            tool = str(call.get("tool") or "")
            message = call.get("message")
            if message:
                parts.append(f"[{tool}] {message}")
            elif call.get("args"):
                parts.append(f"[{tool}] {json.dumps(call['args'], ensure_ascii=False)}")
            elif tool:
                parts.append(f"[{tool}]")
        body = "\n\n".join(p for p in parts if p) or "—"
        cls = f"turn {css}".strip()
        out.append(
            f'        <details class="{cls}"><summary>{html_escape(label)} '
            f'<span class="muted">turn {seq}</span></summary>\n'
            f'        <pre class="msg">{html_escape(body)}</pre></details>'
        )
    return "\n".join(out) if out else '<p class="muted">No conversation turns.</p>'


def _render_baseline_audit_transcripts(transcripts: dict[str, Any] | None) -> str:
    """Per-seed expandable audit: conversation + judge scores + judge rationale."""
    samples = (transcripts or {}).get("samples") or []
    if not samples:
        return (
            '    <div class="namespace-block" id="ns-transcripts">\n'
            "      <h3>audit transcripts</h3>\n"
            '      <p class="empty-namespace">No transcripts in transcripts.json.</p>\n'
            "    </div>"
        )
    blocks: list[str] = []
    for sample in samples:
        seed_id = str(sample.get("id", "?"))
        dims = sample.get("target_dims") or []
        dim_label = ", ".join(html_escape(str(d)) for d in dims) if dims else "—"
        turns = sample.get("turns") or []
        n_turns = sum(1 for t in turns if str(t.get("speaker")) in _BASELINE_TURN_DISPLAY)
        explanation = str(sample.get("judge_explanation") or "")
        explanation_html = (
            '        <details class="turn"><summary>judge rationale</summary>\n'
            f'        <pre class="msg">{html_escape(explanation)}</pre></details>\n'
            if explanation
            else ""
        )
        blocks.append(
            f'      <details class="turn" id="audit-{html_escape(seed_id)}">\n'
            f"        <summary><code>{html_escape(seed_id)}</code> "
            f'<span class="bucket seedgen">{dim_label}</span> '
            f'<span class="muted">{n_turns} turns</span></summary>\n'
            f'        <div class="audit-conversation">\n{_render_baseline_turns(turns)}\n'
            "        </div>\n"
            f"{_render_baseline_score_table(sample.get('scores') or {})}\n"
            f"{explanation_html}"
            "      </details>"
        )
    return (
        '    <div class="namespace-block" id="ns-transcripts">\n'
        f'      <h3>audit transcripts <span class="count">{len(samples)}</span></h3>\n'
        '      <p class="namespace-meta">Each seed\'s auditor↔target conversation '
        "(reasoning + tool sends), the judge’s 22-dim scores, and the judge rationale. "
        "Tool acks and the static auditor role prompt are omitted.</p>\n"
        + "\n".join(blocks)
        + "\n    </div>"
    )


def _gen_timeline_rows(
    archive: list[dict[str, Any]],
    current_baseline: dict[str, Any] | None,
) -> str:
    """Render the legacy gen/mutation timeline rows newest-first, with Δfitness.

    PR-BASELINE-REGISTRY (2026-05-30) — the registry's ``kind="baseline"`` rows
    use a different schema (``id`` / ``margin_rule`` / models, no ``gen_tag``)
    and get their own dense index in a follow-up phase; skip them here so this
    legacy timeline does not render them with blank ids.
    """
    archive = [r for r in archive if r.get("kind") != _BASELINE_REGISTRY_ROW_KIND]
    if not archive:
        return (
            '        <tr><td colspan="5" class="empty">'
            "<em>No baseline_archive.jsonl rows yet.</em></td></tr>"
        )
    # Determine current gen_tag for `.active` highlight.
    current_gen = ""
    if isinstance(current_baseline, dict):
        meta = current_baseline.get("metadata") or {}
        if isinstance(meta, dict):
            current_gen = str(meta.get("gen_tag") or "")
    # Sort newest first by ts_utc, falling back to original order.
    enumerated = list(enumerate(archive))

    def _ts(entry: tuple[int, dict[str, Any]]) -> str:
        return str(entry[1].get("ts_utc") or "")

    sorted_rows = sorted(enumerated, key=_ts, reverse=True)
    out: list[str] = []
    for _, row in sorted_rows:
        gen_tag = str(row.get("gen_tag") or "")
        ts = short_iso(str(row.get("ts_utc") or ""))
        fitness_block = row.get("fitness")
        if isinstance(fitness_block, dict):
            fitness_val = fitness_block.get("value")
        else:
            fitness_val = fitness_block
        if isinstance(fitness_val, int | float):
            fitness_cell = f'<span class="num">{float(fitness_val):.4f}</span>'
            fitness_num: float | None = float(fitness_val)
        else:
            fitness_cell = '<span class="muted">—</span>'
            fitness_num = None
        # Compute Δ vs previous (older) row in archive order.
        delta_cell = '<span class="muted">—</span>'
        # Find this row's archive index, then look at idx-1 (older entry).
        # archive list is operator-appended chronologically per design.
        # NB: This is rendered after sort, so we recompute from original order.
        # Skipping detailed implementation — Δ vs the row immediately
        # *prior* in the archive's chronological order.
        archive_index = -1
        for i, candidate in enumerate(archive):
            if candidate is row:
                archive_index = i
                break
        if archive_index > 0 and fitness_num is not None:
            prev = archive[archive_index - 1]
            prev_fitness_block = prev.get("fitness")
            prev_val = (
                prev_fitness_block.get("value")
                if isinstance(prev_fitness_block, dict)
                else prev_fitness_block
            )
            if isinstance(prev_val, int | float):
                delta = fitness_num - float(prev_val)
                cls, sign = _delta_class(delta)
                delta_cell = f'<span class="{cls}">{sign}{abs(delta):.4f}</span>'
        target = ""
        mut = row.get("mutation")
        if isinstance(mut, dict):
            target = str(mut.get("target_section") or "")
        row_class = "gen-timeline-row"
        if current_gen and gen_tag == current_gen:
            row_class += " active"
        out.append(
            f'        <tr class="{row_class}">\n'
            f'          <td class="id"><code>{html_escape(gen_tag)}</code></td>\n'
            f'          <td class="muted">{html_escape(ts)}</td>\n'
            f"          <td>{fitness_cell}</td>\n"
            f"          <td>{delta_cell}</td>\n"
            f'          <td class="muted"><code>{html_escape(target)}</code></td>\n'
            "        </tr>"
        )
    return "\n".join(out)


_EPOCH_SPEC_ROLES = ("auditor", "target", "judge", "mutator")

#: Sentinel epoch id for rows written before the epoch schema (no ``epoch_hash``).
_PRE_EPOCH = "pre-epoch"


def _epoch_spec_summary(spec: dict[str, Any], role_prov: dict[str, Any]) -> str:
    """One dense line describing the production+measurement surface of an epoch.

    The surface is shared by every baseline in the epoch (that is what the hash
    partitions on), so it renders once per epoch rather than per row. Pulls the
    comparability fields from ``baseline_spec`` and the credential lane from the
    row's ``role_provenance`` (lane is derived from source, not hashed).
    """
    if not spec:
        return (
            "Predates the content-addressed epoch schema — not yet partitioned. "
            "Re-backfilled with epoch fields once the canonical fitness is settled."
        )
    margin = html_escape(str(spec.get("margin_rule") or "—"))
    # promote_policy (E3) — the control arm / version marker for the epoch:
    # gate (selection) / random / never, or "legacy" for a pre-arm baseline. It
    # is part of the hashed spec, so showing it makes the versioned lineage
    # readable (which arm/version each stacked epoch is).
    policy = html_escape(str(spec.get("promote_policy") or "—"))
    dim_set = html_escape(str(spec.get("dim_set") or "—"))
    rubric = html_escape(str(spec.get("rubric_version") or "—"))
    bench = "on" if spec.get("bench") else "off"
    pool = html_escape(str(spec.get("seed_pool_id") or "—"))
    role_bits: list[str] = []
    for role in _EPOCH_SPEC_ROLES:
        prov = role_prov.get(role) if isinstance(role_prov, dict) else None
        prov = prov if isinstance(prov, dict) else {}
        model = html_escape(str(prov.get("model") or "—"))
        lane = html_escape(str(prov.get("lane") or "—"))
        role_bits.append(f"{role} <code>{model}</code>&middot;{lane}")
    return (
        f"margin <code>{margin}</code> &middot; policy <code>{policy}</code> &middot; "
        f"dim_set <code>{dim_set}</code> &middot; rubric <code>{rubric}</code> &middot; "
        f"bench {bench} &middot; pool <code>{pool}</code><br>{' &middot; '.join(role_bits)}"
    )


def _render_baseline_registry_index(archive: list[dict[str, Any]]) -> str:
    """Render the ``kind="baseline"`` registry rows grouped by content-addressed
    epoch (PR-BASELINE-EPOCH).

    Each epoch is a sub-series (like a ``gen-*`` seed-generation run): the
    ``epoch_label`` (be-NNN) + short hash as the heading, a one-line spec summary,
    then a dense table of that epoch's baselines. Epochs are NEVER merged into one
    comparison table — they were produced under different logic and are not
    comparable (that is the whole point of the partition). Epochs are ordered
    newest-first by their most-recent baseline; rows within an epoch likewise.
    """
    rows = [r for r in archive if r.get("kind") == _BASELINE_REGISTRY_ROW_KIND]
    if not rows:
        return (
            '    <p class="empty-namespace">No <code>kind="baseline"</code> registry rows yet. '
            "A row is appended on every promote (<code>core/self_improving/train.py</code>).</p>"
        )
    # Group by epoch_hash, preserving each epoch's label + spec from its first row.
    # Rows written before the epoch schema (no epoch_hash) bucket under a single
    # honest "pre-epoch" group rather than a fabricated hash — they are
    # re-backfilled once the epoch fields are computable (see E1 fitness reconcile).
    epochs: dict[str, dict[str, Any]] = {}
    for row in rows:
        eh = str(row.get("epoch_hash") or _PRE_EPOCH)
        spec = row.get("baseline_spec")
        prov = row.get("role_provenance")
        default_label = "pre-epoch (backfill pending)" if eh == _PRE_EPOCH else eh[:12]
        bucket = epochs.setdefault(
            eh,
            {
                "label": str(row.get("epoch_label") or default_label),
                "spec": spec if isinstance(spec, dict) else {},
                "role_prov": prov if isinstance(prov, dict) else {},
                "rows": [],
            },
        )
        bucket["rows"].append(row)

    def _max_ts(bucket: dict[str, Any]) -> str:
        return max((str(r.get("ts_utc") or "") for r in bucket["rows"]), default="")

    # Real epochs first (newest-first by their most-recent baseline); the
    # pre-epoch bucket always sorts last regardless of its rows' timestamps.
    def _sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, str]:
        eh, bucket = item
        return (0 if eh == _PRE_EPOCH else 1, _max_ts(bucket))

    blocks: list[str] = []
    for eh, bucket in sorted(epochs.items(), key=_sort_key, reverse=True):
        epoch_rows = sorted(bucket["rows"], key=lambda r: str(r.get("ts_utc") or ""), reverse=True)
        body: list[str] = []
        for row in epoch_rows:
            fitness = row.get("fitness")
            fit_cell = (
                f'<span class="num">{float(fitness):.4f}</span>'
                if isinstance(fitness, int | float)
                else '<span class="muted">—</span>'
            )
            stderr = row.get("fitness_stderr")
            stderr_cell = (
                f'<span class="num">{float(stderr):.4f}</span>'
                if isinstance(stderr, int | float)
                else '<span class="muted">—</span>'
            )
            row_id = html_escape(str(row.get("id") or "—"))
            row_ts = html_escape(short_iso(str(row.get("ts_utc") or "")))
            promoted = html_escape(str(row.get("promoted_by") or "—"))
            body.append(
                "        <tr>\n"
                f'          <td class="id"><code>{row_id}</code></td>\n'
                f'          <td class="muted">{row_ts}</td>\n'
                f"          <td>{fit_cell}</td>\n"
                f"          <td>{stderr_cell}</td>\n"
                f'          <td class="muted">{promoted}</td>\n'
                "        </tr>"
            )
        count = len(epoch_rows)
        label = html_escape(str(bucket["label"]))
        summary = _epoch_spec_summary(bucket["spec"], bucket["role_prov"])
        plural = "s" if count != 1 else ""
        # The raw hash is shown only for real epochs (pre-epoch has none).
        hash_cell = ""
        if eh != _PRE_EPOCH:
            hash_cell = f' <code class="muted">{html_escape(eh[:12])}</code>'
        blocks.append(
            '    <div class="namespace-block">\n'
            f"      <h3>{label} "
            f'<span class="count">{count} baseline{plural}</span>{hash_cell}</h3>\n'
            f'      <p class="namespace-meta">{summary}</p>\n'
            '      <table class="records">\n'
            "        <thead><tr>"
            '<th scope="col">baseline-id</th><th scope="col">ts</th>'
            '<th scope="col">fitness</th><th scope="col">fitness_stderr</th>'
            '<th scope="col">promoted by</th></tr></thead>\n'
            "        <tbody>\n" + "\n".join(body) + "\n        </tbody>\n"
            "      </table>\n"
            "    </div>"
        )
    return "\n".join(blocks)


def _delta_class(delta: float) -> tuple[str, str]:
    """Map a Δfitness value to a CSS class + sign char."""
    if delta > 0.005:
        return ("delta-positive", "+")
    if delta < -0.005:
        return ("delta-negative", "-")
    return ("delta-noise", "±")


def _is_pre_e1_mixed_scale(attr: dict[str, Any] | None) -> bool:
    """True when an attribution row predates PR-MARGIN-FITNESS-SCALE E1 (mixed scale).

    E1 (2026-05-30) reconciled per-mutation ``fitness_before`` / ``fitness_delta``
    to the canonical 0-1 ``compute_fitness`` scale. The 8 rows already committed to
    ``state/autoresearch/mutations.jsonl`` still carry the OLD dim-aggregate scale
    (``fitness_before`` was the 1-10 ``dim_means`` mean, so it sits ≈ 1.73-2.29 and
    ``fitness_delta`` ≈ -1.1 to -1.76 — both meaningless against a 0-1 row). The
    git-tracked ledger is intentionally NOT rewritten (a one-shot historical
    backfill is a separate, out-of-scope follow-up), so the hub fixes the scale
    mismatch on the DISPLAY side.

    Robust heuristic — ``fitness_before > 1.0``: post-E1 fitness is bounded to 0-1,
    so any ``fitness_before`` above 1.0 can only be the old dim-mean scale; a new row
    never exceeds 1.0. Graceful contract: a missing / non-numeric ``fitness_before``
    (no attr yet, or malformed) is treated as NOT mixed — it simply is not a row we
    can prove to be on the old scale, so it falls through to normal handling. ``bool``
    is excluded explicitly (``isinstance(True, int)`` is True in Python) so a
    malformed ``fitness_before: true`` is not mistaken for a numeric ``1.0``.
    """
    if attr is None:
        return False
    before = attr.get("fitness_before")
    if isinstance(before, bool) or not isinstance(before, int | float):
        return False
    return float(before) > 1.0


# Codex M2 — the PR-GATE-RECIPE (#1947, v0.99.106) merge boundary. Before that merge
# the attribution ledger wrote ``fitness_after`` / ``fitness_delta`` with the PENALIZED
# ``compute_fitness`` (``baseline_means`` → auxiliary-shortfall penalty / critical
# strict-reject); at/after it both are the gate's PLAIN ``current_raw`` recipe. The two
# recipes are NOT comparable, so the hub must never blend a pre-boundary (penalized)
# row into the same mean-delta aggregate as a post-boundary (plain) row. There is no
# per-row recipe marker yet, so this ts-boundary is the discriminator — the merge time
# of #1947 (commit 2aa3b9a0, 2026-05-31T21:05:49Z UTC = epoch 1780261549). A per-row
# ``fitness_recipe`` marker on the attribution row is the robust long-term replacement
# for this heuristic.
_GATE_RECIPE_BOUNDARY_TS = 1780261549.0  # 2026-05-31T21:05:49Z UTC, #1947 merge (2aa3b9a0)


def _is_pre_gate_recipe_penalized(attr: dict[str, Any] | None) -> bool:
    """True when an attribution row predates PR-GATE-RECIPE (#1947) — penalized recipe.

    Pre-#1947 rows carry the PENALIZED ``fitness_after`` / ``fitness_delta`` (computed
    with ``baseline_means``), while post-#1947 rows carry the gate's PLAIN
    ``current_raw`` recipe. Both sit on the 0-1 scale (so :func:`_is_pre_e1_mixed_scale`
    does NOT catch them — that guard only fires on the old > 1.0 dim-mean scale), but
    they are produced by DIFFERENT fitness recipes, so a penalized delta must not be
    averaged into a plain-recipe mean. Until a per-row ``fitness_recipe`` marker exists
    (the robust long-term replacement), the discriminator is the #1947 merge timestamp:
    a row whose ``ts`` is before :data:`_GATE_RECIPE_BOUNDARY_TS` is penalized-recipe
    (legacy). Graceful contract: a missing / non-numeric ``ts`` (or ``bool``, since
    ``isinstance(True, int)`` is True) is treated as NOT pre-boundary — it cannot be
    proven legacy, so it falls through to normal plain-recipe handling.
    """
    if attr is None:
        return False
    ts = attr.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, int | float):
        return False
    return float(ts) < _GATE_RECIPE_BOUNDARY_TS


def _autoresearch_status_grid(
    baseline: dict[str, Any] | None,
    baseline_path: Path | None,
    mutations_count: int,
    mutations_mtime: str,
    results_count: int,
    results_mtime: str,
    policies_count: int,
    policies_mtime: str,
) -> str:
    """Render the landing-page <dl class="status-grid"> block."""
    if baseline is None:
        rows = [
            ("current baseline", "<em>no baseline yet</em>"),
            (
                "next action",
                "<code>uv run python -m core.self_improving.train --promote</code>",
            ),
        ]
    else:
        meta = baseline.get("metadata") or {}
        fitness_block = baseline.get("fitness") or {}
        audit_block = baseline.get("audit") or {}
        promotion = baseline.get("promotion") or {}
        gen_tag = (
            str(meta.get("gen_tag")) if isinstance(meta, dict) and meta.get("gen_tag") else "—"
        )
        fitness_val: Any = None
        if isinstance(fitness_block, dict):
            fitness_val = fitness_block.get("value")
        fitness_str = f"{float(fitness_val):.4f}" if isinstance(fitness_val, int | float) else "—"
        promote_ts = ""
        if isinstance(promotion, dict):
            promote_ts = str(promotion.get("timestamp") or "")
        rows = [
            ("current baseline", f"<code>{html_escape(gen_tag)}</code>"),
            ("fitness", f'<span class="num">{html_escape(fitness_str)}</span>'),
            (
                "last promote",
                f'<span class="muted">{html_escape(short_iso(promote_ts) or "—")}</span>',
            ),
        ]
        if isinstance(audit_block, dict):
            for label, key in (
                ("auditor", "auditor_model"),
                ("target", "target_model"),
                ("judge", "judge_model"),
            ):
                model = audit_block.get(key)
                if isinstance(model, str) and model:
                    rows.append((f"{label} model", harness_chip(model)))
    # Always-present footer rows.
    muted_mut = f"<span class='muted'>{html_escape(mutations_mtime)}</span>"
    muted_res = f"<span class='muted'>{html_escape(results_mtime)}</span>"
    muted_pol = f"<span class='muted'>{html_escape(policies_mtime)}</span>"
    rows.extend(
        [
            ("mutations.jsonl", f"{mutations_count} rows &middot; {muted_mut}"),
            ("results.tsv", f"{results_count} rows &middot; {muted_res}"),
            ("policies/", f"{policies_count} files &middot; {muted_pol}"),
        ]
    )
    if baseline_path is not None:
        rows.append(("source", f"<code>{html_escape(baseline_path.name)}</code>"))
    out: list[str] = []
    for label, value in rows:
        out.append(f"      <dt>{html_escape(label)}</dt><dd>{value}</dd>")
    return "\n".join(out)


def _autoresearch_subview_rows(
    archive_count: int,
    mutations_count: int,
    results_count: int,
    policies_count: int,
    *,
    mutations_mtime: str,
    results_mtime: str,
    policies_mtime: str,
    baseline_mtime: str,
    held_out_count: int,
) -> str:
    """Render the 5-row sub-view table on the landing page.

    ``held_out_count`` is the number of per-cycle held-out points recorded so far
    (the evidence page's synthesis input); a 0 reads as "awaiting" on that row,
    matching the page's graceful empty state.
    """
    rows = [
        (
            "Baseline",
            "1 (current promoted) &middot; "
            f"<span class='muted'>archive: {archive_count} rows</span>",
            baseline_mtime,
            "/geode/self-improving/autoresearch/baseline/",
        ),
        (
            "Mutations",
            f"{mutations_count} rows",
            mutations_mtime,
            "/geode/self-improving/autoresearch/mutations/",
        ),
        (
            "Results",
            f"{results_count} rows",
            results_mtime,
            "/geode/self-improving/autoresearch/results/",
        ),
        (
            "Evidence",
            (
                f"{held_out_count} held-out points"
                if held_out_count
                else "<span class='muted'>awaiting campaign</span>"
            ),
            mutations_mtime,
            "/geode/self-improving/autoresearch/evidence/",
        ),
        (
            "Policies",
            f"{policies_count} files",
            policies_mtime,
            "/geode/self-improving/autoresearch/policies/",
        ),
    ]
    out: list[str] = []
    for label, count_cell, mtime_cell, href in rows:
        out.append(
            "        <tr>\n"
            f'          <td class="id"><a href="{href}">{html_escape(label)}</a> '
            '<span class="bucket autoresearch">autoresearch</span></td>\n'
            f"          <td>{count_cell}</td>\n"
            f'          <td class="muted">{html_escape(mtime_cell)}</td>\n'
            f'          <td class="id"><a href="{href}">open &rarr;</a></td>\n'
            "        </tr>"
        )
    return "\n".join(out)


_MUTATIONS_COLSPAN = 6


def _join_mutation_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join the two ``mutations.jsonl`` row kinds by ``mutation_id``.

    The self-improving-loop runner appends an APPLY record
    (``target_kind`` / ``target_section`` / ``previous_value`` →
    ``new_value`` / ``rationale`` / ``principle`` / ``target_dim`` /
    ``expected_dim``) when a mutation is applied, then a *separate*
    ATTRIBUTION record (``fitness_before`` / ``fitness_after`` /
    ``fitness_delta`` / ``attribution_score`` / ``significant`` /
    ``observed_dim`` / ``ci95``) once the post-mutation audit completes.
    They share ``mutation_id``.

    SCALE CONTRACT (PR-MARGIN-FITNESS-SCALE E1, 2026-05-30) —
    ``fitness_before`` / ``fitness_after`` / ``fitness_delta`` are all on the
    canonical 0-1 ``compute_fitness`` scale (HIGHER-is-better), so a positive
    ``fitness_delta`` is an improvement and the ±0.005 noise floor in
    :func:`_delta_class` is a fitness-scale epsilon (matching the promote
    gate's ``fitness_margin_floor``). NOTE — pre-E1 rows on disk carry a mixed
    scale (``fitness_before`` was the 1-10 ``dim_means`` aggregate, so
    ``fitness_delta`` for those rows is meaningless, often ≈ -1.7). The ledger is
    intentionally NOT rewritten (a one-shot backfill of historical rows is a
    documented, out-of-scope follow-up); instead :func:`_is_pre_e1_mixed_scale`
    detects them on the DISPLAY side so the per-row renderer tags them and the
    summary aggregate excludes them — see :func:`_render_mutations_summary`.

    RECIPE CONTRACT (PR-GATE-RECIPE #1947, 2026-05-31, Codex M2) — within the 0-1
    scale there are still TWO fitness recipes: rows written before #1947 carry the
    PENALIZED ``fitness_after`` / ``fitness_delta`` (``baseline_means`` penalty),
    rows at/after carry the gate's PLAIN ``current_raw`` recipe. The two are not
    comparable, so :func:`_is_pre_gate_recipe_penalized` detects pre-#1947 rows (by
    the merge-timestamp boundary, until a per-row ``fitness_recipe`` marker exists)
    and keeps them out of the plain-recipe mean-delta — same DISPLAY-side discipline.

    Returns one dict per mutation —
    ``{"id", "apply", "attr"}`` (``attr`` is ``None`` until the
    attribution record lands) — newest applied first.

    The legacy renderer keyed off a nested ``ts_utc`` / ``mutation`` /
    ``mutator`` / ``verdict`` schema that the runner no longer emits, so
    every column rendered empty against production data. This join reads
    the live flat schema instead.
    """
    apply_by_id: dict[str, dict[str, Any]] = {}
    attr_by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        mutation_id = str(row.get("mutation_id") or "")
        if not mutation_id:
            continue
        if "fitness_delta" in row:
            attr_by_id[mutation_id] = row
        elif "target_section" in row:
            apply_by_id[mutation_id] = row
    merged: list[dict[str, Any]] = []
    for mutation_id, apply_row in apply_by_id.items():
        merged.append({"id": mutation_id, "apply": apply_row, "attr": attr_by_id.get(mutation_id)})
    # Attribution-only records (no matching apply row) — surface them too
    # so nothing in the ledger is silently dropped.
    for mutation_id, attr_row in attr_by_id.items():
        if mutation_id not in apply_by_id:
            merged.append({"id": mutation_id, "apply": None, "attr": attr_row})

    def _sort_ts(entry: dict[str, Any]) -> float:
        anchor = entry["apply"] or entry["attr"] or {}
        try:
            return float(anchor.get("ts") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    merged.sort(key=_sort_ts, reverse=True)
    return merged


def _fmt_epoch(ts: Any) -> str:
    """Format a float/epoch ``ts`` as ``YYYY-MM-DD HH:MM`` UTC; ``—`` on bad input."""
    try:
        return _dt.datetime.fromtimestamp(float(ts), tz=_dt.UTC).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return "—"


def _mutation_outcome(attr: dict[str, Any] | None) -> tuple[str, str]:
    """Map a mutation's attribution row to ``(label, css_class)``.

    ``fitness_delta`` is the 0-1 ``compute_fitness`` scale (HIGHER-is-better),
    so a positive delta past the ±0.005 fitness-scale noise floor is an
    improvement. ``None`` attr = audit not yet run. Pre-PR-MARGIN-FITNESS-SCALE-E1
    rows carry a mixed-scale ``fitness_delta`` (see :func:`_is_pre_e1_mixed_scale`)
    and classify as ``pre-E1`` so they are EXCLUDED from the improved/regressed/
    noise tallies instead of polluting them with an old-scale ≈ -1.7 delta.
    """
    if attr is None:
        return ("pending", "muted")
    if _is_pre_e1_mixed_scale(attr):
        return ("pre-E1", "muted")
    # Codex M2 — a pre-#1947 (penalized-recipe) row's delta is on a different fitness
    # recipe than the post-#1947 plain rows, so it is tagged distinctly and excluded
    # from the improved/regressed/noise tallies rather than blended in.
    if _is_pre_gate_recipe_penalized(attr):
        return ("penalized-recipe", "muted")
    delta = attr.get("fitness_delta")
    if not isinstance(delta, int | float):
        return ("pending", "muted")
    cls, _ = _delta_class(float(delta))
    return ({"delta-positive": "improved", "delta-negative": "regressed"}.get(cls, "noise"), cls)


def _render_mutation_payload(entry: dict[str, Any]) -> str:
    """``<details>`` drill-down for one mutation — the full apply + attribution payload.

    Emitted as its own full-width ``<tr><td colspan>`` row (see
    :func:`_render_mutations_rows`), NOT inside the narrow outcome cell — so the
    expanded ``status-grid`` + before/after ``pre`` blocks break out to the full
    table width instead of being squeezed right. The wrapping ``div.mutation-payload``
    is the full-width container the CSS targets.
    """
    apply_row = entry["apply"] or {}
    attr_row = entry["attr"] or {}
    rows: list[str] = [f"<dt>mutation_id</dt><dd><code>{html_escape(entry['id'])}</code></dd>"]

    def _field(label: str, value: Any) -> None:
        if value not in (None, "", [], {}):
            rows.append(f"<dt>{html_escape(label)}</dt><dd>{html_escape(str(value))}</dd>")

    _field("rationale", apply_row.get("rationale"))
    _field("principle", apply_row.get("principle"))
    _field("rollback_condition", apply_row.get("rollback_condition"))
    audit_id = apply_row.get("audit_run_id") or attr_row.get("audit_run_id")
    if audit_id:
        rows.append(f"<dt>audit_run_id</dt><dd><code>{html_escape(str(audit_id))}</code></dd>")
    score = attr_row.get("attribution_score")
    if isinstance(score, int | float):
        rows.append(f"<dt>attribution_score</dt><dd>{float(score):+.3f}</dd>")
    grid = f'<dl class="status-grid">{"".join(rows)}</dl>'

    diff = ""
    prev = apply_row.get("previous_value")
    new = apply_row.get("new_value")
    if prev or new:
        diff = (
            '<p class="muted">previous</p>'
            f'<pre class="msg">{html_escape(str(prev or "—"))}</pre>'
            '<p class="muted">new</p>'
            f'<pre class="msg">{html_escape(str(new or "—"))}</pre>'
        )
    return (
        '<details><summary class="muted">payload</summary>'
        f'<div class="mutation-payload">{grid}{diff}</div></details>'
    )


def _render_mutations_rows(joined: list[dict[str, Any]]) -> str:
    """Render one table row per joined mutation, newest applied first."""
    if not joined:
        return (
            f'        <tr><td colspan="{_MUTATIONS_COLSPAN}" class="empty">'
            "<em>No mutations recorded. Run "
            "<code>uv run python -m core.self_improving.train</code>."
            "</em></td></tr>"
        )
    out: list[str] = []
    for entry in joined:
        apply_row = entry["apply"] or {}
        attr_row = entry["attr"]
        ts_cell = _fmt_epoch(apply_row.get("ts") if apply_row else (attr_row or {}).get("ts"))
        target_kind = str(apply_row.get("target_kind") or "—")
        target_section = str(apply_row.get("target_section") or "—")
        target_dim = str(apply_row.get("target_dim") or "")

        # Aimed dim + its measured move (with a significance chip).
        if target_dim:
            dim_cell = f"<code>{html_escape(target_dim)}</code>"
            observed = (attr_row or {}).get("observed_dim")
            if isinstance(observed, dict) and isinstance(observed.get(target_dim), int | float):
                dim_cell += f' <span class="muted">{float(observed[target_dim]):+.2f}</span>'
            significant = (attr_row or {}).get("significant")
            if isinstance(significant, dict) and significant.get(target_dim):
                dim_cell += ' <span class="bucket seedgen">sig</span>'
        else:
            dim_cell = '<span class="muted">—</span>'

        # Δfitness — before → after + signed delta. Pre-E1 mixed-scale rows show a
        # "pre-E1 (mixed scale)" tag instead of a bogus old-scale delta; they are
        # also dropped from the summary aggregate (see _render_mutations_summary).
        # Codex M2 — pre-#1947 (penalized-recipe) rows likewise show a distinct tag
        # rather than a plain-recipe delta, and are excluded from the mean-delta.
        if _is_pre_e1_mixed_scale(attr_row):
            fit_cell = '<span class="muted">pre-E1 (mixed scale)</span>'
        elif _is_pre_gate_recipe_penalized(attr_row):
            fit_cell = '<span class="muted">penalized recipe (pre-#1947)</span>'
        elif attr_row and isinstance(attr_row.get("fitness_delta"), int | float):
            delta = float(attr_row["fitness_delta"])
            cls, sign = _delta_class(delta)
            before = attr_row.get("fitness_before")
            after = attr_row.get("fitness_after")
            ba = ""
            if isinstance(before, int | float) and isinstance(after, int | float):
                ba = f'<span class="muted">{float(before):.3f} → {float(after):.3f}</span> '
            fit_cell = f'{ba}<span class="{cls}">{sign}{abs(delta):.4f}</span>'
        else:
            fit_cell = '<span class="muted">pending audit</span>'

        score = (attr_row or {}).get("attribution_score")
        attr_cell = (
            f'<span class="num">{float(score):+.2f}</span>'
            if isinstance(score, int | float)
            else '<span class="muted">—</span>'
        )

        label, outcome_cls = _mutation_outcome(attr_row)
        outcome_cell = f'<span class="{outcome_cls}">{label}</span>'

        # The expandable payload lives in its OWN full-width row (colspan), not in
        # the narrow outcome cell — otherwise the opened <details> is squeezed into
        # the last column and renders right-skewed. Same pattern as the policies /
        # results JSON drill-downs (see _render_policies_rows).
        payload_row = (
            '\n        <tr class="mutation-payload-row">\n'
            f'          <td colspan="{_MUTATIONS_COLSPAN}">{_render_mutation_payload(entry)}</td>\n'
            "        </tr>"
        )

        out.append(
            "        <tr>\n"
            f'          <td class="muted">{html_escape(ts_cell)}</td>\n'
            f"          <td><code>{html_escape(target_kind)}</code> &middot; "
            f"{html_escape(target_section)}</td>\n"
            f"          <td>{dim_cell}</td>\n"
            f"          <td>{fit_cell}</td>\n"
            f'          <td class="num">{attr_cell}</td>\n'
            f"          <td>{outcome_cell}</td>\n"
            "        </tr>" + payload_row
        )
    return "\n".join(out)


def _render_mutations_summary(joined: list[dict[str, Any]]) -> str:
    """Aggregate stat block (replaces the non-functional filter mockup)."""
    if not joined:
        return ""
    total = len(joined)
    improved = regressed = noise = pending = pre_e1 = penalized = 0
    # Only 0-1 ``compute_fitness``-scale deltas on the SAME fitness recipe enter the
    # mean. Two row classes are excluded from both the aggregate and the
    # improved/regressed/noise tallies:
    #   (1) Pre-E1 rows (``fitness_before`` > 1.0, old 1-10 dim-mean scale) would skew
    #       the mean toward an ≈ -1.7 garbage value — see :func:`_is_pre_e1_mixed_scale`.
    #   (2) Codex M2 — pre-#1947 (penalized-recipe) rows carry the PENALIZED
    #       ``fitness_delta`` (``baseline_means`` penalty), a DIFFERENT recipe from the
    #       post-#1947 plain ``current_raw`` rows; blending the two into one mean would
    #       mix scales — see :func:`_is_pre_gate_recipe_penalized`. (A per-row
    #       ``fitness_recipe`` marker is the robust long-term replacement for the
    #       ts-boundary heuristic.)
    # An all-excluded input therefore yields an empty `deltas` list → mean of 0.0 with
    # n=0, not a bogus blended average.
    deltas: list[float] = []
    kinds: dict[str, int] = {}
    dims: set[str] = set()
    for entry in joined:
        apply_row = entry["apply"] or {}
        kind = str(apply_row.get("target_kind") or "?")
        kinds[kind] = kinds.get(kind, 0) + 1
        if apply_row.get("target_dim"):
            dims.add(str(apply_row["target_dim"]))
        attr_row = entry["attr"]
        label, _ = _mutation_outcome(attr_row)
        if label == "improved":
            improved += 1
        elif label == "regressed":
            regressed += 1
        elif label == "noise":
            noise += 1
        elif label == "pre-E1":
            pre_e1 += 1
        elif label == "penalized-recipe":
            penalized += 1
        else:
            pending += 1
        # Mixed-scale (pre-E1) AND mixed-recipe (pre-#1947 penalized) rows are both
        # kept out of the plain-recipe mean-delta.
        if _is_pre_e1_mixed_scale(attr_row) or _is_pre_gate_recipe_penalized(attr_row):
            continue
        delta = (attr_row or {}).get("fitness_delta")
        if isinstance(delta, int | float):
            deltas.append(float(delta))
    mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
    kinds_str = " &middot; ".join(f"{html_escape(k)} {v}" for k, v in sorted(kinds.items()))
    dims_str = ", ".join(html_escape(d) for d in sorted(dims)) or "—"
    pre_e1_cell = (
        f' &middot; <span class="muted">{pre_e1} pre-E1 (mixed scale, excluded)</span>'
        if pre_e1
        else ""
    )
    penalized_cell = (
        f' &middot; <span class="muted">{penalized} penalized recipe (pre-#1947, excluded)</span>'
        if penalized
        else ""
    )
    return (
        '    <section class="page-sub"><dl class="status-grid">\n'
        f"      <dt>mutations</dt><dd>{total}</dd>\n"
        "      <dt>outcome</dt><dd>"
        f'<span class="delta-positive">{improved} improved</span> &middot; '
        f'<span class="delta-negative">{regressed} regressed</span> &middot; '
        f'<span class="delta-noise">{noise} noise</span> &middot; '
        f'<span class="muted">{pending} pending audit</span>{pre_e1_cell}'
        f"{penalized_cell}</dd>\n"
        f"      <dt>mean &Delta;fitness</dt><dd>{mean_delta:+.4f} "
        f'<span class="muted">(n={len(deltas)}, 0-1 plain-recipe rows only)</span></dd>\n'
        f"      <dt>target kinds</dt><dd>{kinds_str}</dd>\n"
        f"      <dt>aimed dims</dt><dd>{dims_str}</dd>\n"
        "    </dl></section>"
    )


def _collect_held_out_curve(mutations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pull the per-cycle held-out fitness points from the attribution rows (E2).

    Reads ``kind="attribution"`` rows that carry ``held_out_fitness`` — the
    fixed-ruler measurement recorded EVERY cycle when a held-out bench is
    configured (``core/self_improving/train.py`` E2-wire). Rows without the field
    (no-bench / legacy) are skipped. Points are ordered by ``ts`` ascending so the
    list reads chronologically — generation 1 first — which is how a
    fitness-vs-generation curve is read.

    Graceful contract: every schema-typed cast is guarded. A row whose ``ts`` or
    ``held_out_fitness`` is non-numeric is skipped (it cannot place a point on the
    curve) rather than raising — a malformed row never sinks the whole render.
    Returns ``[{ts, held_out_fitness, held_out_bench_id, mutation_id}]``.
    """
    points: list[dict[str, Any]] = []
    for row in mutations:
        if not isinstance(row, dict) or row.get("kind") != "attribution":
            continue
        raw_fitness = row.get("held_out_fitness")
        if raw_fitness is None:
            continue
        try:
            held_out_fitness = float(raw_fitness)
        except (TypeError, ValueError):
            continue
        raw_ts = row.get("ts")
        # Graceful at the cast boundary: a missing / non-numeric ts is SKIPPED, not
        # defaulted. The curve is ordered by ts and its Δ-vs-prior column depends on
        # that order, so a point with no valid position would mis-place itself (and
        # corrupt two deltas). A row with no positionable ts cannot be a curve point.
        if not isinstance(raw_ts, int | float) or isinstance(raw_ts, bool):
            continue
        ts_value = float(raw_ts)
        points.append(
            {
                "ts": ts_value,
                "held_out_fitness": held_out_fitness,
                "held_out_bench_id": str(row.get("held_out_bench_id") or "—"),
                "mutation_id": str(row.get("mutation_id") or "—"),
            }
        )
    points.sort(key=lambda point: point["ts"])
    return points


def _render_held_out_curve(mutations: list[dict[str, Any]]) -> str:
    """Render the per-cycle held-out (fixed-ruler) fitness curve as a dense table.

    The held-out bench is VERSION-FROZEN, so this fitness IS comparable across
    generations (unlike the co-evolving-pool ``fitness_after`` in the mutations
    table above). One row per cycle that scored the bench: generation index,
    timestamp, held-out fitness (0-1, HIGHER-is-better), its delta from the prior
    generation (a positive delta = improvement on the fixed ruler), and the
    bench's content-address. When no cycle has recorded a held-out point the
    section is omitted entirely (empty string) so a loop without a configured
    bench shows no empty scaffolding. Dense table only — no card grid, accent
    bar, or emoji.
    """
    points = _collect_held_out_curve(mutations)
    if not points:
        return ""
    bench_ids = sorted({point["held_out_bench_id"] for point in points})
    ruler_note = (
        f"fixed ruler <code>{html_escape(bench_ids[0])}</code>"
        if len(bench_ids) == 1
        else f"rulers changed across the run: {len(bench_ids)} distinct bench ids "
        "(a frozen bench was edited — the curve below is NOT fully comparable)"
    )
    rows: list[str] = []
    prior_fitness: float | None = None
    for index, point in enumerate(points, start=1):
        fitness = point["held_out_fitness"]
        if prior_fitness is None:
            delta_cell = '<td class="num muted">—</td>'
        else:
            delta = fitness - prior_fitness
            cls = "delta-positive" if delta > 0 else ("delta-negative" if delta < 0 else "muted")
            delta_cell = f'<td class="num {cls}">{delta:+.4f}</td>'
        prior_fitness = fitness
        bench_id_cell = html_escape(point["held_out_bench_id"])
        rows.append(
            "        <tr>\n"
            f'          <td class="num">{index}</td>\n'
            f'          <td class="muted">{html_escape(_fmt_epoch(point["ts"]))}</td>\n'
            f'          <td class="num">{fitness:.4f}</td>\n'
            f"          {delta_cell}\n"
            f'          <td class="muted"><code>{bench_id_cell}</code></td>\n'
            "        </tr>"
        )
    rows_html = "\n".join(rows)
    return (
        '    <h2 class="section"><span>Held-out fitness curve &middot; '
        f"{len(points)} generation" + ("s" if len(points) != 1 else "") + "</span></h2>\n"
        '    <p class="page-sub">Per-cycle fitness on the VERSION-FROZEN held-out bench '
        "(<code>held_out_fitness</code> in the attribution rows). Because the bench never "
        "mutates, these values ARE comparable across generations — the cross-generation "
        "evidence the co-evolving-pool &Delta;fitness above cannot give. Scored every cycle "
        f"a held-out bench is configured. {ruler_note}.</p>\n"
        '    <table class="records">\n'
        "      <thead>\n"
        "        <tr>\n"
        '          <th scope="col" class="num">gen</th>\n'
        '          <th scope="col">measured</th>\n'
        '          <th scope="col" class="num">held-out fitness</th>\n'
        '          <th scope="col" class="num">&Delta; vs prior</th>\n'
        '          <th scope="col">bench id</th>\n'
        "        </tr>\n"
        "      </thead>\n"
        "      <tbody>\n"
        f"{rows_html}\n"
        "      </tbody>\n"
        "    </table>"
    )


# --------------------------------------------------------------------------- #
# E6 (2026-05-30) — the honest evidence page (methods + results + power).      #
# Reads the recorded ledgers ONLY (mutations.jsonl attribution rows +          #
# baseline_archive.jsonl promoted rows). Measured values only — when a matched #
# 3-arm held-out campaign has not run yet, every section renders an honest     #
# "awaiting" state rather than a fabricated curve / placeholder number.        #
# --------------------------------------------------------------------------- #
def _required_n_seed(sigma: float | None) -> int | None:
    """Required N_seed per arm to detect ``_POWER_DEFAULT_TARGET_EFFECT_SIZE`` at
    ``_POWER_DEFAULT_POWER`` given the RECORDED combined fitness-stderr ``sigma``.

    Mirrors ``core.self_improving.loop.statistical_power.required_samples`` (the
    stdlib-only builder cannot import core): the textbook two-sample mean-difference
    sample size ``n ≈ 2·(z_{α/2}+z_β)²·σ²/δ²`` per arm, rounded UP. Computed from the
    σ actually recorded on the E4 rows — NOT a fabricated number — so the page never
    invents an N.

    Graceful contract: ``sigma is None`` (no variance observed yet), a non-finite /
    negative σ, or δ ≤ 0 yields ``None`` (the caller renders "indeterminate" rather
    than crashing). σ == 0 (perfectly stable) yields 1 (a single sample detects any
    δ > 0 when there is no noise) — identical to the writer's contract.
    """
    if sigma is None:
        return None
    try:
        sigma_value = float(sigma)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(sigma_value) or sigma_value < 0.0:
        return None
    delta = _POWER_DEFAULT_TARGET_EFFECT_SIZE
    if delta <= 0.0:
        return None
    if sigma_value == 0.0:
        return 1
    z_alpha = NormalDist().inv_cdf(1.0 - _POWER_DEFAULT_ALPHA / 2.0)
    z_beta = NormalDist().inv_cdf(_POWER_DEFAULT_POWER)
    raw_n = 2.0 * (z_alpha + z_beta) ** 2 * (sigma_value**2) / (delta**2)
    truncated = int(raw_n)
    n_seed = truncated if truncated == raw_n else truncated + 1
    return max(1, n_seed)


def _held_out_attribution_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attribution rows carrying a numeric ``held_out_fitness``, ordered by ts.

    Graceful at every cast: a non-numeric ``held_out_fitness`` / ``ts`` is skipped
    (it cannot place a positionable curve point) rather than raising. ``promote_policy``
    defaults to ``"gate"`` when the row predates E3 (legacy rows are the selection arm).
    """
    points: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("kind") != "attribution":
            continue
        raw_fitness = row.get("held_out_fitness")
        if raw_fitness is None:
            continue
        try:
            fitness = float(raw_fitness)
        except (TypeError, ValueError):
            continue
        raw_ts = row.get("ts")
        if not isinstance(raw_ts, int | float) or isinstance(raw_ts, bool):
            continue
        arm = row.get("promote_policy")
        arm_tagged = isinstance(arm, str) and bool(arm)
        points.append(
            {
                "ts": float(raw_ts),
                "held_out_fitness": fitness,
                "held_out_bench_id": str(row.get("held_out_bench_id") or "—"),
                # A pre-E3 row has no promote_policy. ``arm`` carries the display label
                # (``"untagged"`` so it is never confused with a real arm) and
                # ``arm_tagged`` records whether the row genuinely declared an arm — the
                # results renderer keeps untagged rows OUT of the gate arm so a
                # pre-experiment cycle never masquerades as matched-campaign evidence.
                "arm": str(arm) if arm_tagged else "untagged",
                "arm_tagged": arm_tagged,
            }
        )
    points.sort(key=lambda point: point["ts"])
    return points


def _evidence_gain_verdicts(
    mutations: list[dict[str, Any]],
    archive: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collect the recorded ci-excludes-0 gain verdicts from both ledgers.

    Reads ``gain_ci_excludes_zero`` / ``gain_verdict`` / ``gain_ci_low`` /
    ``gain_ci_high`` from the attribution rows (per-cycle, numeric ``ts`` epoch) and
    the ``kind="baseline"`` archive rows (per-campaign promote, ISO-string ``ts_utc``).
    The two ledgers carry DIFFERENT timestamp shapes, so each is formatted with its
    own formatter (``_fmt_epoch`` for the numeric cycle ts, ``short_iso`` for the
    archive ISO string) — a previous version floated both and dropped the archive ts.
    A row with no recorded verdict (``gain_ci_excludes_zero`` not a bool) contributes
    nothing. Graceful at every cast: a non-numeric CI bound renders "—", never raises.
    """
    out: list[dict[str, Any]] = []

    def _maybe_float(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _scan(source_rows: list[dict[str, Any]], source: str, ts_label: str) -> None:
        for row in source_rows:
            excludes = row.get("gain_ci_excludes_zero")
            if not isinstance(excludes, bool):
                continue
            raw_ts = row.get(ts_label)
            ts_display = "—"
            if (
                source == "cycle"
                and isinstance(raw_ts, int | float)
                and not isinstance(raw_ts, bool)
            ):
                ts_display = _fmt_epoch(float(raw_ts))
            elif source == "promote" and isinstance(raw_ts, str) and raw_ts:
                ts_display = short_iso(raw_ts) or raw_ts
            arm_tag = row.get("promote_policy")
            out.append(
                {
                    "source": source,
                    "ts_display": ts_display,
                    # Untagged (pre-E3) rows are labelled "untagged", never silently
                    # attributed to the gate arm (matches the results-section fix).
                    "arm": str(arm_tag) if isinstance(arm_tag, str) and arm_tag else "untagged",
                    "excludes_zero": excludes,
                    "verdict": (
                        str(row.get("gain_verdict"))
                        if isinstance(row.get("gain_verdict"), str) and row.get("gain_verdict")
                        else ("gain significant" if excludes else "no evidence yet")
                    ),
                    "ci_low": _maybe_float(row.get("gain_ci_low")),
                    "ci_high": _maybe_float(row.get("gain_ci_high")),
                }
            )

    _scan(mutations, "cycle", "ts")
    _scan(archive, "promote", "ts_utc")
    return out


def _evidence_combined_sigma(mutations: list[dict[str, Any]]) -> float | None:
    """Most-recent recorded combined fitness-stderr ``√(within²+between²)``.

    Reads ``within_mutation_stderr`` + ``between_seed_stderr`` from the LATEST
    attribution row that recorded either (ordered by ts). A missing component is
    treated as 0 (the other dominates) — identical to the writer's
    ``VarianceDecomposition.combined_stderr`` contract. Returns ``None`` when no row
    recorded either component (no variance signal yet → the power line says so).
    Graceful: every cast guarded.
    """
    latest_ts: float = float("-inf")
    latest_sigma: float | None = None
    for row in mutations:
        if not isinstance(row, dict) or row.get("kind") != "attribution":
            continue
        raw_ts = row.get("ts")
        if not isinstance(raw_ts, int | float) or isinstance(raw_ts, bool):
            continue
        within = row.get("within_mutation_stderr")
        between = row.get("between_seed_stderr")

        def _comp(value: Any) -> float | None:
            if isinstance(value, bool) or not isinstance(value, int | float):
                return None
            try:
                f = float(value)
            except (TypeError, ValueError):
                return None
            return f if math.isfinite(f) and f >= 0.0 else None

        w = _comp(within)
        b = _comp(between)
        if w is None and b is None:
            continue
        combined = ((w or 0.0) ** 2 + (b or 0.0) ** 2) ** 0.5
        if float(raw_ts) >= latest_ts:
            latest_ts = float(raw_ts)
            latest_sigma = combined
    return latest_sigma


# --------------------------------------------------------------------------- #
# PR-HUB-CAMPAIGN-VIZ (2026-06-01) — the live 3-arm campaign per-cycle ledger. #
# Datadog-style dense faceted panels: per-arm cycle table (verdict / seeds /    #
# Petri eval deep-link / dim engagement / selection-vs-held_out divergence) +   #
# the gen-0 K-mean noise band + the gate-margin rule. Reads the campaign-       #
# progress.log (verdict SoT) + mutations.jsonl attribution rows + the eval-log  #
# MANIFEST (eval link + seeds + per-sample dims). Measured values only.         #
# --------------------------------------------------------------------------- #
_VERDICT_CLASS: dict[str, str] = {
    "promote": "delta-positive",
    "reject": "delta-noise",
    "SKIP": "muted",
}


def _campaign_gen0_means(progress: dict[str, Any]) -> tuple[float | None, float | None]:
    """Mean (selection, held-out) over the gen-0 K-mean repeats.

    These anchor the per-cycle divergence: an arm's cycle is compared to the SAME
    gen-0 baseline both arms started from. Selection-pool fitness and held-out
    fitness sit on different scales (selection ~0.67, held-out ~0.82), so the
    winner's-curse signal is the DIVERGENCE OF THEIR DELTAS vs this gen-0 anchor —
    NOT the absolute level gap. Returns ``(None, None)`` when no gen-0 repeat is
    recorded (the divergence column then degrades to an honest em-dash).
    """
    gen0 = progress.get("gen0") or []
    sels = [float(r["sel"]) for r in gen0 if isinstance(r.get("sel"), int | float)]
    helds = [float(r["held"]) for r in gen0 if isinstance(r.get("held"), int | float)]
    sel_mean = sum(sels) / len(sels) if sels else None
    held_mean = sum(helds) / len(helds) if helds else None
    return (sel_mean, held_mean)


def _campaign_full_attr(mutations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """All arm-tagged ``kind="attribution"`` rows, ts-ascending, full payload.

    Unlike :func:`_held_out_attribution_rows` (which projects to the curve fields),
    this keeps the whole row so the cycle panel can read ``fitness_after`` /
    ``between_seed_stderr`` / ``audit_run_id`` alongside ``held_out_fitness``.
    """
    out: list[dict[str, Any]] = []
    for row in mutations:
        if not isinstance(row, dict) or row.get("kind") != "attribution":
            continue
        arm = row.get("promote_policy")
        if not (isinstance(arm, str) and arm):
            continue
        raw_ts = row.get("ts")
        if not isinstance(raw_ts, int | float) or isinstance(raw_ts, bool):
            continue
        out.append(row)
    out.sort(key=lambda r: float(r["ts"]))
    return out


def _render_gen0_noise_band(progress: dict[str, Any]) -> str:
    """Render the gen-0 K-mean baseline + its measurement noise band.

    The campaign re-measures the UNMUTATED gen-0 scaffold K times to establish the
    noise floor every arm is judged against. Reads the parsed campaign-progress.log
    (``gen0`` repeats + the ``noise`` band line). The held-out band (mean ± stderr)
    is the ruler: an arm's per-cycle held-out must clear mean+stderr to be evidence
    of real gain, not noise. Honest empty state when no gen-0 measure is recorded.
    """
    gen0 = progress.get("gen0") or []
    noise = progress.get("noise")
    if not gen0 and not noise:
        return (
            '    <h3 class="section"><span>gen-0 baseline noise band</span></h3>\n'
            '    <p class="empty"><em>No gen-0 baseline measure recorded yet — the '
            "campaign establishes the noise floor before the arms run.</em></p>"
        )
    rows: list[str] = []
    for rep in gen0:
        try:
            n = int(rep["n"])
            total = int(rep["total"])
            sel = float(rep["sel"])
            held = float(rep["held"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append(
            "        <tr>\n"
            f'          <td class="num">{n}/{total}</td>\n'
            f'          <td class="num">{sel:.4f}</td>\n'
            f'          <td class="num">{held:.4f}</td>\n'
            "        </tr>"
        )
    rows_html = "\n".join(rows) or (
        '        <tr><td colspan="3" class="empty"><em>no repeats parsed</em></td></tr>'
    )
    band_line = ""
    if isinstance(noise, dict):
        try:
            k = int(noise["k"])
            mean = float(noise["mean"])
            stderr = float(noise["stderr"])
            band_line = (
                f'    <p class="page-sub">K={k} held-out noise band: '
                f'<span class="num">{mean:.4f}</span> &plusmn; '
                f'<span class="num">{stderr:.4f}</span> stderr. An arm beats noise only '
                "when its held-out clears <code>mean + stderr</code> "
                f'(&gt; <span class="num">{mean + stderr:.4f}</span>). held-out fitness is '
                "0-1, HIGHER-is-better.</p>\n"
            )
        except (KeyError, TypeError, ValueError):
            band_line = ""
    return (
        '    <h3 class="section"><span>gen-0 baseline noise band &middot; K-mean '
        "re-measure</span></h3>\n"
        f"{band_line}"
        '    <table class="records">\n'
        "      <thead>\n"
        "        <tr>\n"
        '          <th scope="col" class="num">repeat</th>\n'
        '          <th scope="col" class="num">selection fitness</th>\n'
        '          <th scope="col" class="num">held-out fitness</th>\n'
        "        </tr>\n"
        "      </thead>\n"
        f"      <tbody>\n{rows_html}\n      </tbody>\n"
        "    </table>"
    )


def _render_campaign_margin_rule(
    gen0_baseline: dict[str, Any] | None, progress: dict[str, Any]
) -> str:
    """State the promote-gate margin RULE + the recorded baseline stderr (no fabrication).

    The per-cycle promote margin is NOT persisted as a single number per cycle, so
    rather than inventing one, the rule is stated verbatim (SoT
    ``core/self_improving/train.py::_should_promote``) and the one input that IS recorded —
    the gen-0 baseline's ``raw.fitness_stderr`` — is surfaced. The "gate decision so
    far" line is COMPUTED from the recorded gate-arm ``fitness_delta`` values
    (campaign-progress.log), NOT a hard-coded claim — so it never goes stale as the
    campaign continues and never contradicts the data (e.g. a cycle whose delta is
    positive is counted honestly).
    """
    stderr_cell = "<em>not recorded</em>"
    if isinstance(gen0_baseline, dict):
        raw = gen0_baseline.get("raw")
        if isinstance(raw, dict):
            fs = raw.get("fitness_stderr")
            if isinstance(fs, int | float) and not isinstance(fs, bool):
                stderr_cell = f'<span class="num">{float(fs):.4f}</span>'
    # Compute the gate-arm delta summary from the recorded cycles (no fabrication).
    gate_deltas = [
        float(c["delta"])
        for c in (progress.get("cycles") or [])
        if c.get("arm") == "gate"
        and not c.get("skip")
        and isinstance(c.get("delta"), int | float)
        and not isinstance(c.get("delta"), bool)
    ]
    if not gate_deltas:
        decision_cell = "no gate-arm cycle recorded yet &mdash; the gate is mid-run / awaiting"
    else:
        n_positive = sum(1 for d in gate_deltas if d > 0)
        n_total = len(gate_deltas)
        best = max(gate_deltas)
        promotes = sum(
            1
            for c in (progress.get("cycles") or [])
            if c.get("arm") == "gate" and not c.get("skip") and c.get("verdict") == "promote"
        )
        decision_cell = (
            f"{n_positive}/{n_total} measured gate cycles have a positive "
            f"<code>fitness_delta</code> (best {best:+.4f}); promoted <strong>{promotes}</strong>. "
            "A reject when no gain clears the margin is correct, not a tuning failure"
        )
    return (
        '    <h3 class="section"><span>promote-gate margin rule</span></h3>\n'
        '    <p class="page-sub">The gate promotes only when the fitness gain clears '
        "its own margin (SoT <code>core/self_improving/train.py::_should_promote</code>). The "
        "margin is NOT persisted per-cycle, so the RULE + the recorded baseline stderr "
        "are shown rather than a fabricated number.</p>\n"
        '    <dl class="status-grid">\n'
        "      <dt>margin</dt><dd><code>max(1.0&middot;&radic;(&sigma;_prior&sup2;+"
        "&sigma;_current&sup2;), 0.005 floor, 0.05 if baseline N=1 critical)</code></dd>\n"
        "      <dt>fitness scale</dt><dd>0-1 <code>compute_fitness</code>, "
        "HIGHER-is-better</dd>\n"
        f"      <dt>gen-0 baseline fitness_stderr</dt><dd>{stderr_cell}</dd>\n"
        f"      <dt>gate decision so far</dt><dd>{decision_cell}</dd>\n"
        "    </dl>"
    )


def _render_campaign_cycles(
    progress: dict[str, Any],
    mutations: list[dict[str, Any]],
    manifest: list[dict[str, Any]],
    repo_root: Path,
) -> str:
    """Render the per-arm faceted per-cycle campaign table (the Datadog drill-down).

    One section per arm; one row per cycle. Columns surface EVERY value the loop
    emits per cycle: selection fitness (from the attribution row), held-out fitness
    (frozen ruler), the selection-vs-held_out DIVERGENCE (the winner's-curse signal),
    Δheld-out vs prior (dim-direction-aware: held-out is higher-is-better), the
    verdict (promote/reject/SKIP from campaign-progress.log), the seeds the cycle
    scored + the Petri eval deep-link + dim-engagement count (matched from the
    MANIFEST by completed_at). Honest cells when a value is not recorded — never
    fabricated. SKIP cycles (no attribution row) show as SKIP with em-dash numbers.

    SoT split, stated on the page: the verdict + SKIP are the per-cycle ``latest``
    SoT (campaign-progress.log); the promoted champions are the ``promoted`` SoT
    (baseline_archive). They are NOT conflated.
    """
    cycle_recs = progress.get("cycles") or []
    full_attr = _campaign_full_attr(mutations)
    if not cycle_recs and not full_attr:
        return (
            '    <h3 class="section"><span>per-cycle campaign drill-down</span></h3>\n'
            '    <p class="empty"><em>No campaign cycle recorded yet — awaiting the '
            "matched 3-arm 10-cycle run.</em></p>"
        )

    # Index attribution rows by (arm, rounded-ts) so a cycle log line can pull its
    # recorded numbers. The progress-log ts is ISO 8601; the attribution ts is epoch.
    # Match within the same tolerance used for the eval (a cycle's two writes — log
    # line + attribution row — are seconds apart).
    attr_by_arm_ts: dict[str, list[dict[str, Any]]] = {arm: [] for arm, _ in _EVIDENCE_ARMS}
    for row in full_attr:
        attr_by_arm_ts.setdefault(str(row.get("promote_policy")), []).append(row)

    def _attr_for(arm: str, iso_ts: str) -> dict[str, Any] | None:
        if not iso_ts:
            return None
        try:
            cycle_ts = _dt.datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
        best: dict[str, Any] | None = None
        best_gap = _AUDIT_MATCH_TOLERANCE_S
        for row in attr_by_arm_ts.get(arm, []):
            gap = abs(float(row["ts"]) - cycle_ts)
            if gap <= best_gap:
                best_gap = gap
                best = row
        return best

    blocks: list[str] = []
    blocks.append(
        '    <h3 class="section"><span>per-cycle campaign drill-down &middot; '
        "verdict / seeds / Petri eval / divergence</span></h3>\n"
        '    <p class="page-sub">One row per cycle, faceted by arm. <strong>verdict</strong> '
        "+ <strong>SKIP</strong> are the per-cycle <em>latest</em> SoT "
        "(<code>campaign-progress.log</code>) &mdash; distinct from the <em>promoted</em> "
        "champion SoT (<code>baseline_archive.jsonl</code>, the 3-arm table above). "
        "<strong>divergence</strong> = (selection &minus; gen-0 selection) &minus; "
        "(held-out &minus; gen-0 held-out): the gap between how much the cycle moved the "
        "selection proxy vs the frozen ruler. A <em>positive</em> divergence is the "
        "winner's-curse signal (selection rose more than the held-out ruler). selection + "
        "held-out are 0-1 fitness (HIGHER-is-better) but on DIFFERENT scales, so they are "
        "anchored to their own gen-0 mean before subtracting; the held-out &Delta;-vs-prior "
        "arrow is green when it rises.</p>"
    )

    gen0_sel_mean, gen0_held_mean = _campaign_gen0_means(progress)
    for arm, label in _EVIDENCE_ARMS:
        arm_cycles = [c for c in cycle_recs if c.get("arm") == arm]
        if not arm_cycles:
            blocks.append(
                f'    <h4 class="section"><span>{html_escape(label)} &middot; '
                f"<code>{html_escape(arm)}</code></span></h4>\n"
                '    <p class="empty"><em>No cycle recorded for this arm yet.</em></p>'
            )
            continue
        rows: list[str] = []
        prior_held: float | None = None
        promotes = rejects = skips = 0
        for c in arm_cycles:
            n = c.get("n")
            total = c.get("total")
            cyc_label = f"{n}/{total}"
            if c.get("skip"):
                skips += 1
                rows.append(
                    "        <tr>\n"
                    f'          <td class="num">{html_escape(cyc_label)}</td>\n'
                    '          <td class="num muted">&mdash;</td>\n'
                    '          <td class="num muted">&mdash;</td>\n'
                    '          <td class="num muted">&mdash;</td>\n'
                    '          <td class="num muted">&mdash;</td>\n'
                    '          <td><span class="muted">SKIP</span></td>\n'
                    '          <td class="muted">&mdash;</td>\n'
                    "        </tr>"
                )
                continue
            verdict = str(c.get("verdict") or "")
            if verdict == "promote":
                promotes += 1
            elif verdict == "reject":
                rejects += 1
            try:
                sel = float(c["sel"])
                held = float(c["held"])
            except (KeyError, TypeError, ValueError):
                continue
            # Divergence = how much the cycle moved selection vs the frozen ruler,
            # each anchored to its OWN gen-0 mean (the two scales are not comparable
            # directly). A positive divergence (selection rose more than held-out) is
            # the winner's-curse signal → red. When the gen-0 anchor is unrecorded the
            # cell degrades to an honest em-dash rather than a bogus level-gap.
            if gen0_sel_mean is None or gen0_held_mean is None:
                div_cls = "muted"
                div_text = "&mdash;"
            else:
                divergence = (sel - gen0_sel_mean) - (held - gen0_held_mean)
                div_cls = (
                    "delta-negative"
                    if divergence > 0.005
                    else ("delta-positive" if divergence < -0.005 else "delta-noise")
                )
                div_text = f"{divergence:+.4f}"
            # Δ held-out vs prior cycle: held-out is HIGHER-is-better, so a rise is good.
            if prior_held is None:
                held_delta_cell = '<td class="num muted">&mdash;</td>'
            else:
                d = held - prior_held
                dcls = "delta-positive" if d > 0 else ("delta-negative" if d < 0 else "delta-noise")
                held_delta_cell = f'<td class="num {dcls}">{d:+.4f}</td>'
            prior_held = held
            v_cls = _VERDICT_CLASS.get(verdict, "muted")
            verdict_cell = f'<span class="{v_cls}">{html_escape(verdict or "&mdash;")}</span>'

            # Eval / seeds / dims from the MANIFEST, matched by the attribution-row ts.
            attr = _attr_for(arm, str(c.get("ts") or ""))
            eval_cell = '<span class="muted">no eval recorded</span>'
            if attr is not None:
                audit = _match_audit_for_cycle(float(attr["ts"]), manifest)
                if audit is not None:
                    eval_cell = _render_campaign_eval_cell(audit, repo_root)
            rows.append(
                "        <tr>\n"
                f'          <td class="num">{html_escape(cyc_label)}</td>\n'
                f'          <td class="num">{sel:.4f}</td>\n'
                f'          <td class="num">{held:.4f}</td>\n'
                f'          <td class="num {div_cls}">{div_text}</td>\n'
                f"          {held_delta_cell}\n"
                f"          <td>{verdict_cell}</td>\n"
                f"          <td>{eval_cell}</td>\n"
                "        </tr>"
            )
        rows_html = "\n".join(rows)
        seed_note = ""
        # Surface the held-out seed pool once per arm from the first matched audit.
        first_attr = _attr_for(arm, str((arm_cycles[0] or {}).get("ts") or ""))
        if first_attr is not None:
            first_audit = _match_audit_for_cycle(float(first_attr["ts"]), manifest)
            if first_audit is not None:
                seeds = first_audit.get("seed_ids")
                if isinstance(seeds, list) and seeds:
                    seed_note = (
                        '    <p class="page-sub">held-out seed pool ('
                        f"{len(seeds)} seeds): "
                        + ", ".join(f"<code>{html_escape(str(s))}</code>" for s in seeds[:10])
                        + "</p>\n"
                    )
        blocks.append(
            f'    <h4 class="section"><span>{html_escape(label)} &middot; '
            f"<code>{html_escape(arm)}</code> &middot; "
            f"promote {promotes} &middot; reject {rejects} &middot; SKIP {skips}</span></h4>\n"
            f"{seed_note}"
            '    <table class="records">\n'
            "      <thead>\n"
            "        <tr>\n"
            '          <th scope="col" class="num">cycle</th>\n'
            '          <th scope="col" class="num">selection</th>\n'
            '          <th scope="col" class="num">held-out</th>\n'
            '          <th scope="col" class="num">divergence</th>\n'
            '          <th scope="col" class="num">&Delta; held-out</th>\n'
            '          <th scope="col">verdict</th>\n'
            '          <th scope="col">Petri eval &middot; dims</th>\n'
            "        </tr>\n"
            "      </thead>\n"
            f"      <tbody>\n{rows_html}\n      </tbody>\n"
            "    </table>"
        )
    return "\n".join(blocks)


def _render_campaign_eval_cell(audit: dict[str, Any], repo_root: Path) -> str:
    """Render the Petri-eval deep-link + dim-engagement count for one matched audit.

    The deep-link targets the Inspect-View ``#/logs/<encodeURIComponent(file)>``
    route ONLY (via :func:`inspect_log_route`) — keyed on the ``.eval`` archive
    filename (the ``logs/listing.json`` key), never the task_id (which has no route).
    The dim-engagement count comes from the matched ``summary_yaml`` (count of dims
    that moved off the baseline floor across the audit's samples). Honest "&mdash;"
    when a field is absent.
    """
    archive = audit.get("archive")
    if not (isinstance(archive, str) and archive):
        return '<span class="muted">no archive</span>'
    deep_link = f"{_PETRI_BUNDLE_DEEPLINK_BASE}{inspect_log_route(archive)}"
    short_name = archive.split("_audit_")[0] if "_audit_" in archive else archive[:19]
    cell = f'<a href="{deep_link}"><code>{html_escape(short_name)}</code></a>'
    summary_yaml = audit.get("summary_yaml")
    if isinstance(summary_yaml, str) and summary_yaml:
        dims = _load_summary_dims(repo_root, summary_yaml)
        if dims is not None:
            engaged = dims.get("dim_engaged") or {}
            n_dims = len(engaged)
            n_samples = dims.get("sample_count") or 0
            cell += (
                f' <span class="muted">&middot; {n_dims} dims engaged / {n_samples} samples</span>'
            )
    return cell


def _render_evidence_methods() -> str:
    """Render the METHODS grid — the experimental design, stated honestly.

    Static design facts (the design does not change per-render), as a dense
    definition list: the frozen held-out ruler vs the pinned selection pool (E2/B2),
    the per-mutation replicate + ci-excludes-0 rule (E4), reproducibility pins (E5),
    and the content-addressed epoch partition (A). Plain text + monospace only — no
    card grid, accent bar, or emoji.
    """
    rows: list[tuple[str, str]] = [
        (
            "held-out ruler (E2)",
            "VERSION-FROZEN bench (<code>held_out_bench_id</code>), an older-runs set "
            "DISJOINT from the selection pool. <code>held_out_fitness</code> is the SAME "
            "0-1 <code>compute_fitness</code> (HIGHER-is-better) scored on it EVERY cycle. "
            "Because the bench never mutates, this curve IS comparable across generations.",
        ),
        (
            "selection pool (B2)",
            "the PINNED co-evolving pool <code>pool-68dc6f0c9745</code> the loop selects on. "
            "It co-evolves, so the intrinsic <code>fitness</code> measured on it is NOT "
            "cross-generation evidence — only the held-out ruler is.",
        ),
        (
            "3 control arms (E3)",
            "<code>gate</code> = selection (promote gate) &middot; <code>random</code> = "
            "random-accept control &middot; <code>never</code> = no-mutation floor. The "
            "cross-arm comparison on the SAME fixed ruler isolates selection from drift + "
            "judge noise: if gate does not beat random + never on the held-out curve, the "
            "improvement is not from selection.",
        ),
        (
            "replicate + ci-excludes-0 (E4)",
            "per-mutation replicate <code>M</code> (repeated audits of the same cycle) "
            "decomposes provider jitter (within) from seed heterogeneity (between). A gain "
            "is CLAIMED only when its confidence interval excludes 0 "
            "(<code>gain_ci_excludes_zero</code>); otherwise the honest verdict is "
            '"no evidence yet".',
        ),
        (
            "reproducibility pins (E5)",
            "each cycle records <code>prompt_hash</code> &middot; <code>applied_diff_hash</code> "
            "&middot; <code>sampling_params</code> &middot; <code>rng_seed</code> so a third "
            "party can reconstruct WHAT WAS SENT (auditability — no backend-determinism claim).",
        ),
        (
            "epoch partition (A)",
            "every promoted baseline is hashed into a content-addressed epoch (be-NNN) keyed "
            "on the production+measurement spec; baselines from different epochs were produced "
            "under different logic and are never averaged into one comparison.",
        ),
    ]
    out: list[str] = ['    <dl class="status-grid">']
    for label, value in rows:
        out.append(f"      <dt>{html_escape(label)}</dt><dd>{value}</dd>")
    out.append("    </dl>")
    return "\n".join(out)


def _render_evidence_methods_arms() -> str:
    """Render the 3-arm definition table for the methods section (dense table)."""
    rows: list[str] = []
    for arm, label in _EVIDENCE_ARMS:
        rows.append(
            "        <tr>\n"
            f"          <td><code>{html_escape(arm)}</code></td>\n"
            f"          <td>{html_escape(label)}</td>\n"
            "        </tr>"
        )
    rows_html = "\n".join(rows)
    return (
        '    <h3 class="section"><span>Control arms</span></h3>\n'
        '    <table class="records">\n'
        "      <thead>\n"
        "        <tr>\n"
        '          <th scope="col"><code>promote_policy</code></th>\n'
        '          <th scope="col">role on the fixed ruler</th>\n'
        "        </tr>\n"
        "      </thead>\n"
        "      <tbody>\n"
        f"{rows_html}\n"
        "      </tbody>\n"
        "    </table>"
    )


def _render_evidence_arm_curve(arm: str, label: str, points: list[dict[str, Any]]) -> str:
    """Render one arm's per-cycle held-out curve (or its honest empty state)."""
    if not points:
        return (
            f'    <h3 class="section"><span>{html_escape(label)} '
            f"&middot; <code>{html_escape(arm)}</code></span></h3>\n"
            '    <p class="empty"><em>No held-out cycle recorded for this arm yet — '
            "awaiting the matched 3-arm campaign.</em></p>"
        )
    rows: list[str] = []
    prior: float | None = None
    for index, point in enumerate(points, start=1):
        fitness = point["held_out_fitness"]
        if prior is None:
            delta_cell = '<td class="num muted">—</td>'
        else:
            delta = fitness - prior
            cls = "delta-positive" if delta > 0 else ("delta-negative" if delta < 0 else "muted")
            delta_cell = f'<td class="num {cls}">{delta:+.4f}</td>'
        prior = fitness
        rows.append(
            "        <tr>\n"
            f'          <td class="num">{index}</td>\n'
            f'          <td class="muted">{html_escape(_fmt_epoch(point["ts"]))}</td>\n'
            f'          <td class="num">{fitness:.4f}</td>\n'
            f"          {delta_cell}\n"
            "        </tr>"
        )
    rows_html = "\n".join(rows)
    return (
        f'    <h3 class="section"><span>{html_escape(label)} '
        f"&middot; <code>{html_escape(arm)}</code> &middot; "
        f"{len(points)} generation" + ("s" if len(points) != 1 else "") + "</span></h3>\n"
        '    <table class="records">\n'
        "      <thead>\n"
        "        <tr>\n"
        '          <th scope="col" class="num">gen</th>\n'
        '          <th scope="col">measured</th>\n'
        '          <th scope="col" class="num">held-out fitness</th>\n'
        '          <th scope="col" class="num">&Delta; vs prior</th>\n'
        "        </tr>\n"
        "      </thead>\n"
        "      <tbody>\n"
        f"{rows_html}\n"
        "      </tbody>\n"
        "    </table>"
    )


def _render_evidence_results(
    mutations: list[dict[str, Any]],
    archive: list[dict[str, Any]],
) -> str:
    """Render the RESULTS section: per-arm held-out curve + 3-arm comparison +
    promotion count per arm. Honest empty state when no campaign has run.

    A held-out point / promoted baseline that carries NO ``promote_policy`` (a pre-E3
    row, written before the control arms existed) is NOT silently attributed to the
    ``gate`` arm — that would fabricate a gate-arm campaign result where none was run.
    Untagged rows are counted in an explicit ``untagged (pre-arm)`` bucket so a
    pre-experiment promotion never masquerades as matched-campaign arm evidence.
    """
    points = _held_out_attribution_rows(mutations)
    by_arm: dict[str, list[dict[str, Any]]] = {arm: [] for arm, _ in _EVIDENCE_ARMS}
    untagged_points: list[dict[str, Any]] = []
    for point in points:
        if point["arm_tagged"]:
            by_arm.setdefault(point["arm"], []).append(point)
        else:
            untagged_points.append(point)

    # Promotion count per arm from the promoted-baseline registry rows. An untagged
    # baseline (pre-E3) is counted SEPARATELY — never folded into the gate arm.
    promo_by_arm: dict[str, int] = {arm: 0 for arm, _ in _EVIDENCE_ARMS}
    untagged_promos = 0
    for row in archive:
        if not isinstance(row, dict) or row.get("kind") != "baseline":
            continue
        arm = row.get("promote_policy")
        if isinstance(arm, str) and arm in promo_by_arm:
            promo_by_arm[arm] += 1
        else:
            untagged_promos += 1

    blocks: list[str] = []

    # 3-arm comparison summary (mean held-out fitness + promotion count per arm),
    # plus an explicit untagged (pre-arm) row when any untagged data exists.
    comparison_rows: list[str] = []
    summary_rows: list[tuple[str, str, list[dict[str, Any]], int]] = [
        (arm, label, by_arm.get(arm, []), promo_by_arm.get(arm, 0)) for arm, label in _EVIDENCE_ARMS
    ]
    if untagged_points or untagged_promos:
        summary_rows.append(
            ("untagged", "pre-arm (no promote_policy)", untagged_points, untagged_promos)
        )
    for arm, label, arm_points, promo in summary_rows:
        if arm_points:
            mean_fitness = sum(p["held_out_fitness"] for p in arm_points) / len(arm_points)
            mean_cell = f'<td class="num">{mean_fitness:.4f}</td>'
            n_cell = f'<td class="num">{len(arm_points)}</td>'
        else:
            mean_cell = '<td class="num muted">—</td>'
            n_cell = '<td class="num muted">0</td>'
        comparison_rows.append(
            "        <tr>\n"
            f"          <td><code>{html_escape(arm)}</code> "
            f'<span class="muted">{html_escape(label)}</span></td>\n'
            f"          {n_cell}\n"
            f"          {mean_cell}\n"
            f'          <td class="num">{promo}</td>\n'
            "        </tr>"
        )
    comparison_html = "\n".join(comparison_rows)
    total_points = len(points)
    arm_tagged_points = sum(len(v) for v in by_arm.values())
    if arm_tagged_points == 0:
        untagged_note = (
            f" {untagged_promos} promoted baseline"
            + ("s" if untagged_promos != 1 else "")
            + (" predate" if untagged_promos != 1 else " predates")
            + " the control arms (no <code>promote_policy</code> tag) — counted in "
            "the untagged row, NOT attributed to any arm."
            if untagged_promos
            else ""
        )
        comparison_note = (
            "No arm-tagged held-out cycle recorded yet — the matched 3-arm campaign has "
            "not run. The table below shows the structure; arm values populate when the "
            "campaign writes <code>held_out_fitness</code> + <code>promote_policy</code> rows."
            + untagged_note
        )
    else:
        arm_promos = sum(promo_by_arm.values())
        comparison_note = (
            "Mean held-out fitness (the fixed ruler) per arm. Selection (<code>gate</code>) "
            "is only evidenced if it beats BOTH controls on this ruler. "
            f"Arm-tagged promotions: <strong>{arm_promos}</strong>"
            + (
                " — <strong>0 promotions is a trust-increasing result</strong>: the loop "
                "correctly promoted nothing on null evidence."
                if arm_promos == 0
                else "."
            )
        )
    blocks.append(
        '    <h3 class="section"><span>3-arm comparison &middot; fixed ruler</span></h3>\n'
        f'    <p class="page-sub">{comparison_note}</p>\n'
        '    <table class="records">\n'
        "      <thead>\n"
        "        <tr>\n"
        '          <th scope="col">arm</th>\n'
        '          <th scope="col" class="num">held-out cycles</th>\n'
        '          <th scope="col" class="num">mean held-out fitness</th>\n'
        '          <th scope="col" class="num">promotions</th>\n'
        "        </tr>\n"
        "      </thead>\n"
        "      <tbody>\n"
        f"{comparison_html}\n"
        "      </tbody>\n"
        "    </table>"
    )

    # Per-arm curve (one table per arm; honest empty state per arm).
    if total_points == 0:
        blocks.append(
            '    <p class="empty"><em>No held-out campaign recorded yet — awaiting the '
            "matched 3-arm 10-cycle run. The per-arm curves render here once "
            "<code>core/self_improving/train.py</code> writes them.</em></p>"
        )
    else:
        for arm, label in _EVIDENCE_ARMS:
            blocks.append(_render_evidence_arm_curve(arm, label, by_arm.get(arm, [])))
        if untagged_points:
            blocks.append(
                _render_evidence_arm_curve(
                    "untagged", "pre-arm (no promote_policy)", untagged_points
                )
            )
    return "\n".join(blocks)


def _render_evidence_verdict(
    mutations: list[dict[str, Any]],
    archive: list[dict[str, Any]],
) -> str:
    """Render the per-cycle / per-campaign ci-excludes-0 verdict table (RESULTS).

    Honest empty state when no row recorded a verdict yet.
    """
    verdicts = _evidence_gain_verdicts(mutations, archive)
    if not verdicts:
        return (
            '    <h3 class="section"><span>Gain verdict &middot; ci excludes 0</span></h3>\n'
            '    <p class="empty"><em>No gain verdict recorded yet — no cycle or promote has '
            "written <code>gain_ci_excludes_zero</code>. With no evidence on disk, the honest "
            "statement is: <strong>no evidence of a gain yet.</strong></em></p>"
        )
    rows: list[str] = []
    for entry in verdicts:
        excludes = bool(entry["excludes_zero"])
        v_cls = "delta-positive" if excludes else "muted"
        ci_low = entry["ci_low"]
        ci_high = entry["ci_high"]
        if ci_low is not None and ci_high is not None:
            ci_cell = f'<td class="num">[{ci_low:+.4f}, {ci_high:+.4f}]</td>'
        else:
            ci_cell = '<td class="num muted">—</td>'
        ts_cell = f'<td class="muted">{html_escape(str(entry["ts_display"]))}</td>'
        rows.append(
            "        <tr>\n"
            f'          <td class="muted">{html_escape(entry["source"])}</td>\n'
            f"          {ts_cell}\n"
            f"          <td><code>{html_escape(entry['arm'])}</code></td>\n"
            f"          {ci_cell}\n"
            f'          <td><span class="{v_cls}">{html_escape(entry["verdict"])}</span></td>\n'
            "        </tr>"
        )
    rows_html = "\n".join(rows)
    return (
        '    <h3 class="section"><span>Gain verdict &middot; ci excludes 0 &middot; '
        f"{len(verdicts)} recorded</span></h3>\n"
        '    <p class="page-sub">The explicit "ci excludes 0" evidence statement on the '
        "fitness gain. <code>gain significant</code> only when the CI lies entirely above 0; "
        "otherwise the honest null: <code>no evidence yet</code>.</p>\n"
        '    <table class="records">\n'
        "      <thead>\n"
        "        <tr>\n"
        '          <th scope="col">source</th>\n'
        '          <th scope="col">measured</th>\n'
        '          <th scope="col">arm</th>\n'
        '          <th scope="col" class="num">gain CI</th>\n'
        '          <th scope="col">verdict</th>\n'
        "        </tr>\n"
        "      </thead>\n"
        "      <tbody>\n"
        f"{rows_html}\n"
        "      </tbody>\n"
        "    </table>"
    )


def _render_evidence_power(mutations: list[dict[str, Any]]) -> str:
    """Render the POWER section: the required-N line from the recorded σ + the
    honest verdict. Never fabricates a number — σ unknown → "indeterminate"."""
    sigma = _evidence_combined_sigma(mutations)
    n_seed = _required_n_seed(sigma)
    delta = _POWER_DEFAULT_TARGET_EFFECT_SIZE
    alpha = _POWER_DEFAULT_ALPHA
    power = _POWER_DEFAULT_POWER
    if n_seed is None:
        power_line = (
            f"To detect &delta;={delta:.4f} fitness at {power:.0%} power "
            f"(&alpha;={alpha:.2f}), observed &sigma; is <strong>unknown</strong> &mdash; "
            "N indeterminate (insufficient variance signal; run <code>--replicate M&ge;2</code> "
            "or a multi-sample audit to estimate &sigma;)."
        )
        sigma_cell = "<em>not yet estimated</em>"
        n_cell = "<em>indeterminate</em>"
    else:
        power_line = (
            f"To detect &delta;={delta:.4f} fitness at {power:.0%} power "
            f"(&alpha;={alpha:.2f}), observed &sigma;={sigma:.4f} &rarr; "
            f"need N_seed&ge;<strong>{n_seed}</strong> &times; M_replicate&ge;1."
        )
        sigma_cell = f'<span class="num">{sigma:.4f}</span>'
        n_cell = f'<span class="num">{n_seed}</span>'
    return (
        '    <dl class="status-grid">\n'
        f'      <dt>target effect &delta;</dt><dd><span class="num">{delta:.4f}</span> '
        "(fitness scale, HIGHER-is-better)</dd>\n"
        f'      <dt>significance &alpha;</dt><dd><span class="num">{alpha:.2f}</span></dd>\n'
        f'      <dt>target power</dt><dd><span class="num">{power:.0%}</span></dd>\n'
        f"      <dt>observed &sigma; (recorded)</dt><dd>{sigma_cell}</dd>\n"
        f"      <dt>required N_seed per arm</dt><dd>{n_cell}</dd>\n"
        "    </dl>\n"
        f'    <p class="page-sub">{power_line}</p>'
    )


def _render_results_header_cells() -> str:
    """Render the 12 <th> cells for the results table header."""
    out: list[str] = []
    for col in AUTORESEARCH_RESULTS_TSV_HEADER:
        out.append(f'          <th scope="col">{html_escape(col)}</th>')
    return "\n".join(out)


def _render_results_rows(
    results_rows: list[dict[str, str]],
    jsonl_rows: list[dict[str, Any]],
) -> str:
    """Render results.tsv rows. Pairs with results.jsonl by index for drill-down."""
    if not results_rows:
        return (
            '        <tr><td colspan="12" class="empty">'
            "<em>No iterations recorded yet.</em></td></tr>"
        )
    out: list[str] = []
    for idx, row in enumerate(results_rows):
        cells: list[str] = []
        verdict = row.get("verdict", "")
        for col in AUTORESEARCH_RESULTS_TSV_HEADER:
            value = row.get(col, "")
            if col == "fitness":
                try:
                    val = float(value)
                    cells.append(f'          <td class="num">{val:.4f}</td>')
                except (TypeError, ValueError):
                    cells.append(f'          <td class="muted">{html_escape(value)}</td>')
            elif col in {
                "critical_min",
                "critical_mean",
                "auxiliary_mean",
                "stability_score",
                "info_mean",
            }:
                try:
                    val = float(value)
                    cells.append(f'          <td class="num">{val:.3f}</td>')
                except (TypeError, ValueError):
                    cells.append(f'          <td class="muted">{html_escape(value)}</td>')
            elif col == "dim_count_engaged":
                cells.append(f'          <td class="num">{html_escape(value)}</td>')
            elif col == "verdict":
                v_cls = "muted"
                if verdict in {"keep", "applied", "promoted"}:
                    v_cls = "delta-positive"
                elif verdict in {"reject", "reverted", "discard"}:
                    v_cls = "delta-negative"
                cells.append(
                    f'          <td><span class="{v_cls}">{html_escape(value)}</span></td>'
                )
            elif col == "gen_tag":
                cells.append(f"          <td><code>{html_escape(value)}</code></td>")
            elif col in {"session_id", "commit"}:
                short = value[:12] if value else ""
                cells.append(
                    f'          <td class="muted" title="{html_escape(value)}">'
                    f"<code>{html_escape(short)}</code></td>"
                )
            else:  # description, etc.
                cells.append(f'          <td class="muted">{html_escape(value)}</td>')
        # Drill-down: per-row <details> with the jsonl payload, if matched.
        details = ""
        if idx < len(jsonl_rows):
            try:
                payload = json.dumps(jsonl_rows[idx], ensure_ascii=False, indent=2, sort_keys=True)
            except (TypeError, ValueError):
                payload = ""
            if payload:
                payload_html = html_escape(payload)
                details = (
                    "\n        <tr>\n"
                    '          <td colspan="12">\n'
                    "            <details>\n"
                    "              <summary>jsonl payload</summary>\n"
                    "              "
                    f'<div class="policy-json"><pre>{payload_html}</pre></div>\n'
                    "            </details>\n"
                    "          </td>\n"
                    "        </tr>"
                )
        out.append("        <tr>\n" + "\n".join(cells) + "\n        </tr>" + details)
    return "\n".join(out)


# target_kind -> mirrored policy filename. Local copy of the SoT in
# core/self_improving/loop/policies.py::_KIND_TO_PATH (the docs builder is
# intentionally stdlib-only, so it cannot import core). Kept in lockstep by
# test_policy_file_map_matches_core (dual-SoT drift guard).
_TARGET_KIND_TO_POLICY_FILE: dict[str, str] = {
    "prompt": "wrapper-sections.json",
    "tool_policy": "tool-policy.json",
    "decomposition": "decomposition.json",
    "retrieval": "retrieval.json",
    "reflection": "reflection.json",
    "skill_catalog": "skill-catalog.json",
    "agent_contract": "agent-contracts.json",
    "tool_descriptions": "tool-descriptions.json",
    "hyperparam": "hyperparam.json",
}


def _render_policies_rows(
    policies: list[dict[str, Any]],
    mutations: list[dict[str, Any]],
) -> str:
    """Render the policies table body. Cross-link the latest mutation per file."""
    if not policies:
        return (
            '        <tr><td colspan="5" class="empty">'
            "<em>No policies mirrored yet. Run the autoresearch publisher.</em>"
            "</td></tr>"
        )
    # Index the most-recent mutation per policy filename via the flat-schema
    # target_kind -> filename map. _join_mutation_records is newest-first, so
    # the first entry seen per file is the latest.
    latest_by_file: dict[str, dict[str, Any]] = {}
    for joined in _join_mutation_records(mutations):
        apply_row = joined["apply"]
        if not apply_row:
            continue
        filename = _TARGET_KIND_TO_POLICY_FILE.get(str(apply_row.get("target_kind") or ""))
        if filename:
            latest_by_file.setdefault(filename, joined)
    out: list[str] = []
    for entry in policies:
        filename = str(entry["filename"])
        mtime = _dt.datetime.fromtimestamp(float(entry["mtime"]), tz=_dt.UTC).strftime(
            "%Y-%m-%d %H:%M"
        )
        size = _human_size(int(entry["size"]))
        latest = latest_by_file.get(filename)
        if latest is not None:
            apply_row = latest["apply"] or {}
            section = str(apply_row.get("target_section") or "")
            ts = _fmt_epoch(apply_row.get("ts"))
            label, outcome_cls = _mutation_outcome(latest["attr"])
            mut_cell = (
                f"<code>{html_escape(section)}</code> "
                f'<span class="muted">@ {html_escape(ts)}</span> '
                f'<span class="{outcome_cls}">{html_escape(label)}</span>'
            )
        else:
            mut_cell = '<span class="muted">—</span>'
        if entry["content"] is not None:
            try:
                payload = json.dumps(entry["content"], ensure_ascii=False, indent=2, sort_keys=True)
            except (TypeError, ValueError):
                payload = entry["content_text"]
        else:
            payload = entry["content_text"]
        if not payload:
            payload = "(empty file)"
        view_cell = (
            "<details>\n"
            "              <summary>view JSON</summary>\n"
            f'              <div class="policy-json"><pre>{html_escape(payload)}</pre></div>\n'
            "            </details>"
        )
        out.append(
            "        <tr>\n"
            f'          <td class="id"><code>{html_escape(filename)}</code> '
            '<span class="bucket autoresearch">autoresearch</span></td>\n'
            f'          <td class="muted">{html_escape(mtime)}</td>\n'
            f'          <td class="num">{html_escape(size)}</td>\n'
            f"          <td>{mut_cell}</td>\n"
            f"          <td>{view_cell}</td>\n"
            "        </tr>"
        )
    return "\n".join(out)


@dataclass
class _AutoresearchRenderCtx:
    """Common context shared by all 5 autoresearch renderers."""

    sidebar_petri_recent: str
    sidebar_seedgen_runs: str
    petri_count: int
    seedgen_count_label: str
    autoresearch_status_label: str
    geode_version: str
    build_date: str


def _autoresearch_base_mapping(ctx: _AutoresearchRenderCtx) -> dict[str, str]:
    return {
        "petri_count": str(ctx.petri_count),
        "sidebar_petri_recent": ctx.sidebar_petri_recent,
        "seedgen_count_label": ctx.seedgen_count_label,
        "sidebar_seedgen_runs": ctx.sidebar_seedgen_runs,
        "autoresearch_status_label": ctx.autoresearch_status_label,
        "geode_version": ctx.geode_version,
        "design_schema_version": str(DESIGN_SCHEMA_VERSION),
        "build_date": ctx.build_date,
    }


def render_autoresearch_landing(
    baseline: dict[str, Any] | None,
    baseline_path: Path | None,
    stale: bool,
    archive: list[dict[str, Any]],
    mutations_count: int,
    mutations_mtime: str,
    results_count: int,
    results_mtime: str,
    policies_count: int,
    policies_mtime: str,
    baseline_mtime: str,
    out_dir: Path,
    *,
    template: str,
    ctx: _AutoresearchRenderCtx,
    held_out_count: int = 0,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    mapping = _autoresearch_base_mapping(ctx)
    mapping.update(
        {
            "stale_baseline_warning": _render_warning_banner(baseline_path, stale),
            "status_grid_rows": _autoresearch_status_grid(
                baseline,
                baseline_path,
                mutations_count,
                mutations_mtime,
                results_count,
                results_mtime,
                policies_count,
                policies_mtime,
            ),
            "timeline_section_label": (f"{len(archive)} row" + ("s" if len(archive) != 1 else "")),
            "timeline_rows": _gen_timeline_rows(archive, baseline),
            "baseline_registry_index": _render_baseline_registry_index(archive),
            "subview_rows": _autoresearch_subview_rows(
                archive_count=len(archive),
                mutations_count=mutations_count,
                results_count=results_count,
                policies_count=policies_count,
                mutations_mtime=mutations_mtime,
                results_mtime=results_mtime,
                policies_mtime=policies_mtime,
                baseline_mtime=baseline_mtime,
                held_out_count=held_out_count,
            ),
        }
    )
    rendered = substitute(template, mapping)
    leftover = re.findall(r"\{\{\s*([a-zA-Z_]+)\s*\}\}", rendered)
    if leftover:
        raise RuntimeError(f"autoresearch landing unresolved markers: {sorted(set(leftover))}")
    out_path = out_dir / "index.html"
    out_path.write_text(rendered, encoding="utf-8")
    return out_path


def render_autoresearch_baseline(
    baseline: dict[str, Any] | None,
    baseline_path: Path | None,
    stale: bool,
    out_dir: Path,
    *,
    template: str,
    ctx: _AutoresearchRenderCtx,
    transcripts: dict[str, Any] | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    namespace_blocks: list[str] = []
    if baseline is None:
        namespace_blocks.append(
            '    <div class="namespace-block">\n'
            "      <h3>no baseline</h3>\n"
            '      <p class="empty-namespace">No live <code>baseline.json</code> '
            "and no <code>baseline.json.outdated-*</code> snapshot found. Run "
            "<code>uv run python -m core.self_improving.train --promote</code>.</p>\n"
            "    </div>"
        )
    else:
        for ns in AUTORESEARCH_BASELINE_NAMESPACES:
            ns_data = _baseline_namespace_data(baseline, ns)
            namespace_blocks.append(_render_baseline_namespace(ns, ns_data, stale=stale))
    mapping = _autoresearch_base_mapping(ctx)
    mapping.update(
        {
            "stale_baseline_warning": _render_warning_banner(baseline_path, stale),
            "baseline_process": _render_baseline_process(baseline, transcripts),
            "baseline_namespaces": "\n".join(namespace_blocks),
            "baseline_seed_corpus": _render_baseline_seed_corpus(transcripts),
            "baseline_audit_transcripts": _render_baseline_audit_transcripts(transcripts),
        }
    )
    rendered = substitute(template, mapping)
    leftover = re.findall(r"\{\{\s*([a-zA-Z_]+)\s*\}\}", rendered)
    if leftover:
        raise RuntimeError(f"autoresearch baseline unresolved markers: {sorted(set(leftover))}")
    out_path = out_dir / "baseline" / "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    return out_path


def render_autoresearch_mutations(
    mutations: list[dict[str, Any]],
    out_dir: Path,
    *,
    template: str,
    ctx: _AutoresearchRenderCtx,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    joined = _join_mutation_records(mutations)
    mapping = _autoresearch_base_mapping(ctx)
    mapping.update(
        {
            "mutations_section_label": (
                f"{len(joined)} mutation" + ("s" if len(joined) != 1 else "")
            ),
            "mutations_summary": _render_mutations_summary(joined),
            "mutations_rows": _render_mutations_rows(joined),
            # E2 — per-cycle held-out (fixed-ruler) fitness curve from the raw
            # attribution rows (NOT the joined apply+attr pairs — a held-out point
            # exists on every cycle's attribution row, independent of whether the
            # cycle applied a mutation). Empty string when no bench was scored.
            "held_out_curve": _render_held_out_curve(mutations),
        }
    )
    rendered = substitute(template, mapping)
    leftover = re.findall(r"\{\{\s*([a-zA-Z_]+)\s*\}\}", rendered)
    if leftover:
        raise RuntimeError(f"autoresearch mutations unresolved markers: {sorted(set(leftover))}")
    out_path = out_dir / "mutations" / "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    return out_path


def render_autoresearch_results(
    results_rows: list[dict[str, str]],
    jsonl_rows: list[dict[str, Any]],
    out_dir: Path,
    *,
    template: str,
    ctx: _AutoresearchRenderCtx,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Compose the fitness sparkline from the results table.
    fitness_vals: list[float] = []
    for row in results_rows:
        try:
            fitness_vals.append(float(row.get("fitness", "") or "nan"))
        except (TypeError, ValueError):
            continue
        # Filter out NaN.
    fitness_vals = [v for v in fitness_vals if v == v]  # noqa: PLR0124 — NaN filter
    sparkline = _fitness_sparkline(fitness_vals) if fitness_vals else ""
    if fitness_vals:
        sparkline_legend = (
            f"min {min(fitness_vals):.4f} &middot; max {max(fitness_vals):.4f} &middot; "
            f"n={len(fitness_vals)}"
        )
        sparkline_aria = (
            f"fitness sparkline across {len(fitness_vals)} iterations "
            f"min {min(fitness_vals):.4f} max {max(fitness_vals):.4f}"
        )
    else:
        sparkline = "—"
        sparkline_legend = "no iterations recorded"
        sparkline_aria = "no fitness data"
    mapping = _autoresearch_base_mapping(ctx)
    mapping.update(
        {
            "results_section_label": (
                f"{len(results_rows)} row" + ("s" if len(results_rows) != 1 else "")
            ),
            "results_header_cells": _render_results_header_cells(),
            "results_rows": _render_results_rows(results_rows, jsonl_rows),
            "sparkline": sparkline,
            "sparkline_legend": sparkline_legend,
            "sparkline_aria": sparkline_aria,
        }
    )
    rendered = substitute(template, mapping)
    leftover = re.findall(r"\{\{\s*([a-zA-Z_]+)\s*\}\}", rendered)
    if leftover:
        raise RuntimeError(f"autoresearch results unresolved markers: {sorted(set(leftover))}")
    out_path = out_dir / "results" / "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    return out_path


def render_autoresearch_policies(
    policies: list[dict[str, Any]],
    mutations: list[dict[str, Any]],
    out_dir: Path,
    *,
    template: str,
    ctx: _AutoresearchRenderCtx,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    mapping = _autoresearch_base_mapping(ctx)
    mapping.update(
        {
            "policies_section_label": (
                f"{len(policies)} file" + ("s" if len(policies) != 1 else "")
            ),
            "policies_rows": _render_policies_rows(policies, mutations),
        }
    )
    rendered = substitute(template, mapping)
    leftover = re.findall(r"\{\{\s*([a-zA-Z_]+)\s*\}\}", rendered)
    if leftover:
        raise RuntimeError(f"autoresearch policies unresolved markers: {sorted(set(leftover))}")
    out_path = out_dir / "policies" / "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    return out_path


def render_autoresearch_evidence(
    mutations: list[dict[str, Any]],
    archive: list[dict[str, Any]],
    out_dir: Path,
    *,
    template: str,
    ctx: _AutoresearchRenderCtx,
    progress: dict[str, Any],
    gen0_baseline: dict[str, Any] | None,
    manifest: list[dict[str, Any]],
    repo_root: Path,
) -> Path:
    """Render the E6 evidence page (methods + results + power + live campaign) at
    ``autoresearch/evidence/index.html``.

    Reads the recorded ledgers ONLY (``mutations`` = mutations.jsonl rows;
    ``archive`` = baseline_archive.jsonl rows; ``progress`` = parsed
    campaign-progress.log; ``gen0_baseline`` = the gen-0 K-mean snapshot;
    ``manifest`` = the eval-log MANIFEST for the per-cycle Petri eval deep-link +
    seeds + dims). Every section degrades gracefully to an honest "awaiting
    campaign" / "no evidence yet" state when the matched 3-arm held-out campaign has
    not run — no crash, no fabricated number.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    mapping = _autoresearch_base_mapping(ctx)
    mapping.update(
        {
            "methods_grid": _render_evidence_methods(),
            "methods_arms": _render_evidence_methods_arms(),
            "results_arms": _render_evidence_results(mutations, archive),
            "results_verdict": _render_evidence_verdict(mutations, archive),
            "power_block": _render_evidence_power(mutations),
            # PR-HUB-CAMPAIGN-VIZ — the live per-cycle 3-arm drill-down.
            "campaign_noise_band": _render_gen0_noise_band(progress),
            "campaign_margin_rule": _render_campaign_margin_rule(gen0_baseline, progress),
            "campaign_cycles": _render_campaign_cycles(progress, mutations, manifest, repo_root),
        }
    )
    rendered = substitute(template, mapping)
    leftover = re.findall(r"\{\{\s*([a-zA-Z_]+)\s*\}\}", rendered)
    if leftover:
        raise RuntimeError(f"autoresearch evidence unresolved markers: {sorted(set(leftover))}")
    out_path = out_dir / "evidence" / "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------- #
# Run reports (per-campaign synthesis .md → /runs/ pages)                     #
# --------------------------------------------------------------------------- #
_RUN_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _run_slug(md_path: Path) -> str:
    """Slug for a run report page: filename stem with leading ``run-`` stripped.

    ``run-2606-broken-tool-use.md`` -> ``2606-broken-tool-use`` -> served at
    ``autoresearch/runs/2606-broken-tool-use/``.

    The slug becomes a filesystem path segment AND a URL segment, so it is
    validated against ``^[a-z0-9]+(?:-[a-z0-9]+)*$``. An empty / ``.`` / ``..`` /
    otherwise-unsafe slug (e.g. ``run-.md`` -> ``""``, ``run-..md`` -> ``..``)
    raises so the caller's best-effort ``_safe`` wrapper skips it rather than
    overwriting ``runs/index.html`` or escaping the runs dir.
    """
    stem = md_path.stem
    slug = stem[len("run-") :] if stem.startswith("run-") else stem
    if not _RUN_SLUG_RE.match(slug):
        raise ValueError(
            f"unsafe run-report slug {slug!r} from {md_path.name!r}; "
            "expected lowercase alphanumeric segments joined by '-'"
        )
    return slug


def _run_title(md_body: str, fallback: str) -> str:
    """Title from the markdown's first ``# `` heading; ``fallback`` if none."""
    for line in md_body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def render_autoresearch_runs_index(
    md_files: list[Path],
    out_dir: Path,
    *,
    template: str,
    ctx: _AutoresearchRenderCtx,
) -> Path:
    """Render the runs catalog at ``autoresearch/runs/index.html``.

    Dense list — one link per discovered ``run-*.md`` (title from the md's first
    ``# `` heading, link to ``runs/<slug>/``). Degrades to an honest empty state
    when no run report has been authored yet.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    sorted_files = sorted((p for p in md_files if p.is_file()), key=lambda p: p.name)
    items: list[str] = []
    seen_slugs: set[str] = set()
    for md_path in sorted_files:
        try:
            slug = _run_slug(md_path)
        except ValueError:
            LOG.warning("skipping run report with unsafe slug: %s", md_path.name)
            continue
        if slug in seen_slugs:
            LOG.warning("skipping run report with duplicate slug %r: %s", slug, md_path.name)
            continue
        seen_slugs.add(slug)
        title = _run_title(md_path.read_text(encoding="utf-8"), slug)
        link = f"/geode/self-improving/autoresearch/runs/{html_escape(slug)}/"
        items.append(
            f'        <li><a href="{link}">{html_escape(title)}</a> '
            f"<code>{html_escape(slug)}</code></li>"
        )
    if not items:
        runs_list = '<p class="page-sub">No run reports yet.</p>'
    else:
        runs_list = '    <ul class="nav-list run-report-list">\n' + "\n".join(items) + "\n    </ul>"
    mapping = _autoresearch_base_mapping(ctx)
    mapping.update(
        {
            "runs_section_label": (f"{len(items)} report" + ("s" if len(items) != 1 else "")),
            "runs_list": runs_list,
        }
    )
    rendered = substitute(template, mapping)
    leftover = re.findall(r"\{\{\s*([a-zA-Z_]+)\s*\}\}", rendered)
    if leftover:
        raise RuntimeError(f"autoresearch runs index unresolved markers: {sorted(set(leftover))}")
    out_path = out_dir / "runs" / "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    return out_path


def render_autoresearch_run_report(
    md_path: Path,
    out_dir: Path,
    *,
    template: str,
    ctx: _AutoresearchRenderCtx,
    repo_root: Path,
) -> Path:
    """Render one run report at ``autoresearch/runs/<slug>/index.html``.

    Embeds ``md_path.read_text()`` via the shared Marked.js pattern (the body is
    html-escaped into a ``<script type="text/markdown">`` block + an empty
    ``<article class="markdown-body">`` target — never duplicated into the HTML).
    """
    md_body = md_path.read_text(encoding="utf-8")
    slug = _run_slug(md_path)
    title = _run_title(md_body, slug)
    try:
        source_rel = md_path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        source_rel = md_path.name
    # The body is operator-authored prose rendered CLIENT-SIDE by Marked.js, so
    # its links never reach the static href-safety scan. Warn (don't fail — this
    # is content, not chrome) on a root-absolute markdown link that misses the
    # ``/geode/`` basePath, the one form that 404s on the live Pages site.
    for href in re.findall(r"\]\((/[^)\s]*)\)", md_body):
        if not href.startswith("/geode/"):
            LOG.warning(
                "run report %s has a root-absolute link missing the /geode/ basePath: %s",
                md_path.name,
                href,
            )
    # Fill the chrome markers FIRST and validate that none are left UNRESOLVED —
    # but do the marker scan BEFORE injecting the (operator-authored) markdown
    # body. A run report whose prose / code block legitimately contains a
    # ``{{ ... }}`` token would otherwise be misread as an unresolved template
    # marker and fail the build. The body is substituted last, so the only
    # ``{{ }}`` the validator sees come from the template, never the content.
    mapping = _autoresearch_base_mapping(ctx)
    mapping.update(
        {
            "run_title": html_escape(title),
            "run_source_path": html_escape(source_rel),
            "marked_js_loader": _marked_js_loader_html(),
        }
    )
    chrome = substitute(template, mapping)
    leftover = re.findall(r"\{\{\s*([a-zA-Z_]+)\s*\}\}", chrome)
    # ``run_body`` is the one marker still expected at this point.
    leftover = [m for m in leftover if m != "run_body"]
    if leftover:
        raise RuntimeError(f"autoresearch run report unresolved markers: {sorted(set(leftover))}")
    rendered = substitute(chrome, {"run_body": html_escape(md_body)})
    out_path = out_dir / "runs" / slug / "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------- #
# Substitution + write                                                        #
# --------------------------------------------------------------------------- #
def substitute(template: str, mapping: dict[str, str]) -> str:
    out = template
    for key, value in mapping.items():
        out = out.replace("{{ " + key + " }}", value)
    return out


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--bundle-root", type=Path, default=DEFAULT_BUNDLE_ROOT)
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="self-improving state dir (default: state/autoresearch)",
    )
    # Back-compat (PR-STATE-SELF-IMPROVING-RENAME 2026-06-01): older invocations
    # + the e2e fixtures pass the dir CONTAINING ``state/``. When given, the
    # state dir resolves to ``<value>/state``. Prefer ``--state-dir``.
    parser.add_argument("--autoresearch-root", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--template", type=Path, default=TEMPLATE_PATH)
    parser.add_argument("--pyproject", type=Path, default=PYPROJECT)
    parser.add_argument(
        "--seedgen-out-dir",
        type=Path,
        default=DEFAULT_SEEDGEN_OUT_DIR,
        help="Output dir for seed-generation index + per-run pages.",
    )
    parser.add_argument(
        "--seedgen-index-template",
        type=Path,
        default=SEEDGEN_INDEX_TEMPLATE,
    )
    parser.add_argument(
        "--seedgen-run-template",
        type=Path,
        default=SEEDGEN_RUN_TEMPLATE,
    )
    parser.add_argument(
        "--autoresearch-out-dir",
        type=Path,
        default=DEFAULT_AUTORESEARCH_OUT_DIR,
        help="Output dir for autoresearch landing + 4 sub-view pages.",
    )
    parser.add_argument(
        "--autoresearch-landing-template",
        type=Path,
        default=AUTORESEARCH_LANDING_TEMPLATE,
    )
    parser.add_argument(
        "--autoresearch-baseline-template",
        type=Path,
        default=AUTORESEARCH_BASELINE_TEMPLATE,
    )
    parser.add_argument(
        "--autoresearch-mutations-template",
        type=Path,
        default=AUTORESEARCH_MUTATIONS_TEMPLATE,
    )
    parser.add_argument(
        "--autoresearch-results-template",
        type=Path,
        default=AUTORESEARCH_RESULTS_TEMPLATE,
    )
    parser.add_argument(
        "--autoresearch-policies-template",
        type=Path,
        default=AUTORESEARCH_POLICIES_TEMPLATE,
    )
    parser.add_argument(
        "--autoresearch-evidence-template",
        type=Path,
        default=AUTORESEARCH_EVIDENCE_TEMPLATE,
    )
    parser.add_argument(
        "--autoresearch-runs-index-template",
        type=Path,
        default=AUTORESEARCH_RUNS_INDEX_TEMPLATE,
    )
    parser.add_argument(
        "--autoresearch-run-report-template",
        type=Path,
        default=AUTORESEARCH_RUN_REPORT_TEMPLATE,
    )
    parser.add_argument(
        "--run-reports-dir",
        type=Path,
        default=DEFAULT_RUN_REPORTS_DIR,
        help=(
            "Dir scanned for run-*.md synthesis files (default: docs/self-improving). "
            "Each becomes an autoresearch/runs/<slug>/ page."
        ),
    )
    args = parser.parse_args(argv)

    # Resolve the canonical state dir from the two accepted spellings.
    # ``--state-dir`` wins; ``--autoresearch-root`` is the legacy
    # "dir containing state/" spelling → ``<root>/state``; default is
    # the production ``state/autoresearch``.
    if args.state_dir is not None:
        state_dir = args.state_dir
    elif args.autoresearch_root is not None:
        state_dir = args.autoresearch_root / "state"
    else:
        state_dir = DEFAULT_STATE_DIR

    LOG.info("bundle-root=%s", args.bundle_root)
    LOG.info("state-dir=%s", state_dir)

    version = read_pyproject_version(args.pyproject)
    LOG.info("geode version=%s", version)

    petri_rows = load_petri(args.bundle_root)
    seedgen_rows = load_seedgen(args.bundle_root)
    autoresearch = load_autoresearch(state_dir)

    LOG.info(
        "loaded petri=%d seedgen=%d mutations=%d results=%d policies=%d",
        len(petri_rows),
        len(seedgen_rows),
        autoresearch.mutations_count,
        autoresearch.results_count,
        autoresearch.policies_count,
    )

    petri_section_label = f"{len(petri_rows)} archive" + ("s" if len(petri_rows) != 1 else "")
    seedgen_section_label = f"{len(seedgen_rows)} run" + ("s" if len(seedgen_rows) != 1 else "")
    autoresearch_status_label = (
        "stale"
        if autoresearch.baseline_stale
        else ("live" if autoresearch.baseline_path is not None else "absent")
    )

    build_date = _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%d %H:%M")

    template = args.template.read_text(encoding="utf-8")

    mapping: dict[str, str] = {
        "petri_count": str(len(petri_rows)),
        "petri_section_label": petri_section_label,
        "petri_rows": render_petri_rows(petri_rows),
        "sidebar_petri_recent": render_sidebar_petri(petri_rows),
        "seedgen_count_label": (
            f"{len(seedgen_rows)} run" + ("s" if len(seedgen_rows) != 1 else "")
        ),
        "seedgen_section_label": seedgen_section_label,
        "seedgen_rows": render_seedgen_rows(seedgen_rows),
        "sidebar_seedgen_runs": render_sidebar_seedgen(seedgen_rows),
        "autoresearch_status_label": autoresearch_status_label,
        "autoresearch_rows": render_autoresearch_rows(autoresearch),
        "stale_baseline_warning": render_stale_banner(autoresearch),
        "geode_version": version,
        "design_schema_version": str(DESIGN_SCHEMA_VERSION),
        "build_date": build_date,
    }

    rendered = substitute(template, mapping)

    # Sanity: any remaining {{ }} markers would mean a missing key.
    leftover = re.findall(r"\{\{\s*([a-zA-Z_]+)\s*\}\}", rendered)
    if leftover:
        LOG.error("unfilled template markers: %s", sorted(set(leftover)))
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")
    LOG.info("wrote %s (%d bytes)", args.out, args.out.stat().st_size)

    # ----------------------------------------------------------------- #
    # Seed-generation surface (index + per-run detail pages)            #
    # ----------------------------------------------------------------- #
    seeds_listing_path = args.bundle_root / "seeds" / "listing.json"
    seeds_raw_listing: dict[str, Any] = {}
    if seeds_listing_path.exists():
        try:
            seeds_raw_listing = json.loads(seeds_listing_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            LOG.warning("seedgen listing parse error: %s", seeds_listing_path)
            seeds_raw_listing = {}

    seedgen_index_template = args.seedgen_index_template.read_text(encoding="utf-8")
    seedgen_run_template = args.seedgen_run_template.read_text(encoding="utf-8")

    seedgen_count_label_value = f"{len(seedgen_rows)} run" + ("s" if len(seedgen_rows) != 1 else "")
    sidebar_petri_recent_html = render_sidebar_petri(petri_rows)
    sidebar_seedgen_runs_html = render_sidebar_seedgen(seedgen_rows)

    index_path = render_seedgen_index(
        seeds_raw_listing,
        seedgen_rows,
        args.seedgen_out_dir,
        template=seedgen_index_template,
        petri_count=len(petri_rows),
        seedgen_count_label=seedgen_count_label_value,
        autoresearch_status_label=autoresearch_status_label,
        sidebar_petri_recent=sidebar_petri_recent_html,
        sidebar_seedgen_runs=sidebar_seedgen_runs_html,
        geode_version=version,
        build_date=build_date,
    )
    LOG.info("wrote seedgen index %s (%d bytes)", index_path, index_path.stat().st_size)

    seeds_dir = args.bundle_root / "seeds"
    for run in seedgen_rows:
        state, survivors_doc, meta_doc = _load_per_run(seeds_dir, run.run_id)
        run_path = render_seedgen_run(
            run,
            state,
            survivors_doc,
            meta_doc,
            args.seedgen_out_dir,
            template=seedgen_run_template,
            petri_count=len(petri_rows),
            seedgen_count_label=seedgen_count_label_value,
            autoresearch_status_label=autoresearch_status_label,
            sidebar_petri_recent=sidebar_petri_recent_html,
            sidebar_seedgen_runs=sidebar_seedgen_runs_html,
            geode_version=version,
            build_date=build_date,
            run_bundle_dir=seeds_dir / run.run_id,
        )
        LOG.info("wrote seedgen run %s (%d bytes)", run_path, run_path.stat().st_size)

    # PR-SEEDS-HIRES P3 (2026-05-26) — cross-run /active/ live dashboard.
    active_path = render_seedgen_active(
        seeds_dir,
        args.seedgen_out_dir,
        sidebar_petri_recent=sidebar_petri_recent_html,
        sidebar_seedgen_runs=sidebar_seedgen_runs_html,
        petri_count=len(petri_rows),
        seedgen_count_label=seedgen_count_label_value,
        autoresearch_status_label=autoresearch_status_label,
        geode_version=version,
        build_date=build_date,
    )
    LOG.info("wrote seedgen active %s (%d bytes)", active_path, active_path.stat().st_size)

    # ----------------------------------------------------------------- #
    # Autoresearch surface (5 sub-pages — P6)                          #
    # Each renderer is best-effort: failure of one doesn't block the   #
    # others. The autoresearch_status_label / mtimes / counts come     #
    # from the existing `autoresearch` AutoresearchState dataclass     #
    # already loaded above for the hub landing.                        #
    # ----------------------------------------------------------------- #
    ar_state_dir = state_dir
    baseline_data, baseline_stale, baseline_source = _load_baseline(ar_state_dir)
    archive_rows = _load_baseline_archive(ar_state_dir)
    mutations_rows = _load_mutations(ar_state_dir)
    results_tsv_rows = _load_results_tsv(ar_state_dir)
    results_jsonl_rows = _load_results_jsonl(ar_state_dir)
    policies_entries = _list_policies(ar_state_dir / "policies")
    # PR-HUB-CAMPAIGN-VIZ — the live 3-arm campaign ledgers. The campaign-progress.log
    # sits in the self-improving state dir; the gen-0 snapshot + the eval-log MANIFEST
    # live under the repo root. With the canonical layout the state dir is
    # ``<repo>/state/autoresearch`` so the repo root is two levels up; with the
    # legacy ``--autoresearch-root <X>`` spelling it is ``<X>/state`` → also two up.
    campaign_progress = _load_campaign_progress(ar_state_dir)
    campaign_repo_root = state_dir.parent.parent
    campaign_gen0_baseline = _load_campaign_gen0_baseline(campaign_repo_root)
    audit_manifest = _load_audit_manifest(campaign_repo_root)

    LOG.info(
        "autoresearch loaded baseline=%s stale=%s archive=%d mutations=%d "
        "results_tsv=%d results_jsonl=%d policies=%d",
        baseline_source.name if baseline_source else "(none)",
        baseline_stale,
        len(archive_rows),
        len(mutations_rows),
        len(results_tsv_rows),
        len(results_jsonl_rows),
        len(policies_entries),
    )

    ar_ctx = _AutoresearchRenderCtx(
        sidebar_petri_recent=sidebar_petri_recent_html,
        sidebar_seedgen_runs=sidebar_seedgen_runs_html,
        petri_count=len(petri_rows),
        seedgen_count_label=seedgen_count_label_value,
        autoresearch_status_label=autoresearch_status_label,
        geode_version=version,
        build_date=build_date,
    )

    # E6 (2026-05-30) — held-out point count drives the landing sub-view row's
    # "N held-out points" / "awaiting campaign" label (the same recorded data the
    # evidence page synthesises). Counts attribution rows carrying held_out_fitness.
    held_out_count = len(_held_out_attribution_rows(mutations_rows))

    # Each renderer runs independently; log and continue on failure so
    # one broken page doesn't prevent the others from publishing.
    def _safe(name: str, fn: Any) -> None:
        try:
            path = fn()
            LOG.info("wrote autoresearch %s (%d bytes)", path, path.stat().st_size)
        except Exception:
            # Best-effort per page — log + continue so one broken
            # renderer doesn't block the others from publishing.
            LOG.exception("autoresearch %s render failed", name)

    _safe(
        "landing",
        lambda: render_autoresearch_landing(
            baseline_data,
            baseline_source,
            baseline_stale,
            archive_rows,
            mutations_count=autoresearch.mutations_count,
            mutations_mtime=autoresearch.mutations_mtime,
            results_count=len(results_tsv_rows),
            results_mtime=autoresearch.results_mtime,
            policies_count=len(policies_entries),
            policies_mtime=autoresearch.policies_mtime,
            baseline_mtime=autoresearch.baseline_mtime,
            out_dir=args.autoresearch_out_dir,
            template=args.autoresearch_landing_template.read_text(encoding="utf-8"),
            ctx=ar_ctx,
            held_out_count=held_out_count,
        ),
    )
    baseline_transcripts = _load_baseline_transcripts(
        args.autoresearch_out_dir / "baseline" / "transcripts.json"
    )
    _safe(
        "baseline",
        lambda: render_autoresearch_baseline(
            baseline_data,
            baseline_source,
            baseline_stale,
            args.autoresearch_out_dir,
            template=args.autoresearch_baseline_template.read_text(encoding="utf-8"),
            ctx=ar_ctx,
            transcripts=baseline_transcripts,
        ),
    )
    _safe(
        "mutations",
        lambda: render_autoresearch_mutations(
            mutations_rows,
            args.autoresearch_out_dir,
            template=args.autoresearch_mutations_template.read_text(encoding="utf-8"),
            ctx=ar_ctx,
        ),
    )
    _safe(
        "results",
        lambda: render_autoresearch_results(
            results_tsv_rows,
            results_jsonl_rows,
            args.autoresearch_out_dir,
            template=args.autoresearch_results_template.read_text(encoding="utf-8"),
            ctx=ar_ctx,
        ),
    )
    _safe(
        "policies",
        lambda: render_autoresearch_policies(
            policies_entries,
            mutations_rows,
            args.autoresearch_out_dir,
            template=args.autoresearch_policies_template.read_text(encoding="utf-8"),
            ctx=ar_ctx,
        ),
    )
    _safe(
        "evidence",
        lambda: render_autoresearch_evidence(
            mutations_rows,
            archive_rows,
            args.autoresearch_out_dir,
            template=args.autoresearch_evidence_template.read_text(encoding="utf-8"),
            ctx=ar_ctx,
            progress=campaign_progress,
            gen0_baseline=campaign_gen0_baseline,
            manifest=audit_manifest,
            repo_root=campaign_repo_root,
        ),
    )

    # ----------------------------------------------------------------- #
    # Run reports (PR-HUB-RUN-REPORT) — autoresearch/runs/ index +      #
    # one /runs/<slug>/ page per docs/self-improving/run-*.md synthesis #
    # file, rendered client-side via the shared Marked.js loader        #
    # (single SoT, never duplicated into the HTML). Globbed from the    #
    # source-doc dir (NOT the out dir) so authoring a new run-*.md      #
    # auto-registers it.                                                #
    # ----------------------------------------------------------------- #
    run_report_files = sorted(p for p in args.run_reports_dir.glob(RUN_REPORT_GLOB) if p.is_file())
    LOG.info("run reports discovered=%d under %s", len(run_report_files), args.run_reports_dir)
    runs_index_template = args.autoresearch_runs_index_template.read_text(encoding="utf-8")
    run_report_template = args.autoresearch_run_report_template.read_text(encoding="utf-8")
    _safe(
        "runs-index",
        lambda: render_autoresearch_runs_index(
            run_report_files,
            args.autoresearch_out_dir,
            template=runs_index_template,
            ctx=ar_ctx,
        ),
    )
    for md_path in run_report_files:
        _safe(
            f"run-report:{md_path.name}",
            lambda md_path=md_path: render_autoresearch_run_report(
                md_path,
                args.autoresearch_out_dir,
                template=run_report_template,
                ctx=ar_ctx,
                repo_root=campaign_repo_root,
            ),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
