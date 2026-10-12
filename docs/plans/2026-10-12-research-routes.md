# Research resource paths

Status: implementation in progress. Base: main `fcd0a3b99`.

## Contract

Research has a directly loadable collection at `/geode/research/`.
The existing GEODE and JEVDB readers retain `/geode/research/geode/` and
`/geode/research/jevdb/`. Jev Decision Offloading uses the spelling-corrected
`/geode/research/jev-system1-offloading/`.

GitHub Pages exports directory `index.html` files under the `/geode` base.
Canonical metadata identifies each resource without display-state query or
fragment. Research/readers default to Korean; the existing landing defaults to
English. Explicit `?lang=ko/en` selects the display language. Fragments
continue to identify a page, scene, source sheet, or collection selection.

Existing homepage `#research`, `#research-geode`, `#research-jev`, and
`#jevdb-paper-review` links replace-navigate to the collection, retaining
language and relevant selection. The old `/resaerch/jev-system1-offloading/`
reader replace-navigates to the corrected path with search and fragment intact.
Old PDF, replay, font, and image URLs remain served. No redirect may introduce
a browser Back loop or use an external destination derived from user input.

## Ownership and preservation

Reuse the Research collection and source content. The operator subsequently
approved a content-preserving portfolio restructure with Opus and the TypeUI
Codex skill. Main becomes identity, a recorded task, representative evidence
with limitations, direct publication entries, and start guidance. Research owns
the full collection, Docs owns implementation detail, and readers keep a
minimal Research return/current-location/language header. Existing unique copy
must remain accessible at its detailed destination; no new performance or
career claims. The applied token exceptions and content movement belong in
`site/DESIGN.md`. Update live navigation, related-reader links, sitemap and metadata.
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

## Implementation delegation

The operator requested Opus specifically. Existing Claude Code 2.1.290 executed
`claude-opus-5-5`, confirmed by the provider model-usage receipt and implementation
session init. Only file read/edit tools are available to the implementation
session. The supervising agent owns route/history behavior, original-content
checks, serial builds, independent review, GitFlow, and public deployment QA.

The actual TypeUI skill is preserved in
`site/design-references/typeui-codex/SKILL.md`; its adjacent provenance record
pins the source commit and SHA-256. No TypeUI software, MCP, or authentication
integration is installed. This reference does not override source figure colors,
GEODE identity, artifact fidelity, or accessible contrast.

## Local verification

The implementation candidate passed lint, TypeScript, docs navigation/export,
static build/export, metadata and 87 canonical/sitemap checks. Original Jev
scenes/assets/PDFs, both GEODE PDFs and 184 pages, and the JEVDB PPT/19 images
passed their existing digest contracts. The official docs gate and six landing
evidence tests passed; no new research experiment was run.

Browser checks covered KO/EN at 320, 390, 768, 1024, 1180, and 1440px on the
landing, collection, and three readers (60 combinations), with no horizontal
overflow or page errors. Route/history checks covered 29 cases; follow-up
checks covered eight publication deep-link/tab cases and three moved-section
anchors. Keyboard tab activation and mobile-dialog focus restore passed.
Computed visible text contrast passed on the main (140 elements) and collection
(40). These are scoped browser checks, not a complete accessibility certification.

Independent read-only review found a publication selector scroll problem.
Browser testing showed that native fragment scrolling still conflicted with the
first margin-only repair. Separating panel IDs from public selection hashes
resolved it without changing shared URLs. A low-contrast map label was corrected
within the same deep-rose color family. Final local checks have no known failures.
Remote required CI, main promotion, and public deployment remain pending.
