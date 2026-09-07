---
name: frontier-harness-research
description: Research process for comparing frontier harnesses (Claude Code, Codex, OpenClaw, autoresearch, Prime Agent) with the original/upstream implementation and performing GAP analysis before feature implementation. Triggered by "research" ("리서치"), "gap", "frontier", "harness", "case study" ("사례 조사"), "pattern exploration" ("패턴 탐색"), "comparative analysis" ("비교 분석") keywords.
---

# Frontier Harness Research — Comparative Research Process

> **Purpose**: Before implementing a feature, compare relevant frontier harnesses and the original/upstream implementation, then establish design decision rationale for GEODE application.
> **When to apply**: The user requests a comparison, or an external contract or
> architectural choice needs evidence. Ordinary fixes using an established
> local pattern do not require a multi-system survey.

## Research Sources

| # | System | Type | Core Pattern Areas | GEODE Skill Reference |
|---|--------|------|-------------------|----------------------|
| 1 | **Claude Code** | CLI agent | Permission model, Hook, Memory, Skill, Context management, UI | current official documentation |
| 2 | **Codex** | Coding agent | Sandbox execution, PR workflow, code review, multi-file editing | current official documentation and source |
| 3 | **OpenClaw** | Chat agent | Gateway, Session Key, Binding, Lane Queue, Plugin, Failover, 4-tier automation | `openclaw-patterns` |
| 4 | **autoresearch** | Autonomous experiment loop | Constraint-based design, ratchet, Context Budget, program.md, Simplicity Selection | `karpathy-patterns` |
| 5 | **Prime Agent** | RLM-native coding/research harness | Persistent REPL, programmable context, recursive subagents, continual harness state, native-harness evaluation | official source and technical report |
| 6 | **Original / upstream implementation** | Native authority | Task and scorer semantics, prompts, assets, workspace assumptions, reference results, reproduction path | pinned upstream source and primary docs |

## Research Process

### Step 1: Topic Definition

Define the feature to implement in one line and extract related keywords.

```
Example:
  Topic: "Model Failover automation"
  Keywords: failover, fallback, retry, circuit breaker, model switching
```

### Step 2: Relevant-Source Pattern Exploration

Explore only systems relevant to the decision. Read applicable local skills for
source routing, then verify external claims against current primary docs or
pinned source. Recalled knowledge supplies search terms, not verification;
report unavailable evidence without inventing a capability.

#### 2a. Claude Code Pattern Exploration

| Exploration Area | Checkpoints |
|-----------------|-------------|
| Permission Model | allowlist/denylist, auto-approve, fallback after denial |
| Hook System | pre/post tool hooks, settings.json-based automation |
| Memory | CLAUDE.md, project memory, auto-memory |
| Skill System | skill discovery, trigger keywords, 4-tier priority |
| Context Management | sliding window, compression, token management |
| UI Patterns | status line, progress indicators, error display |
| Safety | HITL tiers, bash safety, dangerous tool gates |

#### 2b. Codex Pattern Exploration

| Exploration Area | Checkpoints |
|-----------------|-------------|
| Sandbox Execution | Isolated environment, filesystem restrictions, network restrictions |
| TDD Loop | test-first, red-green-refactor, automated verification |
| PR Workflow | Branch creation, change summary, review request |
| Multi-file Editing | Dependency tracking, consistency maintenance, refactoring scope |
| Task Decomposition | Complex task breakdown, sequential/parallel determination |

#### 2c. OpenClaw Pattern Exploration (see `openclaw-patterns` skill)

| Exploration Area | Checkpoints |
|-----------------|-------------|
| Gateway + Agent dual system | Control plane vs execution plane separation |
| Session Key hierarchy | `agent:{id}:{context}` format session isolation |
| Binding routing | Most-Specific Wins, static rules, hot reload |
| Lane Queue | Session/Global/Subagent Lane concurrency control |
| Sub-agent Spawn+Announce | Isolated execution, automatic result injection |
| 4-tier automation | Heartbeat, Cron, Internal Hooks, Gateway Hooks |
| Plugin architecture | Channel/Tool/Skill/Hook — 4 extension points |
| Policy Chain | 6-layer tool access control |
| Failover | Auth Rotation, Thinking Fallback, Context Overflow, Model Failover |
| Operational patterns | Coalescing, Atomic Store, Run Log, Hot Reload, Stuck Detection |

#### 2d. autoresearch Pattern Exploration (see `karpathy-patterns` skill)

