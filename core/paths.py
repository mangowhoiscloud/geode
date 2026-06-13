"""GEODE directory hierarchy — centralized path resolution.

Two-tier directory structure following Claude Code's ~/.claude pattern:

  User-level (~/.geode/):
    Global config, credentials, identity, vault, models, usage.
    Project-scoped session data lives in ~/.geode/projects/{project_id}/.

  Project-level ({workspace}/.geode/):
    Project config (gateway bindings), memory, rules, skills, reports, cache.

Project ID encoding follows Claude Code's convention:
  /home/user/workspace/geode  ->  -home-user-workspace-geode
"""

from __future__ import annotations

import logging as _logging
import os
from functools import lru_cache
from pathlib import Path

# ---------------------------------------------------------------------------
# Repository-relative state (CSP-7, 2026-05-22) — machine-portable
# cross-run artefacts.
#
# Pre-CSP-7 the seed-generation pipeline wrote its cross-run handoff
# (latest_seed_pool symlink, latest_meta_review.json symlink,
# sessions.jsonl) and per-run artefacts into ``~/.geode/`` — host-
# specific paths that broke reproducibility across machines (cloned
# repo on a fresh box couldn't pick up the previous run's priors
# because they lived under the previous box's $HOME).
#
# STATE_ROOT moves those handoff + per-run artefacts INTO the repo
# (``state/`` directory, gitignored). Same repo, same state path —
# CI and local boxes share the layout. The runtime artefacts
# themselves stay un-tracked (gitignored under ``state/*``) so
# experimental runs don't pollute git history, but the *path
# convention* is in-tree.
#
# Override via ``GEODE_STATE_ROOT`` env var when an operator wants a
# specific spool location (e.g. a CI runner with limited workspace
# size that needs to redirect state to ephemeral disk). Default
# resolves to ``<repo_root>/state/`` — where ``<repo_root>`` is
# inferred from this module's filesystem location (works under
# editable installs + worktrees).
# ---------------------------------------------------------------------------


def _resolve_repo_root() -> Path:
    """Return the repository root that ships this ``core/paths.py``.

    The file lives at ``<repo_root>/core/paths.py``, so the root is
    two directory levels up. Works under editable installs (``uv tool
    install -e .``) and inside git worktrees alike.
    """
    return Path(__file__).resolve().parent.parent


_REPO_ROOT = _resolve_repo_root()
STATE_ROOT = Path(os.environ.get("GEODE_STATE_ROOT") or (_REPO_ROOT / "state")).expanduser()

# Seed pools — single SoT for the directory the campaign reads and the
# assemble script writes (PR-CLEANUP-D2, 2026-06-10). Deliberately
# REPO-pinned (not STATE_ROOT): the cycle-input pool is a git-tracked
# campaign input, and the 2026-06-03 incident (assemble to a custom
# --out → every worker dropped with "train.py exited 1") came from the
# writer and reader resolving this path independently. REPO-pinned is
# the OPERATOR-DECIDED semantic (D-3, 2026-06-10) — do not make this
# honor GEODE_STATE_ROOT without a new operator decision.
SEED_POOLS_DIR = _REPO_ROOT / "state" / "seed-pools"
CYCLE_INPUT_POOL = SEED_POOLS_DIR / "cycle-input"
HELD_OUT_BENCH_POOL = SEED_POOLS_DIR / "held-out"

# PR-STATE-AUTORESEARCH-RENAME (2026-06-01, Scheme A) — the autoresearch
# optimization loop's in-repo runtime DATA. "autoresearch" is the engine's
# name (operator-approved); this was ``state/autoresearch/`` under
# PR-STATE-SELF-IMPROVING-RENAME (#1955) which collided as a near-synonym
# twin with the hyphenated cross-run handoff dir ``self-improving-loop/``.
# Scheme A folds BOTH under a single ``state/autoresearch/`` root (the
# handoff is now ``handoff/`` NESTED below — see AUTORESEARCH_HANDOFF_DIR)
# so the twin is eliminated. Env-overridable via ``GEODE_STATE_ROOT`` +
# clone-portable like the seed-generation state. This is the SINGLE
# canonical definition — ``core.self_improving.train`` / ``.watch_campaign``
# / ``.campaign`` / ``.prepare`` and ``scripts/build_self_improving_hub.py``
# all import it (no dual SoT, per CLAUDE.md Registry/SoT rules). The CODE
# package ``core/self_improving/`` keeps its name — only the STATE dir moves.
AUTORESEARCH_STATE_DIR = STATE_ROOT / "autoresearch"

# Cross-run handoff (latest_pointer.json, sessions.jsonl). PR-STATE-
# AUTORESEARCH-RENAME (2026-06-01, Scheme A) — nested UNDER the
# autoresearch state root so there is no ``self_improving`` (underscore)
# vs ``self-improving-loop`` (hyphen) near-synonym twin. The handoff
# pointer + run-level registry belong to the same autoresearch loop
# whose ledgers live in ``AUTORESEARCH_STATE_DIR``; the only reason
# they were a separate top-level dir was the pre-CSP-7 history.
AUTORESEARCH_HANDOFF_DIR = AUTORESEARCH_STATE_DIR / "handoff"

