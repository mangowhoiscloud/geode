# Aligned Logging / Transcript / Resume / Replay Policy

> **Status**: design SoT — agreed scope is "full-layer policy doc first, implementation as staged PRs after".
> **Date**: 2026-06-19. **Owner decision pending** on the open questions in §7.
> This doc defines ONE policy for how the four execution subsystems record, resume, and replay their runs, and how their append-logs are written/read. It does not change code; each layer below ships as its own PR.

## 1. Problem

Logging / transcript / resume / replay is a **cross-cutting concern shared by all four execution subsystems** — the agentic loop, autoresearch (self-improving loop), petri audit, and the co-scientist pipeline (`seed_generation`). Every one of them: (a) writes an append-only structured record of a run, (b) must tolerate reading that record while it is still being appended, and (c) has a resume need. Yet the implementations have **diverged**, and the shared primitives that already exist are **inconsistently adopted or half-wired**.

This is the same class of issue as the registry / config-TOML / helper duplications already folded (PR-DEDUP-CONFIG-TOML, PR-DEDUP-2, PR-DEDUP-JSONL): one concern, many copies. Here the concern is bigger (it spans schema + resume + replay, not just an IO helper), so it is settled as a policy first.

### 1.1 Current-state map (measured)

| Dimension | Agentic loop | autoresearch | petri | co-scientist (seed_generation) |
|---|---|---|---|---|
| **Transcript** | `SessionTranscript` bespoke JSONL → `~/.geode/transcripts/<slug>/<id>.jsonl` (`core/observability/transcript.py:75`) | 7 artifacts: `mutations.jsonl` / `baseline_archive.jsonl` / `results.jsonl` (tracked) + `sessions.jsonl` / `transcript.jsonl` / `campaign-progress.log` (runtime), `kind=`-discriminated (`runner.py:1184`, `attribution.py:482`, `ledger.py:478/1025/1060`) | inspect_ai `.eval` (vendored, owns the trace) + `MANIFEST.jsonl` (`core/audit/manifest.py:275`) + `summary.yaml` | per-phase JSON blobs `state.json`/`survivors.json`/`checkpoints/<phase>.json` (`orchestrator.py:1063`, `checkpointer.py:152`) + reads CORE `dialogue.jsonl` |
| **Resume** | (A) claude-cli `--resume` keyed `session_id`+`cwd` over `agent_runtime_state` SQLite (`agent_loop.py:84-246`); (B) `SessionCheckpoint` for `/resume` over `sessions.db` (`session_checkpoint.py:74`) | `RunCheckpoint` per-`run_id` JSON, completed workers only (`campaign.py:1151-1270`) | **none** — single `subprocess.run(check=False)` (`runner.py:854`), lost run is skipped not resumed | phase-granular latest-snapshot (`resume.py:98`, `checkpointer.py:152`) |
| **Replay** | none | none (`merge_worker_transcripts` only concatenates+sorts, `campaign.py:1551`) | **replay-for-measurement** — re-read `.eval` for dims/evidence (`dim_extractor.py:207`, `eval_to_jsonl.py:72`) | **replay-for-derivation** — `.eval` re-export from `state.json` (`eval_export.py:110`) |
| **Logging write** | bespoke append + `atomic_write_json` for metadata only | bespoke `open("a")` + `kind=`, **non-atomic** | bespoke MANIFEST append + inspect_ai `.eval` | per-phase JSON rewrite (atomic `os.replace`) + `sessions.jsonl` append |
| **Shared abstraction used** | `SessionCheckpoint` (resume B only) | `RunTranscript` (half-wired — see §1.3) | `UsageStore` (only) | reads `SessionTranscript`/`RunTranscript`, writes bespoke |

### 1.2 The shared primitives that already exist (and are underused)

