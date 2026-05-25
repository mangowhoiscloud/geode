#!/usr/bin/env python3
"""Build `docs/self-improving/index.html` for the GEODE Self-Improving Hub.

Reads live data at build time and renders the static landing page:

- `docs/self-improving/petri-bundle/logs/listing.json`     -> Petri audit table (top-10)
- `docs/self-improving/petri-bundle/seeds/listing.json`    -> Seed-generation table
- `autoresearch/state/baseline.json`        -> Autoresearch baseline row
   (falls back to most recent `baseline.json.outdated-*` with a stale flag
   per design contract §10 of the master DESIGN.md)
- `autoresearch/state/mutations.jsonl`      -> row count for autoresearch row
- `autoresearch/results.tsv`                -> row count for autoresearch row
- `autoresearch/state/policies/`            -> file count
- `pyproject.toml`                          -> GEODE version stamp

Page contract:   docs/design/self-improving-hub.md
Master tokens:   docs/design/self-improving-hub-system.md

CLI:
    python scripts/build_self_improving_hub.py
        [--bundle-root docs/self-improving/petri-bundle]
        [--autoresearch-root autoresearch]
        [--out docs/self-improving/index.html]

NOTE: `--bundle-root` defaults to `docs/self-improving/petri-bundle/` (post-Phase 3)
relocation the bundle moves to `docs/self-improving/petri-bundle/`; update the
default (or the CI invocation) accordingly.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOG = logging.getLogger("build_self_improving_hub")

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "docs" / "self-improving" / "index.html.template"
DEFAULT_BUNDLE_ROOT = REPO_ROOT / "docs" / "self-improving" / "petri-bundle"
DEFAULT_AUTORESEARCH_ROOT = REPO_ROOT / "autoresearch"
DEFAULT_OUT = REPO_ROOT / "docs" / "self-improving" / "index.html"
PYPROJECT = REPO_ROOT / "pyproject.toml"

DESIGN_SCHEMA_VERSION = 1
PETRI_ROW_LIMIT = 10
PETRI_SIDEBAR_LIMIT = 3

# Map provider prefix (model.split("/")[0]) -> chip class + chip label.
# Per master DESIGN.md §3 — 4 chips only; palette explosion forbidden.
HARNESS_MAP: dict[str, tuple[str, str]] = {
    "anthropic": ("payg", "PAYG"),
    "openai": ("payg", "PAYG"),
    "claude-cli": ("claude", "Claude Code"),
    "codex": ("codex", "Codex Plus"),
    "openai-codex": ("codex", "Codex Plus"),
    "geode": ("geode", "GEODE"),
}


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def html_escape(value: str) -> str:
    """Minimal HTML escape — no external dep."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


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


def harness_chip(model: str) -> str:
    """Render a `<span class="chip ...">label</span> <code>model</code>` cell."""
    if not model:
        return '<span class="muted">.</span>'
    prefix = model.split("/", 1)[0]
    cls, label = HARNESS_MAP.get(prefix, ("payg", "PAYG"))
    return (
        f'<span class="chip {cls}">{html_escape(label)}</span> '
        f"<code>{html_escape(model)}</code>"
    )


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


def load_petri(bundle_root: Path) -> list[PetriRow]:
    listing = bundle_root / "logs" / "listing.json"
    if not listing.exists():
        LOG.warning("petri listing missing: %s", listing)
        return []
    raw: dict[str, dict[str, Any]] = json.loads(listing.read_text(encoding="utf-8"))
    rows: list[PetriRow] = []
    for entry in raw.values():
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


def load_autoresearch(autoresearch_root: Path) -> AutoresearchState:
    state_dir = autoresearch_root / "state"
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

    results_path = autoresearch_root / "results.tsv"
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
        anchor = (
            f"/geode/self-improving/petri-bundle/#/tasks/{html_escape(row.task_id)}"
        )
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
            f'          <td class="num">${row.usd_spent:.2f}</td>\n'
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
            "<code>uv run python autoresearch/train.py --promote</code></span>"
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
            f'policies/ ({state.policies_count} files)</a> '
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
        anchor = (
            f"/geode/self-improving/petri-bundle/#/tasks/{html_escape(row.task_id)}"
        )
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
        "Autoresearch baseline is stale &mdash; rendering from "
        f"<code>{html_escape(state.baseline_path.name if state.baseline_path else '')}</code>. "
        "No live <code>baseline.json</code> present in <code>autoresearch/state/</code>."
        "</div>"
    )


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
    parser.add_argument("--autoresearch-root", type=Path, default=DEFAULT_AUTORESEARCH_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--template", type=Path, default=TEMPLATE_PATH)
    parser.add_argument("--pyproject", type=Path, default=PYPROJECT)
    args = parser.parse_args(argv)

    LOG.info("bundle-root=%s", args.bundle_root)
    LOG.info("autoresearch-root=%s", args.autoresearch_root)

    version = read_pyproject_version(args.pyproject)
    LOG.info("geode version=%s", version)

    petri_rows = load_petri(args.bundle_root)
    seedgen_rows = load_seedgen(args.bundle_root)
    autoresearch = load_autoresearch(args.autoresearch_root)

    LOG.info(
        "loaded petri=%d seedgen=%d mutations=%d results=%d policies=%d",
        len(petri_rows),
        len(seedgen_rows),
        autoresearch.mutations_count,
        autoresearch.results_count,
        autoresearch.policies_count,
    )

    petri_section_label = f"{len(petri_rows)} archive" + (
        "s" if len(petri_rows) != 1 else ""
    )
    seedgen_section_label = (
        f"{len(seedgen_rows)} run" + ("s" if len(seedgen_rows) != 1 else "")
    )
    autoresearch_status_label = "stale" if autoresearch.baseline_stale else (
        "live" if autoresearch.baseline_path is not None else "absent"
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
