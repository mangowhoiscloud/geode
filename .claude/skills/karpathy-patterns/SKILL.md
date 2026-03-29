---
name: karpathy-patterns
description: Reference when designing autonomous agent systems or deciding agent freedom/safety/context management/collaboration infrastructure. 10 design principles distilled from Karpathy autoresearch (autonomous ML experiment loop) + AgentHub (agent-native Git DAG). Triggered by "autoresearch", "agenthub", "ratchet" ("래칫"), "context budget", "dumb platform", "program.md", "overnight", "autonomous experiment" ("자율 실험"), "branchless", "single-file constraint" ("단일 파일 제약"), "fixed time budget" ("고정 시간 예산") keywords.
user-invocable: false
---

# Karpathy Patterns — Autonomous Agent Design Principles

> **Source**: `karpathy/autoresearch` (Python, 3 files) + `karpathy/agenthub` (Go, single binary)
> **Philosophy**: Quality is guaranteed by constraints, not infrastructure.
> **Details**: [Blog 22](docs/blogs/22-karpathy-autoresearch-autonomous-ml-loop.md) · [Blog 23](docs/blogs/23-karpathy-agenthub-agent-native-infrastructure.md)

## 10 Pattern Overview

| # | Pattern | One-line Principle | Freedom | Source |
|---|---------|-------------------|:-------:|--------|
| P1 | Constraint-based design | Define "what cannot be done" first | Guardrail | autoresearch |
| P2 | Single-file constraint | Modification surface = 1 file (or minimal unit) | Guardrail | autoresearch |
| P3 | Fixed time budget | Compare fairly by wall clock, not steps | Guideline | autoresearch |
| P4 | Ratchet mechanism | Keep only improvements, auto-revert on degradation | Guardrail | autoresearch |
| P5 | Git as State Machine | Commit=experiment, reset=discard, tip=best solution | Guideline | autoresearch |
| P6 | Context Budget management | Protect context via redirect + selective extraction | Guardrail | autoresearch |
| P7 | program.md interface | Changing agent behavior = editing the instruction document | Inspiration | autoresearch |
| P8 | Dumb Platform | Platform only stores, orchestration goes in prompts | Inspiration | AgentHub |
| P9 | Branchless DAG | Agent collaboration via unnamed commit DAGs | Inspiration | AgentHub |
| P10 | Simplicity Selection | Code deletion improvement > code addition improvement | Guideline | autoresearch |

> **Freedom legend**: Guardrail = must follow for safety · Guideline = preferred but use judgment · Inspiration = conceptual reference

---

## P1. Constraint-based Design

Restrict agent freedom to the necessary minimum. autoresearch constraints: 3 files, only train.py modifiable, 5-minute wall-clock, no package installation, single val_bpb metric.

**Judgment**: When designing an agent, did you define "what cannot be done" before "what can be done"?

**GEODE counterpart**: Node contracts (output keys restriction, `core/nodes/*.py`), Clean Context (analyses blocked, `analysts.py:417`), Confidence Gate ≥ 0.7 + max 5 iter (`graph.py:66-68`).

---

## P2. Single-file Constraint

```
autoresearch: train.py (~630 lines) = the only modification target
→ Entire code fits in context window, holistic understanding, diff=experiment record
```

**Judgment**:

| Scenario | Applicable? |
|----------|:-----------:|
| Autonomous experiment / config optimization | O |
| Large-scale refactoring / multi-module changes | X |

**GEODE counterpart**: Each Analyst/Evaluator has independent prompts + independent output models. One node does not modify another node's prompts.

---

## P3. Fixed Time Budget

```python
TRAINING_BUDGET_SECONDS = 300  # Efficient architecture = more steps (automatic reward)
```

Instead of "N iterations," use "do your best within T minutes" → the agent optimizes its own efficiency.

**GEODE counterpart**: Currently iteration-based (max 5). Introducing wall-clock would require node timeout + partial result return patterns.

---

## P4. Ratchet Mechanism

```
LOOP:
  modify → evaluate → if better: keep, else: revert
```

**Strength**: Safe for unattended overnight execution. **Weakness**: Can get stuck in local optima.

**Mitigation**: Diversity Forcing (5 consecutive same type → forced switch), Simulated Annealing, Multi-branch (AgentHub DAG), Meta-optimization (program.md self-modification).

> Details: Blog 22 §3.3 Ratchet Mechanism

**GEODE counterpart**: 5-Phase RLHF feedback loop (`automation/feedback_loop.py`). Broader exploration than ratchet (expert panel) + weaker convergence guarantee.

---

## P5. Git as State Machine

```
Commit = experiment record     Branch tip = best solution     git reset = discard failure
```

