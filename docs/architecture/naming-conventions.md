---
title: GEODE code conventions
status: living
authority: code-conventions
evidence_snapshot:
  date: 2026-08-25
  commit: 2c39a6871d156b6b01777f638028fe52015b5961
related:
  - AGENTS.md
  - CLAUDE.md
  - docs/architecture/package-classification.md
  - docs/workflow.md
  - pyproject.toml
  - site/src/data/geode/architecture-baseline.json
---

# GEODE code conventions

This is the canonical convention guide for GEODE code. It covers architecture,
module and symbol naming, Python types and classes, persisted data, tests, the
Next.js site, and versioning. The cross-host
[`geode-code-conventions`](../../.agents/skills/geode-code-conventions/SKILL.md)
skill applies this guide during implementation and review.

The guide records two kinds of evidence without confusing them:

- **Required** rules come from executable configuration, CI, `AGENTS.md`, or a
  named architecture contract. A change must satisfy them.
- **Preferred** rules are deliberate dominant patterns in the measured tree.
  Follow them for new work unless the local subsystem has a stronger reason.
  A historical outlier is evidence to inspect, not a template to copy.

When this prose conflicts with an executable gate, the gate wins and this file
must be corrected in the same change. When no rule exists, inspect the nearest
canonical siblings before introducing a new pattern.

## Evidence snapshot

The 2026-08-25 scan used the synchronized v1.0.26 tree after the Crucible module
rename. Exact generated inventory remains owned by
`site/src/data/geode/architecture-baseline.json`; this table explains the
measured shape that informed the conventions.

| Surface | Measured shape |
|---|---|
| Production Python | 574 files / 183,172 LOC: `core` 412, `evals` 89, `evolve` 73 |
| Python tests | 693 files / 187,016 LOC; 9,744 declared `test_*` functions |
| Production definitions | 820 classes, 5,651 functions, 5,649 explicit return annotations |
| Data/class forms | 334 dataclasses, 68 Pydantic models, 26 Protocols, 7 TypedDicts, 38 enums, 2 ABCs, 52 `*Error` classes |
| Dataclass immutability | 199 frozen; 120 slotted; 100 both frozen and slotted |
| Imports | 5,985 absolute import statements; 106 level-one sibling-relative imports; no parent-relative imports |
| Public exports | 230 production modules declare `__all__` |
| Site | 248 TypeScript files: 233 TSX and 15 TS; strict TypeScript; all non-route filenames use kebab-case |

The counts are an audit snapshot, not count ratchets. Do not update them for an
ordinary file addition. Refresh the snapshot only when re-auditing the
conventions themselves.

## 1. Architecture and dependency direction

### 1.1 Top-level ownership

Production Python has three packages and one dependency direction:

```text
evolve  ->  evals  ->  core
```

| Root | Owns | May depend on |
|---|---|---|
| `core/` | AgenticLoop runtime, operator surfaces, provider adapters, tools, memory, hooks, process wiring | standard library, declared dependencies, `core` |
| `evals/` | measurement, Petri, benchmarks, seed generation, GEO | `core`, `evals` |
| `evolve/` | Crucible, scaffold search, campaign state, promotion | `core`, `evals`, `evolve` |
| `scripts/` | repository operations, validation, generation, release support | canonical package APIs; it is not a fourth product layer |
| `site/` | static public documentation and portfolio | generated data and public contracts; runtime code never imports it |
| `tests/` | mirrored unit, integration, script, and visualization checks | the surface under test |

`core` never imports `evals` or `evolve`; `evals` never imports `evolve`.
Import-linter enforces both directions.

### 1.2 Process and capability boundaries

`pyproject.toml` owns seven import-linter contracts. Their current intent is:

1. `core.cli` does not own server or messaging processes.
2. `core.agent` stays independent of CLI and server entry points.
3. `core.server` may host the agent but never imports CLI.
4. `core.messaging` remains capability-pure: no CLI, server, or agent imports.
5. Runtime does not import evaluation or evolution.
6. Evaluation does not import evolution.
7. `core.tools.handlers` does not reach into agent, CLI, server, or UI layers.

