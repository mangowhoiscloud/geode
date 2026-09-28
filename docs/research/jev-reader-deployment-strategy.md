# Jev reader: local polish and GitHub Pages deployment strategy

Status on 2026-09-28: locally prepared and verified, not deployed. The user has
approved deployment after the report correction. This worktree's report owner
hands off the package; the parent/rollout owner retains GitFlow integration,
workflow dispatch and live readback. No commit, PR or deployment was performed
by this report-preparation task. Film production remains separately owned.

## Scope and preserved authorities

The public route is exactly
`https://mangowhoiscloud.github.io/geode/resaerch/jev-system1-offloading/`.
`resaerch` is the operator's requested spelling, not an automatic correction.

The reader is a projection of source SHA
`37d8e11cabce01fe368d8c9f6d623a28a4ee7965d12bc8129e7efb529a73ff34`.
This v23 causal-language revision has 57 scenes and 81 settled builds per
language, including the compressed scene 4. The scientific text, diagram markup,
replay media and timing stay source-owned. There is no second slide authoring
pipeline, metric calculation or experiment in this work.

| Surface | Owner and binding |
| --- | --- |
| Public package | `site/public/resaerch/jev-system1-offloading/` |
| Reader HTML | `site/scripts/export-jev-report.mjs` projects the frozen source |
| Approved assets | `docs/research/jev-report-assets.json`, exact paths and SHA-256 |
| PDFs | New v23 `report-ko.pdf` and `report-en.pdf`, 81 pages each; then reused unchanged for the source-sheet update |
| Release identities | Package `publication.json`: source, HTML, current generator, original PDF generator, assets and PDFs |
| Public study records | Pinned `geode-eval-artifacts` commit `3bcf4044eb5c2411dd48122d672aef72a83fb30e` |

The modern outer reader originated in v22; it does not define the research
edition. v23 PDFs were freshly exported with `--pdf --asset-package`, using
the approved previous package's 37 asset digests without restoring four missing
private replay aliases. The prior v22 package and superseded 74cfa4 82-page
candidate remain in `tmp/` and were not published.

PDF reuse checks exact complete slide markup (locating the class attribute
regardless of its position), matching scene/build inventories, asset set, source digest, PDF digests and the
original PDF generator identity. Reader-only CSS and controls do not justify a
new PDF render. The reuse receipt keeps the predecessor manifest digest.

## Reader design and reference decisions

This is redesign-preserve for external technical reviewers, with design
variance 4, motion intensity 2 and visual density 4 on the outer UI only.
The actual slide is the main visual. No hero, stock image, theme reset, new
font, UI dependency or decorative card system is added.

The compact header separates report identity, equal-width language choices and
the one filled PDF action. The canvas toolbar groups scene selection, overview,
motion and previous/next builds. Its controls remain available while scrolling
the reader content. The desktop scene panel directly lists the existing 57
scenes; on compact widths the same list opens in a native dialog with Close,
Escape and browser-managed modal focus. There are no nested disclosure controls.

Detailed citations live in one native right-hand sheet, grouped as study records,
TypeSafe documentation, related research, and design/interpretation references.
Reference IDs and original destinations remain intact. Unlinked historical
records are explicitly outside this package, not fake download links. A single
footer button opens the 600px desktop / viewport-fit mobile sheet. The title and
Close row stay fixed while the list scrolls. `#readerSources` opens it directly;
Close, backdrop and Escape restore trigger focus. Tab wraps within it, background
scrolling is locked, and Arrow/Space/other slide keys cannot change the slide
behind it. ID/title columns include actual text whitespace for copying and
screen-reader output, not just a visual CSS gap.

