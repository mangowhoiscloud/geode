---
name: verification-team
description: Select complementary review lenses for a requested multi-perspective review or a high-risk GEODE change. Covers design, agent constraints, gateway operations, and CLI/tool behavior; not a mandatory four-agent gate for ordinary edits.
---

# Verification Team — 4-Persona Verification Framework

> **Purpose**: Multi-angle verification of implementation results from 4 frontier engineer perspectives.
Use only the lenses relevant to the requested review and changed behavior.
Delegate independent, bounded reviews when tools are available and doing so
improves coverage or speed; one reviewer may cover several lenses. The names
below label perspectives, not impersonated reviewers or attributed findings.
Follow [verification gates](../geode-workflow/references/verification-gates.md)
for check scope, evidence reuse, and unavailable-tool handling.

## Team Composition

### 1. Kent Beck — Design Quality & Testing

| Item | Details |
|------|---------|
| **Perspective** | "Clean code that works" |
| **Verification focus** | Test coverage, design simplicity, refactoring needs, over-engineering detection |

**Questions Kent Beck would ask:**
- Were tests written before this code? Or added after implementation?
- Is this the simplest implementation? Are there unnecessary abstractions or future-proofing designs?
- Is there any part that "could be improved by deleting code"? (Simplicity)
- Do the tests document the implementation's intent?
- Is the same thing being said twice? (DRY violation)

**Verification checklist:**
- [ ] Tests exist for new code
- [ ] Tests verify behavior, not implementation details
- [ ] Shared behavior is unified only when a named consumer or failure justifies it
- [ ] Interfaces have minimal surface area
- [ ] Error paths are tested

---

### 2. Andrej Karpathy — Agent Design & Constraints

| Item | Details |
|------|---------|
| **Perspective** | "Constraints guarantee quality. Design with constraints, not infrastructure." |
| **Verification focus** | Context management, ratchet mechanisms, time budgets, simplicity selection, agent autonomy boundaries |

**Questions Karpathy would ask:**
- How much of the agent's context window does this feature consume? (P6 Context Budget)
- Does failure produce the declared recovery or explicit failure outcome? (P4 Ratchet)
- Was "what it cannot do" defined first? (P1 Constraint-based design)
- Would deleting this code make the system better? (P10 Simplicity Selection)
- Is the modification surface area minimized? (P2 Single-file constraint)

**Verification checklist (see `karpathy-patterns` skill):**
- [ ] Token Guard — Tool results do not explode the context
- [ ] Ratchet — Required behavior and coverage gates survive; explain removed tests rather than treating counts as proof
- [ ] Constraints stated — Limitations are explicit in code/config
- [ ] No over-abstraction — No single-use utilities/helpers
- [ ] Time budget — Timeouts exist for infinite loops/recursion

---

### 3. Peter Steinberger — Gateway Operations & Plugin Architecture

| Item | Details |
|------|---------|
| **Perspective** | "Everything is a session, every execution goes through a queue, every extension is a plugin." |
| **Verification focus** | Gateway routing, Session Key isolation, Lane Queue concurrency, Plugin extensibility, Failover, operational stability |

**Questions Steinberger would ask:**
- What session key isolates this request? Is there state leakage between sessions?
- Is message routing deterministic (0 LLM calls)? Is it predictable via Binding rules?
- When concurrent requests arrive, are they serialized via Lane Queue, or is there a race condition?
- Does extension follow the existing registry or composition boundary without introducing a duplicate plugin layer?
- Are MCP server processes cleaned up on exit? Are there no orphans?
- Is atomic write (tmp+rename) used? Are state files corruption-safe on crash?

**Verification checklist (see `openclaw-patterns` skill):**
- [ ] Session Key — Per-request session isolation boundary exists
- [ ] Binding — Static routing rules (config hot-reload capable)
- [ ] Lane Queue — Serial by default, explicitly parallel principle followed
- [ ] Extension — New channels/tools/skills use the owning registration path
- [ ] Failover — Only configured and authorized fallback paths run; otherwise preserve the failure
- [ ] Lifecycle — start/stop/cleanup explicit, atexit registered

---

### 4. Boris Cherny — CLI Agents & Sub-Agents

| Item | Details |
|------|---------|
| **Perspective** | "An agent lives in the terminal, understands the codebase, calls tools, observes results, and repeats the loop of deciding its next action." |
| **Verification focus** | AgenticLoop flow, tool safety classification (HITL), sub-agent isolation, prompt design, context management |

**Questions Cherny would ask:**
- Is this tool correctly selected in the `while(tool_use)` loop? Is the tool description sufficient?
- Is the HITL classification appropriate? Does the WRITE tool have an approval gate?
- Does the sub-agent correctly inherit parent tools/MCP/skills?
- Context window management — does sliding window, clear_tool_uses work?
- Is the prompt clear, unambiguous, and does it guide tool calls?
- Permission model — are dangerous operations requesting user confirmation?

**Verification checklist:**
- [ ] Tool definitions.json includes bilingual descriptions
- [ ] SAFE/STANDARD/WRITE/DANGEROUS classification appropriate
- [ ] Sub-agent depth limit, token guard configured
- [ ] No unnecessary instructions in prompts (minimal surface area)
- [ ] MCP tool auto-approve list appropriate
- [ ] Clear error messages displayed to user on failure

---

## Verification Execution Method

### Research Verification

Select relevant perspectives; require primary-source evidence for external
claims and preserve benchmark authority boundaries. The following questions
are optional review assignments, not a required four-agent deployment:

```
  Agent 1 (Beck): "What unnecessary complexity exists in this design?"
  Agent 2 (Karpathy): "What are the constraints and context costs of this feature?"
  Agent 3 (Steinberger): "What operational patterns are missing compared to OpenClaw patterns?"
  Agent 4 (Cherny): "Is this consistent with the AgenticLoop/tool system?"
```

### Implementation Verification

```
Provide the exact diff and affected invariants to each selected reviewer.
Keep review read-only unless implementation is separately assigned.
Consolidate actionable findings with file/line evidence; omit unused lenses.
```

### Verification Results Format

```markdown
## Verification Team Review Results

| Reviewer | Findings | Severity | Key Findings |
|----------|----------|----------|--------------|
| <actual reviewer / selected lens> | N items | P0/P1/P2 | ... |

### P0 (Fix immediately)
- ...

### P1 (Fix in this PR)
- ...

### P2 (Follow-up work)
- ...
```

## Adversarial Review Routing

For a consequential document, design, PR, or publication, use the
[adversarial review procedure](../geode-workflow/references/verification-gates.md#adversarial-review)
when challenging the claims would improve the decision. This is an optional
focus for the existing reviewer, not another persona or a mandatory review.

GEODE's built-in `reviewer` uses the
[canonical system prompt](../../../core/llm/prompts/reviewer.md). Supply the
selected perspective and frozen task inputs, not a second system prompt or a
copy of its criteria. The Markdown report above is the coordinator's summary;
the runtime reviewer keeps its existing JSON output contract.
