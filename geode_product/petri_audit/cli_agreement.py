"""``geode audit-agreement`` — judge ↔ human agreement CLI sub-app.

A thin Typer front end over the pure functions in
``core.audit.judge_agreement``. Four commands:

- ``extract``     stage a deterministic, stratified pilot of blind items.
- ``label``       interactive, resumable, BLIND labeling loop (the human
                  scores before the judge's score is revealed).
- ``report``      compute per-dim weighted Cohen's kappa + overall
                  Krippendorff's alpha and render the report.
- ``recalibrate`` emit judge-recalibration proposals from the disagreements.

The interactive loop is the only stateful part; the resume logic it relies
on (``pending_items``) and every statistic are unit-tested in
``core.audit.judge_agreement`` so this module stays I/O-only.

Blinding is enforced here: :func:`_label_one` prints the excerpt + rubric and
reads the human score *before* it echoes the judge's score.
"""

from __future__ import annotations

import glob
import logging
import time
from collections import Counter
from pathlib import Path
from typing import Annotated

import typer
from core.audit.judge_agreement import (
    AgreementItem,
    append_label,
    compute_report,
    extract_pairs,
    pending_items,
    read_items,
    read_labels,
    render_recalibration,
    render_report,
    write_items,
)
from core.paths import GLOBAL_AUDIT_AGREEMENT_DIR, PETRI_LOGS_DIR

log = logging.getLogger(__name__)

__all__ = ["audit_agreement_app"]

audit_agreement_app = typer.Typer(
    name="audit-agreement",
    help="Validate the LLM judge against human labels (external-anchor agreement).",
    no_args_is_help=True,
    add_completion=False,
)

_DEFAULT_ITEMS = GLOBAL_AUDIT_AGREEMENT_DIR / "items.jsonl"
_DEFAULT_LABELS = GLOBAL_AUDIT_AGREEMENT_DIR / "labels.jsonl"


@audit_agreement_app.command("extract")
def extract(
    total: Annotated[int, typer.Option("--total", "-n", help="Total items across all dims.")] = 20,
    seed: Annotated[int, typer.Option("--seed", help="Deterministic sampling seed.")] = 0,
    logs_dir: Annotated[
        Path, typer.Option("--logs-dir", help="Directory of .eval archives to sample from.")
    ] = PETRI_LOGS_DIR,
    out: Annotated[
        Path, typer.Option("--out", help="Where to write the pilot items JSONL.")
    ] = _DEFAULT_ITEMS,
) -> None:
    """Stage a blind, stratified pilot of labeling items from the .eval logs."""
    archives = sorted(glob.glob(str(Path(logs_dir).expanduser() / "*.eval")))
    if not archives:
        typer.echo(f"No .eval archives under {logs_dir}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Scanning {len(archives)} archives (seed={seed}, target={total}) …")
    items = extract_pairs(archives, total=total, seed=seed)
    if not items:
        typer.echo("No items extracted. Is the [audit] extra installed (inspect_ai)?", err=True)
        raise typer.Exit(1)
    write_items(items, out)
    dist = Counter(it.dimension for it in items)
    typer.echo(f"Wrote {len(items)} items → {out}")
    typer.echo("Per-dim distribution:")
    for dim, count in sorted(dist.items()):
        typer.echo(f"  {dim:<24} {count}")
    typer.echo(f"\nNext: geode audit-agreement label --items {out}")


def _read_score(prompt: str) -> float | None | str:
    """Read a 1–10 score, ``s`` (skip) or ``q`` (quit). Reprompts on bad input."""
    while True:
        raw = typer.prompt(prompt, default="").strip().lower()
        if raw in ("q", "quit"):
            return "quit"
        if raw in ("s", "skip", ""):
            return None
        try:
            val = int(raw)
        except ValueError:
            typer.echo("  Enter a whole number 1–10, or s=skip, q=quit.")
            continue
        if 1 <= val <= 10:
            return float(val)
        typer.echo("  Out of range. Score must be 1–10.")


