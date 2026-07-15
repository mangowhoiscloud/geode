---
name: geode-distribution
description: Publish a released GEODE version to GitHub Release and PyPI/uv as one verified stable promotion, while keeping unsupported Homebrew commands out of the public install surface. Triggers on "homebrew", "brew", "formula", "tap", "uv tool", "uvx", "배포", "설치 채널", "release tag".
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

Homebrew is not an active stable channel. Do not publish a custom-tap command
or advertise `brew install geode-agent` until the formula is actually present
in Homebrew/core and the unqualified command passes on a clean machine. The
existing custom tap is legacy-only and is outside the normal promotion path.

Source-edge installs are deliberately separate from stable distribution:

```bash
uv tool install git+https://github.com/mangowhoiscloud/geode
uvx --from git+https://github.com/mangowhoiscloud/geode geode
```

The operator development install is also separate:

```bash
uv tool install -e ".[audit]" --force --python 3.12
```

## Stable promotion

### 1. Preflight

```bash
git fetch origin
git status --short --branch
git show origin/main:pyproject.toml | grep '^version'
git show origin/main:CHANGELOG.md | grep '^## \[X.Y.Z\]'
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
```

The GitHub release, public PyPI JSON, and both CLI smokes must all resolve
`X.Y.Z`. Release artifacts must use the immutable URL shape:

```text
https://github.com/mangowhoiscloud/geode/releases/download/vX.Y.Z/geode_agent-X.Y.Z.tar.gz
```

Tag auto-tarballs under `archive/refs/tags` or a VCS-main install described as
a stable release are failures.

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