`core.wiring` is the composition boundary. Cross-process or cross-subsystem
services pass through constructors, grouped configuration, `ToolContext`, or
another existing typed context. Do not bypass a boundary with a new global,
late import, or service-locator `ContextVar`.

### 1.3 Abstraction ladder

Use the first form that expresses the real ownership:

1. A function for stateless behavior.
2. A focused module when several functions share one responsibility.
3. A dataclass when named state must travel together.
4. A concrete class when behavior owns state or a lifecycle.
5. A Protocol at a genuine consumer/provider boundary.
6. A registry only when multiple entries are discovered or selected by name.
7. An adapter when an external backend or native contract must be translated.

Do not add an interface for one implementation, a factory for one constructor,
or a package for one file. GEODE has 26 structural Protocols but only two ABCs:
Protocol is the normal port form; ABC is reserved for a real shared algorithm
or lifecycle that subclasses extend.

### 1.4 Public and private package surfaces

- Use `__init__.py` plus `__all__` to expose a small stable package surface.
- Keep implementation-only modules or symbols prefixed with `_`.
- A package facade may re-export its canonical implementation; it must not keep
  an obsolete implementation alive.
- Compatibility modules get at most the documented one-release grace. Migrate
  callers and delete the shim; Git history is the archive.
- Optional dependencies are imported lazily at the boundary that uses them.

## 2. Packages, files, and symbols

### 2.1 Package and module names

Python packages and modules use `snake_case`. The package supplies context, so
the child name states only its remaining responsibility:

```text
evolve/crucible/admission/regime.py
evolve/crucible/admission/budget.py
evolve/crucible/admission/forecast.py
evolve/crucible/admission/pilot.py
evolve/crucible/assays/receipt.py
```

The earlier `runtime_regime.py`, `runtime_budget.py`, and related filenames
repeated information already supplied by `evolve/crucible`. Their persisted
schema identifiers retained `runtime-*` because artifact identity is a
separate compatibility contract.

Required naming constraints:

- Avoid abstract catch-all package names such as `common`, `helpers`, `lib`,
  `misc`, `text`, `storage`, or `runtime_state`.
- Do not create same-name nesting (`x/x/`) or a one-file package.
- Rename `_helpers.py`, `_utils.py`, or `_misc.py` to the actual responsibility
  once it has a real caller.
- A leading `_` is valid for a package-private seam, not as a substitute for a
  meaningful noun.
- `__init__.py`, `__main__.py`, `page.tsx`, and `layout.tsx` retain their
  framework-defined names.

### 2.2 File placement

- Put behavior with the layer that owns its decision, not the layer that calls
  it most often.
- Keep a vertical external integration together: contract, adapter, runner,
  and normalization can share a benchmark package when they change together.
- Keep platform adapters outside benchmark identity. A platform may host many
  benchmarks; a benchmark remains the measurement authority.
- Group closely related value types in a local `models.py` only when the
  package name makes the domain unambiguous. Do not create a repository-wide
  models bucket.
- Tests mirror the production root and package when practical:
  `evolve/crucible/admission/budget.py` maps to
  `tests/evolve/crucible/admission/test_budget.py`.

### 2.3 Function names

Functions use `snake_case`; async functions follow the same semantic name.
Use verbs consistently:

| Prefix | Meaning |
|---|---|
| `build_*` / `create_*` | construct a new value or owned object |
| `load_*` / `read_*` | read existing state; `load` may parse or validate |
| `write_*` / `persist_*` / `append_*` | mutate an owned store |
| `resolve_*` | choose one canonical value from several sources |
| `parse_*` / `normalize_*` | change representation without granting validity |
| `validate_*` / `verify_*` / `require_*` | reject invalid input or unmet preconditions |
| `register_*` | add an entry to a registry or hook surface |
| `bind_*` / `wire_*` | connect already-created capabilities |
| `handle_*` / `cmd_*` | entry-point dispatch, not domain logic |
| `to_*` / `from_*` | explicit representation conversion |

Avoid pairs whose verbs differ but behavior does not. Names like `process`,
`manage`, or `do` need a domain noun or a more exact verb.

### 2.4 Class names and suffixes

