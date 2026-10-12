# Research resource paths

Status: implementation in progress. Base: main `fcd0a3b99`.

## Contract

Research has a directly loadable collection at `/geode/research/`.
The existing GEODE and JEVDB readers retain `/geode/research/geode/` and
`/geode/research/jevdb/`. Jev Decision Offloading uses the spelling-corrected
`/geode/research/jev-system1-offloading/`.

GitHub Pages exports directory `index.html` files under the `/geode` base.
Canonical metadata identifies each resource without display-state query or
fragment. Korean remains the default; `?lang=en` selects English. Fragments
continue to identify a page, scene, source sheet, or collection selection.

Existing homepage `#research`, `#research-geode`, `#research-jev`, and
`#jevdb-paper-review` links replace-navigate to the collection, retaining
language and relevant selection. The old `/resaerch/jev-system1-offloading/`
reader replace-navigates to the corrected path with search and fragment intact.
Old PDF, replay, font, and image URLs remain served. No redirect may introduce
a browser Back loop or use an external destination derived from user input.

## Ownership and preservation

Reuse the existing Research collection and site navigation, preserving content
and styling. Update live navigation, related-reader links, sitemap and metadata.
Keep frozen reports, source receipts, PDFs/PPT, experimental results, and slide
art unchanged. A static-export routing projection can adapt the existing Jev
package's navigation and asset addresses without creating a second source deck
or duplicating its binary assets in Git. No `<base>` targeting the legacy path:
that would also redirect scene and language anchors.

Check language restoration on browser Back/Forward and preserve Next history
state when updating display preferences. Heavy builds and rendering run serially.
Other sessions and PR #3473 are outside this change.

## Acceptance and evidence

- Direct visit and refresh of the collection and all three readers succeed.
- Canonical and sitemap URLs use the resource paths above.
- KO/EN selection survives navigation, refresh, and browser Back/Forward.
- Existing homepage and misspelled reader links retain their intended destination,
  language, scene, and source-sheet state.
- Original assets and PDFs/PPT retain their hashes; internal links resolve.
- Targeted contracts, lint/type checks, serial static build/export, independent
  read-only review, required PR CI, and actual Pages deployment/public QA pass.

Results will be recorded in the PR before promotion; this plan is not evidence
of implementation or deployment.
