# GEODE site

GEODE's landing page, bilingual documentation, and portfolio are a Next.js
static export published under `/geode/` on GitHub Pages.

## Local development

From this directory:

```bash
npm ci
npm run dev
```

Open [the local site](http://localhost:3000/geode/).
The landing source is `src/app/page.tsx`; documentation pages live under
`src/app/docs/`.

## Build and generated documentation

```bash
npm run sync-stats
npm run build
npm run export-md
```

The output is `out/`, not a `next start` server. Publication is owned by
[the Pages workflow](../.github/workflows/pages.yml), including the separate
self-improving bundle copy. A local build does not publish anything.

Read [DESIGN.md](DESIGN.md) and [CONTENT-CANON.md](CONTENT-CANON.md) before
changing the corresponding UI or prose. Generated file ownership and the
release-facing check are in
[Official Docs Generation](../docs/architecture/official-docs-generation.md).
