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
| Gateway `session_key` (channel/thread) | Maps deterministically to a stable instance id (`s-gw-<sha1[:12]>`, v0.99.329) — a messaging thread IS one machine instance across turns |
| `claude_cli_session_id` | Adapter-side resume token, stored ON the instance (SQLite `agent_runtime_state`), never an instance key |
| Transcript / evidence ledger | Write-only sinks keyed by the same `session_id` |
| Scheduler lane key (`sched:<job>`) | Concurrency control only; each fired job builds a fresh instance |

## State space

`SessionStatus` (`core/memory/session_checkpoint.py`):

| State | Meaning | Terminal |
|---|---|---|
| ACTIVE | The machine may take more turns | no |
| PAUSED | Parked awaiting operator input (pending ask) | no |
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
COMPLETED, ERROR}; PAUSED → {ACTIVE, COMPLETED, ERROR}; COMPLETED → {};
ERROR → {}. The two terminal states are re-enterable ONLY through the
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
| ACTIVE → PAUSED | scheduler drain (pending-ask park); gateway ask continuation (re-ask) |
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

ContextVars (26 across core) inject cross-cutting references
(cognitive state, session ids, notification adapter, gateway, scheduler).
They are NOT machine state: `arun()` re-binds the session-scoped ones
from the loop's restored fields at every turn, so a correct
`restore_from_checkpoint` makes the ambient view converge. The wiring
rules (set/get parity, bootstrap registration) live in CLAUDE.md's
Wiring Verification table. Reducing the ambient surface is deliberately
out of scope for the automaton: the risk of rewiring 26 injection points
exceeds the value while the re-binding contract holds.

## Observability

Every edge — legal transitions, `reopen`, implicit reopens, and REFUSED
attempts — appends one structured row to the transitions ledger
`<sessions>/transitions.jsonl`
(`{ts, session_id, edge, from, to}`), so "how did this session reach
this state" is answerable after the fact. The ledger is append-only,
best-effort (a ledger failure never blocks a transition), and owned by
`SessionCheckpoint._record_transition`. Illegal attempts additionally
log a WARNING. Hook-system integration of these events is deliberately
deferred to the hook-system redesign cycle — the ledger is the stable
substrate that redesign can consume.

## Known gaps

- Gateway multi-turn instances stay ACTIVE between turns by design (the
  gateway cannot know whether another message follows). Terminal edges it
  DOES own: context-exhaustion → COMPLETED, ask park → PAUSED.
- The `messages.json` fallback read remains until the Phase 1b migration
  completes.
- The interactive REPL relies on clean-exit `mark_session_completed`; a
  killed REPL leaves ACTIVE (resumable — intended).