def _label_one(item: AgreementItem, labeler: str, labels_path: Path) -> str:
    """Present one item BLIND, read the human score, then reveal the judge's.

    Returns ``"quit"`` to stop the session, ``"skip"`` to move on without a
    label, or ``"labeled"`` after appending a label record.
    """
    typer.echo("=" * 78)
    typer.echo(f"Item {item.item_id}  ·  dimension: {item.dimension}")
    typer.echo("-" * 78)
    typer.echo(item.rubric)
    typer.echo("-" * 78)
    typer.echo("TRANSCRIPT EXCERPT (judge score hidden):")
    typer.echo(item.excerpt or "(excerpt unavailable for this sample)")
    typer.echo("-" * 78)
    result = _read_score("Your score 1–10 (s=skip, q=quit)")
    if result == "quit":
        return "quit"
    if result is None:
        typer.echo("  skipped.")
        return "skip"
    human_score = float(result)
    # Reveal only AFTER the human has committed.
    typer.echo(
        f"  → judge scored this {item.judge_score:.0f} (Δ = {item.judge_score - human_score:+.0f})"
    )
    from core.audit.judge_agreement import LabelRecord

    append_label(
        LabelRecord(
            item_id=item.item_id,
            human_score=human_score,
            labeler=labeler,
            ts=time.time(),
            dimension=item.dimension,
            judge_score=item.judge_score,
        ),
        labels_path,
    )
    return "labeled"


@audit_agreement_app.command("label")
def label(
    items: Annotated[Path, typer.Option("--items", help="Pilot items JSONL.")] = _DEFAULT_ITEMS,
    labels: Annotated[
        Path, typer.Option("--labels", help="Label ledger JSONL (append).")
    ] = _DEFAULT_LABELS,
    labeler: Annotated[
        str, typer.Option("--labeler", help="Labeler identity recorded per row.")
    ] = "human",
) -> None:
    """Blind, resumable labeling loop — score each excerpt before the judge's
    number is shown. Already-labeled items are skipped, so ``q`` then re-run
    picks up where you left off."""
    staged = read_items(items)
    if not staged:
        typer.echo(f"No items at {items}. Run `geode audit-agreement extract` first.", err=True)
        raise typer.Exit(1)
    existing = read_labels(labels)
    todo = pending_items(staged, existing)
    typer.echo(f"{len(staged)} staged · {len(existing)} labeled · {len(todo)} remaining\n")
    if not todo:
        typer.echo("All items labeled. Run `geode audit-agreement report`.")
        return
    labeled = 0
    for item in todo:
        outcome = _label_one(item, labeler, Path(labels).expanduser())
        if outcome == "quit":
            typer.echo("\nStopped. Re-run the same command to resume.")
            break
        if outcome == "labeled":
            labeled += 1
    typer.echo(f"\nLabeled {labeled} this session → {labels}")


@audit_agreement_app.command("report")
def report(
    items: Annotated[Path, typer.Option("--items", help="Pilot items JSONL.")] = _DEFAULT_ITEMS,
    labels: Annotated[Path, typer.Option("--labels", help="Label ledger JSONL.")] = _DEFAULT_LABELS,
    out_dir: Annotated[
        Path, typer.Option("--out-dir", help="Directory for report.txt + recalibration.md.")
    ] = GLOBAL_AUDIT_AGREEMENT_DIR,
) -> None:
    """Compute per-dim weighted Cohen's kappa + overall Krippendorff's alpha."""
    staged = read_items(items)
    labs = read_labels(labels)
    rep = compute_report(staged, labs)
    text = render_report(rep)
    typer.echo(text)
    out = Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.txt").write_text(text + "\n", encoding="utf-8")
    (out / "recalibration.md").write_text(
        render_recalibration(rep, staged) + "\n", encoding="utf-8"
    )
    typer.echo(f"\nWrote {out / 'report.txt'} and {out / 'recalibration.md'}")


@audit_agreement_app.command("recalibrate")
def recalibrate(
    items: Annotated[Path, typer.Option("--items", help="Pilot items JSONL.")] = _DEFAULT_ITEMS,
    labels: Annotated[Path, typer.Option("--labels", help="Label ledger JSONL.")] = _DEFAULT_LABELS,
    out_dir: Annotated[
        Path, typer.Option("--out-dir", help="Directory for recalibration.md.")
    ] = GLOBAL_AUDIT_AGREEMENT_DIR,
) -> None:
    """Emit judge-recalibration proposals (human anchor → judge skew → edit)."""
    staged = read_items(items)
    labs = read_labels(labels)
    rep = compute_report(staged, labs)
    text = render_recalibration(rep, staged)
    typer.echo(text)
    out = Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    (out / "recalibration.md").write_text(text + "\n", encoding="utf-8")
    typer.echo(f"\nWrote {out / 'recalibration.md'}")