| Primary reference | Adaptation in this reader |
| --- | --- |
| [Linear UI redesign](https://linear.app/now/how-we-redesigned-the-linear-ui) | Separate chrome from content, align control labels on both axes, and retain a low-chroma hierarchy. |
| [Apple toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars) | Group content navigation separately from document-level actions; avoid overcrowding. |
| [Apple segmented controls](https://developer.apple.com/design/human-interface-guidelines/segmented-controls) | Two equal-width language choices with explicit current state, not unrelated actions in a toggle. |
| [Apple buttons](https://developer.apple.com/design/human-interface-guidelines/buttons) | One prominent action, consistent control heights, press/focus states and generous targets. |
| [Apple sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars) | Discoverable desktop navigation and a compact-width alternative. The user explicitly rejects hierarchical disclosure. |
| [Apple sheets](https://developer.apple.com/design/human-interface-guidelines/sheets) | One sheet at a time with an explicit, consistently placed Close action. |
| [Native HTML dialog](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/dialog) | Use native modal/inert/Escape behavior for scene selection and sources; sources also wrap Tab and isolate the inherited slide keyboard listener. |

Spacing at 12/16/24px, title sizes of 18/16px, 13px controls and the 224px scene
panel are local choices. The 44 CSS-pixel web targets adapt Apple's native
44-point recommendation; the units are not interchangeable. These are design
inspirations, not official Apple CSS, Liquid Glass or Linear components.
The exact scoped exception is maintained in `site/DESIGN.md`.

## Existing Pages path, not a new hosting pipeline

`site/next.config.ts` already specifies static export, `basePath` and
`assetPrefix` `/geode`, trailing slashes and unoptimized local images. Next copies
the public package to `site/out/resaerch/jev-system1-offloading/`; the exported
directory itself must not contain another `geode/` prefix. PDF and asset links
remain relative to the report. GEODE return and discovery links include the
public `/geode/` prefix explicitly.

The inspected `.github/workflows/pages.yml` builds PRs targeting develop/main,
but its Deploy job excludes pull requests. Matching pushes to main, the daily
schedule and workflow dispatch can publish `site/out` through the existing
Pages actions. The live Pages configuration readback reported
`build_type: workflow`, HTTPS enforced, and the project-site URL. Its legacy
source tuple `main:/docs` is not a reason to copy this package into `docs/`.
The existing site's `built` status does not prove this new report was deployed.

The pending route change updates the landing discovery link, sitemap, Pages
link-check glob and exact pre-commit paths. It does not change the global
basePath, domain, build system or workflow deployment condition. The original
`/research/jev/` local candidate remains preserved outside the public tree.

## Assets and size budget

Keep the 37 allowlisted assets and two PDFs in regular Git. The local package
contains 41 files, 79,319,834 bytes including the manifest (approximately
76 MiB); its largest file is the KO PDF at
19,830,056 bytes. The package integrity test checks every asset/PDF digest and
every file against the strict local 100 MiB ceiling, including the narrowly
enumerated files exempted from the generic 500 KiB hook. Vendor license bytes
are preserved. No blanket directory exception or hook bypass is used.

GitHub blocks individual Git files larger than 100 MiB. Published Pages sites
must remain below 1 GB and have a 100 GB/month soft bandwidth limit. Git LFS is
not supported for Pages. These current limits were checked in
[GitHub's file-size documentation](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github),
[Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits),
and [LFS restrictions](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage).

The existing, older `site/out` snapshot has 1,639 files and 213,160,907 bytes,
and still contains the previous route and source `f2a55a...`. This is measured
historical headroom, not a build pass for the new route. Recount the completed
current export before deployment. Do not copy the full film into Pages; connect
the owner-approved external video URL only after it exists and is verified.
Current `video_url` is null, so the reader renders no video CTA.

The parent film owner reports v23 completion with full decode, 48,660-frame PTS
and 810 scene-reference samples checked. That is owner-reported video QA, not
this report task's independent film verification. The previously handed-off
803 MB v22 film is a historical edition, not the current v23 deliverable. Neither
full film belongs in Pages Git blobs. The user/owner's YouTube upload and public
URL readback remain a separate operation; no placeholder video link is shown.

The user selected the existing music edition, credits and cover art. That
selection is not evidence of verified rights documentation. The report embeds
no soundtrack, and every bundled replay MP4 is checked to have no audio stream.

## Verification and deployment sequence

1. Keep the current owner and unrelated dirty work intact. This work remains in
   `codex/jev-film-publication-20260928`, on existing commit `c83a46c...` plus local
   changes. Current main ancestry is missing; do not treat this branch as ready
   for integration merely because local UI checks pass.
2. Verify the real local reader in KO and EN, source/PDF identities, flat scene
   selection, language hash retention, active states, keyboard controls, modal
   Escape/focus restoration, reduced motion and responsive geometry. Download
   each PDF over HTTP and check 200, `application/pdf` and its receipt SHA.
3. Before an authorized PR, fetch current refs, inspect actual content drift,
   and incorporate missing main history into this owned feature with a merge
   commit. Incorporate develop if concurrent changes require it. Regenerate
   affected metadata with the existing producer; no rebase or standalone
   main-to-develop sync PR.
4. Run the current site lint/type/build, docs/export/metadata/link gates and
   normal pre-commit checks after video-resource contention is cleared. Check
   the final `site/out` file count, total bytes and exact report/PDF identities.
   The old build is not reusable evidence for the changed reader or route.
5. The parent/rollout owner now has the user's deployment approval. After its
   integration gates, create the feature-to-develop PR,
   attach it to the task and verify required CI against that exact head. Leave
   guarded merge and develop-to-main promotion serialized with the rollout
   owner. Pages PR Build is not a deployment receipt.
6. After authorized main promotion, inspect the actual Pages run/commit and
   fetch the live trailing-slash route, both locale queries, manifest and PDFs.
   Require HTML/PDF digest equality, 200 and PDF MIME, selected-language download
   targets, replay availability and the landing discovery link. A raw GitHub
   blob or successful upload alone is not the public-route check.
7. If live readback fails, retain the candidate and diagnosis. Repair or revert
   only the scoped publication commit through the same reviewed GitFlow path;
   never overwrite research evidence or force-reset another checkout.

Local preview `http://127.0.0.1:8786/resaerch/jev-system1-offloading/` intentionally
serves `site/public` without `/geode`. It establishes reader behavior and actual
download bytes, not deployed basePath correctness. Local QA receipts are kept
under the owned worktree's `tmp/`; they are not added to the public package.
The old 8786 server had stopped. A new report-owned server was started only after
the final local package replacement; fresh HTTP 200 and byte readback passed.
The candidate preview at `http://127.0.0.1:50030/` remains available as well.
Server availability is a point-in-time check, not a persistent hosting promise.

## Completed local checks for this reader

The final reader HTML SHA-256 is
`49ccbd64d055b3efe040cc38e9f42f0029f9520894ab25c7a7f1d9d33b6c8a50`.
Its current generator SHA-256 is
`027b1a6ba8988c745790d976f06c31ab491bd393fa5e87a1cb618a4488b57f22`.
The source digest remains `37d8e11c...`. The original PDF generator is
`2d3b336ba98802f1d7c876589fdd19357cb26adcdf9631fd9a3fffe19810956f`.
The final `publication.json` SHA is
`48906c7fe50d8e2dac67ee6dd5ca0cafe58e6dda59053085a5e974730e105486`.

- The exporter tests passed 10/10, including source/slide/PDF/asset integrity,
  private-path exclusions and the per-file 100 MiB ceiling. Targeted ESLint
  passed for the exporter and its test file.
- The sequential single-browser KO/EN check passed at widths 1440, 1024, 768,
  390, 375 and 320. It checked 57 scenes and 81 builds, language/hash preservation,
  selected-language PDF targets, active states, scene selection, overview,
  previous/next boundaries, keyboard focus and Escape, reduced motion,
  persistent navigation and horizontal overflow. No page or console errors
  were recorded. The receipt is `tmp/jev-reader-v23-source-sheet-qa/web-qa.json`.
  The source sheet additionally passed deep-link, Tab wrap, global slide-key
  isolation, fixed-header, background scroll lock and all dismissal/focus checks.
- All twelve final browser QA PNGs were directly inspected: both languages'
  desktop, mobile, mobile scene dialog, desktop source sheet, 375px source sheet
  and the sheet's historical-record end. No new clipping or overlap was found.
- Both complete PDFs were visually read through 162 actual PDF raster PNGs,
  not substituted HTML screenshots. Scene 4's compressed call contract and all
  five replay scenes have complete text/stills; six A/B study panels contain
  decoded first frames, without dead media controls. All page inventories,
  1440×810 point boxes and 54 Link annotations per language passed. The mapping
  and review are in `tmp/pdfs/v23-37d8e11/pdf-qa.json` and `visual-review.md`.
- Both HTTP PDF downloads returned 200 and `application/pdf` from the candidate
  and the final local public path. The 81-page KO PDF SHA-256 is
  `37d1fca8d821eea0ad0febc081f1a97fbf4a25cad165e706361711ccbafe7dc2`;
  the 81-page EN PDF SHA-256 is
  `da05703b5052dc029db7ccdab94643f2c20322aa1b639b88009b9fb08c17ce92`.
  Source-sheet regeneration reused these exact bytes; it did not rerender PDFs.
- All 20 original unique source destinations remain reachable through anchors;
  the consolidated list has 22 unique destinations with scoring and reproduction
  links. The three pinned study/score/reproduction URLs returned HTTP 200 during
  the earlier v22 wrapper check; this v23 wrapper check preserves their exact URLs,
  not a new network availability claim. Other destinations were retained, not
  all independently network-revalidated. Three unbundled historical records remain explicitly
  distinguished from public downloads.

The package manifest intentionally remains `prepared-not-published`; its broad
release checklist is not a substitute for this scoped UI receipt. Earlier QA
attempts are retained under `tmp/`. The source-sheet test's first focus check
read before the native asynchronous `close` event; a separate event-order check
confirmed the correct next-frame restoration. The final test waits for the
actual closed/focused state, without weakening the assertion. Earlier v22
mouse-focus/native-scene-dialog test assumptions are also preserved separately.

## Remaining gates

No new commit, push, PR, merge, workflow dispatch or deployment was performed
by this report task. The parent's integration/deployment follows user approval.
The latest complete static site build, required
remote CI, final build-size readback, live Pages readback, external video
identity and Lighthouse performance measurements remain separate gates.
No additional PDF reraster, video encode, paid model call or experiment is
required for this reader handoff. Local visual checks are not a whole-film
motion pass or independent reproduction of the research outcomes.
