---
name: frontier-harness-research
description: Research process for exploring related patterns across 4 frontier harnesses (Claude Code, Codex, OpenClaw, autoresearch) and performing GAP analysis before feature implementation. Triggered by "research" ("리서치"), "gap", "frontier", "harness", "case study" ("사례 조사"), "pattern exploration" ("패턴 탐색"), "comparative analysis" ("비교 분석") keywords.
user-invocable: false
---

# Frontier Harness Research — Comparative Research Process

> **Purpose**: Before implementing a feature, explore related patterns across 4 frontier harnesses and establish design decision rationale for GEODE application.
> **When to apply**: Must be performed during Implementation Workflow Step 1 (Research → Plan).

## 4 Frontier Harnesses

| # | System | Type | Core Pattern Areas | GEODE Skill Reference |
|---|--------|------|-------------------|----------------------|
| 1 | **Claude Code** | CLI agent | Permission model, Hook, Memory, Skill, Context management, UI | (built-in knowledge) |
| 2 | **Codex** | Cloud agent | Sandbox execution, TDD loop, PR workflow, code review, multi-file editing | (built-in knowledge) |
| 3 | **OpenClaw** | Chat agent | Gateway, Session Key, Binding, Lane Queue, Plugin, Failover, 4-tier automation | `openclaw-patterns` |
| 4 | **autoresearch** | Autonomous experiment loop | Constraint-based design, ratchet, Context Budget, program.md, Simplicity Selection | `karpathy-patterns` |

## Research Process

### Step 1: Topic Definition

Define the feature to implement in one line and extract related keywords.

```
Example:
  Topic: "Model Failover automation"
  Keywords: failover, fallback, retry, circuit breaker, model switching
```

### Step 2: 4-System Pattern Exploration

Explore patterns related to the topic in each system. **Read the skill file first if available**, otherwise extract from built-in knowledge.

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
| Same pattern in 3+ systems | → Must adopt |
| Similar pattern in 2 systems | → Extract core, adapt for GEODE context |
| Exists in only 1 system | → Verify necessity before deciding |
| Over-engineering risk | → Apply Karpathy P10, implement minimally |
| Conflicts with existing GEODE patterns | → Existing pattern takes priority, gradual transition |

### Step 5: Plan Document Writing

Write a plan document in `docs/plans/`. Research result summary must be included.

```markdown
# Plan: [Feature Name]

## Frontier Research Summary

| System | Related Pattern | Adoption | Rationale |
|--------|----------------|----------|-----------|
| Claude Code | ... | Adopt/Adapt/Reject | ... |
| Codex | ... | Adopt/Adapt/Reject | ... |
| OpenClaw | ... | Adopt/Adapt/Reject | ... |
| autoresearch | ... | Adopt/Adapt/Reject | ... |

## Design Decisions
...

## Implementation Phases
...
```

## Research Checklist

Verify the following before feature implementation:

- [ ] Topic keywords defined
- [ ] Claude Code pattern exploration complete
- [ ] Codex pattern exploration complete
- [ ] OpenClaw pattern exploration complete (see `openclaw-patterns` skill)
- [ ] autoresearch pattern exploration complete (see `karpathy-patterns` skill)
- [ ] GAP analysis table written
- [ ] Design decision rationale documented
- [ ] Research summary included in docs/plans/ plan document

## Notes

- **Research is performed before implementation.** Even if patterns are discovered during implementation, do not go back — improve in the next iteration.
- **Not all 4 systems need to be explored.** Skip systems irrelevant to the topic with "N/A."
- **Always read skill files first if they exist.** The `openclaw-patterns` and `karpathy-patterns` skills already contain distilled patterns, preventing redundant exploration.
- **Prevent over-research**: Research time must not exceed implementation time. Apply Karpathy P3 (fixed time budget).
