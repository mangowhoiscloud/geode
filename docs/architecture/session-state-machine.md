# Session State Machine

> Canonical description of the session lifecycle automaton: the state
> space, the transition graph as it exists in code, the enforcement
> introduced in v0.99.329, and the accepted gaps. The inner-loop terminal
> automaton (the `TerminationReason` closed alphabet, v0.99.328) is a
> separate machine documented in `core/agent/loop/models.py`; this page
> covers the OUTER machine — the persisted session checkpoint.

## Machine instance

One machine instance = one session checkpoint = one `session_id`
(`~/.geode/projects/{id}/sessions/<session_id>/`). Everything else keys
into it:

| Key | Relation to the instance |
|---|---|
| `AgenticLoop._session_id` | The live loop's binding to its instance; set at construction or by `restore_from_checkpoint` |
| Gateway `session_key` (channel/thread) | Maps deterministically to a stable instance id (`s-gw-<sha256[:12]>`, v0.99.329) — a messaging thread IS one machine instance across turns |
| IPC/gateway SessionLane key | The same checkpoint `session_id`; foreground turns and hosted Goal continuation serialize on one machine key |
| Transcript / evidence ledger | Write-only sinks keyed by the same `session_id` |
| Scheduler lane key (`sched:<job>`) | Concurrency control only; each fired job builds a fresh instance |

Slack thread routing normalizes the top-level message `ts` into `thread_id`
before the first turn. The root mention and every later reply therefore derive
the same gateway key and checkpoint id. If the process-local L2 session is
empty after a daemon restart, serve restores message history from that durable
checkpoint through the CLI resume substrate. Only ACTIVE and PAUSED machines
are eligible for implicit thread continuation; COMPLETED and ERROR require a
new addressed turn and the explicit reopen edge.

An explicit active Goal adds a process-level continuation owner without adding
another session machine. While `geode serve` is running, its idle host may
restore an ACTIVE checkpoint under the same `session_id` as a new generation
and enter the existing internal Goal turn. PAUSED checkpoints remain parked for
operator or external-verifier input; COMPLETED, ERROR, missing, and corrupt
checkpoints never launch.

## State space

`SessionStatus` (`core/memory/session_checkpoint.py`):

| State | Meaning | Terminal |
|---|---|---|
| ACTIVE | The machine may take more turns | no |
| PAUSED | Parked awaiting operator input or external verification | no |
| COMPLETED | Cleanly finished; cleanup may remove it | yes (reopen edge only) |
| ERROR | One-shot run died (timeout / unhandled exception) | yes (reopen edge only) |

## Transition graph (enforced, v0.99.329)

```
             save() per turn
            +-----v------+
 (absent) --> A C T I V E <-------------------+
            +--+---+---+-+                    |
               |   |   |                      | resume turn
   ask park    |   |   | timeout/exception    | (save)
 (scheduler,   |   |   +---------> ERROR      |
  continuation)|   |                 .        |
               v   |                 . reopen |
           PAUSED  | clean finish    .        |
               |   +----------> COMPLETED     |
               |                     .        |
               +---------------------.--------+
                answer -> continuation (PAUSED -> ACTIVE)
                                     .
                       reopen(session_id) — explicit edge:
                       resume-by-id of a terminal instance
```

Legal-transition table (`_LEGAL_TRANSITIONS`): ACTIVE → {ACTIVE, PAUSED,
COMPLETED, ERROR}; PAUSED → {ACTIVE, PAUSED, COMPLETED, ERROR} (re-park
is idempotent); COMPLETED → {}; ERROR → {}. The two terminal states are re-enterable ONLY through the
explicit `reopen()` edge (used by resume-by-id surfaces). Any other write
against a terminal state is refused with a warning — the fail-loud signal
that a writer bypassed the graph. `save()` on a terminal instance
performs an implicit reopen WITH a warning instead of dropping the turn's
data: losing a resumed conversation is worse than tolerating a noisy
edge, and the warning plus its pinned test keep the edge visible.

## Transition owners

| Edge | Owner |
|---|---|
| absent → ACTIVE, ACTIVE → ACTIVE | `_lifecycle.save_checkpoint` (per turn, every surface) |
| ACTIVE → ACTIVE, new generation | `geode serve` hosted Goal continuation after idle Lane admission and checkpoint restore |
| ACTIVE → PAUSED | scheduler drain (pending-ask/external-verification park); gateway ask continuation (re-ask) |
| ACTIVE → COMPLETED | REPL clean exit; scheduler drain one-shot finish; gateway ask continuation finish; gateway context-exhaustion |
| ACTIVE → ERROR | scheduler drain timeout / unhandled exception |
| PAUSED → ACTIVE | ask answer → continuation's per-turn save |
| COMPLETED/ERROR → ACTIVE | `reopen()` only (IPC resume-by-id) |

