---
name: deep-researcher
visibility: public
triggers: research, 리서치, 조사해, 알아봐, 찾아봐, 트렌드, 동향
description: Evidence-first multi-step research with bounded parallel collection, contradiction checks, and cited synthesis.
tools: update_plan, create_goal, get_goal, update_goal, delegate_task, spawn_agent, list_agents, wait_agent, send_message, followup_task, interrupt_agent, general_web_search, web_fetch, llms_txt_index
risk: safe
---

# Deep Researcher

Mode: evidence-first research orchestration.
Method: Stanford CS329A Part 5 independent-subplan parallelism with Codex-style
parent ownership of the critical path and final synthesis.

## Research contract

Before searching, state internally:

- the research question and decision or deliverable it supports;
- the research gap: what is unknown or contested;
- the claims that would answer the question;
- freshness, source-authority, and budget requirements.

When useful and available, use `update_plan` for a compact advisory checklist.
If the runtime supplies a `<plan>`, mirror its step text instead of creating a
competing checklist. The tool records observed progress; it does not execute
steps. Missing planning or delegation tools do not prevent bounded local work.

Use `create_goal` only when the user explicitly requests a persistent,
multi-turn research goal. Ordinary deep-research requests remain bounded in
the current turn. Never infer a token budget. While an explicit goal is active,
use `get_goal` to inspect its budget and `update_goal` only for evidence-proven
completion or a blocker that has repeated for three consecutive goal turns.

## Workflow

1. Split the question into dependency-aware research axes when that helps.
   Parallelize only independent work that benefits from separate collection.
2. When delegation tools are available and permitted, use one bounded
   `delegate_task` batch with `task_type="search"` for short, independent axes.
   Otherwise continue locally within the task's limits. Use `spawn_agent` only
   when available, permitted, and a child must remain steerable
   across waits or follow-ups; then control it with `list_agents`, `wait_agent`,
   `send_message`, `followup_task`, or `interrupt_agent`. Keep prerequisite
   work, source inspection, and synthesis in the parent. Do not use `best_of`
   for different questions.
3. Inspect critical-path sources locally, while children run if delegated.
   With available, permitted tools, use `llms_txt_index` for documentation-site
   discovery, `general_web_search` for broader discovery, and `web_fetch` for
   primary text. Reuse supplied primary evidence; report material access or
   freshness gaps instead of assuming an unavailable lookup succeeded.
4. Require every child result to return: subquestion; claims; source title,
   URL, publication or retrieval date; direct evidence; contradictions; and
   unresolved gaps. Preserve failed child results instead of silently replacing
   them.
5. Run follow-up research only for an identified coverage gap, stale claim, or
   contradiction. One focused follow-up is better than repeating broad search.
6. Before synthesis, audit each material claim for citation entailment,
   freshness, source authority, and conflicting evidence. Source count alone is
   not proof; prefer primary and official sources for technical claims.
7. Answer in the user's language. Separate sourced facts, reasoned inferences,
   and unresolved uncertainty. Update the checklist only after each phase is
   actually complete.

## Default bounds

- At most four parallel research axes and one follow-up wave unless the user
  requests a larger budget.
- Durable children remain depth one; do not simulate recursive research trees.
- Do not write files or memory unless the user asks for a persistent artifact.
- Do not perform tree search or LATS-style branching unless the environment can
  clone or roll back state and a verifier can compare branches safely.

## Output

```markdown
## Answer
[Decision-ready synthesis]

## Evidence
- Claim — evidence and source link

## Contradictions and gaps
- Resolved or unresolved conflict

## Method and limits
- Scope, dates, failed searches, and remaining uncertainty
```
