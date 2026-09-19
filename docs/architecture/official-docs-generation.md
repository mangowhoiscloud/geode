# Official Docs Generation

GEODE's public prose is curated; version metadata, catalogs and Markdown
exports are generated. The Next.js static export lives under `site/`. This
document owns their release gate and a small map of code/documentation owners.

## Code and documentation owners

| Surface | Code / entry | Guidance owner | Verification |
|---|---|---|---|
| Contributor instructions | [AGENTS.md](../../AGENTS.md), [CLAUDE.md](../../CLAUDE.md) importing `@AGENTS.md` | [Workflow](../workflow.md), [skill inventory](../scaffold-skills.md) | [Workflow scaffold tests](../../tests/test_workflow_scaffold.py) |
| Runtime identity and prompt assembly | [GEODE.md](../../GEODE.md), [system_prompt.py](../../core/agent/system_prompt.py) | [Prompt modes](../../site/src/app/docs/runtime/llm/system-prompt-modes/page.tsx) | [Behavioral section injection](../../tests/core/agent/test_geode_soul_g1_behavioral.py), [override assembly](../../tests/core/agent/test_agent_loop_system_prompt_override.py) |
| Runtime skill discovery | [Skill loader](../../core/skills/skills.py) | [Skill inventory and ownership](../scaffold-skills.md) | [Discovery tiers](../../tests/core/skills/test_skill_loader_tiers.py) |
| Hook and extension contracts | [Public hooks](../../core/hooks/public.py), [middleware](../../core/hooks/middleware.py), [events](../../core/hooks/system.py) | [Hook contracts](hook-system.md), [naming conventions](naming-conventions.md), [public guide](../../site/src/app/docs/harness/hooks/page.tsx), [registration guide](../../site/src/app/docs/guides/register-hook/page.tsx) | [Public hook schema/decisions](../../tests/core/hooks/test_public_hooks.py), [runtime wiring](../../tests/core/hooks/test_public_hook_wiring.py), [middleware execution](../../tests/core/hooks/test_middleware.py) |
| Conversation recovery | [SessionCheckpoint](../../core/memory/session_checkpoint.py) | [Coding runtime authority](coding-runtime-authority.md), [session state machine](session-state-machine.md) | [Checkpoint tests](../../tests/core/memory/test_session_checkpoint.py) |
| Conversation compaction | [Context manager](../../core/agent/context_manager.py), [text compaction](../../core/orchestration/compaction.py) | [Compaction contract and Codex comparison](context-compaction.md), [public context guide](../../site/src/app/docs/runtime/context/page.tsx) | [Pressure/failure tests](../../tests/core/agent/test_context_manager.py), [tool-pair boundaries](../../tests/core/orchestration/test_compaction_phases.py) |
| Usage and cache evidence | [Adapter usage](../../core/llm/adapters/base.py), [Harbor export](../../evals/platforms/harbor.py) | [Usage accounting](usage-accounting.md) | [Cache accounting](../../tests/core/llm/test_cache_cost_accounting.py), [Harbor boundary](../../tests/evals/benchmarks/test_harbor_geode_agent.py) |
| Evaluation discovery and contracts | [Catalog and validators](../../scripts/eval/contract.py) | [Generated eval index](../eval/index.json), [evaluation entry](../eval/README.md) | [Eval contract tests](../../tests/scripts/test_eval_contract.py) |
| Runtime judgments and confidence | [Candidate selection](../../core/agent/candidate_sampling.py), [cognitive state](../../core/agent/cognitive_state.py), [reflection](../../core/agent/loop/_reflection.py), [turn verification](../../core/agent/verify.py) | [Judgment contracts and limits](../../site/src/app/docs/verification/evaluation/page.tsx) | [Candidate provider inputs](../../tests/core/agent/test_candidate_sampling.py), [reflection validity](../../tests/core/agent/test_reflection_node.py), [verifier schema isolation](../../tests/core/agent/test_model_split.py) |
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
