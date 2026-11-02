# Official Docs Generation

GEODE's public docs and self-improving hub are built by mangowhois-site from
the [publication bundle](publication-bundle.md) that GEODE publishes; their prose
is curated there. This document owns GEODE's docs gate, a small map of
code/documentation owners, and the redirect-only GitHub Pages site that keeps
the old `mangowhoiscloud.github.io/geode/` addresses working.

## Code and documentation owners

| Surface | Code / entry | Guidance owner | Verification |
|---|---|---|---|
| Contributor instructions | [AGENTS.md](../../AGENTS.md), [CLAUDE.md](../../CLAUDE.md) importing `@AGENTS.md` | [Workflow](../workflow.md), [skill inventory](../scaffold-skills.md) | [Workflow scaffold tests](../../tests/test_workflow_scaffold.py) |
| Task routing and evidence authority | [Preflight](../../core/agent/task_preflight.py), [ledger](../../core/agent/evidence_ledger.py), [finalization](../../core/agent/loop/_lifecycle.py) | [Runtime authority](coding-runtime-authority.md#routing-suggestions-and-execution-evidence), [requirements convention](naming-conventions.md#requirements-plans-and-evidence) | [Advisory context and terminal records](../../tests/core/agent/test_capability_evidence_runtime.py), [completion policy](../../tests/core/agent/test_verify.py) |
| PR integration and history | [Merge guard](../../scripts/merge_pr.py) | [GitFlow and Don't cases](../../.agents/skills/geode-gitflow/SKILL.md), [workflow](../workflow.md) | [Admission and merge-parent tests](../../tests/scripts/test_merge_pr.py) |
| IPC failures and diagnostics | [Wire contract](../../core/ipc_protocol.py), [daemon](../../core/server/ipc_server/poller.py), [client](../../core/cli/ipc_client.py), [log formatter](../../core/observability/logging_config.py), [shared redaction](../../core/observability/redaction.py) | [CLI boundary](https://mangowhois.ai/products/geode/docs/harness/cli/), [observability](https://mangowhois.ai/products/geode/docs/verification/observability/), [error conventions](naming-conventions.md#5-errors-logging-and-trust-boundaries) | [IPC failure boundaries](../../tests/core/server/test_ipc_failure_boundaries.py), [fullscreen rendering](../../tests/core/cli/test_fullscreen_app.py), [log metadata and redaction](../../tests/core/observability/test_logging_redaction.py) |
| Runtime identity and prompt assembly | [GEODE.md](../../GEODE.md), [system_prompt.py](../../core/agent/system_prompt.py), [diagnostic dump](../../core/agent/prompt_dump.py), [shared prompt](../../core/llm/prompts/router.md), [XML section renderer](../../core/llm/prompt_assembler.py) | [Prompt modes](https://mangowhois.ai/products/geode/docs/runtime/llm/system-prompt-modes/), [assembly and literal-data boundaries](https://mangowhois.ai/products/geode/docs/runtime/llm/prompt-system/), [writing and assembly checks](../../.agents/skills/prompt-writing/SKILL.md) | [Complete behavioral sections](../../tests/core/agent/test_geode_soul_g1_behavioral.py), [override and slot assembly](../../tests/core/agent/test_agent_loop_system_prompt_override.py), [dump parity](../../tests/core/agent/test_prompt_dump.py), [mode and XML-data boundaries](../../tests/integration/test_prompt_audit_2026_05_12.py), [section escaping](../../tests/core/llm/test_prompt_assembler.py), [caller directives](../../tests/core/agent/test_runtime_hint_envelope.py) |
| Runtime skill discovery, invocation and catalog | [Skill loader and renderer](../../core/skills/skills.py), [grilling invocation](../../core/skills/grilling.py), [catalog policy](../../core/skills/skill_catalog_policy.py) | [Skill inventory and ownership](../scaffold-skills.md), [slash-command routing](https://mangowhois.ai/products/geode/docs/harness/cli/) | [Discovery tiers](../../tests/core/skills/test_skill_loader_tiers.py), [catalog override parity](../../tests/core/skills/test_t2_skill_catalog.py), [daemon handler isolation](../../tests/core/cli/test_command_registry.py), [streamed control state](../../tests/integration/test_slash_goal_geo_e2e.py) |
| Provider tool discovery and replay | [Model capabilities](../../core/llm/model_capabilities.py), [Anthropic projection](../../core/llm/adapters/_anthropic_common.py), [adapter translation](../../core/llm/adapters/translation.py), [session persistence](../../core/memory/session_manager.py) | [Tool protocol and provider boundaries](https://mangowhois.ai/products/geode/docs/runtime/tools/protocol/) | [Model/endpoint/cache admission](../../tests/core/llm/test_tool_search_defer_wire.py), [OpenRouter endpoint boundary](../../tests/core/llm/adapters/test_openrouter_payg.py), [Native replay and resume](../../tests/core/llm/adapters/test_provider_replay_history.py), [Refusal, chat replay, and output-schema contracts](../../tests/core/llm/adapters/test_provider_response_contracts.py) |
| Tool approval details | [Shared approval workflow](../../core/agent/approval.py), [IPC approval transport](../../core/server/ipc_server/poller.py), [model-switch handler](../../core/cli/tool_handlers/system.py) | [Tool access control](https://mangowhois.ai/products/geode/docs/runtime/tools/protocol/) | [Approval details, decisions and IPC round-trip](../../tests/core/agent/test_approval_fsm.py) |
| Source-specific model lifecycle | [Model catalog](../../core/llm/model_catalog.py), [Codex adapter](../../core/llm/adapters/codex_oauth.py), [Anthropic adapter](../../core/llm/adapters/anthropic_payg.py), [model picker](../../core/cli/commands/model.py) | [Provider selection and retirement](https://mangowhois.ai/products/geode/docs/run/providers/) | [Source-scoped lifecycle](../../tests/core/llm/test_model_catalog.py), [Codex admission and no fallback](../../tests/core/llm/adapters/test_codex_oauth_model_policy.py), [Anthropic admission](../../tests/core/llm/adapters/test_anthropic_model_retirement.py), [Per-role picker sources](../../tests/core/cli/test_model_source_retirement.py) |
| Runtime resource lifetime | [Runtime construction and teardown](../../core/runtime.py), [MCP manager](../../core/mcp/manager.py), [MCP connections](../../core/mcp/connection_pool.py), [daemon owner](../../core/cli/typer_serve.py), [turn attribution](../../core/agent/cognitive_state_ctx.py), [SDK cache](../../core/llm/loop_affinity.py) | [Lifecycle guide](https://mangowhois.ai/products/geode/docs/harness/lifecycle/), [error conventions](naming-conventions.md), [bounded lifecycle review](../research/error-lifecycle-20260924.md) | [Runtime failure and recreation](../../tests/core/test_runtime.py), [MCP ownership and cleanup](../../tests/core/mcp/test_mcp_lifecycle.py), [host teardown](../../tests/core/cli/test_serve_shutdown.py), [turn restoration](../../tests/core/agent/test_turn_context_lifecycle.py), [cache rotation](../../tests/core/llm/test_loop_pollution_guardrails.py) |
| Provider SDK client lifetime | [Loop-affine cache and ownership](../../core/llm/loop_affinity.py), [owned loop teardown](../../core/async_runtime.py), [IPC worker ownership](../../core/server/ipc_server/poller.py) | [Adapter ownership and external loop integration](https://mangowhois.ai/products/geode/docs/guides/llm-adapter/) | [Shutdown, rotation, cancellation and transport close](../../tests/core/test_async_runtime.py), [IPC drain and shutdown failures](../../tests/core/server/test_graceful_drain.py) |
| Delegation and worker admission | [Sub-agent manager](../../core/agent/sub_agent.py), [worker request](../../core/agent/worker.py), [process launcher](../../core/orchestration/isolated_execution.py) | [Coding runtime authority](coding-runtime-authority.md), [prompt modes](https://mangowhois.ai/products/geode/docs/runtime/llm/system-prompt-modes/) | [Failure and single invocation](../../tests/core/agent/test_agentic_loop.py), [worker admission](../../tests/core/agent/test_worker.py), [child prompt modes](../../tests/core/orchestration/test_subprocess_env_whitelist.py) |
| Automatic learning admission | [LLM extraction](../../core/hooks/llm_extract_learning.py), [dreaming](../../core/memory/dreaming.py) | [Event-consumer contract](hook-system.md), [memory guide](https://mangowhois.ai/products/geode/docs/runtime/memory/5-tier/) | [Termination-to-consumer matrix](../../tests/core/hooks/test_extract_learning_models_adapter.py), [explicit dreaming](../../tests/core/memory/test_context_artifacts_dreaming.py) |
| GLM requests and source eligibility | [GLM request contract](../../core/llm/providers/glm.py), [subscription adapter](../../core/llm/adapters/glm_coding_plan.py) | [Provider selection](https://mangowhois.ai/products/geode/docs/run/providers/), [Z.AI source evidence](../research/provider-refresh-20260924-zhipu.md) | [Request, stream and policy admission](../../tests/core/llm/adapters/test_glm_contract.py), [subscription identity admission](../../tests/core/llm/adapters/test_builtin_identity.py) |
| Computer grounding availability | [Active-source grounding](../../core/tools/computer_grounding.py) | [Computer use](https://mangowhois.ai/products/geode/docs/runtime/computer-use/) | [Source-aware failure and billing boundary](../../tests/core/tools/test_computer_grounding.py) |
| Native computer actions | [Anthropic toolset translation](../../core/llm/adapters/_anthropic_common.py), [desktop harness](../../core/tools/computer_use.py), [response accounting](../../core/hooks/llm_observation.py) | [Computer use](https://mangowhois.ai/products/geode/docs/runtime/computer-use/) | [Native toolset, replay and rejected-response usage](../../tests/core/llm/adapters/test_anthropic_computer_toolset.py), [Action validation](../../tests/core/tools/test_native_computer_use.py) |
| Model and credential-route authority | [Route policy and accounts](../../core/llm/routing.py), [session model config](../../core/config/session.py), [login source command](../../core/cli/commands/login.py) | [Storage and runtime selection](storage-hierarchy.md), [provider configuration](https://mangowhois.ai/products/geode/docs/run/providers/) | [Source and policy boundaries](../../tests/core/llm/test_routing.py), [actual SDK account and endpoint](../../tests/core/llm/adapters/test_client_isolation.py), [login admission](../../tests/core/cli/test_login_command.py), [empty config provenance](../../tests/core/config/test_config_explain.py) |
| Config reload and persistence | [Settings reload](../../core/config/__init__.py), [TOML editor](../../core/config/toml_edit.py), [picker persistence](../../core/config/env_io.py), [budget command](../../core/cli/commands/cost.py), [file watcher](../../core/orchestration/hot_reload.py), [binding publication](../../core/messaging/binding.py), [gateway composition](../../core/wiring/adapters.py), [evaluation migration](../../evals/config_cli.py) | [Configuration basics](https://mangowhois.ai/products/geode/docs/config/basics/), [configuration reference](https://mangowhois.ai/products/geode/docs/config/reference/), [binding reload](https://mangowhois.ai/products/geode/docs/guides/binding/) | [Reload failure and recovery](../../tests/core/config/test_settings_reload_from_disk.py), [TOML splicing](../../tests/core/config/test_toml_edit.py), [budget persistence](../../tests/core/cli/test_cost_command.py), [picker round-trip](../../tests/integration/test_config_effort_knob.py), [file transitions](../../tests/core/orchestration/test_hot_reload.py), [binding failure and shutdown](../../tests/core/messaging/test_binding.py), [gateway overlay reload](../../tests/core/wiring/test_gateway_config_sot.py), [migration destination](../../tests/evals/test_config_cli.py) |
| Scaffold mutation admission | [Mutation runner](../../evolve/scaffold_search/loop/mutate/runner.py) | [Mutation program contract](https://mangowhois.ai/products/geode/docs/runtime/llm/system-prompt-modes/) | [Active-kind admission](../../tests/evolve/scaffold_search/test_policy_mutation.py), [rollback compatibility](../../tests/evolve/scaffold_search/loop/test_invoke_autoresearch_rollback.py) |
| Hook and extension contracts | [Public hooks](../../core/hooks/public.py), [middleware](../../core/hooks/middleware.py), [events](../../core/hooks/system.py) | [Hook contracts](hook-system.md), [naming conventions](naming-conventions.md), [public guide](https://mangowhois.ai/products/geode/docs/harness/hooks/), [registration guide](https://mangowhois.ai/products/geode/docs/guides/register-hook/) | [Public hook schema/decisions](../../tests/core/hooks/test_public_hooks.py), [runtime wiring](../../tests/core/hooks/test_public_hook_wiring.py), [middleware execution](../../tests/core/hooks/test_middleware.py) |
| Conversation recovery | [SessionCheckpoint](../../core/memory/session_checkpoint.py), [loop guard lifecycle](../../core/agent/loop/_lifecycle.py), [replan dispatch](../../core/agent/loop/_guards.py), [advisory planner](../../core/agent/plan.py) | [Coding runtime authority](coding-runtime-authority.md), [session state machine](session-state-machine.md), [reflection and replan boundaries](hook-system.md) | [Checkpoint tests](../../tests/core/memory/test_session_checkpoint.py), [guard and private-context restore](../../tests/core/agent/test_loop_state_machine.py), [failure instruction delivery](../../tests/core/agent/test_replan.py) |
| Conversation compaction | [Context manager](../../core/agent/context_manager.py), [request admission](../../core/agent/loop/_provider_call.py), [route budget](../../core/orchestration/context_budget.py), [pressure estimator](../../core/orchestration/context_monitor.py), [text compaction](../../core/orchestration/compaction.py) | [Compaction contract and Codex comparison](context-compaction.md), [public context guide](https://mangowhois.ai/products/geode/docs/runtime/context/), [source-bound recovery research](../research/context-compaction-recovery-20260925.md) | [Provider rejection and bounded recovery](../../tests/core/agent/test_context_recovery.py), [middleware admission](../../tests/core/agent/test_provider_context_admission.py), [Pressure/failure tests](../../tests/core/agent/test_context_manager.py), [Replay budget estimation](../../tests/core/agent/test_context_monitor.py), [tool-pair boundaries](../../tests/core/orchestration/test_compaction_phases.py) |
| Usage and cache evidence | [IPC prompt admission](../../core/server/ipc_server/poller.py), [adapter usage](../../core/llm/adapters/base.py), [auxiliary terminal accounting](../../core/hooks/middleware.py), [Harbor export](../../evals/platforms/harbor.py) | [Usage accounting](usage-accounting.md) | [IPC-to-accounting regression](../../tests/core/server/test_prompt_accounting.py), [reflection usage](../../tests/core/agent/test_reflection_node.py), [cache accounting](../../tests/core/llm/test_cache_cost_accounting.py), [Anthropic TTL/wire lifecycle](../../tests/core/llm/adapters/test_anthropic_cache_lifecycle.py), [Harbor boundary](../../tests/evals/benchmarks/test_harbor_geode_agent.py) |
| Provider cache boundaries and session affinity | [Responses shaping](../../core/llm/adapters/_openai_common.py), [OpenRouter shaping](../../core/llm/adapters/openrouter_payg.py) | [Prompt caching](https://mangowhois.ai/products/geode/docs/runtime/llm/prompt-caching/), [source evidence](../research/provider-cache-lifecycle-20260924.md) | [SDK wire, prefix and session ownership](../../tests/core/llm/adapters/test_prompt_cache_lifecycle.py) |
| Evaluation discovery and contracts | [Catalog and validators](../../scripts/eval/contract.py) | [Generated eval index](../eval/index.json), [evaluation entry](../eval/README.md) | [Eval contract tests](../../tests/scripts/test_eval_contract.py) |
| Typed decision admission and candidate scoring | [System One primitive validation](../../core/llm/adapters/typesafe.py), [matched candidate diagnostic](../../evals/benchmarks/decision_candidate.py) | [Three-primitive contract and failure accounting](../eval/typesafe-decision-handoff.md#three-primitive-extension--implementation-contract-not-a-live-result) | [Primitive and completed-usage regression](../../tests/core/llm/adapters/test_typesafe.py), [native candidate path and fallback](../../tests/evals/benchmarks/test_decision_candidate.py) |
| Experimental decision handoff | [Source-bound decision tool](../../evals/benchmarks/decision_handoff.py), [matched final verdict](../../evals/benchmarks/decision_verification.py), [shared TypeSafe transport](../../evals/benchmarks/typesafe_decision.py), [shared root runtime](../../evals/benchmarks/decision_handoff_runtime.py), [pilot CLI](../../scripts/eval/decision_handoff_pilot.py), [Harbor profile](../../evals/platforms/harbor_handoff.py), [static Docker isolation](../../evals/platforms/harbor_docker.py), [observation checker](../../scripts/eval/check_harbor_observations.py), [original five-case fixture](../../evals/benchmarks/fixtures/decision-handoff.json), [separate nine-case fixture](../../evals/benchmarks/fixtures/decision-handoff-hard.json), [complete-candidate inbox fixture](../../evals/benchmarks/fixtures/decision-handoff-inbox.json) | [Comparison scope, admission and replay](../eval/typesafe-decision-handoff.md) | [Decision and observer contracts](../../tests/evals/benchmarks/test_decision_handoff.py), [typed verdict and shared repair](../../tests/evals/benchmarks/test_decision_verification.py), [root continuation and inbox burden](../../tests/scripts/test_decision_handoff_runtime.py), [runner evidence](../../tests/scripts/test_decision_handoff_pilot.py), [Harbor lifecycle](../../tests/evals/platforms/test_harbor_handoff.py), [Docker policy admission](../../tests/evals/platforms/test_harbor_docker.py), [mixed-route observations](../../tests/scripts/test_check_harbor_observations.py) |
| Runtime judgments and confidence | [Candidate selection](../../core/agent/candidate_sampling.py), [cognitive state](../../core/agent/cognitive_state.py), [reflection](../../core/agent/loop/_reflection.py), [turn lifecycle](../../core/agent/loop/agent_loop.py), [judge routing](../../core/agent/loop/_provider_call.py), [session display](../../core/cli/commands/session.py), [turn verification](../../core/agent/verify.py) | [Judgment contracts and limits](https://mangowhois.ai/products/geode/docs/verification/evaluation/) | [Candidate provider inputs](../../tests/core/agent/test_candidate_sampling.py), [reflection validity and deadline](../../tests/core/agent/test_reflection_node.py), [turn privacy boundary](../../tests/core/agent/test_google_workspace_consent.py), [judge route and schema isolation](../../tests/core/agent/test_model_split.py), [confidence persistence](../../tests/core/memory/test_cognitive_state_store.py), [session restore](../../tests/integration/test_session_resume.py) |
| Public documentation checks | [Docs gate](../../scripts/check_official_docs.py), [render lint](../../scripts/lint_pages_markdown.sh) | [Render contract](render-lint.md) | [Docs gate tests](../../tests/integration/test_check_official_docs.py), [render gate tests](../../tests/integration/test_render_lint_config.py) |
| Downstream site publication bundle | [Bundle builder](../../scripts/build_publication_bundle.py), [release publisher](../../.github/workflows/publication-bundle.yml) | [Publication bundle contract](publication-bundle.md) | [Determinism, manifest and exclusion tests](../../tests/scripts/test_build_publication_bundle.py), [publisher contract](../../tests/integration/test_publication_workflow.py) |
| Old GitHub Pages addresses | [Redirect builder](../../scripts/build_pages_redirects.mjs), [rules](../../github-pages/rules.js), [frozen paths](../../github-pages/redirect-paths.json) | [GitHub Pages redirects](official-docs-generation.md#github-pages-redirects) | [Redirect site contract](../../tests/scripts/test_build_pages_redirects.py) |
| Published self-improving state snapshot | [Scaffold-search snapshot](../../evolve/scaffold_search/publication.py), [crucible attempt rows](../../evolve/crucible/publication.py), [rebuild command](../../scripts/refresh_published_state.py) | [Publication bundle contract](publication-bundle.md#published-runtime-snapshot) | [Snapshot writers and log parity](../../tests/evolve/scaffold_search/test_publication.py), [crucible rows](../../tests/evolve/crucible/test_publication.py), [rebuild command](../../tests/scripts/test_refresh_published_state.py) |
| Optional Jev judgment | [Credential-gated selection](../../core/config/judgment.py), [operator picker](../../core/cli/commands/judgment.py), [System One transport](../../core/llm/adapters/typesafe.py) | [Runtime judgment guide](https://mangowhois.ai/products/geode/docs/verification/evaluation/), [configuration](https://mangowhois.ai/products/geode/docs/config/reference/), [usage accounting](usage-accounting.md) | [Selection and persistence](../../tests/core/config/test_judgment.py), [input-only tariff](../../tests/core/llm/test_pricing_loader.py), [key redaction](../../tests/core/tools/test_redaction.py) |
| Jev diagnostic publication | [Trajectory release](../../core/observability/trajectory_release.py), [publication validator](../../scripts/eval/contract.py) | [Run and normalization record](../eval/jev-verdict-publication-20260924.md), [external artifact repository](../eval/external-artifact-repository.md) | [Public payload admission](../../tests/core/observability/test_trajectory_release.py), [publication contracts](../../tests/scripts/test_eval_contract.py) |

When one of these surfaces changes, follow the row to its owner and existing
test; update affected behavior descriptions and links in the same change.
Keep entry points short. Do not copy detailed runtime conduct into contributor
guides or turn a historical record into the current contract.

`python scripts/check_official_docs.py --check-map` checks that this table is
present, each row links code, guidance and verification, and those files exist
inside the repository. A guidance link may instead be a public docs page under
`https://mangowhois.ai/products/geode/docs/`, which is not fetched. The full gate
also runs this check. It does **not**
validate anchors, code symbols, prose meaning, or whole-codebase coverage.
Behavioral agreement still requires the relevant test and source review;
removing a row requires reviewing which supported entry point would be lost.
CI's separate docs filter runs the path check and focused scaffold tests for
contributor-guide changes without enabling the full runtime suite.

CI's `full_tests` filter defaults every changed path to full Python tests and
coverage. Its exact allowlist covers `README.md`, `README.ko.md`, `CHANGELOG.md`,
`CLAUDE.md`, `docs/workflow.md`, `docs/scaffold-skills.md`, this owner document,
`docs/architecture/extensibility-roadmap.md`, and the generated architecture
inventory `docs/architecture/architecture-baseline.json`. These paths still run
documentation contracts; roadmap and inventory changes retain their existing lint
validators, and the required Pages checks lint render-gated docs and build the
redirect site.

The pinned [paths-filter exclusion predicate](https://github.com/dorny/paths-filter/blob/ceb8a2b8f2d89434be7ff52d3de7ec3738c5cc9d/README.md#usage)
classifies the complete PR diff against its base. Resolving a document-only
conflict does not exempt a PR whose remaining diff includes runtime or tests.
Push events compare their non-zero `before` commit to the pushed revision;
missing or invalid prior SHAs fail change detection instead of falling back to
the last commit or the repository's default branch.
Unknown paths, other Markdown/JSON, runtime guidance, dependencies, and workflows
remain full-test inputs. Missing or invalid classification cannot pass `Gate`;
only an explicit `full_tests=false` skips the heavy inner steps of `Test`.
Both required check names and their workflow remain unchanged. No past CI result
or coverage data is reused as current-head verification.

## Reference Patterns

| Reference | Observed docs path | GEODE adoption |
|---|---|---|
| Hermes Agent | Docusaurus site under `website/`; `prebuild.mjs` runs `extract-skills.py` and `generate-llms-txt.py` before `docusaurus build`; CI regenerates skill pages and catalogs, lints diagrams, then builds. | Keep the prebuild idea: the downstream site regenerates its SOT, changelog, and `llms.txt` from each publication bundle instead of from committed copies. |
| OpenClaw | Mintlify docs under `docs/`; package scripts separate generated docs checks, MDX compile checks, link/anchor audit, formatting, and generated plugin inventory checks. | Keep check/generate separation. GEODE's generated inventory and catalog must be committed, and release CI fails if they or render-gated Markdown drift. |

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
4. Lint render-gated Markdown.

## Generated Outputs

`scripts/architecture_baseline.py` owns `docs/architecture/architecture-baseline.json`
and the generated blocks in `AGENTS.md` and the extensibility roadmap.
`scripts/eval/contract.py catalog` owns `docs/eval/index.json`.

`scripts/build_publication_bundle.py` packs the raw inputs the downstream site
needs (changelog, evaluation index, architecture inventory and self-improving
hub data) into a content-addressed archive. Its layout and manifest are owned by
the [publication bundle contract](publication-bundle.md).

## GitHub Pages redirects

GitHub Pages cannot answer 301, so `.github/workflows/pages.yml` deploys a
static redirect site built by `scripts/build_pages_redirects.mjs`:

- `github-pages/redirect-paths.json` freezes the 2,063 page and text paths the
  last real deployment served (its sitemap, the redirect map it applied,
  `site/public`, `docs/self-improving` and `docs/petri-bundle` at `30d4b63d7`).
- Each page path gets a stub with a meta refresh, a canonical link, a visible
  link and `noindex`, plus a script that keeps the query and fragment. Markdown
  and text paths get a one-line note.
- `github-pages/404.html` maps any other address, including images, PDFs and
  `.eval` archives, in the browser.
- `github-pages/rules.js` is the single rule set for both. It is a frozen copy
  of mangowhois-site's canonical URL rules: hub paths go to
  `https://tech.mangowhois.ai/self-improving/`, research readers and media to
  their `tech.mangowhois.ai` addresses, retired hub operator docs to GitHub,
  and everything else to `https://mangowhois.ai/products/geode/` at the same path.

## Next Automation Targets

Possible future automation, not prerequisites for ordinary documentation work:

- A CLI reference generator from Typer command metadata.
- A tool catalog generator from `core/tools/definitions.json`.
- A bilingual-docs checker beyond the current README release-surface gate.

Any such generator would add data to the publication bundle; the pages
themselves stay curated in mangowhois-site.
