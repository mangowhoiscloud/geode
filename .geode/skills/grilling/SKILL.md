---
name: grilling
description: Stress-test a plan, decision, or idea as a dependency-aware design tree. Use for grill-me requests, assumption audits, and decision clarification before implementation.
triggers: grill, grill-me, grilling, 그릴, 검증 질문, 의사결정 압박
tools: get_grill, update_grill, update_plan, general_web_search, web_fetch
---

# Grilling

Mode: decision clarification before action.

Treat `$ARGUMENTS` as the root decision. Build a compact design tree whose
nodes are unresolved user decisions and whose edges are prerequisites. The
current frontier is every unresolved node whose prerequisites are settled.

The runtime creates a typed `grill_state` before this prompt. Call
`update_grill(action="define")` before presenting questions. The tree must be
acyclic, contain 1-24 unique nodes, give every node 2-3 unique options, and name
one recommended option with a reason. Prose is not state: only `update_grill`
can settle a frontier answer or complete the interview. Use `get_grill` after a
rejected update instead of guessing why the validator failed.

## Loop

1. Inspect available code, files, and sources for facts. Never ask the user for
   a fact that can be verified directly.
2. Consider multiple plausible tree shapes internally. Keep the smallest tree
   that covers materially different outcomes; do not expose hidden reasoning.
3. Ask every independent frontier question in one round. Defer a question when
   its answer depends on another unresolved node.
4. For each question, state the decision, 2-3 mutually exclusive options, the
   consequence of each, and one recommended answer with a concrete reason.
5. Wait for the user's answers. Update the tree, surface contradictions, and
   repeat until no unresolved frontier remains.
6. Record answers only for nodes reported in the typed frontier. Call
   `update_grill(action="complete")` only after the validator reports no
   unresolved nodes, then summarize settled decisions, assumptions, rejected
   branches, and open risks. Do not implement until the user confirms the
   shared understanding.

Use this shape for each frontier item:

```text
Q1 — <decision>
- A: <consequence>
- B: <consequence>
Recommendation: <choice and reason>
```

Do not simulate MCTS or LATS. Shared files, shells, and external systems are
not cloneable branch state. This is a decision-tree interview, not speculative
parallel execution.