Classes use `PascalCase`; a leading `_` marks a private implementation. Choose
the suffix by responsibility, not prestige:

| Form | Responsibility |
|---|---|
| `*Config` | operator or construction inputs |
| `*Spec` | frozen executable/measurement contract |
| `*Request` / `*Result` | one operation's input/output envelope |
| `*State` | mutable or persisted lifecycle state |
| `*Record` / `*Receipt` / `*Manifest` / `*Report` | evidence at increasing aggregation boundaries |
| `*Adapter` | translation to an external/provider contract |
| `*Registry` | name-to-capability discovery or selection |
| `*Store` | durable or indexed state ownership |
| `*Policy` | deterministic admission or decision rule |
| `*Runner` | orchestration of an executable unit |
| `*Error` | a typed failure callers may distinguish |
| `*Tool` | model-callable capability |

Protocols are named for the role (`LLMAdapter`, `Tool`, `HookPlugin`), not
mechanically suffixed `Protocol`. `Base*` is reserved for a genuine reusable
base implementation, not used merely to make inheritance possible.

### 2.5 Constants, tools, and events

- Module constants use `UPPER_SNAKE_CASE`; private constants add a leading `_`.
- Environment variables use the `GEODE_*` namespace.
- Tool registry names are `snake_case`; tool classes use `<Noun>Tool`,
  `<Verb><Noun>Tool`, or an established source-specific form.
- `RuntimeEvent` members are `UPPER_SNAKE_CASE` with `lower_snake_case` wire
  values. Lifecycle pairs use `*_STARTED` / `*_ENDED`; failures use
  `*_FAILED`; state-rich transitions use one event plus a typed payload rather
  than one enum per state.
- Do not expand a stable public hook or tool surface merely to mirror an
  internal implementation detail.

### 2.6 TypeScript and React names

- Non-route `.ts` and `.tsx` filenames use kebab-case.
- React components and exported types use `PascalCase`; functions and values
  use `camelCase`; constants may use `UPPER_SNAKE_CASE` when truly fixed.
- Next.js route modules use framework names and default-export their page or
  layout component. Shared components use named exports.
- Prefer `type` for unions, props, and data shapes. Use `interface` only when
  declaration merging or extension is the point. The measured tree has 76
  type declarations, 7 interfaces, and 6 classes.

## 3. Python typing and class design

Python targets 3.12, uses built-in generics (`list[str]`), `X | None` unions,
Ruff formatting at 100 columns, and strict mypy. New public functions and
methods have complete parameter and return annotations. Do not add `# type:
ignore` to avoid understanding a boundary.

### 3.1 Choose the data form

| Need | Preferred form |
|---|---|
| Internal value object | `@dataclass(frozen=True, slots=True)` |
| Mutable owned runtime state | dataclass, with `slots=True` when dynamic attributes are not needed |
| External/config/LLM validation | Pydantic `BaseModel` |
| JSON-shaped mapping passed without construction | `TypedDict` |
| Reusable closed persisted vocabulary | `StrEnum` |
| Small local closed vocabulary | `Literal[...]` |
| Structural consumer/provider port | `Protocol`, optionally `@runtime_checkable` only when runtime checks exist |
| Shared template algorithm with subclass hooks | `ABC` |

Immutability is deliberate, not ceremonial. Freeze specs, requests, receipts,
and identity-bearing values when callers must replace rather than mutate them.
Keep mutable lifecycle state mutable when mutation is its purpose.

Use `field(default_factory=...)` for mutable defaults. Prefer tuples and
frozensets for immutable collections. Accept `Mapping` or `Sequence` when a
caller need not provide a concrete container; return a concrete collection
when the API promises one.

### 3.2 Boundary typing

`Any` is allowed at SDK, JSON, plugin, and legacy boundaries, but it is not a
domain model. Validate or narrow it immediately with a schema, Pydantic model,
`isinstance`, or a focused conversion function. Keep the untyped value from
spreading through the call graph.

Do not use truthiness to collapse valid zero, empty, or false values into
missing data. In evaluation records, observed `0` is a label and `null` means
missing. Apply the same distinction to timeouts, limits, scores, and optional
identifiers.

