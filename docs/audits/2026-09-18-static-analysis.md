# GEODE layer-by-layer static-analysis audit

Date: 2026-09-18 (Asia/Seoul). Product baseline:
`4bb73b909f2c4abd1332784b1b1fd802832a48eb` (`develop`).

## Evidence and scope

The complete committed tree was transported with `git archive`; the local
Git tree hash matched the source tree byte-for-byte, including file modes.
Temporary transport/diagnostic workflows are removed from the integration
change. No protected branch, release, paid provider, operator credential, or
live GUI action is part of this audit.

Baseline diagnostics ran at `0fc0bc697c03180a4e73505bc6aff8a597678bac`, whose
product tree matches the baseline (only the temporary workflow differs):
[Actions run 35246166563](https://github.com/mangowhoiscloud/geode/actions/runs/35246166563).
Reports retain command arguments and exact exit codes, including failures.
The temporary workflow's earlier validation failure is not a product finding.

| Layer | Baseline coverage | Result before correction |
| --- | --- | --- |
| Runtime `core` | 414 Python files | Existing Ruff, format, mypy, Bandit, import contracts pass; one missing explicit return type |
| Measurement `evals` | 94 Python files | Existing checks pass; one missing explicit constructor return type |
| Evolution `evolve` | 73 Python files | Existing checks and new annotation probe pass |
| Tests and repository Python | 714 test files, 57 script files | Existing lint/format/type scope passes; extending Bandit to scripts finds one URL-opening call |
| Runtime skill samples | 8 Python files | Isolated syntax/Pyflakes scan passes; preserve their distinct runtime-skill lint policy |
| Site | 260 TypeScript files; ESLint reports 272 TS/JS inputs | TypeScript and npm audit pass; 22 unused-code and 22 native-image warnings |
| Automation | All 5 baseline workflows and 4 shell scripts | 3 actionlint/ShellCheck embedded-shell findings; 1 standalone style finding and 4 indirect-dispatch false positives |
| JavaScript tooling | All 37 tracked JS/MJS/CJS files | Node syntax check passes; site-specific semantic lint stays under ESLint |
| Native helper | One Swift source on macOS | `swiftc -typecheck` passes; no helper execution |
| Published/generated surfaces | Existing owner-map, inventory, hygiene, render, bundle and generator gates | Preserve provenance; do not restyle historical evidence or regenerate unrelated experiments |

The Python root scan covered 1,352 files, plus the eight separately governed
skill samples. An AST sweep also checked production parameter/return coverage,
parent-relative imports, forbidden top-level dependency direction, bare type
ignores, and generic catch-all module names. It found only the two missing
return annotations in those measured categories. Static analysis is not proof
of runtime correctness or an exhaustive security assessment.

## Tool selection

Retain locked Ruff 0.15.2, mypy 1.19.1, Bandit 1.9.4, deptry 0.25.1,
import-linter 2.11 and the existing architecture ratchets. Their responsibilities
are distinct: syntax/style, type relations, risky APIs, dependency declarations,
and architectural import boundaries. A second Python type checker or wholesale
rule migration would add policy drift without addressing this audit's gaps.

Add actionlint 1.7.12 and ShellCheck 0.11.0 for the previously ungated automation
layer. Initial shell diagnostics used the runner's ShellCheck 0.9.0; the
permanent gate pins 0.11.0 and verifies its release archive checksum. Retain
ESLint/Next TypeScript for the site and the native Swift compiler for the macOS
helper. No product dependency or lockfile upgrade is required.

## Corrections and ratchets

Production signatures now explicitly annotate the context-local mapping
iterator and credential error constructor. A derived Ruff configuration
inherits the baseline and enforces annotations without weakening other rules;
positive/negative regression fixtures include an inherited F401 failure.

The GEO public-host reader uses the already-declared HTTPX client with a
pre-transport HTTPS check on every request, including redirects. Tests retain
non-2xx bodies, repeated robots headers, final URL identity, response-size
limits and closure, and reject non-HTTPS inputs/downgrades without networking.
Bandit now scans `scripts/` in CI, pre-commit, and preflight.

Preflight now includes import contracts, exception-debt checks, production
annotations, automation lint and site lint/types. Full-mode missing audit or
site prerequisites fail non-zero. Failure injection tests ensure later
successful generation cannot erase earlier static-check failures. Explicit
fast mode remains partial and reports what it did not run.

Site cleanup removes unreachable declarations/imports without changing
archived portfolio render content. Twenty-two local images retain their
sources and alternate text while using Next Image under the existing
unoptimized export configuration. Diagram dimensions come from committed SVG
view boxes. Lint now permits zero warnings; standalone route-type generation
and TypeScript checking run before the static build.

Automation no longer parses directory listings through `head`, masks a failed
Petri comparison as an empty result, or interpolates PR metadata directly into
shell source. The Petri comparison has full ancestry. Progress reminders use
JSON encoding, distinguish failed observations from zero, and never treat
commit count as merge authority. The macOS install job also type-checks the
native helper without requesting GUI permissions.

## Preserved contracts and verification boundary

Dependency direction remains `evolve -> evals -> core`. Existing import-edge
exceptions, exception-debt and complexity ceilings, coverage threshold,
performance limits, safety settings, schema identities, and required-check
names are not relaxed. Regenerate architecture and public-doc mirrors through
their canonical generators, not hand edits.

The Dockerfile was reviewed as repository packaging source; this task does not
claim an image build, dependency-license audit, live model evaluation, or full
browser accessibility review. Existing archived experiment receipts remain
unchanged. Final integration status belongs to the exact PR-head Actions
checks and PR verification record, not a prefilled success claim in this report.
