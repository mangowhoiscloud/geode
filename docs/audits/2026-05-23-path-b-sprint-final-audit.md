# Path-B sprint final audit — 2026-05-23

End-of-session scope audit + alignment pass for the Path-B
``LLMAdapter`` migration sprint that ran in this session. Five PRs
merged to develop:

| Step | PR | Outcome |
|------|----|---------|
| I.a — Codex OAuth header dedup | #1542 | 4 inline header dicts collapsed onto :func:`core.llm.providers.codex.build_codex_oauth_headers` |
| J-b.1 — control-layer SoT relocation | #1549 | ``[self_improving_loop.petri.<role>]`` + ``[self_improving_loop.mutator]`` → ``[self_improving_loop.autoresearch.<role>]`` + ``[self_improving_loop.autoresearch.mutator]`` (1-release back-compat with ``DeprecationWarning``) |
| J-b.2 — mutator runner API path | #1555 | ``runner.py:_default_llm_call`` API branch migrated from legacy ``AgenticLLMPort`` to Path-B ``resolve_for + acomplete`` |
| I.b — Codex reasoning-replay pin | #1554 | inspect_ai integration documented + 3-test smoke ratchet |
| I.c — ``adapter_health(name)`` accessor | #1556 | Ergonomic registry wrapper over ``LLMAdapter.test_environment`` |

Plus one fix-up landed alongside J-b.1: the
``tests/test_autonomous_safety.py`` xdist isolation fixture closed a
pre-existing flake that PR-CL-A1 left on develop.

## Sweep results (cross-tree drift)

Five grep sweeps run against the merged develop tip:

| Sweep | Production code | Tests | Docs | Status |
|-------|-----------------|-------|------|--------|
| ``cfg.mutator.`` / ``cfg.petri.`` (non-``autoresearch``) | 0 hits | 0 hits | 0 hits | **clean** — J-b.1 migration complete |
| ``[self_improving_loop.petri.*]`` / ``[self_improving_loop.mutator]`` literal | 0 production-runtime hits (only docstrings + ``DeprecationWarning`` text + back-compat reader) | 12 files (legitimate — back-compat migration fixtures) | ``docs/operator-mode-a.md`` (FIXED in this audit) + 5 historical plan docs (pinned-in-time, left as-is) | **aligned** |
| ``"originator": "codex_cli_rs"`` literal | 2 hits — both legitimate (1 inside ``build_codex_oauth_headers`` itself, 1 in ``core.llm.registry.codex_cloudflare_headers`` for the Cloudflare User-Agent + originator-only path, NOT a JWT-augmented duplicate) | 0 hits | n/a | **clean** — I.a dedup complete |
| ``resolve_agentic_adapter`` callsites | 2 production code consumers remain: ``core/agent/loop/_reflection.py:251`` and ``core/agent/loop/agent_loop.py:1998`` | n/a (testing pattern legitimate) | n/a | **backlog** — see below |
| ``adapter.agentic_call(...)`` non-legacy callers | Same 2 as above | n/a | n/a | **backlog** |

## Remaining drift — explicit backlog

Two production-code surfaces still consume the legacy ``AgenticLLMPort``
contract after J-b.2 migrated the mutator. They are *not* drift from
this sprint's claims; they are documented here as the natural
next-step targets if the Path-B migration continues:

### J-b.3 (backlog) — reflection node API migration

- **Site**: ``core/agent/loop/_reflection.py:59`` import +
  ``:251`` ``resolve_agentic_adapter(provider)`` + ``:290``
  ``adapter.agentic_call(...)``.
- **Scope mirror**: identical pattern J-b.2 migrated for the mutator
  — a single sync-async call site that wraps a non-streaming LLM
  invocation. ~50 LOC delta.
- **Why deferred**: reflection's call shape (``temperature=cognitive_reflection_temperature``,
  ``max_tokens=cognitive_reflection_max_tokens``) is a separate config
  surface; migration should keep the per-knob mapping intact.
  Sizing-wise it's I.a-grade, not a sprint.

### J-b.4 (backlog) — AgenticLoop main-loop API migration

- **Site**: ``core/agent/loop/agent_loop.py:1998``
  ``self._adapter.agentic_call(...)`` inside the main round body.
- **Scope**: the whole agentic loop's per-round LLM dispatch. Streaming
  + tool-use + Codex reasoning replay + telemetry all run through this
  call. Migration is **substantially larger** than the rest of the
  Path-B sprint combined; the Codex reasoning replay alone needs the
  per-``Message`` ``codex_reasoning_items`` annotation to be wired into
  the loop's message accumulator (currently a runtime-attached
  ``dict`` key on the assistant message, not the typed ``Message``
  field).
- **Why deferred**: this is multi-PR work. Treat as a separate sprint.

## CLI-subscription text-output gap (J-b.2 caveat)

Step J-b.2's docstring + CHANGELOG explicitly recorded:

> The CLI-subscription branches (``claude-cli`` / ``openai-codex``
> source) **deliberately remain on the dedicated ``invoke_claude_cli``
> / ``invoke_codex_cli`` helpers** in
> :mod:`core.self_improving_loop.cli_subprocess` rather than going
> through the ``ClaudeCliAdapter`` / ``CodexCliAdapter`` built-ins
> because the built-in adapters speak the streaming-JSON event
> protocol used by the agentic loop, whereas the mutator parser
> consumes plain text.

This is a documented seam between two adapter implementations. The
fix — adding a text-output mode to both ``ClaudeCliAdapter`` and
``CodexCliAdapter`` — is tracked as a follow-up. It belongs to the
same J-b.4 sprint above (the agentic loop migration would naturally
make the CLI adapters more flexible).

## Doc surfaces updated in this audit

- ``docs/operator-mode-a.md`` — Mode B row now references
  ``[self_improving_loop.autoresearch.mutator]`` (new SoT) and notes
  the 1-release legacy section migration.

Plan documents under ``docs/plans/2026-05-21*`` are pinned-in-time
artifacts of their respective sprints; they record the namespaces
that were canonical when they were written. Leaving them as-is
matches the project convention (DONT-table style — each plan is a
frozen lesson).

## Anti-deception sweeps (verified)

| Sweep | Result |
|-------|--------|
| Stale ``cfg.mutator``/``cfg.petri`` in production | 0 |
| Stale legacy section literals in production runtime path | 0 |
| OAuth header dict duplication | 0 (post-I.a) |
| Codex MCP review across 5 PRs | All BLOCKER + HIGH closed |
| ``# type: ignore`` proliferation across sprint | 0 new (I.c LOW-fixed one) |
| CHANGELOG ↔ code parity | Every verb grep-provable per CANNOT rule |

## End-of-sprint summary

Path-B's adapter abstraction is now the SoT for:

1. Codex OAuth header construction (I.a)
2. Self-improving loop model selection (J-b.1)
3. Mutator runner LLM dispatch — API path (J-b.2)
4. Adapter readiness probing (I.c)

inspect_ai's stock pathway owns Codex reasoning replay for the petri
provider (I.b documented + pinned). Backlog J-b.3 + J-b.4 are the
remaining surfaces; they're tracked as separate sprints with explicit
scope rationale.
