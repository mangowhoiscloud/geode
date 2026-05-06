---
title: GEODE naming conventions — RESTful resource orientation
status: living
related:
  - docs/architecture/domain-free-core-audit.md
  - pyproject.toml ([tool.ruff.lint.flake8-tidy-imports.banned-api])
  - core/domains/port.py (DomainPort method taxonomy)
---

# GEODE naming conventions

GEODE follows a **resource-oriented** naming model — the same principle that
makes REST APIs readable. Each name describes *what a thing is*, not *what
process produced it* or *where its predecessor lived*. Predictability across
the codebase comes from a small number of bounded conventions, not from
strict mirroring of every directory tree.

This document codifies the rules that have emerged through v0.66.0 (the
first three steps of the domain-free-core refactor). New contributions
should follow them; deviations should land with a one-line rationale in the
PR.

---

## 1. Plugin internal layout

A plugin (`plugins/<domain>/`) is a Python package whose internal structure
follows two complementary rules:

| Pattern | When to use | Examples |
|---------|-------------|----------|
| **Mirror core** — `plugins/<domain>/<X>/<Y>.py` matches `core/<X>/<Y>.py` | A multi-file core subpackage is being domain-extracted | `core/cli/{batch,ip_names,search}.py` → `plugins/game_ip/cli/{batch,ip_names,search}.py`; `core/tools/data_tools.py:QueryMonoLakeTool` → `plugins/game_ip/tools/data_tools.py` |
| **Flat intent-named** — `plugins/<domain>/<noun>.py` at the package root | A single file/fragment is extracted, OR the file is a plugin-specific aggregation that has no obvious single-file core counterpart | `plugins/game_ip/{adapter,axes,wiring,prompt,scoring_constants}.py` |

**Why two rules?**
- A plugin's surface should read like *its own resources*, not like a
  carbon-copy of `core/`'s incidental layout. `axes.py`, `prompt.py`,
  `wiring.py`, `adapter.py` are first-class plugin resources.
- But when `core/<X>/` had a coherent multi-file subpackage that gets
  extracted, mirroring preserves intuition for developers who already know
  the core layout.

**The test**: an external developer scanning `plugins/game_ip/` should be
able to predict what each name contains without opening it.

Domain-shaped subpackages (`nodes/`, `fixtures/`, `config/`) are intent-named
by definition — they describe the plugin's own structure, not core's.

---

## 2. `DomainPort` method taxonomy

`DomainPort` is the contract every domain plugin implements
(`core/domains/port.py`). Method verbs map deliberately to action semantics
(REST analogy in parentheses):

| Verb prefix | Semantics | Direction | Examples |
|-------------|-----------|-----------|----------|
| (property) | trivial identity | read | `name`, `version`, `description` |
| `get_*` | parameterless read of plugin config | GET | `get_evaluator_axes`, `get_scoring_weights`, `get_tier_thresholds` |
| `list_*` | collection accessor returning a sorted list | GET | `list_fixtures` |
| `wire_*` | caller hands an object to install (mutation, no return) | PUT | `wire_context_assembler` |
| `build_*` | factory — caller passes args, gets a fully constructed object | POST | `build_task_graph`, `build_signal_adapter` |
| `compose_*` | string/template assembly from parts | POST | `compose_static_prefix` |
| `register_*` | subscribe a handler to an event/registry (future) | POST | (none yet — reserved for hook surfaces) |

Picking the right verb:
- **No args, returns config**: `get_*` or property.
- **Args, returns built object**: `build_*`.
- **Caller hands an object in, no return**: `wire_*`.
- **Returns a string assembled from parts**: `compose_*`.
- **Subscribes a handler**: `register_*`.

Don't invent new verbs unless none of the above fit. If two methods feel
identical except for verb, pick one.

---

## 3. TID251 banned-api message format

`[tool.ruff.lint.flake8-tidy-imports.banned-api]` entries (`pyproject.toml`)
follow a fixed format so error messages are scannable across the codebase:

```toml
"<old.dotted.path>".msg = "Moved to <new.dotted.path> (v<X.Y.Z> step <N>)."
```

- One sentence, period at the end.
- Mention the **target path** and the **release/step**, nothing else.
- Don't repeat phrases like "of the domain-free-core refactor" — that
  context belongs in `CHANGELOG.md` and `docs/architecture/domain-free-core-audit.md`,
  not in every lint message.

Each step PR adds the new bans inline; over time the file becomes a ledger
of every relocated symbol with its origin release.

---

## 4. PR titles and branches

| Element | Format | Examples |
|---------|--------|----------|
| PR title | Conventional Commits: `<type>(<scope>): <subject> — <descriptor>` | `feat(core): domain-free core step 3 — lifecycle/system_prompt seam` |
| Sequential refactor branch | `feature/<initiative>-step<N>` | `feature/domain-port-step1`, `feature/domain-port-step2` |
| Topic / hygiene branch | `feature/<topic>` or `chore/<topic>` | `feature/static-analysis-ratchet`, `feature/ruff-tid-bans` |
| Release prep branch | `release/v<X.Y.Z>` | `release/v0.66.0` |

`type` ∈ `{feat, fix, chore, docs, style, refactor, perf, test, ci}`.

---

## 5. Tool class names (`core/tools/`, `plugins/*/tools/`)

`<Verb><Noun>Tool` (action-oriented) or `<Noun>Tool` (resource-oriented) are
both accepted; pick whichever reads better for the operation. Be consistent
within a single tool family:

- `RunAnalystTool`, `RunEvaluatorTool`, `PSMCalculateTool`, `ExplainScoreTool`
  — analysis pipeline tools, action-oriented.
- `BashTool`, `WebSearchTool`, `ReadTool`, `WriteTool`, `EditTool` — generic
  capability tools, resource-oriented.
- `YouTubeSearchTool`, `RedditSentimentTool`, `SteamInfoTool` — signal
  scrapers, `<Source><Action>Tool`.

If you find yourself debating which form to use for a new tool, the
sibling tools in the same module set the precedent.

---

## 6. Hook event names (`core/hooks/`)

Hook events follow `<NOUN>_<PAST_PARTICIPLE>` (e.g. `ANALYST_COMPLETE`,
`SCORING_COMPLETE`, `PIPELINE_END`, `TOOL_EXEC_START`). Past tense reflects
"this event has occurred" semantics. New events should follow the same
shape; don't introduce verb-first names.

---

## What this isn't

This document is **not** an exhaustive style guide. It captures the
naming decisions that have proved load-bearing for GEODE's plugin
architecture and the v0.66.0 refactor. For Python style itself, defer to
`ruff` + `ruff format` (configured in `pyproject.toml`) and to the rules
that import-linter and TID251 already enforce.

When a future situation doesn't fit any of the patterns above, propose a
new convention in the PR that introduces it, and update this document
when it merges.
