---
name: geode-distribution
description: Publish a released GEODE version to end-user install channels — git tag, Homebrew tap (mangowhoiscloud/tap), and uv/uvx. Triggers on "homebrew", "brew", "formula", "tap", "uv tool", "uvx", "배포", "설치 채널", "release tag".
---

# GEODE Distribution — Homebrew Tap + uv

Scope: publishing an already-landed release to install channels. This runs
AFTER the `geode-gitflow` release flow (version stamped across 5 locations,
develop → main merged). It never changes repo code.

## Channel map

| Channel | Consumer | Source of truth |
|---------|----------|-----------------|
| `uv tool install -e ".[audit]"` | Operator dev machine (serve daemon, editable) | workspace checkout |
| Homebrew `mangowhoiscloud/tap/geode` | End users on macOS | `Formula/geode.rb` in the tap repo, pinned to a release tag tarball |
| `uv tool install git+…@vX` / `uvx --from git+…@vX` | Python-toolchain users | the same release tag |

The three MUST resolve the same version after a publication pass.

## Step 1 — Release tag (both channels key off it)

Tag the latest develop → main **merge commit** (precedent: v0.99.308 →
merge commit, not the kanban docs commit), annotated:

```bash
git fetch origin
TARGET=$(git log origin/main --merges -1 --format=%H)
# Ground-truth the version at that commit — titles can lie:
git show $TARGET:pyproject.toml | grep '^version'
git tag -a vX.Y.Z -m "GEODE vX.Y.Z" $TARGET
git push origin vX.Y.Z
```

Trap: `git ls-remote --tags` sorts lexically ("v0.99.308" sorts before
"v0.99.43") — grep for the exact tag instead of eyeballing the tail.

## Step 2 — Homebrew tap update

Tap clone: `brew --repository mangowhoiscloud/tap` → `Formula/geode.rb`.
Template lives in this repo at `packaging/homebrew/geode.rb.in`.

1. **Check the tap for uncommitted WIP first** (`git status`). A prior
   session may have installed from an uncommitted formula — fold it into
   your commit rather than clobbering it.
2. Bump the pin:
   ```bash
   curl -sL https://github.com/mangowhoiscloud/geode/archive/refs/tags/vX.Y.Z.tar.gz -o /tmp/geode.tar.gz
   shasum -a 256 /tmp/geode.tar.gz
   # edit Formula/geode.rb: url → new tag, sha256 → new hash
   ```
3. **Resource stanzas**: only regenerate when base dependencies changed —
   `diff <(git show vOLD:pyproject.toml | sed -n '/^dependencies = \[/,/^\]/p') <(git show vNEW:pyproject.toml | sed -n '/^dependencies = \[/,/^\]/p')`
   (run in the geode repo, not the tap). If it differs:
   `brew update-python-resources geode`.
4. Build + verify before pushing:
   ```bash
   brew reinstall geode        # source build; rust deps take minutes
   /opt/homebrew/bin/geode version   # must print vX.Y.Z
   brew test geode
   ```
5. Commit + push the tap repo (plain push to its default branch — the tap
   is not governed by geode's GitFlow).

## Step 3 — uv channel verification

Never test by overwriting the operator's editable tool install — the tool
name collides (`geode-agent`) and the serve daemon depends on it. Verify in
an ephemeral env:

```bash
uvx --from "git+https://github.com/mangowhoiscloud/geode@vX.Y.Z" geode version
```

End users install with either of:

```bash
uv tool install "geode-agent @ git+https://github.com/mangowhoiscloud/geode@vX.Y.Z"
brew install mangowhoiscloud/tap/geode
```

## Known traps (all incurred 2026-07-13)

| Trap | Rule |
|------|------|
| PATH shadowing | `/opt/homebrew/bin/geode` precedes `~/.local/bin/geode`. The operator's dev CLI and the brew consumer CLI coexist — after publishing, `which -a geode` and confirm BOTH print the released version. A stale Cellar version silently shadows the dev install. |
| Operator install breakage | The dev editable install needs `uv tool install -e ".[audit]" --force --python 3.12` — the `[audit]` chain (inspect-harbor → harbor → litellm) fails to build on Python 3.14. |
| Version at the tag | The `-S`/title of a release commit can disagree with the stamped version — always read `git show TAG:pyproject.toml`. |
| Formula test block | The formula's `test do` asserts `GEODE vX.Y.Z` in `geode version` output — a version/url mismatch fails at `brew test`, not at install. |
| Tap default branch | The tap's default branch is `master`, not `main` — `git reset --hard origin/main` fails silently confusingly. |
| Tap remote divergence | Another session may push the tap while you edit the local clone (brew's clone doubles as a working copy). On non-fast-forward, `git diff origin/master HEAD -- Formula/geode.rb` first: if only the url/sha bump differs, rebase and resolve with your file. |
