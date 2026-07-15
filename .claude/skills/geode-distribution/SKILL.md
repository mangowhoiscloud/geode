---
name: geode-distribution
description: Publish and verify a released GEODE version across GitHub Release and PyPI/uv, prepare or update the separate Homebrew/core geode-agent formula, and prevent deleted custom-tap paths from returning. Use for Homebrew/core admission, brew formula work, uv/uvx distribution, stable promotions, release repair runs, and public installation-channel audits.
---

# GEODE Distribution

Scope: promote an already-landed, version-stamped `origin/main` commit to all
stable end-user channels. The release workflow owns the tag, package upload,
and post-publish checks. Do not create a release tag by hand during the normal
path.

## Channel contract

| Channel | End-user command | Immutable source |
|---------|------------------|------------------|
| PyPI / uv | `uv tool install geode-agent` | wheel + sdist for the promoted version |
| uv one-shot | `uvx --from geode-agent geode` | the same PyPI version |
| GitHub | release `vX.Y.Z` | annotated tag on the promoted main SHA |
| Homebrew/core, after acceptance | `brew install geode-agent` | core formula using the immutable GitHub release sdist |

Treat Homebrew as a separate upstream-admission path, not part of
`publish_stable`. Keep custom-tap repositories deleted and never recreate one
as a fallback. Do not publish a qualified tap command. Do not advertise the
unqualified command until Homebrew/core lists the formula and the clean-machine
postconditions below pass.

Source-edge installs are deliberately separate from stable distribution:

```bash
uv tool install git+https://github.com/mangowhoiscloud/geode
uvx --from git+https://github.com/mangowhoiscloud/geode geode
```

The operator development install is also separate:

```bash
uv tool install -e ".[audit]" --force --python 3.12
```

## Installed-tool updates

Use GEODE's provenance-aware updater for an existing install:

```bash
geode update          # uv tool: latest compatible patch; source: pull + rebuild
geode update --latest # uv tool only: explicitly allow minor/major upgrades
geode update --dry-run
```

For a standard registry-backed uv tool, the default command replaces its stored
install request with `geode-agent~=CURRENT_VERSION` and asks uv to upgrade. The
compatible-release bound permits only newer patches in the current
major/minor series. `--latest` deliberately replaces that bound with
`geode-agent@latest`. For an editable install, the command resolves the source
root from PEP 610 metadata, verifies that it is the GEODE git checkout, and
keeps the existing pull/sync/reinstall path.

Reinstalling a uv tool can discard extras, `--with` dependencies, explicit
Python requests, constraints, and resolver settings. Detect these custom
receipts and stop with actionable manual guidance instead of silently replacing
their metadata. The error must name the receipt path and recorded source;
registry-backed guidance includes a concrete patch-bound starting command,
while source-backed recovery retains the original editable, directory, URL, or
VCS reference and every recorded option instead of redirecting the install to
PyPI. Run the
standard registry update from a fresh temporary directory with `--no-config
--no-sources`; together these prevent an unrelated caller's `pyproject.toml`,
`uv.toml`, or `tool.uv.sources` from redirecting the package. Preserve the
receipt's tool root and entrypoint directory through
`UV_TOOL_DIR` and `UV_TOOL_BIN_DIR`, including when they are non-default. Accept
only a receipt with a valid `geode` entrypoint, and use its absolute executable
for verification and daemon restart instead of assuming the directory is on
`PATH`. Accept a source update only when PEP 610 says `editable=true` and any uv
receipt is a plain editable request for that same checkout. Never infer a source
checkout from the caller's current Git directory when installation metadata is
absent.

When a daemon is already running, resolve, install, and verify the uv update
before stopping it. Stop must satisfy the socket-closed postcondition; only then
start the receipt-derived executable and wait for its socket to become ready.
If installation or verification fails, leave the existing daemon process alone.

Do not add a hidden startup-time network check or background self-update. The
automatic part is installation detection, constraint selection, daemon
restart, and verification inside the explicit `geode update` operation.

## Stable promotion

### 1. Preflight

```bash
git fetch origin
git status --short --branch
git show origin/main:pyproject.toml | rg '^version'
git show origin/main:CHANGELOG.md | rg '^## \[X.Y.Z\]'
```

Confirm:

- the requested version is stamped on the current `origin/main` commit (or,
  for a repair run, on the existing annotated release tag target that remains
  an ancestor of `origin/main`);
- CI for that commit is green;
- the protected `release` environment is ready;
- the PyPI Trusted Publisher is bound to this repository, workflow, and
  release environment.

### 2. Dispatch one promotion

```bash
gh workflow run release.yml \
  --ref main \
  -f ref=main \
  -f version=X.Y.Z \
  -f publish_stable=true \
  -f publish_huggingface_artifacts=false
```

The workflow serializes stable promotions and performs:

1. full release validation, package-content gates, clean-wheel smoke, notes,
   and checksums;
2. an existing-PyPI conflict preflight before any channel is mutated;
3. an annotated tag and GitHub Release with wheel, sdist, and SHA256SUMS;
4. PyPI Trusted Publishing followed by an exact-version public `uvx` smoke;
5. a read-only cross-channel verifier for the annotated tag, release assets,
   exact PyPI files, and SHA-256 parity.

