# R6.3 Extension Trust and Least Authority

Date: 2026-08-23

Roadmap package: R6.3 (`BND-004`, `TRUST-001`, `TRUST-002`)

Base: `origin/develop@586e29b663a959742ab4b4dac1dafb542b394f73`

## Problem

GEODE already has four extension-shaped surfaces, but their lifecycle and
authority rules disagree:

| Surface | Current discovery | Current execution boundary | Gap |
|---|---|---|---|
| Skills | `SKILL.md` metadata, body loaded lazily | in-process prompt expansion; dynamic context can spawn a shell | no shared trust decision before body/executable use |
| Filesystem hooks | `hook.yaml` or `hook.py` | discovery imports class-only hooks; loader imports handlers | executable discovery and load occur before trust |
| MCP servers | TOML/JSON config | subprocess over stdio | child inherits the whole process environment; no common trust/grant state |
| LLM adapters | package entry-point metadata | entry point is loaded and factory instantiated during discovery | trust label is recorded after executable load |

The result is not one honest third-party contract. Startup cannot explain the
difference between installed, enabled, trusted, granted, rejected, and
degraded extensions, and capability-confined execution can accidentally be
presented as stronger than an ordinary Python process boundary.

## Frontier research summary

### OpenClaw

Primary sources:

- [`docs/plugins/manifest.md`](https://github.com/openclaw/openclaw/blob/main/docs/plugins/manifest.md)
- [`docs/plugins/architecture.md`](https://github.com/openclaw/openclaw/blob/main/docs/plugins/architecture.md)
- [`src/plugins/discovery.ts`](https://github.com/openclaw/openclaw/blob/main/src/plugins/discovery.ts)

Adopt:

- read a non-executing manifest before plugin code;
- make precedence, duplicate origin, compatibility failure, and rejected paths
  observable;
- separate fresh discovery metadata from the code/runtime cache created only
  after load.

Adapt:

- keep each GEODE surface's existing manifest/config rather than introducing
  one replacement plugin file format;
- project those records into one small immutable decision vocabulary.

Reject:

- a new process-global mutable plugin manager;
- a broad plugin SDK before two independent third-party consumers need it.

### Codex

Primary sources:

- [`codex-rs/core/src/exec_policy.rs`](https://github.com/openai/codex/blob/main/codex-rs/core/src/exec_policy.rs)
- [`codex-rs/core/src/tools/sandboxing.rs`](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/sandboxing.rs)
- [`codex-rs/protocol/src/protocol.rs`](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs)

Adopt:

- keep policy/approval separate from the actual OS sandbox;
- make sandbox/network policy explicit and fail closed when requested
  isolation cannot be constructed;
- preserve a typed decision record suitable for bounded diagnostics.

Adapt:

- reuse GEODE's existing `sandbox-exec`/`bwrap` resolution and stdio MCP
  process boundary where it provides a real containment seam;
- scrub ambient credentials and pass only explicitly granted environment
  values to a confined child.

Reject:

- calling `subprocess` or Python import isolation a sandbox;
- silently weakening a requested confined execution mode when the host lacks
  an OS sandbox.

### Codex Cloud

The internal extension implementation is not public. No implementation detail
is inferred. Only the public preflight/apply separation is retained as a
constraint: validate and authorize before side effects.

### autoresearch

Primary source:

- [`program.md`](https://github.com/karpathy/autoresearch/blob/master/program.md)

Adopt:

- explicit `CAN`/`CANNOT` boundaries;
- a frozen acceptance harness;
- the simplicity criterion: keep the smallest change that satisfies the
  measured invariant.

Reject:

- importing the single-file experiment loop or its git-reset workflow into
  runtime extension management.

## Decision

Use one neutral immutable descriptor/decision vocabulary and keep the four
surface loaders.

```text
surface manifest/config/entry-point metadata
                 │  (no executable load)
                 ▼
        ExtensionDescriptor
                 │
          ExtensionPolicy
                 │
                 ▼
         ExtensionDecision
        ├── disabled/rejected/degraded → diagnostic only
        ├── trusted in-process         → narrow ExtensionContext
        └── capability-confined        → OS sandbox + brokered protocol
```

The policy file is operator-owned and separate from extension-owned metadata.
It records enablement, trust, requested execution mode, and granted
capabilities by stable `surface:name` ID. Bundled first-party contributions are
classified explicitly and do not masquerade as third-party extensions.

`ExtensionContext` is an immutable mapping of only the granted ports. It is an
API discipline boundary for fully trusted in-process code, not a Python
security boundary.

MCP stdio is the existing brokered protocol. A capability-confined MCP server
receives a clean environment plus explicit grants and must be wrapped by a
real OS sandbox. If the supported sandbox is unavailable, the server is
degraded and is not launched. Trusted MCP servers retain the compatibility
path, but their trust state is explicit and visible.

## Minimum implementation

1. Add the immutable descriptor, policy, decision, context, report, and
   sandbox-launch helpers under the neutral kernel.
2. Make hook discovery manifest-only. Class-only `hook.py` extensions are
   rejected with a migration diagnostic; trusted handler import happens only
   after authorization.
3. Split LLM entry-point enumeration from `entry_point.load()` and require an
   approved in-process decision before factory import/instantiation.
4. Project Skill and MCP metadata into the same state vocabulary. Block skill
   body/dynamic execution until authorized. Launch confined MCP only with a
   clean environment, explicit grants, and an available OS sandbox.
5. Expose bounded startup status, collisions, missing grants, degradation, and
   deterministic teardown through existing runtime health/lifecycle owners.
6. Update the current operator docs, changelog, generated documentation, and
   architecture baseline.

## Explicit non-goals

- No universal replacement plugin manifest.
- No second tool/adapter/hook/skill registry.
- No broad runtime container in `ExtensionContext`.
- No Python-only sandbox claim.
- No arbitrary broker RPC framework; MCP keeps its existing stdio protocol.
- No discovery of bundled `geode_product` features as third-party plugins.
- No R6.4 public-hook or R7 scenario-suite expansion.

## Acceptance and anti-deception matrix

| Invariant | Runnable evidence |
|---|---|
| discovery does not execute code | poison hook/entry-point modules mutate a sentinel on import; metadata discovery leaves it untouched |
| trust precedes load | rejected/untrusted poison factories are never loaded or instantiated |
| states are distinct and observable | exact decision snapshots cover installed, disabled, trusted, granted, rejected, and degraded states |
| collisions fail loud | duplicate stable IDs report both origins before load |
| narrow trusted context | trusted factory receives only its declared immutable port mapping |
| no fake sandbox | confined launch with no OS sandbox returns degraded and never calls `Popen` |
| no ambient credentials | confined child environment equals the explicit allowlist and omits parent secrets |
| broker cannot bypass declared authority | sandbox argv is deny-default/no-network, exposes only system runtime reads plus an isolated scratch directory, and passes exactly the configured environment |
| reload does not mutate an active decision | adapter reload publishes a new generation; Skill and MCP owners rebuild decisions; the loaded Hook set lives until owner teardown |
| stateful owners tear down deterministically | Hooks unregister and close once in reverse load order; MCP clients terminate and clean broker scratch; the current adapter ABI claims no cleanup callback |
| resource identity is declared | mutating extension descriptors carry explicit resource keys; no argument-name inference |
| compatibility is bounded | trusted legacy no-argument factories and trusted MCP configs keep their documented behavior |

## Verification

Run narrow tests first, then the repository gates required by §9. Do not run
`-m live` without separate approval. Local evidence must name any environmental
failure exactly; CI remains authoritative for the complete non-live matrix.
