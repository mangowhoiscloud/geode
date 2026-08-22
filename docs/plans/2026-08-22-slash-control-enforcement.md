# Slash control enforcement — implementation and evaluation plan

Date: 2026-08-22
Base: `origin/develop@c88db60d852664cc9917abca41d0c851ccb22440`
Status: implemented; independent audits and local candidate verified

## Why this follow-up exists

The 2026-08-20 slash release proved routing and prompt contracts, but `/grill`
and `/geo` still relied on prose compliance. A final answer could look correct
without proving that dependencies were closed or that every GEO stage retained
its own denominator and evidence locator. `/plan` also lived only in process
metrics, and `/goal` lacked an operator-owned pause transition and stale-update
guard. This follow-up supersedes only those earlier non-goals; it does not add a
second agent loop or a plan executor.

## Evidence-grounded contract

| Surface | Typed authority | Model authority | Reject when |
|---|---|---|---|
| `/goal` | SQLite projection, goal-id compare-and-set, operator pause/resume/edit | create; complete/block an active goal | stale goal id or illegal transition |
| `/plan` | immutable `Plan` snapshot in the existing checkpoint | propose/revise at most eight advisory steps with tools disabled | malformed schema or execution metadata |
| `/grill` | dependency-validated question tree and computed answerable frontier | propose questions/options and record answers | duplicate/cyclic dependency, non-frontier answer, premature completion |
| `/geo` | ordered phase receipt and seven independent stage measurements | collect and summarize evidence | skipped phase, missing denominator/locator, scalar score, unapproved live authority claim |

The typed projections store decisions and evidence, not hidden chain-of-thought.
`/grill` uses an AND-dependency frontier: a node becomes answerable only when all
of its prerequisites are resolved. This is consistent with clarification as
information acquisition under partial observability. It is deliberately not
MCTS/LATS: GEODE still has no cloned environment state, rollback operator,
visit/value statistics, or typed transition model.

`/geo` keeps `F,R,C,P,A,Q,O` as a vector over fetch/indexability, retrieval,
citation selection, visible placement, answer absorption, support quality, and
downstream outcome. KDD'24 GEO motivates visibility measurement, while C-SEO
Bench shows that rewrites can be ineffective or harmful once retrieval and
competition are included. Therefore no aggregate 0–100 score receives release
authority.

Primary grounding:

- OpenAI Codex agent-loop and harness-engineering publications; local Codex
  source snapshot `343074d4207d` for plan/goal lifecycle patterns.
- Gajae Code `e3c7b42ca425` deep-interview typed topology and completion guard.
- LazyCodex `10f95587d3ae` durable progress ledger and parent-owned verification.
- LATS, ICML 2024 (`openreview.net/forum?id=njwv9BsGHF`) as the explicit search
  boundary, not a name borrowed for a prompt tree.
- GEO, KDD 2024 (`arxiv.org/abs/2311.09735`) and C-SEO Bench, NeurIPS 2025
  (`papers.neurips.cc/paper_files/paper/2025/file/27aa3aeff0f8460a7b43d30fa6c5c032-Paper-Datasets_and_Benchmarks_Track.pdf`).

## Prompt and cache invariant

No authored-static prompt or pinned prompt template changes. Active control
state is rendered as bounded XML and inserted only through
`inject_runtime_hints()` before `</dynamic_context>`. Tests must prove:

1. the byte prefix before `<dynamic_context>` and its OpenAI cache key are
   identical with and without active slash state;
2. the XML envelope remains balanced;
3. snapshots contain no raw hidden reasoning and are bounded;
4. checkpoint restore reproduces the active advisory plan.

## Merge-sized implementation order

1. Add goal pause/resume/edit with goal-id compare-and-set and persist `Plan`
   through the existing checkpoint guard snapshot.
2. Add one compact SQLite JSON projection for grill sessions and one for GEO
   runs; validate in Python at their write boundaries.
3. Register read/update tools and keep them immediately loadable so the slash
   skills can satisfy the typed contract without a hosted tool-search detour.
4. Start each `/grill` or `/geo` run in the existing daemon streaming path and
   return the typed receipt with the ordinary `AgenticLoop` result.
