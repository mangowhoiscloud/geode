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

The command performs four steps in order:

1. Check bilingual release surfaces: `README.md`, `README.ko.md`, and the
   current `CHANGELOG.md` release section must all target the same version, and
   the changelog section must contain both Korean and English release notes.
2. `npm run sync-stats` in `site/`.
3. `scripts/check_docs_links.py --quiet`.
4. `scripts/lint_pages_markdown.sh`.
5. `npm run build` in `site/`.

Use `--skip-build` only for quick local authoring loops. Release validation must
run the full command.

## Generated Outputs

`site/scripts/sync-stats.mjs` owns these generated files:

- `site/src/data/geode/sot.ts`
- `site/src/data/geode/changelog.ts`
- `site/public/llms.txt`
- `site/public/llms-full.txt`

If any source input changes (`pyproject.toml`, `CHANGELOG.md`, site docs, or
public docs metadata), regenerate and commit the outputs in the same change.

## Next Automation Targets

The reference projects expose two useful future generators that GEODE does not
yet have:

- A CLI reference generator from Typer command metadata.
- A tool catalog generator from `core/tools/definitions.json`.
- A fuller bilingual-docs generator/checker that pairs English and Korean pages
  beyond the current README/changelog release-surface gate.

Until those exist, CLI and tool pages remain curated docs backed by link, render,
and site-build checks.