- **`JsonlAppendLog`** (`core/observability/run_log.py:36`) — locked append + atomic size-prune + newest-first read; already consolidated the orchestration + scheduler run logs (subclasses `RunLog` `:132`, `JobRunLog` `:231`). **Not** subclassed by `SessionTranscript`; **not** used by the autoresearch ledgers or petri `MANIFEST.jsonl` — each rolls its own `open("a")`.
- **`RunTranscript` Tier-1 schema** (`core/self_improving/loop/observe/run_transcript.py:21-22`) — the canonical event record `{ts, session_id, gen_tag, component, level, event, payload}`, written through `SessionTranscript.record_lifecycle_event`. A real, named schema — but only autoresearch's `_emit_journal` path uses it, and even that path has a parity gap (§1.3).
- **`core/memory/atomic_write.iter_jsonl` / `read_jsonl`** — the JSONL read primitive (PR-DEDUP-JSONL, #2383). **This is L0 of the policy below** and is the first layer that lands. (Note: an audit reading `main` will not see these yet — #2383 is in-flight.)
- **`.eval` re-read as replay** — petri and co-scientist have already *independently converged* on "the recorded inspect_ai `.eval` is the SoT; replay = re-derive measurements/render from it, never re-run models".

### 1.3 Concrete defects this policy closes as byproducts

1. **Half-wired transcript ContextVar.** `eval_journaling.emit_eval_response_recorded` reads `current_run_transcript()` and no-ops when no scope is bound (`eval_journaling.py:75`); **`train.py` / `campaign.py` never open `run_transcript_scope`**, so the M4.1 DPO `eval_response_recorded` events are silently never recorded on the autoresearch path (read-write parity gap).
2. **`SessionTranscript` duplicates the append-sink.** It re-implements lock + append + seq + size-prune instead of subclassing `JsonlAppendLog` (`transcript.py:517-546` vs `run_log.py:36-103`).
3. **Duplicate JSONL read loops** across `ledger.py` / `campaign.py` / `manifest.py` / `watch_campaign.py` / `orchestrator.py` — folded by #2383 (L0), but their *write* sites remain bespoke (L1).

## 2. Goals & non-goals

**Goals.** One policy, expressed as five layers (L0–L4), each independently shippable, each reducing a real divergence; all four subsystems converge onto the existing shared primitives rather than new bespoke ones.

**Adjacent, distinct concern (out of scope here).** Diagnostic `logging` — the Python `logging` module's JSON formatter + auto-redaction filter + Settings→TOML mapping — is `docs/plans/2026-06-14-obs-logging-config-convergence.md`. That doc governs `log.info(...)` *diagnostic output* (format + secret redaction). This doc governs the *execution transcript / append-ledger* (`SessionTranscript`, `RunTranscript`, `mutations.jsonl`, `.eval`) — the record of what a run DID, not its diagnostic chatter. The two never overlap: a transcript row is structured data the producer emits deliberately; a log line is a diagnostic the `logging` framework formats. Redaction (that doc's A2) does apply to any PII a transcript payload carries — noted as a shared dependency, owned there.

**Non-goals.**
- Do **not** replace or wrap inspect_ai's `.eval` format. petri's execution trace is vendored and stays vendored; only its GEODE-authored side-logs (`MANIFEST.jsonl`, usage) align.
- Do **not** force a single transcript *file* across subsystems — the tracked-vs-runtime split and the per-domain artifacts stay. Alignment is of **policy** (schema, write discipline, read contract, resume contract, replay doctrine), not of storage location.
- Do **not** build a distributed/streamed log bus. These are local append files read by the same host.
- Do **not** rewrite the agentic loop's `arun` hot path for this; L1 adoption for `SessionTranscript` is a contained writer swap, gated behind the open question in §7.

## 3. The aligned policy — layered model

### L0 — JSONL IO primitive  (status: landing via #2383)

The byte-level read/write contract for one-JSON-object-per-line append logs.

- **Read**: `iter_jsonl(path)` (lazy) + `read_jsonl(path, *, tail=N)` (list). Contract: missing file → empty (silent, expected); existing-but-unreadable → **warn + empty** (observable fail-soft, never silent); blank / malformed / non-dict rows skipped; tolerates a partial last line (read-while-appended); `tail<=0 → []`, `tail=None → all`. Never raises.
- **Write** (to add — L0 completion): `append_jsonl(path, record)` — a single-row locked append + `\n` terminator, mirroring the read side's home in `core/memory/atomic_write.py`. This is the lowest write unit; L1 layers locking/prune/atomicity on top.
- **Frontier alignment**: matches codex `recorder.rs:826-836` (skip-blank, `warn!`+continue, fail-soft) and openclaw `transcript-stream.ts` (lazy shared reader replacing per-caller read-all+split). GEODE is more consistent than codex (which has three readers with inconsistent malformed-line policy).