| Exploration Area | Checkpoints |
|-----------------|-------------|
| P1 Constraint-based design | Define "what cannot be done" first |
| P2 Single-file constraint | Minimize modification surface area |
| P3 Fixed time budget | Limit by wall clock, not steps |
| P4 Ratchet mechanism | Keep only improvements, auto-revert on degradation |
| P5 Git as State Machine | Commit=experiment, reset=discard |
| P6 Context Budget | Redirect + selective extraction |
| P7 program.md | Agent behavior change = instruction document modification |
| P10 Simplicity Selection | Code deletion improvement > code addition improvement |

#### 2e. Prime Agent Pattern Exploration

| Exploration Area | Checkpoints |
|-----------------|-------------|
| Recursive Language Model | Persistent REPL, programmatic context access, subagent calls |
| Continual Harness | Prompt, subagent, skill, and memory CRUD from trajectory evidence |
| Long-horizon operation | Goal, heartbeat, autonomous continuation, explicit budgets and gates |
| Evaluation discipline | Same-model harness comparison, native-harness baseline, token and score accounting |
| Failure analysis | Reward hacking, verifier boundary, harness/model co-adaptation |

#### 2f. Original / Upstream Implementation Exploration

| Exploration Area | Checkpoints |
|-----------------|-------------|
| Native authority | Pinned repository/version, official docs, canonical entry point |
| Benchmark invariants | Prompt, task data, assets, workspace, tools, scorer/verifier, stop conditions |
| Reference evidence | Official result, run configuration, seeds/repeats, metric denominator |
| Adapter parity | Same agent/model/config on original and adapted paths; deviations documented |
| Provenance | Original source and adapter code remain distinguishable and auditable |

### Step 3: GAP Analysis

Compare exploration results against GEODE's current state to identify GAPs.

```
Output format:

| # | Pattern | Source | GEODE Status | GAP | Priority |
|---|---------|--------|-------------|-----|----------|
| 1 | Model Failover | OpenClaw | ⚠️ Definition only | No auto-switching logic | P1 |
| 2 | Circuit Breaker | Codex | ✗ None | No blocking on consecutive failures | P1 |
| 3 | Retry Budget | autoresearch P3 | ⚠️ Partial | No time-based limit | P2 |
```

### Step 4: Design Decisions

Select items to implement from GAP analysis results and document design decision rationale.

**Decision Criteria:**

| Criterion | Application |
|-----------|-------------|
| Pattern appears in several systems | Compare the failure it solves and whether GEODE has that failure; prevalence alone does not require adoption |
| Pattern appears in one system | Evaluate the same consumer, failure, and verification evidence; source count alone does not reject it |
| Over-engineering risk | → Apply Karpathy P10, implement minimally |
| Conflicts with existing GEODE patterns | → Existing pattern takes priority, gradual transition |
| Benchmark integration or platform adapter | → Preserve original semantics and require parity evidence before equivalence claims |

### Step 5: Plan Document Writing

Record the decision in the existing task plan or PR. Use a `docs/plans/` document
when durable research detail warrants one; do not create a second plan merely
to satisfy this skill.

```markdown
# Plan: [Feature Name]

## Frontier Research Summary

| System | Related Pattern | Adoption | Rationale |
|--------|----------------|----------|-----------|
| Claude Code | ... | Adopt/Adapt/Reject | ... |
| Codex | ... | Adopt/Adapt/Reject | ... |
| OpenClaw | ... | Adopt/Adapt/Reject | ... |
| autoresearch | ... | Adopt/Adapt/Reject | ... |
| Prime Agent | ... | Adopt/Adapt/Reject | ... |
| Original / upstream | ... | Preserve/Adapt/N/A | ... |

## Design Decisions
...

## Implementation Phases
...
```

## Research Checklist

For the selected research scope, verify:

- [ ] Topic keywords defined
- [ ] Relevant systems selected and primary evidence cited; irrelevant systems omitted
- [ ] Original/upstream source pinned and native invariants checked
- [ ] Adapter parity requirement recorded for benchmark integration or platform adapter
- [ ] GAP analysis table written
- [ ] Design decision rationale documented
- [ ] Decision and limitations recorded in the existing task artifact

## Notes

- **Ground the affected decision before implementation.** If later evidence changes it, revise the plan and verify the affected behavior before proceeding.
- **Not every frontier system is relevant.** Mark irrelevant systems "N/A"; the original/upstream source is mandatory whenever one exists.
- **Always read skill files first if they exist.** The `openclaw-patterns` and `karpathy-patterns` skills already contain distilled patterns, preventing redundant exploration.
- **Prevent over-research**: Stop once the decision is supported or the missing evidence is identified. Respect the task's time and cost budget.