PyPI's simple index and exact-version JSON endpoint can converge at different
times. Keep the bounded `uvx` retry as the installability gate, then let
`verify_public_distribution.py` retry the complete JSON/tag/assets/checksum
snapshot. Do not insert a one-shot JSON/digest check between those two gates;
it duplicates the final verifier and can fail after a successful upload solely
because one CDN surface still returns 404.

### 3. Watch to completion

```bash
gh run list --workflow release.yml --limit 5
gh run watch <run-id>
```

Do not report success while a downstream channel job is queued, awaiting
environment approval, or skipped.

## Public postconditions

Run these after the workflow is green:

```bash
gh release view vX.Y.Z
uvx --no-cache --from "geode-agent==X.Y.Z" geode version
python scripts/verify_public_distribution.py \
  --version X.Y.Z \
  --repository mangowhoiscloud/geode \
  --source-sha RELEASE_TAG_TARGET_SHA
```

The GitHub release, public PyPI JSON, and both CLI smokes must all resolve
`X.Y.Z`. Release artifacts must use the immutable URL shape:

```text
https://github.com/mangowhoiscloud/geode/releases/download/vX.Y.Z/geode_agent-X.Y.Z.tar.gz
```

Tag auto-tarballs under `archive/refs/tags` or a VCS-main install described as
a stable release are failures.

## Homebrew/core admission and updates

Keep this workflow separate from a stable release. A successful GitHub/PyPI
promotion may prepare a formula candidate, but it must not mutate an external
tap or claim Homebrew availability.

### 1. Check upstream eligibility

Read the current official policies before every first submission:

- <https://docs.brew.sh/Acceptable-Formulae>
- <https://docs.brew.sh/Adding-Software-to-Homebrew>
- <https://docs.brew.sh/Python-for-Formula-Authors>

Confirm that the release is stable rather than alpha/beta, the project has
external users, and the current Homebrew notability requirements are met. If
any gate fails, stop before opening the upstream PR. Keep the audited candidate
in the `mangowhoiscloud/homebrew-core` fork instead.

The dated 2026-07-15 decision record lives in
`packaging/homebrew/README.md`: GEODE was marked beta with 12 stars, 2 forks,
and 0 subscribers/watchers. The then-current normal thresholds were 75 stars,
30 forks, or 30 watchers; self-submission thresholds were 225, 90, or 90.
Treat those figures as a snapshot and refresh the official policy and GitHub
API before any future admission decision. Recording the state does not
authorize an upstream PR.

### 2. Refresh the core candidate

Use the prior core candidate as the resource baseline, then refresh resources
against the exact release. Use Homebrew's current default Python formula; do
not preserve an obsolete Python dependency merely to avoid resource churn.

```bash
python scripts/render_homebrew_formula.py \
  --version X.Y.Z \
  --sdist-url "https://github.com/mangowhoiscloud/geode/releases/download/vX.Y.Z/geode_agent-X.Y.Z.tar.gz" \
  --sdist-sha256 SDIST_SHA256 \
  --resources-from-formula /path/to/homebrew-core/Formula/g/geode-agent.rb \
  --output /path/to/homebrew-core/Formula/g/geode-agent.rb

brew update-python-resources --version X.Y.Z geode-agent
```

Run the candidate from a dedicated Homebrew/core checkout or development tap;
never add a user-facing GEODE tap. Require all of these before submission:

```bash
brew audit --strict --new --online geode-agent
brew style Formula/g/geode-agent.rb
brew install --build-from-source geode-agent
brew test geode-agent
geode version
brew uninstall geode-agent
```

The formula name and Ruby class must remain `geode-agent` and `GeodeAgent`.
Its stable URL must be the immutable GitHub release asset, every Python
dependency must be a pinned resource, and tests must exercise both `geode` and
`geode-mcp`.

### 3. Submit and activate only through core

Open the formula PR from the fork to `Homebrew/homebrew-core` only after the
eligibility and candidate gates pass. Let upstream review and CI own admission.
After merge, verify the official API and an unqualified clean install on
supported macOS and Linux:

```bash
curl -fsS https://formulae.brew.sh/api/formula/geode-agent.json
brew update
brew install geode-agent
geode version
brew test geode-agent
brew uninstall geode-agent
```

Only after those commands pass may the landing page, docs, or release notes
present `brew install geode-agent` as an active channel.

## Recovery

The workflow is retry-safe for the same version:

- an existing annotated tag must resolve to the same validated SHA;
- an existing GitHub release may be repaired from a matching partial asset set;
  every existing asset must byte-match before any missing asset is uploaded;
- an existing PyPI version may be repaired from a matching partial file set;
  every existing filename and SHA-256 must match before the publisher skips it
  and uploads only missing files, followed by the exact-version smoke;

If `main` advanced after a partial promotion created the annotated tag, keep
the workflow revision on current `main` and set only the release input to the
tag (for example `--ref main` and `-f ref=vX.Y.Z`). This uses the latest repair
tooling while the workflow verifies that the immutable tag target is unchanged
and still belongs to `main`.

If a channel fails, fix the cause and rerun the same workflow/version. Never
delete or overwrite a GitHub/PyPI release, move a published tag, loosen the exact
version checks, or substitute an unverified install channel merely to make the
run green.
