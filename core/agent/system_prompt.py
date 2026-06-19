"""System prompt builder for AgenticLoop.

Builds the base system prompt from the router.md template, enriched with
project memory context.

Memory hierarchy injected into the system prompt (G1-G3):
  G1: GEODE.md  — Behavioral identity (Voice/Conduct + Principles + CANNOT, ~20 lines)
  G2: .geode/MEMORY.md — Project meta-index (architecture, pipelines, key files)
  G3: .geode/LEARNING.md — Agent learning (patterns, corrections, preferences)
  G4: .geode/memory/PROJECT.md — Runtime insights + rules

Extracted from ``nl_router.py`` so that the AgenticLoop can use the system
prompt without depending on the NL Router module.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from core.agent.heuristics_policy import (
    _load_heuristics_override,
    apply_heuristics_policy,
)
from core.agent.style_guide_policy import (
    _load_style_guide_override,
    apply_style_guide_policy,
)
from core.llm.model_guidance import render_model_guidance
from core.llm.platform_hints import render_platform_hint
from core.llm.prompt_assembler import with_math_output_formatting
from core.llm.prompts import AGENTIC_SUFFIX, ROUTER_SYSTEM
from core.paths import AUTORESEARCH_WRAPPER_SECTIONS_PATH, get_project_root

log = logging.getLogger(__name__)

# Max lines per memory hierarchy section to control context budget
_MAX_SECTION_LINES = 20
# Identity carries four GEODE.md sections (Identity + Voice & Conduct +
# Operating Principles + RUNTIME CANNOT); give it a larger budget than a
# single memory section so RUNTIME CANNOT is never truncated by the cap.
_MAX_IDENTITY_LINES = 40

_SYSTEM_PROMPT_TEMPLATE = ROUTER_SYSTEM
_WRAPPER_OVERRIDE_ENV = "GEODE_WRAPPER_OVERRIDE"
WRAPPER_OVERRIDE_HOOK_READY = True

# Prompt caching boundary marker. The Anthropic adapter splits the prompt at
# this opening tag — content BEFORE it is stable across turns (cache hit),
# content AFTER it changes per turn (no cache). XML-shaped per G7 of the
# 2026-05-12 prompt audit so the entire prompt is consistently tag-delimited.
PROMPT_CACHE_BOUNDARY = "<dynamic_context>"


_WRAPPER_SECTIONS_SOT_PATH = AUTORESEARCH_WRAPPER_SECTIONS_PATH
"""G5a — cross-process SoT path shared with :mod:`core.self_improving.train`.