### L1 — Append-sink  (primitive exists: `JsonlAppendLog`; adoption is the work)

The write discipline for a *log of records* (not a single blob): lock-serialized append, atomic size-prune (tmp + `os.replace`), newest-first read, single logical writer per file.

- **Policy**: any subsystem appending a multi-row execution log routes through `JsonlAppendLog` (or a subclass), not a raw `open("a")`. Reads go through L0 (`read_jsonl`) or the sink's `read()`.
- **Adoption targets**: `SessionTranscript` becomes a `JsonlAppendLog` subclass (defect §1.3.2); the autoresearch ledgers (`mutations.jsonl`, `baseline_archive.jsonl`, `results.jsonl`, `sessions.jsonl`) and petri `MANIFEST.jsonl` route appends through the sink. `baseline.json` and the seed-pipeline per-phase blobs are **single-object rewrites**, not logs — they stay on `atomic_write_json` (correctly already do where atomic).
- **Why atomicity matters here**: the autoresearch ledger appends are currently non-atomic (`campaign.py:1559` even notes "POSIX append is not atomic above PIPE_BUF" and works around it by *isolating* writers rather than locking). The sink centralizes that decision.

### L2 — Transcript schema  (schema exists: `RunTranscript` Tier-1; convergence is the work)

The canonical event record + discriminator for cross-subsystem readability and viewer rendering.

- **Record**: `{ts, seq, session_id, gen_tag, component, level, event, payload}` (the existing `RunTranscript` Tier-1 schema, `run_transcript.py:21`). Multiplexed ledgers (where multiple record types share one file, e.g. `mutations.jsonl` carrying `applied` + `attribution`) additionally carry a top-level `kind=` discriminator — already the de-facto pattern in autoresearch; make it the rule.
- **Convergence**: the four subsystems emit their *lifecycle/event* trace in this schema. petri is the bounded exception — its execution trace is the inspect_ai `.eval`, so only its GEODE-authored manifest/summary rows adopt the schema, not the trace itself.
- **Close the parity gap (§1.3.1)**: `train.py` / `campaign.py` open `run_transcript_scope` so the ContextVar `eval_journaling` path actually records, OR the eval-journaling emit is re-pointed to the already-wired `_emit_journal` path. One of the two; pick at implementation time with a read-write parity test pinning it.

### L3 — Resume contract  (four implementations exist; align the contract, not the class)

A single *protocol* every resume mechanism honors — not a forced base class (the four have genuinely different state shapes).

- **Contract**: (1) persist **outcomes/cursors, not full re-runnable state** where possible (autoresearch `RunCheckpoint` already does — stores `index`/`dim_means`/`fitness`, `campaign.py:1096`); (2) **latest checkpoint is the SoT** (seed_generation already does — `_latest_completed_phase`, `resume.py:88`); (3) restore is **idempotent + corruption-tolerant** (missing/corrupt → fresh run, never crash); (4) resume keying is **documented** (loop = `session_id`+`cwd`; autoresearch = `run_id`; seed = `run_id`+phase).
- **Alignment**: `SessionCheckpoint`, `RunCheckpoint`, and `seed_generation.resume` each state which contract clauses they satisfy in their module docstring; a shared `Resumable` Protocol (typing-only, no runtime base) names `persist()` / `restore()` / `is_resumable()` so the contract is greppable. petri = explicit "no audit-run resume" (documented non-goal — re-run from scratch is the policy).

### L4 — Replay doctrine  (petri + co-scientist already converged; make it the rule)

