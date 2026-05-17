# GEODE v1.0.0 Packaging and Distribution Plan

Date: 2026-05-17
Status: pre-release plan

## Goal

Ship GEODE v1.0.0 as the first stable async-only release, then make the
runtime installable and discoverable through packaging channels that match its
actual user surfaces:

- PyPI / `uv tool install` for the Python CLI.
- GitHub release assets for immutable source distributions and checksums.
- Homebrew tap/formula for macOS CLI users.
- Hugging Face Hub for agent traces, evaluation artifacts, and optional demo
  surfaces, not as a model-weight release.

## Reference Matrix

| Source | Relevant pattern | GEODE decision |
|---|---|---|
| Homebrew Python for Formula Authors | Python applications should be installed into a `libexec` virtualenv, with Python dependencies declared as formula resources and installed into that virtualenv. `brew update-python-resources` is the intended helper for resource stanzas. | Build `packaging/homebrew/geode.rb` around `Language::Python::Virtualenv`, a semver release sdist, and explicit resource stanzas. |
| Homebrew Formula Cookbook | A formula is a Ruby package definition created from an upstream tarball, installed with `brew install`, debugged with `brew install --debug --verbose`, and verified with formula tests/audit. | Treat `brew audit --new --strict geode` and `brew test geode` as release gates before publishing a tap. |
| `../hermes-agent/packaging/homebrew` | Stable Homebrew source should target the semver-named sdist release asset, not a repository auto-tarball. The wrapper exports managed-install environment variables and verifies that self-update routes users back to Homebrew. | Publish `geode-1.0.0.tar.gz` as a GitHub release asset and make the formula point there. Add `GEODE_MANAGED=homebrew` once update/install commands exist. |
| `huggingface/ml-intern` | CLI install is `uv sync` + `uv tool install -e .`; runtime relies on `HF_TOKEN`; sandbox tools can use HF Spaces; sessions are uploaded to a private HF dataset in Claude-Code-style JSONL for trace viewing. | Keep local CLI install first-class, then add optional `HF_TOKEN`-backed trace export to a user-owned dataset and consider a Space demo only after packaging is stable. |
| `../openclaw/extensions/huggingface` | Hugging Face is modeled as a provider with `HF_TOKEN` / `HUGGINGFACE_HUB_TOKEN`, provider-specific config, and OpenAI-compatible router defaults. | If GEODE adds a Hugging Face provider, use provider-scoped auth/config instead of mixing it with packaging. Packaging remains separate from model routing. |
| OpenClaw release validation | Release validation is split into install smoke, cross-OS package checks, package acceptance, live/E2E, and focused rerun handles. | Add GEODE release gates in phases: local build/install smoke first, then Homebrew formula test, then live/E2E and optional HF artifact upload. |

Reference links:

- Homebrew Python for Formula Authors: <https://docs.brew.sh/Python-for-Formula-Authors>
- Homebrew Formula Cookbook: <https://docs.brew.sh/Formula-Cookbook>
- PyPI Trusted Publishing: <https://docs.pypi.org/trusted-publishers/using-a-publisher/>
- PyPA GitHub Action for PyPI publish: <https://github.com/marketplace/actions/pypi-publish>
- Hugging Face Hub CLI: <https://huggingface.co/docs/huggingface_hub/guides/cli>
- Hugging Face `ml-intern`: <https://github.com/huggingface/ml-intern>

## Release Control Strategy

Main branch CI and release publishing are intentionally separate.

- `push` / `pull_request` to `main` or `develop` runs CI and install smoke only.
- GitHub Pages may update documentation from `main`, but package publishing does
  not happen from normal pushes.
- Release publishing starts only from `.github/workflows/release.yml` via
  `workflow_dispatch`.
- The release workflow takes an explicit `ref` and `version`, validates that
  `pyproject.toml` and `CHANGELOG.md` match, rebuilds package artifacts from
  that ref, and uploads artifacts for review.
- Actual publishing jobs are opt-in booleans and protected by the `release`
  environment, so a human approval can sit between validation and publication.

