"""Build ``docs/self-improving/petri-bundle/seeds/listing.json`` from synced seed runs.

Mirrors ``scripts/build_literature_listing.py`` — runs from
``.github/workflows/pages.yml`` at Pages build time, and locally via
``uv run python scripts/build_seeds_listing.py``.

Algorithm
=========

1. Scan ``docs/self-improving/petri-bundle/seeds/<run_id>/`` for per-run dirs (each
   carries ``state.json`` + optional ``survivors.json`` +
   ``meta_review.json`` + ``candidates/<id>.md``).
2. Build a compact row per run for the listing.json:
   - ``run_id`` / ``gen_tag`` / ``target_dim`` / ``status``
   - draft → survivor counts
   - iteration count
   - usd_spent
   - per-phase summary (from state.json's structure)
3. Write ``listing.json`` (atomic tmp + rename).

Idempotency
===========

Re-run with no new runs → byte-identical ``listing.json`` (deterministic
ordering: alphabetical ``run_id``).

Exit codes
==========

- 0 — listing built (or no-op when no synced runs).
- 1 — fatal I/O error.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

LISTING_FILENAME = "listing.json"
SEEDS_DIR = "docs/self-improving/petri-bundle/seeds"


def _resolve_repo_root() -> Path:
    env_root = os.environ.get("GEODE_REPO_ROOT", "").strip()
    if env_root:
        return Path(env_root)
    here = Path.cwd().resolve()
    for ancestor in [here, *here.parents]:
        if (ancestor / "pyproject.toml").is_file():
            return ancestor
    return here


def _seed_count(state: dict[str, Any], key: str) -> int:
    """Defensive int extraction — state.json fields may be missing on early
    abort runs."""
    value = state.get(key)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return 0


def _resolve_harness_source(model: str, provider: str, cli: bool) -> str:
    """Source-prefixed model identifier (e.g. ``claude-cli/claude-opus-4-8``,
    ``openai-codex/gpt-5.5``). ``claude-cli`` when the sub-agent ran via the
    Claude Code CLI (``claude_cli_session_id`` present), else the bare
    ``provider``. Mirrors ``build_self_improving_hub._subagent_harness`` so the
    seedgen table chips match the per-sub-agent detail chips."""
    source = "claude-cli" if cli else (provider or "")
    if source and model and "/" not in model:
        return f"{source}/{model}"
    return model


def _run_harness_models(run_dir: Path) -> list[str]:
    """Distinct source-prefixed models the run's sub-agents ACTUALLY used,
    read from ``sub_agents/*/dialogue.jsonl`` (session_start model+provider) +
    ``session.json`` (claude_cli_session_id), preserving first-seen order.

    A seed-gen run is multi-model (e.g. a Claude drafter/evolver + gpt-5.5
    critics). The hub formerly hardcoded a single ``claude-cli/claude-opus-4-7``
    chip, mislabeling every run as "Claude Code" on the wrong model version and
    hiding the gpt-5.5 (Codex) half entirely. Recording the real set here lets
    the hub render truthful chips.
    """
    sub_root = run_dir / "sub_agents"
    if not sub_root.is_dir():
        return []
    seen: list[str] = []
    for agent_dir in sorted(sub_root.iterdir()):
        if not agent_dir.is_dir():
            continue
        model = ""
        provider = ""
        dialogue = agent_dir / "dialogue.jsonl"
        if dialogue.is_file():
            try:
                dialogue_lines = dialogue.read_text(encoding="utf-8").splitlines()
            except OSError:
                dialogue_lines = []
            for line in dialogue_lines:
                try:
                    event = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(event, dict) and event.get("event") == "session_start":
                    model = str(event.get("model") or "")
                    provider = str(event.get("provider") or "")
                    break
        if not model:
            continue
        cli = False
        session_path = agent_dir / "session.json"
        if session_path.is_file():
            try:
                session = json.loads(session_path.read_text(encoding="utf-8"))
                cli = bool(isinstance(session, dict) and session.get("claude_cli_session_id"))
            except (json.JSONDecodeError, ValueError, OSError):
                cli = False
        resolved = _resolve_harness_source(model, provider, cli)
        if resolved and resolved not in seen:
            seen.append(resolved)
    return seen


def _build_row(run_dir: Path) -> dict[str, Any] | None:
    """Build one listing row from a per-run dir. Returns None if the run
    is incomplete (no state.json)."""
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("build_seeds_listing: skip unparseable %s: %s", state_path, exc)
        return None
    if not isinstance(state, dict):
        return None

    survivors_count = _seed_count(state, "survivors")
    candidates_count = _seed_count(state, "candidates")
    return {
        "run_id": run_dir.name,
        "gen_tag": str(state.get("gen_tag", "") or ""),
        "target_dim": str(state.get("target_dim", "") or ""),
        "candidates_drafted": candidates_count,
        "survivors_count": survivors_count,
        "evolved_count": _seed_count(state, "evolved_candidates"),
        "iterations": int(state.get("current_iteration", 0) or 0),
        "max_iterations": int(state.get("max_iterations", 0) or 0),
        "usd_spent": float(state.get("usd_spent", 0.0) or 0.0),
        "prompt_tokens": int(state.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(state.get("completion_tokens", 0) or 0),
        "has_meta_review": bool(state.get("meta_review")),
        "has_supervisor_guidance": bool(state.get("supervisor_guidance")),
        "literature_snapshots_count": _seed_count(state, "literature_snapshots"),
        "debate_transcripts_count": _seed_count(state, "debate_transcripts"),
        "harness_models": _run_harness_models(run_dir),
        "url": f"seeds/{run_dir.name}/",
    }


def build_listing(repo_root: Path | None = None) -> dict[str, Any]:
    """Build the seeds listing dict (in-memory, no disk write)."""
    root = repo_root or _resolve_repo_root()
    seeds_dir = root / SEEDS_DIR
    if not seeds_dir.is_dir():
        return {"kind": "seeds", "count": 0, "runs": []}
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(seeds_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        row = _build_row(run_dir)
        if row is not None:
            rows.append(row)
    return {"kind": "seeds", "count": len(rows), "runs": rows}


def write_listing(repo_root: Path | None = None) -> Path | None:
    """Build + atomic-write listing.json. Returns the path written, or
    None when the seeds dir doesn't exist (no synced runs yet)."""
    root = repo_root or _resolve_repo_root()
    seeds_dir = root / SEEDS_DIR
    if not seeds_dir.is_dir():
        return None
    listing = build_listing(root)
    listing_path = seeds_dir / LISTING_FILENAME
    tmp = listing_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(listing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(listing_path)
    return listing_path


def main(argv: list[str] | None = None) -> int:
    """CLI entry — build the listing + log the count."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        path = write_listing()
    except OSError as exc:
        log.error("build_seeds_listing: write failed: %s", exc)
        return 1
    if path is None:
        log.info("build_seeds_listing: no seeds dir; nothing to do")
        return 0
    listing = json.loads(path.read_text(encoding="utf-8"))
    log.info(
        "build_seeds_listing: wrote %d runs → %s",
        listing["count"],
        path.relative_to(_resolve_repo_root()),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main(sys.argv[1:]))