- **Doctrine**: *the recorded transcript is the source of truth; replay re-derives measurements / re-renders, and NEVER re-executes models.* petri re-reads `.eval` for dims/evidence (`dim_extractor.py:207`); co-scientist re-exports `.eval` from `state.json` (`eval_export.py:110`). Both treat the trace as replayable input, not a re-execution trigger.
- **Extension**: the loop and autoresearch gain "re-derive metrics from the transcript" as the *only* sanctioned replay (autoresearch currently re-uses the checkpoint's saved measurements, `campaign.py:1114` — same doctrine, different store). No subsystem ever re-runs an LLM from a recorded trace; reproducibility pins (`run_provenance`, `ledger.py:1015`) are audit metadata, not a re-run input — state this explicitly so no future PR builds a model-replay path.

## 4. Per-subsystem convergence summary

| Subsystem | L0 read | L1 sink | L2 schema | L3 resume | L4 replay |
|---|---|---|---|---|---|
| Agentic loop | adopt (#2383 covers status reads; transcript read → `read_jsonl`) | `SessionTranscript` → `JsonlAppendLog` subclass | already emits Tier-1-ish lifecycle events; align keys | `SessionCheckpoint` states contract | "re-derive from transcript" doctrine (no current replay) |
| autoresearch | done (#2383) | ledgers → sink (atomic append) | close ContextVar scope gap; `kind=` rule | `RunCheckpoint` states contract | doctrine: checkpoint-measurement-reuse is the replay |
| petri | done (#2383, `manifest.has_archive`/`read_manifest`) | `MANIFEST.jsonl` → sink | manifest/summary rows adopt schema; **`.eval` stays vendored** | documented non-goal (re-run from scratch) | already the canonical replay-for-measurement |
| co-scientist | done (#2383, dialogue + debate sidecar) | `sessions.jsonl` → sink; per-phase blobs stay `atomic_write_json` | per-phase blobs are state not events — exempt; `dialogue.jsonl` is the trace | `resume.py` states contract (latest-snapshot SoT) | already the canonical replay-for-derivation |

## 5. Staged PR sequence

| PR | Layer | Scope | Risk |
|---|---|---|---|
| #2383 (in-flight) | L0 read | `iter_jsonl`/`read_jsonl` + 14-site migration | LOW (merged green) |
| L0-write | L0 | add `append_jsonl` write companion; migrate the simplest single-row appends | LOW |
| L1-sink | L1 | route autoresearch ledgers + petri MANIFEST through `JsonlAppendLog`; (optional, §7) `SessionTranscript` subclass | MEDIUM (write-path; needs append+prune parity tests) |
| L2-schema | L2 | `kind=` rule + close the `run_transcript_scope` parity gap (+ a pinning test) | MEDIUM |
| L3-resume | L3 | `Resumable` typing Protocol + docstring contract statements; no behavior change | LOW |
| L4-doctrine | L4 | document the replay doctrine in `GEODE.md`/this SoT; add a guard test that no path re-executes from a transcript | LOW (mostly docs + a guard) |

Each PR is independent and behavior-preserving except where it closes a parity gap (L2), which is a fix, not a refactor.

## 6. Verification stance

- L0/L1 (write discipline): append + concurrent-read + size-prune parity tests; the existing `JsonlAppendLog` tests are the template.
- L2: a read-write parity test that an autoresearch run actually records an `eval_response_recorded` event (pins the closed ContextVar gap).
- L3: a contract test per resumable (corrupt checkpoint → fresh run, not crash; latest = SoT).
- L4: a guard asserting no module re-feeds a saved transcript into an LLM call.

## 7. Open decisions (operator)

1. **`SessionTranscript` → `JsonlAppendLog`** retrofit: do it (removes the §1.3.2 duplication but touches the agentic-loop write path), or leave `SessionTranscript` bespoke and only align the *schema* (L2) + *read* (L0)? Recommendation: align schema + read now, defer the base-class retrofit to a dedicated PR with hot-path tests.
2. **ContextVar gap fix direction** (L2): open `run_transcript_scope` in `train.py`/`campaign.py` (records the events) vs re-point eval-journaling to the working `_emit_journal` path (simpler, no scope lifecycle). Recommendation: the latter unless the scope is needed for other Tier-1 events.
3. **autoresearch ledger atomicity** (L1): adopt locked-atomic append via the sink, or keep the writer-isolation model (`campaign.py:1054`) that already sidesteps concurrency? Recommendation: sink for the single-writer ledgers (`mutations`/`baseline_archive`/`results`/`sessions`); keep isolation for the parallel-worker transcripts.

## 8. Reference

- Current-state evidence: four parallel subsystem audits (2026-06-19), file:line cited inline above.
- Frontier alignment: `/Users/mango/workspace/codex` (`recorder.rs:826-836`), `/Users/mango/workspace/openclaw` (`transcript-stream.ts:4-12`), on-disk `~/.claude/projects/*.jsonl` (4399 files confirmed one-object-per-line).
- Prior dedup precedent: PR-DEDUP-CONFIG-TOML, PR-DEDUP-2, PR-DEDUP-JSONL (#2383).