This gives the desired sequence:

1. Work locally in a release worktree.
2. Run local ratchets and package build.
3. Merge the release/version commit to `main`.
4. Trigger the release workflow manually against the known SHA or `main`.
5. Inspect artifacts and release notes.
6. Approve selected publish jobs: GitHub release, PyPI, Hugging Face artifacts.
7. Update Homebrew formula after the GitHub release asset checksum is final.

## Skill Packaging Gate

GEODE's runtime skill surface is part of the package contract. The release
workflow now checks that both wheel and sdist include:

- `core/skills/skills.py`
- report templates under `core/skills/reports/templates/`
- `core/skills/reports/templates/report.html`, explicitly force-included
  because the CLI imports it at startup
- prompt markdown under `core/llm/prompts/`
- tool schema SOT `core/tools/definitions.json`
- Petri audit judge dimensions and seed markdown files

Future optional skill marketplace publishing should be a separate manual step,
not bundled into a normal package push. The package gate should first prove the
built-in runtime skills are present and loadable; marketplace/tap publishing can
then operate on a signed release artifact.

## Channel Plan

### 1. PyPI / uv

Primary install target:

```bash
uv tool install geode
geode --version
```

Release gates:

- `uv lock`
- `uv build`
- install wheel into a clean venv
- run `geode --version`
- run `geode analyze Berserk --dry-run`
- run `twine check dist/*` before upload

### 2. GitHub Release Assets

Release assets:

- `geode-1.0.0.tar.gz`
- `geode-1.0.0-py3-none-any.whl`
- `SHA256SUMS`
- release notes sourced from `CHANGELOG.md` `## [1.0.0]`

The Homebrew formula should target the semver sdist asset, not GitHub's
auto-generated tag tarball, so checksums remain tied to the Python package
artifact.

### 3. Homebrew

Initial formula shape:

- `class Geode < Formula`
- `include Language::Python::Virtualenv`
- `url` points to `geode-1.0.0.tar.gz`
- `depends_on "python@3.y"` using the current Homebrew Python accepted by the
  dependency graph
- install via `virtualenv_install_with_resources` unless GEODE needs custom
  asset wiring
- `test do` asserts `geode --version` includes `1.0.0`

Open items:

- Decide whether heavy optional extras (`audit`, `desktop`, `mcp`) stay out of
  the Homebrew base formula.
- Add a managed-install environment flag only after GEODE has a self-update
  command that needs to defer to Homebrew.
- Verify whether `inspect-petri` git dependency in the optional `audit` extra
  should remain excluded from Homebrew resources.

### 4. Hugging Face Hub

GEODE should not publish to a model repo unless it ships model weights. Use
Hub surfaces by artifact type:

- Dataset repo: GEODE traces, Petri audit outputs, dry-run fixtures, or public
  evaluation examples.
- Space repo: optional demo surface or trace viewer integration.
- Model card conventions: only for model-weight releases; if used for a Space
  or dataset, keep README metadata accurate for that repo type.

Initial HF release gate:

```bash
hf upload <org-or-user>/geode-v1-artifacts ./dist /dist --repo-type=dataset
hf upload <org-or-user>/geode-v1-artifacts ./docs/plans/2026-05-17-v1-packaging-release.md /release/packaging-plan.md --repo-type=dataset
```

This should remain opt-in until the destination organization and visibility are
confirmed.

## v1.0.0 Release Gates

Blocking:

- `git diff --check`
- `uv run ruff check core plugins tests autoresearch`
- `uv run ruff format --check core plugins tests autoresearch`
- `uv run deptry .`
- `uv run mypy core plugins`
- prompt integrity ratchet
- `uv run pytest -q`
- `uv run geode analyze Berserk --dry-run`
- `uv build`
- clean-venv wheel install smoke
- wheel/sdist content gate for skills, prompts, tool schemas, and audit assets

Packaging follow-up:

- Homebrew formula resource generation and audit/test.
- GitHub release asset upload.
- Optional HF dataset/Space upload.