Zero infrastructure cost. **Weakness**: `git reset` loses failure records → risk of repeating the same failures.

> Details: Blog 22 §6 (includes MLflow/W&B comparison)

**GEODE counterpart**: 3-Tier Memory (`memory/organization.py`, `project.py`, `session.py`) solves the failure loss problem via hierarchical TTL.

---

## P6. Context Budget Management

```bash
uv run train.py > run.log 2>&1   # L1: Block (0 context consumption)
grep "^val_bpb:" run.log          # L2: Extract (only 2 lines)
                                  # L3: Summarize → 1-bit judgment (improved/degraded)
```

> Details: Blog 22 §7

**GEODE counterpart**: Clean Context — existing analyses excluded from Send API (`analysts.py:418-434`). Session TTL (`session.py:43-51`). PromptAssembler — assembles only needed information per node (`prompt_assembler.py:48-110`).

---

## P7. program.md Interface

program.md = agent instruction document. Composed of Setup (initialization) + Experimentation (loop protocol) + Constraints (prohibitions) + Preferences (direction) + Style (quality standards).

**Key point**: The quality of program.md determines the quality of the agent's research. To change behavior, modify the instruction document, not the code.

**GEODE counterpart**: CLAUDE.md (project instruction document) + skill system (domain-specific expert instruction documents) + HookSystem 26 events (`hooks.py:19-62`).

---

## P8. Dumb Platform

```
Smart Platform (GEODE/OpenClaw): Platform = routing + concurrency + events + orchestration
Dumb Platform (AgentHub):        Platform = storage + delivery only, orchestration in prompts
```

**Judgment**:

| Scenario | Recommendation |
|----------|---------------|
| Deterministic ordering / SLA | Smart |
| Frequent orchestration changes / open-ended exploration | Dumb |
| **Hybrid** | Pipeline is Smart, inter-agent discussion is Dumb |

> Details: Blog 23 §4, §9 (OpenClaw comparison)

**GEODE counterpart**: Currently Smart Platform. Partial Dumb elements can be introduced when L6 Custom Agent support is added.

---

## P9. Branchless DAG

A DAG where commits branch out in all directions, without branches/PRs/merges. Core operations: `leaves` (frontier), `lineage` (ancestor path), `children` (direct descendants).

> Details: Blog 23 §3

**GEODE counterpart**: TaskSystem's `get_ready_tasks()` (`task_system.py:116-120`) follows the same pattern as the `leaves` operation — pending tasks with fulfilled dependencies = frontier nodes.

---

## P10. Simplicity Selection

```
program.md: "Add 20 lines for 0.001 improvement? Reject. Delete code for 0.001 improvement? Always accept."
```

| Change | Improvement | Verdict |
|--------|-------------|---------|
| Code deletion | Marginal | **Accept** |
| Clean addition | Meaningful | Accept |
| Hacky addition | Marginal | **Reject** |

LLMs are inherently biased toward adding code. The instruction document must explicitly include "prefer simple solutions."

**GEODE counterpart**: Same philosophy as the system prompt's "Avoid over-engineering. Only make changes that are directly requested" principle.

---

## Pattern Relationships

```
P1 Constraint-based design ─── Top-level principle
  ├── P2 Single file     (code level)
  ├── P3 Fixed time      (resource level)
  └── P10 Simplicity     (quality criteria)

P4 Ratchet ─── Safe autonomous execution
  └── P5 Git State Machine (implementation mechanism)

P6 Context Budget ─── Sustained long-running execution
  └── P7 program.md    (human-agent interface)

P8 Dumb Platform ─── Multi-agent scaling
  └── P9 Branchless DAG (implementation pattern)
```

## Scale-based Application Guide

| Scale | Applicable Patterns | Not Applicable |
|-------|-------------------|----------------|
| Single agent, single task | P1, P2, P4, P5 | P8, P9 |
| Single agent, overnight autonomous | P1-P7, P10 | P8, P9 |
| Multi-agent, exploratory | P1, P4, P6, P8, P9 | P2 |
| Multi-agent, production | P1, P3, P4, P6 + Smart | P8 |

## Anti-patterns

| Anti-pattern | Violates | Symptom |
|-------------|----------|---------|
| "All files modifiable" | P2 | Fragmented changes, broken dependencies |
| "Unlimited execution" | P3 | Cost explosion, meaningless exploration |
| "All results into context" | P6 | Context exhaustion, early termination |
| "Platform controls everything" | P8 | Lost flexibility, deployment bottleneck |
| "Accept any improvement" | P10 | Complexity accumulation |
| "Failure records not preserved" | P5 | Repeating the same failures |
