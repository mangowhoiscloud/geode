# Official Docs Generation

GEODE's public prose is curated; version metadata, catalogs and Markdown
exports are generated. The Next.js static export lives under `site/`. This
document owns their release gate and a small map of code/documentation owners.

## Code and documentation owners

| Surface | Code / entry | Guidance owner | Verification |
|---|---|---|---|
| Contributor instructions | [AGENTS.md](../../AGENTS.md), [CLAUDE.md](../../CLAUDE.md) importing `@AGENTS.md` | [Workflow](../workflow.md), [skill inventory](../scaffold-skills.md) | [Workflow scaffold tests](../../tests/test_workflow_scaffold.py) |
| PR integration and history | [Merge guard](../../scripts/merge_pr.py) | [GitFlow and Don't cases](../../.agents/skills/geode-gitflow/SKILL.md), [workflow](../workflow.md) | [Admission and merge-parent tests](../../tests/scripts/test_merge_pr.py) |
| Runtime identity and prompt assembly | [GEODE.md](../../GEODE.md), [system_prompt.py](../../core/agent/system_prompt.py), [diagnostic dump](../../core/agent/prompt_dump.py), [shared prompt](../../core/llm/prompts/router.md) | [Prompt modes](../../site/src/app/docs/runtime/llm/system-prompt-modes/page.tsx), [assembly and literal-data boundaries](../../site/src/app/docs/runtime/llm/prompt-system/page.tsx), [writing and assembly checks](../../.agents/skills/prompt-writing/SKILL.md) | [Complete behavioral sections](../../tests/core/agent/test_geode_soul_g1_behavioral.py), [override and slot assembly](../../tests/core/agent/test_agent_loop_system_prompt_override.py), [dump parity](../../tests/core/agent/test_prompt_dump.py), [mode and XML-data boundaries](../../tests/integration/test_prompt_audit_2026_05_12.py) |
| Runtime skill discovery and catalog | [Skill loader and renderer](../../core/skills/skills.py), [catalog policy](../../core/skills/skill_catalog_policy.py) | [Skill inventory and ownership](../scaffold-skills.md) | [Discovery tiers](../../tests/core/skills/test_skill_loader_tiers.py), [catalog override parity](../../tests/core/skills/test_t2_skill_catalog.py) |
| Provider tool discovery and replay | [Model capabilities](../../core/llm/model_capabilities.py), [Anthropic projection](../../core/llm/adapters/_anthropic_common.py), [adapter translation](../../core/llm/adapters/translation.py), [session persistence](../../core/memory/session_manager.py) | [Tool protocol and provider boundaries](../../site/src/app/docs/runtime/tools/protocol/page.tsx) | [Model/endpoint/cache admission](../../tests/core/llm/test_tool_search_defer_wire.py), [OpenRouter endpoint boundary](../../tests/core/llm/adapters/test_openrouter_payg.py), [Native replay and resume](../../tests/core/llm/adapters/test_provider_replay_history.py), [Refusal, chat replay, and output-schema contracts](../../tests/core/llm/adapters/test_provider_response_contracts.py) |
| Source-specific model lifecycle | [Model catalog](../../core/llm/model_catalog.py), [Codex adapter](../../core/llm/adapters/codex_oauth.py), [Anthropic adapter](../../core/llm/adapters/anthropic_payg.py), [model picker](../../core/cli/commands/model.py) | [Provider selection and retirement](../../site/src/app/docs/run/providers/page.tsx) | [Source-scoped lifecycle](../../tests/core/llm/test_model_catalog.py), [Codex admission and no fallback](../../tests/core/llm/adapters/test_codex_oauth_model_policy.py), [Anthropic admission](../../tests/core/llm/adapters/test_anthropic_model_retirement.py), [Per-role picker sources](../../tests/core/cli/test_model_source_retirement.py) |
| Delegation and worker admission | [Sub-agent manager](../../core/agent/sub_agent.py), [worker request](../../core/agent/worker.py), [process launcher](../../core/orchestration/isolated_execution.py) | [Coding runtime authority](coding-runtime-authority.md), [prompt modes](../../site/src/app/docs/runtime/llm/system-prompt-modes/page.tsx) | [Failure and single invocation](../../tests/core/agent/test_agentic_loop.py), [worker admission](../../tests/core/agent/test_worker.py), [child prompt modes](../../tests/core/orchestration/test_subprocess_env_whitelist.py) |
| Automatic learning admission | [LLM extraction](../../core/hooks/llm_extract_learning.py), [dreaming](../../core/memory/dreaming.py) | [Event-consumer contract](hook-system.md), [memory guide](../../site/src/app/docs/runtime/memory/5-tier/page.tsx) | [Termination-to-consumer matrix](../../tests/core/hooks/test_extract_learning_models_adapter.py), [explicit dreaming](../../tests/core/memory/test_context_artifacts_dreaming.py) |
| Coding Plan routing | [GLM subscription adapter](../../core/llm/adapters/glm_coding_plan.py) | [Provider selection](../../site/src/app/docs/run/providers/page.tsx) | [Subscription identity admission](../../tests/core/llm/adapters/test_builtin_identity.py) |
| Config and budget persistence | [TOML editor](../../core/config/toml_edit.py), [picker persistence](../../core/config/env_io.py), [budget command](../../core/cli/commands/cost.py) | [Configuration reference](../../site/src/app/docs/config/reference/page.tsx) | [TOML splicing](../../tests/core/config/test_toml_edit.py), [budget persistence](../../tests/core/cli/test_cost_command.py), [picker round-trip](../../tests/integration/test_config_effort_knob.py) |
| Scaffold mutation admission | [Mutation runner](../../evolve/scaffold_search/loop/mutate/runner.py) | [Mutation program contract](../../site/src/app/docs/runtime/llm/system-prompt-modes/page.tsx) | [Active-kind admission](../../tests/evolve/scaffold_search/test_policy_mutation.py), [rollback compatibility](../../tests/evolve/scaffold_search/loop/test_invoke_autoresearch_rollback.py) |
| Hook and extension contracts | [Public hooks](../../core/hooks/public.py), [middleware](../../core/hooks/middleware.py), [events](../../core/hooks/system.py) | [Hook contracts](hook-system.md), [naming conventions](naming-conventions.md), [public guide](../../site/src/app/docs/harness/hooks/page.tsx), [registration guide](../../site/src/app/docs/guides/register-hook/page.tsx) | [Public hook schema/decisions](../../tests/core/hooks/test_public_hooks.py), [runtime wiring](../../tests/core/hooks/test_public_hook_wiring.py), [middleware execution](../../tests/core/hooks/test_middleware.py) |
| Conversation recovery | [SessionCheckpoint](../../core/memory/session_checkpoint.py) | [Coding runtime authority](coding-runtime-authority.md), [session state machine](session-state-machine.md) | [Checkpoint tests](../../tests/core/memory/test_session_checkpoint.py) |
| Conversation compaction | [Context manager](../../core/agent/context_manager.py), [pressure estimator](../../core/orchestration/context_monitor.py), [text compaction](../../core/orchestration/compaction.py) | [Compaction contract and Codex comparison](context-compaction.md), [public context guide](../../site/src/app/docs/runtime/context/page.tsx) | [Pressure/failure tests](../../tests/core/agent/test_context_manager.py), [Replay budget estimation](../../tests/core/agent/test_context_monitor.py), [tool-pair boundaries](../../tests/core/orchestration/test_compaction_phases.py) |
| Usage and cache evidence | [IPC prompt admission](../../core/server/ipc_server/poller.py), [adapter usage](../../core/llm/adapters/base.py), [Harbor export](../../evals/platforms/harbor.py) | [Usage accounting](usage-accounting.md) | [IPC-to-accounting regression](../../tests/core/server/test_prompt_accounting.py), [cache accounting](../../tests/core/llm/test_cache_cost_accounting.py), [Harbor boundary](../../tests/evals/benchmarks/test_harbor_geode_agent.py) |
| Evaluation discovery and contracts | [Catalog and validators](../../scripts/eval/contract.py) | [Generated eval index](../eval/index.json), [evaluation entry](../eval/README.md) | [Eval contract tests](../../tests/scripts/test_eval_contract.py) |
| Experimental decision handoff | [Source-bound decision tool](../../evals/benchmarks/decision_handoff.py), [shared root runtime](../../evals/benchmarks/decision_handoff_runtime.py), [pilot CLI](../../scripts/eval/decision_handoff_pilot.py), [Harbor profile](../../evals/platforms/harbor_handoff.py), [static Docker isolation](../../evals/platforms/harbor_docker.py), [observation checker](../../scripts/eval/check_harbor_observations.py), [original five-case fixture](../../evals/benchmarks/fixtures/decision-handoff.json), [separate nine-case fixture](../../evals/benchmarks/fixtures/decision-handoff-hard.json), [complete-candidate inbox fixture](../../evals/benchmarks/fixtures/decision-handoff-inbox.json) | [Comparison scope, admission and replay](../eval/typesafe-decision-handoff.md) | [Decision and observer contracts](../../tests/evals/benchmarks/test_decision_handoff.py), [root continuation and inbox burden](../../tests/scripts/test_decision_handoff_runtime.py), [runner evidence](../../tests/scripts/test_decision_handoff_pilot.py), [Harbor lifecycle](../../tests/evals/platforms/test_harbor_handoff.py), [Docker policy admission](../../tests/evals/platforms/test_harbor_docker.py), [mixed-route observations](../../tests/scripts/test_check_harbor_observations.py) |
| Runtime judgments and confidence | [Candidate selection](../../core/agent/candidate_sampling.py), [cognitive state](../../core/agent/cognitive_state.py), [reflection](../../core/agent/loop/_reflection.py), [judge routing](../../core/agent/loop/_provider_call.py), [session display](../../core/cli/commands/session.py), [turn verification](../../core/agent/verify.py) | [Judgment contracts and limits](../../site/src/app/docs/verification/evaluation/page.tsx) | [Candidate provider inputs](../../tests/core/agent/test_candidate_sampling.py), [reflection validity](../../tests/core/agent/test_reflection_node.py), [judge route and schema isolation](../../tests/core/agent/test_model_split.py), [confidence persistence](../../tests/core/memory/test_cognitive_state_store.py), [session restore](../../tests/integration/test_session_resume.py) |
| Public documentation checks | [Docs gate](../../scripts/check_official_docs.py), [render lint](../../scripts/lint_pages_markdown.sh) | [Render contract](render-lint.md) | [Docs gate tests](../../tests/integration/test_check_official_docs.py), [render gate tests](../../tests/integration/test_render_lint_config.py) |

When one of these surfaces changes, follow the row to its owner and existing
test; update affected behavior descriptions and links in the same change.
Keep entry points short. Do not copy detailed runtime conduct into contributor
guides or turn a historical record into the current contract.

`python scripts/check_official_docs.py --check-map` checks that this table is
present, each row links code, guidance and verification, and those files exist
inside the repository. The full gate also runs this check. It does **not**
validate anchors, code symbols, prose meaning, or whole-codebase coverage.
Behavioral agreement still requires the relevant test and source review;
removing a row requires reviewing which supported entry point would be lost.
CI's separate docs filter runs the path check and focused scaffold tests for
contributor-guide changes without enabling the full runtime suite.

## Reference Patterns

| Reference | Observed docs path | GEODE adoption |
|---|---|---|
| Hermes Agent | Docusaurus site under `website/`; `prebuild.mjs` runs `extract-skills.py` and `generate-llms-txt.py` before `docusaurus build`; CI regenerates skill pages and catalogs, lints diagrams, then builds. | Keep the prebuild idea, but adapt it to GEODE's current Next.js site by making SOT, changelog, and `llms.txt` regeneration explicit before every release docs build. |
| OpenClaw | Mintlify docs under `docs/`; package scripts separate generated docs checks, MDX compile checks, link/anchor audit, formatting, and generated plugin inventory checks. | Keep check/generate separation. GEODE's generated docs must be committed, and release CI should fail if regeneration, links, render-gated Markdown, or site build drift. |

## Canonical GEODE Gate

Run the composed gate from the repository root:

```bash
uv run python scripts/check_official_docs.py
```

The command composes the current checks in `scripts/check_official_docs.py`:

1. Check the declared code/documentation owner paths above.
2. Check bilingual release surfaces: `README.md`, `README.ko.md`, and the
   current `CHANGELOG.md` release section must target the same version.
   Release notes are English; `SECURITY.md` must support the current series.
3. Check the generated architecture inventory and evaluation catalog.
4. Run `npm run sync-stats` in `site/`.
5. Check docs links and lint render-gated Markdown.
6. Run `npm run build`, then `npm run export-md` in `site/`.
7. Fail if regenerated tracked outputs differ from the committed versions.

Use `--skip-build` only for quick local authoring loops. Release validation must
run the full command.

## Generated Outputs

`site/scripts/sync-stats.mjs` owns these generated files:

- `site/src/data/geode/sot.ts`
- `site/src/data/geode/changelog.ts`
- `site/public/llms.txt`

After the site build, `site/scripts/export-docs-md.mjs` owns
`site/public/llms-full.txt` and the published Markdown twins under `site/out/docs/`.
`sync-stats` alone does not refresh their body content.

If any source input changes (`pyproject.toml`, `CHANGELOG.md`, site docs, or
public docs metadata), regenerate and commit the outputs in the same change.

## Next Automation Targets

Possible future automation, not prerequisites for ordinary documentation work:

- A CLI reference generator from Typer command metadata.
- A tool catalog generator from `core/tools/definitions.json`.
- A bilingual-docs checker beyond the current README release-surface gate.

Until those exist, CLI and tool pages remain curated docs backed by link, render,
and site-build checks.
