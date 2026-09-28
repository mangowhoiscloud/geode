# Jev research report publication

The public artifact at `/geode/resaerch/jev-system1-offloading/` uses the
operator's literal path and reuses the approved film HTML's
slide navigation, build steps and bilingual text. It is not another metric
producer. The source film remains unchanged. Packaging and local rendering do
not establish publication or visual approval.

## Inputs and authority

- The corrected v23 film HTML is frozen at
  `37d8e11cabce01fe368d8c9f6d623a28a4ee7965d12bc8129e7efb529a73ff34`:
  57 scenes and 81 settled builds per language. This is the research source;
  the outer reader UI originated in v22 and is not a second content edition.
- Use an explicit asset list with relative `source`, relative `target`, and
  exact `sha256` fields. Include font licenses. Do not copy the source directory.
  Existing replay aliases outside the source directory require explicit
  `dereference: true` and the approved content digest; copy bytes, not symlinks.
- Preserve measured failures, partial/post-hoc labels, denominator caveats and
  synthetic-task limits. Removing production notes is not permission to alter
  research conclusions.
- The fixed public study evidence is commit
  `3bcf4044eb5c2411dd48122d672aef72a83fb30e` in `geode-eval-artifacts`, under
  `reports/e2e-validation/jev-v3-20260927/`.
- The user selected publication of the existing six-track music edition.
  Preserve the source's track credits and cover art; this choice is not a claim
  that rights documentation has been verified. The report itself embeds no
  soundtrack, and every allowlisted replay MP4 must have no audio stream.
  The owner's final music film is linked only after its exact public URL exists.

Example asset-list entry (use a real digest, not this placeholder):

```json
[
  {
    "source": "assets/fonts/ibm-plex/IBMPlexSans-Regular.woff2",
    "target": "assets/fonts/IBMPlexSans-Regular.woff2",
    "sha256": "<approved asset SHA-256>"
  }
]
```

## Prepare and export

The exporter uses existing `playwright` and `pdf-lib` packages, available in
the Codex bundled runtime through `NODE_PATH`; it installs no dependency.
It uses the existing Chrome channel. `ffprobe` verifies that replay media are
audio-free. Resolve the bundled paths from the current runtime instead of
committing a machine-specific path.

```bash
node site/scripts/test-jev-report-export.mjs
node site/scripts/export-jev-report.mjs \
  --source /path/to/approved-film.html \
  --source-sha <final-source-sha256> \
  --assets /path/to/approved-assets.json \
  --date 2026-09-28 \
  --out tmp/jev-report-candidate \
  --pdf --expected-pages <build-count-from-final-audit>
```

Omit `--pdf` only for packaging diagnostics; its PDF links do not represent
existing deliverables. Final output requires both PDFs. To change reader chrome
without rerendering an unchanged source, use `--reuse-pdfs /path/to/prior-package`
instead of `--pdf`. Reuse verifies the source SHA, identical slide markup and
approved assets, bilingual page inventory, PDF hashes and original PDF generator
identity. The new receipt preserves `pdf_generator_sha256` and the prior manifest
digest separately from the current HTML generator. This explicit reuse mode
also reads approved asset targets from that package and checks every digest;
it does not need the private source's former media aliases. The writer refuses an
existing output directory, preserves each prior attempt, and refuses output
under `site/public/` without `--release` and either rendered or verified reused PDFs.

For a changed source that requires newly rendered PDFs, use `--pdf` together with
`--asset-package /path/to/prior-approved-package`. Only the approved assets are
reused: each target must match both the allowlist and that package's receipt,
and its actual bytes and replay streams are checked again. The new receipt binds
the asset package manifest digest. This does not reuse the old PDFs, restore
missing private aliases, or permit combining `--asset-package` with `--reuse-pdfs`.

Each PDF page is one settled build, not one scene. The exporter uses
`window.__film.pages()` and `window.__film.go()`, finishes finite animation,
preserves hidden/retired elements, and prints the single active scene in screen
mode. Replay pages use their explicit poster or a decoded first-frame still,
without nonfunctional native video controls; the web preview retains playback.
It verifies both language inventories, the expected page count, and the
source hash before and after export. Do not substitute the preview's ordinary
print stylesheet: it does not enumerate all builds.

`publication.json` separates the source HTML, packaged HTML, generator, assets
and two PDF digests. A later video has its own identity; a URL is not a video
byte hash. The receipt remains `prepared-not-published` until a separate live
readback proves deployment. No model is called, rescored, or rerun.

The local publication hook checks the exact package inventory, approved asset
hashes and every file's 100 MiB limit. Only the enumerated oversized files bypass
the generic 500 KiB hook. Three vendor licenses and the approved Geodi SVG retain
their original whitespace/EOF bytes; their hashes remain mandatory.

## Review and deployment

For the exact route, reader-only preservation contract, current workflow audit
and remaining release gates, see the
[reader deployment strategy](jev-reader-deployment-strategy.md).

The local package now contains newly generated v23 PDFs, followed by a
wrapper-only source-sheet update using verified `--reuse-pdfs`. The complete
KO and EN PDFs were visually read as 162 actual PDF raster pages. Source links
remain in a single native dialog, not nested disclosures. The source sheet's
open/close, keyboard, 375px layout and HTTP download checks are separate from
PDF inspection. The manifest and deployment strategy bind their exact identities;
neither local preparation nor the user's deployment approval is a live receipt.

1. Reopen all final PDF pages and the actual web preview in both languages.
   Check settled-page completeness, replay stills, mobile overflow, keyboard
   navigation, language switching and the two download targets.
2. Verify every source/asset/PDF digest, PDF page count, local link and private
   path exclusion. Check the actual `site/out` size, not only source asset size.
3. After owner approval, add the complete package under
   `site/public/resaerch/jev-system1-offloading/`, a sitemap entry and the minimal discovery link.
   Add `site/out/resaerch/jev-system1-offloading/**/*.html` to the existing Pages link-check scope;
   the current scope does not cover new research paths automatically.
4. Run site lint, type/build and relevant link/metadata/export checks. Keep
   generated docs under their existing producers. Use the existing guarded
   feature → develop → main integration; do not modify another publication tree.
5. Verify the actual Pages deployment and fetch the live HTML/PDF bytes. A
   merged PR or local export does not prove the public route or download works.

GitHub's regular Git limit is 100 MiB per file; Pages has a 1 GB published-site
limit and a 100 GB/month soft bandwidth limit. Git LFS is not a Pages fallback.
Keep the full film on the separately approved video host, not in this package.
See [large-file limits](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github),
[Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits),
and [Git LFS restrictions](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage).