5. Add bounded dynamic-context snapshots, canonical timeline events, focused
   unit tests, and real Unix-socket fake-model E2E.

## Evaluation and release gate

One deterministic, no-network diagnostic run will create separate canonical
session histories for goal, plan, grill, and GEO. Each session is exported from
`sessions.db` as digest-content `geode.trajectory@1`, integrity checked, privacy
reviewed, and staged under a local `geode-eval-artifacts/trajectories/...`
candidate directory. `.eval` is not fabricated because Inspect is not the
producer. Publication is recommended only when all four trajectories are
scope-complete, tool call/result pairs are correlated, typed completion guards
hold, cache/XML tests pass, and no secret-scan finding exists. Otherwise the
candidate remains withheld and the failing behavior is fixed and rerun.

## Explicit non-goals

- no plan executor, precompiled DAG scheduler, MCTS/LATS controller, or stored
  private reasoning;
- no heuristic natural-language subcommand parser;
- no model-generated approval token granting live network or paid execution;
- no live provider benchmark without a separate frozen run spec and approval.

## Closure evidence

The first local export was withheld because `/goal` and `/plan` control events
had no turn identity. `SessionTimeline.begin_control_turn()` fixed that
correlation boundary before a clean rerun; the failed candidate was not
promoted.

The prospective no-network rerun
`slash-control-typed-20260822t091620z` passed 4/4 workloads. Its four canonical
trajectories contain 62 events: goal 6, plan 2, grill 22, and GEO 32. Grill has
3/3 paired tool calls/results and GEO 8/8, with no orphan or public-verification
events. All four are scope-complete and deliberately replay-incomplete because
private payload bodies are digested.

That candidate was subsequently withheld by an independent state and artifact
audit: grill/GEO start events preceded the physical control-turn binding,
tool-driven state edges omitted `call_id`, model-visible GEO config could mint
approval references, and state writes lacked revision compare-and-set. The
audit also found ordinary grill answers outside the literal slash command did
not inherit the active control workflow and a failed `/plan` checkpoint still
reported installation. The implementation now binds slash initialization and
the returned state snapshot inside the session lane, persists revision CAS,
keeps settled grill nodes immutable, limits answers to declared options,
restores typed renderers on resume, and moves GEO approval/preregistration to
operator-owned slash receipts. A new run, not this candidate, is required for
promotion.

The withheld local artifact remains at
`geode-eval-artifacts/.worktrees/slash-control-typed/trajectories/geode-slash-control-slash-control-typed-20260822t091620z-20260822T092446Z-44608e9cb973/`.
Its manifest SHA-256 is
`44608e9cb97387cafcd54d3627c42afa1fdad1e797168464d4eaa172be54b3a7`;
its byte-level privacy/read-back gate passed, but its behavioral attestation is
invalid and it has no promotion authority. It is not published. No `.eval`
exists because Inspect AI did not produce this diagnostic.

The prospective replacement run `slash-control-typed-20260822t104658z`
executed the same four workloads after three independent empty-context audits
and their follow-up probes passed. The real Unix-socket test completed 4/4 with
86 canonical events: goal 6, plan 2, grill 22, and GEO 56. Grill paired 3/3
tool calls/results; GEO paired 12/12 while traversing preflight, offline, live,
experiment, and complete through operator-owned approval/preregistration
receipts. No verification event ran; the prior grill verification remained
failed while only its stale retry edge cleared. All required turn and
tool-driven mutation call identifiers are present.

The four digest-content trajectories are scope-complete and intentionally
replay-incomplete. Exact-byte staging and independent read-back passed with
zero configured secret-scan findings at
`geode-eval-artifacts/.worktrees/slash-control-typed/trajectories/geode-slash-control-slash-control-typed-20260822t104658z-20260822T105400Z-afdada82756c/`.
The manifest SHA-256 is
`afdada82756cd04ec6149b85ae61a41db1040e181a5e010ccf9553d53079b28f`.
This remains an uncommitted local diagnostic candidate: no remote read-back or
publication claim exists, and no `.eval` was created.