## What the machine state contains

A checkpoint is a COMPLETE machine snapshot (v0.99.328 contract):
conversation messages (SQLite SoT), `cognitive_state`, model/provider,
and `loop_guards` — the guard counters the conversation does not carry
(overthinking streak, LLM-failure counter, diversity tracker,
`ConvergenceDetector`, low-confidence replan arm). The single resume
surgery is `AgenticLoop.restore_from_checkpoint(state)`; `apply_guard_state`
uses replacement semantics so a legacy checkpoint resets — never
inherits — a reused loop's counters.

## Read path (deterministic precedence)

`SessionCheckpoint.load()` reads, in order: `state.json` (metadata,
status normalized against `SessionStatus` — unknown strings coerce to
ERROR with a warning), SQLite `messages` (conversation SoT), then the
`messages.json` hot cache ONLY when the DB cannot answer authoritatively
(pre-migration sessions). This fallback is Phase 1b migration debt: the
target end-state is DB-only with the JSON cache demoted to export
tooling, tracked as follow-up — the fallback is deterministic (same
inputs, same source) but still a dual-SoT read.

## Ambient state (accepted, documented)

The generated inventory currently records 35 module/class-scoped ContextVars
across the production packages, including four created by `ContextLocal`: 7 request
identities, 9 request-local mutable values, 7 diagnostic scopes, 1 cache, and 11 service
locators. Every row records its owner,
setter/reset boundary, lifetime, and teardown in
[`context-var-lifecycles.json`](context-var-lifecycles.json); the generated
architecture baseline attaches the executable async propagation/reset test
reference to every item. They are NOT machine state: `arun()` re-binds the
session-scoped values from restored loop state. The service locators are
explicit R4.2 removal inputs rather than accepted machine-state dependencies.

## Observability

Every status CHANGE — legal transitions, status-changing saves
(absent → ACTIVE, resume PAUSED → ACTIVE), `reopen`, implicit reopens —
and every REFUSED attempt appends one structured row to the transitions
ledger (steady-state ACTIVE → ACTIVE per-turn saves are deliberately not
ledgered — one row per round would be noise). Ledger
`<sessions>/transitions.jsonl`
(`{ts, session_id, edge, from, to}`), so "how did this session reach
this state" is answerable after the fact. The ledger is append-only,
best-effort (a ledger failure never blocks a transition), and owned by
`SessionCheckpoint._record_transition`. Illegal attempts additionally
log a WARNING. Hook-system integration of these events is deliberately
deferred to the hook-system redesign cycle — the ledger is the stable
substrate that redesign can consume.

Hosted Goal restore records `session.started` for the new generation, then
`goal.continued(trigger=serve_idle)`. The continuation objective is request-local
context, not `message.user`. Public `SessionStart` fires only after the restored
checkpoint is saved; subsequent tool, verification, replan, usage, and turn
events use the ordinary AgenticLoop writers. The host does not invent a second
delivery store or push to an unresolvable channel; the next gateway turn reads
the newest timestamped history, with the durable checkpoint as the tie-breaker,
and therefore sees the hosted result without discarding a newer foreground L2
write.

Each hosted admission binds a fresh `SessionMetrics` scope, so an earlier
Goal's wall budget, advisory Plan, or verifier state cannot leak into the next
Goal. Gateway restores retain the configured gateway history limit. Returned
attempts are deduplicated until Goal accounting changes; a raised setup or
execution exception is retried only on the next one-second host tick. IPC
resume selects a target and then reloads it under that target's SessionLane,
preventing a stale pre-admission snapshot from overwriting hosted progress;
`--continue` also refuses that candidate if it became terminal while waiting
for admission, whereas explicit resume-by-id keeps the deliberate reopen edge.
Shutdown stops new admissions and gives the active hosted task the same
30-second bounded drain before cancellation.

## Known gaps

- SessionLane serialization is process-local. Two independently started
  `geode serve` processes still have no cross-process Goal lease, so the
  runtime does not promise exactly-once external side effects. Deploy one
  serve owner per project until measured multi-process demand justifies a
  durable lease.

- Gateway multi-turn instances stay ACTIVE between turns by design (the
  gateway cannot know whether another message follows). Terminal edges it
  DOES own: context-exhaustion → COMPLETED, ask park → PAUSED.
- The `messages.json` fallback read remains until the Phase 1b migration
  completes.
- The interactive REPL awaits clean-exit `amark_session_completed`; a
  killed REPL leaves ACTIVE (resumable — intended).