# Per-run artefacts (state.json, candidates/, survivors/, meta_review.json,
# elo_log.tsv). Pre-CSP-7: ``~/.geode/seed-generation/<run_id>/``.
# PR-STATE-AUTORESEARCH-RENAME (2026-06-01) — snake_case ``seed_generation``
# to match the plugin package ``plugins/seed_generation/`` (no hyphen/
# underscore twin). The Pages-served bundle dir
# (``docs/self-improving/seed-generation/``) keeps its hyphen URL — only
# the READ/state path goes snake.
STATE_SEED_GENERATION_DIR = STATE_ROOT / "seed_generation"

# Single forward-pointer JSON file the seed-generation orchestrator
# writes at the end of every run (CSP-7). Replaces the pre-CSP-7
# pair of ``latest_seed_pool`` / ``latest_meta_review.json`` symlinks.
# Schema (JSON object):
#
#     {
#       "version": 1,
#       "run_id": "gen2-broken_tool_use",
#       "gen_tag": "gen2",
#       "updated_at": "2026-05-22T01:00:00Z",
#       "seed_pool":   "seed_generation/gen2-broken_tool_use/survivors",
#       "meta_review": "seed_generation/gen2-broken_tool_use/meta_review.json"
#     }
#
# Paths stored as STATE_ROOT-relative strings so a clone-on-fresh-box
# can resolve them without honouring the writer's ``$HOME`` or
# absolute layout. Readers MUST go through :func:`read_latest_pointer`
# (validates schema + resolves to absolute via STATE_ROOT).
STATE_LATEST_POINTER_PATH = AUTORESEARCH_HANDOFF_DIR / "latest_pointer.json"


