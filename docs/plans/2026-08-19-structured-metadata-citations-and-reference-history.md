# Structured metadata, citation provenance, and historical audit references

**Status:** VERIFIED
**Date:** 2026-08-19
**Base:** `origin/develop@45aba3ca7ba18bf8d19839e42520b102f4b6669e`
**Scope:** stale slop-audit state, JSON-LD/schema.org, robots policy, citation provenance
**Explicit non-goal:** GEO, AI-crawler optimization, visitor analytics, backlink monitoring

## 1. Grounded decision

Three independent read-only audits evaluated the same four proposals against
the repository and primary sources.

| Proposal | Official-source vote | Repo-gap vote | Adversarial vote | Decision |
|---|---|---|---|---|
| V1: retire the absolute slop baseline as an operational gate | implement | implement | implement | **Implement (3/3)** |
| V2: add truthful JSON-LD/schema.org | implement | implement | implement | **Implement (3/3)** |
| V3: add a project-path `robots.txt` | defer | defer | reject the file | **Do not implement (0/3)** |
| V4: make citations resolvable and machine-readable | implement | implement | implement | **Implement (3/3)** |

The feedback is therefore mostly justified. The robots observation is real—the
deployed origin has no `/robots.txt`—but a file emitted by this project would
live at `/geode/robots.txt`. RFC 9309 requires the authority-root
`/robots.txt`, and an absent file already means allow-all. Pretending the
project-path file controls the host would be fake compliance.

Primary sources:

- [Next.js JSON-LD guide](https://nextjs.org/docs/app/guides/json-ld)
- [Google structured-data introduction](https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data)
- [Schema.org SoftwareSourceCode](https://schema.org/SoftwareSourceCode)
- [Schema.org TechArticle](https://schema.org/TechArticle)
- [Schema.org citation](https://schema.org/citation)
- [RFC 9309 §2.3](https://www.rfc-editor.org/rfc/rfc9309.html#section-2.3)
- [Google robots.txt creation guide](https://developers.google.com/crawling/docs/robots-txt/create-robots-txt)

## 2. GAP audit

| Surface | Current state | GAP | Disposition |
|---|---|---|---|
| `scripts/slop_audit_baseline.md` | 2026-05-18 counts presented as the operational baseline; `--check` now fails permanently | Two competing slop authorities and no machine-readable historical status | Move the unchanged measurement to a dated reference with provenance; keep `slop_audit.py` diagnostic-only; retain `check_slop_ratchet.py` as the sole promotion ratchet |
| Landing structured data | Metadata/OpenGraph only; deployed HTML has no `application/ld+json` | Search and tooling cannot read the repository identity as structured data | Add one truthful `SoftwareSourceCode` object using existing site/package SOTs |
| Robots policy | Host-root and project-path robots files both 404 | Owner is the absent `mangowhoiscloud.github.io` root site, not this project | Do not create an ineffective project file; correct the bundle README so page-level `noindex` is not described as archive access control |
| Citation provenance | Lineage sources and several external-reference rows are plain text | Visible claims are not resolvable; no schema.org citation list | Use one lineage citation list for visible links and `TechArticle.citation`; fill missing official links on the external-reference page; reuse the existing blocking link checker |

## 3. Affected scope

| Area | Planned files | Effect |
|---|---|---|
| Historical reference | `docs/reference/2026-05-18-slop-audit-baseline.md`, `scripts/slop_audit_baseline.md` | Preserve old bytes and provenance, remove active-looking location |
| Diagnostic scanner | `scripts/slop_audit.py`, `.geode/skills/slop-audit/SKILL.md`, focused tests and existing audit/plan wording | Remove baseline/check authority; keep all six discovery lenses |
| JSON-LD | one small shared serializer, landing page, lineage page | XSS-safe JSON-LD with no new dependency |
| Citations | one lineage data module plus the two reference pages | Visible primary links and schema.org citations share the same lineage list |
| Robots wording | Petri bundle README only | State that `noindex` is page metadata, not access control or a host-root robots policy |
| Generated docs | site generators only if their checks report drift | No hand-maintained duplicate |

## 4. Implementation constraints

1. Do not restamp the stale slop counts to make the old gate green.
2. Do not add a citation database, click tracker, analytics SDK, or cookie.
3. Do not add ratings, offers, search actions, or other facts absent from the
   rendered site.
4. Serialize JSON-LD with `<` escaped as `\u003c`, following the Next.js
   security guidance.
5. Do not create `/geode/robots.txt`. Host-root policy requires a separately
   owned root-site repository or custom domain and is deferred until that owner
   exists.

## 5. Acceptance

- the historical baseline declares `status: historical`, `authority:
  reference-only`, measurement/source commits, measured scope, and
  `superseded_by: scripts/check_slop_ratchet.py`;
- no production documentation calls that snapshot an operational baseline,
  and `slop_audit.py` has no baseline/check CLI;
- `slop_audit.py` completes as a diagnostic and the canonical slop ratchet
  passes unchanged;
- the static landing HTML contains one parseable `SoftwareSourceCode` object
  whose version, repository, language, runtime, license, and author agree with
  current SOTs;
- the lineage page renders every citation as a primary-source link and emits
  the same URLs through `TechArticle.citation`;
- no analytics dependency or script is added;
- source and built-site link checks, site build/export, targeted pytest, Ruff,
  mypy, architecture baseline, and the full non-live suite pass;
- an independent verifier reports no P0/P1 before GitFlow promotion.

## 6. GitFlow

After local and independent verification, commit this feature work, open a
feature-to-`develop` PR, wait for terminal green CI, and merge. Then fetch the
canonical branches, reconcile `main` into `develop` only if required by the
repository trust rules, open the `develop`-to-`main` release PR, wait for CI,
and merge without bypassing review or branch protections.

## 7. Verification result

- three independent audits agreed on V1, V2, and V4 (3/3 each) and rejected a
  project-path robots file (0/3);
- targeted pytest passed with 86 passed and 3 optional-extra skips;
- the CI-equivalent full non-live suite passed with 10,342 passed, 65 skipped,
  and 80.96% coverage;
- Ruff, format, mypy, deptry, import-linter, slop ratchet, architecture
  baseline, skill validation, markdown lint, source-link audit, 237-page site
  build, 13-citation metadata verification, and 74-page markdown export passed;
- the restricted-sandbox serial diagnostic is excluded from evidence because
  its failures were denied loopback, Unix socket, DNS, subprocess-home, and
  macOS sandbox capabilities, all of which passed in the CI-equivalent run.