### 3.3 Construction and lifecycle

- Inject services through constructors or an existing context object.
- A `ContextVar` may carry request identity, diagnostics, request-local mutable
  state, or cache state. The generated inventory records zero service-locator
  ContextVars; keep it that way.
- Every setter/binder has an explicit reset or teardown path.
- I/O-facing provider and runtime APIs are async-native. A sync wrapper belongs
  only at a real CLI, SDK, or compatibility boundary.
- A background task has an owner, cancellation path, and awaited shutdown.
- Close files, clients, subprocesses, and database resources in `finally`, a
  context manager, or the owning lifecycle's shutdown method.

## 4. Data, schemas, and persistence

### 4.1 One authority per record

Every persisted record has one canonical writer, one declared authority, and a
reader that validates before use. Derived views point back to native evidence;
they do not rewrite it. The evaluation join is:

```text
example -> rollout -> trajectory -> reward
```

Native benchmark receipts and immutable trajectories remain authorities;
learning views are digest-bound projections.

### 4.2 Schema identity

Keep schema identity next to the builder and validator as a named constant.
GEODE has established families with different historical delimiters:

- public observability records: `geode.<resource>@<major>`;
- subsystem/public envelopes: `<namespace>.<resource>.v<major>`;
- native external records: the upstream identity, often suffixed `@native`;
- algorithm identities: a semantic name plus `.v<major>`.

Preserve the delimiter and field name already used by a family (`schema_id`,
`schema`, or `schema_version`). Do not rename immutable artifacts merely to
make all families look alike. A new incompatible writer gets a new version;
the previous reader remains only through an explicit, tested adapter.

If both a string schema ID and integer `schema_version` exist, they serve
different consumers and must agree. Database migration versions, wire protocol
versions, statistical method versions, and the Python package version are
separate axes; never advance one as a proxy for another.

### 4.3 Write discipline

- Validate the complete artifact before replacing its destination.
- Use the existing atomic-write helpers for mutable files.
- Use append-only records for attempts, events, and evidence where history is
  part of the contract.
- Bind derived results to source digests and stable IDs.
- Keep runtime/user state outside the immutable wheel and source-controlled
  defaults outside mutable user homes.
- Never overwrite published evidence or a released package artifact.
- Generated files identify their source and generator. Edit the source, run the
  generator, and commit source plus generated output together.

## 5. Errors, logging, and trust boundaries

- Domain- or boundary-specific exceptions end in `Error` and inherit the
  narrowest useful built-in or local base.
- Catch only failures the current layer can translate, retry, or clean up.
  Re-raise unexpected failures; use `raise ... from exc` when changing error
  type so causality survives.
- Validate paths, external payloads, credentials, tool arguments, and schema
  versions at their trust boundary. Fail closed when authority or identity is
  ambiguous.
- Library modules use `logging.getLogger(__name__)`. Direct terminal output is
  reserved for CLI/entry-point rendering and explicit scripts.
- Structured logs and events carry bounded identifiers and metadata, not raw
  screenshots, base64 blobs, prompts with secrets, tokens, passwords, or
  credentials. Use the existing redaction helpers.
- Do not silently convert an exception into an empty success. A recoverable
  result must encode its error type and recovery guidance explicitly.

## 6. Imports and dependencies

- Use absolute imports across packages and subsystem boundaries.
- Level-one relative imports are acceptable inside a tightly coupled private
  package. Parent-relative imports are not.
- Keep imports at module level unless lazy loading prevents an optional
  dependency, circular bootstrap, or measured cold-start cost. Explain the
  non-obvious lazy import locally.
- Declare every directly imported third-party package. `deptry` owns drift
  detection; optional extras own opt-in integrations.
- Reuse the standard library or an installed dependency before adding another
  package. A new dependency needs a real consumer and belongs in the narrowest
  base, extra, or development group.
- Never assume a third-party SDK or backend capability from a type alone.
  Ground the contract in current primary documentation/source; require an
  approved live test when the backend behavior is undocumented.

## 7. Tests and verification

- Test files use `test_<responsibility>.py`; test functions describe observable
  behavior as `test_<condition>_<outcome>`.
