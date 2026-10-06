# Temporary GEODE patch of the Next.js ESLint plugin

This is the official `@next/eslint-plugin-next@16.3.8` npm distribution with
one runtime utility changed. It is a private local package, explicitly labelled
`16.3.8-geode.1`, not an upstream security release. The root package's file
dependency and `$@next/eslint-plugin-next` override select it for
`eslint-config-next`; `npm ci` resolves the committed lock without a postinstall
script or an external fork.

## Reason and scope

The upstream dependency path was `fast-glob → micromatch → braces@3.0.3`.
[GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)
has no official patched braces release as of 2026-10-06. The patch removes that
path from both the package manifest and the installed lock. Audit thresholds,
advisory exclusions and all 22 lint rules/configurations are unchanged.
The website does not set `settings.next.rootDir`; its existing default cwd
behavior is unchanged. This is build tooling, not code shipped in the browser.

`dist/utils/get-root-dirs.js` uses the official registry packages `glob@13.0.6`,
`brace-expansion@5.0.12` and `picomatch@4.0.4`. Brace expansion precedes per-input
positive/negative pattern separation. Filesystem discovery follows directory
symlinks and remains case-sensitive. Matching retains dot-directory and extglob
behavior, and a terminal globstar discovers descendants. `fs.statSync` preserves
directory-symlink recognition while excluding files and dangling links. The
original array handling and distinction between process cwd and context cwd stay
intact. Patterns nested beyond 100 brace levels fail with `SyntaxError` before
parser recursion. This intentional input bound is not a claim that every possible
glob is safe or that two glob libraries implement identical grammars.

All other upstream distribution files, including rule implementations and type
declarations, are byte-for-byte unchanged except one trailing comment space in
`node-attributes.js`, removed to satisfy the repository whitespace gate. The package manifest changes its local
identity/dependencies and drops upstream development scripts/dependencies, which
are not needed to consume the published distribution. `upstream.patch` contains
the complete runtime/manifest change. The additional whitespace-only change is
exactly `"/* example: \n"` → `"/* example:\n"` in `dist/utils/node-attributes.js`. `upstream.json` records the official tarball URL,
SHA512, source tag object, original file SHA256 values and patched file SHA256
values. The original Next.js MIT notice is in `LICENSE`. The replacement packages
retain their own registry license notices: glob/minimatch use BlueOak-1.0.0;
brace-expansion and picomatch use MIT.

## Verification and maintenance

`npm run lint` first runs `scripts/test-next-eslint-patch.mjs`. Its committed
fixture was captured from the verified, unmodified 16.3.8 package before removal:
30 root patterns and 12 actual `no-html-link-for-pages` diagnostics, with relative
and absolute paths, Windows separator normalization, wildcards, brace alternatives,
padded/stepped ranges, extglobs, dot directories, arrays, files, directory symlinks
and dangling symlinks. Additional assertions cover negative alternatives, literal/dynamic parent and dot
segments, repeated separators and cwd ownership. All rule names/configuration severities and unchanged source hashes are
checked. Deep nesting runs in isolated child processes with five-second timeouts.
The test also requires the reviewed local package to be selected and rejects any
`braces`, `fast-glob` or `micromatch` installation in the lock.

The fixture compares resolved path sets and actual lint messages, because
filesystem enumeration order and trailing separators are not used by the rule.
It is bounded compatibility evidence, not proof for every possible glob syntax.
The complete site lint, typecheck, tests, static export, browser checks and npm
audit still run. Do not regenerate the fixture from the patched implementation.

At every Next.js dependency update, inspect the official plugin's dependency
graph and [upstream advisory](https://github.com/micromatch/braces/issues/70).
When an official release removes or fixes the vulnerable path:

1. Test that official package against the same root/diagnostic fixture and current
   site. Review any intentional upstream rule changes instead of blessing drift.
2. Remove the local file dependency/override, this vendor directory, its ESLint
   generated-code ignore and the temporary patch test after equivalent official
   behavior is verified. Preserve useful consumer regression cases as appropriate.
3. Regenerate the lock with the official package, run `npm ci`, full site checks
   and `npm audit --audit-level=moderate`, then record the removal in CHANGELOG.

Do not retain this copy silently across framework upgrades, rename vulnerable
packages to evade an advisory, relax the audit gate or publish this package.

References: [Next.js source](https://github.com/vercel/next.js/tree/v16.3.8/packages/eslint-plugin-next),
[glob options](https://github.com/isaacs/node-glob#options),
[minimatch security scope](https://github.com/isaacs/minimatch#important-security-consideration).
