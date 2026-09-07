# Official Docs Generation

GEODE's official documentation is generated from the repository's source of
truth, then validated before release. The current docs site remains a Next.js
static export under `site/`; this document defines the release gate around it.

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

1. Check bilingual release surfaces: `README.md`, `README.ko.md`, and the
   current `CHANGELOG.md` release section must target the same version.
   Release notes are English; `SECURITY.md` must support the current series.
2. Check the generated architecture inventory and evaluation catalog.
3. Run `npm run sync-stats` in `site/`.
4. Check docs links and lint render-gated Markdown.
5. Run `npm run build`, then `npm run export-md` in `site/`.
6. Fail if regenerated tracked outputs differ from the committed versions.

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
