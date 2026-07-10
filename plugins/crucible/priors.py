"""Git-tracked class-prior store plus the campaign-fold writer.

Calibration reads mutation-class priors; without a writer that folds each
campaign's measured flips back into them, the priors silently rot (the
read-write parity failure the scaffold forbids). Priors live as tracked JSON
under ``plugins/crucible/priors/`` — one file per class — each pinned to the
task-pack hash its evidence was measured against.

Train campaigns update only the fix-rate posterior: an enriched train pack
has no untargeted control stratum, so regression evidence must come from
full-pack (sealed) stages and is deliberately not folded here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from plugins.crucible.calibration import MutationClassPrior
from plugins.crucible.contract import ContractError

PRIOR_SCHEMA = "crucible.class-prior.v1"
PRIORS_DIR = Path(__file__).resolve().parent / "priors"


def load_prior(path: Path) -> MutationClassPrior:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read class prior {path}: {exc}") from exc
    if not isinstance(row, dict) or row.get("schema") != PRIOR_SCHEMA:
        raise ContractError(f"class prior {path} must use {PRIOR_SCHEMA!r}")
    try:
        return MutationClassPrior(
            class_name=str(row["class_name"]),
            fix_alpha=float(row["fix_alpha"]),
            fix_beta=float(row["fix_beta"]),
            regression_alpha=float(row["regression_alpha"]),
            regression_beta=float(row["regression_beta"]),
            task_pack_sha256=str(row["task_pack_sha256"]),
            source=str(row["source"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError(f"class prior {path} is malformed: {exc}") from exc


def save_prior(
    prior: MutationClassPrior,
    path: Path,
    *,
    history_entry: dict[str, Any] | None = None,
) -> None:
    history: list[dict[str, Any]] = []
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            recorded = existing.get("history", [])
            if isinstance(recorded, list):
                history = [item for item in recorded if isinstance(item, dict)]
    if history_entry is not None:
        history.append(history_entry)
    payload = {
        "schema": PRIOR_SCHEMA,
        **prior.to_dict(),
        "history": history,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def update_prior_from_campaign(prior_path: Path, state_dir: Path) -> MutationClassPrior:
    """Fold one campaign's measured attempts into the fix-rate posterior.

    Reads the campaign ledger's ``target_flips`` / ``task_count`` emits for
    every measured attempt (KEEP or REJECT — INVALID rows carry no admissible
    evidence). Every attempt's task-pack hash must equal the prior's pin;
    otherwise the campaign measured a different pack and folding it would
    poison the posterior (the phantom-prior guard, write side).
    """
    prior = load_prior(prior_path)
    ledger_path = state_dir / "ledger.jsonl"
    try:
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractError(f"cannot read campaign ledger {ledger_path}: {exc}") from exc
    fix_alpha = prior.fix_alpha
    fix_beta = prior.fix_beta
    folded_attempts = 0
    campaign_id: str | None = None
    for line in lines:
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict) or record.get("kind") != "train_attempt":
            continue
        campaign_id = record.get("campaign_id", campaign_id)
        if record.get("outcome") not in ("KEEP", "REJECT"):
            continue
        flips = record.get("target_flips")
        task_count = record.get("task_count")
        pack_sha = record.get("task_pack_sha256")
        if flips is None or task_count is None:
            continue
        if pack_sha != prior.task_pack_sha256:
            raise ContractError(
                f"campaign attempt {record.get('attempt_id')} measured task pack "
                f"{str(pack_sha)[:12]}… but prior {prior.class_name!r} is pinned to "
                f"{prior.task_pack_sha256[:12]}… — refit instead of folding"
            )
        flips_int = int(flips)
        task_count_int = int(task_count)
        if not 0 <= flips_int <= task_count_int:
            raise ContractError(
                f"campaign attempt {record.get('attempt_id')} has inconsistent "
                f"flip counts ({flips_int}/{task_count_int})"
            )
        fix_alpha += flips_int
        fix_beta += task_count_int - flips_int
        folded_attempts += 1
    if folded_attempts == 0:
        raise ContractError(f"campaign at {state_dir} contains no measured attempts to fold")
    updated = MutationClassPrior(
        class_name=prior.class_name,
        fix_alpha=fix_alpha,
        fix_beta=fix_beta,
        regression_alpha=prior.regression_alpha,
        regression_beta=prior.regression_beta,
        task_pack_sha256=prior.task_pack_sha256,
        source=f"{prior.source} + campaign {campaign_id or state_dir.name}",
    )
    save_prior(
        updated,
        prior_path,
        history_entry={
            "campaign_id": campaign_id or state_dir.name,
            "folded_attempts": folded_attempts,
            "fix_alpha": fix_alpha,
            "fix_beta": fix_beta,
        },
    )
    return updated