def write_latest_pointer(
    *,
    run_id: str,
    gen_tag: str,
    seed_pool: Path | str | None,
    meta_review: Path | str | None,
) -> None:
    """Write the cross-run forward pointer JSON.

    Stores ``seed_pool`` / ``meta_review`` as ``STATE_ROOT``-relative
    strings so a fresh clone resolves them under that machine's
    STATE_ROOT (which itself may be env-overridden). Absolute inputs
    that fall outside STATE_ROOT are stored verbatim — readers must
    then deal with absolute paths (used by tests that stage fixtures
    outside the repo).

    Failures (parent mkdir / write) are NOT swallowed here — the
    caller (orchestrator) owns the "observability must not break the
    run it observes" decision and wraps this in a try/except.
    """
    import json as _json
    from datetime import UTC, datetime

    payload: dict[str, object] = {
        "version": 1,
        "run_id": run_id,
        "gen_tag": gen_tag,
        "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if seed_pool is not None:
        payload["seed_pool"] = _stringify_relative(Path(seed_pool))
    if meta_review is not None:
        payload["meta_review"] = _stringify_relative(Path(meta_review))
    STATE_LATEST_POINTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_LATEST_POINTER_PATH.write_text(
        _json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def read_latest_pointer() -> dict[str, object] | None:
    """Read the cross-run forward pointer JSON.

    Returns the parsed payload with ``seed_pool`` / ``meta_review``
    keys re-resolved to absolute :class:`Path` objects (against
    STATE_ROOT), or ``None`` when:

    - The pointer file does not exist (bootstrap — no prior run on
      this machine + STATE_ROOT pair).
    - The JSON is unparseable.
    - The payload is not a dict.

    Returning a dict (not a class) keeps the surface dependency-free
    for the autoresearch reader (which lives outside ``core/``).
    """
    import json as _json

    if not STATE_LATEST_POINTER_PATH.is_file():
        return None
    try:
        raw = STATE_LATEST_POINTER_PATH.read_text(encoding="utf-8")
        payload = _json.loads(raw)
    except (OSError, _json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    # Resolve relative paths against STATE_ROOT so readers receive
    # absolute Path objects ready to ``open`` / ``iterdir``.
    out: dict[str, object] = dict(payload)
    for key in ("seed_pool", "meta_review"):
        value = out.get(key)
        if isinstance(value, str) and value:
            p = Path(value)
            out[key] = (p if p.is_absolute() else STATE_ROOT / p).resolve()
    return out


def _stringify_relative(path: Path) -> str:
    """Return ``path`` as a STATE_ROOT-relative string when possible.

    Falls back to ``str(path)`` (absolute) when ``path`` lives outside
    STATE_ROOT — the reader then handles it as an absolute path.
    """
    try:
        rel = path.resolve().relative_to(STATE_ROOT.resolve())
    except ValueError:
        return str(path)
    return str(rel)


# ---------------------------------------------------------------------------
# User-level (global) — ~/.geode/
# ---------------------------------------------------------------------------

# ``GEODE_HOME`` env override mirrors the frontier agent-CLI convention
# (``CODEX_HOME`` / ``HERMES_HOME`` / ``OPENCLAW_HOME`` / ``PAPERCLIP_HOME`` /
# ``CRUMB_HOME`` all resolve ``env.get({APP}_HOME) ?? ~/.{app}``) and the
# ``GEODE_STATE_ROOT`` pattern above. Every ``GLOBAL_*`` constant derives from
# this single point, so the override redirects the whole user-global tree (the
# testability + alternate-home story). ``expanduser`` so ``GEODE_HOME=~/x`` and
# ``GEODE_STATE_ROOT=~/x`` actually expand. (PR-PATH-MODERNIZE Phase 1.)
GEODE_HOME = Path(os.environ.get("GEODE_HOME") or (Path.home() / ".geode")).expanduser()

# Global config & credentials
GLOBAL_CONFIG_TOML = GEODE_HOME / "config.toml"
GLOBAL_ENV_FILE = GEODE_HOME / ".env"

# Petri audit runtime logs — single SoT (PR-CLEANUP-D2, 2026-06-10).
# Writer: plugins/petri_audit/cli_audit.py maintains the latest.eval
# symlink; readers: train.py evidence extraction, seed_generation
# baseline_reader, campaign glob, eval_archive, bundle_sync. Six
# independent literal copies of this path existed before the anchor —
# every reader has a graceful-None contract, so a writer-side move
# would have broken fitness evidence + baselines with zero errors.
PETRI_LOGS_DIR = GEODE_HOME / "petri" / "logs"
LATEST_PETRI_EVAL = PETRI_LOGS_DIR / "latest.eval"

# User identity & profile
GLOBAL_IDENTITY_DIR = GEODE_HOME / "identity"
GLOBAL_USER_PROFILE_DIR = GEODE_HOME / "user_profile"
# P3 (v0.95.x) — user preferences TOML inside user_profile/.
# Read by `core/tools/policy.py` to seed ProfilePolicy at boot.
GLOBAL_USER_PREFERENCES = GLOBAL_USER_PROFILE_DIR / "preferences.toml"

# Non-project-scoped data
GLOBAL_VAULT_DIR = GEODE_HOME / "vault"
GLOBAL_MODELS_DIR = GEODE_HOME / "models"
GLOBAL_RUNS_DIR = GEODE_HOME / "runs"
GLOBAL_USAGE_DIR = GEODE_HOME / "usage"
GLOBAL_MCP_DIR = GEODE_HOME / "mcp"
GLOBAL_SCHEDULER_DIR = GEODE_HOME / "scheduler"
# P4 (v0.95.x) — added during lint-guardrail rollout. fa4 diagnostics
# log dir (cross-process append-only) and the auth.toml SoT path.
# `core.auth.auth_toml` overrides via `GEODE_AUTH_TOML` env var; this
# constant is the default fallback.
GLOBAL_DIAGNOSTICS_DIR = GEODE_HOME / "diagnostics"
# P1a + P1c (2026-05-19) — self-improving-loop wiring sprint. Shared cross-loop
# namespace: ``sessions.jsonl`` (P1a, run-level index, one row per
# autoresearch/seed-generation run) + ``<session_id>/transcript.jsonl``
# (P1c, event stream within a single run). See
# ``docs/plans/2026-05-19-self-improving-loop-wiring-sprint.md``.
# PR-STATE-AUTORESEARCH-RENAME (2026-06-01, Scheme A) — the home handoff
# dir moves from ``~/.geode/autoresearch/handoff/`` to
# ``~/.geode/autoresearch/handoff/`` IN CODE so the home layout mirrors
# the in-repo ``state/autoresearch/handoff/`` and the underscore/hyphen
# twin is gone. (The live ``~/.geode`` dir is migrated by the operator
# command, not by the constant.)
GLOBAL_AUTORESEARCH_HANDOFF_DIR = GEODE_HOME / "autoresearch" / "handoff"
# PR-RATCHET-1 (2026-05-21) — the 5 mutation-target files now live in
# the in-repo ``state/autoresearch/policies/`` directory rather than
# the operator's ``~/.geode/autoresearch/handoff/``. The rename converges
# on upstream Karpathy's "branch tip = current best" principle: each
# policy is git-tracked, so ``git diff`` shows the current mutation
# state and ``git revert`` discards a hypothesis. The directory name
# matches the existing module/function/constant naming
# (``policies.py`` / ``load_policy`` / ``GLOBAL_*_POLICY_PATH``).
# PR-MINIMAL-2 (2026-05-21, H2) — constant names also dropped the
# ``_SOT`` suffix (``GLOBAL_*_SOT`` → ``GLOBAL_*_PATH``) so the
# names match the new directory's "policies" semantics rather than
# the legacy "source of truth" label. Lazy migration of any legacy
# ``~/.geode/autoresearch/handoff/<file>.json`` payload is handled
# by :mod:`core.self_improving.loop.mutate.policies`.
# The in-repo policy/ledger state dir is ``AUTORESEARCH_STATE_DIR``
# (``state/autoresearch/``, defined at the top of this module).
GLOBAL_POLICIES_DIR = AUTORESEARCH_STATE_DIR / "policies"
LEGACY_SOT_DIR = GLOBAL_AUTORESEARCH_HANDOFF_DIR
"""Pre-RATCHET-1 policy dir under ``~/.geode/autoresearch/handoff/``.
Kept for the lazy migration path so an upgrade of an existing
operator install copies their last-known wrapper/policy state into
the new in-repo location on first read/write."""
# G5a (2026-05-20) — cross-process SoT for the AgenticLoop wrapper prompt
# sections. Written by ``core.self_improving.train.write_wrapper_prompt_sections``
# after a self-improving-loop promotion; read by
# ``core.agent.system_prompt._load_wrapper_override`` for daily GEODE runs.
GLOBAL_WRAPPER_SECTIONS_PATH = GLOBAL_POLICIES_DIR / "wrapper-sections.json"
# PR-6 C-5 (2026-05-21) — policy mutation SoT files. Each
# ``target_kind`` (tool_policy / decomposition / retrieval /
# reflection) gets its own ``dict[str, str]`` JSON file alongside
# ``wrapper-sections.json``. ``prompt`` keeps the legacy wrapper-
# sections name so older mutation rows replay correctly; the others
# land in fresh files because they evolve independently. Read /
# written by :mod:`core.self_improving.loop.mutate.policies`.
GLOBAL_TOOL_POLICY_PATH = GLOBAL_POLICIES_DIR / "tool-policy.json"
GLOBAL_DECOMPOSITION_POLICY_PATH = GLOBAL_POLICIES_DIR / "decomposition.json"
GLOBAL_RETRIEVAL_POLICY_PATH = GLOBAL_POLICIES_DIR / "retrieval.json"
GLOBAL_REFLECTION_POLICY_PATH = GLOBAL_POLICIES_DIR / "reflection.json"
# ADR-013 T1 (2026-05-21) — Tool descriptions mutation SoT.
GLOBAL_TOOL_DESCRIPTIONS_PATH = GLOBAL_POLICIES_DIR / "tool-descriptions.json"
# PR-HYPERPARAM-FOUNDATION (2026-05-28) — numeric / categorical
# hyperparameter mutation SoT. Distinct from the 7 text-artifact kinds:
# this slot directly tunes the audit-subprocess command line
# (max_turns → -T max_turns=<n>, seed_limit → --limit <n>, dim_set
# → -T judge_dimensions=..., reflection_depth → AgenticLoop config).
# Cycle 1-12 (2026-05-26 → 05-28) observed 11/12 prompt-only mutations
# stuck on redundant_tool_invocation with Δ=0 because the dim's
# measurement_modality (tool_log: programmatic dedup count) lives below
# the LLM's prompt-following surface — only mechanism-level levers
# (turn budget, sample count) can move it. Values are string-encoded
# at the SoT (``{"max_turns": "5"}``) for schema consistency with the
# other 4 simple-shape kinds; runtime readers convert to int /
# categorical at the consumption site (PR-HYPERPARAM-WIRE).
GLOBAL_HYPERPARAM_POLICY_PATH = GLOBAL_POLICIES_DIR / "hyperparam.json"
# PR-BACKFILL-SOT (2026-05-21) — operator-local SoT layer for the 4 active
# mutation surface readers (tool_policy / reflection / decomposition /
# tool_descriptions). Per-machine overrides without touching in-repo
# ratchet-tracked files. Resolution order: env-override (strict/graceful)
# → operator-local (graceful) → in-repo (graceful) → None.
OPERATOR_LOCAL_TOOL_POLICY_PATH = GLOBAL_AUTORESEARCH_HANDOFF_DIR / "tool-policy.json"
OPERATOR_LOCAL_DECOMPOSITION_POLICY_PATH = GLOBAL_AUTORESEARCH_HANDOFF_DIR / "decomposition.json"
OPERATOR_LOCAL_REFLECTION_POLICY_PATH = GLOBAL_AUTORESEARCH_HANDOFF_DIR / "reflection.json"
OPERATOR_LOCAL_TOOL_DESCRIPTIONS_PATH = GLOBAL_AUTORESEARCH_HANDOFF_DIR / "tool-descriptions.json"
# ADR-013 T2 (2026-05-21) — Skill catalog mutation SoT. Mutator overrides
# per-skill description text + user_invocable visibility for the LLM's
# skill-routing context block.
GLOBAL_SKILL_CATALOG_PATH = GLOBAL_POLICIES_DIR / "skill-catalog.json"
OPERATOR_LOCAL_SKILL_CATALOG_PATH = GLOBAL_AUTORESEARCH_HANDOFF_DIR / "skill-catalog.json"
# ADR-013 T3 (2026-05-21) — Response style guide mutation SoT. Typed enum
# schema (tone / verbosity_level / response_format / code_style) — mutator
# picks from constrained alternatives. (ux_means fitness 축은
# PR-MARGIN-FITNESS-SCALE 2026-05-30 에 제거 — 이제 Petri dim 경유로만
# fitness 영향.) wrapper-sections.json (G5a/G5b) 의 free-form 텍스트
# mutation 과 분리: T3 는 constrained typed 선택지.
GLOBAL_STYLE_GUIDE_PATH = GLOBAL_POLICIES_DIR / "style-guide.json"
OPERATOR_LOCAL_STYLE_GUIDE_PATH = GLOBAL_AUTORESEARCH_HANDOFF_DIR / "style-guide.json"
# ADR-013 T4 (2026-05-21) — Provider routing mutation SoT. Mutator picks
# per-model preferred plan chain (plan_id ordered list). OpenRouter-style
# explicit routing — per-call cost knob. (ux_means.token_cost_norm fitness
# 축은 PR-MARGIN-FITNESS-SCALE 2026-05-30 에 제거.)
GLOBAL_PROVIDER_ROUTING_PATH = GLOBAL_POLICIES_DIR / "provider-routing.json"
OPERATOR_LOCAL_PROVIDER_ROUTING_PATH = GLOBAL_AUTORESEARCH_HANDOFF_DIR / "provider-routing.json"
# ADR-013 T5 (2026-05-21) — Cache breakpoint policy mutation SoT. Mutator
# picks how many trailing-message cache_control breakpoints to apply
# (Anthropic의 4-breakpoint cap 중 messages 가 가져갈 수). 0-3 사이.
# trade-off: ↑ → cache hit ↑ but per-call overhead ↑ (각 breakpoint 가
# $0.10/MTok 오버헤드). ↓ → cache hit ↓ but per-call cost ↓.
GLOBAL_CACHE_POLICY_PATH = GLOBAL_POLICIES_DIR / "cache-policy.json"
OPERATOR_LOCAL_CACHE_POLICY_PATH = GLOBAL_AUTORESEARCH_HANDOFF_DIR / "cache-policy.json"
# ADR-013 T6 (2026-05-21) — Heuristic indicators mutation SoT. Mutator
# evolves the keyword/phrase list that primes the LLM's task-triage
# heuristics — complexity / risk / time-pressure markers injected into
# the system prompt static block. Promptbreeder-식 evolution: agent
# uses indicators to classify task → better triage. (ux_means success_rate
# fitness 축은 PR-MARGIN-FITNESS-SCALE 2026-05-30 에 제거 — 이제 Petri dim
# 경유로만 fitness 영향.)
GLOBAL_HEURISTICS_PATH = GLOBAL_POLICIES_DIR / "heuristics.json"
OPERATOR_LOCAL_HEURISTICS_PATH = GLOBAL_AUTORESEARCH_HANDOFF_DIR / "heuristics.json"
# ADR-012 S5 (2026-05-21) — in-context slot configuration SoT. Declares
# the 4 canonical slot categories (exemplars / memory_recall /
# rubric_excerpts / tool_hints) and their per-slot top-K / rank_by /
# injection_point. M4.4 후속 PR 이 이 schema 를 실제 inference path 에서
# 소비하는 wiring 을 담당; 본 PR 은 schema + reader + validation 만.
GLOBAL_IN_CONTEXT_SLOTS_PATH = GLOBAL_POLICIES_DIR / "in-context-slots.json"
OPERATOR_LOCAL_IN_CONTEXT_SLOTS_PATH = GLOBAL_AUTORESEARCH_HANDOFF_DIR / "in-context-slots.json"
# ADR-012 M2 (2026-05-21) — AgentDefinition contract mutation SoT.
# Mutator overrides per-agent role / system_prompt / tools. ``model``
# field 은 Tier 2 — 변경 시 안전성 invariants 가 단번에 무효화될 수
# 있어 mutation surface 에서 제외.
GLOBAL_AGENT_CONTRACTS_PATH = GLOBAL_POLICIES_DIR / "agent-contracts.json"
OPERATOR_LOCAL_AGENT_CONTRACTS_PATH = GLOBAL_AUTORESEARCH_HANDOFF_DIR / "agent-contracts.json"
# ADR-012 M3 (2026-05-21) — Few-shot exemplar pool (JSONL append-only).
# fitness gate 통과한 task-completion candidate 를 누적; runtime 에
# top-K 선별해 system prompt 직후 in-context exemplar 로 적재. S5 의
# ``exemplars`` slot 의 실제 *적재 메커니즘*.
GLOBAL_FEW_SHOT_POOL_PATH = GLOBAL_POLICIES_DIR / "few-shot-pool.jsonl"
OPERATOR_LOCAL_FEW_SHOT_POOL_PATH = GLOBAL_AUTORESEARCH_HANDOFF_DIR / "few-shot-pool.jsonl"
# PR-MINIMAL-2 (2026-05-21) — git-tracked audit ledger of every
# applied mutation. Lives in-repo alongside the 5 policy SoT JSONs
# so the git-as-optimiser ledger and the current-state files are
# co-located. Previously declared in
# ``core/self_improving/loop/mutate/runner.py``; moved here for consistency
# with the other path constants. The runner re-exports the constant
# for backwards compat with existing callers.
MUTATION_AUDIT_LOG_PATH = AUTORESEARCH_STATE_DIR / "mutations.jsonl"
# git-tracked, append-only baseline history JSONL. (The Pareto-archive
# writer that originally populated it was removed in PR-GROUP-REMOVAL;
# the hub still reads any rows for the autoresearch timeline, and the
# baseline-registry follow-up repurposes it as the promote-history SoT.)
BASELINE_ARCHIVE_PATH = AUTORESEARCH_STATE_DIR / "baseline_archive.jsonl"
GLOBAL_AUTH_TOML = GEODE_HOME / "auth.toml"
# PR-4 C-3 (2026-05-21) — cross-session episodic action-outcome log
# (~/.geode/memory/episodes.jsonl). Append-only JSONL: one row per
# tool execution with (timestamp, session_id, tool_name, tool_input,
# success/error, cognitive_state snapshot). Rolling cap of
# ``EPISODE_LOG_MAX_ROWS`` keeps the file bounded. Read by
# :class:`core.memory.episodic.EpisodicStore` retrieval API.
GLOBAL_MEMORY_DIR = GEODE_HOME / "memory"
GLOBAL_EPISODES_LOG = GLOBAL_MEMORY_DIR / "episodes.jsonl"
# P1-F (2026-05-17) — per-user Petri audit role × model × source override.
# Read by ``plugins.petri_audit.user_overrides`` and merged into the
# binding resolver. Kept as a separate TOML (rather than wedged into
# ``config.toml``) so main GEODE config stays decoupled from Petri-only
# concerns; the /petri command writes here.
GLOBAL_PETRI_TOML = GEODE_HOME / "petri.toml"
# P2-A (2026-05-17) — global user override for the routing manifest.
# Loaded by ``core.config.routing_manifest.load_routing_manifest`` and
# merged section-by-section over the shipped ``core/config/routing.toml``
# default. Distinct from ``PROJECT_ROUTING_CONFIG`` (per-project node
# routing legacy file); P2-B..E migrate the legacy consumers onto the
# global manifest.
GLOBAL_ROUTING_TOML = GEODE_HOME / "routing.toml"
# P5 (Session 63, S5.5) — per-user seed-generation role × source override.
# Read by ``plugins.seed_generation.picker.load_user_overrides`` and merged
# into the picker's per-role binding resolver. Distinct from
# ``GLOBAL_PETRI_TOML`` because seed-generation owns its own 7-role × judge-
# panel binding model (see ADR-003 §"override surface").
# PR-STATE-AUTORESEARCH-RENAME (2026-06-01) — snake_case ``seed_generation.toml``
# to match the plugin package ``plugins/seed_generation/`` (was the hyphenated
# ``seed-generation.toml`` twin). The live file is renamed by the operator
# migration command, not by this constant.
GLOBAL_SEED_PIPELINE_TOML = GEODE_HOME / "seed_generation.toml"
# P3 (v0.95.x) — user-tier installed skills (priority 2 of 4-tier
# resolution; see `core/skills/skills.py`). Bundled skills live
# inside the package source tree, not at `GEODE_HOME` — resolve via
# `__file__` in skill_registry, do NOT add a constant for them here.
GLOBAL_SKILLS_DIR = GEODE_HOME / "skills"

# PR-Hermes-1d.2 (2026-05-26) — cross-project search index. Mirrors a
# subset of every per-project ``sessions.db`` ``messages`` table into a
# single FTS5-backed ledger so ``session_search(scope="all")`` and the
# ``geode reindex`` CLI command can answer "have I seen this anywhere
# across my history?" without opening N project DBs. The index is a
# rebuild-from-source artefact (no ground-truth lives here) so the
# rebuild is idempotent.
GLOBAL_SEARCH_DIR = GEODE_HOME / "search"
GLOBAL_SEARCH_DB = GLOBAL_SEARCH_DIR / "global.db"

# Project-scoped user data root
GLOBAL_PROJECTS_DIR = GEODE_HOME / "projects"

# Lifecycle / daemon paths (v0.63.0 — surfaced for /stop, /clean, /uninstall).
# Single source of truth so any future relocation is one-line. Existing
# duplicates in ``ipc_client.py`` + ``poller.py`` (DEFAULT_SOCKET_PATH) +
# ``mcp/registry.py`` (_CACHE_FILE) match these values; dedup is a
# follow-up refactor.
CLI_SOCKET_PATH = GEODE_HOME / "cli.sock"
CLI_STARTUP_LOCK = GEODE_HOME / "cli.startup.lock"
SERVE_LOG_PATH = GEODE_HOME / "logs" / "serve.log"
# PR-SESSION-METRICS (2026-05-23) — ``journal/`` depth 제거. 이전엔
# ``~/.geode/journal/transcripts/<project-slug>/<session_id>.jsonl`` 이중
# nesting 이었으나 transcript 가 단독 Tier-1 으로 정렬되며 ``journal/``
# 디렉터리 의미 사라짐. 이제 ``~/.geode/transcripts/<project-slug>/<session_id>.jsonl``.
# PR-CLEANUP-1 (2026-05-23) — ``GLOBAL_JOURNAL_DIR`` legacy alias 제거
# (1-release grace 만료). 외부 caller 0 확인.
GLOBAL_TRANSCRIPTS_DIR = GEODE_HOME / "transcripts"
GLOBAL_WORKERS_DIR = GEODE_HOME / "workers"
# v0.95.x layout migration v1 — moved under mcp/ to group with other MCP state.
# Legacy ``~/.geode/mcp-registry-cache.json`` migrated by
# ``core.wiring.layout_migrator._migrate_v0_to_v1`` on first bootstrap.
MCP_REGISTRY_CACHE = GEODE_HOME / "mcp" / "registry-cache.json"
# v0.95.x layout migration v1 — renamed to match the actual writer
# (``core.hooks.approval_tracker``, which has always used ``approval_history.jsonl``).
# Legacy ``~/.geode/approve_history.json`` (paths.py-side typo) migrated by
# ``core.wiring.layout_migrator._migrate_v0_to_v1``.
APPROVE_HISTORY = GEODE_HOME / "approval_history.jsonl"

# ---------------------------------------------------------------------------
# Project-level — {workspace}/.geode/
# ---------------------------------------------------------------------------

PROJECT_GEODE_DIR = Path(".geode")
PROJECT_CONFIG_TOML = PROJECT_GEODE_DIR / "config.toml"
PROJECT_MEMORY_DIR = PROJECT_GEODE_DIR / "memory"
PROJECT_RULES_DIR = PROJECT_GEODE_DIR / "rules"
PROJECT_SKILLS_DIR = PROJECT_GEODE_DIR / "skills"
PROJECT_REPORTS_DIR = PROJECT_GEODE_DIR / "reports"
PROJECT_RESULT_CACHE_DIR = PROJECT_GEODE_DIR / "result_cache"
PROJECT_SCHEDULER_FILE = PROJECT_GEODE_DIR / "scheduled_tasks.json"
PROJECT_SCHEDULER_LOCK = PROJECT_GEODE_DIR / "scheduled_tasks.lock"
PROJECT_SCHEDULER_LOG_DIR = PROJECT_GEODE_DIR / "scheduler_logs"
PROJECT_PLANS_FILE = PROJECT_GEODE_DIR / "plans.json"
PROJECT_USER_PROFILE_DIR = PROJECT_GEODE_DIR / "user_profile"
PROJECT_HOOKS_DIR = PROJECT_GEODE_DIR / "hooks"

# Per-project caches surfaced by /clean for selective wipe.
#
# v0.95.x — `PROJECT_EMBEDDING_CACHE` and `PROJECT_VECTORS_DIR` were
# removed (vestigial). No writer ever used either constant; the
# corresponding on-disk directories (`.geode/embedding-cache/`,
# `.geode/vectors/`) stopped receiving writes on 2026-04-05 and are
# archived to `.geode/_archive/` by layout migration v1 → v2 (see
# `core/wiring/layout_migrator.py:_migrate_v1_to_v2`).
PROJECT_TOOL_OFFLOAD = PROJECT_GEODE_DIR / "tool-offload"

# P3 (v0.95.x) — project-level state files. Surfaced here so writers stop
# hardcoding `Path(".geode/<file>")` literals (frontier parity — Hermes
# `hermes_constants.py:14-68` keeps every path on a single SoT module).
PROJECT_MODEL_POLICY = PROJECT_GEODE_DIR / "model-policy.toml"
PROJECT_ROUTING_CONFIG = PROJECT_GEODE_DIR / "routing.toml"


# ---------------------------------------------------------------------------
# Project root — CWD at startup (Claude Code's originalCwd pattern)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_project_root() -> Path:
    """Return the resolved CWD captured at first call.

    Follows Claude Code's ``originalCwd`` pattern: the sandbox boundary is
    the directory where the CLI was invoked, **not** the package installation
    path.  ``lru_cache`` ensures the value is frozen after the first call,
    which happens during CLI startup.
    """
    return Path.cwd().resolve()


# ---------------------------------------------------------------------------
# Project ID — Claude Code-style path encoding
# ---------------------------------------------------------------------------


def encode_project_id(workspace_path: str | Path | None = None) -> str:
    """Encode a workspace path into a project ID.

    Follows Claude Code's convention: replace ``/`` with ``-``.
    Example: ``/home/user/workspace/geode`` -> ``-home-user-workspace-geode``

    Args:
        workspace_path: Absolute workspace path. Defaults to ``cwd()``.
    """
    if workspace_path is None:
        workspace_path = Path.cwd()
    path_str = str(Path(workspace_path).resolve())
    return path_str.replace(os.sep, "-")


@lru_cache(maxsize=4)
def get_project_data_dir(workspace_path: str | Path | None = None) -> Path:
    """User-level project-scoped data directory.

    Returns ``~/.geode/projects/{project_id}/``.
    """
    project_id = encode_project_id(workspace_path)
    return GLOBAL_PROJECTS_DIR / project_id


# ---------------------------------------------------------------------------
# Project-scoped user directories (session, journal, snapshots)
# ---------------------------------------------------------------------------


def get_project_journal_dir(workspace_path: str | Path | None = None) -> Path:
    """Journal directory: ``~/.geode/projects/{id}/journal/``."""
    return get_project_data_dir(workspace_path) / "journal"


def get_project_sessions_dir(workspace_path: str | Path | None = None) -> Path:
    """Sessions directory: ``~/.geode/projects/{id}/sessions/``."""
    return get_project_data_dir(workspace_path) / "sessions"


def get_project_snapshots_dir(workspace_path: str | Path | None = None) -> Path:
    """Snapshots directory: ``~/.geode/projects/{id}/snapshots/``."""
    return get_project_data_dir(workspace_path) / "snapshots"


# ---------------------------------------------------------------------------
# Backward-compat: fallback to old project-level paths
# ---------------------------------------------------------------------------

# Old paths (pre-v0.31) stored these under {workspace}/.geode/
_OLD_JOURNAL_DIR = PROJECT_GEODE_DIR / "journal"
_OLD_SESSION_DIR = PROJECT_GEODE_DIR / "session"
_OLD_SNAPSHOT_DIR = PROJECT_GEODE_DIR / "snapshots"
_OLD_RESULT_CACHE_DIR = PROJECT_GEODE_DIR / "result_cache"
_OLD_VAULT_DIR = PROJECT_GEODE_DIR / "vault"
_OLD_MODELS_DIR = PROJECT_GEODE_DIR / "models"


def resolve_journal_dir(workspace_path: str | Path | None = None) -> Path:
    """Resolve journal directory with backward-compat fallback.

    Returns new path if it exists or old path doesn't exist.
    Falls back to old path if it has data and new path is empty.
    """
    new = get_project_journal_dir(workspace_path)
    return _resolve_with_fallback(new, _OLD_JOURNAL_DIR)


def resolve_sessions_dir(workspace_path: str | Path | None = None) -> Path:
    """Resolve sessions directory with backward-compat fallback."""
    new = get_project_sessions_dir(workspace_path)
    return _resolve_with_fallback(new, _OLD_SESSION_DIR)


def resolve_result_cache_dir(workspace_path: str | Path | None = None) -> Path:
    """Resolve result cache directory with backward-compat fallback."""
    new = get_project_data_dir(workspace_path) / "result_cache"
    return _resolve_with_fallback(new, _OLD_RESULT_CACHE_DIR)


def resolve_vault_dir() -> Path:
    """Resolve vault directory with backward-compat fallback."""
    return _resolve_with_fallback(GLOBAL_VAULT_DIR, _OLD_VAULT_DIR)


def _resolve_with_fallback(new_path: Path, old_path: Path) -> Path:
    """Return new_path unless old_path has data and new_path is empty/missing."""
    if new_path.exists() and any(new_path.iterdir()):
        return new_path
    if old_path.exists() and any(old_path.iterdir()):
        return old_path
    # Neither has data — use new path (will be created on first write)
    return new_path


# ---------------------------------------------------------------------------
# Lazy directory creation — Claude Code pattern (mkdir recursive on-demand)
# ---------------------------------------------------------------------------

_paths_log = _logging.getLogger(__name__)


def ensure_directories() -> None:
    """Create all required directories if missing.

    Called once at bootstrap. Follows Claude Code's lazy creation pattern:
    ``mkdir(parents=True, exist_ok=True)`` — no error if already present,
    creates full tree if absent.

    Two tiers:
    - Global (``~/.geode/``): runs, vault, models, usage, projects
    - Project (``.geode/``): memory, rules, skills, reports, scheduler_logs
    """
    created: list[str] = []

    # --- Global tier ---
    global_dirs = [
        GEODE_HOME,
        GLOBAL_RUNS_DIR,
        GLOBAL_VAULT_DIR,
        GLOBAL_MODELS_DIR,
        GLOBAL_USAGE_DIR,
        GLOBAL_MCP_DIR,
        GLOBAL_SCHEDULER_DIR,
        GLOBAL_PROJECTS_DIR,
        GLOBAL_IDENTITY_DIR,
        GLOBAL_USER_PROFILE_DIR,
    ]
    for d in global_dirs:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(str(d))

    # --- Project-scoped user data (under ~/.geode/projects/{id}/) ---
    project_data = get_project_data_dir()
    project_user_dirs = [
        project_data,
        project_data / "journal",
        project_data / "sessions",
        project_data / "snapshots",
        project_data / "result_cache",
    ]
    for d in project_user_dirs:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(str(d))

    # --- Project tier (.geode/) ---
    project_dirs = [
        PROJECT_GEODE_DIR,
        PROJECT_MEMORY_DIR,
        PROJECT_RULES_DIR,
        PROJECT_SKILLS_DIR,
        PROJECT_REPORTS_DIR,
        PROJECT_SCHEDULER_LOG_DIR,
    ]
    for d in project_dirs:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(str(d))

    # --- .gitignore entry for .geode/ ---
    _ensure_geode_gitignore()

    if created:
        _paths_log.info("Created %d directories: %s", len(created), ", ".join(created))

    # --- Layout migration (Hermes `_init_schema` pattern) ---
    # Runs on every bootstrap, idempotent via the module-level once-flag
    # inside :mod:`core.wiring.layout_migrator`. Reconciles legacy paths
    # produced by older GEODE versions with the current constants above.
    # Lazy import — keeps `core.paths` free of `core.wiring` dependency for
    # consumers that need pure path utilities without bootstrap side-effects.
    try:
        from core.wiring.layout_migrator import ensure_layout_migrated

        ensure_layout_migrated()
    except Exception:  # pragma: no cover — migration must never block boot
        _paths_log.warning("Layout migration skipped", exc_info=True)


def _ensure_geode_gitignore() -> None:
    """Add .geode/ to .gitignore if not already present."""
    gitignore = Path(".gitignore")
    entry = ".geode/"
    try:
        if gitignore.exists():
            content = gitignore.read_text(encoding="utf-8")
            if entry in content:
                return
            if not content.endswith("\n"):
                content += "\n"
        else:
            content = ""
        content += f"\n# GEODE\n{entry}\n"
        gitignore.write_text(content, encoding="utf-8")
    except OSError:
        pass  # read-only filesystem, CI, etc.


# ---------------------------------------------------------------------------
# Published-surface URL anchors (hardcoding sweep, 2026-06-11). The docs
# site + repo URLs appeared as scattered literals (hub builder, docs-link
# checker, sync-stats.mjs); python consumers import these two, the JS side
# mirrors them as file-level consts in site/scripts/sync-stats.mjs.
# ---------------------------------------------------------------------------
GEODE_PAGES_BASE_URL = "https://mangowhoiscloud.github.io/geode"
GEODE_REPO_URL = "https://github.com/mangowhoiscloud/geode"