Aliased from :data:`core.paths.AUTORESEARCH_WRAPPER_SECTIONS_PATH` so the
``.geode`` literal lives in exactly one place (path-literal guard
contract); the module-local alias is kept so tests can monkeypatch
``core.agent.system_prompt._WRAPPER_SECTIONS_SOT_PATH`` without
mutating the shared constant.
"""


def _load_wrapper_override() -> str | None:
    """Return the active wrapper override, or ``None`` when no override is set.

    Resolution order (G5a, 2026-05-20):

    1. ``GEODE_WRAPPER_OVERRIDE`` env var — audit subprocess hook.
       When set, the file MUST exist and parse; schema / load failures
       are fatal so real-mode autoresearch cannot silently spend
       quota on the default wrapper.
    2. ``~/.geode/autoresearch/handoff/wrapper-sections.json`` — daily-run
       SoT written by the G5b self-improving-loop runner. When the env
       var is unset and this file exists, daily ``geode`` invocations
       automatically pick up the evolved wrapper without any manual
       env management. Schema failures here log a WARNING and fall
       through to ``None`` (graceful degrade to ``_generic_static_prefix``)
       so a corrupted SoT can't brick GEODE.
    3. ``None`` — use ``_generic_static_prefix`` (router default).
    """
    override_path = os.environ.get(_WRAPPER_OVERRIDE_ENV)
    if override_path:
        return _strict_load(Path(override_path))
    # G5a env-less fallback — daily-run SoT lookup.
    if _WRAPPER_SECTIONS_SOT_PATH.is_file():
        return _graceful_load(_WRAPPER_SECTIONS_SOT_PATH)
    return None


def _emit_scaffold_diag(wrapper_override: str | None, *, audit_mode: bool) -> None:
    """Emit a diagnostic recording whether the mutated scaffold reached the prompt.

    PR-AUDIT-SCAFFOLD-WIRE (2026-05-31) — the Petri audit target is GEODE
    itself; the closed-loop's fitness signal is only causal if the mutated
    wrapper scaffold (``wrapper-sections.json``) is the base of the target's
    system prompt. ``inspect_ai``'s ``.eval`` ModelEvent only records the
    messages Petri passed to ``GeodeModelAPI.generate`` (the seed scenario),
    NOT the prompt AgenticLoop builds internally — so the scaffold's presence
    was previously unobservable from the archive alone. This diag closes that
    gap: it records ``wrapper_override_present`` + its length + the resolution
    source so a post-mortem can confirm the scaffold was injected without
    relying on the (scenario-only) inspect ModelEvent.

    Best-effort — never raises; a diag failure must not break prompt build.
    """
    try:
        from core.audit.diagnostics import diag

        present = wrapper_override is not None
        env_set = bool(os.environ.get(_WRAPPER_OVERRIDE_ENV))
        source = (
            "env"
            if env_set
            else ("sot_file" if _WRAPPER_SECTIONS_SOT_PATH.is_file() else "generic_prefix")
        )
        diag(
            "system_prompt.scaffold",
            f"wrapper_override_present={present} "
            f"override_chars={len(wrapper_override) if wrapper_override else 0} "
            f"source={source} audit_mode={audit_mode}",
        )
    except Exception:  # pragma: no cover — diagnostics must never break prompt build
        log.debug("scaffold diag emission failed", exc_info=True)


def _strict_load(path: Path) -> str:
    """Audit-subprocess path: schema failures raise RuntimeError."""
    if not path.is_file():
        raise RuntimeError(f"{_WRAPPER_OVERRIDE_ENV}={path} file not found")
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{_WRAPPER_OVERRIDE_ENV}={path} load failed: {exc}") from exc
    if not isinstance(data, dict) or not data:
        raise RuntimeError(f"{_WRAPPER_OVERRIDE_ENV}={path} must be a non-empty dict[str, str]")
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise RuntimeError(
                f"{_WRAPPER_OVERRIDE_ENV}={path} has non-string key/value at {key!r}"
            )
    return "\n\n".join(data.values())


def _graceful_load(path: Path) -> str | None:
    """Daily-run SoT path: schema failures log + return ``None``.

    Asymmetric handling versus :func:`_strict_load` is intentional:
    a daily ``geode`` invocation must never hard-fail because of a
    corrupted self-improving-loop artifact; the audit subprocess
    must hard-fail because spending quota on the wrong wrapper is
    worse than the audit aborting.
    """
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        log.warning("wrapper sections SoT at %s is unreadable; using default", path)
        return None
    if not isinstance(data, dict) or not data:
        log.warning("wrapper sections SoT at %s is not a non-empty dict; using default", path)
        return None
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            log.warning(
                "wrapper sections SoT at %s has non-string key/value at %r; using default",
                path,
                key,
            )
            return None
    return "\n\n".join(data.values())


def _audit_mode_active() -> bool:
    """G3 (2026-05-12) — strip GEODE-specific context when audit-mode is on.

    Petri's auditor controls the scenario's identity via `system_suffix`;
    a GEODE identity / memory / user-profile preamble contaminates the
    transcript (measured `scenario_realism` -1.23 in the 2026-05-12 audit).
    Set by ``cli_audit.audit(--unrestricted)`` before the inspect subprocess.
    """
    return os.environ.get("GEODE_AUDIT_UNRESTRICTED") == "1"


def _persona_on() -> bool:
    """G10 (2026-05-12; default flipped ON 2026-06-14) — GEODE identity injection.

    Default ON — the GEODE.md Identity / Voice & Conduct / Operating
    Principles / RUNTIME CANNOT sections are injected into the runtime
    context so the declared soul + runtime guardrails actually ship. Opt
    out with `GEODE_PERSONA=off` (thin-wrapper mode: behave as a bare
    wrapper around the base model). Audit-mode forces OFF regardless of
    this flag (G3 supersedes G10) — the Petri auditor controls scenario
    identity end-to-end.
    """
    if _audit_mode_active():
        return False
    return os.environ.get("GEODE_PERSONA", "on").lower() not in {"off", "0", "false", "no"}


def _generic_static_prefix() -> str:
    """Render the domain-neutral router prefix.

    ``.format()`` stays kwarg-free — the template's only placeholder is the
    escaped ``{{skill_context}}``, which this call collapses to
    ``{skill_context}`` for the later injection in ``loop/_context.py``.
    """
    return _SYSTEM_PROMPT_TEMPLATE.format()


def build_system_prompt(model: str = "") -> str:
    """Build the AgenticLoop system prompt.

    Layer composition (XML-tag-delimited per the 2026-05-12 prompt audit):

      <static_context> ──── stable across turns → cache hit
        <agent_baseline>   (always present — base capabilities)
        <agent_identity>   (G10: default on; opt out via GEODE_PERSONA=off)
      </static_context>
      <dynamic_context>    ──── changes per turn → no cache
        <model_card>       (always present when ``model`` argument set)
        <current_date>     (always present)
        <project_memory>   (G2: from .geode/MEMORY.md if exists)
        <agent_learning>   (G3: from user_profile/learned.md if exists; format
                            sanitized per G9 — pattern + 1-line summary, not raw
                            prior-conversation context)
        <runtime_rules>    (G4: ProjectMemory recent insights + active rules)
        <user_context>     (UserProfile career + preferences)
      </dynamic_context>

    Two flags govern what gets stripped:

    - ``GEODE_AUDIT_UNRESTRICTED=1`` (audit-mode, G3): strip every
      GEODE-specific layer — identity, memory, user_context — leaving
      only model_card + current_date + the caller's ``system_suffix``.
      Petri auditor controls the scenario's identity end-to-end.
    - ``GEODE_PERSONA`` (G10): inject GEODE identity (G1). Default ON so
      the declared soul + runtime guardrails ship; set ``=off`` for a thin
      wrapper around the base model. Audit-mode forces OFF regardless.

    The baseline is intentionally domain-neutral. Specialized pipelines live
    outside the core runtime.
    """
    wrapper_override = _load_wrapper_override()

    if _audit_mode_active():
        # G3 — minimal prompt for alignment audits.
        #
        # PR-AUDIT-SCAFFOLD-WIRE (2026-05-31) — the wrapper override is the
        # MUTATED GEODE scaffold (``wrapper-sections.json``). It MUST be the
        # base of the audit target's system prompt so scaffold mutations
        # causally move fitness; the auditor's seed scenario rides on
        # ``system_suffix`` (see ``core/agent/loop/_context.py``). Pre-fix
        # this branch returned ONLY dynamic context when the override
        # resolved to ``None`` (env unset + no SoT file) — a scaffold-free
        # target, the causal-disconnect path. Fall back to the same
        # domain-neutral base the non-audit branch uses (``_generic_static_
        # prefix``) so the target always carries a GEODE base scaffold; the
        # mutated wrapper layers on top when present.
        static = with_math_output_formatting(wrapper_override or _generic_static_prefix())
        parts: list[str] = []
        if model:
            mc = _build_model_card(model)
            if mc:
                parts.append(mc)
        parts.append(_build_date_context())
        dynamic = PROMPT_CACHE_BOUNDARY + "\n\n" + "\n\n".join(parts)
        _emit_scaffold_diag(wrapper_override, audit_mode=True)
        # PR-PROMPT-P2A — AGENTIC_SUFFIX is authored-static (cache zone) and
        # the dynamic envelope must CLOSE (B1: it had shipped unterminated
        # on every call since the 2026-05-12 XML conversion).
        return static + "\n\n" + AGENTIC_SUFFIX + "\n\n" + dynamic + "\n\n</dynamic_context>"

    static = with_math_output_formatting(wrapper_override or _generic_static_prefix())

    # ADR-013 T3 (2026-05-21) — response style guide append to static prompt.
    # policy 가 부재면 static 그대로 (no behavior change). 정책이 있으면
    # <response_style> 블록 append — static 영역 이므로 cache-eligible
    # (정책 변경 시에만 cache miss).
    static = apply_style_guide_policy(static, _load_style_guide_override())

    # ADR-013 T6 (2026-05-21) — heuristic indicators append to static.
    # Promptbreeder-식 phrase library — agent 가 task-triage 시 매칭.
    static = apply_heuristics_policy(static, _load_heuristics_override())

    # G10: Agent identity (default ON; opt out via GEODE_PERSONA=off for a
    # thin wrapper around the base model).
    if _persona_on():
        identity_ctx = _build_identity_context()
        if identity_ctx:
            static += "\n\n" + identity_ctx

    # ── DYNAMIC section (changes per turn → no cache) ──
    dynamic_parts: list[str] = []

    if model:
        model_card = _build_model_card(model)
        if model_card:
            dynamic_parts.append(model_card)
        # Hermes Phase 2 — family-aware guidance (Anthropic / OpenAI / Google
        # / xAI). Graceful no-op when family unresolved.
        guidance = render_model_guidance(model)
        if guidance:
            dynamic_parts.append(guidance)

    # Hermes Phase 2 — surface-aware hint (cli / serve_repl / slack / cron /
    # worktree / mcp_remote). Resolution honours $GEODE_SURFACE_TYPE then
    # the ContextVar then "cli". Graceful no-op when surface unmapped.
    hint = render_platform_hint()
    if hint:
        dynamic_parts.append(hint)

    dynamic_parts.append(_build_date_context())

    # G2-G4: Memory hierarchy (may change between turns)
    g2 = _build_geode_memory_context()
    if g2:
        dynamic_parts.append(g2)
    g3 = _build_learning_context()
    if g3:
        dynamic_parts.append(g3)
    g4 = _build_project_memory_context()
    if g4:
        dynamic_parts.append(g4)

    user_ctx = _build_user_context()
    if user_ctx:
        dynamic_parts.append(user_ctx)

    dynamic = "\n\n".join(dynamic_parts)

    _emit_scaffold_diag(wrapper_override, audit_mode=False)
    # PR-PROMPT-P2A — composition: [authored static incl. AGENTIC_SUFFIX,
    # markdown, cache-stable] // <dynamic_context> [injected per-turn XML
    # envelopes] </dynamic_context>. Moving the suffix out of the loop-level
    # post-dynamic append means memory churn no longer invalidates the cache
    # prefix that carries the core behaviour rules; closing the envelope
    # fixes B1 (unterminated tag on every call).
    return (
        static
        + "\n\n"
        + AGENTIC_SUFFIX
        + "\n\n"
        + PROMPT_CACHE_BOUNDARY
        + "\n\n"
        + dynamic
        + "\n\n</dynamic_context>"
    )


def format_current_date() -> str:
    """Return the current date as ``YYYY-MM-DD (Weekday)`` string.

    Shared helper used by both the system prompt and system injection
    to avoid duplicate ``datetime.now()`` formatting.
    """
    return datetime.now().strftime("%Y-%m-%d (%A)")


def get_active_rule_names(limit: int = 5) -> list[str]:
    """Return active analysis rule names from ProjectMemory.

    Shared helper used by both the system prompt (G4 detailed view)
    and system injection (lightweight summary).  Returns empty list
    on any failure (graceful degradation).
    """
    try:
        from core.memory.project import ProjectMemory

        mem = ProjectMemory()
        if not mem.exists():
            return []

        rules = mem.list_rules()
        if not rules:
            return []

        return [r["name"] for r in rules[:limit]]
    except Exception:
        log.debug("Failed to get active rule names", exc_info=True)
        return []


def _build_date_context() -> str:
    """Build current date string for system prompt injection.

    Prevents the LLM from defaulting to its knowledge-cutoff year when
    searching for recent information.
    """
    now = datetime.now()
    date_str = format_current_date()
    return (
        f"<current_date>\n"
        f"Today is {date_str}. The current year is {now.year}. "
        f"When searching for recent or latest information, use {now.year} as the base year.\n"
        f"</current_date>"
    )


@lru_cache(maxsize=8)
def _build_model_card(model: str) -> str:
    """Build a model card string for system prompt injection.

    Reads from MODEL_PRICING and MODEL_CONTEXT_WINDOW so the LLM
    can answer model-related questions directly without tool calls.

    G8 (2026-05-12) — ``lru_cache(maxsize=8)``. The card is a pure
    function of ``model`` (provider lookup + pricing table + fallback
    chain), so repeating the import + dict-lookup work on every
    ``build_system_prompt`` call was pure overhead. 8 entries covers
    the realistic working set (3-provider × ~3 models each).
    """
    try:
        from core.config import _resolve_provider
        from core.llm.token_tracker import MODEL_CONTEXT_WINDOW, MODEL_PRICING

        provider = _resolve_provider(model)
        pricing = MODEL_PRICING.get(model)
        ctx_window = MODEL_CONTEXT_WINDOW.get(model, 0)

        # PR-MIC (2026-05-23) — Option B from the X2 decision:
        # weaken the v0.52.8 strong identity assertion to a single
        # neutral statement. The original 3-sentence "non-negotiable"
        # text (recency-bias defense + explicit stale-ack override)
        # carried ~80 tokens per round but the actual incident root
        # cause (Understood. I am now <prev>. ack pollution) is fully
        # covered by ``_purge_stale_model_switch_acks`` — now block-
        # form aware too. The hypothetical backend system-layer
        # override (Codex outer instructions override) has no public
        # evidence and would re-introduce as Option C if a recurrence
        # surfaces. Aligned with claw + hermes which carry no identity
        # assertion in their system prompt.
        parts: list[str] = [
            f"You are {model} ({provider}).",
        ]

        if ctx_window:
            if ctx_window < 1_000_000:
                ctx_str = f"{ctx_window // 1000}K"
            else:
                ctx_str = f"{ctx_window / 1_000_000:.0f}M"
            parts.append(f"Context window: {ctx_str} tokens.")

        if pricing:
            # pricing.input/output are per-token; multiply back for per-1M display
            in_per_m = pricing.input * 1_000_000
            out_per_m = pricing.output * 1_000_000
            parts.append(f"Cost: ${in_per_m:.2f} input / ${out_per_m:.2f} output per 1M tokens.")

        # Fallback chain
        from core.config import (
            ANTHROPIC_FALLBACK_CHAIN,
            GLM_FALLBACK_CHAIN,
            OPENAI_FALLBACK_CHAIN,
        )

        chains = {
            "anthropic": ANTHROPIC_FALLBACK_CHAIN,
            "openai": OPENAI_FALLBACK_CHAIN,
            "glm": GLM_FALLBACK_CHAIN,
        }
        chain = chains.get(provider, [])
        if chain:
            parts.append(f"Fallback chain: {' -> '.join(chain)}.")

        parts.append(
            "For model-related questions, answer directly from this context. "
            "Do NOT call check_status for model info."
        )

        # GAP-17 — OpenAI / Codex tendency to emit HTML as a single
        # ``data:text/html(;base64)?`` URL ('paste into address bar' shape)
        # silently breaks every downstream GEODE consumer (slide build,
        # report PDF, artifact archiving) and inflates output_tokens 30-50%.
        # Anthropic + GLM do not exhibit this drift, so the guard is
        # provider-gated.
        if provider in ("openai", "openai-codex"):
            parts.append(
                "HTML output: NEVER emit ``data:text/html`` URLs or "
                "base64-encoded single-string blobs (the 'paste into address "
                "bar' shape). Always write raw ``<!DOCTYPE html>...`` source "
                "and propose a file path for storage. The address-bar shape "
                "is unreadable to the GEODE pipeline and inflates output "
                "tokens by 30-50%."
            )

        return "<model_card>\n" + "\n".join(parts) + "\n</model_card>"
    except Exception:
        log.debug("Failed to build model card", exc_info=True)
        return ""


def _build_user_context() -> str:
    """Build user context from profile + career identity.

    Sources:
      ~/.geode/user_profile/profile.md   — role, expertise, bio
      ~/.geode/user_profile/preferences.json — language, output format
      ~/.geode/identity/career.toml      — career summary

    IMPORTANT: This is the USER's profile, not GEODE's identity.
    GEODE's identity comes from GEODE.md (G1 layer).
    """
    try:
        from core.memory.user_profile import FileBasedUserProfile

        profile = FileBasedUserProfile()
        parts: list[str] = []

        # Profile summary (role, expertise, lang, skills)
        context_summary = profile.get_context_summary()
        if context_summary:
            parts.append(context_summary)

        # Career summary (title, experience, seeking)
        career_summary = profile.get_career_summary()
        if career_summary:
            parts.append(f"Career: {career_summary}")

        # PR-PROMPT-P2A (B2) — learned patterns are NOT injected here.
        # This builder shipped raw ``get_learned_patterns()`` rows (prior-
        # turn transcripts, error strings like "Max agentic rounds reached",
        # mid-sentence truncation) straight into every call, bypassing the
        # G9 sanitizer — the exact leak G9 was built to stop, surviving in
        # the SYMMETRIC builder (Conditional Read Parity). Single channel:
        # ``_build_learning_context`` (G3, <agent_learning>, sanitized).

        if not parts:
            return ""

        # G11 (2026-05-12) — drop the "Your identity is GEODE" preamble; the
        # GEODE-identity assertion lives in the opt-in <agent_identity> layer
        # (G10) and was duplicated here.
        header = (
            "<user_context>\n"
            "The following describes the USER who is talking to you. "
            "Use it to tailor responses to the user's expertise and preferences. "
            "Never present the user's profile as your own."
        )
        return header + "\n" + "\n".join(parts) + "\n</user_context>"
    except Exception:
        log.debug("Failed to build user context", exc_info=True)
        return ""


def _build_identity_context() -> str:
    """G1: Extract identity + behavioral sections from GEODE.md.

    Reads GEODE.md via OrganizationMemory.get_soul() and injects the
    Identity (who GEODE is) plus the BEHAVIORAL sections (Voice & Conduct +
    Operating Principles + RUNTIME CANNOT — how GEODE sounds, acts, and
    refuses) into the system prompt, within the ``_MAX_IDENTITY_LINES``
    budget. Default on (GEODE_PERSONA) so the declared soul + runtime
    guardrails actually ship; audit-mode strips it. The numeric Defaults
    section is reference, not identity, so it is deliberately NOT injected
    here (it stays in GEODE.md for the full-soul read + human reference).
    """
    try:
        from core.memory.organization import MonoLakeOrganizationMemory

        org = MonoLakeOrganizationMemory()
        soul = org.get_soul()
        if not soul:
            return ""

        # Extract the identity + behavioral sections only.
        target_sections = {
            "## Identity",
            "## Voice & Conduct",
            "## Operating Principles",
            "## RUNTIME CANNOT",
        }
        extracted_lines: list[str] = []

        current_in_target = False
        for line in soul.split("\n"):
            stripped = line.strip()
            # Detect section headers
            if stripped.startswith("## "):
                current_in_target = stripped in target_sections
                if current_in_target:
                    extracted_lines.append(stripped)
                continue
            # Skip cross-reference blockquotes (`> see CLAUDE.md …`) — they are
            # author-facing notes, not runtime directives.
            if stripped.startswith(">"):
                continue
            if current_in_target and stripped:
                extracted_lines.append(stripped)

        if not extracted_lines:
            return ""

        # Cap at budget
        capped = extracted_lines[:_MAX_IDENTITY_LINES]
        return "<agent_identity>\n" + "\n".join(capped) + "\n</agent_identity>"
    except Exception:
        log.debug("Failed to build identity context (G1 layer)", exc_info=True)
        return ""


def _build_geode_memory_context() -> str:
    """G2: Load .geode/MEMORY.md project meta-index.

    Reads the file and extracts non-empty content lines (skipping blank
    placeholder sections). Capped at ``_MAX_SECTION_LINES`` lines.
    """
    try:
        memory_path = get_project_root() / ".geode" / "MEMORY.md"
        if not memory_path.exists():
            return ""

        content = memory_path.read_text(encoding="utf-8")
        # Extract meaningful lines (headers + content, skip empty placeholders)
        meaningful: list[str] = []
        for line in content.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            # Skip placeholder lines like "(실행 결과가 여기에 기록됩니다)"
            if stripped.startswith("(") and stripped.endswith(")"):
                continue
            meaningful.append(stripped)

        if len(meaningful) <= 1:
            # Only title, no real content
            return ""

        capped = meaningful[:_MAX_SECTION_LINES]
        return "<project_memory>\n" + "\n".join(capped) + "\n</project_memory>"
    except Exception:
        log.debug("Failed to build geode memory context (G2 layer)", exc_info=True)
        return ""


_CONTEXT_LEAK_RE = re.compile(r"\s*\[context:\s.*?\]\s*$", flags=re.DOTALL)


def _sanitize_learned_pattern(line: str) -> str:
    """G9 (2026-05-12) — strip raw prior-conversation context from a learned pattern.

    ``user_profile/learned.md`` rows look like::

      - [2026-05-07] [validation] Validated: 좋아. 2번 플랜 실행 부탁해. [context: 수집 완료. ...]

    The `[context: ...]` trailer is the user's prior-turn raw transcript,
    truncated. Injecting it into every system prompt leaked 30+ raw user
    messages per call (privacy + cost), and contaminated alignment-audit
    scenarios. Strip the trailer, cap the surviving prefix at 120 chars.
    """
    stripped: str = _CONTEXT_LEAK_RE.sub("", line).rstrip()
    if len(stripped) > 120:
        stripped = stripped[:117] + "..."
    return stripped


def _build_learning_context() -> str:
    """G3 layer: Load learned patterns from UserProfile.

    Sources: ~/.geode/user_profile/learned.md (auto_learn hook output).
    LEARNING.md is deprecated — UserProfile is the single source of truth.
    Capped at ``_MAX_SECTION_LINES`` lines AND per-line raw context
    stripped per G9 (2026-05-12) so the user's prior-turn transcripts
    do not leak into every system prompt.
    """
    try:
        from core.tools.profile_tools import get_user_profile

        profile = get_user_profile()
        if profile is None:
            return ""

        patterns = profile.get_learned_patterns()
        if not patterns:
            return ""

        sanitized = [_sanitize_learned_pattern(p) for p in patterns[:_MAX_SECTION_LINES]]
        sanitized = [s for s in sanitized if s]
        if not sanitized:
            return ""
        return (
            "<agent_learning>\n"
            "Patterns learned from the user's behaviour. Apply them to tailor "
            "responses, but never adopt them as your own traits.\n"
            + "\n".join(sanitized)
            + "\n</agent_learning>"
        )
    except Exception:
        log.debug("Failed to build learning context (G3 layer)", exc_info=True)
        return ""


def _build_project_memory_context() -> str:
    """G4: Build runtime project memory (insights + rules) from ProjectMemory.

    G4 needs full rule details (name + paths), so it calls
    ``mem.list_rules()`` directly rather than ``get_active_rule_names()``.
    """
    try:
        from core.memory.project import ProjectMemory

        mem = ProjectMemory()
        if not mem.exists():
            return ""

        parts: list[str] = []

        # Recent insights (last 5 lines from PROJECT.md's recent insights section)
        content = mem.load_memory()
        if "## 최근 인사이트" in content:
            section = content.split("## 최근 인사이트")[1]
            lines = [ln.strip() for ln in section.split("\n") if ln.strip().startswith("- ")]
            if lines:
                parts.append("Recent insights:\n" + "\n".join(lines[:5]))

        # Active rules summary (detailed — name + paths)
        rules = mem.list_rules()
        if rules:
            rule_summaries = [
                f"- {r['name']} (paths: {', '.join(r.get('paths', []))})" for r in rules[:5]
            ]
            parts.append("Active analysis rules:\n" + "\n".join(rule_summaries))

        if not parts:
            return ""
        return "<runtime_rules>\n" + "\n\n".join(parts) + "\n</runtime_rules>"
    except Exception:
        log.debug("Failed to build project memory context (G4 layer)", exc_info=True)
        return ""