- Mirror the production package for unit tests. Use `tests/integration/` for a
  real cross-subsystem contract, `tests/scripts/` for repository tooling, and
  `tests/visualizations/` for render-specific checks.
- Prefer the smallest public seam that proves behavior. Assert both writer and
  reader, registration and dispatch, or bind and reset when wiring is the risk.
- Keep deterministic fake/stub classes private to the test unless they are
  reused through a nearby `conftest.py` fixture.
- Parameterize meaningful input partitions; do not generate test matrices that
  add no new failure mode.
- Mark real network, provider, or paid calls `live`. The default test command
  excludes them, and running them requires explicit approval.
- Never make a change green by deleting, skipping, or weakening a test or
  static gate. Update the assertion only when the contract intentionally
  changed.

Required verification is risk-scaled but reports the exact commands run.
Python changes normally exercise targeted pytest, Ruff check/format, strict
mypy for touched production roots, and import-linter. Site changes exercise
ESLint, TypeScript/Next build, and the relevant export or render gate.

## 8. Site conventions

The public site is a private Next.js application, not a second GEODE product
version. Its `package.json` version stays independent; public GEODE version
data comes from `pyproject.toml` through `site/scripts/sync-stats.mjs`.

- TypeScript remains `strict`, `noEmit`, and `isolatedModules`.
- Use the `@/*` alias for cross-directory `site/src` imports and local relative
  imports for close siblings.
- Default to server components. Add `"use client"` only for hooks, browser APIs,
  or interactive state.
- Use function components; do not introduce React component classes.
- Follow `site/DESIGN.md` for layout, tokens, accessibility, motion, and visual
  constraints. Code convention does not override the design SOT.
- `site/src/data/geode/sot.ts`, `changelog.ts`, public `llms*.txt`, and exported
  markdown are generated views. Do not hand-edit them.

## 9. Versioning and compatibility

### 9.1 Product release version

`pyproject.toml` is the package metadata authority. A release stamps the same
version in five reviewed source locations:

1. `pyproject.toml`;
2. the release heading in `CHANGELOG.md`;
3. `CLAUDE.md`;
4. `README.md`;
5. `README.ko.md`.

Then regenerate `uv.lock`, `site/src/data/geode/sot.ts`,
`site/src/data/geode/changelog.ts`, `site/public/llms.txt`, and
`site/public/llms-full.txt` through their owning commands. Do not hand-stamp a
generated mirror.

Post-1.0 routine releases, including features, default to PATCH. MINOR and
MAJOR are operator-declared milestones; check pledged deprecation versions and
obtain explicit operator approval. Documentation-only work does not bump the
version.

### 9.2 Compatibility changes

- Preserve user-facing CLI, wire, artifact, and public Python contracts unless
  the change explicitly versions or deprecates them.
- A deep internal module rename migrates all callers in one change and does not
  need an alias when no released consumer exists.
- A released compatibility facade is bounded to one release unless a named
  external contract requires longer support.
- Writers emit only the current schema. Legacy readers are explicit adapters
  with tests and a removal condition.
- Historical changelog entries, dated plans, and immutable evaluation evidence
  remain factual; do not rewrite old paths as though they existed then.

### 9.3 Immutable promotion

A released version is one immutable set of bytes across the annotated Git tag,
GitHub assets, PyPI wheel/sdist, and checksum manifest. Never move a published
tag, replace an artifact, or reuse a burned version. Repair only missing files
after byte equality of the published subset is proven.

## 10. Review checklist

Before finalizing a code change, answer:

1. Which root owns the decision, and does dependency direction still hold?
2. Does the package already provide the context repeated in the new name?
3. Is the selected type the smallest one that carries the required validation,
   mutability, and lifecycle?
4. Is there one canonical writer, schema identity, and version axis?
5. Are construction, teardown, failure, logging, and redaction explicit?
6. Does the test sit at the boundary most likely to disconnect?
7. Did every generated mirror and changelog obligation follow its source?
8. Were the exact targeted and broad gates reported without hiding exit codes?

If a decision does not fit this guide, document the exception in the PR and
update this file only when the exception is intended to become a reusable
convention.
