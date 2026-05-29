"""Policy SoT files for non-prompt mutation targets.

PR-6 C-5 of the cognitive-loop-uplift sprint
(``docs/plans/2026-05-21-cognitive-loop-uplift.md``).

Pre-PR-6 the self-improving loop's mutation target was *only* the
wrapper prompt — `wrapper-sections.json`. Tool selection policy,
decomposition policy, retrieval policy, and reflection policy were
hard-coded in Python and never participated in the
self-improvement loop.

This module introduces four sibling SoT files alongside
``wrapper-sections.json``:

  ============  ==============================================
  target_kind   SoT file
  ============  ==============================================
  prompt        wrapper-sections.json   (legacy — unchanged)
  tool_policy   tool-policy.json
  decomposition decomposition.json
  retrieval     retrieval.json
  reflection    reflection.json
  ============  ==============================================

Each file is a ``dict[str, str]`` (same schema as wrapper-sections so
operators learn one format). A mutation row carries ``target_kind``
plus ``target_section``; the runner dispatches to the matching file.

PR-6 stops at the *file format + dispatcher*. The Voyager-style
learning loops that actually exercise the new SoTs (curriculum +
skill library + critic) land as follow-ups; PR-6 just makes sure
the four files exist with stable read/write paths so the
infrastructure is committed before the policies that consume them.

Why no Voyager-style execution yet — Q4 simplicity: this PR ships
*one PR worth of expansion*, not a full curriculum loop. The
existing wrapper-prompt mutation path now goes through the same
dispatcher so a single ``apply_mutation`` call handles all five
kinds.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from core.paths import (
    GLOBAL_AGENT_CONTRACTS_PATH,
    GLOBAL_DECOMPOSITION_POLICY_PATH,
    GLOBAL_HYPERPARAM_POLICY_PATH,
    GLOBAL_REFLECTION_POLICY_PATH,
    GLOBAL_RETRIEVAL_POLICY_PATH,
    GLOBAL_SKILL_CATALOG_PATH,
    GLOBAL_TOOL_DESCRIPTIONS_PATH,
    GLOBAL_TOOL_POLICY_PATH,
    GLOBAL_WRAPPER_SECTIONS_PATH,
    LEGACY_SOT_DIR,
    OPERATOR_LOCAL_TOOL_DESCRIPTIONS_PATH,
)

log = logging.getLogger(__name__)

# PR-RATCHET-1 (2026-05-21) — when the in-repo SoT path doesn't
# exist yet, fall back to the pre-RATCHET-1 ``~/.geode/self-improving-loop/``
# location. Operators upgrading an existing install have their last
# mutation state there; copying it forward on first read keeps the
# loop continuous across the migration without a manual step. The
# legacy file is preserved (not deleted) so an operator can roll back
# manually if needed.
_LEGACY_FILE_NAMES: dict[str, str] = {
    "prompt": "wrapper-sections.json",
    "tool_policy": "tool-policy.json",
    "decomposition": "decomposition.json",
    "retrieval": "retrieval.json",
    "reflection": "reflection.json",
}


# PR-TOOL-DESCRIPTIONS-MUTATE (2026-05-27), Codex MCP review fix-up.
# The runtime reader at ``core/agent/tool_descriptions_policy.py`` (ADR-013 T1)
# honours a 3-layer resolution: env → operator-local
# (``~/.geode/self-improving-loop/tool-descriptions.json``) → in-repo
# (``autoresearch/state/policies/tool-descriptions.json``). Pre-fix the
# mutator's ``load_policy("tool_descriptions")`` only saw the in-repo
# layer, so an operator using the operator-local override would see
# the runtime read from THERE while the mutator wrote to the in-repo
# path — silent divergence + dual SoT drift.
#
# Fix: when the mutator reads ``tool_descriptions``, fall back to the
# operator-local file if the in-repo file is absent. ``load_policy``
# still writes to the in-repo path (so mutation history is auditable),
# which on first write produces the in-repo SoT and the operator-
# local file becomes secondary. Operators who want to keep the
# operator-local file authoritative should either (a) opt the surface
# out of the loop, or (b) accept that the first mutation graduates
# their override to in-repo. This matches the read-write parity rule
# in CLAUDE.md (every read path has a write path that lands in the
# same SoT family).
#
# Kept as a dict instead of hardcoding in ``load_policy`` so future
# kinds with the same 3-layer pattern (none today) extend by adding
# an entry, not by branching on ``kind``.
_OPERATOR_LOCAL_FALLBACK_PATHS: dict[str, Path] = {
    "tool_descriptions": OPERATOR_LOCAL_TOOL_DESCRIPTIONS_PATH,
}


def _maybe_migrate_legacy_sot(kind: str, new_path: Path) -> None:
    """Copy the pre-RATCHET-1 policy file to ``new_path`` if it
    exists and the new in-repo path doesn't yet. Idempotent — once
    the in-repo file is present the legacy copy is ignored on
    subsequent calls.

    Failures are logged but never raise — the caller's
    ``FileNotFoundError`` fallback (returning ``{}``) still produces
    a usable state. The catch is intentionally broad (``Exception``)
    because the migration is best-effort observability glue: a
    decode failure (e.g. non-UTF-8 legacy JSON, ``UnicodeDecodeError``)
    or any other unexpected condition should leave the caller free
    to fall through to the empty-policy state rather than crash the
    self-improving loop. Codex MCP review of PR-RATCHET-1 caught
    the original ``except OSError`` scope being too narrow.
    """
    if new_path.exists():
        return
    legacy_name = _LEGACY_FILE_NAMES.get(kind)
    if legacy_name is None:
        return
    legacy_path = LEGACY_SOT_DIR / legacy_name
    if not legacy_path.is_file():
        return
    try:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_text(legacy_path.read_text(encoding="utf-8"), encoding="utf-8")
        log.info(
            "PR-RATCHET-1 migration: copied %s → %s (legacy preserved)",
            legacy_path,
            new_path,
        )
    except Exception:
        log.warning(
            "PR-RATCHET-1 migration: failed to copy %s → %s",
            legacy_path,
            new_path,
            exc_info=True,
        )


# Canonical list of target kinds. Order matters for the type-hint enum
# only — apply dispatch is by string key.
#
# ADR-012 S0d (2026-05-21) — ``retrieval`` 은 명시적 deprecate. 사유:
# (a) Claude Code architect Boris Cherny (Latent Space, 2025-05): "Originally
#     we tried RAG... agentic search outperformed everything. By a lot...
#     at the cost of latency and tokens, you now have really awesome search
#     without security downsides."
# (b) arXiv 2605.15184 (PwC, 2026-05): "grep generally yields higher accuracy
#     than vector retrieval" (Claude Code/Codex/Gemini CLI 3-harness 교차).
# (c) Anthropic 공식 blog: "navigates a codebase the way a software engineer
#     would: traverses file system, reads files, uses grep" + staleness
#     예시 ("RAG returns a function the team renamed two weeks ago").
# (d) GEODE 의 retrieval slot 은 audit 시점부터 reader 부재 (PR-AUDIT-5SLOT).
#     reader 신설은 외부 vector store 인프라 (sqlite-vec/chromadb + 로컬
#     embedding) 도입 비용 대비 ROI 불명확.
# 보존: ``GLOBAL_RETRIEVAL_POLICY_PATH`` 와 ``_KIND_TO_PATH`` 의 ``retrieval``
# 매핑은 그대로 둠 — 미래 RAG 인프라 신설 시 별도 ADR 로 ``TARGET_KINDS``
# 에 재추가 가능하도록 path-literal guard 유지.
#
# PR-TARGET-KIND-DOC (2026-05-27) — surface-clarity bundle. The 2026-05-26
# attribution sprint Phase A audit (§5 mutation surface verification)
# found an asymmetry: ``autoresearch.train.run_audit``'s env override
# block (around line 868-903) wires STRICT-mode env vars for **13** SoT
# files, but ``TARGET_KINDS`` below originally listed only **6 active**
# mutation slots; PR-TOOL-DESCRIPTIONS-MUTATE (2026-05-27) graduates
# ``tool_descriptions`` so the split is now **7 active + 6 reader-only**.
# The reader-only difference (:data:`_READER_ONLY_KINDS`) tracks the
# SoT surfaces that the audit subprocess consumes (read-only) but the
# mutator cannot dispatch to. ADR-013 phased rollout intent: each
# reader-only surface graduates in its own follow-up PR (matching the
# ADR-012 M1/M2 precedent that opened ``skill_catalog`` and
# ``agent_contract``). Mutator emitting a ``target_kind`` not in
# ``TARGET_KINDS`` fails fast at ``parse_mutation`` (``runner.py:914``
# ValueError) — fail-closed by design. The reader-only set is pinned
# by ``tests/core/self_improving_loop/test_target_kind_surface_doc.py``
# so a future PR that promotes any of them must remove the entry
# explicitly rather than silently expanding mutator dispatch.
TARGET_KINDS: tuple[str, ...] = (
    "prompt",
    "tool_policy",
    "decomposition",
    "reflection",
    # ADR-012 M1 (2026-05-21) — skill catalog mutation slot 개통.
    # T2 (#1418) 이 신설한 ``skill-catalog.json`` reader 를 mutator 가
    # mutate 할 수 있도록 contract 확장. 다른 4 kind 와 달리 disk
    # shape 가 nested (``{skill_name: {description, user_invocable}}``)
    # 이므로 ``load_policy`` / ``write_policy`` 가 dotted-key flat 표현
    # 으로 변환 (mutation row 의 ``target_section`` 은 string 만 허용).
    "skill_catalog",
    # ADR-012 M2 (2026-05-21) — agent contract mutation slot 개통.
    # AgentDefinition.role / system_prompt / tools 의 mutation surface.
    # ``model`` field 는 Tier 2 (안전성 invariants) — 본 slot 에서 명시적
    # 제외. skill_catalog 와 동일 nested ↔ flat 변환 적용.
    "agent_contract",
    # PR-TOOL-DESCRIPTIONS-MUTATE (2026-05-27) — ADR-013 T1 graduation.
    # The ``tool-descriptions.json`` reader has been live since
    # 2026-05-21 (``core/agent/tool_descriptions_policy.py``), and the
    # audit subprocess already wires ``GEODE_TOOL_DESCRIPTIONS_OVERRIDE``
    # for STRICT-mode reads (``autoresearch/train.py:878``). Graduating
    # it to TARGET_KINDS opens the surface mutator can dispatch to —
    # directly attacks Petri 17-dim's ``broken_tool_use`` (the dim
    # whose pressure is best correlated with description quality per
    # OpenAI function-calling docs). nested-schema kind:
    # ``{tool_name: {description: str, hints: list[str]}}``; the
    # ``_LIST_FIELDS_BY_KIND`` mapping below converts the comma-joined
    # mutation row back to a list on write.
    "tool_descriptions",
    # PR-HYPERPARAM-FOUNDATION (2026-05-28) — numeric / categorical
    # hyperparameter mutation slot. Distinct from the 7 text-artifact
    # kinds above: this slot tunes the audit-subprocess command line
    # + AgenticLoop runtime configuration directly (max_turns →
    # ``-T max_turns=<n>``, seed_limit → ``--limit <n>``, dim_set →
    # ``-T judge_dimensions=<value>``, reflection_depth → AgenticLoop
    # reflection-iteration cap). Flat ``dict[str, str]`` schema with
    # string-encoded values (``{"max_turns": "5"}``); runtime readers
    # convert at the consumption site. Bounds enforced at
    # ``parse_mutation`` via ``_HYPERPARAM_INT_BOUNDS`` /
    # ``_HYPERPARAM_CATEGORICAL`` (see ``runner.py``) so a mutator
    # proposing ``max_turns=999`` fails fast instead of silently
    # crashing the next audit. Motivated by cycle 1-12 (2026-05-26 →
    # 05-28) where 11/12 prompt-only mutations could not move
    # ``redundant_tool_invocation`` (tool_log modality, programmatic
    # tool-call dedup) — turn-budget mutation is the first surface
    # the loop has that reaches that mechanism layer. PR-3
    # (PR-HYPERPARAM-WIRE) lands the audit-subprocess argv builder +
    # AgenticLoop reader.
    "hyperparam",
)

# Each kind maps to the SoT file. ``prompt`` re-points to the legacy
# wrapper-sections SoT so older mutations replay unchanged.
#
# ``retrieval`` 매핑은 S0d 이후 deprecated 상태 — ``TARGET_KINDS`` 에서
# 제외돼 mutation dispatch 가 발생하지 않지만 path constant 는 보존.
_KIND_TO_PATH: dict[str, Path] = {
    "prompt": GLOBAL_WRAPPER_SECTIONS_PATH,
    "tool_policy": GLOBAL_TOOL_POLICY_PATH,
    "decomposition": GLOBAL_DECOMPOSITION_POLICY_PATH,
    "retrieval": GLOBAL_RETRIEVAL_POLICY_PATH,
    "reflection": GLOBAL_REFLECTION_POLICY_PATH,
    "skill_catalog": GLOBAL_SKILL_CATALOG_PATH,
    "agent_contract": GLOBAL_AGENT_CONTRACTS_PATH,
    "tool_descriptions": GLOBAL_TOOL_DESCRIPTIONS_PATH,
    "hyperparam": GLOBAL_HYPERPARAM_POLICY_PATH,
}

# M1+M2 (2026-05-21) — nested-schema kinds. ``load_policy`` /
# ``write_policy`` 의 flat ↔ nested 변환 dispatch 분기 키.
# PR-TOOL-DESCRIPTIONS-MUTATE (2026-05-27) — tool_descriptions joins the
# nested-schema set; its disk shape is
# ``{tool_name: {description: str, hints: list[str]}}`` so the flat
# dotted-key contract (``"bash.description"`` etc.) reuses the same
# load/write machinery as skill_catalog / agent_contract.
_NESTED_KINDS: frozenset[str] = frozenset({"skill_catalog", "agent_contract", "tool_descriptions"})


# PR-TARGET-KIND-DOC (2026-05-27) — reader-only SoT surfaces. These are
# wired in ``autoresearch.train.run_audit``'s ``GEODE_*_OVERRIDE`` +
# ``GEODE_*_STRICT`` env block (so the audit subprocess can read them
# under operator-local overrides) but NOT in :data:`TARGET_KINDS` (so
# the mutator can't dispatch to them). Each entry must graduate to
# ``TARGET_KINDS`` via its own follow-up PR — phased rollout matches
# the ADR-012 M1/M2 precedent. Frozen set so a future PR that adds an
# entry to ``TARGET_KINDS`` *must* remove it here (the invariant test
# in ``tests/core/self_improving_loop/test_target_kind_surface_doc.py``
# verifies the two sets are disjoint).
_READER_ONLY_KINDS: frozenset[str] = frozenset(
    {
        # PR-TOOL-DESCRIPTIONS-MUTATE (2026-05-27) — ``tool_descriptions``
        # graduated from this set to :data:`TARGET_KINDS`; the operator-
        # visible signal is now "mutator can dispatch", not "fail-fast at
        # parse_mutation".
        "style_guide",
        "provider_routing",
        "cache_policy",
        "heuristics",
        "in_context_slots",
        "few_shot_pool",
    }
)


def is_valid_target_kind(kind: str) -> bool:
    """Return True iff ``kind`` is one of the *active* mutation targets.

    S0d (2026-05-21) 이후: ``TARGET_KINDS`` 만 active. ``_KIND_TO_PATH`` 의
    ``retrieval`` 매핑은 미래 복원을 위해 보존되지만 mutation 의 valid
    target 은 아님 (Codex MCP S0d review 가 catch — 두 자료 구조의 정합성)."""
    return kind in TARGET_KINDS


def policy_path(kind: str) -> Path:
    """Return the SoT file path for ``kind``.

    PR-TOOL-DESCRIPTIONS-MUTATE (2026-05-27, Codex MCP review fix-up)
    — when ``kind`` is in :data:`_OPERATOR_LOCAL_FALLBACK_PATHS` AND
    the operator-local file exists on disk, that path wins over the
    in-repo default. This mirrors the runtime reader's 3-layer
    resolution (env → operator-local → in-repo) at
    ``core/agent/tool_descriptions_policy.py:_load_tool_descriptions_override``
    so the mutator's READ and WRITE both land on whichever file the
    runtime actually reads. Without this parity the mutator would
    write to the in-repo file while the runtime continued reading
    operator-local — silent dual-SoT drift, a closed-loop breaker
    for the autoresearch ``mutate → measure → baseline`` cycle.

    The env layer is intentionally NOT consulted here — env paths are
    set inside the audit subprocess (STRICT mode) which never invokes
    the mutator, so adding env resolution would just add untestable
    branches without operational benefit.

    Raises :class:`ValueError` on unknown kinds so the runner can
    fail closed rather than silently writing to an unexpected file.
    """
    operator_local = _OPERATOR_LOCAL_FALLBACK_PATHS.get(kind)
    if operator_local is not None and operator_local.is_file():
        return operator_local
    try:
        return _KIND_TO_PATH[kind]
    except KeyError as exc:
        raise ValueError(f"unknown target_kind {kind!r}; expected one of {TARGET_KINDS!r}") from exc


def load_policy(kind: str) -> dict[str, str]:
    """Read the ``dict[str, str]`` policy for ``kind``.

    Missing file returns ``{}`` so a freshly-installed GEODE behaves
    like an empty policy — the runner's mutation step populates it
    over time. Malformed JSON also returns ``{}`` with a WARN, never
    raises; the readers downstream (PR-5 attribution) must remain
    robust to incomplete state.

    PR-RATCHET-1 (2026-05-21) — lazy migration from the pre-PR
    ``~/.geode/self-improving-loop/`` location to the in-repo
    ``autoresearch/state/policies/`` location runs before the read.

    M1 (2026-05-21) — ``skill_catalog`` kind 는 disk 상 nested
    ``{skill_name: {description, user_invocable}}`` 이지만 mutation
    row 의 contract 가 flat string-keyed 이므로 ``_flatten_nested``
    가 dotted-key flat 표현 (``"skill-name.description"`` 등) 으로
    변환해 반환.

    PR-TOOL-DESCRIPTIONS-MUTATE (2026-05-27, Codex MCP review fix-up)
    — :func:`policy_path` returns the operator-local path for
    ``tool_descriptions`` when the operator-local file exists, so this
    function transparently reads whichever layer the runtime reader
    reads. Both READ and WRITE land on the same file.
    """
    path = policy_path(kind)
    _maybe_migrate_legacy_sot(kind, path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        log.warning(
            "policy file %s is not valid JSON; returning empty dict",
            path,
            exc_info=True,
        )
        return {}
    if not isinstance(payload, dict):
        log.warning(
            "policy file %s is %s, expected dict; returning empty",
            path,
            type(payload).__name__,
        )
        return {}
    if kind in _NESTED_KINDS:
        # Disk shape = nested dict; runner contract = flat dotted-key.
        return _flatten_nested(payload)
    # Coerce values to strings — same schema as wrapper-sections so
    # the contract is "string-keyed dict of string sections".
    return {k: str(v) for k, v in payload.items() if isinstance(k, str)}


def _serialize_policy_payload(kind: str, sections: dict[str, str]) -> str:
    """Shared policy serialization (``_NESTED_KINDS`` flatten + JSON
    sort_keys), extracted so ``write_policy`` has one payload format.
    """
    serializable: dict[str, object]
    if kind in _NESTED_KINDS:
        serializable = dict(_unflatten_nested(sections, kind=kind))
    else:
        serializable = {k: v for k, v in sections.items() if isinstance(k, str)}
    return json.dumps(
        serializable,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def write_policy(kind: str, sections: dict[str, str]) -> Path:
    """Write the policy for ``kind`` to its SoT file, returning the
    written path. The dir is created if missing; the file is rewritten
    atomically (temp + rename) so concurrent readers never see a
    partial file.

    PR-RATCHET-1 (2026-05-21) — runs the lazy legacy-SoT migration
    before the write so a pre-PR-RATCHET-1 operator state at
    ``~/.geode/self-improving-loop/`` is captured in the in-repo
    location as the *previous* value of this kind, rather than being
    overwritten on the first mutation after upgrade.

    M1 (2026-05-21) — ``skill_catalog`` kind 는 flat dotted-key flat
    ``sections`` 을 ``_unflatten_nested`` 가 nested
    ``{skill_name: {description, user_invocable}}`` shape 로 변환 후
    저장. ``user_invocable`` field 는 ``"true"``/``"false"`` 문자열을
    bool 로 coerce — T2 reader 의 schema 요구 충족.
    """
    path = policy_path(kind)
    _maybe_migrate_legacy_sot(kind, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _serialize_policy_payload(kind, sections)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


# ---------------------------------------------------------------------------
# M1 + M2 — nested ↔ flat 변환 (ADR-012 M1/M2, 2026-05-21)
# ---------------------------------------------------------------------------

# Mutation row 의 ``new_value`` 는 string-only. nested-schema kinds 의
# 비-string field 는 변환 시 정규화 — bool / list 두 카테고리.
#
# M1 (skill_catalog): ``user_invocable`` (bool) 만 비-string.
# M2 (agent_contract): ``tools`` (list[str]) 만 비-string.
_BOOL_FIELDS_BY_KIND: dict[str, frozenset[str]] = {
    "skill_catalog": frozenset({"user_invocable"}),
    "agent_contract": frozenset(),
    "tool_descriptions": frozenset(),
}
_LIST_FIELDS_BY_KIND: dict[str, frozenset[str]] = {
    "skill_catalog": frozenset(),
    "agent_contract": frozenset({"tools"}),
    # PR-TOOL-DESCRIPTIONS-MUTATE (2026-05-27) — ``hints`` is the only
    # non-string field in the tool-descriptions schema (per
    # ``core/agent/tool_descriptions_policy.py:_validate_schema``).
    # ``_unflatten_nested`` splits the comma-separated mutation
    # ``new_value`` into a list of stripped hint strings on write.
    "tool_descriptions": frozenset({"hints"}),
}


def _flatten_nested(payload: dict[object, object]) -> dict[str, str]:
    """Convert nested ``{name: {field: value}}`` → flat ``{"name.field": "value"}``.

    Used by :func:`load_policy` when ``kind`` is a nested-schema kind
    (skill_catalog / agent_contract) so the runner sees the same
    string-keyed flat shape as the legacy 4 kinds. Non-dict entries
    skipped. Lists are joined with ``", "`` (mutation row → list split
    on the write path).
    """
    flat: dict[str, str] = {}
    for name, entry in payload.items():
        if not isinstance(name, str):
            continue
        if not isinstance(entry, dict):
            continue
        for field, value in entry.items():
            if not isinstance(field, str):
                continue
            if value is True:
                str_value = "true"
            elif value is False:
                str_value = "false"
            elif isinstance(value, list):
                str_value = ", ".join(str(x) for x in value)
            else:
                str_value = str(value)
            flat[f"{name}.{field}"] = str_value
    return flat


def _unflatten_nested(
    sections: dict[str, str],
    *,
    kind: str = "skill_catalog",
) -> dict[str, dict[str, object]]:
    """Convert flat ``{"name.field": "value"}`` → nested
    ``{name: {field: value}}``.

    ``kind`` controls per-field coercion:
      - ``skill_catalog``: ``user_invocable`` (bool) coerced from
        ``"true"``/``"false"``.
      - ``agent_contract``: ``tools`` (list[str]) coerced by
        comma-separated split + strip.

    Keys without a ``.`` are dropped (mutation contract requires dotted
    form for nested kinds).
    """
    bool_fields = _BOOL_FIELDS_BY_KIND.get(kind, frozenset())
    list_fields = _LIST_FIELDS_BY_KIND.get(kind, frozenset())
    nested: dict[str, dict[str, object]] = {}
    for flat_key, value in sections.items():
        if not isinstance(flat_key, str) or "." not in flat_key:
            continue
        name, _, field = flat_key.partition(".")
        if not name or not field:
            continue
        if field in bool_fields:
            coerced: object = value == "true"
        elif field in list_fields:
            coerced = [t.strip() for t in value.split(",") if t.strip()]
        else:
            coerced = value
        nested.setdefault(name, {})[field] = coerced
    return nested


__all__ = [
    "TARGET_KINDS",
    "is_valid_target_kind",
    "load_policy",
    "policy_path",
    "write_policy",
]
