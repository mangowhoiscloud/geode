# Agent anti-pattern field guide

## Contents

1. [Evidence grades](#evidence-grades)
2. [Taxonomy](#taxonomy)
3. [Whole-repository audit](#whole-repository-audit)
4. [Test contribution review](#test-contribution-review)
5. [Finding record](#finding-record)
6. [Deletion gate](#deletion-gate)
7. [Primary references](#primary-references)

## Evidence grades

Grade claims individually.

| Grade | Evidence | Allowed conclusion |
|---|---|---|
| A | Official product contract, source, or certification guide | Normative supported behavior |
| B | Peer-reviewed or primary empirical research | Measured mechanism within the study setup |
| C | Original conference talk or field case | Local audit hypothesis |
| D | Recap, rule of thumb, or static heuristic | Candidate discovery only |

A lower-grade source may route an investigation but cannot justify deletion or
a universal threshold. Combine source evidence with the target code's callers,
state, tests, and runtime contracts.

## Taxonomy

### AP-1: Lifecycle inference

Seductive form: infer completion from assistant prose, an empty text block, or
an arbitrary iteration cap.

Failure mechanism: the host confuses model output with the provider/runtime
state machine, stops before tool results are processed, or reports a safety
timeout as semantic success.

Look for:

- parsed phrases such as “done” or “complete” controlling the loop;
- tool calls that are returned to the user without host execution;
- loop caps reported as successful completion;
- unknown provider terminal states collapsed into a known outcome.

False-positive boundary: time, round, and retry caps are valid safety bounds
when they produce a distinct terminal classification and do not replace the
native completion state.

Correction: use structured terminal state, append tool results before the next
turn, and preserve timeout/cancellation/error as separate outcomes.

### AP-2: Capability overload and ambiguity

Seductive form: expose every available tool to every role or add near-duplicate
generic tools “for flexibility.”

Failure mechanism: overlapping descriptions increase selection ambiguity;
irrelevant schemas consume context; a specialized role crosses its ownership
boundary; broad tools enlarge security and approval surfaces.

Look for:

- multiple tools with the same intent but different names;
- a role receiving tools it cannot legitimately use;
- always-loaded schemas with no observed task use;
- generic fetch/execute tools bypassing constrained domain tools;
- tool descriptions that hide error or result shape differences.

False-positive boundary: a large registry is not itself overload when the
provider uses deferred discovery, tool search, or reliable task-specific
selection. Measure the model-visible set and selection behavior, not inventory
size alone.

Correction: clarify or merge intents, scope by role, defer discovery, constrain
dangerous general tools, and validate on representative tasks. Treat “4–5
tools” as an example from one exam scenario, not a universal maximum.

### AP-3: Context and instruction pollution

Seductive form: load every rule, tool result, transcript, and subagent thought
because a larger window exists.

Failure mechanism: relevant information competes with stale or verbose
content; middle-position information is missed; summaries erase exact facts;
unneeded inherited reasoning correlates downstream decisions.

Look for:

- monolithic always-loaded instructions that could be path/task scoped;
- full tool payloads where a bounded projection would preserve the task;
- subagents returning raw exploration instead of facts and references;
- duplicate prompt/context assemblers with unclear authority;
- compaction that loses identifiers, dates, amounts, state, or provenance.

False-positive boundary: long context can be required for integration work,
legal evidence, or exact replay. Do not shrink it without a fidelity test.
Imports and file splitting do not reduce context when all bodies still load.

Correction: use progressive disclosure, isolated exploration, structured facts,
content-addressed artifacts, bounded summaries, and explicit provenance. Tune
compaction to provider and workload evidence; do not hardcode 150K globally.

### AP-4: Correlated verification

Seductive form: ask the producer to review its own patch in the same context or
show a reviewer the producer's entire rationale before independent inspection.

Failure mechanism: shared assumptions and reasoning anchors reduce the chance
that a reviewer challenges the original decision; target drift can make valid
findings stale.

Look for:

- producer and final reviewer sharing one mutable session or workspace;
- review without frozen base/head/diff identity;
- verification that only repeats producer-authored assertions;
- reviewer outputs treated as promotion authority without objective gates.

False-positive boundary: self-review remains useful as an early pass, and a
second instance does not guarantee independence or correctness. Procedural
separation must complement tests and other objective evidence.

Correction: freeze the target, separate reviewer context and write authority,
withhold producer reasoning when not required, and rerun deterministic gates.

### AP-5: Prompt-only or interactive control

Seductive form: state a mandatory rule in a prompt, invoke an interactive agent
from automation, or turn a failure into a friendly success string.

Failure mechanism: probabilistic instructions cannot guarantee prerequisites;
CI waits for input; callers cannot distinguish empty success from permission,
transport, validation, or retryable failure.

Look for:

- security/compliance order enforced only by prose;
- CI commands without non-interactive and structured-output flags;
- broad exception handlers returning an empty or successful shape;
- structured errors flattened before the coordinator can recover;
- mocks that pass because new keyword arguments raise inside swallowed code.

False-positive boundary: prompts are appropriate for judgment and adaptation.
Hooks and code gates are for deterministic invariants, not every preference.

Correction: enforce hard prerequisites in code/hooks, use non-interactive
invocation, preserve typed error categories, and fail closed at trust
boundaries.

### AP-6: Complexity without contribution

Seductive form: keep a facade, abstraction, registry, compatibility branch,
test-only helper, or parallel state owner because it might be useful later.

Failure mechanism: more paths can drift, hide the actual writer, expand review
surface, preserve dead policy, and require tests that do not protect user
behavior.

Look for:

- production symbols whose only consumers are tests;
- wrappers with no external contract and one canonical caller;
- two stores or context assemblers claiming the same authority;
- interfaces with one implementation and no substitution consumer;
- configuration for values that never vary;
- tests that assert source strings or private shape instead of behavior;
- compatibility code past its named consumer or deprecation window.

False-positive boundary: safety, redaction, rollback, migration, evidence,
provider adaptation, and stable public compatibility are contributions even
when their happy-path caller count is low.

Correction: prove absence through the deletion gate, then delete or inline.
Keep a thin facade only for a named consumer and one canonical implementation.

## Whole-repository audit

Freeze a tracked inventory first. Assign every in-scope file to exactly one
bucket and record exclusions. Full coverage means every bucket received its
declared lenses; it does not mean every line was manually read.

Use these passes:

1. deterministic lint, type, dependency, boundary, slop, and test collection;
2. module/entrypoint/registry/public-export and side-effect reachability;
3. lifecycle, tool, context, review, error, and authority tracing;
4. production-to-test contribution mapping;
5. disposition and independent deletion-gate recheck.

Do not merge counts from tools with different roots or definitions. Report
them beside each other with their authority.

## Test contribution review

For each suspicious test, identify the surviving invariant before changing it.

| Smell | Required check |
|---|---|
| Source-string assertion | Can a behavior or AST/call test replace it? Does a comment make it false-green? |
| Private-shape pin | Is the shape a real compatibility contract or refactor resistance? |
| Deleted code plus deleted tests | Which independent test still protects the remaining behavior? |
| Monkeypatch with stale signature | Can a swallowed `TypeError` make the test pass? |
| HOME/network/credential dependency | Is the test hermetic and correctly marked live? |
| Duplicate scenarios | Does each case cover a distinct branch, provider, failure, or invariant? |
| Snapshot fixture | Is the full payload reviewed and stable, or would semantic assertions be clearer? |
| Skip/xfail/exclusion | Is there a named blocker and visible expiry/owner? |

Test quantity is not contribution. A test contributes when it fails for a
meaningful regression and its fixture does not silently exercise another path.

## Finding record

Use this compact shape:

```markdown
### APX-NNN — title

- Verdict/severity: KEEP|SHRINK|DELETE|MEASURE|DEFER / P0|P1|P2
- Surface: exact paths and symbols
- Current owner/consumer: writer, reader, entrypoint, provider, or test
- Evidence: static + dynamic/public/state evidence
- Harm or non-contribution: observed failure or falsifiable mechanism
- Source grade: A|B|C|D with reference
- False-positive check: counterexample tested
- Test invariant: what must survive
- Smallest correction: delete, inline, narrow, reuse, or measure
- Verification: exact commands and any skipped/live gate
```

Include `KEEP` decisions for representative high-risk false positives. They
calibrate the audit and prevent later scanners from rediscovering the same
candidate as certain debt.

## Deletion gate

Require every applicable condition:

1. no static caller;
2. no entrypoint, registry, decorator, import-by-string, plugin manifest,
   schema, subprocess, reflection, or import-time side-effect consumer;
3. no public, CLI, MCP, tool, provider, or deprecation contract;
4. no persisted-state reader, migration, rollback, or evidence authority;
5. all provider/backend routes were included;
6. a surviving test protects the remaining behavior or proves absence;
7. targeted and full non-live gates pass;
8. the diff adds no skip, exclusion, threshold reduction, secret, lint bypass,
   generated-baseline laundering, or unreviewed test deletion.

Unknown is `MEASURE` or `DEFER`, never `DELETE`.

## Primary references

- [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Anthropic: Multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Anthropic: Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Anthropic: Advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use)
- [Claude Code subagents](https://code.claude.com/docs/en/sub-agents)
- [Claude Code memory and instructions](https://code.claude.com/docs/en/memory)
- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Claude Platform tool definition](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
- [Liu et al., Lost in the Middle, TACL 2024](https://aclanthology.org/2024.tacl-1.9/)
- [Brown et al., AntiPatterns, Wiley 1998](https://www.wiley-vch.de/en/areas-interest/computing-computer-sciences/computer-science-17cs/object-technologies-17cs6/antipatterns-978-0-471-19713-3)
