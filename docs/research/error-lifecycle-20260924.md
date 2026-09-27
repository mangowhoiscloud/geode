# Error and resource lifecycle review — 2026-09-24

## Scope and authority

The operator requested an independent PR evaluating error handling and error
types, then clarified that the acceptance boundary is resource generation and
lifecycle: runtime, SDK clients, database connections and request-local state.
Trace construction → publication → use → failure cleanup → shutdown → recreation.
An exception inventory alone does not establish correct lifecycle behavior.

The existing convention is [naming conventions §5](../architecture/naming-conventions.md#5-errors-logging-and-trust-boundaries).
It already requires narrow exception bases, causal chaining, boundary validation,
bounded diagnostic metadata and explicit failed results. Extend that owner only
for missing reusable lifecycle rules. Do not create a second taxonomy or generate
one error subclass for every message. A distinct type needs a caller that makes
a distinct recovery decision.

## Primary comparison evidence

Retrieved on 2026-09-24. Upstream sources describe their own contracts; the
comparison below is a design assessment, not evidence of equivalent behavior.

| Authority | Observed contract | GEODE decision |
|---|---|---|
| [Python 3.12 task cancellation](https://docs.python.org/3.12/library/asyncio-task.html#task-cancellation) | Cancellation must unwind cleanup; suppressing it can break structured concurrency | Keep cleanup in guaranteed boundaries and propagate cancellation after cleanup |
| [Codex error classification](https://github.com/openai/codex/blob/282cd7b019378746cb87bd91a95d8b4bcae12aa3/codex-rs/protocol/src/error.rs) | Semantic errors drive terminal versus delayed retry decisions; callers enforce retry budgets | Retain the existing GEODE classifier and application retry owner; do not infer retryability from arbitrary message text |
| [Codex startup cancellation regression](https://github.com/openai/codex/blob/282cd7b019378746cb87bd91a95d8b4bcae12aa3/codex-rs/core/tests/suite/startup_cancellation.rs) | Cancelled partial initialization releases its persistence writer before a new resume can acquire it | Test failed construction and cancellation through release and successful recreation, not just an exception assertion |
| [Codex cleanup task owner](https://github.com/openai/codex/blob/282cd7b019378746cb87bd91a95d8b4bcae12aa3/codex-rs/app-server/src/connection_cleanup.rs) | One owner reaps, drains and aborts cleanup tasks; expected cancellation is distinct from cleanup failure | Trace and join owned work; a scheduled cleanup is not proof that cleanup completed |
| [Claude Agent SDK client](https://github.com/anthropics/claude-agent-sdk-python/blob/2b87034f571b75797b976b3f32a6dbe7a03f20eb/src/claude_agent_sdk/client.py) | Failed connect invokes disconnect before rethrowing; async-context exit disconnects; temporary session resources are cleaned after the query | Give partially built runtimes the same cleanup owner as normal shutdown and preserve the primary failure |
| [Anthropic Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python) | Explicit close and context managers own transport lifetime | Define who closes cached clients on credential invalidation and before their event loop exits |

GEODE intentionally keeps its existing visible-stream boundary: an interrupted
stream after delivered output is terminal for automatic replay. Codex's broader
retryable stream category does not justify changing that user-visible contract.
Rust task ownership and Python context management are implementation choices;
their relevant common invariant is that failure does not publish a usable object
or leave a previous generation holding its resources.

## Local review record

Implementation findings and offline failure-path evidence are recorded here as
they are independently reproduced. This document does not claim whole-repository
coverage, live model execution, successful publication or completed cleanup.

The companion S2 change already reproduces SQLite statement/commit failures
leaving a transaction that a later write can accidentally persist. Its existing
connection owner rolls back before releasing its lock and closes/discards the
connection if rollback fails. `SessionManager` closes a connection when schema
initialization fails. E1 must preserve these corrections when integrated.

No global exception framework, new persistence store or lifecycle registry is
required by this review. Separate inherited ownership debt from demonstrated
behavioral failures and record retained/deferred decisions with their reasons.

### E1: reproduced boundaries and repair

| Producer / owner | Failure and affected reader | Bounded repair and regression |
|---|---|---|
| `GeodeRuntime.create`, `_build_core`, `_build_tools` | Stage 2 or final assembly raises after hooks, event storage, watchers or schedulers are constructed; the final constructor-only rollback never owns those failures | Standard-library `ExitStack` registers only newly constructed resources and transfers ownership on success. Tests inject ordinary failures and cancellation, assert event-store closure and scheduler stop, then recreate a runtime against the same isolated path. Secondary rollback interruption does not replace the primary exception. |
| `GeodeRuntime.shutdown` → `typer_serve.run_serve` | Scheduler state-save failure skips `stop`; `_shutdown=True` makes a second call a no-op. The daemon independently saved/stopped the same borrowed scheduler and could skip later teardown on failure | Attempt every runtime owner independently; ordinary failures return `False` and retain logged best-effort behavior with `_shutdown=False`, while dreaming join failure and interruption propagate after sibling cleanup. The daemon closes its ingress owners and delegates scheduler teardown once to the runtime. Actual serve-path tests cover partial gateway startup and preserve the original host error or cancellation through secondary save, stop, poller, admission, gateway and runtime failures. Ingress failure still reaches active-session drain before resource teardown. Normal execution followed by incomplete cleanup prints an incomplete-shutdown message and exits with code 1. Injected legacy runtimes returning `None` remain compatible. |
| `AgenticLoop._arun_once` → cognitive attribution and adapter tracking | Turn cancellation skips final usage clearing; ordinary completion also leaves attribution bound. Same-task nested turns overwrite their caller's bindings/counter | Existing ContextVar owners expose small token-restoring scopes around the physical turn. Final lifecycle payloads read the inner counter before the outer counter is restored. Tests cover success, error, cancellation, nested turns and reuse. |
| `LoopAffineClientCache.get` / `invalidate` | A constructor running outside the cache lock publishes an obsolete client after a concurrent credential invalidation | Serialize synchronous constructor/publication with invalidation under the existing lock. A coordinated two-thread test holds construction, rotates the cache and verifies the next request obtains a fresh client. Constructor failure leaves no entry and allows recreation. |

The daemon's scheduler is `runtime.scheduler_service`; it is borrowed by the
host and is not a second owned resource. Removing its duplicate teardown and
extracting the bounded host-component cleanup also removes the now-unneeded
`PLR0915` exception for `_serve` and its ledger entry. No Ruff threshold is raised.

The construction and physical-turn edits retain the existing stage/phase owners;
large portions of their textual diff are the indentation of guaranteed cleanup
scopes. No new runtime service container, exception hierarchy or persisted schema
is introduced. SDK/application retry policy, visible-stream replay, provider
usage presence and pricing remain unchanged.

### Explicit limits and companion work

The SDK cache still does not close invalidated clients in E1: a caller may still
be using the old generation. E3 separately assesses and implements event-loop
ownership, retained retired generations and awaited drain at process/thread loop
boundaries. A process-shared adapter registry is not owned by one `GeodeRuntime`,
so runtime shutdown must not close another active runtime's clients. E1 proves
cache publication ordering, not connection drainage or SDK backend acceptance.

S2's SQLite rollback/discard and failed initialization cleanup are a companion
change, not an implementation claim for this branch. Integration must retain its
regressions. This audit is bounded to the listed construction, shutdown and turn
boundaries; it does not certify every resource owner in the repository.
